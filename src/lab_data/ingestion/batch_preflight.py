"""Read-only validation for a prepared local batch manifest."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from nomad.datamodel import EntryArchive

from lab_data.ingestion.batch_manifest import (
    BatchManifest,
    CanonicalFile,
    ManifestFile,
    ManifestStatus,
)

__all__ = [
    'PreflightResult',
    'mark_preflight_passed',
    'preflight_batch',
]

_DRIVE_PATH = re.compile(r'^[A-Za-z]:')


@dataclass(frozen=True)
class PreflightResult:
    """Deterministic outcome of validating one local batch."""

    passed: bool
    batch_id: str
    archive_count: int
    companion_count: int
    total_file_count: int
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _relative_path_error(relative_path: str) -> str | None:
    if not relative_path:
        return 'relative path is empty'
    normalized = relative_path.replace('\\', '/')
    if (
        normalized.startswith('/')
        or normalized.startswith('//')
        or _DRIVE_PATH.match(normalized)
    ):
        return f'unsafe absolute relative path: {relative_path}'
    if '..' in normalized.split('/'):
        return f'unsafe traversal relative path: {relative_path}'
    return None


def _transport_error(destination: str) -> str | None:
    error = _relative_path_error(destination)
    if error is None:
        return None
    return error.replace('relative path', 'transport destination')


def _add_file_errors(manifest: BatchManifest) -> list[str]:
    errors: list[str] = []
    canonical_paths: dict[str, str] = {}
    transport_destinations: dict[str, str] = {}
    for file in (*manifest.archive_files, *manifest.companion_files):
        source = Path(file.source_path)
        if not source.exists():
            errors.append(f'missing source file: {file.source_path}')
        elif not source.is_file():
            errors.append(f'source is not a regular file: {file.source_path}')
        relative_path = (
            file.relative_path
            if isinstance(file, CanonicalFile)
            else file.destination_path
        )
        relative_error = _relative_path_error(relative_path)
        if relative_error:
            errors.append(relative_error)
        normalized_relative_path = relative_path.replace('\\', '/')
        prior_source = canonical_paths.get(normalized_relative_path)
        if prior_source is not None:
            errors.append(
                'duplicate canonical relative path: '
                f'{normalized_relative_path} ({prior_source} and {file.source_path})'
            )
        else:
            canonical_paths[normalized_relative_path] = file.source_path
        if isinstance(file, ManifestFile):
            transport_error = _transport_error(file.destination_path)
            if transport_error:
                errors.append(transport_error)
            normalized_destination = file.destination_path.replace('\\', '/')
            prior_source = transport_destinations.get(normalized_destination)
            if prior_source is not None:
                errors.append(
                    'duplicate transport destination: '
                    f'{normalized_destination} ({prior_source} and {file.source_path})'
                )
            else:
                transport_destinations[normalized_destination] = file.source_path
    return errors


def _archive_data(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(payload, dict):
            raise ValueError('archive top level is not an object')
        archive = EntryArchive.m_from_dict(payload)
        if archive.data is None:
            raise ValueError('archive data section is missing')
        data = payload.get('data')
        if not isinstance(data, dict):
            raise ValueError('archive data section is not an object')
        return data
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f'archive read-back failed: {path}: {error}') from error


def _review_errors(data: dict[str, Any], path: Path) -> list[str]:
    errors: list[str] = []
    review = data.get('ingestion_review')
    if not isinstance(review, dict):
        return [f'missing ingestion review: {path}']
    if review.get('needs_review') is not False:
        errors.append(f'archive needs review: {path}')
    warnings = review.get('warnings')
    if warnings:
        errors.append(f'archive has review warnings: {path}')
    for field in ('unresolved_metadata', 'unresolved_relationships', 'conflicts'):
        if data.get(field):
            errors.append(f'archive has {field}: {path}')
    return errors


def _read_archive_errors(manifest: BatchManifest) -> list[str]:
    errors: list[str] = []
    for file in manifest.archive_files:
        try:
            data = _archive_data(Path(file.source_path))
        except ValueError as error:
            errors.append(str(error))
            continue
        errors.extend(_review_errors(data, Path(file.source_path)))
    return errors


def _unique_sorted(errors: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(errors)))


def preflight_batch(manifest: BatchManifest) -> PreflightResult:
    """Validate a planned manifest without network or persistence side effects."""

    errors: list[str] = []
    if manifest.status is not ManifestStatus.PLANNED:
        errors.append(f'manifest status is not planned: {manifest.status.value}')
    if manifest.expected_entry_count != len(manifest.proposal_ids):
        errors.append('expected entry count does not match proposal count')
    if not manifest.proposal_ids:
        errors.append('batch contains no proposals')
    if len(set(manifest.proposal_ids)) != len(manifest.proposal_ids):
        errors.append('proposal IDs are not unique')
    if len(manifest.archive_files) != manifest.expected_entry_count:
        errors.append('archive count does not match expected entry count')

    all_files = (*manifest.archive_files, *manifest.companion_files)
    if manifest.expected_file_count != len(all_files):
        errors.append('expected file count does not match represented file count')
    errors.extend(_add_file_errors(manifest))
    errors.extend(_read_archive_errors(manifest))

    archive_count = len(manifest.archive_files)
    companion_count = len(manifest.companion_files)
    ordered_errors = _unique_sorted(errors)
    return PreflightResult(
        passed=not ordered_errors,
        batch_id=manifest.batch_id,
        archive_count=archive_count,
        companion_count=companion_count,
        total_file_count=len(all_files),
        errors=ordered_errors,
    )


def mark_preflight_passed(
    manifest: BatchManifest, result: PreflightResult
) -> BatchManifest:
    """Return a new preflight-passed manifest when validation succeeded."""

    if not result.passed:
        raise ValueError('cannot mark a failed preflight as passed')
    if result.batch_id != manifest.batch_id:
        raise ValueError('preflight result belongs to a different batch')
    return replace(manifest, status=ManifestStatus.PREFLIGHT_PASSED)
