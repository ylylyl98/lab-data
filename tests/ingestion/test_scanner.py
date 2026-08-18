import json

import pytest

from lab_data.ingestion import scanner
from lab_data.ingestion.scanner import scan_directory

PL_TEMPERATURE_K = 3.6
PL_FIELD_T = 9.0
PL_WAVELENGTH_NM = 633.0
ABS_TEMPERATURE_K = 3.6

CENTER_WAVELENGTH_NM_700 = 700.0
CENTER_WAVELENGTH_NM_720 = 720.0
CENTER_WAVELENGTH_NM_940 = 940.0
EXCITATION_WAVELENGTH_NM_730 = 730.0
EXCITATION_POWER_UW_0P03 = 0.03
EXCITATION_POWER_UW_0P02 = 0.02
INTEGRATION_TIME_S_2 = 2.0
INTEGRATION_TIME_S_5 = 5.0
AVERAGES_10 = 10
GRATING_GROOVES_PER_MM_300 = 300
STAGE_POSITION_50 = 50
TWO_EXPERIMENTS = 2
FIXED_TOP_GATE_V_NEG_0P2 = -0.2
BIAS_POSITIVE_8 = 8.0
BIAS_NEGATIVE_8 = -8.0
BIAS_POSITIVE_20 = 20.0


def _write(path, content: str = '') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_pl_metadata_and_grouping(tmp_path):
    _write(tmp_path / 'Initial Data' / 'D356_3.6K_9T_633nm_PL.csv')
    _write(tmp_path / 'Processed Data' / 'D356_3.6K_9T_633nm_PL.csv')
    _write(tmp_path / 'Processed Data' / 'D356_3.6K_9T_633nm_PL.png')

    result = scan_directory(tmp_path)

    assert result.sample_id == 'D356'
    assert result.unclassified_files == []
    assert len(result.experiments) == 1

    exp = result.experiments[0]
    assert exp.metadata.sample_id == 'D356'
    assert exp.metadata.temperature_K == PL_TEMPERATURE_K
    assert exp.metadata.magnetic_field_T == PL_FIELD_T
    assert exp.metadata.excitation_wavelength_nm == PL_WAVELENGTH_NM
    assert exp.metadata.measurement_type == 'photoluminescence'
    assert exp.raw_files == ['Initial Data/D356_3.6K_9T_633nm_PL.csv']
    assert exp.processed_files == ['Processed Data/D356_3.6K_9T_633nm_PL.csv']
    assert exp.figure_files == ['Processed Data/D356_3.6K_9T_633nm_PL.png']
    assert 0 < exp.confidence <= 1


def test_absorption_grouping_and_yz356_normalization(tmp_path):
    _write(tmp_path / 'Initial Data' / 'YZ356_REF.csv')
    _write(tmp_path / 'Processed Data' / 'YZ356_REF.csv')
    _write(tmp_path / 'Processed Data' / 'YZ356_REF.png')

    result = scan_directory(tmp_path)

    assert result.sample_id == 'D356'
    assert len(result.experiments) == 1

    exp = result.experiments[0]
    assert exp.metadata.sample_id == 'D356'
    assert exp.metadata.measurement_type == 'absorption'
    assert exp.raw_files == ['Initial Data/YZ356_REF.csv']
    assert exp.processed_files == ['Processed Data/YZ356_REF.csv']
    assert exp.figure_files == ['Processed Data/YZ356_REF.png']


def test_dr_r_is_absorption(tmp_path):
    _write(tmp_path / 'Initial Data' / 'D356_DR_R.csv')
    _write(tmp_path / 'Processed Data' / 'D356_DR_R.csv')

    result = scan_directory(tmp_path)

    assert result.experiments[0].metadata.measurement_type == 'absorption'


def test_png_under_processed_data_is_figure(tmp_path):
    _write(tmp_path / 'Processed Data' / 'D356_PL.csv')
    _write(tmp_path / 'Processed Data' / 'D356_PL.png')

    result = scan_directory(tmp_path)

    exp = result.experiments[0]
    assert exp.processed_files == ['Processed Data/D356_PL.csv']
    assert exp.figure_files == ['Processed Data/D356_PL.png']
    assert exp.metadata.measurement_type == 'photoluminescence'


