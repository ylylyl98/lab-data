"""Read-only planning for the local ingestion pipeline.

The planner composes projections of persisted inventory and batch state into a
small, immutable operator plan.  It deliberately does not scan source files,
write the inventory database, generate archives, create manifests, or contact
NOMAD.  An operator can use the returned action tuple to decide which local
work is worth doing next.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from lab_data.ingestion.inventory_index_bridge import plan_metadata_indexing
from lab_data.ingestion.inventory_store import InventoryStore
from lab_data.ingestion.pipeline_status import PipelineStatus, read_pipeline_status
from lab_data.storage import StorageRoot

__all__ = [
    'BatchReadiness',
    'LocalPipelinePlan',
    'MetadataIndexReadiness',
    'plan_local_pipeline',
]


_NO_NOMAD_ACTIONS = ('nomad_upload', 'nomad_publish', 'nomad_process')
_CONTROL_CHARACTER_LIMIT = 32
_DELETE_CHARACTER = 127


@dataclass(frozen=True)
class MetadataIndexReadiness:
    """Immutable summary of records selected for metadata indexing."""

    selected_count: int
    ordinary_selected_count: int
    parser_stale_count: int
    scanner_unit_count: int
    skipped_indexed: int
    skipped_missing: int
    skipped_failed: int


@dataclass(frozen=True)
class BatchReadiness:
    """Immutable summary of persisted archive and batch readiness."""

    discovered_batches: int
    preflight_ready_batches: int
    final_verified_batches: int
    processing_pending_batches: int
    total_expected_entries: int
    total_verified_entries: int
    next_eligible_batch_number: int | None
    next_eligible_batch_id: str | None
    next_eligible_reason: str


@dataclass(frozen=True)
class LocalPipelinePlan:
    """Deterministic, read-only plan for the next local pipeline actions."""

    inventory_db_path: str
    storage_root: str
    batches_dir: str
    dataset_label: str | None
    parser_version: str | None
    metadata: MetadataIndexReadiness
    batches: BatchReadiness
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    excluded_actions: tuple[str, ...] = _NO_NOMAD_ACTIONS
    status: PipelineStatus | None = None


class _ReadOnlyInventoryStore(InventoryStore):
    """InventoryStore view backed by SQLite URI ``mode=ro``.

    ``plan_metadata_indexing`` intentionally accepts an ``InventoryStore`` so
    this narrow subclass lets the planner reuse that API without triggering
    schema creation or migrations.
    """

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            uri = self._path.resolve().as_uri() + '?mode=ro'
            connection = sqlite3.connect(uri, uri=True)
            connection.row_factory = sqlite3.Row
            self._conn = connection
        return self._conn


def _absolute_path(value: str | Path, field: str) -> Path:
    if not isinstance(value, (str, Path)):
        raise TypeError(f'{field} must be a path or string')
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f'{field} must be an absolute path')
    return path


def _validate_parser_version(value: str | None) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError('parser_version must be a non-empty safe string')
    if any(
        ord(character) < _CONTROL_CHARACTER_LIMIT or ord(character) == _DELETE_CHARACTER
        for character in value
    ):
        raise ValueError('parser_version must be a non-empty safe string')


def _metadata_readiness(
    inventory_db_path: Path,
    storage: StorageRoot,
    parser_version: str | None,
    blockers: set[str],
) -> MetadataIndexReadiness:
    empty = MetadataIndexReadiness(0, 0, 0, 0, 0, 0, 0)
    if not inventory_db_path.exists():
        return empty
    store = _ReadOnlyInventoryStore(inventory_db_path)
    try:
        plan = plan_metadata_indexing(
            storage,
            store,
            requested_parser_version=parser_version,
        )
        return MetadataIndexReadiness(
            selected_count=plan.selected_count,
            ordinary_selected_count=plan.ordinary_selected_count,
            parser_stale_count=plan.parser_version_stale_count,
            scanner_unit_count=plan.unit_count,
            skipped_indexed=plan.skipped_indexed,
            skipped_missing=plan.skipped_missing,
            skipped_failed=plan.skipped_failed,
        )
    except (OSError, sqlite3.Error, TypeError, ValueError) as error:
        blockers.add(
            f'metadata indexing plan unavailable: {type(error).__name__}: {error}'
        )
        return empty
    finally:
        store.close()


def _batch_readiness(status: PipelineStatus) -> BatchReadiness:
    counts = status.batches.lifecycle_counts
    eligibility = status.batches.next_eligible
    return BatchReadiness(
        discovered_batches=status.batches.discovered_batches,
        preflight_ready_batches=counts.get('preflight_ready', 0),
        final_verified_batches=counts.get('final_verified', 0),
        processing_pending_batches=counts.get('processing_pending', 0),
        total_expected_entries=status.batches.total_expected_entries,
        total_verified_entries=status.batches.total_verified_entries,
        next_eligible_batch_number=eligibility.batch_number,
        next_eligible_batch_id=eligibility.batch_id,
        next_eligible_reason=eligibility.reason,
    )


def _actions(
    blockers: tuple[str, ...],
    metadata: MetadataIndexReadiness,
    batches: BatchReadiness,
) -> tuple[str, ...]:
    if blockers:
        return ('review_blockers',)
    actions: list[str] = []
    if metadata.selected_count:
        actions.append('index_metadata')
    if batches.preflight_ready_batches == 0:
        actions.extend(('generate_archives', 'build_batches'))
    if not actions:
        actions.append('review_readiness')
    return tuple(actions)


def plan_local_pipeline(
    inventory_db_path: str | Path,
    storage_root: str | Path,
    batches_dir: str | Path,
    *,
    parser_version: str | None = None,
    dataset_label: str | None = None,
) -> LocalPipelinePlan:
    """Return a deterministic local-only plan from persisted project state.

    All paths are required to be absolute.  Missing paths and malformed
    persisted state become blockers in the plan; the function does not create
    directories, open source files, mutate SQLite, or perform network calls.
    """

    db_path = _absolute_path(inventory_db_path, 'inventory_db_path')
    root_path = _absolute_path(storage_root, 'storage_root')
    batches_path = _absolute_path(batches_dir, 'batches_dir')
    if dataset_label is not None and (
        not isinstance(dataset_label, str) or not dataset_label.strip()
    ):
        raise ValueError('dataset_label must be a non-empty string or None')
    _validate_parser_version(parser_version)

    storage = StorageRoot(root_path)
    status = read_pipeline_status(db_path, batches_path, dataset_label=dataset_label)
    blockers = set(status.blockers)
    warnings = set(status.warnings)
    if not root_path.is_dir():
        blockers.add(f'storage root missing: {root_path}')
    elif not root_path.exists():
        blockers.add(f'storage root missing: {root_path}')

    metadata = _metadata_readiness(db_path, storage, parser_version, blockers)
    final_blockers = tuple(sorted(blockers))
    final_warnings = tuple(sorted(warnings))
    batches = _batch_readiness(status)
    return LocalPipelinePlan(
        inventory_db_path=str(db_path),
        storage_root=str(root_path),
        batches_dir=str(batches_path),
        dataset_label=dataset_label,
        parser_version=parser_version,
        metadata=metadata,
        batches=batches,
        blockers=final_blockers,
        warnings=final_warnings,
        allowed_actions=_actions(final_blockers, metadata, batches),
        status=status,
    )
