"""Read-only validation of an inventory against a candidate storage root.

The inventory database is the authoritative record set.  This module performs
only metadata reads (SQLite and ``lstat``); it never creates/migrates the
database, reads file contents, follows file symlinks, or changes storage.
"""

from __future__ import annotations

import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path

from lab_data.storage import StorageRoot

__all__ = [
    'RelocationRecordResult',
    'StorageRelocationResult',
    'StorageRelocationRecord',
    'validate_storage_relocation',
]


@dataclass(frozen=True)
class RelocationRecordResult:
    """Deterministic metadata outcome for one present inventory record."""

    relative_path: str
    expected_size_bytes: int
    actual_size_bytes: int | None
    expected_mtime_ns: int
    actual_mtime_ns: int | None
    outcome: str
    detail: str | None = None


# A descriptive alias keeps the public name easy to discover while preserving
# the concise record type used internally and by callers.
StorageRelocationRecord = RelocationRecordResult


@dataclass(frozen=True)
class StorageRelocationResult:
    """Immutable summary of one relocation validation run."""

    inventory_db_path: Path
    candidate_storage_root: Path
    total_inventory_records: int
    present_inventory_records: int
    missing_inventory_records: int
    validated_records: int
    remaining_records: int
    complete: bool
    matched_count: int
    missing_count: int
    non_regular_count: int
    size_mismatch_count: int
    mtime_mismatch_count: int
    unsafe_path_count: int
    error_count: int
    invalid_count: int
    problem_count: int
    omitted_problem_records: int
    records: tuple[RelocationRecordResult, ...]
    blockers: tuple[str, ...]

    @property
    def has_blockers(self) -> bool:
        """Whether this validation found a blocking condition."""

        return bool(self.blockers)


def _absolute_path(value: str | Path, field: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f'{field} must be absolute: {value}')
    return path


def _empty_result(
    db_path: Path,
    root: Path,
    blockers: tuple[str, ...],
) -> StorageRelocationResult:
    return StorageRelocationResult(
        inventory_db_path=db_path,
        candidate_storage_root=root,
        total_inventory_records=0,
        present_inventory_records=0,
        missing_inventory_records=0,
        validated_records=0,
        remaining_records=0,
        complete=False,
        matched_count=0,
        missing_count=0,
        non_regular_count=0,
        size_mismatch_count=0,
        mtime_mismatch_count=0,
        unsafe_path_count=0,
        error_count=0,
        invalid_count=0,
        problem_count=0,
        omitted_problem_records=0,
        records=(),
        blockers=blockers,
    )