def test_condition_metadata_extraction(tmp_path):
    _write(tmp_path / 'Initial Data' / 'D356_3.6K_9T_633nm_PL.csv')

    exp = scan_directory(tmp_path).experiments[0]

    assert exp.metadata.temperature_K == PL_TEMPERATURE_K
    assert exp.metadata.magnetic_field_T == PL_FIELD_T
    assert exp.metadata.excitation_wavelength_nm == PL_WAVELENGTH_NM


def test_yz356_normalizes_to_d356(tmp_path):
    _write(tmp_path / 'Initial Data' / 'YZ356_PL.csv')

    result = scan_directory(tmp_path)

    assert result.experiments[0].metadata.sample_id == 'D356'
    assert result.sample_id == 'D356'


def test_ambiguous_naming_does_not_fabricate(tmp_path):
    _write(tmp_path / 'Initial Data' / 'sample_run_2024.csv')

    exp = scan_directory(tmp_path).experiments[0]

    assert exp.metadata.sample_id is None
    assert exp.metadata.temperature_K is None
    assert exp.metadata.magnetic_field_T is None
    assert exp.metadata.excitation_wavelength_nm is None
    assert exp.metadata.measurement_type is None


def test_role_suffix_files_group_together(tmp_path):
    _write(tmp_path / 'Initial Data' / 'D356_PL_raw.csv')
    _write(tmp_path / 'Processed Data' / 'D356_PL_processed.csv')
    _write(tmp_path / 'Processed Data' / 'D356_PL_fig.png')

    result = scan_directory(tmp_path)

    assert len(result.experiments) == 1
    exp = result.experiments[0]
    assert exp.raw_files == ['Initial Data/D356_PL_raw.csv']
    assert exp.processed_files == ['Processed Data/D356_PL_processed.csv']
    assert exp.figure_files == ['Processed Data/D356_PL_fig.png']
    assert exp.metadata.measurement_type == 'photoluminescence'


def test_supported_extensions(tmp_path):
    names = ('a.dat', 'b.xlsx', 'c.xls')
    for name in names:
        _write(tmp_path / 'Initial Data' / name)

    result = scan_directory(tmp_path)

    total_raw = sum(len(exp.raw_files) for exp in result.experiments)
    assert total_raw == len(names)


def test_unsupported_files_do_not_break_scanning(tmp_path):
    _write(tmp_path / 'Initial Data' / 'D356_PL.csv')
    _write(tmp_path / 'notes.txt')
    _write(tmp_path / 'Processed Data' / 'report.pdf')

    result = scan_directory(tmp_path)

    assert len(result.experiments) == 1
    assert result.unclassified_files == [
        'Processed Data/report.pdf',
        'notes.txt',
    ]
    assert len(result.warnings) == len(result.unclassified_files)


def test_scan_directory_rejects_missing_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        scan_directory(tmp_path / 'does_not_exist')


def test_scan_directory_rejects_file_path(tmp_path):
    file_path = tmp_path / 'not_a_dir.txt'
    _write(file_path)

    with pytest.raises(NotADirectoryError):
        scan_directory(file_path)


def test_cli_invalid_path_returns_nonzero(tmp_path):
    code = scanner.main([str(tmp_path / 'missing')])

    assert code != 0


def test_to_json_is_valid_and_serializable(tmp_path):
    _write(tmp_path / 'Initial Data' / 'D356_PL.csv')

    result = scan_directory(tmp_path)
    payload = json.loads(result.to_json())

    assert payload['sample_id'] == 'D356'
    assert payload['experiments'][0]['metadata']['measurement_type'] == (
        'photoluminescence'
    )


