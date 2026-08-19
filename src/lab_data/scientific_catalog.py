"""Rebuildable SQLite-backed Scientific Catalog.

This module provides a storage-agnostic persistence boundary for normalized
scientific records: experiments, devices, artifacts, provenance-aware metadata
claims, and entity-neutral relationships.  The SQLite implementation is a local
single-writer store.  A caller-supplied snapshot atomically replaces the
canonical catalog, and the search-facing API delegates to
:mod:`lab_data.experiment_search` so persisted experiments retain the exact
in-memory search semantics.

Claims and relationships are entity-neutral rather than experiment-owned.
Experiment identities are always supplied by the caller and are never derived
from filenames or rewritten.  Canonical storage paths are forward-slash,
storage-relative paths; absolute, drive-qualified, and traversal paths are
rejected.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import KW_ONLY, asdict, dataclass, field, is_dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from lab_data.experiment_search import (
    ExperimentSearchIndex,
    ExperimentSearchRecord,
    RelatedFile,
    SearchLineageEdge,
    build_search_index,
)
from lab_data.experiment_search import (
    find_related_files as _find_related_files,
)
from lab_data.experiment_search import (
    search_experiments as _search_experiments,
)
from lab_data.ingestion.proposal import ExperimentImportProposal, MetadataProvenance

__all__ = [
    'Artifact',
    'CatalogSnapshot',
    'CatalogStore',
    'Device',
    'ENTITY_FILE',
    'Experiment',
    'FILE_ROLES',
    'MetadataClaim',
    'open_read_only_catalog',
    'REVIEW_ACCEPTED',
    'REVIEW_CORRECTED',
    'REVIEW_REJECTED',
    'REVIEW_STATES',
    'REVIEW_UNKNOWN',
    'Relationship',
    'SCHEMA_VERSION',
    'SQLiteCatalogStore',
    'StorageReference',
    'SUBJECT_ARTIFACT',
    'SUBJECT_DEVICE',
    'SUBJECT_EXPERIMENT',
    'UNKNOWN',
    'deterministic_relationship_id',
    'deterministic_storage_reference_id',
    'deterministic_device_id',
]

SCHEMA_VERSION = 2

UNKNOWN = 'UNKNOWN'

REVIEW_UNKNOWN = 'unknown'
REVIEW_ACCEPTED = 'accepted'
REVIEW_CORRECTED = 'corrected'
REVIEW_REJECTED = 'rejected'
REVIEW_STATES = frozenset(
    {REVIEW_UNKNOWN, REVIEW_ACCEPTED, REVIEW_CORRECTED, REVIEW_REJECTED}
)

SUBJECT_EXPERIMENT = 'experiment'
SUBJECT_DEVICE = 'device'
SUBJECT_ARTIFACT = 'artifact'
ENTITY_FILE = 'file'

FILE_ROLES = frozenset({'raw', 'processed', 'figure', 'intermediate', 'artifact'})

_DRIVE_PATH = re.compile(r'^[A-Za-z]:')

_META_TABLE = 'catalog_meta'
_EXPERIMENTS_TABLE = 'experiments'
_DEVICES_TABLE = 'devices'
_ARTIFACTS_TABLE = 'artifacts'
_EXPERIMENT_FILES_TABLE = 'experiment_files'
_CLAIMS_TABLE = 'metadata_claims'
_RELATIONSHIPS_TABLE = 'relationships'
_SCHEMA_KEY = 'schema_version'

_UNSET = object()

# Child tables are deleted first so foreign keys never dangle during rebuild.
_DELETE_ORDER = (
    _RELATIONSHIPS_TABLE,
    _CLAIMS_TABLE,
    _ARTIFACTS_TABLE,
    _EXPERIMENT_FILES_TABLE,
    _DEVICES_TABLE,
    _EXPERIMENTS_TABLE,
)

_META_DDL = f"""
CREATE TABLE IF NOT EXISTS {_META_TABLE} (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

_EXPERIMENTS_DDL = f"""
CREATE TABLE IF NOT EXISTS {_EXPERIMENTS_TABLE} (
    experiment_id TEXT PRIMARY KEY,
    metadata_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    confidence REAL NOT NULL,
    needs_review INTEGER NOT NULL,
    review_state TEXT NOT NULL,
    parser_version TEXT,
    roles_json TEXT NOT NULL,
    ordinal INTEGER NOT NULL
)
"""

_DEVICES_DDL = f"""
CREATE TABLE IF NOT EXISTS {_DEVICES_TABLE} (
    device_id TEXT PRIMARY KEY,
    device_type TEXT NOT NULL,
    aliases_json TEXT NOT NULL,
    review_state TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    maker_namespace TEXT,
    local_device_id TEXT,
    display_label TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    CHECK ((maker_namespace IS NULL) = (local_device_id IS NULL)),
    CHECK (maker_namespace IS NULL OR length(trim(maker_namespace)) > 0),
    CHECK (local_device_id IS NULL OR length(trim(local_device_id)) > 0),
    CHECK (length(trim(display_label)) > 0)
)
"""

_ARTIFACTS_DDL = f"""
CREATE TABLE IF NOT EXISTS {_ARTIFACTS_TABLE} (
    artifact_id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    category TEXT NOT NULL,
    extension TEXT NOT NULL,
    media_type TEXT NOT NULL,
    device_id TEXT,
    experiment_id TEXT,
    storage_source_id TEXT,
    relative_path TEXT,
    size_bytes INTEGER,
    mtime_ns INTEGER,
    review_state TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    FOREIGN KEY (device_id) REFERENCES {_DEVICES_TABLE}(device_id)
        ON DELETE SET NULL,
    FOREIGN KEY (experiment_id) REFERENCES {_EXPERIMENTS_TABLE}(experiment_id)
        ON DELETE SET NULL
)
"""

_EXPERIMENT_FILES_DDL = f"""
CREATE TABLE IF NOT EXISTS {_EXPERIMENT_FILES_TABLE} (
    experiment_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    role TEXT NOT NULL,
    storage_source_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    PRIMARY KEY (experiment_id, ordinal),
    FOREIGN KEY (experiment_id) REFERENCES {_EXPERIMENTS_TABLE}(experiment_id)
        ON DELETE CASCADE
)
"""

_CLAIMS_DDL = f"""
CREATE TABLE IF NOT EXISTS {_CLAIMS_TABLE} (
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    field TEXT NOT NULL,
    value_json TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_reference TEXT,
    extraction_method TEXT NOT NULL,
    confidence REAL,
    category TEXT,
    evidence_json TEXT NOT NULL,
    review_status TEXT NOT NULL,
    reviewed_value_json TEXT,
    PRIMARY KEY (subject_type, subject_id, ordinal)
)
"""

_RELATIONSHIPS_DDL = f"""
CREATE TABLE IF NOT EXISTS {_RELATIONSHIPS_TABLE} (
    relationship_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    provenance_source TEXT,
    review_state TEXT NOT NULL,
    ordinal INTEGER NOT NULL
)
"""

_TABLES_DDL = (
    _EXPERIMENTS_DDL,
    _DEVICES_DDL,
    _ARTIFACTS_DDL,
    _EXPERIMENT_FILES_DDL,
    _CLAIMS_DDL,
    _RELATIONSHIPS_DDL,
)

_DEVICES_QUALIFIED_INDEX = (
    f'CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_qualified_identity '
    f'ON {_DEVICES_TABLE}(maker_namespace, local_device_id) '
    'WHERE maker_namespace IS NOT NULL AND local_device_id IS NOT NULL'
)


def _freeze(value: Any) -> Any:
    """Return an immutable, value-preserving representation of ``value``."""

    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _jsonable(value: Any) -> Any:
    """Return a JSON-serializable, deterministic representation of ``value``."""

    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    return value


def _json_dumps(value: Any) -> str:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(',', ':'))


