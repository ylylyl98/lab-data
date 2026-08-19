"""Read-only Device/Artifact folder scanner with deterministic PPTX extraction.

This module scans a caller-supplied filesystem root for conservative device
folder candidates, inventories files as storage-relative artifacts, and
extracts deterministic PPTX slide structure using only the Python standard
library.  It never modifies source folders, never transmits file contents, and
never calls a provider.  Outputs are directly mergeable into
:class:`lab_data.scientific_catalog.CatalogSnapshot`.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import re
import stat
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from xml.etree import ElementTree

from lab_data.scientific_catalog import (
    REVIEW_ACCEPTED,
    REVIEW_UNKNOWN,
    SUBJECT_ARTIFACT,
    SUBJECT_DEVICE,
    UNKNOWN,
    Artifact,
    CatalogSnapshot,
    Device,
    MetadataClaim,
    Relationship,
    StorageReference,
    _canonical_relative_path,
    deterministic_device_id,
)

__all__ = [
    'DeviceScanResult',
    'SlideRecord',
    'UnresolvedFolder',
    'HumanDeviceIdentityDecision',
    'apply_device_identity_decisions',
    'scan_device_folders',
]

_DEVICE_PREFIX_RE = re.compile(r'^D(\d+)(.*)$')
_TOKEN_SPLIT_RE = re.compile(r'[_\s]+')
_SLIDE_NUMBER_RE = re.compile(r'(\d+)\.xml$')

_P_NS = 'http://schemas.openxmlformats.org/presentationml/2006/main'
_R_ID = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'

_MEDIA_TYPES = {
    'ppt': 'application/vnd.ms-powerpoint',
    'pptx': (
        'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    ),
    'pdf': 'application/pdf',
    'png': 'image/png',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'tif': 'image/tiff',
    'tiff': 'image/tiff',
    'opju': 'application/octet-stream',
}


def _local_name(tag: str) -> str:
    """Return the namespace-free local name of an XML element tag."""

    return tag.rsplit('}', 1)[-1]


def _stable_id(prefix: str, *parts: str) -> str:
    """Return a deterministic, storage-source-independent identifier."""

    digest = hashlib.sha256('::'.join(parts).encode('utf-8')).hexdigest()
    return f'{prefix}-{digest}'


def _device_id_from_basename(basename: str) -> tuple[str, str] | None:
    """Return ``(device_id, remainder)`` for a conservative folder basename.

    A leading ``D`` followed by digits is retained as a candidate.  Compact
    suffixes (for example ``D317mos2bnmote2``) remain reviewable/ambiguous;
    separator-based names are the conservative authoritative-looking form.
    """

    match = _DEVICE_PREFIX_RE.match(basename)
    if match is None:
        return None
    remainder = match.group(2)
    return f'D{match.group(1)}', remainder


def _folder_tokens(remainder: str) -> tuple[str, ...]:
    """Split the non-device remainder into conservative token hints."""

    return tuple(token for token in _TOKEN_SPLIT_RE.split(remainder) if token)


def _extension_of(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix.startswith('.') and len(suffix) > 1:
        return suffix[1:]
    return UNKNOWN


def _normalize_text(text: str) -> str | None:
    stripped = text.strip()
    return stripped or None


def _slide_sort_key(name: str) -> tuple[int, str]:
    match = _SLIDE_NUMBER_RE.search(name)
    return (int(match.group(1)) if match else 0, name)


def _find_child(element: ElementTree.Element, local: str) -> ElementTree.Element | None:
    for child in element:
        if _local_name(child.tag) == local:
            return child
    return None


def _read_rels(archive: zipfile.ZipFile, part: str) -> list[ElementTree.Element]:
    """Return relationship elements for one package part, if present."""

    rels_path = posixpath.join(
        posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels'
    )
    try:
        data = archive.read(rels_path)
    except KeyError:
        return []
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return []
    return [child for child in root if _local_name(child.tag) == 'Relationship']


def _resolve_part(base: str, target: str) -> str:
    """Resolve a package-relative relationship target against ``base``."""

    if target.startswith('/'):
        return target.lstrip('/')
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), target))


def _resolve_slide_parts(archive: zipfile.ZipFile, warnings: list[str]) -> list[str]:
    """Return ordered slide part names, preferring the presentation sldId list."""

    slide_parts: list[str] = []
    try:
        presentation = ElementTree.fromstring(archive.read('ppt/presentation.xml'))
    except (KeyError, ElementTree.ParseError):
        presentation = None

    rels = _read_rels(archive, 'ppt/presentation.xml')
    rel_map = {rel.get('Id'): rel.get('Target') for rel in rels if rel.get('Id')}

    if presentation is not None:
        sld_id_list = _find_child(presentation, 'sldIdLst')
        ordered = []
        if sld_id_list is not None:
            ordered = [
                child.get(_R_ID)
                for child in sld_id_list
                if _local_name(child.tag) == 'sldId' and child.get(_R_ID)
            ]
        for rel_id in ordered:
            target = rel_map.get(rel_id)
            if target:
                slide_parts.append(_resolve_part('ppt/presentation.xml', target))
        if slide_parts:
            return slide_parts

    names = [
        name
        for name in archive.namelist()
        if name.startswith('ppt/slides/slide')
        and name.endswith('.xml')
        and '/_rels/' not in name
    ]
    names.sort(key=_slide_sort_key)
    if not names:
        warnings.append('no slide parts found in pptx')
    return names


def _shape_text_runs(shape: ElementTree.Element) -> list[str]:
    return [
        element.text or ''
        for element in shape.iter()
        if _local_name(element.tag) == 't'
    ]


def _shape_is_title(shape: ElementTree.Element) -> bool:
    return any(
        _local_name(element.tag) == 'ph'
        and element.get('type') in ('title', 'ctrTitle')
        for element in shape.iter()
    )


def _extract_notes(archive: zipfile.ZipFile, part: str) -> str | None:
    rels = _read_rels(archive, part)
    notes_target = None
    for rel in rels:
        if (rel.get('Type') or '').endswith('/notesSlide'):
            notes_target = rel.get('Target')
            break
    if not notes_target:
        return None
    notes_part = _resolve_part(part, notes_target)
    try:
        root = ElementTree.fromstring(archive.read(notes_part))
    except (KeyError, ElementTree.ParseError):
        return None
    runs = [
        element.text.strip()
        for element in root.iter()
        if _local_name(element.tag) == 't' and (element.text or '').strip()
    ]
    return '\n'.join(runs) or None


def _extract_image_refs(archive: zipfile.ZipFile, part: str) -> tuple[str, ...]:
    refs = []
    for rel in _read_rels(archive, part):
        if (rel.get('Type') or '').endswith('/image'):
            target = rel.get('Target')
            if target:
                refs.append(target)
    return tuple(refs)


def _parse_slide(
    archive: zipfile.ZipFile, part: str, rel: str, index: int
) -> SlideRecord:
    root = ElementTree.fromstring(archive.read(part))
    c_sld = _find_child(root, 'cSld')
    sp_tree = _find_child(c_sld, 'spTree') if c_sld is not None else None
    shapes = (
        [child for child in sp_tree if _local_name(child.tag) == 'sp']
        if sp_tree is not None
        else []
    )

    title: str | None = None
    text_boxes: list[tuple[str, ...]] = []
    text_runs: list[str] = []
    labels: list[str] = []

    for shape in shapes:
        runs = _shape_text_runs(shape)
        if _shape_is_title(shape):
            if title is None:
                title = _normalize_text(''.join(runs))
        elif runs:
            text_boxes.append(tuple(runs))
            text_runs.extend(runs)
            for run in runs:
                cleaned = run.strip()
                if cleaned and cleaned not in labels:
                    labels.append(cleaned)

    return SlideRecord(
        deck_relative_path=rel,
        slide_index=index,
        title=title,
        text_boxes=tuple(text_boxes),
        text_runs=tuple(text_runs),
        labels=tuple(labels),
        notes=_extract_notes(archive, part),
        image_refs=_extract_image_refs(archive, part),
    )


def _extract_pptx(path: Path, rel: str) -> tuple[tuple[SlideRecord, ...], list[str]]:
    """Extract deterministic slide records from a PPTX package."""

    warnings: list[str] = []
    slides: list[SlideRecord] = []
    try:
        with zipfile.ZipFile(path) as archive:
            slide_parts = _resolve_slide_parts(archive, warnings)
            for index, part in enumerate(slide_parts, start=1):
                try:
                    slides.append(_parse_slide(archive, part, rel, index))
                except KeyError as error:
                    warnings.append(f'missing slide part {part} in {rel}: {error}')
                except ElementTree.ParseError as error:
                    warnings.append(f'xml parse error in {part} of {rel}: {error}')
    except zipfile.BadZipFile as error:
        warnings.append(f'cannot parse pptx (invalid zip): {rel}: {error}')
    except (RuntimeError, NotImplementedError):
        warnings.append(f'cannot parse pptx package: {rel}')
    except OSError:
        warnings.append(f'cannot read pptx: {rel}')
    return tuple(slides), warnings


@dataclass(frozen=True)
class UnresolvedFolder:
    """A folder that could not be conservatively resolved to a device ID."""

    folder_name: str
    reason: str
    candidate_device_id: str | None = None


@dataclass(frozen=True)
class HumanDeviceIdentityDecision:
    """A reviewed resolution for one exact unresolved folder."""

    relative_folder: str
    maker_namespace: str
    local_device_id: str
    display_label: str
    provenance_source: str
    aliases: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.relative_folder, str) or not self.relative_folder:
            raise ValueError('relative_folder must be a non-empty string')
        if (
            '/' in self.relative_folder
            or '\\' in self.relative_folder
            or self.relative_folder in {'.', '..'}
        ):
            raise ValueError('relative_folder must identify one canonical folder')
        if not isinstance(self.maker_namespace, str) or not self.maker_namespace:
            raise ValueError('maker_namespace must be a non-empty string')
        if not isinstance(self.local_device_id, str) or not self.local_device_id:
            raise ValueError('local_device_id must be a non-empty string')
        if not isinstance(self.display_label, str) or not self.display_label:
            raise ValueError('display_label must be a non-empty string')
        if not isinstance(self.provenance_source, str) or not self.provenance_source:
            raise ValueError('provenance_source must be a non-empty string')
        aliases = tuple(self.aliases)
        if any(not isinstance(item, str) or not item for item in aliases):
            raise ValueError('aliases must contain non-empty strings')
        evidence = tuple(self.evidence)
        if any(not isinstance(item, str) or not item for item in evidence):
            raise ValueError('evidence must contain strings')
        object.__setattr__(self, 'aliases', aliases)
        object.__setattr__(self, 'evidence', evidence)


@dataclass(frozen=True)
class SlideRecord:
    """Deterministic structural extraction for one PPTX slide."""

    deck_relative_path: str
    slide_index: int
    title: str | None = None
    text_boxes: tuple[tuple[str, ...], ...] = ()
    text_runs: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    notes: str | None = None
    image_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeviceScanResult:
    """Immutable, catalog-mergeable result of one device folder scan."""

    devices: tuple[Device, ...] = ()
    artifacts: tuple[Artifact, ...] = ()
    relationships: tuple[Relationship, ...] = ()
    unresolved_folders: tuple[UnresolvedFolder, ...] = ()
    slides: tuple[SlideRecord, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_snapshot(self) -> CatalogSnapshot:
        """Return a :class:`CatalogSnapshot` with no experiment records."""

        return CatalogSnapshot(
            experiments=(),
            devices=self.devices,
            artifacts=self.artifacts,
            relationships=self.relationships,
        )


def _build_device(  # noqa: PLR0913, PLR0917
    device_id: str,
    folder_names: list[str],
    warnings: list[str],
    maker_namespace: str | None = None,
    local_device_id: str | None = None,
    storage_source_id: str | None = None,
) -> Device:
    if len(folder_names) > 1:
        warnings.append(
            f'ambiguous device identity {device_id}: ' + ', '.join(folder_names)
        )

    aliases = tuple(sorted(set(folder_names)))
    claims: list[MetadataClaim] = []
    for folder_name in folder_names:
        parsed = _device_id_from_basename(folder_name)
        remainder = parsed[1] if parsed is not None else ''
        if remainder and remainder[0] not in ('_', ' ', '\t'):
            warnings.append(
                f'ambiguous compact device candidate {device_id}: {folder_name}'
            )
        for token in _folder_tokens(remainder):
            claims.append(
                MetadataClaim(
                    subject_type=SUBJECT_DEVICE,
                    subject_id=device_id,
                    field='folder_token',
                    value=token,
                    source_type='folder_name',
                    source_reference=folder_name,
                    extraction_method='folder_token',
                    confidence=0.5,
                    category='candidate',
                    evidence=(f'folder_name={folder_name}',),
                    review_status=REVIEW_UNKNOWN,
                )
            )
    if maker_namespace is not None:
        claims.append(
            MetadataClaim(
                subject_type=SUBJECT_DEVICE,
                subject_id=device_id,
                field='device_identity',
                value={
                    'namespace': maker_namespace,
                    'local_device_id': local_device_id or device_id,
                },
                source_type='scan_context',
                source_reference=storage_source_id,
                extraction_method='maker_namespace',
                confidence=1.0,
                category='candidate',
                evidence=tuple(f'folder_name={name}' for name in folder_names),
                review_status=REVIEW_UNKNOWN,
            )
        )
    return Device(
        device_id=device_id,
        device_type=UNKNOWN,
        aliases=aliases,
        review_state=REVIEW_UNKNOWN,
        metadata={},
        claims=tuple(claims),
        maker_namespace=maker_namespace,
        local_device_id=(local_device_id or device_id)
        if maker_namespace is not None
        else None,
        display_label=local_device_id or device_id,
    )


def _candidate_entries(
    root_path: Path, warnings: list[str]
) -> tuple[list[str], list[Path]]:
    """Return direct child folders and regular files without following links."""

    folder_names: list[str] = []
    root_files: list[Path] = []
    try:
        entries = list(os.scandir(root_path))
    except OSError:
        warnings.append('directory read error: .')
        return [], []

    for entry in sorted(entries, key=lambda item: item.name):
        path = root_path / entry.name
        relative = path.relative_to(root_path).as_posix()
        try:
            if path.is_symlink():
                warnings.append(f'symlink skipped: {relative}')
                continue
        except OSError:
            warnings.append(f'lstat error: {relative}')
            continue
        try:
            file_stat = path.stat()
        except OSError:
            warnings.append(f'stat error: {relative}')
            continue
        if stat.S_ISDIR(file_stat.st_mode):
            folder_names.append(entry.name)
        elif stat.S_ISREG(file_stat.st_mode):
            root_files.append(path)
    return folder_names, root_files


def _classify_folders(
    candidate_folders: list[str], warnings: list[str]
) -> tuple[dict[str, list[str]], list[UnresolvedFolder]]:
    recognized: dict[str, list[str]] = {}
    unresolved: list[UnresolvedFolder] = []
    for folder_name in candidate_folders:
        parsed = _device_id_from_basename(folder_name)
        if parsed is None:
            unresolved.append(
                UnresolvedFolder(
                    folder_name=folder_name,
                    reason=(
                        'basename does not begin with a standalone D followed by digits'
                    ),
                )
            )
            warnings.append(f'unresolved candidate folder: {folder_name}')
        else:
            recognized.setdefault(parsed[0], []).append(folder_name)

    for device_id in sorted(tuple(recognized)):
        folder_names = sorted(recognized[device_id])
        if len(folder_names) == 1:
            continue
        reason = (
            'ambiguous duplicate identity: multiple top-level folders resolve '
            f'to candidate device {device_id}'
        )
        warnings.append(
            f'ambiguous duplicate device identity {device_id}: '
            + ', '.join(folder_names)
        )
        unresolved.extend(
            UnresolvedFolder(
                folder_name=folder_name,
                reason=reason,
                candidate_device_id=device_id,
            )
            for folder_name in folder_names
        )
        del recognized[device_id]
    return recognized, unresolved


def _build_devices(
    recognized: dict[str, list[str]],
    warnings: list[str],
    maker_namespace: str | None = None,
    storage_source_id: str | None = None,
) -> tuple[Device, ...]:
    devices = []
    for device_id in sorted(recognized):
        internal_id = (
            deterministic_device_id(maker_namespace, device_id)
            if maker_namespace is not None
            else device_id
        )
        devices.append(
            _build_device(
                internal_id,
                sorted(recognized[device_id]),
                warnings,
                maker_namespace,
                device_id,
                storage_source_id,
            )
        )
    return tuple(devices)


def _iter_files(root: Path, folder: Path, warnings: list[str]):
    def onerror(error: OSError) -> None:
        failed_path = Path(error.filename) if error.filename else folder
        try:
            relative = failed_path.relative_to(root).as_posix()
        except ValueError:
            relative = folder.relative_to(root).as_posix()
        warnings.append(f'directory read error: {relative}')

    for dirpath, dirnames, filenames in os.walk(
        folder, followlinks=False, onerror=onerror
    ):
        current = Path(dirpath)
        retained_dirs = []
        for name in sorted(dirnames):
            path = current / name
            relative = path.relative_to(root).as_posix()
            try:
                is_symlink = path.is_symlink()
            except OSError:
                warnings.append(f'lstat error: {relative}')
                continue
            if is_symlink:
                warnings.append(f'symlink skipped: {relative}')
                continue
            retained_dirs.append(name)
        dirnames[:] = retained_dirs
        filenames.sort()
        for name in filenames:
            path = Path(dirpath) / name
            relative = path.relative_to(root).as_posix()
            try:
                is_symlink = path.is_symlink()
            except OSError:
                warnings.append(f'lstat error: {relative}')
                continue
            if is_symlink:
                warnings.append(f'symlink skipped: {relative}')
                continue
            yield path


def _inventory(  # noqa: PLR0913, PLR0915, PLR0917
    root_path: Path,
    candidate_folders: list[str],
    folder_device: dict[str, str],
    root_files: Sequence[Path],
    storage_source_id: str,
    extraction_allowlist: frozenset[str],
    warnings: list[str],
) -> tuple[list[Artifact], list[Artifact], list[SlideRecord], list[Relationship]]:
    artifacts: list[Artifact] = []
    slide_artifacts: list[Artifact] = []
    slide_records: list[SlideRecord] = []
    relationships: list[Relationship] = []

    entries = [(path, None) for path in root_files]
    entries.extend(
        (path, folder_device.get(folder_name))
        for folder_name in candidate_folders
        for path in _iter_files(root_path, root_path / folder_name, warnings)
    )

    for path, device_id in entries:
        rel = path.relative_to(root_path).as_posix()
        try:
            file_stat = path.stat()
        except OSError:
            warnings.append(f'stat error: {rel}')
            continue
        if not stat.S_ISREG(file_stat.st_mode):
            continue

        extension = _extension_of(path)
        media_type = _MEDIA_TYPES.get(extension, UNKNOWN)
        metadata: dict = {}
        if extension == 'ppt':
            metadata = {'deterministic_extraction': 'unsupported'}
            warnings.append(f'legacy PPT extraction unsupported: {rel}')

        artifact_id = _stable_id('art', rel)
        artifacts.append(
            Artifact(
                artifact_id=artifact_id,
                role=UNKNOWN,
                category=UNKNOWN,
                extension=extension,
                media_type=media_type,
                device_id=device_id,
                experiment_id=None,
                storage_reference=StorageReference(storage_source_id, rel),
                size_bytes=file_stat.st_size,
                mtime_ns=file_stat.st_mtime_ns,
                review_state=REVIEW_UNKNOWN,
                metadata=metadata,
                claims=(),
            )
        )

        if device_id is not None:
            relationships.append(
                Relationship(
                    source_type=SUBJECT_ARTIFACT,
                    source_id=artifact_id,
                    predicate='describes',
                    target_type=SUBJECT_DEVICE,
                    target_id=device_id,
                    provenance_source=rel,
                    review_state=REVIEW_UNKNOWN,
                )
            )

        if extension == 'pptx' and rel in extraction_allowlist:
            deck_slides, deck_warnings = _extract_pptx(path, rel)
            warnings.extend(deck_warnings)
            slide_records.extend(deck_slides)
            for slide in deck_slides:
                slide_id = _stable_id('slide', rel, f'{slide.slide_index:04d}')
                slide_artifacts.append(
                    Artifact(
                        artifact_id=slide_id,
                        role=UNKNOWN,
                        category='slide',
                        extension='pptx',
                        media_type=_MEDIA_TYPES['pptx'],
                        device_id=device_id,
                        experiment_id=None,
                        storage_reference=StorageReference(storage_source_id, rel),
                        size_bytes=None,
                        mtime_ns=None,
                        review_state=REVIEW_UNKNOWN,
                        metadata={
                            'slide_index': slide.slide_index,
                            'title': slide.title,
                            'text_runs': slide.text_runs,
                            'labels': slide.labels,
                            'notes': slide.notes,
                            'image_refs': slide.image_refs,
                        },
                        claims=(),
                    )
                )
                relationships.append(
                    Relationship(
                        source_type=SUBJECT_ARTIFACT,
                        source_id=slide_id,
                        predicate='part_of',
                        target_type=SUBJECT_ARTIFACT,
                        target_id=artifact_id,
                        provenance_source=rel,
                        review_state=REVIEW_UNKNOWN,
                    )
                )
                if device_id is not None:
                    relationships.append(
                        Relationship(
                            source_type=SUBJECT_ARTIFACT,
                            source_id=slide_id,
                            predicate='describes',
                            target_type=SUBJECT_DEVICE,
                            target_id=device_id,
                            provenance_source=rel,
                            review_state=REVIEW_UNKNOWN,
                        )
                    )

    return artifacts, slide_artifacts, slide_records, relationships


def scan_device_folders(
    root: str | Path,
    storage_source_id: str,
    *,
    pptx_extraction_allowlist: Sequence[str] | None = None,
    maker_namespace: str | None = None,
) -> DeviceScanResult:
    """Scan ``root`` read-only and return a catalog-mergeable device result."""

    root_path = Path(root)
    if not root_path.is_dir():
        raise ValueError(f'scan root must be a directory: {root}')
    if not isinstance(storage_source_id, str) or not storage_source_id:
        raise ValueError('storage_source_id must be a non-empty string')
    if maker_namespace is not None and (
        not isinstance(maker_namespace, str) or not maker_namespace
    ):
        raise ValueError('maker_namespace must be a non-empty string or None')
    if isinstance(pptx_extraction_allowlist, (str, bytes)):
        raise TypeError('pptx_extraction_allowlist must be a sequence of paths')
    extraction_allowlist = frozenset(
        _canonical_relative_path(item) for item in (pptx_extraction_allowlist or ())
    )

    warnings: list[str] = []
    candidate_folders, root_files = _candidate_entries(root_path, warnings)
    recognized, unresolved = _classify_folders(candidate_folders, warnings)
    folder_device = {
        folder_name: (
            deterministic_device_id(maker_namespace, device_id)
            if maker_namespace is not None
            else device_id
        )
        for device_id, names in recognized.items()
        for folder_name in names
    }
    devices = _build_devices(recognized, warnings, maker_namespace, storage_source_id)
    artifacts, slide_artifacts, slide_records, relationships = _inventory(
        root_path,
        candidate_folders,
        folder_device,
        root_files,
        storage_source_id,
        extraction_allowlist,
        warnings,
    )

    artifacts.sort(key=lambda item: item.storage_reference.relative_path)
    slide_artifacts.sort(
        key=lambda item: (
            item.storage_reference.relative_path,
            item.metadata['slide_index'],
        )
    )
    unresolved.sort(key=lambda item: item.folder_name)
    relationships.sort(key=lambda item: item.relationship_id)

    return DeviceScanResult(
        devices=devices,
        artifacts=tuple(artifacts) + tuple(slide_artifacts),
        relationships=tuple(relationships),
        unresolved_folders=tuple(unresolved),
        slides=tuple(slide_records),
        warnings=tuple(sorted(set(warnings))),
    )


def apply_device_identity_decisions(  # noqa: PLR0912, PLR0915
    snapshot: CatalogSnapshot | DeviceScanResult,
    scan_result: DeviceScanResult | Sequence[HumanDeviceIdentityDecision],
    decisions: Sequence[HumanDeviceIdentityDecision] | None = None,
) -> CatalogSnapshot | DeviceScanResult:
    """Apply exact human resolutions to a scan result and return a new snapshot."""

    return_scan_result = decisions is None and isinstance(snapshot, DeviceScanResult)
    if return_scan_result:
        original_scan = snapshot
        decisions = scan_result  # type: ignore[assignment]
        snapshot = original_scan.to_snapshot()
        scan_result = original_scan
    if not isinstance(snapshot, CatalogSnapshot) or not isinstance(
        scan_result, DeviceScanResult
    ):
        raise TypeError('snapshot and scan_result must use catalog scanner types')
    decisions = tuple(decisions or ())
    unresolved = {item.folder_name: item for item in scan_result.unresolved_folders}
    if len({item.relative_folder for item in decisions}) != len(decisions):
        raise ValueError('duplicate identity decisions are not allowed')
    for decision in decisions:
        if decision.relative_folder not in unresolved:
            raise ValueError(f'unknown unresolved folder: {decision.relative_folder}')

    devices = list(snapshot.devices)
    known_devices = {device.device_id for device in devices}
    for device in scan_result.devices:
        if device.device_id not in known_devices:
            devices.append(device)
            known_devices.add(device.device_id)
    artifacts = list(snapshot.artifacts)
    relationships = list(snapshot.relationships)
    known_artifacts = {artifact.artifact_id for artifact in artifacts}
    for artifact in scan_result.artifacts:
        if artifact.artifact_id not in known_artifacts:
            artifacts.append(artifact)
            known_artifacts.add(artifact.artifact_id)
    known_relationships = {edge.relationship_id for edge in relationships}
    for edge in scan_result.relationships:
        if edge.relationship_id not in known_relationships:
            relationships.append(edge)
            known_relationships.add(edge.relationship_id)
    by_pair = {
        (device.maker_namespace, device.local_device_id): device
        for device in devices
        if device.maker_namespace is not None
    }
    by_id = {device.device_id: device for device in devices}
    target_map: dict[str, str] = {}
    for decision in decisions:
        pair = (decision.maker_namespace, decision.local_device_id)
        target = by_pair.get(pair)
        internal_id = (
            target.device_id if target is not None else deterministic_device_id(*pair)
        )
        existing = by_id.get(internal_id)
        if existing is not None and target is None:
            if (
                existing.maker_namespace is None
                and existing.local_device_id is None
                and decision.maker_namespace == 'YZ'
                and deterministic_device_id(*pair) == existing.device_id
            ):
                target = replace(
                    existing,
                    maker_namespace=decision.maker_namespace,
                    local_device_id=decision.local_device_id,
                    display_label=decision.display_label,
                )
                devices[devices.index(existing)] = target
                by_id[internal_id] = target
            elif (existing.maker_namespace, existing.local_device_id) != pair:
                raise ValueError('identity/internal ID collision')
            else:
                target = existing
        if target is None:
            target = Device(
                device_id=internal_id,
                maker_namespace=decision.maker_namespace,
                local_device_id=decision.local_device_id,
                display_label=decision.display_label,
            )
            devices.append(target)
            by_id[internal_id] = target
            by_pair[pair] = target
        elif target.device_id != internal_id and target.device_id in by_id:
            internal_id = target.device_id
        target_map[decision.relative_folder] = internal_id

        aliases = tuple(
            sorted(set(target.aliases + decision.aliases + (decision.relative_folder,)))
        )
        original = {
            'folder_name': decision.relative_folder,
            'candidate_device_id': unresolved[
                decision.relative_folder
            ].candidate_device_id,
            'reason': unresolved[decision.relative_folder].reason,
        }
        corrected = {
            'namespace': decision.maker_namespace,
            'local_device_id': decision.local_device_id,
            'display_label': decision.display_label,
            'aliases': decision.aliases,
            'evidence': decision.evidence,
        }
        claim = MetadataClaim(
            subject_type=SUBJECT_DEVICE,
            subject_id=internal_id,
            field='device_identity',
            value=original,
            source_type='human_review',
            source_reference=decision.provenance_source,
            extraction_method='human_decision',
            evidence=decision.evidence or (f'folder_name={decision.relative_folder}',),
            review_status='corrected',
            reviewed_value=corrected,
        )
        updated_claims = target.claims + (claim,)
        updated = replace(
            target,
            aliases=aliases,
            claims=updated_claims,
            display_label=decision.display_label,
        )
        target_index = next(
            index
            for index, item in enumerate(devices)
            if item.device_id == target.device_id
        )
        devices[target_index] = updated
        by_id[internal_id] = updated
        by_pair[pair] = updated

    # Rebind all descendants under each exact unresolved folder prefix.
    for index, artifact in enumerate(artifacts):
        reference = artifact.storage_reference
        if reference is None:
            continue
        for folder_name, target_id in target_map.items():
            if (
                reference.relative_path == folder_name
                or reference.relative_path.startswith(folder_name + '/')
            ):
                artifacts[index] = replace(artifact, device_id=target_id)
                if not any(
                    edge.source_type == SUBJECT_ARTIFACT
                    and edge.source_id == artifact.artifact_id
                    and edge.predicate == 'describes'
                    and edge.target_type == SUBJECT_DEVICE
                    and edge.target_id == target_id
                    for edge in relationships
                ):
                    relationships.append(
                        Relationship(
                            source_type=SUBJECT_ARTIFACT,
                            source_id=artifact.artifact_id,
                            predicate='describes',
                            target_type=SUBJECT_DEVICE,
                            target_id=target_id,
                            provenance_source=next(
                                item.provenance_source
                                for item in decisions
                                if target_map.get(item.relative_folder) == target_id
                            ),
                            review_state=REVIEW_ACCEPTED,
                        )
                    )
                break

    resolved = set(target_map)
    remaining_unresolved = tuple(
        item
        for item in scan_result.unresolved_folders
        if item.folder_name not in resolved
    )
    # Include scan entities while preserving caller-provided entities and order.
    resolved_snapshot = CatalogSnapshot(
        experiments=snapshot.experiments,
        devices=tuple(devices),
        artifacts=tuple(artifacts),
        relationships=tuple(relationships),
    )
    if return_scan_result:
        return DeviceScanResult(
            devices=resolved_snapshot.devices,
            artifacts=resolved_snapshot.artifacts,
            relationships=resolved_snapshot.relationships,
            unresolved_folders=remaining_unresolved,
            slides=scan_result.slides,
            warnings=scan_result.warnings,
        )
    return resolved_snapshot
