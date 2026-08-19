"""Focused tests for deterministic next-eligible batch selection."""

from dataclasses import replace

from lab_data.ingestion.batch_manifest import (
    ManifestFile,
    ManifestStatus,
    create_batch_manifest,
    write_batch_manifest,
)
from lab_data.ingestion.batch_planner import plan_batches
from lab_data.ingestion.production_batch_reader import (
    BatchEligibility,
    read_production_batch_state,
    select_next_eligible_batch,
)


def _manifest(  # noqa: PLR0913
    number,
    *,
    item_count=50,
    status=ManifestStatus.PREFLIGHT_PASSED,
    upload_id=None,
    verification=None,
    publish=False,
):
    ids = [f'YZ247-{i:04d}' for i in range(1, item_count + 1)]
    planned = plan_batches(ids, batch_size=50, dataset_label='YZ247')[0]
    manifest = create_batch_manifest(
        planned,
        archive_files=tuple(
            ManifestFile(
                f'C:\\archives\\{pid}.archive.json', f'{pid}.archive.json', 'archive'
            )
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
        status=status,
        upload_id=upload_id,
        verification_status=verification,
        batch_number=number,
    )


def _final_verified(number, *, item_count=50):
    manifest = _manifest(
        number,
        item_count=item_count,
        status=ManifestStatus.SUCCESS,
        upload_id=f'upload-{number}',
        verification='verified',
    )
    return replace(
        manifest,
        entry_ids=tuple((pid, f'entry-{pid}') for pid in manifest.proposal_ids),
    )


def _write_preflight(directory, number, manifest=None):
    write_batch_manifest(
        manifest or _manifest(number),
        directory / f'batch-{number:03d}.preflight_passed.json',
    )


def _write_final(directory, number, manifest=None):
    write_batch_manifest(
        manifest or _final_verified(number),
        directory / f'batch-{number:03d}.final.json',
    )


def test_batch001_verified_selects_batch002(tmp_path):
    _write_final(tmp_path, 1)
    _write_preflight(tmp_path, 2)

    decision = select_next_eligible_batch(tmp_path)

    assert decision == BatchEligibility(
        eligible=True,
        batch_number=2,
        batch_id=decision.batch_id,
        reason='eligible',
    )


def test_batch001_eligible_when_first(tmp_path):
    _write_preflight(tmp_path, 1)

    decision = select_next_eligible_batch(tmp_path)

    assert decision.eligible is True
    assert decision.batch_number == 1
    assert decision.reason == 'eligible'


def test_predecessor_unverified_blocks(tmp_path):
    _write_preflight(tmp_path, 2)

    decision = select_next_eligible_batch(tmp_path)

    assert decision.eligible is False
    assert decision.batch_number == 2  # noqa: PLR2004
    assert decision.blocking_batch == 1
    assert 'predecessor' in decision.reason


def test_already_verified_skips_to_next(tmp_path):
    _write_final(tmp_path, 1)
    _write_final(tmp_path, 2)
    _write_preflight(tmp_path, 3)

    decision = select_next_eligible_batch(tmp_path)

    assert decision.eligible is True
    assert decision.batch_number == 3  # noqa: PLR2004


def test_upload_id_without_verification_blocks_reconcile(tmp_path):
    _write_preflight(
        tmp_path,
        1,
        _manifest(1, upload_id='upload-pending', status=ManifestStatus.UPLOAD_CREATED),
    )
    write_batch_manifest(
        _manifest(1, upload_id='upload-pending', status=ManifestStatus.UPLOAD_CREATED),
        tmp_path / 'batch-001.upload_created.json',
    )

    decision = select_next_eligible_batch(tmp_path)

    assert decision.eligible is False
    assert decision.batch_number == 1
    assert 'reconciliation' in decision.reason


def test_missing_preflight_no_eligible(tmp_path):
    decision = select_next_eligible_batch(tmp_path)

    assert decision.eligible is False
    assert decision.reason == 'no prepared batches'


def test_invalid_preflight_blocks(tmp_path):
    (tmp_path / 'batch-001.preflight_passed.json').write_text('{bad', encoding='utf-8')

    decision = select_next_eligible_batch(tmp_path)

    assert decision.eligible is False
    assert decision.batch_number == 1
    assert 'invalid' in decision.reason


def test_missing_preflight_blocks_at_numeric_batch(tmp_path):
    write_batch_manifest(
        _manifest(1, status=ManifestStatus.PLANNED),
        tmp_path / 'batch-001.json',
    )

    decision = select_next_eligible_batch(tmp_path)

    assert decision.eligible is False
    assert decision.batch_number == 1
    assert decision.batch_id.startswith('YZ247-batch-001-')
    assert decision.reason == 'preflight manifest missing'


def test_publish_true_blocks(tmp_path):
    _write_preflight(tmp_path, 1, _manifest(1, publish=True))

    decision = select_next_eligible_batch(tmp_path)

    assert decision.eligible is False
    assert decision.batch_number == 1
    assert 'publish' in decision.reason


def test_deterministic_selection(tmp_path):
    _write_final(tmp_path, 1)
    _write_preflight(tmp_path, 2)

    first = select_next_eligible_batch(tmp_path)
    second = select_next_eligible_batch(tmp_path)

    assert first == second


def test_restart_from_persisted_artifacts(tmp_path):
    _write_final(tmp_path, 1)
    _write_preflight(tmp_path, 2)

    assert select_next_eligible_batch(tmp_path).batch_number == 2  # noqa: PLR2004
    assert select_next_eligible_batch(tmp_path).batch_number == 2  # noqa: PLR2004


def test_final_batch_item_count_five(tmp_path):
    write_batch_manifest(
        _manifest(31, item_count=5, status=ManifestStatus.PLANNED),
        tmp_path / 'batch-031.json',
    )

    state = read_production_batch_state(tmp_path, 31)

    assert state.batch_number == 31  # noqa: PLR2004
    assert state.item_count == 5  # noqa: PLR2004
