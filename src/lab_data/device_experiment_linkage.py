"""Deterministic device-directory experiment linkage.

Derives one experiment per canonical measurement from an explicit storage
context: an artifact belongs to a device experiment only when its
``device_id`` is set and its storage-relative path starts with that device's
folder alias followed directly by a raw data directory or ``Processed Data``.
Processed DAT files and plotted PNG figures are derived artifacts of the
underlying raw measurement: a processed stem maps onto a raw stem exactly
when it is that raw stem plus a chain of recognized derivative suffixes
(``_PL``, ``_PL_linear``, ``_PL_log``, ``_avg1_DR_R_Self``,
``_avg1_DR_R_External``, ``_DR_R_first_avg1``). A processed stem that cannot
be reduced deterministically to an existing raw stem is then compared, field
by field, against every raw CSV stem in the same device and the same
``Initial Data`` folder using only normalized scientific metadata (sample,
measurement parameters, electrical fields, and the ``_001``-style counter
suffix must be identical); it is linked only when a raw candidate matches on
every compared field. Otherwise it stays its own flagged experiment. No
filename-number mapping, alias inference, fuzzy matching, or generic
underscore stripping is used; the ``YZ356 -> D356`` parser alias is never a
linkage basis.

One case-specific exception exists: :data:`_HUMAN_REVIEWED_RAW_MATCHES` pins
a reviewed raw measurement to one previously unresolved processed experiment.
It is an explicit human adjudication persisted through a ``MetadataClaim``
(``human_review`` source, ``accepted`` review status), not a generic rule: the
raw-only experiment is absorbed into the reviewed experiment and the original
abstention history is preserved in metadata and warnings.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass, replace
from pathlib import Path
from typing import Any

from lab_data.ingestion.scanner import _merge_metadata
from lab_data.scientific_catalog import (
    REVIEW_ACCEPTED,
    REVIEW_UNKNOWN,
    SUBJECT_DEVICE,
    SUBJECT_EXPERIMENT,
    Artifact,
    Device,
    Experiment,
    MetadataClaim,
    Relationship,
    StorageReference,
    deterministic_storage_reference_id,
)

__all__ = [
    'LinkageResult',
    'apply_device_experiment_linkage',
    'build_derived_from_relationships',
    'build_human_reviewed_match_claims',
    'build_measured_on_claims',
    'build_measured_on_relationships',
    'derive_device_experiments',
]

_RAW_DIRECTORIES = frozenset(
    {'Initial Data', 'Initial data', 'Initial data after processing'}
)
_PROCESSED_DIRECTORY = 'Processed Data'
_DATA_EXTENSIONS = frozenset({'csv', 'dat', 'xlsx', 'xls', 'png'})
_MIN_PATH_PARTS = 3
_ROLE_ORDER = ('raw', 'processed', 'figure', 'intermediate')
_ROLE_PRIORITY = {role: index for index, role in enumerate(_ROLE_ORDER)}
_PARSER_VERSION = 'device_directory_context/v2'
_LINKAGE_VERSION_PREFIX = 'device_directory_context/'
_MEASURED_ON_FIELD = 'measured_on_device'
_NORMALIZED_RAW_FOLDER = 'Initial Data'

# Persisted human-reviewed raw matches: processed reduced stem -> raw stem.
# This is a case-specific adjudication (artifacts/d356_0316_human_review_
# packet.md) backed by in-file evidence (Vtg_set/Vtg_meas = 4), not a general
# filename rule; the raw filename omitted the FixTG value the data records.
HUMAN_REVIEWED_RAW_MATCH_FIELD = 'measured_on_raw_match'
_HUMAN_REVIEW_SOURCE_REFERENCE = 'artifacts/d356_0316_human_review_packet.md'
_HUMAN_REVIEWED_RAW_MATCHES: dict[str, str] = {
    'YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG4V-SweepBG1=2_Vb+2to-8':
        'YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG-SweepBG1=2_Vb+2to-8',
}

# Derivative-suffix vocabulary observed in the D356/D345 processed stems.
# Longest first so reduction strips the longest matching chain deterministically.
_DERIVATIVE_SUFFIXES = (
    '_avg1_DR_R_External',
    '_DR_R_first_avg1',
    '_avg1_DR_R_Self',
    '_PL_linear',
    '_PL_log',
    '_PL',
)
_FIGURE_VARIANT_SUFFIXES = {'_PL_linear': 'linear', '_PL_log': 'log'}

# Persisted normalized fields that must be identical between a reduced
# processed stem and a raw candidate for the metadata fallback to link them.
_NORMALIZED_MATCH_FIELDS = (
    'sample_id',
    'measurement_type',
    'measurement_point_label',
    'temperature_K',
    'magnetic_field_T',
    'excitation_wavelength_nm',
    'center_wavelength_nm',
    'integration_time_s',
    'averages',
    'bias_start_V',
    'bias_stop_V',
    'fixed_top_gate_V',
    'active_gate_configuration',
    'fixed_gate_values',
    'stage_position',
    'rotations_deg',
)
_COUNTER_SUFFIX_RE = re.compile(r'_\d+$')


def _jsonable(value: Any) -> Any:
    """Return a JSON-serializable, deterministic representation of ``value``."""

    if isinstance(value, Mapping):
        return {
            str(key): _jsonable(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (set, frozenset)):
        return [_jsonable(item) for item in sorted(value, key=repr)]
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    return value


def _json_dumps(value: Any) -> str:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(',', ':'))


def _folder_aliases(device: Device) -> tuple[str, ...]:
    """Return folder-name aliases; a device with none has no data-dir context."""

    return tuple(alias for alias in device.aliases if alias and '/' not in alias)


def _data_dir_match(artifact: Artifact) -> tuple[str, str, str] | None:
    """Return ``(folder alias, data directory, extension)`` for a data-dir file."""

    reference = artifact.storage_reference
    if reference is None:
        return None
    parts = reference.relative_path.split('/')
    if len(parts) < _MIN_PATH_PARTS:
        return None
    alias, folder = parts[0], parts[1]
    if folder not in _RAW_DIRECTORIES and folder != _PROCESSED_DIRECTORY:
        return None
    extension = (
        artifact.extension
        if artifact.extension
        else Path(reference.relative_path).suffix.lstrip('.').lower()
    ).lower()
    if extension not in _DATA_EXTENSIONS:
        return None
    return alias, folder, extension


def _role_for(folder: str, extension: str) -> str:
    if folder in _RAW_DIRECTORIES or extension == 'csv':
        return 'raw'
    if extension == 'png':
        return 'figure'
    return 'processed'


def _strip_derivative_suffixes(stem: str) -> tuple[str, tuple[str, ...]]:
    """Reduce ``stem`` by stripping recognized derivative suffixes from the end."""

    remaining = stem
    chain: list[str] = []
    while True:
        matched = next(
            (
                suffix
                for suffix in _DERIVATIVE_SUFFIXES
                if remaining.endswith(suffix) and len(remaining) > len(suffix)
            ),
            None,
        )
        if matched is None:
            break
        chain.append(matched)
        remaining = remaining[: -len(matched)]
    return remaining, tuple(chain)


def _counter_suffix(stem: str) -> str | None:
    """Return a trailing ``_001``-style counter suffix, if any."""

    match = _COUNTER_SUFFIX_RE.search(stem)
    return match.group(0) if match else None


def _metadata_profile(stem: str) -> dict[str, object | None]:
    """Return the persisted normalized fields used for metadata matching."""

    metadata, _ = _merge_metadata([stem])
    profile: dict[str, object | None] = {
        field: getattr(metadata, field) for field in _NORMALIZED_MATCH_FIELDS
    }
    profile['electrical_connections'] = tuple(
        sorted(
            (
                tuple(connection.nodes),
                connection.type,
                connection.source_role,
            )
            for connection in metadata.electrical_connections
        )
    )
    profile['counter_suffix'] = _counter_suffix(stem)
    return profile


def _profile_carries_context(profile: Mapping[str, object | None]) -> bool:
    """Return whether any compared field holds a concrete normalized value."""

    for value in profile.values():
        if value is None:
            continue
        if isinstance(value, (dict, tuple, list)) and not value:
            continue
        return True
    return False


def _normalized_metadata_match(
    reduced: str, raw_stems: Sequence[str]
) -> str | None:
    """Return the first raw stem fully compatible with ``reduced``.

    Every deterministic persisted field in ``_NORMALIZED_MATCH_FIELDS`` plus
    the electrical connections and the counter suffix must be identical after
    normalization. ``SweepBG1=2`` stays unparseable on both sides and is
    deliberately not a discriminator. The lexicographically first fully
    compatible raw stem wins, keeping the rule deterministic.
    """

    processed_profile = _metadata_profile(reduced)
    if not _profile_carries_context(processed_profile):
        return None
    for raw_stem in sorted(raw_stems):
        if _metadata_profile(raw_stem) == processed_profile:
            return raw_stem
    return None


def _experiment_from_group(
    device: Device,
    items: Sequence[tuple[Artifact, str, str, str]],
    ordinal: int,
    *,
    unresolved: bool,
) -> Experiment:
    """Build one experiment from every file sharing one canonical measurement."""

    best: dict[tuple[str, str], tuple[str, StorageReference]] = {}
    for artifact, alias, folder, extension in items:
        reference = artifact.storage_reference
        assert reference is not None
        key = (reference.storage_source_id, reference.relative_path)
        role = _role_for(folder, extension)
        current = best.get(key)
        if current is None or _ROLE_PRIORITY[role] > _ROLE_PRIORITY[current[0]]:
            best[key] = (role, reference)

    files_by_role: dict[str, tuple[StorageReference, ...]] = {}
    for role in _ROLE_ORDER:
        references = [
            reference
            for current_role, reference in best.values()
            if current_role == role
        ]
        if references:
            files_by_role[role] = tuple(
                sorted(
                    references,
                    key=lambda reference: (
                        reference.relative_path,
                        reference.storage_source_id,
                    ),
                )
            )

    member_stems = sorted(
        {Path(reference.relative_path).stem for _, reference in best.values()}
    )
    merged, merge_warnings = _merge_metadata(member_stems)
    metadata = asdict(merged)
    metadata['sample_id'] = device.local_device_id or device.device_id
    metadata['device_id'] = device.device_id
    metadata['directory_context'] = items[0][1]

    warnings = list(merge_warnings)
    figure_variants = _figure_variants(files_by_role.get('figure', ()))
    if figure_variants:
        metadata['derived_figure_variants'] = figure_variants
    if unresolved:
        paths = sorted(reference.relative_path for _, reference in best.values())
        metadata['unresolved_processed_files'] = paths
        warnings.append(
            'processed files without a deterministically matching raw '
            f'measurement: {"; ".join(paths)}'
        )

    return Experiment(
        experiment_id=f'{device.local_device_id or device.device_id}-{ordinal:04d}',
        metadata=metadata,
        files_by_role=files_by_role,
        warnings=tuple(warnings),
        confidence=0.0,
        needs_review=unresolved,
        review_state=REVIEW_UNKNOWN,
        parser_version=_PARSER_VERSION,
    )


def _figure_variants(
    figure_references: Sequence[StorageReference],
) -> dict[str, str] | None:
    """Map known display variants (linear/log) to their figure relative paths."""

    variants: dict[str, str] = {}
    for reference in figure_references:
        stem = Path(reference.relative_path).stem
        for suffix, name in _FIGURE_VARIANT_SUFFIXES.items():
            if stem.endswith(suffix):
                variants[name] = reference.relative_path
                break
    return variants if variants else None


def _group_device_files(
    matched: Sequence[tuple[Artifact, str, str, str]],
) -> tuple[
    dict[str, list[tuple[Artifact, str, str, str]]],
    dict[str, list[tuple[Artifact, str, str, str]]],
]:
    """Group one device's files by canonical measurement stem."""

    raw_stems_by_folder: dict[str, set[str]] = {}
    for artifact, _alias, folder, _extension in matched:
        if folder not in _RAW_DIRECTORIES:
            continue
        if (artifact.extension or '').lower() != 'csv':
            continue
        reference = artifact.storage_reference
        assert reference is not None
        raw_stems_by_folder.setdefault(folder, set()).add(
            Path(reference.relative_path).stem
        )
    raw_stems: set[str] = set().union(*raw_stems_by_folder.values())

    grouped: dict[str, list[tuple[Artifact, str, str, str]]] = {}
    unresolved: dict[str, list[tuple[Artifact, str, str, str]]] = {}
    for item in matched:
        artifact, _alias, folder, _extension = item
        reference = artifact.storage_reference
        assert reference is not None
        stem = Path(reference.relative_path).stem
        if folder in _RAW_DIRECTORIES:
            canonical = stem
        else:
            reduced, _chain = _strip_derivative_suffixes(stem)
            if reduced not in raw_stems:
                raw_match = _normalized_metadata_match(
                    reduced,
                    raw_stems_by_folder.get(_NORMALIZED_RAW_FOLDER, ()),
                )
                if raw_match is not None:
                    grouped.setdefault(raw_match, []).append(item)
                    continue
                unresolved.setdefault(stem, []).append(item)
                continue
            canonical = reduced
        grouped.setdefault(canonical, []).append(item)
    return grouped, unresolved


