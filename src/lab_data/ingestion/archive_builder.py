"""Lossless JSON-serializable archive draft models.

This module defines the :class:`ArchiveDraft` container used to hold every
piece of information an import proposal must eventually map into a NOMAD
archive. It is a pure data model: values are stored verbatim, ``None`` values
and relative file paths are preserved unchanged, and no re-parsing,
re-interpretation, or NOMAD serialization is performed here.

The draft is organised into the sections that a future mapping step will
consume: ``sample``, ``experiment``, ``files``, ``provenance``, ``lineage``,
and ``review``. Nested gate and wiring objects reuse the
:class:`~lab_data.ingestion.scanner.GateConstraint` and
:class:`~lab_data.ingestion.scanner.ElectricalConnection` types, while
provenance and lineage entries reuse the JSON-safe
:class:`~lab_data.ingestion.proposal.MetadataProvenance` and
:class:`~lab_data.ingestion.proposal.LineageEdge` types.
"""

import json
import sys
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path

from lab_data.ingestion.proposal import (
    ExperimentImportProposal,
    ImportProposal,
    LineageEdge,
    MetadataProvenance,
    build_import_proposal,
)
from lab_data.ingestion.scanner import (
    ElectricalConnection,
    GateConstraint,
    scan_directory,
)

__all__ = [
    'ArchiveDraft',
    'ExperimentDraft',
    'FileDraft',
    'ReviewDraft',
    'SampleDraft',
    'build_archive_draft',
    'main',
]


@dataclass
class SampleDraft:
    """Sample-level identity carried by an archive draft."""

    sample_id: str | None = None


@dataclass
class ExperimentDraft:
    """Measurement and electrical metadata for a single experiment."""

    measurement_point_label: str | None = None
    measurement_type: str | None = None
    temperature_K: float | None = None
    magnetic_field_T: float | None = None
    excitation_wavelength_nm: float | None = None
    center_wavelength_nm: float | None = None
    excitation_power_uW: float | None = None
    integration_time_s: float | None = None
    averages: int | None = None
    grating_grooves_per_mm: int | None = None
    rotations_deg: list[float] | None = None
    stage_position: int | None = None
    fixed_top_gate_V: float | None = None
    fixed_gate_values: dict[str, float] = field(default_factory=dict)
    active_gate_configuration: str | None = None
    sweep_direction: str | None = None
    bias_start_V: float | None = None
    bias_stop_V: float | None = None
    back_gate_topology: str | None = None
    gate_constraints: list[GateConstraint] = field(default_factory=list)
    electrical_connections: list[ElectricalConnection] = field(
        default_factory=list
    )


@dataclass
class FileDraft:
    """Relative file paths grouped by their role within an experiment."""

    raw_files: list[str] = field(default_factory=list)
    intermediate_files: list[str] = field(default_factory=list)
    processed_files: list[str] = field(default_factory=list)
    figure_files: list[str] = field(default_factory=list)


@dataclass
class ReviewDraft:
    """Review flags and confidence for the archive draft."""

    warnings: list[str] = field(default_factory=list)
    confidence: float = 0.0
    needs_review: bool = False


@dataclass
class ArchiveDraft:
    """Lossless container for every value needed by a future NOMAD mapping."""

    sample: SampleDraft = field(default_factory=SampleDraft)
    experiment: ExperimentDraft = field(default_factory=ExperimentDraft)
    files: FileDraft = field(default_factory=FileDraft)
    provenance: list[MetadataProvenance] = field(default_factory=list)
    lineage: list[LineageEdge] = field(default_factory=list)
    review: ReviewDraft = field(default_factory=ReviewDraft)

    def to_json(self, *, indent: int = 2) -> str:
        """Serialize the draft to indented, deterministic JSON."""

        return json.dumps(asdict(self), indent=indent)


def _copy_gate_constraints(
    constraints: list[GateConstraint],
) -> list[GateConstraint]:
    """Return a deep, value-level copy of parsed gate constraints."""

    return [
        GateConstraint(
            raw_expression=constraint.raw_expression,
            coefficients=dict(constraint.coefficients),
            control_mode=constraint.control_mode,
            sweep_direction=constraint.sweep_direction,
        )
        for constraint in constraints
    ]


def _copy_electrical_connections(
    connections: list[ElectricalConnection],
) -> list[ElectricalConnection]:
    """Return a deep, value-level copy of parsed electrical connections."""

    return [
        ElectricalConnection(
            raw_expression=connection.raw_expression,
            nodes=list(connection.nodes),
            type=connection.type,
            source_role=connection.source_role,
        )
        for connection in connections
    ]


