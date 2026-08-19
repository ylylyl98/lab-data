"""Focused tests for archive batch -> BatchManifest construction."""

from pathlib import Path

import pytest

from lab_data.ingestion.archive_batch_builder import (
    ArchiveBatch,
    ArchiveBatchItem,
    build_batch_manifest,
)
from lab_data.ingestion.batch_manifest import ManifestFile, ManifestStatus


def _batch(count=7):
    return ArchiveBatch(
        items=tuple(
            ArchiveBatchItem(
                proposal_id=f'D356-{index:02d}',
                output_relative_path=f'D356-{index:02d}.archive.json',
                output_path=f'C:\\out\\D356-{index:02d}.archive.json',
            )
            for index in range(1, count + 1)
        ),
        errors=(),
    )


def test_seven_item_manifest_identity_and_order():
    manifest = build_batch_manifest(
        _batch(),
        dataset_label='D356',
        batch_size=50,
        batch_number=1,
        upload_name='lab-data-D356-phase9-batch-001-7',
        publish=False,
        created_utc='2026-08-18T00:00:00Z',
        updated_utc='2026-08-18T00:00:00Z',
    )

    assert manifest.batch_number == 1
    assert manifest.dataset_label == 'D356'
    assert manifest.status is ManifestStatus.PLANNED
    assert manifest.publish is False
    assert manifest.upload_name == 'lab-data-D356-phase9-batch-001-7'
    assert manifest.upload_id is None
    assert manifest.proposal_ids == tuple(f'D356-{i:02d}' for i in range(1, 8))
    assert manifest.expected_entry_count == 7  # noqa: PLR2004
    assert manifest.expected_file_count == 7  # noqa: PLR2004
    assert manifest.batch_id.startswith('D356-batch-001-')


def test_archive_transport_count_and_companions():
    manifest = build_batch_manifest(
        _batch(),
        dataset_label='D356',
        batch_size=50,
        batch_number=1,
        upload_name='lab-data-D356-phase9-batch-001-7',
    )

    assert len(manifest.archive_files) == 7  # noqa: PLR2004
    assert all(isinstance(file, ManifestFile) for file in manifest.archive_files)
    assert [file.role for file in manifest.archive_files] == ['archive'] * 7
    assert manifest.companion_files == ()


def test_archive_destinations_are_deterministic():
    manifest = build_batch_manifest(
        _batch(),
        dataset_label='D356',
        batch_size=50,
        batch_number=1,
        upload_name='lab-data-D356-phase9-batch-001-7',
    )

    assert [file.destination_path for file in manifest.archive_files] == [
        f'D356-{i:02d}.archive.json' for i in range(1, 8)
    ]


def test_repeated_construction_is_equal():
    kwargs = {
        'dataset_label': 'D356',
        'batch_size': 50,
        'batch_number': 1,
        'upload_name': 'lab-data-D356-phase9-batch-001-7',
        'created_utc': '2026-08-18T00:00:00Z',
        'updated_utc': '2026-08-18T00:00:00Z',
    }

    first = build_batch_manifest(_batch(), **kwargs)
    second = build_batch_manifest(_batch(), **kwargs)

    assert first == second


def test_deterministic_batch_id_and_upload_name():
    manifest = build_batch_manifest(
        _batch(),
        dataset_label='D356',
        batch_size=50,
        batch_number=1,
        upload_name='lab-data-D356-phase9-batch-001-7',
    )

    assert manifest.upload_name == 'lab-data-D356-phase9-batch-001-7'
    assert manifest.batch_id == manifest.batch_id


def test_rejected_batch_is_refused():
    rejected = ArchiveBatch(items=(), errors=('incomplete',))

    with pytest.raises(ValueError, match='rejected'):
        build_batch_manifest(
            rejected,
            dataset_label='D356',
            batch_size=50,
            batch_number=1,
            upload_name='x',
        )


def test_unexpected_split_is_rejected():
    batch = _batch(count=51)

    with pytest.raises(ValueError, match='unexpected batch split'):
        build_batch_manifest(
            batch,
            dataset_label='D356',
            batch_size=50,
            batch_number=1,
            upload_name='x',
        )


def test_no_companion_inference():
    manifest = build_batch_manifest(
        _batch(),
        dataset_label='D356',
        batch_size=50,
        batch_number=1,
        upload_name='lab-data-D356-phase9-batch-001-7',
    )

    assert manifest.companion_files == ()
    assert all(file.role == 'archive' for file in manifest.archive_files)


def test_module_has_no_manifest_side_effects():
    source = Path('src/lab_data/ingestion/archive_batch_builder.py').read_text(
        encoding='utf-8'
    )
    lowered = source.lower()

    for forbidden in ('write_batch_manifest', 'preflight', 'requests', 'nomad'):
        assert forbidden not in lowered
