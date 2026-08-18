"""Intermediate import proposal built from scanner output.

This module turns the conservative, file-oriented
:class:`~lab_data.ingestion.scanner.ScanResult` produced by
:mod:`lab_data.ingestion.scanner` into a flat, JSON-serializable import
proposal. It performs no re-parsing: values are copied deterministically from
the scanner result, relative file paths are preserved, and scanner warnings
and unclassified files are propagated unchanged.

On top of the copied scanner values it records deterministic provenance for
every populated metadata field, builds explicit lineage edges between the
known filename families, and captures relationships that cannot be safely
established. ``needs_review`` is set true whenever scanner warnings, unresolved
metadata, or unresolved relationships exist.
"""

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from lab_data.ingestion.scanner import (
    ElectricalConnection,
    ExperimentProposal,
    GateConstraint,
    ScanResult,
    scan_directory,
)

__all__ = [
    'ExperimentImportProposal',
    'ImportProposal',
    'LineageEdge',
    'MetadataProvenance',
    'build_import_proposal',
    'main',
]


@dataclass
class MetadataProvenance:
    """Deterministic provenance for a single metadata value."""

    field: str
    value: object
    source_type: str
    source: str | None
    method: str


@dataclass
class LineageEdge:
    """A directed relationship between two files in an experiment."""

    source: str
    target: str
    relation: str


@dataclass
class ExperimentImportProposal:
    """Flat import proposal for a single experiment from scanner output."""

    measurement_point_label: str | None = None
    sample_id: str | None = None
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
    active_gate_configuration: str | None = None
    bias_start_V: float | None = None
    bias_stop_V: float | None = None
    back_gate_topology: str | None = None
    fixed_gate_values: dict[str, float] = field(default_factory=dict)
    gate_constraints: list[GateConstraint] = field(default_factory=list)
    electrical_connections: list[ElectricalConnection] = field(
        default_factory=list
    )
    raw_files: list[str] = field(default_factory=list)
    processed_files: list[str] = field(default_factory=list)
    figure_files: list[str] = field(default_factory=list)
    intermediate_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confidence: float = 0.0

    lineage: list[LineageEdge] = field(default_factory=list)
    metadata_provenance: list[MetadataProvenance] = field(default_factory=list)
    unresolved_metadata: list = field(default_factory=list)
    unresolved_relationships: list[dict] = field(default_factory=list)
    needs_review: bool = False


@dataclass
class ImportProposal:
    """Top-level import proposal derived from a :class:`ScanResult`."""

    scan_root: str | None = None
    sample_id: str | None = None
    experiments: list[ExperimentImportProposal] = field(default_factory=list)
    unresolved_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_json(self, *, indent: int = 2) -> str:
        """Serialize the proposal to indented, deterministic JSON."""

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


_AVG_SUFFIX_RE = re.compile(r'_avg\d+_DR_R_Self$')

_SCALAR_METADATA_FIELDS = (
    'sample_id',
    'temperature_K',
    'magnetic_field_T',
    'excitation_wavelength_nm',
    'measurement_type',
    'center_wavelength_nm',
    'integration_time_s',
    'averages',
    'excitation_power_uW',
    'grating_grooves_per_mm',
    'stage_position',
    'measurement_point_label',
    'fixed_top_gate_V',
    'active_gate_configuration',
    'bias_start_V',
    'bias_stop_V',
    'back_gate_topology',
)


def _stem(relative_path: str) -> str:
    """Return the filename stem for a relative scanner path."""

    return Path(relative_path).stem


def _raw_to_processed_rule(raw_stem: str, processed_stem: str) -> str | None:
    """Return the known derivation rule linking a raw stem to a processed stem."""

    if processed_stem == raw_stem:
        return 'same'
    if processed_stem == raw_stem + '_PL':
        return 'pl'
    if processed_stem.startswith(raw_stem + '_avg'):
        suffix = processed_stem[len(raw_stem):]
        if _AVG_SUFFIX_RE.match(suffix):
            return 'avg'
    return None


