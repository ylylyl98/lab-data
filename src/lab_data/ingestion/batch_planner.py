"""Deterministically split an ordered proposal sequence into batches."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = ['PlannedBatch', 'plan_batches']


@dataclass(frozen=True)
class PlannedBatch:
    """One immutable, ordered batch produced by :func:`plan_batches`."""

    batch_number: int
    batch_id: str
    proposals: tuple[str, ...]
    dataset_label: str | None = None

    @property
    def item_count(self) -> int:
        """Return the number of proposals in this batch."""

        return len(self.proposals)


def _stable_batch_id(
    proposals: tuple[str, ...],
    *,
    batch_number: int,
    batch_size: int,
    dataset_label: str | None,
) -> str:
    """Build an identifier from canonical JSON and a stable SHA-256 digest."""

    identity = {
        'batch_number': batch_number,
        'batch_size': batch_size,
        'dataset_label': dataset_label,
        'proposals': proposals,
    }
    encoded = json.dumps(
        identity, ensure_ascii=False, separators=(',', ':'), sort_keys=True
    ).encode('utf-8')
    digest = hashlib.sha256(encoded).hexdigest()[:12]
    label = re.sub(r'[^A-Za-z0-9]+', '-', dataset_label or 'dataset').strip('-')
    return f'{label or "dataset"}-batch-{batch_number:03d}-{digest}'


def plan_batches(
    proposals: Sequence[str],
    *,
    batch_size: int = 50,
    dataset_label: str | None = None,
) -> tuple[PlannedBatch, ...]:
    """Split an already ordered sequence into stable consecutive batches.

    Proposal identities must be strings supplied in the caller's deterministic
    order. The planner never sorts, scans files, uses time, or generates random
    identifiers.
    """

    if batch_size <= 0:
        raise ValueError('batch_size must be greater than zero')
    if dataset_label is not None and not isinstance(dataset_label, str):
        raise TypeError('dataset_label must be a string or None')

    ordered = tuple(proposals)
    if any(not isinstance(proposal, str) for proposal in ordered):
        raise TypeError('proposals must contain only string identities')

    batches = []
    for offset in range(0, len(ordered), batch_size):
        batch_number = offset // batch_size + 1
        membership = ordered[offset : offset + batch_size]
        batches.append(
            PlannedBatch(
                batch_number=batch_number,
                batch_id=_stable_batch_id(
                    membership,
                    batch_number=batch_number,
                    batch_size=batch_size,
                    dataset_label=dataset_label,
                ),
                proposals=membership,
                dataset_label=dataset_label,
            )
        )
    return tuple(batches)
