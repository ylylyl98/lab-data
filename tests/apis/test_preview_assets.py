from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from nomad.config import config

from lab_data.artifact_previews import build_artifact_preview
from lab_data.scientific_catalog import (
    Artifact,
    CatalogSnapshot,
    SQLiteCatalogStore,
    StorageReference,
)

config.load_plugins()

from lab_data.apis.api import create_app  # noqa: E402


def _seed(tmp_path: Path) -> tuple[Path, Path, bytes]:
    catalog_path = tmp_path / 'catalog' / 'catalog.db'
    catalog_path.parent.mkdir()
    preview_root = tmp_path / 'preview'
    source_root = tmp_path / 'source'
    source_root.mkdir()
    source_file = source_root / 'table.csv'
    source_file.write_text('x,y\n1,2\n', encoding='utf-8')
    stat = source_file.stat()

    artifact = Artifact(
        'table',
        extension='csv',
        media_type='text/csv',
        storage_reference=StorageReference('source', 'table.csv'),
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )
    store = SQLiteCatalogStore(catalog_path)
    store.rebuild(CatalogSnapshot(experiments=(), artifacts=(artifact,)))
    preview = build_artifact_preview(
        store,
        'table',
        storage_roots={'source': source_root},
        preview_root=preview_root,
    )
    table_bytes = (preview.object_dir / 'table.json').read_bytes()
    store.close()
    return catalog_path, preview_root, table_bytes


def test_preview_asset_route_serves_validated_bytes(tmp_path):
    catalog_path, preview_root, table_bytes = _seed(tmp_path)
    client = TestClient(create_app(catalog_path, preview_root))

    response = client.get('/api/artifacts/table/preview/assets/table.json')
    assert response.status_code == 200  # noqa: PLR2004
    assert response.headers['content-type'] == 'application/json'
    assert response.content == table_bytes


def test_preview_asset_route_rejects_unknown_asset(tmp_path):
    catalog_path, preview_root, _ = _seed(tmp_path)
    client = TestClient(create_app(catalog_path, preview_root))

    response = client.get('/api/artifacts/table/preview/assets/missing.png')
    assert response.status_code == 404  # noqa: PLR2004
    assert response.json()['detail'] == 'preview asset not found'


def test_preview_asset_route_rejects_manifest_external_path(tmp_path):
    catalog_path, preview_root, _ = _seed(tmp_path)
    client = TestClient(create_app(catalog_path, preview_root))

    response = client.get('/api/artifacts/table/preview/assets/../../etc')
    assert response.status_code == 404  # noqa: PLR2004
    # Starlette may normalize the traversal before routing, but either way the
    # request must be rejected and never serve bytes.
    assert 'detail' in response.json()


def test_preview_asset_route_serves_svg_media_type(tmp_path):
    catalog_path, preview_root, _ = _seed(tmp_path)
    client = TestClient(create_app(catalog_path, preview_root))

    response = client.get('/api/artifacts/table/preview/assets/plot.svg')
    assert response.status_code == 200  # noqa: PLR2004
    assert response.headers['content-type'] == 'image/svg+xml'


def test_preview_asset_route_rejects_unknown_artifact(tmp_path):
    catalog_path, preview_root, _ = _seed(tmp_path)
    client = TestClient(create_app(catalog_path, preview_root))

    response = client.get('/api/artifacts/missing/preview/assets/table.json')
    assert response.status_code == 404  # noqa: PLR2004
    assert response.json()['detail'] == 'preview asset not found'


def test_preview_asset_route_requires_preview_root(tmp_path):
    catalog_path, _, _ = _seed(tmp_path)
    client = TestClient(create_app(catalog_path, None))

    response = client.get('/api/artifacts/table/preview/assets/table.json')
    assert response.status_code == 503  # noqa: PLR2004
    assert response.json()['detail'] == 'preview cache is not configured'
