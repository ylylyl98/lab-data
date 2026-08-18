"""Pass S1 tests for minimal EntryArchive construction and serialization."""

import json
from pathlib import Path

from nomad.datamodel import EntryArchive

from lab_data.parsers.archive_serializer import (
    build_entry_archive,
    serialize_entry_archive,
    write_entry_archive_json,
)
from lab_data.schema_packages.schema_package import (
    ElectricalConnection,
    ExperimentFile,
    GateConstraint,
    GateTerm,
    GateValue,
    IngestionReview,
    LineageEdge,
    MetadataProvenance,
    OpticalExperiment,
)


def _experiment(**fields):
    experiment = OpticalExperiment()
    for name, value in fields.items():
        setattr(experiment, name, value)
    return experiment


def test_build_entry_archive_wraps_experiment_as_data():
    experiment = _experiment(sample_id='S1')

    archive = build_entry_archive(experiment)

    assert isinstance(archive, EntryArchive)
    assert archive.data is experiment


def test_minimal_experiment_serializes_identity_fields():
    experiment = _experiment(
        sample_id='S1',
        measurement_type='photoluminescence',
    )

    serialized = serialize_entry_archive(build_entry_archive(experiment))

    assert serialized['data']['sample_id'] == 'S1'
    assert serialized['data']['measurement_type'] == 'photoluminescence'


def test_unit_quantity_value_survives_serialization():
    experiment = _experiment(
        sample_id='S1',
        measurement_type='photoluminescence',
        temperature=3.6,
    )

    serialized = serialize_entry_archive(build_entry_archive(experiment))

    assert serialized['data']['temperature'] == 3.6  # noqa: PLR2004


def test_serialized_dict_is_json_compatible():
    experiment = _experiment(
        sample_id='S1',
        measurement_type='photoluminescence',
        temperature=3.6,
    )

    serialized = serialize_entry_archive(build_entry_archive(experiment))

    json.dumps(serialized)  # must not raise


def test_repeated_serialization_is_deterministic():
    experiment = _experiment(
        sample_id='S1',
        measurement_type='photoluminescence',
        temperature=3.6,
    )
    archive = build_entry_archive(experiment)

    first = serialize_entry_archive(archive)
    second = serialize_entry_archive(archive)

    assert first == second


def test_source_experiment_is_not_mutated():
    experiment = _experiment(
        sample_id='S1',
        measurement_type='photoluminescence',
        temperature=3.6,
    )

    serialize_entry_archive(build_entry_archive(experiment))

    assert experiment.sample_id == 'S1'
    assert experiment.measurement_type == 'photoluminescence'
    assert experiment.temperature.magnitude == 3.6  # noqa: PLR2004


def test_nested_sections_and_units_serialize_losslessly():
    experiment = _experiment(
        sample_id='D356',
        measurement_type='photoluminescence',
        temperature=3.6,
        magnetic_field=9.0,
        excitation_wavelength=633.0,
        center_wavelength=700.0,
        excitation_power=5.0,
        integration_time=2.0,
        averages=10,
        grating=1200.0,
        rotations=[1195.8, 295.0],
        fixed_gate_values=[
            GateValue(gate='BG', voltage=0.0),
            GateValue(gate='TG', voltage=0.0),
        ],
        gate_constraints=[
            GateConstraint(
                raw_expression='TG-BG=0',
                control_mode='constant_displacement_field',
                constant=0.0,
                terms=[
                    GateTerm(node='BG', coefficient=-1.0),
                    GateTerm(node='TG', coefficient=1.0),
                ],
            )
        ],
        electrical_connections=[
            ElectricalConnection(
                nodes=['BG2', 'CG'],
                type='electrically_tied',
                source_role='bias_source',
                raw_expression='BG2-CG',
            )
        ],
        files=[
            ExperimentFile(path='raw/a.csv', role='raw'),
            ExperimentFile(path='work/a.csv', role='intermediate'),
            ExperimentFile(path='processed/a.dat', role='processed'),
            ExperimentFile(path='figures/a.png', role='figure'),
        ],
        metadata_provenance=[
            MetadataProvenance(
                field='temperature_K',
                value='3.6',
                source_type='filename',
                source='raw/a.csv',
                method='deterministic',
            )
        ],
        lineage=[
            LineageEdge(
                source='raw/a.csv',
                target='processed/a.dat',
                relation='derived_from',
            )
        ],
        ingestion_review=IngestionReview(
            warnings=['check calibration'],
            confidence=0.9,
            needs_review=False,
        ),
    )
    before = serialize_entry_archive(build_entry_archive(experiment))
    after = serialize_entry_archive(build_entry_archive(experiment))

    assert before == after
    data = before['data']
    assert data['temperature'] == 3.6  # noqa: PLR2004
    assert data['magnetic_field'] == 9.0  # noqa: PLR2004
    assert data['rotations'] == [1195.8, 295.0]
    assert data['fixed_gate_values'][0]['gate'] == 'BG'
    assert data['gate_constraints'][0]['terms'][0]['coefficient'] == -1.0
    assert data['electrical_connections'][0]['raw_expression'] == 'BG2-CG'
    assert {file['role'] for file in data['files']} == {
        'raw',
        'intermediate',
        'processed',
        'figure',
    }
    assert data['metadata_provenance'][0]['value'] == '3.6'
    assert data['lineage'][0]['relation'] == 'derived_from'
    assert data['ingestion_review']['needs_review'] is False
    assert experiment.temperature.magnitude == 3.6  # noqa: PLR2004


