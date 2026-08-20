"""Security, read-only, and smoke tests for the local MCP adapter."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from lab_data.artifact_previews import build_artifact_preview
from lab_data.device_experiment_linkage import HUMAN_REVIEWED_RAW_MATCH_FIELD
from lab_data.mcp_adapter import (
    CATALOG_PATH_ENV,
    PREVIEW_ROOT_ENV,
    load_mcp_config,
)
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
from lab_data.scientific_tools import MAX_LIMIT, MIN_LIMIT

EXPECTED_TOOLS = frozenset(
    {
        'search_devices',
        'search_experiments',
        'search_artifacts',
        'get_device',
        'get_experiment',
        'get_artifact',
        'find_device_experiments',
        'find_device_documents',
        'get_provenance',
        'get_lineage',
        'get_artifact_preview',
    }
)
EXPECTED_TOOL_COUNT = 11

# FastMCP 1.x emits list returns as one content item per element.
_LIST_TOOLS = frozenset({'get_provenance', 'get_lineage'})

REAL_CATALOG = Path(
    r'C:\NOMAD_Test_Output\scientific_catalog_readiness\yz247_yzdev_catalog.sqlite'
)
REAL_PREVIEW_ROOT = Path(
    r'C:\NOMAD_Test_Output\scientific_catalog_readiness\artifact_previews'
)
REAL_PREVIEW_ARTIFACTS = {
    'image': 'art-029d5b532c378670e00320db94839f95b36ba11224fbafefe2f058b9b88cd8ec',
    'table': 'art-a3c1d812a06420a63dec17ae353af6d2c33f3646bd6371390c4ce6ee87ed93af',
    'slide': 'art-9cab37f35bfa5bc011ec6c95d2477bc015f35d62b273f4b67b3c7fb2202f605d',
}

SMALL_LIMIT = 2
CORE_DEVICE_COUNT = 3
D356_EXPERIMENT_COUNT = 3
CORE_ARTIFACT_COUNT = 4
CORPUS_D356_EXPERIMENTS = 317
CORPUS_YZ247_TOTAL = 1505
CORPUS_PAGE_SIZE = 20


def _file_id(reference: StorageReference) -> str:
    return deterministic_storage_reference_id(
        storage_source_id=reference.storage_source_id,
        relative_path=reference.relative_path,
    )


def _corpus(tmp_path: Path) -> tuple[Path, Path]:
    """Build a small catalog and preview root mirroring corpus shapes."""

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
        evidence=('raw filename omits FixTG value',),
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
    return tmp_path / 'catalog.db', preview_root


def _env(catalog: Path, preview_root: Path) -> dict[str, str]:
    return {
        **os.environ,
        CATALOG_PATH_ENV: str(catalog),
        PREVIEW_ROOT_ENV: str(preview_root),
    }


@asynccontextmanager
async def _mcp_session(catalog: Path, preview_root: Path):
    params = StdioServerParameters(
        command=sys.executable,
        args=['-m', 'lab_data.mcp_adapter'],
        env=_env(catalog, preview_root),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def _call(session, name: str, arguments: Mapping[str, object]):
    result = await session.call_tool(name, dict(arguments))
    texts = [item.text for item in result.content if getattr(item, 'text', None)]
    if result.isError:
        return True, None, texts[0] if texts else None
    payloads = [json.loads(text) for text in texts]
    if name in _LIST_TOOLS:
        payload = payloads
    elif payloads:
        payload = payloads[0]
    else:
        payload = None
    return False, payload, texts[0] if texts else None


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _assert_no_absolute_paths(payload):
    for text in _strings(payload):
        assert 'C:\\' not in text and 'C:/' not in text


@pytest.mark.asyncio
async def test_exposed_tool_set_is_exactly_the_readonly_set(tmp_path):
    async with _mcp_session(*_corpus(tmp_path)) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools.tools}
        assert names == EXPECTED_TOOLS
        for name in names:
            assert not any(
                token in name
                for token in ('create', 'update', 'delete', 'write', 'upload', 'insert')
            )


@pytest.mark.asyncio
async def test_tool_discovery_surface_is_complete_unique_and_bounded(tmp_path):
    """Discovery surface: 11 read-only tools, unique names, and bounded schemas."""
    async with _mcp_session(*_corpus(tmp_path)) as client:
        tools = (await client.list_tools()).tools
        names = [tool.name for tool in tools]
        assert len(tools) == len(EXPECTED_TOOLS) == EXPECTED_TOOL_COUNT
        assert set(names) == EXPECTED_TOOLS
        assert len(names) == len(set(names)), 'duplicate tool names exposed'
        for tool in tools:
            assert not any(
                token in tool.name
                for token in (
                    'create',
                    'update',
                    'delete',
                    'write',
                    'upload',
                    'save',
                    'insert',
                )
            )
            assert tool.description, f'{tool.name} has no description'
            schema = tool.inputSchema
            assert schema and schema.get('type') == 'object'
            properties = schema.get('properties', {})
            if 'limit' in properties:
                assert properties['limit']['minimum'] == MIN_LIMIT
                assert properties['limit']['maximum'] == MAX_LIMIT
            if 'offset' in properties:
                assert properties['offset']['minimum'] == 0
            for key in ('device_id', 'experiment_id', 'artifact_id', 'subject_id', 'entity_id'):
                if key in properties:
                    assert properties[key].get('minLength', 0) >= 1
                    assert key in schema.get('required', ())


@pytest.mark.asyncio
async def test_search_is_bounded_and_deterministic(tmp_path):
    async with _mcp_session(*_corpus(tmp_path)) as client:
        error, payload, _ = await _call(client, 'search_devices', {'q': '356'})
        assert not error
        assert payload['total_count'] == 1
        assert [item['device_id'] for item in payload['items']] == ['D356']

        error, payload, _ = await _call(client, 'search_devices', {'limit': SMALL_LIMIT})
        assert not error
        assert len(payload['items']) == SMALL_LIMIT
        assert payload['total_count'] == CORE_DEVICE_COUNT

        error, payload, _ = await _call(
            client,
            'find_device_experiments',
            {'device_id': 'D356', 'limit': SMALL_LIMIT},
        )
        assert not error
        assert payload['total_count'] == D356_EXPERIMENT_COUNT
        assert len(payload['items']) == SMALL_LIMIT


@pytest.mark.asyncio
async def test_review_states_surface(tmp_path):
    async with _mcp_session(*_corpus(tmp_path)) as client:
        error, payload, _ = await _call(
            client, 'get_experiment', {'experiment_id': 'D356-0316'}
        )
        assert not error
        assert payload['needs_review'] is False
        assert payload['review_state'] == 'accepted'
        assert sorted(payload['files_by_role']) == ['figure', 'processed', 'raw']

        error, payload, _ = await _call(
            client, 'get_experiment', {'experiment_id': 'D356-0317'}
        )
        assert not error
        assert payload['needs_review'] is True
        assert payload['review_state'] == 'unknown'


@pytest.mark.asyncio
async def test_provenance_and_lineage_via_mcp(tmp_path):
    async with _mcp_session(*_corpus(tmp_path)) as client:
        error, payload, _ = await _call(
            client,
            'get_provenance',
            {'subject_type': 'experiment', 'subject_id': 'D356-0316'},
        )
        assert not error
        claims = {claim['field']: claim for claim in payload}
        assert claims['measured_on_device']['value']['device_id'] == 'D356'
        review = claims[HUMAN_REVIEWED_RAW_MATCH_FIELD]
        assert review['source_type'] == 'human_review'
        assert review['extraction_method'] == 'human_reviewed_match'
        assert review['review_status'] == 'accepted'

        raw_ref = StorageReference(
            'source', 'Initial Data/YZ356_pa_BG2-CG_3.6KREF.csv'
        )
        error, payload, _ = await _call(
            client,
            'get_lineage',
            {'entity_type': ENTITY_FILE, 'entity_id': _file_id(raw_ref)},
        )
        assert not error
        assert payload[0]['predicate'] == 'derived_from'
        assert payload[0]['source_path'] == raw_ref.relative_path
        assert payload[0]['target_path'].endswith('.dat')


@pytest.mark.asyncio
async def test_preview_is_metadata_only_and_missing_ids_are_harmless(tmp_path):
    async with _mcp_session(*_corpus(tmp_path)) as client:
        error, payload, _ = await _call(
            client, 'get_artifact_preview', {'artifact_id': 'art-preview'}
        )
        assert not error
        assert payload['artifact_id'] == 'art-preview'
        assert payload['status'] == 'ready'
        assert payload['kind'] == 'table'
        assert all(not Path(asset['path']).is_absolute() for asset in payload['assets'])
        assert 'object_dir' not in payload and 'manifest_path' not in payload
        _assert_no_absolute_paths(payload)

        error, payload, _ = await _call(
            client, 'get_artifact_preview', {'artifact_id': 'missing'}
        )
        assert not error
        assert payload is None


@pytest.mark.asyncio
async def test_all_responses_are_relative_without_absolute_paths(tmp_path):
    raw_ref = StorageReference('source', 'Initial Data/YZ356_pa_BG2-CG_3.6KREF.csv')
    calls = [
        ('search_devices', {'q': '356'}),
        ('search_devices', {'limit': 200}),
        ('search_experiments', {'limit': 200}),
        ('search_artifacts', {'limit': 200}),
        ('get_device', {'device_id': 'D356'}),
        ('get_experiment', {'experiment_id': 'D356-0316'}),
        ('get_artifact', {'artifact_id': 'art-fig-0316'}),
        ('find_device_experiments', {'device_id': 'D356', 'limit': 200}),
        ('find_device_documents', {'device_id': 'D356'}),
        ('get_provenance', {'subject_type': 'experiment', 'subject_id': 'D356-0316'}),
        ('get_lineage', {'entity_type': ENTITY_FILE, 'entity_id': _file_id(raw_ref)}),
        ('get_artifact_preview', {'artifact_id': 'art-preview'}),
    ]
    async with _mcp_session(*_corpus(tmp_path)) as client:
        for name, arguments in calls:
            error, payload, _ = await _call(client, name, arguments)
            assert not error, f'{name} failed'
            _assert_no_absolute_paths(payload)


@pytest.mark.asyncio
async def test_invalid_arguments_are_rejected(tmp_path):
    async with _mcp_session(*_corpus(tmp_path)) as client:
        for name, arguments in (
            ('get_device', {'device_id': ''}),
            ('get_experiment', {'experiment_id': ''}),
            ('get_artifact', {'artifact_id': ''}),
            ('find_device_experiments', {'device_id': ''}),
            ('get_provenance', {'subject_type': 'experiment', 'subject_id': ''}),
            ('search_devices', {'limit': 201}),
            ('search_devices', {'limit': 0}),
            ('search_devices', {'offset': -1}),
        ):
            error, _, text = await _call(client, name, arguments)
            assert error, f'{name} {arguments} was accepted'
            assert text and 'Error executing tool' in text

        error, _, text = await _call(
            client, 'search_experiments', {'filters': {'bogus': 1}}
        )
        assert error and 'unknown experiment filter' in text

        error, _, text = await _call(
            client,
            'get_provenance',
            {'subject_type': 'bogus', 'subject_id': 'D356-0316'},
        )
        assert error and 'unknown subject type' in text

        error, _, text = await _call(client, 'search_artifacts', {'kind': 'bogus'})
        assert error and 'unknown artifact kind' in text


def test_config_validation_requires_existing_paths(tmp_path, monkeypatch):
    catalog, preview_root = _corpus(tmp_path)
    monkeypatch.setenv(CATALOG_PATH_ENV, str(catalog))
    monkeypatch.setenv(PREVIEW_ROOT_ENV, str(preview_root))
    assert load_mcp_config() == (catalog, preview_root)

    monkeypatch.delenv(CATALOG_PATH_ENV, raising=False)
    monkeypatch.delenv(PREVIEW_ROOT_ENV, raising=False)
    with pytest.raises(ValueError, match='must both be set'):
        load_mcp_config()

    monkeypatch.setenv(CATALOG_PATH_ENV, str(tmp_path / 'missing.sqlite'))
    monkeypatch.setenv(PREVIEW_ROOT_ENV, str(preview_root))
    with pytest.raises(ValueError, match='does not point to a readable catalog'):
        load_mcp_config()

    monkeypatch.setenv(CATALOG_PATH_ENV, str(catalog))
    monkeypatch.setenv(PREVIEW_ROOT_ENV, str(tmp_path / 'missing-preview'))
    with pytest.raises(ValueError, match='does not point to a preview directory'):
        load_mcp_config()


@pytest.mark.skipif(
    not REAL_CATALOG.is_file(),
    reason='real YZ247/YZDEV corpus not present on this machine',
)
@pytest.mark.asyncio
async def test_real_corpus_mcp_smoke():  # noqa: PLR0915
    """Deterministic real-corpus checks; prints one JSON summary per call."""

    async with _mcp_session(REAL_CATALOG, REAL_PREVIEW_ROOT) as session:

        async def report(label: str, name: str, arguments: dict) -> None:
            error, payload, _ = await _call(session, name, arguments)
            print(f'SMOKE {label}: {json.dumps(payload, sort_keys=True)}')
            assert not error, f'{label} failed'
            return payload

        devices = await report('search_devices_356', 'search_devices', {'q': '356'})
        assert [item['device_id'] for item in devices['items']] == ['D356']

        page = await report(
            'find_device_experiments_D356',
            'find_device_experiments',
            {'device_id': 'D356', 'limit': 5},
        )
        assert page['total_count'] == CORPUS_D356_EXPERIMENTS

        page = await report(
            'find_device_experiments_D357',
            'find_device_experiments',
            {'device_id': 'D357'},
        )
        assert page['total_count'] == 0

        exact = await report(
            'get_experiment_YZ247-0432',
            'get_experiment',
            {'experiment_id': 'YZ247-0432'},
        )
        assert exact['experiment_id'] == 'YZ247-0432'
        assert exact['metadata']['sample_id'] == 'YZ247'
        assert exact['metadata']['measurement_type'] == 'photoluminescence'

        accepted = await report(
            'get_experiment_D356-0316',
            'get_experiment',
            {'experiment_id': 'D356-0316'},
        )
        assert accepted['review_state'] == 'accepted'
        assert accepted['needs_review'] is False
        assert {
            role: len(paths) for role, paths in accepted['files_by_role'].items()
        } == {'raw': 1, 'processed': 1, 'figure': 1}

        unresolved = await report(
            'get_experiment_D356-0317',
            'get_experiment',
            {'experiment_id': 'D356-0317'},
        )
        assert unresolved['needs_review'] is True
        assert unresolved['review_state'] == 'unknown'

        claims = await report(
            'provenance_D356-0316',
            'get_provenance',
            {'subject_type': 'experiment', 'subject_id': 'D356-0316'},
        )
        claims_by_field = {claim['field']: claim for claim in claims}
        assert claims_by_field['measured_on_device']['value']['device_id'] == 'D356'
        review = claims_by_field[HUMAN_REVIEWED_RAW_MATCH_FIELD]
        assert review['source_type'] == 'human_review'
        assert review['extraction_method'] == 'human_reviewed_match'
        assert review['review_status'] == 'accepted'

        raw_path = accepted['files_by_role']['raw'][0]
        raw_artifacts = await report(
            'raw_artifact_lookup',
            'search_artifacts',
            {'filters': {'relative_path': raw_path}, 'limit': 1},
        )
        raw_artifact = raw_artifacts['items'][0]
        raw_file_id = deterministic_storage_reference_id(
            storage_source_id=raw_artifact['storage_source_id'],
            relative_path=raw_artifact['relative_path'],
        )
        lineage = await report(
            'lineage_D356-0316_raw',
            'get_lineage',
            {'entity_type': ENTITY_FILE, 'entity_id': raw_file_id},
        )
        assert lineage[0]['predicate'] == 'derived_from'
        assert lineage[0]['source_path'] == raw_path
        assert lineage[0]['target_path'].endswith('.dat')

        broad = await report(
            'search_YZ247_bounded',
            'search_experiments',
            {'q': 'YZ247', 'limit': 20},
        )
        assert broad['total_count'] == CORPUS_YZ247_TOTAL
        assert len(broad['items']) == CORPUS_PAGE_SIZE

        filtered = await report(
            'search_measurement_type_plus_q',
            'search_experiments',
            {
                'q': '0432',
                'filters': {'measurement_type': 'photoluminescence'},
                'limit': 10,
            },
        )
        assert filtered['total_count'] == 1
        assert filtered['items'][0]['experiment_id'] == 'YZ247-0432'

        for kind, artifact_id in REAL_PREVIEW_ARTIFACTS.items():
            preview = await report(
                f'preview_{kind}',
                'get_artifact_preview',
                {'artifact_id': artifact_id},
            )
            assert preview['status'] == 'ready'
            assert preview['kind'] == kind
            assert all(
                not Path(asset['path']).is_absolute() for asset in preview['assets']
            )
            assert all(asset['media_type'] for asset in preview['assets'])
            _assert_no_absolute_paths(preview)

        for label, payload in (
            ('devices', devices),
            ('d356_experiments', page),
            ('d357_experiments', page),
            ('exact', exact),
            ('accepted', accepted),
            ('unresolved', unresolved),
            ('provenance', claims),
            ('lineage', lineage),
            ('broad', broad),
            ('filtered', filtered),
        ):
            _assert_no_absolute_paths(payload)
