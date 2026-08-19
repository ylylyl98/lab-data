"""Focused tests for the GET-only NOMAD status adapter."""

from dataclasses import replace

import pytest
import requests

from lab_data.ingestion.batch_manifest import ManifestStatus, create_batch_manifest
from lab_data.ingestion.batch_planner import plan_batches
from lab_data.ingestion.batch_reconcile import reconcile_batch
from lab_data.ingestion.nomad_status import (
    NomadStatusAuthenticationError,
    NomadStatusMalformedResponse,
    NomadStatusNetworkError,
    RemoteBatchState,
    fetch_nomad_upload_state,
)


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= HTTP_BAD_REQUEST:
            raise requests.HTTPError(f'HTTP {self.status_code}')


HTTP_BAD_REQUEST = 400
EXPECTED_GET_CALLS = 2
PAGINATED_GET_CALLS = 3
REQUEST_TIMEOUT = 30


def _upload(**changes):
    data = {
        'upload_id': 'upload-1',
        'process_status': 'SUCCESS',
        'process_running': False,
        'published': False,
        'errors': [],
        'warnings': [],
    }
    data.update(changes)
    return {'data': data}


def _entries(ids=('entry-1', 'entry-2'), pagination=None):
    payload = {'data': [{'entry_id': entry_id} for entry_id in ids]}
    if pagination is not None:
        payload['pagination'] = pagination
    return payload


def _getter(responses):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    get.calls = calls
    return get


def test_success_with_ordered_entry_ids():
    get = _getter([Response(_upload()), Response(_entries())])

    state = fetch_nomad_upload_state(
        'upload-1',
        api_base_url='http://example/api',
        proposal_ids=('proposal-1', 'proposal-2'),
        get=get,
    )

    assert state == RemoteBatchState(
        upload_id='upload-1',
        process_status='SUCCESS',
        entry_ids=(('proposal-1', 'entry-1'), ('proposal-2', 'entry-2')),
    )


def test_running_state_and_publication_propagate():
    get = _getter([
        Response(_upload(process_status='RUNNING', process_running=True, published=True)),
        Response(_entries(ids=())),
    ])

    state = fetch_nomad_upload_state('upload-1', api_base_url='http://example/api', get=get)

    assert state.process_running is True
    assert state.published is True
    assert state.entry_ids == ()


def test_failure_errors_and_warnings_propagate():
    get = _getter([
        Response(_upload(process_status='FAILURE', errors=['bad'], warnings=['warn'])),
        Response(_entries(ids=())),
    ])

    state = fetch_nomad_upload_state('upload-1', api_base_url='http://example/api', get=get)

    assert state.process_status == 'FAILURE'
    assert state.errors == ('bad',)
    assert state.warnings == ('warn',)


def test_clean_upload_404_becomes_not_found():
    state = fetch_nomad_upload_state(
        'missing', api_base_url='http://example/api', get=_getter([Response({}, 404)])
    )

    assert state == RemoteBatchState(upload_id='missing', not_found=True)


def test_clean_entries_404_becomes_not_found():
    state = fetch_nomad_upload_state(
        'upload-1',
        api_base_url='http://example/api',
        get=_getter([Response(_upload()), Response({}, 404)]),
    )

    assert state.upload_id == 'upload-1'
    assert state.not_found is True


@pytest.mark.parametrize('status_code', [401, 403])
def test_auth_failures_are_distinct_from_not_found(status_code):
    with pytest.raises(NomadStatusAuthenticationError):
        fetch_nomad_upload_state(
            'upload-1',
            api_base_url='http://example/api',
            get=_getter([Response({}, status_code)]),
        )


def test_malformed_upload_response_fails():
    with pytest.raises(NomadStatusMalformedResponse):
        fetch_nomad_upload_state(
            'upload-1', api_base_url='http://example/api', get=_getter([Response({'data': []})])
        )


def test_malformed_entries_response_fails():
    with pytest.raises(NomadStatusMalformedResponse):
        fetch_nomad_upload_state(
            'upload-1',
            api_base_url='http://example/api',
            get=_getter([Response(_upload()), Response({'data': [{'bad': 'entry'}]})]),
        )


