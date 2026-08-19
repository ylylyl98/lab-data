"""Focused tests for the read-only production batch-state reader."""

from dataclasses import replace
from pathlib import Path

import pytest

from lab_data.ingestion.batch_manifest import (
    ManifestFile,
    ManifestStatus,
    create_batch_manifest,
    write_batch_manifest,
)
from lab_data.ingestion.batch_planner import plan_batches
from lab_data.ingestion.production_batch_reader import (
    ProductionBatchState,
    read_production_batch_state,
)


def _manifest(status=ManifestStatus.PLANNED, upload_id=None, verification=None):
    planned = plan_batches(
        [f'YZ247-{i:04d}' for i in range(1, 4)],
        batch_size=50,
        dataset_label='YZ247',
    )[0]
    manifest = create_batch_manifest(
        planned,
        archive_files=tuple(
            ManifestFile(
                f'C:\\archives\\{pid}.archive.json',
                f'{pid}.archive.json',
                'archive',
            )
            for pid in planned.proposals
        ),
        companion_files=(),
        publish=False,
        upload_name='lab-data-YZ247-phase9-batch-001',
        created_utc='2026-08-18T00:00:00Z',
        updated_utc='2026-08-18T00:00:00Z',
    )
    manifest = replace(
        manifest,
        status=status,
        upload_id=upload_id,
        verification_status=verification,
    )
    return manifest


def test_reads_planned_batch_without_lifecycle(tmp_path):
    write_batch_manifest(_manifest(), tmp_path / 'batch-001.json')

    state = read_production_batch_state(tmp_path, 1)

    assert isinstance(state, ProductionBatchState)
    assert state.batch_number == 1
    assert state.batch_id.startswith('YZ247-batch-001-')
    assert (
        state.batch_id
        == plan_batches(
            [f'YZ247-{i:04d}' for i in range(1, 4)],
            batch_size=50,
            dataset_label='YZ247',
        )[0].batch_id
    )
    assert state.manifest_path == str(tmp_path / 'batch-001.json')
    assert state.preflight_manifest_path is None
    assert state.final_state_path is None
    assert state.upload_id is None
    assert state.status == 'planned'
    assert state.verification_status is None
    assert state.published is False
    assert state.item_count == 3  # noqa: PLR2004


def test_reads_preflight_and_final_state(tmp_path):
    write_batch_manifest(_manifest(), tmp_path / 'batch-001.json')
    write_batch_manifest(
        _manifest(status=ManifestStatus.PREFLIGHT_PASSED),
        tmp_path / 'batch-001.preflight_passed.json',
    )
    write_batch_manifest(
        _manifest(
            status=ManifestStatus.SUCCESS,
            upload_id='upload-1',
            verification='verified',
        ),
        tmp_path / 'batch-001.final.json',
    )

    state = read_production_batch_state(tmp_path, 1)

    assert state.preflight_manifest_path == str(
        tmp_path / 'batch-001.preflight_passed.json'
    )
    assert state.final_state_path == str(tmp_path / 'batch-001.final.json')
    assert state.upload_id == 'upload-1'
    assert state.status == 'success'
    assert state.verification_status == 'verified'
    assert state.item_count == 3  # noqa: PLR2004


def test_upload_created_precedes_preflight(tmp_path):
    write_batch_manifest(_manifest(), tmp_path / 'batch-001.json')
    write_batch_manifest(
        _manifest(status=ManifestStatus.PREFLIGHT_PASSED),
        tmp_path / 'batch-001.preflight_passed.json',
    )
    write_batch_manifest(
        _manifest(status=ManifestStatus.UPLOAD_CREATED, upload_id='upload-2'),
        tmp_path / 'batch-001.upload_created.json',
    )

    state = read_production_batch_state(tmp_path, 1)

    assert state.upload_id == 'upload-2'
    assert state.status == 'upload_created'
    assert state.final_state_path is None


def test_missing_manifest_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match='batch manifest not found'):
        read_production_batch_state(tmp_path, 1)


def test_missing_directory_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match='does not exist'):
        read_production_batch_state(tmp_path / 'missing', 1)


def test_invalid_batch_number(tmp_path):
    with pytest.raises(ValueError):
        read_production_batch_state(tmp_path, 0)
    with pytest.raises(TypeError):
        read_production_batch_state(tmp_path, True)  # type: ignore[arg-type]


def test_reader_does_not_write_files(tmp_path):
    write_batch_manifest(_manifest(), tmp_path / 'batch-001.json')
    before = {p.name for p in tmp_path.iterdir()}

    read_production_batch_state(tmp_path, 1)

    assert {p.name for p in tmp_path.iterdir()} == before


def test_module_has_no_nomad_or_network_coupling():
    source = Path('src/lab_data/ingestion/production_batch_reader.py').read_text(
        encoding='utf-8'
    )
    lowered = source.lower()

    assert 'import nomad' not in lowered
    assert 'from nomad' not in lowered
    assert 'requests' not in lowered
    assert 'nomad_uploader' not in lowered
    assert 'batch_upload' not in lowered
