"""Read-only, atomic backups for the SQLite inventory store.

Backups use SQLite's online backup API rather than copying database files.  A
source database is opened read-only and validated before the backup begins.
The destination is built in a sibling temporary file, validated, and then
installed without replacing an existing path.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from lab_data.ingestion.inventory_store import SCHEMA_VERSION

__all__ = [
    'InventoryBackupError',
    'InventoryBackupMetadata',
    'backup_inventory_database',
    'verify_inventory_backup',
]

_META_TABLE = 'inventory_meta'
_RECORDS_TABLE = 'inventory_records'
_SESSIONS_TABLE = 'scan_sessions'
_SCHEMA_KEY = 'schema_version'

_REQUIRED_COLUMNS = {
    _META_TABLE: frozenset({'key', 'value'}),
    _RECORDS_TABLE: frozenset(
        {
            'relative_path',
            'size_bytes',
            'mtime_ns',
            'inventory_status',
            'metadata_status',
            'content_hash',
            'parser_version',
            'file_kind',
            'sample_hint',
            'last_seen_session_id',
            'last_seen_generation',
            'created_utc',
            'updated_utc',
        }
    ),
    _SESSIONS_TABLE: frozenset(
        {
            'session_id',
            'generation',
            'status',
            'checkpoint_path',
            'files_seen',
            'files_new',
            'files_unchanged',
            'files_changed',
            'files_restored',
            'files_marked_missing',
            'errors_count',
            'errors_json',
            'created_utc',
            'updated_utc',
        }
    ),
}


class InventoryBackupError(RuntimeError):
    """Raised when an inventory database cannot be safely backed up."""


@dataclass(frozen=True)
class InventoryBackupMetadata:
    """Deterministic facts captured while validating a backup pair."""

    source_schema_version: int
    destination_schema_version: int
    source_record_count: int
    destination_record_count: int
    source_scan_session_count: int
    destination_scan_session_count: int
    source_integrity: str
    destination_integrity: str
    source_size_bytes: int
    destination_size_bytes: int


@dataclass(frozen=True)
class _DatabaseFacts:
    schema_version: int
    record_count: int
    scan_session_count: int
    integrity: str
    size_bytes: int


def _absolute_path(value: str | Path, field_name: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f'{field_name} must be an absolute path')
    return path


def _read_only_uri(path: Path) -> str:
    encoded_path = quote(str(path), safe='/:\\\\')
    return f'file:{encoded_path}?mode=ro'


def _connect_read_only(path: Path) -> sqlite3.Connection:
    try:
        connection = sqlite3.connect(_read_only_uri(path), uri=True)
        connection.execute('PRAGMA query_only = ON')
        return connection
    except (sqlite3.Error, OSError) as error:
        raise InventoryBackupError(f'cannot open inventory database: {path}') from error


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    rows = connection.execute(f'PRAGMA table_info({table})').fetchall()
    return {str(row[1]) for row in rows}


def _database_facts(path: Path) -> _DatabaseFacts:  # noqa: PLR0912
    if not path.exists():
        raise FileNotFoundError(path)
    if not path.is_file():
        raise InventoryBackupError(f'inventory database is not a file: {path}')

    try:
        connection = _connect_read_only(path)
    except sqlite3.Error as error:
        raise InventoryBackupError(f'invalid inventory database: {path}') from error

    try:
        integrity_rows = connection.execute('PRAGMA integrity_check').fetchall()
        if integrity_rows != [('ok',)]:
            details = ', '.join(str(row[0]) for row in integrity_rows)
            raise InventoryBackupError(
                f'inventory integrity check failed for {path}: {details}'
            )

        for table, required_columns in _REQUIRED_COLUMNS.items():
            if not _table_exists(connection, table):
                raise InventoryBackupError(
                    f'inventory schema is missing table {table!r}: {path}'
                )
            if not required_columns.issubset(_table_columns(connection, table)):
                raise InventoryBackupError(
                    f'inventory schema is missing columns for {table!r}: {path}'
                )

        row = connection.execute(
            f'SELECT value FROM {_META_TABLE} WHERE key = ?', (_SCHEMA_KEY,)
        ).fetchone()
        if row is None:
            raise InventoryBackupError(f'inventory schema version is missing: {path}')
        try:
            schema_version = int(row[0])
        except (TypeError, ValueError) as error:
            raise InventoryBackupError(
                f'inventory schema version is invalid: {path}'
            ) from error
        if schema_version != SCHEMA_VERSION:
            raise InventoryBackupError(
                f'unsupported inventory schema version: {schema_version}'
            )

        record_count = int(
            connection.execute(f'SELECT COUNT(*) FROM {_RECORDS_TABLE}').fetchone()[0]
        )
        scan_session_count = int(
            connection.execute(f'SELECT COUNT(*) FROM {_SESSIONS_TABLE}').fetchone()[0]
        )
        return _DatabaseFacts(
            schema_version=schema_version,
            record_count=record_count,
            scan_session_count=scan_session_count,
            integrity='ok',
            size_bytes=path.stat().st_size,
        )
    except InventoryBackupError:
        raise
    except (sqlite3.Error, OSError) as error:
        raise InventoryBackupError(f'cannot read inventory database: {path}') from error
    finally:
        connection.close()


def _run_online_backup(
    source: sqlite3.Connection, destination: sqlite3.Connection
) -> None:
    source.backup(destination)
    destination.commit()


def _temporary_sibling(destination: Path) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f'.{destination.name}.', suffix='.tmp', dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    temporary.unlink()
    return temporary


def _install_without_replace(temporary: Path, destination: Path) -> None:
    """Install a sibling file atomically while refusing an existing target."""

    try:
        os.link(temporary, destination)
    except FileExistsError as error:
        raise FileExistsError(
            f'backup destination already exists: {destination}'
        ) from error
    except OSError as error:
        if destination.exists():
            raise FileExistsError(
                f'backup destination already exists: {destination}'
            ) from error
        if os.name == 'nt':
            try:
                # Windows os.rename is atomic and refuses an existing target;
                # never use this fallback on POSIX, where rename can replace.
                os.rename(temporary, destination)
            except FileExistsError as rename_error:
                raise FileExistsError(
                    f'backup destination already exists: {destination}'
                ) from rename_error
            except OSError as rename_error:
                if destination.exists():
                    raise FileExistsError(
                        f'backup destination already exists: {destination}'
                    ) from rename_error
                raise InventoryBackupError(
                    f'cannot atomically install backup at {destination}'
                ) from rename_error
            return
        raise InventoryBackupError(
            f'cannot atomically install backup at {destination}'
        ) from error
    finally:
        if destination.exists() and temporary.exists():
            temporary.unlink()


def _metadata(
    source: _DatabaseFacts, destination: _DatabaseFacts
) -> InventoryBackupMetadata:
    return InventoryBackupMetadata(
        source_schema_version=source.schema_version,
        destination_schema_version=destination.schema_version,
        source_record_count=source.record_count,
        destination_record_count=destination.record_count,
        source_scan_session_count=source.scan_session_count,
        destination_scan_session_count=destination.scan_session_count,
        source_integrity=source.integrity,
        destination_integrity=destination.integrity,
        source_size_bytes=source.size_bytes,
        destination_size_bytes=destination.size_bytes,
    )


def verify_inventory_backup(
    source_db: str | Path, destination: str | Path
) -> InventoryBackupMetadata:
    """Verify two inventory databases without modifying either one."""

    source_path = _absolute_path(source_db, 'source_db')
    destination_path = _absolute_path(destination, 'destination')
    source_facts = _database_facts(source_path)
    destination_facts = _database_facts(destination_path)
    if (
        source_facts.schema_version != destination_facts.schema_version
        or source_facts.record_count != destination_facts.record_count
        or source_facts.scan_session_count != destination_facts.scan_session_count
        or source_facts.integrity != destination_facts.integrity
    ):
        raise InventoryBackupError('inventory backup does not match its source')
    return _metadata(source_facts, destination_facts)


def backup_inventory_database(
    source_db: str | Path,
    destination: str | Path,
    *,
    backup_runner: Callable[[sqlite3.Connection, sqlite3.Connection], None]
    | None = None,
) -> InventoryBackupMetadata:
    """Create and verify a no-clobber online backup of an inventory database."""

    source_path = _absolute_path(source_db, 'source_db')
    destination_path = _absolute_path(destination, 'destination')
    if destination_path.exists():
        raise FileExistsError(f'backup destination already exists: {destination_path}')
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    if not destination_path.parent.is_dir():
        raise FileNotFoundError(
            f'backup destination parent does not exist: {destination_path.parent}'
        )

    source_facts = _database_facts(source_path)
    temporary = _temporary_sibling(destination_path)
    runner = backup_runner or _run_online_backup
    try:
        source_connection = _connect_read_only(source_path)
        try:
            destination_connection = sqlite3.connect(str(temporary))
            try:
                runner(source_connection, destination_connection)
            finally:
                destination_connection.close()
        finally:
            source_connection.close()

        destination_facts = _database_facts(temporary)
        if (
            source_facts.schema_version != destination_facts.schema_version
            or source_facts.record_count != destination_facts.record_count
            or source_facts.scan_session_count != destination_facts.scan_session_count
            or source_facts.integrity != destination_facts.integrity
        ):
            raise InventoryBackupError('inventory backup does not match its source')
        _install_without_replace(temporary, destination_path)
        return _metadata(source_facts, destination_facts)
    except InventoryBackupError:
        raise
    except FileExistsError:
        raise
    except Exception as error:
        raise InventoryBackupError('inventory backup failed') from error
    finally:
        if temporary.exists():
            temporary.unlink()
