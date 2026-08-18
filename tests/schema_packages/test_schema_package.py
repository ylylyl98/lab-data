import os

import pytest
from nomad.client import normalize_all, parse

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

EXPECTED_TEMPERATURE = 3.6
EXPECTED_MAGNETIC_FIELD = 9
EXPECTED_GRATING = 1200
EXPECTED_GATE_COUNT = 2
BG_VOLTAGE = 1.5
BG_COEFFICIENT = -1.8
EXPECTED_TERM_COUNT = 2
EXPECTED_CONSTRAINT_COUNT = 2
EXPECTED_CONNECTION_COUNT = 2
TOP_GATE_VOLTAGE = -1.5
BIAS_MAGNITUDE = 8.0
CENTER_WAVELENGTH = 700
EXCITATION_WAVELENGTH = 532
INTEGRATION_TIME = 2
INTEGRATION_TIME_SHORT = 0.06
AVERAGES = 10
ROTATIONS = [1195.8, 295.0]
STAGE_POSITION = 50
EXPECTED_SAME_ROLE_FILE_COUNT = 4
EXPECTED_LEGACY_FILE_COUNT = 2
EXPECTED_PROVENANCE_COUNT = 2
EXPECTED_LINEAGE_COUNT = 2
REVIEW_CONFIDENCE = 0.8
REVIEW_CONFIDENCE_LOW = 0.5
REVIEW_CONFIDENCE_HIGH = 0.9


def test_schema_package():
    test_file = os.path.join('tests', 'data', 'test.archive.yaml')

    entry_archive = parse(test_file)[0]
    normalize_all(entry_archive)

    data = entry_archive.data

    assert data.experiment_id == 'TEST-001'
    assert data.sample_id == 'D356'
    assert data.measurement_type == 'photocurrent'
    assert data.temperature.magnitude == EXPECTED_TEMPERATURE
    assert data.magnetic_field.magnitude == EXPECTED_MAGNETIC_FIELD
    assert data.polarization == 'sigma_plus'
    assert data.instrument == 'WinSpec'
    assert data.grating.magnitude == EXPECTED_GRATING


def test_gate_value_voltage():
    gate = GateValue(gate='TG', voltage=0.0)

    assert gate.gate == 'TG'
    assert gate.voltage.magnitude == 0.0
    assert str(gate.voltage.units) == 'volt'


def test_multiple_fixed_gate_values_preserved_independently():
    experiment = OpticalExperiment()
    experiment.fixed_gate_values = [
        GateValue(gate='TG', voltage=0.0),
        GateValue(gate='BG', voltage=1.5),
    ]

    assert len(experiment.fixed_gate_values) == EXPECTED_GATE_COUNT
    assert experiment.fixed_gate_values[0].gate == 'TG'
    assert experiment.fixed_gate_values[0].voltage.magnitude == 0.0
    assert experiment.fixed_gate_values[1].gate == 'BG'
    assert experiment.fixed_gate_values[1].voltage.magnitude == BG_VOLTAGE


def test_existing_fields_remain_usable_with_gate_values():
    experiment = OpticalExperiment(
        experiment_id='TEST-002',
        sample_id='D356',
        measurement_type='photocurrent',
        temperature=EXPECTED_TEMPERATURE,
        magnetic_field=EXPECTED_MAGNETIC_FIELD,
        polarization='sigma_plus',
        instrument='WinSpec',
        grating=EXPECTED_GRATING,
        fixed_gate_values=[GateValue(gate='TG', voltage=0.0)],
    )

    assert experiment.experiment_id == 'TEST-002'
    assert experiment.sample_id == 'D356'
    assert experiment.measurement_type == 'photocurrent'
    assert experiment.temperature.magnitude == EXPECTED_TEMPERATURE
    assert experiment.magnetic_field.magnitude == EXPECTED_MAGNETIC_FIELD
    assert experiment.polarization == 'sigma_plus'
    assert experiment.instrument == 'WinSpec'
    assert experiment.grating.magnitude == EXPECTED_GRATING
    assert experiment.fixed_gate_values[0].gate == 'TG'


