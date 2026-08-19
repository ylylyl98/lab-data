"""Focused reproducer tests for upload-ID ambiguity at the public boundary."""

from dataclasses import replace

import pytest
import requests as requests_module

import lab_data.parsers.nomad_uploader as uploader_module
from lab_data.ingestion.batch_manifest import (
    ManifestFile,
    ManifestStatus,
    create_batch_manifest,
)
from lab_data.ingestion.batch_planner import plan_batches


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:  # noqa: PLR2004
            raise RuntimeError(f'http {self.status_code}')

    def json(self):
        return self._payload


class _Transport:
    def __init__(self, create_payload, entries_sequence, *, get_errors=()):
        self.create_payload = create_payload
        self.entries_sequence = entries_sequence
        self.get_errors = dict(get_errors)
        self.post_calls = 0
        self.get_calls = 0

    def post(self, url, **kwargs):
        self.post_calls += 1
        if isinstance(self.create_payload, Exception):
            raise self.create_payload
        return _Response(self.create_payload)

    def get(self, url, **kwargs):
        self.get_calls += 1
        if self.get_calls in self.get_errors:
            raise self.get_errors[self.get_calls]
        index = min(self.get_calls - 1, len(self.entries_sequence) - 1)
        return _Response(self.entries_sequence[index])


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    monkeypatch.setattr(
        requests_module, 'post', lambda *a, **k: pytest.fail('real POST')
    )
    monkeypatch.setattr(requests_module, 'get', lambda *a, **k: pytest.fail('real GET'))


def _install_transport(monkeypatch, transport):
    monkeypatch.setattr(requests_module, 'post', transport.post)
    monkeypatch.setattr(requests_module, 'get', transport.get)
    monkeypatch.setattr(uploader_module, '_MAX_POLL_ATTEMPTS', 20)
    monkeypatch.setattr(uploader_module, '_POLL_INTERVAL_SECONDS', 0)
    return transport


def _entries(count, status='SUCCESS'):
    return {
        'data': [
            {'entry_id': f'e{i}', 'processing_status': status} for i in range(count)
        ]
    }


def _write_archives(tmp_path, count=1):
    paths = []
    for i in range(count):
        path = tmp_path / f'a{i}.archive.json'
        path.write_text('{}', encoding='utf-8')
        paths.append(str(path))
    return paths


def test_known_id_processing_running_preserved(monkeypatch, tmp_path):
    paths = _write_archives(tmp_path)
    transport = _install_transport(
        monkeypatch,
        _Transport(
            {'data': {'upload_id': 'upload-1'}},
            [_entries(1, status='RUNNING')],
        ),
    )

    result = uploader_module.upload_entry_archive(
        archive_files=paths,
        api_base_url='http://example/api',
        upload_name='batch',
        bearer_token='token',
        dry_run=False,
    )

    assert transport.post_calls == 1
    assert result.upload_id == 'upload-1'
    assert result.entry_id == 'e0'
    assert result.processing_status == 'RUNNING'


def test_known_id_poll_timeout_preserved(monkeypatch, tmp_path):
    paths = _write_archives(tmp_path)
    transport = _install_transport(
        monkeypatch,
        _Transport({'data': {'upload_id': 'upload-1'}}, [{'data': []}]),
    )
    monkeypatch.setattr(uploader_module, '_MAX_POLL_ATTEMPTS', 1)

    result = uploader_module.upload_entry_archive(
        archive_files=paths,
        api_base_url='http://example/api',
        upload_name='batch',
        bearer_token='token',
        dry_run=False,
    )

    assert transport.post_calls == 1
    assert result.upload_id == 'upload-1'
    assert result.entry_id is None


