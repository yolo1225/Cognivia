"""Stage-three V3 flow: profile -> retrieval -> generation -> review."""

from __future__ import annotations

import pytest

from app.agents.contract_adapters import (
    analyze_profile_output_to_patch,
    build_analyze_profile_input,
    build_finalize_task_input,
    build_generate_resource_input,
    build_retrieve_knowledge_input,
    build_review_resource_input,
    generate_resource_output_to_patch,
    prepare_task_output_to_patch,
    retrieve_knowledge_output_to_patch,
    review_resource_output_to_patch,
    finalize_task_output_to_patch,
    render_resource_markdown,
)
from app.agents.contracts import (
    AnalyzeProfileInput,
    ModelReview,
    ReviewCriterionScores,
    PrepareTaskOutput,
    RetrieveKnowledgeInput,
    RetrieveKnowledgeOutput,
    RetrievedChunk,
    RetrievedQuestion,
    QuestionType,
    RetrievalMatchType,
    ReviewDecision,
    SourceRef,
    TaskRequest,
    TriggerType,
)
from app.agents.state import AgentGraphState
from app.agents.generation_agent import ContentGenerationAgent
from app.agents.profile_analysis_agent import ProfileAnalysisAgent
from app.agents.profile_analysis_config import AI_APP_DEV_PROFILE_V2
from app.agents.retrieval_agent import KnowledgeRetrievalAgent
from app.agents.review_agent import ReviewValidationAgent
from app.agents.orchestrator_agent import OrchestratorAgent
from app.services.profile_v3_fixture_service import rendered_cases


class FlowRetriever:
    """Controlled V3 retrieval boundary used to exercise downstream contracts."""

    def __init__(self) -> None:
        self.requests: list[RetrieveKnowledgeInput] = []

    def execute(self, request: RetrieveKnowledgeInput) -> RetrieveKnowledgeOutput:
        self.requests.append(request)
        knowledge_ids = list(
            dict.fromkeys(
                [
                    *request.retrieval_plan.priority_knowledge_ids,
                    *request.retrieval_plan.prerequisite_knowledge_ids,
                ]
            )
        )
        chunks = [
            RetrievedChunk(
                chunk_id=f"{knowledge_id}::chunk::0",
                knowledge_id=knowledge_id,
                name=f"知识点 {knowledge_id}",
                category="ai_app_dev",
                difficulty=request.retrieval_plan.target_difficulty,
                content=(
                    f"{knowledge_id} 的可追溯学习证据。\n"
                    "操作步骤：\n1. 执行以下配置检查并记录结果。"
                ),
                similarity=0.95 - index * 0.01,
                matched_by=(
                    RetrievalMatchType.PRIORITY
                    if knowledge_id in request.retrieval_plan.priority_knowledge_ids
                    else RetrievalMatchType.PREREQUISITE
                ),
                used_for=request.purpose,
                source=SourceRef(
                    source_ref_id=f"{knowledge_id}::chunk::0",
                    knowledge_id=knowledge_id,
                    source_title=f"知识库条目 {knowledge_id}",
                    license_note="team-authored",
                ),
                source_locator=f"knowledge:{knowledge_id}#chunk=0",
            )
            for index, knowledge_id in enumerate(knowledge_ids)
        ]
        reference_questions = []
        for knowledge_id in knowledge_ids:
            for slot in range(1, 7):
                is_choice = slot % 2 == 1
                reference_questions.append(
                    RetrievedQuestion(
                        question_id=f"formal-{knowledge_id}-{slot}",
                        knowledge_id=knowledge_id,
                        question_type=(
                            QuestionType.SINGLE_CHOICE
                            if is_choice
                            else QuestionType.SHORT_ANSWER
                        ),
                        stem=f"{knowledge_id} 正式题库题目 {slot}",
                        options=["正确项", "干扰项一", "干扰项二", "干扰项三"]
                        if is_choice
                        else [],
                        answer_key={
                            **(
                                {"correct_option": 0}
                                if is_choice
                                else {"answer": "来源支持的答案", "rubric": ["要点一", "要点二"]}
                            ),
                            "explanation": "依据知识库材料作答。",
                            "source_ref_ids": [f"{knowledge_id}::chunk::0"],
                            "source_locator": f"knowledge:{knowledge_id}#chunk=0",
                            "question_bank_uses": ["graded_quiz"],
                            "question_slot": slot,
                            "quiz_level": (
                                "foundation"
                                if slot <= 2
                                else "improvement"
                                if slot <= 4
                                else "challenge"
                            ),
                        },
                        explanation="依据知识库材料作答。",
                        difficulty=min(5, slot),
                    )
                )
        return RetrieveKnowledgeOutput(
            task_id=request.task_id,
            query_text=" ".join(request.retrieval_plan.query_terms),
            chunks=chunks,
            covered_knowledge_ids=knowledge_ids,
            missing_knowledge_ids=[],
            reference_questions=reference_questions,
        )