def test_pl_derived_suffixes_group_into_one_experiment(tmp_path):
    base = 'YZ356_9Tp1n1_3.6KPL_633nm_700nmc_2sx1_FixTG=-0.2_Vb0to+20'
    _write(tmp_path / 'Initial Data' / f'{base}.csv')
    _write(tmp_path / 'Processed Data' / f'{base}_PL.dat')
    _write(tmp_path / 'Processed Data' / f'{base}_PL_linear.png')
    _write(tmp_path / 'Processed Data' / f'{base}_PL_log.png')

    result = scan_directory(tmp_path)

    assert result.sample_id == 'D356'
    assert result.unclassified_files == []
    assert len(result.experiments) == 1

    exp = result.experiments[0]
    assert exp.metadata.sample_id == 'D356'
    assert exp.metadata.measurement_type == 'photoluminescence'
    assert exp.metadata.temperature_K == PL_TEMPERATURE_K
    assert exp.metadata.magnetic_field_T == PL_FIELD_T
    assert exp.metadata.excitation_wavelength_nm == PL_WAVELENGTH_NM
    assert exp.raw_files == [f'Initial Data/{base}.csv']
    assert exp.processed_files == [f'Processed Data/{base}_PL.dat']
    assert exp.figure_files == [
        f'Processed Data/{base}_PL_linear.png',
        f'Processed Data/{base}_PL_log.png',
    ]


def test_absorption_derived_suffixes_group_into_one_experiment(tmp_path):
    base = 'YZ356_p1_3.6KREF_720nmc_0p06sx10_TGonly'
    _write(tmp_path / 'Initial Data' / f'{base}.csv')
    _write(tmp_path / 'Processed Data' / f'{base}_avg1_DR_R_Self.dat')
    _write(tmp_path / 'Processed Data' / f'{base}_avg1_DR_R_Self.png')

    result = scan_directory(tmp_path)

    assert result.sample_id == 'D356'
    assert result.unclassified_files == []
    assert len(result.experiments) == 1

    exp = result.experiments[0]
    assert exp.metadata.sample_id == 'D356'
    assert exp.metadata.measurement_type == 'absorption'
    assert exp.metadata.temperature_K == ABS_TEMPERATURE_K
    assert exp.raw_files == [f'Initial Data/{base}.csv']
    assert exp.processed_files == [f'Processed Data/{base}_avg1_DR_R_Self.dat']
    assert exp.figure_files == [f'Processed Data/{base}_avg1_DR_R_Self.png']


def test_split_back_gate_pl_derived_suffixes_group_into_one_experiment(tmp_path):
    base = 'YZ356_9Tp1n1_3.6KPL_633nm_700nmc_2sx1_BG1+BG2=0_Vb+8to-8'
    _write(tmp_path / 'Initial Data' / f'{base}.csv')
    _write(tmp_path / 'Processed Data' / f'{base}_PL.dat')
    _write(tmp_path / 'Processed Data' / f'{base}_PL_linear.png')

    result = scan_directory(tmp_path)

    assert result.sample_id == 'D356'
    assert result.unclassified_files == []
    assert len(result.experiments) == 1

    exp = result.experiments[0]
    assert exp.metadata.sample_id == 'D356'
    assert exp.metadata.measurement_type == 'photoluminescence'
    assert exp.metadata.back_gate_topology == 'split'
    assert exp.raw_files == [f'Initial Data/{base}.csv']
    assert exp.processed_files == [f'Processed Data/{base}_PL.dat']
    assert exp.figure_files == [f'Processed Data/{base}_PL_linear.png']


def test_yz247_pl_derived_suffixes_group_into_one_experiment(tmp_path):
    base = (
        'YZ247_pc1_300g_3.6KPL_730nm0.03uW_940nmc_5sx1_'
        'Rot1195p8deg_Rot295deg_Stage50_TG+BG=0'
    )
    _write(tmp_path / 'Initial Data' / f'{base}.csv')
    _write(tmp_path / 'Processed Data' / f'{base}_PL.dat')
    _write(tmp_path / 'Processed Data' / f'{base}_PL_linear.png')

    result = scan_directory(tmp_path)

    assert result.sample_id == 'YZ247'
    assert result.unclassified_files == []
    assert len(result.experiments) == 1

    exp = result.experiments[0]
    assert exp.metadata.sample_id == 'YZ247'
    assert exp.metadata.measurement_type == 'photoluminescence'
    assert exp.raw_files == [f'Initial Data/{base}.csv']
    assert exp.processed_files == [f'Processed Data/{base}_PL.dat']
    assert exp.figure_files == [f'Processed Data/{base}_PL_linear.png']