def _json_loads(value: str) -> Any:
    return json.loads(value)


def _require_non_empty_string(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f'{field_name} must be a non-empty string')


def _require_optional_string(value: object, field_name: str) -> None:
    if value is not None and (not isinstance(value, str) or not value):
        raise ValueError(f'{field_name} must be a non-empty string or None')


def _canonical_relative_path(value: object) -> str:
    """Validate and normalize a storage-relative forward-slash path."""

    if not isinstance(value, str) or not value:
        raise ValueError('relative_path must be a non-empty string')
    normalized = value.replace('\\', '/')
    if normalized.startswith('/') or _DRIVE_PATH.match(normalized):
        raise ValueError(f'relative_path must be storage-relative: {value!r}')
    components = normalized.split('/')
    if '..' in components:
        raise ValueError(f'relative_path must not contain ..: {value!r}')
    filtered = tuple(
        component for component in components if component not in ('', '.')
    )
    if not filtered:
        raise ValueError('relative_path must not be empty')
    return '/'.join(filtered)


def _require_review_state(value: object) -> None:
    if value not in REVIEW_STATES:
        raise ValueError(f'invalid review state: {value!r}')


def _require_finite_number(value: object, field_name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f'{field_name} must be a finite number')
    return float(value)


def _require_optional_confidence(value: object) -> float | None:
    if value is None:
        return None
    return _require_finite_number(value, 'confidence')


def _require_optional_non_negative_int(value: object, field_name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f'{field_name} must be a non-negative integer or None')


def _require_bool(value: object, field_name: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f'{field_name} must be a boolean')


def _require_string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    normalized = tuple(value)
    if any(not isinstance(item, str) or not item for item in normalized):
        raise ValueError(f'{field_name} must contain non-empty strings')
    return normalized


def deterministic_relationship_id(  # noqa: PLR0913
    *,
    source_type: str,
    source_id: str,
    predicate: str,
    target_type: str,
    target_id: str,
    provenance_source: str | None,
) -> str:
    """Return a stable ID for an entity-neutral relationship edge."""

    payload = [
        source_type,
        source_id,
        predicate,
        target_type,
        target_id,
        provenance_source,
    ]
    digest = hashlib.sha256(_json_dumps(payload).encode('utf-8')).hexdigest()
    return f'rel-{digest}'


def deterministic_storage_reference_id(
    *, storage_source_id: str, relative_path: str
) -> str:
    """Return a stable identity for one storage-scoped relative file path."""

    _require_non_empty_string(storage_source_id, 'storage_source_id')
    canonical_path = _canonical_relative_path(relative_path)
    digest = hashlib.sha256(
        _json_dumps([storage_source_id, canonical_path]).encode('utf-8')
    ).hexdigest()
    return f'file-{digest}'


def deterministic_device_id(namespace: str, local: str) -> str:
    """Return a stable internal ID for a maker-qualified device identity."""

    _require_non_empty_string(namespace, 'namespace')
    _require_non_empty_string(local, 'local')
    if namespace == 'YZ' and re.fullmatch(r'D[0-9]+', local):
        return local
    digest = hashlib.sha256(_json_dumps([namespace, local]).encode('utf-8')).hexdigest()
    return f'dev-{digest}'


@dataclass(frozen=True)
class StorageReference:
    """A canonical file reference scoped to one storage source."""

    storage_source_id: str
    relative_path: str

    def __post_init__(self) -> None:
        _require_non_empty_string(self.storage_source_id, 'storage_source_id')
        object.__setattr__(
            self, 'relative_path', _canonical_relative_path(self.relative_path)
        )


@dataclass(frozen=True)
class MetadataClaim:
    """An entity-neutral, provenance-aware, reviewable metadata claim."""

    subject_type: str
    subject_id: str
    field: str
    value: Any
    source_type: str = UNKNOWN
    source_reference: str | None = None
    extraction_method: str = UNKNOWN
    confidence: float | None = None
    category: str | None = None
    evidence: tuple[str, ...] = ()
    review_status: str = REVIEW_UNKNOWN
    reviewed_value: Any = _UNSET

    def __post_init__(self) -> None:
        _require_non_empty_string(self.subject_type, 'subject_type')
        _require_non_empty_string(self.subject_id, 'subject_id')
        _require_non_empty_string(self.field, 'field')
        _require_non_empty_string(self.source_type, 'source_type')
        _require_non_empty_string(self.extraction_method, 'extraction_method')
        _require_optional_string(self.source_reference, 'source_reference')
        _require_optional_string(self.category, 'category')
        _require_review_state(self.review_status)
        if self.review_status == REVIEW_CORRECTED and self.reviewed_value is _UNSET:
            raise ValueError('corrected metadata claims require reviewed_value')
        if self.review_status != REVIEW_CORRECTED and self.reviewed_value is not _UNSET:
            raise ValueError(
                'reviewed_value is only valid for corrected metadata claims'
            )
        object.__setattr__(
            self, 'confidence', _require_optional_confidence(self.confidence)
        )
        object.__setattr__(self, 'value', _freeze(self.value))
        if self.reviewed_value is not _UNSET:
            object.__setattr__(self, 'reviewed_value', _freeze(self.reviewed_value))
        evidence = tuple(self.evidence)
        if any(not isinstance(item, str) for item in evidence):
            raise TypeError('evidence must contain strings')
        object.__setattr__(self, 'evidence', evidence)


