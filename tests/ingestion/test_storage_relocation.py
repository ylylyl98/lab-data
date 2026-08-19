import sqlite3
from pathlib import Path

import pytest

from lab_data.ingestion import storage_relocation
from lab_data.ingestion.inventory_store import (
    INVENTORY_MISSING,
    INVENTORY_PRESENT,
    METADATA_INDEXED,
    InventoryRecord,
    InventoryStore,
)
from lab_data.ingestion.storage_relocation import validate_storage_relocation


def _record(path: str, size: int, mtime: int, status: str = INVENTORY_PRESENT):
    return InventoryRecord(
        relative_path=path,
        size_bytes=size,
        mtime_ns=mtime,
        inventory_status=status,
        metadata_status=METADATA_INDEXED,
    )


def _db(tmp_path: Path, records: list[InventoryRecord]) -> Path:
    path = tmp_path / 'inventory.db'
    with InventoryStore(path) as store:
        for record in records:
            store.upsert(record)
    return path


def _raw_db(tmp_path: Path, rows: list[tuple[object, ...]]) -> Path:
    path = tmp_path / 'raw-inventory.db'
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE inventory_records (
                relative_path TEXT, size_bytes INTEGER, mtime_ns INTEGER,
                inventory_status TEXT
            )"""
        )
        connection.executemany(
            'INSERT INTO inventory_records VALUES (?, ?, ?, ?)', rows
        )
    return path


def test_clean_relocation_matches_present_records_and_skips_missing_inventory(tmp_path):
    root = tmp_path / 'root'
    (root / 'YZ247').mkdir(parents=True)
    payload = root / 'YZ247' / 'a.dat'
    payload.write_bytes(b'abc')
    db = _db(
        tmp_path,
        [
            _record('YZ247/a.dat', 3, payload.stat().st_mtime_ns),
            _record('YZ247/old.dat', 0, 0, INVENTORY_MISSING),
        ],
    )

    result = validate_storage_relocation(db, root)

    assert result.complete
    assert result.total_inventory_records == 2  # noqa: PLR2004
    assert result.present_inventory_records == 1
    assert result.missing_inventory_records == 1
    assert result.matched_count == 1
    assert result.blockers == ()


def test_missing_nonregular_and_size_mismatch_are_explicit_blockers(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'directory').mkdir()
    (root / 'wrong.bin').write_bytes(b'x')
    db = _db(
        tmp_path,
        [
            _record('missing.bin', 2, 0),
            _record('directory', 0, 0),
            _record('wrong.bin', 4, 0),
        ],
    )

    result = validate_storage_relocation(db, root)

    assert result.missing_count == 1
    assert result.non_regular_count == 1
    assert result.size_mismatch_count == 1
    assert result.blockers


@pytest.mark.parametrize(
    ('relative_path', 'size', 'expected_text'),
    [
        ('missing.bin', 2, 'candidate is missing'),
        ('directory', 0, 'candidate is not a regular file'),
    ],
)
def test_missing_and_nonregular_each_add_an_independent_blocker(
    tmp_path, relative_path, size, expected_text
):
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'directory').mkdir()
    db = _db(tmp_path, [_record(relative_path, size, 0)])

    result = validate_storage_relocation(db, root)

    assert result.blockers == (f'{relative_path}: {expected_text}',)


def test_mtime_is_opt_in_and_does_not_stat_as_blocker_when_disabled(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    payload = root / 'a.dat'
    payload.write_bytes(b'abc')
    db = _db(tmp_path, [_record('a.dat', 3, payload.stat().st_mtime_ns + 1)])

    disabled = validate_storage_relocation(db, root)
    enabled = validate_storage_relocation(db, root, compare_mtime=True)

    assert disabled.matched_count == 1
    assert disabled.mtime_mismatch_count == 0
    assert disabled.blockers == ()
    assert enabled.mtime_mismatch_count == 1
    assert enabled.blockers


def test_partial_coverage_is_deterministic_and_reports_remaining(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    records = []
    for name in ('c', 'a', 'b'):
        path = root / f'{name}.dat'
        path.write_bytes(name.encode())
        records.append(_record(f'{name}.dat', len(name), path.stat().st_mtime_ns))
    # Names are deliberately inserted in non-sorted order; SQLite query order
    # must still make the bounded sample stable.
    db = _db(tmp_path, records)
    first = validate_storage_relocation(db, root, max_records=2)
    second = validate_storage_relocation(db, root, max_records=2)

    assert first == second
    assert first.records == ()
    assert first.validated_records == 2  # noqa: PLR2004
    assert first.remaining_records == 1
    assert not first.complete


def test_read_only_validation_does_not_create_or_modify_database(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    payload = root / 'a.dat'
    payload.write_bytes(b'abc')
    db = _db(tmp_path, [_record('a.dat', 3, payload.stat().st_mtime_ns)])
    before = db.read_bytes()

    result = validate_storage_relocation(db, root)

    assert result.blockers == ()
    assert db.read_bytes() == before
    with sqlite3.connect(db) as connection:
        assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_requires_absolute_paths_and_existing_directory(tmp_path):
    db = _db(tmp_path, [])
    with pytest.raises(ValueError, match='inventory_db_path must be absolute'):
        validate_storage_relocation(Path('relative.db'), tmp_path)
    with pytest.raises(ValueError, match='candidate_storage_root must be absolute'):
        validate_storage_relocation(db, Path('relative'))
    missing = tmp_path / 'missing'
    result = validate_storage_relocation(db, missing)
    assert result.blockers


def test_traversal_in_inventory_is_reported_without_escape(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    db = tmp_path / 'inventory.db'
    with sqlite3.connect(db) as connection:
        connection.executescript(
            """
            CREATE TABLE inventory_records (
                relative_path TEXT, size_bytes INTEGER, mtime_ns INTEGER,
                inventory_status TEXT
            );
            INSERT INTO inventory_records VALUES ('../outside', 1, 1, 'present');
            """
        )

    result = validate_storage_relocation(db, root)

    assert result.validated_records == 1
    assert result.unsafe_path_count == 1
    assert result.invalid_count == 0
    assert result.blockers


def test_invalid_selected_inventory_row_is_not_complete(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    db = tmp_path / 'inventory.db'
    with sqlite3.connect(db) as connection:
        connection.executescript(
            """
            CREATE TABLE inventory_records (
                relative_path TEXT, size_bytes TEXT, mtime_ns INTEGER,
                inventory_status TEXT
            );
            INSERT INTO inventory_records VALUES ('bad.dat', 'not-an-int', 1, 'present');
            """
        )

    result = validate_storage_relocation(db, root)

    assert result.validated_records == 1
    assert result.invalid_count == 1
    assert result.remaining_records == 0
    assert not result.complete
    assert result.blockers


def test_problem_details_are_deterministically_capped_but_counts_are_exact(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    good = root / '000-good.dat'
    good.write_bytes(b'ok')
    rows = [('000-good.dat', 2, good.stat().st_mtime_ns, 'present')]
    rows.extend((f'{index:03d}-missing.dat', 1, 0, 'present') for index in range(1, 51))
    for index in range(51, 101):
        wrong = root / f'{index:03d}-wrong.dat'
        wrong.write_bytes(b'x')
        rows.append((wrong.name, 2, 0, 'present'))
    db = _raw_db(tmp_path, rows)

    result = validate_storage_relocation(db, root, max_problem_records=3)

    assert result.complete is True
    assert result.present_inventory_records == 101  # noqa: PLR2004
    assert result.validated_records == 101  # noqa: PLR2004
    assert result.matched_count == 1
    assert result.missing_count == 50  # noqa: PLR2004
    assert result.size_mismatch_count == 50  # noqa: PLR2004
    assert result.problem_count == 100  # noqa: PLR2004
    assert result.omitted_problem_records == 97  # noqa: PLR2004
    assert len(result.records) == 3  # noqa: PLR2004
    assert [record.relative_path for record in result.records] == [
        '001-missing.dat',
        '002-missing.dat',
        '003-missing.dat',
    ]
    assert (
        result.blockers[-1] == '97 additional relocation problems omitted from details'
    )


def test_zero_problem_detail_cap_keeps_only_bounded_summary(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    db = _raw_db(tmp_path, [('missing.dat', 1, 0, 'present')])

    result = validate_storage_relocation(db, root, max_problem_records=0)

    assert result.records == ()
    assert result.problem_count == 1
    assert result.omitted_problem_records == 1
    assert result.blockers == ('1 additional relocation problems omitted from details',)


@pytest.mark.parametrize('value', [True, -1, '3', 1.5])
def test_problem_detail_cap_requires_nonnegative_integer(tmp_path, value):
    root = tmp_path / 'root'
    root.mkdir()
    db = _db(tmp_path, [])
    with pytest.raises(ValueError, match='max_problem_records'):
        validate_storage_relocation(db, root, max_problem_records=value)


def test_multi_thousand_clean_fixture_has_bounded_details_and_blockers(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    rows = []
    for index in range(2048):
        relative = f'YZ247/{index:04d}.dat'
        path = root / relative
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b'x')
        rows.append((relative, 1, path.stat().st_mtime_ns, 'present'))
    db = _raw_db(tmp_path, rows)

    result = validate_storage_relocation(db, root)

    assert result.complete
    assert result.present_inventory_records == 2048  # noqa: PLR2004
    assert result.validated_records == 2048  # noqa: PLR2004
    assert result.matched_count == 2048  # noqa: PLR2004
    assert result.problem_count == 0
    assert result.records == ()
    assert result.blockers == ()


def test_symlink_escape_is_blocked_when_supported(tmp_path):
    root = tmp_path / 'root'
    outside = tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    target = outside / 'secret.dat'
    target.write_bytes(b'secret')
    link = root / 'link.dat'
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip('symlinks unavailable')
    db = _db(tmp_path, [_record('link.dat', 6, target.stat().st_mtime_ns)])

    result = validate_storage_relocation(db, root)

    assert result.records[0].outcome == 'unsafe_path'
    assert result.blockers


def test_reparse_component_is_blocked_without_following(tmp_path, monkeypatch):
    root = tmp_path / 'root'
    root.mkdir()
    payload = root / 'reparse.dat'
    payload.write_bytes(b'payload')
    db = _db(tmp_path, [_record('reparse.dat', 7, payload.stat().st_mtime_ns)])

    monkeypatch.setattr(
        Path,
        'is_junction',
        lambda path: path.name == 'reparse.dat',
        raising=False,
    )

    result = validate_storage_relocation(db, root)

    assert storage_relocation._is_reparse_component(payload)
    assert result.records[0].outcome == 'unsafe_path'
    assert result.blockers