def _record_result(  # noqa: PLR0911, PLR0912
    storage_root: StorageRoot,
    relative_path: str,
    expected_size: int,
    expected_mtime: int,
    *,
    compare_mtime: bool,
) -> RelocationRecordResult:
    # Resolve the lexical path first.  ``StorageRoot.resolve`` rejects absolute
    # and traversal paths; the inventory's canonical path is checked again so a
    # malformed database cannot escape the candidate root.
    try:
        lexical = storage_root.resolve(relative_path)
    except (TypeError, ValueError) as error:
        return RelocationRecordResult(
            relative_path,
            expected_size,
            None,
            expected_mtime,
            None,
            'unsafe_path',
            f'candidate path is unsafe: {error}',
        )
    try:
        resolved = lexical.resolve(strict=False)
        resolved.relative_to(storage_root.root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as error:
        return RelocationRecordResult(
            relative_path,
            expected_size,
            None,
            expected_mtime,
            None,
            'unsafe_path',
            f'path resolves outside candidate root or cannot be resolved: {error}',
        )

    # Do not follow symlinks/reparse points.  Check each component so a
    # symlinked directory cannot redirect a regular-looking child elsewhere.
    current = storage_root.root
    components = Path(relative_path.replace('\\', '/')).parts
    for component in components:
        current = current / component
        try:
            if _is_reparse_component(current):
                return RelocationRecordResult(
                    relative_path,
                    expected_size,
                    None,
                    expected_mtime,
                    None,
                    'unsafe_path',
                    'symlink/reparse component is not followed',
                )
        except OSError as error:
            return RelocationRecordResult(
                relative_path,
                expected_size,
                None,
                expected_mtime,
                None,
                'error',
                f'path inspection failed: {error}',
            )

    try:
        metadata = lexical.lstat()
    except FileNotFoundError:
        return RelocationRecordResult(
            relative_path,
            expected_size,
            None,
            expected_mtime,
            None,
            'missing',
        )
    except OSError as error:
        return RelocationRecordResult(
            relative_path,
            expected_size,
            None,
            expected_mtime,
            None,
            'error',
            f'metadata inspection failed: {error}',
        )

    actual_size = int(metadata.st_size)
    actual_mtime = int(metadata.st_mtime_ns)
    if not stat.S_ISREG(metadata.st_mode):
        return RelocationRecordResult(
            relative_path,
            expected_size,
            actual_size,
            expected_mtime,
            actual_mtime,
            'non_regular',
            'candidate is not a regular file',
        )
    size_mismatch = actual_size != expected_size
    mtime_mismatch = compare_mtime and actual_mtime != expected_mtime
    if size_mismatch:
        outcome = 'size_mismatch'
    elif mtime_mismatch:
        outcome = 'mtime_mismatch'
    else:
        outcome = 'matched'
    return RelocationRecordResult(
        relative_path,
        expected_size,
        actual_size,
        expected_mtime,
        actual_mtime,
        outcome,
        'size and/or mtime differs from inventory'
        if size_mismatch or mtime_mismatch
        else None,
    )


def _is_reparse_component(path: Path) -> bool:
    """Return whether ``path`` is a link/reparse point, without following it."""

    if path.is_symlink():
        return True
    is_junction = getattr(path, 'is_junction', None)
    if is_junction is not None and is_junction():
        return True
    # ``st_file_attributes`` is Windows-specific and is exposed by pathlib's
    # lstat result.  FILE_ATTRIBUTE_REPARSE_POINT is 0x400.
    try:
        return bool(path.lstat().st_file_attributes & 0x400)
    except (AttributeError, FileNotFoundError, OSError):
        return False


def validate_storage_relocation(  # noqa: PLR0912, PLR0915
    inventory_db_path: str | Path,
    candidate_storage_root: str | Path,
    *,
    compare_mtime: bool = False,
    max_records: int | None = None,
    max_problem_records: int = 100,
) -> StorageRelocationResult:
    """Validate present inventory records under a candidate root.

    The records are ordered by canonical relative path.  ``max_records``
    provides deterministic bounded coverage; omitted means all present records.
    Missing inventory records are counted separately and are not tested against
    the candidate root.  ``records`` contains only the first
    ``max_problem_records`` problem details; aggregate counters cover every
    selected row even when details are capped.
    """

    if not isinstance(compare_mtime, bool):
        raise TypeError('compare_mtime must be a boolean')
    if max_records is not None and (
        isinstance(max_records, bool)
        or not isinstance(max_records, int)
        or max_records < 0
    ):
        raise ValueError('max_records must be a non-negative integer or None')
    if (
        isinstance(max_problem_records, bool)
        or not isinstance(max_problem_records, int)
        or max_problem_records < 0
    ):
        raise ValueError('max_problem_records must be a non-negative integer')

    db_path = _absolute_path(inventory_db_path, 'inventory_db_path')
    root_path = _absolute_path(candidate_storage_root, 'candidate_storage_root')
    if not db_path.exists() or not db_path.is_file():
        return _empty_result(
            db_path, root_path, (f'inventory database missing: {db_path}',)
        )
    try:
        root_resolved = root_path.resolve(strict=True)
    except OSError as error:
        return _empty_result(
            db_path, root_path, (f'candidate storage root is unreadable: {error}',)
        )
    if not root_resolved.is_dir():
        return _empty_result(
            db_path,
            root_resolved,
            (f'candidate storage root is not a directory: {root_path}',),
        )
    storage_root = StorageRoot(root_resolved)

    blockers: set[str] = set()
    connection: sqlite3.Connection | None = None
    try:
        # URI mode=ro prevents accidental creation, schema migration, or any
        # other write side effect when validating a NAS copy.
        connection = sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True)
        connection.row_factory = sqlite3.Row
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if 'inventory_records' not in tables:
            connection.close()
            return _empty_result(
                db_path,
                root_resolved,
                ('inventory database has no inventory_records table',),
            )
        total = int(
            connection.execute('SELECT COUNT(*) FROM inventory_records').fetchone()[0]
        )
        missing_inventory = int(
            connection.execute(
                'SELECT COUNT(*) FROM inventory_records '
                "WHERE inventory_status = 'missing'"
            ).fetchone()[0]
        )
        present_total = int(
            connection.execute(
                'SELECT COUNT(*) FROM inventory_records '
                "WHERE inventory_status = 'present'"
            ).fetchone()[0]
        )
        unknown_status = tuple(
            str(row[0])
            for row in connection.execute(
                'SELECT DISTINCT inventory_status FROM inventory_records '
                'WHERE inventory_status IS NULL '
                "OR inventory_status NOT IN ('present', 'missing') "
                'ORDER BY inventory_status ASC'
            )
        )
        limit_clause = '' if max_records is None else ' LIMIT ?'
        params: tuple[int, ...] = () if max_records is None else (max_records,)
        row_cursor = connection.execute(
            'SELECT relative_path, size_bytes, mtime_ns, inventory_status '
            "FROM inventory_records WHERE inventory_status = 'present' "
            'ORDER BY relative_path ASC, rowid ASC' + limit_clause,
            params,
        )
    except (OSError, sqlite3.Error) as error:
        if connection is not None:
            connection.close()
        return _empty_result(
            db_path,
            root_resolved,
            (f'inventory database unreadable: {db_path} ({error})',),
        )

    blockers.update(
        f'inventory record has unknown status: {status}' for status in unknown_status
    )
    results: list[RelocationRecordResult] = []
    counts = {
        outcome: 0
        for outcome in (
            'matched',
            'missing',
            'non_regular',
            'size_mismatch',
            'mtime_mismatch',
            'unsafe_path',
            'error',
            'invalid',
        )
    }
    selected_count = 0
    problem_count = 0
    for row in iter(lambda: row_cursor.fetchmany(256), []):
        for item in row:
            selected_count += 1
            try:
                relative = str(item['relative_path'])
                expected_size = int(item['size_bytes'])
                expected_mtime = int(item['mtime_ns'])
                if expected_size < 0 or expected_mtime < 0:
                    raise ValueError('inventory metadata must be non-negative')
                record = _record_result(
                    storage_root,
                    relative,
                    expected_size,
                    expected_mtime,
                    compare_mtime=compare_mtime,
                )
            except (TypeError, ValueError) as error:
                counts['invalid'] += 1
                problem_count += 1
                if len(results) < max_problem_records:
                    results.append(
                        RelocationRecordResult(
                            str(item['relative_path']),
                            0,
                            None,
                            0,
                            None,
                            'invalid',
                            f'invalid inventory record ({error})',
                        )
                    )
                continue
            counts[record.outcome] += 1
            if record.outcome != 'matched':
                problem_count += 1
                if len(results) < max_problem_records:
                    results.append(record)
    row_cursor.close()
    connection.close()
    remaining = present_total - selected_count
    omitted_problem_records = problem_count - len(results)
    for item in results:
        if item.outcome in {'unsafe_path', 'error'}:
            blockers.add(f'{item.relative_path}: {item.outcome}: {item.detail}')
        if item.outcome == 'invalid':
            blockers.add(f'{item.relative_path}: {item.detail}')
        if item.outcome == 'missing':
            blockers.add(f'{item.relative_path}: candidate is missing')
        if item.outcome == 'non_regular':
            blockers.add(f'{item.relative_path}: candidate is not a regular file')
        if item.outcome == 'size_mismatch':
            blockers.add(f'{item.relative_path}: size mismatch')
        if compare_mtime and item.outcome == 'mtime_mismatch':
            blockers.add(f'{item.relative_path}: mtime mismatch')
    if omitted_problem_records:
        blockers.add(
            f'{omitted_problem_records} additional relocation problems omitted '
            'from details'
        )
    return StorageRelocationResult(
        inventory_db_path=db_path,
        candidate_storage_root=root_resolved,
        total_inventory_records=total,
        present_inventory_records=present_total,
        missing_inventory_records=missing_inventory,
        validated_records=selected_count,
        remaining_records=remaining,
        complete=remaining == 0 and counts['invalid'] == 0,
        matched_count=counts['matched'],
        missing_count=counts['missing'],
        non_regular_count=counts['non_regular'],
        size_mismatch_count=counts['size_mismatch'],
        mtime_mismatch_count=counts['mtime_mismatch'],
        unsafe_path_count=counts['unsafe_path'],
        error_count=counts['error'],
        invalid_count=counts['invalid'],
        problem_count=problem_count,
        omitted_problem_records=omitted_problem_records,
        records=tuple(results),
        blockers=tuple(sorted(blockers)),
    )
