"""Deterministic, rebuildable filesystem previews for catalog artifacts.

The preview cache is deliberately independent of the canonical SQLite catalog.  It
contains only bounded, derived files and can be deleted and rebuilt at any time.
"""

# The compact parsers intentionally keep their bounded state machines local.
# ruff: noqa: PLR0911, PLR0912, PLR0915, PLR2004

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import struct
import tempfile
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lab_data.scientific_catalog import Artifact, CatalogStore
from lab_data.storage import StorageRoot

__all__ = [
    'ArtifactPreview',
    'ArtifactPreviewAsset',
    'build_artifact_preview',
    'build_artifact_preview_report',
    'discover_artifact_preview',
    'search_artifact_previews',
]

GENERATOR_VERSION = 'artifact-preview-1'
SCHEMA_VERSION = 1
POLICY_VERSION = 'bounded-1'


class _SecurityError(ValueError):
    """Unsafe preview source path; never downgraded to a content placeholder."""


MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_IMAGE_AXIS = 20_000
MAX_IMAGE_PIXELS = 50_000_000
MAX_TABLE_BYTES = 2 * 1024 * 1024
MAX_TABLE_ROWS = 200
MAX_TABLE_COLS = 50
MAX_CELL_CHARS = 512
MAX_PPTX_MEMBERS = 2_000
MAX_PPTX_UNCOMPRESSED = 256 * 1024 * 1024
MAX_PPTX_RATIO = 100
MAX_PPTX_XML = 4 * 1024 * 1024
MAX_PPTX_SLIDES = 200
MAX_PPTX_CHARS = 100_000
MAX_MANIFEST_BYTES = 1024 * 1024
PREVIEW_STATUSES = frozenset(
    {'ready', 'stale_catalog', 'too_large', 'malformed', 'unsupported', 'unavailable'}
)
PREVIEW_KINDS = frozenset({'image', 'table', 'slide', 'placeholder'})


@dataclass(frozen=True)
class ArtifactPreviewAsset:
    """One cache asset, with a path relative to the preview object directory."""

    path: str
    kind: str
    media_type: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class ArtifactPreview:
    """Validated preview metadata returned by build/discover."""

    artifact_id: str
    preview_id: str
    object_dir: Path
    manifest_path: Path
    assets: tuple[ArtifactPreviewAsset, ...]
    warnings: tuple[str, ...] = ()
    status: str = 'ok'
    fresh: bool = True
    search_text: str = ''
    kind: str = 'placeholder'
    source_freshness_checked: bool = True


def _json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        + '\n'
    ).encode('utf-8')


def _canonical_source(artifact: Artifact) -> tuple[str, str] | None:
    ref = artifact.storage_reference
    if ref is None:
        return None
    return ref.storage_source_id, ref.relative_path


def _preview_id(artifact: Artifact) -> str:
    source = _canonical_source(artifact)
    payload = {
        'generator': GENERATOR_VERSION,
        'schema_version': SCHEMA_VERSION,
        'policy_version': POLICY_VERSION,
        'artifact_id': artifact.artifact_id,
        'storage_source_id': source[0] if source else None,
        'relative_path': source[1] if source else None,
        'catalog_size_bytes': artifact.size_bytes,
        'catalog_mtime_ns': artifact.mtime_ns,
    }
    return hashlib.sha256(_json(payload)).hexdigest()


def _roots(storage_roots: Mapping[str, StorageRoot | Path]) -> dict[str, StorageRoot]:
    result: dict[str, StorageRoot] = {}
    for key, value in storage_roots.items():
        if not isinstance(key, str) or not key:
            raise ValueError('storage source IDs must be non-empty strings')
        root = value if isinstance(value, StorageRoot) else StorageRoot(Path(value))
        if root.root.is_symlink():
            raise ValueError('storage root must not be a symlink')
        result[key] = root
    return result


def _has_symlink_component(path: Path) -> bool:
    """Return whether any existing component of an absolute path is a symlink."""

    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            is_symlink = current.is_symlink()
        except OSError:
            # An unreadable cache component cannot be proven safe to traverse.
            return True
        if is_symlink:
            return True
    return False


