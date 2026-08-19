import socket
import sqlite3
import urllib.request
from pathlib import Path

import pytest

from lab_data import scientific_catalog
from lab_data.experiment_search import (
    NumericRange,
    build_search_index,
    search_experiments,
)
from lab_data.ingestion.proposal import (
    ElectricalConnection,
    ExperimentImportProposal,
    GateConstraint,
    LineageEdge,
)
from lab_data.scientific_catalog import (
    REVIEW_ACCEPTED,
    REVIEW_CORRECTED,
    REVIEW_UNKNOWN,
    SUBJECT_ARTIFACT,
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
    deterministic_device_id,
    deterministic_storage_reference_id,
)

EXPECTED_EXPERIMENTS = 1505
EXPECTED_STORAGE_REFERENCES = 2772
EXPECTED_INDEX_BUILDS = 2


def test_list_artifacts_device_filter_is_deterministic(tmp_path):
    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    snapshot = CatalogSnapshot(
        experiments=(),
        devices=(Device('D1'), Device('D2')),
        artifacts=(
            Artifact(
                'a1', storage_reference=StorageReference('s', 'a1'), device_id='D1'
            ),
            Artifact(
                'a2', storage_reference=StorageReference('s', 'a2'), device_id='D2'
            ),
            Artifact(
                'a3', storage_reference=StorageReference('s', 'a3'), device_id=None
            ),
        ),
    )
    store.rebuild(snapshot)
    assert [item.artifact_id for item in store.list_artifacts(device_id='D1')] == ['a1']
    assert store.list_artifacts(device_id='missing') == ()


EXPECTED_CLAIMS = 2


def test_maker_namespace_defaults_and_deterministic_identity():
    assert Device('D1').display_label == 'D1'
    with pytest.raises(ValueError):
        Device('D1', maker_namespace='YZ')
    assert deterministic_device_id('YZ', 'D148') == 'D148'
    assert deterministic_device_id('QC', '148') == (
        'dev-89884074b3d573960d5de098f7894deefe3a0572c61d419dbbff014c9f036cc3'
    )


