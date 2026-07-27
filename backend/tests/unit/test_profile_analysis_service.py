from __future__ import annotations

from copy import deepcopy

import pytest

from app.agents.contracts import (
    AbilityScores,
    AnalyzeProfileInput,
    DiagnosticSummary,
    EvidenceRef,
    EvidenceType,
    ExecutionMode,
    KnowledgeAssessment,
    ProfileSnapshot,
    ProfileType,
    RecommendedAction,
    ResourceType,
    TaskContext,
)
from app.services.profile_analysis_service import ProfileAnalysisError, analyze_profile


def _initial_input() -> AnalyzeProfileInput:
    task_id = "profile_algorithm_test"
    evidence = EvidenceRef(
        evidence_id="evidence_profile_algorithm_test",
        evidence_type=EvidenceType.DIAGNOSTIC_RESULT,
        summary="脱敏诊断评分",
        knowledge_id="rag_pipeline_overview",
        confidence=0.9,
        confirmed=True,
    )
    return AnalyzeProfileInput(
        task_id=task_id,
        context=TaskContext(
            task_id=task_id,
            session_id=task_id,
            trigger_type="initial_generation",
            execution_mode=ExecutionMode.AUTO,
            learner_id="learner_fixture",
            profile_id="profile_fixture",
            domain_code="ai_app_dev",
            resource_types=[ResourceType.LECTURE],
            learning_goal="掌握 RAG 流程总览",
        ),
        current_profile=ProfileSnapshot(
            profile_id="profile_fixture",
            profile_version=1,
            profile_type=ProfileType.INTERMEDIATE,
            ability_scores=AbilityScores(
                theory=60,
                practice=60,
                problem_solving=60,
                knowledge_breadth=60,
                learning_speed=50,
            ),
        ),
        diagnostic_summary=DiagnosticSummary(
            diagnostic_session_id="diagnostic_fixture",
            question_count=10,
            answered_count=10,
            correct_count=2,
            skipped_count=0,
            score_percent=20,
            evidence=[evidence],
        ),
        knowledge_assessments=[
            KnowledgeAssessment(
                assessment_id="assessment_profile_algorithm_test",
                evidence_id=evidence.evidence_id,
                knowledge_id="rag_pipeline_overview",
                score=0.2,
                difficulty=2,
                attempted=True,
                confidence=0.9,
            )
        ],
    )


def _feedback_payload(action: RecommendedAction) -> dict:
    payload = _initial_input().model_dump()
    payload["context"].update(
        {
            "trigger_type": "resource_feedback",
            "resource_id": "resource_fixture",
            "feedback_id": "feedback_fixture",
        }
    )
    payload["diagnostic_summary"] = None
    payload["knowledge_assessments"] = []
    payload["recommended_action"] = action.value
    return payload


def test_confirmed_diagnostic_creates_a_valid_profile_decision() -> None:
    result = analyze_profile(_initial_input())

    assert result.profile_update_required
    assert result.profile.profile_version == 2
    assert result.profile.profile_type is ProfileType.BEGINNER
    assert result.profile.ability_scores.knowledge_breadth == 60
    assert result.profile.ability_scores.learning_speed == 50
    assert result.evidence_refs
    assert result.retrieval_plan.query_terms
    assert result.affected_scope.path_node_ids == []
    assert result.affected_scope.resource_ids == []


def test_single_quick_feedback_does_not_update_profile() -> None:
    payload = _feedback_payload(RecommendedAction.ASK_FOLLOW_UP)
    payload["feedback_evidence"] = [
        {
            "evidence_id": "quick_feedback",
            "evidence_type": "quick_feedback",
            "summary": "脱敏快捷反馈",
            "knowledge_id": "rag_pipeline_overview",
            "confidence": 0.3,
            "confirmed": False,
        }
    ]

    result = analyze_profile(AnalyzeProfileInput.model_validate(payload))

    assert not result.profile_update_required
    assert result.changed_dimensions == []
    assert not result.needs_generation


def test_resource_review_never_reduces_profile() -> None:
    node_input = AnalyzeProfileInput.model_validate(_feedback_payload(RecommendedAction.REVIEW))
    result = analyze_profile(node_input)

    assert not result.profile_update_required
    assert result.profile == node_input.current_profile
    assert result.needs_generation


def test_unscored_attempt_is_coverage_only() -> None:
    payload = _initial_input().model_dump()
    payload["knowledge_assessments"][0]["score"] = None
    result = analyze_profile(AnalyzeProfileInput.model_validate(payload))

    assert not result.profile_update_required
    assert result.profile.profile_version == 1


def test_conflicting_evidence_ids_fail_without_guessing() -> None:
    payload = _initial_input().model_dump()
    duplicate = deepcopy(payload["diagnostic_summary"]["evidence"][0])
    duplicate["summary"] = "conflicting summary"
    payload["feedback_evidence"] = [duplicate]

    with pytest.raises(ProfileAnalysisError, match="evidence_id_conflict"):
        analyze_profile(AnalyzeProfileInput.model_validate(payload))


def test_same_input_is_deterministic() -> None:
    node_input = _initial_input()
    outputs = [analyze_profile(node_input).model_dump(mode="json") for _ in range(100)]

    assert all(output == outputs[0] for output in outputs)
