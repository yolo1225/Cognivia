"""Standalone V3 tutoring Agent with model understanding and deterministic policy."""

from __future__ import annotations

import logging
from typing import Protocol

from pydantic import ValidationError

from app.agents.contracts import InterpretFeedbackInput, InterpretFeedbackOutput
from app.agents.observability import record_model_call
from app.core.config import settings
from app.services.llm_service import OpenAICompatibleGateway, gateway
from app.services.tutoring_policy import (
    TutoringSemanticResult,
    build_feedback_evidence,
    decide_tutoring_action,
)


TUTORING_AGENT_NAME = "tutoring_agent_v3"
SYSTEM_PROMPT = (
    "你是人工智能应用开发实训的导学语义理解组件。只基于输入的脱敏画像、资源和会话摘要，"
    "识别反馈意图、困难点、是否仍未解决，并给出简洁的候选追问。不得决定画像更新、资源发布、"
    "审核结论或任务创建；不得编造来源、成绩、行为或未提供的事实。"
)


class TutoringAgentError(RuntimeError):
    """Controlled boundary error for invalid V3 tutoring input or output."""


class TutoringSemanticInterpreter(Protocol):
    def interpret(self, request: InterpretFeedbackInput) -> TutoringSemanticResult: ...


class OpenAICompatibleTutoringInterpreter:
    """Use the project gateway for validated, OpenAI-compatible structured semantics."""

    def __init__(
        self,
        *,
        model: str | None = None,
        model_gateway: OpenAICompatibleGateway = gateway,
    ) -> None:
        self._model = model if model is not None else settings.primary_llm_model
        self._gateway = model_gateway

    def interpret(self, request: InterpretFeedbackInput) -> TutoringSemanticResult:
        result, metadata = self._gateway.complete_json(
            model=self._model,
            system_prompt=SYSTEM_PROMPT,
            payload={"feedback_request": request.model_dump(mode="json")},
            fixture_factory=lambda: _fixture_semantics(request),
            response_model=TutoringSemanticResult,
        )
        record_model_call(metadata, role="tutoring_model")
        return TutoringSemanticResult.model_validate(result)


class TutoringAgent:
    """V3 boundary: model semantics -> controlled policy -> contract-validated response."""

    name = TUTORING_AGENT_NAME
    system_prompt = SYSTEM_PROMPT

    def __init__(
        self,
        interpreter: TutoringSemanticInterpreter | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._interpreter = interpreter or OpenAICompatibleTutoringInterpreter()
        self._logger = logger or logging.getLogger(__name__)

    def execute(self, request: InterpretFeedbackInput) -> InterpretFeedbackOutput:
        if not isinstance(request, InterpretFeedbackInput):
            self._logger.warning("tutoring_rejected error_code=invalid_interpret_feedback_input_type")
            raise TutoringAgentError("invalid_interpret_feedback_input_type")

        try:
            validated_request = InterpretFeedbackInput.model_validate(request.model_dump(mode="python"))
        except ValidationError as exc:
            self._log_failure(request, "invalid_interpret_feedback_input")
            raise TutoringAgentError("invalid_interpret_feedback_input") from exc

        semantic, semantic_status = self._interpret_safely(validated_request)
        decision = decide_tutoring_action(validated_request, semantic)
        reply = _select_reply(decision.reply_template, semantic, decision.use_candidate_reply)

        try:
            output = InterpretFeedbackOutput(
                task_id=validated_request.task_id,
                feedback_intent=decision.feedback_intent,
                recommended_action=decision.recommended_action,
                reply=reply,
                evidence=build_feedback_evidence(validated_request, semantic),
                needs_generation=decision.needs_generation,
                decision_reason=decision.decision_reason,
            )
        except ValidationError as exc:
            self._log_failure(validated_request, "invalid_interpret_feedback_output")
            raise TutoringAgentError("invalid_interpret_feedback_output") from exc

        self._logger.info(
            "tutoring_completed task_id=%s resource_id=%s intent=%s action=%s "
            "needs_generation=%s evidence_count=%s semantic_status=%s confidence=%s",
            output.task_id,
            validated_request.feedback.resource.resource_id,
            output.feedback_intent,
            output.recommended_action,
            output.needs_generation,
            len(output.evidence),
            semantic_status,
            semantic.confidence,
        )
        return output

    def _interpret_safely(
        self, request: InterpretFeedbackInput
    ) -> tuple[TutoringSemanticResult, str]:
        try:
            semantic = TutoringSemanticResult.model_validate(self._interpreter.interpret(request))
            return semantic, "model"
        except Exception as exc:  # gateway/provider exceptions must not alter learner state
            self._log_failure(request, f"semantic_interpretation_failed:{type(exc).__name__}")
            return _safe_fallback_semantics(request), "fallback"

    def _log_failure(self, request: InterpretFeedbackInput, error_code: str) -> None:
        self._logger.warning(
            "tutoring_failed task_id=%s resource_id=%s error_code=%s",
            request.task_id,
            request.feedback.resource.resource_id,
            error_code,
        )


def _fixture_semantics(request: InterpretFeedbackInput) -> dict[str, object]:
    """Non-production fixture response used only by the existing test gateway mode."""
    return {
        "intent": request.feedback.quick_tag.value if request.feedback.quick_tag else None,
        "difficulty_focus": None,
        "unresolved": False,
        "mastery_evidence_present": False,
        "candidate_reply": None,
        "confidence": 0.5,
    }


def _safe_fallback_semantics(request: InterpretFeedbackInput) -> TutoringSemanticResult:
    summary = " ".join(
        (
            request.feedback.feedback_summary,
            request.feedback.conversation.latest_message_summary,
        )
    )
    if "太简单" in summary:
        # This fallback recognizes only the explicit intent. The deterministic
        # policy still requires controlled mastery evidence before CHALLENGE and
        # never treats this phrase alone as a profile update.
        return TutoringSemanticResult(
            intent="too_easy",
            confidence=1.0,
        )
    return TutoringSemanticResult(
        intent=request.feedback.quick_tag,
        confidence=0.0,
    )


def _select_reply(template: str, semantic: TutoringSemanticResult, use_candidate_reply: bool) -> str:
    candidate = (semantic.candidate_reply or "").strip()
    if (
        use_candidate_reply
        and semantic.confidence >= 0.6
        and candidate
        and ("？" in candidate or "?" in candidate)
        and "画像" not in candidate
        and "发布" not in candidate
    ):
        return candidate
    return template
