"""Focused tests for schema migration and resumable scan sessions."""

import sqlite3
import types
from pathlib import Path

import pytest

from lab_data.ingestion import inventory_scan
from lab_data.ingestion.inventory_scan import scan_inventory_batch
from lab_data.ingestion.inventory_store import (
    INVENTORY_MISSING,
    INVENTORY_PRESENT,
    METADATA_INDEXED,
    METADATA_PENDING,
    METADATA_STALE,
    SCHEMA_VERSION,
    SESSION_ACTIVE,
    SESSION_COMPLETED,
    SESSION_FAILED,
    InventoryRecord,
    InventoryStore,
)
from lab_data.storage import StorageRoot


def _setup(tmp_path: Path, *, max_files: int | None = None):
    root = tmp_path / 'root'
    root.mkdir(parents=True)
    store = InventoryStore(tmp_path / 'inventory.db')
    return StorageRoot(root), store, max_files


def _write(path: Path, content: bytes = b'x') -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


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


def _v1_database(path: Path) -> None:
    connection = sqlite3.connect(str(path))
    try:
        connection.execute(
            'CREATE TABLE inventory_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)'
        )
        connection.execute(
            "INSERT INTO inventory_meta (key, value) VALUES ('schema_version', '1')"
        )
        connection.execute(
            """
            CREATE TABLE inventory_records (
                relative_path TEXT PRIMARY KEY,
                size_bytes INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                inventory_status TEXT NOT NULL,
                metadata_status TEXT NOT NULL,
                content_hash TEXT,
                parser_version TEXT,
                file_kind TEXT,
                sample_hint TEXT,
                created_utc TEXT NOT NULL,
                updated_utc TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO inventory_records (
                relative_path, size_bytes, mtime_ns, inventory_status,
                metadata_status, content_hash, parser_version, file_kind,
                sample_hint, created_utc, updated_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                'D356/Initial Data/a.csv',
                123,
                456,
                INVENTORY_PRESENT,
                METADATA_INDEXED,
                'old-hash',
                'old-parser',
                'csv',
                'D356',
                '2026-01-01T00:00:00Z',
                '2026-01-01T00:00:00Z',
            ),
        )
        connection.commit()
    finally:
        connection.close()


def test_v1_database_migrates_to_v2_preserving_rows(tmp_path):
    path = tmp_path / 'inventory.db'
    _v1_database(path)

    with InventoryStore(path) as store:
        assert store.count() == 1
        record = store.get('D356/Initial Data/a.csv')
        assert record is not None
        assert record.size_bytes == 123  # noqa: PLR2004
        assert record.mtime_ns == 456  # noqa: PLR2004
        assert record.content_hash == 'old-hash'
        assert record.parser_version == 'old-parser'
        assert record.last_seen_session_id is None
        assert record.last_seen_generation is None

    connection = sqlite3.connect(str(path))
    try:
        version = connection.execute(
            "SELECT value FROM inventory_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        assert int(version) == SCHEMA_VERSION
        columns = {
            row[1] for row in connection.execute('PRAGMA table_info(inventory_records)')
        }
        assert 'last_seen_session_id' in columns
        assert 'last_seen_generation' in columns
        sessions = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name = 'scan_sessions'"
        ).fetchone()
        assert sessions is not None
    finally:
        connection.close()


def test_future_schema_is_still_rejected(tmp_path):
    path = tmp_path / 'inventory.db'
    connection = sqlite3.connect(str(path))
    try:
        connection.execute(
            'CREATE TABLE inventory_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)'
        )
        connection.execute(
            "INSERT INTO inventory_meta (key, value) VALUES ('schema_version', '99')"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ValueError, match='unsupported inventory schema version'):
        InventoryStore(path).count()


def test_begin_and_resume_active_session(tmp_path):
    _, store, _ = _setup(tmp_path)

    session = store.begin_scan(session_id='session-a')

    assert session.session_id == 'session-a'
    assert session.generation == 1
    assert session.status == SESSION_ACTIVE
    assert session.checkpoint_path is None
    assert session.files_seen == 0

    resumed = store.resume_scan()
    assert resumed == session


def test_only_one_active_session_is_allowed(tmp_path):
    _, store, _ = _setup(tmp_path)
    store.begin_scan(session_id='first')

    with pytest.raises(ValueError, match='active scan session already exists'):
        store.begin_scan(session_id='second')


def test_bounded_scan_resumes_after_close_and_reopen(tmp_path):
    storage, _, max_files = _setup(tmp_path, max_files=2)
    for index in range(5):
        _write(storage.root / f'f{index}.csv')
    db_path = tmp_path / 'inventory.db'

    first_store = InventoryStore(db_path)
    first = scan_inventory_batch(storage, first_store, max_files=max_files)
    assert first.scan_complete is False
    assert first.seen == 2  # noqa: PLR2004
    assert first.remaining == 3  # noqa: PLR2004
    assert first.status == SESSION_ACTIVE
    assert first_store.resume_scan().checkpoint_path == 'f1.csv'
    first_store.close()

    reopened = InventoryStore(db_path)
    resumed = reopened.resume_scan()
    assert resumed is not None
    assert resumed.checkpoint_path == 'f1.csv'
    assert resumed.files_seen == 2  # noqa: PLR2004

    second = scan_inventory_batch(storage, reopened, max_files=max_files)
    assert second.scan_complete is False
    assert second.seen == 4  # noqa: PLR2004
    assert second.remaining == 1
    assert reopened.count() == 4  # noqa: PLR2004

    third = scan_inventory_batch(storage, reopened, max_files=max_files)
    assert third.scan_complete is True
    assert third.seen == 5  # noqa: PLR2004
    assert third.remaining == 0
    assert third.status == SESSION_COMPLETED
    assert reopened.count() == 5  # noqa: PLR2004
    reopened.close()


def test_missing_reconciliation_deferred_until_complete(tmp_path):
    storage, _, max_files = _setup(tmp_path, max_files=1)
    _write(storage.root / 'a.csv')
    _write(storage.root / 'b.csv')
    _write(storage.root / 'c.csv')
    db_path = tmp_path / 'inventory.db'
    store = InventoryStore(db_path)

    # First completed generation records all files as present.
    scan_inventory_batch(storage, store, max_files=None)
    assert store.get('a.csv').inventory_status == INVENTORY_PRESENT
    assert store.get('b.csv').inventory_status == INVENTORY_PRESENT
    assert store.get('c.csv').inventory_status == INVENTORY_PRESENT

    # Delete c.csv, then run partial scans that do not yet cover every file.
    (storage.root / 'c.csv').unlink()
    partial = scan_inventory_batch(storage, store, max_files=max_files)
    assert partial.scan_complete is False
    assert store.get('b.csv').inventory_status == INVENTORY_PRESENT
    assert store.get('c.csv').inventory_status == INVENTORY_PRESENT

    final = scan_inventory_batch(storage, store, max_files=max_files)
    assert final.scan_complete is True
    assert final.marked_missing == 1
    assert store.get('c.csv').inventory_status == INVENTORY_MISSING
    store.close()


def test_changed_new_restored_across_resume(tmp_path):
    storage, _, max_files = _setup(tmp_path, max_files=1)
    _write(storage.root / 'a.csv', b'new-size')
    _write(storage.root / 'b.csv')
    _write(storage.root / 'c.csv')
    db_path = tmp_path / 'inventory.db'
    store = InventoryStore(db_path)

    _seed(store, 'a.csv', size_bytes=1, mtime_ns=1000)
    _seed(
        store,
        'c.csv',
        size_bytes=1,
        mtime_ns=1000,
        inventory_status=INVENTORY_MISSING,
    )

    first = scan_inventory_batch(storage, store, max_files=max_files)
    assert first.changed == 1
    assert store.get('a.csv').metadata_status == METADATA_STALE

    second = scan_inventory_batch(storage, store, max_files=max_files)
    assert second.new == 1
    assert store.get('b.csv').metadata_status == METADATA_PENDING

    third = scan_inventory_batch(storage, store, max_files=max_files)
    assert third.restored == 1
    assert third.scan_complete is True
    assert store.get('c.csv').inventory_status == INVENTORY_PRESENT
    store.close()


def test_failure_never_reconciles_missing_and_retry_starts_new_generation(tmp_path):
    storage, store, _ = _setup(tmp_path)
    _write(storage.root / 'a.csv')
    _seed(store, 'a.csv', size_bytes=1, mtime_ns=1000)
    _seed(store, 'gone.csv', size_bytes=1, mtime_ns=1000)

    session = store.begin_scan(session_id='will-fail')
    store.fail_scan(
        session.session_id,
        errors=('simulated failure',),
        files_seen=1,
        files_new=1,
    )

    failed = store.get_session('will-fail')
    assert failed.status == SESSION_FAILED
    assert failed.errors == ('simulated failure',)
    assert store.get('a.csv').inventory_status == INVENTORY_PRESENT
    assert store.get('gone.csv').inventory_status == INVENTORY_PRESENT

    # A fresh session resumes cleanly without the failed generation reconciling.
    result = scan_inventory_batch(storage, store, max_files=None)
    assert result.scan_complete is True
    assert result.generation == 2  # noqa: PLR2004
    assert store.get('a.csv').inventory_status == INVENTORY_PRESENT
    assert store.get('gone.csv').inventory_status == INVENTORY_MISSING


def test_chunked_simulation_over_hundreds_of_files(tmp_path):
    storage, _, max_files = _setup(tmp_path, max_files=50)
    for index in range(275):
        _write(storage.root / f'file-{index:04d}.csv')
    db_path = tmp_path / 'inventory.db'
    store = InventoryStore(db_path)

    batches = []
    result = scan_inventory_batch(storage, store, max_files=max_files)
    batches.append(result)
    while not result.scan_complete:
        result = scan_inventory_batch(storage, store, max_files=max_files)
        batches.append(result)

    assert result.scan_complete is True
    assert result.seen == 275  # noqa: PLR2004
    assert result.new == 275  # noqa: PLR2004
    assert result.marked_missing == 0
    assert store.count() == 275  # noqa: PLR2004
    assert store.resume_scan() is None
    assert [batch.generation for batch in batches] == [1] * len(batches)
    store.close()


def test_checkpoint_updates_counts_without_completing(tmp_path):
    _, store, _ = _setup(tmp_path)
    session = store.begin_scan(session_id='checkpoint')

    updated = store.checkpoint_scan(
        session.session_id,
        checkpoint_path='a/file.csv',
        files_seen=3,
        files_new=2,
        files_unchanged=1,
    )

    assert updated.checkpoint_path == 'a/file.csv'
    assert updated.files_seen == 3  # noqa: PLR2004
    assert updated.files_new == 2  # noqa: PLR2004
    assert updated.files_unchanged == 1
    assert updated.status == SESSION_ACTIVE


def test_complete_scan_marks_unseen_and_closes_session(tmp_path):
    _, store, _ = _setup(tmp_path)
    store.upsert(
        InventoryRecord(
            relative_path='seen.csv',
            size_bytes=1,
            mtime_ns=1,
            inventory_status=INVENTORY_PRESENT,
            metadata_status=METADATA_PENDING,
        )
    )
    store.upsert(
        InventoryRecord(
            relative_path='unseen.csv',
            size_bytes=1,
            mtime_ns=1,
            inventory_status=INVENTORY_PRESENT,
            metadata_status=METADATA_PENDING,
        )
    )
    session = store.begin_scan(session_id='complete')
    store.mark_seen('seen.csv', session.session_id, session.generation)

    completed = store.complete_scan(
        session.session_id,
        files_seen=1,
        files_unchanged=1,
    )

    assert completed.status == SESSION_COMPLETED
    assert completed.files_marked_missing == 1
    assert store.get('unseen.csv').inventory_status == INVENTORY_MISSING
    assert store.get('seen.csv').inventory_status == INVENTORY_PRESENT


def test_session_statuses_round_trip(tmp_path):
    _, store, _ = _setup(tmp_path)
    active = store.begin_scan(session_id='status')
    store.checkpoint_scan(active.session_id, checkpoint_path='a.csv', files_seen=1)
    store.fail_scan(active.session_id, errors=('x',))

    failed = store.get_session('status')
    assert failed.status == SESSION_FAILED
    assert failed.checkpoint_path == 'a.csv'
    assert failed.files_seen == 1
    assert failed.errors == ('x',)


def test_scan_module_has_no_content_hash_or_parser_coupling():
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


def test_scan_is_streaming_and_does_not_materialize_all_files(tmp_path):
    source = Path('src/lab_data/ingestion/inventory_scan.py').read_text(
        encoding='utf-8'
    )

    assert 'def _iter_file_entries' in source
    assert '_collect_files' not in source
    assert 'entries = []' not in source

    storage, store, _ = _setup(tmp_path)
    for index in range(500):
        _write(storage.root / f'f{index:04d}.csv')

    errors: list[str] = []
    generator = inventory_scan._iter_file_entries(storage, errors)
    assert isinstance(generator, types.GeneratorType)
    first = next(generator)
    assert first.canonical == 'f0000.csv'
    generator.close()

    result = scan_inventory_batch(storage, store, max_files=100)
    assert result.scan_complete is False
    assert result.seen == 100  # noqa: PLR2004
    assert result.remaining == 400  # noqa: PLR2004
    assert store.count() == 100  # noqa: PLR2004
