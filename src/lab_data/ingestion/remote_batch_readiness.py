"""Read-only remote readiness check for a production batch upload name."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin

from lab_data.ingestion.nomad_status import (
    NomadStatusAuthenticationError,
    NomadStatusMalformedResponse,
    NomadStatusNetworkError,
)

__all__ = ['RemoteBatchReadiness', 'check_remote_batch_readiness']

GetCallable = Callable[..., object]
_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class RemoteBatchReadiness:
    """Immutable outcome of a read-only remote duplicate check."""

    outcome: str
    matching_upload_ids: tuple[str, ...]
    reason: str

    @property
    def may_create(self) -> bool:
        """Return whether no matching upload exists and creation is safe."""

        return self.outcome == 'no_match'


def _request_options(bearer_token: str | None, auth: object) -> dict:
    return {
        'headers': (
            {'Authorization': f'Bearer {bearer_token}'}
            if bearer_token is not None
            else None
        ),
        'auth': None if bearer_token is not None else auth,
        'timeout': _TIMEOUT_SECONDS,
    }


def _get_upload_page(
    get: GetCallable,
    url: str,
    *,
    options: dict,
    page: int | None,
) -> object:
    try:
        response = get(
            url,
            **options,
            **({'params': {'page': page}} if page is not None else {}),
        )
    except Exception as error:
        raise NomadStatusNetworkError(f'GET request failed: {url}') from error

    status_code = getattr(response, 'status_code', None)
    if status_code in (401, 403):
        raise NomadStatusAuthenticationError(
            f'GET request was not authorized (HTTP {status_code})'
        )
    try:
        response.raise_for_status()
        return response.json()
    except Exception as error:
        raise NomadStatusMalformedResponse(
            f'invalid GET response from {url}'
        ) from error


def _parse_upload_page(payload: object) -> tuple[list[dict], dict]:
    if isinstance(payload, dict):
        data = payload.get('data')
        pagination = payload.get('pagination', {})
    else:
        data = payload
        pagination = {}
    if (
        not isinstance(data, list)
        or any(not isinstance(item, dict) for item in data)
        or not isinstance(pagination, dict)
    ):
        raise NomadStatusMalformedResponse('uploads response is invalid')
    return data, pagination


def _pagination_values(
    pagination: dict,
    data_length: int,
) -> tuple[int | None, str | None]:
    data_count = pagination.get('data_count')
    if data_count is not None:
        if isinstance(data_count, bool) or not isinstance(data_count, int):
            raise NomadStatusMalformedResponse('uploads data_count is invalid')
        if data_count < 0 or data_count != data_length:
            raise NomadStatusMalformedResponse('uploads data_count is inconsistent')

    total = pagination.get('total')
    if total is not None and (
        isinstance(total, bool) or not isinstance(total, int) or total < 0
    ):
        raise NomadStatusMalformedResponse('uploads total is invalid')

    next_page_url = pagination.get('next_page_url')
    if next_page_url is not None and not isinstance(next_page_url, str):
        raise NomadStatusMalformedResponse('uploads next_page_url is invalid')
    return total, next_page_url


def _list_uploads(
    api_base_url: str,
    *,
    bearer_token: str | None,
    auth: object,
    get: GetCallable,
) -> list[dict]:
    url = api_base_url.rstrip('/') + '/v1/uploads'
    options = _request_options(bearer_token, auth)
    uploads: list[dict] = []
    page = 1
    next_url: str | None = url
    seen_requests: set[tuple[str, int | None]] = set()
    total: int | None = None

    while next_url is not None:
        request_page = page if next_url == url and page > 1 else None
        request_key = (next_url, request_page)
        if request_key in seen_requests:
            raise NomadStatusMalformedResponse('uploads pagination repeated a URL')
        seen_requests.add(request_key)
        payload = _get_upload_page(
            get,
            next_url,
            options=options,
            page=request_page,
        )
        data, pagination = _parse_upload_page(payload)
        total_value, candidate = _pagination_values(pagination, len(data))
        if total_value is not None:
            if total is not None and total_value != total:
                raise NomadStatusMalformedResponse('uploads total is inconsistent')
            total = total_value
        uploads.extend(data)
        if candidate:
            next_url = urljoin(next_url, candidate)
            page += 1
            continue
        if total is not None and len(uploads) < total:
            if not data:
                raise NomadStatusMalformedResponse('uploads count does not match total')
            page += 1
            next_url = url
            continue
        if total is not None and len(uploads) > total:
            raise NomadStatusMalformedResponse('uploads exceed reported total')
        next_url = None

    if total is not None and len(uploads) != total:
        raise NomadStatusMalformedResponse('uploads count does not match total')
    return uploads


def check_remote_batch_readiness(  # noqa: PLR0913
    api_base_url: str,
    upload_name: str,
    *,
    bearer_token: str | None = None,
    auth: object = None,
    get: GetCallable | None = None,
) -> RemoteBatchReadiness:
    """Check whether any existing upload matches ``upload_name``.

    Exactly three outcomes are produced: ``no_match``, ``single_match``, and
    ``ambiguous``. Credentials never appear in the returned model.
    """

    if not isinstance(api_base_url, str) or not api_base_url:
        raise ValueError('api_base_url must be a non-empty string')
    if not isinstance(upload_name, str) or not upload_name:
        raise ValueError('upload_name must be a non-empty string')
    if get is None:
        import requests

        get = requests.get

    uploads = _list_uploads(
        api_base_url,
        bearer_token=bearer_token,
        auth=auth,
        get=get,
    )
    matching = [
        upload for upload in uploads if upload.get('upload_name') == upload_name
    ]
    upload_ids = tuple(
        sorted(
            {
                upload.get('upload_id')
                for upload in matching
                if isinstance(upload.get('upload_id'), str) and upload.get('upload_id')
            }
        )
    )

    if len(upload_ids) == 0:
        return RemoteBatchReadiness(
            outcome='no_match',
            matching_upload_ids=(),
            reason='no existing upload matches the name',
        )
    if len(upload_ids) == 1:
        return RemoteBatchReadiness(
            outcome='single_match',
            matching_upload_ids=upload_ids,
            reason='exactly one existing upload matches the name',
        )
    return RemoteBatchReadiness(
        outcome='ambiguous',
        matching_upload_ids=upload_ids,
        reason='multiple existing uploads match the name',
    )
