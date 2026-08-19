"""Focused tests for deterministic metadata-indexing record selection."""

from pathlib import Path

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


def _record(
    relative_path: str,
    *,
    inventory_status: str = INVENTORY_PRESENT,
    metadata_status: str,
) -> InventoryRecord:
    return InventoryRecord(
        relative_path=relative_path,
        size_bytes=1,
        mtime_ns=1,
        inventory_status=inventory_status,
        metadata_status=metadata_status,
    )


def _populated_store(tmp_path: Path) -> InventoryStore:
    store = InventoryStore(tmp_path / 'inventory.db')
    store.upsert(_record('b/pending.csv', metadata_status=METADATA_PENDING))
    store.upsert(_record('a/stale.csv', metadata_status=METADATA_STALE))
    store.upsert(_record('c/indexed.csv', metadata_status=METADATA_INDEXED))
    store.upsert(
        _record(
            'd/missing.csv',
            inventory_status=INVENTORY_MISSING,
            metadata_status=METADATA_PENDING,
        )
    )
    store.upsert(_record('e/failed.csv', metadata_status=METADATA_FAILED))
    return store


def test_default_selects_pending_and_stale_present_records(tmp_path):
    store = _populated_store(tmp_path)

    selected = store.list_for_metadata_indexing()

    assert [record.relative_path for record in selected] == [
        'a/stale.csv',
        'b/pending.csv',
    ]
    store.close()


def test_default_excludes_failed(tmp_path):
    store = _populated_store(tmp_path)

    paths = {record.relative_path for record in store.list_for_metadata_indexing()}

    assert 'e/failed.csv' not in paths
    store.close()


def test_include_failed_selects_failed_records(tmp_path):
    store = _populated_store(tmp_path)

    selected = store.list_for_metadata_indexing(include_failed=True)

    assert [record.relative_path for record in selected] == [
        'a/stale.csv',
        'b/pending.csv',
        'e/failed.csv',
    ]
    store.close()


def test_indexed_and_missing_are_never_selected(tmp_path):
    store = _populated_store(tmp_path)

    for include_failed in (False, True):
        paths = {
            record.relative_path
            for record in store.list_for_metadata_indexing(
                include_failed=include_failed
            )
        }
        assert 'c/indexed.csv' not in paths
        assert 'd/missing.csv' not in paths
    store.close()


def test_ordering_is_deterministic(tmp_path):
    store = _populated_store(tmp_path)

    first = store.list_for_metadata_indexing()
    second = store.list_for_metadata_indexing()

    assert first == second
    assert [record.relative_path for record in first] == [
        'a/stale.csv',
        'b/pending.csv',
    ]
    store.close()


def test_canonical_paths_are_forward_slash(tmp_path):
    store = InventoryStore(tmp_path / 'inventory.db')
    store.upsert(
        _record('D356/Initial Data/file.csv', metadata_status=METADATA_PENDING)
    )
    store.upsert(
        _record('D356\\Initial Data\\file2.csv', metadata_status=METADATA_STALE)
    )

    selected = store.list_for_metadata_indexing()

    assert [record.relative_path for record in selected] == [
        'D356/Initial Data/file.csv',
        'D356/Initial Data/file2.csv',
    ]
    assert all('\\' not in record.relative_path for record in selected)
    store.close()


def test_include_failed_type_is_validated(tmp_path):
    store = InventoryStore(tmp_path / 'inventory.db')

    try:
        store.list_for_metadata_indexing(include_failed=1)  # type: ignore[arg-type]
    except TypeError:
        pass
    else:
        raise AssertionError('expected TypeError for non-bool include_failed')
    finally:
        store.close()


def test_selection_does_not_mutate_status(tmp_path):
    store = _populated_store(tmp_path)
    before = store.list_records()

    store.list_for_metadata_indexing()
    store.list_for_metadata_indexing(include_failed=True)

    assert store.list_records() == before
    store.close()
