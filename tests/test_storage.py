"""Focused tests for storage-root path resolution."""

import pytest

from lab_data.ingestion.batch_manifest import CanonicalFile
from lab_data.storage import StorageRoot


def test_local_root_resolves_nested_canonical_path(tmp_path):
    storage = StorageRoot(tmp_path / 'LabData')

    resolved = storage.resolve('D356/Initial Data/file.csv')

    assert resolved == tmp_path / 'LabData' / 'D356' / 'Initial Data' / 'file.csv'


def test_unc_style_root_is_configurable_without_nas_access():
    storage = StorageRoot(r'\\NAS\LabData')

    resolved = storage.resolve('YZ247/Processed Data/result.dat')

    assert str(resolved).endswith(r'NAS\LabData\YZ247\Processed Data\result.dat')


def test_absolute_under_root_round_trips_to_canonical_path(tmp_path):
    storage = StorageRoot(tmp_path / 'LabData')
    absolute = storage.resolve('YZ247/Initial Data after process/a.csv')

    canonical = storage.canonicalize(absolute)

    assert canonical == 'YZ247/Initial Data after process/a.csv'
    assert storage.resolve(canonical) == absolute


def test_outside_root_absolute_path_is_rejected(tmp_path):
    storage = StorageRoot(tmp_path / 'LabData')

    with pytest.raises(ValueError, match='outside storage root'):
        storage.canonicalize(tmp_path / 'Other' / 'file.csv')


@pytest.mark.parametrize(
    'relative_path',
    [
        '../file.csv',
        'D356/../../file.csv',
        r'C:\LabData\file.csv',
        r'\\NAS\LabData\file.csv',
        '/file.csv',
        '',
    ],
)
def test_unsafe_canonical_paths_are_rejected(tmp_path, relative_path):
    storage = StorageRoot(tmp_path / 'LabData')

    with pytest.raises(ValueError):
        storage.resolve(relative_path)


def test_valid_nested_paths_are_preserved(tmp_path):
    storage = StorageRoot(tmp_path)

    assert storage.canonicalize(
        storage.resolve('D356/Initial Data/file.csv')
    ) == 'D356/Initial Data/file.csv'
    assert storage.resolve('YZ247/Processed Data/result.dat').name == 'result.dat'


def test_same_canonical_path_can_use_different_runtime_roots(tmp_path):
    relative = 'D356/Initial Data/file.csv'
    first = StorageRoot(tmp_path / 'PC')
    second = StorageRoot(tmp_path / 'NAS')

    assert first.resolve(relative) != second.resolve(relative)
    assert first.canonicalize(first.resolve(relative)) == relative
    assert second.canonicalize(second.resolve(relative)) == relative


def test_resolution_does_not_require_target_existence(tmp_path):
    resolved = StorageRoot(tmp_path).resolve('missing/future/file.csv')

    assert not resolved.exists()


def test_canonical_file_identity_remains_relative_and_unchanged(tmp_path):
    reference = CanonicalFile(
        str(tmp_path / 'file.csv'),
        'D356/Initial Data/file.csv',
        'raw',
    )
    storage = StorageRoot(tmp_path)

    storage.resolve(reference.relative_path)

    assert reference.relative_path == 'D356/Initial Data/file.csv'


def test_storage_root_does_not_create_or_modify_files(tmp_path):
    storage = StorageRoot(tmp_path / 'configured-root')
    before = sorted(path.name for path in tmp_path.iterdir())

    storage.resolve('future/file.csv')

    assert sorted(path.name for path in tmp_path.iterdir()) == before
