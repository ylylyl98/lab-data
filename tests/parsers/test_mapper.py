"""Pass A tests for the ArchiveDraft -> OpticalExperiment scalar mapping."""

import json

import pytest

from lab_data.ingestion.archive_builder import (
    ArchiveDraft,
    ExperimentDraft,
    FileDraft,
    ReviewDraft,
    SampleDraft,
)
from lab_data.ingestion.proposal import LineageEdge as ProposalLineageEdge
from lab_data.ingestion.proposal import MetadataProvenance as ProposalProvenance
from lab_data.ingestion.scanner import ElectricalConnection, GateConstraint
from lab_data.parsers.mapper import build_optical_experiment
from lab_data.schema_packages.schema_package import OpticalExperiment

REVIEW_CONFIDENCE_WARNING = 0.75
REVIEW_CONFIDENCE_FULL = 0.9
REVIEW_CONFIDENCE_SOURCE = 0.8


def _draft(sample_id=None, **experiment_fields):
    return ArchiveDraft(
        sample=SampleDraft(sample_id=sample_id),
        experiment=ExperimentDraft(**experiment_fields),
    )


def _constraint(raw_expression, coefficients, control_mode=None):
    return GateConstraint(
        raw_expression=raw_expression,
        coefficients=dict(coefficients),
        control_mode=control_mode,
    )


def _connection(
    raw_expression='BG2-CG',
    nodes=('BG2', 'CG'),
    type='electrically_tied',
    source_role='bias_source',
):
    return ElectricalConnection(
        raw_expression=raw_expression,
        nodes=list(nodes),
        type=type,
        source_role=source_role,
    )


def test_minimal_mapping():
    draft = _draft(sample_id='S1')

    experiment = build_optical_experiment(draft)

    assert isinstance(experiment, OpticalExperiment)
    assert experiment.sample_id == 'S1'
    assert experiment.measurement_type is None
    assert experiment.temperature is None
    assert experiment.sweep_direction is None


def test_d356_pl_like_scalar_metadata():
    draft = _draft(
        sample_id='D356',
        measurement_type='photoluminescence',
        measurement_point_label='p1n1',
        temperature_K=3.6,
        magnetic_field_T=9.0,
        excitation_wavelength_nm=532.0,
        center_wavelength_nm=700.0,
        excitation_power_uW=5.0,
        grating_grooves_per_mm=1200,
        rotations_deg=[1195.8, 295.0],
        stage_position=50,
        integration_time_s=2.0,
        averages=10,
    )

    experiment = build_optical_experiment(draft)

    assert experiment.sample_id == 'D356'
    assert experiment.measurement_type == 'photoluminescence'
    assert experiment.measurement_point_label == 'p1n1'
    assert experiment.temperature.magnitude == 3.6  # noqa: PLR2004
    assert experiment.magnetic_field.magnitude == 9.0  # noqa: PLR2004
    assert experiment.excitation_wavelength.magnitude == 532.0  # noqa: PLR2004
    assert experiment.center_wavelength.magnitude == 700.0  # noqa: PLR2004
    assert experiment.excitation_power.magnitude == 5.0  # noqa: PLR2004
    assert experiment.grating.magnitude == 1200.0  # noqa: PLR2004
    assert list(experiment.rotations.magnitude) == [1195.8, 295.0]
    assert experiment.stage_position == 50  # noqa: PLR2004
    assert experiment.integration_time.magnitude == 2.0  # noqa: PLR2004
    assert experiment.averages == 10  # noqa: PLR2004


def test_absorption_like_metadata():
    draft = _draft(
        sample_id='S2',
        measurement_type='absorption',
        temperature_K=77.0,
        excitation_wavelength_nm=633.0,
        grating_grooves_per_mm=600,
        integration_time_s=0.06,
        averages=1,
    )

    experiment = build_optical_experiment(draft)

    assert experiment.measurement_type == 'absorption'
    assert experiment.temperature.magnitude == 77.0  # noqa: PLR2004
    assert experiment.excitation_wavelength.magnitude == 633.0  # noqa: PLR2004
    assert experiment.grating.magnitude == 600.0  # noqa: PLR2004
    assert experiment.integration_time.magnitude == 0.06  # noqa: PLR2004
    assert experiment.averages == 1  # noqa: PLR2004


def test_unit_dimensions_preserved():
    draft = _draft(
        temperature_K=3.6,
        magnetic_field_T=9.0,
        excitation_wavelength_nm=532.0,
        center_wavelength_nm=700.0,
        excitation_power_uW=5.0,
        grating_grooves_per_mm=1200,
        rotations_deg=[295.0],
        fixed_top_gate_V=-1.5,
        bias_start_V=8.0,
        bias_stop_V=-8.0,
        integration_time_s=2.0,
    )

    experiment = build_optical_experiment(draft)

    assert str(experiment.temperature.units) == 'kelvin'
    assert str(experiment.magnetic_field.units) == 'tesla'
    assert str(experiment.excitation_wavelength.units) == 'nanometer'
    assert str(experiment.center_wavelength.units) == 'nanometer'
    assert str(experiment.excitation_power.units) == 'microwatt'
    assert str(experiment.grating.units) == '1 / millimeter'
    assert str(experiment.rotations.units) == 'degree'
    assert str(experiment.fixed_top_gate.units) == 'volt'
    assert str(experiment.bias_start.units) == 'volt'
    assert str(experiment.bias_stop.units) == 'volt'
    assert str(experiment.integration_time.units) == 'second'