def _experiment_reduced_stems(experiment: Experiment) -> set[str]:
    """Return the derivative-reduced stems of an experiment's derived files."""

    reduced: set[str] = set()
    for role in ('processed', 'figure'):
        for reference in experiment.files_by_role.get(role, ()):
            stem, _chain = _strip_derivative_suffixes(
                Path(reference.relative_path).stem
            )
            reduced.add(stem)
    return reduced


def _merged_human_reviewed(
    processed: Experiment, raw_experiment: Experiment
) -> Experiment:
    """Merge an adjudicated raw experiment into its reviewed experiment."""

    files_by_role = {
        role: tuple(references) for role, references in processed.files_by_role.items()
    }
    raw_references = {
        *files_by_role.get('raw', ()),
        *raw_experiment.files_by_role.get('raw', ()),
    }
    files_by_role['raw'] = tuple(
        sorted(
            raw_references,
            key=lambda reference: (
                reference.relative_path,
                reference.storage_source_id,
            ),
        )
    )
    metadata = dict(processed.metadata)
    if 'unresolved_processed_files' in metadata:
        metadata['resolved_unresolved_history'] = metadata.pop(
            'unresolved_processed_files'
        )
    return replace(
        processed,
        files_by_role=files_by_role,
        metadata=metadata,
        needs_review=False,
        review_state=REVIEW_ACCEPTED,
    )


