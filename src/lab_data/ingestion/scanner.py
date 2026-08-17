"""Deterministic experimental-data folder scanner.

Scans a directory tree for supported experimental data files, classifies each
file by its location (raw / processed / figure), and groups related files into
conservative experiment proposals using normalized filename stems.

Only clear, well-known filename metadata is extracted. No metadata is
fabricated for ambiguous or unrecognised naming.
"""

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

__all__ = [
    'ExperimentMetadata',
    'ExperimentProposal',
    'GateConstraint',
    'ElectricalConnection',
    'SUPPORTED_EXTENSIONS',
    'ScanResult',
    'main',
    'scan_directory',
]

SUPPORTED_EXTENSIONS = frozenset({'.csv', '.dat', '.xlsx', '.xls', '.png'})

_RAW_DIR = 'initial data'
_PROCESSED_DIR = 'processed data'

# Whole-word role tokens removed from stems before grouping so that, for
# example, ``D356_PL_raw.csv`` and ``D356_PL_processed.csv`` share a key.
_ROLE_TOKENS = frozenset(
    {
        'data',
        'dataset',
        'datasets',
        'fig',
        'figure',
        'figures',
        'final',
        'graph',
        'image',
        'img',
        'output',
        'plot',
        'plots',
        'proc',
        'process',
        'processed',
        'raw',
        'result',
        'results',
    }
)

_SAMPLE_RE = re.compile(r'(?<![a-z0-9])(?:d|yz)(\d{2,4})(?![a-z0-9])')
_SAMPLE_ALIASES = {
    'YZ356': 'D356',
}
_TEMPERATURE_RE = re.compile(
    r'(?<![a-z0-9])(\d+(?:\.\d+)?)k(?=(?:pl|ref)?(?![a-z0-9]))'
)
_FIELD_RE = re.compile(r'(?<![a-z0-9])(\d+(?:\.\d+)?)t(?=p\d|[^a-z0-9])')
_WAVELENGTH_RE = re.compile(r'(?<![a-z0-9])(\d+(?:\.\d+)?)nm(?![a-z])')
_PL_RE = re.compile(r'(?:(?<![a-z0-9])|(?<=k))pl(?![a-z0-9])')
_ABSORPTION_RE = re.compile(
    r'(?:(?:(?<![a-z0-9])|(?<=k))ref|(?<![a-z0-9])(?:dr_r|drr|absorb(?:ance|ption)?))'
    r'(?![a-z0-9])'
)
_CENTER_WAVELENGTH_RE = re.compile(
    r'(?<![a-z0-9])(\d+(?:[p.]\d+)?)nmc(?![a-z0-9])'
)
_EXCITATION_POWER_RE = re.compile(r'(\d+(?:[p.]\d+)?)uw(?![a-z])')
_INTEGRATION_RE = re.compile(
    r'(?<![a-z0-9])(\d+(?:[p.]\d+)?)sx(\d+)(?![a-z0-9])'
)
_GRATING_RE = re.compile(r'(?<![a-z0-9])(\d+)g(?![a-z0-9])')
_ROTATION_RE = re.compile(r'(?<![a-z0-9])rot_?(\d+(?:[p.]\d+)?)deg(?![a-z])')
_STAGE_RE = re.compile(r'(?<![a-z0-9])stage(\d+)(?![a-z0-9])')
_MEASUREMENT_POINT_RE = re.compile(
    r'(?:(?<![a-z0-9])|(?<=\dt))p(?:\d+[a-z0-9]*|[a-z]\d+|x)(?![a-z0-9])',
    re.I,
)

# Electrical metadata tokens. These are parsed from the *original* stem
# because normalisation would strip the signed operators and decimal signs
# that carry the meaning of the expression.
_FIX_TG_RE = re.compile(r'^fixtg=([+-]?(?:\d+(?:[.p]\d+)?))$', re.I)
_BIAS_RE = re.compile(
    r'^vb([+-]?(?:\d+(?:[.p]\d+)?))to([+-]?(?:\d+(?:[.p]\d+)?))$',
    re.I,
)
_TERM_RE = re.compile(r'[+-]?(?:\d+(?:[.p]\d+)?)?(?:tg|bg1|bg2|bg|cg)')
_GATE_SUFFIX_RE = re.compile(r'(tg|bg1|bg2|bg|cg)$')