def test_signed_bias_endpoints():
    draft = _draft(bias_start_V=-8.0, bias_stop_V=8.0)

    experiment = build_optical_experiment(draft)

    assert experiment.bias_start.magnitude == -8.0  # noqa: PLR2004
    assert experiment.bias_stop.magnitude == 8.0  # noqa: PLR2004


def test_reverse_sweep_direction():
    draft = _draft(sweep_direction='reverse')

    experiment = build_optical_experiment(draft)

    assert experiment.sweep_direction == 'reverse'


def test_split_topology():
    draft = _draft(back_gate_topology='split')

    experiment = build_optical_experiment(draft)

    assert experiment.back_gate_topology == 'split'


def test_opaque_measurement_point_preserved():
    draft = _draft(measurement_point_label='pX')

    experiment = build_optical_experiment(draft)

    assert experiment.measurement_point_label == 'pX'


def test_null_optionals_absent():
    draft = _draft(sample_id='S3')

    experiment = build_optical_experiment(draft)

    assert experiment.measurement_type is None
    assert experiment.measurement_point_label is None
    assert experiment.temperature is None
    assert experiment.magnetic_field is None
    assert experiment.excitation_wavelength is None
    assert experiment.center_wavelength is None
    assert experiment.excitation_power is None
    assert experiment.grating is None
    assert experiment.rotations is None
    assert experiment.stage_position is None
    assert experiment.integration_time is None
    assert experiment.averages is None
    assert experiment.fixed_top_gate is None
    assert experiment.active_gate_configuration is None
    assert experiment.sweep_direction is None
    assert experiment.bias_start is None
    assert experiment.bias_stop is None
    assert experiment.back_gate_topology is None


def test_deterministic_repeated_calls():
    draft = _draft(
        sample_id='D356',
        measurement_type='photoluminescence',
        temperature_K=3.6,
        rotations_deg=[1195.8, 295.0],
    )

    first = build_optical_experiment(draft)
    second = build_optical_experiment(draft)

    assert first.sample_id == second.sample_id
    assert first.measurement_type == second.measurement_type
    assert first.temperature.magnitude == second.temperature.magnitude
    assert list(first.rotations.magnitude) == list(second.rotations.magnitude)


def test_source_draft_unchanged():
    draft = _draft(
        sample_id='D356',
        measurement_type='photoluminescence',
        rotations_deg=[1195.8, 295.0],
    )
    original_rotations = list(draft.experiment.rotations_deg)

    build_optical_experiment(draft)

    assert draft.sample.sample_id == 'D356'
    assert draft.experiment.measurement_type == 'photoluminescence'
    assert draft.experiment.rotations_deg == original_rotations


def test_fixed_gate_value_maps_with_voltage_unit():
    draft = _draft(fixed_gate_values={'TG': 0.0})

    experiment = build_optical_experiment(draft)

    assert len(experiment.fixed_gate_values) == 1
    assert experiment.fixed_gate_values[0].gate == 'TG'
    assert experiment.fixed_gate_values[0].voltage.magnitude == 0.0
    assert str(experiment.fixed_gate_values[0].voltage.units) == 'volt'


def test_multiple_fixed_gate_values_are_sorted_and_preserved():
    draft = _draft(fixed_gate_values={'TG': 0.0, 'BG': -1.5})

    experiment = build_optical_experiment(draft)

    assert [value.gate for value in experiment.fixed_gate_values] == ['BG', 'TG']
    assert [value.voltage.magnitude for value in experiment.fixed_gate_values] == [
        -1.5,
        0.0,
    ]


def test_fixed_gate_value_mapping_is_deterministic_and_non_mutating():
    draft = _draft(fixed_gate_values={'TG': 0.0, 'BG': 0.0})
    original_values = dict(draft.experiment.fixed_gate_values)

    first = build_optical_experiment(draft)
    second = build_optical_experiment(draft)

    assert [value.gate for value in first.fixed_gate_values] == ['BG', 'TG']
    assert [value.gate for value in second.fixed_gate_values] == ['BG', 'TG']
    assert draft.experiment.fixed_gate_values == original_values


def test_absent_or_empty_fixed_gate_values_stays_empty():
    absent = build_optical_experiment(_draft())
    empty = build_optical_experiment(_draft(fixed_gate_values={}))

    assert absent.fixed_gate_values == []
    assert empty.fixed_gate_values == []


