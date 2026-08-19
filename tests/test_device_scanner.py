import errno
import socket
import urllib.request
import zipfile
from pathlib import Path

import pytest

from lab_data import device_scanner
from lab_data.device_scanner import (
    DeviceScanResult,
    HumanDeviceIdentityDecision,
    UnresolvedFolder,
    apply_device_identity_decisions,
    scan_device_folders,
)
from lab_data.scientific_catalog import (
    SUBJECT_ARTIFACT,
    SUBJECT_DEVICE,
    UNKNOWN,
    Artifact,
    Device,
    SQLiteCatalogStore,
    StorageReference,
)

EXPECTED_ARTIFACT_COUNT = 5


def test_explicit_namespace_qualifies_without_legacy_inference(tmp_path):
    (tmp_path / 'D237').mkdir()
    (tmp_path / 'D237' / 'note.pdf').write_bytes(b'pdf')
    legacy = scan_device_folders(tmp_path, 'source-a')
    qualified = scan_device_folders(tmp_path, 'source-a', maker_namespace='YZ')
    assert legacy.devices[0].maker_namespace is None
    assert qualified.devices[0].device_id == 'D237'
    assert qualified.devices[0].maker_namespace == 'YZ'
    assert qualified.artifacts[0].device_id == 'D237'
    assert [claim.field for claim in qualified.devices[0].claims].count(
        'device_identity'
    ) == 1


def test_identity_decision_rebinds_descendants_and_removes_unresolved(tmp_path):
    (tmp_path / 'mystery').mkdir()
    (tmp_path / 'mystery' / 'note.pdf').write_bytes(b'pdf')
    result = scan_device_folders(tmp_path, 'source-a')
    resolved = apply_device_identity_decisions(
        result,
        (
            HumanDeviceIdentityDecision(
                relative_folder='mystery',
                maker_namespace='QC',
                local_device_id='148',
                display_label='QC 148',
                provenance_source='reviewer:test',
            ),
        ),
    )
    assert resolved.unresolved_folders == ()
    device = resolved.devices[0]
    assert device.maker_namespace == 'QC'
    assert resolved.artifacts[0].device_id == device.device_id
    assert any(claim.review_status == 'corrected' for claim in device.claims)


def test_identity_decisions_merge_existing_devices_and_preserve_unresolved(tmp_path):
    existing = (
        Device('D237', aliases=('237',), display_label='D237'),
        Device(
            'D148', maker_namespace='YZ', local_device_id='D148', display_label='D148'
        ),
    )
    artifact = Artifact(
        'a',
        extension='pdf',
        media_type='application/pdf',
        storage_reference=StorageReference('source-a', 'Photocurrent sample/note.pdf'),
    )
    result = DeviceScanResult(
        devices=existing,
        artifacts=(artifact,),
        unresolved_folders=(
            UnresolvedFolder('237_2s sensing', 'ambiguous', 'D237'),
            UnresolvedFolder('Photocurrent sample', 'unresolved'),
            UnresolvedFolder('D302', 'unresolved', 'D302'),
            UnresolvedFolder('D327', 'unresolved', 'D327'),
        ),
    )
    resolved = apply_device_identity_decisions(
        result,
        (
            HumanDeviceIdentityDecision(
                '237_2s sensing',
                'YZ',
                'D237',
                'D237',
                'review:D237',
                aliases=('237', '237_2s sensing'),
                evidence=('folder=237', 'folder=237_2s sensing'),
            ),
            HumanDeviceIdentityDecision(
                'Photocurrent sample',
                'QC',
                '148',
                'QC148',
                'review:QC148',
                aliases=('QC148',),
                evidence=('nested=Photocurrent sample',),
            ),
        ),
    )
    assert {item.folder_name for item in resolved.unresolved_folders} == {
        'D302',
        'D327',
    }
    qc = next(item for item in resolved.devices if item.maker_namespace == 'QC')
    assert qc.display_label == 'QC148'
    yz = next(item for item in resolved.devices if item.maker_namespace == 'YZ')
    assert yz.aliases == ('237', '237_2s sensing')
    assert qc.aliases == ('Photocurrent sample', 'QC148')
    assert resolved.artifacts[0].device_id == qc.device_id
    edge = next(
        item for item in resolved.relationships if item.predicate == 'describes'
    )
    assert edge.review_state == 'accepted'
    assert edge.provenance_source == 'review:QC148'
    corrected = next(item for item in qc.claims if item.review_status == 'corrected')
    assert corrected.value['folder_name'] == 'Photocurrent sample'
    db = tmp_path / 'resolved.db'
    with SQLiteCatalogStore(db) as store:
        store.rebuild(resolved.to_snapshot())
    with SQLiteCatalogStore(db) as reopened:
        persisted = reopened.get_device_by_identity('QC', '148')
        assert persisted.display_label == 'QC148'
        assert any(item.review_status == 'corrected' for item in persisted.claims)