@dataclass
class GateConstraint:
    """A parsed electrical gate constraint (e.g. ``TG+BG=0``)."""

    raw_expression: str
    coefficients: dict[str, float]
    control_mode: str | None = None


@dataclass
class ElectricalConnection:
    """A parsed electrical wiring between gates (e.g. ``BG2-CG``)."""

    raw_expression: str
    nodes: list[str]
    type: str
    source_role: str


@dataclass
class ExperimentMetadata:
    """Clearly extracted metadata for a single experiment proposal."""

    sample_id: str | None = None
    temperature_K: float | None = None
    magnetic_field_T: float | None = None
    excitation_wavelength_nm: float | None = None
    measurement_type: str | None = None
    center_wavelength_nm: float | None = None
    integration_time_s: float | None = None
    averages: int | None = None
    excitation_power_uW: float | None = None
    grating_grooves_per_mm: int | None = None
    rotations_deg: list[float] = field(default_factory=list)
    stage_position: int | None = None
    measurement_point_label: str | None = None
    fixed_top_gate_V: float | None = None
    active_gate_configuration: str | None = None
    bias_start_V: float | None = None
    bias_stop_V: float | None = None
    back_gate_topology: str | None = None
    gate_constraints: list[GateConstraint] = field(default_factory=list)
    electrical_connections: list[ElectricalConnection] = field(
        default_factory=list
    )


@dataclass
class ExperimentProposal:
    """A conservative grouping of related raw, processed, and figure files."""

    metadata: ExperimentMetadata = field(default_factory=ExperimentMetadata)
    raw_files: list[str] = field(default_factory=list)
    processed_files: list[str] = field(default_factory=list)
    figure_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class ScanResult:
    """Result of scanning an experiment directory."""

    sample_id: str | None = None
    scan_root: str | None = None
    experiments: list[ExperimentProposal] = field(default_factory=list)
    unclassified_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_json(self, *, indent: int = 2) -> str:
        """Serialize the result to indented JSON."""

        return json.dumps(asdict(self), indent=indent)


def _normalize_stem(stem: str) -> str:
    """Lower-case a stem and canonicalize separators to underscores."""

    return re.sub(r'[^a-z0-9.]+', '_', stem.lower()).strip('_')


def _normalize_component(name: str) -> str:
    """Lower-case a path component and canonicalize separators to spaces."""

    return re.sub(r'[^a-z0-9]+', ' ', name.lower()).strip()


_DERIVED_SUFFIX_RE = re.compile(r'(?:_(?:pl|linear|log|self|drr|dr_r|avg\d*))+$')


def _group_key(stem: str) -> str:
    """Return the deterministic grouping key for a filename stem.

    Generic role tokens are removed wherever they appear, then recognized
    derived suffix tokens (``pl``, ``linear``, ``log``, ``avg``/``avgN``,
    ``dr_r``/``drr``, and ``self``) are stripped from the end.
    """

    normalized = _normalize_stem(stem)
    core = '_'.join(
        token for token in normalized.split('_') if token not in _ROLE_TOKENS
    )
    core = _DERIVED_SUFFIX_RE.sub('', core)
    return core or normalized


def _extract_sample_id(stem: str) -> str | None:
    """Return the sample identifier, normalizing only explicitly aliased YZ ids."""

    match = _SAMPLE_RE.search(stem)
    if match is None:
        return None
    identifier = match.group(0).upper()
    return _SAMPLE_ALIASES.get(identifier, identifier)


def _extract_float(stem: str, pattern: re.Pattern[str]) -> float | None:
    match = pattern.search(stem)
    if match is None:
        return None
    return float(match.group(1))


def _parse_decimal(text: str) -> float:
    """Parse a numeric token where ``p`` denotes the decimal point."""

    return float(text.replace('p', '.'))


def _extract_decimal(stem: str, pattern: re.Pattern[str]) -> float | None:
    match = pattern.search(stem)
    if match is None:
        return None
    return _parse_decimal(match.group(1))