def _processed_to_figure_rule(
    processed_stem: str, figure_stem: str
) -> str | None:
    """Return the known derivation rule linking a processed stem to a figure stem."""

    if figure_stem == processed_stem:
        return 'same'
    if figure_stem == processed_stem + '_linear':
        return 'linear'
    if figure_stem == processed_stem + '_log':
        return 'log'
    return None


def _group_by_stem(files: list[str]) -> dict[str, list[str]]:
    """Group relative file paths by their filename stem."""

    grouped: dict[str, list[str]] = {}
    for file_path in files:
        grouped.setdefault(_stem(file_path), []).append(file_path)
    return grouped


def _unresolved_entry(
    source_role: str,
    source: str,
    target_role: str,
    reason: str,
    candidates: list[str] | None = None,
) -> dict:
    """Build a JSON-serializable unresolved-relationship record."""

    entry: dict = {
        'source_role': source_role,
        'source': source,
        'target_role': target_role,
        'reason': reason,
    }
    if candidates is not None:
        entry['candidates'] = candidates
    return entry


def _build_lineage(
    proposal: ExperimentProposal,
    has_processed_files: bool,
) -> tuple[list[LineageEdge], list[dict]]:
    """Build explicit lineage edges from the known filename families only."""

    raw_files = sorted(proposal.raw_files)
    processed_files = sorted(proposal.processed_files)
    figure_files = sorted(proposal.figure_files)

    processed_by_stem = _group_by_stem(processed_files)
    figure_by_stem = _group_by_stem(figure_files)

    edges: list[LineageEdge] = []
    unresolved: list[dict] = []

    for raw_file in raw_files:
        raw_stem = _stem(raw_file)
        matched_stems = sorted(
            stem
            for stem in processed_by_stem
            if _raw_to_processed_rule(raw_stem, stem) is not None
        )
        if not matched_stems:
            if has_processed_files:
                unresolved.append(
                    _unresolved_entry(
                        'raw',
                        raw_file,
                        'processed',
                        'no processed file with a known derivation',
                    )
                )
            continue
        for processed_stem in matched_stems:
            candidates = processed_by_stem[processed_stem]
            if len(candidates) == 1:
                edges.append(
                    LineageEdge(raw_file, candidates[0], 'derived_from')
                )
            else:
                unresolved.append(
                    _unresolved_entry(
                        'raw',
                        raw_file,
                        'processed',
                        'ambiguous processed stem',
                        candidates,
                    )
                )

    for processed_file in processed_files:
        processed_stem = _stem(processed_file)
        matched_stems = sorted(
            stem
            for stem in figure_by_stem
            if _processed_to_figure_rule(processed_stem, stem) is not None
        )
        if not matched_stems:
            unresolved.append(
                _unresolved_entry(
                    'processed',
                    processed_file,
                    'figure',
                    'no figure file with a known derivation',
                )
            )
            continue
        for figure_stem in matched_stems:
            candidates = figure_by_stem[figure_stem]
            if len(candidates) == 1:
                edges.append(
                    LineageEdge(processed_file, candidates[0], 'visualization_of')
                )
            else:
                unresolved.append(
                    _unresolved_entry(
                        'processed',
                        processed_file,
                        'figure',
                        'ambiguous figure stem',
                        candidates,
                    )
                )

    return edges, unresolved


def _provenance_source(proposal: ExperimentProposal) -> str | None:
    """Return a deterministic source file for metadata provenance."""

    for files in (
        proposal.raw_files,
        proposal.processed_files,
        proposal.figure_files,
    ):
        if files:
            return sorted(files)[0]
    return None


