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

    def count_artifacts(
        self,
        *,
        filters=None,
        q=None,
        kind=None,
        extensions=None,
        exclude_slide_category=False,
    ):
        self.calls.append(('count_artifacts', filters))
        return self.store.count_artifacts(
            filters=filters,
            q=q,
            kind=kind,
            extensions=extensions,
            exclude_slide_category=exclude_slide_category,
        )

    def page_artifacts(
        self,
        *,
        filters=None,
        q=None,
        kind=None,
        extensions=None,
        exclude_slide_category=False,
        limit=None,
        offset=None,
    ):
        self.calls.append(('page_artifacts', filters))
        return self.store.page_artifacts(
            filters=filters,
            q=q,
            kind=kind,
            extensions=extensions,
            exclude_slide_category=exclude_slide_category,
            limit=limit,
            offset=offset,
        )

    def get_lineage(self, entity_type, entity_id):
        self.calls.append(('get_lineage', (entity_type, entity_id)))
        return self.store.get_lineage(entity_type, entity_id)

    def get_provenance(self, subject_type, subject_id):
        self.calls.append(('get_provenance', (subject_type, subject_id)))
        return self.store.get_provenance(subject_type, subject_id)

    def resolve_file_references(self, file_ids):
        self.calls.append(('resolve_file_references', tuple(file_ids)))
        return self.store.resolve_file_references(file_ids)

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
    assert [item['device_id'] for item in devices.items] == ['D356', 'D357']
    assert devices.total_count == 2
    assert json.loads(json.dumps(devices.items)) == list(devices.items)
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
    ).items == (devices.items[0],)
    assert search_devices(store, filters={'device_type': 'chip'}).items == devices.items
    artifacts = search_artifacts(store)
    assert [item['artifact_id'] for item in artifacts.items] == [
        'doc-a',
        'doc-b',
        'slides-b',
    ]
    assert artifacts.total_count == 3
    assert (
        search_artifacts(
            store,
            filters={'storage_source_id': 'source', 'relative_path': 'docs/D356.ppt'},
        ).items[0]['artifact_id']
        == 'doc-a'
    )
    experiments = search_experiments(store)
    assert [item['experiment_id'] for item in experiments.items] == [
        'exp-a',
        'exp-b',
    ]
    assert experiments.total_count == 2
    assert json.loads(json.dumps(experiments.items)) == list(experiments.items)
    for artifact in artifacts.items:
        assert (
            artifact['relative_path'] is None
            or not Path(artifact['relative_path']).is_absolute()
        )
    for experiment in experiments.items:
        for paths in experiment['files_by_role'].values():
            assert all(not Path(path).is_absolute() for path in paths)


def test_filters_are_allowlisted_and_missing_ids_are_safe(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match='unknown device filter'):
        search_devices(store, filters={'alias': 'alias-a'})
    with pytest.raises(ValueError, match='unknown artifact filter'):
        search_artifacts(store, filters={'path': 'docs/D356.ppt'})
    assert find_device_experiments(store, 'missing').items == ()
    assert find_device_experiments(store, 'missing').total_count == 0
    assert find_device_documents(store, 'missing').items == ()
    assert find_device_documents(store, 'missing').total_count == 0
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
        item['experiment_id'] for item in find_device_experiments(store, 'D357').items
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
        item['experiment_id'] for item in find_device_experiments(store, 'D357').items
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
        for item in search_experiments(store).items
        if item['experiment_id'] in {'exp-a', 'exp-b', 'exp-c'}
    ]
    assert [
        item['experiment_id'] for item in find_device_experiments(store, 'D356').items
    ] == expected
    assert expected == ['exp-b', 'exp-a', 'exp-c']


def test_documents_exclude_slide_category(tmp_path):
    store = _store(tmp_path)
    page = find_device_documents(store, 'D357')
    assert [item['artifact_id'] for item in page.items] == ['doc-b']
    assert page.total_count == 1


