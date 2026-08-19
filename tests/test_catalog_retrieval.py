import json
import sqlite3
import urllib.request
from pathlib import Path

import pytest

import lab_data.artifact_previews as previews
from lab_data.artifact_previews import build_artifact_preview
from lab_data.catalog_retrieval import (
    find_device_documents,
    find_device_experiments,
    get_artifact_preview,
    search_artifacts,
    search_devices,
    search_experiments,
)
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


class _NoSnapshotStore:
    """Protocol fake that makes accidental full-snapshot hydration observable."""

    def __init__(self, store: SQLiteCatalogStore):
        self.store = store
        self.calls: list[tuple[str, object]] = []

    def snapshot(self):
        raise AssertionError('retrieval must not hydrate a full snapshot')

    def list_devices(self):
        self.calls.append(('list_devices', None))
        return self.store.list_devices()

    def get_artifact(self, artifact_id):
        self.calls.append(('get_artifact', artifact_id))
        return self.store.get_artifact(artifact_id)

    def list_artifacts(self, *, device_id=None):
        self.calls.append(('list_artifacts', device_id))
        return self.store.list_artifacts(device_id=device_id)

    def get_lineage(self, entity_type, entity_id):
        self.calls.append(('get_lineage', (entity_type, entity_id)))
        return self.store.get_lineage(entity_type, entity_id)

    def get_device_experiments(self, device_id):
        self.calls.append(('get_device_experiments', device_id))
        return self.store.get_device_experiments(device_id)

    def search_experiments(self, *, filters=None):
        self.calls.append(('search_experiments', filters))
        return self.store.search_experiments(filters=filters)


class _ConnectionProxy:
    """Delegate a connection while running a hook immediately before SELECTs."""

    def __init__(self, connection, before_select):
        self._connection = connection
        self._before_select = before_select

    def execute(self, sql, parameters=()):
        self._before_select(sql, parameters)
        return self._connection.execute(sql, parameters)

    def commit(self):
        return self._connection.commit()

    def rollback(self):
        return self._connection.rollback()

    def close(self):
        return self._connection.close()


def _device_experiment_snapshot(experiment_id):
    return CatalogSnapshot(
        experiments=(
            Experiment(
                experiment_id=experiment_id,
                metadata={},
                files_by_role={},
            ),
        ),
        devices=(Device('D356'),),
        relationships=(
            Relationship(
                source_type=SUBJECT_EXPERIMENT,
                source_id=experiment_id,
                predicate='measured_on',
                target_type=SUBJECT_DEVICE,
                target_id='D356',
            ),
        ),
    )


def _store(tmp_path: Path) -> SQLiteCatalogStore:
    experiments = (
        Experiment(
            experiment_id='exp-b',
            metadata={'sample_id': 'D357', 'measurement_type': 'transport'},
            files_by_role={'raw': (StorageReference('source', 'raw/D357.dat'),)},
        ),
        Experiment(
            experiment_id='exp-a',
            metadata={'sample_id': 'D356', 'measurement_type': 'optical'},
            files_by_role={'raw': (StorageReference('source', 'raw/D356.dat'),)},
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
    )
    relationships = (
        Relationship(
            source_type='experiment',
            source_id='exp-a',
            predicate='measured_on',
            target_type='device',
            target_id='D356',
        ),
    )
    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(CatalogSnapshot(experiments, devices, artifacts, relationships))
    return store


def test_search_projections_are_deterministic_and_json_safe(tmp_path):
    store = _store(tmp_path)
    devices = search_devices(store)
    assert [item['device_id'] for item in devices] == ['D356', 'D357']
    assert json.loads(json.dumps(devices)) == list(devices)
    assert search_devices(
        store,
        filters={
            'device_id': 'D356',
            'display_label': 'A',
            'maker_namespace': None,
            'local_device_id': None,
            'device_type': 'chip',
            'review_state': 'unknown',
        },
    ) == (devices[0],)
    assert search_devices(store, filters={'device_type': 'chip'}) == devices
    assert [item['artifact_id'] for item in search_artifacts(store)] == [
        'doc-a',
        'doc-b',
        'slides-b',
    ]
    assert (
        search_artifacts(
            store,
            filters={'storage_source_id': 'source', 'relative_path': 'docs/D356.ppt'},
        )[0]['artifact_id']
        == 'doc-a'
    )
    assert [item['experiment_id'] for item in search_experiments(store)] == [
        'exp-a',
        'exp-b',
    ]
    experiments = search_experiments(store)
    assert json.loads(json.dumps(experiments)) == list(experiments)
    for artifact in search_artifacts(store):
        assert (
            artifact['relative_path'] is None
            or not Path(artifact['relative_path']).is_absolute()
        )
    for experiment in experiments:
        for paths in experiment['files_by_role'].values():
            assert all(not Path(path).is_absolute() for path in paths)


def test_filters_are_allowlisted_and_missing_ids_are_safe(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match='unknown device filter'):
        search_devices(store, filters={'alias': 'alias-a'})
    with pytest.raises(ValueError, match='unknown artifact filter'):
        search_artifacts(store, filters={'path': 'docs/D356.ppt'})
    assert find_device_experiments(store, 'missing') == ()
    assert find_device_documents(store, 'missing') == ()
    assert (
        get_artifact_preview(store, 'missing', preview_root=tmp_path / 'cache') is None
    )


@pytest.mark.parametrize('invalid_device_id', [None, ''])
def test_device_queries_reject_invalid_ids(tmp_path, invalid_device_id):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match='device_id must be a non-empty string'):
        find_device_experiments(store, invalid_device_id)
    with pytest.raises(ValueError, match='device_id must be a non-empty string'):
        find_device_documents(store, invalid_device_id)


