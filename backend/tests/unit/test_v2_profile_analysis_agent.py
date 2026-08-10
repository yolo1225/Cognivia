from __future__ import annotations

from copy import deepcopy
import logging
from pathlib import Path

import pytest

from app.agents.contracts import AnalyzeProfileInput, AnalyzeProfileOutput, RecommendedAction
from app.agents.v2_profile_analysis_agent import (
    PROFILE_ANALYSIS_AGENT_NAME,
    SYSTEM_PROMPT,
    V2ProfileAnalysisAgent,
)
from app.services.profile_analysis_service import ProfileAnalysisError, analyze_profile
from app.services.profile_v2_fixture_service import rendered_cases


def _input_for_case(case_id: str) -> AnalyzeProfileInput:
    for current_case_id, payload, _ in rendered_cases():
        if current_case_id == case_id:
            return AnalyzeProfileInput.model_validate(payload)
    raise AssertionError(f"missing fixture case: {case_id}")


def test_v2_agent_matches_pure_algorithm_for_all_frozen_cases() -> None:
    agent = V2ProfileAnalysisAgent()

    for case_id, payload, _ in rendered_cases():
        request = AnalyzeProfileInput.model_validate(payload)
        output = agent.execute(request)

        assert isinstance(output, AnalyzeProfileOutput)
        assert output.model_dump(mode="json") == analyze_profile(request).model_dump(mode="json"), case_id


def test_v2_agent_exposes_the_required_identity_and_prompt() -> None:
    agent = V2ProfileAnalysisAgent()

    assert agent.name == PROFILE_ANALYSIS_AGENT_NAME
    assert agent.system_prompt == SYSTEM_PROMPT
    assert "LLM" in agent.system_prompt


def test_v2_agent_rejects_raw_dict_without_logging_payload(caplog: pytest.LogCaptureFixture) -> None:
    agent = V2ProfileAnalysisAgent()
    caplog.set_level(logging.WARNING)

    with pytest.raises(ProfileAnalysisError, match="invalid_analyze_profile_input_type"):
        agent.execute({"task_id": "feedback-secret"})  # type: ignore[arg-type]

    assert "feedback-secret" not in caplog.text
    assert "invalid_analyze_profile_input_type" in caplog.text


def test_v2_agent_preserves_controlled_evidence_conflict_error() -> None:
    payload = _input_for_case("accept-initial-01").model_dump(mode="python")
    duplicate = deepcopy(payload["diagnostic_summary"]["evidence"][0])
    duplicate["summary"] = "complete learner feedback secret"
    payload["feedback_evidence"] = [duplicate]

    with pytest.raises(ProfileAnalysisError, match="evidence_id_conflict"):
        V2ProfileAnalysisAgent().execute(AnalyzeProfileInput.model_validate(payload))


def test_v2_agent_rejects_unknown_knowledge_with_a_controlled_error() -> None:
    payload = _input_for_case("accept-initial-01").model_dump(mode="python")
    unknown_id = "unknown_knowledge"
    payload["diagnostic_summary"]["evidence"][0]["knowledge_id"] = unknown_id
    payload["knowledge_assessments"][0]["knowledge_id"] = unknown_id

    with pytest.raises(ProfileAnalysisError, match="unknown_knowledge_id"):
        V2ProfileAnalysisAgent().execute(AnalyzeProfileInput.model_validate(payload))


def test_v2_agent_keeps_no_change_and_review_semantics() -> None:
    no_change = _input_for_case("accept-feedback-01")
    review = _input_for_case("accept-review-01")
    agent = V2ProfileAnalysisAgent()

    no_change_output = agent.execute(no_change)
    review_output = agent.execute(review)

    assert no_change.recommended_action is RecommendedAction.NO_CHANGE
    assert not no_change_output.profile_update_required
    assert not no_change_output.needs_generation
    assert review.recommended_action is RecommendedAction.REVIEW
    assert review_output.profile == review.current_profile
    assert review_output.needs_generation


def test_v2_agent_logs_only_safe_summary_fields(caplog: pytest.LogCaptureFixture) -> None:
    payload = _input_for_case("accept-initial-01").model_dump(mode="python")
    secret = "complete-feedback-and-resource-body-secret"
    payload["diagnostic_summary"]["evidence"][0]["summary"] = secret
    request = AnalyzeProfileInput.model_validate(payload)
    logger = logging.getLogger("tests.v2_profile_analysis_agent")
    caplog.set_level(logging.INFO, logger=logger.name)

    V2ProfileAnalysisAgent(logger=logger).execute(request)

    assert "profile_analysis_completed" in caplog.text
    assert request.task_id in caplog.text
    assert request.current_profile.profile_id in caplog.text
    assert secret not in caplog.text
    assert "AbilityScores(" not in caplog.text


def test_v2_agent_has_no_legacy_or_runtime_dependencies() -> None:
    source = Path(__file__).parents[2] / "app" / "agents" / "v2_profile_analysis_agent.py"
    text = source.read_text(encoding="utf-8")

    for forbidden_reference in (
        "legacy_contracts",
        "legacy_state",
        "SessionLocal",
        "VectorStore",
        "StateGraph",
        "OpenAI",
    ):
        assert forbidden_reference not in text
