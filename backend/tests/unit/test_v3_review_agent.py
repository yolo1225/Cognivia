from __future__ import annotations

import threading
import time

import pytest

from app.agents.contract_examples import initial_generation_flow_example, resource_examples
from app.core.config import settings
from app.agents.contracts import (
    EvidenceVerdict,
    GradedQuizContent,
    ModelReview,
    ReviewCriterionScores,
    ReviewDecision,
    ReviewResourceInput,
    ResourceType,
)
from app.agents.review_agent import (
    OpenAICompatibleReviewChannel,
    ReviewBatchCache,
    ReviewError,
    ReviewValidationAgent,
    build_review_resource_output,
    REVIEW_INPUT_TOKEN_BUDGET,
    _adapt_model_review_payload,
    _build_review_payload,
    _cross_validate,
    _decision_from_claims,
    _deterministic_coverage,
    _merge_evidence,
    _review_decision,
    _reviews_disagree,
    _plan_review_batches,
    _project_claim_source_ids,
    _review_certified_quiz,
    extract_atomic_claims,
)
from app.services.llm_service import ModelCallError, ModelOutputTruncatedError


class DeterministicChannel:
    def review(self, *, deterministic_review, **_kwargs):
        return deterministic_review


def test_arbitration_merge_keeps_full_v8_evidence_budget() -> None:
    chunk = initial_generation_flow_example()["review_resource"]["input"].evidence[0]
    evidence = [
        chunk.model_copy(
            update={
                "chunk_id": f"chunk-{index}",
                "source": chunk.source.model_copy(
                    update={"source_ref_id": f"source-{index}"}
                ),
            }
        )
        for index in range(18)
    ]

    assert len(_merge_evidence(evidence[:12], evidence[12:])) == 18


def test_resource_decision_defers_difficulty_and_coverage_to_package() -> None:
    assert (
        _decision_from_claims(
            contradicted_ids=[],
            undetermined_ids=[],
            unresolved_ids=set(),
        )
        is ReviewDecision.PASSED
    )
    assert (
        _decision_from_claims(
            contradicted_ids=[],
            undetermined_ids=["claim_missing_evidence"],
            unresolved_ids=set(),
        )
        is ReviewDecision.REVISION_REQUIRED
    )


class PersistentConflictChannel:
    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    def review(self, *, role, model, deterministic_review, **_kwargs):
        with self._lock:
            self.calls += 1
        checks = list(deterministic_review.fact_checks)
        if role == "secondary_review_model":
            checks[0] = checks[0].model_copy(
                update={
                    "verdict": EvidenceVerdict.CONTRADICTED,
                    "supported": False,
                    "determinable": True,
                    "reason": "次审核通道认为证据明确冲突。",
                }
            )
        return deterministic_review.model_copy(
            update={"model_role": role, "model_name": model or role, "fact_checks": checks}
        )


def _with_verdicts(deterministic_review, verdict: EvidenceVerdict, source_ids=None):
    checks = [
        check.model_copy(
            update={
                "verdict": verdict,
                "supported": True if verdict is EvidenceVerdict.SUPPORTED else False,
                "determinable": verdict is not EvidenceVerdict.EVIDENCE_INSUFFICIENT,
                "source_ref_ids": (
                    list(source_ids or check.source_ref_ids)
                    if verdict is EvidenceVerdict.SUPPORTED
                    else check.source_ref_ids
                ),
                "reason": f"受控测试结论：{verdict.value}",
            }
        )
        for check in deterministic_review.fact_checks
    ]
    return deterministic_review.model_copy(update={"fact_checks": checks})


class ConsensusContradictionChannel:
    def review(self, *, deterministic_review, **_kwargs):
        return _with_verdicts(deterministic_review, EvidenceVerdict.CONTRADICTED)


class ResolvingConflictChannel:
    def __init__(self) -> None:
        self.claim_counts: list[tuple[bool, int]] = []

    def review(self, *, role, recheck, deterministic_review, resource, **_kwargs):
        self.claim_counts.append((recheck, len(deterministic_review.fact_checks)))
        reviewed = _with_verdicts(
            deterministic_review,
            EvidenceVerdict.SUPPORTED,
            [source.source_ref_id for source in resource.source_refs],
        )
        if not recheck and role == "secondary_review_model":
            checks = list(reviewed.fact_checks)
            checks[0] = checks[0].model_copy(
                update={
                    "verdict": EvidenceVerdict.CONTRADICTED,
                    "supported": False,
                    "reason": "首次审核制造单条 claim 分歧。",
                }
            )
            reviewed = reviewed.model_copy(update={"fact_checks": checks})
        return reviewed


class SupplementalOnlyChannel:
    def __init__(self, supplemental_source_id: str) -> None:
        self.supplemental_source_id = supplemental_source_id

    def review(self, *, role, recheck, deterministic_review, resource, **_kwargs):
        source_ids = (
            [self.supplemental_source_id]
            if recheck
            else [source.source_ref_id for source in resource.source_refs]
        )
        reviewed = _with_verdicts(deterministic_review, EvidenceVerdict.SUPPORTED, source_ids)
        if not recheck and role == "secondary_review_model":
            checks = list(reviewed.fact_checks)
            checks[0] = checks[0].model_copy(
                update={
                    "verdict": EvidenceVerdict.EVIDENCE_INSUFFICIENT,
                    "supported": None,
                    "determinable": False,
                    "source_ref_ids": [],
                    "reason": "首次证据不足。",
                }
            )
            reviewed = reviewed.model_copy(update={"fact_checks": checks})
        return reviewed


class StaticSupplementalRetriever:
    def __init__(self, evidence):
        self.evidence = evidence

    def retrieve(self, **_kwargs):
        return self.evidence


class RecordingBatchChannel:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool, tuple[str, ...]]] = []

    def review(self, *, role, recheck, deterministic_review, **_kwargs):
        self.calls.append(
            (
                role,
                recheck,
                tuple(item.claim_id for item in deterministic_review.fact_checks),
            )
        )
        return deterministic_review


class SplitOnceChannel(RecordingBatchChannel):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def review(self, *, role, recheck, deterministic_review, **kwargs):
        result = super().review(
            role=role,
            recheck=recheck,
            deterministic_review=deterministic_review,
            **kwargs,
        )
        if (
            role == "secondary_review_model"
            and len(deterministic_review.fact_checks) > 1
            and not self.failed
        ):
            self.failed = True
            raise ReviewError("review_output_truncated")
        return result


class FallbackChannel(RecordingBatchChannel):
    def __init__(self) -> None:
        super().__init__()
        self.models: list[tuple[str, str | None]] = []

    def review(self, *, role, model, recheck, deterministic_review, **kwargs):
        self.models.append((role, model))
        self.calls.append(
            (
                role,
                recheck,
                tuple(item.claim_id for item in deterministic_review.fact_checks),
            )
        )
        if model == "slow-primary":
            raise ReviewError("review_model_call_failed")
        return deterministic_review.model_copy(update={"model_name": model or role})


class BoundedConcurrencyChannel:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def review(self, *, deterministic_review, **_kwargs):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.03)
        with self._lock:
            self.active -= 1
        return deterministic_review