def _resolve_source(artifact: Artifact, roots: Mapping[str, StorageRoot]) -> Path:
    ref = artifact.storage_reference
    if ref is None:
        raise FileNotFoundError('artifact has no storage reference')
    root = roots.get(ref.storage_source_id)
    if root is None:
        raise FileNotFoundError('storage source is not configured')
    path = root.resolve(ref.relative_path)
    # Reject symlinks in every path component, including the file itself.
    current = root.root
    for component in Path(ref.relative_path.replace('\\', '/')).parts:
        current = current / component
        if current.is_symlink():
            raise _SecurityError('storage source path must not contain symlinks')
    try:
        path.relative_to(root.root)
    except ValueError as error:
        raise _SecurityError('storage path escapes storage root') from error
    stat_result = path.stat()
    if not path.is_file() or not stat_result:
        raise ValueError('artifact source is not a regular file')
    return path


def _read_bounded(path: Path, limit: int) -> bytes:
    with path.open('rb') as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError('source exceeds bounded preview limit')
    return data


def _placeholder() -> bytes:
    return b'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="100%" height="100%" fill="#eee"/><text x="20" y="40" font-family="sans-serif" font-size="18">Preview unavailable</text></svg>\n'


def _image_dimensions(data: bytes, ext: str) -> tuple[int, int]:  # noqa: PLR0912, PLR0915, PLR2004
    ext = ext.lower().lstrip('.')
    if ext == 'png':
        if len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
            raise ValueError('malformed PNG')
        width, height = struct.unpack('>II', data[16:24])
        return width, height
    if ext in {'jpg', 'jpeg'}:
        if len(data) < 4 or data[:2] != b'\xff\xd8':
            raise ValueError('malformed JPEG')
        pos = 2
        while pos + 4 <= len(data):
            if data[pos] != 0xFF:
                pos += 1
                continue
            marker = data[pos + 1]
            pos += 2
            if marker in {0xD8, 0xD9}:
                continue
            if pos + 2 > len(data):
                break
            length = struct.unpack('>H', data[pos : pos + 2])[0]
            if length < 2 or pos + length > len(data):
                break
            if marker in set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8)) | set(
                range(0xC9, 0xCC)
            ) | set(range(0xCD, 0xD0)):
                if length < 7:
                    break
                height, width = struct.unpack('>HH', data[pos + 3 : pos + 7])
                return width, height
            pos += length
        raise ValueError('malformed JPEG')
    if ext in {'tif', 'tiff'}:
        if len(data) < 8 or data[:2] not in {b'II', b'MM'}:
            raise ValueError('malformed TIFF')
        endian = '<' if data[:2] == b'II' else '>'
        if struct.unpack(endian + 'H', data[2:4])[0] != 42:
            raise ValueError('malformed TIFF')
        ifd = struct.unpack(endian + 'I', data[4:8])[0]
        if ifd + 2 > len(data):
            raise ValueError('malformed TIFF')
        count = struct.unpack(endian + 'H', data[ifd : ifd + 2])[0]
        width = height = None
        for index in range(count):
            off = ifd + 2 + index * 12
            if off + 12 > len(data):
                break
            tag, typ, n = struct.unpack(endian + 'HHI', data[off : off + 8])
            size = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8}.get(typ)
            if size is None or n == 0:
                continue
            raw = (
                data[off + 8 : off + 12]
                if size * n <= 4
                else data[struct.unpack(endian + 'I', data[off + 8 : off + 12])[0] :]
            )
            if len(raw) < size * n:
                continue
            if typ not in {3, 4}:
                continue
            value = struct.unpack(endian + ('H' if typ == 3 else 'I'), raw[:size])[0]
            if tag == 256:
                width = value
            elif tag == 257:
                height = value
        if width is None or height is None:
            raise ValueError('malformed TIFF')
        return width, height
    raise ValueError('unsupported image')