def test_experiment_projection_includes_review_state_and_measured_on(tmp_path):
    experiments = (
        Experiment(
            experiment_id='exp-measured',
            metadata={},
            files_by_role={},
            claims=(
                MetadataClaim(
                    subject_type=SUBJECT_EXPERIMENT,
                    subject_id='exp-measured',
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
            experiment_id='exp-free',
            metadata={},
            files_by_role={},
            review_state='accepted',
        ),
    )
    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(
        CatalogSnapshot(
            experiments,
            devices=(Device('D356'),),
            relationships=(
                Relationship(
                    source_type=SUBJECT_EXPERIMENT,
                    source_id='exp-measured',
                    predicate='measured_on',
                    target_type=SUBJECT_DEVICE,
                    target_id='D356',
                    provenance_source='D356 WSe2_AuSplitGate',
                ),
            ),
        )
    )

    by_id = {item['experiment_id']: item for item in search_experiments(store).items}
    assert by_id['exp-free']['measured_on'] is None
    assert by_id['exp-free']['review_state'] == 'accepted'
    assert by_id['exp-measured']['review_state'] == 'unknown'
    assert by_id['exp-measured']['measured_on'] == {
        'device_id': 'D356',
        'evidence': 'explicit device-directory context',
        'source_reference': 'D356 WSe2_AuSplitGate',
        'extraction_method': 'device_directory_context',
        'review_status': 'unknown',
    }


def test_measured_on_falls_back_to_relationship_without_claim(tmp_path):
    store = _store(tmp_path)
    by_id = {item['experiment_id']: item for item in search_experiments(store).items}
    assert by_id['exp-a']['measured_on'] == {
        'device_id': 'D356',
        'evidence': 'explicit device-directory context',
        'source_reference': None,
        'extraction_method': None,
        'review_status': 'unknown',
    }


def test_experiment_detail_lookup_keeps_working(tmp_path):
    store = _store(tmp_path)
    page = search_experiments(store, filters={'experiment_id': 'exp-a'})
    assert page.total_count == 1
    item = page.items[0]
    assert item['experiment_id'] == 'exp-a'
    assert item['review_state'] == 'unknown'
    assert item['measured_on']['device_id'] == 'D356'


def test_artifact_projection_resolves_derived_from_paths(tmp_path):
    raw = StorageReference('source', 'raw/YZ356_BG1only.csv')
    dat = StorageReference('source', 'processed/YZ356_BG1only_PL.dat')
    linear = StorageReference('source', 'processed/YZ356_BG1only_PL_linear.png')
    experiment = Experiment(
        experiment_id='exp-fig',
        metadata={},
        files_by_role={'raw': (raw,), 'processed': (dat,), 'figure': (linear,)},
    )
    artifact = Artifact(
        'fig-linear',
        extension='png',
        media_type='image/png',
        storage_reference=linear,
    )
    relationships = (
        Relationship(
            source_type=ENTITY_FILE,
            source_id=deterministic_storage_reference_id(
                storage_source_id=dat.storage_source_id,
                relative_path=dat.relative_path,
            ),
            predicate='derived_from',
            target_type=ENTITY_FILE,
            target_id=deterministic_storage_reference_id(
                storage_source_id=raw.storage_source_id,
                relative_path=raw.relative_path,
            ),
        ),
        Relationship(
            source_type=ENTITY_FILE,
            source_id=deterministic_storage_reference_id(
                storage_source_id=linear.storage_source_id,
                relative_path=linear.relative_path,
            ),
            predicate='derived_from',
            target_type=ENTITY_FILE,
            target_id=deterministic_storage_reference_id(
                storage_source_id=dat.storage_source_id,
                relative_path=dat.relative_path,
            ),
        ),
    )
    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(
        CatalogSnapshot(
            (experiment,),
            artifacts=(artifact,),
            relationships=relationships,
        )
    )

    page = search_artifacts(store, filters={'artifact_id': 'fig-linear'})
    assert page.total_count == 1
    assert page.items[0]['derived_from'] == [
        {
            'source': linear.relative_path,
            'target': dat.relative_path,
            'relation': 'derived_from',
        },
    ]


def test_find_device_documents_keeps_payload_shape(tmp_path):
    store = _store(tmp_path)
    page = find_device_documents(store, 'D357')
    assert [item['artifact_id'] for item in page.items] == ['doc-b']
    item = page.items[0]
    for key in (
        'artifact_id',
        'device_id',
        'role',
        'category',
        'extension',
        'relative_path',
        'filename',
        'review_state',
    ):
        assert key in item
    assert item['derived_from'] == []


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
    assert ('get_device_experiments', 'D356') in store.calls
    assert sum(call[0] == 'page_artifacts' for call in store.calls) == 4
    assert sum(call[0] == 'count_artifacts' for call in store.calls) == 4
    assert ('page_artifacts', {'artifact_id': 'doc-b'}) in store.calls
    assert ('page_artifacts', {'device_id': 'D357'}) in store.calls
    assert ('page_artifacts', {}) in store.calls
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
        item['experiment_id']
        for item in find_device_experiments(first_store, 'D356').items
    ] == ['exp-a']
    assert rebuilt

    first_store.close()
    second_store.close()


def test_artifact_pagination_is_deterministic_and_non_overlapping(tmp_path):
    store = _store(tmp_path)
    all_ids = [
        item['artifact_id'] for item in search_artifacts(store, limit=200).items
    ]
    assert all_ids == ['doc-a', 'doc-b', 'slides-b']

    collected = []
    offset = 0
    while offset < len(all_ids):
        page = search_artifacts(store, limit=2, offset=offset)
        assert page.total_count == len(all_ids)
        collected.extend(item['artifact_id'] for item in page.items)
        offset += 2
    assert collected == all_ids


def test_device_q_substring_matches_numeric_device_id(tmp_path):
    store = _store(tmp_path)
    page = search_devices(store, q='356')
    assert [item['device_id'] for item in page.items] == ['D356']
    assert page.total_count == 1


def test_artifact_projection_includes_filename(tmp_path):
    store = _store(tmp_path)
    first = search_artifacts(store, limit=200).items[0]
    assert first['artifact_id'] == 'doc-a'
    assert first['relative_path'] == 'docs/D356.ppt'
    assert first['filename'] == 'D356.ppt'


def test_artifact_kind_classification_is_deterministic(tmp_path):
    store = SQLiteCatalogStore(tmp_path / 'kinds.db')
    artifacts = (
        Artifact(
            'png-1',
            extension='png',
            media_type='image/png',
            storage_reference=StorageReference('s', 'a/png.png'),
        ),
        Artifact(
            'jpg-1',
            extension='jpg',
            media_type='image/jpeg',
            storage_reference=StorageReference('s', 'a/jpg.jpg'),
        ),
        Artifact(
            'svg-1',
            extension='svg',
            media_type='image/svg+xml',
            storage_reference=StorageReference('s', 'a/svg.svg'),
        ),
        Artifact(
            'img-media',
            extension='UNKNOWN',
            media_type='image/gif',
            storage_reference=StorageReference('s', 'a/gif.gif'),
        ),
        Artifact(
            'pdf-1',
            extension='pdf',
            media_type='application/pdf',
            storage_reference=StorageReference('s', 'a/pdf.pdf'),
        ),
        Artifact(
            'csv-1',
            extension='csv',
            media_type='text/csv',
            storage_reference=StorageReference('s', 'a/csv.csv'),
        ),
        Artifact(
            'mat-1',
            extension='mat',
            media_type='UNKNOWN',
            storage_reference=StorageReference('s', 'a/mat.mat'),
        ),
        Artifact(
            'other-1',
            extension='xyz',
            media_type='UNKNOWN',
            storage_reference=StorageReference('s', 'a/other.xyz'),
        ),
    )
    store.rebuild(CatalogSnapshot(experiments=(), artifacts=artifacts))

    def ids(kind):
        return [item['artifact_id'] for item in search_artifacts(store, kind=kind).items]

    assert ids('image') == ['img-media', 'jpg-1', 'png-1', 'svg-1']
    assert ids('document') == ['pdf-1']
    assert ids('data') == ['csv-1', 'mat-1']
    assert ids('other') == ['other-1']


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