def _input() -> ReviewResourceInput:
    request = initial_generation_flow_example()["review_resource"]["input"]
    lecture = next(
        item for item in request.resources if item.resource_type is ResourceType.LECTURE
    )
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.LECTURE],
            "required_knowledge_ids": request.requirements.resource_knowledge_targets[
                ResourceType.LECTURE
            ],
            "resource_knowledge_targets": {
                ResourceType.LECTURE: request.requirements.resource_knowledge_targets[
                    ResourceType.LECTURE
                ]
            },
        }
    )
    return request.model_copy(update={"resources": [lecture], "requirements": requirements})


def test_claim_source_projection_selects_only_relevant_declared_evidence() -> None:
    request = _input()
    evidence = list(request.evidence[:2])
    assert len(evidence) == 2
    first, second = evidence
    source_ids = (first.source.source_ref_id, second.source.source_ref_id)
    evidence_by_source = {item.source.source_ref_id: item for item in evidence}

    selected = _project_claim_source_ids(first.content, source_ids, evidence_by_source)
    unrelated = _project_claim_source_ids(
        "量子色动力学的规范对称性", source_ids, evidence_by_source
    )

    assert selected == (first.source.source_ref_id,)
    assert unrelated == ()


def test_v3_review_emits_dual_model_contract_report() -> None:
    output = ReviewValidationAgent(channel=DeterministicChannel()).execute(_input())

    report = output.reports[0]
    assert output.contract_version == "agent-contract-v9"
    assert report.primary_review.model_role == "primary_review_model"
    assert report.secondary_review.model_role == "secondary_review_model"
    assert report.decision in {ReviewDecision.PASSED, ReviewDecision.REVISION_REQUIRED}
    assert not report.arbitration.required


def test_evidence_not_mentioned_is_undetermined_without_factual_penalty() -> None:
    request = _input()
    unrelated = [
        chunk.model_copy(update={"content": "火星地质样本与本资源没有内容重叠。"})
        for chunk in request.evidence
    ]
    output = ReviewValidationAgent(channel=DeterministicChannel()).execute(
        request.model_copy(update={"evidence": unrelated})
    )

    report = output.reports[0]
    assert report.decision is ReviewDecision.REVISION_REQUIRED
    assert report.final_scores.factual_accuracy == 100
    assert report.final_scores.source_traceability == 0
    assert report.undetermined_claim_ids
    assert not report.contradicted_claim_ids
    assert report.arbitration.required
    assert report.quality_metrics.evaluated_claim_count == sum(
        len(values)
        for values in (
            report.supported_claim_ids,
            report.contradicted_claim_ids,
            report.undetermined_claim_ids,
            report.unresolved_claim_ids,
        )
    )
    assert report.quality_metrics.evidence_insufficient_claim_count == len(
        report.undetermined_claim_ids
    )
    assert report.quality_metrics.hallucination_rate == 0


def test_consensus_contradiction_requires_revision_not_manual_review() -> None:
    report = (
        ReviewValidationAgent(channel=ConsensusContradictionChannel()).execute(_input()).reports[0]
    )

    assert report.decision is ReviewDecision.REVISION_REQUIRED
    assert report.final_scores.factual_accuracy == 0
    assert report.contradicted_claim_ids
    assert report.arbitration.required


def test_resolved_claim_conflict_rechecks_only_the_disputed_claim() -> None:
    channel = ResolvingConflictChannel()
    report = ReviewValidationAgent(channel=channel).execute(_input()).reports[0]

    initial_counts = [count for recheck, count in channel.claim_counts if not recheck]
    recheck_counts = [count for recheck, count in channel.claim_counts if recheck]
    assert len(initial_counts) == 2 and initial_counts[0] > 1
    assert recheck_counts == [1, 1]
    assert report.arbitration.required
    assert not report.arbitration.disagreement_remains
    assert report.decision is ReviewDecision.PASSED


def test_supplemental_only_support_requires_resource_revision_for_citation() -> None:
    request = _input()
    original = request.evidence[0]
    supplemental_source_id = "AIAPP-K029::chunk::supplemental"
    supplemental = original.model_copy(
        update={
            "chunk_id": supplemental_source_id,
            "content": "补充证据明确支持争议事实。",
            "source": original.source.model_copy(update={"source_ref_id": supplemental_source_id}),
        }
    )
    report = (
        ReviewValidationAgent(
            channel=SupplementalOnlyChannel(supplemental_source_id),
            evidence_retriever=StaticSupplementalRetriever([*request.evidence, supplemental]),
        )
        .execute(request)
        .reports[0]
    )

    assert report.arbitration.required
    assert not report.arbitration.disagreement_remains
    assert supplemental_source_id in report.arbitration.additional_source_ref_ids
    assert report.decision is ReviewDecision.REVISION_REQUIRED
    assert report.undetermined_claim_ids


def test_atomic_claim_extraction_is_field_specific_and_excludes_wrong_options() -> None:
    request = _input()
    lecture_claims = extract_atomic_claims(request.resources[0], request)
    assert any(item.field_path.startswith("core_concepts") for item in lecture_claims)
    assert any(item.field_path.startswith("misconceptions") for item in lecture_claims)

    artifacts = resource_examples()
    practice = artifacts[1]
    practice_requirements = request.requirements.model_copy(
        update={
            "resource_types": [practice.resource_type],
            "resource_knowledge_targets": {
                practice.resource_type: request.requirements.required_knowledge_ids
            },
        }
    )
    practice_request = request.model_copy(
        update={"resources": [practice], "requirements": practice_requirements}
    )
    practice_claims = extract_atomic_claims(practice, practice_request)
    assert any(item.field_path.endswith("code_or_command") for item in practice_claims)

    quiz = artifacts[2]
    quiz_content = quiz.structured_content.model_copy(deep=True)
    quiz_content.questions[0].options = ["A. 正确答案", "B. 明显错误选项"]
    quiz = quiz.model_copy(update={"structured_content": quiz_content})
    quiz_requirements = request.requirements.model_copy(
        update={
            "resource_types": [quiz.resource_type],
            "resource_knowledge_targets": {
                quiz.resource_type: request.requirements.required_knowledge_ids
            },
        }
    )
    quiz_request = request.model_copy(
        update={"resources": [quiz], "requirements": quiz_requirements}
    )
    quiz_claims = extract_atomic_claims(quiz, quiz_request)
    assert all("明显错误选项" not in item.claim for item in quiz_claims)
    assert {item.field_path for item in quiz_claims} == {
        f"questions[{index}].{field_name}"
        for index in range(len(quiz_content.questions))
        for field_name in ("correct_answer", "explanation")
    }
    for claim in quiz_claims:
        question_index = int(claim.field_path.split("[", 1)[1].split("]", 1)[0])
        field_name = claim.field_path.rsplit(".", 1)[-1]
        assert getattr(quiz_content.questions[question_index], field_name) in claim.claim


def test_quiz_prompt_excludes_questions_but_keeps_independent_factual_premises() -> None:
    request = _input()
    quiz = resource_examples()[2]
    content = quiz.structured_content.model_copy(deep=True)
    content.questions[0].prompt = "哪一种做法更适合当前任务？"
    content.questions[1].prompt = "系统默认自动重试三次，哪一种说明正确？"
    content.questions[2].prompt = "规范将哪些机制共同列为核心要素？"
    quiz = quiz.model_copy(update={"structured_content": content})
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.GRADED_QUIZ],
            "resource_knowledge_targets": {
                ResourceType.GRADED_QUIZ: request.requirements.required_knowledge_ids
            },
        }
    )
    quiz_request = request.model_copy(
        update={"resources": [quiz], "requirements": requirements}
    )

    paths = {claim.field_path for claim in extract_atomic_claims(quiz, quiz_request)}

    assert "questions[0].prompt" not in paths
    assert "questions[1].prompt" in paths
    assert "questions[2].prompt" not in paths
    assert "questions[0].correct_answer" in paths
    assert "questions[0].explanation" in paths


