"""Focused tests for the single-create batch upload adapter."""

from dataclasses import replace

import pytest

from lab_data.ingestion.batch_manifest import (
    CanonicalFile,
    ManifestFile,
    ManifestStatus,
    create_batch_manifest,
)
from lab_data.ingestion.batch_planner import plan_batches
from lab_data.ingestion.batch_reconcile import RemoteBatchState, reconcile_batch
from lab_data.ingestion.batch_upload import create_batch_upload
from lab_data.parsers.nomad_uploader import NomadUploadError, UploadResult


def _manifest(*, status=ManifestStatus.PREFLIGHT_PASSED, upload_id=None, files=True):
    planned = plan_batches(('proposal-1', 'proposal-2'), dataset_label='synthetic')[0]
    archive_files = (
        (
            ManifestFile('archive-1.json', 'archive-1.archive.json', 'archive'),
            ManifestFile('archive-2.json', 'archive-2.archive.json', 'archive'),
        )
        if files
        else (
            CanonicalFile(
                'archive-1.json', 'D356/Initial Data/archive-1.json', 'archive'
            ),
        )
    )
    manifest = create_batch_manifest(
        planned,
        archive_files=archive_files,
        companion_files=(ManifestFile('raw.csv', 'Initial Data/raw.csv', 'raw'),),
        upload_name='synthetic-upload',
        created_utc='2026-01-01T00:00:00Z',
        updated_utc='2026-01-01T00:01:00Z',
    )
    return replace(manifest, status=status, upload_id=upload_id)


def _result(*, dry_run=False, upload_id='upload-1', status='SUCCESS'):
    return UploadResult(
        dry_run=dry_run,
        upload_id=None if dry_run else upload_id,
        entry_id='entry-1',
        processing_status=status,
        published=False,
        plan={'publish': False} if dry_run else None,
    )


def _fake_uploader(result=None, error=None):
    calls = []

    def uploader(*args, **kwargs):
        calls.append((args, kwargs))
        if error is not None:
            raise error
        return result or _result()

    uploader.calls = calls
    return uploader


def test_preflight_passed_manifest_creates_once_and_records_id():
    manifest = _manifest()
    uploader = _fake_uploader()

    result = create_batch_upload(
        manifest, api_base_url='http://example/api', uploader=uploader
    )

    assert result.created is True
    assert result.state == 'upload_created'
    assert result.manifest.upload_id == 'upload-1'
    assert result.manifest.status is ManifestStatus.UPLOAD_CREATED
    assert len(uploader.calls) == 1


@pytest.mark.parametrize(
    'status',
    [
        ManifestStatus.PLANNED,
        ManifestStatus.PROCESSING,
        ManifestStatus.SUCCESS,
        ManifestStatus.PROCESSING_FAILED,
        ManifestStatus.VERIFICATION_FAILED,
    ],
)
def test_non_preflight_status_is_rejected(status):
    uploader = _fake_uploader()

    result = create_batch_upload(
        _manifest(status=status), api_base_url='http://example/api', uploader=uploader
    )

    assert result.state == 'rejected'
    assert uploader.calls == []


def test_existing_upload_id_is_rejected_without_replacement():
    manifest = _manifest(upload_id='existing')
    uploader = _fake_uploader()

    result = create_batch_upload(
        manifest, api_base_url='http://example/api', uploader=uploader
    )

    assert result.manifest == manifest
    assert result.errors
    assert uploader.calls == []


def test_canonical_references_are_not_implicitly_uploaded():
    uploader = _fake_uploader()

    result = create_batch_upload(
        _manifest(files=False), api_base_url='http://example/api', uploader=uploader
    )

    assert result.state == 'rejected'
    assert 'explicit transport archive' in result.errors[0]
    assert uploader.calls == []


def test_explicit_archive_and_companion_mappings_are_selected():
    uploader = _fake_uploader()

    create_batch_upload(
        _manifest(), api_base_url='http://example/api', uploader=uploader
    )

    args, kwargs = uploader.calls[0]
    assert args == ()
    assert kwargs['archive_files'] == ['archive-1.json', 'archive-2.json']
    assert [file.destination_path for file in kwargs['upload_files']] == [
        'Initial Data/raw.csv',
    ]


def test_processing_status_is_recorded_without_claiming_success():
    uploader = _fake_uploader(result=_result(status='PROCESSING'))

    result = create_batch_upload(
        _manifest(), api_base_url='http://example/api', uploader=uploader
    )

    assert result.manifest.processing_status == 'PROCESSING'
    assert result.state == 'processing'
    assert result.created is True
    assert result.manifest.upload_id == 'upload-1'
    assert result.manifest.status is ManifestStatus.PROCESSING


