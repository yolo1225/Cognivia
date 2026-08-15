"""Stage-three in-memory verification for the tutoring-to-profile V3 data flow."""

from __future__ import annotations

import json
from pathlib import Path

from app.agents.contract_adapters import (
    build_analyze_profile_input,
    build_interpret_feedback_input,
    interpret_feedback_output_to_patch,
    prepare_task_output_to_patch,
)
from app.agents.contracts import (
    EvidenceType,
    FeedbackIntent,
    InterpretFeedbackInput,
    KnowledgeAssessment,
    PrepareTaskOutput,
    RecommendedAction,
    TaskRequest,
)
from app.agents.state import AgentGraphState
from app.agents.profile_analysis_agent import ProfileAnalysisAgent
from app.agents.tutoring_agent import TutoringAgent
from app.services.tutoring_policy import TutoringSemanticResult


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "v3_tutoring"
    / "minimal_feedback_input.json"
)
KNOWLEDGE_ID = "rag_pipeline_overview"


class FakeInterpreter:
    def __init__(self, result: TutoringSemanticResult) -> None:
        self._result = result

    def interpret(self, _request: InterpretFeedbackInput) -> TutoringSemanticResult:
        return self._result


def _request(
    *,
    supporting_evidence: list[dict[str, object]] | None = None,
    message_id: str,
) -> InterpretFeedbackInput:
    document = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload = document["input"]
    payload["feedback"]["quick_tag"] = "too_easy"
    payload["feedback"]["supporting_evidence"] = supporting_evidence or []
    payload["context"]["tutoring_message_id"] = message_id
    return InterpretFeedbackInput.model_validate(payload)


def _state_for(request: InterpretFeedbackInput) -> AgentGraphState:
    task_request = TaskRequest.model_validate(
        request.context.model_dump(mode="python", exclude={"contract_version"})
    )
    prepared = PrepareTaskOutput(
        task_id=request.task_id,
        context=request.context,
        next_node="interpret_feedback",
    )
    state: AgentGraphState = {
        "contract_version": "agent-contract-v3",
        "task_request": task_request,
        "current_profile": request.profile,
        "feedback_context": request.feedback,
    }
    state.update(prepare_task_output_to_patch(prepared))
    return state


def _run_flow(
    request: InterpretFeedbackInput,
    *,
    knowledge_assessments: list[KnowledgeAssessment] | None = None,
):
    state = _state_for(request)
    tutoring_input = build_interpret_feedback_input(state)
    assert tutoring_input == request

    tutoring_output = TutoringAgent(
        interpreter=FakeInterpreter(
            TutoringSemanticResult(intent=FeedbackIntent.TOO_EASY, confidence=0.9)
        )
    ).execute(tutoring_input)
    state.update(interpret_feedback_output_to_patch(tutoring_output))

    profile_input = build_analyze_profile_input(
        state, knowledge_assessments=knowledge_assessments
    )
    profile_output = ProfileAnalysisAgent().execute(profile_input)
    return tutoring_output, profile_input, profile_output


def _validated_behavior(evidence_id: str = "validated_behavior") -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "evidence_type": EvidenceType.VALIDATED_BEHAVIOR,
        "summary": "已确认的迁移任务完成行为",
        "knowledge_id": KNOWLEDGE_ID,
        "confidence": 0.9,
        "confirmed": True,
    }


def _assessment(evidence_id: str) -> KnowledgeAssessment:
    return KnowledgeAssessment(
        assessment_id=f"assessment_{evidence_id}",
        evidence_id=evidence_id,
        knowledge_id=KNOWLEDGE_ID,
        score=0.95,
        difficulty=3,
        attempted=True,
        confidence=0.9,
    )


def test_single_subjective_too_easy_feedback_does_not_update_profile() -> None:
    request = _request(message_id="stage3_subjective_001")

    tutoring_output, profile_input, profile_output = _run_flow(request)

    assert tutoring_output.recommended_action is RecommendedAction.ASK_FOLLOW_UP
    assert not tutoring_output.needs_generation
    assert len(tutoring_output.evidence) == 1
    assert tutoring_output.evidence[0].evidence_type is EvidenceType.QUICK_FEEDBACK
    assert not tutoring_output.evidence[0].confirmed
    assert profile_input.feedback_evidence == tutoring_output.evidence
    assert not profile_output.profile_update_required
    assert profile_output.profile.profile_version == request.profile.profile_version


def test_confirmed_behavior_without_assessment_does_not_update_profile() -> None:
    behavior = _validated_behavior()
    request = _request(
        supporting_evidence=[behavior], message_id="stage3_behavior_without_assessment_001"
    )

    tutoring_output, profile_input, profile_output = _run_flow(request)

    assert tutoring_output.recommended_action is RecommendedAction.CHALLENGE
    assert tutoring_output.needs_generation
    assert any(
        evidence.evidence_id == behavior["evidence_id"]
        and evidence.evidence_type is EvidenceType.VALIDATED_BEHAVIOR
        for evidence in tutoring_output.evidence
    )
    assert profile_input.feedback_evidence == tutoring_output.evidence
    assert not profile_output.profile_update_required
    assert profile_output.profile.profile_version == request.profile.profile_version


def test_confirmed_behavior_with_scored_assessment_updates_profile() -> None:
    behavior = _validated_behavior()
    request = _request(
        supporting_evidence=[behavior], message_id="stage3_behavior_with_assessment_001"
    )

    tutoring_output, profile_input, profile_output = _run_flow(
        request, knowledge_assessments=[_assessment(behavior["evidence_id"])]
    )

    assert "profile_update_required" not in tutoring_output.model_dump()
    assert "profile" not in tutoring_output.model_dump()
    assert tutoring_output.recommended_action is RecommendedAction.CHALLENGE
    assert profile_input.feedback_evidence == tutoring_output.evidence
    assert profile_output.profile_update_required
    assert profile_output.profile.profile_version == request.profile.profile_version + 1
    assert any(
        evidence.evidence_type is EvidenceType.VALIDATED_BEHAVIOR
        for evidence in profile_output.evidence_refs
    )
    assert profile_output.needs_generation


def test_subjective_feedback_cannot_bypass_evidence_type_whitelist() -> None:
    quick_feedback = {
        "evidence_id": "quick_feedback_assessment",
        "evidence_type": EvidenceType.QUICK_FEEDBACK,
        "summary": "学习者认为内容太简单",
        "knowledge_id": KNOWLEDGE_ID,
        "confidence": 0.9,
        "confirmed": True,
    }
    request = _request(
        supporting_evidence=[quick_feedback], message_id="stage3_subjective_assessment_001"
    )

    tutoring_output, profile_input, profile_output = _run_flow(
        request, knowledge_assessments=[_assessment(quick_feedback["evidence_id"])]
    )

    assert tutoring_output.recommended_action is RecommendedAction.ASK_FOLLOW_UP
    assert profile_input.feedback_evidence == tutoring_output.evidence
    assert not profile_output.profile_update_required
    assert profile_output.profile.profile_version == request.profile.profile_version