class DeterministicReviewChannel:
    """Both V3 review channels independently return their computed baseline."""

    def review(self, *, deterministic_review: ModelReview, **_kwargs) -> ModelReview:
        return deterministic_review


class PassingReviewChannel:
    """A controlled independent review channel for the completed-task branch."""

    def review(self, *, role, model, deterministic_review: ModelReview, **_kwargs) -> ModelReview:
        return ModelReview(
            model_role=role,
            model_name=model or role,
            scores=ReviewCriterionScores(
                factual_accuracy=90,
                source_traceability=90,
                difficulty_match=90,
                core_knowledge_coverage=90,
            ),
            passed=True,
            fact_checks=deterministic_review.fact_checks,
        )


def _analysis_input(case_id: str) -> AnalyzeProfileInput:
    for current_case_id, payload, _ in rendered_cases():
        if current_case_id == case_id:
            return AnalyzeProfileInput.model_validate(payload)
    raise AssertionError(f"missing V3 profile fixture: {case_id}")


def _initial_state(request: AnalyzeProfileInput) -> AgentGraphState:
    task_request = TaskRequest.model_validate(
        request.context.model_dump(mode="python", exclude={"contract_version"})
    )
    prepared = PrepareTaskOutput(
        task_id=request.task_id,
        context=request.context,
        next_node=(
            "interpret_feedback"
            if request.context.trigger_type is TriggerType.RESOURCE_FEEDBACK
            else "analyze_profile"
        ),
    )
    state: AgentGraphState = {
        "contract_version": "agent-contract-v3",
        "task_request": task_request,
        "current_profile": request.current_profile,
        "diagnostic_summary": request.diagnostic_summary,
    }
    state.update(prepare_task_output_to_patch(prepared))
    return state