def _table(data: bytes, ext: str) -> tuple[dict[str, Any], str, str]:  # noqa: PLR0912, PLR0915, PLR2004
    text = data.decode('utf-8-sig', errors='replace')
    sample = text[:8192]
    counts = {delimiter: sample.count(delimiter) for delimiter in (',', '\t', ';')}
    if max(counts.values()) == 0:
        delimiter = None
    else:
        delimiter = max(
            (',', '\t', ';'), key=lambda item: (counts[item], -(',\t;'.index(item)))
        )
    if delimiter is None:
        rows = [line.split() for line in text.splitlines()]
    else:
        try:
            rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        except csv.Error as error:
            raise ValueError('malformed table') from error
    rows = rows[: MAX_TABLE_ROWS + 1]
    if any(len(cell) > MAX_CELL_CHARS for row in rows for cell in row):
        raise ValueError('table cell exceeds bounded preview limit')
    rows = [[cell[:MAX_CELL_CHARS] for cell in row[:MAX_TABLE_COLS]] for row in rows]
    if not rows:
        raise ValueError('empty table')
    headers = rows[0]
    body = rows[1:]
    table = {'delimiter': delimiter or 'whitespace', 'headers': headers, 'rows': body}
    numeric_cols: list[int] = []
    for col in range(min(len(headers), MAX_TABLE_COLS)):
        values = []
        for row in body:
            if col < len(row):
                try:
                    values.append(float(row[col]))
                except ValueError:
                    pass
        if values:
            numeric_cols.append(col)
    if len(numeric_cols) >= 2:
        x_col, y_col = numeric_cols[:2]
    elif numeric_cols:
        x_col, y_col = -1, numeric_cols[0]
    else:
        x_col = y_col = None
    if y_col is None:
        plot = '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><text x="20" y="30">No numeric data</text></svg>\n'
    else:
        points: list[str] = []
        vals: list[tuple[float, float]] = []
        for idx, row in enumerate(body):
            try:
                x = float(idx + 1) if x_col == -1 else float(row[x_col])
                y = float(row[y_col])
            except (ValueError, IndexError):
                continue
            vals.append((x, y))
        if vals:
            xmin, xmax = min(x for x, _ in vals), max(x for x, _ in vals)
            ymin, ymax = min(y for _, y in vals), max(y for _, y in vals)
            dx = xmax - xmin or 1.0
            dy = ymax - ymin or 1.0
            points = [
                f'{40 + 560 * (x - xmin) / dx:.3f},{320 - 280 * (y - ymin) / dy:.3f}'
                for x, y in vals
            ]
        plot = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><polyline fill="none" stroke="#246" points="'
            + ' '.join(points)
            + '"/></svg>\n'
        )
    search = re.sub(
        r'\s+', ' ', ' '.join(headers + [cell for row in body for cell in row])
    ).strip()[:MAX_PPTX_CHARS]
    return table, plot, search


def _pptx(data: bytes, rel: str) -> tuple[list[tuple[str, bytes]], str]:
    from lab_data.device_scanner import _extract_pptx

    if not data.startswith(b'PK'):
        raise ValueError('malformed PPTX')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_PPTX_MEMBERS:
                raise ValueError('PPTX member count exceeds bounded preview limit')
            total = 0
            slide_count = 0
            for info in infos:
                total += info.file_size
                if total > MAX_PPTX_UNCOMPRESSED:
                    raise ValueError(
                        'PPTX uncompressed size exceeds bounded preview limit'
                    )
                if (
                    info.compress_size
                    and info.file_size / info.compress_size > MAX_PPTX_RATIO
                ):
                    raise ValueError(
                        'PPTX compression ratio exceeds bounded preview limit'
                    )
                if (
                    info.filename.lower().endswith('.xml')
                    and info.file_size > MAX_PPTX_XML
                ):
                    raise ValueError('PPTX XML member exceeds bounded preview limit')
                if info.filename.startswith(
                    'ppt/slides/slide'
                ) and info.filename.endswith('.xml'):
                    slide_count += 1
            if slide_count > MAX_PPTX_SLIDES:
                raise ValueError('PPTX slide count exceeds bounded preview limit')
    except zipfile.BadZipFile as error:
        raise ValueError('malformed PPTX') from error
    descriptor, temp_name = tempfile.mkstemp(suffix='.pptx')
    os.close(descriptor)
    try:
        temp_path = Path(temp_name)
        temp_path.write_bytes(data)
        slides, warnings = _extract_pptx(temp_path, rel)
    finally:
        Path(temp_name).unlink(missing_ok=True)
    if warnings or not slides:
        raise ValueError('malformed PPTX')
    assets: list[tuple[str, bytes]] = []
    chunks: list[str] = []
    for slide in slides[:MAX_PPTX_SLIDES]:
        text = ' '.join(filter(None, (slide.title, *slide.text_runs, slide.notes)))[
            :MAX_PPTX_CHARS
        ]
        chunks.append(text)
        escaped = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        assets.append(
            (
                f'slides/{slide.slide_index:04d}.svg',
                f'<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="576"><rect width="100%" height="100%" fill="white"/><text x="24" y="48" font-family="sans-serif" font-size="24">{escaped}</text></svg>\n'.encode(),
            )
        )
    return assets, re.sub(r'\s+', ' ', ' '.join(chunks)).strip()[:MAX_PPTX_CHARS]


