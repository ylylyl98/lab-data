"""Focused tests for deterministic proposal batching."""

import pytest

from lab_data.ingestion.batch_planner import plan_batches

BATCH_SIZE = 50
TOTAL_PROPOSALS = 1505
EXPECTED_BATCHES = 31
FULL_BATCHES = 30


def test_empty_input_produces_no_batches():
    assert plan_batches([]) == ()


def test_one_proposal_produces_one_item_batch():
    batch = plan_batches(['proposal-001'])[0]

    assert batch.batch_number == 1
    assert batch.proposals == ('proposal-001',)
    assert batch.item_count == 1


def test_exactly_fifty_proposals_fit_one_batch():
    batches = plan_batches([f'proposal-{i:04d}' for i in range(50)])

    assert len(batches) == 1
    assert batches[0].item_count == BATCH_SIZE


def test_fifty_one_proposals_make_a_partial_final_batch():
    proposals = [f'proposal-{i:04d}' for i in range(51)]
    batches = plan_batches(proposals)

    assert [batch.item_count for batch in batches] == [50, 1]
    assert tuple(item for batch in batches for item in batch.proposals) == tuple(
        proposals
    )


def test_1505_proposals_make_thirty_one_batches():
    batches = plan_batches(
        [f'proposal-{i:04d}' for i in range(TOTAL_PROPOSALS)]
    )

    assert len(batches) == EXPECTED_BATCHES
    assert [batch.item_count for batch in batches[:FULL_BATCHES]] == [
        BATCH_SIZE
    ] * FULL_BATCHES
    assert batches[-1].item_count == TOTAL_PROPOSALS % BATCH_SIZE


@pytest.mark.parametrize('batch_size', [0, -1])
def test_non_positive_batch_size_is_rejected(batch_size):
    with pytest.raises(ValueError, match='batch_size must be greater than zero'):
        plan_batches(['proposal-001'], batch_size=batch_size)


def test_input_order_is_preserved_without_sorting():
    proposals = ['proposal-003', 'proposal-001', 'proposal-002']

    assert plan_batches(proposals, batch_size=2)[0].proposals == tuple(proposals[:2])
    assert plan_batches(proposals, batch_size=2)[1].proposals == (proposals[2],)


def test_identical_inputs_produce_identical_membership_and_ids():
    proposals = [f'proposal-{i:04d}' for i in range(7)]

    first = plan_batches(proposals, batch_size=3, dataset_label='YZ247')
    second = plan_batches(proposals, batch_size=3, dataset_label='YZ247')

    assert first == second
    assert [batch.batch_id for batch in first] == [batch.batch_id for batch in second]


def test_batch_id_changes_for_order_membership_or_dataset_label_changes():
    proposals = ['proposal-001', 'proposal-002', 'proposal-003']
    baseline = plan_batches(proposals, dataset_label='YZ247')[0].batch_id

    assert plan_batches(list(reversed(proposals)), dataset_label='YZ247')[0].batch_id != baseline
    assert plan_batches(['proposal-001', 'proposal-002', 'proposal-004'], dataset_label='YZ247')[0].batch_id != baseline
    assert plan_batches(proposals, dataset_label='D356')[0].batch_id != baseline


def test_final_batch_has_no_padding_or_duplicates():
    proposals = ['proposal-001', 'proposal-002', 'proposal-003', 'proposal-004']
    batches = plan_batches(proposals, batch_size=3)

    flattened = [proposal for batch in batches for proposal in batch.proposals]
    assert batches[-1].proposals == ('proposal-004',)
    assert flattened == proposals
    assert len(flattened) == len(set(flattened))
