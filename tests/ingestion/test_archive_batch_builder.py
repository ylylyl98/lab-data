"""Focused tests for the archive batch adapter."""

from pathlib import Path

import pytest

from lab_data.ingestion.archive_batch_builder import (
    ArchiveBatchItem,
    build_archive_batch,
)
from lab_data.ingestion.archive_generation import (
    ArchiveGenerationError,
    ArchiveGenerationExecutionResult,
    ArchiveGenerationJob,
    ArchiveGenerationPlan,
)


def _job(proposal_id, *, output_relative=None):
    return ArchiveGenerationJob(
        proposal_id=proposal_id,
        source_paths=(f'{proposal_id}/source.csv',),
        output_relative_path=output_relative or f'{proposal_id}.archive.json',
    )


def _plan(proposal_ids, *, errors=()):
    return ArchiveGenerationPlan(
        jobs=tuple(_job(pid) for pid in proposal_ids),
        warnings=(),
        errors=tuple(errors),
    )


def _success(plan):
    return ArchiveGenerationExecutionResult(
        jobs_requested=len(plan.jobs),
        jobs_succeeded=len(plan.jobs),
        jobs_failed=0,
        output_paths=tuple(f'C:\\out\\{job.output_relative_path}' for job in plan.jobs),
        errors=(),
    )


def test_complete_success_maps_one_to_one_in_order():
    plan = _plan(['proposal-0002', 'proposal-0001'])
    result = _success(plan)

    batch = build_archive_batch(plan, result)

    assert batch.rejected is False
    assert batch.item_count == 2  # noqa: PLR2004
    assert batch.proposal_ids == ('proposal-0002', 'proposal-0001')
    assert batch.items == (
        ArchiveBatchItem(
            proposal_id='proposal-0002',
            output_relative_path='proposal-0002.archive.json',
            output_path='C:\\out\\proposal-0002.archive.json',
        ),
        ArchiveBatchItem(
            proposal_id='proposal-0001',
            output_relative_path='proposal-0001.archive.json',
            output_path='C:\\out\\proposal-0001.archive.json',
        ),
    )


def test_failed_job_is_rejected_by_default():
    plan = _plan(['proposal-0001', 'proposal-0002'])
    result = ArchiveGenerationExecutionResult(
        jobs_requested=2,
        jobs_succeeded=1,
        jobs_failed=1,
        output_paths=('C:\\out\\proposal-0001.archive.json',),
        errors=(ArchiveGenerationError('proposal-0002', 'boom'),),
    )

    batch = build_archive_batch(plan, result)

    assert batch.rejected is True
    assert batch.items == ()
    assert any('incomplete' in error for error in batch.errors)
    assert any('proposal-0002' in error for error in batch.errors)


def test_allow_partial_produces_successful_only_batch():
    plan = _plan(['proposal-0001', 'proposal-0002', 'proposal-0003'])
    result = ArchiveGenerationExecutionResult(
        jobs_requested=3,
        jobs_succeeded=2,
        jobs_failed=1,
        output_paths=(
            'C:\\out\\proposal-0001.archive.json',
            'C:\\out\\proposal-0003.archive.json',
        ),
        errors=(ArchiveGenerationError('proposal-0002', 'boom'),),
    )

    batch = build_archive_batch(plan, result, allow_partial=True)

    assert batch.rejected is False
    assert batch.proposal_ids == ('proposal-0001', 'proposal-0003')
    assert batch.items[0].output_path == 'C:\\out\\proposal-0001.archive.json'
    assert batch.items[1].output_path == 'C:\\out\\proposal-0003.archive.json'


def test_missing_output_rejects():
    plan = _plan(['proposal-0001', 'proposal-0002'])
    result = ArchiveGenerationExecutionResult(
        jobs_requested=2,
        jobs_succeeded=1,
        jobs_failed=1,
        output_paths=(),
        errors=(ArchiveGenerationError('proposal-0002', 'boom'),),
    )

    batch = build_archive_batch(plan, result)

    assert batch.rejected is True
    assert any('output path count' in error for error in batch.errors)


def test_duplicate_proposal_ids_reject():
    plan = _plan(['proposal-0001', 'proposal-0001'])
    result = _success(plan)

    batch = build_archive_batch(plan, result)

    assert batch.rejected is True
    assert any('duplicate proposal ids' in error for error in batch.errors)


def test_duplicate_output_paths_reject():
    plan = _plan(['proposal-0001', 'proposal-0002'])
    result = ArchiveGenerationExecutionResult(
        jobs_requested=2,
        jobs_succeeded=2,
        jobs_failed=0,
        output_paths=(
            'C:\\out\\proposal-0001.archive.json',
            'C:\\out\\proposal-0001.archive.json',
        ),
        errors=(),
    )

    batch = build_archive_batch(plan, result)

    assert batch.rejected is True
    assert any('duplicate output paths' in error for error in batch.errors)


def test_plan_errors_reject():
    plan = _plan(['proposal-0001'], errors=('collision: something',))
    result = _success(plan)

    batch = build_archive_batch(plan, result)

    assert batch.rejected is True
    assert any('plan error' in error for error in batch.errors)


def test_empty_plan_rejects():
    plan = _plan([])
    result = _success(plan)

    batch = build_archive_batch(plan, result)

    assert batch.rejected is True
    assert any('no jobs' in error for error in batch.errors)


def test_type_validation():
    with pytest.raises(TypeError):
        build_archive_batch(None, None)  # type: ignore[arg-type]

    plan = _plan(['proposal-0001'])
    result = _success(plan)
    with pytest.raises(TypeError):
        build_archive_batch(plan, result, allow_partial=1)  # type: ignore[arg-type]


def test_no_directory_guessing_or_nomad_coupling():
    source = Path('src/lab_data/ingestion/archive_batch_builder.py').read_text(
        encoding='utf-8'
    )
    lowered = source.lower()

    for forbidden in (
        'os.walk',
        'rglob',
        'iterdir',
        'scandir',
        'scan_directory',
        'import nomad',
        'from nomad',
        'import requests',
        'inventory_store',
        'inventory_scan',
    ):
        assert forbidden not in lowered
