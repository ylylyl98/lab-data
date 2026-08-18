import json

from lab_data.ingestion import proposal, scanner
from lab_data.ingestion.proposal import build_import_proposal
from lab_data.ingestion.scanner import (
    ElectricalConnection,
    ExperimentMetadata,
    ExperimentProposal,
    GateConstraint,
    ScanResult,
    scan_directory,
)


def _full_experiment() -> ExperimentProposal:
    """Build a synthetic scanner proposal with every field populated."""

    return ExperimentProposal(
        metadata=ExperimentMetadata(
            sample_id='D356',
            temperature_K=3.6,
            magnetic_field_T=9.0,
            excitation_wavelength_nm=633.0,
            measurement_type='photoluminescence',
            center_wavelength_nm=700.0,
            integration_time_s=2.0,
            averages=1,
            excitation_power_uW=0.03,
            grating_grooves_per_mm=300,
            rotations_deg=[45.0, 90.0],
            stage_position=50,
            measurement_point_label='p1n1',
            fixed_top_gate_V=-0.2,
            active_gate_configuration='TG_only',
            bias_start_V=0.0,
            bias_stop_V=20.0,
            back_gate_topology='single',
            gate_constraints=[
                GateConstraint(
                    raw_expression='TG+BG=0',
                    coefficients={'TG': 1.0, 'BG': 1.0},
                    control_mode='constant_doping',
                )
            ],
            electrical_connections=[
                ElectricalConnection(
                    raw_expression='BG2-CG',
                    nodes=['BG2', 'CG'],
                    type='electrically_tied',
                    source_role='bias_source',
                )
            ],
        ),
        raw_files=['Initial Data/D356_3.6K_9T_633nm_PL.csv'],
        processed_files=['Processed Data/D356_3.6K_9T_633nm_PL.dat'],
        figure_files=['Processed Data/D356_3.6K_9T_633nm_PL.png'],
        warnings=['conflicting temperature_K values: [3.6, 4.0]'],
        confidence=0.95,
    )


def _full_scan_result() -> ScanResult:
    return ScanResult(
        sample_id='D356',
        scan_root='/data/D356',
        experiments=[_full_experiment()],
        unclassified_files=['notes.txt'],
        warnings=['unsupported extension ".txt": notes.txt'],
    )


def test_build_import_proposal_preserves_scan_level_fields():
    source = _full_scan_result()

    result = build_import_proposal(source)

    assert result.scan_root == source.scan_root
    assert result.sample_id == source.sample_id
    assert result.unresolved_files == source.unclassified_files
    assert result.warnings == source.warnings


def test_all_metadata_fields_are_preserved():
    source = _full_scan_result()
    metadata = source.experiments[0].metadata

    experiment = build_import_proposal(source).experiments[0]

    assert experiment.sample_id == metadata.sample_id
    assert experiment.temperature_K == metadata.temperature_K
    assert experiment.magnetic_field_T == metadata.magnetic_field_T
    assert experiment.excitation_wavelength_nm == metadata.excitation_wavelength_nm
    assert experiment.measurement_type == metadata.measurement_type
    assert experiment.center_wavelength_nm == metadata.center_wavelength_nm
    assert experiment.integration_time_s == metadata.integration_time_s
    assert experiment.averages == metadata.averages
    assert experiment.excitation_power_uW == metadata.excitation_power_uW
    assert experiment.grating_grooves_per_mm == metadata.grating_grooves_per_mm
    assert experiment.rotations_deg == metadata.rotations_deg
    assert experiment.stage_position == metadata.stage_position
    assert experiment.fixed_top_gate_V == metadata.fixed_top_gate_V
    assert experiment.active_gate_configuration == metadata.active_gate_configuration
    assert experiment.bias_start_V == metadata.bias_start_V
    assert experiment.bias_stop_V == metadata.bias_stop_V
    assert experiment.back_gate_topology == metadata.back_gate_topology


