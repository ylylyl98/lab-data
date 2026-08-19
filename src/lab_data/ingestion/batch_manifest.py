"""Versioned local persistence for one deterministic planned batch."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from lab_data.ingestion.batch_planner import PlannedBatch

__all__ = [
    'BatchManifest',
    'CanonicalFile',
    'ManifestFile',
    'ManifestStatus',
    'create_batch_manifest',
    'manifest_from_dict',
    'manifest_to_dict',
    'read_batch_manifest',
    'write_batch_manifest',
]

MANIFEST_VERSION = 1


class ManifestStatus(str, Enum):
    """Supported durable states for a batch manifest."""

    PLANNED = 'planned'
    PREFLIGHT_PASSED = 'preflight_passed'
    UPLOAD_CREATED = 'upload_created'
    PROCESSING = 'processing'
    SUCCESS = 'success'
    PROCESSING_FAILED = 'processing_failed'
    VERIFICATION_FAILED = 'verification_failed'


@dataclass(frozen=True)
class CanonicalFile:
    """Storage-agnostic experiment file identity."""

    source_path: str
    relative_path: str
    role: str


@dataclass(frozen=True)
class ManifestFile:
    """Legacy explicit source-to-transport destination mapping.

    This form remains supported for compatibility. New metadata-only manifests
    should use :class:`CanonicalFile` instead.
    """

    source_path: str
    destination_path: str
    role: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _validate_utc_timestamp(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f'{field_name} must be an ISO-8601 UTC string')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise ValueError(
            f'{field_name} must be an ISO-8601 UTC string'
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(f'{field_name} must include UTC timezone information')
    return value


def _manifest_file_to_dict(
    file: CanonicalFile | ManifestFile,
) -> dict[str, str]:
    if isinstance(file, CanonicalFile):
        return {
            'source_path': file.source_path,
            'relative_path': file.relative_path,
            'role': file.role,
        }
    return {
        'source_path': file.source_path,
        'destination_path': file.destination_path,
        'role': file.role,
    }


def _manifest_file_from_dict(data: Any) -> CanonicalFile | ManifestFile:
    if not isinstance(data, Mapping):
        raise ValueError('manifest file must be a JSON object')
    common = {'source_path', 'role'}
    if set(data) == common | {'relative_path'}:
        values = [data[name] for name in common | {'relative_path'}]
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError('manifest file fields must be non-empty strings')
        return CanonicalFile(
            source_path=data['source_path'],
            relative_path=data['relative_path'],
            role=data['role'],
        )
    required = common | {'destination_path'}
    if set(data) != required:
        raise ValueError('manifest file has missing or unknown fields')
    values = [data[name] for name in required]
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError('manifest file fields must be non-empty strings')
    return ManifestFile(
        source_path=data['source_path'],
        destination_path=data['destination_path'],
        role=data['role'],
    )


@dataclass(frozen=True)
class BatchManifest:
    """Immutable, versioned local state for one planned batch."""

    batch_id: str
    batch_number: int
    dataset_label: str | None
    status: ManifestStatus
    proposal_ids: tuple[str, ...]
    archive_files: tuple[CanonicalFile | ManifestFile, ...]
    companion_files: tuple[CanonicalFile | ManifestFile, ...]
    expected_entry_count: int
    expected_file_count: int
    publish: bool
    upload_name: str | None
    upload_id: str | None = None
    entry_ids: tuple[tuple[str, str], ...] = ()
    processing_status: str | None = None
    verification_status: str | None = None
    created_utc: str = field(default_factory=_utc_now)
    updated_utc: str = field(default_factory=_utc_now)
    manifest_version: int = MANIFEST_VERSION

    @classmethod
    def from_planned_batch(  # noqa: PLR0913
        cls,
        planned_batch: PlannedBatch,
        *,
        archive_files: Sequence[CanonicalFile | ManifestFile] = (),
        companion_files: Sequence[CanonicalFile | ManifestFile] = (),
        publish: bool = False,
        upload_name: str | None = None,
        created_utc: str | None = None,
        updated_utc: str | None = None,
    ) -> BatchManifest:
        """Create planned local state from an existing planned batch."""

        created = created_utc or _utc_now()
        updated = updated_utc or created
        return cls(
            batch_id=planned_batch.batch_id,
            batch_number=planned_batch.batch_number,
            dataset_label=planned_batch.dataset_label,
            status=ManifestStatus.PLANNED,
            proposal_ids=planned_batch.proposals,
            archive_files=tuple(archive_files),
            companion_files=tuple(companion_files),
            expected_entry_count=len(planned_batch.proposals),
            expected_file_count=len(archive_files) + len(companion_files),
            publish=publish,
            upload_name=upload_name,
            created_utc=created,
            updated_utc=updated,
        )


def create_batch_manifest(  # noqa: PLR0913
    planned_batch: PlannedBatch,
    *,
    archive_files: Sequence[CanonicalFile | ManifestFile] = (),
    companion_files: Sequence[CanonicalFile | ManifestFile] = (),
    publish: bool = False,
    upload_name: str | None = None,
    created_utc: str | None = None,
    updated_utc: str | None = None,
) -> BatchManifest:
    """Construct a planned manifest without scanning or touching files."""

    return BatchManifest.from_planned_batch(
        planned_batch,
        archive_files=archive_files,
        companion_files=companion_files,
        publish=publish,
        upload_name=upload_name,
        created_utc=created_utc,
        updated_utc=updated_utc,
    )


def manifest_to_dict(manifest: BatchManifest) -> dict[str, Any]:
    """Convert a manifest to a deterministic JSON-compatible dictionary."""

    return {
        'manifest_version': manifest.manifest_version,
        'batch_id': manifest.batch_id,
        'batch_number': manifest.batch_number,
        'dataset_label': manifest.dataset_label,
        'status': manifest.status.value,
        'proposal_ids': list(manifest.proposal_ids),
        'archive_files': [
            _manifest_file_to_dict(file) for file in manifest.archive_files
        ],
        'companion_files': [
            _manifest_file_to_dict(file) for file in manifest.companion_files
        ],
        'expected_entry_count': manifest.expected_entry_count,
        'expected_file_count': manifest.expected_file_count,
        'publish': manifest.publish,
        'upload_name': manifest.upload_name,
        'upload_id': manifest.upload_id,
        'entry_ids': [
            {'proposal_id': proposal_id, 'entry_id': entry_id}
            for proposal_id, entry_id in manifest.entry_ids
        ],
        'processing_status': manifest.processing_status,
        'verification_status': manifest.verification_status,
        'created_utc': manifest.created_utc,
        'updated_utc': manifest.updated_utc,
    }


def _require_string(data: Mapping[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f'{name} must be a non-empty string')
    return value


def _require_non_negative_int(data: Mapping[str, Any], name: str) -> int:
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f'{name} must be a non-negative integer')
    return value


def manifest_from_dict(data: Any) -> BatchManifest:  # noqa: PLR0912
    """Validate and reconstruct a manifest from a JSON-compatible object."""

    if not isinstance(data, Mapping):
        raise ValueError('manifest must be a top-level JSON object')
    required = set(manifest_to_dict(BatchManifest(
        batch_id='placeholder',
        batch_number=1,
        dataset_label=None,
        status=ManifestStatus.PLANNED,
        proposal_ids=(),
        archive_files=(),
        companion_files=(),
        expected_entry_count=0,
        expected_file_count=0,
        publish=False,
        upload_name=None,
        created_utc='2000-01-01T00:00:00Z',
        updated_utc='2000-01-01T00:00:00Z',
    )))
    if set(data) != required:
        raise ValueError('manifest has missing or unknown fields')
    if data['manifest_version'] != MANIFEST_VERSION:
        raise ValueError(f'unsupported manifest version: {data["manifest_version"]!r}')

    batch_number = data['batch_number']
    if isinstance(batch_number, bool) or not isinstance(batch_number, int) or batch_number < 1:
        raise ValueError('batch_number must be a positive integer')
    dataset_label = data['dataset_label']
    if dataset_label is not None and not isinstance(dataset_label, str):
        raise ValueError('dataset_label must be a string or null')
    try:
        status = ManifestStatus(data['status'])
    except (TypeError, ValueError) as error:
        raise ValueError(f'invalid manifest status: {data["status"]!r}') from error

    proposal_ids = data['proposal_ids']
    if not isinstance(proposal_ids, list) or any(
        not isinstance(item, str) for item in proposal_ids
    ):
        raise ValueError('proposal_ids must be an ordered list of strings')
    archive_files = data['archive_files']
    companion_files = data['companion_files']
    if not isinstance(archive_files, list) or not isinstance(companion_files, list):
        raise ValueError('archive_files and companion_files must be lists')
    entry_ids = data['entry_ids']
    if not isinstance(entry_ids, list):
        raise ValueError('entry_ids must be an ordered list')
    parsed_entry_ids = []
    for item in entry_ids:
        if not isinstance(item, Mapping) or set(item) != {'proposal_id', 'entry_id'}:
            raise ValueError('entry_ids items must map proposal_id to entry_id')
        if not isinstance(item['proposal_id'], str) or not isinstance(item['entry_id'], str):
            raise ValueError('entry_ids values must be strings')
        parsed_entry_ids.append((item['proposal_id'], item['entry_id']))
    if not isinstance(data['publish'], bool):
        raise ValueError('publish must be a boolean')
    for name in ('upload_name', 'upload_id', 'processing_status', 'verification_status'):
        if data[name] is not None and not isinstance(data[name], str):
            raise ValueError(f'{name} must be a string or null')

    return BatchManifest(
        manifest_version=MANIFEST_VERSION,
        batch_id=_require_string(data, 'batch_id'),
        batch_number=batch_number,
        dataset_label=dataset_label,
        status=status,
        proposal_ids=tuple(proposal_ids),
        archive_files=tuple(_manifest_file_from_dict(item) for item in archive_files),
        companion_files=tuple(
            _manifest_file_from_dict(item) for item in companion_files
        ),
        expected_entry_count=_require_non_negative_int(data, 'expected_entry_count'),
        expected_file_count=_require_non_negative_int(data, 'expected_file_count'),
        publish=data['publish'],
        upload_name=data['upload_name'],
        upload_id=data['upload_id'],
        entry_ids=tuple(parsed_entry_ids),
        processing_status=data['processing_status'],
        verification_status=data['verification_status'],
        created_utc=_validate_utc_timestamp(data['created_utc'], 'created_utc'),
        updated_utc=_validate_utc_timestamp(data['updated_utc'], 'updated_utc'),
    )


def write_batch_manifest(manifest: BatchManifest, path: Path | str) -> Path:
    """Write a manifest once, refusing to overwrite an existing path."""

    target = Path(path)
    if target.exists():
        raise FileExistsError(f'refusing to overwrite manifest: {target}')
    payload = json.dumps(
        manifest_to_dict(manifest),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    target.write_text(payload + '\n', encoding='utf-8')
    return target


def read_batch_manifest(path: Path | str) -> BatchManifest:
    """Read and validate a UTF-8 JSON batch manifest."""

    target = Path(path)
    try:
        data = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f'invalid batch manifest: {target}') from error
    return manifest_from_dict(data)
