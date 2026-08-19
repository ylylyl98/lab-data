"""Read-only summary and selection of persisted production batch state."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from lab_data.ingestion.batch_manifest import BatchManifest, read_batch_manifest

__all__ = [
    'BatchEligibility',
    'ProductionBatchPlan',
    'ProductionBatchState',
    'plan_production_batch',
    'read_production_batch_state',
    'select_next_eligible_batch',
]

# Lifecycle states ordered from most to least advanced. The most advanced
# existing file supplies status/upload/verification fields while the base
# planned manifest supplies stable batch identity and membership.
_LIFECYCLE_SUFFIXES = (
    '.final.json',
    '.reconciled_mainfile.json',
    '.reconciled.json',
    '.upload_created.json',
    '.preflight_passed.json',
)


@dataclass(frozen=True)
class ProductionBatchState:
    """Immutable read-only summary of one production batch."""

    batch_number: int
    batch_id: str
    manifest_path: str | None
    preflight_manifest_path: str | None
    final_state_path: str | None
    upload_id: str | None
    status: str
    verification_status: str | None
    published: bool
    item_count: int


@dataclass(frozen=True)
class BatchEligibility:
    """Immutable deterministic decision for the next production batch."""

    eligible: bool
    batch_number: int | None
    batch_id: str | None
    reason: str
    blocking_batch: int | None = None


@dataclass(frozen=True)
class ProductionBatchPlan:
    """Immutable one-batch production decision with no credentials."""

    batch_number: int | None
    batch_id: str | None
    manifest_path: str | None
    preflight_path: str | None
    action: str
    reason: str
    publish: bool


def _existing_lifecycle(
    batches_dir: Path, batch_number: int
) -> tuple[str, BatchManifest] | None:
    for suffix in _LIFECYCLE_SUFFIXES:
        path = batches_dir / f'batch-{batch_number:03d}{suffix}'
        if path.exists():
            return str(path), read_batch_manifest(path)
    return None


def read_production_batch_state(
    batches_dir: str | Path, batch_number: int
) -> ProductionBatchState:
    """Read one batch's persisted artifacts without mutation or network access.

    The base planned manifest is authoritative for batch identity and item
    count. The most advanced lifecycle file supplies the current status,
    upload ID, published flag, and verification status.
    """

    if isinstance(batch_number, bool) or not isinstance(batch_number, int):
        raise TypeError('batch_number must be an integer')
    if batch_number < 1:
        raise ValueError('batch_number must be a positive integer')

    directory = Path(batches_dir)
    if not directory.is_dir():
        raise FileNotFoundError(f'batches directory does not exist: {directory}')

    base_path = directory / f'batch-{batch_number:03d}.json'
    if not base_path.exists():
        raise FileNotFoundError(f'batch manifest not found: {base_path}')
    base = read_batch_manifest(base_path)

    preflight_path = directory / f'batch-{batch_number:03d}.preflight_passed.json'
    preflight = read_batch_manifest(preflight_path) if preflight_path.exists() else None

    lifecycle = _existing_lifecycle(directory, batch_number)
    if lifecycle is None:
        advanced = base
        advanced_path = str(base_path)
        final_path = None
    else:
        advanced_path, advanced = lifecycle
        final_candidate = directory / f'batch-{batch_number:03d}.final.json'
        final_path = str(final_candidate) if final_candidate.exists() else None

    return ProductionBatchState(
        batch_number=base.batch_number,
        batch_id=base.batch_id,
        manifest_path=str(base_path),
        preflight_manifest_path=str(preflight_path) if preflight else None,
        final_state_path=final_path,
        upload_id=advanced.upload_id,
        status=advanced.status.value,
        verification_status=advanced.verification_status,
        published=advanced.publish,
        item_count=len(base.proposal_ids),
    )


def _read_optional(path: Path) -> BatchManifest | None:
    try:
        return read_batch_manifest(path)
    except (ValueError, OSError):
        return None


def _candidate_numbers(directory: Path) -> tuple[int, ...]:
    """Return sorted batch numbers referenced by base or lifecycle files."""

    numbers: set[int] = set()
    for path in directory.glob('batch-*.json'):
        match = re.fullmatch(r'batch-(\d+)(?:\.[a-z_]+)?\.json', path.name)
        if match:
            numbers.add(int(match.group(1)))
    return tuple(sorted(numbers))


def _base_batch_id(directory: Path, batch_number: int) -> str | None:
    manifest = _read_optional(directory / f'batch-{batch_number:03d}.json')
    return manifest.batch_id if manifest is not None else None


def _is_final_verified(directory: Path, batch_number: int) -> bool:
    manifest = _read_optional(directory / f'batch-{batch_number:03d}.final.json')
    if manifest is None:
        return False
    return (
        manifest.status.value == 'success'
        and manifest.verification_status == 'verified'
        and manifest.upload_id is not None
        and bool(manifest.entry_ids)
    )


def _advanced_manifest(
    directory: Path, batch_number: int
) -> tuple[Path, BatchManifest] | None:
    for suffix in _LIFECYCLE_SUFFIXES:
        path = directory / f'batch-{batch_number:03d}{suffix}'
        if path.exists():
            manifest = _read_optional(path)
            if manifest is not None:
                return path, manifest
    return None


def select_next_eligible_batch(  # noqa: PLR0911
    batches_dir: str | Path,
) -> BatchEligibility:
    """Return the lowest numeric prepared batch that is eligible for production.

    Prepared batches are those with a persisted ``preflight_passed`` artifact.
    A batch is skipped once its final state is verified. A candidate is
    blocked when its preflight is missing/invalid, it is published, it already
    has a known upload ID (reconciliation required), or its predecessor (for
    batch numbers greater than one) is not final and verified.
    """

    directory = Path(batches_dir)
    if not directory.is_dir():
        return BatchEligibility(
            eligible=False,
            batch_number=None,
            batch_id=None,
            reason='batches directory does not exist',
        )

    numbers = _candidate_numbers(directory)
    if not numbers:
        return BatchEligibility(
            eligible=False,
            batch_number=None,
            batch_id=None,
            reason='no prepared batches',
        )

    for number in numbers:
        if _is_final_verified(directory, number):
            continue

        preflight_path = directory / f'batch-{number:03d}.preflight_passed.json'
        if not preflight_path.exists():
            return BatchEligibility(
                eligible=False,
                batch_number=number,
                batch_id=_base_batch_id(directory, number),
                reason='preflight manifest missing',
            )

        preflight = _read_optional(preflight_path)
        if preflight is None:
            return BatchEligibility(
                eligible=False,
                batch_number=number,
                batch_id=None,
                reason='invalid or unreadable preflight manifest',
            )

        advanced = _advanced_manifest(directory, number)
        advanced_manifest = advanced[1] if advanced else preflight
        if advanced_manifest.upload_id is not None:
            return BatchEligibility(
                eligible=False,
                batch_number=number,
                batch_id=advanced_manifest.batch_id,
                reason='known upload requires reconciliation',
            )
        if advanced_manifest.publish:
            return BatchEligibility(
                eligible=False,
                batch_number=number,
                batch_id=advanced_manifest.batch_id,
                reason='batch publish is True',
            )

        if number > 1 and not _is_final_verified(directory, number - 1):
            return BatchEligibility(
                eligible=False,
                batch_number=number,
                batch_id=advanced_manifest.batch_id,
                reason='predecessor batch is not final and verified',
                blocking_batch=number - 1,
            )

        return BatchEligibility(
            eligible=True,
            batch_number=number,
            batch_id=advanced_manifest.batch_id,
            reason='eligible',
        )

    return BatchEligibility(
        eligible=False,
        batch_number=None,
        batch_id=None,
        reason='no eligible batches',
    )


def plan_production_batch(  # noqa: PLR0911
    batches_dir: str | Path,
    remote: object,
) -> ProductionBatchPlan:
    """Build a one-batch production plan from local selection and remote state.

    ``remote`` must expose ``outcome`` and ``matching_upload_ids`` (for example
    :class:`RemoteBatchReadiness`). The plan is ``create`` only when the local
    selector is eligible, ``publish`` is false, there is no local upload ID,
    and the remote outcome is ``no_match``. A single remote match yields
    ``reconcile``; any ambiguity or local blocking condition yields
    ``blocked``.
    """

    directory = Path(batches_dir)
    eligibility = select_next_eligible_batch(directory)

    remote_outcome = getattr(remote, 'outcome', None)
    matching_ids = tuple(getattr(remote, 'matching_upload_ids', ()))

    if eligibility.eligible:
        state = read_production_batch_state(directory, eligibility.batch_number)
        if state.published:
            return ProductionBatchPlan(
                batch_number=state.batch_number,
                batch_id=state.batch_id,
                manifest_path=state.manifest_path,
                preflight_path=state.preflight_manifest_path,
                action='blocked',
                reason='batch publish is True',
                publish=True,
            )
        if state.upload_id is not None:
            return ProductionBatchPlan(
                batch_number=state.batch_number,
                batch_id=state.batch_id,
                manifest_path=state.manifest_path,
                preflight_path=state.preflight_manifest_path,
                action='blocked',
                reason='known upload requires reconciliation',
                publish=state.published,
            )
        if state.status not in ('planned', 'preflight_passed'):
            return ProductionBatchPlan(
                batch_number=state.batch_number,
                batch_id=state.batch_id,
                manifest_path=state.manifest_path,
                preflight_path=state.preflight_manifest_path,
                action='blocked',
                reason='batch has unresolved local state',
                publish=state.published,
            )

        if remote_outcome == 'no_match':
            return ProductionBatchPlan(
                batch_number=state.batch_number,
                batch_id=state.batch_id,
                manifest_path=state.manifest_path,
                preflight_path=state.preflight_manifest_path,
                action='create',
                reason='eligible and no remote match',
                publish=state.published,
            )
        if remote_outcome == 'single_match' and len(matching_ids) == 1:
            return ProductionBatchPlan(
                batch_number=state.batch_number,
                batch_id=state.batch_id,
                manifest_path=state.manifest_path,
                preflight_path=state.preflight_manifest_path,
                action='reconcile',
                reason='exactly one remote upload matches',
                publish=state.published,
            )

        return ProductionBatchPlan(
            batch_number=state.batch_number,
            batch_id=state.batch_id,
            manifest_path=state.manifest_path,
            preflight_path=state.preflight_manifest_path,
            action='blocked',
            reason='ambiguous remote match',
            publish=state.published,
        )

    if eligibility.batch_number is not None:
        state = read_production_batch_state(directory, eligibility.batch_number)
        return ProductionBatchPlan(
            batch_number=state.batch_number,
            batch_id=state.batch_id,
            manifest_path=state.manifest_path,
            preflight_path=state.preflight_manifest_path,
            action='blocked',
            reason=eligibility.reason,
            publish=state.published,
        )

    return ProductionBatchPlan(
        batch_number=None,
        batch_id=None,
        manifest_path=None,
        preflight_path=None,
        action='blocked',
        reason=eligibility.reason,
        publish=False,
    )