def test_known_id_temporary_get_error_preserved(monkeypatch, tmp_path):
    paths = _write_archives(tmp_path)
    transport = _install_transport(
        monkeypatch,
        _Transport(
            {'data': {'upload_id': 'upload-1'}},
            [_entries(1)],
            get_errors={1: TimeoutError('temporary')},
        ),
    )

    result = uploader_module.upload_entry_archive(
        archive_files=paths,
        api_base_url='http://example/api',
        upload_name='batch',
        bearer_token='token',
        dry_run=False,
    )

    assert transport.post_calls == 1
    assert result.upload_id == 'upload-1'
    assert result.entry_id is None


def test_known_id_raw_put_error_preserved_without_retry(monkeypatch, tmp_path):
    paths = _write_archives(tmp_path)
    raw = tmp_path / 'raw.csv'
    raw.write_text('a,b\n', encoding='utf-8')
    transport = _install_transport(
        monkeypatch,
        _Transport({'data': {'upload_id': 'upload-1'}}, [_entries(1)]),
    )

    def put(*args, **kwargs):
        raise TimeoutError('raw put')

    monkeypatch.setattr(requests_module, 'put', put)

    result = uploader_module.upload_entry_archive(
        archive_files=paths,
        upload_files=[uploader_module.UploadFile(raw, 'Initial Data/raw.csv')],
        api_base_url='http://example/api',
        upload_name='batch',
        bearer_token='token',
        dry_run=False,
    )

    assert transport.post_calls == 1
    assert transport.get_calls == 0
    assert result.upload_id == 'upload-1'
    assert result.entry_id is None


def test_known_id_processing_failure_preserved(monkeypatch, tmp_path):
    paths = _write_archives(tmp_path)
    transport = _install_transport(
        monkeypatch,
        _Transport(
            {'data': {'upload_id': 'upload-1'}},
            [_entries(1, status='FAILURE')],
        ),
    )

    result = uploader_module.upload_entry_archive(
        archive_files=paths,
        api_base_url='http://example/api',
        upload_name='batch',
        bearer_token='token',
        dry_run=False,
    )

    assert transport.post_calls == 1
    assert result.upload_id == 'upload-1'
    assert result.processing_status == 'FAILURE'


def test_known_id_increasing_entry_counts_success(monkeypatch, tmp_path):
    paths = _write_archives(tmp_path, count=50)
    _install_transport(
        monkeypatch,
        _Transport(
            {'data': {'upload_id': 'upload-1'}},
            [{'data': []}, _entries(17), _entries(50)],
        ),
    )

    result = uploader_module.upload_entry_archive(
        archive_files=paths,
        api_base_url='http://example/api',
        upload_name='batch',
        bearer_token='token',
        dry_run=False,
    )

    assert result.upload_id == 'upload-1'
    assert result.entry_id == 'e0'
    assert result.processing_status == 'SUCCESS'


def test_known_id_partial_entry_count_times_out_without_discarding_id(
    monkeypatch, tmp_path
):
    paths = _write_archives(tmp_path, count=50)
    transport = _install_transport(
        monkeypatch,
        _Transport({'data': {'upload_id': 'upload-1'}}, [_entries(17)]),
    )
    monkeypatch.setattr(uploader_module, '_MAX_POLL_ATTEMPTS', 2)

    result = uploader_module.upload_entry_archive(
        archive_files=paths,
        api_base_url='http://example/api',
        upload_name='batch',
        bearer_token='token',
        dry_run=False,
    )

    assert transport.post_calls == 1
    assert transport.get_calls == 2  # noqa: PLR2004
    assert result.upload_id == 'upload-1'
    assert result.entry_id is None
    assert result.processing_status is None


def test_post_ambiguous_before_id(monkeypatch, tmp_path):
    paths = _write_archives(tmp_path)
    transport = _install_transport(
        monkeypatch,
        _Transport({'data': {}}, [_entries(1)]),
    )

    with pytest.raises(uploader_module.NomadUploadError):
        uploader_module.upload_entry_archive(
            archive_files=paths,
            api_base_url='http://example/api',
            upload_name='batch',
            bearer_token='token',
            dry_run=False,
        )

    assert transport.post_calls == 1
    assert transport.get_calls == 0


