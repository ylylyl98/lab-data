"""Build a small, truthful local catalog and preview cache for smoke testing.

This script writes only under ``C:\\CodexRepos\\lab-data\\.smoke`` (or the path
given as the first CLI argument).  It never touches ``C:\\NOMAD_Test`` or any
existing data.  The catalog, preview cache, and source files are all rebuilt
from scratch on every run.
"""

from __future__ import annotations

import struct
import sys
import zipfile
from pathlib import Path

from lab_data.scientific_catalog import (
    Artifact,
    CatalogSnapshot,
    Device,
    Experiment,
    SQLiteCatalogStore,
    StorageReference,
)


_P_NS = 'http://schemas.openxmlformats.org/presentationml/2006/main'
_A_NS = 'http://schemas.openxmlformats.org/drawingml/2006/main'
_R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def _minimal_png(path: Path) -> None:
    """Write a small valid 1x1 RGBA PNG using only the standard library."""

    import zlib

    def chunk(kind: bytes, payload: bytes) -> bytes:
        import binascii

        checksum = binascii.crc32(kind + payload) & 0xFFFFFFFF
        return (
            struct.pack('>I', len(payload))
            + kind
            + payload
            + struct.pack('>I', checksum)
        )

    ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0)
    raw = b'\x00' + b'\x40\x40\x40\x40'
    idat = zlib.compress(raw)
    path.write_bytes(
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', ihdr)
        + chunk(b'IDAT', idat)
        + chunk(b'IEND', b'')
    )


def _minimal_pptx(path: Path) -> None:
    """Write a valid minimal PPTX deck with one titled, text-bearing slide."""

    presentation = (
        f'<p:presentation xmlns:p="{_P_NS}" xmlns:r="{_R_NS}">'
        '<p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst>'
        '</p:presentation>'
    )
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{_R_NS}/slide" Target="slides/slide1.xml"/>'
        '</Relationships>'
    )
    slide = (
        f'<p:sld xmlns:p="{_P_NS}" xmlns:a="{_A_NS}">'
        '<p:cSld><p:spTree>'
        '<p:sp><p:nvSpPr><p:cNvPr id="1" name="Title"/><p:cNvSpPr/>'
        '<p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr><p:spPr/>'
        '<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>'
        'Device D356 measurement deck'
        '</a:t></a:r></a:p></p:txBody></p:sp>'
        '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Body"/><p:cNvSpPr/>'
        '<p:nvPr/></p:nvSpPr><p:spPr/>'
        '<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>'
        'Optical characterization summary'
        '</a:t></a:r></a:p></p:txBody></p:sp>'
        '</p:spTree></p:cSld></p:sld>'
    )
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('ppt/presentation.xml', presentation)
        archive.writestr('ppt/_rels/presentation.xml.rels', rels)
        archive.writestr('ppt/slides/slide1.xml', slide)


def _write_source_files(source_root: Path) -> None:
    source_root.mkdir(parents=True, exist_ok=True)
    (source_root / 'D356').mkdir(exist_ok=True)
    (source_root / 'YZ247-0432').mkdir(exist_ok=True)

    _minimal_png(source_root / 'D356' / 'figure.png')
    _minimal_png(source_root / 'YZ247-0432' / 'figure.png')
    (source_root / 'D356' / 'table.csv').write_text(
        'wavelength_nm,intensity\n532,0.42\n633,0.71\n785,0.18\n', encoding='utf-8'
    )
    (source_root / 'D356' / 'table.dat').write_text(
        'time_s\tsignal\n0.0\t1.2\n1.0\t1.5\n2.0\t1.1\n', encoding='utf-8'
    )
    _minimal_pptx(source_root / 'D356' / 'deck.pptx')
    (source_root / 'D356' / 'raw-YZ247-0432.dat').write_text(
        'gate_V\tcurrent_A\n-1.0\t0.1\n0.0\t0.3\n1.0\t0.6\n', encoding='utf-8'
    )


def _artifact(
    artifact_id: str,
    *,
    source_root: Path,
    relative_path: str,
    extension: str,
    media_type: str,
    role: str = 'raw',
    category: str = 'unknown',
    device_id: str | None = None,
    experiment_id: str | None = None,
) -> Artifact:
    stat = (source_root / relative_path).stat()
    return Artifact(
        artifact_id,
        role=role,
        category=category,
        extension=extension,
        media_type=media_type,
        device_id=device_id,
        experiment_id=experiment_id,
        storage_reference=StorageReference('source', relative_path),
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )


def main() -> None:
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('.smoke')
    base = base.resolve()
    source_root = base / 'source'
    catalog_path = base / 'catalog' / 'catalog.db'
    preview_root = base / 'preview'
    catalog_path.parent.mkdir(parents=True, exist_ok=True)

    _write_source_files(source_root)

    devices = (
        Device(
            'D356',
            device_type='spectrometer',
            aliases=('YZ-D356',),
            display_label='D356 Spectrometer',
            metadata={'manufacturer': 'YZ Optics', 'status': 'active'},
        ),
        Device(
            'D357',
            device_type='cryostat',
            aliases=(),
            display_label='D357 Cryostat',
            metadata={'manufacturer': 'YZ Cryo', 'status': 'standby'},
        ),
    )
    experiments = (
        Experiment(
            'YZ247-0432',
            metadata={
                'sample_id': 'YZ247-0432',
                'measurement_type': 'transport',
                'temperature_K': 4.2,
            },
            files_by_role={
                'raw': (StorageReference('source', 'D356/raw-YZ247-0432.dat'),)
            },
            confidence=0.82,
            needs_review=False,
        ),
    )
    artifacts = (
        _artifact(
            'img-D356-png',
            source_root=source_root,
            relative_path='D356/figure.png',
            extension='png',
            media_type='image/png',
            role='figure',
            category='image',
            device_id='D356',
        ),
        _artifact(
            'table-D356-csv',
            source_root=source_root,
            relative_path='D356/table.csv',
            extension='csv',
            media_type='text/csv',
            role='raw',
            category='table',
            device_id='D356',
        ),
        _artifact(
            'table-D356-dat',
            source_root=source_root,
            relative_path='D356/table.dat',
            extension='dat',
            media_type='text/plain',
            role='raw',
            category='table',
            device_id='D356',
        ),
        _artifact(
            'deck-D356-pptx',
            source_root=source_root,
            relative_path='D356/deck.pptx',
            extension='pptx',
            media_type=(
                'application/vnd.openxmlformats-officedocument.'
                'presentationml.presentation'
            ),
            role='document',
            category='document',
            device_id='D356',
        ),
        _artifact(
            'img-YZ247-0432-png',
            source_root=source_root,
            relative_path='YZ247-0432/figure.png',
            extension='png',
            media_type='image/png',
            role='figure',
            category='image',
            experiment_id='YZ247-0432',
        ),
    )

    store = SQLiteCatalogStore(catalog_path)
    store.rebuild(
        CatalogSnapshot(
            experiments=experiments,
            devices=devices,
            artifacts=artifacts,
            relationships=(),
        )
    )
    from lab_data.artifact_previews import build_artifact_preview

    for artifact in artifacts:
        build_artifact_preview(
            store,
            artifact.artifact_id,
            storage_roots={'source': source_root},
            preview_root=preview_root,
        )
    store.close()

    print(f'catalog_path={catalog_path}')
    print(f'preview_root={preview_root}')
    print(f'source_root={source_root}')


if __name__ == '__main__':
    main()