def test_gate_term_coefficients():
    tg = GateTerm(node='TG', coefficient=1.0)
    bg = GateTerm(node='BG', coefficient=BG_COEFFICIENT)

    assert tg.node == 'TG'
    assert tg.coefficient == 1.0
    assert bg.node == 'BG'
    assert bg.coefficient == BG_COEFFICIENT


def _constraint(raw_expression, control_mode, constant, terms):
    return GateConstraint(
        raw_expression=raw_expression,
        control_mode=control_mode,
        constant=constant,
        terms=[GateTerm(node=node, coefficient=coefficient) for node, coefficient in terms],
    )


def test_gate_constraint_repeated_terms():
    constraint = _constraint(
        raw_expression='TG + BG = 0',
        control_mode='constant_doping',
        constant=0.0,
        terms=[('TG', 1.0), ('BG', 1.0)],
    )

    assert len(constraint.terms) == EXPECTED_TERM_COUNT
    assert constraint.terms[0].node == 'TG'
    assert constraint.terms[0].coefficient == 1.0
    assert constraint.terms[1].node == 'BG'
    assert constraint.terms[1].coefficient == 1.0


def test_gate_constraint_exact_raw_expression_and_control_modes():
    cases = [
        ('TG + BG = 0', 'constant_doping', [('TG', 1.0), ('BG', 1.0)]),
        ('TG - BG = 0', 'constant_displacement_field', [('TG', 1.0), ('BG', -1.0)]),
        ('0.7TG + BG = 0', 'constant_doping', [('TG', 0.7), ('BG', 1.0)]),
        ('TG - 1.8BG = 0', 'constant_displacement_field', [('TG', 1.0), ('BG', BG_COEFFICIENT)]),
        ('BG1 + BG2 = 0', 'constant_doping', [('BG1', 1.0), ('BG2', 1.0)]),
        ('BG1 - BG2 = 0', 'constant_displacement_field', [('BG1', 1.0), ('BG2', -1.0)]),
    ]

    for raw_expression, control_mode, terms in cases:
        constraint = _constraint(
            raw_expression=raw_expression,
            control_mode=control_mode,
            constant=0.0,
            terms=terms,
        )
        assert constraint.raw_expression == raw_expression
        assert constraint.control_mode == control_mode
        assert constraint.constant == 0.0
        assert [(t.node, t.coefficient) for t in constraint.terms] == terms


def test_multiple_gate_constraints_on_one_experiment():
    experiment = OpticalExperiment()
    experiment.gate_constraints = [
        _constraint('TG + BG = 0', 'constant_doping', 0.0, [('TG', 1.0), ('BG', 1.0)]),
        _constraint('BG1 - BG2 = 0', 'constant_displacement_field', 0.0, [('BG1', 1.0), ('BG2', -1.0)]),
    ]

    assert len(experiment.gate_constraints) == EXPECTED_CONSTRAINT_COUNT
    assert experiment.gate_constraints[0].raw_expression == 'TG + BG = 0'
    assert experiment.gate_constraints[1].control_mode == 'constant_displacement_field'


def test_existing_gate_value_and_schema_quantities_still_usable():
    experiment = OpticalExperiment(
        experiment_id='TEST-003',
        temperature=EXPECTED_TEMPERATURE,
        fixed_gate_values=[GateValue(gate='TG', voltage=0.0)],
        gate_constraints=[
            _constraint('TG + BG = 0', 'constant_doping', 0.0, [('TG', 1.0), ('BG', 1.0)]),
        ],
    )

    assert experiment.fixed_gate_values[0].gate == 'TG'
    assert experiment.fixed_gate_values[0].voltage.magnitude == 0.0
    assert experiment.temperature.magnitude == EXPECTED_TEMPERATURE
    assert experiment.gate_constraints[0].raw_expression == 'TG + BG = 0'


def test_electrical_connection_bg2_cg():
    connection = ElectricalConnection(
        nodes=['BG2', 'CG'],
        type='electrically_tied',
        source_role='bias_source',
        raw_expression='BG2-CG',
    )

    assert connection.nodes == ['BG2', 'CG']
    assert connection.type == 'electrically_tied'
    assert connection.source_role == 'bias_source'
    assert connection.raw_expression == 'BG2-CG'