@pytest.mark.parametrize(
    "case_id",
    ["dev-initial-01", "dev-update-01", "accept-initial-01"],
)
def test_v3_profile_retrieval_generation_review_flow(case_id: str) -> None:
    original_input = _analysis_input(case_id)
    state = _initial_state(original_input)

    if original_input.context.trigger_type is TriggerType.RESOURCE_FEEDBACK:
        # The tutoring-to-profile state construction is covered by
        # test_v3_tutoring_profile_flow; continue this chain from its V3 input.
        profile_input = original_input
    else:
        profile_input = build_analyze_profile_input(
            state, knowledge_assessments=original_input.knowledge_assessments
        )
        assert profile_input == original_input
    profile_output = ProfileAnalysisAgent(AI_APP_DEV_PROFILE_V2).execute(profile_input)
    assert profile_output.needs_generation
    state.update(analyze_profile_output_to_patch(profile_output))

    retriever = FlowRetriever()
    retrieval_input = build_retrieve_knowledge_input(state)
    retrieval_output = KnowledgeRetrievalAgent(retriever).execute(retrieval_input)
    assert retriever.requests == [retrieval_input]
    assert retrieval_output.task_id == profile_output.task_id
    state.update(retrieve_knowledge_output_to_patch(retrieval_output))

    generation_input = build_generate_resource_input(state)
    generation_output = ContentGenerationAgent(renderer=render_resource_markdown).execute(
        generation_input
    )
    assert generation_output.task_id == retrieval_output.task_id
    assert {item.resource_type for item in generation_output.resources} == set(
        generation_input.requirements.resource_types
    )
    for artifact in generation_output.resources:
        assert {source.source_ref_id for source in artifact.source_refs}.issubset(
            generation_input.requirements.source_whitelist
        )
    state.update(generate_resource_output_to_patch(generation_input, generation_output))

    review_input = build_review_resource_input(state)
    review_output = ReviewValidationAgent(channel=DeterministicReviewChannel()).execute(
        review_input
    )
    assert review_output.task_id == generation_output.task_id
    assert {report.resource_type for report in review_output.reports} == {
        resource.resource_type for resource in generation_output.resources
    }
    assert all(
        report.decision in {ReviewDecision.PASSED, ReviewDecision.REVISION_REQUIRED}
        for report in review_output.reports
    )
    assert all(report.final_scores.factual_accuracy == 100 for report in review_output.reports)
    assert all(
        report.decision is ReviewDecision.REVISION_REQUIRED
        for report in review_output.reports
        if report.undetermined_claim_ids
    )
    assert all(
        report.final_scores.source_traceability < 100
        for report in review_output.reports
        if report.undetermined_claim_ids
    )
    state.update(review_resource_output_to_patch(review_input, review_output))

    finalize_input = build_finalize_task_input(state)
    finalize_output = OrchestratorAgent().execute(finalize_input)
    assert finalize_output.task_id == review_output.task_id
    expected_revision_types = [
        report.resource_type
        for report in review_output.reports
        if report.decision is ReviewDecision.REVISION_REQUIRED
    ]
    if expected_revision_types:
        assert finalize_output.decision.value == "revision_required"
        assert finalize_output.revision_count == 1
        assert finalize_output.revision_plan is not None
        assert finalize_output.revision_plan.resource_types == expected_revision_types
    else:
        assert finalize_output.decision.value == "completed"
    state.update(finalize_task_output_to_patch(finalize_output))

    assert state["review_resource"] == review_output
    assert state["finalize_task"] == finalize_output


def test_v3_full_chain_requires_revision_when_high_scores_lack_field_evidence() -> None:
    original_input = _analysis_input("dev-initial-01")
    state = _initial_state(original_input)
    profile_output = ProfileAnalysisAgent(AI_APP_DEV_PROFILE_V2).execute(
        build_analyze_profile_input(
            state, knowledge_assessments=original_input.knowledge_assessments
        )
    )
    state.update(analyze_profile_output_to_patch(profile_output))

    retriever = FlowRetriever()
    retrieval_input = build_retrieve_knowledge_input(state)
    retrieval_output = KnowledgeRetrievalAgent(retriever).execute(retrieval_input)
    state.update(retrieve_knowledge_output_to_patch(retrieval_output))

    generation_input = build_generate_resource_input(state)
    generation_output = ContentGenerationAgent(renderer=render_resource_markdown).execute(
        generation_input
    )
    state.update(generate_resource_output_to_patch(generation_input, generation_output))

    review_input = build_review_resource_input(state)
    review_input = review_input.model_copy(
        update={
            "evidence": [
                chunk.model_copy(update={"content": "仅包含与生成字段无关的背景材料。"})
                for chunk in review_input.evidence
            ]
        }
    )
    review_output = ReviewValidationAgent(channel=PassingReviewChannel()).execute(review_input)
    assert any(
        report.decision is ReviewDecision.REVISION_REQUIRED for report in review_output.reports
    )
    state.update(review_resource_output_to_patch(review_input, review_output))

    finalize_output = OrchestratorAgent().execute(build_finalize_task_input(state))
    assert finalize_output.decision.value == "revision_required"
    assert finalize_output.revision_plan is not None
