"""Read-only, deterministic operator status for the local ingestion pipeline.

The status report is deliberately a projection of persisted state.  It opens
the inventory database in SQLite read-only mode and reads batch manifests
without touching source data, generating archives, or contacting NOMAD.  A
malformed artifact is represented as a blocker in the returned report rather
than making an operator lose the rest of the report to an exception.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from lab_data.ingestion.batch_manifest import BatchManifest, read_batch_manifest
from lab_data.ingestion.production_batch_reader import (
    BatchEligibility,
    select_next_eligible_batch,
)

__all__ = [
    'BatchStatusReport',
    'InventoryStatusReport',
    'PipelineStatus',
    'ScanStatusReport',
    'build_pipeline_status',
    'read_pipeline_status',
]


_LIFECYCLE_SUFFIXES = (
    '.final.json',
    '.reconciled_mainfile.json',
    '.reconciled.json',
    '.upload_created.json',
    '.preflight_passed.json',
)
_BATCH_FILE_RE = re.compile(r'^batch-(\d+)(?:\.[^.]+)*\.json$')


def _frozen_counts(values: Mapping[str, int]) -> Mapping[str, int]:
    """Return a deterministic immutable count mapping."""

    return MappingProxyType(dict(sorted(values.items())))


@dataclass(frozen=True)
class ScanStatusReport:
    """Latest persisted scan-session counters, if any."""

    session_id: str
    generation: int
    status: str
    files_seen: int
    files_new: int
    files_unchanged: int
    files_changed: int
    files_restored: int
    files_marked_missing: int
    errors: tuple[str, ...]


@dataclass(frozen=True)
class InventoryStatusReport:
    """Read-only inventory and metadata coverage summary."""

    total_records: int
    inventory_status_counts: Mapping[str, int]
    metadata_status_counts: Mapping[str, int]
    parser_version_presence: Mapping[str, int]
    file_kind_presence: Mapping[str, int]
    sample_hint_presence: Mapping[str, int]
    latest_scan: ScanStatusReport | None


@dataclass(frozen=True)
class BatchStatusReport:
    """Read-only projection of numbered production batch artifacts."""

    discovered_batches: int
    lifecycle_counts: Mapping[str, int]
    total_expected_entries: int
    total_verified_entries: int
    unpublished_batches: int
    published_batches: int
    next_eligible: BatchEligibility
    duplicate_proposal_ids: tuple[str, ...]
    duplicate_upload_ids: tuple[str, ...]
    malformed_artifacts: tuple[str, ...]


@dataclass(frozen=True)
class PipelineStatus:
    """Complete immutable operator status report.

    ``blockers`` and ``warnings`` are sorted tuples so repeated reads of the
    same persisted state compare equal and produce stable output.
    """

    inventory: InventoryStatusReport
    batches: BatchStatusReport
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    dataset_label: str | None = None


def _read_inventory(
    db_path: Path,
    blockers: set[str],
) -> InventoryStatusReport:
    """Read inventory records and latest scan session without DB mutation."""

    empty = InventoryStatusReport(
        total_records=0,
        inventory_status_counts=_frozen_counts({}),
        metadata_status_counts=_frozen_counts({}),
        parser_version_presence=_frozen_counts({'missing': 0, 'present': 0}),
        file_kind_presence=_frozen_counts({'missing': 0, 'present': 0}),
        sample_hint_presence=_frozen_counts({'missing': 0, 'present': 0}),
        latest_scan=None,
    )
    if not db_path.exists():
        blockers.add(f'inventory database missing: {db_path}')
        return empty

    connection: sqlite3.Connection | None = None
    try:
        # URI mode=ro is important: status generation must never create or
        # migrate an inventory database as a side effect.
        uri = db_path.resolve().as_uri() + '?mode=ro'
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        tables = {
            row['name']
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if 'inventory_records' not in tables:
            blockers.add('inventory database has no inventory_records table')
            return empty

        records = connection.execute(
            'SELECT inventory_status, metadata_status, parser_version, '
            'file_kind, sample_hint FROM inventory_records'
        ).fetchall()
        inventory_counts: dict[str, int] = defaultdict(int)
        metadata_counts: dict[str, int] = defaultdict(int)
        presence: dict[str, dict[str, int]] = {
            field: {'missing': 0, 'present': 0}
            for field in ('parser_version', 'file_kind', 'sample_hint')
        }
        for row in records:
            inventory_counts[str(row['inventory_status'])] += 1
            metadata_counts[str(row['metadata_status'])] += 1
            for field, counts in presence.items():
                counts['present' if row[field] else 'missing'] += 1

        latest: ScanStatusReport | None = None
        if 'scan_sessions' in tables:
            session = connection.execute(
                'SELECT * FROM scan_sessions ORDER BY generation DESC, '
                'updated_utc DESC LIMIT 1'
            ).fetchone()
            if session is not None:
                errors: tuple[str, ...]
                try:
                    parsed = json.loads(session['errors_json'])
                    errors = (
                        tuple(str(item) for item in parsed)
                        if isinstance(parsed, list)
                        else ()
                    )
                    if not isinstance(parsed, list):
                        blockers.add('latest scan session errors_json is not a list')
                except (TypeError, ValueError):
                    errors = ()
                    blockers.add('latest scan session errors_json is malformed')
                latest = ScanStatusReport(
                    session_id=str(session['session_id']),
                    generation=int(session['generation']),
                    status=str(session['status']),
                    files_seen=int(session['files_seen']),
                    files_new=int(session['files_new']),
                    files_unchanged=int(session['files_unchanged']),
                    files_changed=int(session['files_changed']),
                    files_restored=int(session['files_restored']),
                    files_marked_missing=int(session['files_marked_missing']),
                    errors=errors,
                )
        return InventoryStatusReport(
            total_records=len(records),
            inventory_status_counts=_frozen_counts(inventory_counts),
            metadata_status_counts=_frozen_counts(metadata_counts),
            parser_version_presence=_frozen_counts(presence['parser_version']),
            file_kind_presence=_frozen_counts(presence['file_kind']),
            sample_hint_presence=_frozen_counts(presence['sample_hint']),
            latest_scan=latest,
        )
    except (OSError, sqlite3.Error) as error:
        blockers.add(f'inventory database unreadable: {db_path} ({error})')
        return empty
    finally:
        if connection is not None:
            connection.close()


def _manifest_for(
    path: Path,
    malformed: set[str],
) -> BatchManifest | None:
    try:
        return read_batch_manifest(path)
    except (OSError, ValueError) as error:
        malformed.add(f'{path}: {error}')
        return None


def _batch_report(  # noqa: PLR0912, PLR0915
    batches_dir: Path,
    blockers: set[str],
    warnings: set[str],
) -> BatchStatusReport:
    malformed: set[str] = set()
    if not batches_dir.is_dir():
        blockers.add(f'batches directory missing: {batches_dir}')
        empty_eligibility = BatchEligibility(
            False, None, None, 'batches directory does not exist'
        )
        return BatchStatusReport(
            0, _frozen_counts({}), 0, 0, 0, 0, empty_eligibility, (), (), ()
        )

    numbers: set[int] = set()
    for path in batches_dir.glob('batch-*.json'):
        match = _BATCH_FILE_RE.fullmatch(path.name)
        if match:
            numbers.add(int(match.group(1)))
            suffix = path.name[len(f'batch-{int(match.group(1)):03d}') :]
            if suffix not in {'.json', *_LIFECYCLE_SUFFIXES}:
                malformed.add(f'{path}: unrecognized lifecycle artifact suffix')
        elif path.name.startswith('batch-'):
            malformed.add(f'{path}: unrecognized batch artifact name')

    proposal_batches: dict[str, set[int]] = defaultdict(set)
    upload_batches: dict[str, set[int]] = defaultdict(set)
    lifecycle_counts: dict[str, int] = defaultdict(int)
    expected_total = verified_total = unpublished = published = 0

    for number in sorted(numbers):
        base_path = batches_dir / f'batch-{number:03d}.json'
        base = _manifest_for(base_path, malformed) if base_path.exists() else None
        if base is None:
            malformed.add(f'{base_path}: base manifest missing or invalid')
            lifecycle_counts['blocked_invalid'] += 1
            continue
        expected_total += base.expected_entry_count
        for proposal_id in base.proposal_ids:
            proposal_batches[proposal_id].add(number)

        manifests: list[tuple[str, BatchManifest]] = []
        for suffix in _LIFECYCLE_SUFFIXES:
            path = batches_dir / f'batch-{number:03d}{suffix}'
            if path.exists():
                manifest = _manifest_for(path, malformed)
                if manifest is not None:
                    manifests.append((suffix, manifest))
                    for proposal_id in manifest.proposal_ids:
                        proposal_batches[proposal_id].add(number)
                    if manifest.upload_id:
                        upload_batches[manifest.upload_id].add(number)
                    if (
                        manifest.batch_id != base.batch_id
                        or manifest.batch_number != base.batch_number
                    ):
                        blockers.add(
                            f'batch {number:03d} lifecycle identity conflicts with base manifest'
                        )

        advanced = manifests[0][1] if manifests else base
        if advanced.publish:
            published += 1
            blockers.add(f'batch {number:03d} has publish=true')
        else:
            unpublished += 1

        final = next((m for suffix, m in manifests if suffix == '.final.json'), None)
        if final is not None and (
            final.status.value == 'success'
            and final.verification_status == 'verified'
            and final.upload_id
            and final.entry_ids
        ):
            lifecycle_counts['final_verified'] += 1
            verified_total += len(final.entry_ids)
        elif not manifests or all(
            suffix == '.preflight_passed.json' for suffix, _ in manifests
        ):
            lifecycle_counts['preflight_ready'] += 1
            warnings.add(
                f'batch {number:03d} is preflight-ready; this does not imply NOMAD upload'
            )
        elif advanced.status.value in {'upload_created', 'processing'}:
            lifecycle_counts['processing_pending'] += 1
            blockers.add(
                f'batch {number:03d} is not final and verified ({advanced.status.value})'
            )
        else:
            lifecycle_counts['blocked_invalid'] += 1
            blockers.add(
                f'batch {number:03d} is not final and verified ({advanced.status.value})'
            )

        if advanced.upload_id and final is None:
            blockers.add(f'batch {number:03d} has an upload ID but no final artifact')

    duplicate_proposals = tuple(
        sorted(item for item, batches in proposal_batches.items() if len(batches) > 1)
    )
    duplicate_uploads = tuple(
        sorted(item for item, batches in upload_batches.items() if len(batches) > 1)
    )
    if duplicate_proposals:
        blockers.add('duplicate proposal membership: ' + ', '.join(duplicate_proposals))
    if duplicate_uploads:
        blockers.add('duplicate confirmed upload IDs: ' + ', '.join(duplicate_uploads))
    if malformed:
        blockers.update('malformed artifact: ' + item for item in sorted(malformed))

    try:
        eligibility = select_next_eligible_batch(batches_dir)
    except (OSError, ValueError) as error:
        eligibility = BatchEligibility(False, None, None, 'selector failed')
        blockers.add(f'next eligible batch selector failed: {error}')
    if not eligibility.eligible:
        warnings.add(f'no eligible batch: {eligibility.reason}')

    return BatchStatusReport(
        discovered_batches=len(numbers),
        lifecycle_counts=_frozen_counts(lifecycle_counts),
        total_expected_entries=expected_total,
        total_verified_entries=verified_total,
        unpublished_batches=unpublished,
        published_batches=published,
        next_eligible=eligibility,
        duplicate_proposal_ids=duplicate_proposals,
        duplicate_upload_ids=duplicate_uploads,
        malformed_artifacts=tuple(sorted(malformed)),
    )


def read_pipeline_status(
    inventory_db_path: str | Path,
    batches_dir: str | Path,
    *,
    dataset_label: str | None = None,
) -> PipelineStatus:
    """Build a deterministic, read-only report from persisted pipeline state."""

    blockers: set[str] = set()
    warnings: set[str] = set()
    inventory = _read_inventory(Path(inventory_db_path), blockers)
    if inventory.metadata_status_counts.get('pending', 0):
        blockers.add(
            f'{inventory.metadata_status_counts["pending"]} inventory records have pending metadata'
        )
    if inventory.latest_scan is not None:
        if inventory.latest_scan.status != 'completed':
            blockers.add(
                f'latest scan session is {inventory.latest_scan.status}, not completed'
            )
        if inventory.latest_scan.errors:
            blockers.add(
                f'latest scan session has {len(inventory.latest_scan.errors)} persisted errors'
            )
    batches = _batch_report(Path(batches_dir), blockers, warnings)
    return PipelineStatus(
        inventory=inventory,
        batches=batches,
        blockers=tuple(sorted(blockers)),
        warnings=tuple(sorted(warnings)),
        dataset_label=dataset_label,
    )


build_pipeline_status = read_pipeline_status
