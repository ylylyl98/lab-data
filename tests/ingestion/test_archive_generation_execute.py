"""Focused tests for local archive-generation execution."""

from pathlib import Path

from lab_data.ingestion.archive_generation import (
    execute_archive_generation,
    plan_archive_generation,
)
from lab_data.ingestion.proposal import (
    ExperimentImportProposal,
    LineageEdge,
    MetadataProvenance,
)
from lab_data.ingestion.scanner import ElectricalConnection


def _experiment(**overrides):
    values = {
        'sample_id': 'D356',
        'measurement_type': 'photoluminescence',
        'temperature_K': 3.6,
        'magnetic_field_T': 9.0,
        'excitation_wavelength_nm': 633.0,
        'center_wavelength_nm': 700.0,
        'integration_time_s': 2.0,
        'averages': 1,
        'grating_grooves_per_mm': 300,
        'raw_files': ['Initial Data/D356_3.6K_9T_633nm_PL.csv'],
        'processed_files': ['Processed Data/D356_3.6K_9T_633nm_PL.dat'],
        'figure_files': ['Processed Data/D356_3.6K_9T_633nm_PL_linear.png'],
        'lineage': [
            LineageEdge(
                source='Processed Data/D356_3.6K_9T_633nm_PL.dat',
                target='Processed Data/D356_3.6K_9T_633nm_PL_linear.png',
                relation='visualization_of',
            )
        ],
        'metadata_provenance': [
            MetadataProvenance(
                field='temperature_K',
                value=3.6,
                source_type='filename',
                source='Initial Data/D356_3.6K_9T_633nm_PL.csv',
                method='deterministic',
            )
        ],
        'confidence': 0.8,
        'needs_review': False,
    }
    values.update(overrides)
    return ExperimentImportProposal(**values)


def test_successful_generation_and_read_back(tmp_path):
    output_root = tmp_path / 'out'
    output_root.mkdir()
    experiment = _experiment()
    plan = plan_archive_generation(['proposal-0001'], [experiment])

    result = execute_archive_generation(
        plan,
        {'proposal-0001': experiment},
        output_root=output_root,
    )

    assert result.jobs_requested == 1
    assert result.jobs_succeeded == 1
    assert result.jobs_failed == 0
    assert result.failed_proposal_ids == ()
    assert result.errors == ()
    assert result.output_paths == (
        str(output_root / 'archives' / 'proposal-0001.archive.json'),
    )
    assert (output_root / 'archives' / 'proposal-0001.archive.json').is_file()


def test_identity_file_membership_and_review_are_preserved(tmp_path):
    output_root = tmp_path / 'out'
    output_root.mkdir()
    experiment = _experiment(
        sample_id='YZ247',
        electrical_connections=[
            ElectricalConnection(
                raw_expression='BG2-CG',
                nodes=['BG2', 'CG'],
                type='electrically_tied',
                source_role='bias_source',
            )
        ],
    )
    plan = plan_archive_generation(['proposal-0001'], [experiment])

    result = execute_archive_generation(
        plan,
        {'proposal-0001': experiment},
        output_root=output_root,
    )

    assert result.jobs_succeeded == 1
    import json

    payload = json.loads(
        (output_root / 'archives' / 'proposal-0001.archive.json').read_text(
            encoding='utf-8'
        )
    )
    data = payload['data']
    assert data['sample_id'] == 'YZ247'
    assert data['measurement_type'] == 'photoluminescence'
    assert data['files'][0]['role'] == 'raw'
    assert data['ingestion_review']['needs_review'] is False
    assert data['electrical_connections'][0]['nodes'] == ['BG2', 'CG']
    assert data['lineage'][0]['relation'] == 'visualization_of'
    assert len(data['metadata_provenance']) > 0


def test_one_mocked_failure_is_isolated(tmp_path, monkeypatch):
    output_root = tmp_path / 'out'
    output_root.mkdir()
    experiment = _experiment()
    plan = plan_archive_generation(
        ['proposal-0001', 'proposal-0002'],
        [experiment, _experiment(sample_id='D357')],
    )

    import lab_data.ingestion.archive_generation as module

    original = module.build_optical_experiment

    def failing_builder(draft):
        if draft.sample.sample_id == 'D357':
            raise RuntimeError('mocked failure')
        return original(draft)

    monkeypatch.setattr(module, 'build_optical_experiment', failing_builder)

    result = execute_archive_generation(
        plan,
        {'proposal-0001': experiment, 'proposal-0002': _experiment(sample_id='D357')},
        output_root=output_root,
    )

    assert result.jobs_requested == 2  # noqa: PLR2004
    assert result.jobs_succeeded == 1
    assert result.jobs_failed == 1
    assert result.failed_proposal_ids == ('proposal-0002',)
    assert result.errors[0].proposal_id == 'proposal-0002'
    assert (output_root / 'archives' / 'proposal-0001.archive.json').is_file()
    assert not (output_root / 'archives' / 'proposal-0002.archive.json').exists()


def test_existing_output_is_not_overwritten(tmp_path):
    output_root = tmp_path / 'out'
    output_root.mkdir()
    target_dir = output_root / 'archives'
    target_dir.mkdir()
    target = target_dir / 'proposal-0001.archive.json'
    target.write_text('existing', encoding='utf-8')
    experiment = _experiment()
    plan = plan_archive_generation(
        ['proposal-0001'],
        [experiment],
        output_root=output_root,
    )

    result = execute_archive_generation(
        plan,
        {'proposal-0001': experiment},
        output_root=output_root,
    )

    assert result.jobs_failed == 1
    assert result.failed_proposal_ids == ('proposal-0001',)
    assert target.read_text(encoding='utf-8') == 'existing'


def test_missing_experiment_is_attributable_failure(tmp_path):
    output_root = tmp_path / 'out'
    output_root.mkdir()
    plan = plan_archive_generation(['proposal-0001'], [_experiment()])

    result = execute_archive_generation(
        plan,
        {},
        output_root=output_root,
    )

    assert result.jobs_failed == 1
    assert result.errors[0].proposal_id == 'proposal-0001'


def test_module_has_no_nomad_coupling():
    source = Path('src/lab_data/ingestion/archive_generation.py').read_text(
        encoding='utf-8'
    )
    lowered = source.lower()

    assert 'requests' not in lowered
    assert 'nomad_uploader' not in lowered
    assert 'batch_upload' not in lowered
    assert 'inventory_store' not in lowered
    assert 'inventory_scan' not in lowered
    assert 'update_metadata_status' not in source
