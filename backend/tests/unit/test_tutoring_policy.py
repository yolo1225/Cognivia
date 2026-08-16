from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.contracts import FeedbackIntent, InterpretFeedbackInput, RecommendedAction
from app.services.tutoring_policy import (
    TutoringSemanticResult,
    build_feedback_evidence,
    decide_tutoring_action,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "v3_tutoring"
    / "minimal_feedback_input.json"
)


def _request() -> InterpretFeedbackInput:
    document = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return InterpretFeedbackInput.model_validate(document["input"])


def _semantic(intent: FeedbackIntent, **overrides: object) -> TutoringSemanticResult:
    return TutoringSemanticResult(intent=intent, confidence=0.9, **overrides)


@pytest.mark.parametrize("intent", [FeedbackIntent.TOO_HARD, FeedbackIntent.CONFUSING])
def test_first_difficulty_feedback_asks_follow_up(intent: FeedbackIntent) -> None:
    payload = _request().model_dump(mode="python")
    payload["feedback"]["quick_tag"] = intent
    request = InterpretFeedbackInput.model_validate(payload)

    decision = decide_tutoring_action(request, _semantic(intent, difficulty_focus="来源追溯"))

    assert decision.recommended_action is RecommendedAction.ASK_FOLLOW_UP
    assert not decision.needs_generation


def test_same_unresolved_difficulty_in_later_turn_requests_remedial_explanation() -> None:
    payload = _request().model_dump(mode="python")
    payload["feedback"]["conversation"]["turn_count"] = 2
    payload["feedback"]["conversation"]["previous_intents"] = ["too_hard"]
    request = InterpretFeedbackInput.model_validate(payload)

    decision = decide_tutoring_action(
        request,
        _semantic(FeedbackIntent.TOO_HARD, unresolved=True),
    )

    assert decision.recommended_action is RecommendedAction.EXPLAIN
    assert decision.needs_generation


def test_too_easy_without_controlled_evidence_keeps_confirmation_loop() -> None:
    payload = _request().model_dump(mode="python")
    payload["feedback"]["quick_tag"] = "too_easy"
    request = InterpretFeedbackInput.model_validate(payload)

    decision = decide_tutoring_action(request, _semantic(FeedbackIntent.TOO_EASY))

    assert decision.recommended_action is RecommendedAction.ASK_FOLLOW_UP
    assert not decision.needs_generation


def test_too_easy_with_confirmed_scored_evidence_requests_challenge() -> None:
    payload = _request().model_dump(mode="python")
    payload["feedback"]["quick_tag"] = "too_easy"
    payload["feedback"]["supporting_evidence"] = [
        {
            "evidence_id": "evidence_scored_quiz_001",
            "evidence_type": "scored_quiz",
            "summary": "计分题已确认掌握",
            "knowledge_id": "AIAPP-K029",
            "confidence": 0.9,
            "confirmed": True,
        }
    ]
    request = InterpretFeedbackInput.model_validate(payload)

    decision = decide_tutoring_action(request, _semantic(FeedbackIntent.TOO_EASY))

    assert decision.recommended_action is RecommendedAction.CHALLENGE
    assert decision.needs_generation


def test_incorrect_feedback_has_priority_and_requests_review() -> None:
    payload = _request().model_dump(mode="python")
    payload["feedback"]["quick_tag"] = "incorrect"
    request = InterpretFeedbackInput.model_validate(payload)

    decision = decide_tutoring_action(request, _semantic(FeedbackIntent.TOO_HARD))

    assert decision.feedback_intent is FeedbackIntent.INCORRECT
    assert decision.recommended_action is RecommendedAction.REVIEW
    assert decision.needs_generation
    assert "画像" in decision.reply_template


def test_helpful_feedback_does_not_change_or_generate() -> None:
    payload = _request().model_dump(mode="python")
    payload["feedback"]["quick_tag"] = "helpful"
    request = InterpretFeedbackInput.model_validate(payload)

    decision = decide_tutoring_action(request, _semantic(FeedbackIntent.HELPFUL))

    assert decision.recommended_action is RecommendedAction.NO_CHANGE
    assert not decision.needs_generation


def test_low_confidence_and_conflicting_intent_fail_closed_to_follow_up() -> None:
    request = _request()

    low_confidence = decide_tutoring_action(
        request,
        TutoringSemanticResult(intent=FeedbackIntent.TOO_HARD, confidence=0.3),
    )
    conflict = decide_tutoring_action(request, _semantic(FeedbackIntent.TOO_EASY))

    assert low_confidence.feedback_intent is FeedbackIntent.OTHER
    assert low_confidence.recommended_action is RecommendedAction.ASK_FOLLOW_UP
    assert not low_confidence.needs_generation
    assert conflict.feedback_intent is FeedbackIntent.OTHER
    assert conflict.recommended_action is RecommendedAction.ASK_FOLLOW_UP


def test_feedback_evidence_id_is_distinct_for_different_turns_of_one_task() -> None:
    first = _request()
    payload = first.model_dump(mode="python")
    payload["feedback"]["conversation"]["turn_count"] = 2
    payload["context"]["tutoring_message_id"] = "message_stage1_002"
    second = InterpretFeedbackInput.model_validate(payload)
    semantic = _semantic(FeedbackIntent.TOO_HARD)

    first_evidence = build_feedback_evidence(first, semantic)
    second_evidence = build_feedback_evidence(second, semantic)

    assert first_evidence[-1].evidence_id != second_evidence[-1].evidence_id