@dataclass(frozen=True)
class Relationship:
    """A fully entity-neutral, provenance-aware relationship edge."""

    source_type: str
    source_id: str
    predicate: str
    target_type: str
    target_id: str
    relationship_id: str | None = None
    provenance_source: str | None = None
    review_state: str = REVIEW_UNKNOWN

    def __post_init__(self) -> None:
        _require_non_empty_string(self.source_type, 'source_type')
        _require_non_empty_string(self.source_id, 'source_id')
        _require_non_empty_string(self.predicate, 'predicate')
        _require_non_empty_string(self.target_type, 'target_type')
        _require_non_empty_string(self.target_id, 'target_id')
        _require_optional_string(self.provenance_source, 'provenance_source')
        _require_review_state(self.review_state)
        if self.relationship_id is None:
            relationship_id = deterministic_relationship_id(
                source_type=self.source_type,
                source_id=self.source_id,
                predicate=self.predicate,
                target_type=self.target_type,
                target_id=self.target_id,
                provenance_source=self.provenance_source,
            )
        else:
            _require_non_empty_string(self.relationship_id, 'relationship_id')
            relationship_id = self.relationship_id
        object.__setattr__(self, 'relationship_id', relationship_id)


@dataclass(frozen=True)
class Device:
    """A scientific device with a canonical ``device_id`` and optional claims."""

    device_id: str
    device_type: str = UNKNOWN
    aliases: tuple[str, ...] = ()
    review_state: str = REVIEW_UNKNOWN
    metadata: Mapping[str, Any] = field(default_factory=dict)
    claims: tuple[MetadataClaim, ...] = ()
    _: KW_ONLY
    maker_namespace: str | None = None
    local_device_id: str | None = None
    display_label: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty_string(self.device_id, 'device_id')
        _require_non_empty_string(self.device_type, 'device_type')
        _require_review_state(self.review_state)
        _require_optional_string(self.maker_namespace, 'maker_namespace')
        _require_optional_string(self.local_device_id, 'local_device_id')
        if (self.maker_namespace is None) != (self.local_device_id is None):
            raise ValueError(
                'maker_namespace and local_device_id must both be set or both be None'
            )
        display_label = (
            self.device_id if self.display_label is None else self.display_label
        )
        _require_non_empty_string(display_label, 'display_label')
        if self.maker_namespace is not None:
            expected_id = deterministic_device_id(
                self.maker_namespace, self.local_device_id
            )
            if self.device_id != expected_id:
                raise ValueError(
                    'qualified device_id must match deterministic identity'
                )
        object.__setattr__(self, 'display_label', display_label)
        object.__setattr__(
            self, 'aliases', _require_string_tuple(self.aliases, 'aliases')
        )
        object.__setattr__(self, 'metadata', _freeze(self.metadata))
        object.__setattr__(
            self,
            'claims',
            self._validated_claims(self.claims, SUBJECT_DEVICE, self.device_id),
        )

    @staticmethod
    def _validated_claims(
        claims: tuple[MetadataClaim, ...], subject_type: str, subject_id: str
    ) -> tuple[MetadataClaim, ...]:
        normalized = tuple(claims)
        for claim in normalized:
            if not isinstance(claim, MetadataClaim):
                raise TypeError('claims must contain MetadataClaim values')
            if claim.subject_type != subject_type or claim.subject_id != subject_id:
                raise ValueError('claims must reference the owning subject')
        return normalized


@dataclass(frozen=True)
class Artifact:
    """A persisted artifact with independent type, role, and storage metadata."""

    artifact_id: str
    role: str = UNKNOWN
    category: str = UNKNOWN
    extension: str = UNKNOWN
    media_type: str = UNKNOWN
    device_id: str | None = None
    experiment_id: str | None = None
    storage_reference: StorageReference | None = None
    size_bytes: int | None = None
    mtime_ns: int | None = None
    review_state: str = REVIEW_UNKNOWN
    metadata: Mapping[str, Any] = field(default_factory=dict)
    claims: tuple[MetadataClaim, ...] = ()

    def __post_init__(self) -> None:
        _require_non_empty_string(self.artifact_id, 'artifact_id')
        _require_non_empty_string(self.role, 'role')
        _require_non_empty_string(self.category, 'category')
        _require_non_empty_string(self.extension, 'extension')
        _require_non_empty_string(self.media_type, 'media_type')
        _require_optional_string(self.device_id, 'device_id')
        _require_optional_string(self.experiment_id, 'experiment_id')
        _require_review_state(self.review_state)
        _require_optional_non_negative_int(self.size_bytes, 'size_bytes')
        _require_optional_non_negative_int(self.mtime_ns, 'mtime_ns')
        if self.storage_reference is not None and not isinstance(
            self.storage_reference, StorageReference
        ):
            raise TypeError('storage_reference must be a StorageReference')
        object.__setattr__(self, 'metadata', _freeze(self.metadata))
        object.__setattr__(
            self,
            'claims',
            Device._validated_claims(self.claims, SUBJECT_ARTIFACT, self.artifact_id),
        )


@dataclass(frozen=True)
class Experiment:
    """An immutable persisted experiment with explicit identity and provenance."""

    experiment_id: str
    metadata: Mapping[str, Any]
    files_by_role: Mapping[str, tuple[StorageReference, ...]]
    warnings: tuple[str, ...] = ()
    confidence: float = 0.0
    needs_review: bool = False
    review_state: str = REVIEW_UNKNOWN
    parser_version: str | None = None
    claims: tuple[MetadataClaim, ...] = ()

    def __post_init__(self) -> None:
        _require_non_empty_string(self.experiment_id, 'experiment_id')
        _require_review_state(self.review_state)
        _require_optional_string(self.parser_version, 'parser_version')
        _require_bool(self.needs_review, 'needs_review')
        object.__setattr__(
            self, 'confidence', _require_finite_number(self.confidence, 'confidence')
        )
        object.__setattr__(self, 'metadata', _freeze(self.metadata))
        object.__setattr__(
            self,
            'files_by_role',
            _freeze(
                {
                    role: tuple(references)
                    for role, references in self.files_by_role.items()
                }
            ),
        )
        object.__setattr__(self, 'warnings', tuple(self.warnings))
        object.__setattr__(
            self,
            'claims',
            Device._validated_claims(
                self.claims, SUBJECT_EXPERIMENT, self.experiment_id
            ),
        )

        for references in self.files_by_role.values():
            if any(
                not isinstance(reference, StorageReference) for reference in references
            ):
                raise TypeError('files_by_role values must contain StorageReference')


def _claim_from_provenance(
    experiment_id: str, provenance: MetadataProvenance
) -> MetadataClaim:
    return MetadataClaim(
        subject_type=SUBJECT_EXPERIMENT,
        subject_id=experiment_id,
        field=provenance.field,
        value=_jsonable(provenance.value),
        source_type=provenance.source_type,
        source_reference=provenance.source,
        extraction_method=provenance.method,
        review_status=REVIEW_UNKNOWN,
    )


