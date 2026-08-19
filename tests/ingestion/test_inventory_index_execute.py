"""Focused tests for executing a metadata-indexing plan."""

from pathlib import Path

import pytest

from lab_data.ingestion.inventory_index_bridge import (
    execute_metadata_indexing,
    plan_metadata_indexing,
)
from lab_data.ingestion.inventory_store import (
    INVENTORY_MISSING,
    INVENTORY_PRESENT,
    METADATA_FAILED,
    METADATA_INDEXED,
    METADATA_PENDING,
    METADATA_STALE,
    InventoryRecord,
    InventoryStore,
)
from lab_data.storage import StorageRoot


def _record(
    relative_path: str,
    *,
    inventory_status: str = INVENTORY_PRESENT,
    metadata_status: str,
) -> InventoryRecord:
    return InventoryRecord(
        relative_path=relative_path,
        size_bytes=1,
        mtime_ns=1,
        inventory_status=inventory_status,
        metadata_status=metadata_status,
    )


def _write(path: Path, content: str = '') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def _setup(tmp_path: Path):
    root = tmp_path / 'root'
    root.mkdir(parents=True)
    storage = StorageRoot(root)
    store = InventoryStore(tmp_path / 'inventory.db')
    return storage, store


def test_pending_and_stale_are_indexed_when_clean(tmp_path):
    storage, store = _setup(tmp_path)
    _write(storage.root / 'D356' / 'Initial Data' / 'D356_9T_3.6K_PL_633nm.csv')
    _write(storage.root / 'D356' / 'Initial Data' / 'D356_9T_3.6K_PL_532nm.csv')
    store.upsert(
        _record(
            'D356/Initial Data/D356_9T_3.6K_PL_633nm.csv',
            metadata_status=METADATA_PENDING,
        )
    )
    store.upsert(
        _record(
            'D356/Initial Data/D356_9T_3.6K_PL_532nm.csv',
            metadata_status=METADATA_STALE,
        )
    )

    plan = plan_metadata_indexing(storage, store)
    result = execute_metadata_indexing(plan, storage, store)

    assert result.units_processed == 1
    assert result.proposals_produced == 2  # noqa: PLR2004
    assert set(result.indexed_paths) == {
        'D356/Initial Data/D356_9T_3.6K_PL_633nm.csv',
        'D356/Initial Data/D356_9T_3.6K_PL_532nm.csv',
    }
    assert result.failed_paths == ()
    assert result.errors == ()
    assert store.get('D356/Initial Data/D356_9T_3.6K_PL_633nm.csv').metadata_status == (
        METADATA_INDEXED
    )
    assert store.get('D356/Initial Data/D356_9T_3.6K_PL_532nm.csv').metadata_status == (
        METADATA_INDEXED
    )
    store.close()


def test_indexed_missing_and_failed_are_never_selected(tmp_path):
    storage, store = _setup(tmp_path)
    _write(storage.root / 'D356' / 'Initial Data' / 'D356_9T_3.6K_PL_633nm.csv')
    store.upsert(
        _record(
            'D356/Initial Data/D356_9T_3.6K_PL_633nm.csv',
            metadata_status=METADATA_PENDING,
        )
    )
    store.upsert(_record('indexed.csv', metadata_status=METADATA_INDEXED))
    store.upsert(
        _record(
            'missing.csv',
            inventory_status=INVENTORY_MISSING,
            metadata_status=METADATA_PENDING,
        )
    )
    store.upsert(_record('failed.csv', metadata_status=METADATA_FAILED))

    plan = plan_metadata_indexing(storage, store)
    result = execute_metadata_indexing(plan, storage, store)

    assert {record.relative_path for record in result.candidate_records} == {
        'D356/Initial Data/D356_9T_3.6K_PL_633nm.csv'
    }
    assert store.get('indexed.csv').metadata_status == METADATA_INDEXED
    assert store.get('missing.csv').inventory_status == INVENTORY_MISSING
    assert store.get('failed.csv').metadata_status == METADATA_FAILED
    store.close()


def test_scanner_only_invoked_for_affected_units(tmp_path):
    storage, store = _setup(tmp_path)
    _write(storage.root / 'D356' / 'Initial Data' / 'D356_9T_3.6K_PL_633nm.csv')
    _write(storage.root / 'D357' / 'Initial Data' / 'D357_REF.csv')
    store.upsert(
        _record(
            'D356/Initial Data/D356_9T_3.6K_PL_633nm.csv',
            metadata_status=METADATA_PENDING,
        )
    )
    store.upsert(
        _record('D357/Initial Data/D357_REF.csv', metadata_status=METADATA_PENDING)
    )

    calls = []

    def scanner(root, paths):
        calls.append(tuple(paths))
        from lab_data.ingestion.scanner import scan_relative_files

        return scan_relative_files(root, paths)

    plan = plan_metadata_indexing(storage, store)
    execute_metadata_indexing(plan, storage, store, scanner=scanner)

    assert len(calls) == 2  # noqa: PLR2004
    assert ('D356/Initial Data/D356_9T_3.6K_PL_633nm.csv',) in calls
    assert ('D357/Initial Data/D357_REF.csv',) in calls
    store.close()