_P_NS = 'http://schemas.openxmlformats.org/presentationml/2006/main'
_A_NS = 'http://schemas.openxmlformats.org/drawingml/2006/main'
_R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
_PKG_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'


def _write_minimal_pptx(path: Path, *, title_type: str = 'title') -> None:
    presentation = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<p:presentation xmlns:p="{_P_NS}" xmlns:r="{_R_NS}">'
        '<p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst>'
        '</p:presentation>'
    )
    presentation_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{_PKG_NS}">'
        f'<Relationship Id="rId1" Type="{_R_NS}/slide" '
        'Target="slides/slide1.xml"/></Relationships>'
    )
    slide = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<p:sld xmlns:p="{_P_NS}" xmlns:a="{_A_NS}" xmlns:r="{_R_NS}">'
        '<p:cSld><p:spTree>'
        '<p:sp><p:nvSpPr><p:cNvPr id="1" name="Title 1"/><p:cNvSpPr/>'
        f'<p:nvPr><p:ph type="{title_type}"/></p:nvPr></p:nvSpPr><p:spPr/>'
        '<p:txBody><a:bodyPr/><a:lstStyle/>'
        '<a:p><a:r><a:t>My Slide Title</a:t></a:r></a:p></p:txBody></p:sp>'
        '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Content 2"/><p:cNvSpPr/>'
        '<p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr><p:spPr/>'
        '<p:txBody><a:bodyPr/><a:lstStyle/>'
        '<a:p><a:r><a:t>Sample device scan</a:t></a:r></a:p></p:txBody></p:sp>'
        '</p:spTree></p:cSld></p:sld>'
    )
    slide_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{_PKG_NS}">'
        f'<Relationship Id="rId2" Type="{_R_NS}/image" '
        'Target="../media/image1.png"/>'
        f'<Relationship Id="rId3" Type="{_R_NS}/notesSlide" '
        'Target="../notesSlides/notesSlide1.xml"/></Relationships>'
    )
    notes = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<p:notes xmlns:p="{_P_NS}" xmlns:a="{_A_NS}">'
        '<p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes 3"/>'
        '<p:cNvSpPr/><p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr>'
        '<p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>'
        '<a:p><a:r><a:t>Speaker note text</a:t></a:r></a:p></p:txBody></p:sp>'
        '</p:spTree></p:cSld></p:notes>'
    )

    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('ppt/presentation.xml', presentation)
        archive.writestr('ppt/_rels/presentation.xml.rels', presentation_rels)
        archive.writestr('ppt/slides/slide1.xml', slide)
        archive.writestr('ppt/slides/_rels/slide1.xml.rels', slide_rels)
        archive.writestr('ppt/notesSlides/notesSlide1.xml', notes)
        archive.writestr('ppt/media/image1.png', b'fake-image')


def _snapshot_tree(root: Path) -> tuple[tuple[str, int, int], ...]:
    entries = []
    for path in sorted(root.rglob('*')):
        file_stat = path.stat()
        entries.append(
            (
                path.relative_to(root).as_posix(),
                file_stat.st_size,
                file_stat.st_mtime_ns,
            )
        )
    return tuple(entries)