def _extract_int(stem: str, pattern: re.Pattern[str]) -> int | None:
    match = pattern.search(stem)
    if match is None:
        return None
    return int(match.group(1))


def _extract_measurement_type(stem: str) -> str | None:
    if _PL_RE.search(stem):
        return 'photoluminescence'
    if _ABSORPTION_RE.search(stem):
        return 'absorption'
    return None


def _extract_measurement_point_label(stem: str) -> str | None:
    """Return an explicit ``p``-prefixed measurement-point label.

    A point label is ``p`` followed by a digit run (optionally with an
    alphanumeric suffix), a single letter plus digits, or the letter ``X``
    (optionally followed by digits). The original spelling is preserved
    exactly. The ``p`` must either begin a token or immediately follow the
    magnetic-field ``T`` marker (e.g. ``9Tp1n1``), so decimal notation and
    arbitrary ``p``-words are never classified.
    """

    match = _MEASUREMENT_POINT_RE.search(stem)
    if match is None:
        return None
    return match.group(0)


def _extract_metadata(stem: str) -> ExperimentMetadata:
    normalized = _normalize_stem(stem)
    integration = _INTEGRATION_RE.search(normalized)
    rotations = [
        _parse_decimal(value) for value in _ROTATION_RE.findall(normalized)
    ]
    return ExperimentMetadata(
        sample_id=_extract_sample_id(normalized),
        temperature_K=_extract_float(normalized, _TEMPERATURE_RE),
        magnetic_field_T=_extract_float(normalized, _FIELD_RE),
        excitation_wavelength_nm=_extract_float(normalized, _WAVELENGTH_RE),
        measurement_type=_extract_measurement_type(normalized),
        center_wavelength_nm=_extract_decimal(normalized, _CENTER_WAVELENGTH_RE),
        integration_time_s=(
            _parse_decimal(integration.group(1)) if integration else None
        ),
        averages=int(integration.group(2)) if integration else None,
        excitation_power_uW=_extract_decimal(normalized, _EXCITATION_POWER_RE),
        grating_grooves_per_mm=_extract_int(normalized, _GRATING_RE),
        rotations_deg=rotations,
        stage_position=_extract_int(normalized, _STAGE_RE),
        measurement_point_label=_extract_measurement_point_label(stem),
    )


@dataclass
class _ElectricalExtraction:
    """Intermediate electrical metadata for a single stem."""

    fixed_top_gate_V: float | None = None
    active_gate_configuration: str | None = None
    bias_start_V: float | None = None
    bias_stop_V: float | None = None
    gate_constraints: list[GateConstraint] = field(default_factory=list)
    electrical_connections: list[ElectricalConnection] = field(
        default_factory=list
    )
    gates: set[str] = field(default_factory=set)


def _parse_constraint_terms(expression: str) -> dict[str, float] | None:
    """Parse a ``term+term`` expression into signed gate coefficients.

    Returns ``None`` when the expression contains anything other than a
    sequence of optional-signed, optional-coefficient gate terms (so that
    unsupported operators such as ``*`` or ``/`` are never invented).
    """

    coefficients: dict[str, float] = {}
    position = 0
    for match in _TERM_RE.finditer(expression):
        if match.start() != position:
            return None
        text = match.group(0)
        gate_match = _GATE_SUFFIX_RE.search(text)
        gate = gate_match.group(1).upper()
        coefficient_text = text[: gate_match.start()]
        if coefficient_text in ('', '+'):
            coefficient = 1.0
        elif coefficient_text == '-':
            coefficient = -1.0
        else:
            coefficient = _parse_decimal(coefficient_text)
        coefficients[gate] = coefficients.get(gate, 0.0) + coefficient
        position = match.end()
    if position != len(expression):
        return None
    return coefficients


def _control_mode(coefficients: dict[str, float]) -> str | None:
    """Infer the control mode for a two-gate constant-sweep constraint."""

    if set(coefficients) == {'TG', 'BG'}:
        product = coefficients['TG'] * coefficients['BG']
        if product > 0:
            return 'constant_doping'
        if product < 0:
            return 'constant_displacement_field'
    return None