def experiment_from_proposal(  # noqa: PLR0913
    proposal: ExperimentImportProposal,
    *,
    experiment_id: str,
    storage_source_id: str = 'local',
    parser_version: str | None = None,
    review_state: str = REVIEW_UNKNOWN,
) -> Experiment:
    """Build an :class:`Experiment` from a proposal and an explicit ID."""

    index = build_search_index([proposal], experiment_ids=(experiment_id,))
    record = index.records[0]
    files_by_role = {
        role: tuple(
            StorageReference(storage_source_id=storage_source_id, relative_path=path)
            for path in paths
        )
        for role, paths in record.files_by_role.items()
    }
    return Experiment(
        experiment_id=experiment_id,
        metadata=dict(record.metadata),
        files_by_role=files_by_role,
        warnings=tuple(record.warnings),
        confidence=record.confidence,
        needs_review=record.needs_review,
        review_state=review_state,
        parser_version=parser_version,
        claims=tuple(
            _claim_from_provenance(experiment_id, provenance)
            for provenance in proposal.metadata_provenance
        ),
    )


@dataclass(frozen=True)
class CatalogSnapshot:
    """A complete, immutable snapshot used to replace the canonical catalog."""

    experiments: tuple[Experiment, ...]
    devices: tuple[Device, ...] = ()
    artifacts: tuple[Artifact, ...] = ()
    relationships: tuple[Relationship, ...] = ()

    def __post_init__(self) -> None:
        experiments = tuple(self.experiments)
        devices = tuple(self.devices)
        artifacts = tuple(self.artifacts)
        relationships = tuple(self.relationships)
        if any(not isinstance(item, Experiment) for item in experiments):
            raise TypeError('experiments must contain Experiment values')
        if any(not isinstance(item, Device) for item in devices):
            raise TypeError('devices must contain Device values')
        if any(not isinstance(item, Artifact) for item in artifacts):
            raise TypeError('artifacts must contain Artifact values')
        if any(not isinstance(item, Relationship) for item in relationships):
            raise TypeError('relationships must contain Relationship values')
        self._require_unique_ids(
            [item.experiment_id for item in experiments], 'experiment'
        )
        self._require_unique_ids([item.device_id for item in devices], 'device')
        qualified: dict[tuple[str, str], str] = {}
        by_internal: dict[str, tuple[str | None, str | None]] = {}
        for device in devices:
            pair = (device.maker_namespace, device.local_device_id)
            if device.maker_namespace is not None and pair in qualified:
                raise ValueError('duplicate qualified device identity is not allowed')
            if device.maker_namespace is not None:
                qualified[pair] = device.device_id
            prior = by_internal.get(device.device_id)
            current = (device.maker_namespace, device.local_device_id)
            if prior is not None and prior != current:
                raise ValueError('device internal ID has conflicting qualifications')
            by_internal[device.device_id] = current
        self._require_unique_ids([item.artifact_id for item in artifacts], 'artifact')
        self._require_unique_ids(
            [item.relationship_id for item in relationships], 'relationship'
        )
        endpoint_ids = {
            SUBJECT_EXPERIMENT: {item.experiment_id for item in experiments},
            SUBJECT_DEVICE: {item.device_id for item in devices},
            SUBJECT_ARTIFACT: {item.artifact_id for item in artifacts},
            ENTITY_FILE: {
                deterministic_storage_reference_id(
                    storage_source_id=reference.storage_source_id,
                    relative_path=reference.relative_path,
                )
                for experiment in experiments
                for references in experiment.files_by_role.values()
                for reference in references
            }
            | {
                deterministic_storage_reference_id(
                    storage_source_id=reference.storage_source_id,
                    relative_path=reference.relative_path,
                )
                for artifact in artifacts
                if artifact.storage_reference is not None
                for reference in (artifact.storage_reference,)
            },
        }
        for relationship in relationships:
            for endpoint_type, endpoint_id in (
                (relationship.source_type, relationship.source_id),
                (relationship.target_type, relationship.target_id),
            ):
                if endpoint_type not in endpoint_ids:
                    raise ValueError(
                        f'unsupported relationship endpoint type: {endpoint_type!r}'
                    )
                if endpoint_id not in endpoint_ids[endpoint_type]:
                    raise ValueError(
                        f'dangling relationship endpoint: {endpoint_type}:{endpoint_id}'
                    )
        object.__setattr__(self, 'experiments', experiments)
        object.__setattr__(self, 'devices', devices)
        object.__setattr__(self, 'artifacts', artifacts)
        object.__setattr__(self, 'relationships', relationships)

    @staticmethod
    def _require_unique_ids(ids: Sequence[str], kind: str) -> None:
        if any(not isinstance(value, str) or not value for value in ids):
            raise ValueError(f'{kind} IDs must be non-empty strings')
        if len(set(ids)) != len(ids):
            raise ValueError(f'duplicate {kind} IDs are not allowed')

    @classmethod
    def from_proposals(  # noqa: PLR0913
        cls,
        proposals: Sequence[ExperimentImportProposal],
        *,
        experiment_ids: Sequence[str],
        storage_source_id: str = 'local',
        parser_version: str | None = None,
        devices: Sequence[Device] = (),
        artifacts: Sequence[Artifact] = (),
        relationships: Sequence[Relationship] = (),
    ) -> CatalogSnapshot:
        """Build a snapshot from import proposals and explicit experiment IDs."""

        proposal_values = tuple(proposals)
        ids = tuple(experiment_ids)
        if len(ids) != len(proposal_values):
            raise ValueError('experiment_ids count must match proposals count')
        if any(not isinstance(value, str) or not value for value in ids):
            raise ValueError('experiment_ids must contain non-empty strings')
        if len(set(ids)) != len(ids):
            raise ValueError('duplicate experiment IDs are not allowed')
        experiments = tuple(
            experiment_from_proposal(
                proposal,
                experiment_id=experiment_id,
                storage_source_id=storage_source_id,
                parser_version=parser_version,
            )
            for proposal, experiment_id in zip(proposal_values, ids, strict=True)
        )
        lineage_relationships = tuple(
            Relationship(
                source_type=ENTITY_FILE,
                source_id=deterministic_storage_reference_id(
                    storage_source_id=storage_source_id,
                    relative_path=edge.source,
                ),
                predicate=edge.relation,
                target_type=ENTITY_FILE,
                target_id=deterministic_storage_reference_id(
                    storage_source_id=storage_source_id,
                    relative_path=edge.target,
                ),
                provenance_source=None,
                review_state=REVIEW_UNKNOWN,
            )
            for proposal in proposal_values
            for edge in proposal.lineage
        )
        return cls(
            experiments=experiments,
            devices=tuple(devices),
            artifacts=tuple(artifacts),
            relationships=lineage_relationships + tuple(relationships),
        )