@pytest.mark.parametrize(
    ('raw_expression', 'coefficients', 'expected_terms', 'control_mode'),
    [
        (
            'TG+BG=0',
            {'TG': 1.0, 'BG': 1.0},
            [('BG', 1.0), ('TG', 1.0)],
            'constant_doping',
        ),
        (
            'TG-BG=0',
            {'TG': 1.0, 'BG': -1.0},
            [('BG', -1.0), ('TG', 1.0)],
            'constant_displacement_field',
        ),
        (
            '0.7TG+BG=0',
            {'TG': 0.7, 'BG': 1.0},
            [('BG', 1.0), ('TG', 0.7)],
            'constant_doping',
        ),
        (
            'TG-1.8BG=0',
            {'TG': 1.0, 'BG': -1.8},
            [('BG', -1.8), ('TG', 1.0)],
            'constant_displacement_field',
        ),
        (
            'BG1+BG2=0',
            {'BG1': 1.0, 'BG2': 1.0},
            [('BG1', 1.0), ('BG2', 1.0)],
            None,
        ),
        (
            'BG1-BG2=0',
            {'BG1': 1.0, 'BG2': -1.0},
            [('BG1', 1.0), ('BG2', -1.0)],
            None,
        ),
    ],
)
def test_gate_constraint_mapping(
    raw_expression, coefficients, expected_terms, control_mode
):
    draft = _draft(
        gate_constraints=[
            _constraint(raw_expression, coefficients, control_mode)
        ],
    )

    experiment = build_optical_experiment(draft)

    assert len(experiment.gate_constraints) == 1
    constraint = experiment.gate_constraints[0]
    assert constraint.raw_expression == raw_expression
    assert constraint.control_mode == control_mode
    assert constraint.constant == 0.0
    assert [
        (term.node, term.coefficient) for term in constraint.terms
    ] == expected_terms


def test_multiple_gate_constraints_preserved_in_order():
    draft = _draft(
        gate_constraints=[
            _constraint('TG+BG=0', {'TG': 1.0, 'BG': 1.0}, 'constant_doping'),
            _constraint('BG1-BG2=0', {'BG1': 1.0, 'BG2': -1.0}),
        ],
    )

    experiment = build_optical_experiment(draft)

    assert [c.raw_expression for c in experiment.gate_constraints] == [
        'TG+BG=0',
        'BG1-BG2=0',
    ]


def test_gate_constraint_source_draft_unchanged():
    draft = _draft(
        gate_constraints=[
            _constraint('TG+BG=0', {'TG': 1.0, 'BG': 1.0}, 'constant_doping'),
        ],
    )
    original = list(draft.experiment.gate_constraints)

    build_optical_experiment(draft)

    assert draft.experiment.gate_constraints == original
    assert draft.experiment.gate_constraints[0].raw_expression == 'TG+BG=0'
    assert draft.experiment.gate_constraints[0].coefficients == {
        'TG': 1.0,
        'BG': 1.0,
    }


def test_constraints_only_draft_creates_no_electrical_connections():
    draft = _draft(
        gate_constraints=[
            _constraint('TG+BG=0', {'TG': 1.0, 'BG': 1.0}, 'constant_doping'),
        ],
    )

    experiment = build_optical_experiment(draft)

    assert experiment.electrical_connections == []


def test_bg2_cg_connection_maps_exact_fields():
    draft = _draft(electrical_connections=[_connection()])

    experiment = build_optical_experiment(draft)

    assert len(experiment.electrical_connections) == 1
    connection = experiment.electrical_connections[0]
    assert list(connection.nodes) == ['BG2', 'CG']
    assert connection.type == 'electrically_tied'
    assert connection.source_role == 'bias_source'
    assert connection.raw_expression == 'BG2-CG'


def test_multiple_connections_deterministic_repeated_runs():
    draft = _draft(
        electrical_connections=[
            _connection(),
            _connection(
                raw_expression='BG1-BG2',
                nodes=('BG1', 'BG2'),
                source_role='measurement_source',
            ),
        ],
    )

    first = build_optical_experiment(draft)
    second = build_optical_experiment(draft)

    assert [
        (list(connection.nodes), connection.type, connection.source_role,
         connection.raw_expression)
        for connection in first.electrical_connections
    ] == [
        (list(connection.nodes), connection.type, connection.source_role,
         connection.raw_expression)
        for connection in second.electrical_connections
    ]
    assert len(first.electrical_connections) == 2  # noqa: PLR2004
    assert [
        connection.raw_expression
        for connection in first.electrical_connections
    ] == ['BG2-CG', 'BG1-BG2']


def test_missing_optional_connection_fields_remain_absent():
    draft = _draft(
        electrical_connections=[
            ElectricalConnection(
                raw_expression=None,
                nodes=['BG2', 'CG'],
                type=None,
                source_role=None,
            ),
        ],
    )

    experiment = build_optical_experiment(draft)

    assert len(experiment.electrical_connections) == 1
    connection = experiment.electrical_connections[0]
    assert list(connection.nodes) == ['BG2', 'CG']
    assert connection.type is None
    assert connection.source_role is None
    assert connection.raw_expression is None


def test_absent_or_empty_connections_stays_empty():
    absent = build_optical_experiment(_draft())
    empty = build_optical_experiment(_draft(electrical_connections=[]))

    assert absent.electrical_connections == []
    assert empty.electrical_connections == []


