"""Focused tests for deterministic archive-generation planning."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from lab_data.ingestion.archive_generation import (
    ArchiveGenerationPlan,
    plan_archive_generation,
)


@dataclass
class _Experiment:
    sample_id: str | None = None
    raw_files: tuple[str, ...] = ()
    intermediate_files: tuple[str, ...] = ()
    processed_files: tuple[str, ...] = ()
    figure_files: tuple[str, ...] = ()


def _experiment(
    sample_id='D356',
    *,
    raw=(),
    processed=(),
    figures=(),
    intermediate=(),
):
    return _Experiment(
        sample_id=sample_id,
        raw_files=tuple(raw),
        processed_files=tuple(processed),
        figure_files=tuple(figures),
        intermediate_files=tuple(intermediate),
    )


def test_one_proposal_plans_one_job(tmp_path):
    plan = plan_archive_generation(
        ['proposal-0001'],
        [_experiment(raw=['Initial Data/a.csv'], processed=['Processed Data/a.dat'])],
    )

    assert isinstance(plan, ArchiveGenerationPlan)
    assert plan.proposal_count == 1
    assert plan.collision_count == 0
    assert plan.errors == ()
    job = plan.jobs[0]
    assert job.proposal_id == 'proposal-0001'
    assert job.sample_id == 'D356'
    assert job.output_relative_path == 'archives/proposal-0001.archive.json'
    assert job.source_paths == (
        'Initial Data/a.csv',
        'Processed Data/a.dat',
    )


def test_multiple_proposals_are_deterministically_ordered():
    experiments = [
        _experiment(sample_id='D357'),
        _experiment(sample_id='D356'),
        _experiment(sample_id='D358'),
    ]

    plan = plan_archive_generation(
        ['proposal-0003', 'proposal-0001', 'proposal-0002'],
        experiments,
    )

    assert [job.proposal_id for job in plan.jobs] == [
        'proposal-0003',
        'proposal-0001',
        'proposal-0002',
    ]
    assert [job.sample_id for job in plan.jobs] == ['D357', 'D356', 'D358']
    assert [job.output_relative_path for job in plan.jobs] == [
        'archives/proposal-0003.archive.json',
        'archives/proposal-0001.archive.json',
        'archives/proposal-0002.archive.json',
    ]


def test_repeated_planning_is_equal():
    ids = ['proposal-0001', 'proposal-0002']
    experiments = [_experiment(), _experiment(sample_id='D357')]

    first = plan_archive_generation(ids, experiments)
    second = plan_archive_generation(ids, experiments)

    assert first == second


def test_deterministic_output_name_and_source_order(tmp_path):
    plan = plan_archive_generation(
        ['proposal-0001'],
        [
            _experiment(
                raw=['Initial Data/b.csv', 'Initial Data/a.csv'],
                figures=['Processed Data/z.png'],
                processed=['Processed Data/m.dat'],
                intermediate=['Initial data after process/i.csv'],
            )
        ],
        output_dir='out/YZ247',
    )

    job = plan.jobs[0]
    assert job.output_relative_path == 'out/YZ247/proposal-0001.archive.json'
    assert job.source_paths == (
        'Initial Data/a.csv',
        'Initial Data/b.csv',
        'Initial data after process/i.csv',
        'Processed Data/m.dat',
        'Processed Data/z.png',
    )


def test_existing_output_target_is_collision(tmp_path):
    out_dir = tmp_path / 'archives'
    out_dir.mkdir()
    (out_dir / 'proposal-0001.archive.json').write_text('existing', encoding='utf-8')

    plan = plan_archive_generation(
        ['proposal-0001'],
        [_experiment()],
        output_root=tmp_path,
    )

    assert plan.collision_count == 1
    assert any('already exists' in error for error in plan.errors)


def test_duplicate_destination_is_collision():
    # Two distinct proposal ids canonicalize to the same output path.
    plan = plan_archive_generation(
        ['proposal/0001', 'proposal\\0001'],
        [_experiment(), _experiment()],
    )

    assert plan.collision_count == 1
    assert any('duplicate output target' in error for error in plan.errors)
    assert plan.jobs[0].output_relative_path == plan.jobs[1].output_relative_path


def test_large_synthetic_plan(tmp_path):
    count = 300
    ids = [f'proposal-{index:04d}' for index in range(count)]
    experiments = [_experiment() for _ in range(count)]

    plan = plan_archive_generation(ids, experiments)

    assert plan.proposal_count == count
    assert len(plan.jobs) == count
    assert plan.jobs[0].proposal_id == 'proposal-0000'
    assert plan.jobs[-1].proposal_id == 'proposal-0299'
    assert plan.jobs[-1].output_relative_path == ('archives/proposal-0299.archive.json')


def test_length_mismatch_rejects():
    with pytest.raises(ValueError, match='equal length'):
        plan_archive_generation(['proposal-0001'], [])


def test_non_string_proposal_id_rejects():
    with pytest.raises(ValueError, match='non-empty string'):
        plan_archive_generation([''], [_experiment()])


def test_source_paths_are_canonical_relative(tmp_path):
    plan = plan_archive_generation(
        ['proposal-0001'],
        [_experiment(raw=['D356\\Initial Data\\a.csv'])],
    )

    assert plan.jobs[0].source_paths == ('D356/Initial Data/a.csv',)


def test_plan_does_not_write_or_overwrite(tmp_path):
    out_dir = tmp_path / 'archives'
    out_dir.mkdir()
    existing = out_dir / 'proposal-0001.archive.json'
    existing.write_text('existing', encoding='utf-8')

    plan = plan_archive_generation(
        ['proposal-0001'],
        [_experiment()],
        output_root=tmp_path,
    )

    assert existing.read_text(encoding='utf-8') == 'existing'
    assert plan.errors


def test_module_has_no_nomad_coupling():
    source = Path('src/lab_data/ingestion/archive_generation.py').read_text(
        encoding='utf-8'
    )
    lowered = source.lower()

    assert 'nomad_uploader' not in lowered
    assert 'batch_upload' not in lowered
    assert 'import requests' not in lowered
