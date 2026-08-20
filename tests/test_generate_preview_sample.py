import importlib.util
from pathlib import Path

import pytest

from lab_data.scientific_catalog import (
    Artifact,
    CatalogSnapshot,
    Device,
    SQLiteCatalogStore,
    StorageReference,
)

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / 'scripts'
    / 'generate_preview_sample.py'
)
_spec = importlib.util.spec_from_file_location('generate_preview_sample', _SCRIPT)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f'cannot load script: {_SCRIPT}')
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
select_sample_artifact_ids = _module.select_sample_artifact_ids


def _artifact(artifact_id, device_id, extension, media_type):
    return Artifact(
        artifact_id,
        extension=extension,
        media_type=media_type,
        device_id=device_id,
        storage_reference=StorageReference(
            'source', f'{device_id}/{artifact_id}.{extension}'
        ),
    )


def _store(tmp_path: Path) -> SQLiteCatalogStore:
    devices = (Device('D356'), Device('D357'))
    artifacts = (
        _artifact('img-a', 'D356', 'png', 'image/png'),
        _artifact('img-b', 'D356', 'jpg', 'image/jpeg'),
        _artifact('img-c', 'D357', 'png', 'image/png'),
        _artifact('doc-a', 'D356', 'pdf', 'application/pdf'),
        _artifact('data-a', 'D356', 'csv', 'text/csv'),
        _artifact('other-a', 'D356', 'xyz', 'UNKNOWN'),
    )
    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(
        CatalogSnapshot(experiments=(), devices=devices, artifacts=artifacts)
    )
    return store


def test_select_sample_artifact_ids_is_deterministic_and_bounded(tmp_path):
    store = _store(tmp_path)
    try:
        ids = select_sample_artifact_ids(
            store, device_id='D356', kind='image', limit=2
        )
        again = select_sample_artifact_ids(
            store, device_id='D356', kind='image', limit=2
        )
        no_device = select_sample_artifact_ids(
            store, device_id='D999', kind='image', limit=10
        )
    finally:
        store.close()

    assert ids == ('img-a', 'img-b')
    assert again == ids
    assert no_device == ()


def test_select_sample_artifact_ids_filters_kind(tmp_path):
    store = _store(tmp_path)
    try:
        documents = select_sample_artifact_ids(
            store, device_id='D356', kind='document', limit=10
        )
        data = select_sample_artifact_ids(
            store, device_id='D356', kind='data', limit=10
        )
        other = select_sample_artifact_ids(
            store, device_id='D356', kind='other', limit=10
        )
    finally:
        store.close()

    assert documents == ('doc-a',)
    assert data == ('data-a',)
    assert other == ('other-a',)


def test_validate_paths_rejects_equal_roots(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()

    with pytest.raises(ValueError):
        _module._validate_paths(root, root)


def test_validate_paths_rejects_preview_inside_storage(tmp_path):
    storage = tmp_path / 'storage'
    storage.mkdir()
    preview = storage / 'preview'

    with pytest.raises(ValueError):
        _module._validate_paths(preview, storage)


def test_validate_paths_accepts_preview_outside_storage(tmp_path):
    storage = tmp_path / 'storage'
    storage.mkdir()
    preview = tmp_path / 'preview'

    resolved_preview, resolved_storage = _module._validate_paths(
        preview, storage
    )

    assert resolved_preview == preview.resolve()
    assert resolved_storage == storage.resolve()


def test_validate_paths_rejects_relative_preview(tmp_path):
    storage = tmp_path / 'storage'
    storage.mkdir()
    preview = Path('preview')

    with pytest.raises(ValueError):
        _module._validate_paths(preview, storage)


def test_validate_paths_rejects_missing_storage(tmp_path):
    preview = tmp_path / 'preview'
    storage = tmp_path / 'missing'

    with pytest.raises(ValueError):
        _module._validate_paths(preview, storage)
