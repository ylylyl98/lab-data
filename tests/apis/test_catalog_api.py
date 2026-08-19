from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from nomad.config import config

from lab_data.artifact_previews import build_artifact_preview
from lab_data.scientific_catalog import (
    SUBJECT_DEVICE,
    SUBJECT_EXPERIMENT,
    Artifact,
    CatalogSnapshot,
    Device,
    Experiment,
    Relationship,
    SQLiteCatalogStore,
    StorageReference,
)

config.load_plugins()

from lab_data.apis.api import create_app  # noqa: E402


def _dir_files(root: Path) -> tuple[str, ...]:
    return tuple(sorted(path.name for path in root.rglob('*') if path.is_file()))


def _tree_hashes(root: Path) -> tuple[tuple[str, str], ...]:
    entries = []
    for path in sorted(root.rglob('*')):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            entries.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    return tuple(entries)


def _seed(tmp_path: Path) -> tuple[Path, Path, Path]:
    catalog_path = tmp_path / 'catalog' / 'catalog.db'
    catalog_path.parent.mkdir()
    preview_root = tmp_path / 'preview'
    source_root = tmp_path / 'source'
    source_root.mkdir()
    source_file = source_root / 'table.csv'
    source_file.write_text('x,y\n1,2\n', encoding='utf-8')
    stat = source_file.stat()

    experiments = (
        Experiment(
            experiment_id='exp-a',
            metadata={'sample_id': 'D356', 'measurement_type': 'optical'},
            files_by_role={'raw': (StorageReference('source', 'raw/D356.dat'),)},
        ),
        Experiment(
            experiment_id='exp-b',
            metadata={'sample_id': 'D357', 'measurement_type': 'transport'},
            files_by_role={'raw': (StorageReference('source', 'raw/D357.dat'),)},
        ),
        Experiment(
            experiment_id='exp-inferred',
            metadata={'sample_id': 'D356', 'measurement_type': 'zzz'},
            files_by_role={},
        ),
    )
    devices = (
        Device('D357', device_type='chip', aliases=('alias-b',), display_label='B'),
        Device('D356', device_type='chip', aliases=('alias-a',), display_label='A'),
    )
    artifacts = (
        Artifact(
            'doc-b',
            extension='pdf',
            media_type='application/pdf',
            device_id='D357',
            storage_reference=StorageReference('source', 'docs/D357.pdf'),
        ),
        Artifact(
            'slides-b',
            extension='pptx',
            media_type='application/vnd.openxmlformats-officedocument.presentationml.presentation',
            category='slide',
            device_id='D357',
            storage_reference=StorageReference('source', 'docs/D357.pptx'),
        ),
        Artifact(
            'doc-a',
            extension='ppt',
            media_type='application/vnd.ms-powerpoint',
            device_id='D356',
            storage_reference=StorageReference('source', 'docs/D356.ppt'),
        ),
        Artifact(
            'table',
            extension='csv',
            media_type='text/csv',
            device_id='D356',
            storage_reference=StorageReference('source', 'table.csv'),
            size_bytes=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
        ),
    )
    relationships = (
        Relationship(
            source_type=SUBJECT_EXPERIMENT,
            source_id='exp-a',
            predicate='measured_on',
            target_type=SUBJECT_DEVICE,
            target_id='D356',
        ),
    )

    store = SQLiteCatalogStore(catalog_path)
    store.rebuild(CatalogSnapshot(experiments, devices, artifacts, relationships))
    build_artifact_preview(
        store,
        'table',
        storage_roots={'source': source_root},
        preview_root=preview_root,
    )
    store.close()
    return catalog_path, preview_root, source_file


