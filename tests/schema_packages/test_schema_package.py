import os

from nomad.client import normalize_all, parse

from lab_data.schema_packages.schema_package import GateValue, OpticalExperiment

EXPECTED_TEMPERATURE = 3.6
EXPECTED_MAGNETIC_FIELD = 9
EXPECTED_GRATING = 1200
EXPECTED_GATE_COUNT = 2
BG_VOLTAGE = 1.5


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