def _build_assets(
    artifact: Artifact, data: bytes, rel: str
) -> tuple[list[tuple[str, str, str, bytes]], list[str], str]:
    ext = artifact.extension.lower().lstrip('.')
    warnings: list[str] = []
    if ext in {'png', 'jpg', 'jpeg', 'tif', 'tiff'}:
        try:
            width, height = _image_dimensions(data, ext)
        except struct.error as error:
            raise ValueError('malformed image') from error
        if (
            width <= 0
            or height <= 0
            or width > MAX_IMAGE_AXIS
            or height > MAX_IMAGE_AXIS
            or width * height > MAX_IMAGE_PIXELS
        ):
            raise ValueError('image dimensions exceed bounded preview limit')
        name = f'image.{ext}'
        media = (
            'image/jpeg'
            if ext in {'jpg', 'jpeg'}
            else ('image/tiff' if ext in {'tif', 'tiff'} else 'image/png')
        )
        return [(name, 'image', media, data)], warnings, ''
    if ext in {'csv', 'dat', 'tsv'}:
        table, plot, search = _table(data[:MAX_TABLE_BYTES], ext)
        table_data = _json(table)
        return (
            [
                ('table.json', 'table', 'application/json', table_data),
                ('plot.svg', 'plot', 'image/svg+xml', plot.encode()),
            ],
            warnings,
            search,
        )
    if ext == 'pptx':
        ppt_assets, search = _pptx(data, rel)
        result = [
            (name, 'slide', 'image/svg+xml', content) for name, content in ppt_assets
        ]
        result.append(
            ('search_text.txt', 'search', 'text/plain', search.encode('utf-8'))
        )
        return result, warnings, search
    raise ValueError('unsupported artifact type')


def _asset_from_file(
    path: Path, kind: str, media: str, rel: str
) -> ArtifactPreviewAsset:
    data = path.read_bytes()
    return ArtifactPreviewAsset(
        rel, kind, media, len(data), hashlib.sha256(data).hexdigest()
    )


def _preview_from_manifest(
    object_dir: Path,
    manifest: Mapping[str, Any],
    *,
    fresh: bool,
    source_freshness_checked: bool = True,
) -> ArtifactPreview | None:
    try:
        if manifest.get('generator') != GENERATOR_VERSION:
            return None
        if manifest.get('schema_version') != SCHEMA_VERSION:
            return None
        if manifest.get('policy_version') != POLICY_VERSION:
            return None
        artifact_id = manifest['artifact_id']
        preview_id = manifest['preview_id']
        assets = tuple(ArtifactPreviewAsset(**item) for item in manifest['assets'])
        warnings = tuple(sorted(str(item) for item in manifest.get('warnings', ())))
        status = str(manifest.get('status', 'ok'))
        search_text = str(manifest.get('search_text', ''))
        kind = str(manifest.get('kind', 'placeholder'))
        if not isinstance(artifact_id, str) or not isinstance(preview_id, str):
            return None
        if status not in PREVIEW_STATUSES or kind not in PREVIEW_KINDS:
            return None
        if len(search_text) > MAX_PPTX_CHARS:
            return None
        for asset in assets:
            if Path(asset.path).is_absolute() or '..' in Path(asset.path).parts:
                return None
            if _has_symlink_component(object_dir / asset.path):
                return None
            candidate = (object_dir / asset.path).resolve()
            candidate.relative_to(object_dir.resolve())
            if (
                not candidate.is_file()
                or _asset_from_file(candidate, asset.kind, asset.media_type, asset.path)
                != asset
            ):
                return None
        return ArtifactPreview(
            artifact_id,
            preview_id,
            object_dir,
            object_dir / 'manifest.json',
            assets,
            warnings,
            status,
            fresh,
            search_text,
            kind,
            source_freshness_checked,
        )
    except (KeyError, TypeError, ValueError, OSError):
        return None


