"""Deterministic teaching policy for the standalone V3 tutoring Agent.

The policy deliberately owns business decisions.  A language model may describe a
learner's feedback, but it may not decide whether a learner profile changes or
whether a task is created.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from pydantic import BaseModel, Field

from app.agents.contracts import (
    EvidenceRef,
    EvidenceType,
    FeedbackIntent,
    InterpretFeedbackInput,
    RecommendedAction,
)


SEMANTIC_CONFIDENCE_THRESHOLD = 0.6
CONTROLLED_MASTERY_EVIDENCE_TYPES = {
    EvidenceType.SCORED_QUIZ,
    EvidenceType.VALIDATED_BEHAVIOR,
}
DIFFICULTY_INTENTS = {FeedbackIntent.TOO_HARD, FeedbackIntent.CONFUSING}


class TutoringSemanticResult(BaseModel):
    """Internal, model-produced description of feedback; it is not a V3 contract."""

    intent: FeedbackIntent | None = None
    difficulty_focus: str | None = Field(default=None, max_length=300)
    unresolved: bool = False
    mastery_evidence_present: bool = False
    candidate_reply: str | None = Field(default=None, max_length=2000)
    confidence: float = Field(ge=0, le=1)


@dataclass(frozen=True)
class TutoringPolicyDecision:
    feedback_intent: FeedbackIntent
    recommended_action: RecommendedAction
    needs_generation: bool
    decision_reason: str
    reply_template: str
    use_candidate_reply: bool = False


def decide_tutoring_action(
    request: InterpretFeedbackInput,
    semantic: TutoringSemanticResult,
) -> TutoringPolicyDecision:
    """Choose the only allowed next action from controlled input and semantics."""
    quick_tag = request.feedback.quick_tag

    # A suspected resource error has priority and must never become a learner-level judgement.
    if quick_tag is FeedbackIntent.INCORRECT or semantic.intent is FeedbackIntent.INCORRECT:
        return _decision(
            FeedbackIntent.INCORRECT,
            RecommendedAction.REVIEW,
            True,
            "疑似资源事实或表述错误，必须重新检索来源并复核；该反馈不作为能力下降证据。",
            "已记录疑似资源错误。我会请求复核来源和内容，这不会影响你的能力画像。",
        )

    # A first explicit difficulty statement is safe to classify deterministically:
    # it only records a no-change teaching interaction and never serves as profile
    # evidence.  This keeps the normal-demo path stable when structured model
    # semantics are unavailable or under-classify an otherwise unambiguous phrase.
    explicit_difficulty = _explicit_difficulty_intent(request)
    if explicit_difficulty is not None and request.feedback.conversation.turn_count == 1:
        return _decision(
            explicit_difficulty,
            RecommendedAction.NO_CHANGE,
            False,
            "首次明确的困难反馈仅返回解释与定位提示；不更新画像，也不创建下游任务。",
            _difficulty_follow_up(semantic.difficulty_focus),
            use_candidate_reply=True,
        )

    if (
        semantic.intent is None
        and semantic.confidence >= SEMANTIC_CONFIDENCE_THRESHOLD
        and str(semantic.candidate_reply or "").strip()
    ):
        return _decision(
            FeedbackIntent.OTHER,
            RecommendedAction.NO_CHANGE,
            False,
            "已依据当前资源回答学习问题；本轮没有形成可更新画像的结构化证据。",
            "我会依据当前资源回答这个问题。",
            use_candidate_reply=True,
        )
    if semantic.confidence < SEMANTIC_CONFIDENCE_THRESHOLD or semantic.intent is None:
        return _safe_follow_up("反馈意图置信度不足，先追问而不创建下游任务。")

    if quick_tag is not None and quick_tag is not semantic.intent:
        return _safe_follow_up("自然语言理解与快捷标签冲突，先澄清反馈意图。")

    intent = semantic.intent
    if intent in DIFFICULTY_INTENTS:
        if _same_difficulty_remains_unresolved(request, intent, semantic):
            return _decision(
                intent,
                RecommendedAction.EXPLAIN,
                True,
                "同一困难在后续轮次仍未解决，请求后续链路生成可审核的补救解释；困难反馈本身不更新画像。",
                "我会为这个困难点准备一份更分步骤、可追溯来源的补救解释。",
            )
        return _decision(
            intent,
            RecommendedAction.NO_CHANGE,
            False,
            "首次或尚未确认的困难反馈仅返回定位提示；不更新画像，也不创建下游任务。",
            _difficulty_follow_up(semantic.difficulty_focus),
            use_candidate_reply=True,
        )

    if intent is FeedbackIntent.TOO_EASY:
        if _has_controlled_mastery_evidence(request):
            return _decision(
                intent,
                RecommendedAction.CHALLENGE,
                True,
                "存在已确认的计分题或学习行为证据，可请求生成挑战任务；画像是否更新仍由学情分析 Agent 判断。",
                "已确认你具备相关掌握证据。我会请求生成一项关联知识点的挑战任务。",
            )
        return _decision(
            intent,
            RecommendedAction.ASK_FOLLOW_UP,
            False,
            "“太简单”尚无受控掌握证据，先用迁移问题或小任务确认掌握情况。",
            "你愿意先用一个迁移小问题说明你的解题思路吗？我会据此确认是否需要挑战任务。",
            use_candidate_reply=True,
        )

    if intent is FeedbackIntent.HELPFUL:
        return _decision(
            intent,
            RecommendedAction.NO_CHANGE,
            False,
            "正向主观反馈仅作为辅助证据，本轮不改变画像或创建资源任务。",
            "已记录这次反馈。后续计分结果或已确认学习行为会作为画像判断的证据。",
        )

    if intent is FeedbackIntent.OTHER and str(semantic.candidate_reply or "").strip():
        return _decision(
            intent,
            RecommendedAction.NO_CHANGE,
            False,
            "已直接回答当前资源范围内的学习请求；本轮不构成画像更新证据。",
            "我会依据当前资源回答这个问题。",
            use_candidate_reply=True,
        )

    return _safe_follow_up("反馈未能归入可执行教学意图，先追问具体学习目标。")


def build_feedback_evidence(
    request: InterpretFeedbackInput,
    semantic: TutoringSemanticResult,
) -> list[EvidenceRef]:
    """Preserve controlled evidence and add one safe, non-verbatim feedback reference."""
    evidence = list(request.feedback.supporting_evidence[:49])
    conversation = request.feedback.conversation
    evidence_key = (
        f"{request.task_id}:{conversation.tutoring_session_id}:"
        f"{conversation.turn_count}:{request.context.tutoring_message_id or ''}"
    )
    evidence.append(
        EvidenceRef(
            evidence_id=f"tutoring_{sha256(evidence_key.encode()).hexdigest()[:32]}",
            evidence_type=(
                EvidenceType.QUICK_FEEDBACK
                if request.feedback.quick_tag is not None
                else EvidenceType.NATURAL_LANGUAGE
            ),
            summary=(
                f"第 {conversation.turn_count} 轮导学反馈"
                f"（{request.feedback.quick_tag or 'natural_language'}）"
            ),
            confidence=round(min(max(semantic.confidence, 0.0), 1.0), 2),
            confirmed=False,
        )
    )
    return evidence


def _same_difficulty_remains_unresolved(
    request: InterpretFeedbackInput,
    intent: FeedbackIntent,
    semantic: TutoringSemanticResult,
) -> bool:
    conversation = request.feedback.conversation
    return (
        conversation.turn_count >= 2
        and intent in conversation.previous_intents
        and semantic.unresolved
    )


def _has_controlled_mastery_evidence(request: InterpretFeedbackInput) -> bool:
    return any(
        evidence.evidence_type in CONTROLLED_MASTERY_EVIDENCE_TYPES
        and evidence.confirmed
        and evidence.confidence >= 0.7
        for evidence in request.feedback.supporting_evidence
    )


def _difficulty_follow_up(difficulty_focus: str | None) -> str:
    if difficulty_focus:
        return f"你在“{difficulty_focus}”的哪个步骤卡住了：概念理解、操作过程，还是结果验证？"
    return "你具体卡在概念理解、操作过程，还是结果验证？我先据此给出针对性提示。"


def _explicit_difficulty_intent(request: InterpretFeedbackInput) -> FeedbackIntent | None:
    summary = " ".join(
        (
            request.feedback.feedback_summary,
            request.feedback.conversation.latest_message_summary,
        )
    )
    if "太难" in summary:
        return FeedbackIntent.TOO_HARD
    return None


def _safe_follow_up(reason: str) -> TutoringPolicyDecision:
    return _decision(
        FeedbackIntent.OTHER,
        RecommendedAction.ASK_FOLLOW_UP,
        False,
        reason,
        "请告诉我你希望确认的具体概念、步骤或结果，我会先帮你定位下一步。",
    )


def _decision(
    feedback_intent: FeedbackIntent,
    recommended_action: RecommendedAction,
    needs_generation: bool,
    decision_reason: str,
    reply_template: str,
    *,
    use_candidate_reply: bool = False,
) -> TutoringPolicyDecision:
    return TutoringPolicyDecision(
        feedback_intent=feedback_intent,
        recommended_action=recommended_action,
        needs_generation=needs_generation,
        decision_reason=decision_reason,
        reply_template=reply_template,
        use_candidate_reply=use_candidate_reply,
    )
