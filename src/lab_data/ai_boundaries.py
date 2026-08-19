"""Provider-neutral contracts for optional metadata inference and embeddings.

The deterministic scanner and normalized proposal model remain the source of
scientific truth.  These contracts describe optional, reviewable suggestions
and comparable evidence records; they do not select or call a provider.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

__all__ = [
    'ArtifactRoleInferenceContext',
    'DeviceImageInferenceContext',
    'DeviceMetadataInferenceContext',
    'DeviceStructureInferenceContext',
    'EmbeddingProvider',
    'EmbeddingVector',
    'InferenceEvaluation',
    'MetadataInferenceContext',
    'MetadataInferenceProvider',
    'MetadataInferenceResult',
    'ScientificArtifactInferenceProvider',
    'ScientificArtifactInferenceResult',
    'ScientificInferenceCandidate',
    'SearchAgentEvaluation',
]


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class MetadataInferenceContext:
    """Deterministic context supplied to an optional inference provider.

    ``normalized_metadata`` is a snapshot of scanner/proposal values.  It is
    intentionally separate from provider suggestions so inference cannot
    replace scientific ground truth.
    """

    experiment_id: str
    normalized_metadata: Mapping[str, Any]
    source_files: tuple[str, ...] = ()
    context_version: str = '1'

    def __post_init__(self) -> None:
        if not isinstance(self.experiment_id, str) or not self.experiment_id:
            raise ValueError('experiment_id must be non-empty')
        if not self.context_version:
            raise ValueError('context_version must be non-empty')
        object.__setattr__(
            self, 'normalized_metadata', _freeze(self.normalized_metadata)
        )
        object.__setattr__(self, 'source_files', tuple(self.source_files))


@dataclass(frozen=True)
class MetadataInferenceResult:
    """Reviewable suggestions returned by a metadata inference provider."""

    provider_id: str
    model_id: str | None
    suggestions: Mapping[str, Any]
    abstained: bool = False
    requires_review: bool = False
    deterministic_validation_passed: bool | None = None
    validation_errors: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise ValueError('provider_id must be non-empty')
        if self.model_id is not None and (
            not isinstance(self.model_id, str) or not self.model_id
        ):
            raise ValueError('model_id must be a non-empty string when supplied')
        object.__setattr__(self, 'suggestions', _freeze(self.suggestions))
        object.__setattr__(self, 'validation_errors', tuple(self.validation_errors))
        object.__setattr__(self, 'evidence', tuple(self.evidence))
        if self.suggestions and not self.requires_review:
            raise ValueError('non-empty suggestions must require review')
        if self.abstained and self.suggestions:
            raise ValueError('abstained results cannot contain suggestions')
        if self.deterministic_validation_passed is True and self.validation_errors:
            raise ValueError(
                'validation_errors cannot be present when validation passed'
            )


@runtime_checkable
class MetadataInferenceProvider(Protocol):
    """Provider-neutral metadata inference boundary."""

    def infer(self, context: MetadataInferenceContext) -> MetadataInferenceResult:
        """Return suggestions without mutating ``context`` or ground truth."""


@dataclass(frozen=True)
class EmbeddingVector:
    """Provider-neutral embedding output, kept separate from metadata/storage."""

    values: tuple[float, ...]
    provider_id: str
    model_id: str | None = None
    embedding_space_id: str | None = None
    version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise ValueError('provider_id must be non-empty')
        if not self.values:
            raise ValueError('values must contain at least one number')
        normalized_values = []
        for value in self.values:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError('values must contain only finite numbers')
            normalized_values.append(float(value))
        object.__setattr__(self, 'values', tuple(normalized_values))
        for name in ('model_id', 'embedding_space_id', 'version'):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f'{name} must be a non-empty string when supplied')


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Optional embedding generation boundary with no storage assumptions."""

    def embed(self, text: str) -> EmbeddingVector:
        """Return a vector tagged with provider/model/space identity."""


