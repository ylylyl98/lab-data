from dataclasses import FrozenInstanceError

import pytest

from lab_data.ai_boundaries import (
    ArtifactRoleInferenceContext,
    DeviceImageInferenceContext,
    DeviceMetadataInferenceContext,
    DeviceStructureInferenceContext,
    EmbeddingProvider,
    EmbeddingVector,
    InferenceEvaluation,
    MetadataInferenceContext,
    MetadataInferenceProvider,
    MetadataInferenceResult,
    ScientificArtifactInferenceProvider,
    ScientificArtifactInferenceResult,
    ScientificInferenceCandidate,
    SearchAgentEvaluation,
)

EXPECTED_INFERRED_TEMPERATURE_K = 4.2


class FirstProvider:
    def infer(self, context):
        return MetadataInferenceResult(
            provider_id='provider-a',
            model_id='model-a',
            suggestions={'temperature_K': 4.2},
            requires_review=True,
            deterministic_validation_passed=False,
            validation_errors=('conflicts with scanner value',),
        )


class SecondProvider:
    def infer(self, context):
        return MetadataInferenceResult(
            provider_id='provider-b',
            model_id='model-b',
            suggestions={},
            abstained=True,
            requires_review=True,
            deterministic_validation_passed=True,
        )


class MockEmbeddingProvider:
    def embed(self, text):
        return EmbeddingVector(
            (1, 2), 'embedding-provider', 'embedding-model', 'space-1'
        )


def test_distinct_providers_share_contract_and_do_not_replace_ground_truth():
    context = MetadataInferenceContext(
        experiment_id='exp-1',
        normalized_metadata={'temperature_K': 3.6},
        source_files=('raw/sample.dat',),
    )
    original = dict(context.normalized_metadata)

    assert isinstance(FirstProvider(), MetadataInferenceProvider)
    assert isinstance(SecondProvider(), MetadataInferenceProvider)
    first = FirstProvider().infer(context)
    second = SecondProvider().infer(context)

    assert first.suggestions['temperature_K'] == EXPECTED_INFERRED_TEMPERATURE_K
    assert second.abstained is True
    assert first.requires_review is True
    assert first.deterministic_validation_passed is False
    assert dict(context.normalized_metadata) == original


def test_inference_result_rejects_unsafe_candidate_states():
    with pytest.raises(ValueError, match='must require review'):
        MetadataInferenceResult('provider-a', 'model-a', {'sample_id': 'D357'})
    with pytest.raises(ValueError, match='cannot contain suggestions'):
        MetadataInferenceResult(
            'provider-a',
            'model-a',
            {'sample_id': 'D357'},
            abstained=True,
            requires_review=True,
        )
    with pytest.raises(ValueError, match='validation_errors'):
        MetadataInferenceResult(
            'provider-a',
            'model-a',
            {},
            deterministic_validation_passed=True,
            validation_errors=('bad',),
        )


def test_contract_objects_are_immutable_and_embedding_is_separate():
    mutable_tags = {'candidate'}
    context = MetadataInferenceContext(
        'exp-1', {'sample_id': 'D356', 'tags': mutable_tags}
    )
    with pytest.raises(FrozenInstanceError):
        context.experiment_id = 'changed'
    mutable_tags.add('changed')
    assert context.normalized_metadata['tags'] == frozenset({'candidate'})
    provider = MockEmbeddingProvider()
    assert isinstance(provider, EmbeddingProvider)
    vector = provider.embed('sample')
    assert vector.provider_id == 'embedding-provider'
    assert vector.model_id == 'embedding-model'
    assert vector.embedding_space_id == 'space-1'
    assert vector.values == (1.0, 2.0)
    for invalid in ((), (True,), (float('nan'),), (float('inf'),), ('1',)):
        with pytest.raises(ValueError, match='finite|at least one'):
            EmbeddingVector(invalid, 'embedding-provider')
    with pytest.raises(ValueError, match='provider_id'):
        EmbeddingVector((1,), '')


