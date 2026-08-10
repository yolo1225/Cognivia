from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.contracts import (
    ConversationSummary,
    EvidenceRef,
    EvidenceType,
    FeedbackContext,
    FeedbackIntent,
    InterpretFeedbackInput,
    ResourceSummary,
    TaskContext,
)
from app.agents.v2_observability import collect_model_calls
from app.agents.v2_tutoring_agent import V2TutoringAgent
from app.models import (
    AgentMessageRecord,
    AgentRun,
    Feedback,
    GenerationTask,
    Learner,
    LearnerProfile,
    LearningResource,
    TutoringMessage,
    TutoringSession,
)
from app.services.feedback_service import create_feedback_task
from app.services.profile_service import public_id
from app.services.v2_contract_mapping import profile_snapshot


TUTORING_AGENT_NAME = "tutoring_agent"


def _agent_message(
    db: Session,
    *,
    session_id: str,
    sender: str,
    receiver: str,
    message_type: str,
    payload: dict,
) -> None:
    db.add(
        AgentMessageRecord(
            session_id=session_id,
            task_id=session_id,
            sender=sender,
            receiver=receiver,
            message_type=message_type,
            payload_summary_json=payload,
        )
    )


def _supporting_evidence(values: list[dict]) -> list[EvidenceRef]:
    evidence: list[EvidenceRef] = []
    allowed = {item.value for item in EvidenceType}
    for index, item in enumerate(values[:50]):
        evidence_type = str(item.get("evidence_type") or item.get("type") or "")
        if evidence_type not in allowed:
            continue
        evidence.append(
            EvidenceRef(
                evidence_id=str(item.get("evidence_id") or f"support_{index}_{public_id('ev')}")[:64],
                evidence_type=evidence_type,
                summary=str(item.get("summary") or "导学会话提供的结构化证据")[:500],
                knowledge_id=str(item["knowledge_id"])[:64]
                if item.get("knowledge_id")
                else None,
                source_ref_id=str(item["source_ref_id"])[:128]
                if item.get("source_ref_id")
                else None,
                confidence=max(0.0, min(1.0, float(item.get("confidence") or 0))),
                confirmed=bool(item.get("confirmed", False)),
            )
        )
    return evidence


def create_session(
    db: Session, *, learner: Learner, resource: LearningResource | None
) -> TutoringSession:
    if resource is None:
        raise ValueError("P0 tutoring sessions must be attached to a learning resource")
    session = TutoringSession(
        public_id=public_id("tutor"),
        learner_id=learner.id,
        resource_id=resource.id,
        status="active",
        turn_count=0,
    )
    db.add(session)
    db.flush()
    return session


