"""Map an archive draft into a NOMAD :class:`OpticalExperiment`.

This module implements the archive-to-NOMAD mapping. It consumes a lossless
:class:`~lab_data.ingestion.archive_builder.ArchiveDraft` directly and produces
a :class:`~lab_data.schema_packages.schema_package.OpticalExperiment` populated
with the scalar and basic fields (Pass A) plus the gate, electrical-connection,
and file collections (Pass B). Only non-``None`` scalar values are assigned, so
absent optionals remain absent on the resulting experiment.
"""

from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING

from lab_data.schema_packages.schema_package import (
    ElectricalConnection,
    ExperimentFile,
    GateConstraint,
    GateTerm,
    GateValue,
    IngestionReview,
    LineageEdge,
    MetadataProvenance,
    OpticalExperiment,
)

if TYPE_CHECKING:
    from lab_data.ingestion.archive_builder import ArchiveDraft, ReviewDraft

__all__ = ['build_optical_experiment']


_SCALAR_FIELD_MAP: dict[str, str] = {
    'measurement_type': 'measurement_type',
    'measurement_point_label': 'measurement_point_label',
    'temperature_K': 'temperature',
    'magnetic_field_T': 'magnetic_field',
    'excitation_wavelength_nm': 'excitation_wavelength',
    'center_wavelength_nm': 'center_wavelength',
    'excitation_power_uW': 'excitation_power',
    'grating_grooves_per_mm': 'grating',
    'stage_position': 'stage_position',
    'integration_time_s': 'integration_time',
    'averages': 'averages',
    'fixed_top_gate_V': 'fixed_top_gate',
    'active_gate_configuration': 'active_gate_configuration',
    'sweep_direction': 'sweep_direction',
    'bias_start_V': 'bias_start',
    'bias_stop_V': 'bias_stop',
    'back_gate_topology': 'back_gate_topology',
}


def _map_ingestion_review(review_draft: ReviewDraft) -> IngestionReview:
    """Map review values while preserving explicit falsey and null values."""

    review = IngestionReview()
    if review_draft.warnings is not None:
        review.warnings = list(review_draft.warnings)
    if review_draft.confidence is not None:
        review.confidence = review_draft.confidence
    if review_draft.needs_review is not None:
        review.needs_review = review_draft.needs_review
    return review


def _to_json_safe(value: object) -> object:
    """Recursively convert ``value`` into JSON-serializable primitives.

    JSON primitives (``None``, booleans, numbers, and strings) are returned
    unchanged. Lists and tuples become arrays, and dictionaries become objects
    with their existing string keys preserved while their values are converted
    recursively. Dataclass instances are converted through
    :func:`dataclasses.fields`, including only their declared public fields.
    Any other object raises a :class:`TypeError` naming its type.
    """

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_json_safe(item) for key, item in value.items()}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _to_json_safe(getattr(value, field.name))
            for field in dataclasses.fields(value)
            if not field.name.startswith('_')
        }
    raise TypeError(
        f'unsupported provenance value type: {type(value).__name__}'
    )


def build_optical_experiment(archive_draft: ArchiveDraft) -> OpticalExperiment:
    """Build an :class:`OpticalExperiment` from an archive draft.

    Scalar and basic fields are copied from ``archive_draft.sample`` and
    ``archive_draft.experiment`` only when present. NOMAD quantities are
    assigned with their declared units, so no units are embedded manually. Gate
    values, gate constraints, electrical connections, and files are mapped from
    their draft collections in deterministic order. The source draft is never
    mutated.
    """

    experiment = OpticalExperiment()
    experiment_draft = archive_draft.experiment

    if archive_draft.sample.sample_id is not None:
        experiment.sample_id = archive_draft.sample.sample_id

    for source_field, target_field in _SCALAR_FIELD_MAP.items():
        value = getattr(experiment_draft, source_field)
        if value is not None:
            setattr(experiment, target_field, value)

    if experiment_draft.rotations_deg is not None:
        experiment.rotations = list(experiment_draft.rotations_deg)

    for gate, voltage in sorted(experiment_draft.fixed_gate_values.items()):
        experiment.fixed_gate_values.append(GateValue(gate=gate, voltage=voltage))

    for constraint in experiment_draft.gate_constraints:
        experiment.gate_constraints.append(
            GateConstraint(
                raw_expression=constraint.raw_expression,
                control_mode=constraint.control_mode,
                constant=0.0,
                terms=[
                    GateTerm(node=node, coefficient=coefficient)
                    for node, coefficient in sorted(
                        constraint.coefficients.items()
                    )
                ],
            )
        )

    for connection in experiment_draft.electrical_connections:
        experiment.electrical_connections.append(
            ElectricalConnection(
                nodes=list(connection.nodes),
                type=connection.type,
                source_role=connection.source_role,
                raw_expression=connection.raw_expression,
            )
        )

    files_draft = archive_draft.files
    for role in ('raw', 'intermediate', 'processed', 'figure'):
        for path in sorted(getattr(files_draft, f'{role}_files')):
            experiment.files.append(ExperimentFile(path=path, role=role))

    raw_paths = sorted(files_draft.raw_files)
    if raw_paths:
        experiment.raw_data_file = raw_paths[0]

    processed_paths = sorted(files_draft.processed_files)
    if processed_paths:
        experiment.processed_data_file = processed_paths[0]

    for record in archive_draft.provenance:
        experiment.metadata_provenance.append(
            MetadataProvenance(
                field=record.field,
                value=json.dumps(
                    _to_json_safe(record.value),
                    sort_keys=True,
                    separators=(',', ':'),
                ),
                source_type=record.source_type,
                source=record.source,
                method=record.method,
            )
        )

    experiment.lineage.extend(
        LineageEdge(
            source=record.source,
            target=record.target,
            relation=record.relation,
        )
        for record in archive_draft.lineage
    )

    experiment.ingestion_review = _map_ingestion_review(archive_draft.review)

    return experiment