def test_bg2_cg_connection_creates_no_gate_constraint():
    draft = _draft(electrical_connections=[_connection()])

    experiment = build_optical_experiment(draft)

    assert experiment.gate_constraints == []


def test_existing_gate_constraints_remain_alongside_connection():
    draft = _draft(
        gate_constraints=[
            _constraint('TG+BG=0', {'TG': 1.0, 'BG': 1.0}, 'constant_doping'),
        ],
        electrical_connections=[_connection()],
    )

    experiment = build_optical_experiment(draft)

    assert len(experiment.gate_constraints) == 1
    assert experiment.gate_constraints[0].raw_expression == 'TG+BG=0'
    assert len(experiment.electrical_connections) == 1
    assert experiment.electrical_connections[0].raw_expression == 'BG2-CG'


def test_connection_source_draft_unchanged():
    draft = _draft(electrical_connections=[_connection()])
    original = list(draft.experiment.electrical_connections)

    build_optical_experiment(draft)

    assert draft.experiment.electrical_connections == original
    assert draft.experiment.electrical_connections[0].raw_expression == 'BG2-CG'
    assert draft.experiment.electrical_connections[0].nodes == ['BG2', 'CG']
    assert draft.experiment.electrical_connections[0].type == 'electrically_tied'
    assert (
        draft.experiment.electrical_connections[0].source_role == 'bias_source'
    )


def _draft_with_files(
    raw=(),
    intermediate=(),
    processed=(),
    figure=(),
    **experiment_fields,
):
    return ArchiveDraft(
        sample=SampleDraft(),
        experiment=ExperimentDraft(**experiment_fields),
        files=FileDraft(
            raw_files=list(raw),
            intermediate_files=list(intermediate),
            processed_files=list(processed),
            figure_files=list(figure),
        ),
    )


def test_all_four_file_roles_are_mapped_in_order():
    draft = _draft_with_files(
        raw=['raw/01.DAT'],
        intermediate=['work/sub.npy'],
        processed=['out/final.csv'],
        figure=['out/plot.png'],
    )

    experiment = build_optical_experiment(draft)

    assert [(file.role, file.path) for file in experiment.files] == [
        ('raw', 'raw/01.DAT'),
        ('intermediate', 'work/sub.npy'),
        ('processed', 'out/final.csv'),
        ('figure', 'out/plot.png'),
    ]


def test_file_roles_follow_role_order_regardless_of_input():
    draft = _draft_with_files(
        raw=['r'],
        figure=['f'],
        processed=['p'],
        intermediate=['i'],
    )

    experiment = build_optical_experiment(draft)

    assert [file.role for file in experiment.files] == [
        'raw',
        'intermediate',
        'processed',
        'figure',
    ]


def test_within_role_files_sorted_lexically():
    draft = _draft_with_files(raw=['raw/b.DAT', 'raw/a.DAT', 'raw/c.DAT'])

    experiment = build_optical_experiment(draft)

    assert [file.path for file in experiment.files] == [
        'raw/a.DAT',
        'raw/b.DAT',
        'raw/c.DAT',
    ]
    assert [file.role for file in experiment.files] == ['raw', 'raw', 'raw']


def test_exact_relative_paths_are_preserved():
    expected = {
        'raw': '../Data/2026-08-17/sample 01.DAT',
        'processed': 'Processed Data/final result.csv',
    }
    draft = _draft_with_files(
        raw=[expected['raw']],
        processed=[expected['processed']],
    )

    experiment = build_optical_experiment(draft)

    assert {file.role: file.path for file in experiment.files} == expected


def test_intermediate_and_figure_roles_remain_distinct():
    draft = _draft_with_files(
        intermediate=['work/norm.npy'],
        processed=['out/final.csv'],
        figure=['out/plot.png'],
    )

    experiment = build_optical_experiment(draft)

    by_role = {file.role: file.path for file in experiment.files}
    assert by_role['intermediate'] == 'work/norm.npy'
    assert by_role['processed'] == 'out/final.csv'
    assert by_role['figure'] == 'out/plot.png'
    assert by_role['intermediate'] != by_role['processed']
    assert by_role['figure'] != by_role['processed']


def test_legacy_fields_use_first_sorted_raw_and_processed_path():
    draft = _draft_with_files(
        raw=['raw/z.DAT', 'raw/a.DAT'],
        processed=['out/y.csv', 'out/b.csv'],
    )

    experiment = build_optical_experiment(draft)

    assert experiment.raw_data_file == 'raw/a.DAT'
    assert experiment.processed_data_file == 'out/b.csv'


def test_figure_only_does_not_populate_processed_data_file():
    draft = _draft_with_files(figure=['out/plot.png'])

    experiment = build_optical_experiment(draft)

    assert [file.role for file in experiment.files] == ['figure']
    assert experiment.processed_data_file is None
    assert experiment.raw_data_file is None


def test_empty_raw_and_processed_leave_legacy_fields_absent():
    draft = _draft_with_files(
        intermediate=['work/sub.npy'],
        figure=['out/plot.png'],
    )

    experiment = build_optical_experiment(draft)

    assert experiment.raw_data_file is None
    assert experiment.processed_data_file is None


