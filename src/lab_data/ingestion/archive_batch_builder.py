"""Deterministic adapter from generated archives to ordered batch items.

This module consumes an :class:`ArchiveGenerationPlan` and its
:class:`ArchiveGenerationExecutionResult` and produces ordered batch items. It
never discovers files from a directory, scans, uploads, or touches inventory
or generated archive files. The default production policy requires a complete
one-to-one success; an explicit ``allow_partial=True`` opt-in produces a
successful-only batch for retry/reconciliation tooling.
"""

from __future__ import annotations

from dataclasses import dataclass

from lab_data.ingestion.archive_generation import (
    ArchiveGenerationExecutionResult,
    ArchiveGenerationPlan,
)
from lab_data.ingestion.batch_manifest import (
    BatchManifest,
    ManifestFile,
    create_batch_manifest,
)
from lab_data.ingestion.batch_planner import plan_batches

__all__ = [
    'ArchiveBatch',
    'ArchiveBatchItem',
    'build_archive_batch',
    'build_batch_manifest',
]


@dataclass(frozen=True)
class ArchiveBatchItem:
    """One generated archive mapped to a batch item in deterministic order."""

    proposal_id: str
    output_relative_path: str
    output_path: str


@dataclass(frozen=True)
class ArchiveBatch:
    """Immutable result of building a batch from explicit generated outputs."""

    items: tuple[ArchiveBatchItem, ...]
    errors: tuple[str, ...]

    @property
    def rejected(self) -> bool:
        """Return whether this batch was rejected for production use."""

        return bool(self.errors)

    @property
    def item_count(self) -> int:
        """Return the number of mapped batch items."""

        return len(self.items)

    @property
    def proposal_ids(self) -> tuple[str, ...]:
        """Return ordered proposal IDs in the batch."""

        return tuple(item.proposal_id for item in self.items)


def build_archive_batch(  # noqa: PLR0912
    plan: ArchiveGenerationPlan,
    execution_result: ArchiveGenerationExecutionResult,
    *,
    allow_partial: bool = False,
) -> ArchiveBatch:
    """Build ordered batch items from a plan and its execution result.

    By default this rejects unless every planned job succeeded exactly once and
    the result has no errors. With ``allow_partial=True``, failed jobs are
    excluded and a successful-only batch is returned; missing or duplicate
    outputs still reject deterministically.
    """

    if not isinstance(plan, ArchiveGenerationPlan):
        raise TypeError('plan must be an ArchiveGenerationPlan')
    if not isinstance(execution_result, ArchiveGenerationExecutionResult):
        raise TypeError('execution_result must be an ArchiveGenerationExecutionResult')
    if not isinstance(allow_partial, bool):
        raise TypeError('allow_partial must be a boolean')

    errors: list[str] = []

    proposal_ids = [job.proposal_id for job in plan.jobs]
    if not proposal_ids:
        errors.append('plan contains no jobs')

    if len(set(proposal_ids)) != len(proposal_ids):
        duplicates = sorted(pid for pid in proposal_ids if proposal_ids.count(pid) > 1)
        errors.append('duplicate proposal ids: ' + ', '.join(dict.fromkeys(duplicates)))

    if plan.errors:
        errors.extend(f'plan error: {message}' for message in plan.errors)

    if execution_result.jobs_requested != len(plan.jobs):
        errors.append(
            'execution requested count does not match plan job count '
            f'({execution_result.jobs_requested} != {len(plan.jobs)})'
        )

    failed_ids = execution_result.failed_proposal_ids
    if len(set(failed_ids)) != len(failed_ids):
        errors.append('execution result contains duplicate failure records')

    if not allow_partial:
        if failed_ids:
            errors.append(
                'batch is incomplete: failed proposal ids: ' + ', '.join(failed_ids)
            )
        if execution_result.jobs_succeeded != len(plan.jobs):
            errors.append(
                'execution success count does not match plan job count '
                f'({execution_result.jobs_succeeded} != {len(plan.jobs)})'
            )
        expected_output_count = len(plan.jobs)
    else:
        expected_output_count = execution_result.jobs_succeeded

    output_paths = list(execution_result.output_paths)
    if len(output_paths) != expected_output_count:
        errors.append(
            'output path count does not match expected count '
            f'({len(output_paths)} != {expected_output_count})'
        )

    if len(set(output_paths)) != len(output_paths):
        errors.append('duplicate output paths in execution result')

    output_relative_by_proposal = {
        job.proposal_id: job.output_relative_path for job in plan.jobs
    }
    if len(output_relative_by_proposal) != len(plan.jobs):
        errors.append('duplicate output relative paths in plan')

    if errors:
        return ArchiveBatch(items=(), errors=tuple(sorted(set(errors))))

    failed_set = set(failed_ids)
    successful_ids = [pid for pid in proposal_ids if pid not in failed_set]
    if len(successful_ids) != len(output_paths):
        errors.append(
            'successful proposal count does not match output path count '
            f'({len(successful_ids)} != {len(output_paths)})'
        )
        return ArchiveBatch(items=(), errors=tuple(sorted(set(errors))))

    items = tuple(
        ArchiveBatchItem(
            proposal_id=proposal_id,
            output_relative_path=output_relative_by_proposal[proposal_id],
            output_path=output_path,
        )
        for proposal_id, output_path in zip(successful_ids, output_paths, strict=True)
    )
    return ArchiveBatch(items=items, errors=())


