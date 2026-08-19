"""Focused tests for the read-only persisted pipeline status report."""

from __future__ import annotations

import json
from pathlib import Path

from lab_data.ingestion.batch_manifest import (
    CanonicalFile,
    ManifestStatus,
    create_batch_manifest,
    manifest_to_dict,
)
from lab_data.ingestion.batch_planner import PlannedBatch
from lab_data.ingestion.inventory_store import (
    INVENTORY_PRESENT,
    METADATA_INDEXED,
    METADATA_PENDING,
    InventoryRecord,
    InventoryStore,
)
from lab_data.ingestion.pipeline_status import read_pipeline_status


def _planned(number: int, proposal: str) -> PlannedBatch:
    return PlannedBatch(
        batch_number=number,
        batch_id=f'batch-{number}',
        dataset_label='YZ247',
        proposals=(proposal,),
    )


def _manifest(number: int, proposal: str, **updates: object) -> dict[str, object]:
    manifest = create_batch_manifest(
        _planned(number, proposal),
        archive_files=(
            CanonicalFile(
                source_path=f'/source/{proposal}.json',
                relative_path=f'YZ247/{proposal}.json',
                role='archive',
            ),
        ),
        upload_name=f'upload-{number}',
    )
    data = manifest_to_dict(manifest)
    data.update(updates)
    return data


def _write_batch(
    directory: Path, number: int, proposal: str, **updates: object
) -> None:
    payload = _manifest(number, proposal, **updates)
    (directory / f'batch-{number:03d}.json').write_text(
        json.dumps(payload), encoding='utf-8'
    )


def _write_lifecycle(
    directory: Path,
    number: int,
    proposal: str,
    suffix: str,
    **updates: object,
) -> None:
    payload = _manifest(number, proposal, **updates)
    (directory / f'batch-{number:03d}{suffix}').write_text(
        json.dumps(payload), encoding='utf-8'
    )


def _inventory_db(tmp_path: Path, *, pending: bool = False) -> Path:
    path = tmp_path / 'inventory.sqlite'
    with InventoryStore(path) as store:
        store.upsert(
            InventoryRecord(
                relative_path='YZ247/Initial Data/a.csv',
                size_bytes=1,
                mtime_ns=1,
                inventory_status=INVENTORY_PRESENT,
                metadata_status=METADATA_PENDING if pending else METADATA_INDEXED,
                parser_version=None if pending else 'parser-1',
                file_kind=None if pending else 'csv',
                sample_hint=None if pending else 'YZ247',
            )
        )
        session = store.begin_scan('session-1')
        store.complete_scan(session.session_id, files_seen=1)
    return path


def test_healthy_state_is_deterministic_and_read_only(tmp_path: Path) -> None:
    batches = tmp_path / 'batches'
    batches.mkdir()
    inventory = _inventory_db(tmp_path)
    _write_batch(batches, 1, 'p-1')
    _write_lifecycle(
        batches,
        1,
        'p-1',
        '.preflight_passed.json',
        status=ManifestStatus.PREFLIGHT_PASSED.value,
    )

    before = inventory.read_bytes()
    first = read_pipeline_status(inventory, batches, dataset_label='YZ247')
    second = read_pipeline_status(inventory, batches, dataset_label='YZ247')

    assert first == second
    assert first.inventory.total_records == 1
    assert first.inventory.latest_scan is not None
    assert first.inventory.latest_scan.status == 'completed'
    assert first.batches.lifecycle_counts['preflight_ready'] == 1
    assert first.batches.next_eligible.eligible
    assert first.warnings
    assert inventory.read_bytes() == before


def test_pending_metadata_and_incomplete_scan_are_blockers(tmp_path: Path) -> None:
    inventory = _inventory_db(tmp_path, pending=True)
    batches = tmp_path / 'batches'
    batches.mkdir()
    status = read_pipeline_status(inventory, batches)
    assert any('pending metadata' in item for item in status.blockers)

    # Replace the latest session with an active one in a separate fixture.
    active_db = tmp_path / 'active.sqlite'
    with InventoryStore(active_db) as store:
        session = store.begin_scan('active')
        assert session.status == 'active'
    active_status = read_pipeline_status(active_db, batches)
    assert any(
        'latest scan session is active' in item for item in active_status.blockers
    )


def test_duplicate_membership_and_upload_ids_are_reported(tmp_path: Path) -> None:
    inventory = _inventory_db(tmp_path)
    batches = tmp_path / 'batches'
    batches.mkdir()
    _write_batch(batches, 1, 'duplicate')
    _write_batch(batches, 2, 'duplicate')
    for number in (1, 2):
        _write_lifecycle(
            batches,
            number,
            'duplicate',
            '.upload_created.json',
            status=ManifestStatus.UPLOAD_CREATED.value,
            upload_id='same-upload',
        )
    status = read_pipeline_status(inventory, batches)
    assert status.batches.duplicate_proposal_ids == ('duplicate',)
    assert status.batches.duplicate_upload_ids == ('same-upload',)
    assert any('duplicate proposal' in item for item in status.blockers)
    assert any('duplicate confirmed upload' in item for item in status.blockers)


def test_malformed_artifact_is_explicit_and_does_not_crash(tmp_path: Path) -> None:
    inventory = _inventory_db(tmp_path)
    batches = tmp_path / 'batches'
    batches.mkdir()
    _write_batch(batches, 1, 'p-1')
    (batches / 'batch-001.final.json').write_text('{not-json', encoding='utf-8')
    status = read_pipeline_status(inventory, batches)
    assert status.batches.malformed_artifacts
    assert any('malformed artifact' in item for item in status.blockers)


def test_no_eligible_batch_is_reported_without_network_or_writes(
    tmp_path: Path,
) -> None:
    inventory = _inventory_db(tmp_path)
    batches = tmp_path / 'batches'
    batches.mkdir()
    before = sorted(path.name for path in batches.iterdir())
    status = read_pipeline_status(inventory, batches)
    assert not status.batches.next_eligible.eligible
    assert any('no eligible batch' in item for item in status.warnings)
    assert sorted(path.name for path in batches.iterdir()) == before


def test_published_batch_is_blocked_and_not_treated_as_upload_ready(
    tmp_path: Path,
) -> None:
    inventory = _inventory_db(tmp_path)
    batches = tmp_path / 'batches'
    batches.mkdir()
    _write_batch(batches, 1, 'p-1')
    _write_lifecycle(
        batches,
        1,
        'p-1',
        '.preflight_passed.json',
        status=ManifestStatus.PREFLIGHT_PASSED.value,
        publish=True,
    )
    status = read_pipeline_status(inventory, batches)
    assert status.batches.published_batches == 1
    assert any('publish=true' in item for item in status.blockers)