def test_routes_are_read_only_and_deterministic(tmp_path):
    catalog_path, preview_root, source_file = _seed(tmp_path)
    catalog_hash = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    catalog_files = _dir_files(catalog_path.parent)
    preview_before = _tree_hashes(preview_root)
    source_file.unlink()

    client = TestClient(create_app(catalog_path, preview_root))

    assert client.get('/').json() == {'message': 'Hello World'}

    devices = client.get('/devices')
    assert devices.status_code == 200  # noqa: PLR2004
    assert [item['device_id'] for item in devices.json()] == ['D356', 'D357']

    filtered = client.get('/devices', params={'device_id': 'D356'})
    assert [item['device_id'] for item in filtered.json()] == ['D356']
    assert filtered.json()[0]['display_label'] == 'A'

    experiments = client.get('/experiments')
    assert experiments.status_code == 200  # noqa: PLR2004
    assert [item['experiment_id'] for item in experiments.json()] == [
        'exp-a',
        'exp-inferred',
        'exp-b',
    ]

    filtered = client.get('/experiments', params={'experiment_id': 'exp-a'})
    assert [item['experiment_id'] for item in filtered.json()] == ['exp-a']

    artifacts = client.get('/artifacts')
    assert [item['artifact_id'] for item in artifacts.json()] == [
        'doc-a',
        'doc-b',
        'slides-b',
        'table',
    ]

    filtered = client.get('/artifacts', params={'device_id': 'D356'})
    assert [item['artifact_id'] for item in filtered.json()] == ['doc-a', 'table']

    device_experiments = client.get('/devices/D356/experiments')
    assert [item['experiment_id'] for item in device_experiments.json()] == ['exp-a']

    device_documents = client.get('/devices/D356/documents')
    assert [item['artifact_id'] for item in device_documents.json()] == ['doc-a']

    preview = client.get('/artifacts/table/preview')
    assert preview.status_code == 200  # noqa: PLR2004
    assert preview.headers['content-type'].startswith('application/json')
    assert preview.json()['artifact_id'] == 'table'
    assert preview.json()['preview_id']

    missing_preview = client.get('/artifacts/missing/preview')
    assert missing_preview.status_code == 200  # noqa: PLR2004
    assert missing_preview.json() is None

    assert hashlib.sha256(catalog_path.read_bytes()).hexdigest() == catalog_hash
    assert _dir_files(catalog_path.parent) == catalog_files
    assert _tree_hashes(preview_root) == preview_before


def test_missing_catalog_path_fails_without_creating_files(tmp_path):
    catalog_path = tmp_path / 'missing' / 'catalog.db'
    client = TestClient(create_app(catalog_path, tmp_path / 'preview'))

    for route in ('/devices', '/experiments', '/artifacts'):
        response = client.get(route)
        assert response.status_code == 503  # noqa: PLR2004
        assert response.json()['detail'] == 'catalog is unavailable'
        assert str(catalog_path) not in response.text

    assert not catalog_path.exists()
    assert not catalog_path.parent.exists()


def test_unconfigured_catalog_fails_clearly():
    client = TestClient(create_app(None, None))
    response = client.get('/devices')
    assert response.status_code == 503  # noqa: PLR2004
    assert response.json()['detail'] == 'catalog is not configured'


def test_unconfigured_preview_fails_clearly(tmp_path):
    catalog_path, _, _ = _seed(tmp_path)
    client = TestClient(create_app(catalog_path, None))
    response = client.get('/artifacts/table/preview')
    assert response.status_code == 503  # noqa: PLR2004
    assert response.json()['detail'] == 'preview cache is not configured'


def test_invalid_query_type_returns_fastapi_validation_error(tmp_path):
    catalog_path, preview_root, _ = _seed(tmp_path)
    client = TestClient(create_app(catalog_path, preview_root))
    response = client.get('/experiments', params={'needs_review': 'not-a-bool'})
    assert response.status_code == 422  # noqa: PLR2004


def _experiment_filter_seed(tmp_path: Path) -> Path:
    catalog_path = tmp_path / 'catalog' / 'catalog.db'
    catalog_path.parent.mkdir()
    experiments = (
        Experiment(
            'exp-b',
            metadata={
                'sample_id': 'S1',
                'measurement_type': 'transport',
                'temperature_K': 300.0,
                'averages': 10,
                'measurement_point_label': 'P2',
                'stage_position': 2,
                'fixed_top_gate_V': -1.0,
                'active_gate_configuration': 'double',
            },
            files_by_role={},
            needs_review=True,
        ),
        Experiment(
            'exp-a',
            metadata={
                'sample_id': 'S1',
                'measurement_type': 'optical',
                'temperature_K': 77.0,
                'averages': 5,
                'measurement_point_label': 'P1',
                'excitation_wavelength_nm': 532.0,
                'center_wavelength_nm': 520.0,
                'excitation_power_uW': 50.0,
                'grating_grooves_per_mm': 600,
            },
            files_by_role={},
            confidence=0.9,
        ),
        Experiment(
            'exp-c',
            metadata={
                'sample_id': 'S2',
                'measurement_type': 'optical',
                'magnetic_field_T': 1.5,
                'integration_time_s': 0.06,
                'bias_start_V': -3.0,
                'bias_stop_V': 3.0,
                'back_gate_topology': 'floating',
            },
            files_by_role={},
        ),
    )
    store = SQLiteCatalogStore(catalog_path)
    store.rebuild(CatalogSnapshot(experiments=experiments, devices=(Device('D356'),)))
    store.close()
    return catalog_path