def test_d357_folder_resolves_device_and_token_claims(tmp_path):
    folder = tmp_path / 'D357_Au_split gate_WSe2'
    folder.mkdir()
    (folder / 'notes.pdf').write_bytes(b'pdf')

    result = scan_device_folders(tmp_path, 'source-a')

    assert [device.device_id for device in result.devices] == ['D357']
    device = result.devices[0]
    assert device.device_type == UNKNOWN
    assert device.aliases == ('D357_Au_split gate_WSe2',)
    assert [(claim.field, claim.value) for claim in device.claims] == [
        ('folder_token', 'Au'),
        ('folder_token', 'split'),
        ('folder_token', 'gate'),
        ('folder_token', 'WSe2'),
    ]
    assert all(claim.source_type == 'folder_name' for claim in device.claims)
    assert all(claim.category == 'candidate' for claim in device.claims)
    assert all(claim.review_status == 'unknown' for claim in device.claims)
    assert device.claims[0].evidence == ('folder_name=D357_Au_split gate_WSe2',)


def test_d71_without_suffix_is_valid_unknown(tmp_path):
    (tmp_path / 'D71').mkdir()

    result = scan_device_folders(tmp_path, 'source-a')

    assert len(result.devices) == 1
    device = result.devices[0]
    assert device.device_id == 'D71'
    assert device.device_type == UNKNOWN
    assert device.aliases == ('D71',)
    assert device.claims == ()
    assert device.review_state == 'unknown'


def test_compact_device_folder_is_reviewable_candidate(tmp_path):
    (tmp_path / 'YZ123_mystery').mkdir()
    (tmp_path / 'Data_backup').mkdir()
    (tmp_path / 'D71abc').mkdir()
    (tmp_path / 'YZ123_mystery' / 'note.pdf').write_bytes(b'pdf')

    result = scan_device_folders(tmp_path, 'source-a')

    assert [device.device_id for device in result.devices] == ['D71']
    assert result.devices[0].aliases == ('D71abc',)
    assert result.devices[0].claims[0].source_reference == 'D71abc'
    assert {item.folder_name for item in result.unresolved_folders} == {
        'YZ123_mystery',
        'Data_backup',
    }
    assert result.artifacts[0].device_id is None
    assert result.artifacts[0].storage_reference.relative_path == (
        'YZ123_mystery/note.pdf'
    )
    assert any('unresolved candidate folder' in item for item in result.warnings)


def test_storage_references_are_relative_without_absolute_leakage(tmp_path):
    (tmp_path / 'D71').mkdir()
    (tmp_path / 'D71' / 'scan.pdf').write_bytes(b'pdf')

    result = scan_device_folders(tmp_path, 'source-a')

    reference = result.artifacts[0].storage_reference
    assert reference.storage_source_id == 'source-a'
    assert reference.relative_path == 'D71/scan.pdf'
    assert not reference.relative_path.startswith('/')
    assert '\\' not in reference.relative_path
    assert str(tmp_path) not in reference.relative_path


def test_root_level_files_are_base_artifacts_without_device_relationships(tmp_path):
    (tmp_path / 'root.pdf').write_bytes(b'pdf')
    (tmp_path / 'D71').mkdir()
    (tmp_path / 'D71' / 'device.pdf').write_bytes(b'pdf')

    result = scan_device_folders(tmp_path, 'source-a')

    root_artifact = next(
        artifact
        for artifact in result.artifacts
        if artifact.storage_reference.relative_path == 'root.pdf'
    )
    assert root_artifact.device_id is None
    assert root_artifact.role == UNKNOWN
    assert root_artifact.category == UNKNOWN
    assert root_artifact.review_state == 'unknown'
    assert root_artifact.media_type == 'application/pdf'
    assert root_artifact.size_bytes == len(b'pdf')
    assert all(
        relationship.source_id != root_artifact.artifact_id
        for relationship in result.relationships
    )


def test_root_level_pptx_is_not_opened_without_allowlist(tmp_path, monkeypatch):
    deck = tmp_path / 'root.pptx'
    deck.write_bytes(b'not opened')

    def fail_extract(*args, **kwargs):
        raise AssertionError('PPTX extraction was not explicitly selected')

    monkeypatch.setattr(device_scanner, '_extract_pptx', fail_extract)
    result = scan_device_folders(tmp_path, 'source-a')

    assert result.slides == ()
    assert [
        artifact.storage_reference.relative_path for artifact in result.artifacts
    ] == ['root.pptx']
    assert result.relationships == ()