def _infer_back_gate_topology(gates: set[str]) -> tuple[str | None, str | None]:
    """Infer back-gate topology from the gate variables present."""

    has_split = bool(gates & {'BG1', 'BG2'})
    has_single = 'BG' in gates
    if has_split and has_single:
        return (
            None,
            'both ordinary BG and split BG1/BG2 gates present; '
            'back_gate_topology left unset',
        )
    if has_split:
        return 'split', None
    if has_single:
        return 'single', None
    return None, None


def _extract_electrical(stem: str) -> tuple[_ElectricalExtraction, list[str]]:
    """Extract supported electrical metadata from an original stem."""

    result = _ElectricalExtraction()
    warnings: list[str] = []

    for token in stem.split('_'):
        if not token:
            continue
        lower = token.lower()

        fix_tg = _FIX_TG_RE.match(lower)
        if fix_tg:
            result.fixed_top_gate_V = _parse_decimal(fix_tg.group(1))
            result.gates.add('TG')
            continue

        if lower == 'tgonly':
            result.active_gate_configuration = 'TG_only'
            result.gates.add('TG')
            continue
        if lower == 'bg1only':
            result.active_gate_configuration = 'BG1_only'
            result.gates.add('BG1')
            continue

        bias = _BIAS_RE.match(lower)
        if bias:
            result.bias_start_V = _parse_decimal(bias.group(1))
            result.bias_stop_V = _parse_decimal(bias.group(2))
            continue

        if lower == 'bg2-cg':
            result.electrical_connections.append(
                ElectricalConnection(
                    raw_expression=token,
                    nodes=['BG2', 'CG'],
                    type='electrically_tied',
                    source_role='bias_source',
                )
            )
            result.gates.update(('BG2', 'CG'))
            continue

        if '=' in lower:
            left, right = lower.split('=', 1)
            if right.strip() == '0':
                coefficients = _parse_constraint_terms(left.strip())
                if coefficients is not None and set(coefficients) in (
                    {'TG', 'BG'},
                    {'BG1', 'BG2'},
                ):
                    result.gate_constraints.append(
                        GateConstraint(
                            raw_expression=token,
                            coefficients=coefficients,
                            control_mode=_control_mode(coefficients),
                        )
                    )
                    result.gates.update(coefficients)
                    continue
            warnings.append(f'unsupported electrical expression: {token}')
            continue

    return result, warnings


_METADATA_FIELDS = (
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
    'rotations_deg',
    'stage_position',
    'measurement_point_label',
)


_ELECTRICAL_SCALAR_FIELDS = (
    'fixed_top_gate_V',
    'active_gate_configuration',
    'bias_start_V',
    'bias_stop_V',
    'back_gate_topology',
)


def _merge_single(
    candidates: set, field_name: str, warnings: list[str]
) -> object | None:
    """Merge a scalar field, warning and unsetting on conflict."""

    if len(candidates) == 1:
        return next(iter(candidates))
    if len(candidates) > 1:
        warnings.append(
            f'conflicting {field_name} values: {sorted(candidates)}'
        )
    return None


def _dedup_constraints(items: list[GateConstraint]) -> list[GateConstraint]:
    """Deduplicate semantically equal constraints, keeping first occurrence."""

    seen: set[tuple] = set()
    result: list[GateConstraint] = []
    for constraint in items:
        key = (
            tuple(sorted(constraint.coefficients.items())),
            constraint.control_mode,
        )
        if key not in seen:
            seen.add(key)
            result.append(constraint)
    return result


def _dedup_connections(
    items: list[ElectricalConnection],
) -> list[ElectricalConnection]:
    """Deduplicate semantically equal connections, keeping first occurrence."""

    seen: set[tuple] = set()
    result: list[ElectricalConnection] = []
    for connection in items:
        key = (
            tuple(connection.nodes),
            connection.type,
            connection.source_role,
        )
        if key not in seen:
            seen.add(key)
            result.append(connection)
    return result


def _dedupe_warnings(warnings: list[str]) -> list[str]:
    """Remove duplicate warnings while preserving first-occurrence order."""

    seen: set[str] = set()
    result: list[str] = []
    for warning in warnings:
        if warning not in seen:
            seen.add(warning)
            result.append(warning)
    return result


