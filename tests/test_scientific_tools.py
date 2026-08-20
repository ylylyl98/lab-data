import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from lab_data.artifact_previews import build_artifact_preview
from lab_data.device_experiment_linkage import HUMAN_REVIEWED_RAW_MATCH_FIELD
from lab_data.scientific_catalog import (
    ENTITY_FILE,
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
from lab_data.scientific_tools import MAX_LIMIT, MIN_LIMIT, ScientificToolLayer

SMALL_LIMIT = 2
CORE_DEVICE_COUNT = 3
D356_EXPERIMENT_COUNT = 3
CORE_EXPERIMENT_COUNT = 4
CORE_ARTIFACT_COUNT = 4
CORPUS_D356_EXPERIMENTS = 317
CORPUS_PAGE_SIZE = 20


def _file_id(reference: StorageReference) -> str:
    return deterministic_storage_reference_id(
        storage_source_id=reference.storage_source_id,
        relative_path=reference.relative_path,
    )


def _core_layer(tmp_path: Path) -> tuple[ScientificToolLayer, Path, Path]:
    """Build a small corpus mirroring the verified real-corpus shapes."""

    source = tmp_path / 'source'
    csv_dir = source / 'Initial Data'
    processed_dir = source / 'Processed Data'
    csv_dir.mkdir(parents=True)
    processed_dir.mkdir(parents=True)
    (source / 'docs').mkdir()
    preview_path = csv_dir / 'preview.csv'
    preview_path.write_text('x,y\n1,2\n', encoding='utf-8')
    preview_stat = preview_path.stat()

    raw_ref = StorageReference('source', 'Initial Data/YZ356_pa_BG2-CG_3.6KREF.csv')
    dat_ref = StorageReference(
        'source', 'Processed Data/YZ356_pa_BG2-CG_3.6KREF_avg1.dat'
    )
    png_ref = StorageReference(
        'source', 'Processed Data/YZ356_pa_BG2-CG_3.6KREF_avg1.png'
    )
    yz_raw = StorageReference('source', 'YZ247/raw/run_0432.dat')
    yz_dat = StorageReference('source', 'YZ247/processed/run_0432_avg.dat')
    yz_png = StorageReference('source', 'YZ247/figures/run_0432.png')
    ppt_ref = StorageReference('source', 'docs/D356 deck.ppt')
    pptx_ref = StorageReference('source', 'docs/D356 slides.pptx')
    preview_ref = StorageReference('source', 'Initial Data/preview.csv')

    measured_on_device_claim = MetadataClaim(
        subject_type=SUBJECT_EXPERIMENT,
        subject_id='D356-0316',
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
    )
    human_review_claim = MetadataClaim(
        subject_type=SUBJECT_EXPERIMENT,
        subject_id='D356-0316',
        field=HUMAN_REVIEWED_RAW_MATCH_FIELD,
        value={
            'device_id': 'D356',
            'experiment_id': 'D356-0316',
            'raw_relative_path': raw_ref.relative_path,
        },
        source_type='human_review',
        source_reference='artifacts/d356_0316_human_review_packet.md',
        extraction_method='human_reviewed_match',
        category='device_linkage',
        evidence=(
            'raw filename omits FixTG value',
            'artifacts/d356_0316_human_review_packet.md',
        ),
        review_status='accepted',
    )

    experiments = (
        Experiment(
            experiment_id='D356-0316',
            metadata={'sample_id': 'D356', 'measurement_type': 'PL'},
            files_by_role={
                'raw': (raw_ref,),
                'processed': (dat_ref,),
                'figure': (png_ref,),
            },
            needs_review=False,
            review_state='accepted',
            claims=(measured_on_device_claim, human_review_claim),
        ),
        Experiment(
            experiment_id='D356-0317',
            metadata={
                'sample_id': 'D356',
                'measurement_type': 'PL',
                'unresolved_processed_files': ['Initial Data/unlinked.csv'],
                'resolved_unresolved_history': [],
            },
            files_by_role={'raw': (raw_ref,)},
            needs_review=True,
            review_state='unknown',
        ),
        Experiment(
            experiment_id='D356-0001',
            metadata={'sample_id': 'D356', 'measurement_type': 'transport'},
            files_by_role={},
        ),
        Experiment(
            experiment_id='YZ247-0432',
            metadata={'sample_id': 'YZ247', 'measurement_type': 'transport'},
            files_by_role={
                'raw': (yz_raw,),
                'processed': (yz_dat,),
                'figure': (yz_png,),
            },
        ),
    )
    devices = (
        Device(
            'D356',
            device_type='chip',
            aliases=('D356 WSe2_AuSplitGate',),
            maker_namespace='YZ',
            local_device_id='D356',
            display_label='D356',
        ),
        Device('D357', device_type='chip'),
        Device('YZ247', device_type='chip', aliases=('YZ247_Stripe',)),
    )
    artifacts = (
        Artifact(
            'art-fig-0316',
            role='figure',
            category='image',
            extension='png',
            media_type='image/png',
            device_id='D356',
            experiment_id='D356-0316',
            storage_reference=png_ref,
        ),
        Artifact(
            'art-doc',
            role='document',
            category='document',
            extension='ppt',
            media_type='application/vnd.ms-powerpoint',
            device_id='D356',
            storage_reference=ppt_ref,
        ),
        Artifact(
            'art-deck',
            role='document',
            category='slide',
            extension='pptx',
            media_type=(
                'application/vnd.openxmlformats-officedocument.'
                'presentationml.presentation'
            ),
            device_id='D356',
            storage_reference=pptx_ref,
        ),
        Artifact(
            'art-preview',
            role='raw',
            category='data',
            extension='csv',
            media_type='text/csv',
            device_id='D356',
            storage_reference=preview_ref,
            size_bytes=preview_stat.st_size,
            mtime_ns=preview_stat.st_mtime_ns,
        ),
    )
    relationships = (
        Relationship(
            source_type=SUBJECT_EXPERIMENT,
            source_id='D356-0316',
            predicate='measured_on',
            target_type='device',
            target_id='D356',
            provenance_source='D356 WSe2_AuSplitGate',
        ),
        Relationship(
            source_type=SUBJECT_EXPERIMENT,
            source_id='D356-0317',
            predicate='measured_on',
            target_type='device',
            target_id='D356',
        ),
        Relationship(
            source_type=SUBJECT_EXPERIMENT,
            source_id='D356-0001',
            predicate='measured_on',
            target_type='device',
            target_id='D356',
        ),
        Relationship(
            source_type=SUBJECT_EXPERIMENT,
            source_id='YZ247-0432',
            predicate='measured_on',
            target_type='device',
            target_id='YZ247',
        ),
        Relationship(
            source_type=ENTITY_FILE,
            source_id=_file_id(raw_ref),
            predicate='derived_from',
            target_type=ENTITY_FILE,
            target_id=_file_id(dat_ref),
        ),
        Relationship(
            source_type=ENTITY_FILE,
            source_id=_file_id(dat_ref),
            predicate='derived_from',
            target_type=ENTITY_FILE,
            target_id=_file_id(png_ref),
        ),
    )
    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(CatalogSnapshot(experiments, devices, artifacts, relationships))
    preview_root = tmp_path / 'cache'
    build_artifact_preview(
        store,
        'art-preview',
        storage_roots={'source': source},
        preview_root=preview_root,
    )
    return ScientificToolLayer(store, preview_root=preview_root), source, preview_root


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _assert_json_safe_and_relative(value):
    json.dumps(value)
    for text in _strings(value):
        assert 'C:\\' not in text and 'C:/' not in text


def test_search_is_bounded_with_correct_total(tmp_path):
    layer, _, _ = _core_layer(tmp_path)
    devices = layer.search_devices(limit=SMALL_LIMIT)
    assert len(devices['items']) == SMALL_LIMIT
    assert devices['total_count'] == CORE_DEVICE_COUNT
    assert (devices['limit'], devices['offset']) == (SMALL_LIMIT, 0)
    experiments = layer.search_experiments(limit=SMALL_LIMIT)
    assert len(experiments['items']) == SMALL_LIMIT
    assert experiments['total_count'] == CORE_EXPERIMENT_COUNT
    artifacts = layer.search_artifacts(limit=SMALL_LIMIT)
    assert len(artifacts['items']) == SMALL_LIMIT
    assert artifacts['total_count'] == CORE_ARTIFACT_COUNT


def test_exact_id_retrieval_shapes(tmp_path):
    layer, _, _ = _core_layer(tmp_path)
    device = layer.get_device('D356')
    assert device['device_id'] == 'D356'
    assert device['aliases'] == ['D356 WSe2_AuSplitGate']
    assert layer.get_device('missing') is None

    experiment = layer.get_experiment('YZ247-0432')
    for key in (
        'experiment_id',
        'metadata',
        'files_by_role',
        'lineage',
        'warnings',
        'needs_review',
        'review_state',
        'measured_on',
        'review_evidence',
    ):
        assert key in experiment
    assert experiment['measured_on']['device_id'] == 'YZ247'
    assert sorted(experiment['files_by_role']) == ['figure', 'processed', 'raw']
    assert layer.get_experiment('missing') is None

    artifact = layer.get_artifact('art-fig-0316')
    assert artifact['artifact_id'] == 'art-fig-0316'
    assert artifact['derived_from'] == [
        {
            'source': 'Processed Data/YZ356_pa_BG2-CG_3.6KREF_avg1.dat',
            'target': 'Processed Data/YZ356_pa_BG2-CG_3.6KREF_avg1.png',
            'relation': 'derived_from',
        }
    ]
    assert layer.get_artifact('missing') is None


def test_numeric_device_shorthand_and_ambiguous_experiment_search(tmp_path):
    layer, _, _ = _core_layer(tmp_path)
    devices = layer.search_devices('356')
    assert [item['device_id'] for item in devices['items']] == ['D356']
    assert devices['total_count'] == 1

    experiments = layer.search_experiments('356')
    assert experiments['total_count'] > 1
    assert {item['experiment_id'] for item in experiments['items']} == {
        'D356-0001',
        'D356-0316',
        'D356-0317',
    }
    assert experiments['total_count'] == D356_EXPERIMENT_COUNT


def test_review_state_and_unresolved_metadata_are_preserved(tmp_path):
    layer, _, _ = _core_layer(tmp_path)
    unresolved = layer.get_experiment('D356-0317')
    assert unresolved['needs_review'] is True
    assert unresolved['review_state'] == 'unknown'
    assert unresolved['metadata']['unresolved_processed_files'] == [
        'Initial Data/unlinked.csv'
    ]
    assert unresolved['metadata']['resolved_unresolved_history'] == []

    accepted = layer.get_experiment('D356-0316')
    assert accepted['needs_review'] is False
    assert accepted['review_state'] == 'accepted'
    assert accepted['measured_on']['device_id'] == 'D356'
    assert {role: len(paths) for role, paths in accepted['files_by_role'].items()} == {
        'raw': 1,
        'processed': 1,
        'figure': 1,
    }
    assert accepted['review_evidence'][0]['field'] == HUMAN_REVIEWED_RAW_MATCH_FIELD
    assert accepted['review_evidence'][0]['source_type'] == 'human_review'
    assert accepted['review_evidence'][0]['extraction_method'] == 'human_reviewed_match'
    assert accepted['review_evidence'][0]['review_status'] == 'accepted'


def test_device_experiments_and_documents_are_bounded(tmp_path):
    layer, _, _ = _core_layer(tmp_path)
    page = layer.find_device_experiments('D356', limit=SMALL_LIMIT)
    assert page['total_count'] == D356_EXPERIMENT_COUNT
    assert len(page['items']) == SMALL_LIMIT
    documents = layer.find_device_documents('D356')
    assert documents['total_count'] == 1
    assert documents['items'][0]['artifact_id'] == 'art-doc'
    assert documents['items'][0]['extension'] == 'ppt'


def test_d356_corpus_style_fixture_returns_317_experiments(tmp_path):
    experiments = tuple(
        Experiment(
            experiment_id=f'D356-{index:04d}',
            metadata={'sample_id': 'D356'},
            files_by_role={},
        )
        for index in range(CORPUS_D356_EXPERIMENTS)
    )
    relationships = tuple(
        Relationship(
            source_type=SUBJECT_EXPERIMENT,
            source_id=experiment.experiment_id,
            predicate='measured_on',
            target_type='device',
            target_id='D356',
        )
        for experiment in experiments
    )
    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(
        CatalogSnapshot(
            experiments=experiments,
            devices=(Device('D356'),),
            relationships=relationships,
        )
    )
    layer = ScientificToolLayer(store)
    page = layer.find_device_experiments('D356', limit=CORPUS_PAGE_SIZE)
    assert page['total_count'] == CORPUS_D356_EXPERIMENTS
    assert len(page['items']) == CORPUS_PAGE_SIZE
    assert page['items'][0]['experiment_id'] == 'D356-0000'
    assert page['items'][-1]['experiment_id'] == 'D356-0019'


def test_provenance_and_lineage_expose_persisted_edges_only(tmp_path):
    layer, _, _ = _core_layer(tmp_path)
    claims = {
        claim['field']: claim
        for claim in layer.get_provenance('experiment', 'D356-0316')
    }
    assert claims['measured_on_device']['value']['device_id'] == 'D356'
    assert claims['measured_on_device']['source_type'] == 'storage_directory'
    assert claims['measured_on_device']['review_status'] == 'unknown'
    review = claims[HUMAN_REVIEWED_RAW_MATCH_FIELD]
    assert review['source_type'] == 'human_review'
    assert review['extraction_method'] == 'human_reviewed_match'
    assert review['review_status'] == 'accepted'
    assert review['evidence']
    assert review['source_reference'].startswith('artifacts/d356_0316')

    raw_ref = StorageReference('source', 'Initial Data/YZ356_pa_BG2-CG_3.6KREF.csv')
    dat_ref = StorageReference(
        'source', 'Processed Data/YZ356_pa_BG2-CG_3.6KREF_avg1.dat'
    )
    raw_lineage = layer.get_lineage(ENTITY_FILE, _file_id(raw_ref))
    assert len(raw_lineage) == 1
    assert raw_lineage[0]['predicate'] == 'derived_from'
    assert raw_lineage[0]['source_path'] == raw_ref.relative_path
    assert raw_lineage[0]['target_path'] == dat_ref.relative_path
    assert raw_lineage[0]['source_id'] != raw_lineage[0]['source_path']

    measured_on = layer.get_lineage('experiment', 'D356-0316')
    assert measured_on[0]['predicate'] == 'measured_on'
    assert measured_on[0]['target_id'] == 'D356'
    assert measured_on[0]['provenance_source'] == 'D356 WSe2_AuSplitGate'
    assert layer.get_lineage(ENTITY_FILE, _file_id(dat_ref))[1]['target_path'].endswith(
        '.png'
    )


def test_preview_returns_report_only_and_stays_within_preview_root(tmp_path):
    layer, source, preview_root = _core_layer(tmp_path)
    before = sorted(item for item in preview_root.rglob('*') if item.is_file())
    before_bytes = [item.read_bytes() for item in before]
    (source / 'Initial Data' / 'preview.csv').unlink()

    report = layer.get_artifact_preview('art-preview')
    assert report is not None
    assert report['artifact_id'] == 'art-preview'
    assert report['status'] == 'ready'
    assert report['kind'] == 'table'
    assert report['source_freshness_checked'] is False
    assert all(not Path(asset['path']).is_absolute() for asset in report['assets'])
    assert 'object_dir' not in report and 'manifest_path' not in report
    assert layer.get_artifact_preview('missing') is None

    after = sorted(item for item in preview_root.rglob('*') if item.is_file())
    assert [item.read_bytes() for item in after] == before_bytes


def test_preview_root_is_configuration_not_a_caller_path(tmp_path):
    layer, _, _ = _core_layer(tmp_path)
    with pytest.raises(ValueError, match='preview_root must be an absolute path'):
        ScientificToolLayer(layer.store, preview_root=Path('relative-cache'))
    unconfigured = ScientificToolLayer(layer.store)
    with pytest.raises(ValueError, match='not configured'):
        unconfigured.get_artifact_preview('art-preview')


def test_from_catalog_is_read_only(tmp_path):
    layer, _, _ = _core_layer(tmp_path)
    db_path = tmp_path / 'catalog.db'
    mtime_before = db_path.stat().st_mtime_ns
    opened = ScientificToolLayer.from_catalog(db_path, preview_root=tmp_path / 'cache')
    assert opened.get_device('D356')['device_id'] == 'D356'
    assert opened.search_devices('356')['total_count'] == 1
    opened.close()
    assert db_path.stat().st_mtime_ns == mtime_before


def test_all_tool_outputs_are_json_safe_without_absolute_paths(tmp_path):
    layer, _, _ = _core_layer(tmp_path)
    outputs = [
        layer.search_devices(limit=200),
        layer.search_experiments(limit=200),
        layer.search_artifacts(limit=200),
        layer.get_device('D356'),
        layer.get_experiment('D356-0316'),
        layer.get_artifact('art-fig-0316'),
        layer.find_device_experiments('D356', limit=200),
        layer.find_device_documents('D356', limit=200),
        layer.get_provenance('experiment', 'D356-0316'),
        layer.get_lineage(
            ENTITY_FILE,
            _file_id(
                StorageReference('source', 'Initial Data/YZ356_pa_BG2-CG_3.6KREF.csv')
            ),
        ),
        layer.get_artifact_preview('art-preview'),
    ]
    for output in outputs:
        _assert_json_safe_and_relative(output)


def test_invalid_inputs_raise_clear_errors(tmp_path):
    layer, _, _ = _core_layer(tmp_path)
    for tool in (layer.get_device, layer.get_experiment, layer.get_artifact):
        with pytest.raises(ValueError, match='non-empty string'):
            tool('')
    with pytest.raises(ValueError, match='non-empty string'):
        layer.get_device(None)
    with pytest.raises(ValueError, match='non-empty string'):
        layer.find_device_experiments('')

    with pytest.raises(ValueError, match='limit must be an integer'):
        layer.search_devices(limit=0)
    with pytest.raises(ValueError, match='limit must be an integer'):
        layer.search_experiments(limit=MAX_LIMIT + 1)
    with pytest.raises(ValueError, match='limit must be an integer'):
        layer.search_artifacts(limit=MIN_LIMIT - 1)
    with pytest.raises(ValueError, match='limit must be an integer'):
        layer.search_devices(limit=True)
    with pytest.raises(ValueError, match='offset must be a non-negative integer'):
        layer.search_devices(offset=-1)

    with pytest.raises(ValueError, match='unknown device filter'):
        layer.search_devices(filters={'alias': 'alias-a'})
    with pytest.raises(ValueError, match='unknown artifact filter'):
        layer.search_artifacts(filters={'path': 'docs/D356.ppt'})
    with pytest.raises(ValueError, match='unknown experiment filter'):
        layer.search_experiments(filters={'bogus': 1})
    with pytest.raises(ValueError, match='unknown artifact kind'):
        layer.search_artifacts(kind='bogus')
    with pytest.raises(ValueError, match='unknown subject type'):
        layer.get_provenance('bogus', 'D356-0316')
    with pytest.raises(ValueError, match='unknown entity type'):
        layer.get_lineage('bogus', 'D356-0316')
    with pytest.raises(ValueError, match='non-empty string'):
        layer.get_provenance('experiment', '')
    with pytest.raises(ValueError, match='q must be a string or None'):
        layer.search_devices(q=356)
