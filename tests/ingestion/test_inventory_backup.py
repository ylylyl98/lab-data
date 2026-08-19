"""Focused safety tests for online SQLite inventory backups."""

import os
import sqlite3
from pathlib import Path

import pytest

from lab_data.ingestion import inventory_backup
from lab_data.ingestion.inventory_backup import (
    InventoryBackupError,
    backup_inventory_database,
    verify_inventory_backup,
)
from lab_data.ingestion.inventory_store import (
    INVENTORY_PRESENT,
    METADATA_INDEXED,
    SCHEMA_VERSION,
    InventoryRecord,
    InventoryStore,
)

EXPECTED_RECORD_COUNT = 2
EXPECTED_SESSION_COUNT = 1


def _record(path: str) -> InventoryRecord:
    return InventoryRecord(
        relative_path=path,
        size_bytes=12,
        mtime_ns=34,
        inventory_status=INVENTORY_PRESENT,
        metadata_status=METADATA_INDEXED,
        parser_version='scanner-v1',
        file_kind='csv',
        sample_hint='YZ247',
    )


def _make_inventory(path: Path) -> None:
    with InventoryStore(path) as store:
        store.upsert(_record('YZ247/Initial Data/a.csv'))
        session = store.begin_scan(session_id='scan-001')
        store.upsert_seen(_record('YZ247/Initial Data/b.csv'), session.session_id, 1)
        store.complete_scan(session.session_id, files_seen=1, files_new=1)


def test_online_backup_verifies_schema_counts_and_inventory_store_round_trip(tmp_path):
    source = tmp_path / 'source.db'
    destination = tmp_path / 'backups' / 'inventory.db'
    destination.parent.mkdir()
    _make_inventory(source)

    metadata = backup_inventory_database(source, destination)

    assert (
        metadata.source_schema_version
        == metadata.destination_schema_version
        == SCHEMA_VERSION
    )
    assert (
        metadata.source_record_count
        == metadata.destination_record_count
        == EXPECTED_RECORD_COUNT
    )
    assert (
        metadata.source_scan_session_count
        == metadata.destination_scan_session_count
        == EXPECTED_SESSION_COUNT
    )
    assert metadata.source_integrity == metadata.destination_integrity == 'ok'
    assert metadata.destination_size_bytes == destination.stat().st_size
    assert verify_inventory_backup(source, destination) == metadata

    with InventoryStore(destination) as store:
        assert [record.relative_path for record in store.list_records()] == [
            'YZ247/Initial Data/a.csv',
            'YZ247/Initial Data/b.csv',
        ]
        assert all(
            record.parser_version == 'scanner-v1' for record in store.list_records()
        )
        assert store.get_session('scan-001') is not None


def test_backup_refuses_existing_destination_without_modifying_it(tmp_path):
    source = tmp_path / 'source.db'
    destination = tmp_path / 'existing.db'
    _make_inventory(source)
    destination.write_bytes(b'keep this file')
    source_bytes = source.read_bytes()
    source_mtime = source.stat().st_mtime_ns

    with pytest.raises(FileExistsError):
        backup_inventory_database(source, destination)

    assert destination.read_bytes() == b'keep this file'
    assert source.read_bytes() == source_bytes
    assert source.stat().st_mtime_ns == source_mtime


def test_backup_requires_absolute_paths_and_existing_parent(tmp_path):
    source = tmp_path / 'source.db'
    _make_inventory(source)

    with pytest.raises(ValueError, match='absolute'):
        backup_inventory_database(Path('relative.db'), tmp_path / 'destination.db')
    with pytest.raises(FileNotFoundError, match='parent'):
        backup_inventory_database(source, tmp_path / 'missing' / 'destination.db')


