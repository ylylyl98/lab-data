import os

from nomad.client import normalize_all, parse


def test_schema_package():
    test_file = os.path.join('tests', 'data', 'test.archive.yaml')

    entry_archive = parse(test_file)[0]
    normalize_all(entry_archive)

    data = entry_archive.data

    assert data.experiment_id == 'TEST-001'
    assert data.sample_id == 'D356'
    assert data.measurement_type == 'photocurrent'
    assert data.temperature.magnitude == 3.6
    assert data.magnetic_field.magnitude == 9
    assert data.polarization == 'sigma_plus'
    assert data.instrument == 'WinSpec'
    assert data.grating.magnitude == 1200