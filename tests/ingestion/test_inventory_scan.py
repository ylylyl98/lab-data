"""Focused tests for the filesystem inventory scanner."""

import os
from pathlib import Path

import pytest

from lab_data.ingestion import inventory_scan
from lab_data.ingestion.inventory_scan import scan_inventory
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


def _storage_and_store(tmp_path: Path, root_name: str = 'root'):
    root = tmp_path / root_name
    root.mkdir(parents=True)
    store = InventoryStore(tmp_path / 'inventory.db')
    return StorageRoot(root), store


def _write(path: Path, content: bytes = b'x') -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _set_mtime(path: Path, mtime_ns: int) -> None:
    os.utime(path, ns=(mtime_ns, mtime_ns))


def _seed(  # noqa: PLR0913
    store: InventoryStore,
    relative_path: str,
    *,
    size_bytes: int,
    mtime_ns: int,
    inventory_status: str = INVENTORY_PRESENT,
    metadata_status: str = METADATA_INDEXED,
    content_hash: str | None = 'hash',
    parser_version: str | None = 'v1',
) -> InventoryRecord:
    return store.upsert(
        InventoryRecord(
            relative_path=relative_path,
            size_bytes=size_bytes,
            mtime_ns=mtime_ns,
            inventory_status=inventory_status,
            metadata_status=metadata_status,
            content_hash=content_hash,
            parser_version=parser_version,
        )
    )


def test_empty_tree_produces_complete_zero_result(tmp_path):
    storage, store = _storage_and_store(tmp_path)

    result = scan_inventory(storage, store)

    assert result.scan_complete is True
    assert result.seen == 0
    assert result.new == 0
    assert result.unchanged == 0
    assert result.changed == 0
    assert result.restored == 0
    assert result.marked_missing == 0
    assert result.errors == ()
    assert result.error_count == 0


def test_single_new_file_is_recorded_present_pending(tmp_path):
    storage, store = _storage_and_store(tmp_path)
    _write(storage.root / 'a.csv', b'abc')

    result = scan_inventory(storage, store)

    assert result.seen == 1
    assert result.new == 1
    record = store.get('a.csv')
    assert record is not None
    assert record.inventory_status == INVENTORY_PRESENT
    assert record.metadata_status == METADATA_PENDING
    assert record.parser_version is None
    assert record.content_hash is None
    assert record.size_bytes == 3  # noqa: PLR2004


def test_nested_tree_and_deterministic_order(tmp_path):
    storage, store = _storage_and_store(tmp_path)
    _write(storage.root / 'z' / 'b.csv')
    _write(storage.root / 'a' / 'c.csv')
    _write(storage.root / 'a' / 'a.csv')

    result = scan_inventory(storage, store)

    assert result.seen == 3  # noqa: PLR2004
    assert result.new == 3  # noqa: PLR2004
    assert [record.relative_path for record in store.list_records()] == [
        'a/a.csv',
        'a/c.csv',
        'z/b.csv',
    ]


def test_directories_are_not_recorded(tmp_path):
    storage, store = _storage_and_store(tmp_path)
    _write(storage.root / 'nested' / 'file.csv')
    _write(storage.root / 'empty' / '.keep', b'')

    result = scan_inventory(storage, store)

    assert result.seen == 2  # noqa: PLR2004
    assert store.count() == 2  # noqa: PLR2004
    assert [record.relative_path for record in store.list_records()] == [
        'empty/.keep',
        'nested/file.csv',
    ]


def test_unchanged_indexed_record_is_preserved(tmp_path):
    storage, store = _storage_and_store(tmp_path)
    path = _write(storage.root / 'a.csv', b'abc')
    _set_mtime(path, 1000)
    _seed(
        store,
        'a.csv',
        size_bytes=3,
        mtime_ns=1000,
        metadata_status=METADATA_INDEXED,
        content_hash='keep-hash',
        parser_version='keep-version',
    )

    result = scan_inventory(storage, store)

    assert result.seen == 1
    assert result.unchanged == 1
    assert result.changed == 0
    record = store.get('a.csv')
    assert record.metadata_status == METADATA_INDEXED
    assert record.content_hash == 'keep-hash'
    assert record.parser_version == 'keep-version'


def test_changed_size_marks_record_stale_and_preserves_metadata(tmp_path):
    storage, store = _storage_and_store(tmp_path)
    _write(storage.root / 'a.csv', b'abcdef')
    _seed(
        store,
        'a.csv',
        size_bytes=3,
        mtime_ns=1000,
        metadata_status=METADATA_INDEXED,
        content_hash='keep-hash',
        parser_version='keep-version',
    )

    result = scan_inventory(storage, store)

    assert result.changed == 1
    assert result.unchanged == 0
    record = store.get('a.csv')
    assert record.metadata_status == METADATA_STALE
    assert record.size_bytes == 6  # noqa: PLR2004
    assert record.content_hash == 'keep-hash'
    assert record.parser_version == 'keep-version'


def test_changed_mtime_marks_record_stale(tmp_path):
    storage, store = _storage_and_store(tmp_path)
    path = _write(storage.root / 'a.csv', b'abc')
    _set_mtime(path, 2000)
    _seed(
        store,
        'a.csv',
        size_bytes=3,
        mtime_ns=1000,
        metadata_status=METADATA_PENDING,
    )

    result = scan_inventory(storage, store)

    assert result.changed == 1
    assert store.get('a.csv').metadata_status == METADATA_STALE