def _build_provenance(
    proposal: ExperimentProposal,
) -> list[MetadataProvenance]:
    """Record provenance for every populated metadata field."""

    metadata = proposal.metadata
    source = _provenance_source(proposal)
    provenance: list[MetadataProvenance] = []

    def add(field_name: str, value: object) -> None:
        provenance.append(
            MetadataProvenance(
                field=field_name,
                value=value,
                source_type='filename',
                source=source,
                method='deterministic',
            )
        )

    for field_name in _SCALAR_METADATA_FIELDS:
        value = getattr(metadata, field_name)
        if value is not None:
            add(field_name, value)

    if metadata.rotations_deg:
        add('rotations_deg', list(metadata.rotations_deg))
    if metadata.fixed_gate_values:
        add('fixed_gate_values', dict(metadata.fixed_gate_values))
    if metadata.gate_constraints:
        add(
            'gate_constraints',
            _copy_gate_constraints(metadata.gate_constraints),
        )
    if metadata.electrical_connections:
        add(
            'electrical_connections',
            _copy_electrical_connections(metadata.electrical_connections),
        )

    return provenance


def _build_experiment(
    proposal: ExperimentProposal,
) -> ExperimentImportProposal:
    """Copy one scanner proposal into a flat import proposal."""

    metadata = proposal.metadata
    lineage, unresolved_relationships = _build_lineage(
        proposal, bool(proposal.processed_files)
    )
    unresolved_metadata: list = []
    needs_review = (
        bool(proposal.warnings)
        or bool(unresolved_metadata)
        or bool(unresolved_relationships)
    )
    return ExperimentImportProposal(
        measurement_point_label=metadata.measurement_point_label,
        sample_id=metadata.sample_id,
        measurement_type=metadata.measurement_type,
        temperature_K=metadata.temperature_K,
        magnetic_field_T=metadata.magnetic_field_T,
        excitation_wavelength_nm=metadata.excitation_wavelength_nm,
        center_wavelength_nm=metadata.center_wavelength_nm,
        excitation_power_uW=metadata.excitation_power_uW,
        integration_time_s=metadata.integration_time_s,
        averages=metadata.averages,
        grating_grooves_per_mm=metadata.grating_grooves_per_mm,
        rotations_deg=(
            list(metadata.rotations_deg)
            if metadata.rotations_deg is not None
            else None
        ),
        stage_position=metadata.stage_position,
        fixed_top_gate_V=metadata.fixed_top_gate_V,
        active_gate_configuration=metadata.active_gate_configuration,
        bias_start_V=metadata.bias_start_V,
        bias_stop_V=metadata.bias_stop_V,
        back_gate_topology=metadata.back_gate_topology,
        fixed_gate_values=dict(metadata.fixed_gate_values),
        gate_constraints=_copy_gate_constraints(metadata.gate_constraints),
        electrical_connections=_copy_electrical_connections(
            metadata.electrical_connections
        ),
        raw_files=list(proposal.raw_files),
        processed_files=list(proposal.processed_files),
        figure_files=list(proposal.figure_files),
        intermediate_files=list(proposal.intermediate_files),
        warnings=list(proposal.warnings),
        confidence=proposal.confidence,
        lineage=lineage,
        metadata_provenance=_build_provenance(proposal),
        unresolved_metadata=unresolved_metadata,
        unresolved_relationships=unresolved_relationships,
        needs_review=needs_review,
    )


def build_import_proposal(scan_result: ScanResult) -> ImportProposal:
    """Build an :class:`ImportProposal` from scanner output.

    Values are copied deterministically without re-parsing filenames. Relative
    file paths are preserved, scanner ``unclassified_files`` become
    ``unresolved_files``, and scan-level warnings are propagated as-is.
    """

    return ImportProposal(
        scan_root=scan_result.scan_root,
        sample_id=scan_result.sample_id,
        experiments=[
            _build_experiment(experiment) for experiment in scan_result.experiments
        ],
        unresolved_files=list(scan_result.unclassified_files),
        warnings=list(scan_result.warnings),
    )


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point for ``python -m lab_data.ingestion.proposal``."""

    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(
            'usage: python -m lab_data.ingestion.proposal <path>',
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

    proposal = build_import_proposal(scan_directory(root))
    print(proposal.to_json())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
