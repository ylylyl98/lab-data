"""Focused tests for read-only remote batch readiness."""

import pytest

from lab_data.ingestion.nomad_status import (
    NomadStatusAuthenticationError,
    NomadStatusMalformedResponse,
    NomadStatusNetworkError,
)
from lab_data.ingestion.remote_batch_readiness import (
    RemoteBatchReadiness,
    check_remote_batch_readiness,
)


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:  # noqa: PLR2004
            raise RuntimeError('http error')

    def json(self):
        return self._payload


def _getter(records, status_code=200):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response({'data': records}, status_code)

    get.calls = calls
    return get


def test_no_matching_upload(tmp_path):
    get = _getter([])

    result = check_remote_batch_readiness('http://example/api', 'my-batch', get=get)

    assert result == RemoteBatchReadiness(
        outcome='no_match',
        matching_upload_ids=(),
        reason='no existing upload matches the name',
    )
    assert result.may_create is True


def test_exactly_one_matching_upload(tmp_path):
    get = _getter(
        [
            {'upload_id': 'a', 'upload_name': 'other'},
            {'upload_id': 'b', 'upload_name': 'my-batch'},
        ]
    )

    result = check_remote_batch_readiness('http://example/api', 'my-batch', get=get)

    assert result.outcome == 'single_match'
    assert result.matching_upload_ids == ('b',)
    assert result.may_create is False


def test_matching_upload_on_later_page_is_found(tmp_path):
    responses = iter(
        [
            _Response(
                {
                    'data': [{'upload_id': 'a', 'upload_name': 'other'}],
                    'pagination': {
                        'total': 2,
                        'next_page_url': '/v1/uploads?page=2',
                    },
                }
            ),
            _Response(
                {
                    'data': [{'upload_id': 'b', 'upload_name': 'my-batch'}],
                    'pagination': {'total': 2},
                }
            ),
        ]
    )

    def get(url, **kwargs):
        return next(responses)

    result = check_remote_batch_readiness('http://example/api', 'my-batch', get=get)

    assert result.outcome == 'single_match'
    assert result.matching_upload_ids == ('b',)


def test_total_pagination_is_followed_when_next_url_is_omitted(tmp_path):
    responses = iter(
        [
            _Response(
                {
                    'data': [{'upload_id': 'a', 'upload_name': 'other'}],
                    'pagination': {'total': 2, 'data_count': 1},
                }
            ),
            _Response(
                {
                    'data': [{'upload_id': 'b', 'upload_name': 'my-batch'}],
                    'pagination': {'total': 2, 'data_count': 1},
                }
            ),
        ]
    )
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return next(responses)

    result = check_remote_batch_readiness('http://example/api', 'my-batch', get=get)

    assert result.matching_upload_ids == ('b',)
    assert calls[1][1]['params'] == {'page': 2}


def test_malformed_upload_pagination_is_rejected(tmp_path):
    with pytest.raises(NomadStatusMalformedResponse, match='data_count'):
        check_remote_batch_readiness(
            'http://example/api',
            'my-batch',
            get=lambda url, **kwargs: _Response(
                {
                    'data': [{'upload_id': 'a', 'upload_name': 'other'}],
                    'pagination': {'total': 2, 'data_count': 3},
                }
            ),
        )


def test_repeated_upload_pagination_url_is_rejected(tmp_path):
    response = _Response(
        {
            'data': [{'upload_id': 'a', 'upload_name': 'other'}],
            'pagination': {'next_page_url': '/next'},
        }
    )

    with pytest.raises(NomadStatusMalformedResponse, match='repeated'):
        check_remote_batch_readiness(
            'http://example/api', 'my-batch', get=lambda url, **kwargs: response
        )


def test_multiple_matching_uploads_ambiguous(tmp_path):
    get = _getter(
        [
            {'upload_id': 'a', 'upload_name': 'my-batch'},
            {'upload_id': 'b', 'upload_name': 'my-batch'},
        ]
    )

    result = check_remote_batch_readiness('http://example/api', 'my-batch', get=get)

    assert result.outcome == 'ambiguous'
    assert result.matching_upload_ids == ('a', 'b')
    assert result.may_create is False


def test_remote_authentication_error(tmp_path):
    def get(url, **kwargs):
        return _Response({'detail': 'auth'}, status_code=401)

    with pytest.raises(NomadStatusAuthenticationError):
        check_remote_batch_readiness('http://example/api', 'my-batch', get=get)


def test_remote_network_error(tmp_path):
    def get(url, **kwargs):
        raise TimeoutError('timeout')

    with pytest.raises(NomadStatusNetworkError):
        check_remote_batch_readiness('http://example/api', 'my-batch', get=get)


def test_malformed_response_error(tmp_path):
    def get(url, **kwargs):
        return _Response({'data': 'not-a-list'})

    with pytest.raises(NomadStatusMalformedResponse):
        check_remote_batch_readiness('http://example/api', 'my-batch', get=get)


def test_invalid_inputs(tmp_path):
    with pytest.raises(ValueError):
        check_remote_batch_readiness('', 'my-batch')
    with pytest.raises(ValueError):
        check_remote_batch_readiness('http://example/api', '')


def test_no_uploader_or_create_called(tmp_path):
    get = _getter([])

    check_remote_batch_readiness('http://example/api', 'my-batch', get=get)

    urls = [call[0] for call in get.calls]
    assert urls == ['http://example/api/v1/uploads']
    assert all('uploads' in url for url in urls)


def test_credentials_not_in_result(tmp_path):
    get = _getter([{'upload_id': 'a', 'upload_name': 'my-batch'}])

    result = check_remote_batch_readiness(
        'http://example/api',
        'my-batch',
        bearer_token='secret-token',
        get=get,
    )

    assert 'secret-token' not in repr(result)
    assert 'Bearer' not in repr(result)
    assert result.matching_upload_ids == ('a',)


def test_module_has_no_uploader_create_coupling():
    from pathlib import Path

    source = Path('src/lab_data/ingestion/remote_batch_readiness.py').read_text(
        encoding='utf-8'
    )
    lowered = source.lower()

    assert 'create_batch_upload' not in lowered
    assert 'upload_entry_archive' not in lowered
    assert 'post' not in lowered