@dataclass(frozen=True)
class InferenceEvaluation:
    """Comparable evidence for one benchmark case and one provider result."""

    benchmark_case_id: str
    provider_id: str
    model_id: str | None = None
    correctness: bool | None = None
    abstained: bool = False
    requires_review: bool = False
    false_positive: bool | None = None
    latency_ms: float | None = None
    token_count: int | None = None
    cost: float | None = None
    deterministic_validation_passed: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.benchmark_case_id, str) or not self.benchmark_case_id:
            raise ValueError('benchmark_case_id must be non-empty')
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise ValueError('provider_id must be non-empty')
        if self.model_id is not None and (
            not isinstance(self.model_id, str) or not self.model_id
        ):
            raise ValueError('model_id must be a non-empty string when supplied')
        if self.latency_ms is not None and (
            isinstance(self.latency_ms, bool)
            or not isinstance(self.latency_ms, (int, float))
            or not math.isfinite(self.latency_ms)
            or self.latency_ms < 0
        ):
            raise ValueError('latency_ms must be non-negative')
        if self.token_count is not None and (
            isinstance(self.token_count, bool)
            or not isinstance(self.token_count, int)
            or self.token_count < 0
        ):
            raise ValueError('token_count must be non-negative')
        if self.cost is not None and (
            isinstance(self.cost, bool)
            or not isinstance(self.cost, (int, float))
            or not math.isfinite(self.cost)
            or self.cost < 0
        ):
            raise ValueError('cost must be non-negative')


@dataclass(frozen=True)
class SearchAgentEvaluation:
    """Comparable evidence for a search-agent benchmark case.

    This is a passive record only.  It does not define query interpretation,
    ranking, or an execution strategy for a search agent.
    """

    benchmark_question_id: str
    provider_id: str
    model_id: str | None = None
    retrieval_correctness: bool | None = None
    recall: float | None = None
    ranking_quality: float | None = None
    interpretation_quality: float | None = None
    false_positive_rate: float | None = None
    clarification_behavior: str | None = None
    latency_ms: float | None = None
    cost: float | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.benchmark_question_id, str)
            or not self.benchmark_question_id
        ):
            raise ValueError('benchmark_question_id must be non-empty')
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise ValueError('provider_id must be non-empty')
        if self.model_id is not None and (
            not isinstance(self.model_id, str) or not self.model_id
        ):
            raise ValueError('model_id must be a non-empty string when supplied')
        for field_name in (
            'recall',
            'ranking_quality',
            'interpretation_quality',
            'false_positive_rate',
        ):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 1
            ):
                raise ValueError(f'{field_name} must be between 0 and 1')
        if self.latency_ms is not None and (
            isinstance(self.latency_ms, bool)
            or not isinstance(self.latency_ms, (int, float))
            or not math.isfinite(self.latency_ms)
            or self.latency_ms < 0
        ):
            raise ValueError('latency_ms must be non-negative')
        if self.cost is not None and (
            isinstance(self.cost, bool)
            or not isinstance(self.cost, (int, float))
            or not math.isfinite(self.cost)
            or self.cost < 0
        ):
            raise ValueError('cost must be non-negative')


@dataclass(frozen=True)
class ScientificInferenceCandidate:
    """One reviewable, provenance-shaped inference candidate."""

    field: str
    value: Any
    confidence: float | None = None
    category: str | None = None
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.field, str) or not self.field:
            raise ValueError('field must be a non-empty string')
        if self.confidence is not None and (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not math.isfinite(self.confidence)
        ):
            raise ValueError('confidence must be a finite number when supplied')
        if self.category is not None and (
            not isinstance(self.category, str) or not self.category
        ):
            raise ValueError('category must be a non-empty string when supplied')
        object.__setattr__(self, 'value', _freeze(self.value))
        object.__setattr__(self, 'evidence', tuple(self.evidence))