def test_electrical_connection_multiple_nodes_and_connections_on_experiment():
    experiment = OpticalExperiment()
    experiment.electrical_connections = [
        ElectricalConnection(
            nodes=['BG2', 'CG'],
            type='electrically_tied',
            source_role='bias_source',
            raw_expression='BG2-CG',
        ),
        ElectricalConnection(
            nodes=['BG1', 'CG'],
            type='electrically_tied',
            source_role='bias_source',
            raw_expression='BG1-CG',
        ),
    ]

    assert len(experiment.electrical_connections) == EXPECTED_CONNECTION_COUNT
    assert experiment.electrical_connections[0].nodes == ['BG2', 'CG']
    assert experiment.electrical_connections[1].nodes == ['BG1', 'CG']
    assert experiment.electrical_connections[1].raw_expression == 'BG1-CG'


def test_electrical_connections_separate_from_gate_constraints():
    experiment = OpticalExperiment()
    experiment.electrical_connections = [
        ElectricalConnection(
            nodes=['BG2', 'CG'],
            type='electrically_tied',
            source_role='bias_source',
            raw_expression='BG2-CG',
        ),
    ]
    experiment.gate_constraints = [
        _constraint('TG + BG = 0', 'constant_doping', 0.0, [('TG', 1.0), ('BG', 1.0)]),
    ]

    assert len(experiment.electrical_connections) == 1
    assert len(experiment.gate_constraints) == 1
    assert experiment.electrical_connections[0].raw_expression == 'BG2-CG'
    assert experiment.gate_constraints[0].raw_expression == 'TG + BG = 0'


def test_fixed_top_gate_voltage():
    experiment = OpticalExperiment(fixed_top_gate=TOP_GATE_VOLTAGE)

    assert experiment.fixed_top_gate.magnitude == TOP_GATE_VOLTAGE
    assert str(experiment.fixed_top_gate.units) == 'volt'


def test_active_gate_configuration_tg_and_bg1():
    cases = ['TG_only', 'BG1_only']

    for configuration in cases:
        experiment = OpticalExperiment(active_gate_configuration=configuration)
        assert experiment.active_gate_configuration == configuration


def test_sweep_direction_reverse():
    experiment = OpticalExperiment(sweep_direction='reverse')

    assert experiment.sweep_direction == 'reverse'


def test_sweep_direction_absent_is_null():
    experiment = OpticalExperiment()

    assert experiment.sweep_direction is None


def test_signed_bias_endpoints():
    forward = OpticalExperiment(bias_start=BIAS_MAGNITUDE, bias_stop=-BIAS_MAGNITUDE)
    reverse = OpticalExperiment(bias_start=-BIAS_MAGNITUDE, bias_stop=BIAS_MAGNITUDE)

    assert forward.bias_start.magnitude == BIAS_MAGNITUDE
    assert forward.bias_stop.magnitude == -BIAS_MAGNITUDE
    assert reverse.bias_start.magnitude == -BIAS_MAGNITUDE
    assert reverse.bias_stop.magnitude == BIAS_MAGNITUDE
    assert str(forward.bias_start.units) == 'volt'


def test_back_gate_topology_single_and_split():
    for topology in ['single', 'split']:
        experiment = OpticalExperiment(back_gate_topology=topology)
        assert experiment.back_gate_topology == topology


def test_measurement_point_label_p1n1_exact_opaque():
    experiment = OpticalExperiment(measurement_point_label='p1n1')

    assert experiment.measurement_point_label == 'p1n1'


def test_measurement_point_label_px_exact_opaque():
    experiment = OpticalExperiment(measurement_point_label='pX')

    assert experiment.measurement_point_label == 'pX'


def test_center_wavelength_distinct_from_excitation_wavelength():
    experiment = OpticalExperiment(
        center_wavelength=CENTER_WAVELENGTH,
        excitation_wavelength=EXCITATION_WAVELENGTH,
    )

    assert experiment.center_wavelength.magnitude == CENTER_WAVELENGTH
    assert str(experiment.center_wavelength.units) == 'nanometer'
    assert experiment.excitation_wavelength.magnitude == EXCITATION_WAVELENGTH
    assert experiment.center_wavelength.magnitude != experiment.excitation_wavelength.magnitude


