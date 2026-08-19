"""Focused tests for deterministic batch-manifest persistence."""

import json
from dataclasses import replace

import pytest

from lab_data.ingestion.batch_manifest import (
    CanonicalFile,
    ManifestFile,
    ManifestStatus,
    create_batch_manifest,
    manifest_from_dict,
    manifest_to_dict,
    read_batch_manifest,
    write_batch_manifest,
)
from lab_data.ingestion.batch_planner import plan_batches

CREATED = '2026-01-01T00:00:00Z'
UPDATED = '2026-01-01T00:01:00Z'
EXPECTED_FILES = 2


def _manifest(**overrides):
    planned = plan_batches(
        ['proposal-003', 'proposal-001', 'proposal-002'],
        batch_size=2,
        dataset_label='YZ247',
    )[0]
    values = {
        'archive_files': (
            ManifestFile(
                r'C:\NOMAD_Test\YZ247\Initial Data\file.csv',
                'Initial Data/file.csv',
                'raw',
            ),
        ),
        'companion_files': (
            ManifestFile(
                r'C:\NOMAD_Test\YZ247\Processed Data\file.dat',
                'Processed Data/file.dat',
                'processed',
            ),
        ),
        'publish': False,
        'upload_name': 'yz247-batch-001',
        'created_utc': CREATED,
        'updated_utc': UPDATED,
    }
    status = overrides.pop('status', None)
    values.update(overrides)
    manifest = create_batch_manifest(planned, **values)
    return replace(manifest, status=status) if status is not None else manifest


def test_manifest_creation_from_planned_batch():
    manifest = _manifest()

    assert manifest.batch_id == plan_batches(
        ['proposal-003', 'proposal-001', 'proposal-002'],
        batch_size=2,
        dataset_label='YZ247',
    )[0].batch_id
    assert manifest.proposal_ids == ('proposal-003', 'proposal-001')
    assert manifest.expected_entry_count == EXPECTED_FILES
    assert manifest.expected_file_count == EXPECTED_FILES
    assert manifest.status is ManifestStatus.PLANNED
    assert manifest.upload_id is None
    assert manifest.entry_ids == ()


def test_json_round_trip_preserves_all_fields():
    manifest = _manifest(
        status=ManifestStatus.SUCCESS,
    )
    restored = manifest_from_dict(manifest_to_dict(manifest))

    assert restored == manifest


def test_serializing_same_manifest_is_deterministic():
    manifest = _manifest()

    first = json.dumps(manifest_to_dict(manifest), sort_keys=True, indent=2)
    second = json.dumps(manifest_to_dict(manifest), sort_keys=True, indent=2)

    assert first == second


def test_proposal_and_file_order_is_preserved():
    manifest = _manifest()
    payload = manifest_to_dict(manifest)

    assert payload['proposal_ids'] == ['proposal-003', 'proposal-001']
    assert [item['destination_path'] for item in payload['archive_files']] == [
        'Initial Data/file.csv'
    ]
    assert [item['destination_path'] for item in payload['companion_files']] == [
        'Processed Data/file.dat'
    ]


def test_nested_file_mapping_and_utf8_paths_round_trip():
    manifest = _manifest(
        archive_files=(ManifestFile('C:\\測定\\file.csv', 'Initial Data/é.csv', 'raw'),)
    )

    restored = manifest_from_dict(manifest_to_dict(manifest))

    assert restored.archive_files == manifest.archive_files


def test_storage_agnostic_canonical_file_round_trips_without_destination():
    planned = plan_batches(['proposal-001'], dataset_label='YZ247')[0]
    canonical = CanonicalFile(
        r'C:\NOMAD_Test\YZ247\Initial Data\file.csv',
        'Initial Data/file.csv',
        'raw',
    )
    manifest = create_batch_manifest(
        planned,
        archive_files=(canonical,),
        created_utc=CREATED,
        updated_utc=UPDATED,
    )

    restored = manifest_from_dict(manifest_to_dict(manifest))
    payload = manifest_to_dict(manifest)

    assert restored.archive_files == (canonical,)
    assert payload['archive_files'] == [
        {
            'source_path': canonical.source_path,
            'relative_path': canonical.relative_path,
            'role': canonical.role,
        }
    ]


def test_serialized_manifest_contains_no_credential_fields():
    serialized = json.dumps(manifest_to_dict(_manifest()))

    for forbidden in ('NOMAD_TOKEN', 'Authorization', 'Bearer', 'password', 'token'):
        assert forbidden not in serialized


def test_invalid_status_is_rejected():
    payload = manifest_to_dict(_manifest())
    payload['status'] = 'unknown'

    with pytest.raises(ValueError, match='invalid manifest status'):
        manifest_from_dict(payload)


def test_unsupported_manifest_version_is_rejected():
    payload = manifest_to_dict(_manifest())
    payload['manifest_version'] = 99

    with pytest.raises(ValueError, match='unsupported manifest version'):
        manifest_from_dict(payload)


def test_missing_required_field_is_rejected():
    payload = manifest_to_dict(_manifest())
    del payload['batch_id']

    with pytest.raises(ValueError, match='missing or unknown fields'):
        manifest_from_dict(payload)


def test_writer_refuses_to_overwrite_existing_path(tmp_path):
    target = tmp_path / 'batch.json'
    target.write_text('existing', encoding='utf-8')

    with pytest.raises(FileExistsError):
        write_batch_manifest(_manifest(), target)


def test_writer_and_reader_use_deterministic_utf8_json(tmp_path):
    target = tmp_path / 'batch.json'
    manifest = _manifest()

    written = write_batch_manifest(manifest, target)

    assert written == target
    assert target.read_text(encoding='utf-8').endswith('\n')
    assert read_batch_manifest(target) == manifest


def test_empty_entry_ids_are_valid_before_upload():
    manifest = _manifest()

    assert manifest_from_dict(manifest_to_dict(manifest)).entry_ids == ()


def test_populated_upload_state_round_trips(tmp_path):
    manifest = _manifest()
    manifest = replace(
        manifest,
        status=ManifestStatus.PROCESSING,
        upload_id='upload-123',
        entry_ids=(('proposal-003', 'entry-003'),),
        processing_status='RUNNING',
        verification_status='pending',
    )

    target = tmp_path / 'batch.json'
    restored = read_batch_manifest(write_batch_manifest(manifest, target))

    assert restored == manifest