def test_yz247_sample_id_is_not_renamed_to_d247(tmp_path):
    _write(
        tmp_path
        / 'Initial Data'
        / 'YZ247_pc1_300g_3.6KPL_730nm0.03uW_940nmc_5sx1.csv'
    )

    exp = scan_directory(tmp_path).experiments[0]

    assert exp.metadata.sample_id == 'YZ247'
    assert exp.metadata.sample_id != 'D247'


def test_unknown_derived_suffix_is_not_silently_stripped(tmp_path):
    base = 'YZ356_9Tp1n1_3.6KPL_633nm_700nmc_2sx1_FixTG=-0.2_Vb0to+20'
    _write(tmp_path / 'Initial Data' / f'{base}.csv')
    _write(tmp_path / 'Processed Data' / f'{base}_mystery.dat')
    _write(tmp_path / 'Processed Data' / f'{base}_mystery.png')

    result = scan_directory(tmp_path)

    # An unrecognised suffix must never be stripped or silently associated
    # with the raw base, so the raw file and the mystery derivatives stay in
    # separate experiment proposals.
    assert result.unclassified_files == []
    assert len(result.experiments) == TWO_EXPERIMENTS

    raw_experiments = [exp for exp in result.experiments if exp.raw_files]
    assert len(raw_experiments) == 1
    raw_exp = raw_experiments[0]
    assert raw_exp.raw_files == [f'Initial Data/{base}.csv']
    assert raw_exp.processed_files == []
    assert raw_exp.figure_files == []

    mystery_experiments = [
        exp for exp in result.experiments if exp.processed_files or exp.figure_files
    ]
    assert len(mystery_experiments) == 1
    mystery_exp = mystery_experiments[0]
    assert mystery_exp.raw_files == []
    assert mystery_exp.processed_files == [
        f'Processed Data/{base}_mystery.dat'
    ]
    assert mystery_exp.figure_files == [f'Processed Data/{base}_mystery.png']


def _scan_single(tmp_path, stem):
    _write(tmp_path / 'Initial Data' / f'{stem}.csv')
    return scan_directory(tmp_path).experiments[0]


def test_center_wavelength_700nmc(tmp_path):
    exp = _scan_single(tmp_path, 'D356_700nmc')

    assert exp.metadata.center_wavelength_nm == CENTER_WAVELENGTH_NM_700
    assert exp.metadata.excitation_wavelength_nm is None


def test_center_wavelength_720nmc(tmp_path):
    exp = _scan_single(tmp_path, 'D356_720nmc')

    assert exp.metadata.center_wavelength_nm == CENTER_WAVELENGTH_NM_720
    assert exp.metadata.excitation_wavelength_nm is None


def test_center_wavelength_940nmc(tmp_path):
    exp = _scan_single(tmp_path, 'D356_940nmc')

    assert exp.metadata.center_wavelength_nm == CENTER_WAVELENGTH_NM_940
    assert exp.metadata.excitation_wavelength_nm is None


def test_excitation_wavelength_633nm(tmp_path):
    exp = _scan_single(tmp_path, 'D356_633nm')

    assert exp.metadata.excitation_wavelength_nm == PL_WAVELENGTH_NM
    assert exp.metadata.center_wavelength_nm is None


def test_excitation_wavelength_730nm(tmp_path):
    exp = _scan_single(tmp_path, 'D356_730nm')

    assert exp.metadata.excitation_wavelength_nm == EXCITATION_WAVELENGTH_NM_730


def test_730nm_power_yields_wavelength_and_power(tmp_path):
    exp = _scan_single(tmp_path, 'D356_730nm0.03uW')

    assert exp.metadata.excitation_wavelength_nm == EXCITATION_WAVELENGTH_NM_730
    assert exp.metadata.excitation_power_uW == EXCITATION_POWER_UW_0P03


def test_excitation_power_0p03uW(tmp_path):
    exp = _scan_single(tmp_path, 'D356_0.03uW')

    assert exp.metadata.excitation_power_uW == EXCITATION_POWER_UW_0P03


def test_excitation_power_0p02uW(tmp_path):
    exp = _scan_single(tmp_path, 'D356_0.02uW')

    assert exp.metadata.excitation_power_uW == EXCITATION_POWER_UW_0P02