def test_raw_only_state():
    draft = _draft_with_files(raw=['raw/a.DAT', 'raw/b.DAT'])

    experiment = build_optical_experiment(draft)

    assert [file.role for file in experiment.files] == ['raw', 'raw']
    assert experiment.raw_data_file == 'raw/a.DAT'
    assert experiment.processed_data_file is None


def test_intermediate_only_state():
    draft = _draft_with_files(intermediate=['work/sub.npy'])

    experiment = build_optical_experiment(draft)

    assert [file.role for file in experiment.files] == ['intermediate']
    assert experiment.raw_data_file is None
    assert experiment.processed_data_file is None


def test_processed_plus_figure_state():
    draft = _draft_with_files(
        processed=['out/final.csv'],
        figure=['out/plot.png'],
    )

    experiment = build_optical_experiment(draft)

    assert [file.role for file in experiment.files] == ['processed', 'figure']
    assert experiment.processed_data_file == 'out/final.csv'
    assert experiment.raw_data_file is None


def test_file_mapping_does_not_mutate_source_draft():
    draft = _draft_with_files(
        raw=['raw/b.DAT', 'raw/a.DAT'],
        processed=['out/final.csv'],
    )
    raw_before = list(draft.files.raw_files)
    processed_before = list(draft.files.processed_files)

    build_optical_experiment(draft)

    assert draft.files.raw_files == raw_before == ['raw/b.DAT', 'raw/a.DAT']
    assert draft.files.processed_files == processed_before == ['out/final.csv']


def test_file_mapping_is_deterministic_across_repeated_calls():
    draft = _draft_with_files(
        raw=['raw/z.DAT', 'raw/a.DAT'],
        intermediate=['work/sub.npy'],
        processed=['out/y.csv', 'out/b.csv'],
        figure=['out/plot.png'],
    )

    first = build_optical_experiment(draft)
    second = build_optical_experiment(draft)

    def snapshot(experiment):
        return (
            [(file.role, file.path) for file in experiment.files],
            experiment.raw_data_file,
            experiment.processed_data_file,
        )

    assert snapshot(first) == snapshot(second)


def _draft_with_provenance(records, **experiment_fields):
    return ArchiveDraft(
        sample=SampleDraft(),
        experiment=ExperimentDraft(**experiment_fields),
        provenance=list(records),
    )


def _provenance(
    field='temperature_K',
    value=3.6,
    source_type='filename',
    source='data/exp.txt',
    method='deterministic',
):
    return ProposalProvenance(
        field=field,
        value=value,
        source_type=source_type,
        source=source,
        method=method,
    )


def test_provenance_numeric_value_serialized_as_json():
    draft = _draft_with_provenance([_provenance(value=3.6)])

    experiment = build_optical_experiment(draft)

    assert len(experiment.metadata_provenance) == 1
    record = experiment.metadata_provenance[0]
    assert record.field == 'temperature_K'
    assert record.value == '3.6'
    assert json.loads(record.value) == 3.6  # noqa: PLR2004


def test_provenance_json_string_value_serialized_with_quotes():
    draft = _draft_with_provenance([_provenance(value='photoluminescence')])

    experiment = build_optical_experiment(draft)

    assert experiment.metadata_provenance[0].value == '"photoluminescence"'
    assert json.loads(experiment.metadata_provenance[0].value) == (
        'photoluminescence'
    )


def test_provenance_list_value_serialized_without_spaces():
    draft = _draft_with_provenance([_provenance(value=[1195.8, 295.0])])

    experiment = build_optical_experiment(draft)

    assert experiment.metadata_provenance[0].value == '[1195.8,295.0]'
    assert json.loads(experiment.metadata_provenance[0].value) == [
        1195.8,
        295.0,
    ]


def test_provenance_dict_value_uses_stable_sorted_keys():
    draft = _draft_with_provenance(
        [_provenance(value={'b': 2, 'a': 1, 'c': [3, 1, 2]})]
    )

    experiment = build_optical_experiment(draft)

    assert experiment.metadata_provenance[0].value == '{"a":1,"b":2,"c":[3,1,2]}'
    assert json.loads(experiment.metadata_provenance[0].value) == {
        'a': 1,
        'b': 2,
        'c': [3, 1, 2],
    }


def test_provenance_bool_and_null_values_serialized_as_json():
    draft = _draft_with_provenance(
        [_provenance(field='a', value=True), _provenance(field='b', value=None)]
    )

    experiment = build_optical_experiment(draft)

    assert experiment.metadata_provenance[0].value == 'true'
    assert experiment.metadata_provenance[1].value == 'null'
    assert json.loads(experiment.metadata_provenance[0].value) is True
    assert json.loads(experiment.metadata_provenance[1].value) is None


def test_provenance_all_metadata_fields_preserved():
    draft = _draft_with_provenance(
        [
            _provenance(
                field='temperature_K',
                value=3.6,
                source_type='filename',
                source='data/exp.txt',
                method='deterministic',
            )
        ]
    )

    experiment = build_optical_experiment(draft)

    record = experiment.metadata_provenance[0]
    assert record.field == 'temperature_K'
    assert record.source_type == 'filename'
    assert record.source == 'data/exp.txt'
    assert record.method == 'deterministic'


