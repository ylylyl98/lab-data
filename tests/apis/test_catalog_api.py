from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from nomad.config import config

from lab_data.artifact_previews import build_artifact_preview
from lab_data.scientific_catalog import (
    ENTITY_FILE,
    SUBJECT_DEVICE,
    SUBJECT_EXPERIMENT,
    Artifact,
    CatalogSnapshot,
    Device,
    Experiment,
    MetadataClaim,
    Relationship,
    SQLiteCatalogStore,
    StorageReference,
    deterministic_storage_reference_id,
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
            claims=(
                MetadataClaim(
                    subject_type=SUBJECT_EXPERIMENT,
                    subject_id='exp-a',
                    field='measured_on_device',
                    value={
                        'device_id': 'D356',
                        'directory_context': 'D356 WSe2_AuSplitGate',
                    },
                    source_type='storage_directory',
                    source_reference='D356 WSe2_AuSplitGate',
                    extraction_method='device_directory_context',
                    category='device_linkage',
                    review_status='unknown',
                ),
            ),
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

    devices = client.get('/api/devices')
    assert devices.status_code == 200  # noqa: PLR2004
    assert devices.json()['total_count'] == 2  # noqa: PLR2004
    assert devices.json()['limit'] == 50  # noqa: PLR2004
    assert devices.json()['offset'] == 0
    assert [item['device_id'] for item in devices.json()['items']] == ['D356', 'D357']

    filtered = client.get('/api/devices', params={'device_id': 'D356'})
    assert [item['device_id'] for item in filtered.json()['items']] == ['D356']
    assert filtered.json()['items'][0]['display_label'] == 'A'

    experiments = client.get('/api/experiments')
    assert experiments.status_code == 200  # noqa: PLR2004
    assert [item['experiment_id'] for item in experiments.json()['items']] == [
        'exp-a',
        'exp-inferred',
        'exp-b',
    ]

    filtered = client.get('/api/experiments', params={'experiment_id': 'exp-a'})
    assert [item['experiment_id'] for item in filtered.json()['items']] == ['exp-a']

    artifacts = client.get('/api/artifacts')
    assert [item['artifact_id'] for item in artifacts.json()['items']] == [
        'doc-a',
        'doc-b',
        'slides-b',
        'table',
    ]

    filtered = client.get('/api/artifacts', params={'device_id': 'D356'})
    assert [item['artifact_id'] for item in filtered.json()['items']] == [
        'doc-a',
        'table',
    ]

    device_experiments = client.get('/api/devices/D356/experiments')
    assert [
        item['experiment_id'] for item in device_experiments.json()['items']
    ] == ['exp-a']

    device_documents = client.get('/api/devices/D356/documents')
    assert [item['artifact_id'] for item in device_documents.json()['items']] == ['doc-a']

    preview = client.get('/api/artifacts/table/preview')
    assert preview.status_code == 200  # noqa: PLR2004
    assert preview.headers['content-type'].startswith('application/json')
    assert preview.json()['artifact_id'] == 'table'
    assert preview.json()['preview_id']

    missing_preview = client.get('/api/artifacts/missing/preview')
    assert missing_preview.status_code == 200  # noqa: PLR2004
    assert missing_preview.json() is None

    assert hashlib.sha256(catalog_path.read_bytes()).hexdigest() == catalog_hash
    assert _dir_files(catalog_path.parent) == catalog_files
    assert _tree_hashes(preview_root) == preview_before


def test_experiment_provenance_projections(tmp_path):
    catalog_path, preview_root, _ = _seed(tmp_path)
    client = TestClient(create_app(catalog_path, preview_root))

    measured = client.get('/api/experiments', params={'experiment_id': 'exp-a'})
    measured_item = measured.json()['items'][0]
    assert measured_item['review_state'] == 'unknown'
    assert measured_item['measured_on'] == {
        'device_id': 'D356',
        'evidence': 'explicit device-directory context',
        'source_reference': 'D356 WSe2_AuSplitGate',
        'extraction_method': 'device_directory_context',
        'review_status': 'unknown',
    }

    free = client.get('/api/experiments', params={'experiment_id': 'exp-b'})
    free_item = free.json()['items'][0]
    assert free_item['measured_on'] is None
    assert free_item['review_state'] == 'unknown'


def _lineage_seed(tmp_path: Path) -> Path:
    catalog_path = tmp_path / 'catalog' / 'catalog.db'
    catalog_path.parent.mkdir()
    raw = StorageReference('source', 'raw/YZ356_BG1only.csv')
    dat = StorageReference('source', 'processed/YZ356_BG1only_PL.dat')
    linear = StorageReference('source', 'processed/YZ356_BG1only_PL_linear.png')
    experiment = Experiment(
        'exp-fig',
        metadata={},
        files_by_role={'raw': (raw,), 'processed': (dat,), 'figure': (linear,)},
    )
    artifact = Artifact(
        'fig-linear',
        extension='png',
        media_type='image/png',
        storage_reference=linear,
    )

    def file_id(reference: StorageReference) -> str:
        return deterministic_storage_reference_id(
            storage_source_id=reference.storage_source_id,
            relative_path=reference.relative_path,
        )

    relationships = (
        Relationship(
            source_type=ENTITY_FILE,
            source_id=file_id(dat),
            predicate='derived_from',
            target_type=ENTITY_FILE,
            target_id=file_id(raw),
        ),
        Relationship(
            source_type=ENTITY_FILE,
            source_id=file_id(linear),
            predicate='derived_from',
            target_type=ENTITY_FILE,
            target_id=file_id(dat),
        ),
    )
    store = SQLiteCatalogStore(catalog_path)
    store.rebuild(
        CatalogSnapshot(
            (experiment,), artifacts=(artifact,), relationships=relationships
        )
    )
    store.close()
    return catalog_path


def test_artifact_derived_from_projection(tmp_path):
    catalog_path = _lineage_seed(tmp_path)
    client = TestClient(create_app(catalog_path, None))

    response = client.get('/api/artifacts', params={'artifact_id': 'fig-linear'})
    assert response.status_code == 200  # noqa: PLR2004
    item = response.json()['items'][0]
    assert item['derived_from'] == [
        {
            'source': 'processed/YZ356_BG1only_PL_linear.png',
            'target': 'processed/YZ356_BG1only_PL.dat',
            'relation': 'derived_from',
        },
    ]
    assert not any(
        Path(edge['source']).is_absolute() or Path(edge['target']).is_absolute()
        for edge in item['derived_from']
    )


def test_missing_catalog_path_fails_without_creating_files(tmp_path):
    catalog_path = tmp_path / 'missing' / 'catalog.db'
    client = TestClient(create_app(catalog_path, tmp_path / 'preview'))

    for route in ('/api/devices', '/api/experiments', '/api/artifacts'):
        response = client.get(route)
        assert response.status_code == 503  # noqa: PLR2004
        assert response.json()['detail'] == 'catalog is unavailable'
        assert str(catalog_path) not in response.text

    assert not catalog_path.exists()
    assert not catalog_path.parent.exists()


def test_unconfigured_catalog_fails_clearly():
    client = TestClient(create_app(None, None))
    response = client.get('/api/devices')
    assert response.status_code == 503  # noqa: PLR2004
    assert response.json()['detail'] == 'catalog is not configured'


def test_unconfigured_preview_fails_clearly(tmp_path):
    catalog_path, _, _ = _seed(tmp_path)
    client = TestClient(create_app(catalog_path, None))
    response = client.get('/api/artifacts/table/preview')
    assert response.status_code == 503  # noqa: PLR2004
    assert response.json()['detail'] == 'preview cache is not configured'


def test_invalid_query_type_returns_fastapi_validation_error(tmp_path):
    catalog_path, preview_root, _ = _seed(tmp_path)
    client = TestClient(create_app(catalog_path, preview_root))
    response = client.get('/api/experiments', params={'needs_review': 'not-a-bool'})
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

    assert [
        item['experiment_id'] for item in client.get('/api/experiments').json()['items']
    ] == ['exp-a', 'exp-b', 'exp-c']

    broad = client.get('/api/experiments', params={'sample_id': 'S1'})
    assert broad.status_code == 200  # noqa: PLR2004
    assert [item['experiment_id'] for item in broad.json()['items']] == [
        'exp-a',
        'exp-b',
    ]

    by_measurement = client.get(
        '/api/experiments', params={'measurement_type': 'optical'}
    )
    assert [item['experiment_id'] for item in by_measurement.json()['items']] == [
        'exp-a',
        'exp-c',
    ]

    by_temperature = client.get('/api/experiments', params={'temperature_K': '77.0'})
    assert [item['experiment_id'] for item in by_temperature.json()['items']] == ['exp-a']

    by_averages = client.get('/api/experiments', params={'averages': '10'})
    assert [item['experiment_id'] for item in by_averages.json()['items']] == ['exp-b']

    by_field = client.get('/api/experiments', params={'magnetic_field_T': '1.5'})
    assert [item['experiment_id'] for item in by_field.json()['items']] == ['exp-c']

    by_integration = client.get(
        '/api/experiments', params={'integration_time_s': '0.06'}
    )
    assert [item['experiment_id'] for item in by_integration.json()['items']] == ['exp-c']

    by_point = client.get('/api/experiments', params={'measurement_point_label': 'P1'})
    assert [item['experiment_id'] for item in by_point.json()['items']] == ['exp-a']

    by_confidence = client.get('/api/experiments', params={'confidence': '0.9'})
    assert [item['experiment_id'] for item in by_confidence.json()['items']] == ['exp-a']

    by_review = client.get('/api/experiments', params={'needs_review': 'true'})
    assert [item['experiment_id'] for item in by_review.json()['items']] == ['exp-b']

    exact = client.get('/api/experiments', params={'experiment_id': 'exp-b'})
    assert [item['experiment_id'] for item in exact.json()['items']] == ['exp-b']


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
    response = client.get('/api/experiments', params={param: value})
    assert response.status_code == 200  # noqa: PLR2004
    assert [item['experiment_id'] for item in response.json()['items']] == [expected]


@pytest.mark.parametrize(
    ('route', 'misspelled'),
    [
        ('/api/devices', 'devce_id'),
        ('/api/experiments', 'sampel_id'),
        ('/api/artifacts', 'artifct_id'),
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


def test_summary_counts(tmp_path):
    catalog_path, preview_root, _ = _seed(tmp_path)
    client = TestClient(create_app(catalog_path, preview_root))
    assert client.get('/api/summary').json() == {
        'devices': 2,
        'experiments': 3,
        'artifacts': 4,
    }


def test_list_envelope_shape_and_pagination_bounds(tmp_path):
    catalog_path, preview_root, _ = _seed(tmp_path)
    client = TestClient(create_app(catalog_path, preview_root))

    body = client.get('/api/artifacts', params={'limit': 2, 'offset': 0}).json()
    assert set(body) == {'items', 'total_count', 'limit', 'offset'}
    assert len(body['items']) == 2  # noqa: PLR2004
    assert body['limit'] == 2  # noqa: PLR2004
    assert body['offset'] == 0
    assert body['total_count'] == 4  # noqa: PLR2004

    assert client.get('/api/artifacts', params={'limit': 0}).status_code == 422  # noqa: PLR2004
    assert client.get('/api/artifacts', params={'limit': 201}).status_code == 422  # noqa: PLR2004
    assert client.get('/api/artifacts', params={'offset': -1}).status_code == 422  # noqa: PLR2004


def test_artifact_pagination_adjacent_pages_do_not_overlap(tmp_path):
    catalog_path, preview_root, _ = _seed(tmp_path)
    client = TestClient(create_app(catalog_path, preview_root))

    first = client.get('/api/artifacts', params={'limit': 2, 'offset': 0}).json()
    second = client.get('/api/artifacts', params={'limit': 2, 'offset': 2}).json()

    assert [item['artifact_id'] for item in first['items']] == ['doc-a', 'doc-b']
    assert [item['artifact_id'] for item in second['items']] == ['slides-b', 'table']
    assert first['total_count'] == second['total_count'] == 4  # noqa: PLR2004


def test_artifact_kind_filter(tmp_path):
    catalog_path, preview_root, _ = _seed(tmp_path)
    client = TestClient(create_app(catalog_path, preview_root))

    data = client.get('/api/artifacts', params={'kind': 'data'})
    assert [item['artifact_id'] for item in data.json()['items']] == ['table']
    assert data.json()['total_count'] == 1
    assert client.get('/api/artifacts', params={'kind': 'invalid'}).status_code == 422  # noqa: PLR2004


def test_q_search_is_case_insensitive_substring(tmp_path):
    catalog_path, preview_root, _ = _seed(tmp_path)
    client = TestClient(create_app(catalog_path, preview_root))

    devices = client.get('/api/devices', params={'q': '356'})
    assert [item['device_id'] for item in devices.json()['items']] == ['D356']

    experiments = client.get('/api/experiments', params={'q': 'd356'})
    assert [item['experiment_id'] for item in experiments.json()['items']] == [
        'exp-a',
        'exp-inferred',
    ]

    artifacts = client.get('/api/artifacts', params={'q': 'D356'})
    assert [item['artifact_id'] for item in artifacts.json()['items']] == ['doc-a']
    assert artifacts.json()['items'][0]['filename'] == 'D356.ppt'