def test_excitation_power_p_decimal_notation(tmp_path):
    exp = _scan_single(tmp_path, 'D356_0p03uW')

    assert exp.metadata.excitation_power_uW == EXCITATION_POWER_UW_0P03


def test_integration_2sx1(tmp_path):
    exp = _scan_single(tmp_path, 'D356_2sx1')

    assert exp.metadata.integration_time_s == INTEGRATION_TIME_S_2
    assert exp.metadata.averages == 1


def test_integration_5sx1(tmp_path):
    exp = _scan_single(tmp_path, 'D356_5sx1')

    assert exp.metadata.integration_time_s == INTEGRATION_TIME_S_5
    assert exp.metadata.averages == 1


def test_integration_0p06sx10(tmp_path):
    exp = _scan_single(tmp_path, 'D356_0p06sx10')

    assert exp.metadata.integration_time_s == pytest.approx(0.06)
    assert exp.metadata.averages == AVERAGES_10


def test_integration_0p07sx10(tmp_path):
    exp = _scan_single(tmp_path, 'D356_0p07sx10')

    assert exp.metadata.integration_time_s == pytest.approx(0.07)
    assert exp.metadata.averages == AVERAGES_10


def test_grating_300g(tmp_path):
    exp = _scan_single(tmp_path, 'D356_300g')

    assert exp.metadata.grating_grooves_per_mm == GRATING_GROOVES_PER_MM_300


def test_stage_position_50(tmp_path):
    exp = _scan_single(tmp_path, 'D356_Stage50')

    assert exp.metadata.stage_position == STAGE_POSITION_50


def test_multiple_rotations_in_order(tmp_path):
    exp = _scan_single(tmp_path, 'D356_Rot0deg_Rot45deg_Rot90deg')

    assert exp.metadata.rotations_deg == [0.0, 45.0, 90.0]


def test_rotation_p_decimal_notation(tmp_path):
    exp = _scan_single(tmp_path, 'D356_Rot0p5deg')

    assert exp.metadata.rotations_deg == [0.5]


def test_token_order_tolerance(tmp_path):
    _write(
        tmp_path
        / 'Initial Data'
        / 'D100_730nm0.03uW_700nmc_0p06sx10_300g_Rot45deg_Stage50.csv'
    )
    _write(
        tmp_path
        / 'Initial Data'
        / 'D200_Stage50_300g_Rot45deg_700nmc_0p06sx10_730nm0.03uW.csv'
    )

    result = scan_directory(tmp_path)

    assert len(result.experiments) == TWO_EXPERIMENTS
    for exp in result.experiments:
        assert exp.metadata.center_wavelength_nm == CENTER_WAVELENGTH_NM_700
        assert exp.metadata.excitation_wavelength_nm == EXCITATION_WAVELENGTH_NM_730
        assert exp.metadata.excitation_power_uW == EXCITATION_POWER_UW_0P03
        assert exp.metadata.integration_time_s == pytest.approx(0.06)
        assert exp.metadata.averages == AVERAGES_10
        assert exp.metadata.grating_grooves_per_mm == GRATING_GROOVES_PER_MM_300
        assert exp.metadata.rotations_deg == [45.0]
        assert exp.metadata.stage_position == STAGE_POSITION_50


def _constraint(exp, raw_expression):
    for constraint in exp.metadata.gate_constraints:
        if constraint.raw_expression.lower() == raw_expression.lower():
            return constraint
    return None


def _connection(exp, raw_expression):
    for connection in exp.metadata.electrical_connections:
        if connection.raw_expression.lower() == raw_expression.lower():
            return connection
    return None


def test_fix_tg_negative(tmp_path):
    exp = _scan_single(tmp_path, 'D356_FixTG=-0.2')

    assert exp.metadata.fixed_top_gate_V == FIXED_TOP_GATE_V_NEG_0P2


def test_active_gate_tgonly(tmp_path):
    exp = _scan_single(tmp_path, 'D356_TGonly')

    assert exp.metadata.active_gate_configuration == 'TG_only'


def test_active_gate_bg1only(tmp_path):
    exp = _scan_single(tmp_path, 'D356_BG1only')

    assert exp.metadata.active_gate_configuration == 'BG1_only'