def test_quiz_prompt_excludes_short_answer_directive_without_question_mark() -> None:
    request = _input()
    quiz = resource_examples()[2]
    content = quiz.structured_content.model_copy(deep=True)
    content.questions[0].prompt = "请概括材料直接说明的关键要点。"
    quiz = quiz.model_copy(update={"structured_content": content})
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.GRADED_QUIZ],
            "resource_knowledge_targets": {
                ResourceType.GRADED_QUIZ: request.requirements.required_knowledge_ids
            },
        }
    )
    quiz_request = request.model_copy(
        update={"resources": [quiz], "requirements": requirements}
    )

    paths = {claim.field_path for claim in extract_atomic_claims(quiz, quiz_request)}

    assert "questions[0].prompt" not in paths
    assert "questions[0].correct_answer" in paths
    assert "questions[0].explanation" in paths


def test_quiz_prompt_does_not_audit_the_unknown_answer_slot_twice() -> None:
    request = _input()
    quiz = resource_examples()[2]
    content = quiz.structured_content.model_copy(deep=True)
    content.questions[0].prompt = (
        "根据引用材料，哪三类内容不应进入 Git 版本库？请列举一项。"
    )
    quiz = quiz.model_copy(update={"structured_content": content})
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.GRADED_QUIZ],
            "resource_knowledge_targets": {
                ResourceType.GRADED_QUIZ: request.requirements.required_knowledge_ids
            },
        }
    )
    quiz_request = request.model_copy(
        update={"resources": [quiz], "requirements": requirements}
    )

    paths = {claim.field_path for claim in extract_atomic_claims(quiz, quiz_request)}

    assert "questions[0].prompt" not in paths
    assert "questions[0].correct_answer" in paths
    assert "questions[0].explanation" in paths


def test_quiz_prompt_does_not_treat_contextual_need_as_an_independent_fact() -> None:
    request = _input()
    quiz = resource_examples()[2]
    content = quiz.structured_content.model_copy(deep=True)
    content.questions[0].prompt = (
        "当多智能体需要协调执行流程时，可采用哪两种控制权交接方式？"
    )
    quiz = quiz.model_copy(update={"structured_content": content})
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.GRADED_QUIZ],
            "resource_knowledge_targets": {
                ResourceType.GRADED_QUIZ: request.requirements.required_knowledge_ids
            },
        }
    )
    quiz_request = request.model_copy(
        update={"resources": [quiz], "requirements": requirements}
    )

    paths = {claim.field_path for claim in extract_atomic_claims(quiz, quiz_request)}

    assert "questions[0].prompt" not in paths
    assert "questions[0].correct_answer" in paths
    assert "questions[0].explanation" in paths


def test_quiz_prompt_excludes_context_clause_with_automatic_review_wording() -> None:
    request = _input()
    quiz = resource_examples()[2]
    content = quiz.structured_content.model_copy(deep=True)
    content.questions[0].prompt = (
        "当评审智能体在自动评审中发现高风险事实时，应采取什么处置动作？"
    )
    quiz = quiz.model_copy(update={"structured_content": content})
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.GRADED_QUIZ],
            "resource_knowledge_targets": {
                ResourceType.GRADED_QUIZ: request.requirements.required_knowledge_ids
            },
        }
    )
    quiz_request = request.model_copy(
        update={"resources": [quiz], "requirements": requirements}
    )

    paths = {claim.field_path for claim in extract_atomic_claims(quiz, quiz_request)}

    assert "questions[0].prompt" not in paths
    assert "questions[0].correct_answer" in paths
    assert "questions[0].explanation" in paths


def test_practice_instruction_excludes_conditional_request_for_reason() -> None:
    request = _input()
    practice = resource_examples()[1]
    content = practice.structured_content.model_copy(deep=True)
    content.steps[0].instruction = (
        "若请求中断，根据幂等性判断是否重试；若不允许，请说明理由。"
    )
    practice = practice.model_copy(update={"structured_content": content})
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.PRACTICE_GUIDE],
            "resource_knowledge_targets": {
                ResourceType.PRACTICE_GUIDE: request.requirements.required_knowledge_ids
            },
        }
    )
    practice_request = request.model_copy(
        update={"resources": [practice], "requirements": requirements}
    )

    paths = {claim.field_path for claim in extract_atomic_claims(practice, practice_request)}

    assert "steps[0].instruction[0]" in paths
    assert "steps[0].instruction[1]" not in paths


def test_summary_excludes_meta_prose_but_preserves_factual_claims_and_ids() -> None:
    request = _input()
    resource = request.resources[0]
    content = resource.structured_content.model_copy(deep=True)
    content.summary = (
        "所有结论均源自所列官方文档。"
        "RAG 资源应保留可追溯的来源引用。"
        "本节将帮助你回顾以上内容。"
    )
    resource = resource.model_copy(update={"structured_content": content})
    request = request.model_copy(update={"resources": [resource]})

    first = extract_atomic_claims(resource, request)
    second = extract_atomic_claims(resource, request)
    summaries = [item for item in first if item.field_path.startswith("summary")]

    assert [item.claim for item in summaries] == ["RAG 资源应保留可追溯的来源引用。"]
    assert summaries[0].field_path == "summary[1]"
    assert [item.claim_id for item in first] == [item.claim_id for item in second]


def test_summary_excludes_provided_knowledge_fragment_meta_variant() -> None:
    request = _input()
    resource = request.resources[0]
    content = resource.structured_content.model_copy(deep=True)
    content.summary = "所有结论均基于所提供知识片段。" "RAG 资源应保留可追溯的来源引用。"
    resource = resource.model_copy(update={"structured_content": content})
    request = request.model_copy(update={"resources": [resource]})

    summaries = [
        item
        for item in extract_atomic_claims(resource, request)
        if item.field_path.startswith("summary")
    ]

    assert [item.claim for item in summaries] == ["RAG 资源应保留可追溯的来源引用。"]


def test_explicit_meta_only_resource_cannot_pass_as_empty_claim_set() -> None:
    request = _input()
    resource = request.resources[0]
    content = resource.structured_content.model_copy(deep=True)
    for concept in content.core_concepts:
        concept.explanation = "所有内容均来自所列官方资料。"
        concept.example = None
    content.misconceptions = []
    content.summary = "本讲义严格基于检索证据。"
    resource = resource.model_copy(update={"structured_content": content})
    request = request.model_copy(update={"resources": [resource]})

    with pytest.raises(ReviewError, match="review_claim_set_empty"):
        extract_atomic_claims(resource, request)


def test_v4_review_rechecks_and_requires_revision_for_persistent_conflict() -> None:
    channel = PersistentConflictChannel()
    output = ReviewValidationAgent(channel=channel).execute(_input())

    report = output.reports[0]
    assert channel.calls == 4
    assert report.arbitration.required
    assert report.arbitration.retrieval_performed
    assert report.arbitration.primary_recheck is not None
    assert report.arbitration.secondary_recheck is not None
    assert report.arbitration.disagreement_remains
    assert report.decision == ReviewDecision.REVISION_REQUIRED
    classified_count = sum(
        len(values)
        for values in (
            report.supported_claim_ids,
            report.contradicted_claim_ids,
            report.undetermined_claim_ids,
            report.unresolved_claim_ids,
        )
    )
    assert report.quality_metrics.evaluated_claim_count == classified_count
    assert report.quality_metrics.hallucinated_claim_count <= classified_count
    assert report.quality_metrics.hallucination_rate == round(
        100 * report.quality_metrics.hallucinated_claim_count / classified_count,
        2,
    )