def _merge_electrical(
    stems: list[str],
) -> tuple[
    dict[str, object | None],
    list[GateConstraint],
    list[ElectricalConnection],
    list[str],
]:
    """Merge electrical metadata across stems into scalar/list results."""

    scalar_seen: dict[str, set] = {
        name: set() for name in _ELECTRICAL_SCALAR_FIELDS
    }
    constraints: list[GateConstraint] = []
    connections: list[ElectricalConnection] = []
    warnings: list[str] = []

    scalar_attributes = (
        ('fixed_top_gate_V', 'fixed_top_gate_V'),
        ('active_gate_configuration', 'active_gate_configuration'),
        ('bias_start_V', 'bias_start_V'),
        ('bias_stop_V', 'bias_stop_V'),
    )

    for stem in stems:
        electrical, electrical_warnings = _extract_electrical(stem)
        warnings.extend(electrical_warnings)
        for attribute, field_name in scalar_attributes:
            value = getattr(electrical, attribute)
            if value is not None:
                scalar_seen[field_name].add(value)
        topology, topology_warning = _infer_back_gate_topology(
            electrical.gates
        )
        if topology is not None:
            scalar_seen['back_gate_topology'].add(topology)
        if topology_warning:
            warnings.append(topology_warning)
        constraints.extend(electrical.gate_constraints)
        connections.extend(electrical.electrical_connections)

    merged: dict[str, object | None] = {}
    for field_name in _ELECTRICAL_SCALAR_FIELDS:
        merged[field_name] = _merge_single(
            scalar_seen[field_name], field_name, warnings
        )

    return (
        merged,
        _dedup_constraints(constraints),
        _dedup_connections(connections),
        warnings,
    )


def _merge_metadata(stems: list[str]) -> tuple[ExperimentMetadata, list[str]]:
    """Merge metadata from original stems into a single proposal metadata.

    A field is kept only when exactly one distinct clear value exists across
    the stems. Conflicting values leave the field unset and record a warning.
    Electrical scalar fields follow the same rule, while constraints and
    connections are deterministically deduplicated rather than conflicting.
    """

    seen: dict[str, set] = {field_name: set() for field_name in _METADATA_FIELDS}
    warnings: list[str] = []

    for stem in stems:
        extracted = _extract_metadata(stem)
        for field_name in _METADATA_FIELDS:
            value = getattr(extracted, field_name)
            if field_name == 'rotations_deg':
                value = tuple(value) if value else None
            if value is not None:
                seen[field_name].add(value)

    merged: dict[str, object | None] = {}
    for field_name in _METADATA_FIELDS:
        candidates = seen[field_name]
        if len(candidates) == 1:
            value = next(iter(candidates))
            merged[field_name] = (
                list(value) if field_name == 'rotations_deg' else value
            )
        elif len(candidates) > 1:
            merged[field_name] = None
            warnings.append(
                f'conflicting {field_name} values: {sorted(candidates)}'
            )
        else:
            merged[field_name] = None

    electrical_merged, constraints, connections, electrical_warnings = (
        _merge_electrical(stems)
    )
    warnings.extend(electrical_warnings)
    warnings = _dedupe_warnings(warnings)

    return (
        ExperimentMetadata(
            sample_id=merged['sample_id'],
            temperature_K=merged['temperature_K'],
            magnetic_field_T=merged['magnetic_field_T'],
            excitation_wavelength_nm=merged['excitation_wavelength_nm'],
            measurement_type=merged['measurement_type'],
            center_wavelength_nm=merged['center_wavelength_nm'],
            integration_time_s=merged['integration_time_s'],
            averages=merged['averages'],
            excitation_power_uW=merged['excitation_power_uW'],
            grating_grooves_per_mm=merged['grating_grooves_per_mm'],
            rotations_deg=merged['rotations_deg'],
            stage_position=merged['stage_position'],
            measurement_point_label=merged['measurement_point_label'],
            fixed_top_gate_V=electrical_merged['fixed_top_gate_V'],
            active_gate_configuration=electrical_merged[
                'active_gate_configuration'
            ],
            bias_start_V=electrical_merged['bias_start_V'],
            bias_stop_V=electrical_merged['bias_stop_V'],
            back_gate_topology=electrical_merged['back_gate_topology'],
            gate_constraints=constraints,
            electrical_connections=connections,
        ),
        warnings,
    )