def _apply_human_reviewed_matches(
    experiments: Sequence[Experiment],
) -> tuple[Experiment, ...]:
    """Absorb each reviewed raw experiment into its processed experiment.

    The reviewed experiment keeps its identity and ordinal, so every other
    experiment ID (including remaining unresolved ones) is untouched; only the
    absorbed raw-only experiment disappears.
    """

    result = list(experiments)
    for processed_reduced, raw_stem in _HUMAN_REVIEWED_RAW_MATCHES.items():
        processed_index = next(
            (
                index
                for index, experiment in enumerate(result)
                if processed_reduced in _experiment_reduced_stems(experiment)
            ),
            None,
        )
        raw_index = next(
            (
                index
                for index, experiment in enumerate(result)
                if any(
                    Path(reference.relative_path).stem == raw_stem
                    for reference in experiment.files_by_role.get('raw', ())
                )
            ),
            None,
        )
        if processed_index is None:
            continue
        if raw_index is None or raw_index == processed_index:
            # The reviewed raw file is absent (the same reduced stem can also
            # occur with a deterministically resolved raw), so there is no
            # adjudicated merge to apply.
            continue
        merged = _merged_human_reviewed(
            result[processed_index], result[raw_index]
        )
        result = [
            (merged if index == processed_index else experiment)
            for index, experiment in enumerate(result)
            if index != raw_index
        ]
    return tuple(result)