def test_v3_review_rejects_non_contract_input() -> None:
    with pytest.raises(ReviewError, match="invalid_review_input_type"):
        ReviewValidationAgent(channel=DeterministicChannel()).execute({})  # type: ignore[arg-type]


def test_review_provider_adapter_binds_known_metadata_and_normalizes_aliases() -> None:
    payload = _adapt_model_review_payload(
        {
            "review_scores": {
                "accuracy": 95,
                "traceability": 93,
                "difficulty": 90,
                "coverage": 91,
            },
            "passed": True,
            "fact_checks": [
                {
                    "claim": "证据支持该结论",
                    "is_supported": True,
                    "source_ref_ids": "AIAPP-K001::source::0",
                    "reason": "来源直接说明。",
                }
            ],
        },
        role="primary_review_model",
        model_name="qwen-max",
    )
    review = ModelReview.model_validate(payload)

    assert review.model_role == "primary_review_model"
    assert review.model_name == "qwen-max"
    assert review.scores.factual_accuracy == 95
    assert review.fact_checks[0].source_ref_ids == ["AIAPP-K001::source::0"]


def test_unsupported_determinable_fact_cannot_pass_even_with_perfect_scores() -> None:
    request = _input()
    # Build against the frozen example's valid sources so this isolates the model
    # channel's explicit negative fact conclusion from deterministic score checks.
    deterministic = ReviewValidationAgent(channel=DeterministicChannel())._review_pair(
        request.resources[0], request, recheck=False
    )[0]
    checks = list(deterministic.fact_checks)
    checks[0] = checks[0].model_copy(
        update={
            "verdict": EvidenceVerdict.CONTRADICTED,
            "supported": False,
            "determinable": True,
            "reason": "证据明确给出了相反结论。",
        }
    )
    reviewed = deterministic.model_copy(
        update={
            "scores": ReviewCriterionScores(
                factual_accuracy=100,
                source_traceability=100,
                difficulty_match=100,
                core_knowledge_coverage=100,
            ),
            "passed": True,
            "fact_checks": checks,
        }
    )

    validated = _cross_validate(reviewed, deterministic, request)

    assert not validated.passed
    assert validated.scores.factual_accuracy < 85
    assert any(issue.code.value == "contradicted_claim" for issue in validated.issues)


def test_supported_model_verdict_restores_canonical_source_ids_when_omitted() -> None:
    request = _input()
    deterministic = ReviewValidationAgent(channel=DeterministicChannel())._review_pair(
        request.resources[0], request, recheck=False
    )[0]
    first = deterministic.fact_checks[0]
    reviewed = deterministic.model_copy(
        update={
            "fact_checks": [
                check.model_copy(update={"source_ref_ids": []})
                if check.claim_id == first.claim_id
                else check
                for check in deterministic.fact_checks
            ]
        }
    )

    validated = _cross_validate(reviewed, deterministic, request)
    restored = next(
        check for check in validated.fact_checks if check.claim_id == first.claim_id
    )

    assert restored.verdict is EvidenceVerdict.SUPPORTED
    assert restored.source_ref_ids == first.source_ref_ids


def test_exact_command_literal_overrides_model_contradiction() -> None:
    request = _input()
    practice = resource_examples()[1]
    content = practice.structured_content.model_copy(deep=True)
    content.steps[0].code_or_command = "RAG 检索需要保留知识片段与来源标识"
    practice = practice.model_copy(update={"structured_content": content})
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.PRACTICE_GUIDE],
            "resource_knowledge_targets": {
                ResourceType.PRACTICE_GUIDE: request.requirements.required_knowledge_ids
            },
        }
    )
    practice_request = request.model_copy(
        update={"resources": [practice], "requirements": requirements}
    )
    canonical, _ = ReviewValidationAgent(channel=DeterministicChannel())._review_pair(
        practice,
        practice_request,
        recheck=False,
    )
    code_check = next(
        check for check in canonical.fact_checks if check.field_path.endswith(".code_or_command")
    )
    contradicted = canonical.model_copy(
        update={
            "fact_checks": [
                check.model_copy(update={"verdict": EvidenceVerdict.CONTRADICTED})
                if check.claim_id == code_check.claim_id
                else check
                for check in canonical.fact_checks
            ]
        }
    )

    validated = _cross_validate(contradicted, canonical, practice_request)

    result = next(check for check in validated.fact_checks if check.claim_id == code_check.claim_id)
    assert result.verdict is EvidenceVerdict.SUPPORTED
    assert result.source_ref_ids == code_check.source_ref_ids


def test_unsupported_fact_difference_requires_arbitration_and_never_passes() -> None:
    request = _input()
    primary, secondary = ReviewValidationAgent(channel=DeterministicChannel())._review_pair(
        request.resources[0], request, recheck=False
    )
    canonical_primary = primary
    checks = list(primary.fact_checks)
    checks[0] = checks[0].model_copy(
        update={
            "verdict": EvidenceVerdict.CONTRADICTED,
            "supported": False,
            "determinable": True,
            "reason": "证据明确给出了相反结论。",
        }
    )
    primary = _cross_validate(
        primary.model_copy(update={"fact_checks": checks, "passed": True}),
        canonical_primary,
        request,
    )

    assert _reviews_disagree(primary, secondary)
    decision = _review_decision(
        primary,
        secondary,
        primary.scores,
        disagreement_remains=False,
    )
    assert decision != ReviewDecision.PASSED


def test_v3_review_module_has_no_legacy_dependency() -> None:
    imported = __import__("app.agents.review_agent", fromlist=["*"])
    source = __import__("inspect").getsource(imported)
    assert "legacy_contracts" not in source
    assert "legacy_state" not in source


def test_review_payload_excludes_markdown_duplicate_and_keeps_structure() -> None:
    request = _input()
    resource = request.resources[0].model_copy(update={"content_md": "重复正文" * 20_000})
    compact_request = request.model_copy(update={"resources": [resource]})

    payload, tokens, truncated = _build_review_payload(
        role="primary_review_model",
        recheck=False,
        resource=resource,
        request=compact_request,
    )

    assert "content_md" not in payload["resource"]
    assert payload["resource"]["structured_content"]
    assert tokens <= REVIEW_INPUT_TOKEN_BUDGET
    assert truncated == 0


def test_review_payload_uses_minimum_provider_output_schema() -> None:
    request = _input()
    payload, _, _ = _build_review_payload(
        role="primary_review_model",
        recheck=False,
        resource=request.resources[0],
        request=request,
    )

    schema = payload["output_schema"]
    assert set(schema["properties"]) == {"fact_checks"}
    check_schema = schema["$defs"]["_CompactFactCheck"]
    assert set(check_schema["properties"]) == {
        "claim_id",
        "verdict",
        "source_ref_ids",
    }
    assert "content_md" not in str(payload)


class _FailingReviewGateway:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def complete_json(self, **_kwargs):
        raise self.error


