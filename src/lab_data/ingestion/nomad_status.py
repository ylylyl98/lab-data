"""Read-only conversion of an existing NOMAD upload into remote state."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from urllib.parse import quote, urljoin

from lab_data.ingestion.batch_reconcile import RemoteBatchState

__all__ = [
    'NomadStatusAuthenticationError',
    'NomadStatusError',
    'NomadStatusMalformedResponse',
    'NomadStatusNetworkError',
    'fetch_nomad_upload_state',
]

_TIMEOUT_SECONDS = 30
_NOT_FOUND = 404
_AUTH_FAILURES = (401, 403)
GetCallable = Callable[..., object]


class NomadStatusError(Exception):
    """Base error for read-only NOMAD status retrieval."""


class NomadStatusAuthenticationError(NomadStatusError):
    """The supplied credentials were rejected."""


class NomadStatusMalformedResponse(NomadStatusError):
    """NOMAD returned a response that cannot represent remote state."""


class NomadStatusNetworkError(NomadStatusError):
    """The read-only request could not be completed."""


@dataclass(frozen=True)
class _NotFound:
    value: bool = True


def _request_options(bearer_token: str | None, auth: object) -> dict:
    return {
        'headers': (
            {'Authorization': f'Bearer {bearer_token}' }
            if bearer_token is not None
            else None
        ),
        'auth': None if bearer_token is not None else auth,
        'timeout': _TIMEOUT_SECONDS,
    }


def _get_json(
    getter: GetCallable,
    url: str,
    *,
    options: dict,
    params: dict[str, int] | None = None,
) -> dict | list | _NotFound:
    try:
        response = getter(url, params=params, **options)
    except Exception as error:
        try:
            import requests

            request_error = isinstance(error, requests.RequestException)
        except ImportError:
            request_error = False
        if request_error:
            raise NomadStatusNetworkError(f'GET request failed: {url}') from error
        raise
    status_code = getattr(response, 'status_code', None)
    if status_code == _NOT_FOUND:
        return _NotFound()
    if status_code in _AUTH_FAILURES:
        raise NomadStatusAuthenticationError(
            f'GET request was not authorized (HTTP {status_code})'
        )
    try:
        response.raise_for_status()
        payload = response.json()
    except Exception as error:
        raise NomadStatusMalformedResponse(
            f'invalid GET response from {url}'
        ) from error
    if not isinstance(payload, (dict, list)):
        raise NomadStatusMalformedResponse(f'non-JSON-object response from {url}')
    return payload


def _as_strings(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise NomadStatusMalformedResponse(f'{field} must be a list of strings')
    return tuple(value)


def _upload_data(payload: dict, upload_id: str) -> dict:
    data = payload.get('data')
    if not isinstance(data, dict):
        raise NomadStatusMalformedResponse('upload response data is missing')
    observed_id = data.get('upload_id') or payload.get('upload_id')
    if observed_id != upload_id:
        raise NomadStatusMalformedResponse('upload response has an unexpected upload_id')
    for field in ('process_status', 'process_running', 'published'):
        if field not in data:
            raise NomadStatusMalformedResponse(f'upload response lacks {field}')
    if not isinstance(data['process_running'], bool) or not isinstance(data['published'], bool):
        raise NomadStatusMalformedResponse('upload state booleans are invalid')
    return data


def _entry_page(payload: dict | list, url: str) -> tuple[list[dict], dict]:
    if not isinstance(payload, dict):
        raise NomadStatusMalformedResponse(f'entries response is invalid: {url}')
    entries = payload.get('data')
    if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
        raise NomadStatusMalformedResponse('entries response data is invalid')
    pagination = payload.get('pagination') or {}
    if not isinstance(pagination, dict):
        raise NomadStatusMalformedResponse('entries pagination is invalid')
    return entries, pagination


def _all_entries(
    getter: GetCallable,
    entries_url: str,
    *,
    options: dict,
) -> list[dict] | _NotFound:
    entries: list[dict] = []
    page = 1
    next_url: str | None = entries_url
    seen_requests: set[tuple[str, int | None]] = set()
    total: int | None = None
    while next_url is not None:
        request_page = page if next_url == entries_url else None
        request_key = (next_url, request_page)
        if request_key in seen_requests:
            raise NomadStatusMalformedResponse('entries pagination repeated a URL')
        seen_requests.add(request_key)
        payload = _get_json(
            getter,
            next_url,
            options=options,
            params=None if request_page is None else {'page': request_page},
        )
        if isinstance(payload, _NotFound):
            return payload
        page_entries, pagination = _entry_page(payload, next_url)
        entries.extend(page_entries)
        total_value = pagination.get('total')
        if total_value is not None:
            if isinstance(total_value, bool) or not isinstance(total_value, int):
                raise NomadStatusMalformedResponse('entries total is invalid')
            total = total_value
        candidate = pagination.get('next_page_url')
        if candidate is not None and not isinstance(candidate, str):
            raise NomadStatusMalformedResponse('entries next_page_url is invalid')
        if candidate:
            next_url = urljoin(next_url, candidate)
            page += 1
            continue
        if total is not None and len(entries) < total:
            page += 1
            next_url = entries_url
            continue
        if total is not None and len(entries) > total:
            raise NomadStatusMalformedResponse('entries exceed reported total')
        next_url = None
    if total is not None and len(entries) != total:
        raise NomadStatusMalformedResponse('entries count does not match total')
    return entries


def fetch_nomad_upload_state(  # noqa: PLR0913
    upload_id: str,
    *,
    api_base_url: str,
    bearer_token: str | None = None,
    auth: object = None,
    proposal_ids: Sequence[str] = (),
    get: GetCallable | None = None,
) -> RemoteBatchState:
    """Fetch an existing upload using GET requests only.

    ``proposal_ids`` supplies the local ordered identity needed to form the
    existing ``(proposal_id, entry_id)`` reconciliation pairs. Without it,
    entry IDs are deliberately omitted rather than fabricated.
    """

    if not isinstance(upload_id, str) or not upload_id:
        raise ValueError('upload_id must be a non-empty string')
    if get is None:
        import requests

        get = requests.get
    base = api_base_url.rstrip('/') + '/'
    encoded_id = quote(upload_id, safe='')
    options = _request_options(bearer_token, auth)
    upload_url = urljoin(base, f'v1/uploads/{encoded_id}')
    upload_payload = _get_json(get, upload_url, options=options)
    if isinstance(upload_payload, _NotFound):
        return RemoteBatchState(upload_id=upload_id, not_found=True)
    if not isinstance(upload_payload, dict):
        raise NomadStatusMalformedResponse('upload response is invalid')
    data = _upload_data(upload_payload, upload_id)
    entries_url = urljoin(base, f'v1/uploads/{encoded_id}/entries')
    entry_payload = _all_entries(get, entries_url, options=options)
    if isinstance(entry_payload, _NotFound):
        return RemoteBatchState(upload_id=upload_id, not_found=True)
    entry_values: tuple[tuple[str, str], ...] = ()
    entry_ids = []
    for entry in entry_payload:
        entry_id = entry.get('entry_id')
        if not isinstance(entry_id, str) or not entry_id:
            raise NomadStatusMalformedResponse('entry lacks a valid entry_id')
        entry_ids.append(entry_id)
    if proposal_ids:
        if len(proposal_ids) != len(entry_ids):
            raise NomadStatusMalformedResponse(
                'proposal_ids count does not match entry count'
            )
        entry_values = tuple(zip(proposal_ids, entry_ids, strict=True))
    return RemoteBatchState(
        upload_id=upload_id,
        process_status=data['process_status'],
        process_running=data['process_running'],
        published=data['published'],
        entry_ids=entry_values,
        errors=_as_strings(data.get('errors'), 'errors'),
        warnings=_as_strings(data.get('warnings'), 'warnings'),
    )