def derive_device_experiments(
    devices: Sequence[Device],
    artifacts: Sequence[Artifact],
) -> tuple[Experiment, ...]:
    """Derive deterministic experiments from explicit device data directories."""

    experiments: list[Experiment] = []
    for device in sorted(devices, key=lambda item: item.device_id):
        aliases = set(_folder_aliases(device))
        if not aliases:
            continue
        matched: list[tuple[Artifact, str, str, str]] = []
        for artifact in artifacts:
            if artifact.device_id != device.device_id:
                continue
            match = _data_dir_match(artifact)
            if match is None or match[0] not in aliases:
                continue
            matched.append((artifact, match[0], match[1], match[2]))
        if not matched:
            continue
        matched.sort(
            key=lambda item: (
                item[0].storage_reference.relative_path,
                item[0].artifact_id,
            )
        )
        grouped, unresolved = _group_device_files(matched)

        ordered = [
            *((stem, grouped[stem], False) for stem in sorted(grouped)),
            *((stem, unresolved[stem], True) for stem in sorted(unresolved)),
        ]
        for ordinal, (stem, items, is_unresolved) in enumerate(ordered):
            experiments.append(
                _experiment_from_group(
                    device, items, ordinal, unresolved=is_unresolved
                )
            )
    return _apply_human_reviewed_matches(experiments)


