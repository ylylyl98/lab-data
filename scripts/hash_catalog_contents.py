"""Print a deterministic content hash over all six catalog tables."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

_TABLES = (
    'experiments',
    'experiment_files',
    'metadata_claims',
    'relationships',
    'devices',
    'artifacts',
)


def content_hash(catalog_path: str | Path) -> str:
    connection = sqlite3.connect(str(catalog_path))
    digest = hashlib.sha256()
    for table in _TABLES:
        digest.update(table.encode('utf-8'))
        rows = connection.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall()
        digest.update(
            json.dumps([tuple(row) for row in rows], sort_keys=True).encode('utf-8')
        )
    connection.close()
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', required=True, help='path to the catalog db')
    args = parser.parse_args(argv)
    print(content_hash(args.catalog))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
