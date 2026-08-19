"""Focused tests for the deterministic metadata-indexing planner."""

import dataclasses
from pathlib import Path

import pytest

from lab_data.ingestion.inventory_index_bridge import plan_metadata_indexing
from lab_data.ingestion.inventory_store import (
    INVENTORY_MISSING,
    INVENTORY_PRESENT,
    METADATA_FAILED,
    METADATA_INDEXED,
    METADATA_PENDING,
    METADATA_STALE,
    InventoryRecord,
    InventoryStore,
)
from lab_data.storage import StorageRoot


def _record(
    relative_path: str,
    *,
    inventory_status: str = INVENTORY_PRESENT,
    metadata_status: str,
    parser_version: str | None = None,
) -> InventoryRecord:
    return InventoryRecord(
        relative_path=relative_path,
        size_bytes=1,
        mtime_ns=1,
        inventory_status=inventory_status,
        metadata_status=metadata_status,
        parser_version=parser_version,
    )


def _store(tmp_path: Path) -> InventoryStore:
    return InventoryStore(tmp_path / 'inventory.db')


def _storage(tmp_path: Path) -> StorageRoot:
    root = tmp_path / 'root'
    root.mkdir(parents=True)
    return StorageRoot(root)


def test_selection_groups_by_top_level_scanner_unit(tmp_path):
    storage = _storage(tmp_path)
    store = _store(tmp_path)
    store.upsert(_record('YZ247/Initial Data/a.csv', metadata_status=METADATA_PENDING))
    store.upsert(_record('YZ247/Processed Data/b.dat', metadata_status=METADATA_STALE))
    store.upsert(_record('D356/Initial Data/c.csv', metadata_status=METADATA_PENDING))

    plan = plan_metadata_indexing(storage, store)

    assert plan.selected_count == 3  # noqa: PLR2004
    assert plan.unit_count == 2  # noqa: PLR2004
    assert [unit.scanner_unit for unit in plan.units] == ['D356', 'YZ247']
    assert plan.units[0].relative_paths == ('D356/Initial Data/c.csv',)
    assert plan.units[1].relative_paths == (
        'YZ247/Initial Data/a.csv',
        'YZ247/Processed Data/b.dat',
    )
    store.close()


def test_units_are_deterministically_ordered(tmp_path):
    storage = _storage(tmp_path)
    store = _store(tmp_path)
    store.upsert(_record('z/file.csv', metadata_status=METADATA_PENDING))
    store.upsert(_record('a/file.csv', metadata_status=METADATA_STALE))
    store.upsert(_record('m/file.csv', metadata_status=METADATA_PENDING))

    first = plan_metadata_indexing(storage, store)
    second = plan_metadata_indexing(storage, store)

    assert first == second
    assert [unit.scanner_unit for unit in first.units] == ['a', 'm', 'z']
    store.close()


def test_selected_paths_preserve_canonical_forward_slash(tmp_path):
    storage = _storage(tmp_path)
    store = _store(tmp_path)
    store.upsert(
        _record('D356\\Initial Data\\file.csv', metadata_status=METADATA_PENDING)
    )

    plan = plan_metadata_indexing(storage, store)

    assert plan.selected_records[0].relative_path == 'D356/Initial Data/file.csv'
    assert '\\' not in plan.selected_records[0].relative_path
    assert plan.units[0].relative_paths == ('D356/Initial Data/file.csv',)
    store.close()


def test_indexed_missing_and_failed_are_excluded_and_counted(tmp_path):
    storage = _storage(tmp_path)
    store = _store(tmp_path)
    store.upsert(_record('pending.csv', metadata_status=METADATA_PENDING))
    store.upsert(_record('indexed.csv', metadata_status=METADATA_INDEXED))
    store.upsert(
        _record(
            'missing.csv',
            inventory_status=INVENTORY_MISSING,
            metadata_status=METADATA_PENDING,
        )
    )
    store.upsert(_record('failed.csv', metadata_status=METADATA_FAILED))

    plan = plan_metadata_indexing(storage, store)

    assert plan.selected_count == 1
    assert plan.skipped_indexed == 1
    assert plan.skipped_missing == 1
    assert plan.skipped_failed == 1
    assert {r.relative_path for r in plan.selected_records} == {'pending.csv'}
    store.close()


def test_include_failed_selects_failed_and_clears_failed_skip(tmp_path):
    storage = _storage(tmp_path)
    store = _store(tmp_path)
    store.upsert(_record('failed.csv', metadata_status=METADATA_FAILED))
    store.upsert(_record('indexed.csv', metadata_status=METADATA_INDEXED))

    plan = plan_metadata_indexing(storage, store, include_failed=True)

    assert plan.selected_count == 1
    assert plan.skipped_failed == 0
    assert plan.skipped_indexed == 1
    assert plan.selected_records[0].relative_path == 'failed.csv'
    store.close()


