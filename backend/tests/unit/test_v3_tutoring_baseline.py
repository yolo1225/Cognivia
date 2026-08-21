"""阶段一：验证导学 Agent 的最小 V3 输入 fixture 可被冻结契约消费。"""

from __future__ import annotations

import json
from pathlib import Path

from app.agents.contracts import (
    CONTRACT_VERSION,
    FeedbackIntent,
    InterpretFeedbackInput,
    TriggerType,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "v3_tutoring"
    / "minimal_feedback_input.json"
)


def test_minimal_feedback_fixture_validates_against_frozen_v3_contract() -> None:
    document = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    request = InterpretFeedbackInput.model_validate(document["input"])

    assert document["contract_version"] == CONTRACT_VERSION
    assert request.contract_version == CONTRACT_VERSION
    assert request.task_id == request.context.task_id
    assert request.context.trigger_type == TriggerType.RESOURCE_FEEDBACK
    assert request.feedback.conversation.turn_count == 1
    assert request.feedback.quick_tag == FeedbackIntent.TOO_HARD
