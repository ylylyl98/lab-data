"""Deterministically generate a bounded preview-cache sample.

This script selects a deterministic, SQL-bounded page of artifacts for one
device and kind, builds their atomic previews, and prints a JSON report.  It
only reads source files and only writes additively into the preview root, which
must live outside the source corpus.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from lab_data.artifact_previews import build_artifact_preview
from lab_data.catalog_retrieval import search_artifacts
from lab_data.scientific_catalog import CatalogStore, open_read_only_catalog

ARTIFACT_KINDS = ('image', 'document', 'data', 'other')
MIN_SAMPLE_LIMIT = 1
MAX_SAMPLE_LIMIT = 200


def select_sample_artifact_ids(
    store: CatalogStore,
    *,
    device_id: str,
    kind: str,
    limit: int,
) -> tuple[str, ...]:
    """Return a deterministic, bounded page of matching artifact IDs."""

    page = search_artifacts(
        store,
        filters={'device_id': device_id},
        kind=kind,
        limit=limit,
        offset=0,
    )
    return tuple(item['artifact_id'] for item in page.items)


def _bounded_limit(value: str) -> int:
    limit = int(value)
    if not MIN_SAMPLE_LIMIT <= limit <= MAX_SAMPLE_LIMIT:
        raise argparse.ArgumentTypeError(
            f'--limit must be between {MIN_SAMPLE_LIMIT} and {MAX_SAMPLE_LIMIT}'
        )
    return limit


def _validate_paths(
    preview_root: Path, storage_root: Path
) -> tuple[Path, Path]:
    """Validate routing and return resolved preview and storage roots."""

    preview = Path(preview_root)
    storage = Path(storage_root)
    if not preview.is_absolute():
        raise ValueError('preview_root must be an absolute path')
    resolved_preview = preview.resolve()
    resolved_storage = storage.resolve()
    if not resolved_storage.is_dir():
        raise ValueError(
            'storage_root does not exist or is not a directory: '
            f'{resolved_storage}'
        )
    if resolved_preview == resolved_storage:
        raise ValueError('preview_root must not equal storage_root')
    try:
        resolved_preview.relative_to(resolved_storage)
    except ValueError:
        pass
    else:
        raise ValueError('preview_root must not be inside storage_root')
    return resolved_preview, resolved_storage


def _preview_record(preview: Any) -> dict[str, Any]:
    return {
        'artifact_id': preview.artifact_id,
        'preview_id': preview.preview_id,
        'kind': preview.kind,
        'status': preview.status,
        'asset_count': len(preview.assets),
        'warnings': list(preview.warnings),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--preview-root', type=Path, required=True)
    parser.add_argument('--storage-root', type=Path, required=True)
    parser.add_argument('--storage-source-id', default='dropbox_device_docs')
    parser.add_argument('--device-id', required=True)
    parser.add_argument('--kind', required=True, choices=ARTIFACT_KINDS)
    parser.add_argument('--limit', type=_bounded_limit, default=6)
    args = parser.parse_args()

    preview_root, storage_root = _validate_paths(
        args.preview_root, args.storage_root
    )

    store = open_read_only_catalog(args.catalog)
    try:
        artifact_ids = select_sample_artifact_ids(
            store,
            device_id=args.device_id,
            kind=args.kind,
            limit=args.limit,
        )
        previews = [
            build_artifact_preview(
                store,
                artifact_id,
                storage_roots={args.storage_source_id: storage_root},
                preview_root=preview_root,
            )
            for artifact_id in artifact_ids
        ]
    finally:
        store.close()

    report = {
        'input': {
            'catalog': str(Path(args.catalog).resolve()),
            'preview_root': str(preview_root),
            'storage_root': str(storage_root),
            'storage_source_id': args.storage_source_id,
            'device_id': args.device_id,
            'kind': args.kind,
            'limit': args.limit,
        },
        'selected_artifact_ids': list(artifact_ids),
        'artifacts': [_preview_record(preview) for preview in previews],
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