def test_provenance_multiple_records_preserved_in_upstream_order():
    draft = _draft_with_provenance(
        [
            _provenance(field='first', value=1),
            _provenance(field='second', value='two'),
            _provenance(field='third', value=[3]),
        ]
    )

    experiment = build_optical_experiment(draft)

    assert [r.field for r in experiment.metadata_provenance] == [
        'first',
        'second',
        'third',
    ]
    assert [json.loads(r.value) for r in experiment.metadata_provenance] == [
        1,
        'two',
        [3],
    ]


def test_absent_or_empty_provenance_yields_no_sections():
    absent = build_optical_experiment(_draft_with_provenance([]))
    default = build_optical_experiment(_draft())

    assert absent.metadata_provenance == []
    assert default.metadata_provenance == []


def test_provenance_mapping_does_not_mutate_source():
    value = {'b': 2, 'a': 1}
    draft = _draft_with_provenance([_provenance(value=value)])
    original = list(draft.provenance)

    build_optical_experiment(draft)

    assert draft.provenance == original
    assert draft.provenance[0].value == value


def test_provenance_mapping_is_deterministic_across_repeated_calls():
    draft = _draft_with_provenance(
        [
            _provenance(field='a', value={'b': 2, 'a': 1}),
            _provenance(field='b', value=[3, 1, 2]),
        ]
    )

    first = build_optical_experiment(draft)
    second = build_optical_experiment(draft)

    def snapshot(experiment):
        return [
            (
                r.field,
                r.value,
                r.source_type,
                r.source,
                r.method,
            )
            for r in experiment.metadata_provenance
        ]

    assert snapshot(first) == snapshot(second)


def test_provenance_gate_constraint_object_serialized_recursively():
    constraint = GateConstraint(
        raw_expression='TG-BG=0',
        coefficients={'TG': 1.0, 'BG': -1.0},
        control_mode='constant_displacement_field',
        sweep_direction='reverse',
    )
    draft = _draft_with_provenance(
        [_provenance(field='gate_constraints', value=constraint)]
    )

    experiment = build_optical_experiment(draft)

    record = experiment.metadata_provenance[0]
    assert record.value == (
        '{"coefficients":{"BG":-1.0,"TG":1.0},'
        '"control_mode":"constant_displacement_field",'
        '"raw_expression":"TG-BG=0",'
        '"sweep_direction":"reverse"}'
    )
    assert json.loads(record.value) == {
        'raw_expression': 'TG-BG=0',
        'coefficients': {'TG': 1.0, 'BG': -1.0},
        'control_mode': 'constant_displacement_field',
        'sweep_direction': 'reverse',
    }


def test_provenance_list_of_gate_constraints_serialized():
    constraints = [
        GateConstraint('TG+BG=0', {'TG': 1.0, 'BG': 1.0}, 'constant_doping', None),
        GateConstraint('BG1-BG2=0', {'BG1': 1.0, 'BG2': -1.0}, None, None),
    ]
    draft = _draft_with_provenance(
        [_provenance(field='gate_constraints', value=constraints)]
    )

    experiment = build_optical_experiment(draft)

    record = experiment.metadata_provenance[0]
    expected = (
        '[{"coefficients":{"BG":1.0,"TG":1.0},'
        '"control_mode":"constant_doping",'
        '"raw_expression":"TG+BG=0",'
        '"sweep_direction":null},'
        '{"coefficients":{"BG1":1.0,"BG2":-1.0},'
        '"control_mode":null,'
        '"raw_expression":"BG1-BG2=0",'
        '"sweep_direction":null}]'
    )
    assert record.value == expected
    loaded = json.loads(record.value)
    assert loaded[0]['coefficients']['BG'] == 1.0  # noqa: PLR2004
    assert loaded[1]['coefficients']['BG2'] == -1.0  # noqa: PLR2004


def test_provenance_gate_constraint_preserves_signed_coefficients_and_none():
    constraint = GateConstraint(
        raw_expression='0.7TG+BG=0',
        coefficients={'TG': 0.7, 'BG': -1.8},
        control_mode='constant_displacement_field',
        sweep_direction=None,
    )
    draft = _draft_with_provenance(
        [_provenance(field='gate_constraints', value=constraint)]
    )

    experiment = build_optical_experiment(draft)

    value = json.loads(experiment.metadata_provenance[0].value)
    assert value['raw_expression'] == '0.7TG+BG=0'
    assert value['coefficients'] == {'TG': 0.7, 'BG': -1.8}
    assert value['control_mode'] == 'constant_displacement_field'
    assert value['sweep_direction'] is None