def test_integration_time_two_seconds():
    experiment = OpticalExperiment(integration_time=INTEGRATION_TIME)

    assert experiment.integration_time.magnitude == INTEGRATION_TIME
    assert str(experiment.integration_time.units) == 'second'


def test_integration_time_sixty_milliseconds():
    experiment = OpticalExperiment(integration_time=INTEGRATION_TIME_SHORT)

    assert experiment.integration_time.magnitude == INTEGRATION_TIME_SHORT
    assert str(experiment.integration_time.units) == 'second'


def test_averages():
    experiment = OpticalExperiment(averages=AVERAGES)

    assert experiment.averages == AVERAGES


def test_rotations_preserve_order():
    experiment = OpticalExperiment(rotations=ROTATIONS)

    assert list(experiment.rotations.magnitude) == ROTATIONS


def test_stage_position_unitless():
    experiment = OpticalExperiment(stage_position=STAGE_POSITION)

    assert experiment.stage_position == STAGE_POSITION


def test_absent_optional_fields_remain_none():
    experiment = OpticalExperiment()

    assert experiment.measurement_point_label is None
    assert experiment.center_wavelength is None
    assert experiment.integration_time is None
    assert experiment.averages is None
    assert experiment.rotations is None
    assert experiment.stage_position is None


def test_optional_acquisition_fields_coexist_with_electrical_and_original_fields():
    experiment = OpticalExperiment(
        experiment_id='TEST-004',
        sample_id='D356',
        measurement_type='photocurrent',
        temperature=EXPECTED_TEMPERATURE,
        magnetic_field=EXPECTED_MAGNETIC_FIELD,
        polarization='sigma_plus',
        instrument='WinSpec',
        grating=EXPECTED_GRATING,
        measurement_point_label='p1n1',
        center_wavelength=CENTER_WAVELENGTH,
        integration_time=INTEGRATION_TIME,
        averages=AVERAGES,
        rotations=ROTATIONS,
        stage_position=STAGE_POSITION,
        fixed_top_gate=TOP_GATE_VOLTAGE,
        fixed_gate_values=[GateValue(gate='TG', voltage=0.0)],
        gate_constraints=[
            _constraint('TG + BG = 0', 'constant_doping', 0.0, [('TG', 1.0), ('BG', 1.0)]),
        ],
        electrical_connections=[
            ElectricalConnection(
                nodes=['BG2', 'CG'],
                type='electrically_tied',
                source_role='bias_source',
                raw_expression='BG2-CG',
            ),
        ],
    )

    assert experiment.experiment_id == 'TEST-004'
    assert experiment.temperature.magnitude == EXPECTED_TEMPERATURE
    assert experiment.measurement_point_label == 'p1n1'
    assert experiment.center_wavelength.magnitude == CENTER_WAVELENGTH
    assert experiment.integration_time.magnitude == INTEGRATION_TIME
    assert experiment.averages == AVERAGES
    assert list(experiment.rotations.magnitude) == ROTATIONS
    assert experiment.stage_position == STAGE_POSITION
    assert experiment.fixed_top_gate.magnitude == TOP_GATE_VOLTAGE
    assert experiment.fixed_gate_values[0].gate == 'TG'
    assert experiment.gate_constraints[0].raw_expression == 'TG + BG = 0'
    assert experiment.electrical_connections[0].raw_expression == 'BG2-CG'


def test_experiment_file_instantiates_each_role():
    roles = ['raw', 'intermediate', 'processed', 'figure']

    for role in roles:
        file = ExperimentFile(path='data/sample.txt', role=role)
        assert file.role == role
        assert file.path == 'data/sample.txt'


def test_experiment_file_all_four_roles_coexist():
    experiment = OpticalExperiment()
    experiment.files = [
        ExperimentFile(path='raw/sample.dat', role='raw'),
        ExperimentFile(path='intermediate/sample.npy', role='intermediate'),
        ExperimentFile(path='processed/sample.csv', role='processed'),
        ExperimentFile(path='figures/sample.png', role='figure'),
    ]

    assert [f.role for f in experiment.files] == ['raw', 'intermediate', 'processed', 'figure']