def add_learner_message(
    db: Session,
    *,
    session: TutoringSession,
    profile: LearnerProfile,
    content: str,
    evidence: list[dict] | None = None,
) -> tuple[TutoringMessage, TutoringMessage, Feedback, GenerationTask | None, dict]:
    if session.status != "active":
        raise ValueError("tutoring session is not active")
    resource = db.get(LearningResource, session.resource_id) if session.resource_id else None
    learner = db.get(Learner, session.learner_id)
    if learner is None:
        raise ValueError("learner not found")
    if resource is None:
        raise ValueError("tutoring session resource not found")

    learner_message = TutoringMessage(
        public_id=public_id("msg"),
        session_id=session.id,
        sender="learner",
        message_type="question",
        content=content,
    )
    db.add(learner_message)
    db.flush()
    session.turn_count += 1
    previous_feedback = db.scalar(
        select(Feedback)
        .where(Feedback.tutoring_session_id == session.id)
        .order_by(Feedback.id.desc())
    )
    source_ids = [
        str(item.get("knowledge_id"))
        for item in (resource.sources_json or [])
        if isinstance(item, dict) and item.get("knowledge_id")
    ]
    verification_evidence: list[dict] = []
    if (
        session.turn_count >= 2
        and previous_feedback
        and previous_feedback.feedback_intent in {"too_easy", "too_hard", "confusing"}
        and len(content) >= 20
    ):
        verification_evidence = [
            {
                "type": "validated_behavior",
                "summary": "follow-up tutoring response supplied after a verification prompt",
                "knowledge_id": knowledge_id,
                "confidence": 0.75,
                "confirmed": True,
            }
            for knowledge_id in source_ids[:8]
        ]
    feedback = Feedback(
        resource_id=resource.id,
        learner_id=learner.id,
        rating=None,
        feedback_type="tutoring_message",
        feedback_summary_json={"message_summary": content[:120]},
        triggered_action="pending",
        comment=content[:2000],
        tutoring_session_id=session.id,
        tutoring_message_id=learner_message.id,
        feedback_intent=None,
        recommended_action=None,
        profile_update_required=False,
        profile_change_evidence_json=[],
        decision_confidence=0,
        decision_reason="pending_v2_tutoring",
    )
    db.add(feedback)
    db.flush()
    learner_message.feedback_id = feedback.id

    previous_intents = list(
        db.scalars(
            select(Feedback.feedback_intent)
            .where(Feedback.tutoring_session_id == session.id)
            .where(Feedback.id != feedback.id)
            .where(Feedback.feedback_intent.is_not(None))
            .order_by(Feedback.id.desc())
            .limit(20)
        )
    )
    context = TaskContext(
        task_id=session.public_id,
        session_id=session.public_id,
        trigger_type="resource_feedback",
        execution_mode="auto",
        learner_id=learner.public_id,
        profile_id=profile.public_id,
        domain_code=profile.domain_code,
        resource_types=[resource.resource_type],
        learning_goal="根据导学反馈提供解释、复核或挑战任务",
        resource_id=resource.public_id,
        feedback_id=str(feedback.id),
        tutoring_session_id=session.public_id,
        tutoring_message_id=learner_message.public_id,
    )
    safe_evidence = _supporting_evidence([*(evidence or []), *verification_evidence])
    request = InterpretFeedbackInput(
        task_id=session.public_id,
        context=context,
        profile=profile_snapshot(profile),
        feedback=FeedbackContext(
            resource=ResourceSummary(
                resource_id=resource.public_id,
                resource_type=resource.resource_type,
                title=resource.title,
                difficulty=resource.difficulty,
                source_ref_ids=[
                    str(item.get("source_ref_id"))
                    for item in (resource.sources_json or [])
                    if isinstance(item, dict) and item.get("source_ref_id")
                ],
            ),
            conversation=ConversationSummary(
                tutoring_session_id=session.public_id,
                turn_count=session.turn_count,
                latest_message_summary=content[:500],
                previous_intents=[
                    FeedbackIntent(item)
                    for item in previous_intents
                    if item in {intent.value for intent in FeedbackIntent}
                ],
            ),
            feedback_summary=content[:500],
            supporting_evidence=safe_evidence,
        ),
    )
    started_at = time.perf_counter()
    run = AgentRun(
        generation_task_id=None,
        agent_name=TUTORING_AGENT_NAME,
        status="running",
        input_summary_json={
            "task_id": session.public_id,
            "resource_id": resource.public_id,
            "turn_count": session.turn_count,
            "evidence_count": len(safe_evidence),
        },
        output_summary_json={},
        prompt_version="v2",
    )
    db.add(run)
    _agent_message(
        db,
        session_id=session.public_id,
        sender="orchestrator_agent",
        receiver=TUTORING_AGENT_NAME,
        message_type="command",
        payload={"node_name": "interpret_feedback", "turn_count": session.turn_count},
    )
    with collect_model_calls() as collector:
        output_model = V2TutoringAgent().execute(request)
    model_calls = collector.snapshot()
    output = output_model.model_dump(mode="json")
    action = output_model.recommended_action.value
    all_evidence = [
        *[item.model_dump(mode="json") for item in output_model.evidence],
        *[item.model_dump(mode="json") for item in safe_evidence],
    ]
    feedback.triggered_action = action
    feedback.feedback_intent = output_model.feedback_intent.value
    feedback.recommended_action = action
    feedback.profile_change_evidence_json = all_evidence
    feedback.decision_confidence = 0.75 if safe_evidence else 0.45
    feedback.decision_reason = output_model.decision_reason
    run.status = "completed"
    run.output_summary_json = {
        "task_id": session.public_id,
        "feedback_intent": output_model.feedback_intent.value,
        "recommended_action": action,
        "needs_generation": output_model.needs_generation,
        "evidence_count": len(all_evidence),
        "provider_mode": model_calls[0]["provider_mode"] if model_calls else "fallback",
        "model_calls": model_calls,
    }
    run.llm_calls = len(model_calls)
    run.tokens_input = sum(item["tokens_input"] for item in model_calls)
    run.tokens_output = sum(item["tokens_output"] for item in model_calls)
    run.tokens_used = run.tokens_input + run.tokens_output
    run.model_name = model_calls[0]["model_name"] if model_calls else None
    run.duration_ms = round((time.perf_counter() - started_at) * 1000)
    _agent_message(
        db,
        session_id=session.public_id,
        sender=TUTORING_AGENT_NAME,
        receiver="orchestrator_agent",
        message_type="result",
        payload={
            "node_name": "interpret_feedback",
            "feedback_intent": output_model.feedback_intent.value,
            "recommended_action": action,
            "needs_generation": output_model.needs_generation,
        },
    )
    reply = TutoringMessage(
        public_id=public_id("msg"),
        session_id=session.id,
        sender="tutoring_agent",
        message_type="hint" if session.turn_count == 1 else "explanation",
        content=output_model.reply,
        feedback_id=feedback.id,
    )
    db.add(reply)
    db.flush()

    task = None
    if output_model.needs_generation and action in {
        "review",
        "challenge",
        "explain",
        "regenerate",
    }:
        task = create_feedback_task(
            db,
            learner=learner,
            profile=profile,
            resource=resource,
            feedback=feedback,
            resource_types=[resource.resource_type],
        )
    return learner_message, reply, feedback, task, output


def serialize_session(db: Session, session: TutoringSession) -> dict:
    messages = list(
        db.scalars(
            select(TutoringMessage)
            .where(TutoringMessage.session_id == session.id)
            .order_by(TutoringMessage.id)
        )
    )
    return {
        "session_id": session.public_id,
        "status": session.status,
        "turn_count": session.turn_count,
        "messages": [
            {
                "message_id": item.public_id,
                "sender": item.sender,
                "message_type": item.message_type,
                "content": item.content,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in messages
        ],
    }