def test_device_experiment_relationship_is_exact_not_inferred(tmp_path):
    store = _store(tmp_path)
    assert [
        item['experiment_id'] for item in find_device_experiments(store, 'D357')
    ] == []
    store.rebuild(
        CatalogSnapshot(
            store.snapshot().experiments,
            store.snapshot().devices,
            store.snapshot().artifacts,
            store.snapshot().relationships
            + (
                Relationship(
                    source_type='experiment',
                    source_id='exp-b',
                    predicate='measured_on',
                    target_type='device',
                    target_id='D357',
                ),
            ),
        )
    )
    assert [
        item['experiment_id'] for item in find_device_experiments(store, 'D357')
    ] == ['exp-b']


def test_find_device_experiments_matches_canonical_search_order(tmp_path):
    experiments = (
        Experiment(
            experiment_id='exp-a',
            metadata={'sample_id': 'aa', 'measurement_type': 'transport'},
            files_by_role={},
        ),
        Experiment(
            experiment_id='exp-b',
            metadata={'sample_id': 'aa', 'measurement_type': 'optical'},
            files_by_role={},
        ),
        Experiment(
            experiment_id='exp-c',
            metadata={'sample_id': 'bb', 'measurement_type': 'optical'},
            files_by_role={},
        ),
    )
    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(
        CatalogSnapshot(
            experiments=experiments,
            devices=(Device('D356'),),
            relationships=tuple(
                Relationship(
                    source_type=SUBJECT_EXPERIMENT,
                    source_id=experiment.experiment_id,
                    predicate='measured_on',
                    target_type=SUBJECT_DEVICE,
                    target_id='D356',
                )
                for experiment in experiments
            ),
        )
    )

    expected = [
        item['experiment_id']
        for item in search_experiments(store)
        if item['experiment_id'] in {'exp-a', 'exp-b', 'exp-c'}
    ]
    assert [
        item['experiment_id'] for item in find_device_experiments(store, 'D356')
    ] == expected
    assert expected == ['exp-b', 'exp-a', 'exp-c']


def test_documents_exclude_slide_category(tmp_path):
    store = _store(tmp_path)
    assert [item['artifact_id'] for item in find_device_documents(store, 'D357')] == [
        'doc-b'
    ]


def test_retrieval_uses_narrow_catalog_protocol_operations(tmp_path):
    backing = _store(tmp_path)
    store = _NoSnapshotStore(backing)

    search_devices(store)
    search_artifacts(store, filters={'artifact_id': 'doc-b'})
    search_artifacts(store, filters={'device_id': 'D357'})
    search_artifacts(store)
    find_device_documents(store, 'D357')
    find_device_experiments(store, 'D356')

    assert ('list_devices', None) in store.calls
    assert ('get_artifact', 'doc-b') in store.calls
    assert ('list_artifacts', 'D357') in store.calls
    assert ('list_artifacts', None) in store.calls
    assert ('get_device_experiments', 'D356') in store.calls
    assert sum(call[0] == 'get_device_experiments' for call in store.calls) == 1


