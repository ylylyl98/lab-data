import json

from lab_data.ingestion import archive_builder, proposal, scanner
from lab_data.ingestion.archive_builder import (
    ArchiveDraft,
    ExperimentDraft,
    FileDraft,
    ReviewDraft,
    SampleDraft,
    build_archive_draft,
)
from lab_data.ingestion.proposal import (
    ExperimentImportProposal,
    ImportProposal,
    LineageEdge,
    MetadataProvenance,
)
from lab_data.ingestion.scanner import ElectricalConnection, GateConstraint


def _representative_draft() -> ArchiveDraft:
    """Build a draft with every section and nested object populated."""

    return ArchiveDraft(
        sample=SampleDraft(sample_id='D356'),
        experiment=ExperimentDraft(
            measurement_point_label='p1n1',
            measurement_type='photoluminescence',
            temperature_K=3.6,
            magnetic_field_T=9.0,
            excitation_wavelength_nm=633.0,
            center_wavelength_nm=700.0,
            excitation_power_uW=0.03,
            integration_time_s=2.0,
            averages=1,
            grating_grooves_per_mm=300,
            rotations_deg=[45.0, 90.0],
            stage_position=50,
            fixed_top_gate_V=-0.2,
            fixed_gate_values={'TG': 0.0, 'BG': 0.0},
            active_gate_configuration='TG_only',
            sweep_direction='reverse',
            bias_start_V=0.0,
            bias_stop_V=20.0,
            back_gate_topology='single',
            gate_constraints=[
                GateConstraint(
                    raw_expression='TG-BG=0Rev',
                    coefficients={'TG': 1.0, 'BG': -1.0},
                    control_mode='constant_displacement_field',
                    sweep_direction='reverse',
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
        files=FileDraft(
            raw_files=['Initial Data/D356_3.6K_9T_633nm_PL.csv'],
            intermediate_files=['Initial Data after Process/D356_sub.csv'],
            processed_files=['Processed Data/D356_3.6K_9T_633nm_PL.dat'],
            figure_files=['Processed Data/D356_3.6K_9T_633nm_PL.png'],
        ),
        provenance=[
            MetadataProvenance(
                field='temperature_K',
                value=3.6,
                source_type='filename',
                source='Initial Data/D356_3.6K_9T_633nm_PL.csv',
                method='deterministic',
            )
        ],
        lineage=[
            LineageEdge(
                source='Initial Data/D356_3.6K_9T_633nm_PL.csv',
                target='Processed Data/D356_3.6K_9T_633nm_PL.dat',
                relation='derived_from',
            )
        ],
        review=ReviewDraft(
            warnings=['conflicting temperature_K values: [3.6, 4.0]'],
            confidence=0.95,
            needs_review=True,
        ),
    )


def test_empty_draft_serializes_to_json():
    payload = json.loads(ArchiveDraft().to_json())

    assert payload['sample'] == {'sample_id': None}
    assert payload['experiment']['temperature_K'] is None
    assert payload['files']['raw_files'] == []
    assert payload['provenance'] == []
    assert payload['lineage'] == []
    assert payload['review'] == {
        'warnings': [],
        'confidence': 0.0,
        'needs_review': False,
    }


def test_to_json_is_json_serializable():
    draft = _representative_draft()

    payload = json.loads(draft.to_json())

    assert isinstance(payload, dict)


def test_all_proposal_metadata_fields_are_preserved():
    draft = _representative_draft()
    payload = json.loads(draft.to_json())
    experiment = payload['experiment']

    expected = {
        'measurement_point_label': 'p1n1',
        'measurement_type': 'photoluminescence',
        'temperature_K': 3.6,
        'magnetic_field_T': 9.0,
        'excitation_wavelength_nm': 633.0,
        'center_wavelength_nm': 700.0,
        'excitation_power_uW': 0.03,
        'integration_time_s': 2.0,
        'averages': 1,
        'grating_grooves_per_mm': 300,
        'rotations_deg': [45.0, 90.0],
        'stage_position': 50,
        'fixed_top_gate_V': -0.2,
        'fixed_gate_values': {'TG': 0.0, 'BG': 0.0},
        'active_gate_configuration': 'TG_only',
        'sweep_direction': 'reverse',
        'bias_start_V': 0.0,
        'bias_stop_V': 20.0,
        'back_gate_topology': 'single',
    }
    for field_name, value in expected.items():
        assert experiment[field_name] == value
    assert payload['sample']['sample_id'] == 'D356'


def test_null_fields_are_preserved():
    draft = ArchiveDraft()
    payload = json.loads(draft.to_json())

    experiment = payload['experiment']
    for field_name in (
        'measurement_point_label',
        'measurement_type',
        'temperature_K',
        'magnetic_field_T',
        'excitation_wavelength_nm',
        'center_wavelength_nm',
        'excitation_power_uW',
        'integration_time_s',
        'averages',
        'grating_grooves_per_mm',
        'rotations_deg',
        'stage_position',
        'fixed_top_gate_V',
        'active_gate_configuration',
        'sweep_direction',
        'bias_start_V',
        'bias_stop_V',
        'back_gate_topology',
    ):
        assert experiment[field_name] is None
    assert payload['sample']['sample_id'] is None


def test_sweep_direction_preserves_one_reverse_value():
    draft = ArchiveDraft(
        experiment=ExperimentDraft(sweep_direction='reverse')
    )
    payload = json.loads(draft.to_json())

    assert payload['experiment']['sweep_direction'] == 'reverse'


def test_nested_gate_constraint_is_preserved():
    payload = json.loads(_representative_draft().to_json())

    constraint = payload['experiment']['gate_constraints'][0]
    assert constraint == {
        'raw_expression': 'TG-BG=0Rev',
        'coefficients': {'TG': 1.0, 'BG': -1.0},
        'control_mode': 'constant_displacement_field',
        'sweep_direction': 'reverse',
    }


def test_nested_electrical_connection_is_preserved():
    payload = json.loads(_representative_draft().to_json())

    connection = payload['experiment']['electrical_connections'][0]
    assert connection == {
        'raw_expression': 'BG2-CG',
        'nodes': ['BG2', 'CG'],
        'type': 'electrically_tied',
        'source_role': 'bias_source',
    }


def test_nested_provenance_and_lineage_objects_are_preserved():
    payload = json.loads(_representative_draft().to_json())

    assert payload['provenance'][0] == {
        'field': 'temperature_K',
        'value': 3.6,
        'source_type': 'filename',
        'source': 'Initial Data/D356_3.6K_9T_633nm_PL.csv',
        'method': 'deterministic',
    }
    assert payload['lineage'][0] == {
        'source': 'Initial Data/D356_3.6K_9T_633nm_PL.csv',
        'target': 'Processed Data/D356_3.6K_9T_633nm_PL.dat',
        'relation': 'derived_from',
    }


def test_relative_file_paths_are_preserved():
    payload = json.loads(_representative_draft().to_json())

    assert payload['files'] == {
        'raw_files': ['Initial Data/D356_3.6K_9T_633nm_PL.csv'],
        'intermediate_files': ['Initial Data after Process/D356_sub.csv'],
        'processed_files': ['Processed Data/D356_3.6K_9T_633nm_PL.dat'],
        'figure_files': ['Processed Data/D356_3.6K_9T_633nm_PL.png'],
    }


def test_review_data_is_preserved():
    payload = json.loads(_representative_draft().to_json())

    assert payload['review'] == {
        'warnings': ['conflicting temperature_K values: [3.6, 4.0]'],
        'confidence': 0.95,
        'needs_review': True,
    }


def _full_experiment(**overrides) -> ExperimentImportProposal:
    """Build a fully-populated experiment proposal with common defaults."""

    defaults = dict(
        measurement_point_label='p1n1',
        sample_id='D356',
        measurement_type='photoluminescence',
        temperature_K=3.6,
        magnetic_field_T=9.0,
        excitation_wavelength_nm=633.0,
        center_wavelength_nm=700.0,
        excitation_power_uW=0.03,
        integration_time_s=2.0,
        averages=1,
        grating_grooves_per_mm=300,
        rotations_deg=[45.0, 90.0],
        stage_position=50,
        fixed_top_gate_V=-0.2,
        active_gate_configuration='TG_only',
        bias_start_V=0.0,
        bias_stop_V=20.0,
        back_gate_topology='single',
        fixed_gate_values={'TG': 0.0, 'BG': 0.0},
        gate_constraints=[
            GateConstraint(
                raw_expression='TG-BG=0Rev',
                coefficients={'TG': 1.0, 'BG': -1.0},
                control_mode='constant_displacement_field',
                sweep_direction='reverse',
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
        raw_files=['Initial Data/D356_3.6K_9T_633nm_PL.csv'],
        processed_files=['Processed Data/D356_3.6K_9T_633nm_PL.dat'],
        figure_files=['Processed Data/D356_3.6K_9T_633nm_PL.png'],
        intermediate_files=['Initial Data after Process/D356_sub.csv'],
        warnings=['conflicting temperature_K values: [3.6, 4.0]'],
        confidence=0.95,
        lineage=[
            LineageEdge(
                source='Initial Data/D356_3.6K_9T_633nm_PL.csv',
                target='Processed Data/D356_3.6K_9T_633nm_PL.dat',
                relation='derived_from',
            )
        ],
        metadata_provenance=[
            MetadataProvenance(
                field='temperature_K',
                value=3.6,
                source_type='filename',
                source='Initial Data/D356_3.6K_9T_633nm_PL.csv',
                method='deterministic',
            )
        ],
        needs_review=True,
    )
    defaults.update(overrides)
    return ExperimentImportProposal(**defaults)


def test_standard_pl_experiment_maps_all_metadata():
    draft = build_archive_draft(
        ImportProposal(experiments=[_full_experiment()])
    )[0]

    assert draft.sample.sample_id == 'D356'
    experiment = draft.experiment
    expected = {
        'measurement_point_label': 'p1n1',
        'measurement_type': 'photoluminescence',
        'temperature_K': 3.6,
        'magnetic_field_T': 9.0,
        'excitation_wavelength_nm': 633.0,
        'center_wavelength_nm': 700.0,
        'excitation_power_uW': 0.03,
        'integration_time_s': 2.0,
        'averages': 1,
        'grating_grooves_per_mm': 300,
        'rotations_deg': [45.0, 90.0],
        'stage_position': 50,
        'fixed_top_gate_V': -0.2,
        'fixed_gate_values': {'TG': 0.0, 'BG': 0.0},
        'active_gate_configuration': 'TG_only',
        'sweep_direction': 'reverse',
        'bias_start_V': 0.0,
        'bias_stop_V': 20.0,
        'back_gate_topology': 'single',
    }
    for field_name, value in expected.items():
        assert getattr(experiment, field_name) == value


def test_absorption_measurement_type_is_preserved():
    draft = build_archive_draft(
        ImportProposal(
            experiments=[
                _full_experiment(
                    measurement_type='absorption',
                    excitation_wavelength_nm=None,
                )
            ]
        )
    )[0]

    assert draft.experiment.measurement_type == 'absorption'


def test_yz247_gate_trajectory_constraint_is_preserved():
    draft = build_archive_draft(
        ImportProposal(
            experiments=[
                _full_experiment(
                    sample_id='YZ247',
                    gate_constraints=[
                        GateConstraint(
                            raw_expression='TG-BG=0Rev',
                            coefficients={'TG': 1.0, 'BG': -1.0},
                            control_mode='constant_displacement_field',
                            sweep_direction='reverse',
                        )
                    ],
                )
            ]
        )
    )[0]

    assert draft.sample.sample_id == 'YZ247'
    assert draft.experiment.gate_constraints == [
        GateConstraint(
            raw_expression='TG-BG=0Rev',
            coefficients={'TG': 1.0, 'BG': -1.0},
            control_mode='constant_displacement_field',
            sweep_direction='reverse',
        )
    ]


def test_fixed_tg_bg_zero_keeps_sweep_direction_none():
    draft = build_archive_draft(
        ImportProposal(
            experiments=[
                _full_experiment(
                    fixed_gate_values={'TG': 0.0, 'BG': 0.0},
                    gate_constraints=[],
                )
            ]
        )
    )[0]

    assert draft.experiment.fixed_gate_values == {'TG': 0.0, 'BG': 0.0}
    assert draft.experiment.sweep_direction is None


def test_reverse_sweep_direction_is_copied():
    draft = build_archive_draft(
        ImportProposal(
            experiments=[
                _full_experiment(
                    gate_constraints=[
                        GateConstraint(
                            raw_expression='TG+BG=0Rev',
                            coefficients={'TG': 1.0, 'BG': 1.0},
                            control_mode='constant_doping',
                            sweep_direction='reverse',
                        )
                    ]
                )
            ]
        )
    )[0]

    assert draft.experiment.sweep_direction == 'reverse'


def test_conflicting_sweep_directions_yield_none():
    draft = build_archive_draft(
        ImportProposal(
            experiments=[
                _full_experiment(
                    gate_constraints=[
                        GateConstraint(
                            raw_expression='TG-BG=0Rev',
                            coefficients={'TG': 1.0, 'BG': -1.0},
                            control_mode='constant_displacement_field',
                            sweep_direction='reverse',
                        ),
                        GateConstraint(
                            raw_expression='BG1-BG2=0Rev',
                            coefficients={'BG1': 1.0, 'BG2': -1.0},
                            control_mode=None,
                            sweep_direction='reverse',
                        ),
                    ]
                )
            ]
        )
    )[0]

    assert draft.experiment.sweep_direction is None


def test_split_back_gate_topology_is_preserved():
    draft = build_archive_draft(
        ImportProposal(
            experiments=[
                _full_experiment(back_gate_topology='split')
            ]
        )
    )[0]

    assert draft.experiment.back_gate_topology == 'split'


def test_bg2_cg_wiring_is_preserved():
    draft = build_archive_draft(
        ImportProposal(
            experiments=[
                _full_experiment(
                    electrical_connections=[
                        ElectricalConnection(
                            raw_expression='BG2-CG',
                            nodes=['BG2', 'CG'],
                            type='electrically_tied',
                            source_role='bias_source',
                        )
                    ]
                )
            ]
        )
    )[0]

    assert draft.experiment.electrical_connections == [
        ElectricalConnection(
            raw_expression='BG2-CG',
            nodes=['BG2', 'CG'],
            type='electrically_tied',
            source_role='bias_source',
        )
    ]


def test_intermediate_files_are_preserved():
    draft = build_archive_draft(
        ImportProposal(
            experiments=[
                _full_experiment(
                    intermediate_files=[
                        'Initial Data after Process/D356_sub.csv'
                    ]
                )
            ]
        )
    )[0]

    assert draft.files.intermediate_files == [
        'Initial Data after Process/D356_sub.csv'
    ]


def test_measurement_point_label_is_preserved():
    draft = build_archive_draft(
        ImportProposal(
            experiments=[_full_experiment(measurement_point_label='9Tp1n1')]
        )
    )[0]

    assert draft.experiment.measurement_point_label == '9Tp1n1'


def test_provenance_and_lineage_are_preserved():
    draft = build_archive_draft(
        ImportProposal(experiments=[_full_experiment()])
    )[0]

    assert draft.provenance == [
        MetadataProvenance(
            field='temperature_K',
            value=3.6,
            source_type='filename',
            source='Initial Data/D356_3.6K_9T_633nm_PL.csv',
            method='deterministic',
        )
    ]
    assert draft.lineage == [
        LineageEdge(
            source='Initial Data/D356_3.6K_9T_633nm_PL.csv',
            target='Processed Data/D356_3.6K_9T_633nm_PL.dat',
            relation='derived_from',
        )
    ]


def test_null_optionals_are_preserved():
    draft = build_archive_draft(
        ImportProposal(experiments=[ExperimentImportProposal()])
    )[0]

    assert draft.sample.sample_id is None
    experiment = draft.experiment
    for field_name in (
        'measurement_point_label',
        'measurement_type',
        'temperature_K',
        'magnetic_field_T',
        'excitation_wavelength_nm',
        'center_wavelength_nm',
        'excitation_power_uW',
        'integration_time_s',
        'averages',
        'grating_grooves_per_mm',
        'rotations_deg',
        'stage_position',
        'fixed_top_gate_V',
        'active_gate_configuration',
        'sweep_direction',
        'bias_start_V',
        'bias_stop_V',
        'back_gate_topology',
    ):
        assert getattr(experiment, field_name) is None
    assert experiment.fixed_gate_values == {}
    assert experiment.gate_constraints == []
    assert experiment.electrical_connections == []
    assert draft.review.warnings == []
    assert draft.review.confidence == 0.0
    assert draft.review.needs_review is False


def test_multiple_experiments_produce_multiple_drafts():
    drafts = build_archive_draft(
        ImportProposal(
            experiments=[
                _full_experiment(sample_id='D356'),
                _full_experiment(
                    sample_id='D357',
                    measurement_type='absorption',
                ),
            ]
        )
    )

    assert [draft.sample.sample_id for draft in drafts] == ['D356', 'D357']
    assert drafts[1].experiment.measurement_type == 'absorption'


def test_build_does_not_mutate_source_and_is_deterministic():
    source = ImportProposal(experiments=[_full_experiment()])
    before = json.loads(source.to_json())

    first = build_archive_draft(source)
    second = build_archive_draft(source)

    assert first == second
    assert first[0].to_json() == second[0].to_json()
    assert json.loads(source.to_json()) == before

    # Mutating a mapped draft must not touch the source proposal.
    first[0].experiment.gate_constraints[0].coefficients['TG'] = 99.0
    first[0].experiment.fixed_gate_values['TG'] = 99.0
    first[0].experiment.rotations_deg.append(180.0)
    first[0].files.raw_files.append('other.csv')

    assert json.loads(source.to_json()) == before
    assert source.experiments[0].gate_constraints[0].coefficients['TG'] == 1.0
    assert source.experiments[0].fixed_gate_values['TG'] == 0.0
    assert source.experiments[0].rotations_deg == [45.0, 90.0]
    assert source.experiments[0].raw_files == [
        'Initial Data/D356_3.6K_9T_633nm_PL.csv'
    ]


def test_nested_objects_do_not_alias_source():
    experiment = _full_experiment()
    draft = build_archive_draft(ImportProposal(experiments=[experiment]))[0]

    assert draft.sample is not experiment
    assert draft.experiment.gate_constraints is not experiment.gate_constraints
    assert (
        draft.experiment.gate_constraints[0]
        is not experiment.gate_constraints[0]
    )
    assert draft.experiment.gate_constraints[0].coefficients is not (
        experiment.gate_constraints[0].coefficients
    )
    assert (
        draft.experiment.electrical_connections
        is not experiment.electrical_connections
    )
    assert (
        draft.experiment.electrical_connections[0].nodes
        is not experiment.electrical_connections[0].nodes
    )
    assert draft.experiment.fixed_gate_values is not experiment.fixed_gate_values
    assert draft.experiment.rotations_deg is not experiment.rotations_deg
    assert draft.files.raw_files is not experiment.raw_files
    assert draft.provenance is not experiment.metadata_provenance
    assert draft.provenance[0] is not experiment.metadata_provenance[0]
    assert draft.lineage is not experiment.lineage
    assert draft.lineage[0] is not experiment.lineage[0]
    assert draft.review.warnings is not experiment.warnings


def _write(path, content: str = '') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


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


def _run_archive_builder_cli(path, capsys):
    code = archive_builder.main([str(path)])
    captured = capsys.readouterr()
    return code, captured


def _draft_for_sample(drafts, sample_id):
    return next(
        draft
        for draft in drafts
        if draft['sample']['sample_id'] == sample_id
    )


def test_archive_builder_cli_valid_json(tmp_path, capsys):
    _write_pl_tree(tmp_path)

    code, captured = _run_archive_builder_cli(tmp_path, capsys)

    assert code == 0
    assert captured.err == ''
    payload = json.loads(captured.out)
    assert set(payload) == {'drafts'}
    assert len(payload['drafts']) == 1
    draft = payload['drafts'][0]
    assert draft['sample']['sample_id'] == 'D356'
    assert draft['experiment']['measurement_type'] == 'photoluminescence'


def test_archive_builder_cli_missing_path_nonzero(tmp_path, capsys):
    missing = tmp_path / 'does-not-exist'

    code, captured = _run_archive_builder_cli(missing, capsys)

    assert code != 0
    assert captured.out == ''
    assert 'does not exist' in captured.err


def test_archive_builder_cli_not_a_directory_nonzero(tmp_path, capsys):
    target = tmp_path / 'a-file.txt'
    _write(target)

    code, captured = _run_archive_builder_cli(target, capsys)

    assert code != 0
    assert captured.out == ''
    assert 'not a directory' in captured.err


def test_archive_builder_cli_wrong_argument_count_nonzero(tmp_path, capsys):
    for args in ([], [str(tmp_path), 'extra']):
        code = archive_builder.main(args)
        captured = capsys.readouterr()

        assert code != 0
        assert captured.out == ''
        assert 'usage' in captured.err


def test_archive_builder_cli_does_not_write_files(tmp_path, capsys):
    _write_pl_tree(tmp_path)
    before = _file_set(tmp_path)

    code, _ = _run_archive_builder_cli(tmp_path, capsys)

    assert code == 0
    assert _file_set(tmp_path) == before


def test_archive_builder_cli_representative_content(tmp_path, capsys):
    _write_pl_tree(tmp_path)
    _write(tmp_path / 'Initial Data' / 'D357_REF.csv')
    _write(tmp_path / 'Processed Data' / 'D357_REF.dat')
    _write(tmp_path / 'Processed Data' / 'D357_REF_linear.png')
    _write(
        tmp_path / 'Initial Data after process' / 'D358_TG=BG=0_TG+BG=0Rev.csv'
    )

    code, captured = _run_archive_builder_cli(tmp_path, capsys)

    assert code == 0
    drafts = json.loads(captured.out)['drafts']

    pl = _draft_for_sample(drafts, 'D356')
    assert pl['experiment']['measurement_type'] == 'photoluminescence'
    assert pl['files']['raw_files'] == [
        'Initial Data/D356_3.6K_9T_633nm_PL.csv'
    ]
    assert pl['files']['processed_files'] == [
        'Processed Data/D356_3.6K_9T_633nm_PL.dat'
    ]
    assert pl['files']['figure_files'] == [
        'Processed Data/D356_3.6K_9T_633nm_PL_linear.png'
    ]

    absorption = _draft_for_sample(drafts, 'D357')
    assert absorption['experiment']['measurement_type'] == 'absorption'

    fixed = _draft_for_sample(drafts, 'D358')
    assert fixed['experiment']['fixed_gate_values'] == {'TG': 0.0, 'BG': 0.0}
    assert fixed['experiment']['sweep_direction'] == 'reverse'
    assert fixed['files']['intermediate_files'] == [
        'Initial Data after process/D358_TG=BG=0_TG+BG=0Rev.csv'
    ]


def test_scanner_and_proposal_cli_still_usable(tmp_path, capsys):
    _write_pl_tree(tmp_path)

    scanner_code = scanner.main([str(tmp_path)])
    scanner_captured = capsys.readouterr()
    proposal_code = proposal.main([str(tmp_path)])
    proposal_captured = capsys.readouterr()

    assert scanner_code == 0
    assert json.loads(scanner_captured.out)['sample_id'] == 'D356'
    assert proposal_code == 0
    assert json.loads(proposal_captured.out)['sample_id'] == 'D356'
