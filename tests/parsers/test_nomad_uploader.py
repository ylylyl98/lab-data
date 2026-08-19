"""Tests for the dry-run-first NOMAD entry archive uploader."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from unittest import mock

import pytest
import requests

from lab_data.parsers.nomad_uploader import (
    NomadAuthenticationError,
    NomadUploadError,
    UploadFile,
    UploadResult,
    upload_entry_archive,
)


def _make_archive(tmp_path, name='entry.archive.json') -> str:
    archive = tmp_path / name
    archive.write_text('{"data": {}}', encoding='utf-8')
    return str(archive)


def _make_raw(tmp_path, name='raw.csv') -> str:
    raw = tmp_path / name
    raw.write_text('a,b\n', encoding='utf-8')
    return str(raw)


def _response(json_data, status=200):
    response = mock.MagicMock()
    response.status_code = status
    response.json.return_value = json_data
    response.raise_for_status.return_value = None
    return response


def test_dry_run_is_default_and_returns_plan_without_ids_or_writes(tmp_path):
    archive = _make_archive(tmp_path)
    raw = _make_raw(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())

    with (
        mock.patch('requests.post') as post,
        mock.patch('requests.put') as put,
        mock.patch('requests.get') as get,
    ):
        result = upload_entry_archive(archive, [raw])

    assert isinstance(result, UploadResult)
    assert result.dry_run is True
    assert result.upload_id is None
    assert result.entry_id is None
    assert result.processing_status is None
    assert result.published is False
    assert result.plan == {
        'archive_path': archive,
        'files': [
            {'source_path': raw, 'destination_path': 'raw.csv'},
        ],
        'upload_name': None,
        'publish': False,
    }
    post.assert_not_called()
    put.assert_not_called()
    get.assert_not_called()
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_dry_run_plan_preserves_caller_path_strings_and_order(tmp_path):
    archive = _make_archive(tmp_path)
    first = _make_raw(tmp_path, 'first.csv')
    second = _make_raw(tmp_path, 'second.csv')

    result = upload_entry_archive(archive, [first, second], upload_name='run-1')

    assert result.plan['archive_path'] == archive
    assert result.plan['files'] == [
        {'source_path': first, 'destination_path': 'first.csv'},
        {'source_path': second, 'destination_path': 'second.csv'},
    ]
    assert result.plan['upload_name'] == 'run-1'


def test_dry_run_plan_reflects_publish_flag(tmp_path):
    archive = _make_archive(tmp_path)

    result = upload_entry_archive(archive, publish=True)

    assert result.plan['publish'] is True
    assert result.published is False  # nothing is published in a dry run


def test_missing_archive_path_raises(tmp_path):
    missing = tmp_path / 'missing.archive.json'

    with pytest.raises(FileNotFoundError):
        upload_entry_archive(missing)


def test_arbitrary_json_suffix_is_rejected(tmp_path):
    plain = tmp_path / 'entry.json'
    plain.write_text('{}', encoding='utf-8')

    with pytest.raises(ValueError):
        upload_entry_archive(plain)


def test_missing_raw_path_raises(tmp_path):
    archive = _make_archive(tmp_path)
    missing_raw = tmp_path / 'missing.csv'

    with pytest.raises(FileNotFoundError):
        upload_entry_archive(archive, [missing_raw])


def test_dry_run_does_not_mutate_files(tmp_path):
    archive = _make_archive(tmp_path)
    raw = _make_raw(tmp_path)
    archive_bytes = (tmp_path / 'entry.archive.json').read_bytes()
    raw_bytes = (tmp_path / 'raw.csv').read_bytes()

    upload_entry_archive(archive, [raw])

    assert (tmp_path / 'entry.archive.json').read_bytes() == archive_bytes
    assert (tmp_path / 'raw.csv').read_bytes() == raw_bytes


def test_non_dry_run_without_auth_raises_before_any_request(tmp_path):
    archive = _make_archive(tmp_path)

    with (
        mock.patch('requests.post') as post,
        mock.patch('requests.put') as put,
        mock.patch('requests.get') as get,
    ):
        with pytest.raises(NomadAuthenticationError):
            upload_entry_archive(archive, dry_run=False)

    post.assert_not_called()
    put.assert_not_called()
    get.assert_not_called()


def _fake_requests():
    """Return request mocks that emulate a minimal successful NOMAD Oasis."""

    def post(url, **kwargs):
        if url.endswith('/v1/uploads'):
            return _response({'data': {'upload_id': 'U1'}})
        if url.endswith('/action/process'):
            return _response({'data': {}})
        if url.endswith('/action/publish'):
            return _response({'data': {}})
        raise AssertionError(f'unexpected POST url: {url}')

    get = mock.MagicMock()
    get.return_value = _response(
        {'data': [{'entry_id': 'E1', 'processing_status': 'SUCCESS'}]}
    )

    return mock.MagicMock(side_effect=post), mock.MagicMock(), get


def test_non_dry_run_performs_single_upload_and_raw_puts(tmp_path):
    archive = _make_archive(tmp_path)
    raw = _make_raw(tmp_path)
    post, put, get = _fake_requests()
    base = 'http://localhost/nomad-oasis/api'

    with (
        mock.patch('requests.post', post),
        mock.patch('requests.put', put),
        mock.patch('requests.get', get),
    ):
        result = upload_entry_archive(
            archive,
            [raw],
            api_base_url=base,
            auth=('user', 'pass'),
            dry_run=False,
        )

    assert result.dry_run is False
    assert result.upload_id == 'U1'
    assert result.entry_id == 'E1'
    assert result.processing_status == 'SUCCESS'
    assert result.published is False
    assert result.plan is None

    create_urls = [c.args[0] for c in post.call_args_list if 'action/' not in c.args[0]]
    assert create_urls == [f'{base}/v1/uploads']
    assert put.call_args_list[0].args[0] == f'{base}/v1/uploads/U1/raw/raw.csv'
    assert get.call_args_list[0].args[0] == f'{base}/v1/uploads/U1/entries'
    publish_urls = [
        c.args[0] for c in post.call_args_list if 'action/publish' in c.args[0]
    ]
    assert publish_urls == []


def test_multi_archive_upload_sends_all_mainfiles_and_accepts_json(tmp_path):
    first = _make_archive(tmp_path, 'first.archive.json')
    second = _make_archive(tmp_path, 'second.archive.json')
    third = _make_archive(tmp_path, 'third.archive.json')
    post, put, get = _fake_requests()
    get.return_value = _response(
        {
            'data': [
                {'entry_id': 'E1', 'processing_status': 'SUCCESS'},
                {'entry_id': 'E2', 'processing_status': 'SUCCESS'},
                {'entry_id': 'E3', 'processing_status': 'SUCCESS'},
            ]
        }
    )

    with (
        mock.patch('requests.post', post),
        mock.patch('requests.put', put),
        mock.patch('requests.get', get),
    ):
        result = upload_entry_archive(
            archive_files=[first, second, third],
            auth=('user', 'pass'),
            dry_run=False,
        )

    create_call = post.call_args_list[0]
    assert [part[1][0] for part in create_call.kwargs['files']] == [
        'first.archive.json',
        'second.archive.json',
        'third.archive.json',
    ]
    assert create_call.kwargs['headers'] == {'Accept': 'application/json'}
    assert result.entry_id == 'E1'


def test_bearer_token_authenticates_every_real_request_without_leaking_token(
    tmp_path,
):
    archive = _make_archive(tmp_path)
    raw = _make_raw(tmp_path)
    post, put, get = _fake_requests()
    token = 'fake-pat-for-tests'

    with (
        mock.patch('requests.post', post),
        mock.patch('requests.put', put),
        mock.patch('requests.get', get),
    ):
        result = upload_entry_archive(
            archive,
            [raw],
            bearer_token=token,
            dry_run=False,
        )

    expected_headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {token}',
    }
    for request in [*post.call_args_list, *put.call_args_list, *get.call_args_list]:
        assert request.kwargs['headers'] == expected_headers
        assert request.kwargs['auth'] is None
    assert token not in repr(result)


def test_bearer_token_is_absent_from_dry_run_plan_and_repr(tmp_path):
    archive = _make_archive(tmp_path)
    token = 'fake-pat-for-tests'

    with (
        mock.patch('requests.post') as post,
        mock.patch('requests.put') as put,
        mock.patch('requests.get') as get,
    ):
        result = upload_entry_archive(
            archive,
            bearer_token=token,
            dry_run=True,
        )

    assert token not in repr(result)
    assert token not in repr(result.plan)
    assert 'bearer_token' not in result.plan
    post.assert_not_called()
    put.assert_not_called()
    get.assert_not_called()


def test_non_dry_run_publishes_only_when_requested(tmp_path):
    archive = _make_archive(tmp_path)
    post, put, get = _fake_requests()

    with (
        mock.patch('requests.post', post),
        mock.patch('requests.put', put),
        mock.patch('requests.get', get),
    ):
        result = upload_entry_archive(
            archive, auth=('user', 'pass'), publish=True, dry_run=False
        )

    assert result.published is True
    publish_urls = [
        c.args[0] for c in post.call_args_list if 'action/publish' in c.args[0]
    ]
    assert publish_urls == [
        'http://localhost/nomad-oasis/api/v1/uploads/U1/action/publish'
    ]


def test_non_dry_run_http_error_is_wrapped(tmp_path):
    archive = _make_archive(tmp_path)
    post = mock.MagicMock()
    response = mock.Mock(status_code=403, reason='Forbidden')
    response.headers = {'Content-Type': 'application/json'}
    response.text = '{"detail":"forbidden"}'
    error = requests.HTTPError('403 forbidden')
    error.response = response
    response.raise_for_status.side_effect = error
    post.return_value = response

    with mock.patch('requests.post', post):
        with pytest.raises(NomadUploadError, match='status=403') as caught:
            upload_entry_archive(archive, auth=('user', 'pass'), dry_run=False)
    assert 'forbidden' in str(caught.value)
    assert 'Authorization' not in str(caught.value)
    assert post.call_count == 1


def test_unpublished_upload_limit_is_ambiguous_before_id_without_retry(tmp_path):
    archive = _make_archive(tmp_path)
    post = mock.MagicMock()
    response = mock.Mock(status_code=400, reason='Bad Request')
    response.headers = {'Content-Type': 'application/json'}
    response.text = '{"detail":"Limit of unpublished uploads exceeded for user."}'
    response.raise_for_status.side_effect = requests.HTTPError('HTTP 400')
    post.return_value = response

    with mock.patch('requests.post', post):
        with pytest.raises(NomadUploadError) as caught:
            upload_entry_archive(archive, auth=('user', 'pass'), dry_run=False)

    message = str(caught.value)
    assert 'status=400' in message
    assert 'Limit of unpublished uploads exceeded for user.' in message
    assert post.call_count == 1


@pytest.mark.parametrize(
    ('status', 'body'),
    [
        (400, '{"detail":"bad request"}'),
        (401, 'unauthorized'),
        (413, '{"detail":"too large"}'),
        (422, '{"detail":"invalid"}'),
        (500, 'server error'),
        (502, 'proxy error'),
        (504, 'gateway timeout'),
    ],
)
def test_http_error_diagnostics_are_bounded_and_secret_free(tmp_path, status, body):
    archive = _make_archive(tmp_path)
    post = mock.MagicMock()
    response = mock.Mock(status_code=status, reason='failure')
    response.headers = {'Content-Type': 'text/plain'}
    response.text = body
    error = requests.HTTPError(f'HTTP {status}')
    error.response = response
    response.raise_for_status.side_effect = error
    post.return_value = response
    token = 'do-not-leak-token'

    with mock.patch('requests.post', post):
        with pytest.raises(NomadUploadError) as caught:
            upload_entry_archive(
                archive,
                bearer_token=token,
                dry_run=False,
            )

    message = str(caught.value)
    assert f'status={status}' in message
    assert body.split('{')[0].strip() in message or body in message
    assert token not in message
    assert 'Authorization' not in message
    assert post.call_count == 1


def test_processing_failure_returns_partial_with_known_id(tmp_path):
    archive = _make_archive(tmp_path)
    post, put, get = _fake_requests()
    get.return_value = _response(
        {'data': [{'entry_id': 'E1', 'processing_status': 'FAILURE'}]}
    )

    with (
        mock.patch('requests.post', post),
        mock.patch('requests.put', put),
        mock.patch('requests.get', get),
    ):
        result = upload_entry_archive(archive, auth=('user', 'pass'), dry_run=False)

    assert result.upload_id == 'U1'
    assert result.entry_id == 'E1'
    assert result.processing_status == 'FAILURE'
    assert result.published is False


def test_result_and_plan_never_leak_credentials(tmp_path):
    archive = _make_archive(tmp_path)
    secret = 'super-secret-token'

    dry = upload_entry_archive(archive, auth=('user', secret))
    assert secret not in repr(dry)
    assert secret not in repr(dry.plan)
    assert 'auth' not in dry.plan


def test_explicit_upload_files_preserve_nested_destinations_and_spaces(tmp_path):
    archive = _make_archive(tmp_path)
    first = _make_raw(tmp_path, 'same.csv')
    second = _make_raw(tmp_path, 'other.csv')

    result = upload_entry_archive(
        archive,
        upload_files=[
            UploadFile(first, 'Initial Data/same.csv'),
            UploadFile(second, 'Processed Data after process/same.csv'),
        ],
    )

    assert result.plan['files'] == [
        {
            'source_path': first,
            'destination_path': 'Initial Data/same.csv',
        },
        {
            'source_path': second,
            'destination_path': 'Processed Data after process/same.csv',
        },
    ]


@pytest.mark.parametrize(
    'destination',
    [
        r'C:\NOMAD_Test\file.csv',
        r'\\server\share\file.csv',
        '/absolute/file.csv',
        r'..\outside.csv',
        'folder/../outside.csv',
    ],
)
def test_invalid_upload_destinations_are_rejected(tmp_path, destination):
    archive = _make_archive(tmp_path)
    raw = _make_raw(tmp_path)

    with pytest.raises(ValueError):
        upload_entry_archive(
            archive,
            upload_files=[UploadFile(raw, destination)],
        )


def test_windows_separators_are_normalized_but_source_is_unchanged(tmp_path):
    archive = _make_archive(tmp_path)
    raw = _make_raw(tmp_path)
    before = raw, (tmp_path / 'raw.csv').read_bytes()

    result = upload_entry_archive(
        archive,
        upload_files=[UploadFile(raw, r'Initial Data\raw.csv')],
    )

    assert result.plan['files'][0]['destination_path'] == 'Initial Data/raw.csv'
    assert before[1] == (tmp_path / 'raw.csv').read_bytes()


def test_upload_file_is_immutable(tmp_path):
    raw = _make_raw(tmp_path)
    upload_file = UploadFile(raw, 'Initial Data/raw.csv')

    with pytest.raises(FrozenInstanceError):
        upload_file.destination_path = 'other.csv'


def test_explicit_upload_files_require_upload_file_instances(tmp_path):
    archive = _make_archive(tmp_path)
    with pytest.raises(TypeError):
        upload_entry_archive(archive, upload_files=['raw.csv'])


def test_nested_destination_is_used_by_real_upload(tmp_path):
    archive = _make_archive(tmp_path)
    raw = _make_raw(tmp_path, 'same.csv')
    post, put, get = _fake_requests()

    with (
        mock.patch('requests.post', post),
        mock.patch('requests.put', put),
        mock.patch('requests.get', get),
    ):
        upload_entry_archive(
            archive,
            upload_files=[UploadFile(raw, 'Processed Data/same.csv')],
            auth=('user', 'pass'),
            dry_run=False,
        )

    assert put.call_args_list[0].args[0] == (
        'http://localhost/nomad-oasis/api/v1/uploads/U1/raw/Processed Data/same.csv'
    )


def test_dry_run_with_explicit_files_makes_no_network_requests(tmp_path):
    archive = _make_archive(tmp_path)
    raw = _make_raw(tmp_path)

    with (
        mock.patch('requests.post') as post,
        mock.patch('requests.put') as put,
        mock.patch('requests.get') as get,
    ):
        result = upload_entry_archive(
            archive,
            upload_files=[UploadFile(raw, 'Initial Data/raw.csv')],
        )

    post.assert_not_called()
    put.assert_not_called()
    get.assert_not_called()
    assert result.plan['files'][0]['destination_path'] == 'Initial Data/raw.csv'


def test_upload_name_is_sent_as_query_parameter_not_form_data(tmp_path):
    archive = _make_archive(tmp_path)
    post, put, get = _fake_requests()
    base = 'http://localhost/nomad-oasis/api'

    with (
        mock.patch('requests.post', post),
        mock.patch('requests.put', put),
        mock.patch('requests.get', get),
    ):
        upload_entry_archive(
            archive,
            api_base_url=base,
            upload_name='run-1',
            auth=('user', 'pass'),
            dry_run=False,
        )

    create_call = post.call_args_list[0]
    assert create_call.kwargs['params'] == {'upload_name': 'run-1'}
    assert 'data' not in create_call.kwargs


def test_upload_name_none_omits_query_parameter(tmp_path):
    archive = _make_archive(tmp_path)
    post, put, get = _fake_requests()

    with (
        mock.patch('requests.post', post),
        mock.patch('requests.put', put),
        mock.patch('requests.get', get),
    ):
        upload_entry_archive(archive, auth=('user', 'pass'), dry_run=False)

    create_call = post.call_args_list[0]
    assert create_call.kwargs['params'] is None


def test_real_upload_never_calls_explicit_process_action(tmp_path):
    archive = _make_archive(tmp_path)
    raw = _make_raw(tmp_path)
    post, put, get = _fake_requests()

    with (
        mock.patch('requests.post', post),
        mock.patch('requests.put', put),
        mock.patch('requests.get', get),
    ):
        upload_entry_archive(
            archive,
            [raw],
            auth=('user', 'pass'),
            dry_run=False,
        )

    process_urls = [
        call.args[0] for call in post.call_args_list if 'action/process' in call.args[0]
    ]
    assert process_urls == []


def test_real_upload_parses_successful_create_response(tmp_path):
    archive = _make_archive(tmp_path)
    post = mock.MagicMock()

    def post_side_effect(url, **kwargs):
        if url.endswith('/v1/uploads'):
            return _response(
                {
                    'upload_id': 'U9',
                    'data': {
                        'upload_id': 'U9',
                        'upload_name': 'run-9',
                        'process_status': 'SUCCESS',
                    },
                }
            )
        raise AssertionError(f'unexpected POST url: {url}')

    post.side_effect = post_side_effect
    get = mock.MagicMock()
    get.return_value = _response(
        {'data': [{'entry_id': 'E9', 'processing_status': 'SUCCESS'}]}
    )

    with (
        mock.patch('requests.post', post),
        mock.patch('requests.put', mock.MagicMock()),
        mock.patch('requests.get', get),
    ):
        result = upload_entry_archive(
            archive,
            api_base_url='http://localhost/nomad-oasis/api',
            upload_name='run-9',
            auth=('user', 'pass'),
            dry_run=False,
        )

    assert result.upload_id == 'U9'
    assert result.entry_id == 'E9'
    assert result.processing_status == 'SUCCESS'


def test_non_json_create_response_is_not_treated_as_success(tmp_path):
    archive = _make_archive(tmp_path)
    bad = mock.MagicMock()
    bad.status_code = 200
    bad.raise_for_status.return_value = None
    bad.json.side_effect = requests.exceptions.JSONDecodeError('empty body', '', 0)
    post = mock.MagicMock(return_value=bad)

    with mock.patch('requests.post', post):
        with pytest.raises(requests.exceptions.JSONDecodeError):
            upload_entry_archive(archive, auth=('user', 'pass'), dry_run=False)

    assert post.call_count == 1
