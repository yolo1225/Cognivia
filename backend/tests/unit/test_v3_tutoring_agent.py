from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from app.agents.contracts import EvidenceType, FeedbackIntent, InterpretFeedbackInput, InterpretFeedbackOutput, RecommendedAction
from app.agents.tutoring_agent import (
    SYSTEM_PROMPT,
    TUTORING_AGENT_NAME,
    TutoringAgentError,
    TutoringAgent,
)
from app.services.tutoring_policy import TutoringSemanticResult


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "v3_tutoring"
    / "minimal_feedback_input.json"
)


class FakeInterpreter:
    def __init__(self, result: Any) -> None:
        self._result = result

    def interpret(self, _request: InterpretFeedbackInput) -> Any:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _request() -> InterpretFeedbackInput:
    document = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return InterpretFeedbackInput.model_validate(document["input"])


def _semantic(intent: FeedbackIntent, **overrides: object) -> TutoringSemanticResult:
    return TutoringSemanticResult(intent=intent, confidence=0.9, **overrides)


def _execute(request: InterpretFeedbackInput, semantic: Any) -> InterpretFeedbackOutput:
    return TutoringAgent(interpreter=FakeInterpreter(semantic)).execute(request)


def test_v3_agent_exposes_identity_and_model_boundary_prompt() -> None:
    agent = TutoringAgent(interpreter=FakeInterpreter(_semantic(FeedbackIntent.TOO_HARD)))

    assert agent.name == TUTORING_AGENT_NAME
    assert agent.system_prompt == SYSTEM_PROMPT
    assert "不得决定画像更新" in agent.system_prompt


def test_first_difficulty_returns_model_worded_follow_up_and_contract_output() -> None:
    output = _execute(
        _request(),
        _semantic(
            FeedbackIntent.TOO_HARD,
            difficulty_focus="来源追溯",
            candidate_reply="你先说说是检索结果、来源标注还是验证步骤让你困惑？",
        ),
    )

    assert isinstance(output, InterpretFeedbackOutput)
    assert output.recommended_action is RecommendedAction.ASK_FOLLOW_UP
    assert not output.needs_generation
    assert output.reply == "你先说说是检索结果、来源标注还是验证步骤让你困惑？"
    assert output.evidence[-1].evidence_type is EvidenceType.QUICK_FEEDBACK


def test_model_candidate_cannot_claim_profile_or_publication_action() -> None:
    output = _execute(
        _request(),
        _semantic(
            FeedbackIntent.TOO_HARD,
            candidate_reply="我会更新画像并发布新的资源。",
        ),
    )

    assert output.recommended_action is RecommendedAction.ASK_FOLLOW_UP
    assert output.reply != "我会更新画像并发布新的资源。"


def test_second_unresolved_difficulty_requests_explanation() -> None:
    payload = _request().model_dump(mode="python")
    payload["feedback"]["conversation"]["turn_count"] = 2
    payload["feedback"]["conversation"]["previous_intents"] = ["too_hard"]
    request = InterpretFeedbackInput.model_validate(payload)

    output = _execute(request, _semantic(FeedbackIntent.TOO_HARD, unresolved=True))

    assert output.recommended_action is RecommendedAction.EXPLAIN
    assert output.needs_generation


def test_too_easy_requires_confirmed_evidence_before_challenge() -> None:
    payload = _request().model_dump(mode="python")
    payload["feedback"]["quick_tag"] = "too_easy"
    no_evidence = _execute(
        InterpretFeedbackInput.model_validate(payload),
        _semantic(FeedbackIntent.TOO_EASY),
    )

    payload["feedback"]["supporting_evidence"] = [
        {
            "evidence_id": "evidence_behavior_001",
            "evidence_type": "validated_behavior",
            "summary": "已确认的迁移任务完成行为",
            "knowledge_id": "AIAPP-K029",
            "confidence": 0.8,
            "confirmed": True,
        }
    ]
    with_evidence = _execute(
        InterpretFeedbackInput.model_validate(payload),
        _semantic(FeedbackIntent.TOO_EASY),
    )

    assert no_evidence.recommended_action is RecommendedAction.ASK_FOLLOW_UP
    assert not no_evidence.needs_generation
    assert with_evidence.recommended_action is RecommendedAction.CHALLENGE
    assert with_evidence.needs_generation


def test_incorrect_and_helpful_keep_their_required_boundaries() -> None:
    incorrect_payload = _request().model_dump(mode="python")
    incorrect_payload["feedback"]["quick_tag"] = "incorrect"
    incorrect = _execute(
        InterpretFeedbackInput.model_validate(incorrect_payload),
        _semantic(FeedbackIntent.TOO_HARD),
    )

    helpful_payload = _request().model_dump(mode="python")
    helpful_payload["feedback"]["quick_tag"] = "helpful"
    helpful = _execute(
        InterpretFeedbackInput.model_validate(helpful_payload),
        _semantic(FeedbackIntent.HELPFUL),
    )

    assert incorrect.recommended_action is RecommendedAction.REVIEW
    assert incorrect.needs_generation
    assert "不作为能力下降证据" in incorrect.decision_reason
    assert helpful.recommended_action is RecommendedAction.NO_CHANGE
    assert not helpful.needs_generation


@pytest.mark.parametrize(
    "semantic",
    [
        TutoringSemanticResult(intent=FeedbackIntent.TOO_HARD, confidence=0.2),
        {"intent": "not_an_intent", "confidence": 0.9},
        RuntimeError("model transport failure"),
    ],
)
def test_invalid_or_failed_model_semantics_safely_fall_back(semantic: Any) -> None:
    output = _execute(_request(), semantic)

    assert output.feedback_intent is FeedbackIntent.OTHER
    assert output.recommended_action is RecommendedAction.ASK_FOLLOW_UP
    assert not output.needs_generation


def test_agent_rejects_raw_dict() -> None:
    with pytest.raises(TutoringAgentError, match="invalid_interpret_feedback_input_type"):
        TutoringAgent(interpreter=FakeInterpreter(_semantic(FeedbackIntent.TOO_HARD))).execute(  # type: ignore[arg-type]
            {"task_id": "not-a-contract"}
        )


def test_logs_safe_identifiers_without_feedback_body(caplog: pytest.LogCaptureFixture) -> None:
    payload = _request().model_dump(mode="python")
    secret = "complete-learner-message-must-not-appear-in-log"
    payload["feedback"]["feedback_summary"] = secret
    request = InterpretFeedbackInput.model_validate(payload)
    logger = logging.getLogger("tests.tutoring_agent")
    caplog.set_level(logging.INFO, logger=logger.name)

    TutoringAgent(
        interpreter=FakeInterpreter(_semantic(FeedbackIntent.TOO_HARD)), logger=logger
    ).execute(request)

    assert "tutoring_completed" in caplog.text
    assert request.task_id in caplog.text
    assert request.feedback.resource.resource_id in caplog.text
    assert secret not in caplog.text


def test_agent_has_no_legacy_graph_or_database_dependency() -> None:
    source = Path(__file__).parents[2] / "app" / "agents" / "tutoring_agent.py"
    text = source.read_text(encoding="utf-8")

    for forbidden_reference in (
        "legacy_contracts",
        "legacy_state",
        "SessionLocal",
        "StateGraph",
        "generation_worker",
    ):
        assert forbidden_reference not in text