def test_bias_0to_positive_20(tmp_path):
    exp = _scan_single(tmp_path, 'D356_Vb0to+20')

    assert exp.metadata.bias_start_V == 0.0
    assert exp.metadata.bias_stop_V == BIAS_POSITIVE_20


def test_bias_positive_8_to_negative_8(tmp_path):
    exp = _scan_single(tmp_path, 'D356_Vb+8to-8')

    assert exp.metadata.bias_start_V == BIAS_POSITIVE_8
    assert exp.metadata.bias_stop_V == BIAS_NEGATIVE_8


def test_bias_negative_8_to_positive_8(tmp_path):
    exp = _scan_single(tmp_path, 'D356_Vb-8to+8')

    assert exp.metadata.bias_start_V == BIAS_NEGATIVE_8
    assert exp.metadata.bias_stop_V == BIAS_POSITIVE_8


def test_bg1_plus_bg2_constraint(tmp_path):
    exp = _scan_single(tmp_path, 'D356_BG1+BG2=0')

    constraint = _constraint(exp, 'BG1+BG2=0')
    assert constraint is not None
    assert constraint.coefficients == {'BG1': 1.0, 'BG2': 1.0}
    assert constraint.control_mode is None


def test_bg1_minus_bg2_constraint(tmp_path):
    exp = _scan_single(tmp_path, 'D356_BG1-BG2=0')

    constraint = _constraint(exp, 'BG1-BG2=0')
    assert constraint is not None
    assert constraint.coefficients == {'BG1': 1.0, 'BG2': -1.0}
    assert constraint.control_mode is None


def test_tg_plus_bg_constant_doping(tmp_path):
    exp = _scan_single(tmp_path, 'D356_TG+BG=0')

    constraint = _constraint(exp, 'TG+BG=0')
    assert constraint is not None
    assert constraint.coefficients == {'TG': 1.0, 'BG': 1.0}
    assert constraint.control_mode == 'constant_doping'


def test_0p7_tg_plus_bg_constant_doping(tmp_path):
    exp = _scan_single(tmp_path, 'D356_0.7TG+BG=0')

    constraint = _constraint(exp, '0.7TG+BG=0')
    assert constraint is not None
    assert constraint.coefficients == {'TG': pytest.approx(0.7), 'BG': 1.0}
    assert constraint.control_mode == 'constant_doping'


def test_tg_plus_1p8_bg_constant_doping(tmp_path):
    exp = _scan_single(tmp_path, 'D356_TG+1.8BG=0')

    constraint = _constraint(exp, 'TG+1.8BG=0')
    assert constraint is not None
    assert constraint.coefficients == {'TG': 1.0, 'BG': pytest.approx(1.8)}
    assert constraint.control_mode == 'constant_doping'


def test_tg_minus_bg_constant_displacement_field(tmp_path):
    exp = _scan_single(tmp_path, 'D356_TG-BG=0')

    constraint = _constraint(exp, 'TG-BG=0')
    assert constraint is not None
    assert constraint.coefficients == {'TG': 1.0, 'BG': -1.0}
    assert constraint.control_mode == 'constant_displacement_field'


def test_0p7_tg_minus_bg_constant_displacement_field(tmp_path):
    exp = _scan_single(tmp_path, 'D356_0.7TG-BG=0')

    constraint = _constraint(exp, '0.7TG-BG=0')
    assert constraint is not None
    assert constraint.coefficients == {'TG': pytest.approx(0.7), 'BG': -1.0}
    assert constraint.control_mode == 'constant_displacement_field'


def test_tg_minus_1p8_bg_constant_displacement_field(tmp_path):
    exp = _scan_single(tmp_path, 'D356_TG-1.8BG=0')

    constraint = _constraint(exp, 'TG-1.8BG=0')
    assert constraint is not None
    assert constraint.coefficients == {'TG': 1.0, 'BG': pytest.approx(-1.8)}
    assert constraint.control_mode == 'constant_displacement_field'