def test_dry_run_keeps_manifest_and_does_not_create():
    manifest = _manifest()
    uploader = _fake_uploader(result=_result(dry_run=True))

    result = create_batch_upload(
        manifest,
        api_base_url='http://example/api',
        uploader=uploader,
        dry_run=True,
    )

    assert result.state == 'planned'
    assert result.created is False
    assert result.manifest == manifest
    assert result.upload_result.plan == {'publish': False}


def test_publish_and_upload_name_are_forwarded():
    manifest = replace(_manifest(), publish=False, upload_name='fixed-name')
    uploader = _fake_uploader()

    create_batch_upload(manifest, api_base_url='http://example/api', uploader=uploader)

    kwargs = uploader.calls[0][1]
    assert kwargs['publish'] is False
    assert kwargs['upload_name'] == 'fixed-name'


def test_legacy_auth_is_forwarded_without_bearer_token():
    uploader = _fake_uploader()

    create_batch_upload(
        _manifest(),
        api_base_url='http://example/api',
        auth=('user', 'password'),
        uploader=uploader,
    )

    kwargs = uploader.calls[0][1]
    assert kwargs['auth'] == ('user', 'password')
    assert kwargs['bearer_token'] is None


def test_verification_status_is_not_falsely_completed():
    manifest = replace(_manifest(), verification_status='pending')
    result = create_batch_upload(
        manifest, api_base_url='http://example/api', uploader=_fake_uploader()
    )

    assert result.manifest.verification_status == 'pending'


def test_upload_result_is_retained_for_caller_reconciliation():
    uploader = _fake_uploader()

    result = create_batch_upload(
        _manifest(), api_base_url='http://example/api', uploader=uploader
    )

    assert result.upload_result is not None
    assert result.upload_result.upload_id == 'upload-1'


def test_bearer_and_legacy_auth_are_forwarded_without_result_leak():
    token = 'fake-token'
    uploader = _fake_uploader()

    result = create_batch_upload(
        _manifest(),
        api_base_url='http://example/api',
        bearer_token=token,
        auth=('user', 'password'),
        uploader=uploader,
    )

    kwargs = uploader.calls[0][1]
    assert kwargs['bearer_token'] == token
    assert kwargs['auth'] == ('user', 'password')
    assert token not in repr(result)


@pytest.mark.parametrize(
    'error',
    [
        TimeoutError('ambiguous'),
        RuntimeError('server failure'),
        NomadUploadError(
            'POST /v1/uploads failed before upload ID: status=400; '
            'body="Limit of unpublished uploads exceeded for user."'
        ),
    ],
)
def test_uploader_failure_never_retries_or_changes_manifest(error):
    manifest = _manifest()
    uploader = _fake_uploader(error=error)

    result = create_batch_upload(
        manifest, api_base_url='http://example/api', uploader=uploader
    )

    assert result.state == 'creation_unknown'
    assert result.manifest == manifest
    assert len(uploader.calls) == 1
    assert 'ambiguous' not in result.errors[0]


def test_non_json_uploader_response_is_ambiguous_and_never_retries():
    import requests

    manifest = _manifest()
    uploader = _fake_uploader(
        error=requests.exceptions.JSONDecodeError('empty body', '', 0)
    )

    result = create_batch_upload(
        manifest, api_base_url='http://example/api', uploader=uploader
    )

    assert result.state == 'creation_unknown'
    assert result.manifest == manifest
    assert result.manifest.upload_id is None
    assert len(uploader.calls) == 1


def test_no_upload_id_is_assigned_when_uploader_returns_none():
    uploader = _fake_uploader(result=_result(upload_id=None))

    result = create_batch_upload(
        _manifest(), api_base_url='http://example/api', uploader=uploader
    )

    assert result.created is False
    assert result.manifest.upload_id is None


def test_result_is_compatible_with_reconciliation():
    upload = create_batch_upload(
        _manifest(), api_base_url='http://example/api', uploader=_fake_uploader()
    )
    remote = RemoteBatchState(
        upload_id=upload.manifest.upload_id,
        process_status='SUCCESS',
        entry_ids=(('proposal-1', 'entry-1'), ('proposal-2', 'entry-2')),
    )

    reconciled, result = reconcile_batch(upload.manifest, remote)

    assert result.state == 'success'
    assert reconciled.status is ManifestStatus.SUCCESS


def test_confirmed_id_with_no_entry_is_processing_and_reconcileable():
    uploader = _fake_uploader(
        result=UploadResult(
            dry_run=False,
            upload_id='upload-pending',
            entry_id=None,
            processing_status=None,
            published=False,
        )
    )

    result = create_batch_upload(
        _manifest(), api_base_url='http://example/api', uploader=uploader
    )

    assert result.state == 'processing'
    assert result.created is True
    assert result.manifest.upload_id == 'upload-pending'
    assert result.manifest.status is ManifestStatus.PROCESSING
    assert result.manifest.processing_status is None
