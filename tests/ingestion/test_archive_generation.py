"""Focused tests for the archive-generation job model."""

import dataclasses
from pathlib import Path

import pytest

from lab_data.ingestion.archive_generation import ArchiveGenerationJob


def _job(**overrides):
    values = {
        'proposal_id': 'proposal-0001',
        'source_paths': (
            'D356/Initial Data/a.csv',
            'D356/Processed Data/a_PL.dat',
        ),
        'output_relative_path': 'archives/proposal-0001.archive.json',
        'sample_id': 'D356',
        'experiment_id': None,
    }
    values.update(overrides)
    return ArchiveGenerationJob(**values)


def test_job_is_frozen_and_immutable():
    job = _job()

    with pytest.raises(dataclasses.FrozenInstanceError):
        job.proposal_id = 'other'


def test_deterministic_identity_and_ordering():
    first = _job()
    second = _job()

    assert first == second
    assert first.proposal_id == 'proposal-0001'
    assert first.source_paths == (
        'D356/Initial Data/a.csv',
        'D356/Processed Data/a_PL.dat',
    )
    assert first.source_count == 2  # noqa: PLR2004


def test_source_order_is_preserved():
    job = _job(
        source_paths=(
            'D356/Processed Data/a_PL.dat',
            'D356/Initial Data/a.csv',
        )
    )

    assert job.source_paths == (
        'D356/Processed Data/a_PL.dat',
        'D356/Initial Data/a.csv',
    )


@pytest.mark.parametrize(
    'path',
    [
        '',
        '../escape.csv',
        'D356/../../escape.csv',
        '/absolute.csv',
        r'C:\absolute.csv',
        r'\\NAS\share\file.csv',
    ],
)
def test_unsafe_source_paths_reject(path):
    with pytest.raises(ValueError):
        _job(source_paths=(path,))


@pytest.mark.parametrize(
    'path',
    [
        '',
        '../escape.archive.json',
        '/absolute.archive.json',
        r'C:\absolute.archive.json',
    ],
)
def test_unsafe_output_paths_reject(path):
    with pytest.raises(ValueError):
        _job(output_relative_path=path)


def test_relative_paths_are_canonicalized_to_forward_slash():
    job = _job(
        source_paths=(
            'D356\\Initial Data\\a.csv',
            'D356/Processed Data/a_PL.dat',
        ),
        output_relative_path='archives\\proposal-0001.archive.json',
    )

    assert job.source_paths == (
        'D356/Initial Data/a.csv',
        'D356/Processed Data/a_PL.dat',
    )
    assert job.output_relative_path == 'archives/proposal-0001.archive.json'


def test_sample_and_experiment_identity_are_preserved():
    job = _job(sample_id='YZ247', experiment_id='exp-42')

    assert job.sample_id == 'YZ247'
    assert job.experiment_id == 'exp-42'


def test_invalid_identity_values_reject():
    with pytest.raises(ValueError):
        _job(proposal_id='')
    with pytest.raises(ValueError):
        _job(sample_id='')
    with pytest.raises(ValueError):
        _job(experiment_id='')


def test_source_paths_must_be_sequence():
    with pytest.raises(TypeError):
        _job(source_paths='D356/Initial Data/a.csv')


def test_module_has_no_nomad_or_inventory_coupling():
    source = Path('src/lab_data/ingestion/archive_generation.py').read_text(
        encoding='utf-8'
    )
    lowered = source.lower()

    assert 'inventory_store' not in lowered
    assert 'inventory_scan' not in lowered
    assert 'nomad_uploader' not in lowered
    assert 'batch_upload' not in lowered
    assert 'requests' not in lowered
    assert 'import uuid' not in lowered
    assert 'open(' not in lowered