def _read_manifest(object_dir: Path) -> Mapping[str, Any] | None:
    """Read one bounded, regular manifest confined to its preview object."""

    manifest_path = object_dir / 'manifest.json'
    try:
        if manifest_path.is_symlink() or not manifest_path.is_file():
            return None
        resolved = manifest_path.resolve()
        resolved.relative_to(object_dir.resolve())
        if resolved.stat().st_size > MAX_MANIFEST_BYTES:
            return None
        with resolved.open('rb') as handle:
            data = handle.read(MAX_MANIFEST_BYTES + 1)
        if len(data) > MAX_MANIFEST_BYTES:
            return None
        value = json.loads(data.decode('utf-8'))
        return value if isinstance(value, Mapping) else None
    except (OSError, ValueError, UnicodeError):
        return None


def build_artifact_preview(
    store: CatalogStore,
    artifact_id: str,
    *,
    storage_roots: Mapping[str, StorageRoot | Path],
    preview_root: Path,
) -> ArtifactPreview:  # noqa: PLR0912, PLR0915
    """Build and atomically publish one deterministic artifact preview."""
    preview_root = Path(preview_root)
    if not preview_root.is_absolute():
        raise ValueError('preview_root must be absolute')
    if _has_symlink_component(preview_root):
        raise ValueError('preview cache path must not contain symlinks')
    artifact = store.get_artifact(artifact_id)
    if artifact is None:
        raise KeyError(artifact_id)
    roots = _roots(storage_roots)
    preview_id = _preview_id(artifact)
    object_dir = preview_root / 'v1' / 'objects' / preview_id[:2] / preview_id
    object_dir.parent.mkdir(parents=True, exist_ok=True)
    if _has_symlink_component(object_dir):
        raise ValueError('preview cache path must not contain symlinks')
    warnings: list[str] = []
    status = 'ready'
    kind = 'placeholder'
    fresh = True
    search_text = ''
    source = _canonical_source(artifact)
    source_meta = {
        'storage_source_id': source[0] if source else None,
        'relative_path': source[1] if source else None,
        'size_bytes': artifact.size_bytes,
        'mtime_ns': artifact.mtime_ns,
    }
    try:
        path = _resolve_source(artifact, roots)
        before = path.stat()
        if before.st_size > MAX_SOURCE_BYTES:
            raise ValueError('source exceeds 64MiB cap')
        data = _read_bounded(path, MAX_SOURCE_BYTES)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('source changed while reading')
        if artifact.size_bytes is not None and before.st_size != artifact.size_bytes:
            raise ValueError('source size differs from catalog')
        if artifact.mtime_ns is not None and before.st_mtime_ns != artifact.mtime_ns:
            raise ValueError('source mtime differs from catalog')
        built, _, search = _build_assets(artifact, data, source[1] if source else '')
        search_text = search
        kind = (
            'table'
            if artifact.extension.lower().lstrip('.') in {'csv', 'dat', 'tsv'}
            else (
                'slide' if artifact.extension.lower().lstrip('.') == 'pptx' else 'image'
            )
        )
        if search and not any(name == 'search_text.txt' for name, *_ in built):
            built.append(
                ('search_text.txt', 'search', 'text/plain', search.encode('utf-8'))
            )
    except _SecurityError:
        raise
    except (FileNotFoundError, PermissionError, OSError, ValueError) as error:
        status = (
            'unavailable'
            if isinstance(error, (FileNotFoundError, PermissionError))
            else 'malformed'
        )
        message = str(error)
        if ('exceeds' in message and 'table cell' not in message) or '64MiB' in message:
            status = 'too_large'
        elif 'unsupported' in message:
            status = 'unsupported'
        if isinstance(error, (FileNotFoundError, PermissionError)) or str(error) in {
            'source size differs from catalog',
            'source mtime differs from catalog',
        }:
            fresh = False
        if str(error) in {
            'source size differs from catalog',
            'source mtime differs from catalog',
        }:
            status = 'stale_catalog'
        warnings.append('preview unavailable: ' + type(error).__name__)
        built = [('placeholder.svg', 'placeholder', 'image/svg+xml', _placeholder())]
    temp = Path(tempfile.mkdtemp(prefix=f'.{preview_id}.', dir=str(object_dir.parent)))
    try:
        assets: list[ArtifactPreviewAsset] = []
        for name, asset_kind, media, content in sorted(built, key=lambda item: item[0]):
            target = temp / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            assets.append(
                ArtifactPreviewAsset(
                    name,
                    asset_kind,
                    media,
                    len(content),
                    hashlib.sha256(content).hexdigest(),
                )
            )
        manifest = {
            'artifact_id': artifact.artifact_id,
            'generator': GENERATOR_VERSION,
            'schema_version': SCHEMA_VERSION,
            'policy_version': POLICY_VERSION,
            'preview_id': preview_id,
            'source': source_meta,
            'status': status,
            'kind': kind,
            'search_text': search_text,
            'warnings': sorted(warnings),
            'assets': [asset.__dict__ for asset in assets],
        }
        (temp / 'manifest.json').write_bytes(_json(manifest))
        backup = object_dir.with_name(f'.{preview_id}.old')
        if backup.exists():
            shutil.rmtree(backup)
        if object_dir.exists():
            os.replace(object_dir, backup)
        try:
            os.replace(temp, object_dir)
        except BaseException:
            if backup.exists() and not object_dir.exists():
                os.replace(backup, object_dir)
            raise
        finally:
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
    finally:
        if temp.exists():
            shutil.rmtree(temp, ignore_errors=True)
    result = _preview_from_manifest(object_dir, manifest, fresh=fresh)
    if result is None:
        raise OSError('published preview manifest failed validation')
    return result


