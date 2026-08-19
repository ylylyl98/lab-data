"""Focused tests for local batch preflight validation."""

import json
from dataclasses import replace

import pytest
from nomad.datamodel import EntryArchive

from lab_data.ingestion.batch_manifest import (
    BatchManifest,
    CanonicalFile,
    ManifestFile,
    ManifestStatus,
    create_batch_manifest,
)
from lab_data.ingestion.batch_planner import plan_batches
from lab_data.ingestion.batch_preflight import (
    mark_preflight_passed,
    preflight_batch,
)
from lab_data.parsers.archive_serializer import (
    build_entry_archive,
    serialize_entry_archive,
)
from lab_data.schema_packages.schema_package import IngestionReview, OpticalExperiment

CREATED = '2026-01-01T00:00:00Z'
UPDATED = '2026-01-01T00:01:00Z'
TEST_FILE_COUNT = 2


def _write_archive(path, *, needs_review=False, warnings=None):
    experiment = OpticalExperiment(
        sample_id='S1',
        ingestion_review=IngestionReview(
            warnings=warnings or [],
            confidence=1.0,
            needs_review=needs_review,
        ),
    )
    path.write_text(
        json.dumps(serialize_entry_archive(build_entry_archive(experiment))),
        encoding='utf-8',
    )


def _manifest(tmp_path, *, archive_count=1, companion_count=1, **changes):
    archive_files = []
    for index in range(archive_count):
        path = tmp_path / f'archive-{index}.archive.json'
        _write_archive(path)
        archive_files.append(ManifestFile(str(path), f'archives/{path.name}', 'archive'))
    companion_files = []
    for index in range(companion_count):
        path = tmp_path / f'companion-{index}.csv'
        path.write_text('x\n', encoding='utf-8')
        companion_files.append(ManifestFile(str(path), f'raw/{path.name}', 'raw'))
    proposal_ids = [f'proposal-{index}' for index in range(archive_count)]
    planned = plan_batches(proposal_ids, dataset_label='synthetic')
    manifest = create_batch_manifest(
        planned[0],
        archive_files=archive_files,
        companion_files=companion_files,
        created_utc=CREATED,
        updated_utc=UPDATED,
    )
    return replace(manifest, **changes)


def test_valid_synthetic_batch_passes(tmp_path):
    result = preflight_batch(_manifest(tmp_path))

    assert result.passed is True
    assert result.archive_count == 1
    assert result.companion_count == 1
    assert result.total_file_count == TEST_FILE_COUNT
    assert result.errors == ()


def test_missing_archive_fails(tmp_path):
    manifest = _manifest(tmp_path)
    missing = replace(manifest.archive_files[0], source_path=str(tmp_path / 'gone'))

    result = preflight_batch(replace(manifest, archive_files=(missing,)))

    assert result.passed is False
    assert any('missing source file' in error for error in result.errors)


def test_missing_companion_fails(tmp_path):
    manifest = _manifest(tmp_path)
    missing = replace(manifest.companion_files[0], source_path=str(tmp_path / 'gone'))

    result = preflight_batch(replace(manifest, companion_files=(missing,)))

    assert result.passed is False


def test_directory_passed_as_file_fails(tmp_path):
    manifest = _manifest(tmp_path)
    directory = replace(manifest.companion_files[0], source_path=str(tmp_path))

    result = preflight_batch(replace(manifest, companion_files=(directory,)))

    assert any('not a regular file' in error for error in result.errors)


@pytest.mark.parametrize('destination', ['/absolute.csv', r'C:\absolute.csv', '../escape.csv'])
def test_unsafe_destinations_fail(tmp_path, destination):
    manifest = _manifest(tmp_path)
    unsafe = replace(manifest.companion_files[0], destination_path=destination)

    result = preflight_batch(replace(manifest, companion_files=(unsafe,)))

    assert result.passed is False
    assert any('unsafe' in error for error in result.errors)


def test_destination_collision_fails(tmp_path):
    manifest = _manifest(tmp_path)
    duplicate = replace(
        manifest.companion_files[0], destination_path=manifest.archive_files[0].destination_path
    )

    result = preflight_batch(replace(manifest, companion_files=(duplicate,)))

    assert any('duplicate transport destination' in error for error in result.errors)


def test_canonical_references_do_not_require_transport_destinations(tmp_path):
    manifest = _manifest(tmp_path)
    canonical_archive = CanonicalFile(
        manifest.archive_files[0].source_path,
        'Initial Data/file.archive.json',
        'archive',
    )
    canonical_companion = CanonicalFile(
        manifest.companion_files[0].source_path,
        'Processed Data/file.dat',
        'processed',
    )

    result = preflight_batch(
        replace(
            manifest,
            archive_files=(canonical_archive,),
            companion_files=(canonical_companion,),
        )
    )

    assert result.passed is True


