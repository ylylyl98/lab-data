"""Versioned SQLite inventory store with persisted scan sessions.

This module records file inventory metadata (size, modification time, status,
and optional content hash and parser metadata) without scanning the
filesystem, hashing files, or contacting NOMAD. It is storage-agnostic:
canonical relative paths are validated and normalized through
:class:`lab_data.storage.StorageRoot`, and the database path is always supplied
by the caller.

Schema version 2 adds a persisted scan-session model plus per-record
last-seen session/generation columns so a resumable scan can reconcile missing
files from persisted state instead of an in-memory set of every path.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from lab_data.storage import StorageRoot

__all__ = [
    'InventoryRecord',
    'InventoryStore',
    'ScanSession',
    'SCHEMA_VERSION',
    'INVENTORY_PRESENT',
    'INVENTORY_MISSING',
    'METADATA_PENDING',
    'METADATA_INDEXED',
    'METADATA_STALE',
    'METADATA_FAILED',
    'INVENTORY_STATUSES',
    'METADATA_STATUSES',
    'SESSION_ACTIVE',
    'SESSION_COMPLETED',
    'SESSION_FAILED',
    'SESSION_STATUSES',
]

SCHEMA_VERSION = 2

INVENTORY_PRESENT = 'present'
INVENTORY_MISSING = 'missing'

METADATA_PENDING = 'pending'
METADATA_INDEXED = 'indexed'
METADATA_STALE = 'stale'
METADATA_FAILED = 'failed'

INVENTORY_STATUSES = frozenset({INVENTORY_PRESENT, INVENTORY_MISSING})
METADATA_STATUSES = frozenset(
    {METADATA_PENDING, METADATA_INDEXED, METADATA_STALE, METADATA_FAILED}
)

SESSION_ACTIVE = 'active'
SESSION_COMPLETED = 'completed'
SESSION_FAILED = 'failed'
SESSION_STATUSES = frozenset({SESSION_ACTIVE, SESSION_COMPLETED, SESSION_FAILED})

_META_TABLE = 'inventory_meta'
_RECORDS_TABLE = 'inventory_records'
_SESSIONS_TABLE = 'scan_sessions'
_SCHEMA_KEY = 'schema_version'
_UNSET = object()
_CONTROL_CHARACTER_LIMIT = 32
_DELETE_CHARACTER = 127

_RECORDS_DDL_V2 = f"""
CREATE TABLE IF NOT EXISTS {_RECORDS_TABLE} (
    relative_path TEXT PRIMARY KEY,
    size_bytes INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    inventory_status TEXT NOT NULL,
    metadata_status TEXT NOT NULL,
    content_hash TEXT,
    parser_version TEXT,
    file_kind TEXT,
    sample_hint TEXT,
    last_seen_session_id TEXT,
    last_seen_generation INTEGER,
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL
)
"""

_SESSIONS_DDL = f"""
CREATE TABLE IF NOT EXISTS {_SESSIONS_TABLE} (
    session_id TEXT PRIMARY KEY,
    generation INTEGER NOT NULL,
    status TEXT NOT NULL,
    checkpoint_path TEXT,
    files_seen INTEGER NOT NULL,
    files_new INTEGER NOT NULL,
    files_unchanged INTEGER NOT NULL,
    files_changed INTEGER NOT NULL,
    files_restored INTEGER NOT NULL,
    files_marked_missing INTEGER NOT NULL,
    errors_count INTEGER NOT NULL,
    errors_json TEXT NOT NULL,
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL
)
"""


def _validation_root() -> Path:
    """Return an absolute throwaway root used only for path normalization."""

    return Path(os.path.abspath(os.sep))


def _canonical_relative_path(value: object) -> str:
    """Validate and normalize a canonical relative path using StorageRoot."""

    if not isinstance(value, str) or not value:
        raise ValueError('relative_path must be a non-empty string')
    root = StorageRoot(_validation_root())
    resolved = root.resolve(value)
    return root.canonicalize(resolved)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _require_non_negative_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f'{field_name} must be a non-negative integer')


def _require_optional_string(value: object, field_name: str) -> None:
    if value is not None and (not isinstance(value, str) or not value):
        raise ValueError(f'{field_name} must be a non-empty string or None')


def _require_parser_version(value: object) -> None:
    """Validate caller-supplied parser provenance without normalizing it."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError('parser_version must be a non-empty safe string')
    if any(
        ord(character) < _CONTROL_CHARACTER_LIMIT or ord(character) == _DELETE_CHARACTER
        for character in value
    ):
        raise ValueError('parser_version must be a non-empty safe string')