def test_evaluation_records_compare_same_benchmark_case_across_providers():
    records = (
        InferenceEvaluation(
            'case-1',
            'provider-a',
            'model-a',
            correctness=True,
            deterministic_validation_passed=True,
            latency_ms=12.0,
            token_count=100,
            cost=0.01,
        ),
        InferenceEvaluation(
            'case-1',
            'provider-b',
            'model-b',
            correctness=None,
            abstained=True,
            requires_review=True,
            deterministic_validation_passed=True,
        ),
    )
    assert {record.benchmark_case_id for record in records} == {'case-1'}
    assert records[0].provider_id != records[1].provider_id
    assert records[1].abstained is True


def test_search_agent_evaluation_is_separate_and_range_validated():
    record = SearchAgentEvaluation(
        'question-1',
        'provider-a',
        'model-a',
        retrieval_correctness=True,
        recall=1.0,
        ranking_quality=0.5,
        interpretation_quality=0.75,
        false_positive_rate=0.0,
        clarification_behavior='none',
        latency_ms=2.0,
        cost=0.01,
    )
    assert record.benchmark_question_id == 'question-1'
    for invalid in ('bad', True, float('nan'), float('inf')):
        with pytest.raises(ValueError, match='between 0 and 1'):
            SearchAgentEvaluation('question-1', 'provider-a', recall=invalid)


class FakeScientificProvider:
    def infer_device_metadata_from_text(self, context):
        return ScientificArtifactInferenceResult(
            provider_id='sci-provider',
            model_id='sci-model',
            task='device_metadata_from_text',
            requires_review=True,
            candidates=(
                ScientificInferenceCandidate(
                    'material', 'Au', confidence=0.6, category='hint'
                ),
            ),
        )

    def infer_device_structure_from_slide(self, context):
        return ScientificArtifactInferenceResult(
            provider_id='sci-provider',
            model_id='sci-model',
            task='device_structure_from_slide',
            abstained=True,
            requires_review=True,
        )

    def classify_device_image(self, context):
        return ScientificArtifactInferenceResult(
            provider_id='sci-provider',
            model_id='sci-model',
            task='classify_device_image',
            requires_review=True,
            candidates=(ScientificInferenceCandidate('device_kind', 'transport'),),
        )

    def infer_artifact_role(self, context):
        return ScientificArtifactInferenceResult(
            provider_id='sci-provider',
            model_id='sci-model',
            task='infer_artifact_role',
            requires_review=True,
            candidates=(ScientificInferenceCandidate('role', 'figure'),),
        )


def test_scientific_provider_conforms_and_returns_reviewable_candidates():
    provider = FakeScientificProvider()
    assert isinstance(provider, ScientificArtifactInferenceProvider)

    text_result = provider.infer_device_metadata_from_text(
        DeviceMetadataInferenceContext('D357', 'Au split gate WSe2')
    )
    assert text_result.task == 'device_metadata_from_text'
    assert text_result.requires_review is True
    assert text_result.candidates[0].field == 'material'
    assert text_result.candidates[0].value == 'Au'

    structure_result = provider.infer_device_structure_from_slide(
        DeviceStructureInferenceContext('D357', 1, title='slide')
    )
    assert structure_result.abstained is True
    assert structure_result.candidates == ()


def test_scientific_result_rejects_unsafe_candidate_states():
    with pytest.raises(ValueError, match='must require review'):
        ScientificArtifactInferenceResult(
            'provider-a',
            'model-a',
            'task',
            candidates=(ScientificInferenceCandidate('field', 'value'),),
        )
    with pytest.raises(ValueError, match='cannot contain candidates'):
        ScientificArtifactInferenceResult(
            'provider-a',
            'model-a',
            'task',
            abstained=True,
            requires_review=True,
            candidates=(ScientificInferenceCandidate('field', 'value'),),
        )


def test_scientific_contexts_are_immutable_and_validated():
    context = DeviceMetadataInferenceContext('D71', 'hello')
    with pytest.raises(FrozenInstanceError):
        context.device_id = 'changed'
    with pytest.raises(ValueError, match='slide_index'):
        DeviceStructureInferenceContext('D71', 0)
    with pytest.raises(ValueError, match='image_reference'):
        DeviceImageInferenceContext('D71', '')
    with pytest.raises(ValueError, match='media_type'):
        ArtifactRoleInferenceContext('art-1', 'png', '')