def _to_search_record(
    experiment: Experiment, lineage: tuple[Relationship, ...]
) -> ExperimentSearchRecord:
    file_paths = {
        deterministic_storage_reference_id(
            storage_source_id=reference.storage_source_id,
            relative_path=reference.relative_path,
        ): reference.relative_path
        for references in experiment.files_by_role.values()
        for reference in references
    }
    return ExperimentSearchRecord(
        experiment_id=experiment.experiment_id,
        metadata=experiment.metadata,
        files_by_role={
            role: tuple(reference.relative_path for reference in references)
            for role, references in experiment.files_by_role.items()
        },
        lineage=tuple(
            SearchLineageEdge(
                file_paths.get(edge.source_id, edge.source_id),
                file_paths.get(edge.target_id, edge.target_id),
                edge.predicate,
            )
            for edge in lineage
        ),
        warnings=experiment.warnings,
        confidence=experiment.confidence,
        needs_review=experiment.needs_review,
    )


def _experiment_lineage(
    experiment: Experiment, relationships: Sequence[Relationship]
) -> tuple[Relationship, ...]:
    file_ids = {
        deterministic_storage_reference_id(
            storage_source_id=reference.storage_source_id,
            relative_path=reference.relative_path,
        )
        for references in experiment.files_by_role.values()
        for reference in references
    }
    return tuple(
        edge
        for edge in relationships
        if edge.source_type == ENTITY_FILE
        and edge.target_type == ENTITY_FILE
        and edge.source_id in file_ids
        and edge.target_id in file_ids
    )


@runtime_checkable
class CatalogStore(Protocol):
    """Storage-agnostic scientific catalog persistence boundary."""

    def rebuild(self, snapshot: CatalogSnapshot) -> CatalogSnapshot:
        """Atomically replace the canonical catalog and return its snapshot."""

    def snapshot(self) -> CatalogSnapshot:
        """Return the canonical catalog snapshot."""

    def get_experiment(self, experiment_id: str) -> Experiment | None:
        """Return one persisted experiment."""

    def get_device(self, device_id: str) -> Device | None:
        """Return one persisted device."""

    def list_devices(self) -> tuple[Device, ...]:
        """Return persisted devices in canonical order."""

    def get_device_by_identity(self, namespace: str, local: str) -> Device | None:
        """Return one persisted maker-qualified device."""

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        """Return one persisted artifact."""

    def list_artifacts(self, *, device_id: str | None = None) -> tuple[Artifact, ...]:
        """Return persisted artifacts in canonical order, optionally by device."""

    def get_provenance(
        self, subject_type: str, subject_id: str
    ) -> tuple[MetadataClaim, ...]:
        """Return persisted claims for one subject."""

    def get_lineage(self, entity_type: str, entity_id: str) -> tuple[Relationship, ...]:
        """Return persisted relationships touching one entity."""

    def get_device_experiments(
        self, device_id: str
    ) -> tuple[ExperimentSearchRecord, ...]:
        """Return search records for experiments explicitly measured on a device."""

    def search_experiments(
        self, *, filters: Mapping[str, Any] | None = None
    ) -> tuple[ExperimentSearchRecord, ...]:
        """Search persisted experiments with the canonical search semantics."""


def _claim_from_row(row: sqlite3.Row) -> MetadataClaim:
    reviewed_value = _UNSET
    if row['reviewed_value_json'] is not None:
        reviewed_value = _json_loads(row['reviewed_value_json'])
    return MetadataClaim(
        subject_type=row['subject_type'],
        subject_id=row['subject_id'],
        field=row['field'],
        value=_json_loads(row['value_json']),
        source_type=row['source_type'],
        source_reference=row['source_reference'],
        extraction_method=row['extraction_method'],
        confidence=row['confidence'],
        category=row['category'],
        evidence=tuple(_json_loads(row['evidence_json'])),
        review_status=row['review_status'],
        reviewed_value=reviewed_value,
    )


def _relationship_from_row(row: sqlite3.Row) -> Relationship:
    return Relationship(
        relationship_id=row['relationship_id'],
        source_type=row['source_type'],
        source_id=row['source_id'],
        predicate=row['predicate'],
        target_type=row['target_type'],
        target_id=row['target_id'],
        provenance_source=row['provenance_source'],
        review_state=row['review_state'],
    )


def _device_from_row(row: sqlite3.Row, claims: tuple[MetadataClaim, ...]) -> Device:
    return Device(
        device_id=row['device_id'],
        device_type=row['device_type'],
        aliases=tuple(_json_loads(row['aliases_json'])),
        review_state=row['review_state'],
        metadata=_json_loads(row['metadata_json']),
        claims=claims,
        maker_namespace=row['maker_namespace'],
        local_device_id=row['local_device_id'],
        display_label=row['display_label'],
    )


def _artifact_from_row(row: sqlite3.Row, claims: tuple[MetadataClaim, ...]) -> Artifact:
    storage_reference = None
    if row['storage_source_id'] is not None and row['relative_path'] is not None:
        storage_reference = StorageReference(
            storage_source_id=row['storage_source_id'],
            relative_path=row['relative_path'],
        )
    return Artifact(
        artifact_id=row['artifact_id'],
        role=row['role'],
        category=row['category'],
        extension=row['extension'],
        media_type=row['media_type'],
        device_id=row['device_id'],
        experiment_id=row['experiment_id'],
        storage_reference=storage_reference,
        size_bytes=row['size_bytes'],
        mtime_ns=row['mtime_ns'],
        review_state=row['review_state'],
        metadata=_json_loads(row['metadata_json']),
        claims=claims,
    )