@pytest.mark.parametrize(
    ("gateway_error", "expected_code"),
    [
        (
            ModelOutputTruncatedError(
                "truncated",
                metadata={"model_name": "test", "provider_mode": "live"},
            ),
            "review_output_truncated",
        ),
        (
            ModelCallError(
                "timeout",
                metadata={"model_name": "test", "provider_mode": "live"},
            ),
            "review_model_call_failed",
        ),
    ],
)
def test_review_preserves_model_failure_codes(gateway_error, expected_code) -> None:
    channel = OpenAICompatibleReviewChannel(_FailingReviewGateway(gateway_error))

    with pytest.raises(ReviewError, match=expected_code):
        ReviewValidationAgent(channel=channel).execute(_input())


def test_review_payload_dynamically_trims_cited_evidence_without_mutation() -> None:
    request = _input()
    original = request.evidence[0]
    long_content = "检索证据内容" * 5_000
    long_evidence = original.model_copy(update={"content": long_content})
    long_request = request.model_copy(update={"evidence": [long_evidence]})

    payload, tokens, truncated = _build_review_payload(
        role="secondary_review_model",
        recheck=False,
        resource=request.resources[0],
        request=long_request,
    )

    assert tokens <= REVIEW_INPUT_TOKEN_BUDGET
    assert truncated == 1
    assert payload["evidence"][0]["evidence_truncated"] is True
    assert len(payload["evidence"][0]["content"]) < len(long_content)
    assert long_request.evidence[0].content == long_content


def test_review_payload_canonicalizes_large_structured_text_without_mutation() -> None:
    request = _input()
    resource = resource_examples()[0]
    content = resource.structured_content.model_copy(deep=True)
    content.core_concepts[0].explanation = "超长结构化正文" * 20_000
    oversized = resource.model_copy(update={"structured_content": content})
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [oversized.resource_type],
            "resource_knowledge_targets": {
                oversized.resource_type: request.requirements.required_knowledge_ids
            },
        }
    )
    oversized_request = request.model_copy(
        update={"resources": [oversized], "requirements": requirements}
    )

    batches = _plan_review_batches(
        resource=oversized,
        request=oversized_request,
        recheck=False,
    )
    assert len(batches) > 1
    for batch in batches:
        payload, tokens, _ = _build_review_payload(
            role="primary_review_model",
            recheck=False,
            resource=oversized,
            request=oversized_request,
            claim_ids=set(batch.claim_ids),
        )
        assert tokens <= REVIEW_INPUT_TOKEN_BUDGET
        assert payload["resource"]["content_representation"] == (
            "canonical_claims_with_structural_outline"
        )
        assert "超长结构化正文" not in str(payload["resource"]["structured_content"])
    assert oversized.structured_content.core_concepts[0].explanation.startswith("超长结构化正文")


def test_oversized_claim_is_split_without_text_loss_and_ids_are_stable() -> None:
    request = _input()
    resource = resource_examples()[0]
    content = resource.structured_content.model_copy(deep=True)
    original = "超长事实片段" * 1_200
    content.core_concepts[0].explanation = original
    oversized = resource.model_copy(update={"structured_content": content})

    first = extract_atomic_claims(oversized, request)
    second = extract_atomic_claims(oversized, request)
    fragments = [
        claim for claim in first if claim.field_path.startswith("core_concepts[0].explanation")
    ]

    assert len(fragments) > 1
    assert "".join(claim.claim for claim in fragments) == original
    assert all(len(claim.claim) <= 1900 for claim in fragments)
    assert [claim.claim_id for claim in first] == [claim.claim_id for claim in second]


def test_batch_outline_contains_only_items_referenced_by_batch_claims() -> None:
    request = _long_practice_input()
    resource = request.resources[0]
    claim = next(
        item
        for item in extract_atomic_claims(resource, request)
        if item.field_path.startswith("steps[4]")
    )

    payload, tokens, _ = _build_review_payload(
        role="primary_review_model",
        recheck=False,
        resource=resource,
        request=request,
        claim_ids={claim.claim_id},
    )

    assert tokens <= settings.review_batch_hard_input_tokens
    assert len(payload["resource"]["structured_content"]["steps"]) == 1
    assert payload["resource"]["structured_content"]["steps"][0]["title"] == "稳定批次步骤 4"


def test_evidence_projection_prefers_claim_relevant_sentences() -> None:
    request = _input()
    resource = request.resources[0]
    claim = extract_atomic_claims(resource, request)[0]
    original = next(
        item for item in request.evidence if item.source.source_ref_id in claim.source_ref_ids
    )
    content = ("无关背景材料。" * 500) + f"关键证据明确说明：{claim.claim}。"
    projected_request = request.model_copy(
        update={"evidence": [original.model_copy(update={"content": content})]}
    )

    payload, _, truncated = _build_review_payload(
        role="primary_review_model",
        recheck=False,
        resource=resource,
        request=projected_request,
        claim_ids={claim.claim_id},
        input_token_budget=1800,
    )

    assert truncated == 1
    assert claim.claim in payload["evidence"][0]["content"]


def test_recheck_caps_supplemental_evidence_without_dropping_declared_sources() -> None:
    request = _input()
    resource = request.resources[0]
    claim = extract_atomic_claims(resource, request)[0]
    declared = next(
        item for item in request.evidence if item.source.source_ref_id in claim.source_ref_ids
    )
    supplemental = [
        declared.model_copy(
            update={
                "chunk_id": f"supplemental::{index}",
                "content": ("补充复核证据。" * 1_000) + claim.claim,
                "source": declared.source.model_copy(
                    update={"source_ref_id": f"supplemental::{index}"}
                ),
            }
        )
        for index in range(12)
    ]
    recheck_request = request.model_copy(update={"evidence": [declared, *supplemental]})

    payload, tokens, _ = _build_review_payload(
        role="primary_review_model",
        recheck=True,
        resource=resource,
        request=recheck_request,
        claim_ids={claim.claim_id},
    )

    roles = [item["evidence_role"] for item in payload["evidence"]]
    assert tokens <= settings.review_batch_hard_input_tokens
    assert roles.count("declared") == 1
    assert roles.count("supplemental") == 4
    assert payload["evidence"][0]["source"]["source_ref_id"] in claim.source_ref_ids


def test_verdict_adapter_normalizes_only_unambiguous_aliases() -> None:
    payload = {
        "fact_checks": [
            {"claim_id": "clm_supported_001", "verdict": "  SUPPORTED  ", "source_ref_ids": []},
            {"claim_id": "clm_unknown_0001", "verdict": "unsupported", "source_ref_ids": []},
        ]
    }

    adapted = _adapt_model_review_payload(payload, role="secondary_review_model", model_name="test")

    assert adapted["fact_checks"][0]["verdict"] == "supported"
    assert adapted["fact_checks"][1]["verdict"] == "unsupported"


def test_review_adapter_safely_normalizes_source_reference_shapes() -> None:
    payload = {
        "fact_checks": [
            {
                "claim_id": "clm_no_sources_001",
                "verdict": "evidence_insufficient",
                "source_ref_ids": None,
            },
            {
                "claim_id": "clm_mixed_sources_01",
                "verdict": "supported",
                "source_ref_ids": [
                    " source::1 ",
                    {"source_ref_id": "source::2"},
                    "source::1",
                    None,
                    {"title": "not-a-source-id"},
                ],
            },
        ]
    }

    adapted = _adapt_model_review_payload(payload, role="primary_review_model", model_name="test")

    assert adapted["fact_checks"][0]["source_ref_ids"] == []
    assert adapted["fact_checks"][1]["source_ref_ids"] == [
        "source::1",
        "source::2",
    ]