def build_batch_manifest(  # noqa: PLR0913
    batch: ArchiveBatch,
    *,
    dataset_label: str,
    batch_size: int,
    batch_number: int,
    upload_name: str,
    publish: bool = False,
    created_utc: str | None = None,
    updated_utc: str | None = None,
) -> BatchManifest:
    """Construct one deterministic planned BatchManifest from a complete batch.

    The batch must be non-rejected and contain at least one item. Its ordered
    proposal IDs are passed directly to ``plan_batches`` with the supplied
    ``batch_size``; only a single produced batch with the requested
    ``batch_number`` and item count is accepted. Exactly one explicit
    ``ManifestFile`` archive mapping is created per generated output, with
    zero companion mappings.
    """

    if not isinstance(batch, ArchiveBatch):
        raise TypeError('batch must be an ArchiveBatch')
    if batch.rejected:
        raise ValueError('cannot build a manifest from a rejected batch')
    if not batch.items:
        raise ValueError('cannot build a manifest from an empty batch')
    if not isinstance(dataset_label, str) or not dataset_label:
        raise ValueError('dataset_label must be a non-empty string')
    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or batch_size <= 0
    ):
        raise ValueError('batch_size must be a positive integer')
    if (
        isinstance(batch_number, bool)
        or not isinstance(batch_number, int)
        or batch_number < 1
    ):
        raise ValueError('batch_number must be a positive integer')
    if not isinstance(upload_name, str) or not upload_name:
        raise ValueError('upload_name must be a non-empty string')
    if not isinstance(publish, bool):
        raise TypeError('publish must be a boolean')

    proposal_ids = batch.proposal_ids
    planned = plan_batches(
        proposal_ids,
        batch_size=batch_size,
        dataset_label=dataset_label,
    )
    if len(planned) != 1:
        raise ValueError(
            f'unexpected batch split: expected exactly one batch, got {len(planned)}'
        )
    if planned[0].batch_number != batch_number:
        raise ValueError(
            f'batch number mismatch: expected {batch_number}, '
            f'got {planned[0].batch_number}'
        )
    if planned[0].item_count != len(proposal_ids):
        raise ValueError(
            'planned batch item count does not match proposal count '
            f'({planned[0].item_count} != {len(proposal_ids)})'
        )

    archive_files = tuple(
        ManifestFile(
            source_path=item.output_path,
            destination_path=item.output_relative_path,
            role='archive',
        )
        for item in batch.items
    )

    return create_batch_manifest(
        planned[0],
        archive_files=archive_files,
        companion_files=(),
        publish=publish,
        upload_name=upload_name,
        created_utc=created_utc,
        updated_utc=updated_utc,
    )
