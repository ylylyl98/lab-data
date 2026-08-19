"""Focused tests for injected-state batch reconciliation."""

from dataclasses import replace

import pytest

from lab_data.ingestion.batch_manifest import (
    CanonicalFile,
    ManifestFile,
    ManifestStatus,
    create_batch_manifest,
)
from lab_data.ingestion.batch_planner import plan_batches
from lab_data.ingestion.batch_reconcile import (
    RemoteBatchState,
    reconcile_batch,
)


def _manifest(*, upload_id='upload-1', files=(), publish=False):
    planned = plan_batches(['proposal-001', 'proposal-002'], dataset_label='synthetic')[0]
    manifest = create_batch_manifest(
        planned,
        archive_files=files,
        publish=publish,
        upload_name='synthetic-batch',
        created_utc='2026-01-01T00:00:00Z',
        updated_utc='2026-01-01T00:01:00Z',
    )
    return replace(manifest, upload_id=upload_id)


def _remote(**changes):
    values = {
        'upload_id': 'upload-1',
        'process_status': 'success',
        'entry_ids': (('proposal-001', 'entry-001'), ('proposal-002', 'entry-002')),
    }
    values.update(changes)
    return RemoteBatchState(**values)


def test_no_upload_id_is_not_created_or_inferred():
    manifest = _manifest(upload_id=None)

    reconciled, result = reconcile_batch(manifest, _remote(upload_id='new'))

    assert reconciled == manifest
    assert result.state == 'not_created'
    assert result.reconciled is False


def test_matching_id_success_updates_copy():
    manifest = _manifest()

    reconciled, result = reconcile_batch(manifest, _remote())

    assert result.reconciled is True
    assert result.state == 'success'
    assert reconciled.status is ManifestStatus.SUCCESS
    assert reconciled.entry_ids == _remote().entry_ids
    assert reconciled.verification_status is None
    assert manifest.status is ManifestStatus.PLANNED
    assert reconciled is not manifest


def test_repeated_success_reconciliation_is_idempotent():
    manifest = _manifest()
    remote = _remote()

    first = reconcile_batch(manifest, remote)
    second = reconcile_batch(first[0], remote)

    assert first == second


def test_id_mismatch_fails_without_switching_identity():
    manifest = _manifest()

    reconciled, result = reconcile_batch(manifest, _remote(upload_id='other'))

    assert reconciled == manifest
    assert result.state == 'id_mismatch'
    assert result.reconciled is False


@pytest.mark.parametrize('process_status', ['pending', 'running', 'processing'])
def test_pending_or_running_state_becomes_processing(process_status):
    manifest = _manifest()

    reconciled, result = reconcile_batch(
        manifest,
        _remote(process_status=process_status, process_running=process_status == 'running'),
    )

    assert result.state == 'processing'
    assert reconciled.status is ManifestStatus.PROCESSING
    assert reconciled.entry_ids == _remote().entry_ids


def test_success_requires_matching_entry_count():
    manifest = _manifest()

    reconciled, result = reconcile_batch(
        manifest, _remote(entry_ids=(('proposal-001', 'entry-001'),))
    )

    assert result.state == 'reconciliation_error'
    assert result.reconciled is False
    assert reconciled.status is ManifestStatus.PLANNED


def test_failed_state_is_preserved_and_does_not_retry():
    manifest = _manifest()
    remote = _remote(process_status='failure', errors=('z-error', 'a-error'))

    first = reconcile_batch(manifest, remote)
    second = reconcile_batch(first[0], remote)

    assert first == second
    assert first[0].status is ManifestStatus.PROCESSING_FAILED
    assert first[1].state == 'processing_failed'


def test_unexpected_publication_is_not_accepted():
    manifest = _manifest(publish=False)

    reconciled, result = reconcile_batch(manifest, _remote(published=True))

    assert result.reconciled is False
    assert result.state == 'reconciliation_error'
    assert reconciled.status is ManifestStatus.PLANNED


def test_expected_publication_can_be_true_when_requested():
    manifest = _manifest(publish=True)

    reconciled, result = reconcile_batch(manifest, _remote(published=True))

    assert result.reconciled is True
    assert reconciled.status is ManifestStatus.SUCCESS


def test_not_found_preserves_recorded_upload_id():
    manifest = _manifest()

    reconciled, result = reconcile_batch(manifest, _remote(not_found=True))

    assert reconciled.upload_id == 'upload-1'
    assert result.state == 'not_found'
    assert result.reconciled is False


def test_success_preserves_recorded_upload_id():
    manifest = _manifest()

    reconciled, _ = reconcile_batch(manifest, _remote())

    assert reconciled.upload_id == manifest.upload_id


def test_entry_order_is_preserved():
    manifest = _manifest()
    entries = (('proposal-002', 'entry-002'), ('proposal-001', 'entry-001'))

    reconciled, _ = reconcile_batch(manifest, _remote(entry_ids=entries))

    assert reconciled.entry_ids == entries


def test_errors_are_deterministically_ordered():
    manifest = _manifest()
    remote = _remote(errors=('z-error', 'a-error'), published=True)

    _, result = reconcile_batch(manifest, remote)

    assert result.errors == tuple(sorted(result.errors))


def test_metadata_only_manifest_is_supported():
    manifest = _manifest(
        files=(CanonicalFile('nas/archive.json', 'Initial Data/archive.json', 'archive'),)
    )

    reconciled, result = reconcile_batch(manifest, _remote())

    assert result.reconciled is True
    assert reconciled.status is ManifestStatus.SUCCESS


def test_transport_manifest_is_supported():
    manifest = _manifest(
        files=(ManifestFile('source/archive.json', 'upload/archive.json', 'archive'),)
    )

    reconciled, result = reconcile_batch(manifest, _remote())

    assert result.reconciled is True
    assert reconciled.status is ManifestStatus.SUCCESS


def test_remote_warnings_are_preserved_and_sorted():
    _, result = reconcile_batch(manifest := _manifest(), _remote(warnings=('z', 'a')))

    assert manifest.status is ManifestStatus.PLANNED
    assert result.warnings == ('a', 'z')


def test_no_credentials_are_handled_or_exposed():
    remote = _remote()

    assert 'NOMAD_TOKEN' not in repr(remote)
    assert 'Authorization' not in repr(remote)


def test_reconciliation_has_no_filesystem_or_network_side_effects(monkeypatch):
    import requests

    def fail(*args, **kwargs):
        pytest.fail('network operation attempted')

    monkeypatch.setattr(requests, 'get', fail)
    monkeypatch.setattr(requests, 'post', fail)

    reconciled, result = reconcile_batch(_manifest(), _remote())

    assert reconciled.status is ManifestStatus.SUCCESS
    assert result.reconciled is True