def _confidence(
    metadata: ExperimentMetadata, raw_count: int, processed_count: int
) -> float:
    """Return a deterministic confidence score in the range ``[0, 1]``."""

    score = 0.0
    if metadata.sample_id:
        score += 0.2
    if metadata.measurement_type:
        score += 0.25
    conditions = (
        metadata.temperature_K,
        metadata.magnetic_field_T,
        metadata.excitation_wavelength_nm,
    )
    score += 0.1 * sum(1 for value in conditions if value is not None)
    if raw_count:
        score += 0.15
    if processed_count:
        score += 0.1
    return round(min(score, 1.0), 2)


def scan_directory(root: str | Path) -> ScanResult:
    """Recursively scan ``root`` and return a structured :class:`ScanResult`."""

    root_path = Path(root)
    if not root_path.exists():
        raise FileNotFoundError(f'path does not exist: {root_path}')
    if not root_path.is_dir():
        raise NotADirectoryError(f'path is not a directory: {root_path}')

    warnings: list[str] = []
    unclassified: list[str] = []
    groups: dict[str, dict[str, list[str]]] = {}
    stems_by_key: dict[str, set[str]] = {}

    files = [path for path in root_path.rglob('*') if path.is_file()]
    for file_path in sorted(files, key=lambda path: path.as_posix()):
        rel_path = file_path.relative_to(root_path)
        relative = rel_path.as_posix()
        extension = file_path.suffix.lower()

        if extension not in SUPPORTED_EXTENSIONS:
            unclassified.append(relative)
            warnings.append(f'unsupported extension {extension or "(none)"!r}: {relative}')
            continue

        parent_dirs = {_normalize_component(part) for part in rel_path.parts[:-1]}
        if _RAW_DIR in parent_dirs:
            category = 'raw'
        elif _PROCESSED_DIR in parent_dirs:
            category = 'figure' if extension == '.png' else 'processed'
        else:
            unclassified.append(relative)
            warnings.append(f'outside recognised data directories: {relative}')
            continue

        key = _group_key(file_path.stem)
        groups.setdefault(key, {'raw': [], 'processed': [], 'figure': []})[
            category
        ].append(relative)
        stems_by_key.setdefault(key, set()).add(file_path.stem)

    experiments: list[ExperimentProposal] = []
    for key in sorted(groups):
        bucket = groups[key]
        raw_files = sorted(bucket['raw'])
        processed_files = sorted(bucket['processed'])
        figure_files = sorted(bucket['figure'])
        metadata, metadata_warnings = _merge_metadata(sorted(stems_by_key[key]))

        proposal_warnings: list[str] = list(metadata_warnings)
        if figure_files and not raw_files and not processed_files:
            proposal_warnings.append(
                'figures found without associated raw or processed data'
            )

        experiments.append(
            ExperimentProposal(
                metadata=metadata,
                raw_files=raw_files,
                processed_files=processed_files,
                figure_files=figure_files,
                warnings=proposal_warnings,
                confidence=_confidence(metadata, len(raw_files), len(processed_files)),
            )
        )

    sample_ids = sorted(
        {exp.metadata.sample_id for exp in experiments if exp.metadata.sample_id}
    )
    if len(sample_ids) == 1:
        sample_id = sample_ids[0]
    else:
        sample_id = None
        if len(sample_ids) > 1:
            warnings.append(
                'multiple sample identifiers detected; scan-level sample_id left unset'
            )

    return ScanResult(
        sample_id=sample_id,
        scan_root=str(root_path),
        experiments=experiments,
        unclassified_files=unclassified,
        warnings=warnings,
    )


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point for ``python -m lab_data.ingestion.scanner``."""

    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print('usage: python -m lab_data.ingestion.scanner <path>', file=sys.stderr)
        return 2

    root = Path(args[0])
    if not root.exists() or not root.is_dir():
        print(f'error: not a directory: {args[0]}', file=sys.stderr)
        return 1

    print(scan_directory(root).to_json())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
