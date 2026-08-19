"""Serve the read-only catalog API against an on-disk catalog and preview cache.

Requires ``LAB_DATA_CATALOG_PATH`` and ``LAB_DATA_PREVIEW_ROOT`` to be set.  The
catalog is opened read-only, so serving never creates or mutates catalog files.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from nomad.config import config

config.load_plugins()

import uvicorn  # noqa: E402

from lab_data.apis.api import create_app  # noqa: E402


def main() -> None:
    catalog_path = os.environ.get('LAB_DATA_CATALOG_PATH')
    preview_root = os.environ.get('LAB_DATA_PREVIEW_ROOT')
    if not catalog_path or not preview_root:
        print(
            'LAB_DATA_CATALOG_PATH and LAB_DATA_PREVIEW_ROOT must both be set',
            file=sys.stderr,
        )
        raise SystemExit(1)

    app = create_app(Path(catalog_path), Path(preview_root))
    uvicorn.run(app, host='127.0.0.1', port=8000)


if __name__ == '__main__':
    main()