def test_root_level_pptx_allowlist_extracts_without_device_relationship(tmp_path):
    _write_minimal_pptx(tmp_path / 'root.pptx')

    result = scan_device_folders(
        tmp_path,
        'source-a',
        pptx_extraction_allowlist=['root.pptx'],
    )

    assert len(result.slides) == 1
    slide_artifact = next(
        artifact for artifact in result.artifacts if artifact.category == 'slide'
    )
    assert slide_artifact.device_id is None
    assert all(item.predicate != 'describes' for item in result.relationships)
    assert [item.predicate for item in result.relationships] == ['part_of']


def test_duplicate_device_candidates_are_unresolved_without_entities_or_relationships(
    tmp_path,
):
    for folder_name in ('D302', 'D302_repeat'):
        folder = tmp_path / folder_name
        folder.mkdir()
        (folder / 'data.pdf').write_bytes(folder_name.encode())

    first = scan_device_folders(tmp_path, 'source-a')
    second = scan_device_folders(tmp_path, 'source-b')

    assert first.devices == ()
    assert [item.folder_name for item in first.unresolved_folders] == [
        'D302',
        'D302_repeat',
    ]
    assert [item.candidate_device_id for item in first.unresolved_folders] == [
        'D302',
        'D302',
    ]
    assert all(
        'ambiguous duplicate identity' in item.reason
        for item in first.unresolved_folders
    )
    assert all(artifact.device_id is None for artifact in first.artifacts)
    assert first.relationships == ()
    assert [artifact.artifact_id for artifact in first.artifacts] == [
        artifact.artifact_id for artifact in second.artifacts
    ]
    assert first.unresolved_folders == second.unresolved_folders


def test_os_error_warning_does_not_leak_absolute_source_path(tmp_path, monkeypatch):
    folder = tmp_path / 'D71'
    folder.mkdir()
    unreadable = folder / 'secret.pdf'
    unreadable.write_bytes(b'pdf')
    real_stat = Path.stat

    def fail_selected_stat(self, *args, **kwargs):
        if self == unreadable and kwargs.get('follow_symlinks', True):
            raise OSError(errno.EACCES, 'denied', str(self))
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'stat', fail_selected_stat)

    result = scan_device_folders(tmp_path, 'source-a')

    assert 'stat error: D71/secret.pdf' in result.warnings
    assert all(str(tmp_path) not in warning for warning in result.warnings)


def test_lstat_error_is_relative_and_does_not_abort_scan(tmp_path, monkeypatch):
    folder = tmp_path / 'D71'
    folder.mkdir()
    unreadable = folder / 'broken-reparse.pdf'
    unreadable.write_bytes(b'pdf')
    real_stat = Path.stat

    def fail_selected_lstat(self, *args, **kwargs):
        if self == unreadable and kwargs.get('follow_symlinks') is False:
            raise OSError(errno.EACCES, 'denied', str(self))
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'stat', fail_selected_lstat)

    result = scan_device_folders(tmp_path, 'source-a')

    assert result.artifacts == ()
    assert 'lstat error: D71/broken-reparse.pdf' in result.warnings
    assert all(str(tmp_path) not in warning for warning in result.warnings)


def test_artifact_role_is_unknown_regardless_of_extension(tmp_path):
    folder = tmp_path / 'D71'
    folder.mkdir()
    for name in ('a.pptx', 'b.png', 'c.pdf', 'd.opju', 'e.unknown'):
        (folder / name).write_bytes(b'x')

    result = scan_device_folders(tmp_path, 'source-a')

    assert len(result.artifacts) == EXPECTED_ARTIFACT_COUNT
    for artifact in result.artifacts:
        assert artifact.role == UNKNOWN
        assert artifact.category == UNKNOWN