class SQLiteCatalogStore:
    """Versioned, single-writer SQLite implementation of :class:`CatalogStore`."""

    def __init__(self, db_path: str | Path):
        self._path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._search_index_cache: ExperimentSearchIndex | None = None
        self._search_index_data_version: int | None = None

    def _invalidate_search_index(self) -> None:
        self._search_index_cache = None
        self._search_index_data_version = None

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            connection = sqlite3.connect(str(self._path), isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys = ON')
            self._initialize_schema(connection)
            self._conn = connection
        return self._conn

    def _initialize_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(_META_DDL)
        row = connection.execute(
            f'SELECT value FROM {_META_TABLE} WHERE key = ?', (_SCHEMA_KEY,)
        ).fetchone()
        if row is None:
            for ddl in _TABLES_DDL:
                connection.execute(ddl)
            connection.execute(_DEVICES_QUALIFIED_INDEX)
            violations = connection.execute('PRAGMA foreign_key_check').fetchall()
            if violations:
                raise ValueError(
                    f'foreign key check failed during migration: {violations!r}'
                )
            connection.execute(
                f'INSERT INTO {_META_TABLE} (key, value) VALUES (?, ?)',
                (_SCHEMA_KEY, str(SCHEMA_VERSION)),
            )
            return
        try:
            version = int(row['value'])
        except (TypeError, ValueError) as error:
            raise ValueError('catalog schema version is not an integer') from error
        if version not in (1, SCHEMA_VERSION):
            raise ValueError(f'unsupported catalog schema version: {version}')
        if version == 1:
            self._migrate_v1_to_v2(connection)
        for ddl in _TABLES_DDL:
            connection.execute(ddl)
        connection.execute(_DEVICES_QUALIFIED_INDEX)

    def _migrate_v1_to_v2(self, connection: sqlite3.Connection) -> None:
        """Copy the v1 devices table into the constrained v2 shape atomically."""

        foreign_keys_were_on = bool(
            connection.execute('PRAGMA foreign_keys').fetchone()[0]
        )
        if foreign_keys_were_on:
            connection.execute('PRAGMA foreign_keys = OFF')
        connection.execute('BEGIN IMMEDIATE')
        try:
            initial_violations = connection.execute(
                'PRAGMA foreign_key_check'
            ).fetchall()
            if initial_violations:
                raise ValueError(
                    f'foreign key check failed during migration: {initial_violations!r}'
                )
            connection.execute(
                _DEVICES_DDL.replace(
                    f'CREATE TABLE IF NOT EXISTS {_DEVICES_TABLE}',
                    'CREATE TABLE devices_v2',
                )
            )
            connection.execute(
                f"""
                INSERT INTO devices_v2 (
                    device_id, device_type, aliases_json, review_state, metadata_json,
                    maker_namespace, local_device_id, display_label, ordinal
                )
                SELECT device_id, device_type, aliases_json, review_state, metadata_json,
                       NULL, NULL, device_id, ordinal
                FROM {_DEVICES_TABLE}
                """
            )
            connection.execute(f'DROP TABLE {_DEVICES_TABLE}')
            connection.execute('ALTER TABLE devices_v2 RENAME TO devices')
            connection.execute(
                f'UPDATE {_META_TABLE} SET value = ? WHERE key = ?',
                (str(SCHEMA_VERSION), _SCHEMA_KEY),
            )
            connection.execute(_DEVICES_QUALIFIED_INDEX)
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            if foreign_keys_were_on:
                connection.execute('PRAGMA foreign_keys = ON')

    def __enter__(self) -> SQLiteCatalogStore:
        self._connection()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        self.close()
        return False

    def close(self) -> None:
        self._invalidate_search_index()
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def rebuild(self, snapshot: CatalogSnapshot) -> CatalogSnapshot:
        if not isinstance(snapshot, CatalogSnapshot):
            raise TypeError('snapshot must be a CatalogSnapshot')
        connection = self._connection()
        connection.execute('BEGIN IMMEDIATE')
        try:
            for table in _DELETE_ORDER:
                connection.execute(f'DELETE FROM {table}')
            self._insert_snapshot(connection, snapshot)
        except BaseException:
            connection.rollback()
            raise
        connection.commit()
        self._invalidate_search_index()
        return self.snapshot()

    def _insert_snapshot(
        self, connection: sqlite3.Connection, snapshot: CatalogSnapshot
    ) -> None:
        for ordinal, device in enumerate(snapshot.devices):
            connection.execute(
                f"""
                INSERT INTO {_DEVICES_TABLE} (
                    device_id, device_type, aliases_json, review_state,
                    metadata_json, maker_namespace, local_device_id,
                    display_label, ordinal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device.device_id,
                    device.device_type,
                    _json_dumps(device.aliases),
                    device.review_state,
                    _json_dumps(device.metadata),
                    device.maker_namespace,
                    device.local_device_id,
                    device.display_label,
                    ordinal,
                ),
            )

        for ordinal, experiment in enumerate(snapshot.experiments):
            connection.execute(
                f"""
                INSERT INTO {_EXPERIMENTS_TABLE} (
                    experiment_id, metadata_json, warnings_json, confidence,
                    needs_review, review_state, parser_version, roles_json,
                    ordinal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment.experiment_id,
                    _json_dumps(experiment.metadata),
                    _json_dumps(experiment.warnings),
                    experiment.confidence,
                    int(experiment.needs_review),
                    experiment.review_state,
                    experiment.parser_version,
                    _json_dumps(tuple(experiment.files_by_role)),
                    ordinal,
                ),
            )

            file_ordinal = 0
            for role, references in experiment.files_by_role.items():
                for reference in references:
                    connection.execute(
                        f"""
                        INSERT INTO {_EXPERIMENT_FILES_TABLE} (
                            experiment_id, ordinal, role, storage_source_id,
                            relative_path
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            experiment.experiment_id,
                            file_ordinal,
                            role,
                            reference.storage_source_id,
                            reference.relative_path,
                        ),
                    )
                    file_ordinal += 1

        for ordinal, artifact in enumerate(snapshot.artifacts):
            storage_source_id = None
            relative_path = None
            if artifact.storage_reference is not None:
                storage_source_id = artifact.storage_reference.storage_source_id
                relative_path = artifact.storage_reference.relative_path
            connection.execute(
                f"""
                INSERT INTO {_ARTIFACTS_TABLE} (
                    artifact_id, role, category, extension, media_type,
                    device_id, experiment_id, storage_source_id, relative_path,
                    size_bytes, mtime_ns, review_state, metadata_json, ordinal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.artifact_id,
                    artifact.role,
                    artifact.category,
                    artifact.extension,
                    artifact.media_type,
                    artifact.device_id,
                    artifact.experiment_id,
                    storage_source_id,
                    relative_path,
                    artifact.size_bytes,
                    artifact.mtime_ns,
                    artifact.review_state,
                    _json_dumps(artifact.metadata),
                    ordinal,
                ),
            )

        for claims in (
            tuple(experiment.claims for experiment in snapshot.experiments)
            + tuple(device.claims for device in snapshot.devices)
            + tuple(artifact.claims for artifact in snapshot.artifacts)
        ):
            for claim_ordinal, claim in enumerate(claims):
                reviewed_value_json = (
                    None
                    if claim.reviewed_value is _UNSET
                    else _json_dumps(claim.reviewed_value)
                )
                connection.execute(
                    f"""
                    INSERT INTO {_CLAIMS_TABLE} (
                        subject_type, subject_id, ordinal, field, value_json,
                        source_type, source_reference, extraction_method,
                        confidence, category, evidence_json, review_status,
                        reviewed_value_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        claim.subject_type,
                        claim.subject_id,
                        claim_ordinal,
                        claim.field,
                        _json_dumps(claim.value),
                        claim.source_type,
                        claim.source_reference,
                        claim.extraction_method,
                        claim.confidence,
                        claim.category,
                        _json_dumps(claim.evidence),
                        claim.review_status,
                        reviewed_value_json,
                    ),
                )

        for ordinal, relationship in enumerate(snapshot.relationships):
            connection.execute(
                f"""
                INSERT INTO {_RELATIONSHIPS_TABLE} (
                    relationship_id, source_type, source_id, predicate,
                    target_type, target_id, provenance_source, review_state,
                    ordinal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    relationship.relationship_id,
                    relationship.source_type,
                    relationship.source_id,
                    relationship.predicate,
                    relationship.target_type,
                    relationship.target_id,
                    relationship.provenance_source,
                    relationship.review_state,
                    ordinal,
                ),
            )

    def snapshot(self) -> CatalogSnapshot:
        return CatalogSnapshot(
            experiments=self.list_experiments(),
            devices=self.list_devices(),
            artifacts=self.list_artifacts(),
            relationships=self.list_relationships(),
        )

    def _claims_by_subject(
        self, connection: sqlite3.Connection
    ) -> dict[tuple[str, str], tuple[MetadataClaim, ...]]:
        rows = connection.execute(
            f'SELECT * FROM {_CLAIMS_TABLE} '
            'ORDER BY subject_type ASC, subject_id ASC, ordinal ASC'
        ).fetchall()
        grouped: dict[tuple[str, str], list[MetadataClaim]] = {}
        for row in rows:
            grouped.setdefault((row['subject_type'], row['subject_id']), []).append(
                _claim_from_row(row)
            )
        return {key: tuple(items) for key, items in grouped.items()}

    def _experiment_from_row(
        self,
        row: sqlite3.Row,
        files: Sequence[sqlite3.Row],
        claims: tuple[MetadataClaim, ...],
    ) -> Experiment:
        files_by_role: dict[str, list[StorageReference]] = {
            role: [] for role in _json_loads(row['roles_json'])
        }
        for file_row in files:
            files_by_role.setdefault(file_row['role'], []).append(
                StorageReference(
                    storage_source_id=file_row['storage_source_id'],
                    relative_path=file_row['relative_path'],
                )
            )
        return Experiment(
            experiment_id=row['experiment_id'],
            metadata=_json_loads(row['metadata_json']),
            files_by_role={
                role: tuple(references) for role, references in files_by_role.items()
            },
            warnings=tuple(_json_loads(row['warnings_json'])),
            confidence=row['confidence'],
            needs_review=bool(row['needs_review']),
            review_state=row['review_state'],
            parser_version=row['parser_version'],
            claims=claims,
        )

    def get_experiment(self, experiment_id: str) -> Experiment | None:
        _require_non_empty_string(experiment_id, 'experiment_id')
        connection = self._connection()
        row = connection.execute(
            f'SELECT * FROM {_EXPERIMENTS_TABLE} WHERE experiment_id = ?',
            (experiment_id,),
        ).fetchone()
        if row is None:
            return None
        files = connection.execute(
            f'SELECT * FROM {_EXPERIMENT_FILES_TABLE} WHERE experiment_id = ? '
            'ORDER BY ordinal ASC',
            (experiment_id,),
        ).fetchall()
        claims = self.get_provenance(SUBJECT_EXPERIMENT, experiment_id)
        return self._experiment_from_row(row, files, claims)

    def list_experiments(self) -> tuple[Experiment, ...]:
        connection = self._connection()
        rows = connection.execute(
            f'SELECT * FROM {_EXPERIMENTS_TABLE} ORDER BY ordinal ASC'
        ).fetchall()
        files_by_experiment: dict[str, list[sqlite3.Row]] = {}
        for file_row in connection.execute(
            f'SELECT * FROM {_EXPERIMENT_FILES_TABLE} '
            'ORDER BY experiment_id ASC, ordinal ASC'
        ).fetchall():
            files_by_experiment.setdefault(file_row['experiment_id'], []).append(
                file_row
            )
        claims_by_subject = self._claims_by_subject(connection)
        return tuple(
            self._experiment_from_row(
                row,
                files_by_experiment.get(row['experiment_id'], ()),
                claims_by_subject.get((SUBJECT_EXPERIMENT, row['experiment_id']), ()),
            )
            for row in rows
        )

    def list_devices(self) -> tuple[Device, ...]:
        connection = self._connection()
        rows = connection.execute(
            f'SELECT * FROM {_DEVICES_TABLE} ORDER BY ordinal ASC'
        ).fetchall()
        claims_by_subject = self._claims_by_subject(connection)
        return tuple(
            _device_from_row(
                row, claims_by_subject.get((SUBJECT_DEVICE, row['device_id']), ())
            )
            for row in rows
        )

    def get_device(self, device_id: str) -> Device | None:
        _require_non_empty_string(device_id, 'device_id')
        row = (
            self._connection()
            .execute(
                f'SELECT * FROM {_DEVICES_TABLE} WHERE device_id = ?',
                (device_id,),
            )
            .fetchone()
        )
        if row is None:
            return None
        return _device_from_row(row, self.get_provenance(SUBJECT_DEVICE, device_id))

    def get_device_by_identity(self, namespace: str, local: str) -> Device | None:
        _require_non_empty_string(namespace, 'namespace')
        _require_non_empty_string(local, 'local')
        row = (
            self._connection()
            .execute(
                f'SELECT * FROM {_DEVICES_TABLE} WHERE maker_namespace = ? AND local_device_id = ?',
                (namespace, local),
            )
            .fetchone()
        )
        if row is None:
            return None
        return _device_from_row(
            row, self.get_provenance(SUBJECT_DEVICE, row['device_id'])
        )

    def list_artifacts(self, *, device_id: str | None = None) -> tuple[Artifact, ...]:
        """Return persisted artifacts in canonical order, optionally by device."""
        if device_id is not None:
            _require_non_empty_string(device_id, 'device_id')
        connection = self._connection()
        if device_id is None:
            rows = connection.execute(
                f'SELECT * FROM {_ARTIFACTS_TABLE} ORDER BY ordinal ASC'
            ).fetchall()
        else:
            rows = connection.execute(
                f'SELECT * FROM {_ARTIFACTS_TABLE} WHERE device_id = ? '
                'ORDER BY ordinal ASC',
                (device_id,),
            ).fetchall()
        claims_by_subject = self._claims_by_subject(connection)
        return tuple(
            _artifact_from_row(
                row,
                claims_by_subject.get((SUBJECT_ARTIFACT, row['artifact_id']), ()),
            )
            for row in rows
        )

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        _require_non_empty_string(artifact_id, 'artifact_id')
        row = (
            self._connection()
            .execute(
                f'SELECT * FROM {_ARTIFACTS_TABLE} WHERE artifact_id = ?',
                (artifact_id,),
            )
            .fetchone()
        )
        if row is None:
            return None
        return _artifact_from_row(
            row, self.get_provenance(SUBJECT_ARTIFACT, artifact_id)
        )

    def get_provenance(
        self, subject_type: str, subject_id: str
    ) -> tuple[MetadataClaim, ...]:
        _require_non_empty_string(subject_type, 'subject_type')
        _require_non_empty_string(subject_id, 'subject_id')
        rows = (
            self._connection()
            .execute(
                f'SELECT * FROM {_CLAIMS_TABLE} WHERE subject_type = ? '
                'AND subject_id = ? ORDER BY ordinal ASC',
                (subject_type, subject_id),
            )
            .fetchall()
        )
        return tuple(_claim_from_row(row) for row in rows)

    def get_lineage(self, entity_type: str, entity_id: str) -> tuple[Relationship, ...]:
        _require_non_empty_string(entity_type, 'entity_type')
        _require_non_empty_string(entity_id, 'entity_id')
        rows = (
            self._connection()
            .execute(
                f'SELECT * FROM {_RELATIONSHIPS_TABLE} '
                'WHERE (source_type = ? AND source_id = ?) '
                'OR (target_type = ? AND target_id = ?) ORDER BY ordinal ASC',
                (entity_type, entity_id, entity_type, entity_id),
            )
            .fetchall()
        )
        return tuple(_relationship_from_row(row) for row in rows)

    def get_device_experiments(
        self, device_id: str
    ) -> tuple[ExperimentSearchRecord, ...]:
        """Return search records for experiments explicitly measured on a device.

        Relationships and experiments are read inside one transaction so a
        concurrent rebuild on another connection cannot interleave snapshots.
        """
        _require_non_empty_string(device_id, 'device_id')
        connection = self._connection()
        connection.execute('BEGIN')
        records: list[ExperimentSearchRecord] = []
        try:
            experiment_ids = tuple(
                row['source_id']
                for row in connection.execute(
                    f'SELECT DISTINCT source_id FROM {_RELATIONSHIPS_TABLE} '
                    'WHERE source_type = ? AND predicate = ? '
                    'AND target_type = ? AND target_id = ? '
                    'ORDER BY source_id ASC',
                    (SUBJECT_EXPERIMENT, 'measured_on', SUBJECT_DEVICE, device_id),
                ).fetchall()
            )
            if experiment_ids:
                relationships = tuple(
                    _relationship_from_row(row)
                    for row in connection.execute(
                        f'SELECT * FROM {_RELATIONSHIPS_TABLE} '
                        'WHERE source_type = ? AND target_type = ? '
                        'ORDER BY ordinal ASC',
                        (ENTITY_FILE, ENTITY_FILE),
                    ).fetchall()
                )
                placeholders = ', '.join('?' for _ in experiment_ids)
                rows = connection.execute(
                    f'SELECT * FROM {_EXPERIMENTS_TABLE} '
                    f'WHERE experiment_id IN ({placeholders}) '
                    'ORDER BY experiment_id ASC',
                    experiment_ids,
                ).fetchall()
                files_by_experiment: dict[str, list[sqlite3.Row]] = {}
                for file_row in connection.execute(
                    f'SELECT * FROM {_EXPERIMENT_FILES_TABLE} '
                    f'WHERE experiment_id IN ({placeholders}) '
                    'ORDER BY experiment_id ASC, ordinal ASC',
                    experiment_ids,
                ).fetchall():
                    files_by_experiment.setdefault(
                        file_row['experiment_id'], []
                    ).append(file_row)
                for row in rows:
                    experiment = self._experiment_from_row(
                        row,
                        files_by_experiment.get(row['experiment_id'], ()),
                        (),
                    )
                    records.append(
                        _to_search_record(
                            experiment,
                            _experiment_lineage(experiment, relationships),
                        )
                    )
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        return _search_experiments(ExperimentSearchIndex(records=records), filters=None)

    def list_claims(self) -> tuple[MetadataClaim, ...]:
        rows = (
            self._connection()
            .execute(
                f'SELECT * FROM {_CLAIMS_TABLE} '
                'ORDER BY subject_type ASC, subject_id ASC, ordinal ASC'
            )
            .fetchall()
        )
        return tuple(_claim_from_row(row) for row in rows)

    def list_relationships(self) -> tuple[Relationship, ...]:
        rows = (
            self._connection()
            .execute(f'SELECT * FROM {_RELATIONSHIPS_TABLE} ORDER BY ordinal ASC')
            .fetchall()
        )
        return tuple(_relationship_from_row(row) for row in rows)

    def list_storage_references(self) -> tuple[StorageReference, ...]:
        rows = (
            self._connection()
            .execute(
                f'SELECT storage_source_id, relative_path FROM {_EXPERIMENT_FILES_TABLE} '
                f'UNION SELECT storage_source_id, relative_path FROM {_ARTIFACTS_TABLE} '
                'WHERE storage_source_id IS NOT NULL AND relative_path IS NOT NULL '
                'ORDER BY storage_source_id ASC, relative_path ASC'
            )
            .fetchall()
        )
        return tuple(
            StorageReference(
                storage_source_id=row['storage_source_id'],
                relative_path=row['relative_path'],
            )
            for row in rows
        )

    def _search_index(self) -> ExperimentSearchIndex:
        connection = self._connection()
        data_version = int(connection.execute('PRAGMA data_version').fetchone()[0])
        if (
            self._search_index_cache is not None
            and self._search_index_data_version == data_version
        ):
            return self._search_index_cache
        connection.execute('BEGIN')
        try:
            relationships = tuple(
                _relationship_from_row(row)
                for row in connection.execute(
                    f'SELECT * FROM {_RELATIONSHIPS_TABLE} '
                    'WHERE source_type = ? AND target_type = ? '
                    'ORDER BY ordinal ASC',
                    (ENTITY_FILE, ENTITY_FILE),
                ).fetchall()
            )
            experiments = self.list_experiments()
            records = tuple(
                _to_search_record(
                    experiment, _experiment_lineage(experiment, relationships)
                )
                for experiment in experiments
            )
            index = ExperimentSearchIndex(records=records)
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        self._search_index_cache = index
        self._search_index_data_version = data_version
        return index

    def search_experiments(
        self, *, filters: Mapping[str, Any] | None = None
    ) -> tuple[ExperimentSearchRecord, ...]:
        return _search_experiments(self._search_index(), filters=filters)

    def find_related_files(
        self, experiment_id: str, *, role: str | None = None
    ) -> tuple[RelatedFile, ...]:
        return _find_related_files(self._search_index(), experiment_id, role=role)


def open_read_only_catalog(db_path: str | Path) -> SQLiteCatalogStore:
    """Open an existing catalog read-only without creating or migrating it.

    Serving requests must never trigger ``SQLiteCatalogStore``'s lazy schema
    initialization, which would create or migrate the database file. This
    factory bypasses that path and wires a ``mode=ro`` connection instead.
    """

    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f'catalog does not exist: {path}')
    store = SQLiteCatalogStore(path)
    connection = sqlite3.connect(
        f'{path.resolve().as_uri()}?mode=ro', uri=True, isolation_level=None
    )
    connection.row_factory = sqlite3.Row
    store._conn = connection  # noqa: SLF001 - read-only wiring for serving
    return store
