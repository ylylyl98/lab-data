"""Upload a NOMAD entry archive to a NOMAD Oasis instance.

This module implements a small, side-effect-free uploader for the
``.archive.json`` files produced by :mod:`lab_data.parsers.archive_serializer`.
By default every call is a *dry run*: it validates the inputs and returns a
deterministic plan without performing any authentication, HTTP request, or
file transfer. The real write path is hidden behind ``dry_run=False`` and
requires an explicitly injected ``auth`` argument.

The uploader never scans, copies, renames, or modifies any local file. Paths
under ``C:\\NOMAD_Test`` are read only as explicit inputs when supplied by the
caller; the uploader never writes anywhere on the local filesystem.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

__all__ = [
    'NomadAuthenticationError',
    'NomadUploadError',
    'UploadFile',
    'UploadResult',
    'upload_entry_archive',
]


_DEFAULT_API_BASE_URL = 'http://localhost/nomad-oasis/api'
_ACCEPT_JSON = 'application/json'
_HTTP_TIMEOUT_SECONDS = 30
_POLL_INTERVAL_SECONDS = 1.0
_MAX_POLL_ATTEMPTS = 30
_MAX_ERROR_BODY_LENGTH = 512


class NomadUploadError(Exception):
    """Base error raised when a real (non-dry-run) upload fails."""


class NomadAuthenticationError(NomadUploadError):
    """Raised when a real upload is attempted without authentication."""


@dataclasses.dataclass(frozen=True)
class UploadFile:
    """A single file to upload alongside the entry archive.

    ``source_path`` is the local filesystem path to read; it is never resolved
    or modified and is preserved as the caller supplied it. ``destination_path``
    is the relative, forward-slash-separated path the file occupies inside the
    upload. Instances are immutable (frozen).
    """

    source_path: str | Path
    destination_path: str


@dataclasses.dataclass(frozen=True)
class UploadResult:
    """Outcome of an upload attempt.

    ``upload_id``, ``entry_id``, and ``processing_status`` are ``None`` for a
    dry run so no fake identifiers are ever fabricated. ``plan`` is populated
    only for dry runs and contains no secrets.
    """

    dry_run: bool
    upload_id: str | None
    entry_id: str | None
    processing_status: str | None
    published: bool
    plan: dict[str, Any] | None = None


def _normalize_destination(destination_path: str) -> str:
    """Validate and normalize a relative upload destination path.

    Rejects absolute, drive-letter, UNC, leading-slash, and parent-reference
    (``..``) paths, and normalizes backslashes to forward slashes. The original
    string is never resolved against the filesystem.
    """

    dest = str(destination_path)
    if dest == '':
        raise ValueError('destination_path must not be empty')

    if dest[:1].isalpha() and dest[1:2] == ':':
        raise ValueError(f'destination_path must be relative (drive path): {dest!r}')

    if dest.startswith(('\\\\', '//')):
        raise ValueError(f'destination_path must be relative (UNC path): {dest!r}')

    if dest.startswith(('/', '\\')):
        raise ValueError(f'destination_path must be relative (leading slash): {dest!r}')

    normalized = dest.replace('\\', '/')
    if '..' in normalized.split('/'):
        raise ValueError(
            f'destination_path must not contain a parent reference: {dest!r}'
        )

    return normalized


def _collect_files(raw_paths: Any, upload_files: Any) -> list[UploadFile]:
    """Combine explicit upload files with legacy raw paths in a fixed order.

    ``upload_files`` entries must already be :class:`UploadFile` instances and
    are emitted first. Each legacy ``raw_path`` becomes an :class:`UploadFile`
    whose destination is its basename, preserving prior basename-only upload
    behavior.
    """

    files: list[UploadFile] = []
    for upload_file in upload_files:
        if not isinstance(upload_file, UploadFile):
            raise TypeError(
                'upload_files entries must be UploadFile instances; got '
                f'{type(upload_file).__name__}'
            )
        files.append(upload_file)

    for raw_path in raw_paths:
        raw_str = str(raw_path)
        files.append(UploadFile(raw_str, Path(raw_path).name))

    return files


def _validate_archive_path(archive_path: Any) -> str:
    """Validate one archive mainfile path and return its string form."""

    archive_str = str(archive_path)
    if not archive_str.endswith('.archive.json'):
        raise ValueError(
            f"archive_path must end with '.archive.json'; got: {archive_str!r}"
        )

    archive = Path(archive_path)
    if not archive.exists() or not archive.is_file():
        raise FileNotFoundError(f'archive_path does not exist: {archive_str}')

    return archive_str


def _collect_archives(archive_path: Any, archive_files: Any) -> list[str]:
    """Resolve the ordered archive mainfile list from the two input forms.

    archive_files is the explicit multi-archive form and takes precedence;
    archive_path is the legacy single-archive form. Exactly one of the two
    must be supplied, and archive ordering is preserved as given.
    """

    if archive_files:
        if archive_path is not None:
            raise ValueError('provide either archive_path or archive_files, not both')
        return [_validate_archive_path(path) for path in archive_files]
    if archive_path is None:
        raise ValueError('archive_path is required when archive_files is not provided')
    return [_validate_archive_path(archive_path)]


def _validate_inputs(
    archive_path: Any, raw_paths: Any, upload_files: Any, archive_files: Any
) -> tuple[list[str], list[UploadFile]]:
    """Validate the archive and companion inputs without modifying anything.

    Returns the ordered list of archive mainfile paths and the normalized,
    source-validated list of ordinary companion files to upload.
    """

    archive_paths = _collect_archives(archive_path, archive_files)

    normalized_files: list[UploadFile] = []
    for upload_file in _collect_files(raw_paths, upload_files):
        source = str(upload_file.source_path)
        if not Path(source).exists() or not Path(source).is_file():
            raise FileNotFoundError(f'source path does not exist: {source}')
        destination = _normalize_destination(upload_file.destination_path)
        normalized_files.append(UploadFile(source, destination))

    return archive_paths, normalized_files


def _build_plan(
    archive_paths: list[str],
    files: list[UploadFile],
    upload_name: str | None,
    publish: bool,
) -> dict[str, Any]:
    """Build the deterministic dry-run plan without secrets or identifiers."""

    plan: dict[str, Any] = {
        'files': [
            {
                'source_path': upload_file.source_path,
                'destination_path': upload_file.destination_path,
            }
            for upload_file in files
        ],
        'upload_name': upload_name,
        'publish': publish,
    }
    if len(archive_paths) == 1:
        plan['archive_path'] = archive_paths[0]
    else:
        plan['archive_paths'] = list(archive_paths)
    return plan


def _aggregate_status(statuses: list[Any]) -> str | None:
    """Aggregate per-entry processing statuses into one upload status."""

    if all(status == 'SUCCESS' for status in statuses):
        return 'SUCCESS'
    for preferred in ('PROCESSING', 'PENDING'):
        if preferred in statuses:
            return preferred
    return statuses[0] if statuses else None


def _http_error_diagnostics(
    response: Any,
    *,
    endpoint: str,
    upload_name: str | None,
    archive_paths: list[str],
    files: list[UploadFile],
) -> str:
    """Return bounded, secret-free diagnostics for a failed create response."""

    status = getattr(response, 'status_code', None)
    reason = getattr(response, 'reason', None) or 'unknown'
    headers = getattr(response, 'headers', {}) or {}
    content_type = headers.get('Content-Type', 'unknown')
    body = getattr(response, 'text', '') or ''
    body = ' '.join(str(body).split())[:_MAX_ERROR_BODY_LENGTH]
    names = [
        Path(path).name
        for path in (*archive_paths, *(file.source_path for file in files))
    ]
    source_bytes = sum(
        Path(path).stat().st_size
        for path in (*archive_paths, *(file.source_path for file in files))
    )
    return (
        f'POST {endpoint} failed before upload ID: status={status!r}; '
        f'reason={reason!r}; content_type={content_type!r}; '
        f'body={body!r}; upload_name={upload_name!r}; publish=False; '
        f'multipart_file_count={len(names)}; multipart_names={names!r}; '
        f'source_bytes={source_bytes}'
    )


def _real_upload(  # noqa: PLR0912, PLR0913, PLR0915, PLR0917
    archive_paths: list[str],
    files: list[UploadFile],
    api_base_url: str,
    upload_name: str | None,
    auth: Any,
    publish: bool,
    bearer_token: str | None,
) -> UploadResult:
    """Perform the real NOMAD Oasis upload over HTTP using injected ``auth``."""

    import time

    import requests

    base_url = api_base_url.rstrip('/')
    request_auth = None if bearer_token is not None else auth
    request_headers = {'Accept': _ACCEPT_JSON}
    if bearer_token is not None:
        request_headers['Authorization'] = f'Bearer {bearer_token}'
    request_options = {'auth': request_auth, 'headers': request_headers}

    handles = []
    try:
        multipart_files = []
        for archive_path in archive_paths:
            handle = open(archive_path, 'rb')
            handles.append(handle)
            multipart_files.append(
                ('file', (Path(archive_path).name, handle, 'application/json'))
            )
        create_params = (
            {'upload_name': upload_name} if upload_name is not None else None
        )
        create_resp = requests.post(
            f'{base_url}/v1/uploads',
            files=multipart_files,
            params=create_params,
            **request_options,
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
    finally:
        for handle in handles:
            handle.close()
    try:
        create_resp.raise_for_status()
    except Exception as error:
        raise NomadUploadError(
            _http_error_diagnostics(
                create_resp,
                endpoint=f'{base_url}/v1/uploads',
                upload_name=upload_name,
                archive_paths=archive_paths,
                files=files,
            )
        ) from error
    payload = create_resp.json()
    upload_id = (payload.get('data') or {}).get('upload_id')
    if not upload_id:
        raise NomadUploadError(
            f'upload response did not include an upload_id: {payload!r}'
        )

    entry_id: str | None = None
    processing_status: str | None = None
    published = False

    def partial() -> UploadResult:
        """Preserve a confirmed upload ID even when later steps fail."""

        return UploadResult(
            dry_run=False,
            upload_id=upload_id,
            entry_id=entry_id,
            processing_status=processing_status,
            published=published,
        )

    try:
        for upload_file in files:
            destination = upload_file.destination_path
            with open(upload_file.source_path, 'rb') as handle:
                raw_resp = requests.put(
                    f'{base_url}/v1/uploads/{upload_id}/raw/{destination}',
                    files={'file': (Path(destination).name, handle)},
                    **request_options,
                    timeout=_HTTP_TIMEOUT_SECONDS,
                )
            raw_resp.raise_for_status()

        for _ in range(_MAX_POLL_ATTEMPTS):
            entries_resp = requests.get(
                f'{base_url}/v1/uploads/{upload_id}/entries',
                **request_options,
                timeout=_HTTP_TIMEOUT_SECONDS,
            )
            entries_resp.raise_for_status()
            entries = entries_resp.json().get('data') or []
            if len(entries) >= len(archive_paths):
                first = entries[0]
                entry_id = first.get('entry_id')
                processing_status = first.get('processing_status')
                break
            time.sleep(_POLL_INTERVAL_SECONDS)

        if processing_status == 'FAILURE':
            return partial()

        if entry_id is None:
            return partial()

        if publish:
            publish_resp = requests.post(
                f'{base_url}/v1/uploads/{upload_id}/action/publish',
                **request_options,
                timeout=_HTTP_TIMEOUT_SECONDS,
            )
            publish_resp.raise_for_status()
            published = True
    except Exception:
        # The upload was created; later raw-put/poll/publish failures must not
        # discard the already-known upload ID.
        return partial()

    return partial()


def upload_entry_archive(  # noqa: PLR0913
    archive_path: str | Path | None = None,
    raw_paths: Any = (),
    *,
    upload_files: Any = (),
    archive_files: Any = (),
    api_base_url: str = _DEFAULT_API_BASE_URL,
    upload_name: str | None = None,
    auth: Any = None,
    bearer_token: str | None = None,
    publish: bool = False,
    dry_run: bool = True,
) -> UploadResult:
    """Validate and optionally upload a ``.archive.json`` entry archive.

    ``archive_path`` must exist and end with ``.archive.json`` when supplied;
    ``archive_files`` can be used for an ordered multi-mainfile upload. Every
    path in ``raw_paths`` must exist. Paths are never scanned, copied, renamed, or
    modified, and a dry run performs no writes, authentication, or network
    traffic. A non-dry-run requires an injected ``auth`` and performs the real
    NOMAD Oasis REST sequence (create upload, add raw files, poll entries,
    optionally publish) using :mod:`requests`. The create endpoint already
    processes the submitted mainfiles, so no separate process action is issued.

    ``upload_files`` accepts :class:`UploadFile` instances whose
    ``destination_path`` is a validated relative path; ``raw_paths`` remains
    supported and each entry is uploaded under its basename. When both are
    supplied, ``upload_files`` entries precede ``raw_paths`` entries. A
    supplied ``bearer_token`` is used only for the real request path and is
    never included in the dry-run result.
    """

    archive_paths, files = _validate_inputs(
        archive_path, raw_paths, upload_files, archive_files
    )

    if dry_run:
        return UploadResult(
            dry_run=True,
            upload_id=None,
            entry_id=None,
            processing_status=None,
            published=False,
            plan=_build_plan(archive_paths, files, upload_name, publish),
        )

    if auth is None and bearer_token is None:
        raise NomadAuthenticationError(
            'authentication is required for a real upload (dry_run=False); '
            'pass an explicit `auth` or `bearer_token` argument'
        )

    return _real_upload(
        archive_paths,
        files,
        api_base_url,
        upload_name,
        auth,
        publish,
        bearer_token,
    )