def discover_artifact_preview(
    store: CatalogStore,
    artifact_id: str,
    *,
    storage_roots: Mapping[str, StorageRoot | Path],
    preview_root: Path,
) -> ArtifactPreview | None:
    """Discover and validate an existing cache object; return ``None`` if absent/invalid."""
    preview_root = Path(preview_root)
    if not preview_root.is_absolute() or _has_symlink_component(preview_root):
        return None
    artifact = store.get_artifact(artifact_id)
    if artifact is None:
        return None
    preview_id = _preview_id(artifact)
    object_dir = preview_root / 'v1' / 'objects' / preview_id[:2] / preview_id
    if _has_symlink_component(object_dir):
        return None
    manifest = _read_manifest(object_dir)
    if manifest is None:
        return None
    if (
        manifest.get('preview_id') != preview_id
        or manifest.get('artifact_id') != artifact_id
    ):
        return None
    fresh = True
    try:
        roots = _roots(storage_roots)
        source = _resolve_source(artifact, roots)
        current = source.stat()
        if artifact.size_bytes is not None and current.st_size != artifact.size_bytes:
            fresh = False
        if artifact.mtime_ns is not None and current.st_mtime_ns != artifact.mtime_ns:
            fresh = False
    except (FileNotFoundError, PermissionError, OSError, ValueError, _SecurityError):
        fresh = False
    result = _preview_from_manifest(object_dir, manifest, fresh=fresh)
    if result is not None and not fresh:
        return ArtifactPreview(
            result.artifact_id,
            result.preview_id,
            result.object_dir,
            result.manifest_path,
            result.assets,
            result.warnings,
            'stale_catalog',
            False,
            result.search_text,
            result.kind,
            True,
        )
    return result