def test_measurement_point_label_is_preserved():
    source = _full_scan_result()

    experiment = build_import_proposal(source).experiments[0]

    assert (
        experiment.measurement_point_label
        == source.experiments[0].metadata.measurement_point_label
    )
    assert experiment.measurement_point_label == 'p1n1'


def test_nested_gate_constraint_objects_are_preserved():
    experiment = build_import_proposal(_full_scan_result()).experiments[0]

    assert len(experiment.gate_constraints) == 1
    constraint = experiment.gate_constraints[0]
    assert constraint.raw_expression == 'TG+BG=0'
    assert constraint.coefficients == {'TG': 1.0, 'BG': 1.0}
    assert constraint.control_mode == 'constant_doping'


def test_nested_electrical_connection_objects_are_preserved():
    experiment = build_import_proposal(_full_scan_result()).experiments[0]

    assert len(experiment.electrical_connections) == 1
    connection = experiment.electrical_connections[0]
    assert connection.raw_expression == 'BG2-CG'
    assert connection.nodes == ['BG2', 'CG']
    assert connection.type == 'electrically_tied'
    assert connection.source_role == 'bias_source'


def test_file_roles_and_paths_are_preserved():
    experiment = build_import_proposal(_full_scan_result()).experiments[0]

    assert experiment.raw_files == ['Initial Data/D356_3.6K_9T_633nm_PL.csv']
    assert experiment.processed_files == [
        'Processed Data/D356_3.6K_9T_633nm_PL.dat'
    ]
    assert experiment.figure_files == [
        'Processed Data/D356_3.6K_9T_633nm_PL.png'
    ]


def _experiment_with_intermediate(intermediate, raw=None, processed=None):
    return ExperimentProposal(
        metadata=ExperimentMetadata(),
        raw_files=raw if raw is not None else [],
        processed_files=processed if processed is not None else [],
        figure_files=[],
        intermediate_files=intermediate,
        warnings=[],
        confidence=0.0,
    )


def test_intermediate_files_are_preserved():
    experiment = _single_experiment(
        _experiment_with_intermediate(
            ['Intermediate Data/D356_sub.csv'],
            raw=['Initial Data/D356.csv'],
            processed=['Processed Data/D356_PL.dat'],
        )
    )

    assert experiment.intermediate_files == ['Intermediate Data/D356_sub.csv']


def test_intermediate_files_serialize_in_json():
    result = build_import_proposal(
        ScanResult(
            experiments=[
                _experiment_with_intermediate(
                    ['Intermediate Data/D356_sub.csv']
                )
            ]
        )
    )

    payload = json.loads(result.to_json())

    assert payload['experiments'][0]['intermediate_files'] == [
        'Intermediate Data/D356_sub.csv'
    ]


def test_raw_and_intermediate_without_processed_remain_unreviewed():
    experiment = _single_experiment(
        _experiment_with_intermediate(
            ['Intermediate Data/D356_sub.csv'],
            raw=['Initial Data/D356.csv'],
        )
    )

    assert experiment.intermediate_files == ['Intermediate Data/D356_sub.csv']
    assert experiment.processed_files == []
    assert experiment.needs_review is False


def test_no_review_due_solely_to_missing_counterpart():
    experiment = _single_experiment(
        _proposal(raw=['Initial Data/D356.csv'])
    )

    assert experiment.raw_files == ['Initial Data/D356.csv']
    assert experiment.intermediate_files == []
    assert experiment.processed_files == []
    assert experiment.needs_review is False


def test_raw_intermediate_only_with_separate_processed_experiment_unreviewed():
    result = build_import_proposal(
        ScanResult(
            experiments=[
                _experiment_with_intermediate(
                    ['Intermediate Data/D356_sub.csv'],
                    raw=['Initial Data/D356.csv'],
                ),
                _proposal(
                    raw=['Initial Data/D357.csv'],
                    processed=['Processed Data/D357_PL.dat'],
                ),
            ]
        )
    )

    raw_intermediate = result.experiments[0]
    assert raw_intermediate.intermediate_files == ['Intermediate Data/D356_sub.csv']
    assert raw_intermediate.processed_files == []
    assert raw_intermediate.needs_review is False