def test_pagination_collects_all_entries_in_api_order():
    get = _getter([
        Response(_upload()),
        Response(_entries(('entry-1',), {'total': 2, 'page': 1, 'page_size': 1})),
        Response(_entries(('entry-2',), {'total': 2, 'page': 2, 'page_size': 1})),
    ])

    state = fetch_nomad_upload_state(
        'upload-1',
        api_base_url='http://example/api',
        proposal_ids=('proposal-1', 'proposal-2'),
        get=get,
    )

    assert state.entry_ids == (('proposal-1', 'entry-1'), ('proposal-2', 'entry-2'))
    assert len(get.calls) == PAGINATED_GET_CALLS
    assert get.calls[2][1]['params'] == {'page': 2}


def test_next_page_url_pagination_is_followed():
    get = _getter([
        Response(_upload()),
        Response(_entries(('entry-1',), {'total': 2, 'next_page_url': '/next'})),
        Response(_entries(('entry-2',), {'total': 2})),
    ])

    state = fetch_nomad_upload_state(
        'upload-1',
        api_base_url='http://example/api',
        proposal_ids=('proposal-1', 'proposal-2'),
        get=get,
    )

    assert state.entry_ids == (('proposal-1', 'entry-1'), ('proposal-2', 'entry-2'))
    assert get.calls[2][0] == 'http://example/next'


def test_upload_id_in_response_must_match_request():
    with pytest.raises(NomadStatusMalformedResponse, match='unexpected upload_id'):
        fetch_nomad_upload_state(
            'upload-1',
            api_base_url='http://example/api',
            get=_getter([Response(_upload(upload_id='other'))]),
        )


def test_zero_entry_upload_is_supported():
    get = _getter([Response(_upload()), Response(_entries(ids=(), pagination={'total': 0}))])

    state = fetch_nomad_upload_state('upload-1', api_base_url='http://example/api', get=get)

    assert state.entry_ids == ()


def test_bearer_auth_is_sent_and_not_returned():
    token = 'fake-token'
    get = _getter([Response(_upload()), Response(_entries(ids=()))])

    state = fetch_nomad_upload_state(
        'upload-1', api_base_url='http://example/api', bearer_token=token, get=get
    )

    assert all(call[1]['headers'] == {'Authorization': f'Bearer {token}'} for call in get.calls)
    assert token not in repr(state)


def test_legacy_auth_is_passed_when_no_bearer_token():
    auth = ('user', 'password')
    get = _getter([Response(_upload()), Response(_entries(ids=()))])

    fetch_nomad_upload_state(
        'upload-1', api_base_url='http://example/api', auth=auth, get=get
    )

    assert all(call[1]['auth'] == auth for call in get.calls)


def test_proposal_count_mismatch_is_rejected():
    with pytest.raises(NomadStatusMalformedResponse):
        fetch_nomad_upload_state(
            'upload-1',
            api_base_url='http://example/api',
            proposal_ids=('only-one',),
            get=_getter([Response(_upload()), Response(_entries())]),
        )


def test_entries_without_proposal_ids_are_not_fabricated():
    state = fetch_nomad_upload_state(
        'upload-1',
        api_base_url='http://example/api',
        get=_getter([Response(_upload()), Response(_entries())]),
    )

    assert state.entry_ids == ()


def test_only_get_is_used_and_no_retry_occurs():
    get = _getter([Response(_upload()), Response(_entries(ids=()))])

    fetch_nomad_upload_state('upload-1', api_base_url='http://example/api', get=get)

    assert len(get.calls) == EXPECTED_GET_CALLS
    assert all(call[1]['timeout'] == REQUEST_TIMEOUT for call in get.calls)


def test_network_failure_is_wrapped_without_token_leak():
    token = 'secret-token'
    with pytest.raises(NomadStatusNetworkError) as error:
        fetch_nomad_upload_state(
            'upload-1',
            api_base_url='http://example/api',
            bearer_token=token,
            get=_getter([requests.ConnectionError('offline')]),
        )
    assert token not in str(error.value)


def test_fetch_result_reconciles_existing_manifest():
    planned = plan_batches(('proposal-1', 'proposal-2'), dataset_label='synthetic')[0]
    manifest = replace(
        create_batch_manifest(planned, created_utc='2026-01-01T00:00:00Z', updated_utc='2026-01-01T00:01:00Z'),
        upload_id='upload-1',
    )
    state = fetch_nomad_upload_state(
        'upload-1',
        api_base_url='http://example/api',
        proposal_ids=manifest.proposal_ids,
        get=_getter([Response(_upload()), Response(_entries())]),
    )

    reconciled, result = reconcile_batch(manifest, state)

    assert result.state == 'success'
    assert reconciled.status is ManifestStatus.SUCCESS