def test_bg2_cg_is_wiring_not_subtraction(tmp_path):
    exp = _scan_single(tmp_path, 'D356_BG2-CG')

    assert exp.metadata.gate_constraints == []
    connection = _connection(exp, 'BG2-CG')
    assert connection is not None
    assert connection.nodes == ['BG2', 'CG']
    assert connection.type == 'electrically_tied'
    assert connection.source_role == 'bias_source'


def test_back_gate_topology_split(tmp_path):
    exp = _scan_single(tmp_path, 'D356_BG1+BG2=0')

    assert exp.metadata.back_gate_topology == 'split'


def test_back_gate_topology_single(tmp_path):
    exp = _scan_single(tmp_path, 'D356_TG+BG=0')

    assert exp.metadata.back_gate_topology == 'single'


def test_back_gate_topology_conflict_unsets(tmp_path):
    exp = _scan_single(tmp_path, 'D356_TG+BG=0_BG1+BG2=0')

    assert exp.metadata.back_gate_topology is None
    assert any(
        'back_gate_topology left unset' in warning for warning in exp.warnings
    )


def test_unsupported_electrical_expression_warns(tmp_path):
    exp = _scan_single(tmp_path, 'D356_TG+BG=1')

    assert exp.metadata.gate_constraints == []
    assert any(
        warning == 'unsupported electrical expression: TG+BG=1'
        for warning in exp.warnings
    )


def test_unknown_electrical_tokens_are_ignored(tmp_path):
    exp = _scan_single(tmp_path, 'D356_p1_pa1_pc1_p1n1')

    assert exp.metadata.fixed_top_gate_V is None
    assert exp.metadata.active_gate_configuration is None
    assert exp.metadata.bias_start_V is None
    assert exp.metadata.bias_stop_V is None
    assert exp.metadata.back_gate_topology is None
    assert exp.metadata.gate_constraints == []
    assert exp.metadata.electrical_connections == []
    assert not any(
        'unsupported electrical expression' in warning
        for warning in exp.warnings
    )


def test_measurement_point_label_p1(tmp_path):
    exp = _scan_single(tmp_path, 'D356_p1')

    assert exp.metadata.measurement_point_label == 'p1'


def test_measurement_point_label_p1n1(tmp_path):
    exp = _scan_single(tmp_path, 'D356_p1n1')

    assert exp.metadata.measurement_point_label == 'p1n1'


def test_measurement_point_label_embedded_after_field_t(tmp_path):
    exp = _scan_single(tmp_path, 'YZ356_9Tp1n1')

    assert exp.metadata.measurement_point_label == 'p1n1'


def test_measurement_point_label_pa1(tmp_path):
    exp = _scan_single(tmp_path, 'D356_pa1')

    assert exp.metadata.measurement_point_label == 'pa1'


def test_measurement_point_label_pc1(tmp_path):
    exp = _scan_single(tmp_path, 'D356_pc1')

    assert exp.metadata.measurement_point_label == 'pc1'


def test_measurement_point_label_px(tmp_path):
    exp = _scan_single(tmp_path, 'D356_pX')

    assert exp.metadata.measurement_point_label == 'pX'


def test_measurement_point_label_px1(tmp_path):
    exp = _scan_single(tmp_path, 'D356_pX1')

    assert exp.metadata.measurement_point_label == 'pX1'


def test_measurement_point_label_preserves_case(tmp_path):
    exp = _scan_single(tmp_path, 'D356_PX1')

    assert exp.metadata.measurement_point_label == 'PX1'


def test_unrelated_p_words_remain_unset(tmp_path):
    exp = _scan_single(tmp_path, 'D356_plot_phase_power_peak')

    assert exp.metadata.measurement_point_label is None


def test_intermediate_folder_maps_to_intermediate_role(tmp_path):
    _write(tmp_path / 'Initial Data after process' / 'D356_PL.csv')

    exp = scan_directory(tmp_path).experiments[0]

    assert exp.intermediate_files == ['Initial Data after process/D356_PL.csv']
    assert exp.raw_files == []
    assert exp.processed_files == []
    assert exp.figure_files == []