def build_measured_on_relationships(
    experiments: Sequence[Experiment],
) -> tuple[Relationship, ...]:
    """Build one ``measured_on`` device relationship per derived experiment."""

    relationships: list[Relationship] = []
    for experiment in experiments:
        metadata = experiment.metadata
        relationships.append(
            Relationship(
                source_type=SUBJECT_EXPERIMENT,
                source_id=experiment.experiment_id,
                predicate='measured_on',
                target_type=SUBJECT_DEVICE,
                target_id=metadata['device_id'],
                provenance_source=metadata['directory_context'],
                review_state=REVIEW_UNKNOWN,
            )
        )
    return tuple(relationships)


def build_measured_on_claims(
    experiments: Sequence[Experiment],
) -> tuple[MetadataClaim, ...]:
    """Build one storage-directory linkage claim per derived experiment."""

    claims: list[MetadataClaim] = []
    for experiment in experiments:
        metadata = experiment.metadata
        claims.append(
            MetadataClaim(
                subject_type=SUBJECT_EXPERIMENT,
                subject_id=experiment.experiment_id,
                field=_MEASURED_ON_FIELD,
                value={
                    'device_id': metadata['device_id'],
                    'directory_context': metadata['directory_context'],
                },
                source_type='storage_directory',
                source_reference=metadata['directory_context'],
                extraction_method='device_directory_context',
                confidence=None,
                category='device_linkage',
                evidence=(),
                review_status=REVIEW_UNKNOWN,
            )
        )
    return tuple(claims)


def build_human_reviewed_match_claims(
    experiments: Sequence[Experiment],
) -> tuple[MetadataClaim, ...]:
    """Build persisted claims for case-specific human-reviewed raw matches."""

    claims: list[MetadataClaim] = []
    for _processed_reduced, raw_stem in _HUMAN_REVIEWED_RAW_MATCHES.items():
        matches = tuple(
            (experiment, reference)
            for experiment in experiments
            for reference in experiment.files_by_role.get('raw', ())
            if Path(reference.relative_path).stem == raw_stem
        )
        if not matches:
            continue
        experiment, reference = sorted(
            matches,
            key=lambda item: (
                item[1].relative_path,
                item[1].storage_source_id,
            ),
        )[0]
        claims.append(
            MetadataClaim(
                subject_type=SUBJECT_EXPERIMENT,
                subject_id=experiment.experiment_id,
                field=HUMAN_REVIEWED_RAW_MATCH_FIELD,
                value={
                    'raw_relative_path': reference.relative_path,
                    'device_id': experiment.metadata['device_id'],
                    'experiment_id': experiment.experiment_id,
                },
                source_type='human_review',
                source_reference=_HUMAN_REVIEW_SOURCE_REFERENCE,
                extraction_method='human_reviewed_match',
                confidence=None,
                category='device_linkage',
                evidence=(
                    'Vtg_set=4',
                    'Vtg_meas=4',
                    'raw filename omits FixTG value',
                    _HUMAN_REVIEW_SOURCE_REFERENCE,
                ),
                review_status=REVIEW_ACCEPTED,
            )
        )
    return tuple(claims)


def _file_id(reference: StorageReference) -> str:
    return deterministic_storage_reference_id(
        storage_source_id=reference.storage_source_id,
        relative_path=reference.relative_path,
    )


