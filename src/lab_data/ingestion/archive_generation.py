"""Deterministic archive-generation job model.

An :class:`ArchiveGenerationJob` captures the caller-supplied identity and
ordered canonical relative source paths needed to generate one metadata
archive. It is intentionally local and generic: it carries no NOMAD fields,
inventory status, machine-specific source identity, or generated archive
content.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from nomad.datamodel import EntryArchive

from lab_data.ingestion.archive_builder import build_archive_draft
from lab_data.ingestion.proposal import ImportProposal
from lab_data.parsers.archive_serializer import (
    build_entry_archive,
    write_entry_archive_json,
)
from lab_data.parsers.mapper import build_optical_experiment
from lab_data.storage import StorageRoot

__all__ = [
    'ArchiveGenerationJob',
    'ArchiveGenerationPlan',
    'ArchiveGenerationExecutionResult',
    'ArchiveGenerationError',
    'execute_archive_generation',
    'plan_archive_generation',
]


def _validation_root() -> Path:
    """Return an absolute throwaway root used only for path normalization."""

    return Path(os.path.abspath(os.sep))


def _canonical_relative_path(value: object) -> str:
    """Validate and canonicalize one relative source or output path."""

    if not isinstance(value, str) or not value:
        raise ValueError('relative path must be a non-empty string')
    root = StorageRoot(_validation_root())
    resolved = root.resolve(value)
    return root.canonicalize(resolved)


@dataclass(frozen=True)
class ArchiveGenerationJob:
    """Immutable deterministic identity for one archive-generation task.

    ``proposal_id`` is supplied by the caller and is the only identity key.
    ``source_paths`` preserves the caller-provided order after canonicalizing
    each path to a forward-slash relative form. ``output_relative_path`` is the
    caller-resolved artifact destination, also canonicalized relative form.
    """

    proposal_id: str
    source_paths: tuple[str, ...]
    output_relative_path: str
    sample_id: str | None = None
    experiment_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.proposal_id, str) or not self.proposal_id:
            raise ValueError('proposal_id must be a non-empty string')
        if self.sample_id is not None and (
            not isinstance(self.sample_id, str) or not self.sample_id
        ):
            raise ValueError('sample_id must be a non-empty string or None')
        if self.experiment_id is not None and (
            not isinstance(self.experiment_id, str) or not self.experiment_id
        ):
            raise ValueError('experiment_id must be a non-empty string or None')
        if not isinstance(self.source_paths, (tuple, list)):
            raise TypeError('source_paths must be a tuple or list')

        object.__setattr__(
            self,
            'source_paths',
            tuple(_canonical_relative_path(path) for path in self.source_paths),
        )
        object.__setattr__(
            self,
            'output_relative_path',
            _canonical_relative_path(self.output_relative_path),
        )

    @property
    def source_count(self) -> int:
        """Return the number of source paths in this job."""

        return len(self.source_paths)


@dataclass(frozen=True)
class ArchiveGenerationPlan:
    """Immutable, deterministic result of archive-generation planning."""

    jobs: tuple[ArchiveGenerationJob, ...]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def proposal_count(self) -> int:
        """Return the number of planned jobs."""

        return len(self.jobs)

    @property
    def collision_count(self) -> int:
        """Return the number of detected destination collisions."""

        return sum(1 for error in self.errors if error.startswith('collision:'))


@dataclass(frozen=True)
class ArchiveGenerationError:
    """One attributable archive-generation failure."""

    proposal_id: str
    message: str


@dataclass(frozen=True)
class ArchiveGenerationExecutionResult:
    """Immutable outcome of executing an archive-generation plan."""

    jobs_requested: int
    jobs_succeeded: int
    jobs_failed: int
    output_paths: tuple[str, ...]
    errors: tuple[ArchiveGenerationError, ...]

    @property
    def failed_proposal_ids(self) -> tuple[str, ...]:
        """Return attributable proposal IDs for failed jobs in plan order."""

        return tuple(error.proposal_id for error in self.errors)


def _source_membership(experiment: object) -> tuple[str, ...]:
    """Return deterministic ordered canonical source paths for one experiment."""

    paths: list[str] = []
    for attribute in (
        'raw_files',
        'intermediate_files',
        'processed_files',
        'figure_files',
    ):
        paths.extend(sorted(getattr(experiment, attribute, ())))
    return tuple(paths)


def plan_archive_generation(  # noqa: PLR0913
    proposal_ids: Sequence[str],
    experiments: Sequence[object],
    *,
    output_dir: str = 'archives',
    output_root: str | Path | None = None,
) -> ArchiveGenerationPlan:
    """Plan exactly one deterministic archive-generation job per proposal.

    ``proposal_ids`` and ``experiments`` must have equal length. Each job uses
    the proposal id as its identity, preserves the experiment sample id, and
    records the experiment's role-bucket source membership in deterministic
    order. Output targets are ``<output_dir>/<proposal_id>.archive.json``.

    Duplicate output targets within the plan and any already-existing target
    under ``output_root`` are reported as collision errors; nothing is written
    or overwritten by this function.
    """

    if not isinstance(proposal_ids, Sequence) or isinstance(proposal_ids, (str, bytes)):
        raise TypeError('proposal_ids must be a sequence of strings')
    if not isinstance(experiments, Sequence) or isinstance(experiments, (str, bytes)):
        raise TypeError('experiments must be a sequence of experiment objects')
    if len(proposal_ids) != len(experiments):
        raise ValueError('proposal_ids and experiments must have equal length')

    jobs: list[ArchiveGenerationJob] = []
    warnings: list[str] = []
    errors: list[str] = []
    seen_outputs: set[str] = set()

    for index, (proposal_id, experiment) in enumerate(
        zip(proposal_ids, experiments, strict=True)
    ):
        if not isinstance(proposal_id, str) or not proposal_id:
            raise ValueError(f'proposal_ids[{index}] must be a non-empty string')

        try:
            output_relative = _canonical_relative_path(
                f'{output_dir}/{proposal_id}.archive.json'
            )
        except ValueError as error:
            raise ValueError(
                f'invalid output path for proposal {proposal_id!r}: {error}'
            ) from error

        if output_relative in seen_outputs:
            errors.append(
                f'collision: duplicate output target {output_relative!r} '
                f'for proposal {proposal_id!r}'
            )
        seen_outputs.add(output_relative)

        if output_root is not None:
            root_path = Path(output_root)
            target = root_path.joinpath(*output_relative.split('/'))
            if target.exists():
                errors.append(f'collision: output target already exists: {target}')

        sample_id = getattr(experiment, 'sample_id', None)
        jobs.append(
            ArchiveGenerationJob(
                proposal_id=proposal_id,
                source_paths=_source_membership(experiment),
                output_relative_path=output_relative,
                sample_id=sample_id,
                experiment_id=None,
            )
        )

    return ArchiveGenerationPlan(
        jobs=tuple(jobs),
        warnings=tuple(sorted(warnings)),
        errors=tuple(sorted(errors)),
    )


def _read_back_and_verify(
    output_path: Path,
    *,
    sample_id: str | None,
    needs_review: bool | None,
) -> bool:
    """Read back a written archive and verify identity/review markers."""

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    archive = EntryArchive.m_from_dict(payload)
    if archive.data is None:
        return False
    if sample_id is not None and archive.data.sample_id != sample_id:
        return False
    review = getattr(archive.data, 'ingestion_review', None)
    if needs_review is not None:
        if review is None or review.needs_review != needs_review:
            return False
    return True


def execute_archive_generation(  # noqa: PLR0912, PLR0913
    plan: ArchiveGenerationPlan,
    experiments_by_proposal: dict[str, object],
    *,
    output_root: str | Path,
) -> ArchiveGenerationExecutionResult:
    """Generate local archive files for a plan using the existing pipeline.

    Each job looks up its experiment, maps it through the archive draft,
    optical-experiment, and entry-archive builders, then writes a single archive
    JSON with the refuse-on-overwrite serializer. A job is reported successful
    only after its written archive round-trips and identity/review checks pass.
    """

    if not isinstance(plan, ArchiveGenerationPlan):
        raise TypeError('plan must be an ArchiveGenerationPlan')
    if not isinstance(experiments_by_proposal, dict):
        raise TypeError('experiments_by_proposal must be a mapping')
    root_path = Path(output_root)

    errors: list[ArchiveGenerationError] = []
    output_paths: list[str] = []

    for job in plan.jobs:
        try:
            experiment = experiments_by_proposal[job.proposal_id]
        except KeyError:
            errors.append(
                ArchiveGenerationError(
                    job.proposal_id,
                    f'missing experiment for proposal {job.proposal_id!r}',
                )
            )
            continue

        try:
            draft = build_archive_draft(ImportProposal(experiments=[experiment]))[0]
            optical = build_optical_experiment(draft)
            archive = build_entry_archive(optical)
            output_path = root_path.joinpath(*job.output_relative_path.split('/'))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            write_entry_archive_json(archive, output_path)

            if not _read_back_and_verify(
                output_path,
                sample_id=job.sample_id,
                needs_review=getattr(experiment, 'needs_review', None),
            ):
                raise ValueError('written archive failed read-back verification')
        except Exception as error:  # noqa: BLE001 - attributable boundary
            errors.append(
                ArchiveGenerationError(
                    job.proposal_id,
                    f'{type(error).__name__}: {error}',
                )
            )
            continue

        output_paths.append(str(output_path))

    return ArchiveGenerationExecutionResult(
        jobs_requested=len(plan.jobs),
        jobs_succeeded=len(output_paths),
        jobs_failed=len(errors),
        output_paths=tuple(output_paths),
        errors=tuple(errors),
    )