def test_failure_is_not_falsely_indexed(tmp_path):
    storage, store = _setup(tmp_path)
    _write(storage.root / 'D356' / 'Initial Data' / 'D356_9T_3.6K_PL_633nm.csv')
    store.upsert(
        _record(
            'D356/Initial Data/D356_9T_3.6K_PL_633nm.csv',
            metadata_status=METADATA_PENDING,
        )
    )

    def failing_scanner(root, paths):
        raise RuntimeError('boom')

    plan = plan_metadata_indexing(storage, store)
    result = execute_metadata_indexing(
        plan, storage, store, scanner=failing_scanner, parser_version='scanner-v1'
    )

    assert result.units_processed == 0
    assert result.indexed_paths == ()
    assert len(result.errors) == 1
    assert store.get('D356/Initial Data/D356_9T_3.6K_PL_633nm.csv').metadata_status == (
        METADATA_PENDING
    )
    assert (
        store.get('D356/Initial Data/D356_9T_3.6K_PL_633nm.csv').parser_version is None
    )
    store.close()


def test_ambiguous_proposal_leaves_path_unchanged(tmp_path):
    storage, store = _setup(tmp_path)
    _write(storage.root / 'D356' / 'Initial Data' / 'D356_9T_3.6K_PL_633nm.csv')
    store.upsert(
        _record(
            'D356/Initial Data/D356_9T_3.6K_PL_633nm.csv',
            metadata_status=METADATA_PENDING,
        )
    )

    class _AmbiguousProposal:
        experiments = []
        unresolved_files = []

    class _AmbiguousExperiment:
        needs_review = True
        raw_files = ['D356/Initial Data/D356_9T_3.6K_PL_633nm.csv']
        processed_files = []
        figure_files = []
        intermediate_files = []

    _AmbiguousProposal.experiments = [_AmbiguousExperiment()]

    plan = plan_metadata_indexing(storage, store)
    result = execute_metadata_indexing(
        plan,
        storage,
        store,
        proposal_builder=lambda scan_result: _AmbiguousProposal(),
        parser_version='scanner-v1',
    )

    assert result.indexed_paths == ()
    assert result.failed_paths == ()
    assert result.warnings
    assert store.get('D356/Initial Data/D356_9T_3.6K_PL_633nm.csv').metadata_status == (
        METADATA_PENDING
    )
    assert (
        store.get('D356/Initial Data/D356_9T_3.6K_PL_633nm.csv').parser_version is None
    )
    store.close()


def test_rerun_with_no_selected_records_produces_no_scanner_work(tmp_path):
    storage, store = _setup(tmp_path)
    _write(storage.root / 'D356' / 'Initial Data' / 'D356_9T_3.6K_PL_633nm.csv')
    store.upsert(
        _record(
            'D356/Initial Data/D356_9T_3.6K_PL_633nm.csv',
            metadata_status=METADATA_INDEXED,
        )
    )

    calls = []

    def scanner(root, paths):
        calls.append(tuple(paths))
        from lab_data.ingestion.scanner import scan_relative_files

        return scan_relative_files(root, paths)

    plan = plan_metadata_indexing(storage, store)
    result = execute_metadata_indexing(plan, storage, store, scanner=scanner)

    assert result.units_processed == 0
    assert calls == []
    store.close()


def test_omitted_parser_version_preserves_backward_compatibility(tmp_path):
    storage, store = _setup(tmp_path)
    _write(storage.root / 'D356' / 'Initial Data' / 'D356_9T_3.6K_PL_633nm.csv')
    store.upsert(
        _record(
            'D356/Initial Data/D356_9T_3.6K_PL_633nm.csv',
            metadata_status=METADATA_PENDING,
        )
    )

    plan = plan_metadata_indexing(storage, store)
    execute_metadata_indexing(plan, storage, store)

    assert (
        store.get('D356/Initial Data/D356_9T_3.6K_PL_633nm.csv').parser_version is None
    )
    store.close()