def _copy_provenance(
    provenance: list[MetadataProvenance],
) -> list[MetadataProvenance]:
    """Return a deep, value-level copy of metadata provenance entries."""

    return [
        MetadataProvenance(
            field=item.field,
            value=deepcopy(item.value),
            source_type=item.source_type,
            source=item.source,
            method=item.method,
        )
        for item in provenance
    ]


def _copy_lineage(lineage: list[LineageEdge]) -> list[LineageEdge]:
    """Return a deep, value-level copy of lineage edges."""

    return [
        LineageEdge(
            source=edge.source,
            target=edge.target,
            relation=edge.relation,
        )
        for edge in lineage
    ]


def _resolve_sweep_direction(
    constraints: list[GateConstraint],
) -> str | None:
    """Resolve a single unambiguous constraint sweep direction.

    The direction is copied only when exactly one constraint carries a
    non-null ``sweep_direction``. Zero or multiple directions yield ``None``;
    conflicts are never resolved and ``forward`` is never inferred.
    """

    directions = [
        constraint.sweep_direction
        for constraint in constraints
        if constraint.sweep_direction is not None
    ]
    if len(directions) == 1:
        return directions[0]
    return None


def _build_experiment_draft(
    experiment: ExperimentImportProposal,
) -> ArchiveDraft:
    """Map one :class:`ExperimentImportProposal` into an :class:`ArchiveDraft`."""

    return ArchiveDraft(
        sample=SampleDraft(sample_id=experiment.sample_id),
        experiment=ExperimentDraft(
            measurement_point_label=experiment.measurement_point_label,
            measurement_type=experiment.measurement_type,
            temperature_K=experiment.temperature_K,
            magnetic_field_T=experiment.magnetic_field_T,
            excitation_wavelength_nm=experiment.excitation_wavelength_nm,
            center_wavelength_nm=experiment.center_wavelength_nm,
            excitation_power_uW=experiment.excitation_power_uW,
            integration_time_s=experiment.integration_time_s,
            averages=experiment.averages,
            grating_grooves_per_mm=experiment.grating_grooves_per_mm,
            rotations_deg=(
                list(experiment.rotations_deg)
                if experiment.rotations_deg is not None
                else None
            ),
            stage_position=experiment.stage_position,
            fixed_top_gate_V=experiment.fixed_top_gate_V,
            fixed_gate_values=dict(experiment.fixed_gate_values),
            active_gate_configuration=experiment.active_gate_configuration,
            sweep_direction=_resolve_sweep_direction(
                experiment.gate_constraints
            ),
            bias_start_V=experiment.bias_start_V,
            bias_stop_V=experiment.bias_stop_V,
            back_gate_topology=experiment.back_gate_topology,
            gate_constraints=_copy_gate_constraints(
                experiment.gate_constraints
            ),
            electrical_connections=_copy_electrical_connections(
                experiment.electrical_connections
            ),
        ),
        files=FileDraft(
            raw_files=list(experiment.raw_files),
            intermediate_files=list(experiment.intermediate_files),
            processed_files=list(experiment.processed_files),
            figure_files=list(experiment.figure_files),
        ),
        provenance=_copy_provenance(experiment.metadata_provenance),
        lineage=_copy_lineage(experiment.lineage),
        review=ReviewDraft(
            warnings=list(experiment.warnings),
            confidence=experiment.confidence,
            needs_review=experiment.needs_review,
        ),
    )


def build_archive_draft(
    import_proposal: ImportProposal,
) -> list[ArchiveDraft]:
    """Build one :class:`ArchiveDraft` per experiment in an import proposal.

    Values are copied deterministically without re-parsing filenames, reading
    scientific contents, or touching NOMAD. Nested dataclasses, lists, and
    dicts are deep-copied so the resulting drafts never alias or mutate the
    source proposal.
    """

    return [
        _build_experiment_draft(experiment)
        for experiment in import_proposal.experiments
    ]


def main(argv: list[str] | None = None) -> int:
    """Dry-run command-line entry point for archive drafting.

    ``python -m lab_data.ingestion.archive_builder <path>`` scans the
    directory, builds an import proposal, and prints the resulting archive
    drafts as JSON. Nothing is written to disk and nothing is uploaded.
    """

    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(
            'usage: python -m lab_data.ingestion.archive_builder <path>',
            file=sys.stderr,
        )
        return 2

    root = Path(args[0])
    if not root.exists():
        print(f'error: path does not exist: {args[0]}', file=sys.stderr)
        return 1
    if not root.is_dir():
        print(f'error: not a directory: {args[0]}', file=sys.stderr)
        return 1

    scan_result = scan_directory(root)
    import_proposal = build_import_proposal(scan_result)
    drafts = build_archive_draft(import_proposal)
    print(json.dumps({'drafts': [asdict(draft) for draft in drafts]}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