@dataclass(frozen=True)
class ScientificArtifactInferenceResult:
    """Provider-neutral scientific inference output with benchmark fields."""

    provider_id: str
    model_id: str | None
    task: str
    abstained: bool = False
    requires_review: bool = False
    candidates: tuple[ScientificInferenceCandidate, ...] = ()
    warnings: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise ValueError('provider_id must be a non-empty string')
        if self.model_id is not None and (
            not isinstance(self.model_id, str) or not self.model_id
        ):
            raise ValueError('model_id must be a non-empty string when supplied')
        if not isinstance(self.task, str) or not self.task:
            raise ValueError('task must be a non-empty string')
        if any(
            not isinstance(item, ScientificInferenceCandidate)
            for item in self.candidates
        ):
            raise TypeError(
                'candidates must contain ScientificInferenceCandidate values'
            )
        if self.candidates and not self.requires_review:
            raise ValueError('non-empty candidates must require review')
        if self.abstained and self.candidates:
            raise ValueError('abstained results cannot contain candidates')
        object.__setattr__(self, 'candidates', tuple(self.candidates))
        object.__setattr__(self, 'warnings', tuple(self.warnings))
        object.__setattr__(self, 'evidence', tuple(self.evidence))


@dataclass(frozen=True)
class DeviceMetadataInferenceContext:
    """Text-based device metadata inference context."""

    device_id: str
    text: str
    context_version: str = '1'

    def __post_init__(self) -> None:
        if not isinstance(self.device_id, str) or not self.device_id:
            raise ValueError('device_id must be a non-empty string')
        if not isinstance(self.text, str):
            raise ValueError('text must be a string')
        if not self.context_version:
            raise ValueError('context_version must be non-empty')


@dataclass(frozen=True)
class DeviceStructureInferenceContext:
    """Slide-structure-based device metadata inference context."""

    device_id: str
    slide_index: int
    title: str | None = None
    text_runs: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    image_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.device_id, str) or not self.device_id:
            raise ValueError('device_id must be a non-empty string')
        if (
            isinstance(self.slide_index, bool)
            or not isinstance(self.slide_index, int)
            or self.slide_index < 1
        ):
            raise ValueError('slide_index must be a positive integer')
        if self.title is not None and (
            not isinstance(self.title, str) or not self.title
        ):
            raise ValueError('title must be a non-empty string when supplied')
        object.__setattr__(self, 'text_runs', tuple(self.text_runs))
        object.__setattr__(self, 'labels', tuple(self.labels))
        object.__setattr__(self, 'image_refs', tuple(self.image_refs))


@dataclass(frozen=True)
class DeviceImageInferenceContext:
    """Image-based device classification context."""

    device_id: str
    image_reference: str

    def __post_init__(self) -> None:
        if not isinstance(self.device_id, str) or not self.device_id:
            raise ValueError('device_id must be a non-empty string')
        if not isinstance(self.image_reference, str) or not self.image_reference:
            raise ValueError('image_reference must be a non-empty string')


@dataclass(frozen=True)
class ArtifactRoleInferenceContext:
    """Artifact role inference context, independent of raw file extension."""

    artifact_id: str
    extension: str
    media_type: str
    relative_path: str | None = None
    device_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_id, str) or not self.artifact_id:
            raise ValueError('artifact_id must be a non-empty string')
        if not isinstance(self.extension, str) or not self.extension:
            raise ValueError('extension must be a non-empty string')
        if not isinstance(self.media_type, str) or not self.media_type:
            raise ValueError('media_type must be a non-empty string')
        for name in ('relative_path', 'device_id'):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f'{name} must be a non-empty string when supplied')


@runtime_checkable
class ScientificArtifactInferenceProvider(Protocol):
    """Provider-neutral boundary for optional scientific artifact inference."""

    def infer_device_metadata_from_text(
        self, context: DeviceMetadataInferenceContext
    ) -> ScientificArtifactInferenceResult:
        """Suggest device metadata from textual provenance."""

    def infer_device_structure_from_slide(
        self, context: DeviceStructureInferenceContext
    ) -> ScientificArtifactInferenceResult:
        """Suggest device metadata from slide structure."""

    def classify_device_image(
        self, context: DeviceImageInferenceContext
    ) -> ScientificArtifactInferenceResult:
        """Classify a device image."""

    def infer_artifact_role(
        self, context: ArtifactRoleInferenceContext
    ) -> ScientificArtifactInferenceResult:
        """Suggest an artifact role without relying on extension alone."""