def _long_practice_input() -> ReviewResourceInput:
    request = _input()
    practice = resource_examples()[1]
    content = practice.structured_content.model_copy(deep=True)
    template = content.steps[0]
    content.environment_requirements = ["准备一个受控测试环境"]
    content.acceptance_criteria = ["全部步骤成功", "输出符合预期"]
    content.steps = [
        template.model_copy(
            update={
                "title": f"稳定批次步骤 {index}",
                "instruction": f"执行第 {index} 个受控操作并核对输入输出。",
                "expected_result": f"第 {index} 个操作返回预期结果。",
                "troubleshooting": f"若第 {index} 个操作失败，检查对应配置。",
            }
        )
        for index in range(9)
    ]
    practice = practice.model_copy(update={"structured_content": content})
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [practice.resource_type],
            "resource_knowledge_targets": {
                practice.resource_type: request.requirements.required_knowledge_ids
            },
        }
    )
    return request.model_copy(update={"resources": [practice], "requirements": requirements})


def test_pedagogical_actions_are_excluded_but_mixed_technical_claims_remain() -> None:
    request = _input()
    practice = resource_examples()[1]
    content = practice.structured_content.model_copy(deep=True)
    template = content.steps[0]
    content.steps = [
        template.model_copy(
            update={
                "instruction": "记录结果，接口将在 30 秒后自动重试三次。",
                "expected_result": "记录实际结果并与引用材料中的描述进行核对。",
            }
        ),
        template.model_copy(
            update={
                "instruction": "阅读材料并比较两种方案的差异。",
                "expected_result": "形成一份对比记录。",
                "code_or_command": None,
                "troubleshooting": None,
            }
        ),
        template.model_copy(
            update={
                "instruction": "完成练习。",
                "expected_result": "接口返回固定 JSON 字段。",
                "code_or_command": None,
                "troubleshooting": None,
            }
        ),
        template.model_copy(
            update={
                "instruction": "阅读引用材料，整理其中明确描述的处理流程。",
                "expected_result": "记录实际结果并与引用材料中的描述进行核对。",
                "code_or_command": None,
                "troubleshooting": None,
            }
        ),
    ]
    practice = practice.model_copy(update={"structured_content": content})
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.PRACTICE_GUIDE],
            "resource_knowledge_targets": {
                ResourceType.PRACTICE_GUIDE: request.requirements.required_knowledge_ids
            },
        }
    )
    practice_request = request.model_copy(
        update={"resources": [practice], "requirements": requirements}
    )

    paths = {claim.field_path for claim in extract_atomic_claims(practice, practice_request)}

    assert "steps[0].instruction[0]" in paths
    assert "steps[0].expected_result[0]" not in paths
    assert "steps[1].instruction[0]" not in paths
    assert "steps[1].expected_result[0]" not in paths
    assert "steps[2].instruction[0]" not in paths
    assert "steps[2].expected_result[0]" in paths
    assert "steps[3].instruction[0]" not in paths
    assert "steps[3].expected_result[0]" not in paths


def test_operational_pedagogical_step_counts_toward_practice_coverage() -> None:
    request = _input()
    practice = resource_examples()[1]
    chunk = request.evidence[0].model_copy(
        update={"content": "## 操作步骤\n1. 记录目标服务实际响应字段并整理来源。"}
    )
    content = practice.structured_content.model_copy(deep=True)
    content.steps = [
        content.steps[0].model_copy(
            update={
                "instruction": "记录目标服务实际响应字段并整理来源。",
                "source_ref_ids": [chunk.source.source_ref_id],
                "code_or_command": None,
                "expected_result": "记录实际结果并与引用材料中的描述进行核对。",
                "troubleshooting": None,
            }
        )
    ]
    practice = practice.model_copy(
        update={
            "structured_content": content,
            "source_refs": [chunk.source],
            "knowledge_coverage": {
                chunk.knowledge_id: [chunk.source.source_ref_id]
            },
        }
    )
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.PRACTICE_GUIDE],
            "required_knowledge_ids": [chunk.knowledge_id],
            "resource_knowledge_targets": {
                ResourceType.PRACTICE_GUIDE: [chunk.knowledge_id]
            },
            "source_whitelist": [chunk.source.source_ref_id],
        }
    )
    practice_request = request.model_copy(
        update={
            "resources": [practice],
            "requirements": requirements,
            "evidence": [chunk],
        }
    )

    targets, covered = _deterministic_coverage(practice, practice_request)

    assert targets == {chunk.knowledge_id}
    assert covered == targets


def test_practice_environment_and_acceptance_actions_are_not_factual_claims() -> None:
    request = _input()
    practice = resource_examples()[1]
    content = practice.structured_content.model_copy(deep=True)
    content.environment_requirements = [
        "可访问目标 API 文档以核对响应结构与契约要求",
        "请确保不暴露真实凭证或敏感数据",
        "API 默认 30 秒超时",
    ]
    content.acceptance_criteria = [
        "学习者记录 Python 脚本运行结果，并对照 Python 官方文档核对其行为",
        "学习者提交练习记录并标注引用材料",
        "命令固定返回 JSON 字段",
        "错误响应分析包含 request_id 提取过程及识别依据",
        "在清单旁注明所识别出的至少一处可量化指标示例和一处失败样例反馈路径描述",
        "在清单旁注明接口固定返回 JSON 字段",
    ]
    practice = practice.model_copy(update={"structured_content": content})
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.PRACTICE_GUIDE],
            "resource_knowledge_targets": {
                ResourceType.PRACTICE_GUIDE: request.requirements.required_knowledge_ids
            },
        }
    )
    practice_request = request.model_copy(
        update={"resources": [practice], "requirements": requirements}
    )

    claims = extract_atomic_claims(practice, practice_request)
    claims_by_path = {claim.field_path: claim.claim for claim in claims}

    assert "environment_requirements[0][0]" not in claims_by_path
    assert "environment_requirements[1][0]" not in claims_by_path
    assert "acceptance_criteria[0][0]" not in claims_by_path
    assert "acceptance_criteria[1][0]" not in claims_by_path
    assert claims_by_path["environment_requirements[2][0]"] == "API 默认 30 秒超时"
    assert claims_by_path["acceptance_criteria[2][0]"] == "命令固定返回 JSON 字段"
    assert "acceptance_criteria[3][0]" not in claims_by_path
    assert "acceptance_criteria[4][0]" not in claims_by_path
    assert claims_by_path["acceptance_criteria[5][0]"] == "在清单旁注明接口固定返回 JSON 字段"


def test_practice_compound_observation_and_summary_actions_are_not_split_as_facts() -> None:
    request = _input()
    practice = resource_examples()[1]
    content = practice.structured_content.model_copy(deep=True)
    content.steps[0].expected_result = "记录实际收到的响应结构；与文档中声明的响应格式进行比对。"
    content.acceptance_criteria = [
        "总结 asyncio 事件循环调度机制的核心要点：await 触发挂起、事件循环恢复协程"
    ]
    practice = practice.model_copy(update={"structured_content": content})
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.PRACTICE_GUIDE],
            "resource_knowledge_targets": {
                ResourceType.PRACTICE_GUIDE: request.requirements.required_knowledge_ids
            },
        }
    )
    practice_request = request.model_copy(
        update={"resources": [practice], "requirements": requirements}
    )

    paths = {claim.field_path for claim in extract_atomic_claims(practice, practice_request)}

    assert not any(path.startswith("steps[0].expected_result") for path in paths)
    assert not any(path.startswith("acceptance_criteria[0]") for path in paths)