def test_experiment_warnings_and_confidence_are_preserved():
    source = _full_scan_result()

    experiment = build_import_proposal(source).experiments[0]

    assert experiment.warnings == source.experiments[0].warnings
    assert experiment.confidence == source.experiments[0].confidence


def test_placeholder_fields_are_empty():
    empty = ExperimentProposal(
        metadata=ExperimentMetadata(),
        raw_files=[],
        processed_files=[],
        figure_files=[],
        warnings=[],
        confidence=0.0,
    )
    experiment = build_import_proposal(
        ScanResult(experiments=[empty])
    ).experiments[0]

    assert experiment.lineage == []
    assert experiment.metadata_provenance == []
    assert experiment.unresolved_metadata == []
    assert experiment.unresolved_relationships == []
    assert experiment.needs_review is False


def _proposal(raw=None, processed=None, figure=None, warnings=None, metadata=None):
    return ExperimentProposal(
        metadata=metadata if metadata is not None else ExperimentMetadata(),
        raw_files=raw if raw is not None else [],
        processed_files=processed if processed is not None else [],
        figure_files=figure if figure is not None else [],
        warnings=warnings if warnings is not None else [],
        confidence=0.0,
    )


def _single_experiment(proposal):
    return build_import_proposal(
        ScanResult(experiments=[proposal])
    ).experiments[0]


def test_standard_pl_lineage_edges():
    experiment = _single_experiment(
        _proposal(
            raw=['Initial Data/D356.csv'],
            processed=['Processed Data/D356_PL.dat'],
            figure=[
                'Processed Data/D356_PL_linear.png',
                'Processed Data/D356_PL_log.png',
            ],
        )
    )

    edges = {(edge.source, edge.target, edge.relation) for edge in experiment.lineage}

    assert edges == {
        (
            'Initial Data/D356.csv',
            'Processed Data/D356_PL.dat',
            'derived_from',
        ),
        (
            'Processed Data/D356_PL.dat',
            'Processed Data/D356_PL_linear.png',
            'visualization_of',
        ),
        (
            'Processed Data/D356_PL.dat',
            'Processed Data/D356_PL_log.png',
            'visualization_of',
        ),
    }
    assert experiment.unresolved_relationships == []
    assert experiment.needs_review is False


def test_absorption_lineage_edges():
    experiment = _single_experiment(
        _proposal(
            raw=['Initial Data/D356.csv'],
            processed=['Processed Data/D356_avg2_DR_R_Self.dat'],
            figure=['Processed Data/D356_avg2_DR_R_Self_linear.png'],
        )
    )

    edges = {(edge.source, edge.target, edge.relation) for edge in experiment.lineage}

    assert edges == {
        (
            'Initial Data/D356.csv',
            'Processed Data/D356_avg2_DR_R_Self.dat',
            'derived_from',
        ),
        (
            'Processed Data/D356_avg2_DR_R_Self.dat',
            'Processed Data/D356_avg2_DR_R_Self_linear.png',
            'visualization_of',
        ),
    }


def test_unknown_suffix_has_no_lineage_and_preserves_unresolved():
    experiment = _single_experiment(
        _proposal(
            raw=['Initial Data/D356.csv'],
            processed=['Processed Data/D356_mystery.dat'],
        )
    )

    assert experiment.lineage == []
    assert any(
        entry['source_role'] == 'raw'
        and entry['source'] == 'Initial Data/D356.csv'
        and entry['target_role'] == 'processed'
        for entry in experiment.unresolved_relationships
    )
    assert experiment.needs_review is True


