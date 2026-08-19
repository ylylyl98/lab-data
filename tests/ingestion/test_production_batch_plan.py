"""Focused tests for the immutable one-batch production plan."""

from dataclasses import replace
from pathlib import Path

from lab_data.ingestion.batch_manifest import (
    ManifestFile,
    ManifestStatus,
    create_batch_manifest,
    write_batch_manifest,
)
from lab_data.ingestion.batch_planner import plan_batches
from lab_data.ingestion.production_batch_reader import plan_production_batch


class _Remote:
    def __init__(self, outcome, matching_upload_ids=()):
        self.outcome = outcome
        self.matching_upload_ids = tuple(matching_upload_ids)


def _manifest(
    number,
    *,
    status=ManifestStatus.PREFLIGHT_PASSED,
    upload_id=None,
    verification=None,
    publish=False,
):
    ids = [f'YZ247-{i:04d}' for i in range(1, 3)]
    planned = plan_batches(ids, batch_size=50, dataset_label='YZ247')[0]
    manifest = create_batch_manifest(
        planned,
        archive_files=tuple(
            ManifestFile(f'C:\\a\\{pid}.archive.json', f'{pid}.archive.json', 'archive')
            for pid in ids
        ),
        companion_files=(),
        publish=publish,
        upload_name=f'lab-data-YZ247-phase9-batch-{number:03d}',
        created_utc='2026-08-18T00:00:00Z',
        updated_utc='2026-08-18T00:00:00Z',
    )
    return replace(
        manifest,
        batch_number=number,
        status=status,
        upload_id=upload_id,
        verification_status=verification,
    )


def _write_final(number):
    manifest = _manifest(
        number,
        status=ManifestStatus.SUCCESS,
        upload_id=f'u{number}',
        verification='verified',
    )
    return replace(
        manifest, entry_ids=tuple((pid, f'e-{pid}') for pid in manifest.proposal_ids)
    )


def _write_preflight(directory, number, manifest=None):
    manifest = manifest or _manifest(number)
    write_batch_manifest(
        manifest, directory / f'batch-{number:03d}.preflight_passed.json'
    )
    write_batch_manifest(
        replace(manifest, status=ManifestStatus.PLANNED),
        directory / f'batch-{number:03d}.json',
    )


def _write_final_file(directory, number, manifest=None):
    write_batch_manifest(
        manifest or _write_final(number),
        directory / f'batch-{number:03d}.final.json',
    )


def test_create_plan(tmp_path):
    _write_preflight(tmp_path, 1)

    plan = plan_production_batch(tmp_path, _Remote('no_match'))

    assert plan.batch_number == 1
    assert plan.action == 'create'
    assert plan.reason == 'eligible and no remote match'
    assert plan.publish is False
    assert plan.manifest_path is not None
    assert plan.preflight_path is not None


def test_reconcile_plan(tmp_path):
    _write_preflight(tmp_path, 1)

    plan = plan_production_batch(tmp_path, _Remote('single_match', ['remote-1']))

    assert plan.action == 'reconcile'
    assert plan.reason == 'exactly one remote upload matches'


def test_ambiguous_remote_blocks(tmp_path):
    _write_preflight(tmp_path, 1)

    plan = plan_production_batch(
        tmp_path, _Remote('ambiguous', ['remote-1', 'remote-2'])
    )

    assert plan.action == 'blocked'
    assert 'ambiguous' in plan.reason


def test_predecessor_block(tmp_path):
    _write_preflight(tmp_path, 2)

    plan = plan_production_batch(tmp_path, _Remote('no_match'))

    assert plan.action == 'blocked'
    assert plan.batch_number == 2  # noqa: PLR2004
    assert 'predecessor' in plan.reason


def test_publish_block(tmp_path):
    _write_preflight(tmp_path, 1, _manifest(1, publish=True))

    plan = plan_production_batch(tmp_path, _Remote('no_match'))

    assert plan.action == 'blocked'
    assert plan.publish is True
    assert 'publish' in plan.reason


def test_missing_preflight_blocks(tmp_path):
    plan = plan_production_batch(tmp_path, _Remote('no_match'))

    assert plan.action == 'blocked'
    assert plan.batch_number is None
    assert 'no prepared batches' in plan.reason


def test_creation_unknown_never_advances(tmp_path):
    _write_preflight(
        tmp_path, 1, _manifest(1, status=ManifestStatus.UPLOAD_CREATED, upload_id=None)
    )
    write_batch_manifest(
        _manifest(1, status=ManifestStatus.UPLOAD_CREATED, upload_id=None),
        tmp_path / 'batch-001.upload_created.json',
    )

    plan = plan_production_batch(tmp_path, _Remote('no_match'))

    assert plan.action == 'blocked'


def test_one_batch_only(tmp_path):
    _write_preflight(tmp_path, 1)
    _write_preflight(tmp_path, 2)

    plan = plan_production_batch(tmp_path, _Remote('no_match'))

    assert plan.batch_number == 1


def test_no_credentials_in_plan(tmp_path):
    _write_preflight(tmp_path, 1)

    plan = plan_production_batch(tmp_path, _Remote('no_match'))

    text = repr(plan)
    for forbidden in ('token', 'Bearer', 'password', 'Authorization'):
        assert forbidden not in text


def test_module_has_no_uploader_coupling():
    source = Path('src/lab_data/ingestion/production_batch_reader.py').read_text(
        encoding='utf-8'
    )
    lowered = source.lower()

    assert 'create_batch_upload' not in lowered
    assert 'upload_entry_archive' not in lowered
    assert 'requests.post' not in lowered