def test_experiment_file_multiple_same_role_files():
    experiment = OpticalExperiment()
    experiment.files = [
        ExperimentFile(path='raw/a.dat', role='raw'),
        ExperimentFile(path='raw/b.dat', role='raw'),
        ExperimentFile(path='processed/a.csv', role='processed'),
        ExperimentFile(path='processed/b.csv', role='processed'),
    ]

    assert len(experiment.files) == EXPECTED_SAME_ROLE_FILE_COUNT
    assert [f.path for f in experiment.files] == [
        'raw/a.dat',
        'raw/b.dat',
        'processed/a.csv',
        'processed/b.csv',
    ]
    assert all(f.role in ('raw', 'processed') for f in experiment.files)


def test_experiment_file_preserves_exact_relative_path():
    path = '../data/2026-08-17/measurement/sample 01.DAT'
    file = ExperimentFile(path=path, role='raw')

    assert file.path == path


def test_intermediate_and_figure_distinct_from_processed():
    experiment = OpticalExperiment()
    experiment.files = [
        ExperimentFile(path='intermediate/norm.npy', role='intermediate'),
        ExperimentFile(path='processed/final.csv', role='processed'),
        ExperimentFile(path='figures/plot.pdf', role='figure'),
    ]

    roles = {f.path: f.role for f in experiment.files}
    assert roles['intermediate/norm.npy'] == 'intermediate'
    assert roles['processed/final.csv'] == 'processed'
    assert roles['figures/plot.pdf'] == 'figure'
    assert roles['intermediate/norm.npy'] != roles['processed/final.csv']
    assert roles['figures/plot.pdf'] != roles['processed/final.csv']


def test_legacy_raw_and_processed_data_files_remain_usable_with_files():
    experiment = OpticalExperiment(
        raw_data_file='raw/legacy.dat',
        processed_data_file='processed/legacy.csv',
        files=[
            ExperimentFile(path='raw/legacy.dat', role='raw'),
            ExperimentFile(path='processed/legacy.csv', role='processed'),
        ],
    )

    assert experiment.raw_data_file == 'raw/legacy.dat'
    assert experiment.processed_data_file == 'processed/legacy.csv'
    assert len(experiment.files) == EXPECTED_LEGACY_FILE_COUNT


def test_files_coexist_with_existing_schema_fields():
    experiment = OpticalExperiment(
        experiment_id='TEST-005',
        temperature=EXPECTED_TEMPERATURE,
        fixed_gate_values=[GateValue(gate='TG', voltage=0.0)],
        gate_constraints=[
            _constraint('TG + BG = 0', 'constant_doping', 0.0, [('TG', 1.0), ('BG', 1.0)]),
        ],
        electrical_connections=[
            ElectricalConnection(
                nodes=['BG2', 'CG'],
                type='electrically_tied',
                source_role='bias_source',
                raw_expression='BG2-CG',
            ),
        ],
        files=[ExperimentFile(path='raw/sample.dat', role='raw')],
    )

    assert experiment.experiment_id == 'TEST-005'
    assert experiment.temperature.magnitude == EXPECTED_TEMPERATURE
    assert experiment.fixed_gate_values[0].gate == 'TG'
    assert experiment.gate_constraints[0].raw_expression == 'TG + BG = 0'
    assert experiment.electrical_connections[0].raw_expression == 'BG2-CG'
    assert experiment.files[0].role == 'raw'


def test_experiment_file_invalid_role_rejected_by_enum_validation():
    with pytest.raises(ValueError):
        ExperimentFile(path='data/sample.txt', role='bogus')


def test_metadata_provenance_string_serialized_numeric_values():
    provenance = MetadataProvenance(
        field='temperature',
        value='3.6',
        source_type='manual',
        source='lab notebook',
        method='direct',
    )

    assert provenance.field == 'temperature'
    assert provenance.value == '3.6'
    assert provenance.source_type == 'manual'
    assert provenance.source == 'lab notebook'
    assert provenance.method == 'direct'