def test_provenance_nested_dataclass_list_dict_deterministic_json():
    value = {
        'z': GateConstraint(
            raw_expression='TG+BG=0',
            coefficients={'TG': 1.0, 'BG': -1.0},
            control_mode='constant_displacement_field',
            sweep_direction=None,
        ),
        'a': [1, {'nested': (2, 3.5)}],
    }
    draft = _draft_with_provenance([_provenance(field='nested', value=value)])

    first = build_optical_experiment(draft)
    second = build_optical_experiment(draft)

    serialized = first.metadata_provenance[0].value
    assert serialized == second.metadata_provenance[0].value
    loaded = json.loads(serialized)
    assert loaded['a'] == [1, {'nested': [2, 3.5]}]
    assert loaded['z']['coefficients'] == {'TG': 1.0, 'BG': -1.0}
    assert loaded['z']['sweep_direction'] is None


def test_provenance_gate_constraint_repeated_calls_deterministic():
    draft = _draft_with_provenance(
        [
            _provenance(
                field='gate_constraints',
                value=GateConstraint(
                    raw_expression='TG-BG=0',
                    coefficients={'TG': 1.0, 'BG': -1.0},
                    control_mode='constant_displacement_field',
                    sweep_direction='reverse',
                ),
            )
        ]
    )

    first = build_optical_experiment(draft)
    second = build_optical_experiment(draft)

    assert first.metadata_provenance[0].value == (
        second.metadata_provenance[0].value
    )


def test_provenance_gate_constraint_does_not_mutate_source():
    constraint = GateConstraint(
        raw_expression='TG+BG=0',
        coefficients={'TG': 1.0, 'BG': -1.0},
        control_mode='constant_doping',
        sweep_direction=None,
    )
    draft = _draft_with_provenance(
        [_provenance(field='gate_constraints', value=constraint)]
    )
    original = list(draft.provenance)

    build_optical_experiment(draft)

    assert draft.provenance == original
    assert draft.provenance[0].value is constraint
    assert constraint.raw_expression == 'TG+BG=0'
    assert constraint.coefficients == {'TG': 1.0, 'BG': -1.0}
    assert constraint.control_mode == 'constant_doping'
    assert constraint.sweep_direction is None


def test_provenance_unsupported_object_raises_clear_type_error():
    class Arbitrary:
        pass

    draft = _draft_with_provenance(
        [_provenance(field='bad', value=Arbitrary())]
    )

    with pytest.raises(TypeError, match='Arbitrary'):
        build_optical_experiment(draft)


def _draft_with_lineage(records, **experiment_fields):
    return ArchiveDraft(
        sample=SampleDraft(),
        experiment=ExperimentDraft(**experiment_fields),
        lineage=list(records),
    )


def _lineage(source='raw/01.DAT', target='processed/final.csv',
             relation='derived_from'):
    return ProposalLineageEdge(
        source=source,
        target=target,
        relation=relation,
    )


def test_lineage_raw_to_processed_edge_maps():
    draft = _draft_with_lineage(
        [_lineage(source='raw/01.DAT', target='processed/final.csv')]
    )

    experiment = build_optical_experiment(draft)

    assert len(experiment.lineage) == 1
    assert experiment.lineage[0].source == 'raw/01.DAT'
    assert experiment.lineage[0].target == 'processed/final.csv'
    assert experiment.lineage[0].relation == 'derived_from'


def test_lineage_processed_to_figure_edge_maps():
    draft = _draft_with_lineage(
        [_lineage(source='processed/final.csv', target='figure/plot.png')]
    )

    experiment = build_optical_experiment(draft)

    assert len(experiment.lineage) == 1
    assert experiment.lineage[0].source == 'processed/final.csv'
    assert experiment.lineage[0].target == 'figure/plot.png'
    assert experiment.lineage[0].relation == 'derived_from'


def test_lineage_exact_source_target_relation_preserved():
    draft = _draft_with_lineage(
        [
            _lineage(
                source='../Data/2026-08-17/sample 01.DAT',
                target='Processed Data/final result.csv',
                relation='transformed_by',
            )
        ]
    )

    experiment = build_optical_experiment(draft)

    edge = experiment.lineage[0]
    assert edge.source == '../Data/2026-08-17/sample 01.DAT'
    assert edge.target == 'Processed Data/final result.csv'
    assert edge.relation == 'transformed_by'


def test_lineage_multiple_edges_preserved_in_upstream_order():
    draft = _draft_with_lineage(
        [
            _lineage(source='raw/a.DAT', target='work/a.npy', relation='derived_from'),
            _lineage(source='work/a.npy', target='out/a.csv', relation='derived_from'),
            _lineage(source='out/a.csv', target='out/a.png', relation='derived_from'),
        ]
    )

    experiment = build_optical_experiment(draft)

    assert [
        (edge.source, edge.target, edge.relation)
        for edge in experiment.lineage
    ] == [
        ('raw/a.DAT', 'work/a.npy', 'derived_from'),
        ('work/a.npy', 'out/a.csv', 'derived_from'),
        ('out/a.csv', 'out/a.png', 'derived_from'),
    ]


def test_absent_or_empty_lineage_yields_no_edges():
    absent = build_optical_experiment(_draft_with_lineage([]))
    default = build_optical_experiment(_draft())

    assert absent.lineage == []
    assert default.lineage == []


