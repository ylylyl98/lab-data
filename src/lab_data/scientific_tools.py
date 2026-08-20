"""Provider-neutral, deterministic, read-only scientific tool surface.

This module wraps the existing deterministic retrieval contracts so a future
MCP adapter or AI client can call them without duplicating scientific logic.
Canonical truth stays in the catalog layer; every tool here is bounded,
JSON-safe, read-only, and model-independent.  There are no external AI calls
and no caller-supplied filesystem paths.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from lab_data.catalog_retrieval import (
    find_device_documents as _find_device_documents,
)
from lab_data.catalog_retrieval import (
    find_device_experiments as _find_device_experiments,
)
from lab_data.catalog_retrieval import (
    get_artifact_preview as _get_artifact_preview,
)
from lab_data.catalog_retrieval import (
    search_artifacts as _search_artifacts,
)
from lab_data.catalog_retrieval import (
    search_devices as _search_devices,
)
from lab_data.catalog_retrieval import (
    search_experiments as _search_experiments,
)
from lab_data.scientific_catalog import (
    ENTITY_FILE,
    SUBJECT_ARTIFACT,
    SUBJECT_DEVICE,
    SUBJECT_EXPERIMENT,
    CatalogStore,
    open_read_only_catalog,
)

__all__ = [
    'DEFAULT_PAGE_SIZE',
    'MAX_LIMIT',
    'MIN_LIMIT',
    'ScientificToolLayer',
]

DEFAULT_PAGE_SIZE = 50
MIN_LIMIT = 1
MAX_LIMIT = 200

_PROVENANCE_SUBJECT_TYPES = frozenset(
    {SUBJECT_EXPERIMENT, SUBJECT_DEVICE, SUBJECT_ARTIFACT}
)
_LINEAGE_ENTITY_TYPES = frozenset(
    {SUBJECT_EXPERIMENT, SUBJECT_DEVICE, SUBJECT_ARTIFACT, ENTITY_FILE}
)


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


def _require_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f'{name} must be a non-empty string')
    return value


def _require_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f'{name} must be a string or None')
    return value


def _require_page(limit: object, offset: object) -> tuple[int, int]:
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not MIN_LIMIT <= limit <= MAX_LIMIT
    ):
        raise ValueError(
            f'limit must be an integer between {MIN_LIMIT} and {MAX_LIMIT}'
        )
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError('offset must be a non-negative integer')
    return limit, offset


def _page_payload(page: Any, limit: int, offset: int) -> dict[str, Any]:
    return {
        'items': list(page.items),
        'total_count': page.total_count,
        'limit': limit,
        'offset': offset,
    }


def _project_claim(claim: Any) -> dict[str, Any]:
    return {
        'field': claim.field,
        'value': _json_safe(claim.value),
        'source_type': claim.source_type,
        'source_reference': claim.source_reference,
        'extraction_method': claim.extraction_method,
        'category': claim.category,
        'confidence': claim.confidence,
        'evidence': list(claim.evidence),
        'review_status': claim.review_status,
    }


def _project_relationship(
    edge: Any, paths: Mapping[str, Mapping[str, str]]
) -> dict[str, Any]:
    def path_for(file_id: str) -> str | None:
        resolved = paths.get(file_id)
        return None if resolved is None else resolved.get('relative_path')

    return {
        'predicate': edge.predicate,
        'source_type': edge.source_type,
        'source_id': edge.source_id,
        'target_type': edge.target_type,
        'target_id': edge.target_id,
        'provenance_source': edge.provenance_source,
        'review_state': edge.review_state,
        'source_path': path_for(edge.source_id),
        'target_path': path_for(edge.target_id),
    }


class ScientificToolLayer:
    """Read-only, bounded, JSON-safe facade over the catalog retrieval layer.

    ``preview_root`` is configuration for the preview tool, never a per-call
    caller-supplied path.  A layer built without one can use every tool except
    :meth:`get_artifact_preview`.
    """

    def __init__(
        self, store: CatalogStore, *, preview_root: str | Path | None = None
    ) -> None:
        self._store = store
        self._preview_root = None
        if preview_root is not None:
            root = Path(preview_root)
            if not root.is_absolute():
                raise ValueError('preview_root must be an absolute path')
            self._preview_root = root

    @classmethod
    def from_catalog(
        cls,
        catalog_path: str | Path,
        *,
        preview_root: str | Path | None = None,
    ) -> ScientificToolLayer:
        """Open a catalog read-only and build a layer over it."""

        return cls(open_read_only_catalog(catalog_path), preview_root=preview_root)

    @property
    def store(self) -> CatalogStore:
        """The underlying read-only catalog store."""

        return self._store

    @property
    def preview_root(self) -> Path | None:
        """The configured preview cache root, or ``None`` when unset."""

        return self._preview_root

    def close(self) -> None:
        """Close an owned catalog store (safe on protocol fakes)."""

        close = getattr(self._store, 'close', None)
        if callable(close):
            close()

    def search_devices(
        self,
        q: str | None = None,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
        filters: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Search devices by substring or exact filter, with stable ordering.

        Deterministic example: ``search_devices('356')`` returns only D356
        when the catalog holds devices D356, D357, and YZ247.
        """

        _require_text(q, 'q')
        limit, offset = _require_page(limit, offset)
        page = _search_devices(
            self._store, filters=filters, q=q, limit=limit, offset=offset
        )
        return _page_payload(page, limit, offset)

    def search_experiments(
        self,
        q: str | None = None,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
        filters: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Search experiments by substring or exact filter, canonically ordered."""

        _require_text(q, 'q')
        limit, offset = _require_page(limit, offset)
        page = _search_experiments(
            self._store, filters=filters, q=q, limit=limit, offset=offset
        )
        return _page_payload(page, limit, offset)

    def search_artifacts(  # noqa: PLR0913
        self,
        q: str | None = None,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
        kind: str | None = None,
        filters: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Search artifacts by substring, kind, or exact filter, ordered by ID."""

        _require_text(q, 'q')
        limit, offset = _require_page(limit, offset)
        page = _search_artifacts(
            self._store,
            filters=filters,
            q=q,
            kind=kind,
            limit=limit,
            offset=offset,
        )
        return _page_payload(page, limit, offset)

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        """Return one exact device by ID, or ``None`` when absent."""

        _require_id(device_id, 'device_id')
        page = _search_devices(
            self._store, filters={'device_id': device_id}, limit=1, offset=0
        )
        return page.items[0] if page.items else None

    def get_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        """Return one exact experiment with review state and measured-on data.

        Deterministic example: ``get_experiment('YZ247-0432')`` returns its
        metadata, files by role, lineage, and review state.
        """

        _require_id(experiment_id, 'experiment_id')
        page = _search_experiments(
            self._store,
            filters={'experiment_id': experiment_id},
            limit=1,
            offset=0,
        )
        return page.items[0] if page.items else None

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        """Return one exact artifact including its ``derived_from`` edges."""

        _require_id(artifact_id, 'artifact_id')
        page = _search_artifacts(
            self._store, filters={'artifact_id': artifact_id}, limit=1, offset=0
        )
        return page.items[0] if page.items else None

    def find_device_experiments(
        self,
        device_id: str,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
        q: str | None = None,
    ) -> dict[str, Any]:
        """Return explicit device-measured experiments as one bounded page.

        Deterministic example: ``find_device_experiments('D356')`` returns
        ``total_count == 317`` for the YZ247/YZDEV corpus.
        """

        _require_id(device_id, 'device_id')
        _require_text(q, 'q')
        limit, offset = _require_page(limit, offset)
        page = _find_device_experiments(
            self._store, device_id, q=q, limit=limit, offset=offset
        )
        return _page_payload(page, limit, offset)

    def find_device_documents(
        self,
        device_id: str,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
        q: str | None = None,
    ) -> dict[str, Any]:
        """Return bounded device-bound PDF/PPT/PPTX documents as one page."""

        _require_id(device_id, 'device_id')
        _require_text(q, 'q')
        limit, offset = _require_page(limit, offset)
        page = _find_device_documents(
            self._store, device_id, q=q, limit=limit, offset=offset
        )
        return _page_payload(page, limit, offset)

    def get_artifact_preview(self, artifact_id: str) -> dict[str, Any] | None:
        """Return one validated cache-only preview report, or ``None``.

        The report contains manifest-validated asset metadata only; asset
        bytes are read by ``read_artifact_preview_asset`` (or a later MCP
        adapter) under the same validated preview root.  Deterministic
        example: a D356 processed PNG returns a ``ready``/``image`` report
        whose asset path is ``image.png``.
        """

        _require_id(artifact_id, 'artifact_id')
        if self._preview_root is None:
            raise ValueError('preview_root is not configured for this layer')
        return _get_artifact_preview(
            self._store, artifact_id, preview_root=self._preview_root
        )

    def get_provenance(
        self, subject_type: str, subject_id: str
    ) -> list[dict[str, Any]]:
        """Return persisted metadata claims for one subject.

        Only persisted claims are exposed; nothing is inferred.  Deterministic
        example: D356-0316 returns a ``measured_on_device`` claim plus a
        ``measured_on_raw_match`` claim with ``source_type == 'human_review'``,
        ``extraction_method == 'human_reviewed_match'``, and
        ``review_status == 'accepted'``.
        """

        _require_id(subject_id, 'subject_id')
        if subject_type not in _PROVENANCE_SUBJECT_TYPES:
            raise ValueError(
                'unknown subject type: '
                f'{subject_type!r}; expected one of: '
                + ', '.join(sorted(_PROVENANCE_SUBJECT_TYPES))
            )
        claims = self._store.get_provenance(subject_type, subject_id)
        return [_project_claim(claim) for claim in claims]

    def get_lineage(self, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        """Return persisted relationship edges touching one entity.

        File entity IDs are also resolved to storage-relative paths when the
        store knows them; the persisted edge fields are otherwise unchanged.
        Deterministic example: the raw file of D356-0316 returns one
        ``derived_from`` edge from the raw path to the processed path
        (upstream raw -> processed -> figure downstream).
        """

        _require_id(entity_id, 'entity_id')
        if entity_type not in _LINEAGE_ENTITY_TYPES:
            raise ValueError(
                'unknown entity type: '
                f'{entity_type!r}; expected one of: '
                + ', '.join(sorted(_LINEAGE_ENTITY_TYPES))
            )
        edges = self._store.get_lineage(entity_type, entity_id)
        if not edges:
            return []
        file_ids = {
            edge.source_id for edge in edges if edge.source_type == ENTITY_FILE
        } | {edge.target_id for edge in edges if edge.target_type == ENTITY_FILE}
        resolved = self._store.resolve_file_references(file_ids)
        return [_project_relationship(edge, resolved) for edge in edges]
