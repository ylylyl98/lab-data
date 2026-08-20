"""Deterministic, AI-free retrieval over normalized import proposals.

This module intentionally provides retrieval primitives only.  Intent
interpretation, ranking, synthesis, and any semantic/vector retrieval remain
outside the canonical search layer.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from types import MappingProxyType
from typing import Any

from lab_data.ingestion.proposal import ExperimentImportProposal

__all__ = [
    'ExperimentSearchIndex',
    'ExperimentSearchRecord',
    'NumericRange',
    'RelatedFile',
    'SearchLineageEdge',
    'build_search_index',
    'find_related_files',
    'get_experiment',
    'search_experiments',
]


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class NumericRange:
    """Inclusive/exclusive deterministic range for one numeric field."""

    minimum: int | float | None = None
    maximum: int | float | None = None
    include_minimum: bool = True
    include_maximum: bool = True

    def __post_init__(self) -> None:
        for name in ('minimum', 'maximum'):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f'{name} must be a finite number or None')
        if not isinstance(self.include_minimum, bool) or not isinstance(
            self.include_maximum, bool
        ):
            raise TypeError('range inclusivity flags must be bool')
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError('minimum must not exceed maximum')


@dataclass(frozen=True)
class SearchLineageEdge:
    source: str
    target: str
    relation: str


@dataclass(frozen=True)
class RelatedFile:
    path: str
    role: str
    lineage: tuple[SearchLineageEdge, ...] = ()


@dataclass(frozen=True)
class ExperimentSearchRecord:
    experiment_id: str
    metadata: Mapping[str, Any]
    files_by_role: Mapping[str, tuple[str, ...]]
    lineage: tuple[SearchLineageEdge, ...]
    warnings: tuple[str, ...]
    confidence: float
    needs_review: bool
    review_state: str = 'unknown'

    def __post_init__(self) -> None:
        if not isinstance(self.experiment_id, str) or not self.experiment_id:
            raise ValueError('experiment_id must be non-empty')
        if not isinstance(self.review_state, str) or not self.review_state:
            raise ValueError('review_state must be a non-empty string')
        object.__setattr__(self, 'metadata', _freeze(self.metadata))
        object.__setattr__(self, 'files_by_role', _freeze(self.files_by_role))
        object.__setattr__(self, 'lineage', tuple(self.lineage))
        object.__setattr__(self, 'warnings', tuple(self.warnings))


def _record_from_proposal(
    proposal: ExperimentImportProposal,
    experiment_id: str,
) -> ExperimentSearchRecord:
    metadata = {
        key: value
        for key, value in asdict(proposal).items()
        if key
        not in {
            'raw_files',
            'processed_files',
            'figure_files',
            'intermediate_files',
            'warnings',
            'confidence',
            'lineage',
        }
    }
    files_by_role = {
        'raw': tuple(proposal.raw_files),
        'processed': tuple(proposal.processed_files),
        'figure': tuple(proposal.figure_files),
        'intermediate': tuple(proposal.intermediate_files),
    }
    lineage = tuple(
        SearchLineageEdge(edge.source, edge.target, edge.relation)
        for edge in proposal.lineage
    )
    return ExperimentSearchRecord(
        experiment_id=experiment_id,
        metadata=metadata,
        files_by_role=files_by_role,
        lineage=lineage,
        warnings=tuple(proposal.warnings),
        confidence=proposal.confidence,
        needs_review=proposal.needs_review,
    )


@dataclass(frozen=True)
class ExperimentSearchIndex:
    """Immutable deterministic index of proposal snapshots."""

    records: tuple[ExperimentSearchRecord, ...]

    _SEPARATE_FIELDS = frozenset(
        {
            'raw_files',
            'processed_files',
            'figure_files',
            'intermediate_files',
            'warnings',
            'confidence',
            'lineage',
        }
    )
    _NUMERIC_FIELDS = frozenset(
        {
            'temperature_K',
            'magnetic_field_T',
            'excitation_wavelength_nm',
            'center_wavelength_nm',
            'excitation_power_uW',
            'integration_time_s',
            'averages',
            'grating_grooves_per_mm',
            'stage_position',
            'fixed_top_gate_V',
            'bias_start_V',
            'bias_stop_V',
            'confidence',
        }
    )

    def __post_init__(self) -> None:
        records = tuple(self.records)
        if any(not isinstance(record, ExperimentSearchRecord) for record in records):
            raise TypeError('records must contain ExperimentSearchRecord values')
        record_ids = [record.experiment_id for record in records]
        if len(set(record_ids)) != len(record_ids):
            raise ValueError('duplicate experiment IDs are not allowed')
        object.__setattr__(self, 'records', records)

    @classmethod
    def from_proposals(
        cls,
        proposals: Iterable[ExperimentImportProposal],
        *,
        experiment_ids: Sequence[str] | None = None,
    ) -> ExperimentSearchIndex:
        proposal_values = tuple(proposals)
        if experiment_ids is None:
            raise ValueError(
                'experiment_ids are required; inferred IDs are not allowed'
            )
        if len(experiment_ids) != len(proposal_values):
            raise ValueError('experiment_ids count must match proposals count')
        ids = tuple(experiment_ids)
        if any(not isinstance(value, str) or not value for value in ids):
            raise ValueError('experiment_ids must contain non-empty strings')
        records = tuple(
            _record_from_proposal(proposal, experiment_id)
            for proposal, experiment_id in zip(proposal_values, ids, strict=True)
        )
        record_ids = [record.experiment_id for record in records]
        if len(set(record_ids)) != len(record_ids):
            raise ValueError('duplicate experiment IDs are not allowed')
        return cls(records=records)

    def search_experiments(
        self, *, filters: Mapping[str, Any] | None = None
    ) -> tuple[ExperimentSearchRecord, ...]:
        expected = {key: _freeze(value) for key, value in (filters or {}).items()}
        allowed = {
            'experiment_id',
            'needs_review',
            'confidence',
            *self._metadata_keys(),
        }
        unknown = sorted(set(expected) - allowed)
        if unknown:
            raise ValueError(f'unknown experiment filter(s): {", ".join(unknown)}')

        def matches(record: ExperimentSearchRecord) -> bool:
            missing = object()
            for key, value in expected.items():
                actual = (
                    record.experiment_id
                    if key == 'experiment_id'
                    else record.needs_review
                    if key == 'needs_review'
                    else record.confidence
                    if key == 'confidence'
                    else record.metadata.get(key, missing)
                )
                if actual is missing:
                    return False
                if isinstance(value, NumericRange):
                    if key not in self._NUMERIC_FIELDS:
                        raise ValueError(
                            f'numeric ranges are not supported for field: {key}'
                        )
                    if (
                        isinstance(actual, bool)
                        or not isinstance(actual, (int, float))
                        or not math.isfinite(actual)
                    ):
                        return False
                    if value.minimum is not None and (
                        actual < value.minimum
                        or (actual == value.minimum and not value.include_minimum)
                    ):
                        return False
                    if value.maximum is not None and (
                        actual > value.maximum
                        or (actual == value.maximum and not value.include_maximum)
                    ):
                        return False
                elif actual != value:
                    return False
            return True

        return tuple(
            sorted(
                (record for record in self.records if matches(record)),
                key=lambda record: (
                    record.metadata.get('sample_id') or '',
                    record.metadata.get('measurement_type') or '',
                    record.experiment_id,
                ),
            )
        )

    def _metadata_keys(self) -> set[str]:
        return {
            field.name
            for field in fields(ExperimentImportProposal)
            if field.name not in self._SEPARATE_FIELDS
        }

    def get_experiment(self, experiment_id: str) -> ExperimentSearchRecord | None:
        return next(
            (
                record
                for record in self.records
                if record.experiment_id == experiment_id
            ),
            None,
        )

    def find_related_files(
        self, experiment_id: str, *, role: str | None = None
    ) -> tuple[RelatedFile, ...]:
        record = self.get_experiment(experiment_id)
        if record is None:
            return ()
        roles = (role,) if role is not None else tuple(sorted(record.files_by_role))
        if any(current not in record.files_by_role for current in roles):
            raise ValueError(f'unknown file role: {role}')
        result: list[RelatedFile] = []
        for current_role in roles:
            for path in record.files_by_role[current_role]:
                result.append(
                    RelatedFile(
                        path=path,
                        role=current_role,
                        lineage=tuple(
                            edge
                            for edge in record.lineage
                            if path in {edge.source, edge.target}
                        ),
                    )
                )
        return tuple(result)


def build_search_index(
    proposals: Iterable[ExperimentImportProposal],
    *,
    experiment_ids: Sequence[str] | None = None,
) -> ExperimentSearchIndex:
    return ExperimentSearchIndex.from_proposals(
        proposals, experiment_ids=experiment_ids
    )


def search_experiments(
    index: ExperimentSearchIndex,
    *,
    filters: Mapping[str, Any] | None = None,
) -> tuple[ExperimentSearchRecord, ...]:
    return index.search_experiments(filters=filters)


def get_experiment(
    index: ExperimentSearchIndex, experiment_id: str
) -> ExperimentSearchRecord | None:
    return index.get_experiment(experiment_id)


def find_related_files(
    index: ExperimentSearchIndex,
    experiment_id: str,
    *,
    role: str | None = None,
) -> tuple[RelatedFile, ...]:
    return index.find_related_files(experiment_id, role=role)