def _file_edge(source: StorageReference, target: StorageReference) -> Relationship:
    """Return a deterministic ``derived_from`` edge between two file identities.

    Source is the upstream file and target is the downstream derivative, which
    matches the canonical orientation used by the proposal lineage (raw ->
    processed/figure).
    """

    return Relationship(
        source_type='file',
        source_id=_file_id(source),
        predicate='derived_from',
        target_type='file',
        target_id=_file_id(target),
        review_state=REVIEW_UNKNOWN,
    )


def build_derived_from_relationships(
    experiments: Sequence[Experiment],
) -> tuple[Relationship, ...]:
    """Build deterministic file-to-file ``derived_from`` edges per experiment."""

    edges: dict[tuple[str, str], Relationship] = {}
    for experiment in experiments:
        raw_refs = experiment.files_by_role.get('raw', ())
        if not raw_refs:
            continue
        processed_refs = experiment.files_by_role.get('processed', ())
        processed_by_stem = {
            Path(reference.relative_path).stem: reference
            for reference in processed_refs
        }
        for raw in raw_refs:
            for dat in processed_refs:
                edge = _file_edge(raw, dat)
                edges[(edge.source_id, edge.target_id)] = edge
        for figure in experiment.files_by_role.get('figure', ()):
            stem = Path(figure.relative_path).stem
            parent = processed_by_stem.get(stem)
            if parent is None:
                if stem.endswith('_PL_linear'):
                    parent = processed_by_stem.get(stem[: -len('_linear')])
                elif stem.endswith('_PL_log'):
                    parent = processed_by_stem.get(stem[: -len('_log')])
            if parent is not None:
                edge = _file_edge(parent, figure)
                edges[(edge.source_id, edge.target_id)] = edge
            else:
                for raw in raw_refs:
                    edge = _file_edge(raw, figure)
                    edges[(edge.source_id, edge.target_id)] = edge
    return tuple(edges.values())


@dataclass(frozen=True)
class LinkageResult:
    """Counts of rows newly inserted by one linkage apply."""

    experiments: int = 0
    experiment_files: int = 0
    claims: int = 0
    relationships: int = 0
    derived_from: int = 0


def _max_integer(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    where: Sequence[tuple[str, str]] = (),
) -> int:
    clause = ''
    params: list[str] = []
    if where:
        clause = ' WHERE ' + ' AND '.join(f'{name} = ?' for name, _ in where)
        params = [value for _, value in where]
    row = connection.execute(
        f'SELECT MAX({column}) FROM {table}{clause}', params
    ).fetchone()
    value = row[0]
    return 0 if value is None else int(value)


def _clear_derived_rows(
    connection: sqlite3.Connection, derived_ids: Sequence[str]
) -> None:
    """Delete every previously derived experiment and its provenance rows."""

    if not derived_ids:
        return
    placeholders = ','.join('?' * len(derived_ids))
    params = list(derived_ids)

    derived_file_ids: set[str] = set()
    for experiment_id in derived_ids:
        for storage_source_id, relative_path in connection.execute(
            """
            SELECT storage_source_id, relative_path FROM experiment_files
            WHERE experiment_id = ?
            """,
            (experiment_id,),
        ):
            derived_file_ids.add(
                deterministic_storage_reference_id(
                    storage_source_id=storage_source_id,
                    relative_path=relative_path,
                )
            )
    if derived_file_ids:
        file_placeholders = ','.join('?' * len(derived_file_ids))
        file_params = list(derived_file_ids)
        connection.execute(
            f"""
            DELETE FROM relationships
            WHERE predicate = 'derived_from' AND source_type = 'file'
            AND target_type = 'file'
            AND (source_id IN ({file_placeholders})
                 OR target_id IN ({file_placeholders}))
            """,
            [*file_params, *file_params],
        )

    connection.execute(
        f"""
        DELETE FROM metadata_claims
        WHERE subject_type = 'experiment' AND subject_id IN ({placeholders})
        """,
        params,
    )
    connection.execute(
        f"""
        DELETE FROM experiment_files
        WHERE experiment_id IN ({placeholders})
        """,
        params,
    )
    connection.execute(
        f"""
        DELETE FROM relationships
        WHERE predicate = 'measured_on' AND source_id IN ({placeholders})
        """,
        params,
    )
    connection.execute(
        "DELETE FROM experiments WHERE parser_version LIKE ?",
        (f'{_LINKAGE_VERSION_PREFIX}%',),
    )