def test_preview_is_cache_only_and_invalid_cache_returns_none(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    path = source / 'table.csv'
    path.write_text('x,y\n1,2\n', encoding='utf-8')
    stat = path.stat()
    artifact = Artifact(
        'table',
        extension='csv',
        media_type='text/csv',
        storage_reference=StorageReference('source', 'table.csv'),
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )
    store = SQLiteCatalogStore(tmp_path / 'preview.db')
    store.rebuild(CatalogSnapshot((), artifacts=(artifact,)))
    cache = tmp_path / 'cache'
    before_catalog = store.snapshot()
    assert get_artifact_preview(store, 'table', preview_root=cache) is None
    build_artifact_preview(
        store, 'table', storage_roots={'source': source}, preview_root=cache
    )
    manifest_before = next(cache.rglob('manifest.json')).read_bytes()
    path.unlink()

    def fail(*_args, **_kwargs):
        raise AssertionError('cache-only lookup touched a forbidden boundary')

    monkeypatch.setattr(previews, '_resolve_source', fail)
    monkeypatch.setattr(previews, 'build_artifact_preview', fail)
    monkeypatch.setattr(urllib.request, 'urlopen', fail)
    report = get_artifact_preview(store, 'table', preview_root=cache)
    assert report is not None and report['source_freshness_checked'] is False
    assert store.snapshot() == before_catalog
    assert next(cache.rglob('manifest.json')).read_bytes() == manifest_before
    manifest = (
        cache
        / 'v1'
        / 'objects'
        / report['preview_id'][:2]
        / report['preview_id']
        / 'manifest.json'
    )
    manifest.write_text('{}', encoding='utf-8')
    assert get_artifact_preview(store, 'table', preview_root=cache) is None


def test_device_experiments_read_one_snapshot_across_connections(tmp_path):
    path = tmp_path / 'catalog.db'
    connection = sqlite3.connect(path)
    connection.execute('PRAGMA journal_mode=WAL')
    connection.close()

    first_store = SQLiteCatalogStore(path)
    second_store = SQLiteCatalogStore(path)
    first_store.rebuild(_device_experiment_snapshot('exp-a'))

    real_connection = first_store._connection()
    rebuilt = False

    def commit_before_experiments(sql, parameters):
        nonlocal rebuilt
        if (
            not rebuilt
            and isinstance(sql, str)
            and 'FROM experiments' in sql
            and 'experiment_id IN' in sql
        ):
            rebuilt = True
            second_store.rebuild(_device_experiment_snapshot('exp-b'))

    first_store._conn = _ConnectionProxy(real_connection, commit_before_experiments)

    assert [
        item['experiment_id'] for item in find_device_experiments(first_store, 'D356')
    ] == ['exp-a']
    assert rebuilt

    first_store.close()
    second_store.close()


def test_pre_fix_two_read_race_returns_empty(tmp_path):
    path = tmp_path / 'legacy.db'
    connection = sqlite3.connect(path)
    connection.execute('PRAGMA journal_mode=WAL')
    connection.close()

    first_store = SQLiteCatalogStore(path)
    second_store = SQLiteCatalogStore(path)
    first_store.rebuild(_device_experiment_snapshot('exp-a'))

    lineage = first_store.get_lineage(SUBJECT_DEVICE, 'D356')
    second_store.rebuild(_device_experiment_snapshot('exp-b'))
    records = first_store.search_experiments()

    measured_on_ids = {
        relationship.source_id
        for relationship in lineage
        if (
            relationship.source_type == SUBJECT_EXPERIMENT
            and relationship.predicate == 'measured_on'
            and relationship.target_type == SUBJECT_DEVICE
            and relationship.target_id == 'D356'
        )
    }
    record_ids = {record.experiment_id for record in records}

    assert measured_on_ids == {'exp-a'}
    assert record_ids == {'exp-b'}
    assert measured_on_ids & record_ids == set()

    first_store.close()
    second_store.close()