def test_provenance_includes_core_fields_with_filename_source():
    source = _full_scan_result()
    experiment = build_import_proposal(source).experiments[0]

    by_field = {item.field: item for item in experiment.metadata_provenance}

    assert 'temperature_K' in by_field
    assert 'sample_id' in by_field
    assert 'measurement_point_label' in by_field
    assert 'gate_constraints' in by_field
    assert 'electrical_connections' in by_field
    assert (
        by_field['temperature_K'].value
        == source.experiments[0].metadata.temperature_K
    )
    assert by_field['sample_id'].value == 'D356'
    assert by_field['measurement_point_label'].value == 'p1n1'
    for item in experiment.metadata_provenance:
        assert item.source_type == 'filename'
        assert item.method == 'deterministic'
        assert item.source == 'Initial Data/D356_3.6K_9T_633nm_PL.csv'


def test_scanner_warnings_set_needs_review():
    experiment = _single_experiment(_full_experiment())

    assert experiment.warnings
    assert experiment.needs_review is True


def test_clean_proposal_with_missing_optional_metadata_remains_unreviewed():
    experiment = _single_experiment(
        _proposal(
            metadata=ExperimentMetadata(
                sample_id='D356',
                measurement_type='photoluminescence',
            ),
            raw=['Initial Data/D356.csv'],
            processed=['Processed Data/D356_PL.dat'],
            figure=['Processed Data/D356_PL_linear.png'],
        )
    )

    assert experiment.temperature_K is None
    assert experiment.magnetic_field_T is None
    assert experiment.lineage
    assert experiment.needs_review is False


def test_json_serializes_nested_lineage_provenance_and_unresolved():
    result = build_import_proposal(_full_scan_result())

    payload = json.loads(result.to_json())
    experiment = payload['experiments'][0]

    relations = {edge['relation'] for edge in experiment['lineage']}
    assert 'derived_from' in relations
    assert 'visualization_of' in relations
    assert all(
        item['source_type'] == 'filename' and item['method'] == 'deterministic'
        for item in experiment['metadata_provenance']
    )
    assert 'unresolved_relationships' in experiment


def test_lineage_repeated_conversion_is_deterministic():
    source = _full_scan_result()

    first = build_import_proposal(source).experiments[0]
    second = build_import_proposal(source).experiments[0]

    assert first.lineage == second.lineage
    assert first.metadata_provenance == second.metadata_provenance
    assert first.unresolved_relationships == second.unresolved_relationships
    assert first.needs_review == second.needs_review


def test_to_json_is_serializable_and_stable():
    result = build_import_proposal(_full_scan_result())

    payload = json.loads(result.to_json())

    assert payload['sample_id'] == 'D356'
    assert payload['unresolved_files'] == ['notes.txt']
    experiment = payload['experiments'][0]
    assert experiment['measurement_point_label'] == 'p1n1'
    assert experiment['raw_files'] == ['Initial Data/D356_3.6K_9T_633nm_PL.csv']
    assert experiment['gate_constraints'][0]['coefficients'] == {
        'TG': 1.0,
        'BG': 1.0,
    }
    assert experiment['electrical_connections'][0]['nodes'] == ['BG2', 'CG']


def test_repeated_conversion_is_deterministic():
    source = _full_scan_result()

    first = build_import_proposal(source)
    second = build_import_proposal(source)

    assert first == second
    assert first.to_json() == second.to_json()


def test_conversion_does_not_mutate_source():
    source = _full_scan_result()

    build_import_proposal(source)

    assert source.experiments[0].raw_files == [
        'Initial Data/D356_3.6K_9T_633nm_PL.csv'
    ]
    assert source.unclassified_files == ['notes.txt']
    assert source.experiments[0].metadata.gate_constraints[0].coefficients == {
        'TG': 1.0,
        'BG': 1.0,
    }


def test_unresolved_files_are_copied_not_aliased():
    source = _full_scan_result()

    result = build_import_proposal(source)
    result.unresolved_files.append('extra.txt')

    assert source.unclassified_files == ['notes.txt']


