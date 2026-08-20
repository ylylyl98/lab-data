"""Production single-origin server for the lab-data browser.

Serves the read-only catalog API and the built React frontend from one
FastAPI process.  Requires ``LAB_DATA_CATALOG_PATH`` and
``LAB_DATA_PREVIEW_ROOT``; binds ``127.0.0.1:8000`` by default, overridable
with ``LAB_DATA_HOST`` and ``LAB_DATA_PORT``.
"""

from __future__ import annotations

import argparse
import sys

from nomad.config import config

config.load_plugins()

import uvicorn  # noqa: E402

from lab_data.apis.api import create_app  # noqa: E402
from lab_data.deployment import (  # noqa: E402
    load_host,
    load_port,
    load_production_config,
)


def main() -> None:
    parser = argparse.ArgumentParser(description='Serve the lab-data browser.')
    parser.add_argument(
        '--frontend-dir',
        default=None,
        help='path to the built frontend (defaults to FRONTEND_DIST env or '
        '<repo>/frontend/dist)',
    )
    args = parser.parse_args()

    try:
        catalog_path, preview_root, frontend_dir = load_production_config(
            args.frontend_dir
        )
        host = load_host()
        port = load_port()
    except ValueError as error:
        print(f'error: {error}', file=sys.stderr)
        raise SystemExit(1) from error

    app = create_app(catalog_path, preview_root, frontend_dir=frontend_dir)
    uvicorn.run(app, host=host, port=port)


if __name__ == '__main__':
    main()
