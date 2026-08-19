"""Filesystem inventory scan without content reads or network access.

The scanner recursively enumerates regular files under a caller-supplied
:class:`lab_data.storage.StorageRoot`, derives their canonical relative paths,
collects only ``st_size`` and ``st_mtime_ns``, and reconciles those values
against a caller-supplied :class:`lab_data.ingestion.inventory_store.InventoryStore`.

The scan never opens, reads, or hashes file contents, and it never contacts
NOMAD or any network service. Symlinked directories and junctions are not
followed. Symlinked files are treated conservatively: they are skipped and
reported as a deterministic error because their target may escape the storage
root.

Scans are resumable. A bounded call processes at most ``max_files`` entries and
persists a checkpoint plus cumulative counters in the store's active scan
session. Only a fully completed, error-free traversal marks previously-present
unseen records missing.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from lab_data.ingestion.inventory_store import (
    INVENTORY_MISSING,
    INVENTORY_PRESENT,
    METADATA_PENDING,
    METADATA_STALE,
    SESSION_ACTIVE,
    SESSION_COMPLETED,
    SESSION_FAILED,
    InventoryRecord,
    InventoryStore,
)
from lab_data.storage import StorageRoot

__all__ = ['InventoryScanResult', 'scan_inventory', 'scan_inventory_batch']


@dataclass(frozen=True)
class InventoryScanResult:
    """Immutable, deterministic outcome of one inventory scan."""

    scan_complete: bool
    seen: int
    new: int
    unchanged: int
    changed: int
    restored: int
    marked_missing: int
    errors: tuple[str, ...]
    session_id: str | None = None
    generation: int | None = None
    status: str | None = None
    remaining: int = 0

    @property
    def error_count(self) -> int:
        """Return the number of deterministic traversal or stat errors."""

        return len(self.errors)


@dataclass(frozen=True)
class _FileEntry:
    canonical: str
    path: Path
    size_bytes: int
    mtime_ns: int


def _traversal_error(errors: list[str], error: OSError) -> None:
    filename = getattr(error, 'filename', None) or '<storage root>'
    errors.append(f'traversal error: {filename}: {error}')


def _walk_files(root: Path, errors: list[str]):
    """Yield file paths in deterministic directory order without following links."""

    def on_error(error: OSError) -> None:
        _traversal_error(errors, error)

    for dirpath, dirnames, filenames in os.walk(
        root, topdown=True, followlinks=False, onerror=on_error
    ):
        dirnames.sort()
        filenames.sort()
        for filename in filenames:
            yield Path(dirpath) / filename


def _error_message(prefix: str, path: object, error: Exception) -> str:
    return f'{prefix}: {path}: {error}'


def _iter_file_entries(storage: StorageRoot, errors: list[str]):
    """Stream regular-file entries lazily in deterministic walk order.

    Entries are produced one at a time without materializing the full traversal
    as a list. Directory symlinks and junctions are not followed; a file
    symlink is skipped and reported as a deterministic error.
    """

    for path in _walk_files(storage.root, errors):
        try:
            metadata = path.lstat()
        except OSError as error:
            errors.append(_error_message('stat error', path, error))
            continue

        if stat.S_ISLNK(metadata.st_mode):
            errors.append(f'symlinked file not followed: {path}')
            continue
        if not stat.S_ISREG(metadata.st_mode):
            continue

        try:
            canonical = storage.canonicalize(path)
        except ValueError as error:
            errors.append(_error_message('canonical path error', path, error))
            continue

        yield _FileEntry(
            canonical=canonical,
            path=path,
            size_bytes=metadata.st_size,
            mtime_ns=metadata.st_mtime_ns,
        )


def _reconcile_entry(
    store: InventoryStore,
    session_id: str,
    generation: int,
    entry: _FileEntry,
    prior: InventoryRecord | None,
) -> str:
    if prior is None:
        store.upsert_seen(
            InventoryRecord(
                relative_path=entry.canonical,
                size_bytes=entry.size_bytes,
                mtime_ns=entry.mtime_ns,
                inventory_status=INVENTORY_PRESENT,
                metadata_status=METADATA_PENDING,
            ),
            session_id,
            generation,
        )
        return 'new'

    stats_differ = (
        prior.size_bytes != entry.size_bytes or prior.mtime_ns != entry.mtime_ns
    )

    if prior.inventory_status == INVENTORY_MISSING:
        metadata_status = METADATA_STALE if stats_differ else prior.metadata_status
        store.upsert_seen(
            InventoryRecord(
                relative_path=entry.canonical,
                size_bytes=entry.size_bytes,
                mtime_ns=entry.mtime_ns,
                inventory_status=INVENTORY_PRESENT,
                metadata_status=metadata_status,
                content_hash=prior.content_hash,
                parser_version=prior.parser_version,
                file_kind=prior.file_kind,
                sample_hint=prior.sample_hint,
            ),
            session_id,
            generation,
        )
        return 'restored'

    if stats_differ:
        store.upsert_seen(
            InventoryRecord(
                relative_path=entry.canonical,
                size_bytes=entry.size_bytes,
                mtime_ns=entry.mtime_ns,
                inventory_status=INVENTORY_PRESENT,
                metadata_status=METADATA_STALE,
                content_hash=prior.content_hash,
                parser_version=prior.parser_version,
                file_kind=prior.file_kind,
                sample_hint=prior.sample_hint,
            ),
            session_id,
            generation,
        )
        return 'changed'

    store.mark_seen(entry.canonical, session_id, generation)
    return 'unchanged'


def scan_inventory_batch(
    storage: StorageRoot,
    store: InventoryStore,
    *,
    max_files: int | None = None,
) -> InventoryScanResult:  # noqa: PLR0915
    """Scan up to ``max_files`` files, resuming any active session.

    Reaching ``max_files`` with files remaining leaves the session active and
    never reconciles missing records. A completed traversal completes the
    session and marks previously-present unseen records missing. Any traversal
    or stat error fails the session without reconciling missing records.
    """

    if max_files is not None and (
        isinstance(max_files, bool) or not isinstance(max_files, int) or max_files <= 0
    ):
        raise ValueError('max_files must be a positive integer or None')

    session = store.resume_scan()
    if session is None:
        session = store.begin_scan()

    errors: list[str] = []
    generation = session.generation
    processed = 0
    remaining = 0
    last_processed = session.checkpoint_path
    batch_new = 0
    batch_unchanged = 0
    batch_changed = 0
    batch_restored = 0

    for entry in _iter_file_entries(storage, errors):
        prior = store.get(entry.canonical)
        if prior is not None and prior.last_seen_generation == generation:
            # Already reconciled earlier in this persisted generation.
            continue
        if max_files is not None and processed >= max_files:
            remaining += 1
            continue

        outcome = _reconcile_entry(store, session.session_id, generation, entry, prior)
        processed += 1
        last_processed = entry.canonical
        if outcome == 'new':
            batch_new += 1
        elif outcome == 'unchanged':
            batch_unchanged += 1
        elif outcome == 'changed':
            batch_changed += 1
        elif outcome == 'restored':
            batch_restored += 1

    seen = session.files_seen + processed
    new = session.files_new + batch_new
    unchanged = session.files_unchanged + batch_unchanged
    changed = session.files_changed + batch_changed
    restored = session.files_restored + batch_restored

    if errors:
        final = store.fail_scan(
            session.session_id,
            errors=tuple(sorted(errors)),
            files_seen=seen,
            files_new=new,
            files_unchanged=unchanged,
            files_changed=changed,
            files_restored=restored,
        )
        return InventoryScanResult(
            scan_complete=False,
            seen=seen,
            new=new,
            unchanged=unchanged,
            changed=changed,
            restored=restored,
            marked_missing=0,
            errors=tuple(sorted(errors)),
            session_id=session.session_id,
            generation=session.generation,
            status=SESSION_FAILED,
            remaining=remaining,
        )

    if remaining > 0:
        new_checkpoint = last_processed
        store.checkpoint_scan(
            session.session_id,
            checkpoint_path=new_checkpoint,
            files_seen=seen,
            files_new=new,
            files_unchanged=unchanged,
            files_changed=changed,
            files_restored=restored,
        )
        return InventoryScanResult(
            scan_complete=False,
            seen=seen,
            new=new,
            unchanged=unchanged,
            changed=changed,
            restored=restored,
            marked_missing=0,
            errors=(),
            session_id=session.session_id,
            generation=session.generation,
            status=SESSION_ACTIVE,
            remaining=remaining,
        )

    final = store.complete_scan(
        session.session_id,
        files_seen=seen,
        files_new=new,
        files_unchanged=unchanged,
        files_changed=changed,
        files_restored=restored,
    )
    return InventoryScanResult(
        scan_complete=True,
        seen=seen,
        new=new,
        unchanged=unchanged,
        changed=changed,
        restored=restored,
        marked_missing=final.files_marked_missing,
        errors=(),
        session_id=session.session_id,
        generation=session.generation,
        status=SESSION_COMPLETED,
        remaining=0,
    )


def scan_inventory(storage: StorageRoot, store: InventoryStore) -> InventoryScanResult:
    """Reconcile files under ``storage`` against ``store`` in one pass."""

    return scan_inventory_batch(storage, store, max_files=None)