def test_post_connection_drop_before_id(monkeypatch, tmp_path):
    paths = _write_archives(tmp_path)
    transport = _install_transport(
        monkeypatch,
        _Transport(TimeoutError('drop'), [_entries(1)]),
    )

    with pytest.raises(TimeoutError):
        uploader_module.upload_entry_archive(
            archive_files=paths,
            api_base_url='http://example/api',
            upload_name='batch',
            bearer_token='token',
            dry_run=False,
        )

    assert transport.post_calls == 1
    assert transport.get_calls == 0


def test_normal_50_entry_success_single_post(monkeypatch, tmp_path):
    paths = _write_archives(tmp_path, count=50)
    transport = _install_transport(
        monkeypatch,
        _Transport({'data': {'upload_id': 'upload-1'}}, [_entries(50)]),
    )

    result = uploader_module.upload_entry_archive(
        archive_files=paths,
        api_base_url='http://example/api',
        upload_name='batch',
        bearer_token='token',
        dry_run=False,
    )

    assert result.upload_id == 'upload-1'
    assert result.entry_id == 'e0'
    assert result.processing_status == 'SUCCESS'
    assert transport.post_calls == 1


def test_batch_boundary_confirmed_id_is_processing_and_retained(monkeypatch):
    manifest = create_batch_manifest(
        plan_batches(['proposal-1'], dataset_label='YZ247')[0],
        archive_files=(ManifestFile('a.archive.json', 'a.archive.json', 'archive'),),
        companion_files=(),
        upload_name='batch',
        created_utc='2026-01-01T00:00:00Z',
        updated_utc='2026-01-01T00:00:00Z',
    )
    manifest = replace(manifest, status=ManifestStatus.PREFLIGHT_PASSED)

    def partial_uploader(**kwargs):
        return uploader_module.UploadResult(
            dry_run=False,
            upload_id='upload-1',
            entry_id=None,
            processing_status=None,
            published=False,
        )

    from lab_data.ingestion.batch_upload import create_batch_upload

    result = create_batch_upload(
        manifest,
        api_base_url='http://example/api',
        bearer_token='token',
        uploader=partial_uploader,
        dry_run=False,
    )

    assert result.state == 'processing'
    assert result.created is True
    assert result.manifest.upload_id == 'upload-1'
    assert result.manifest.status is ManifestStatus.PROCESSING
    assert result.upload_result is not None
    assert result.upload_result.upload_id == 'upload-1'


def test_batch_processing_failure_is_distinct_from_creation_unknown(monkeypatch):
    manifest = create_batch_manifest(
        plan_batches(['proposal-1'], dataset_label='YZ247')[0],
        archive_files=(ManifestFile('a.archive.json', 'a.archive.json', 'archive'),),
        companion_files=(),
        upload_name='batch',
        created_utc='2026-01-01T00:00:00Z',
        updated_utc='2026-01-01T00:00:00Z',
    )
    manifest = replace(manifest, status=ManifestStatus.PREFLIGHT_PASSED)

    def failing_processing_uploader(**kwargs):
        return uploader_module.UploadResult(
            dry_run=False,
            upload_id='upload-1',
            entry_id='entry-1',
            processing_status='FAILURE',
            published=False,
        )

    from lab_data.ingestion.batch_upload import create_batch_upload

    result = create_batch_upload(
        manifest,
        api_base_url='http://example/api',
        bearer_token='token',
        uploader=failing_processing_uploader,
        dry_run=False,
    )

    assert result.state == 'processing_failed'
    assert result.created is True
    assert result.manifest.upload_id == 'upload-1'
    assert result.manifest.status is ManifestStatus.PROCESSING_FAILED
    assert result.manifest.processing_status == 'FAILURE'