def test_raw_intermediate_processed_figure_separation(tmp_path):
    _write(tmp_path / 'Initial Data' / 'D356_PL.csv')
    _write(tmp_path / 'Initial Data after process' / 'D356_PL.csv')
    _write(tmp_path / 'Processed Data' / 'D356_PL.csv')
    _write(tmp_path / 'Processed Data' / 'D356_PL.png')

    result = scan_directory(tmp_path)

    assert len(result.experiments) == 1
    exp = result.experiments[0]
    assert exp.raw_files == ['Initial Data/D356_PL.csv']
    assert exp.intermediate_files == [
        'Initial Data after process/D356_PL.csv'
    ]
    assert exp.processed_files == ['Processed Data/D356_PL.csv']
    assert exp.figure_files == ['Processed Data/D356_PL.png']


def test_initial_data_after_processing_alias_maps_to_intermediate(tmp_path):
    _write(tmp_path / 'Initial data after processing' / 'D356_PL.csv')
    _write(tmp_path / 'Initial Data after process' / 'D356_PL.csv')
    _write(tmp_path / 'Processed Data' / 'D356_PL.csv')
    _write(tmp_path / 'Processed Data' / 'D356_PL.png')

    result = scan_directory(tmp_path)

    assert len(result.experiments) == 1
    exp = result.experiments[0]
    assert exp.intermediate_files == [
        'Initial Data after process/D356_PL.csv',
        'Initial data after processing/D356_PL.csv',
    ]
    assert exp.raw_files == []
    assert exp.processed_files == ['Processed Data/D356_PL.csv']
    assert exp.figure_files == ['Processed Data/D356_PL.png']


def test_nested_intermediate_path_uses_relative_posix(tmp_path):
    _write(tmp_path / 'Initial Data after process' / 'sub' / 'D356_PL.csv')

    exp = scan_directory(tmp_path).experiments[0]

    assert exp.intermediate_files == [
        'Initial Data after process/sub/D356_PL.csv'
    ]
    assert exp.raw_files == []
    assert exp.processed_files == []
    assert exp.figure_files == []


def test_unknown_folder_is_preserved_as_unclassified(tmp_path):
    _write(tmp_path / 'Unknown Data' / 'D356_PL.csv')

    result = scan_directory(tmp_path)

    assert result.experiments == []
    assert result.unclassified_files == ['Unknown Data/D356_PL.csv']
    assert any(
        'outside recognised data directories' in warning
        for warning in result.warnings
    )


def test_intermediate_files_serialize_to_json(tmp_path):
    _write(tmp_path / 'Initial Data after process' / 'D356_PL.csv')

    result = scan_directory(tmp_path)
    payload = json.loads(result.to_json())

    assert payload['experiments'][0]['intermediate_files'] == [
        'Initial Data after process/D356_PL.csv'
    ]


def test_tg_eq_bg_eq_0_is_fixed_values_not_constraint(tmp_path):
    exp = _scan_single(tmp_path, 'D356_TG=BG=0')

    assert exp.metadata.fixed_gate_values == {'TG': 0.0, 'BG': 0.0}
    assert exp.metadata.gate_constraints == []


def test_tg_plus_bg_0_rev_reverse_sweep(tmp_path):
    exp = _scan_single(tmp_path, 'D356_TG+BG=0Rev')

    constraint = _constraint(exp, 'TG+BG=0Rev')
    assert constraint is not None
    assert constraint.raw_expression == 'TG+BG=0Rev'
    assert constraint.coefficients == {'TG': 1.0, 'BG': 1.0}
    assert constraint.control_mode == 'constant_doping'
    assert constraint.sweep_direction == 'reverse'


def test_tg_minus_bg_0_rev_reverse_sweep(tmp_path):
    exp = _scan_single(tmp_path, 'D356_TG-BG=0Rev')

    constraint = _constraint(exp, 'TG-BG=0Rev')
    assert constraint is not None
    assert constraint.raw_expression == 'TG-BG=0Rev'
    assert constraint.coefficients == {'TG': 1.0, 'BG': -1.0}
    assert constraint.control_mode == 'constant_displacement_field'
    assert constraint.sweep_direction == 'reverse'


def test_tg_plus_bg_without_rev_has_no_sweep_direction(tmp_path):
    exp = _scan_single(tmp_path, 'D356_TG+BG=0')

    constraint = _constraint(exp, 'TG+BG=0')
    assert constraint is not None
    assert constraint.sweep_direction is None
