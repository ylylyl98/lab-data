"""Rebuild deterministic device-directory experiments into a catalog.

Reads the catalog read-write, derives one experiment per canonical
measurement from explicit device data-directory context (raw data
directories and ``Processed Data`` under a device folder alias), and
atomically replaces the previously derived experiments, experiment files,
linkage claims, ``measured_on`` relationships, and ``derived_from`` file
edges. Re-running is a deterministic no-op on the final catalog contents;
no source files are touched.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from lab_data.device_experiment_linkage import (
    LinkageResult,
    apply_device_experiment_linkage,
    build_derived_from_relationships,
    build_human_reviewed_match_claims,
    build_measured_on_claims,
    build_measured_on_relationships,
    derive_device_experiments,
)
from lab_data.scientific_catalog import (
    Artifact,
    Device,
    StorageReference,
)

DEFAULT_CATALOG = Path(
    r'C:\NOMAD_Test_Output\scientific_catalog_readiness\yz247_yzdev_catalog.sqlite'
)


def read_catalog_objects(
    connection: sqlite3.Connection,
) -> tuple[list[Device], list[Artifact]]:
    """Materialize devices and artifacts from catalog tables."""

    connection.row_factory = sqlite3.Row
    devices: list[Device] = []
    for row in connection.execute(
        'SELECT * FROM devices ORDER BY ordinal ASC'
    ).fetchall():
        devices.append(
            Device(
                device_id=row['device_id'],
                device_type=row['device_type'],
                aliases=tuple(json.loads(row['aliases_json'])),
                review_state=row['review_state'],
                metadata=json.loads(row['metadata_json']),
                maker_namespace=row['maker_namespace'],
                local_device_id=row['local_device_id'],
                display_label=row['display_label'],
            )
        )
    artifacts: list[Artifact] = []
    for row in connection.execute(
        'SELECT * FROM artifacts ORDER BY ordinal ASC'
    ).fetchall():
        storage_source_id = row['storage_source_id']
        relative_path = row['relative_path']
        reference = (
            None
            if storage_source_id is None or relative_path is None
            else StorageReference(storage_source_id, relative_path)
        )
        artifacts.append(
            Artifact(
                artifact_id=row['artifact_id'],
                role=row['role'],
                category=row['category'],
                extension=row['extension'],
                media_type=row['media_type'],
                device_id=row['device_id'],
                experiment_id=row['experiment_id'],
                storage_reference=reference,
                size_bytes=row['size_bytes'],
                mtime_ns=row['mtime_ns'],
                review_state=row['review_state'],
                metadata=json.loads(row['metadata_json']),
            )
        )
    return devices, artifacts


def _counts(connection: sqlite3.Connection) -> dict[str, int]:
    def count(sql: str) -> int:
        return int(connection.execute(sql).fetchone()[0])

    return {
        'devices': count('SELECT COUNT(*) FROM devices'),
        'experiments': count('SELECT COUNT(*) FROM experiments'),
        'yz247_experiments': count(
            "SELECT COUNT(*) FROM experiments WHERE experiment_id LIKE 'YZ247-%'"
        ),
        'artifacts': count('SELECT COUNT(*) FROM artifacts'),
        'd356_experiments': count(
            "SELECT COUNT(*) FROM experiments WHERE experiment_id LIKE 'D356-%'"
        ),
        'd345_experiments': count(
            "SELECT COUNT(*) FROM experiments WHERE experiment_id LIKE 'D345-%'"
        ),
        'measured_on_relationships': count(
            "SELECT COUNT(*) FROM relationships WHERE predicate = 'measured_on'"
        ),
        'derived_from_relationships': count(
            "SELECT COUNT(*) FROM relationships WHERE predicate = 'derived_from'"
        ),
    }


def run_linkage(
    catalog_path: str | Path,
) -> tuple[dict[str, int], dict[str, int], LinkageResult]:
    """Apply the linkage and return before/after counts plus inserted rows."""

    connection = sqlite3.connect(str(catalog_path), isolation_level=None)
    try:
        before = _counts(connection)
        devices, artifacts = read_catalog_objects(connection)
        experiments = derive_device_experiments(devices, artifacts)
        relationships = build_measured_on_relationships(experiments)
        claims = build_measured_on_claims(experiments)
        claims = [*claims, *build_human_reviewed_match_claims(experiments)]
        derived_from = build_derived_from_relationships(experiments)
        result = apply_device_experiment_linkage(
            connection,
            experiments,
            [*relationships, *derived_from],
            claims,
        )
        after = _counts(connection)
    finally:
        connection.close()
    return before, after, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            'Insert deterministic device-directory experiments and measured_on '
            'relationships into a lab-data catalog.'
        )
    )
    parser.add_argument(
        '--catalog',
        default=str(DEFAULT_CATALOG),
        help='path to the catalog database (default: derived data dir)',
    )
    args = parser.parse_args(argv)

    before, after, result = run_linkage(args.catalog)
    print(f'devices: {before["devices"]} -> {after["devices"]}')
    print(f'experiments: {before["experiments"]} -> {after["experiments"]}')
    print(
        'YZ247-* experiments: '
        f'{before["yz247_experiments"]} -> {after["yz247_experiments"]}'
    )
    print(f'artifacts: {before["artifacts"]} -> {after["artifacts"]}')
    print(
        'D356 experiments: '
        f'{before["d356_experiments"]} -> {after["d356_experiments"]}'
    )
    print(
        'D345 experiments: '
        f'{before["d345_experiments"]} -> {after["d345_experiments"]}'
    )
    print(
        'measured_on relationships: '
        f'{before["measured_on_relationships"]} -> '
        f'{after["measured_on_relationships"]}'
    )
    print(
        'derived_from relationships: '
        f'{before["derived_from_relationships"]} -> '
        f'{after["derived_from_relationships"]}'
    )
    print(f'new experiments inserted: {result.experiments}')
    print(f'new experiment_files inserted: {result.experiment_files}')
    print(f'new claims inserted: {result.claims}')
    print(f'new relationships inserted: {result.relationships}')
    print(f'new derived_from edges inserted: {result.derived_from}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