def test_lineage_mapping_creates_no_extra_edges():
    draft = _draft_with_lineage(
        [_lineage(source='raw/01.DAT', target='processed/final.csv')]
    )

    experiment = build_optical_experiment(draft)

    assert len(experiment.lineage) == 1


def test_lineage_mapping_does_not_mutate_source():
    draft = _draft_with_lineage(
        [_lineage(source='raw/01.DAT', target='processed/final.csv')]
    )
    original = list(draft.lineage)

    build_optical_experiment(draft)

    assert draft.lineage == original
    assert draft.lineage[0].source == 'raw/01.DAT'
    assert draft.lineage[0].target == 'processed/final.csv'
    assert draft.lineage[0].relation == 'derived_from'


def test_lineage_mapping_is_deterministic_across_repeated_calls():
    draft = _draft_with_lineage(
        [
            _lineage(source='raw/a.DAT', target='work/a.npy'),
            _lineage(source='work/a.npy', target='out/a.csv'),
        ]
    )

    first = build_optical_experiment(draft)
    second = build_optical_experiment(draft)

    def snapshot(experiment):
        return [
            (edge.source, edge.target, edge.relation)
            for edge in experiment.lineage
        ]

    assert snapshot(first) == snapshot(second)


def _draft_with_review(review):
    return ArchiveDraft(
        sample=SampleDraft(),
        experiment=ExperimentDraft(),
        review=review,
    )


def test_review_single_warning_maps():
    draft = _draft_with_review(
        ReviewDraft(warnings=['temperature out of range'])
    )

    experiment = build_optical_experiment(draft)

    assert experiment.ingestion_review.warnings == ['temperature out of range']


def test_review_multiple_warnings_preserve_order_and_duplicates():
    draft = _draft_with_review(
        ReviewDraft(warnings=['first', 'second', 'first'])
    )

    experiment = build_optical_experiment(draft)

    assert experiment.ingestion_review.warnings == ['first', 'second', 'first']


def test_review_confidence_maps():
    draft = _draft_with_review(
        ReviewDraft(confidence=REVIEW_CONFIDENCE_WARNING)
    )

    experiment = build_optical_experiment(draft)

    assert experiment.ingestion_review.confidence == REVIEW_CONFIDENCE_WARNING


def test_review_needs_review_true_maps():
    draft = _draft_with_review(ReviewDraft(needs_review=True))

    experiment = build_optical_experiment(draft)

    assert experiment.ingestion_review.needs_review is True


def test_review_needs_review_false_is_explicitly_preserved():
    draft = _draft_with_review(ReviewDraft(needs_review=False))

    experiment = build_optical_experiment(draft)

    assert experiment.ingestion_review.needs_review is False


def test_review_missing_confidence_and_needs_review_stay_none():
    draft = _draft_with_review(
        ReviewDraft(warnings=['warn'], confidence=None, needs_review=None)
    )

    experiment = build_optical_experiment(draft)

    assert experiment.ingestion_review.warnings == ['warn']
    assert experiment.ingestion_review.confidence is None
    assert experiment.ingestion_review.needs_review is None


def test_review_empty_warnings_preserved():
    draft = _draft_with_review(ReviewDraft(warnings=[]))

    experiment = build_optical_experiment(draft)

    assert experiment.ingestion_review.warnings == []


def test_review_full_state_maps_all_fields():
    draft = _draft_with_review(
        ReviewDraft(
            warnings=['missing temperature', 'unusual power'],
            confidence=REVIEW_CONFIDENCE_FULL,
            needs_review=True,
        )
    )

    experiment = build_optical_experiment(draft)

    assert experiment.ingestion_review.warnings == [
        'missing temperature',
        'unusual power',
    ]
    assert experiment.ingestion_review.confidence == REVIEW_CONFIDENCE_FULL
    assert experiment.ingestion_review.needs_review is True


def test_review_explicit_clean_state_preserved():
    draft = _draft_with_review(ReviewDraft())

    experiment = build_optical_experiment(draft)

    assert experiment.ingestion_review.warnings == []
    assert experiment.ingestion_review.confidence == 0.0
    assert experiment.ingestion_review.needs_review is False


def test_review_mapping_does_not_mutate_source():
    draft = _draft_with_review(
        ReviewDraft(
            warnings=['first', 'second'],
            confidence=REVIEW_CONFIDENCE_SOURCE,
            needs_review=True,
        )
    )

    build_optical_experiment(draft)

    assert draft.review.warnings == ['first', 'second']
    assert draft.review.confidence == REVIEW_CONFIDENCE_SOURCE
    assert draft.review.needs_review is True


def test_review_mapping_is_deterministic_across_repeated_calls():
    draft = _draft_with_review(
        ReviewDraft(warnings=['a', 'b', 'a'], confidence=0.5, needs_review=False)
    )

    first = build_optical_experiment(draft)
    second = build_optical_experiment(draft)

    def snapshot(experiment):
        review = experiment.ingestion_review
        return (list(review.warnings), review.confidence, review.needs_review)

    assert snapshot(first) == snapshot(second)
