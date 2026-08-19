"""Deterministic, JSON-safe retrieval adapters for the scientific catalog."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from lab_data.artifact_previews import build_artifact_preview_report
from lab_data.experiment_search import ExperimentSearchRecord, SearchLineageEdge
from lab_data.scientific_catalog import (
    Artifact,
    CatalogStore,
    Device,
)

__all__ = [
    'search_devices',
    'search_experiments',
    'search_artifacts',
    'find_device_experiments',
    'find_device_documents',
    'get_artifact_preview',
]

_DEVICE_FILTERS = frozenset(
    {
        'device_id',
        'display_label',
        'maker_namespace',
        'local_device_id',
        'device_type',
        'review_state',
    }
)
_ARTIFACT_FILTERS = frozenset(
    {
        'artifact_id',
        'device_id',
        'experiment_id',
        'role',
        'category',
        'extension',
        'media_type',
        'review_state',
        'storage_source_id',
        'relative_path',
    }
)


def _require_device_id(device_id: str) -> str:
    """Validate a device identifier before applying an exact-match query."""

    if not isinstance(device_id, str) or not device_id:
        raise ValueError('device_id must be a non-empty string')
    return device_id


def _json_safe(value: Any) -> Any:
    """Copy frozen catalog values into plain JSON-compatible containers."""

    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (set, frozenset)):
        return [_json_safe(item) for item in sorted(value, key=repr)]
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if is_dataclass(value):
        return _json_safe(asdict(value))
    return value


def _filters(
    filters: Mapping[str, Any] | None,
    allowed: frozenset[str],
    label: str,
) -> dict[str, Any]:
    if filters is None:
        return {}
    if not isinstance(filters, Mapping):
        raise TypeError('filters must be a mapping or None')
    unknown = sorted(set(filters) - allowed)
    if unknown:
        raise ValueError(f'unknown {label} filter(s): {", ".join(unknown)}')
    return dict(filters)


def _project_device(device: Device) -> dict[str, Any]:
    return {
        'device_id': device.device_id,
        'display_label': device.display_label,
        'maker_namespace': device.maker_namespace,
        'local_device_id': device.local_device_id,
        'device_type': device.device_type,
        'review_state': device.review_state,
        'aliases': _json_safe(device.aliases),
        'metadata': _json_safe(device.metadata),
    }


def _project_artifact(artifact: Artifact) -> dict[str, Any]:
    reference = artifact.storage_reference
    return {
        'artifact_id': artifact.artifact_id,
        'device_id': artifact.device_id,
        'experiment_id': artifact.experiment_id,
        'role': artifact.role,
        'category': artifact.category,
        'extension': artifact.extension,
        'media_type': artifact.media_type,
        'review_state': artifact.review_state,
        'storage_source_id': None if reference is None else reference.storage_source_id,
        'relative_path': None if reference is None else reference.relative_path,
        'size_bytes': artifact.size_bytes,
        'mtime_ns': artifact.mtime_ns,
        'metadata': _json_safe(artifact.metadata),
    }


def _project_lineage(edge: SearchLineageEdge) -> dict[str, str]:
    return {'source': edge.source, 'target': edge.target, 'relation': edge.relation}


def _project_experiment(record: ExperimentSearchRecord) -> dict[str, Any]:
    return {
        'experiment_id': record.experiment_id,
        'metadata': _json_safe(record.metadata),
        'files_by_role': _json_safe(record.files_by_role),
        'lineage': [_project_lineage(edge) for edge in record.lineage],
        'warnings': _json_safe(record.warnings),
        'confidence': record.confidence,
        'needs_review': record.needs_review,
    }


def search_devices(
    store: CatalogStore, *, filters: Mapping[str, Any] | None = None
) -> tuple[dict[str, Any], ...]:
    """Return deterministic device projections matching exact scalar filters."""

    expected = _filters(filters, _DEVICE_FILTERS, 'device')
    devices = []
    for device in store.list_devices():
        if all(getattr(device, key) == value for key, value in expected.items()):
            devices.append(device)
    return tuple(
        _project_device(device)
        for device in sorted(devices, key=lambda item: item.device_id)
    )


def search_experiments(
    store: CatalogStore, *, filters: Mapping[str, Any] | None = None
) -> tuple[dict[str, Any], ...]:
    """Delegate experiment filtering to the canonical search implementation."""

    return tuple(
        _project_experiment(record)
        for record in store.search_experiments(filters=filters)
    )


def search_artifacts(
    store: CatalogStore, *, filters: Mapping[str, Any] | None = None
) -> tuple[dict[str, Any], ...]:
    """Return deterministic artifact projections matching exact filters."""

    expected = _filters(filters, _ARTIFACT_FILTERS, 'artifact')
    artifact_id = expected.get('artifact_id')
    device_id = expected.get('device_id')
    if isinstance(artifact_id, str) and artifact_id:
        candidate = store.get_artifact(artifact_id)
        artifacts = [] if candidate is None else [candidate]
    elif isinstance(device_id, str) and device_id:
        artifacts = list(store.list_artifacts(device_id=device_id))
    else:
        artifacts = list(store.list_artifacts())
    matching = []
    for artifact in artifacts:
        reference = artifact.storage_reference
        actual = {
            'artifact_id': artifact.artifact_id,
            'device_id': artifact.device_id,
            'experiment_id': artifact.experiment_id,
            'role': artifact.role,
            'category': artifact.category,
            'extension': artifact.extension,
            'media_type': artifact.media_type,
            'review_state': artifact.review_state,
            'storage_source_id': None
            if reference is None
            else reference.storage_source_id,
            'relative_path': None if reference is None else reference.relative_path,
        }
        if all(actual[key] == value for key, value in expected.items()):
            matching.append(artifact)
    return tuple(
        _project_artifact(artifact)
        for artifact in sorted(matching, key=lambda item: item.artifact_id)
    )


def find_device_experiments(
    store: CatalogStore, device_id: str
) -> tuple[dict[str, Any], ...]:
    """Return experiments connected by explicit ``measured_on`` relationships."""

    device_id = _require_device_id(device_id)
    return tuple(
        _project_experiment(record)
        for record in store.get_device_experiments(device_id)
    )


def find_device_documents(
    store: CatalogStore, device_id: str
) -> tuple[dict[str, Any], ...]:
    """Return explicitly device-bound base PDF/PPT/PPTX artifacts only."""

    device_id = _require_device_id(device_id)
    documents = [
        artifact
        for artifact in store.list_artifacts(device_id=device_id)
        if (
            artifact.device_id == device_id
            and artifact.extension.casefold().lstrip('.') in {'pdf', 'ppt', 'pptx'}
            and artifact.category.casefold() != 'slide'
        )
    ]
    return tuple(
        _project_artifact(artifact)
        for artifact in sorted(documents, key=lambda item: item.artifact_id)
    )


def get_artifact_preview(
    store: CatalogStore, artifact_id: str, *, preview_root: Path
) -> dict[str, Any] | None:
    """Return one validated cache-only preview report, or ``None`` if absent."""

    reports = build_artifact_preview_report(
        store, (artifact_id,), preview_root=preview_root
    )
    return reports[0] if reports else None