def _write(path, content: str = '') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_build_from_tiny_temp_scan(tmp_path):
    _write(tmp_path / 'Initial Data' / 'D356_3.6K_9T_633nm_PL.csv')
    _write(tmp_path / 'Processed Data' / 'D356_3.6K_9T_633nm_PL.csv')
    _write(tmp_path / 'notes.txt')

    result = build_import_proposal(scan_directory(tmp_path))

    assert result.sample_id == 'D356'
    assert result.unresolved_files == ['notes.txt']
    assert len(result.experiments) == 1
    experiment = result.experiments[0]
    assert experiment.measurement_type == 'photoluminescence'
    assert experiment.rotations_deg is None
    assert experiment.raw_files == ['Initial Data/D356_3.6K_9T_633nm_PL.csv']
    assert experiment.processed_files == [
        'Processed Data/D356_3.6K_9T_633nm_PL.csv'
    ]


def test_proposal_module_exports_expected_names():
    assert proposal.ImportProposal is not None
    assert proposal.ExperimentImportProposal is not None
    assert proposal.build_import_proposal is build_import_proposal
    assert proposal.main is not None


def _file_set(root):
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob('*')
        if path.is_file()
    }


def _write_pl_tree(root):
    _write(root / 'Initial Data' / 'D356_3.6K_9T_633nm_PL.csv')
    _write(root / 'Processed Data' / 'D356_3.6K_9T_633nm_PL.dat')
    _write(root / 'Processed Data' / 'D356_3.6K_9T_633nm_PL_linear.png')


def _run_proposal_cli(path, capsys):
    code = proposal.main([str(path)])
    captured = capsys.readouterr()
    return code, captured


def test_proposal_cli_valid_output(tmp_path, capsys):
    _write_pl_tree(tmp_path)

    code, captured = _run_proposal_cli(tmp_path, capsys)

    assert code == 0
    assert captured.err == ''
    payload = json.loads(captured.out)
    assert payload['scan_root'] == str(tmp_path)
    assert payload['sample_id'] == 'D356'
    assert len(payload['experiments']) == 1


def test_proposal_cli_invalid_path_nonzero(tmp_path, capsys):
    missing = tmp_path / 'does-not-exist'

    code, captured = _run_proposal_cli(missing, capsys)

    assert code != 0
    assert captured.out == ''
    assert 'does not exist' in captured.err


def test_proposal_cli_not_a_directory_nonzero(tmp_path, capsys):
    target = tmp_path / 'a-file.txt'
    _write(target)

    code, captured = _run_proposal_cli(target, capsys)

    assert code != 0
    assert captured.out == ''
    assert 'not a directory' in captured.err


def test_proposal_cli_does_not_write_files(tmp_path, capsys):
    _write_pl_tree(tmp_path)
    before = _file_set(tmp_path)

    code, _ = _run_proposal_cli(tmp_path, capsys)

    assert code == 0
    assert _file_set(tmp_path) == before


def test_scanner_cli_still_usable(tmp_path, capsys):
    _write_pl_tree(tmp_path)

    code = scanner.main([str(tmp_path)])
    captured = capsys.readouterr()

    assert code == 0
    payload = json.loads(captured.out)
    assert payload['scan_root'] == str(tmp_path)
    assert payload['sample_id'] == 'D356'


def test_proposal_cli_standard_pl_json_roles_lineage_provenance(
    tmp_path, capsys
):
    _write_pl_tree(tmp_path)

    code, captured = _run_proposal_cli(tmp_path, capsys)

    assert code == 0
    experiment = json.loads(captured.out)['experiments'][0]
    assert experiment['raw_files'] == ['Initial Data/D356_3.6K_9T_633nm_PL.csv']
    assert experiment['processed_files'] == [
        'Processed Data/D356_3.6K_9T_633nm_PL.dat'
    ]
    assert experiment['figure_files'] == [
        'Processed Data/D356_3.6K_9T_633nm_PL_linear.png'
    ]
    relations = {edge['relation'] for edge in experiment['lineage']}
    assert 'derived_from' in relations
    assert 'visualization_of' in relations
    assert experiment['metadata_provenance']


