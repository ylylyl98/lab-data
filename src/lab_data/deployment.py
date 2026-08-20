"""Production serving configuration for the single-origin lab-data browser."""

from __future__ import annotations

import os
from pathlib import Path

from lab_data.apis.api import CATALOG_PATH_ENV, PREVIEW_ROOT_ENV

HOST_ENV = 'LAB_DATA_HOST'
PORT_ENV = 'LAB_DATA_PORT'
FRONTEND_DIST_ENV = 'FRONTEND_DIST'

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 8000
FRONTEND_DIST_DIRNAME = 'frontend/dist'
_MAX_PORT = 65535


def repo_root() -> Path:
    """Repository root, derived from this package's location."""

    return Path(__file__).resolve().parents[2]


def default_frontend_dir() -> Path:
    return repo_root() / FRONTEND_DIST_DIRNAME


def load_host() -> str:
    return os.environ.get(HOST_ENV) or DEFAULT_HOST


def load_port() -> int:
    raw = os.environ.get(PORT_ENV, '').strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError as error:
        raise ValueError(f'{PORT_ENV} must be an integer, got {raw!r}') from error
    if not 0 < port <= _MAX_PORT:
        raise ValueError(f'{PORT_ENV} must be between 1 and 65535, got {port}')
    return port


def load_frontend_dir(cli_override: str | None = None) -> Path:
    raw = cli_override or os.environ.get(FRONTEND_DIST_ENV)
    return Path(raw) if raw else default_frontend_dir()


def load_production_config(
    cli_frontend_dir: str | None = None,
) -> tuple[Path, Path, Path]:
    """Resolve and validate catalog, preview root, and frontend build paths.

    Raises ``ValueError`` with a clear message when required configuration is
    missing or points at paths that do not exist.
    """

    catalog_value = os.environ.get(CATALOG_PATH_ENV)
    preview_value = os.environ.get(PREVIEW_ROOT_ENV)
    if not catalog_value or not preview_value:
        raise ValueError(
            f'{CATALOG_PATH_ENV} and {PREVIEW_ROOT_ENV} must both be set '
            f'(current values: {CATALOG_PATH_ENV}={catalog_value!r}, '
            f'{PREVIEW_ROOT_ENV}={preview_value!r})'
        )
    catalog_path = Path(catalog_value)
    preview_root = Path(preview_value)
    if not catalog_path.is_file():
        raise ValueError(
            f'{CATALOG_PATH_ENV} does not point to a readable catalog file: '
            f'{catalog_path}'
        )
    if not preview_root.is_dir():
        raise ValueError(
            f'{PREVIEW_ROOT_ENV} does not point to a preview directory: {preview_root}'
        )
    frontend_dir = load_frontend_dir(cli_frontend_dir)
    if not (frontend_dir / 'index.html').is_file():
        raise ValueError(
            f'frontend build not found at {frontend_dir}: run `npm run build` '
            f'in frontend/ first, or set {FRONTEND_DIST_ENV}'
        )
    return catalog_path, preview_root, frontend_dir