def test_v1_schema_migration_preserves_legacy_device_and_artifact(tmp_path):
    path = tmp_path / 'legacy.db'
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE catalog_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO catalog_meta VALUES ('schema_version', '1');
        CREATE TABLE devices (
            device_id TEXT PRIMARY KEY, device_type TEXT NOT NULL,
            aliases_json TEXT NOT NULL, review_state TEXT NOT NULL,
            metadata_json TEXT NOT NULL, ordinal INTEGER NOT NULL
        );
        INSERT INTO devices VALUES ('D1', 'UNKNOWN', '[\"legacy\"]', 'unknown', '{}', 0);
        """
    )
    connection.commit()
    connection.close()
    with SQLiteCatalogStore(path) as store:
        assert store.get_device('D1').display_label == 'D1'
        assert store.get_device_by_identity('YZ', 'D1') is None
        assert (
            store._connection()
            .execute("SELECT value FROM catalog_meta WHERE key='schema_version'")
            .fetchone()[0]
            == '2'
        )


def test_v2_device_constraints_reject_partial_identity_and_blank_label(tmp_path):
    with SQLiteCatalogStore(tmp_path / 'constraints.db') as store:
        connection = store._connection()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO devices (device_id,device_type,aliases_json,review_state,metadata_json,maker_namespace,local_device_id,display_label,ordinal) VALUES ('bad','UNKNOWN','[]','unknown','{}','YZ',NULL,'bad',0)"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO devices (device_id,device_type,aliases_json,review_state,metadata_json,maker_namespace,local_device_id,display_label,ordinal) VALUES ('bad2','UNKNOWN','[]','unknown','{}',NULL,NULL,'',0)"
            )


EXPECTED_ARTIFACT_SIZE = 2048


def test_schema_v0_is_rejected(tmp_path):
    path = tmp_path / 'v0.db'
    connection = sqlite3.connect(path)
    connection.execute(
        'CREATE TABLE catalog_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)'
    )
    connection.execute("INSERT INTO catalog_meta VALUES ('schema_version', '0')")
    connection.commit()
    connection.close()
    with pytest.raises(ValueError, match='unsupported catalog schema version'):
        SQLiteCatalogStore(path).snapshot()


def test_v1_full_graph_migrates_and_reopens(tmp_path):
    path = tmp_path / 'full-v1.db'
    connection = sqlite3.connect(path)
    connection.execute(
        'CREATE TABLE catalog_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)'
    )
    connection.execute("INSERT INTO catalog_meta VALUES ('schema_version', '1')")
    connection.executescript(
        """
        CREATE TABLE devices (device_id TEXT PRIMARY KEY, device_type TEXT NOT NULL, aliases_json TEXT NOT NULL, review_state TEXT NOT NULL, metadata_json TEXT NOT NULL, ordinal INTEGER NOT NULL);
        CREATE TABLE experiments (experiment_id TEXT PRIMARY KEY, metadata_json TEXT NOT NULL, warnings_json TEXT NOT NULL, confidence REAL NOT NULL, needs_review INTEGER NOT NULL, review_state TEXT NOT NULL, parser_version TEXT, roles_json TEXT NOT NULL, ordinal INTEGER NOT NULL);
        CREATE TABLE artifacts (artifact_id TEXT PRIMARY KEY, role TEXT NOT NULL, category TEXT NOT NULL, extension TEXT NOT NULL, media_type TEXT NOT NULL, device_id TEXT, experiment_id TEXT, storage_source_id TEXT, relative_path TEXT, size_bytes INTEGER, mtime_ns INTEGER, review_state TEXT NOT NULL, metadata_json TEXT NOT NULL, ordinal INTEGER NOT NULL, FOREIGN KEY(device_id) REFERENCES devices(device_id));
        CREATE TABLE experiment_files (experiment_id TEXT NOT NULL, ordinal INTEGER NOT NULL, role TEXT NOT NULL, storage_source_id TEXT NOT NULL, relative_path TEXT NOT NULL, PRIMARY KEY(experiment_id,ordinal), FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id));
        CREATE TABLE metadata_claims (subject_type TEXT NOT NULL, subject_id TEXT NOT NULL, ordinal INTEGER NOT NULL, field TEXT NOT NULL, value_json TEXT NOT NULL, source_type TEXT NOT NULL, source_reference TEXT, extraction_method TEXT NOT NULL, confidence REAL, category TEXT, evidence_json TEXT NOT NULL, review_status TEXT NOT NULL, reviewed_value_json TEXT, PRIMARY KEY(subject_type,subject_id,ordinal));
        CREATE TABLE relationships (relationship_id TEXT PRIMARY KEY, source_type TEXT NOT NULL, source_id TEXT NOT NULL, predicate TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL, provenance_source TEXT, review_state TEXT NOT NULL, ordinal INTEGER NOT NULL);
        INSERT INTO devices VALUES ('D1','UNKNOWN','["legacy"]','unknown','{}',0);
        INSERT INTO artifacts VALUES ('a','raw','x','pdf','application/pdf','D1',NULL,'s','D1/a.pdf',1,2,'unknown','{}',0);
        INSERT INTO metadata_claims VALUES ('device','D1',0,'maker','"legacy"','test','v1','manual',NULL,NULL,'["evidence"]','unknown',NULL);
        INSERT INTO relationships VALUES ('r','artifact','a','describes','device','D1','v1','unknown',0);
        """
    )
    connection.commit()
    connection.close()
    with SQLiteCatalogStore(path) as store:
        assert store.get_artifact('a').device_id == 'D1'
        assert store.get_provenance('device', 'D1')[0].value == 'legacy'
        assert store.list_relationships()[0].target_id == 'D1'
        assert store._connection().execute('PRAGMA foreign_key_check').fetchall() == []
        assert (
            'CHECK'
            in store._connection()
            .execute("SELECT sql FROM sqlite_master WHERE name='devices'")
            .fetchone()[0]
        )
    with SQLiteCatalogStore(path) as reopened:
        assert reopened.get_device('D1').aliases == ('legacy',)


def test_malformed_v1_graph_rolls_back_migration(tmp_path):
    path = tmp_path / 'bad-v1.db'
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE catalog_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL); INSERT INTO catalog_meta VALUES ('schema_version','1'); CREATE TABLE devices (device_id TEXT PRIMARY KEY, device_type TEXT NOT NULL, aliases_json TEXT NOT NULL, review_state TEXT NOT NULL, metadata_json TEXT NOT NULL, ordinal INTEGER NOT NULL); INSERT INTO devices VALUES ('D1','UNKNOWN','[]','unknown','{}',0); CREATE TABLE artifacts (artifact_id TEXT PRIMARY KEY, role TEXT, category TEXT, extension TEXT, media_type TEXT, device_id TEXT, experiment_id TEXT, storage_source_id TEXT, relative_path TEXT, size_bytes INTEGER, mtime_ns INTEGER, review_state TEXT, metadata_json TEXT, ordinal INTEGER, FOREIGN KEY(device_id) REFERENCES devices(device_id)); PRAGMA foreign_keys=OFF; INSERT INTO artifacts VALUES ('bad','raw','x','pdf','application/pdf','MISSING',NULL,NULL,NULL,NULL,NULL,'unknown','{}',0);"
    )
    connection.commit()
    connection.close()
    with pytest.raises(ValueError, match='foreign key check failed'):
        SQLiteCatalogStore(path).snapshot()
    raw = sqlite3.connect(path)
    assert (
        raw.execute(
            "SELECT value FROM catalog_meta WHERE key='schema_version'"
        ).fetchone()[0]
        == '1'
    )
    assert (
        raw.execute("SELECT name FROM sqlite_master WHERE name='devices_v2'").fetchone()
        is None
    )
    raw.close()


def test_rebuild_rejects_non_deterministic_qualified_device(tmp_path):
    store = SQLiteCatalogStore(tmp_path / 'bad-device.db')
    with pytest.raises(ValueError, match='deterministic identity'):
        store.rebuild(
            CatalogSnapshot(
                experiments=(),
                devices=(
                    Device(
                        'D148',
                        maker_namespace='QC',
                        local_device_id='148',
                        display_label='QC148',
                    ),
                ),
            )
        )


EXPECTED_ARTIFACT_MTIME = 1700000000000000000


def _proposal(
    sample_id,
    measurement_type,
    *,
    electrical='BG2-CG',
    constraint='BG2-CG=0',
):
    if constraint == 'BG2-CG=0':
        coefficients = {'BG2': 1.0, 'CG': -1.0}
    elif constraint == 'BG1+BG2=0':
        coefficients = {'BG1': 1.0, 'BG2': 1.0}
    else:
        coefficients = {'BG1': 1.0, 'BG2': -1.0}
    return ExperimentImportProposal(
        sample_id=sample_id,
        measurement_type=measurement_type,
        raw_files=[f'raw/{sample_id}.dat'],
        processed_files=[f'processed/{sample_id}.csv'],
        lineage=[
            LineageEdge(
                source=f'raw/{sample_id}.dat',
                target=f'processed/{sample_id}.csv',
                relation='derived_from',
            )
        ],
        electrical_connections=[
            ElectricalConnection(
                raw_expression=electrical,
                nodes=['BG2', 'CG'],
                type='electrically_tied',
                source_role='bias_source',
            )
        ],
        gate_constraints=[
            GateConstraint(
                raw_expression=constraint,
                coefficients=coefficients,
                control_mode='constant_doping',
            )
        ],
    )


def _minimal_proposal(index):
    sample_id = f'D{100 + index}'
    return ExperimentImportProposal(
        sample_id=sample_id,
        measurement_type='transport',
        raw_files=[f'raw/{sample_id}.dat'],
    )


def _minimal_experiment(experiment_id, *, sample_id=None):
    metadata = {} if sample_id is None else {'sample_id': sample_id}
    return Experiment(
        experiment_id=experiment_id,
        metadata=metadata,
        files_by_role={},
    )


def _sample_snapshot():
    device = Device(
        device_id='D71',
        device_type='cryostat',
        aliases=(),
        review_state=REVIEW_ACCEPTED,
        metadata={'vendor': 'acme'},
        claims=(
            MetadataClaim(
                subject_type=SUBJECT_DEVICE,
                subject_id='D71',
                field='vendor',
                value='acme',
                source_type='manifest',
                source_reference='devices.yaml',
                extraction_method='literal',
                review_status=REVIEW_ACCEPTED,
            ),
        ),
    )
    artifact = Artifact(
        artifact_id='art-1',
        role='figure',
        category='spectrum',
        extension='png',
        media_type='image/png',
        device_id='D71',
        experiment_id='exp-1',
        storage_reference=StorageReference('source-a', 'fig/D71.png'),
        size_bytes=123,
        mtime_ns=456,
        review_state=REVIEW_UNKNOWN,
        claims=(
            MetadataClaim(
                subject_type=SUBJECT_ARTIFACT,
                subject_id='art-1',
                field='figure_kind',
                value='spectrum',
                source_type='filename',
                source_reference='fig/D71.png',
                extraction_method='deterministic',
                review_status=REVIEW_UNKNOWN,
            ),
        ),
    )
    experiment = Experiment(
        experiment_id='exp-1',
        metadata={'sample_id': 'D71', 'temperature_K': 3.6},
        files_by_role={
            'raw': (StorageReference('source-a', 'raw/D71.dat'),),
            'processed': (StorageReference('source-a', 'processed/D71.csv'),),
        },
        warnings=('ambiguous stem',),
        confidence=0.8,
        needs_review=True,
        review_state=REVIEW_ACCEPTED,
        parser_version='scanner-1.2.3',
        claims=(
            MetadataClaim(
                subject_type=SUBJECT_EXPERIMENT,
                subject_id='exp-1',
                field='temperature_K',
                value=3.6,
                source_type='filename',
                source_reference='raw/D71.dat',
                extraction_method='deterministic',
                review_status=REVIEW_ACCEPTED,
            ),
        ),
    )
    relationships = (
        Relationship(
            source_type='file',
            source_id=deterministic_storage_reference_id(
                storage_source_id='source-a', relative_path='raw/D71.dat'
            ),
            predicate='derived_from',
            target_type='file',
            target_id=deterministic_storage_reference_id(
                storage_source_id='source-a', relative_path='processed/D71.csv'
            ),
            review_state=REVIEW_ACCEPTED,
        ),
        Relationship(
            source_type=SUBJECT_ARTIFACT,
            source_id='art-1',
            predicate='describes',
            target_type=SUBJECT_DEVICE,
            target_id='D71',
            review_state=REVIEW_UNKNOWN,
        ),
    )
    return CatalogSnapshot(
        experiments=(experiment,),
        devices=(device,),
        artifacts=(artifact,),
        relationships=relationships,
    )


def test_rebuild_is_idempotent_and_equivalent_snapshot(tmp_path):
    snapshot = _sample_snapshot()
    store = SQLiteCatalogStore(tmp_path / 'catalog.db')

    assert store.rebuild(snapshot) == snapshot
    assert store.rebuild(snapshot) == snapshot
    assert store.snapshot() == snapshot

    equivalent = _sample_snapshot()
    other = SQLiteCatalogStore(tmp_path / 'other.db')
    assert other.rebuild(equivalent) == snapshot
    assert other.snapshot() == equivalent

    store.close()
    other.close()


def test_missing_and_duplicate_experiment_ids_are_rejected():
    proposals = [_minimal_proposal(0), _minimal_proposal(1)]
    with pytest.raises(TypeError):
        CatalogSnapshot.from_proposals(proposals)
    with pytest.raises(ValueError, match='count must match'):
        CatalogSnapshot.from_proposals(proposals, experiment_ids=('x',))
    with pytest.raises(ValueError, match='duplicate experiment IDs'):
        CatalogSnapshot.from_proposals(proposals, experiment_ids=('x', 'x'))
    with pytest.raises(ValueError, match='non-empty'):
        Experiment(experiment_id='', metadata={}, files_by_role={})


def test_preserves_1505_explicit_stable_ids_without_duplicates(tmp_path):
    # Synthetic stress test only: this does not validate the absent real corpus.
    proposals = [_minimal_proposal(index) for index in range(EXPECTED_EXPERIMENTS)]
    experiment_ids = tuple(f'exp-{index:04d}' for index in range(EXPECTED_EXPERIMENTS))
    snapshot = CatalogSnapshot.from_proposals(
        proposals,
        experiment_ids=experiment_ids,
        storage_source_id='synthetic',
        parser_version='scanner-2.0.0',
    )

    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(snapshot)

    persisted = store.list_experiments()
    assert len(persisted) == EXPECTED_EXPERIMENTS
    assert len({item.experiment_id for item in persisted}) == EXPECTED_EXPERIMENTS
    assert [item.experiment_id for item in persisted] == list(experiment_ids)
    assert store.get_experiment('exp-0000').experiment_id == 'exp-0000'
    assert store.get_experiment('exp-0000').metadata['sample_id'] == 'D100'


def test_preserves_2772_storage_references_with_alignment(tmp_path):
    # Synthetic stress test only: this does not validate the absent real corpus.
    experiments = []
    per_experiment = EXPECTED_STORAGE_REFERENCES // 3
    for experiment_index in range(3):
        source = f'source-{experiment_index}'
        references = tuple(
            StorageReference(
                storage_source_id=source,
                relative_path=f'raw/device{experiment_index}/file{file_index}.dat',
            )
            for file_index in range(per_experiment)
        )
        experiments.append(
            Experiment(
                experiment_id=f'exp-{experiment_index}',
                metadata={},
                files_by_role={'raw': references},
            )
        )

    snapshot = CatalogSnapshot(experiments=tuple(experiments))
    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(snapshot)

    references = store.list_storage_references()
    assert len(references) == EXPECTED_STORAGE_REFERENCES
    assert len(set(references)) == EXPECTED_STORAGE_REFERENCES

    persisted = store.list_experiments()
    assert (
        sum(len(item.files_by_role['raw']) for item in persisted)
        == EXPECTED_STORAGE_REFERENCES
    )
    for item in persisted:
        expected_source = f'source-{item.experiment_id.rsplit("-", 1)[-1]}'
        assert all(
            ref.storage_source_id == expected_source
            for ref in item.files_by_role['raw']
        )
        assert all(
            ref.relative_path.startswith('raw/') for ref in item.files_by_role['raw']
        )


def test_storage_reference_enforces_storage_relative_paths():
    assert StorageReference('source-a', r'raw\D71.dat').relative_path == 'raw/D71.dat'
    assert StorageReference('source-a', './raw/D71.dat').relative_path == 'raw/D71.dat'
    for invalid in (
        'C:/data/D71.dat',
        r'C:\data\D71.dat',
        '/abs/D71.dat',
        '../D71.dat',
    ):
        with pytest.raises(ValueError, match=r'storage-relative|\.\.'):
            StorageReference('source-a', invalid)
    with pytest.raises(ValueError, match='non-empty'):
        StorageReference('source-a', '')


def test_persisted_search_matches_in_memory_index_exactly(tmp_path):
    proposals = [
        _proposal('D357', 'transport'),
        _proposal('D356', 'optical'),
        _proposal('D358', 'transport', constraint='BG1+BG2=0'),
        _proposal('D359', 'optical', constraint='BG1-BG2=0'),
    ]
    proposals[0].temperature_K = 3.6
    proposals[1].temperature_K = 4.2
    experiment_ids = ('exp-b', 'exp-a', 'plus', 'minus')

    snapshot = CatalogSnapshot.from_proposals(
        proposals,
        experiment_ids=experiment_ids,
        storage_source_id='synthetic',
    )
    in_memory = build_search_index(proposals, experiment_ids=experiment_ids)

    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(snapshot)

    wiring = {
        'electrical_connections': [
            {
                'raw_expression': 'BG2-CG',
                'nodes': ['BG2', 'CG'],
                'type': 'electrically_tied',
                'source_role': 'bias_source',
            }
        ]
    }
    plus = {
        'gate_constraints': [
            {
                'raw_expression': 'BG1+BG2=0',
                'coefficients': {'BG1': 1.0, 'BG2': 1.0},
                'control_mode': 'constant_doping',
                'sweep_direction': None,
            }
        ]
    }
    minus = {
        'gate_constraints': [
            {
                'raw_expression': 'BG1-BG2=0',
                'coefficients': {'BG1': 1.0, 'BG2': -1.0},
                'control_mode': 'constant_doping',
                'sweep_direction': None,
            }
        ]
    }
    default_constraint = {
        'gate_constraints': [
            {
                'raw_expression': 'BG2-CG=0',
                'coefficients': {'BG2': 1.0, 'CG': -1.0},
                'control_mode': 'constant_doping',
                'sweep_direction': None,
            }
        ]
    }

    for filters in (
        None,
        {'sample_id': 'D356'},
        wiring,
        plus,
        minus,
        default_constraint,
        {'temperature_K': NumericRange(3, 4)},
    ):
        assert store.search_experiments(filters=filters) == search_experiments(
            in_memory, filters=filters
        )

    assert [
        item.experiment_id for item in store.search_experiments(filters=wiring)
    ] == ['exp-a', 'exp-b', 'plus', 'minus']
    assert [item.experiment_id for item in store.search_experiments(filters=plus)] == [
        'plus'
    ]
    assert [item.experiment_id for item in store.search_experiments(filters=minus)] == [
        'minus'
    ]
    assert [
        item.experiment_id
        for item in store.search_experiments(filters=default_constraint)
    ] == ['exp-a', 'exp-b']


def test_search_index_does_not_hydrate_artifacts_or_unrelated_relationships(
    tmp_path, monkeypatch
):
    proposal = _proposal('D356', 'optical')
    snapshot = CatalogSnapshot.from_proposals(
        [proposal],
        experiment_ids=('exp-1',),
        storage_source_id='synthetic',
        artifacts=(
            Artifact(
                'unrelated-a',
                storage_reference=StorageReference('outside', 'a.dat'),
            ),
            Artifact(
                'unrelated-b',
                storage_reference=StorageReference('outside', 'b.dat'),
            ),
        ),
        relationships=(
            Relationship(
                source_type='file',
                source_id=deterministic_storage_reference_id(
                    storage_source_id='outside', relative_path='a.dat'
                ),
                predicate='derived_from',
                target_type='file',
                target_id=deterministic_storage_reference_id(
                    storage_source_id='outside', relative_path='b.dat'
                ),
            ),
        ),
    )
    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(snapshot)

    monkeypatch.setattr(
        store,
        'snapshot',
        lambda: (_ for _ in ()).throw(
            AssertionError('search index must not hydrate a snapshot')
        ),
    )
    monkeypatch.setattr(
        store,
        'list_artifacts',
        lambda **_: (_ for _ in ()).throw(
            AssertionError('search index must not hydrate artifacts')
        ),
    )

    records = store.search_experiments()
    assert records[0].experiment_id == 'exp-1'
    assert records[0].lineage
    assert all(edge.source != 'a.dat' for edge in records[0].lineage)


def test_search_index_cache_reuses_one_completed_build(tmp_path, monkeypatch):
    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(_sample_snapshot())
    original = store.list_experiments
    calls = 0

    def counted_list_experiments():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(store, 'list_experiments', counted_list_experiments)
    first = store._search_index()
    second = store._search_index()

    assert first is second
    assert calls == 1


def test_search_index_cache_invalidates_after_successful_rebuild(tmp_path, monkeypatch):
    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(_sample_snapshot())
    original = store.list_experiments
    calls = 0

    def counted_list_experiments():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(store, 'list_experiments', counted_list_experiments)
    first = store._search_index()
    store.rebuild(CatalogSnapshot(experiments=(_minimal_experiment('new'),)))
    second = store._search_index()

    assert first is not second
    # Successful rebuild returns a snapshot, then the next query rebuilds the index.
    assert calls == EXPECTED_INDEX_BUILDS + 1
    assert second.records[0].experiment_id == 'new'


def test_failed_rebuild_retains_search_index_cache(tmp_path, monkeypatch):
    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(_sample_snapshot())
    original = store.list_experiments
    calls = 0

    def counted_list_experiments():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(store, 'list_experiments', counted_list_experiments)
    first = store._search_index()
    invalid = CatalogSnapshot(
        experiments=(_minimal_experiment('new'),),
        artifacts=(Artifact('orphan', device_id='missing-device'),),
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.rebuild(invalid)

    assert store._search_index() is first
    assert calls == 1


def test_search_index_cache_retries_after_build_exception(tmp_path, monkeypatch):
    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(_sample_snapshot())
    original = store.list_experiments
    attempts = 0

    def fail_once():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError('transient index build failure')
        return original()

    monkeypatch.setattr(store, 'list_experiments', fail_once)
    with pytest.raises(RuntimeError, match='transient'):
        store._search_index()
    assert store._search_index().records
    assert attempts == EXPECTED_INDEX_BUILDS


def test_search_index_cache_invalidates_on_close_and_external_store_rebuild(tmp_path):
    path = tmp_path / 'catalog.db'
    first_store = SQLiteCatalogStore(path)
    second_store = SQLiteCatalogStore(path)
    first_store.rebuild(CatalogSnapshot(experiments=(_minimal_experiment('one'),)))
    first_index = first_store._search_index()

    second_store.rebuild(CatalogSnapshot(experiments=(_minimal_experiment('two'),)))
    external_index = first_store._search_index()
    assert external_index is not first_index
    assert external_index.records[0].experiment_id == 'two'

    first_store.close()
    reopened = SQLiteCatalogStore(path)
    reopened_index = reopened._search_index()
    assert reopened_index.records[0].experiment_id == 'two'
    assert reopened_index is not external_index
    second_store.close()
    reopened.close()


def test_search_index_snapshot_is_not_mixed_by_concurrent_rebuild(
    tmp_path, monkeypatch
):
    path = tmp_path / 'catalog.db'
    setup = sqlite3.connect(path)
    setup.execute('PRAGMA journal_mode=WAL')
    setup.close()

    def lineage_snapshot(experiment_id, raw_path, processed_path):
        return CatalogSnapshot(
            experiments=(
                Experiment(
                    experiment_id=experiment_id,
                    metadata={},
                    files_by_role={
                        'raw': (StorageReference('source-a', raw_path),),
                        'processed': (StorageReference('source-a', processed_path),),
                    },
                ),
            ),
            relationships=(
                Relationship(
                    source_type='file',
                    source_id=deterministic_storage_reference_id(
                        storage_source_id='source-a', relative_path=raw_path
                    ),
                    predicate='derived_from',
                    target_type='file',
                    target_id=deterministic_storage_reference_id(
                        storage_source_id='source-a', relative_path=processed_path
                    ),
                ),
            ),
        )

    old_snapshot = lineage_snapshot('old', 'raw/old.dat', 'processed/old.csv')
    new_snapshot = lineage_snapshot('new', 'raw/new.dat', 'processed/new.csv')

    first_store = SQLiteCatalogStore(path)
    second_store = SQLiteCatalogStore(path)
    first_store.rebuild(old_snapshot)

    original_list_experiments = first_store.list_experiments

    def rebuild_then_list_experiments():
        # Commit the competing snapshot after the file-to-file relationships have
        # already been read, but before experiments are read.
        second_store.rebuild(new_snapshot)
        return original_list_experiments()

    monkeypatch.setattr(first_store, 'list_experiments', rebuild_then_list_experiments)

    index = first_store._search_index()

    assert len(index.records) == 1
    record = index.records[0]
    # The mixed state would pair the new experiment with the old lineage and drop
    # the edge, because the old file ids no longer belong to the new experiment.
    assert record.lineage
    if record.experiment_id == 'old':
        assert record.lineage[0].source == 'raw/old.dat'
        assert record.lineage[0].target == 'processed/old.csv'
    else:
        assert record.experiment_id == 'new'
        assert record.lineage[0].source == 'raw/new.dat'
        assert record.lineage[0].target == 'processed/new.csv'

    first_store.close()
    second_store.close()


def test_unknown_device_and_artifact_states_are_valid(tmp_path):
    device = Device('D71')
    artifact = Artifact('art-unknown')
    snapshot = CatalogSnapshot(
        experiments=(_minimal_experiment('exp-1', sample_id='D71'),),
        devices=(device,),
        artifacts=(artifact,),
    )

    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(snapshot)

    assert store.get_device('D71') == device
    assert store.get_artifact('art-unknown') == artifact
    assert store.get_device('missing') is None
    assert store.get_artifact('missing') is None


def test_conflicting_device_claims_are_preserved(tmp_path):
    claims = (
        MetadataClaim(
            subject_type=SUBJECT_DEVICE,
            subject_id='D357',
            field='contact_material',
            value='gold',
            source_type='filename',
            source_reference='a.dat',
            extraction_method='deterministic',
            review_status=REVIEW_ACCEPTED,
        ),
        MetadataClaim(
            subject_type=SUBJECT_DEVICE,
            subject_id='D357',
            field='contact_material',
            value='platinum',
            source_type='filename',
            source_reference='b.dat',
            extraction_method='deterministic',
            review_status=REVIEW_UNKNOWN,
        ),
    )
    snapshot = CatalogSnapshot(
        experiments=(),
        devices=(Device('D357', claims=claims),),
    )

    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(snapshot)

    persisted = store.get_device('D357').claims
    assert len(persisted) == EXPECTED_CLAIMS
    assert {item.value for item in persisted} == {'gold', 'platinum'}
    assert len(store.get_provenance(SUBJECT_DEVICE, 'D357')) == EXPECTED_CLAIMS


def test_corrected_review_retains_candidate_and_evidence(tmp_path):
    claim = MetadataClaim(
        subject_type=SUBJECT_DEVICE,
        subject_id='D357',
        field='sample_label',
        value='D357_Au_split gate_WSe2',
        source_type='folder',
        source_reference='D357_Au_split gate_WSe2',
        extraction_method='folder_name',
        evidence=('folder_name=D357_Au_split gate_WSe2',),
        review_status=REVIEW_CORRECTED,
        reviewed_value='D357',
    )
    snapshot = CatalogSnapshot(
        experiments=(),
        devices=(Device('D357', claims=(claim,)),),
    )

    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(snapshot)

    persisted = store.get_provenance(SUBJECT_DEVICE, 'D357')[0]
    assert persisted.value == 'D357_Au_split gate_WSe2'
    assert persisted.reviewed_value == 'D357'
    assert persisted.evidence == ('folder_name=D357_Au_split gate_WSe2',)
    assert persisted.review_status == REVIEW_CORRECTED


def test_ordering_is_deterministic_across_rebuilds(tmp_path):
    experiment_ids = ('zeta', 'alpha', 'middle')
    experiments = tuple(
        _minimal_experiment(experiment_id, sample_id=f'D{100 + index}')
        for index, experiment_id in enumerate(experiment_ids)
    )
    snapshot = CatalogSnapshot(
        experiments=experiments,
        devices=(Device('D71'), Device('D357')),
    )

    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(snapshot)
    store.rebuild(snapshot)

    assert [item.experiment_id for item in store.list_experiments()] == list(
        experiment_ids
    )
    assert store.list_devices() == (Device('D71'), Device('D357'))
    assert store.list_claims() == store.list_claims()
    assert store.list_relationships() == store.list_relationships()


def test_failed_rebuild_rolls_back_atomically(tmp_path):
    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(_sample_snapshot())

    invalid = CatalogSnapshot(
        experiments=(_minimal_experiment('exp-new'),),
        artifacts=(Artifact('orphan', device_id='missing-device'),),
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.rebuild(invalid)

    assert store.get_experiment('exp-1') is not None
    assert store.get_experiment('exp-new') is None
    assert store.get_artifact('art-1') is not None


def test_device_folder_example_round_trips_with_artifact(tmp_path):
    device = Device(
        device_id='D357',
        aliases=('D357_Au_split gate_WSe2',),
        claims=(
            MetadataClaim(
                subject_type=SUBJECT_DEVICE,
                subject_id='D357',
                field='contact_material',
                value='Au',
                source_type='folder',
                source_reference='D357_Au_split gate_WSe2',
                extraction_method='folder_token',
                review_status=REVIEW_UNKNOWN,
            ),
            MetadataClaim(
                subject_type=SUBJECT_DEVICE,
                subject_id='D357',
                field='gate_configuration',
                value='split gate',
                source_type='folder',
                source_reference='D357_Au_split gate_WSe2',
                extraction_method='folder_token',
                review_status=REVIEW_UNKNOWN,
            ),
        ),
    )
    artifact = Artifact(
        artifact_id='art-d357',
        role='transport_curve',
        category='measurement',
        extension='csv',
        media_type='text/csv',
        device_id='D357',
        storage_reference=StorageReference('source-a', 'processed/D357.csv'),
        size_bytes=EXPECTED_ARTIFACT_SIZE,
        mtime_ns=EXPECTED_ARTIFACT_MTIME,
        review_state=REVIEW_UNKNOWN,
    )
    unknown_device = Device('D71')
    snapshot = CatalogSnapshot(
        experiments=(),
        devices=(device, unknown_device),
        artifacts=(artifact,),
        relationships=(
            Relationship(
                source_type=SUBJECT_ARTIFACT,
                source_id='art-d357',
                predicate='describes',
                target_type=SUBJECT_DEVICE,
                target_id='D357',
                review_state=REVIEW_UNKNOWN,
            ),
        ),
    )

    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(snapshot)

    persisted_device = store.get_device('D357')
    assert persisted_device == device
    assert persisted_device.aliases == ('D357_Au_split gate_WSe2',)
    assert store.get_device('D71') == Device('D71')

    persisted_artifact = store.get_artifact('art-d357')
    assert persisted_artifact == artifact
    assert persisted_artifact.extension == 'csv'
    assert persisted_artifact.role == 'transport_curve'
    assert persisted_artifact.device_id == 'D357'
    assert persisted_artifact.size_bytes == EXPECTED_ARTIFACT_SIZE
    assert persisted_artifact.mtime_ns == EXPECTED_ARTIFACT_MTIME


def test_global_relationships_and_provenance_retrieval(tmp_path):
    artifact_device = Relationship(
        source_type=SUBJECT_ARTIFACT,
        source_id='art-1',
        predicate='describes',
        target_type=SUBJECT_DEVICE,
        target_id='D357',
        review_state=REVIEW_UNKNOWN,
    )
    snapshot = CatalogSnapshot(
        experiments=(),
        devices=(Device('D357'),),
        artifacts=(
            Artifact(
                'art-1',
                device_id='D357',
                claims=(
                    MetadataClaim(
                        subject_type=SUBJECT_ARTIFACT,
                        subject_id='art-1',
                        field='kind',
                        value='figure',
                        review_status=REVIEW_UNKNOWN,
                    ),
                ),
            ),
        ),
        relationships=(artifact_device,),
    )

    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(snapshot)

    assert store.list_relationships() == (artifact_device,)
    assert store.get_lineage(SUBJECT_DEVICE, 'D357') == (artifact_device,)
    assert store.get_provenance(SUBJECT_ARTIFACT, 'art-1')[0].value == 'figure'


def test_unsupported_relationship_endpoints_are_rejected():
    with pytest.raises(ValueError, match='unsupported relationship endpoint type'):
        CatalogSnapshot(
            experiments=(),
            relationships=(
                Relationship(
                    source_type='pptslide',
                    source_id='slide-1',
                    predicate='part_of',
                    target_type='ppt',
                    target_id='deck-1',
                ),
            ),
        )


def test_rebuild_writes_only_to_supplied_db_and_makes_no_network_calls(
    tmp_path, monkeypatch
):
    source_dir = Path(scientific_catalog.__file__).parent
    before = sorted(
        str(path.relative_to(source_dir))
        for path in source_dir.rglob('*')
        if '__pycache__' not in path.parts
    )

    def fail_network(*args, **kwargs):
        raise AssertionError('network call attempted')

    monkeypatch.setattr(socket, 'socket', fail_network)
    monkeypatch.setattr(urllib.request, 'urlopen', fail_network)

    db_path = tmp_path / 'catalog.db'
    store = SQLiteCatalogStore(db_path)
    store.rebuild(_sample_snapshot())
    store.close()

    after = sorted(
        str(path.relative_to(source_dir))
        for path in source_dir.rglob('*')
        if '__pycache__' not in path.parts
    )
    assert before == after
    assert {path.name for path in tmp_path.iterdir()} <= {'catalog.db'}


def test_find_related_files_delegates_to_search_index(tmp_path):
    proposal = _proposal('D357', 'transport')
    snapshot = CatalogSnapshot.from_proposals(
        [proposal],
        experiment_ids=('exp-1',),
        storage_source_id='synthetic',
    )
    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(snapshot)

    files = store.find_related_files('exp-1', role='raw')
    assert len(files) == 1
    assert files[0].path == 'raw/D357.dat'
    assert files[0].role == 'raw'
    assert files[0].lineage[0].relation == 'derived_from'


def test_file_lineage_ids_are_scoped_by_storage_source(tmp_path):
    proposal = _proposal('D357', 'transport')
    first = CatalogSnapshot.from_proposals(
        [proposal], experiment_ids=('exp-a',), storage_source_id='source-a'
    )
    second = CatalogSnapshot.from_proposals(
        [proposal], experiment_ids=('exp-b',), storage_source_id='source-b'
    )
    assert first.relationships[0].source_id != second.relationships[0].source_id
    assert first.relationships[0].target_id != second.relationships[0].target_id


def test_metadata_claim_reviewed_value_invariant():
    with pytest.raises(ValueError, match='require reviewed_value'):
        MetadataClaim(
            subject_type=SUBJECT_DEVICE,
            subject_id='D1',
            field='name',
            value='candidate',
            review_status=REVIEW_CORRECTED,
        )
    with pytest.raises(ValueError, match='only valid'):
        MetadataClaim(
            subject_type=SUBJECT_DEVICE,
            subject_id='D1',
            field='name',
            value='candidate',
            review_status=REVIEW_ACCEPTED,
            reviewed_value='accepted',
        )