def test_backup_rejects_missing_or_invalid_sources(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup_inventory_database(tmp_path / 'missing.db', tmp_path / 'destination.db')

    invalid = tmp_path / 'invalid.db'
    invalid.write_bytes(b'not sqlite')
    with pytest.raises(InventoryBackupError):
        backup_inventory_database(invalid, tmp_path / 'destination.db')


def test_backup_failure_cleans_temporary_file_and_leaves_no_destination(tmp_path):
    source = tmp_path / 'source.db'
    destination = tmp_path / 'destination.db'
    _make_inventory(source)

    def fail_backup(_source, _destination):
        raise RuntimeError('injected backup failure')

    with pytest.raises(InventoryBackupError, match='failed'):
        backup_inventory_database(source, destination, backup_runner=fail_backup)

    assert not destination.exists()
    assert list(tmp_path.glob('.destination.db.*.tmp')) == []


def test_verify_rejects_mismatched_inventory_without_modifying_databases(tmp_path):
    source = tmp_path / 'source.db'
    destination = tmp_path / 'destination.db'
    _make_inventory(source)
    backup_inventory_database(source, destination)
    source_bytes = source.read_bytes()
    destination_bytes = destination.read_bytes()

    with InventoryStore(destination) as store:
        store.upsert(_record('YZ247/Initial Data/extra.csv'))

    with pytest.raises(InventoryBackupError, match='does not match'):
        verify_inventory_backup(source, destination)

    assert source.read_bytes() == source_bytes
    assert destination.read_bytes() != destination_bytes


def test_backup_does_not_write_source(tmp_path):
    source = tmp_path / 'source.db'
    destination = tmp_path / 'destination.db'
    _make_inventory(source)
    before_bytes = source.read_bytes()
    before_mtime = source.stat().st_mtime_ns

    backup_inventory_database(source, destination)

    assert source.read_bytes() == before_bytes
    assert source.stat().st_mtime_ns == before_mtime
    assert os.access(source, os.R_OK)


def test_verify_rejects_corrupt_destination(tmp_path):
    source = tmp_path / 'source.db'
    destination = tmp_path / 'destination.db'
    _make_inventory(source)
    backup_inventory_database(source, destination)
    with destination.open('r+b') as stream:
        stream.seek(0)
        stream.write(b'corrupt')

    with pytest.raises(InventoryBackupError):
        verify_inventory_backup(source, destination)


def test_backup_source_readability_validation_does_not_create_destination(tmp_path):
    invalid = tmp_path / 'invalid.db'
    invalid.write_text('invalid sqlite database')
    destination = tmp_path / 'destination.db'

    with pytest.raises(InventoryBackupError):
        backup_inventory_database(invalid, destination)

    assert not destination.exists()


def test_windows_rename_fallback_installs_when_hardlink_is_unavailable(
    tmp_path, monkeypatch
):
    source = tmp_path / 'source.db'
    destination = tmp_path / 'destination.db'
    _make_inventory(source)
    real_rename = os.rename
    calls = []

    def unsupported_link(*args, **kwargs):
        raise OSError('hard links are unavailable')

    def tracked_rename(*args, **kwargs):
        calls.append((args, kwargs))
        return real_rename(*args, **kwargs)

    monkeypatch.setattr(inventory_backup.os, 'link', unsupported_link)
    monkeypatch.setattr(inventory_backup.os, 'rename', tracked_rename)
    monkeypatch.setattr(inventory_backup.os, 'name', 'nt')

    metadata = backup_inventory_database(source, destination)

    assert metadata.destination_record_count == EXPECTED_RECORD_COUNT
    assert destination.exists()
    assert calls
    assert list(tmp_path.glob('.destination.db.*.tmp')) == []


def test_destination_race_is_refused_without_overwrite_or_temp_leak(
    tmp_path, monkeypatch
):
    source = tmp_path / 'source.db'
    destination = tmp_path / 'destination.db'
    _make_inventory(source)
    racing_bytes = b'racing destination'

    def racing_link(temporary, target):
        Path(target).write_bytes(racing_bytes)
        raise FileExistsError('destination appeared during install')

    monkeypatch.setattr(inventory_backup.os, 'link', racing_link)

    with pytest.raises(FileExistsError):
        backup_inventory_database(source, destination)

    assert destination.read_bytes() == racing_bytes
    assert list(tmp_path.glob('.destination.db.*.tmp')) == []


def test_backup_destination_can_be_opened_read_only(tmp_path):
    source = tmp_path / 'source.db'
    destination = tmp_path / 'destination.db'
    _make_inventory(source)
    backup_inventory_database(source, destination)

    connection = sqlite3.connect(f'file:{destination.as_posix()}?mode=ro', uri=True)
    try:
        assert (
            connection.execute('SELECT COUNT(*) FROM inventory_records').fetchone()[0]
            == EXPECTED_RECORD_COUNT
        )
    finally:
        connection.close()
