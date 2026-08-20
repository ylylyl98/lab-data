"""Tests for production single-origin serving and deployment configuration."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from nomad.config import config

config.load_plugins()

from lab_data import deployment  # noqa: E402
from lab_data.apis.api import create_app  # noqa: E402
from lab_data.scientific_catalog import (  # noqa: E402
    Artifact,
    CatalogSnapshot,
    Experiment,
    SQLiteCatalogStore,
    StorageReference,
)


def _make_frontend(tmp_path: Path) -> Path:
    frontend = tmp_path / 'frontend'
    (frontend / 'assets').mkdir(parents=True)
    (frontend / 'index.html').write_text(
        '<!doctype html><title>lab-data browser</title>', encoding='utf-8'
    )
    (frontend / 'assets' / 'app.js').write_text(
        'console.log("lab-data");', encoding='utf-8'
    )
    (frontend / 'assets' / 'app.css').write_text(
        'body { color: red; }', encoding='utf-8'
    )
    return frontend


def _seed_catalog(tmp_path: Path) -> Path:
    catalog_path = tmp_path / 'catalog' / 'catalog.db'
    catalog_path.parent.mkdir()
    store = SQLiteCatalogStore(catalog_path)
    store.rebuild(
        CatalogSnapshot(
            experiments=(Experiment('D356-0316', metadata={}, files_by_role={}),),
            artifacts=(
                Artifact(
                    'table',
                    extension='csv',
                    media_type='text/csv',
                    storage_reference=StorageReference('source', 'table.csv'),
                ),
            ),
        )
    )
    store.close()
    return catalog_path


def test_default_host_and_port(monkeypatch):
    monkeypatch.delenv(deployment.HOST_ENV, raising=False)
    monkeypatch.delenv(deployment.PORT_ENV, raising=False)
    assert deployment.DEFAULT_HOST == '127.0.0.1'
    assert deployment.DEFAULT_PORT == 8000  # noqa: PLR2004
    assert deployment.load_host() == '127.0.0.1'
    assert deployment.load_port() == 8000  # noqa: PLR2004


def test_explicit_host_and_port_env(monkeypatch):
    monkeypatch.setenv(deployment.HOST_ENV, '0.0.0.0')
    monkeypatch.setenv(deployment.PORT_ENV, '8765')
    assert deployment.load_host() == '0.0.0.0'
    assert deployment.load_port() == 8765  # noqa: PLR2004


@pytest.mark.parametrize('raw', ['not-a-port', '-1', '70000', '0'])
def test_invalid_port_rejected(monkeypatch, raw):
    monkeypatch.setenv(deployment.PORT_ENV, raw)
    with pytest.raises(ValueError):
        deployment.load_port()


def test_default_frontend_dir_is_repo_relative():
    assert deployment.default_frontend_dir() == (
        deployment.repo_root() / 'frontend' / 'dist'
    )


def test_frontend_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv(deployment.FRONTEND_DIST_ENV, str(tmp_path / 'dist'))
    assert deployment.load_frontend_dir() == tmp_path / 'dist'


def test_production_config_requires_env(monkeypatch):
    monkeypatch.delenv(deployment.CATALOG_PATH_ENV, raising=False)
    monkeypatch.delenv(deployment.PREVIEW_ROOT_ENV, raising=False)
    with pytest.raises(ValueError, match='must both be set'):
        deployment.load_production_config()


def test_production_config_validates_paths(monkeypatch, tmp_path):
    monkeypatch.setenv(deployment.CATALOG_PATH_ENV, str(tmp_path / 'missing.db'))
    monkeypatch.setenv(deployment.PREVIEW_ROOT_ENV, str(tmp_path / 'missing-preview'))
    with pytest.raises(ValueError, match='catalog file'):
        deployment.load_production_config()


def test_production_frontend_serving(tmp_path):
    frontend = _make_frontend(tmp_path)
    client = TestClient(create_app(None, None, frontend_dir=frontend))

    root = client.get('/')
    assert root.status_code == 200  # noqa: PLR2004
    assert root.headers['content-type'].startswith('text/html')
    assert 'lab-data browser' in root.text

    script = client.get('/assets/app.js')
    assert script.status_code == 200  # noqa: PLR2004
    assert script.headers['content-type'].startswith('text/javascript')
    assert script.text == 'console.log("lab-data");'

    styles = client.get('/assets/app.css')
    assert styles.status_code == 200  # noqa: PLR2004
    assert styles.headers['content-type'].startswith('text/css')

    for spa_route in (
        '/devices',
        '/experiments',
        '/artifacts',
        '/devices/D356',
        '/experiments/D356-0000',
        '/artifacts/table',
    ):
        spa = client.get(spa_route)
        assert spa.status_code == 200  # noqa: PLR2004
        assert spa.headers['content-type'].startswith('text/html')
        assert 'lab-data browser' in spa.text


def test_spa_fallback_does_not_capture_api(tmp_path):
    catalog_path = _seed_catalog(tmp_path)
    frontend = _make_frontend(tmp_path)
    client = TestClient(create_app(catalog_path, None, frontend_dir=frontend))

    for route in ('/api/summary', '/api/devices', '/api/experiments', '/api/artifacts'):
        response = client.get(route)
        assert response.status_code == 200  # noqa: PLR2004
        assert response.headers['content-type'].startswith('application/json')

    preview = client.get('/api/artifacts/table/preview')
    assert preview.status_code == 503  # noqa: PLR2004
    assert preview.headers['content-type'].startswith('application/json')

    asset = client.get('/api/artifacts/table/preview/assets/table.json')
    assert asset.status_code == 503  # noqa: PLR2004
    assert asset.headers['content-type'].startswith('application/json')

    for api_shaped in (
        '/api/devices/D356/experiments/extra',
        '/api/devices/D356/documents/extra',
        '/api/summary/extra',
        '/api/artifacts/D356/preview/extra',
    ):
        response = client.get(api_shaped)
        assert response.status_code == 404  # noqa: PLR2004
        assert response.headers['content-type'].startswith('application/json')


def test_spa_list_routes_stay_pages_while_api_returns_json(tmp_path):
    catalog_path = _seed_catalog(tmp_path)
    frontend = _make_frontend(tmp_path)
    client = TestClient(create_app(catalog_path, None, frontend_dir=frontend))

    for spa_route in ('/devices', '/experiments', '/artifacts'):
        page = client.get(spa_route)
        assert page.status_code == 200  # noqa: PLR2004
        assert page.headers['content-type'].startswith('text/html')
        assert 'lab-data browser' in page.text

    api = client.get('/api/devices')
    assert api.status_code == 200  # noqa: PLR2004
    assert api.headers['content-type'].startswith('application/json')
    assert api.json()['total_count'] == 0


def test_missing_frontend_build_raises(tmp_path):
    with pytest.raises(ValueError, match='index.html'):
        create_app(None, None, frontend_dir=tmp_path / 'missing-frontend')
    empty = tmp_path / 'empty-frontend'
    empty.mkdir()
    with pytest.raises(ValueError, match='index.html'):
        create_app(None, None, frontend_dir=empty)


def test_frontend_static_path_traversal_rejected(tmp_path):
    frontend = _make_frontend(tmp_path)
    client = TestClient(create_app(None, None, frontend_dir=frontend))
    for path in (
        '/assets/%2e%2e/secrets.txt',
        '/assets/..%2fsecrets.txt',
        '/%2e%2e/secrets.txt',
        '/..%2fsecrets.txt',
    ):
        response = client.get(path)
        assert response.status_code in (400, 404, 422)  # noqa: PLR2004
        assert 'SECRETS' not in response.text
        assert not response.headers['content-type'].startswith('text/html')


def test_all_routes_are_get_only(tmp_path):
    frontend = _make_frontend(tmp_path)
    app = create_app(None, None, frontend_dir=frontend)
    for route in app.routes:
        methods = getattr(route, 'methods', None)
        if methods is not None:
            assert methods <= {'GET', 'HEAD'}, route.path