def test_write_entry_archive_json_writes_and_reads_back(tmp_path):
    experiment = _experiment(
        sample_id='S3',
        measurement_type='photoluminescence',
        metadata_provenance=[
            MetadataProvenance(
                field='temperature_K',
                value='3.6',
                source_type='filename',
                source='raw/a.csv',
                method='deterministic',
            )
        ],
    )
    output_path = tmp_path / 'archive.json'

    written = write_entry_archive_json(build_entry_archive(experiment), output_path)

    assert written == output_path
    assert isinstance(written, Path)
    with output_path.open(encoding='utf-8') as handle:
        payload = json.loads(handle.read())
    assert payload['data']['sample_id'] == 'S3'
    assert payload['data']['metadata_provenance'][0]['field'] == 'temperature_K'
    assert payload['data']['metadata_provenance'][0]['value'] == '3.6'


def test_write_entry_archive_json_accepts_str_path(tmp_path):
    experiment = _experiment(sample_id='S3')
    output_path = tmp_path / 'archive.json'

    written = write_entry_archive_json(build_entry_archive(experiment), str(output_path))

    assert written == output_path
    assert output_path.exists()


def test_write_entry_archive_json_is_deterministic(tmp_path):
    experiment = _experiment(
        sample_id='S3',
        measurement_type='photoluminescence',
        temperature=3.6,
    )
    archive = build_entry_archive(experiment)
    first_path = tmp_path / 'first.json'
    second_path = tmp_path / 'second.json'

    write_entry_archive_json(archive, first_path)
    write_entry_archive_json(archive, second_path)

    assert first_path.read_text(encoding='utf-8') == second_path.read_text(
        encoding='utf-8'
    )


def test_write_entry_archive_json_refuses_to_overwrite_existing_file(tmp_path):
    experiment = _experiment(sample_id='S3')
    output_path = tmp_path / 'archive.json'
    output_path.write_text('original', encoding='utf-8')

    try:
        write_entry_archive_json(build_entry_archive(experiment), output_path)
    except FileExistsError:
        pass
    else:
        raise AssertionError('expected FileExistsError')

    assert output_path.read_text(encoding='utf-8') == 'original'


def test_write_entry_archive_json_does_not_touch_source_dirs(tmp_path):
    source_dir = tmp_path / 'experiment'
    source_dir.mkdir()
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    experiment = _experiment(
        sample_id='S3',
        raw_data_file=str(data_dir / 'raw.csv'),
        files=[ExperimentFile(path=str(data_dir / 'raw.csv'), role='raw')],
    )
    output_path = tmp_path / 'archive.json'

    write_entry_archive_json(build_entry_archive(experiment), output_path)

    assert list(source_dir.iterdir()) == []
    assert list(data_dir.iterdir()) == []
    assert output_path.exists()


def test_serialize_entry_archive_writes_no_files(tmp_path):
    experiment = _experiment(sample_id='S3')

    serialize_entry_archive(build_entry_archive(experiment))
    build_entry_archive(experiment)

    assert list(tmp_path.iterdir()) == []