def apply_device_experiment_linkage(
    connection: sqlite3.Connection,
    experiments: Sequence[Experiment],
    relationships: Sequence[Relationship],
    claims: Sequence[MetadataClaim],
) -> LinkageResult:
    """Reset and reinsert derived linkage rows inside one transaction."""

    if not isinstance(connection, sqlite3.Connection):
        raise TypeError('connection must be a sqlite3.Connection')
    connection.execute('BEGIN IMMEDIATE')
    result = LinkageResult()
    try:
        derived_ids = [
            row[0]
            for row in connection.execute(
                """
                SELECT experiment_id FROM experiments
                WHERE parser_version LIKE ?
                """,
                (f'{_LINKAGE_VERSION_PREFIX}%',),
            )
        ]
        _clear_derived_rows(connection, derived_ids)

        experiment_ordinal = _max_integer(connection, 'experiments', 'ordinal') + 1
        for experiment in experiments:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO experiments (
                    experiment_id, metadata_json, warnings_json, confidence,
                    needs_review, review_state, parser_version, roles_json,
                    ordinal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment.experiment_id,
                    _json_dumps(experiment.metadata),
                    _json_dumps(experiment.warnings),
                    experiment.confidence,
                    int(experiment.needs_review),
                    experiment.review_state,
                    experiment.parser_version,
                    _json_dumps(tuple(experiment.files_by_role)),
                    experiment_ordinal,
                ),
            )
            result = replace(result, experiments=result.experiments + cursor.rowcount)
            experiment_ordinal += 1

        for experiment in experiments:
            file_ordinal = 1
            for role in _ROLE_ORDER:
                for reference in experiment.files_by_role.get(role, ()):
                    cursor = connection.execute(
                        """
                        INSERT OR IGNORE INTO experiment_files (
                            experiment_id, ordinal, role, storage_source_id,
                            relative_path
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            experiment.experiment_id,
                            file_ordinal,
                            role,
                            reference.storage_source_id,
                            reference.relative_path,
                        ),
                    )
                    result = replace(
                        result,
                        experiment_files=result.experiment_files + cursor.rowcount,
                    )
                    file_ordinal += 1

        for claim in claims:
            claim_ordinal = (
                _max_integer(
                    connection,
                    'metadata_claims',
                    'ordinal',
                    where=(
                        ('subject_type', claim.subject_type),
                        ('subject_id', claim.subject_id),
                    ),
                )
                + 1
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO metadata_claims (
                    subject_type, subject_id, ordinal, field, value_json,
                    source_type, source_reference, extraction_method,
                    confidence, category, evidence_json, review_status,
                    reviewed_value_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim.subject_type,
                    claim.subject_id,
                    claim_ordinal,
                    claim.field,
                    _json_dumps(claim.value),
                    claim.source_type,
                    claim.source_reference,
                    claim.extraction_method,
                    claim.confidence,
                    claim.category,
                    _json_dumps(claim.evidence),
                    claim.review_status,
                    None,
                ),
            )
            result = replace(result, claims=result.claims + 1)

        relationship_ordinal = (
            _max_integer(connection, 'relationships', 'ordinal') + 1
        )
        for relationship in relationships:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO relationships (
                    relationship_id, source_type, source_id, predicate,
                    target_type, target_id, provenance_source, review_state,
                    ordinal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    relationship.relationship_id,
                    relationship.source_type,
                    relationship.source_id,
                    relationship.predicate,
                    relationship.target_type,
                    relationship.target_id,
                    relationship.provenance_source,
                    relationship.review_state,
                    relationship_ordinal,
                ),
            )
            inserted = cursor.rowcount
            result = replace(
                result,
                relationships=result.relationships + inserted,
            )
            if relationship.predicate == 'derived_from':
                result = replace(
                    result, derived_from=result.derived_from + inserted
                )
            relationship_ordinal += 1
    except BaseException:
        connection.rollback()
        raise
    connection.commit()
    return result
