"""Standalone V10 tutoring Agent with model understanding and deterministic policy."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import ValidationError

from app.agents.contracts import InterpretFeedbackInput, InterpretFeedbackOutput
from app.agents.observability import record_model_call
from app.agents.prompt_registry import get_prompt
from app.core.config import settings
from app.services.llm_service import OpenAICompatibleGateway, gateway
from app.services.tutoring_policy import (
    TutoringSemanticResult,
    build_feedback_evidence,
    decide_tutoring_action,
)


TUTORING_AGENT_NAME = "tutoring_agent_v3"
SYSTEM_PROMPT = get_prompt("tutoring")


def build_system_prompt(domain_display_name: str | None) -> str:
    display_name = str(domain_display_name or "").strip()
    if not display_name:
        return SYSTEM_PROMPT
    return f"当前教学领域：{display_name}。{SYSTEM_PROMPT}"


class TutoringAgentError(RuntimeError):
    """Controlled boundary error for invalid tutoring input or output."""


class TutoringSemanticInterpreter(Protocol):
    def interpret(self, request: InterpretFeedbackInput) -> TutoringSemanticResult: ...


class OpenAICompatibleTutoringInterpreter:
    """Use the project gateway for validated, OpenAI-compatible structured semantics."""

    def __init__(
        self,
        *,
        model: str | None = None,
        model_gateway: OpenAICompatibleGateway = gateway,
        domain_display_name: str | None = None,
        resource_context: dict[str, Any] | None = None,
    ) -> None:
        self._model = model if model is not None else settings.primary_llm_model
        self._gateway = model_gateway
        self._system_prompt = build_system_prompt(domain_display_name)
        self._resource_context = resource_context or {}

    def interpret(self, request: InterpretFeedbackInput) -> TutoringSemanticResult:
        result, metadata = self._gateway.complete_json(
            model=self._model,
            system_prompt=self._system_prompt,
            payload={
                "feedback_request": request.model_dump(mode="json"),
                "resource_context": self._resource_context,
                "reply_requirement": (
                    "candidate_reply 必须直接回答学习者问题，并严格依据 resource_context；"
                    "不得只复述分类结论。"
                ),
            },
            fixture_factory=lambda: _fixture_semantics(request),
            response_model=TutoringSemanticResult,
        )
        record_model_call(metadata, role="tutoring_model")
        return TutoringSemanticResult.model_validate(result)

    def stream_interpret(
        self,
        request: InterpretFeedbackInput,
        on_json_chunk: Callable[[str], None],
    ) -> TutoringSemanticResult:
        """Run the same semantic request once and forward its JSON fragments."""
        started_at = time.perf_counter()
        fragments: list[str] = []
        try:
            for chunk in self._gateway.stream_json(
                model=self._model,
                system_prompt=self._system_prompt,
                payload={
                    "feedback_request": request.model_dump(mode="json"),
                    "resource_context": self._resource_context,
                    "reply_requirement": (
                        "candidate_reply 必须直接回答学习者问题，并严格依据 resource_context；"
                        "不得只复述分类结论。"
                    ),
                },
                fixture_factory=lambda: _fixture_semantics(request),
            ):
                fragments.append(chunk)
                on_json_chunk(chunk)
            result = TutoringSemanticResult.model_validate(json.loads("".join(fragments)))
        except Exception:
            raise
        else:
            record_model_call(
                {
                    "provider_mode": "live" if settings.openai_api_key else "fixture",
                    "model_name": self._model or "fixture-model",
                    "tokens_input": 0,
                    "tokens_output": 0,
                    "duration_ms": round((time.perf_counter() - started_at) * 1000),
                },
                role="tutoring_model",
            )
            return result


class _StreamingCandidateReply:
    """Incrementally extract the final JSON `candidate_reply` string."""

    _CANDIDATE_FIELD = re.compile(r'"candidate_reply"\s*:\s*"')

    def __init__(self) -> None:
        self._before_candidate = ""
        self._semantic: TutoringSemanticResult | None = None
        self._closed = False
        self._escaping = False
        self._reading_unicode = False
        self._unicode_digits: list[str] = []

    @property
    def semantic(self) -> TutoringSemanticResult | None:
        return self._semantic

    def feed(self, chunk: str) -> str:
        if self._semantic is None:
            self._before_candidate += chunk
            marker = self._CANDIDATE_FIELD.search(self._before_candidate)
            if marker is None:
                return ""
            prefix = self._before_candidate[: marker.start()].rstrip()
            if prefix.endswith(","):
                prefix = prefix[:-1]
            self._semantic = TutoringSemanticResult.model_validate(json.loads(f"{prefix}}}"))
            remainder = self._before_candidate[marker.end() :]
            self._before_candidate = ""
            return self._decode(remainder)
        return self._decode(chunk)

    def _decode(self, value: str) -> str:
        if self._closed:
            return ""
        emitted: list[str] = []
        escapes = {"\"": '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
        for char in value:
            if self._reading_unicode:
                self._unicode_digits.append(char)
                if len(self._unicode_digits) == 4:
                    emitted.append(chr(int("".join(self._unicode_digits), 16)))
                    self._unicode_digits = []
                    self._reading_unicode = False
                    self._escaping = False
                continue
            if self._escaping:
                if char == "u":
                    self._reading_unicode = True
                else:
                    emitted.append(escapes.get(char, char))
                    self._escaping = False
                continue
            if char == "\\":
                self._escaping = True
            elif char == '"':
                self._closed = True
                break
            else:
                emitted.append(char)
        return "".join(emitted)


class TutoringAgent:
    """V10 boundary: model semantics -> controlled policy -> validated response."""

    name = TUTORING_AGENT_NAME
    system_prompt = SYSTEM_PROMPT

    def __init__(
        self,
        interpreter: TutoringSemanticInterpreter | None = None,
        logger: logging.Logger | None = None,
        domain_display_name: str | None = None,
        resource_context: dict[str, Any] | None = None,
    ) -> None:
        self._interpreter = interpreter or OpenAICompatibleTutoringInterpreter(
            domain_display_name=domain_display_name,
            resource_context=resource_context,
        )
        self._logger = logger or logging.getLogger(__name__)
        self.system_prompt = build_system_prompt(domain_display_name)

    def execute(self, request: InterpretFeedbackInput) -> InterpretFeedbackOutput:
        if not isinstance(request, InterpretFeedbackInput):
            self._logger.warning(
                "tutoring_rejected error_code=invalid_interpret_feedback_input_type"
            )
            raise TutoringAgentError("invalid_interpret_feedback_input_type")

        try:
            validated_request = InterpretFeedbackInput.model_validate(
                request.model_dump(mode="python")
            )
        except ValidationError as exc:
            self._log_failure(request, "invalid_interpret_feedback_input")
            raise TutoringAgentError("invalid_interpret_feedback_input") from exc

        semantic, semantic_status = self._interpret_safely(validated_request)
        return self._build_output(validated_request, semantic, semantic_status)

    def stream_execute(
        self,
        request: InterpretFeedbackInput,
        on_reply_delta: Callable[[str], None],
    ) -> InterpretFeedbackOutput:
        """Execute one model call while forwarding reply text before it ends."""
        if not isinstance(request, InterpretFeedbackInput):
            raise TutoringAgentError("invalid_interpret_feedback_input_type")
        validated_request = InterpretFeedbackInput.model_validate(request.model_dump(mode="python"))
        stream_interpret = getattr(self._interpreter, "stream_interpret", None)
        if not callable(stream_interpret):
            output = self.execute(validated_request)
            on_reply_delta(output.reply)
            return output

        parser = _StreamingCandidateReply()
        decision = None
        static_reply_sent = False

        def consume_json_chunk(chunk: str) -> None:
            nonlocal decision, static_reply_sent
            candidate_delta = parser.feed(chunk)
            if parser.semantic is not None and decision is None:
                # The parser has reached a quoted candidate_reply value, so
                # policy may safely decide whether that value is eligible even
                # though its complete text has not arrived yet.
                streaming_semantic = parser.semantic.model_copy(
                    update={"candidate_reply": "streaming"}
                )
                decision = decide_tutoring_action(validated_request, streaming_semantic)
                if not decision.use_candidate_reply:
                    on_reply_delta(decision.reply_template)
                    static_reply_sent = True
            if decision is not None and decision.use_candidate_reply and candidate_delta:
                on_reply_delta(candidate_delta)

        try:
            semantic = TutoringSemanticResult.model_validate(
                stream_interpret(validated_request, consume_json_chunk)
            )
            semantic_status = "model"
        except Exception as exc:
            self._log_failure(validated_request, f"streaming_semantic_interpretation_failed:{type(exc).__name__}")
            semantic = _safe_fallback_semantics(validated_request)
            semantic_status = "fallback"

        output = self._build_output(validated_request, semantic, semantic_status)
        if decision is None or not decision.use_candidate_reply:
            if not static_reply_sent:
                on_reply_delta(output.reply)
        elif output.reply != (semantic.candidate_reply or "").strip():
            # The policy rejected the candidate after full validation. The
            # completed event remains authoritative for the persisted answer.
            on_reply_delta(output.reply)
        return output

    def _build_output(
        self,
        request: InterpretFeedbackInput,
        semantic: TutoringSemanticResult,
        semantic_status: str,
    ) -> InterpretFeedbackOutput:
        decision = decide_tutoring_action(request, semantic)
        reply = _select_reply(decision.reply_template, semantic, decision.use_candidate_reply)
        try:
            output = InterpretFeedbackOutput(
                task_id=request.task_id,
                feedback_intent=decision.feedback_intent,
                recommended_action=decision.recommended_action,
                reply=reply,
                evidence=build_feedback_evidence(request, semantic),
                needs_generation=decision.needs_generation,
                decision_reason=decision.decision_reason,
            )
        except ValidationError as exc:
            self._log_failure(request, "invalid_interpret_feedback_output")
            raise TutoringAgentError("invalid_interpret_feedback_output") from exc
        self._logger.info(
            "tutoring_completed task_id=%s resource_id=%s intent=%s action=%s "
            "needs_generation=%s evidence_count=%s semantic_status=%s confidence=%s",
            output.task_id,
            request.feedback.resource.resource_id,
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
    if "太难" in summary or "没看懂" in summary or "仍然答错" in summary:
        return TutoringSemanticResult(
            intent="too_hard",
            unresolved=any(marker in summary for marker in ("仍然", "还是", "再次")),
            confidence=1.0,
        )
    return TutoringSemanticResult(
        intent=request.feedback.quick_tag,
        confidence=0.0,
    )


def _select_reply(
    template: str, semantic: TutoringSemanticResult, use_candidate_reply: bool
) -> str:
    candidate = (semantic.candidate_reply or "").strip()
    if (
        use_candidate_reply
        and semantic.confidence >= 0.6
        and candidate
        and "画像" not in candidate
        and "发布" not in candidate
    ):
        return candidate
    return template