def test_restore_missing_record_with_same_stats_preserves_metadata(tmp_path):
    storage, store = _storage_and_store(tmp_path)
    path = _write(storage.root / 'a.csv', b'abc')
    _set_mtime(path, 1000)
    _seed(
        store,
        'a.csv',
        size_bytes=3,
        mtime_ns=1000,
        inventory_status=INVENTORY_MISSING,
        metadata_status=METADATA_INDEXED,
    )

    result = scan_inventory(storage, store)

    assert result.restored == 1
    assert result.new == 0
    record = store.get('a.csv')
    assert record.inventory_status == INVENTORY_PRESENT
    assert record.metadata_status == METADATA_INDEXED


def test_restore_missing_record_with_different_stats_marks_stale(tmp_path):
    storage, store = _storage_and_store(tmp_path)
    _write(storage.root / 'a.csv', b'abcdef')
    _seed(
        store,
        'a.csv',
        size_bytes=3,
        mtime_ns=1000,
        inventory_status=INVENTORY_MISSING,
        metadata_status=METADATA_INDEXED,
    )

    result = scan_inventory(storage, store)

    assert result.restored == 1
    assert result.changed == 0
    record = store.get('a.csv')
    assert record.inventory_status == INVENTORY_PRESENT
    assert record.metadata_status == METADATA_STALE


def test_complete_scan_marks_unseen_present_record_missing(tmp_path):
    storage, store = _storage_and_store(tmp_path)
    _write(storage.root / 'kept.csv')
    _seed(store, 'kept.csv', size_bytes=1, mtime_ns=1000)
    _seed(store, 'gone.csv', size_bytes=1, mtime_ns=1000)

    result = scan_inventory(storage, store)

    assert result.marked_missing == 1
    gone = store.get('gone.csv')
    assert gone is not None
    assert gone.inventory_status == INVENTORY_MISSING
    assert gone.size_bytes == 1


def test_incomplete_traversal_does_not_mark_unseen_missing(tmp_path, monkeypatch):
    storage, store = _storage_and_store(tmp_path)
    _write(storage.root / 'kept.csv')
    _seed(store, 'kept.csv', size_bytes=1, mtime_ns=1000)
    _seed(store, 'gone.csv', size_bytes=1, mtime_ns=1000)

    real_walk = inventory_scan._walk_files

    def failing_walk(root, errors):
        errors.append('traversal error: simulated failure')
        yield from real_walk(root, errors)

    monkeypatch.setattr(inventory_scan, '_walk_files', failing_walk)

    result = scan_inventory(storage, store)

    assert result.scan_complete is False
    assert result.marked_missing == 0
    assert any('traversal error' in error for error in result.errors)
    assert store.get('gone.csv').inventory_status == INVENTORY_PRESENT


def test_reopen_preserves_scanned_records(tmp_path):
    storage, store = _storage_and_store(tmp_path)
    _write(storage.root / 'a.csv')
    scan_inventory(storage, store)
    store.close()

    reopened = InventoryStore(tmp_path / 'inventory.db')
    record = reopened.get('a.csv')
    reopened.close()

    assert record is not None
    assert record.metadata_status == METADATA_PENDING


def test_storage_root_portability_preserves_relative_forward_slash_paths(tmp_path):
    storage, store = _storage_and_store(tmp_path, root_name='deep/root')
    _write(storage.root / 'nested' / 'file.csv')

    scan_inventory(storage, store)

    record = store.list_records()[0]
    assert record.relative_path == 'nested/file.csv'
    assert '\\' not in record.relative_path


def test_error_count_matches_sorted_errors(tmp_path):
    storage, store = _storage_and_store(tmp_path)

    result = scan_inventory(storage, store)

    assert result.error_count == len(result.errors)
    assert tuple(sorted(result.errors)) == result.errors


def test_module_does_not_read_contents_or_couple_to_nomad():
    source = Path('src/lab_data/ingestion/inventory_scan.py').read_text(
        encoding='utf-8'
    )
    lowered = source.lower()

    assert 'open(' not in lowered
    assert 'read_bytes' not in lowered
    assert 'read_text' not in lowered
    assert 'hashlib' not in lowered
    assert 'import nomad' not in lowered
    assert 'from nomad' not in lowered
    assert 'import requests' not in lowered
    assert 'scan_directory' not in source


def _make_symlink(link: Path, target: Path) -> bool:
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError):
        return False
    return True


def test_directory_symlink_is_not_followed(tmp_path):
    storage, store = _storage_and_store(tmp_path)
    real = storage.root / 'real'
    _write(real / 'file.csv')
    link = storage.root / 'link'
    if not _make_symlink(link, real):
        pytest.skip('symlink creation not available')

    result = scan_inventory(storage, store)

    assert result.scan_complete is True
    assert result.seen == 1
    assert store.get('real/file.csv') is not None
    assert store.get('link/file.csv') is None


def test_file_symlink_is_skipped_and_reported_as_error(tmp_path):
    storage, store = _storage_and_store(tmp_path)
    real = _write(storage.root / 'real.csv')
    link = storage.root / 'link.csv'
    if not _make_symlink(link, real):
        pytest.skip('symlink creation not available')

    result = scan_inventory(storage, store)

    assert result.scan_complete is False
    assert result.seen == 1
    assert store.get('real.csv') is not None
    assert store.get('link.csv') is None
    assert any('symlinked file not followed' in error for error in result.errors)


def test_failed_metadata_status_is_preserved_when_unchanged(tmp_path):
    storage, store = _storage_and_store(tmp_path)
    path = _write(storage.root / 'a.csv', b'abc')
    _set_mtime(path, 1000)
    _seed(
        store,
        'a.csv',
        size_bytes=3,
        mtime_ns=1000,
        metadata_status=METADATA_FAILED,
    )

    result = scan_inventory(storage, store)

    assert result.unchanged == 1
    assert store.get('a.csv').metadata_status == METADATA_FAILED