@pytest.mark.parametrize(
    'relative_path',
    ['/absolute.csv', r'C:\absolute.csv', r'\\server\share\file.csv', '../escape.csv'],
)
def test_unsafe_canonical_relative_paths_fail(tmp_path, relative_path):
    manifest = _manifest(tmp_path)
    canonical = CanonicalFile(
        manifest.archive_files[0].source_path,
        relative_path,
        'archive',
    )

    result = preflight_batch(replace(manifest, archive_files=(canonical,)))

    assert result.passed is False
    assert any('unsafe' in error for error in result.errors)


def test_malformed_archive_fails(tmp_path):
    manifest = _manifest(tmp_path)
    path = tmp_path / 'bad.archive.json'
    path.write_text('{bad', encoding='utf-8')

    result = preflight_batch(
        replace(manifest, archive_files=(replace(manifest.archive_files[0], source_path=str(path)),))
    )

    assert any('archive read-back failed' in error for error in result.errors)


def test_archive_readback_failure_fails(tmp_path, monkeypatch):
    manifest = _manifest(tmp_path)

    def fail(_payload):
        raise ValueError('not a valid archive')

    monkeypatch.setattr(EntryArchive, 'm_from_dict', fail)
    result = preflight_batch(manifest)

    assert any('archive read-back failed' in error for error in result.errors)


@pytest.mark.parametrize('needs_review,warnings,passed', [(True, [], False), (False, [], True), (False, ['check'], False)])
def test_review_state_controls_preflight(tmp_path, needs_review, warnings, passed):
    manifest = _manifest(tmp_path)
    path = tmp_path / 'review.archive.json'
    _write_archive(path, needs_review=needs_review, warnings=warnings)
    archive = replace(manifest.archive_files[0], source_path=str(path))

    result = preflight_batch(replace(manifest, archive_files=(archive,)))

    assert result.passed is passed


def test_expected_counts_and_archive_count_mismatch_fail(tmp_path):
    manifest = _manifest(tmp_path)

    result = preflight_batch(
        replace(manifest, expected_entry_count=2, expected_file_count=8)
    )

    assert 'expected entry count does not match proposal count' in result.errors
    assert 'archive count does not match expected entry count' in result.errors
    assert 'expected file count does not match represented file count' in result.errors


def test_empty_batch_behavior_is_explicit():
    planned = plan_batches([], dataset_label='empty')
    assert planned == ()


def test_empty_manifest_batch_is_rejected():
    manifest = BatchManifest(
        batch_id='empty-batch',
        batch_number=1,
        dataset_label='empty',
        status=ManifestStatus.PLANNED,
        proposal_ids=(),
        archive_files=(),
        companion_files=(),
        expected_entry_count=0,
        expected_file_count=0,
        publish=False,
        upload_name=None,
        created_utc=CREATED,
        updated_utc=UPDATED,
    )

    result = preflight_batch(manifest)

    assert result.passed is False
    assert 'batch contains no proposals' in result.errors


def test_duplicate_proposal_ids_are_rejected(tmp_path):
    manifest = _manifest(tmp_path)

    result = preflight_batch(
        replace(manifest, proposal_ids=('proposal-0', 'proposal-0'))
    )

    assert 'proposal IDs are not unique' in result.errors


def test_non_planned_status_is_rejected(tmp_path):
    manifest = _manifest(tmp_path)

    result = preflight_batch(replace(manifest, status=ManifestStatus.SUCCESS))

    assert any('status is not planned' in error for error in result.errors)


def test_errors_are_reported_in_deterministic_order(tmp_path):
    manifest = _manifest(tmp_path)
    missing = replace(manifest.companion_files[0], source_path=str(tmp_path / 'missing'))
    unsafe = replace(manifest.archive_files[0], destination_path='../escape')

    result = preflight_batch(
        replace(manifest, archive_files=(unsafe,), companion_files=(missing,))
    )

    assert result.errors == tuple(sorted(result.errors))


def test_valid_nested_destinations_pass(tmp_path):
    manifest = _manifest(tmp_path)
    companion = replace(
        manifest.companion_files[0], destination_path='Processed Data/nested/file.csv'
    )

    assert preflight_batch(replace(manifest, companion_files=(companion,))).passed


def test_preflight_does_not_use_network(monkeypatch, tmp_path):
    import requests

    monkeypatch.setattr(requests, 'get', lambda *args, **kwargs: pytest.fail('network used'))

    assert preflight_batch(_manifest(tmp_path)).passed


def test_mark_preflight_passed_returns_copy_without_mutating_manifest(tmp_path):
    manifest = _manifest(tmp_path)
    result = preflight_batch(manifest)

    updated = mark_preflight_passed(manifest, result)

    assert updated.status is ManifestStatus.PREFLIGHT_PASSED
    assert manifest.status is ManifestStatus.PLANNED