def test_proposal_cli_absorption_json(tmp_path, capsys):
    _write(tmp_path / 'Initial Data' / 'D356.csv')
    _write(tmp_path / 'Processed Data' / 'D356_avg2_DR_R_Self.dat')
    _write(tmp_path / 'Processed Data' / 'D356_avg2_DR_R_Self_linear.png')

    code, captured = _run_proposal_cli(tmp_path, capsys)

    assert code == 0
    experiment = json.loads(captured.out)['experiments'][0]
    assert experiment['measurement_type'] == 'absorption'
    relations = {edge['relation'] for edge in experiment['lineage']}
    assert 'derived_from' in relations
    assert 'visualization_of' in relations


def test_proposal_cli_unknown_suffix_has_no_fabricated_lineage(
    tmp_path, capsys
):
    _write(tmp_path / 'Initial Data' / 'D356.csv')
    _write(tmp_path / 'Processed Data' / 'D356_mystery.dat')

    code, captured = _run_proposal_cli(tmp_path, capsys)

    assert code == 0
    experiments = json.loads(captured.out)['experiments']
    raw_experiment = experiments[0]
    assert raw_experiment['lineage'] == []
    assert raw_experiment['raw_files'] == ['Initial Data/D356.csv']
    assert raw_experiment['processed_files'] == []
    assert raw_experiment['needs_review'] is False
    mystery_experiment = experiments[1]
    assert mystery_experiment['lineage'] == []
    assert mystery_experiment['processed_files'] == [
        'Processed Data/D356_mystery.dat'
    ]


def test_proposal_cli_repeated_is_deterministic(tmp_path, capsys):
    _write_pl_tree(tmp_path)

    first_code, first = _run_proposal_cli(tmp_path, capsys)
    second_code, second = _run_proposal_cli(tmp_path, capsys)

    assert first_code == second_code == 0
    assert first.out == second.out
    assert first.err == second.err
    assert json.loads(first.out) == json.loads(second.out)


def test_fixed_gate_values_survive_conversion():
    experiment = _single_experiment(
        _proposal(
            raw=['Initial Data/D356.csv'],
            metadata=ExperimentMetadata(
                sample_id='D356',
                fixed_gate_values={'TG': 0.0, 'BG': 0.0},
                gate_constraints=[
                    GateConstraint(
                        raw_expression='TG-BG=0Rev',
                        coefficients={'TG': 1.0, 'BG': -1.0},
                        control_mode='constant_displacement_field',
                        sweep_direction='reverse',
                    )
                ],
            ),
        )
    )

    assert experiment.fixed_gate_values == {'TG': 0.0, 'BG': 0.0}
    assert experiment.gate_constraints[0].sweep_direction == 'reverse'


def test_fixed_gate_values_and_sweep_direction_survive_json():
    result = build_import_proposal(
        ScanResult(
            experiments=[
                _proposal(
                    raw=['Initial Data/D356.csv'],
                    metadata=ExperimentMetadata(
                        sample_id='D356',
                        fixed_gate_values={'TG': 0.0, 'BG': 0.0},
                        gate_constraints=[
                            GateConstraint(
                                raw_expression='TG-BG=0Rev',
                                coefficients={'TG': 1.0, 'BG': -1.0},
                                control_mode='constant_displacement_field',
                                sweep_direction='reverse',
                            )
                        ],
                    ),
                )
            ]
        )
    )

    payload = json.loads(result.to_json())
    experiment = payload['experiments'][0]
    assert experiment['fixed_gate_values'] == {'TG': 0.0, 'BG': 0.0}
    assert experiment['gate_constraints'][0]['sweep_direction'] == 'reverse'
    assert experiment['gate_constraints'][0]['raw_expression'] == 'TG-BG=0Rev'
