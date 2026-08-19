"""Focused tests for scanning a supplied subset of relative files."""

import pytest

from lab_data.ingestion.scanner import scan_directory, scan_relative_files


def _write(path, content: str = '') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def test_supplied_subset_is_honored(tmp_path):
    _write(tmp_path / 'Initial Data' / 'D356_9T_3.6K_PL_633nm.csv')
    _write(tmp_path / 'Processed Data' / 'D356_9T_3.6K_PL_633nm_PL.dat')
    _write(tmp_path / 'Initial Data' / 'D357_REF.csv')

    result = scan_relative_files(
        tmp_path,
        ['Initial Data/D356_9T_3.6K_PL_633nm.csv'],
    )

    assert len(result.experiments) == 1
    assert result.experiments[0].raw_files == ['Initial Data/D356_9T_3.6K_PL_633nm.csv']
    assert result.experiments[0].processed_files == []
    assert result.sample_id == 'D356'
    assert result.unclassified_files == []


def test_supplied_related_files_group_identically(tmp_path):
    _write(tmp_path / 'Initial Data' / 'D356_9T_3.6K_PL_633nm.csv')
    _write(tmp_path / 'Processed Data' / 'D356_9T_3.6K_PL_633nm_PL.dat')

    subset = scan_relative_files(
        tmp_path,
        [
            'Processed Data/D356_9T_3.6K_PL_633nm_PL.dat',
            'Initial Data/D356_9T_3.6K_PL_633nm.csv',
        ],
    )
    full = scan_directory(tmp_path)

    assert [e.raw_files for e in subset.experiments] == [
        e.raw_files for e in full.experiments
    ]
    assert [e.processed_files for e in subset.experiments] == [
        e.processed_files for e in full.experiments
    ]
    assert subset.experiments[0].metadata == full.experiments[0].metadata


def test_relative_ordering_is_deterministic(tmp_path):
    _write(tmp_path / 'Initial Data' / 'D356_9T_3.6K_PL_633nm.csv')
    _write(tmp_path / 'Initial Data' / 'D357_REF.csv')

    first = scan_relative_files(
        tmp_path,
        [
            'Initial Data/D357_REF.csv',
            'Initial Data/D356_9T_3.6K_PL_633nm.csv',
        ],
    )
    second = scan_relative_files(
        tmp_path,
        [
            'Initial Data/D357_REF.csv',
            'Initial Data/D356_9T_3.6K_PL_633nm.csv',
        ],
    )

    assert first.to_json() == second.to_json()
    assert [e.metadata.sample_id for e in first.experiments] == ['D356', 'D357']


@pytest.mark.parametrize(
    'relative',
    [
        '../outside.csv',
        'D356/../../outside.csv',
        '/abs.csv',
        r'C:\abs.csv',
        r'\\NAS\share\file.csv',
        '',
    ],
)
def test_invalid_or_escaping_candidates_reject(tmp_path, relative):
    _write(tmp_path / 'Initial Data' / 'D356_9T_3.6K_PL_633nm.csv')

    with pytest.raises(ValueError):
        scan_relative_files(tmp_path, [relative])


def test_missing_supplied_file_rejects(tmp_path):
    _write(tmp_path / 'Initial Data' / 'D356_9T_3.6K_PL_633nm.csv')

    with pytest.raises(FileNotFoundError, match='supplied file does not exist'):
        scan_relative_files(tmp_path, ['Initial Data/missing.csv'])


def test_non_string_candidate_rejects(tmp_path):
    with pytest.raises(TypeError, match='only strings'):
        scan_relative_files(tmp_path, [123])  # type: ignore[list-item]


def test_duplicate_candidates_are_deduplicated(tmp_path):
    _write(tmp_path / 'Initial Data' / 'D356_9T_3.6K_PL_633nm.csv')

    result = scan_relative_files(
        tmp_path,
        [
            'Initial Data/D356_9T_3.6K_PL_633nm.csv',
            'Initial Data/D356_9T_3.6K_PL_633nm.csv',
        ],
    )

    assert len(result.experiments) == 1
    assert result.experiments[0].raw_files == ['Initial Data/D356_9T_3.6K_PL_633nm.csv']


def test_unsupported_extension_still_unclassified(tmp_path):
    _write(tmp_path / 'Initial Data' / 'notes.txt')

    result = scan_relative_files(tmp_path, ['Initial Data/notes.txt'])

    assert result.experiments == []
    assert result.unclassified_files == ['Initial Data/notes.txt']
    assert any('unsupported extension' in warning for warning in result.warnings)