def _require_session_id(value: object) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError('session_id must be a non-empty string')


def _require_generation(value: object) -> None:
    _require_non_negative_int(value, 'generation')


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row['name'] for row in connection.execute(f'PRAGMA table_info({table})')}


@dataclass(frozen=True)
class InventoryRecord:
    """Immutable file inventory record.

    ``relative_path`` is validated and canonicalized to forward-slash form.
    ``content_hash``, ``parser_version``, ``file_kind``, and ``sample_hint``
    are optional metadata. ``created_utc`` and ``updated_utc`` are managed by
    :class:`InventoryStore`.

    ``last_seen_session_id`` and ``last_seen_generation`` are populated by the
    scan-session lifecycle rather than by ordinary callers. They are included
    here so read-back records expose the persisted reconciliation state.
    """

    relative_path: str
    size_bytes: int
    mtime_ns: int
    inventory_status: str
    metadata_status: str
    content_hash: str | None = None
    parser_version: str | None = None
    file_kind: str | None = None
    sample_hint: str | None = None
    last_seen_session_id: str | None = None
    last_seen_generation: int | None = None
    created_utc: str | None = None
    updated_utc: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, 'relative_path', _canonical_relative_path(self.relative_path)
        )
        _require_non_negative_int(self.size_bytes, 'size_bytes')
        _require_non_negative_int(self.mtime_ns, 'mtime_ns')
        if self.inventory_status not in INVENTORY_STATUSES:
            raise ValueError(f'invalid inventory status: {self.inventory_status!r}')
        if self.metadata_status not in METADATA_STATUSES:
            raise ValueError(f'invalid metadata status: {self.metadata_status!r}')
        _require_optional_string(self.content_hash, 'content_hash')
        _require_optional_string(self.parser_version, 'parser_version')
        _require_optional_string(self.file_kind, 'file_kind')
        _require_optional_string(self.sample_hint, 'sample_hint')
        _require_optional_string(self.last_seen_session_id, 'last_seen_session_id')
        if self.last_seen_generation is not None:
            _require_non_negative_int(self.last_seen_generation, 'last_seen_generation')
        _require_optional_string(self.created_utc, 'created_utc')
        _require_optional_string(self.updated_utc, 'updated_utc')


@dataclass(frozen=True)
class ScanSession:
    """Immutable snapshot of one persisted scan session."""

    session_id: str
    generation: int
    status: str
    checkpoint_path: str | None
    files_seen: int
    files_new: int
    files_unchanged: int
    files_changed: int
    files_restored: int
    files_marked_missing: int
    errors: tuple[str, ...]
    created_utc: str
    updated_utc: str


def _record_from_row(row: sqlite3.Row) -> InventoryRecord:
    return InventoryRecord(
        relative_path=row['relative_path'],
        size_bytes=row['size_bytes'],
        mtime_ns=row['mtime_ns'],
        inventory_status=row['inventory_status'],
        metadata_status=row['metadata_status'],
        content_hash=row['content_hash'],
        parser_version=row['parser_version'],
        file_kind=row['file_kind'],
        sample_hint=row['sample_hint'],
        last_seen_session_id=row['last_seen_session_id'],
        last_seen_generation=row['last_seen_generation'],
        created_utc=row['created_utc'],
        updated_utc=row['updated_utc'],
    )


def _session_from_row(row: sqlite3.Row) -> ScanSession:
    try:
        errors = tuple(json.loads(row['errors_json']))
    except (TypeError, ValueError):
        errors = ()
    return ScanSession(
        session_id=row['session_id'],
        generation=row['generation'],
        status=row['status'],
        checkpoint_path=row['checkpoint_path'],
        files_seen=row['files_seen'],
        files_new=row['files_new'],
        files_unchanged=row['files_unchanged'],
        files_changed=row['files_changed'],
        files_restored=row['files_restored'],
        files_marked_missing=row['files_marked_missing'],
        errors=errors,
        created_utc=row['created_utc'],
        updated_utc=row['updated_utc'],
    )


