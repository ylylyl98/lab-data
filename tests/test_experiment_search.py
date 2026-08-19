import copy

import pytest

from lab_data.experiment_search import (
    NumericRange,
    build_search_index,
    find_related_files,
    get_experiment,
    search_experiments,
)
from lab_data.ingestion.proposal import (
    ElectricalConnection,
    ExperimentImportProposal,
    GateConstraint,
    LineageEdge,
)

EXPECTED_WIRING_MATCHES = 2


def _proposal(
    sample_id,
    measurement_type,
    *,
    electrical='BG2-CG',
    constraint='BG2-CG=0',
):
    return ExperimentImportProposal(
        sample_id=sample_id,
        measurement_type=measurement_type,
        raw_files=[f'raw/{sample_id}.dat'],
        processed_files=[f'processed/{sample_id}.csv'],
        lineage=[
            LineageEdge(
                source=f'raw/{sample_id}.dat',
                target=f'processed/{sample_id}.csv',
                relation='derived_from',
            )
        ],
        electrical_connections=[
            ElectricalConnection(
                raw_expression=electrical,
                nodes=['BG2', 'CG'],
                type='electrically_tied',
                source_role='bias_source',
            )
        ],
        gate_constraints=[
            GateConstraint(
                raw_expression=constraint,
                coefficients={
                    'BG2': 1.0,
                    'CG': -1.0,
                }
                if constraint == 'BG2-CG=0'
                else {
                    'BG1': 1.0,
                    'BG2': 1.0,
                }
                if constraint == 'BG1+BG2=0'
                else {
                    'BG1': 1.0,
                    'BG2': -1.0,
                },
                control_mode='constant_doping',
            )
        ],
    )


def test_search_is_deterministic_exact_and_does_not_mutate_proposals():
    proposals = [_proposal('D357', 'transport'), _proposal('D356', 'optical')]
    before = copy.deepcopy(proposals)
    index = build_search_index(proposals, experiment_ids=('exp-b', 'exp-a'))

    result = search_experiments(index, filters={'sample_id': 'D356'})
    assert [item.experiment_id for item in result] == ['exp-a']
    assert result[0].metadata['electrical_connections'][0]['raw_expression'] == 'BG2-CG'
    assert proposals == before
    assert search_experiments(index) == tuple(
        sorted(
            index.records,
            key=lambda item: (
                item.metadata['sample_id'],
                item.metadata['measurement_type'],
                item.experiment_id,
            ),
        )
    )


def test_get_missing_and_related_files_are_read_only_role_lineage_primitives():
    index = build_search_index(
        [_proposal('D356', 'optical')], experiment_ids=('exp-1',)
    )

    assert get_experiment(index, 'missing') is None
    files = find_related_files(index, 'exp-1', role='raw')
    assert len(files) == 1
    assert files[0].path == 'raw/D356.dat'
    assert files[0].role == 'raw'
    assert files[0].lineage[0].relation == 'derived_from'
    with pytest.raises(ValueError, match='unknown file role'):
        find_related_files(index, 'exp-1', role='unknown')


def test_duplicate_ids_are_rejected_and_structured_values_stay_exact():
    with pytest.raises(ValueError, match='duplicate experiment IDs'):
        build_search_index(
            [_proposal('D356', 'optical')] * 2, experiment_ids=('x', 'x')
        )

    plus = _proposal('D356', 'optical', constraint='BG1+BG2=0')
    minus = _proposal('D357', 'optical', constraint='BG1-BG2=0')
    index = build_search_index([plus, minus], experiment_ids=('plus', 'minus'))
    assert (
        len(
            search_experiments(
                index,
                filters={
                    'gate_constraints': [
                        {
                            'raw_expression': 'BG1+BG2=0',
                            'coefficients': {'BG1': 1.0, 'BG2': 1.0},
                            'control_mode': 'constant_doping',
                            'sweep_direction': None,
                        }
                    ]
                },
            )
        )
        == 1
    )
    assert [
        item.experiment_id
        for item in search_experiments(
            index,
            filters={
                'gate_constraints': [
                    {
                        'raw_expression': 'BG1-BG2=0',
                        'coefficients': {'BG1': 1.0, 'BG2': -1.0},
                        'control_mode': 'constant_doping',
                        'sweep_direction': None,
                    }
                ]
            },
        )
    ] == ['minus']
    assert (
        len(
            search_experiments(
                index,
                filters={
                    'electrical_connections': [
                        {
                            'raw_expression': 'BG2-CG',
                            'nodes': ['BG2', 'CG'],
                            'type': 'electrically_tied',
                            'source_role': 'bias_source',
                        }
                    ]
                },
            )
        )
        == EXPECTED_WIRING_MATCHES
    )
    assert (
        len(
            search_experiments(
                index,
                filters={
                    'gate_constraints': [
                        {
                            'raw_expression': 'BG2-CG=0',
                            'coefficients': {'BG2': 1.0, 'CG': -1.0},
                            'control_mode': 'constant_doping',
                            'sweep_direction': None,
                        }
                    ]
                },
            )
        )
        == 0
    )


def test_ids_are_required_and_canonical_filters_work_on_empty_index():
    with pytest.raises(ValueError, match='experiment_ids are required'):
        build_search_index([])
    empty = build_search_index([], experiment_ids=())
    assert search_experiments(empty, filters={'temperature_K': 3.6}) == ()


def test_sparse_metadata_filters_are_missing_safe():
    index = build_search_index(
        [ExperimentImportProposal(sample_id='D1', measurement_type='transport')],
        experiment_ids=('one',),
    )
    assert search_experiments(index, filters={'temperature_K': 3.6}) == ()
    assert (
        search_experiments(index, filters={'temperature_K': NumericRange(3, 4)}) == ()
    )


def test_direct_index_construction_is_immutable_and_validates_records():
    index = build_search_index([_proposal('D356', 'optical')], experiment_ids=('one',))
    records = list(index.records)
    records.clear()
    assert len(index.records) == 1
    with pytest.raises(ValueError, match='duplicate experiment IDs'):
        type(index)(records=(index.records[0], index.records[0]))


def test_numeric_ranges_are_strict_structured_filters():
    first = _proposal('D356', 'optical')
    first.temperature_K = 3.6
    first.magnetic_field_T = 9.0
    second = _proposal('D357', 'optical')
    second.temperature_K = 4.2
    second.magnetic_field_T = 2.0
    index = build_search_index([first, second], experiment_ids=('one', 'two'))
    assert [
        item.experiment_id
        for item in search_experiments(
            index, filters={'temperature_K': NumericRange(3, 4)}
        )
    ] == ['one']
    assert [
        item.experiment_id
        for item in search_experiments(
            index, filters={'magnetic_field_T': NumericRange(maximum=2)}
        )
    ] == ['two']
    with pytest.raises(ValueError, match='minimum must not exceed'):
        NumericRange(4, 3)
    with pytest.raises(ValueError, match='finite'):
        NumericRange(float('nan'))
    with pytest.raises(ValueError, match='numeric ranges'):
        search_experiments(index, filters={'sample_id': NumericRange(1, 2)})