def _cached_preview(
    store: CatalogStore,
    artifact_id: str,
    preview_root: Path,
) -> ArtifactPreview | None:
    """Return one cache-valid preview without touching its source storage."""

    artifact = store.get_artifact(artifact_id)
    if artifact is None:
        return None
    preview_id = _preview_id(artifact)
    object_dir = preview_root / 'v1' / 'objects' / preview_id[:2] / preview_id
    if _has_symlink_component(object_dir):
        return None
    manifest = _read_manifest(object_dir)
    if manifest is None:
        return None
    if (
        manifest.get('preview_id') != preview_id
        or manifest.get('artifact_id') != artifact_id
    ):
        return None
    return _preview_from_manifest(
        object_dir,
        manifest,
        fresh=False,
        source_freshness_checked=False,
    )


def _literal_filter(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be a non-empty string or None')
    return re.sub(r'\s+', ' ', value).strip().casefold()


def search_artifact_previews(  # noqa: PLR0913
    store: CatalogStore,
    artifact_ids: Iterable[str],
    *,
    preview_root: Path,
    status: str | None = None,
    kind: str | None = None,
    text: str | None = None,
) -> tuple[ArtifactPreview, ...]:
    """Search existing cache manifests without reading or statting source files.

    Results are ordered by artifact ID and validate every cached asset.  Their
    ``source_freshness_checked`` flag is false because this cache-only operation
    deliberately does not consult source storage.
    """

    if isinstance(artifact_ids, (str, bytes)):
        raise TypeError('artifact_ids must be an iterable of artifact ID strings')
    try:
        ids = tuple(artifact_ids)
    except TypeError as error:
        raise TypeError('artifact_ids must be iterable') from error
    if any(not isinstance(item, str) or not item.strip() for item in ids):
        raise ValueError('artifact_ids must contain non-empty strings')

    preview_root = Path(preview_root)
    if not preview_root.is_absolute():
        raise ValueError('preview_root must be absolute')
    if _has_symlink_component(preview_root):
        raise ValueError('preview cache path must not contain symlinks')

    status_filter = _literal_filter(status, 'status')
    kind_filter = _literal_filter(kind, 'kind')
    text_filter = _literal_filter(text, 'text')
    results: list[ArtifactPreview] = []
    for artifact_id in sorted(set(ids)):
        preview = _cached_preview(store, artifact_id, preview_root)
        if preview is None:
            continue
        if status_filter is not None and preview.status.casefold() != status_filter:
            continue
        if kind_filter is not None and preview.kind.casefold() != kind_filter:
            continue
        searchable = re.sub(r'\s+', ' ', preview.search_text).strip().casefold()
        if text_filter is not None and text_filter not in searchable:
            continue
        results.append(preview)
    return tuple(results)


def build_artifact_preview_report(  # noqa: PLR0913
    store: CatalogStore,
    artifact_ids: Iterable[str],
    *,
    preview_root: Path,
    status: str | None = None,
    kind: str | None = None,
    text: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Return a JSON-safe report for explicit, cache-only artifact IDs.

    This is a presentation adapter over :func:`search_artifact_previews`.  It
    validates only existing preview objects, never reads source storage, and
    omits absent or invalid IDs just as the underlying search does.  Every
    returned path is relative to the preview object; cache-internal absolute
    paths are deliberately not exposed.
    """

    previews = search_artifact_previews(
        store,
        artifact_ids,
        preview_root=preview_root,
        status=status,
        kind=kind,
        text=text,
    )
    query = text
    return tuple(
        {
            'artifact_id': item.artifact_id,
            'preview_id': item.preview_id,
            'status': item.status,
            'kind': item.kind,
            'fresh': item.fresh,
            'source_freshness_checked': item.source_freshness_checked,
            'assets': [
                {
                    'path': asset.path,
                    'kind': asset.kind,
                    'media_type': asset.media_type,
                    'size_bytes': asset.size_bytes,
                    'sha256': asset.sha256,
                }
                for asset in item.assets
            ],
            'warnings': list(item.warnings),
            'search_match': {
                'query': query,
                'matched': None if query is None else True,
                'text_available': bool(item.search_text),
            },
        }
        for item in previews
    )