def test_workflow_mapping_and_learning_record_are_pedagogical_actions() -> None:
    request = _input()
    practice = resource_examples()[1]
    content = practice.structured_content.model_copy(deep=True)
    content.steps[0].instruction = (
        "将前序步骤中的 API 调用行为映射至流程清单中的具体环节，"
        "说明该动作在任务定义、知识准备、模型接入、编排、输出校验、"
        "离线评测或运行监控等环节中的定位，并明确其输入、输出、"
        "可观察结果及失败处理方式。"
    )
    content.acceptance_criteria = [
        "完成一份学习记录，包含所列七个环节的简要说明及对应来源核对结论"
    ]
    practice = practice.model_copy(update={"structured_content": content})
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.PRACTICE_GUIDE],
            "resource_knowledge_targets": {
                ResourceType.PRACTICE_GUIDE: request.requirements.required_knowledge_ids
            },
        }
    )
    practice_request = request.model_copy(
        update={"resources": [practice], "requirements": requirements}
    )

    paths = {claim.field_path for claim in extract_atomic_claims(practice, practice_request)}

    assert "steps[0].instruction[0]" not in paths
    assert "acceptance_criteria[0][0]" not in paths


def test_realistic_regression_shapes_extract_20_38_12_claims() -> None:
    request = _input()
    lecture, _, quiz = resource_examples()
    lecture_content = lecture.structured_content.model_copy(deep=True)
    concept = lecture_content.core_concepts[0]
    lecture_content.core_concepts = [
        concept.model_copy(
            update={
                "title": f"概念 {index}",
                "explanation": f"概念 {index} 的证据约束解释。",
                "example": f"概念 {index} 的受控示例。",
            }
        )
        for index in range(9)
    ]
    lecture_content.misconceptions = lecture_content.misconceptions[:1]
    lecture_content.summary = "总结受控证据范围。"
    lecture = lecture.model_copy(update={"structured_content": lecture_content})

    practice_request = _long_practice_input()
    quiz_content = quiz.structured_content.model_copy(deep=True)
    question = quiz_content.questions[0]
    quiz_content.questions = [
        question.model_copy(
            update={
                "prompt": f"第 {index} 题应如何判断？",
                "correct_answer": f"第 {index} 题正确答案",
                "explanation": f"第 {index} 题证据解析",
            }
        )
        for index in range(6)
    ]
    quiz = quiz.model_copy(update={"structured_content": quiz_content})

    assert len(extract_atomic_claims(lecture, request)) == 19
    assert len(extract_atomic_claims(practice_request.resources[0], practice_request)) == 38
    assert len(extract_atomic_claims(quiz, request)) == 12


def test_long_practice_uses_stable_budgeted_batches_for_both_models() -> None:
    request = _long_practice_input()
    resource = request.resources[0]
    assert len(extract_atomic_claims(resource, request)) == 38
    batches = _plan_review_batches(
        resource=resource,
        request=request,
        recheck=False,
    )

    assert len(batches) >= 3
    assert all(len(batch.claim_ids) <= 12 for batch in batches)
    for batch in batches:
        primary, primary_tokens, _ = _build_review_payload(
            role="primary_review_model",
            recheck=False,
            resource=resource,
            request=request,
            claim_ids=set(batch.claim_ids),
        )
        secondary, secondary_tokens, _ = _build_review_payload(
            role="secondary_review_model",
            recheck=False,
            resource=resource,
            request=request,
            claim_ids=set(batch.claim_ids),
        )
        assert primary["canonical_claims"] == secondary["canonical_claims"]
        assert primary["evidence"] == secondary["evidence"]
        assert primary_tokens <= 5000 and secondary_tokens <= 5000

    channel = RecordingBatchChannel()
    ReviewValidationAgent(channel=channel).execute(request)
    primary_calls = [
        ids
        for role, recheck, ids in channel.calls
        if role == "primary_review_model" and not recheck
    ]
    secondary_calls = [
        ids
        for role, recheck, ids in channel.calls
        if role == "secondary_review_model" and not recheck
    ]
    expected = {batch.claim_ids for batch in batches}
    assert len(primary_calls) == len(secondary_calls) == len(batches)
    assert set(primary_calls) == set(secondary_calls) == expected
    assert any(recheck for _role, recheck, _ids in channel.calls)


def test_review_batches_run_in_bounded_parallel_pairs() -> None:
    channel = BoundedConcurrencyChannel()

    ReviewValidationAgent(channel=channel).execute(_long_practice_input())

    assert 2 < channel.max_active <= settings.review_model_concurrency


def test_initial_review_projects_only_claim_declared_evidence() -> None:
    request = _input()
    resource = request.resources[0]
    claim = extract_atomic_claims(resource, request)[0]
    original = request.evidence[0]
    unrelated_source = "AIAPP-K999::chunk::unrelated"
    unrelated = original.model_copy(
        update={
            "chunk_id": unrelated_source,
            "knowledge_id": "AIAPP-K999",
            "source": original.source.model_copy(update={"source_ref_id": unrelated_source}),
        }
    )
    expanded = request.model_copy(update={"evidence": [*request.evidence, unrelated]})

    payload, _, _ = _build_review_payload(
        role="primary_review_model",
        recheck=False,
        resource=resource,
        request=expanded,
        claim_ids={claim.claim_id},
    )
    evidence_ids = {item["source"]["source_ref_id"] for item in payload["evidence"]}

    assert unrelated_source not in evidence_ids
    assert evidence_ids == set(claim.source_ref_ids)


def test_truncated_batch_is_split_without_restarting_the_resource() -> None:
    request = _long_practice_input()
    channel = SplitOnceChannel()

    output = ReviewValidationAgent(channel=channel).execute(request)

    assert output.reports
    assert channel.failed
    assert any(len(ids) < 12 for _, _, ids in channel.calls)


def test_completed_review_batches_are_reused_without_model_calls() -> None:
    request = _long_practice_input()
    cache = ReviewBatchCache()
    first_channel = RecordingBatchChannel()
    ReviewValidationAgent(channel=first_channel, batch_cache=cache).execute(request)
    first_count = len(first_channel.calls)

    second_channel = RecordingBatchChannel()
    ReviewValidationAgent(channel=second_channel, batch_cache=cache).execute(request)

    assert first_count > 0
    assert second_channel.calls == []
    snapshot = cache.snapshot()
    assert snapshot["entry_count"] == first_count
    assert snapshot["hits"] == first_count
    assert set(snapshot["entries"][0]["fact_checks"][0]) == {
        "claim_id",
        "verdict",
        "source_ref_ids",
    }


def test_failed_primary_batch_uses_independent_fallback_model(monkeypatch) -> None:
    channel = FallbackChannel()
    monkeypatch.setattr(settings, "primary_review_model", "slow-primary")
    monkeypatch.setattr(settings, "primary_review_fallback_model", "fast-primary")
    monkeypatch.setattr(settings, "secondary_review_model", "stable-secondary")
    monkeypatch.setattr(settings, "secondary_review_fallback_model", None)

    report = ReviewValidationAgent(channel=channel).execute(_input()).reports[0]

    assert report.primary_review.model_name == "fast-primary"
    assert report.secondary_review.model_name == "stable-secondary"
    assert ("primary_review_model", "slow-primary") in channel.models
    assert ("primary_review_model", "fast-primary") in channel.models
    assert ("secondary_review_model", "stable-secondary") in channel.models


