import hashlib
import json
import socket
import struct
import urllib.request
import zipfile
from pathlib import Path

import pytest

import lab_data.artifact_previews as previews
from lab_data.artifact_previews import (
    build_artifact_preview,
    build_artifact_preview_report,
    discover_artifact_preview,
    search_artifact_previews,
)
from lab_data.scientific_catalog import (
    Artifact,
    CatalogSnapshot,
    SQLiteCatalogStore,
    StorageReference,
)


def _store(
    tmp_path: Path, source: Path, *, name: str = 'data.csv', extension: str = 'csv'
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = source / name
    stat = path.stat()
    artifact = Artifact(
        artifact_id='artifact-1',
        extension=extension,
        media_type='text/csv',
        storage_reference=StorageReference('source', name),
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )
    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(CatalogSnapshot(experiments=(), artifacts=(artifact,)))
    return store, artifact


def test_csv_preview_and_discovery_are_deterministic(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'data.csv').write_text('time,value\n1,2\n2,5\n', encoding='utf-8')
    store, artifact = _store(tmp_path, source)
    cache_a = tmp_path / 'cache-a'
    cache_b = tmp_path / 'cache-b'
    assert (
        discover_artifact_preview(
            store,
            artifact.artifact_id,
            storage_roots={'source': source},
            preview_root=cache_a,
        )
        is None
    )
    first = build_artifact_preview(
        store,
        artifact.artifact_id,
        storage_roots={'source': source},
        preview_root=cache_a,
    )
    second = build_artifact_preview(
        store,
        artifact.artifact_id,
        storage_roots={'source': source},
        preview_root=cache_b,
    )
    assert first.status == 'ready' and first.kind == 'table'
    tree_a = {
        p.relative_to(first.object_dir).as_posix(): p.read_bytes()
        for p in first.object_dir.rglob('*')
        if p.is_file()
    }
    tree_b = {
        p.relative_to(second.object_dir).as_posix(): p.read_bytes()
        for p in second.object_dir.rglob('*')
        if p.is_file()
    }
    assert tree_a == tree_b
    assert discover_artifact_preview(
        store,
        artifact.artifact_id,
        storage_roots={'source': source},
        preview_root=cache_a,
    ).fresh


def test_malformed_and_unsupported_use_placeholder(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'data.bin').write_bytes(b'not supported')
    store, artifact = _store(tmp_path, source, name='data.bin', extension='bin')
    preview = build_artifact_preview(
        store,
        artifact.artifact_id,
        storage_roots={'source': source},
        preview_root=tmp_path / 'cache',
    )
    assert preview.status == 'unsupported' and preview.kind == 'placeholder'
    try:
        link = source / 'link.csv'
        link.symlink_to(source / 'data.csv')
    except (OSError, NotImplementedError):
        return
    link_artifact = artifact.__class__(
        artifact_id='link',
        extension='csv',
        media_type='text/csv',
        storage_reference=StorageReference('source', 'link.csv'),
        size_bytes=artifact.size_bytes,
        mtime_ns=artifact.mtime_ns,
    )
    store.rebuild(CatalogSnapshot(experiments=(), artifacts=(link_artifact,)))
    with pytest.raises(ValueError, match='symlinks'):
        build_artifact_preview(
            store,
            'link',
            storage_roots={'source': source},
            preview_root=tmp_path / 'cache-link',
        )
    assert (preview.object_dir / 'placeholder.svg').is_file()


def test_missing_source_discovers_stale_preview(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'data.csv').write_text('x,y\n1,2\n', encoding='utf-8')
    store, artifact = _store(tmp_path, source)
    cache = tmp_path / 'cache'
    build_artifact_preview(
        store,
        artifact.artifact_id,
        storage_roots={'source': source},
        preview_root=cache,
    )
    (source / 'data.csv').unlink()
    discovered = discover_artifact_preview(
        store,
        artifact.artifact_id,
        storage_roots={'source': source},
        preview_root=cache,
    )
    assert discovered is not None and not discovered.fresh


def test_stale_catalog_record_is_classified(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    path = source / 'data.csv'
    path.write_text('x,y\n1,2\n', encoding='utf-8')
    store, artifact = _store(tmp_path, source)
    stale = Artifact(
        artifact_id=artifact.artifact_id,
        extension='csv',
        media_type='text/csv',
        storage_reference=StorageReference('source', 'data.csv'),
        size_bytes=999,
        mtime_ns=artifact.mtime_ns,
    )
    store.rebuild(CatalogSnapshot(experiments=(), artifacts=(stale,)))
    preview = build_artifact_preview(
        store,
        stale.artifact_id,
        storage_roots={'source': source},
        preview_root=tmp_path / 'cache-stale',
    )
    assert preview.status == 'stale_catalog' and not preview.fresh


def test_oversized_csv_field_is_malformed_placeholder(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    path = source / 'data.csv'
    path.write_text('header\n' + ('x' * 131_073) + '\n', encoding='utf-8')
    store, artifact = _store(tmp_path, source)
    preview = build_artifact_preview(
        store,
        artifact.artifact_id,
        storage_roots={'source': source},
        preview_root=tmp_path / 'cache',
    )
    assert preview.status == 'malformed' and preview.kind == 'placeholder'


def test_malformed_tiff_field_type_is_placeholder(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    path = source / 'image.tiff'
    path.write_bytes(
        b'II*\x00'
        + struct.pack('<I', 8)
        + struct.pack('<H', 2)
        + struct.pack('<HHI', 256, 1, 4)
        + b'\x00\x00\x00\x00'
        + struct.pack('<HHI', 257, 1, 4)
        + b'\x00\x00\x00\x00'
        + struct.pack('<I', 0)
    )
    store, artifact = _store(tmp_path, source, name='image.tiff', extension='tiff')
    preview = build_artifact_preview(
        store,
        artifact.artifact_id,
        storage_roots={'source': source},
        preview_root=tmp_path / 'cache-tiff',
    )
    assert preview.status == 'malformed' and preview.kind == 'placeholder'


def test_manifest_is_canonical_json(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'data.csv').write_text('x,y\n1,2\n', encoding='utf-8')
    store, artifact = _store(tmp_path, source)
    preview = build_artifact_preview(
        store,
        artifact.artifact_id,
        storage_roots={'source': source},
        preview_root=tmp_path / 'cache',
    )
    raw = (preview.object_dir / 'manifest.json').read_bytes()
    assert raw.endswith(b'\n')
    assert json.loads(raw) == json.loads(raw)
    assert str(tmp_path) not in raw.decode()


def test_preview_does_not_change_catalog_or_use_network(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'data.csv').write_text('x,y\n1,2\n', encoding='utf-8')
    store, artifact = _store(tmp_path, source)
    db_hash = hashlib.sha256((tmp_path / 'catalog.db').read_bytes()).hexdigest()

    def fail(*args, **kwargs):
        raise AssertionError('network call attempted')

    monkeypatch.setattr(socket, 'socket', fail)
    monkeypatch.setattr(urllib.request, 'urlopen', fail)
    build_artifact_preview(
        store,
        artifact.artifact_id,
        storage_roots={'source': source},
        preview_root=tmp_path / 'cache',
    )
    assert hashlib.sha256((tmp_path / 'catalog.db').read_bytes()).hexdigest() == db_hash


def test_supported_image_signatures_and_malformed_placeholder(tmp_path):
    cases = {
        'png': b'\x89PNG\r\n\x1a\n'
        + b'\x00\x00\x00\rIHDR'
        + struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0),
        'jpg': b'\xff\xd8\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x03\x01\x11\x00\xff\xd9',
        'tiff': b'II*\x00'
        + struct.pack('<I', 8)
        + struct.pack('<H', 2)
        + struct.pack('<HHI', 256, 4, 1)
        + struct.pack('<I', 1)
        + struct.pack('<HHI', 257, 4, 1)
        + struct.pack('<I', 1)
        + struct.pack('<I', 0),
    }
    for extension, data in cases.items():
        source = tmp_path / extension
        source.mkdir()
        path = source / f'image.{extension}'
        path.write_bytes(data)
        store, artifact = _store(
            tmp_path / f'db-{extension}', source, name=path.name, extension=extension
        )
        preview = build_artifact_preview(
            store,
            artifact.artifact_id,
            storage_roots={'source': source},
            preview_root=tmp_path / f'cache-{extension}',
        )
        assert preview.status == 'ready' and preview.kind == 'image'
        assert (preview.object_dir / f'image.{extension}').read_bytes() == data
    bad = tmp_path / 'bad'
    bad.mkdir()
    (bad / 'bad.png').write_bytes(b'bad')
    store, artifact = _store(tmp_path / 'db-bad', bad, name='bad.png', extension='png')
    preview = build_artifact_preview(
        store,
        artifact.artifact_id,
        storage_roots={'source': bad},
        preview_root=tmp_path / 'cache-bad',
    )
    assert preview.status == 'malformed' and preview.kind == 'placeholder'


def test_too_large_and_symlink_inputs_are_placeholders(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'data.csv').write_text('x,y\n1,2\n', encoding='utf-8')
    store, artifact = _store(tmp_path / 'db-large', source)
    monkeypatch.setattr(previews, 'MAX_SOURCE_BYTES', 1)
    preview = build_artifact_preview(
        store,
        artifact.artifact_id,
        storage_roots={'source': source},
        preview_root=tmp_path / 'cache-large',
    )
    assert preview.status == 'too_large' and preview.kind == 'placeholder'


def test_dat_delimiter_and_pptx_search_text(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'data.dat').write_text('x;y\n1;2\n', encoding='utf-8')
    store, artifact = _store(
        tmp_path / 'db-dat', source, name='data.dat', extension='dat'
    )
    preview = build_artifact_preview(
        store,
        artifact.artifact_id,
        storage_roots={'source': source},
        preview_root=tmp_path / 'cache-dat',
    )
    assert (
        json.loads((preview.object_dir / 'table.json').read_text())['delimiter'] == ';'
    )
    deck = source / 'deck.pptx'
    slide = '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="1" name="Title"/><p:cNvSpPr/><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>Deck title</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>'
    presentation = '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId id="1" r:id="rId1"/></p:sldIdLst></p:presentation>'
    rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/></Relationships>'
    slide_rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" Target="../notesSlides/notesSlide1.xml"/></Relationships>'
    notes = '<p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="2" name="Notes"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>Speaker note</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:notes>'
    with zipfile.ZipFile(deck, 'w') as archive:
        archive.writestr('ppt/presentation.xml', presentation)
        archive.writestr('ppt/_rels/presentation.xml.rels', rels)
        archive.writestr('ppt/slides/slide1.xml', slide)
        archive.writestr('ppt/slides/_rels/slide1.xml.rels', slide_rels)
        archive.writestr('ppt/notesSlides/notesSlide1.xml', notes)
    store, ppt = _store(
        tmp_path / 'db-pptx', source, name='deck.pptx', extension='pptx'
    )
    preview = build_artifact_preview(
        store,
        ppt.artifact_id,
        storage_roots={'source': source},
        preview_root=tmp_path / 'cache-pptx',
    )
    assert preview.status == 'ready' and preview.kind == 'slide'
    assert 'Deck title' in preview.search_text and 'Speaker note' in preview.search_text
    assert (preview.object_dir / 'slides/0001.svg').is_file()


def test_storage_traversal_is_rejected():
    with pytest.raises(ValueError):
        StorageReference('source', '../escape.csv')


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob('*') if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b'\0')
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_cache_only_preview_search_is_deterministic_and_read_only(
    tmp_path, monkeypatch
):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'alpha.csv').write_text('label,value\nAlpha   Beta,1\n', encoding='utf-8')
    (source / 'gamma.csv').write_text('label,value\nGamma,2\n', encoding='utf-8')
    artifacts = []
    for artifact_id, name in (('artifact-b', 'gamma.csv'), ('artifact-a', 'alpha.csv')):
        stat_result = (source / name).stat()
        artifacts.append(
            Artifact(
                artifact_id,
                extension='csv',
                media_type='text/csv',
                storage_reference=StorageReference('source', name),
                size_bytes=stat_result.st_size,
                mtime_ns=stat_result.st_mtime_ns,
            )
        )
    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    store.rebuild(CatalogSnapshot(experiments=(), artifacts=tuple(artifacts)))
    preview_root = tmp_path / 'cache'
    for artifact in artifacts:
        build_artifact_preview(
            store,
            artifact.artifact_id,
            storage_roots={'source': source},
            preview_root=preview_root,
        )

    catalog_hash = hashlib.sha256((tmp_path / 'catalog.db').read_bytes()).hexdigest()
    cache_hash = _tree_hash(preview_root)
    for path in source.iterdir():
        path.unlink()

    def fail(*args, **kwargs):
        raise AssertionError('network or source access attempted')

    monkeypatch.setattr(socket, 'socket', fail)
    monkeypatch.setattr(urllib.request, 'urlopen', fail)
    results = search_artifact_previews(
        store,
        ['artifact-b', 'artifact-a', 'artifact-b', 'missing'],
        preview_root=preview_root,
    )
    assert [item.artifact_id for item in results] == ['artifact-a', 'artifact-b']
    assert all(not item.source_freshness_checked and not item.fresh for item in results)
    assert [
        item.artifact_id
        for item in search_artifact_previews(
            store,
            ['artifact-b', 'artifact-a'],
            preview_root=preview_root,
            status='READY',
            kind='table',
            text=' alpha beta ',
        )
    ] == ['artifact-a']
    assert (
        search_artifact_previews(
            store,
            ['artifact-a'],
            preview_root=preview_root,
            text='not present',
        )
        == ()
    )
    assert (
        hashlib.sha256((tmp_path / 'catalog.db').read_bytes()).hexdigest()
        == catalog_hash
    )
    assert _tree_hash(preview_root) == cache_hash


def test_cache_only_preview_search_skips_tampering_and_validates_inputs(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'data.csv').write_text('x,y\n1,2\n', encoding='utf-8')
    store, artifact = _store(tmp_path, source)
    preview_root = tmp_path / 'cache'
    preview = build_artifact_preview(
        store,
        artifact.artifact_id,
        storage_roots={'source': source},
        preview_root=preview_root,
    )
    assert search_artifact_previews(
        store, [artifact.artifact_id], preview_root=preview_root
    )
    (preview.object_dir / preview.assets[0].path).write_bytes(b'tampered')
    assert (
        search_artifact_previews(
            store, [artifact.artifact_id], preview_root=preview_root
        )
        == ()
    )
    preview = build_artifact_preview(
        store,
        artifact.artifact_id,
        storage_roots={'source': source},
        preview_root=preview_root,
    )
    manifest = json.loads(preview.manifest_path.read_text(encoding='utf-8'))
    manifest['search_text'] = 'x' * (previews.MAX_PPTX_CHARS + 1)
    preview.manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    assert (
        search_artifact_previews(
            store, [artifact.artifact_id], preview_root=preview_root
        )
        == ()
    )
    preview = build_artifact_preview(
        store,
        artifact.artifact_id,
        storage_roots={'source': source},
        preview_root=preview_root,
    )
    manifest = json.loads(preview.manifest_path.read_text(encoding='utf-8'))
    manifest['assets'][0]['path'] = '../escape.json'
    preview.manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    assert (
        search_artifact_previews(
            store, [artifact.artifact_id], preview_root=preview_root
        )
        == ()
    )
    preview = build_artifact_preview(
        store,
        artifact.artifact_id,
        storage_roots={'source': source},
        preview_root=preview_root,
    )
    preview.manifest_path.write_bytes(b'{' + b'x' * previews.MAX_MANIFEST_BYTES)
    assert (
        search_artifact_previews(
            store, [artifact.artifact_id], preview_root=preview_root
        )
        == ()
    )
    preview = build_artifact_preview(
        store,
        artifact.artifact_id,
        storage_roots={'source': source},
        preview_root=preview_root,
    )
    external_manifest = tmp_path / 'external-manifest.json'
    external_manifest.write_text('{}', encoding='utf-8')
    preview.manifest_path.unlink()
    try:
        preview.manifest_path.symlink_to(external_manifest)
    except (OSError, NotImplementedError):
        pass
    else:
        assert (
            search_artifact_previews(
                store, [artifact.artifact_id], preview_root=preview_root
            )
            == ()
        )
    assert search_artifact_previews(store, ['missing'], preview_root=preview_root) == ()

    with pytest.raises(TypeError):
        search_artifact_previews(store, 'artifact-1', preview_root=preview_root)
    with pytest.raises(ValueError):
        search_artifact_previews(store, [''], preview_root=preview_root)
    with pytest.raises(ValueError):
        search_artifact_previews(
            store, ['artifact-1'], preview_root=preview_root, status=' '
        )
    with pytest.raises(ValueError):
        search_artifact_previews(
            store, ['artifact-1'], preview_root=Path('relative-cache')
        )


def test_preview_report_is_json_safe_cache_only_and_deterministic(
    tmp_path, monkeypatch
):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'data.csv').write_text(
        'label,value\nReport   sample,3\n', encoding='utf-8'
    )
    store, artifact = _store(tmp_path, source)
    preview_root = tmp_path / 'cache'
    build_artifact_preview(
        store,
        artifact.artifact_id,
        storage_roots={'source': source},
        preview_root=preview_root,
    )
    catalog_hash = hashlib.sha256((tmp_path / 'catalog.db').read_bytes()).hexdigest()
    cache_hash = _tree_hash(preview_root)
    (source / 'data.csv').unlink()

    def fail(*args, **kwargs):
        raise AssertionError('source or network access attempted')

    monkeypatch.setattr(previews, '_resolve_source', fail)
    monkeypatch.setattr(socket, 'socket', fail)
    monkeypatch.setattr(urllib.request, 'urlopen', fail)
    report = build_artifact_preview_report(
        store,
        ['missing', artifact.artifact_id, artifact.artifact_id],
        preview_root=preview_root,
        kind='TABLE',
        text=' report sample ',
    )
    assert [item['artifact_id'] for item in report] == [artifact.artifact_id]
    assert report[0]['status'] == 'ready'
    assert report[0]['kind'] == 'table'
    assert report[0]['source_freshness_checked'] is False
    assert report[0]['search_match'] == {
        'query': ' report sample ',
        'matched': True,
        'text_available': True,
    }
    assert all(
        not Path(asset['path']).is_absolute()
        for item in report
        for asset in item['assets']
    )
    assert all(
        key not in item for item in report for key in ('object_dir', 'manifest_path')
    )
    json.dumps(report)
    assert hashlib.sha256((tmp_path / 'catalog.db').read_bytes()).hexdigest() == (
        catalog_hash
    )
    assert _tree_hash(preview_root) == cache_hash
