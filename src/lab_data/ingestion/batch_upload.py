"""Single-create batch upload adapter using the existing uploader."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from lab_data.ingestion.batch_manifest import (
    BatchManifest,
    ManifestFile,
    ManifestStatus,
)
from lab_data.parsers.nomad_uploader import (
    NomadUploadError,
    UploadFile,
    UploadResult,
    upload_entry_archive,
)

__all__ = ['BatchUploadResult', 'create_batch_upload']

Uploader = Callable[..., UploadResult]


@dataclass(frozen=True)
class BatchUploadResult:
    """Immutable outcome of one batch-upload adapter invocation."""

    manifest: BatchManifest
    upload_result: UploadResult | None
    created: bool
    state: str
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _rejection(manifest: BatchManifest, message: str) -> BatchUploadResult:
    return BatchUploadResult(
        manifest=manifest,
        upload_result=None,
        created=False,
        state='rejected',
        errors=(message,),
    )


def _transport_inputs(manifest: BatchManifest) -> tuple[list[str], list[UploadFile]]:
    archives = [
        file for file in manifest.archive_files if isinstance(file, ManifestFile)
    ]
    if not archives:
        raise ValueError('no explicit transport archive mainfile is present')
    companions = [
        *(file for file in manifest.companion_files if isinstance(file, ManifestFile)),
    ]
    upload_files = [
        UploadFile(Path(file.source_path), file.destination_path) for file in companions
    ]
    return [str(file.source_path) for file in archives], upload_files


def create_batch_upload(  # noqa: PLR0911, PLR0913
    manifest: BatchManifest,
    *,
    api_base_url: str,
    bearer_token: str | None = None,
    auth: object = None,
    uploader: Uploader = upload_entry_archive,
    dry_run: bool = False,
) -> BatchUploadResult:
    """Create at most one upload from explicit transport mappings.

    CanonicalFile references are intentionally ignored. A caller must provide
    at least one explicit ManifestFile archive mapping for transport.
    """

    if manifest.status is not ManifestStatus.PREFLIGHT_PASSED:
        return _rejection(
            manifest,
            'batch upload requires manifest status preflight_passed',
        )
    if manifest.upload_id is not None:
        return _rejection(
            manifest,
            'batch already has an upload_id; reconcile instead of creating',
        )
    try:
        archive_paths, upload_files = _transport_inputs(manifest)
    except ValueError as error:
        return _rejection(manifest, str(error))

    try:
        result = uploader(
            archive_files=archive_paths,
            upload_files=upload_files,
            api_base_url=api_base_url,
            upload_name=manifest.upload_name or manifest.batch_id,
            auth=auth,
            bearer_token=bearer_token,
            publish=manifest.publish,
            dry_run=dry_run,
        )
    except Exception as error:
        detail = str(error).strip()
        message = f'uploader failed without a confirmed outcome: {type(error).__name__}'
        if detail and isinstance(error, NomadUploadError):
            message = f'{message}: {detail}'
        return BatchUploadResult(
            manifest=manifest,
            upload_result=None,
            created=False,
            state='creation_unknown',
            errors=(message,),
        )

    if dry_run:
        return BatchUploadResult(
            manifest=manifest,
            upload_result=result,
            created=False,
            state='planned',
        )
    if not result.upload_id:
        return BatchUploadResult(
            manifest=manifest,
            upload_result=result,
            created=False,
            state='creation_unknown',
            errors=('uploader returned no confirmed upload_id',),
        )

    if result.processing_status == 'FAILURE':
        updated = replace(
            manifest,
            upload_id=result.upload_id,
            status=ManifestStatus.PROCESSING_FAILED,
            processing_status=result.processing_status,
        )
        return BatchUploadResult(
            manifest=updated,
            upload_result=result,
            created=True,
            state='processing_failed',
            errors=('upload processing failed',),
        )

    if result.entry_id is None or result.processing_status != 'SUCCESS':
        # The upload exists and has a confirmed ID, but processing is either
        # incomplete or not known to have succeeded. Persist the ID and mark
        # the manifest as processing so reconciliation can resume later. This
        # must never fall back to ``creation_unknown`` after a confirmed POST.
        updated = replace(
            manifest,
            upload_id=result.upload_id,
            status=ManifestStatus.PROCESSING,
            processing_status=result.processing_status,
        )
        return BatchUploadResult(
            manifest=updated,
            upload_result=result,
            created=True,
            state='processing',
            warnings=('upload created; processing requires reconciliation',),
        )

    updated = replace(
        manifest,
        upload_id=result.upload_id,
        status=ManifestStatus.UPLOAD_CREATED,
        processing_status=result.processing_status,
    )
    return BatchUploadResult(
        manifest=updated,
        upload_result=result,
        created=True,
        state='upload_created',
    )