class InventoryStore:
    """Versioned SQLite inventory with a caller-supplied database path."""

    def __init__(self, db_path: str | Path, *, now: Callable[[], str] | None = None):
        self._path = Path(db_path)
        self._now = now if now is not None else _utc_now
        self._conn: sqlite3.Connection | None = None

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            connection = sqlite3.connect(str(self._path))
            connection.row_factory = sqlite3.Row
            self._initialize_schema(connection)
            self._conn = connection
        return self._conn

    def _initialize_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            f'CREATE TABLE IF NOT EXISTS {_META_TABLE} '
            '(key TEXT PRIMARY KEY, value TEXT NOT NULL)'
        )
        row = connection.execute(
            f'SELECT value FROM {_META_TABLE} WHERE key = ?',
            (_SCHEMA_KEY,),
        ).fetchone()

        if row is None:
            connection.execute(
                f'INSERT INTO {_META_TABLE} (key, value) VALUES (?, ?)',
                (_SCHEMA_KEY, str(SCHEMA_VERSION)),
            )
            connection.execute(_RECORDS_DDL_V2)
            connection.execute(_SESSIONS_DDL)
            connection.commit()
            return

        try:
            version = int(row['value'])
        except (TypeError, ValueError) as error:
            raise ValueError('inventory schema version is not an integer') from error

        if version == 1:
            self._migrate_v1_to_v2(connection)
            return
        if version != SCHEMA_VERSION:
            raise ValueError(f'unsupported inventory schema version: {version}')

        self._ensure_records_v2(connection)
        connection.execute(_SESSIONS_DDL)
        connection.commit()

    def _ensure_records_v2(self, connection: sqlite3.Connection) -> None:
        if not _table_exists(connection, _RECORDS_TABLE):
            connection.execute(_RECORDS_DDL_V2)
            return
        columns = _table_columns(connection, _RECORDS_TABLE)
        if 'last_seen_session_id' not in columns:
            connection.execute(
                f'ALTER TABLE {_RECORDS_TABLE} ADD COLUMN last_seen_session_id TEXT'
            )
        if 'last_seen_generation' not in columns:
            connection.execute(
                f'ALTER TABLE {_RECORDS_TABLE} ADD COLUMN last_seen_generation INTEGER'
            )

    def _migrate_v1_to_v2(self, connection: sqlite3.Connection) -> None:
        self._ensure_records_v2(connection)
        connection.execute(_SESSIONS_DDL)
        connection.execute(
            f'UPDATE {_META_TABLE} SET value = ? WHERE key = ?',
            (str(SCHEMA_VERSION), _SCHEMA_KEY),
        )
        connection.commit()

    def __enter__(self) -> InventoryStore:
        self._connection()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        self.close()
        return False

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def upsert(self, record: InventoryRecord) -> InventoryRecord:
        """Insert or replace a record while preserving created and last-seen state."""

        if not isinstance(record, InventoryRecord):
            raise TypeError('record must be an InventoryRecord')
        now = self._now()
        connection = self._connection()
        connection.execute(
            f"""
            INSERT INTO {_RECORDS_TABLE} (
                relative_path, size_bytes, mtime_ns, inventory_status,
                metadata_status, content_hash, parser_version, file_kind,
                sample_hint, created_utc, updated_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(relative_path) DO UPDATE SET
                size_bytes = excluded.size_bytes,
                mtime_ns = excluded.mtime_ns,
                inventory_status = excluded.inventory_status,
                metadata_status = excluded.metadata_status,
                content_hash = excluded.content_hash,
                parser_version = excluded.parser_version,
                file_kind = excluded.file_kind,
                sample_hint = excluded.sample_hint,
                updated_utc = excluded.updated_utc
            """,
            (
                record.relative_path,
                record.size_bytes,
                record.mtime_ns,
                record.inventory_status,
                record.metadata_status,
                record.content_hash,
                record.parser_version,
                record.file_kind,
                record.sample_hint,
                now,
                now,
            ),
        )
        connection.commit()
        stored = self.get(record.relative_path)
        if stored is None:
            raise RuntimeError('upsert did not produce a stored record')
        return stored

    def upsert_seen(
        self, record: InventoryRecord, session_id: str, generation: int
    ) -> InventoryRecord:
        """Upsert a record and mark it seen by a scan session."""

        if not isinstance(record, InventoryRecord):
            raise TypeError('record must be an InventoryRecord')
        _require_session_id(session_id)
        _require_generation(generation)
        now = self._now()
        connection = self._connection()
        connection.execute(
            f"""
            INSERT INTO {_RECORDS_TABLE} (
                relative_path, size_bytes, mtime_ns, inventory_status,
                metadata_status, content_hash, parser_version, file_kind,
                sample_hint, last_seen_session_id, last_seen_generation,
                created_utc, updated_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(relative_path) DO UPDATE SET
                size_bytes = excluded.size_bytes,
                mtime_ns = excluded.mtime_ns,
                inventory_status = excluded.inventory_status,
                metadata_status = excluded.metadata_status,
                content_hash = excluded.content_hash,
                parser_version = excluded.parser_version,
                file_kind = excluded.file_kind,
                sample_hint = excluded.sample_hint,
                last_seen_session_id = excluded.last_seen_session_id,
                last_seen_generation = excluded.last_seen_generation,
                updated_utc = excluded.updated_utc
            """,
            (
                record.relative_path,
                record.size_bytes,
                record.mtime_ns,
                record.inventory_status,
                record.metadata_status,
                record.content_hash,
                record.parser_version,
                record.file_kind,
                record.sample_hint,
                session_id,
                generation,
                now,
                now,
            ),
        )
        connection.commit()
        stored = self.get(record.relative_path)
        if stored is None:
            raise RuntimeError('upsert_seen did not produce a stored record')
        return stored

    def mark_seen(
        self, relative_path: str | Path, session_id: str, generation: int
    ) -> InventoryRecord:
        """Mark an existing record seen without changing its other fields."""

        _require_session_id(session_id)
        _require_generation(generation)
        canonical = _canonical_relative_path(relative_path)
        now = self._now()
        connection = self._connection()
        cursor = connection.execute(
            f'UPDATE {_RECORDS_TABLE} SET last_seen_session_id = ?, '
            'last_seen_generation = ?, updated_utc = ? WHERE relative_path = ?',
            (session_id, generation, now, canonical),
        )
        if cursor.rowcount == 0:
            raise KeyError(f'inventory record not found: {relative_path}')
        connection.commit()
        stored = self.get(canonical)
        if stored is None:
            raise RuntimeError('mark_seen did not produce a stored record')
        return stored

    def get(self, relative_path: str | Path) -> InventoryRecord | None:
        canonical = _canonical_relative_path(relative_path)
        row = (
            self._connection()
            .execute(
                f'SELECT * FROM {_RECORDS_TABLE} WHERE relative_path = ?',
                (canonical,),
            )
            .fetchone()
        )
        return _record_from_row(row) if row is not None else None

    def list_records(self) -> tuple[InventoryRecord, ...]:
        rows = (
            self._connection()
            .execute(f'SELECT * FROM {_RECORDS_TABLE} ORDER BY relative_path ASC')
            .fetchall()
        )
        return tuple(_record_from_row(row) for row in rows)

    def list_for_metadata_indexing(
        self, *, include_failed: bool = False
    ) -> tuple[InventoryRecord, ...]:
        """Return present records that still need metadata indexing.

        By default this selects only ``pending`` and ``stale`` records and
        excludes ``indexed``, ``missing``, and ``failed`` records. Passing
        ``include_failed=True`` explicitly opts into retrying failed records
        as well. ``indexed`` and ``missing`` records are always excluded.
        """

        if not isinstance(include_failed, bool):
            raise TypeError('include_failed must be a boolean')
        statuses = (METADATA_PENDING, METADATA_STALE)
        if include_failed:
            statuses = (METADATA_PENDING, METADATA_STALE, METADATA_FAILED)
        placeholders = ', '.join('?' for _ in statuses)
        rows = (
            self._connection()
            .execute(
                f'SELECT * FROM {_RECORDS_TABLE} '
                'WHERE inventory_status = ? AND metadata_status IN '
                f'({placeholders}) ORDER BY relative_path ASC',
                (INVENTORY_PRESENT, *statuses),
            )
            .fetchall()
        )
        return tuple(_record_from_row(row) for row in rows)

    def count(self) -> int:
        row = (
            self._connection()
            .execute(f'SELECT COUNT(*) AS count FROM {_RECORDS_TABLE}')
            .fetchone()
        )
        return int(row['count'])

    def update_metadata_status(
        self, relative_path: str | Path, metadata_status: str
    ) -> InventoryRecord:
        if metadata_status not in METADATA_STATUSES:
            raise ValueError(f'invalid metadata status: {metadata_status!r}')
        return self._update_status(
            relative_path,
            assignment='metadata_status = ?',
            value=metadata_status,
        )

    def update_metadata_status_and_parser_version(
        self,
        relative_path: str | Path,
        metadata_status: str,
        parser_version: str | None | object = _UNSET,
    ) -> InventoryRecord:
        """Atomically update metadata status and optional parser provenance.

        Omitting ``parser_version`` preserves the existing value. Passing
        ``None`` clears it; passing a string requires a non-empty safe value.
        No other inventory fields are modified.
        """

        if metadata_status not in METADATA_STATUSES:
            raise ValueError(f'invalid metadata status: {metadata_status!r}')
        if parser_version is _UNSET:
            return self.update_metadata_status(relative_path, metadata_status)
        if parser_version is not None:
            _require_parser_version(parser_version)

        canonical = _canonical_relative_path(relative_path)
        now = self._now()
        connection = self._connection()
        cursor = connection.execute(
            f'UPDATE {_RECORDS_TABLE} SET metadata_status = ?, '
            'parser_version = ?, updated_utc = ? WHERE relative_path = ?',
            (metadata_status, parser_version, now, canonical),
        )
        if cursor.rowcount == 0:
            raise KeyError(f'inventory record not found: {relative_path}')
        connection.commit()
        stored = self.get(canonical)
        if stored is None:
            raise RuntimeError(
                'metadata status/version update did not produce a record'
            )
        return stored

    def mark_missing(self, relative_path: str | Path) -> InventoryRecord:
        """Mark an existing record missing without deleting it."""

        return self._update_status(
            relative_path,
            assignment='inventory_status = ?',
            value=INVENTORY_MISSING,
        )

    def mark_present(self, relative_path: str | Path) -> InventoryRecord:
        """Restore a missing record to present."""

        return self._update_status(
            relative_path,
            assignment='inventory_status = ?',
            value=INVENTORY_PRESENT,
        )

    def _update_status(
        self, relative_path: str | Path, *, assignment: str, value: str
    ) -> InventoryRecord:
        canonical = _canonical_relative_path(relative_path)
        now = self._now()
        connection = self._connection()
        cursor = connection.execute(
            f'UPDATE {_RECORDS_TABLE} SET {assignment}, updated_utc = ? '
            'WHERE relative_path = ?',
            (value, now, canonical),
        )
        if cursor.rowcount == 0:
            raise KeyError(f'inventory record not found: {relative_path}')
        connection.commit()
        stored = self.get(canonical)
        if stored is None:
            raise RuntimeError('status update did not produce a stored record')
        return stored

    def begin_scan(self, session_id: str | None = None) -> ScanSession:
        """Start a new scan session with a fresh generation."""

        if session_id is not None:
            _require_session_id(session_id)
        if self.resume_scan() is not None:
            raise ValueError('an active scan session already exists')
        generation = self._next_generation()
        identifier = session_id or uuid.uuid4().hex
        now = self._now()
        connection = self._connection()
        connection.execute(
            f"""
            INSERT INTO {_SESSIONS_TABLE} (
                session_id, generation, status, checkpoint_path, files_seen,
                files_new, files_unchanged, files_changed, files_restored,
                files_marked_missing, errors_count, errors_json, created_utc,
                updated_utc
            ) VALUES (?, ?, ?, NULL, 0, 0, 0, 0, 0, 0, 0, '[]', ?, ?)
            """,
            (identifier, generation, SESSION_ACTIVE, now, now),
        )
        connection.commit()
        session = self.get_session(identifier)
        if session is None:
            raise RuntimeError('begin_scan did not produce a session')
        return session

    def _next_generation(self) -> int:
        row = (
            self._connection()
            .execute(
                f'SELECT COALESCE(MAX(generation), 0) AS generation '
                f'FROM {_SESSIONS_TABLE}'
            )
            .fetchone()
        )
        return int(row['generation']) + 1

    def resume_scan(self) -> ScanSession | None:
        """Return the active session, if one exists."""

        row = (
            self._connection()
            .execute(
                f'SELECT * FROM {_SESSIONS_TABLE} WHERE status = ? '
                'ORDER BY created_utc ASC LIMIT 1',
                (SESSION_ACTIVE,),
            )
            .fetchone()
        )
        return _session_from_row(row) if row is not None else None

    def get_session(self, session_id: str) -> ScanSession | None:
        _require_session_id(session_id)
        row = (
            self._connection()
            .execute(
                f'SELECT * FROM {_SESSIONS_TABLE} WHERE session_id = ?',
                (session_id,),
            )
            .fetchone()
        )
        return _session_from_row(row) if row is not None else None

    def checkpoint_scan(  # noqa: PLR0913
        self,
        session_id: str,
        *,
        checkpoint_path: str | None = None,
        files_seen: int | None = None,
        files_new: int | None = None,
        files_unchanged: int | None = None,
        files_changed: int | None = None,
        files_restored: int | None = None,
    ) -> ScanSession:
        """Persist counters and checkpoint for the active session."""

        self._require_active_session(session_id)
        return self._update_session(
            session_id,
            checkpoint_path=checkpoint_path,
            files_seen=files_seen,
            files_new=files_new,
            files_unchanged=files_unchanged,
            files_changed=files_changed,
            files_restored=files_restored,
        )

    def complete_scan(  # noqa: PLR0913
        self,
        session_id: str,
        *,
        files_seen: int | None = None,
        files_new: int | None = None,
        files_unchanged: int | None = None,
        files_changed: int | None = None,
        files_restored: int | None = None,
    ) -> ScanSession:
        """Finalize a successful session and reconcile unseen present records."""

        session = self._require_active_session(session_id)
        self._update_session(
            session_id,
            files_seen=files_seen,
            files_new=files_new,
            files_unchanged=files_unchanged,
            files_changed=files_changed,
            files_restored=files_restored,
        )
        now = self._now()
        connection = self._connection()
        cursor = connection.execute(
            f'UPDATE {_RECORDS_TABLE} SET inventory_status = ?, updated_utc = ? '
            'WHERE inventory_status = ? '
            'AND (last_seen_generation IS NULL OR last_seen_generation != ?)',
            (INVENTORY_MISSING, now, INVENTORY_PRESENT, session.generation),
        )
        connection.commit()
        return self._update_session(
            session_id,
            status=SESSION_COMPLETED,
            files_marked_missing=cursor.rowcount,
        )

    def fail_scan(  # noqa: PLR0913
        self,
        session_id: str,
        *,
        errors: tuple[str, ...] = (),
        files_seen: int | None = None,
        files_new: int | None = None,
        files_unchanged: int | None = None,
        files_changed: int | None = None,
        files_restored: int | None = None,
    ) -> ScanSession:
        """Mark a session failed without reconciling missing records."""

        self._require_active_session(session_id)
        return self._update_session(
            session_id,
            status=SESSION_FAILED,
            errors=errors,
            files_seen=files_seen,
            files_new=files_new,
            files_unchanged=files_unchanged,
            files_changed=files_changed,
            files_restored=files_restored,
        )

    def _require_active_session(self, session_id: str) -> ScanSession:
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(f'scan session not found: {session_id}')
        if session.status != SESSION_ACTIVE:
            raise ValueError(f'scan session is not active: {session_id}')
        return session

    def _update_session(  # noqa: PLR0913
        self,
        session_id: str,
        *,
        status: str | None = None,
        checkpoint_path: object = _UNSET,
        files_seen: int | None = None,
        files_new: int | None = None,
        files_unchanged: int | None = None,
        files_changed: int | None = None,
        files_restored: int | None = None,
        files_marked_missing: int | None = None,
        errors: tuple[str, ...] | None = None,
    ) -> ScanSession:
        sets: list[str] = []
        params: list[object] = []

        if status is not None:
            if status not in SESSION_STATUSES:
                raise ValueError(f'invalid session status: {status!r}')
            sets.append('status = ?')
            params.append(status)
        if checkpoint_path is not _UNSET:
            if checkpoint_path is not None:
                _require_optional_string(checkpoint_path, 'checkpoint_path')
            sets.append('checkpoint_path = ?')
            params.append(checkpoint_path)

        counters = (
            ('files_seen', files_seen),
            ('files_new', files_new),
            ('files_unchanged', files_unchanged),
            ('files_changed', files_changed),
            ('files_restored', files_restored),
            ('files_marked_missing', files_marked_missing),
        )
        for field, value in counters:
            if value is not None:
                _require_non_negative_int(value, field)
                sets.append(f'{field} = ?')
                params.append(value)

        if errors is not None:
            normalized = tuple(sorted(set(errors)))
            sets.append('errors_json = ?')
            params.append(json.dumps(normalized, sort_keys=True))
            sets.append('errors_count = ?')
            params.append(len(normalized))

        if not sets:
            session = self.get_session(session_id)
            if session is None:
                raise KeyError(f'scan session not found: {session_id}')
            return session

        sets.append('updated_utc = ?')
        params.append(self._now())
        params.append(session_id)
        connection = self._connection()
        cursor = connection.execute(
            f'UPDATE {_SESSIONS_TABLE} SET {", ".join(sets)} WHERE session_id = ?',
            params,
        )
        if cursor.rowcount == 0:
            raise KeyError(f'scan session not found: {session_id}')
        connection.commit()
        session = self.get_session(session_id)
        if session is None:
            raise RuntimeError('session update did not produce a session')
        return session