def test_pptx_inventory_is_metadata_only_by_default(tmp_path, monkeypatch):
    folder = tmp_path / 'D71'
    folder.mkdir()
    (folder / 'deck.pptx').write_bytes(b'not opened')

    def fail_extract(*args, **kwargs):
        raise AssertionError('PPTX extraction was not explicitly selected')

    monkeypatch.setattr(device_scanner, '_extract_pptx', fail_extract)
    result = scan_device_folders(tmp_path, 'source-a')

    assert result.slides == ()
    assert result.artifacts[0].storage_reference.relative_path == 'D71/deck.pptx'


@pytest.mark.parametrize(
    'invalid', ['/D71/deck.pptx', '../D71/deck.pptx', 'C:/deck.pptx']
)
def test_pptx_allowlist_rejects_non_relative_paths(tmp_path, invalid):
    with pytest.raises(ValueError):
        scan_device_folders(tmp_path, 'source-a', pptx_extraction_allowlist=[invalid])


def test_ids_and_ordering_are_source_independent_and_stable(tmp_path):
    folder_a = tmp_path / 'D357_Au'
    folder_a.mkdir()
    folder_b = tmp_path / 'D71'
    folder_b.mkdir()
    (folder_a / 'one.pdf').write_bytes(b'1')
    (folder_a / 'two.png').write_bytes(b'2')
    (folder_b / 'three.pdf').write_bytes(b'3')

    first = scan_device_folders(tmp_path, 'source-a')
    second = scan_device_folders(tmp_path, 'source-b')
    third = scan_device_folders(tmp_path, 'source-a')

    first_ids = [artifact.artifact_id for artifact in first.artifacts]
    second_ids = [artifact.artifact_id for artifact in second.artifacts]
    third_ids = [artifact.artifact_id for artifact in third.artifacts]
    assert first_ids == second_ids == third_ids
    assert [device.device_id for device in first.devices] == ['D357', 'D71']
    assert [
        artifact.storage_reference.relative_path for artifact in first.artifacts
    ] == ['D357_Au/one.pdf', 'D357_Au/two.png', 'D71/three.pdf']
    assert all(
        artifact.storage_reference.storage_source_id == 'source-b'
        for artifact in second.artifacts
    )


def test_scan_is_read_only(tmp_path):
    folder = tmp_path / 'D71'
    folder.mkdir()
    (folder / 'data.pdf').write_bytes(b'pdf')

    before = _snapshot_tree(tmp_path)
    scan_device_folders(tmp_path, 'source-a')
    after = _snapshot_tree(tmp_path)

    assert before == after


def test_pptx_slide_extraction_and_relationships(tmp_path):
    folder = tmp_path / 'D357_Au'
    folder.mkdir()
    _write_minimal_pptx(folder / 'device.pptx')

    result = scan_device_folders(
        tmp_path,
        'source-a',
        pptx_extraction_allowlist=['D357_Au/device.pptx'],
    )

    assert len(result.slides) == 1
    slide = result.slides[0]
    assert slide.slide_index == 1
    assert slide.title == 'My Slide Title'
    assert slide.text_runs == ('Sample device scan',)
    assert slide.labels == ('Sample device scan',)
    assert slide.notes == 'Speaker note text'
    assert slide.image_refs == ('../media/image1.png',)

    slide_artifact = next(
        artifact for artifact in result.artifacts if artifact.category == 'slide'
    )
    assert slide_artifact.device_id == 'D357'
    assert slide_artifact.metadata['slide_index'] == 1

    deck_artifact = next(
        artifact
        for artifact in result.artifacts
        if artifact.category == UNKNOWN
        and artifact.storage_reference.relative_path == 'D357_Au/device.pptx'
    )

    part_of = [item for item in result.relationships if item.predicate == 'part_of']
    assert len(part_of) == 1
    assert part_of[0].source_type == SUBJECT_ARTIFACT
    assert part_of[0].source_id == slide_artifact.artifact_id
    assert part_of[0].target_type == SUBJECT_ARTIFACT
    assert part_of[0].target_id == deck_artifact.artifact_id

    describes = [item for item in result.relationships if item.predicate == 'describes']
    slide_describes = [
        item for item in describes if item.source_id == slide_artifact.artifact_id
    ]
    assert len(slide_describes) == 1
    assert slide_describes[0].source_type == SUBJECT_ARTIFACT
    assert slide_describes[0].target_type == SUBJECT_DEVICE
    assert slide_describes[0].target_id == 'D357'

    store = SQLiteCatalogStore(tmp_path / 'catalog.db')
    try:
        persisted = store.rebuild(result.to_snapshot())
        persisted_ids = {
            SUBJECT_ARTIFACT: {item.artifact_id for item in persisted.artifacts},
            SUBJECT_DEVICE: {item.device_id for item in persisted.devices},
        }
        assert all(
            relationship.source_id in persisted_ids[relationship.source_type]
            and relationship.target_id in persisted_ids[relationship.target_type]
            for relationship in persisted.relationships
        )
    finally:
        store.close()


