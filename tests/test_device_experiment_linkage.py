"""Focused tests for deterministic device-directory experiment linkage."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from nomad.config import config

from lab_data.device_experiment_linkage import (
    LinkageResult,
    apply_device_experiment_linkage,
    build_derived_from_relationships,
    build_human_reviewed_match_claims,
    build_measured_on_claims,
    build_measured_on_relationships,
    derive_device_experiments,
)
from lab_data.scientific_catalog import (
    SUBJECT_DEVICE,
    SUBJECT_EXPERIMENT,
    Artifact,
    CatalogSnapshot,
    Device,
    Experiment,
    SQLiteCatalogStore,
    StorageReference,
    deterministic_relationship_id,
    deterministic_storage_reference_id,
)

config.load_plugins()

from lab_data.apis.api import create_app  # noqa: E402

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / 'scripts'
    / 'link_device_experiments.py'
)
_spec = importlib.util.spec_from_file_location('link_device_experiments', _SCRIPT)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f'cannot load script: {_SCRIPT}')
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
read_catalog_objects = _module.read_catalog_objects

ALIAS = 'D356 WSe2_AuSplitGate'
D345_ALIAS = 'D345 WSe2 BL WS2 ML WSe2 sense'
_SOURCE = 'dropbox_device_docs'
FIXED_TOP_GATE_V_4 = 4.0
FIXED_TOP_GATE_V_NEG_4 = -4.0
FIXED_TOP_GATE_V_NEG_6 = -6.0


def _artifact(artifact_id: str, device_id: str | None, relative_path: str, extension: str):
    return Artifact(
        artifact_id,
        extension=extension,
        media_type='UNKNOWN',
        device_id=device_id,
        storage_reference=StorageReference(_SOURCE, relative_path),
    )


def _fixture() -> tuple[tuple[Device, ...], tuple[Artifact, ...]]:
    devices = (
        Device(
            'D356',
            maker_namespace='YZ',
            local_device_id='D356',
            aliases=(ALIAS,),
        ),
        Device(
            'D345',
            maker_namespace='YZ',
            local_device_id='D345',
            aliases=(D345_ALIAS,),
        ),
        Device(
            'D357',
            maker_namespace='YZ',
            local_device_id='D357',
            aliases=('D357 WSe2',),
        ),
        Device('QC148', aliases=('QC148', 'Photocurrent sample')),
    )
    artifacts = (
        # Raw measurements under ``Initial Data``.
        _artifact('a-other', 'D356', f'{ALIAS}/Initial Data/other.csv', 'csv'),
        _artifact('a-trace-raw', 'D356', f'{ALIAS}/Initial Data/trace.csv', 'csv'),
        # PL family: processed DAT plus linear/log display figures.
        _artifact('a-trace-pl', 'D356', f'{ALIAS}/Processed Data/trace_PL.dat', 'dat'),
        _artifact(
            'a-trace-pl-linear',
            'D356',
            f'{ALIAS}/Processed Data/trace_PL_linear.png',
            'png',
        ),
        _artifact(
            'a-trace-pl-log', 'D356', f'{ALIAS}/Processed Data/trace_PL_log.png', 'png'
        ),
        # Analysis outputs: dat + figure pairs.
        _artifact(
            'a-trace-self-dat',
            'D356',
            f'{ALIAS}/Processed Data/trace_avg1_DR_R_Self.dat',
            'dat',
        ),
        _artifact(
            'a-trace-self-png',
            'D356',
            f'{ALIAS}/Processed Data/trace_avg1_DR_R_Self.png',
            'png',
        ),
        _artifact(
            'a-trace-ext-dat',
            'D356',
            f'{ALIAS}/Processed Data/trace_avg1_DR_R_External.dat',
            'dat',
        ),
        _artifact(
            'a-trace-ext-png',
            'D356',
            f'{ALIAS}/Processed Data/trace_avg1_DR_R_External.png',
            'png',
        ),
        # ``_001`` is part of the raw measurement identity, not a suffix.
        _artifact('a-amb', 'D356', f'{ALIAS}/Initial Data/amb.csv', 'csv'),
        _artifact('a-amb-001', 'D356', f'{ALIAS}/Initial Data/amb_001.csv', 'csv'),
        _artifact('a-amb-001-pl', 'D356', f'{ALIAS}/Processed Data/amb_001_PL.dat', 'dat'),
        # Exact duplicate of a raw measurement placed under Processed Data.
        _artifact('a-other-copy', 'D356', f'{ALIAS}/Processed Data/other.csv', 'csv'),
        # Processed file with no deterministically matching raw measurement.
        _artifact('a-standalone', 'D356', f'{ALIAS}/Processed Data/standalone.dat', 'dat'),
        # Nested ``D356/`` subtree and root documents are not data directories.
        _artifact('a-nested-raw', 'D356', f'{ALIAS}/D356/Initial Data/trace.csv', 'csv'),
        _artifact(
            'a-nested-dat', 'D356', f'{ALIAS}/D356/Processed Data/trace_PL.dat', 'dat'
        ),
        _artifact('a-notes', 'D356', f'{ALIAS}/notes.pptx', 'pptx'),
        _artifact(
            'a-incidents',
            'D356',
            f'{ALIAS}/Initial Data/hardware_incidents.jsonl',
            'jsonl',
        ),
        # D345: lowercase raw folders with exact duplicate raw copies.
        _artifact('a-d345-raw-a', 'D345', f'{D345_ALIAS}/Initial data/run1.csv', 'csv'),
        _artifact(
            'a-d345-raw-b',
            'D345',
            f'{D345_ALIAS}/Initial data after processing/run1.csv',
            'csv',
        ),
        _artifact(
            'a-d345-dat',
            'D345',
            f'{D345_ALIAS}/Processed Data/run1_avg1_DR_R_Self.dat',
            'dat',
        ),
        _artifact(
            'a-d345-png',
            'D345',
            f'{D345_ALIAS}/Processed Data/run1_avg1_DR_R_Self.png',
            'png',
        ),
        # D357 has a device_id but no data-directory path.
        _artifact('a-d357-doc', 'D357', 'D357 WSe2/notes.docx', 'docx'),
        # D302/D327 collision artifacts carry no device_id.
        _artifact('a-d302', None, 'D302 WSe2/Initial Data/x.csv', 'csv'),
        _artifact('a-d327', None, 'D327 BL/Initial Data/y.csv', 'csv'),
        # QC device documents only.
        _artifact('a-qc', 'QC148', 'Photocurrent sample/QC148-summary.pptx', 'pptx'),
    )
    return devices, artifacts


def _derived() -> tuple[tuple[Experiment, ...], tuple[Device, ...], tuple[Artifact, ...]]:
    devices, artifacts = _fixture()
    experiments = derive_device_experiments(devices, artifacts)
    return experiments, devices, artifacts


def test_pl_family_collapses_into_one_experiment():
    experiments, _, _ = _derived()
    by_id = {experiment.experiment_id: experiment for experiment in experiments}
    trace = by_id['D356-0003']
    assert trace.files_by_role['raw'] == (
        StorageReference(_SOURCE, f'{ALIAS}/Initial Data/trace.csv'),
    )
    assert trace.files_by_role['processed'] == (
        StorageReference(_SOURCE, f'{ALIAS}/Processed Data/trace_PL.dat'),
        StorageReference(
            _SOURCE, f'{ALIAS}/Processed Data/trace_avg1_DR_R_External.dat'
        ),
        StorageReference(
            _SOURCE, f'{ALIAS}/Processed Data/trace_avg1_DR_R_Self.dat'
        ),
    )
    assert trace.files_by_role['figure'] == (
        StorageReference(
            _SOURCE, f'{ALIAS}/Processed Data/trace_PL_linear.png'
        ),
        StorageReference(_SOURCE, f'{ALIAS}/Processed Data/trace_PL_log.png'),
        StorageReference(
            _SOURCE, f'{ALIAS}/Processed Data/trace_avg1_DR_R_External.png'
        ),
        StorageReference(
            _SOURCE, f'{ALIAS}/Processed Data/trace_avg1_DR_R_Self.png'
        ),
    )
    assert trace.metadata['derived_figure_variants'] == {
        'linear': f'{ALIAS}/Processed Data/trace_PL_linear.png',
        'log': f'{ALIAS}/Processed Data/trace_PL_log.png',
    }


def test_dr_analysis_outputs_collapse_into_the_measurement():
    experiments, _, _ = _derived()
    by_id = {experiment.experiment_id: experiment for experiment in experiments}
    trace = by_id['D356-0003']
    assert len(trace.files_by_role['processed']) == 3  # noqa: PLR2004
    assert len(trace.files_by_role['figure']) == 4  # noqa: PLR2004
    stems = {
        Path(reference.relative_path).stem
        for references in trace.files_by_role.values()
        for reference in references
    }
    assert stems == {
        'trace',
        'trace_PL',
        'trace_PL_linear',
        'trace_PL_log',
        'trace_avg1_DR_R_Self',
        'trace_avg1_DR_R_External',
    }


def test_counter_suffix_is_part_of_the_measurement_identity():
    experiments, _, _ = _derived()
    by_id = {experiment.experiment_id: experiment for experiment in experiments}
    amb = by_id['D356-0000']
    assert amb.files_by_role['raw'] == (
        StorageReference(_SOURCE, f'{ALIAS}/Initial Data/amb.csv'),
    )
    assert 'processed' not in amb.files_by_role
    amb_001 = by_id['D356-0001']
    assert amb_001.files_by_role['raw'] == (
        StorageReference(_SOURCE, f'{ALIAS}/Initial Data/amb_001.csv'),
    )
    assert amb_001.files_by_role['processed'] == (
        StorageReference(_SOURCE, f'{ALIAS}/Processed Data/amb_001_PL.dat'),
    )


def test_exact_raw_duplicate_under_processed_data_stays_raw():
    experiments, _, _ = _derived()
    by_id = {experiment.experiment_id: experiment for experiment in experiments}
    other = by_id['D356-0002']
    assert other.files_by_role['raw'] == (
        StorageReference(_SOURCE, f'{ALIAS}/Initial Data/other.csv'),
        StorageReference(_SOURCE, f'{ALIAS}/Processed Data/other.csv'),
    )


def test_unresolved_processed_file_is_flagged():
    experiments, _, _ = _derived()
    by_id = {experiment.experiment_id: experiment for experiment in experiments}
    standalone = by_id['D356-0004']
    assert standalone.files_by_role == {
        'processed': (
            StorageReference(_SOURCE, f'{ALIAS}/Processed Data/standalone.dat'),
        )
    }
    assert standalone.metadata['unresolved_processed_files'] == (
        f'{ALIAS}/Processed Data/standalone.dat',
    )
    assert any(
        'without a deterministically matching raw measurement' in warning
        for warning in standalone.warnings
    )


def test_d345_lowercase_raw_folders_with_duplicate_copies():
    experiments, _, _ = _derived()
    by_id = {experiment.experiment_id: experiment for experiment in experiments}
    run1 = by_id['D345-0000']
    assert run1.files_by_role['raw'] == (
        StorageReference(
            _SOURCE,
            f'{D345_ALIAS}/Initial data after processing/run1.csv',
        ),
        StorageReference(_SOURCE, f'{D345_ALIAS}/Initial data/run1.csv'),
    )
    assert run1.files_by_role['processed'] == (
        StorageReference(
            _SOURCE, f'{D345_ALIAS}/Processed Data/run1_avg1_DR_R_Self.dat'
        ),
    )
    assert run1.files_by_role['figure'] == (
        StorageReference(
            _SOURCE, f'{D345_ALIAS}/Processed Data/run1_avg1_DR_R_Self.png'
        ),
    )


def test_metadata_merges_across_all_member_stems():
    device = Device(
        'D356', maker_namespace='YZ', local_device_id='D356', aliases=(ALIAS,)
    )
    artifacts = (
        _artifact(
            'm-raw',
            'D356',
            f'{ALIAS}/Initial Data/'
            'YZ356_9Tp1n1_3.6KPL_633nm_700nmc_2sx1_FixTG=-0.2_Vb0to+20.csv',
            'csv',
        ),
        _artifact(
            'm-pl',
            'D356',
            f'{ALIAS}/Processed Data/'
            'YZ356_9Tp1n1_3.6KPL_633nm_700nmc_2sx1_FixTG=-0.2_Vb0to+20_PL.dat',
            'dat',
        ),
        _artifact(
            'm-linear',
            'D356',
            f'{ALIAS}/Processed Data/'
            'YZ356_9Tp1n1_3.6KPL_633nm_700nmc_2sx1_FixTG=-0.2_Vb0to+20_PL_linear.png',
            'png',
        ),
        _artifact(
            'm-log',
            'D356',
            f'{ALIAS}/Processed Data/'
            'YZ356_9Tp1n1_3.6KPL_633nm_700nmc_2sx1_FixTG=-0.2_Vb0to+20_PL_log.png',
            'png',
        ),
    )
    (experiment,) = derive_device_experiments((device,), artifacts)
    metadata = experiment.metadata
    assert {
        key: metadata[key]
        for key in (
            'sample_id',
            'temperature_K',
            'magnetic_field_T',
            'excitation_wavelength_nm',
            'center_wavelength_nm',
            'integration_time_s',
            'averages',
            'measurement_type',
            'measurement_point_label',
            'fixed_top_gate_V',
            'bias_start_V',
            'bias_stop_V',
        )
    } == {
        'sample_id': 'D356',
        'temperature_K': 3.6,
        'magnetic_field_T': 9.0,
        'excitation_wavelength_nm': 633.0,
        'center_wavelength_nm': 700.0,
        'integration_time_s': 2.0,
        'averages': 1,
        'measurement_type': 'photoluminescence',
        'measurement_point_label': 'p1n1',
        'fixed_top_gate_V': -0.2,
        'bias_start_V': 0.0,
        'bias_stop_V': 20.0,
    }
    assert metadata['device_id'] == 'D356'
    assert metadata['directory_context'] == ALIAS
    assert metadata['derived_figure_variants']['linear'].endswith('_PL_linear.png')
    assert metadata['derived_figure_variants']['log'].endswith('_PL_log.png')
    assert experiment.parser_version == 'device_directory_context/v2'
    assert experiment.confidence == 0.0
    assert experiment.needs_review is False
    assert experiment.review_state == 'unknown'
    assert experiment.warnings == ()


def test_derivation_is_deterministic_and_zero_padded_per_device():
    experiments, _, _ = _derived()
    again, _, _ = _derived()
    assert experiments == again
    assert [experiment.experiment_id for experiment in experiments] == [
        'D345-0000',
        'D356-0000',
        'D356-0001',
        'D356-0002',
        'D356-0003',
        'D356-0004',
    ]
    assert len({experiment.experiment_id for experiment in experiments}) == len(
        experiments
    )


def _corpus_experiments(raw_stem: str, processed_stem: str):
    device = Device(
        'D356', maker_namespace='YZ', local_device_id='D356', aliases=(ALIAS,)
    )
    artifacts = (
        _artifact(
            'c-raw', 'D356', f'{ALIAS}/Initial Data/{raw_stem}.csv', 'csv'
        ),
        _artifact(
            'c-proc', 'D356', f'{ALIAS}/Processed Data/{processed_stem}.dat', 'dat'
        ),
    )
    return derive_device_experiments((device,), artifacts)


RAW_ADJUDICATED_STEM = (
    'YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG-SweepBG1=2_Vb+2to-8'
)
PROCESSED_ADJUDICATED_STEM = (
    'YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_'
    'FixTG4V-SweepBG1=2_Vb+2to-8_avg1_DR_R_Self'
)


def test_human_reviewed_adjudication_merges_raw_into_processed():
    experiments = _corpus_experiments(
        RAW_ADJUDICATED_STEM, PROCESSED_ADJUDICATED_STEM
    )
    assert len(experiments) == 1  # noqa: PLR2004
    (experiment,) = experiments
    # The reviewed processed experiment keeps its identity; the raw-only
    # experiment is absorbed.
    assert experiment.experiment_id == 'D356-0001'
    assert experiment.files_by_role == {
        'raw': (
            StorageReference(
                _SOURCE,
                f'{ALIAS}/Initial Data/'
                f'{RAW_ADJUDICATED_STEM}.csv',
            ),
        ),
        'processed': (
            StorageReference(
                _SOURCE,
                f'{ALIAS}/Processed Data/'
                f'{PROCESSED_ADJUDICATED_STEM}.dat',
            ),
        ),
    }
    assert experiment.metadata['fixed_top_gate_V'] == FIXED_TOP_GATE_V_4
    assert experiment.needs_review is False
    assert experiment.review_state == 'accepted'
    # The original abstention history is preserved, not deleted.
    assert 'unresolved_processed_files' not in experiment.metadata
    assert experiment.metadata['resolved_unresolved_history'] == (
        f'{ALIAS}/Processed Data/{PROCESSED_ADJUDICATED_STEM}.dat',
    )
    assert any(
        'without a deterministically matching raw measurement' in warning
        for warning in experiment.warnings
    )
    assert any(
        'unsupported electrical expression: SweepBG1=2' in warning
        for warning in experiment.warnings
    )


def test_human_reviewed_adjudication_claim_fields_and_evidence():
    experiments = _corpus_experiments(
        RAW_ADJUDICATED_STEM, PROCESSED_ADJUDICATED_STEM
    )
    (claims,) = build_human_reviewed_match_claims(experiments)
    assert claims.subject_type == SUBJECT_EXPERIMENT
    assert claims.subject_id == 'D356-0001'
    assert claims.field == 'measured_on_raw_match'
    assert claims.value == {
        'raw_relative_path': (
            f'{ALIAS}/Initial Data/{RAW_ADJUDICATED_STEM}.csv'
        ),
        'device_id': 'D356',
        'experiment_id': 'D356-0001',
    }
    assert claims.source_type == 'human_review'
    assert claims.source_reference == 'artifacts/d356_0316_human_review_packet.md'
    assert claims.extraction_method == 'human_reviewed_match'
    assert claims.category == 'device_linkage'
    assert {
        'Vtg_set=4',
        'Vtg_meas=4',
        'raw filename omits FixTG value',
        'artifacts/d356_0316_human_review_packet.md',
    } <= set(claims.evidence)
    assert claims.review_status == 'accepted'


def test_fixtg4v_without_adjudicated_raw_stays_deterministically_linked():
    experiments = _corpus_experiments(
        'YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG=4-SweepBG1=2_Vb+2to-8',
        PROCESSED_ADJUDICATED_STEM,
    )
    assert len(experiments) == 1  # noqa: PLR2004
    (experiment,) = experiments
    assert experiment.needs_review is False
    assert experiment.metadata['fixed_top_gate_V'] == FIXED_TOP_GATE_V_4
    assert build_human_reviewed_match_claims(experiments) == ()


def test_d356_0317_analog_stays_unresolved_and_unchanged():
    processed_stem = (
        'YZ356_pa_BG2-CG_3.6KREF_720nmc_0p1sx10_'
        'FixTG=-4-SweepBG1=2_Vb0to+12_001_avg1_DR_R_External'
    )
    device = Device(
        'D356', maker_namespace='YZ', local_device_id='D356', aliases=(ALIAS,)
    )
    artifacts = (
        _artifact(
            'r-317-dat',
            'D356',
            f'{ALIAS}/Processed Data/{processed_stem}.dat',
            'dat',
        ),
        _artifact(
            'r-317-png',
            'D356',
            f'{ALIAS}/Processed Data/{processed_stem}.png',
            'png',
        ),
    )
    (experiment,) = derive_device_experiments((device,), artifacts)
    assert experiment.experiment_id == 'D356-0000'
    assert experiment.needs_review is True
    assert experiment.review_state == 'unknown'
    assert experiment.metadata['unresolved_processed_files'] == (
        f'{ALIAS}/Processed Data/{processed_stem}.dat',
        f'{ALIAS}/Processed Data/{processed_stem}.png',
    )
    assert any(
        'without a deterministically matching raw measurement' in warning
        for warning in experiment.warnings
    )
    assert build_human_reviewed_match_claims((experiment,)) == ()


def test_normalized_metadata_match_links_fully_compatible_raw():
    experiments = _corpus_experiments(
        'YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG=4-SweepBG1=2_Vb+2to-8',
        'YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_'
        'FixTG4V-SweepBG1=2_Vb+2to-8_avg1_DR_R_Self',
    )
    assert len(experiments) == 1  # noqa: PLR2004
    (experiment,) = experiments
    assert experiment.needs_review is False
    assert experiment.metadata['fixed_top_gate_V'] == FIXED_TOP_GATE_V_4
    assert experiment.files_by_role['raw'] == (
        StorageReference(
            _SOURCE,
            f'{ALIAS}/Initial Data/'
            'YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_'
            'FixTG=4-SweepBG1=2_Vb+2to-8.csv',
        ),
    )
    assert experiment.files_by_role['processed'] == (
        StorageReference(
            _SOURCE,
            f'{ALIAS}/Processed Data/'
            'YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_'
            'FixTG4V-SweepBG1=2_Vb+2to-8_avg1_DR_R_Self.dat',
        ),
    )


def test_counter_suffix_mismatch_prevents_normalized_link():
    experiments = _corpus_experiments(
        'YZ356_pa_BG2-CG_3.6KREF_720nmc_0p1sx10_FixTG=4-SweepBG1=2_Vb0to+12',
        'YZ356_pa_BG2-CG_3.6KREF_720nmc_0p1sx10_'
        'FixTG4V-SweepBG1=2_Vb0to+12_001_avg1_DR_R_External',
    )
    by_id = {experiment.experiment_id: experiment for experiment in experiments}
    assert len(by_id) == 2  # noqa: PLR2004
    processed = by_id['D356-0001']
    assert processed.needs_review is True


def test_gate_value_mismatch_prevents_normalized_link():
    experiments = _corpus_experiments(
        'YZ356_pa_BG2-CG_3.6KREF_720nmc_0p1sx10_'
        'FixTG=-6-SweepBG1=2_Vb0to+12_001',
        'YZ356_pa_BG2-CG_3.6KREF_720nmc_0p1sx10_'
        'FixTG=-4-SweepBG1=2_Vb0to+12_001_avg1_DR_R_External',
    )
    by_id = {experiment.experiment_id: experiment for experiment in experiments}
    assert len(by_id) == 2  # noqa: PLR2004
    raw = by_id['D356-0000']
    processed = by_id['D356-0001']
    assert raw.metadata['fixed_top_gate_V'] == FIXED_TOP_GATE_V_NEG_6
    assert processed.metadata['fixed_top_gate_V'] == FIXED_TOP_GATE_V_NEG_4
    assert processed.needs_review is True


def test_relationships_and_claims_are_exact_and_deterministic():
    experiments, _, _ = _derived()
    relationships = build_measured_on_relationships(experiments)
    assert len(relationships) == len(experiments)
    ids = []
    for experiment, relationship in zip(experiments, relationships, strict=True):
        assert relationship.source_type == SUBJECT_EXPERIMENT
        assert relationship.source_id == experiment.experiment_id
        assert relationship.predicate == 'measured_on'
        assert relationship.target_type == SUBJECT_DEVICE
        assert relationship.target_id == experiment.metadata['device_id']
        assert relationship.provenance_source == experiment.metadata['directory_context']
        assert relationship.review_state == 'unknown'
        assert relationship.relationship_id == deterministic_relationship_id(
            source_type=SUBJECT_EXPERIMENT,
            source_id=experiment.experiment_id,
            predicate='measured_on',
            target_type=SUBJECT_DEVICE,
            target_id=experiment.metadata['device_id'],
            provenance_source=experiment.metadata['directory_context'],
        )
        ids.append(relationship.relationship_id)
    assert len(set(ids)) == len(ids)

    claims = build_measured_on_claims(experiments)
    assert len(claims) == len(experiments)
    for experiment, claim in zip(experiments, claims, strict=True):
        assert claim.subject_type == SUBJECT_EXPERIMENT
        assert claim.subject_id == experiment.experiment_id
        assert claim.field == 'measured_on_device'
        assert claim.source_type == 'storage_directory'
        assert claim.source_reference == experiment.metadata['directory_context']
        assert claim.extraction_method == 'device_directory_context'
        assert claim.review_status == 'unknown'


def test_derived_from_edges_are_deterministic_and_chain_correctly():
    experiments, _, _ = _derived()
    edges = build_derived_from_relationships(experiments)
    by_pair = {(edge.source_id, edge.target_id): edge for edge in edges}
    assert len(by_pair) == len(edges)
    for edge in edges:
        assert edge.source_type == 'file'
        assert edge.target_type == 'file'
        assert edge.predicate == 'derived_from'
        assert edge.review_state == 'unknown'

    def file_id(relative_path: str) -> str:
        return deterministic_storage_reference_id(
            storage_source_id=_SOURCE, relative_path=relative_path
        )

    # PL chain: raw -> processed DAT -> figure (canonical data-flow direction).
    assert (
        file_id(f'{ALIAS}/Initial Data/trace.csv'),
        file_id(f'{ALIAS}/Processed Data/trace_PL.dat'),
    ) in by_pair
    assert (
        file_id(f'{ALIAS}/Processed Data/trace_PL.dat'),
        file_id(f'{ALIAS}/Processed Data/trace_PL_linear.png'),
    ) in by_pair
    assert (
        file_id(f'{ALIAS}/Processed Data/trace_PL.dat'),
        file_id(f'{ALIAS}/Processed Data/trace_PL_log.png'),
    ) in by_pair
    # DR analysis: raw -> DAT -> figure.
    assert (
        file_id(f'{ALIAS}/Processed Data/trace_avg1_DR_R_Self.dat'),
        file_id(f'{ALIAS}/Processed Data/trace_avg1_DR_R_Self.png'),
    ) in by_pair
    assert (
        file_id(f'{ALIAS}/Initial Data/trace.csv'),
        file_id(f'{ALIAS}/Processed Data/trace_avg1_DR_R_External.dat'),
    ) in by_pair
    # D345: both raw copies are lineage sources of the analysis DAT.
    assert (
        file_id(f'{D345_ALIAS}/Initial data/run1.csv'),
        file_id(f'{D345_ALIAS}/Processed Data/run1_avg1_DR_R_Self.dat'),
    ) in by_pair
    assert (
        file_id(f'{D345_ALIAS}/Initial data after processing/run1.csv'),
        file_id(f'{D345_ALIAS}/Processed Data/run1_avg1_DR_R_Self.dat'),
    ) in by_pair


def _seed_catalog(tmp_path: Path) -> Path:
    catalog_path = tmp_path / 'catalog.db'
    devices, artifacts = _fixture()
    store = SQLiteCatalogStore(catalog_path)
    store.rebuild(
        CatalogSnapshot(
            experiments=(
                Experiment(
                    'YZ247-0432',
                    metadata={'sample_id': 'YZ247', 'measurement_type': 'photoluminescence'},
                    files_by_role={},
                ),
            ),
            devices=devices,
            artifacts=artifacts,
        )
    )
    store.close()
    return catalog_path


def _apply(
    catalog_path: Path,
) -> tuple[sqlite3.Connection, LinkageResult, dict[str, int]]:
    connection = sqlite3.connect(str(catalog_path), isolation_level=None)
    devices, artifacts = read_catalog_objects(connection)
    experiments = derive_device_experiments(devices, artifacts)
    relationships = build_measured_on_relationships(experiments)
    claims = build_measured_on_claims(experiments)
    claims = [*claims, *build_human_reviewed_match_claims(experiments)]
    derived_from = build_derived_from_relationships(experiments)
    result = apply_device_experiment_linkage(
        connection,
        experiments,
        [*relationships, *derived_from],
        claims,
    )
    connection.row_factory = sqlite3.Row

    def count(sql: str) -> int:
        return int(connection.execute(sql).fetchone()[0])

    counts = {
        'experiments': count('SELECT COUNT(*) FROM experiments'),
        'experiment_files': count('SELECT COUNT(*) FROM experiment_files'),
        'claims': count('SELECT COUNT(*) FROM metadata_claims'),
        'relationships': count('SELECT COUNT(*) FROM relationships'),
        'devices': count('SELECT COUNT(*) FROM devices'),
        'artifacts': count('SELECT COUNT(*) FROM artifacts'),
        'yz247': count(
            "SELECT COUNT(*) FROM experiments WHERE experiment_id = 'YZ247-0432'"
        ),
    }
    return connection, result, counts


def _content_hash(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for table in (
        'experiments',
        'experiment_files',
        'metadata_claims',
        'relationships',
        'devices',
        'artifacts',
    ):
        digest.update(table.encode('utf-8'))
        rows = connection.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall()
        digest.update(
            json.dumps([tuple(row) for row in rows], sort_keys=True).encode('utf-8')
        )
    return digest.hexdigest()


def test_reset_and_rerun_is_byte_identical(tmp_path):
    catalog_path = _seed_catalog(tmp_path)
    connection, first, first_counts = _apply(catalog_path)
    first_hash = _content_hash(connection)
    yz247_row = dict(
        connection.execute(
            "SELECT * FROM experiments WHERE experiment_id = 'YZ247-0432'"
        ).fetchone()
    )
    connection.close()

    connection, second, second_counts = _apply(catalog_path)
    second_hash = _content_hash(connection)
    connection.close()

    assert first.experiments == 6  # noqa: PLR2004
    assert first.experiment_files == 18  # noqa: PLR2004
    assert first.claims == 6  # noqa: PLR2004
    assert first.relationships == 17  # noqa: PLR2004
    assert first.derived_from == 11  # noqa: PLR2004
    assert second.experiments == first.experiments
    assert second.experiment_files == first.experiment_files
    assert second.claims == first.claims
    assert second.relationships == first.relationships
    assert second.derived_from == first.derived_from
    assert second_counts == first_counts
    assert second_hash == first_hash
    assert first_counts['experiments'] == 7  # noqa: PLR2004
    assert first_counts['devices'] == 4  # noqa: PLR2004
    assert first_counts['artifacts'] == 26  # noqa: PLR2004
    assert first_counts['yz247'] == 1  # noqa: PLR2004
    assert yz247_row['metadata_json'] == json.dumps(
        {'sample_id': 'YZ247', 'measurement_type': 'photoluminescence'},
        sort_keys=True,
        separators=(',', ':'),
    )


def test_no_duplicate_file_associations(tmp_path):
    catalog_path = _seed_catalog(tmp_path)
    connection, _, _ = _apply(catalog_path)
    rows = connection.execute(
        """
        SELECT experiment_id, storage_source_id, relative_path
        FROM experiment_files
        """
    ).fetchall()
    assert len(rows) == len(set(rows))
    connection.close()


def test_device_experiments_api_returns_linked_experiments(tmp_path):
    catalog_path = _seed_catalog(tmp_path)
    connection, _, _ = _apply(catalog_path)
    connection.close()

    client = TestClient(create_app(catalog_path, tmp_path / 'preview'))
    response = client.get(
        '/api/devices/D356/experiments', params={'limit': 5, 'offset': 0}
    )
    assert response.status_code == 200  # noqa: PLR2004
    payload = response.json()
    assert payload['total_count'] == 5  # noqa: PLR2004
    assert {item['experiment_id'] for item in payload['items']} == {
        'D356-0000',
        'D356-0001',
        'D356-0002',
        'D356-0003',
        'D356-0004',
    }

    trace = next(item for item in payload['items'] if item['experiment_id'] == 'D356-0003')
    assert any(
        path.endswith('Initial Data/trace.csv') for path in trace['files_by_role']['raw']
    )
    assert any(
        path.endswith('Processed Data/trace_PL.dat')
        for path in trace['files_by_role']['processed']
    )
    assert {
        Path(path).stem
        for path in trace['files_by_role']['figure']
    } == {'trace_PL_linear', 'trace_PL_log', 'trace_avg1_DR_R_Self', 'trace_avg1_DR_R_External'}

    d345 = client.get('/api/devices/D345/experiments')
    assert d345.status_code == 200  # noqa: PLR2004
    assert d345.json()['total_count'] == 1  # noqa: PLR2004
    assert d345.json()['items'][0]['experiment_id'] == 'D345-0000'

    empty = client.get('/api/devices/D357/experiments')
    assert empty.status_code == 200  # noqa: PLR2004
    assert empty.json()['total_count'] == 0

    searched = client.get('/api/experiments', params={'q': 'D356'})
    assert searched.json()['total_count'] == 5  # noqa: PLR2004

    exact = client.get('/api/experiments', params={'q': 'YZ247-0432'})
    assert [item['experiment_id'] for item in exact.json()['items']] == ['YZ247-0432']

    artifacts = client.get(
        '/api/artifacts', params={'device_id': 'D356', 'limit': 5, 'offset': 0}
    )
    assert artifacts.status_code == 200  # noqa: PLR2004
    assert len(artifacts.json()['items']) == 5  # noqa: PLR2004
    assert artifacts.json()['total_count'] == 18  # noqa: PLR2004


def _adjudication_seed_catalog(tmp_path: Path) -> Path:
    catalog_path = tmp_path / 'catalog.db'
    device = Device(
        'D356', maker_namespace='YZ', local_device_id='D356', aliases=(ALIAS,)
    )
    artifacts = (
        _artifact(
            'ad-raw',
            'D356',
            f'{ALIAS}/Initial Data/{RAW_ADJUDICATED_STEM}.csv',
            'csv',
        ),
        _artifact(
            'ad-dat',
            'D356',
            f'{ALIAS}/Processed Data/{PROCESSED_ADJUDICATED_STEM}.dat',
            'dat',
        ),
        _artifact(
            'ad-png',
            'D356',
            f'{ALIAS}/Processed Data/{PROCESSED_ADJUDICATED_STEM}.png',
            'png',
        ),
        _artifact(
            'nb-raw',
            'D356',
            f'{ALIAS}/Initial Data/'
            'YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_'
            'FixTG=-3-SweepBG1=2_Vb+8to0.csv',
            'csv',
        ),
        _artifact(
            'nb-dat',
            'D356',
            f'{ALIAS}/Processed Data/'
            'YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_'
            'FixTG=-3-SweepBG1=2_Vb+8to0_avg1_DR_R_External.dat',
            'dat',
        ),
        _artifact(
            'nb-png',
            'D356',
            f'{ALIAS}/Processed Data/'
            'YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_'
            'FixTG=-3-SweepBG1=2_Vb+8to0_avg1_DR_R_External.png',
            'png',
        ),
    )
    store = SQLiteCatalogStore(catalog_path)
    store.rebuild(
        CatalogSnapshot(
            experiments=(
                Experiment(
                    'YZ247-0432',
                    metadata={
                        'sample_id': 'YZ247',
                        'measurement_type': 'photoluminescence',
                    },
                    files_by_role={},
                ),
            ),
            devices=(device,),
            artifacts=artifacts,
        )
    )
    store.close()
    return catalog_path


def test_adjudication_merge_is_idempotent_and_absorbs_raw_experiment(tmp_path):
    catalog_path = _adjudication_seed_catalog(tmp_path)
    connection, first, first_counts = _apply(catalog_path)
    first_hash = _content_hash(connection)
    connection.close()

    connection, second, second_counts = _apply(catalog_path)
    second_hash = _content_hash(connection)
    connection.close()

    assert second_counts == first_counts
    assert second_hash == first_hash
    assert first_counts['experiments'] == 3  # noqa: PLR2004
    assert first.experiments == 2  # noqa: PLR2004
    assert first.claims == 3  # noqa: PLR2004
    assert first.derived_from == 4  # noqa: PLR2004

    connection = sqlite3.connect(str(catalog_path), isolation_level=None)
    connection.row_factory = sqlite3.Row
    ids = {
        row['experiment_id']
        for row in connection.execute('SELECT experiment_id FROM experiments')
    }
    assert 'D356-0002' in ids
    assert 'D356-0000' not in ids  # raw-only experiment absorbed

    row = connection.execute(
        "SELECT * FROM experiments WHERE experiment_id = 'D356-0002'"
    ).fetchone()
    assert row['needs_review'] == 0
    assert row['review_state'] == 'accepted'
    metadata = json.loads(row['metadata_json'])
    assert 'unresolved_processed_files' not in metadata
    assert metadata['resolved_unresolved_history'] == [
        f'{ALIAS}/Processed Data/{PROCESSED_ADJUDICATED_STEM}.dat',
        f'{ALIAS}/Processed Data/{PROCESSED_ADJUDICATED_STEM}.png',
    ]
    assert any(
        'without a deterministically matching raw measurement' in warning
        for warning in json.loads(row['warnings_json'])
    )

    files = connection.execute(
        "SELECT role, relative_path FROM experiment_files "
        "WHERE experiment_id = 'D356-0002' ORDER BY ordinal"
    ).fetchall()
    assert [row['role'] for row in files] == ['raw', 'processed', 'figure']
    assert files[0]['relative_path'].endswith(
        f'Initial Data/{RAW_ADJUDICATED_STEM}.csv'
    )

    claims = connection.execute(
        "SELECT field, review_status FROM metadata_claims "
        "WHERE subject_id = 'D356-0002' ORDER BY ordinal"
    ).fetchall()
    assert [tuple(row) for row in claims] == [
        ('measured_on_device', 'unknown'),
        ('measured_on_raw_match', 'accepted'),
    ]

    files_by_experiment = connection.execute(
        "SELECT experiment_id, storage_source_id, relative_path "
        "FROM experiment_files"
    ).fetchall()
    assert len(files_by_experiment) == len(set(files_by_experiment))
    connection.close()


def test_api_projects_review_evidence_for_adjudicated_experiment(tmp_path):
    catalog_path = _adjudication_seed_catalog(tmp_path)
    connection, _, _ = _apply(catalog_path)
    connection.close()

    client = TestClient(create_app(catalog_path, tmp_path / 'preview'))
    response = client.get('/api/devices/D356/experiments', params={'limit': 10, 'offset': 0})
    assert response.status_code == 200  # noqa: PLR2004
    payload = response.json()
    assert payload['total_count'] == 2  # noqa: PLR2004
    by_id = {item['experiment_id']: item for item in payload['items']}
    merged = by_id['D356-0002']
    assert merged['needs_review'] is False
    assert merged['review_state'] == 'accepted'
    assert any(
        path.endswith(f'Initial Data/{RAW_ADJUDICATED_STEM}.csv')
        for path in merged['files_by_role']['raw']
    )
    assert merged['lineage'] == [
        {
            'source': f'{ALIAS}/Initial Data/{RAW_ADJUDICATED_STEM}.csv',
            'target': f'{ALIAS}/Processed Data/{PROCESSED_ADJUDICATED_STEM}.dat',
            'relation': 'derived_from',
        },
        {
            'source': f'{ALIAS}/Processed Data/{PROCESSED_ADJUDICATED_STEM}.dat',
            'target': f'{ALIAS}/Processed Data/{PROCESSED_ADJUDICATED_STEM}.png',
            'relation': 'derived_from',
        },
    ]
    assert merged['review_evidence'] == [
        {
            'field': 'measured_on_raw_match',
                'value': {
                    'raw_relative_path': (
                        f'{ALIAS}/Initial Data/{RAW_ADJUDICATED_STEM}.csv'
                    ),
                    'device_id': 'D356',
                    'experiment_id': 'D356-0002',
                },
            'source_type': 'human_review',
            'source_reference': 'artifacts/d356_0316_human_review_packet.md',
            'extraction_method': 'human_reviewed_match',
            'category': 'device_linkage',
            'evidence': [
                'Vtg_set=4',
                'Vtg_meas=4',
                'raw filename omits FixTG value',
                'artifacts/d356_0316_human_review_packet.md',
            ],
            'review_status': 'accepted',
        }
    ]
    assert by_id['D356-0001']['review_evidence'] is None
    assert by_id['D356-0001']['needs_review'] is False

    exact = client.get('/api/experiments', params={'experiment_id': 'D356-0002'})
    assert exact.status_code == 200  # noqa: PLR2004
    assert exact.json()['total_count'] == 1  # noqa: PLR2004
    assert (
        exact.json()['items'][0]['review_evidence'][0]['review_status']
        == 'accepted'
    )
