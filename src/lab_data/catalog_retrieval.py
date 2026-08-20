"""Deterministic, JSON-safe retrieval adapters for the scientific catalog."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, NamedTuple

from lab_data.artifact_previews import build_artifact_preview_report
from lab_data.device_experiment_linkage import HUMAN_REVIEWED_RAW_MATCH_FIELD
from lab_data.experiment_search import ExperimentSearchRecord, SearchLineageEdge
from lab_data.scientific_catalog import (
    ARTIFACT_KINDS,
    ENTITY_FILE,
    SUBJECT_EXPERIMENT,
    Artifact,
    CatalogStore,
    Device,
    deterministic_storage_reference_id,
)

__all__ = [
    'search_devices',
    'search_experiments',
    'search_artifacts',
    'find_device_experiments',
    'find_device_documents',
    'get_artifact_preview',
    'Page',
]


class Page(NamedTuple):
    """A bounded, deterministically ordered page plus its matching total."""

    items: tuple[dict[str, Any], ...]
    total_count: int

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

# ``/devices/{device_id}/documents`` keeps the narrower historical document
# contract: only base PDF/PPT/PPTX files, and never slide-category decks.
_DEVICE_DOCUMENT_EXTENSIONS = frozenset({'pdf', 'ppt', 'pptx'})


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


def _project_artifact(
    artifact: Artifact, *, derived_from: list[dict[str, str]]
) -> dict[str, Any]:
    reference = artifact.storage_reference
    relative_path = None if reference is None else reference.relative_path
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
        'relative_path': relative_path,
        'filename': None if relative_path is None else relative_path.rsplit('/', 1)[-1],
        'size_bytes': artifact.size_bytes,
        'mtime_ns': artifact.mtime_ns,
        'metadata': _json_safe(artifact.metadata),
        'derived_from': derived_from,
    }


def _project_lineage(edge: SearchLineageEdge) -> dict[str, str]:
    return {'source': edge.source, 'target': edge.target, 'relation': edge.relation}


def _project_experiment(
    record: ExperimentSearchRecord,
    *,
    measured_on: dict[str, Any] | None,
    review_evidence: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    return {
        'experiment_id': record.experiment_id,
        'metadata': _json_safe(record.metadata),
        'files_by_role': _json_safe(record.files_by_role),
        'lineage': [_project_lineage(edge) for edge in record.lineage],
        'warnings': _json_safe(record.warnings),
        'confidence': record.confidence,
        'needs_review': record.needs_review,
        'review_state': record.review_state,
        'measured_on': measured_on,
        'review_evidence': review_evidence,
    }


def _measured_on_payload(
    store: CatalogStore, record: ExperimentSearchRecord
) -> dict[str, Any] | None:
    """Project persisted device-directory linkage for one experiment page item."""

    relationships = tuple(
        relationship
        for relationship in store.get_lineage(
            SUBJECT_EXPERIMENT, record.experiment_id
        )
        if relationship.predicate == 'measured_on'
    )
    if not relationships:
        return None
    relationship = relationships[0]
    claims = tuple(
        claim
        for claim in store.get_provenance(
            SUBJECT_EXPERIMENT, record.experiment_id
        )
        if claim.field == 'measured_on_device'
    )
    claim = claims[0] if claims else None
    return {
        'device_id': relationship.target_id,
        'evidence': (
            '; '.join(claim.evidence)
            if claim is not None and claim.evidence
            else 'explicit device-directory context'
        ),
        'source_reference': (
            claim.source_reference
            if claim is not None
            else relationship.provenance_source
        ),
        'extraction_method': claim.extraction_method if claim is not None else None,
        'review_status': (
            claim.review_status if claim is not None else relationship.review_state
        ),
    }


def _review_evidence_payload(
    store: CatalogStore, record: ExperimentSearchRecord
) -> list[dict[str, Any]] | None:
    """Project persisted human-review claims for one experiment page item."""

    claims = tuple(
        claim
        for claim in store.get_provenance(SUBJECT_EXPERIMENT, record.experiment_id)
        if claim.field == HUMAN_REVIEWED_RAW_MATCH_FIELD
    )
    if not claims:
        return None
    return [
        {
            'field': claim.field,
            'value': _json_safe(claim.value),
            'source_type': claim.source_type,
            'source_reference': claim.source_reference,
            'extraction_method': claim.extraction_method,
            'category': claim.category,
            'evidence': _json_safe(claim.evidence),
            'review_status': claim.review_status,
        }
        for claim in claims
    ]


def _artifact_derived_from(
    store: CatalogStore, artifact: Artifact
) -> list[dict[str, str]]:
    """Project persisted file-to-file derivation edges for one artifact."""

    reference = artifact.storage_reference
    if reference is None:
        return []
    file_id = deterministic_storage_reference_id(
        storage_source_id=reference.storage_source_id,
        relative_path=reference.relative_path,
    )
    edges = tuple(
        edge
        for edge in store.get_lineage(ENTITY_FILE, file_id)
        if edge.predicate == 'derived_from'
    )
    if not edges:
        return []
    paths = store.resolve_file_references(
        {edge.source_id for edge in edges} | {edge.target_id for edge in edges}
    )
    pairs = {
        (paths[edge.source_id]['relative_path'], paths[edge.target_id]['relative_path'])
        for edge in edges
        if edge.source_id in paths and edge.target_id in paths
    }
    return [
        {'source': source, 'target': target, 'relation': 'derived_from'}
        for source, target in sorted(pairs)
    ]


def _normalize_q(q: str | None) -> str | None:
    """Return a case-folded query string, or ``None`` for an empty query."""

    if q is None:
        return None
    normalized = q.strip().casefold()
    return normalized or None


def _slice(items: tuple[Any, ...], limit: int, offset: int) -> tuple[Any, ...]:
    return items[offset : offset + limit]


def _device_matches_q(device: Device, needle: str) -> bool:
    if needle in device.device_id.casefold():
        return True
    if needle in (device.display_label or '').casefold():
        return True
    if device.local_device_id and needle in device.local_device_id.casefold():
        return True
    return any(needle in alias.casefold() for alias in device.aliases)


def _experiment_matches_q(record: ExperimentSearchRecord, needle: str) -> bool:
    if needle in record.experiment_id.casefold():
        return True
    sample_id = record.metadata.get('sample_id')
    return isinstance(sample_id, str) and needle in sample_id.casefold()


def search_devices(
    store: CatalogStore,
    *,
    filters: Mapping[str, Any] | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Page:
    """Return a deterministically ordered device page plus its total count."""

    expected = _filters(filters, _DEVICE_FILTERS, 'device')
    needle = _normalize_q(q)
    devices = [
        device
        for device in store.list_devices()
        if all(getattr(device, key) == value for key, value in expected.items())
        and (needle is None or _device_matches_q(device, needle))
    ]
    # Stable device ordering: device_id ascending.
    devices.sort(key=lambda item: item.device_id)
    total_count = len(devices)
    return Page(
        tuple(_project_device(device) for device in _slice(devices, limit, offset)),
        total_count,
    )


def search_experiments(
    store: CatalogStore,
    *,
    filters: Mapping[str, Any] | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Page:
    """Return a canonically ordered experiment page plus its total count."""

    needle = _normalize_q(q)
    records = tuple(store.search_experiments(filters=filters))
    if needle is not None:
        records = tuple(
            record for record in records if _experiment_matches_q(record, needle)
        )
    total_count = len(records)
    page_items = _slice(records, limit, offset)
    return Page(
        tuple(
            _project_experiment(
                record,
                measured_on=_measured_on_payload(store, record),
                review_evidence=_review_evidence_payload(store, record),
            )
            for record in page_items
        ),
        total_count,
    )


def search_artifacts(  # noqa: PLR0913
    store: CatalogStore,
    *,
    filters: Mapping[str, Any] | None = None,
    q: str | None = None,
    kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Page:
    """Return a deterministically ordered artifact page plus its total count."""

    expected = _filters(filters, _ARTIFACT_FILTERS, 'artifact')
    if kind is not None and kind not in ARTIFACT_KINDS:
        raise ValueError(f'unknown artifact kind: {kind!r}')
    artifacts = store.page_artifacts(
        filters=expected,
        q=q,
        kind=kind,
        limit=limit,
        offset=offset,
    )
    total_count = store.count_artifacts(filters=expected, q=q, kind=kind)
    return Page(
        tuple(
            _project_artifact(
                artifact, derived_from=_artifact_derived_from(store, artifact)
            )
            for artifact in artifacts
        ),
        total_count,
    )


def find_device_experiments(
    store: CatalogStore,
    device_id: str,
    *,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Page:
    """Return device-measured experiments, ordered canonically, as a page."""

    device_id = _require_device_id(device_id)
    needle = _normalize_q(q)
    records = tuple(store.get_device_experiments(device_id))
    if needle is not None:
        records = tuple(
            record for record in records if _experiment_matches_q(record, needle)
        )
    total_count = len(records)
    page_items = _slice(records, limit, offset)
    return Page(
        tuple(
            _project_experiment(
                record,
                measured_on=_measured_on_payload(store, record),
                review_evidence=_review_evidence_payload(store, record),
            )
            for record in page_items
        ),
        total_count,
    )


def find_device_documents(
    store: CatalogStore,
    device_id: str,
    *,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Page:
    """Return bounded device-bound PDF/PPT/PPTX documents plus their total."""

    device_id = _require_device_id(device_id)
    filters = {'device_id': device_id}
    artifacts = store.page_artifacts(
        filters=filters,
        q=q,
        extensions=_DEVICE_DOCUMENT_EXTENSIONS,
        exclude_slide_category=True,
        limit=limit,
        offset=offset,
    )
    total_count = store.count_artifacts(
        filters=filters,
        q=q,
        extensions=_DEVICE_DOCUMENT_EXTENSIONS,
        exclude_slide_category=True,
    )
    return Page(
        tuple(
            _project_artifact(
                artifact, derived_from=_artifact_derived_from(store, artifact)
            )
            for artifact in artifacts
        ),
        total_count,
    )


def get_artifact_preview(
    store: CatalogStore, artifact_id: str, *, preview_root: Path
) -> dict[str, Any] | None:
    """Return one validated cache-only preview report, or ``None`` if absent."""

    reports = build_artifact_preview_report(
        store, (artifact_id,), preview_root=preview_root
    )
    return reports[0] if reports else None
