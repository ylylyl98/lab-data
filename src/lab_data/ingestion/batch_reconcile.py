"""Pure reconciliation of immutable local batch state with observed remote state."""

from __future__ import annotations

from dataclasses import dataclass, replace

from lab_data.ingestion.batch_manifest import BatchManifest, ManifestStatus

__all__ = [
    'ReconciliationResult',
    'RemoteBatchState',
    'reconcile_batch',
]

_PENDING_STATES = {'pending', 'running', 'processing'}
_SUCCESS_STATES = {'success', 'succeeded', 'complete', 'completed'}
_FAILURE_STATES = {'failed', 'failure'}


@dataclass(frozen=True)
class RemoteBatchState:
    """Observed external execution state supplied by the caller."""

    upload_id: str | None = None
    process_status: str | None = None
    process_running: bool = False
    published: bool = False
    entry_ids: tuple[tuple[str, str], ...] = ()
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    not_found: bool = False


@dataclass(frozen=True)
class ReconciliationResult:
    """Deterministic outcome of reconciling one observed remote state."""

    batch_id: str
    reconciled: bool
    state: str
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _ordered(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def _observed_manifest(
    manifest: BatchManifest,
    remote: RemoteBatchState,
    *,
    status: ManifestStatus | None = None,
) -> BatchManifest:
    return replace(
        manifest,
        status=status or manifest.status,
        upload_id=manifest.upload_id,
        entry_ids=remote.entry_ids or manifest.entry_ids,
        processing_status=remote.process_status,
    )


def reconcile_batch(  # noqa: PLR0911
    manifest: BatchManifest,
    remote_state: RemoteBatchState,
) -> tuple[BatchManifest, ReconciliationResult]:  # noqa: PLR0911
    """Reconcile local state without performing I/O or changing the input.

    A successful result means external processing completed successfully. It
    does not claim scientific or archive verification, which remains a later
    concern represented by ``verification_status``.
    """

    errors = list(remote_state.errors)
    warnings = list(remote_state.warnings)

    if manifest.upload_id is None:
        errors.append('manifest has no upload_id; creation is not reconciled')
        result = ReconciliationResult(
            manifest.batch_id,
            False,
            'not_created',
            _ordered(errors),
            _ordered(warnings),
        )
        return manifest, result

    if remote_state.not_found:
        errors.append('remote upload not found; recovery decision required')
        result = ReconciliationResult(
            manifest.batch_id,
            False,
            'not_found',
            _ordered(errors),
            _ordered(warnings),
        )
        return manifest, result

    if remote_state.upload_id != manifest.upload_id:
        errors.append(
            f'upload_id mismatch: expected {manifest.upload_id}, '
            f'observed {remote_state.upload_id}'
        )
        result = ReconciliationResult(
            manifest.batch_id,
            False,
            'id_mismatch',
            _ordered(errors),
            _ordered(warnings),
        )
        return manifest, result

    if remote_state.published and not manifest.publish:
        errors.append('remote upload is published although publish=False')

    process_status = (remote_state.process_status or '').lower()
    if remote_state.process_running or process_status in _PENDING_STATES:
        observed = _observed_manifest(
            manifest, remote_state, status=ManifestStatus.PROCESSING
        )
        result = ReconciliationResult(
            manifest.batch_id,
            not errors,
            'processing',
            _ordered(errors),
            _ordered(warnings),
        )
        return observed, result

    if process_status in _FAILURE_STATES:
        observed = _observed_manifest(
            manifest, remote_state, status=ManifestStatus.PROCESSING_FAILED
        )
        result = ReconciliationResult(
            manifest.batch_id,
            True,
            'processing_failed',
            _ordered(errors),
            _ordered(warnings),
        )
        return observed, result

    if process_status in _SUCCESS_STATES:
        if len(remote_state.entry_ids) != manifest.expected_entry_count:
            errors.append(
                'entry count mismatch: expected '
                f'{manifest.expected_entry_count}, observed {len(remote_state.entry_ids)}'
            )
        if errors:
            observed = _observed_manifest(manifest, remote_state)
            result = ReconciliationResult(
                manifest.batch_id,
                False,
                'reconciliation_error',
                _ordered(errors),
                _ordered(warnings),
            )
            return observed, result
        observed = _observed_manifest(
            manifest, remote_state, status=ManifestStatus.SUCCESS
        )
        result = ReconciliationResult(
            manifest.batch_id,
            True,
            'success',
            (),
            _ordered(warnings),
        )
        return observed, result

    errors.append(f'unsupported or missing process status: {remote_state.process_status!r}')
    result = ReconciliationResult(
        manifest.batch_id,
        False,
        'reconciliation_error',
        _ordered(errors),
        _ordered(warnings),
    )
    return manifest, result