def test_metadata_provenance_string_serialized_list_values():
    provenance = MetadataProvenance(
        field='rotations',
        value='[1195.8, 295.0]',
        source_type='parser',
        source='winspec',
        method='scan_header',
    )

    assert provenance.value == '[1195.8, 295.0]'
    assert provenance.source_type == 'parser'


def test_multiple_metadata_provenance_entries_on_experiment():
    experiment = OpticalExperiment()
    experiment.metadata_provenance = [
        MetadataProvenance(
            field='temperature',
            value='3.6',
            source_type='manual',
            source='lab notebook',
            method='direct',
        ),
        MetadataProvenance(
            field='grating',
            value='1200',
            source_type='parser',
            source='winspec',
            method='scan_header',
        ),
    ]

    assert len(experiment.metadata_provenance) == EXPECTED_PROVENANCE_COUNT
    assert experiment.metadata_provenance[0].field == 'temperature'
    assert experiment.metadata_provenance[0].value == '3.6'
    assert experiment.metadata_provenance[1].field == 'grating'
    assert experiment.metadata_provenance[1].value == '1200'


def test_lineage_raw_to_processed_and_processed_to_figure():
    experiment = OpticalExperiment()
    experiment.lineage = [
        LineageEdge(source='raw/sample.dat', target='processed/sample.csv', relation='derived_from'),
        LineageEdge(source='processed/sample.csv', target='figures/sample.png', relation='visualized_as'),
    ]

    assert len(experiment.lineage) == EXPECTED_LINEAGE_COUNT
    assert experiment.lineage[0].source == 'raw/sample.dat'
    assert experiment.lineage[0].target == 'processed/sample.csv'
    assert experiment.lineage[0].relation == 'derived_from'
    assert experiment.lineage[1].source == 'processed/sample.csv'
    assert experiment.lineage[1].target == 'figures/sample.png'
    assert experiment.lineage[1].relation == 'visualized_as'


def test_ingestion_review_multiple_warnings_and_confidence():
    review = IngestionReview(
        warnings=['missing instrument', 'ambiguous unit'],
        confidence=REVIEW_CONFIDENCE,
        needs_review=True,
    )

    assert list(review.warnings) == ['missing instrument', 'ambiguous unit']
    assert review.confidence == REVIEW_CONFIDENCE
    assert review.needs_review is True


def test_ingestion_review_absent_needs_review_is_none():
    review = IngestionReview(warnings=['missing instrument'], confidence=REVIEW_CONFIDENCE_LOW)

    assert review.needs_review is None
    assert review.confidence == REVIEW_CONFIDENCE_LOW
    assert list(review.warnings) == ['missing instrument']


def test_ingestion_review_single_subsection_on_experiment():
    experiment = OpticalExperiment()
    experiment.ingestion_review = IngestionReview(
        warnings=['missing instrument'],
        confidence=REVIEW_CONFIDENCE_HIGH,
        needs_review=True,
    )

    assert experiment.ingestion_review.warnings[0] == 'missing instrument'
    assert experiment.ingestion_review.confidence == REVIEW_CONFIDENCE_HIGH
    assert experiment.ingestion_review.needs_review is True


def test_existing_structures_unchanged_with_new_subsections():
    experiment = OpticalExperiment(
        experiment_id='TEST-006',
        temperature=EXPECTED_TEMPERATURE,
        fixed_gate_values=[GateValue(gate='TG', voltage=0.0)],
        gate_constraints=[
            _constraint('TG + BG = 0', 'constant_doping', 0.0, [('TG', 1.0), ('BG', 1.0)]),
        ],
        electrical_connections=[
            ElectricalConnection(
                nodes=['BG2', 'CG'],
                type='electrically_tied',
                source_role='bias_source',
                raw_expression='BG2-CG',
            ),
        ],
        files=[ExperimentFile(path='raw/sample.dat', role='raw')],
    )

    assert experiment.experiment_id == 'TEST-006'
    assert experiment.temperature.magnitude == EXPECTED_TEMPERATURE
    assert experiment.fixed_gate_values[0].gate == 'TG'
    assert experiment.gate_constraints[0].raw_expression == 'TG + BG = 0'
    assert experiment.electrical_connections[0].raw_expression == 'BG2-CG'
    assert experiment.files[0].role == 'raw'