def test_requested_parser_version_selects_missing_and_differing_indexed_records(
    tmp_path,
):
    storage = _storage(tmp_path)
    store = _store(tmp_path)
    store.upsert(
        _record(
            'missing-version.csv',
            metadata_status=METADATA_INDEXED,
        )
    )
    store.upsert(
        _record(
            'old-version.csv',
            metadata_status=METADATA_INDEXED,
            parser_version='parser-v1',
        )
    )
    store.upsert(
        _record(
            'same-version.csv',
            metadata_status=METADATA_INDEXED,
            parser_version='parser-v2',
        )
    )

    plan = plan_metadata_indexing(
        storage,
        store,
        requested_parser_version='parser-v2',
    )

    assert [record.relative_path for record in plan.selected_records] == [
        'missing-version.csv',
        'old-version.csv',
    ]
    assert plan.requested_parser_version == 'parser-v2'
    assert plan.parser_version_stale_count == 2  # noqa: PLR2004
    assert plan.ordinary_selected_count == 0
    assert plan.skipped_indexed == 1
    store.close()


def test_requested_parser_version_keeps_pending_stale_and_failed_semantics(tmp_path):
    storage = _storage(tmp_path)
    store = _store(tmp_path)
    store.upsert(_record('pending.csv', metadata_status=METADATA_PENDING))
    store.upsert(_record('stale.csv', metadata_status=METADATA_STALE))
    store.upsert(_record('failed.csv', metadata_status=METADATA_FAILED))

    default_plan = plan_metadata_indexing(
        storage,
        store,
        requested_parser_version='parser-v2',
    )
    retry_plan = plan_metadata_indexing(
        storage,
        store,
        include_failed=True,
        requested_parser_version='parser-v2',
    )

    assert [record.relative_path for record in default_plan.selected_records] == [
        'pending.csv',
        'stale.csv',
    ]
    assert default_plan.ordinary_selected_count == 2  # noqa: PLR2004
    assert default_plan.selected_failed_count == 0
    assert default_plan.skipped_failed == 1
    assert [record.relative_path for record in retry_plan.selected_records] == [
        'failed.csv',
        'pending.csv',
        'stale.csv',
    ]
    assert retry_plan.ordinary_selected_count == 3  # noqa: PLR2004
    assert retry_plan.selected_failed_count == 1
    assert retry_plan.skipped_failed == 0
    store.close()


def test_requested_parser_version_order_counts_and_planning_are_deterministic(
    tmp_path,
):
    storage = _storage(tmp_path)
    store = _store(tmp_path)
    store.upsert(
        _record(
            'z/indexed-old.csv',
            metadata_status=METADATA_INDEXED,
            parser_version='parser-v1',
        )
    )
    store.upsert(_record('a/pending.csv', metadata_status=METADATA_PENDING))
    store.upsert(
        _record(
            'm/indexed-same.csv',
            metadata_status=METADATA_INDEXED,
            parser_version='parser-v2',
        )
    )
    before = store.list_records()

    first = plan_metadata_indexing(
        storage,
        store,
        requested_parser_version='parser-v2',
    )
    second = plan_metadata_indexing(
        storage,
        store,
        requested_parser_version='parser-v2',
    )

    assert first == second
    assert [record.relative_path for record in first.selected_records] == [
        'a/pending.csv',
        'z/indexed-old.csv',
    ]
    assert first.selected_count == 2  # noqa: PLR2004
    assert first.ordinary_selected_count == 1
    assert first.parser_version_stale_count == 1
    assert first.skipped_indexed == 1
    assert store.list_records() == before
    store.close()


def test_plan_is_immutable_and_read_only(tmp_path):
    storage = _storage(tmp_path)
    store = _store(tmp_path)
    store.upsert(_record('a/file.csv', metadata_status=METADATA_PENDING))
    before = store.list_records()

    plan = plan_metadata_indexing(storage, store)

    assert store.list_records() == before
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.skipped_indexed = 9
    store.close()


def test_module_has_no_nomad_or_content_read_coupling():
    source = Path('src/lab_data/ingestion/inventory_index_bridge.py').read_text(
        encoding='utf-8'
    )
    lowered = source.lower()

    assert 'import nomad' not in lowered
    assert 'from nomad' not in lowered
    assert 'import requests' not in lowered
    assert 'open(' not in lowered
    assert 'read_bytes' not in lowered