def test_experiment_scalar_equality_filters(tmp_path):
    catalog_path = _experiment_filter_seed(tmp_path)
    client = TestClient(create_app(catalog_path, None))

    assert [item['experiment_id'] for item in client.get('/experiments').json()] == [
        'exp-a',
        'exp-b',
        'exp-c',
    ]

    broad = client.get('/experiments', params={'sample_id': 'S1'})
    assert broad.status_code == 200  # noqa: PLR2004
    assert [item['experiment_id'] for item in broad.json()] == ['exp-a', 'exp-b']

    by_measurement = client.get('/experiments', params={'measurement_type': 'optical'})
    assert [item['experiment_id'] for item in by_measurement.json()] == [
        'exp-a',
        'exp-c',
    ]

    by_temperature = client.get('/experiments', params={'temperature_K': '77.0'})
    assert [item['experiment_id'] for item in by_temperature.json()] == ['exp-a']

    by_averages = client.get('/experiments', params={'averages': '10'})
    assert [item['experiment_id'] for item in by_averages.json()] == ['exp-b']

    by_field = client.get('/experiments', params={'magnetic_field_T': '1.5'})
    assert [item['experiment_id'] for item in by_field.json()] == ['exp-c']

    by_integration = client.get('/experiments', params={'integration_time_s': '0.06'})
    assert [item['experiment_id'] for item in by_integration.json()] == ['exp-c']

    by_point = client.get('/experiments', params={'measurement_point_label': 'P1'})
    assert [item['experiment_id'] for item in by_point.json()] == ['exp-a']

    by_confidence = client.get('/experiments', params={'confidence': '0.9'})
    assert [item['experiment_id'] for item in by_confidence.json()] == ['exp-a']

    by_review = client.get('/experiments', params={'needs_review': 'true'})
    assert [item['experiment_id'] for item in by_review.json()] == ['exp-b']

    exact = client.get('/experiments', params={'experiment_id': 'exp-b'})
    assert [item['experiment_id'] for item in exact.json()] == ['exp-b']


@pytest.mark.parametrize(
    ('param', 'value', 'expected'),
    [
        ('excitation_wavelength_nm', '532.0', 'exp-a'),
        ('center_wavelength_nm', '520.0', 'exp-a'),
        ('excitation_power_uW', '50.0', 'exp-a'),
        ('grating_grooves_per_mm', '600', 'exp-a'),
        ('stage_position', '2', 'exp-b'),
        ('fixed_top_gate_V', '-1.0', 'exp-b'),
        ('active_gate_configuration', 'double', 'exp-b'),
        ('bias_start_V', '-3.0', 'exp-c'),
        ('bias_stop_V', '3.0', 'exp-c'),
        ('back_gate_topology', 'floating', 'exp-c'),
    ],
)
def test_experiment_remaining_scalar_filters(tmp_path, param, value, expected):
    catalog_path = _experiment_filter_seed(tmp_path)
    client = TestClient(create_app(catalog_path, None))
    response = client.get('/experiments', params={param: value})
    assert response.status_code == 200  # noqa: PLR2004
    assert [item['experiment_id'] for item in response.json()] == [expected]


@pytest.mark.parametrize(
    ('route', 'misspelled'),
    [
        ('/devices', 'devce_id'),
        ('/experiments', 'sampel_id'),
        ('/artifacts', 'artifct_id'),
    ],
)
def test_unknown_query_parameters_return_422(tmp_path, route, misspelled):
    catalog_path, preview_root, _ = _seed(tmp_path)
    client = TestClient(create_app(catalog_path, preview_root))
    response = client.get(route, params={misspelled: 'value'})
    assert response.status_code == 422  # noqa: PLR2004
    detail = response.json()['detail']
    assert isinstance(detail, list)
    assert any(item.get('loc') == ['query', misspelled] for item in detail)
