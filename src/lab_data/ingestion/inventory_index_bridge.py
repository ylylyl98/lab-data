"""Thin planner for metadata indexing over a resumable inventory.

This module turns the selected inventory records into a deterministic grouping
plan for the metadata indexer. It performs no scanning, file content reads,
status mutation, parsing, serialization, or network access. The planner groups
selected records by their top-level folder (the smallest directory boundary
under which the scanner's role classification and cross-role filename-stem
grouping remain valid) so downstream work can be scheduled per scanner unit
rather than per file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from lab_data.ingestion.inventory_store import (
    INVENTORY_MISSING,
    METADATA_FAILED,
    METADATA_INDEXED,
    METADATA_PENDING,
    METADATA_STALE,
    InventoryRecord,
    InventoryStore,
)
from lab_data.ingestion.proposal import build_import_proposal
from lab_data.ingestion.scanner import scan_relative_files
from lab_data.storage import StorageRoot

__all__ = [
    'MetadataIndexExecutionResult',
    'MetadataIndexPlan',
    'MetadataIndexUnit',
    'execute_metadata_indexing',
    'plan_metadata_indexing',
]

_CONTROL_CHARACTER_LIMIT = 32
_DELETE_CHARACTER = 127


def _scanner_unit(relative_path: str) -> str:
    """Return the smallest safe scanner grouping boundary for a record.

    The scanner groups filename stems across role subfolders under a single
    scan root, so the smallest directory that can be re-scanned without losing
    cross-role grouping is the top-level component under the storage root. A
    root-level file has no folder boundary and is represented by its filename.
    """

    parts = PurePosixPath(relative_path).parts
    return parts[0] if parts else relative_path


@dataclass(frozen=True)
class MetadataIndexUnit:
    """One deterministic scanner grouping boundary."""

    scanner_unit: str
    relative_paths: tuple[str, ...]

    @property
    def record_count(self) -> int:
        """Return the number of records in this unit."""

        return len(self.relative_paths)


@dataclass(frozen=True)
class MetadataIndexPlan:
    """Immutable deterministic plan for metadata indexing."""

    selected_records: tuple[InventoryRecord, ...]
    units: tuple[MetadataIndexUnit, ...]
    skipped_indexed: int
    skipped_missing: int
    skipped_failed: int
    requested_parser_version: str | None = None
    parser_version_stale_count: int = 0

    @property
    def ordinary_selected_count(self) -> int:
        """Return records selected by their pending/stale/failed status."""

        return sum(
            record.metadata_status
            in {METADATA_PENDING, METADATA_STALE, METADATA_FAILED}
            for record in self.selected_records
        )

    @property
    def selected_failed_count(self) -> int:
        """Return failed records selected through ``include_failed``."""

        return sum(
            record.metadata_status == METADATA_FAILED
            for record in self.selected_records
        )

    @property
    def selected_count(self) -> int:
        """Return the number of records selected for indexing."""

        return len(self.selected_records)

    @property
    def unit_count(self) -> int:
        """Return the number of scanner grouping units."""

        return len(self.units)


@dataclass(frozen=True)
class MetadataIndexExecutionResult:
    """Immutable outcome of executing a metadata-indexing plan."""

    candidate_records: tuple[InventoryRecord, ...]
    units_processed: int
    proposals_produced: int
    indexed_paths: tuple[str, ...]
    failed_paths: tuple[str, ...]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    parser_version: str | None = None


def plan_metadata_indexing(
    storage_root: StorageRoot,
    store: InventoryStore,
    *,
    include_failed: bool = False,
    requested_parser_version: str | None = None,
) -> MetadataIndexPlan:
    """Plan metadata indexing from selected inventory records.

    Selected records are the present ``pending``/``stale`` records (plus
    ``failed`` only when ``include_failed=True``). Indexed and missing records
    are always excluded unless an explicit ``requested_parser_version`` marks
    an indexed record as parser-stale. The plan does not mutate the store or
    read any file.
    """

    if not isinstance(storage_root, StorageRoot):
        raise TypeError('storage_root must be a StorageRoot')
    if not isinstance(store, InventoryStore):
        raise TypeError('store must be an InventoryStore')
    _validate_parser_version(requested_parser_version)

    ordinary_selected = store.list_for_metadata_indexing(include_failed=include_failed)
    selected_by_path = {record.relative_path: record for record in ordinary_selected}
    parser_version_stale_count = 0

    skipped_indexed = 0
    skipped_missing = 0
    skipped_failed = 0
    for record in store.list_records():
        if record.inventory_status == INVENTORY_MISSING:
            skipped_missing += 1
        elif record.metadata_status == METADATA_INDEXED:
            if (
                requested_parser_version is not None
                and record.parser_version != requested_parser_version
            ):
                selected_by_path[record.relative_path] = record
                parser_version_stale_count += 1
            else:
                skipped_indexed += 1
        elif record.metadata_status == METADATA_FAILED:
            if not include_failed:
                skipped_failed += 1

    selected = tuple(selected_by_path[path] for path in sorted(selected_by_path))

    grouped: dict[str, list[str]] = {}
    for record in selected:
        grouped.setdefault(_scanner_unit(record.relative_path), []).append(
            record.relative_path
        )

    units = tuple(
        MetadataIndexUnit(
            scanner_unit=unit,
            relative_paths=tuple(paths),
        )
        for unit, paths in sorted(grouped.items())
    )

    return MetadataIndexPlan(
        selected_records=selected,
        units=units,
        skipped_indexed=skipped_indexed,
        skipped_missing=skipped_missing,
        skipped_failed=skipped_failed,
        requested_parser_version=requested_parser_version,
        parser_version_stale_count=parser_version_stale_count,
    )


def _experiment_paths(experiment: object) -> tuple[str, ...]:
    """Return the role-bucket paths that participated in one proposal."""

    return tuple(
        sorted(
            {
                *getattr(experiment, 'raw_files', ()),
                *getattr(experiment, 'processed_files', ()),
                *getattr(experiment, 'figure_files', ()),
                *getattr(experiment, 'intermediate_files', ()),
            }
        )
    )


def _validate_parser_version(parser_version: str | None) -> None:
    """Validate explicit parser provenance before any indexing work begins."""

    if parser_version is None:
        return
    if not isinstance(parser_version, str) or not parser_version.strip():
        raise ValueError('parser_version must be a non-empty safe string')
    if any(
        ord(character) < _CONTROL_CHARACTER_LIMIT or ord(character) == _DELETE_CHARACTER
        for character in parser_version
    ):
        raise ValueError('parser_version must be a non-empty safe string')


def execute_metadata_indexing(  # noqa: PLR0912, PLR0913
    plan: MetadataIndexPlan,
    storage_root: StorageRoot,
    store: InventoryStore,
    *,
    scanner=scan_relative_files,
    proposal_builder=build_import_proposal,
    parser_version: str | None = None,
) -> MetadataIndexExecutionResult:
    """Execute a metadata-indexing plan unit by unit.

    Each unit is passed to ``scanner(storage_root.root, unit.relative_paths)``
    followed by ``proposal_builder(scan_result)``. Only paths that land in a
    successful (non-``needs_review``) proposal are marked indexed; unclassified
    selected paths are marked failed. Ambiguous proposal paths are left
    unchanged. Missing and indexed records are never selected, and failed
    records are retried only when the plan was built with ``include_failed``.
    """

    if not isinstance(plan, MetadataIndexPlan):
        raise TypeError('plan must be a MetadataIndexPlan')
    if not isinstance(storage_root, StorageRoot):
        raise TypeError('storage_root must be a StorageRoot')
    if not isinstance(store, InventoryStore):
        raise TypeError('store must be an InventoryStore')
    _validate_parser_version(parser_version)
    if (
        plan.requested_parser_version is not None
        and parser_version != plan.requested_parser_version
    ):
        raise ValueError(
            'parser_version must match plan.requested_parser_version '
            f'({plan.requested_parser_version!r})'
        )

    selected = {record.relative_path for record in plan.selected_records}
    indexed: set[str] = set()
    failed: set[str] = set()
    warnings: list[str] = []
    errors: list[str] = []
    units_processed = 0
    proposals_produced = 0

    for unit in plan.units:
        try:
            scan_result = scanner(storage_root.root, unit.relative_paths)
            proposal = proposal_builder(scan_result)
        except Exception as error:  # noqa: BLE001 - boundary reporting
            errors.append(
                f'{unit.scanner_unit}: scanner/proposal failed: '
                f'{type(error).__name__}: {error}'
            )
            continue

        units_processed += 1
        classified: set[str] = set()
        for experiment in proposal.experiments:
            proposals_produced += 1
            paths = _experiment_paths(experiment)
            for path in paths:
                classified.add(path)
                if path not in selected:
                    continue
                if experiment.needs_review:
                    warnings.append(
                        f'{unit.scanner_unit}: {path}: ambiguous proposal; '
                        'left unchanged'
                    )
                else:
                    indexed.add(path)

        for path in proposal.unresolved_files:
            if path in selected and path not in classified:
                failed.add(path)

    for path in sorted(indexed):
        if parser_version is None:
            store.update_metadata_status(path, METADATA_INDEXED)
        else:
            store.update_metadata_status_and_parser_version(
                path, METADATA_INDEXED, parser_version
            )
    for path in sorted(failed):
        if path not in indexed:
            store.update_metadata_status(path, METADATA_FAILED)

    return MetadataIndexExecutionResult(
        candidate_records=plan.selected_records,
        units_processed=units_processed,
        proposals_produced=proposals_produced,
        indexed_paths=tuple(sorted(indexed)),
        failed_paths=tuple(sorted(failed)),
        warnings=tuple(sorted(warnings)),
        errors=tuple(sorted(errors)),
        parser_version=parser_version,
    )