def test_package_quality_uses_weighted_counts_after_partial_revision() -> None:
    flow = initial_generation_flow_example()
    base_reports = flow["review_resource"]["output"].reports
    claim_counts = [14, 41, 6]
    hallucinated_counts = [0, 12, 0]
    reports = []
    for index, report in enumerate(base_reports):
        hallucinated = hallucinated_counts[index]
        metrics = report.quality_metrics.model_copy(
            update={
                "evaluated_claim_count": claim_counts[index],
                "verifiable_claim_count": claim_counts[index],
                "contradicted_claim_count": hallucinated,
                "hallucinated_claim_count": hallucinated,
                "hallucination_rate": round(100 * hallucinated / claim_counts[index], 2),
                "difficulty_match_score": 100,
                "passed": hallucinated == 0,
                "revision_count": 1,
            }
        )
        reports.append(
            report.model_copy(
                update={
                    "quality_metrics": metrics,
                    "decision": (
                        ReviewDecision.PASSED
                        if hallucinated == 0
                        else ReviewDecision.REVISION_REQUIRED
                    ),
                    "passed": hallucinated == 0,
                }
            )
        )

    output = build_review_resource_output(
        task_id=flow["review_resource"]["output"].task_id,
        reports=reports,
        required_knowledge_ids=flow[
            "review_resource"
        ]["input"].requirements.required_knowledge_ids,
        revision_count=1,
    )

    assert output.package_quality.verifiable_claim_count == 55
    assert output.package_quality.hallucinated_claim_count == 12
    assert output.package_quality.hallucination_rate == 21.82
    assert output.package_quality.difficulty_match_score == 100
    assert output.package_quality.revision_count == 1
    assert not output.package_quality.passed
    assert not output.package_passed


def test_certified_quiz_uses_deterministic_suitability_review() -> None:
    flow = initial_generation_flow_example()
    request = flow["review_resource"]["input"]
    quiz = next(
        resource
        for resource in request.resources
        if resource.resource_type is ResourceType.GRADED_QUIZ
    )
    for question in quiz.structured_content.questions:
        question.reference_question_ids = [question.question_id]

    report = _review_certified_quiz(quiz, request)

    assert report.passed
    assert report.primary_review.model_name == "deterministic-certified-question-validator"
    assert report.secondary_review.model_name == "deterministic-certified-question-validator"
    assert not report.arbitration.required
    assert report.quality_metrics.hallucination_rate == 0
    assert all("correct_answer" not in (check.field_path or "") for check in report.primary_review.fact_checks)


def test_certified_quiz_allows_three_question_single_level_package() -> None:
    flow = initial_generation_flow_example()
    request = flow["review_resource"]["input"]
    quiz = next(
        resource
        for resource in request.resources
        if resource.resource_type is ResourceType.GRADED_QUIZ
    )
    assert isinstance(quiz.structured_content, GradedQuizContent)
    questions = [
        question.model_copy(update={"reference_question_ids": [question.question_id]})
        for question in quiz.structured_content.questions[:3]
    ]
    target_id = questions[0].knowledge_id
    short_quiz = quiz.model_copy(
        update={"structured_content": quiz.structured_content.model_copy(update={"questions": questions})}
    )
    short_request = request.model_copy(
        update={
            "requirements": request.requirements.model_copy(
                update={
                    "resource_knowledge_targets": {
                        ResourceType.GRADED_QUIZ: [target_id]
                    }
                }
            )
        }
    )

    report = _review_certified_quiz(short_quiz, short_request)

    assert report.passed
    assert report.decision is ReviewDecision.PASSED


@pytest.mark.parametrize("resource_count", [1, 2, 3])
def test_package_quality_accepts_exact_requested_resource_set(resource_count: int) -> None:
    flow = initial_generation_flow_example()
    reports = flow["review_resource"]["output"].reports[:resource_count]

    output = build_review_resource_output(
        task_id="task_partial_refresh",
        reports=reports,
        expected_resource_types=[report.resource_type for report in reports],
        required_knowledge_ids=sorted(
            {knowledge_id for report in reports for knowledge_id in report.target_knowledge_ids}
        ),
        revision_count=0,
    )

    assert output.package_quality.passed
    assert output.package_passed


def test_quiz_assessment_cannot_backfill_primary_teaching_coverage() -> None:
    flow = initial_generation_flow_example()
    lecture = flow["review_resource"]["output"].reports[0]
    quiz = flow["review_resource"]["output"].reports[2]
    knowledge_id = lecture.target_knowledge_ids[0]
    lecture = lecture.model_copy(
        update={
            "target_knowledge_ids": [knowledge_id],
            "covered_knowledge_ids": [],
            "missing_knowledge_ids": [knowledge_id],
        }
    )
    quiz = quiz.model_copy(
        update={
            "target_knowledge_ids": [knowledge_id],
            "covered_knowledge_ids": [knowledge_id],
            "missing_knowledge_ids": [],
        }
    )

    output = build_review_resource_output(
        task_id="task_primary_owner",
        reports=[lecture, quiz],
        expected_resource_types=[ResourceType.LECTURE, ResourceType.GRADED_QUIZ],
        required_knowledge_ids=[knowledge_id],
        revision_count=0,
    )

    assert output.package_covered_knowledge_ids == []
    assert output.package_missing_knowledge_ids == [knowledge_id]
    assert output.package_quality.core_knowledge_coverage == 0
    assert not output.package_passed


def test_teaching_coverage_uses_lecture_and_practice_union() -> None:
    flow = initial_generation_flow_example()
    lecture = flow["review_resource"]["output"].reports[0]
    practice = flow["review_resource"]["output"].reports[1]
    knowledge_ids = lecture.target_knowledge_ids[:1]
    lecture = lecture.model_copy(
        update={
            "target_knowledge_ids": knowledge_ids,
            "covered_knowledge_ids": knowledge_ids,
            "missing_knowledge_ids": [],
        }
    )
    practice = practice.model_copy(
        update={
            "target_knowledge_ids": knowledge_ids,
            "covered_knowledge_ids": [],
            "missing_knowledge_ids": knowledge_ids,
        }
    )

    output = build_review_resource_output(
        task_id="task_teaching_union",
        reports=[lecture, practice],
        expected_resource_types=[ResourceType.LECTURE, ResourceType.PRACTICE_GUIDE],
        required_knowledge_ids=knowledge_ids,
        revision_count=0,
    )

    assert output.package_covered_knowledge_ids == sorted(knowledge_ids)
    assert output.package_missing_knowledge_ids == []
    assert output.package_quality.core_knowledge_coverage == 100


def test_package_quality_rejects_mismatched_requested_resource_set() -> None:
    flow = initial_generation_flow_example()
    reports = flow["review_resource"]["output"].reports[:2]

    output = build_review_resource_output(
        task_id="task_partial_refresh",
        reports=reports,
        expected_resource_types=[ResourceType.LECTURE, ResourceType.GRADED_QUIZ],
        required_knowledge_ids=[],
        revision_count=0,
    )

    assert not output.package_quality.passed
    assert not output.package_passed