def test_supplied_parser_version_is_persisted_atomically(tmp_path):
    storage, store = _setup(tmp_path)
    source = storage.root / 'D356' / 'Initial Data' / 'D356_9T_3.6K_PL_633nm.csv'
    _write(source, 'signal')
    store.upsert(
        _record(
            'D356/Initial Data/D356_9T_3.6K_PL_633nm.csv',
            metadata_status=METADATA_PENDING,
        )
    )

    plan = plan_metadata_indexing(storage, store)
    result = execute_metadata_indexing(
        plan, storage, store, parser_version='scanner-v1'
    )

    stored = store.get('D356/Initial Data/D356_9T_3.6K_PL_633nm.csv')
    assert result.parser_version == 'scanner-v1'
    assert stored.metadata_status == METADATA_INDEXED
    assert stored.parser_version == 'scanner-v1'
    assert stored.size_bytes == 1  # noqa: PLR2004 - status update preserves inventory
    store.close()


def test_changed_parser_version_updates_stale_record(tmp_path):
    storage, store = _setup(tmp_path)
    path = 'D356/Initial Data/D356_9T_3.6K_PL_633nm.csv'
    _write(storage.root / path, 'signal')
    store.upsert(_record(path, metadata_status=METADATA_PENDING))
    execute_metadata_indexing(
        plan_metadata_indexing(storage, store),
        storage,
        store,
        parser_version='scanner-v1',
    )
    store.update_metadata_status(path, METADATA_STALE)

    execute_metadata_indexing(
        plan_metadata_indexing(storage, store),
        storage,
        store,
        parser_version='scanner-v2',
    )

    assert store.get(path).parser_version == 'scanner-v2'
    assert store.get(path).metadata_status == METADATA_INDEXED
    store.close()


def test_same_parser_version_rerun_is_idempotent(tmp_path):
    storage, store = _setup(tmp_path)
    path = 'D356/Initial Data/D356_9T_3.6K_PL_633nm.csv'
    source = storage.root / path
    _write(source, 'signal')
    store.upsert(_record(path, metadata_status=METADATA_PENDING))
    execute_metadata_indexing(
        plan_metadata_indexing(storage, store),
        storage,
        store,
        parser_version='scanner-v1',
    )
    first = store.get(path)
    store.update_metadata_status(path, METADATA_STALE)
    execute_metadata_indexing(
        plan_metadata_indexing(storage, store),
        storage,
        store,
        parser_version='scanner-v1',
    )
    second = store.get(path)

    assert second.parser_version == first.parser_version == 'scanner-v1'
    assert second.metadata_status == METADATA_INDEXED
    assert source.read_text(encoding='utf-8') == 'signal'
    store.close()


def test_invalid_parser_version_is_rejected_before_scanning(tmp_path):
    storage, store = _setup(tmp_path)
    path = 'D356/Initial Data/D356_9T_3.6K_PL_633nm.csv'
    _write(storage.root / path, 'signal')
    store.upsert(_record(path, metadata_status=METADATA_PENDING))
    plan = plan_metadata_indexing(storage, store)

    with pytest.raises(ValueError, match='safe string'):
        execute_metadata_indexing(plan, storage, store, parser_version='\n')

    assert store.get(path).metadata_status == METADATA_PENDING
    assert store.get(path).parser_version is None
    store.close()


@pytest.mark.parametrize('runtime_parser_version', [None, 'scanner-v1'])
def test_plan_parser_version_mismatch_is_rejected_before_scanning_or_mutation(
    tmp_path, runtime_parser_version
):
    storage, store = _setup(tmp_path)
    path = 'D356/Initial Data/D356_9T_3.6K_PL_633nm.csv'
    _write(storage.root / path, 'signal')
    store.upsert(_record(path, metadata_status=METADATA_PENDING))
    plan = plan_metadata_indexing(
        storage,
        store,
        requested_parser_version='scanner-v2',
    )
    before = store.list_records()
    calls = []

    def scanner(_root, paths):
        calls.append(tuple(paths))
        raise AssertionError('scanner must not run on parser-version mismatch')

    with pytest.raises(ValueError, match='must match plan.requested_parser_version'):
        execute_metadata_indexing(
            plan,
            storage,
            store,
            scanner=scanner,
            parser_version=runtime_parser_version,
        )

    assert calls == []
    assert store.list_records() == before
    store.close()


def test_canonical_paths_are_forward_slash_in_result(tmp_path):
    storage, store = _setup(tmp_path)
    _write(storage.root / 'D356' / 'Initial Data' / 'D356_9T_3.6K_PL_633nm.csv')
    store.upsert(
        _record(
            'D356\\Initial Data\\D356_9T_3.6K_PL_633nm.csv',
            metadata_status=METADATA_PENDING,
        )
    )

    plan = plan_metadata_indexing(storage, store)
    result = execute_metadata_indexing(plan, storage, store)

    assert result.indexed_paths == ('D356/Initial Data/D356_9T_3.6K_PL_633nm.csv',)
    assert '\\' not in result.indexed_paths[0]
    store.close()
