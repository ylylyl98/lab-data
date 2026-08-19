"""Focused tests for the standalone SQLite inventory store."""

import sqlite3
from pathlib import Path

import pytest

from lab_data.ingestion.inventory_store import (
    INVENTORY_MISSING,
    INVENTORY_PRESENT,
    METADATA_FAILED,
    METADATA_INDEXED,
    METADATA_PENDING,
    SCHEMA_VERSION,
    InventoryRecord,
    InventoryStore,
)


class _Clock:
    """Deterministic incrementing timestamp source."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return f'2026-01-01T00:00:{self.calls:02d}Z'


def _record(**overrides) -> InventoryRecord:
    values = {
        'relative_path': 'YZ247/Initial Data/file.csv',
        'size_bytes': 123,
        'mtime_ns': 456,
        'inventory_status': INVENTORY_PRESENT,
        'metadata_status': METADATA_PENDING,
    }
    values.update(overrides)
    return InventoryRecord(**values)


def _db_path(tmp_path: Path) -> Path:
    return tmp_path / 'inventory.db'


def test_new_database_initializes_schema_version(tmp_path):
    with InventoryStore(_db_path(tmp_path)) as store:
        assert store.count() == 0

    connection = sqlite3.connect(str(_db_path(tmp_path)))
    try:
        value = connection.execute(
            "SELECT value FROM inventory_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        assert int(value) == SCHEMA_VERSION
    finally:
        connection.close()


def test_insert_and_get_round_trips_all_fields(tmp_path):
    record = _record(
        content_hash='a' * 64,
        parser_version='v1.2.3',
        file_kind='csv',
        sample_hint='YZ247',
    )

    with InventoryStore(_db_path(tmp_path)) as store:
        stored = store.upsert(record)

        assert stored == store.get('YZ247/Initial Data/file.csv')
        assert stored.size_bytes == 123  # noqa: PLR2004
        assert stored.mtime_ns == 456  # noqa: PLR2004
        assert stored.inventory_status == INVENTORY_PRESENT
        assert stored.metadata_status == METADATA_PENDING
        assert stored.content_hash == 'a' * 64
        assert stored.parser_version == 'v1.2.3'
        assert stored.file_kind == 'csv'
        assert stored.sample_hint == 'YZ247'
        assert stored.created_utc is not None
        assert stored.updated_utc == stored.created_utc


def test_upsert_preserves_created_and_updates_updated_timestamp(tmp_path):
    clock = _Clock()
    store = InventoryStore(_db_path(tmp_path), now=clock)

    first = store.upsert(_record(size_bytes=1))
    second = store.upsert(_record(size_bytes=2))

    assert first.created_utc == '2026-01-01T00:00:01Z'
    assert first.updated_utc == '2026-01-01T00:00:01Z'
    assert second.created_utc == first.created_utc
    assert second.updated_utc == '2026-01-01T00:00:02Z'
    assert second.size_bytes == 2  # noqa: PLR2004
    assert store.count() == 1  # noqa: PLR2004
    store.close()


def test_upsert_updates_existing_record_fields(tmp_path):
    with InventoryStore(_db_path(tmp_path)) as store:
        store.upsert(_record(metadata_status=METADATA_PENDING))
        updated = store.upsert(
            _record(metadata_status=METADATA_INDEXED, size_bytes=999)
        )

        assert updated.metadata_status == METADATA_INDEXED
        assert updated.size_bytes == 999  # noqa: PLR2004
        assert store.count() == 1  # noqa: PLR2004


def test_list_records_is_deterministic_and_ordered(tmp_path):
    store = InventoryStore(_db_path(tmp_path))
    store.upsert(_record(relative_path='YZ247/Processed Data/b.dat'))
    store.upsert(_record(relative_path='D356/Initial Data/a.csv'))
    store.upsert(_record(relative_path='YZ247/Initial Data/a.csv'))

    first = store.list_records()
    second = store.list_records()

    assert first == second
    assert [record.relative_path for record in first] == [
        'D356/Initial Data/a.csv',
        'YZ247/Initial Data/a.csv',
        'YZ247/Processed Data/b.dat',
    ]
    store.close()


def test_count_reflects_records(tmp_path):
    with InventoryStore(_db_path(tmp_path)) as store:
        assert store.count() == 0
        store.upsert(_record())
        store.upsert(_record(relative_path='other/file.csv'))
        assert store.count() == 2  # noqa: PLR2004


def test_nested_relative_paths_are_canonicalized(tmp_path):
    with InventoryStore(_db_path(tmp_path)) as store:
        store.upsert(_record(relative_path='D356/Initial Data/file.csv'))

        assert store.get('D356/Initial Data/file.csv') is not None
        assert store.get('D356\\Initial Data\\file.csv') is not None
        assert store.get('D356/Initial Data/file.csv').relative_path == (
            'D356/Initial Data/file.csv'
        )


@pytest.mark.parametrize(
    'relative_path',
    [
        '',
        '../file.csv',
        'D356/../../file.csv',
        '/file.csv',
        r'C:\LabData\file.csv',
        r'\\NAS\LabData\file.csv',
    ],
)
def test_unsafe_paths_are_rejected(tmp_path, relative_path):
    with InventoryStore(_db_path(tmp_path)) as store:
        with pytest.raises(ValueError):
            store.upsert(_record(relative_path=relative_path))


def test_optional_content_hash_round_trips(tmp_path):
    with InventoryStore(_db_path(tmp_path)) as store:
        hashed = store.upsert(_record(content_hash='opaque-digest'))
        unhashed = store.upsert(
            _record(relative_path='other/file.csv', content_hash=None)
        )

        assert hashed.content_hash == 'opaque-digest'
        assert unhashed.content_hash is None


@pytest.mark.parametrize('field', ['size_bytes', 'mtime_ns'])
def test_negative_size_and_mtime_rejected(tmp_path, field):
    with InventoryStore(_db_path(tmp_path)) as store:
        with pytest.raises(ValueError, match='non-negative'):
            store.upsert(_record(**{field: -1}))


@pytest.mark.parametrize('field', ['size_bytes', 'mtime_ns'])
def test_boolean_size_and_mtime_rejected(tmp_path, field):
    with InventoryStore(_db_path(tmp_path)) as store:
        with pytest.raises(ValueError, match='non-negative'):
            store.upsert(_record(**{field: True}))


def test_invalid_inventory_status_rejected(tmp_path):
    with InventoryStore(_db_path(tmp_path)) as store:
        with pytest.raises(ValueError, match='inventory status'):
            store.upsert(_record(inventory_status='unknown'))


def test_invalid_metadata_status_rejected(tmp_path):
    with InventoryStore(_db_path(tmp_path)) as store:
        with pytest.raises(ValueError, match='metadata status'):
            store.upsert(_record(metadata_status='unknown'))


def test_mark_missing_then_mark_present_restores(tmp_path):
    with InventoryStore(_db_path(tmp_path)) as store:
        store.upsert(_record())
        missing = store.mark_missing('YZ247/Initial Data/file.csv')
        present = store.mark_present('YZ247/Initial Data/file.csv')

        assert missing.inventory_status == INVENTORY_MISSING
        assert present.inventory_status == INVENTORY_PRESENT
        assert store.count() == 1  # noqa: PLR2004
        assert store.get('YZ247/Initial Data/file.csv').size_bytes == 123  # noqa: PLR2004


def test_mark_missing_raises_for_unknown_record(tmp_path):
    with InventoryStore(_db_path(tmp_path)) as store:
        with pytest.raises(KeyError, match='not found'):
            store.mark_missing('missing/file.csv')


def test_update_metadata_status_round_trips(tmp_path):
    with InventoryStore(_db_path(tmp_path)) as store:
        store.upsert(_record())
        updated = store.update_metadata_status(
            'YZ247/Initial Data/file.csv', METADATA_FAILED
        )

        assert updated.metadata_status == METADATA_FAILED
        assert store.get('YZ247/Initial Data/file.csv').metadata_status == (
            METADATA_FAILED
        )


def test_update_metadata_status_and_parser_version_preserves_other_fields(tmp_path):
    with InventoryStore(_db_path(tmp_path)) as store:
        store.upsert(
            _record(
                metadata_status=METADATA_PENDING,
                content_hash='hash',
                file_kind='raw',
                sample_hint='YZ247',
            )
        )
        updated = store.update_metadata_status_and_parser_version(
            'YZ247/Initial Data/file.csv',
            METADATA_INDEXED,
            'scanner-v1',
        )

        assert updated.metadata_status == METADATA_INDEXED
        assert updated.parser_version == 'scanner-v1'
        assert updated.content_hash == 'hash'
        assert updated.file_kind == 'raw'
        assert updated.sample_hint == 'YZ247'


def test_update_metadata_status_and_parser_version_rejects_unsafe_value(tmp_path):
    with InventoryStore(_db_path(tmp_path)) as store:
        store.upsert(_record())
        with pytest.raises(ValueError, match='safe string'):
            store.update_metadata_status_and_parser_version(
                'YZ247/Initial Data/file.csv', METADATA_INDEXED, 'bad\nversion'
            )

        stored = store.get('YZ247/Initial Data/file.csv')
        assert stored.metadata_status == METADATA_PENDING
        assert stored.parser_version is None


def test_parser_version_round_trips(tmp_path):
    with InventoryStore(_db_path(tmp_path)) as store:
        stored = store.upsert(_record(parser_version='v9.9.9'))

        assert stored.parser_version == 'v9.9.9'
        assert store.get('YZ247/Initial Data/file.csv').parser_version == 'v9.9.9'


def test_future_schema_version_rejected(tmp_path):
    path = _db_path(tmp_path)
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


def test_reopen_preserves_data(tmp_path):
    path = _db_path(tmp_path)
    store = InventoryStore(path)
    store.upsert(_record())
    store.close()

    reopened = InventoryStore(path)
    record = reopened.get('YZ247/Initial Data/file.csv')
    reopened.close()

    assert record is not None
    assert record.size_bytes == 123  # noqa: PLR2004
    assert record.created_utc is not None


def test_context_manager_closes_connection(tmp_path):
    store = InventoryStore(_db_path(tmp_path))
    with store:
        assert store._conn is not None
    assert store._conn is None


def test_store_has_no_real_root_dependency(tmp_path):
    path = _db_path(tmp_path)

    # The record and store never require the referenced file to exist.
    with InventoryStore(path) as store:
        store.upsert(_record(relative_path='missing/nested/file.csv'))

    assert path.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ['inventory.db']


def test_module_has_no_nomad_coupling():
    source = Path('src/lab_data/ingestion/inventory_store.py').read_text(
        encoding='utf-8'
    )

    assert 'import nomad' not in source.lower()
    assert 'from nomad' not in source.lower()
    assert 'requests' not in source.lower()
    assert 'scan_directory' not in source
    assert 'hashlib' not in source.lower()