def test_pptx_ctr_title_placeholder_is_recognized(tmp_path):
    folder = tmp_path / 'D357_Au'
    folder.mkdir()
    _write_minimal_pptx(folder / 'device.pptx', title_type='ctrTitle')

    result = scan_device_folders(
        tmp_path,
        'source-a',
        pptx_extraction_allowlist=['D357_Au/device.pptx'],
    )

    assert len(result.slides) == 1
    assert result.slides[0].title == 'My Slide Title'


def test_malformed_pptx_and_legacy_ppt_are_graceful(tmp_path):
    folder = tmp_path / 'D71'
    folder.mkdir()
    (folder / 'broken.pptx').write_bytes(b'not a zip')
    (folder / 'legacy.ppt').write_bytes(b'legacy binary')

    result = scan_device_folders(
        tmp_path,
        'source-a',
        pptx_extraction_allowlist=['D71/broken.pptx'],
    )

    assert result.slides == ()
    assert any('cannot parse pptx' in item for item in result.warnings)
    assert any('legacy PPT extraction unsupported' in item for item in result.warnings)
    ppt_artifact = next(
        artifact for artifact in result.artifacts if artifact.extension == 'ppt'
    )
    assert ppt_artifact.metadata['deterministic_extraction'] == 'unsupported'


def test_unsupported_pptx_package_member_is_graceful(tmp_path, monkeypatch):
    folder = tmp_path / 'D71'
    folder.mkdir()
    deck = folder / 'unsupported.pptx'
    _write_minimal_pptx(deck)
    real_read = zipfile.ZipFile.read

    def fail_encrypted_member(self, name, *args, **kwargs):
        if name == 'ppt/presentation.xml':
            raise RuntimeError(f'encrypted member from {deck}')
        return real_read(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, 'read', fail_encrypted_member)

    result = scan_device_folders(
        tmp_path,
        'source-a',
        pptx_extraction_allowlist=['D71/unsupported.pptx'],
    )

    assert result.slides == ()
    assert 'cannot parse pptx package: D71/unsupported.pptx' in result.warnings
    assert all(str(tmp_path) not in warning for warning in result.warnings)


def test_symlink_warning_uses_storage_relative_path(tmp_path, monkeypatch):
    folder = tmp_path / 'D71'
    folder.mkdir()
    target = folder / 'real.pdf'
    target.write_bytes(b'x')
    link = folder / 'link.pdf'

    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        link.write_bytes(b'x')
        real_is_symlink = Path.is_symlink

        def fake_is_symlink(self):
            if self == link:
                return True
            return real_is_symlink(self)

        monkeypatch.setattr(Path, 'is_symlink', fake_is_symlink)

    result = scan_device_folders(tmp_path, 'source-a')

    symlink_warnings = [item for item in result.warnings if 'symlink skipped' in item]
    assert symlink_warnings
    assert symlink_warnings[0] == 'symlink skipped: D71/link.pdf'
    assert str(tmp_path) not in symlink_warnings[0]
    assert '\\' not in symlink_warnings[0]


def test_scanner_makes_no_network_calls(tmp_path, monkeypatch):
    def fail_network(*args, **kwargs):
        raise AssertionError('network call attempted')

    monkeypatch.setattr(socket, 'socket', fail_network)
    monkeypatch.setattr(urllib.request, 'urlopen', fail_network)

    folder = tmp_path / 'D71'
    folder.mkdir()
    (folder / 'x.pdf').write_bytes(b'x')

    scan_device_folders(tmp_path, 'source-a')
