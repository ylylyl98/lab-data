"""Focused tests for the read-only local pipeline planner."""

from pathlib import Path

import pytest

from lab_data.ingestion.inventory_store import (
    INVENTORY_PRESENT,
    METADATA_INDEXED,
    METADATA_PENDING,
    InventoryRecord,
    InventoryStore,
)
from lab_data.ingestion.local_pipeline import plan_local_pipeline


def _inventory(
    path: Path,
    *,
    metadata_status: str = METADATA_INDEXED,
    parser_version: str | None = 'scanner-v1',
) -> None:
    with InventoryStore(path) as store:
        store.upsert(
            InventoryRecord(
                relative_path='YZ247/Initial Data/file.csv',
                size_bytes=1,
                mtime_ns=1,
                inventory_status=INVENTORY_PRESENT,
                metadata_status=metadata_status,
                parser_version=parser_version,
            )
        )
        session = store.begin_scan('session-1')
        store.mark_seen(
            'YZ247/Initial Data/file.csv', session.session_id, session.generation
        )
        store.complete_scan(session.session_id, files_seen=1)


def _paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    db = tmp_path / 'inventory.sqlite'
    root = tmp_path / 'storage'
    batches = tmp_path / 'batches'
    root.mkdir()
    batches.mkdir()
    return db, root, batches


def test_clean_state_is_deterministic_and_local_only(tmp_path: Path) -> None:
    db, root, batches = _paths(tmp_path)
    _inventory(db)
    before = db.read_bytes()

    first = plan_local_pipeline(db, root, batches, dataset_label='YZ247')
    second = plan_local_pipeline(db, root, batches, dataset_label='YZ247')

    assert first == second
    assert first.blockers == ()
    assert first.metadata.selected_count == 0
    assert first.allowed_actions == ('generate_archives', 'build_batches')
    assert first.excluded_actions == (
        'nomad_upload',
        'nomad_publish',
        'nomad_process',
    )
    assert db.read_bytes() == before


def test_pending_and_parser_stale_selection_is_reported(tmp_path: Path) -> None:
    db, root, batches = _paths(tmp_path)
    _inventory(db, metadata_status=METADATA_PENDING, parser_version=None)

    pending = plan_local_pipeline(db, root, batches)
    assert pending.metadata.selected_count == 1
    assert pending.metadata.ordinary_selected_count == 1
    assert pending.allowed_actions == ('review_blockers',)
    assert any('pending metadata' in blocker for blocker in pending.blockers)

    with InventoryStore(db) as store:
        store.update_metadata_status_and_parser_version(
            'YZ247/Initial Data/file.csv', METADATA_INDEXED, 'scanner-v1'
        )
    stale = plan_local_pipeline(db, root, batches, parser_version='scanner-v2')
    assert stale.metadata.selected_count == 1
    assert stale.metadata.ordinary_selected_count == 0
    assert stale.metadata.parser_stale_count == 1
    assert stale.allowed_actions == (
        'index_metadata',
        'generate_archives',
        'build_batches',
    )


def test_missing_paths_are_blockers_and_never_created(tmp_path: Path) -> None:
    db = tmp_path / 'missing.sqlite'
    root = tmp_path / 'missing-storage'
    batches = tmp_path / 'missing-batches'

    plan = plan_local_pipeline(db, root, batches)

    assert plan.allowed_actions == ('review_blockers',)
    assert any('inventory database missing' in item for item in plan.blockers)
    assert any('storage root missing' in item for item in plan.blockers)
    assert any('batches directory missing' in item for item in plan.blockers)
    assert not db.exists()
    assert not root.exists()
    assert not batches.exists()


def test_invalid_paths_and_parser_version_fail_safely(tmp_path: Path) -> None:
    db, root, batches = _paths(tmp_path)
    _inventory(db)
    with pytest.raises(ValueError, match='absolute'):
        plan_local_pipeline('relative.sqlite', root, batches)
    with pytest.raises(ValueError, match='safe string'):
        plan_local_pipeline(db, root, batches, parser_version='bad\nversion')


def test_planner_never_advertises_nomad_execution(tmp_path: Path) -> None:
    db, root, batches = _paths(tmp_path)
    _inventory(db)
    plan = plan_local_pipeline(db, root, batches)

    assert not any('nomad' in action for action in plan.allowed_actions)
    assert 'nomad_upload' in plan.excluded_actions
    assert 'nomad_publish' in plan.excluded_actions
    assert 'nomad_process' in plan.excluded_actions
