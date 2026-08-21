from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import case, select
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
from app.agents.observability import collect_model_calls
from app.agents.prompt_registry import PROMPT_VERSION, prompt_hash
from app.agents.tutoring_agent import TutoringAgent
from app.models import (
    AgentMessageRecord,
    AgentRun,
    AnswerRecord,
    DiagnosticQuestion,
    Domain,
    Feedback,
    GenerationTask,
    Learner,
    LearnerProfile,
    KnowledgeItem,
    LearningPath,
    LearningResource,
    TutoringMessage,
    TutoringSession,
)
from app.services.feedback_service import create_feedback_task
from app.services.profile_service import public_id
from app.services.contract_mapping import profile_snapshot
from app.core.compatibility import AGENT_CONTRACT_VERSION
from app.services.resource_tutoring_service import (
    TutoringAnswer,
    build_resource_tutoring_context,
)


TUTORING_AGENT_NAME = "tutoring_agent"


@dataclass(frozen=True)
class TutoringTurnResult:
    learner_message: TutoringMessage
    reply: TutoringMessage
    feedback: Feedback
    task: GenerationTask | None
    output: dict[str, Any]

    def serialize(self) -> dict[str, Any]:
        metadata = self.reply.metadata_json or {}
        return {
            "session_id": self.output["session_id"],
            "reply": {
                "message_id": self.reply.public_id,
                "message_type": self.reply.message_type,
                "content": self.reply.content,
                "sources": metadata.get("sources", []),
                "scope_status": metadata.get("scope_status"),
                "assessment": metadata.get("assessment"),
                "assessment_unavailable": metadata.get("assessment_unavailable"),
            },
            "feedback_id": str(self.feedback.id),
            "feedback_intent": self.feedback.feedback_intent,
            "recommended_action": self.feedback.recommended_action,
            "profile_update_required": bool(self.feedback.profile_update_required),
            "decision_reason": self.feedback.decision_reason,
            "task_id": self.task.public_id if self.task else None,
        }


def _current_path_knowledge_id(
    db: Session, *, learner: Learner, domain_code: str
) -> str | None:
    path = db.scalar(
        select(LearningPath)
        .where(
            LearningPath.learner_id == learner.id,
            LearningPath.domain_code == domain_code,
            LearningPath.status == "active",
        )
        .order_by(LearningPath.id.desc())
    )
    payload = path.path_json or {} if path is not None else {}
    node_id = payload.get("current_node_id")
    node = (payload.get("node_states") or {}).get(node_id, {}) if node_id else {}
    knowledge_id = node.get("knowledge_id") if isinstance(node, dict) else None
    return str(knowledge_id) if knowledge_id else None


def _formal_assessment(
    db: Session,
    *,
    session: TutoringSession,
    learner: Learner,
    resource: LearningResource,
    feedback: Feedback,
    needed: bool,
) -> tuple[dict[str, Any] | None, str | None]:
    if not needed:
        return None, None
    knowledge_ids = [
        str(item.get("knowledge_id"))
        for item in (resource.sources_json or [])
        if isinstance(item, dict) and item.get("knowledge_id")
    ]
    if not knowledge_ids:
        return None, "assessment_unavailable"
    attempted_question_ids = [
        record.question_id
        for record in db.scalars(
            select(AnswerRecord).where(AnswerRecord.learner_id == learner.id)
        )
        if (record.answer_summary_json or {}).get("tutoring_session_id") == session.id
    ]
    source_task = db.get(GenerationTask, resource.generation_task_id)
    if source_task is None:
        return None, "assessment_unavailable"
    current_knowledge_id = _current_path_knowledge_id(
        db, learner=learner, domain_code=source_task.domain_code
    )
    current_first = case(
        (KnowledgeItem.public_id == current_knowledge_id, 0),
        else_=1,
    )
    question = db.scalar(
        select(DiagnosticQuestion)
        .join(KnowledgeItem, KnowledgeItem.id == DiagnosticQuestion.knowledge_item_id)
        .where(
            DiagnosticQuestion.domain_code == source_task.domain_code,
            DiagnosticQuestion.question_type == "single_choice",
            KnowledgeItem.public_id.in_(knowledge_ids),
            DiagnosticQuestion.id.not_in(attempted_question_ids),
        )
        .order_by(current_first, DiagnosticQuestion.difficulty, DiagnosticQuestion.id)
    )
    if question is None:
        # A resource may cite a knowledge item with only one validation question.
        # Keep the second controlled check inside the same domain and session,
        # while allowing another domain question after source-linked questions
        # have been exhausted.
        question = db.scalar(
            select(DiagnosticQuestion)
            .join(KnowledgeItem, KnowledgeItem.id == DiagnosticQuestion.knowledge_item_id)
            .where(
                DiagnosticQuestion.domain_code == source_task.domain_code,
                DiagnosticQuestion.question_type == "single_choice",
                DiagnosticQuestion.id.not_in(attempted_question_ids),
            )
            .order_by(current_first, DiagnosticQuestion.difficulty, DiagnosticQuestion.id)
        )
    if question is None:
        return None, "assessment_unavailable"
    knowledge = db.get(KnowledgeItem, question.knowledge_item_id)
    assessment_id = public_id("tval")
    return {
        "assessment_id": assessment_id,
        "question_id": question.public_id,
        "knowledge_id": knowledge.public_id,
        "question_type": question.question_type,
        "difficulty": question.difficulty,
        "stem": question.stem,
        "options": question.options_json or [],
        "status": "pending",
        "feedback_id": str(feedback.id),
        "session_id": session.public_id,
        "learner_id": learner.public_id,
        "domain_code": source_task.domain_code,
    }, None


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
                evidence_id=str(item.get("evidence_id") or f"support_{index}_{public_id('ev')}")[
                    :64
                ],
                evidence_type=evidence_type,
                summary=str(item.get("summary") or "导学会话提供的结构化证据")[:500],
                knowledge_id=str(item["knowledge_id"])[:64] if item.get("knowledge_id") else None,
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
    existing = db.scalar(
        select(TutoringSession)
        .where(TutoringSession.learner_id == learner.id)
        .where(TutoringSession.resource_id == resource.id)
        .where(TutoringSession.status == "active")
        .order_by(TutoringSession.id.desc())
    )
    if existing is not None:
        return existing
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


def create_streaming_messages(
    db: Session, *, session: TutoringSession, content: str
) -> tuple[TutoringMessage, TutoringMessage, LearningResource]:
    if session.status != "active":
        raise ValueError("tutoring session is not active")
    resource = db.get(LearningResource, session.resource_id) if session.resource_id else None
    if resource is None:
        raise ValueError("tutoring session resource not found")
    learner = db.get(Learner, session.learner_id)
    source_task = db.get(GenerationTask, resource.generation_task_id)
    if learner is None or source_task is None or source_task.domain_code != learner.target_domain:
        raise ValueError("tutoring_domain_mismatch")
    domain = db.scalar(select(Domain).where(Domain.domain_code == source_task.domain_code))
    if domain is None or not domain.name.strip():
        raise ValueError("tutoring_domain_not_found")
    learner_message = TutoringMessage(
        public_id=public_id("msg"),
        session_id=session.id,
        sender="learner",
        message_type="question",
        content=content,
        metadata_json={"stream_status": "completed"},
    )
    reply = TutoringMessage(
        public_id=public_id("msg"),
        session_id=session.id,
        sender="tutoring_agent",
        message_type="explanation",
        content="",
        metadata_json={"stream_status": "streaming"},
    )
    db.add_all([learner_message, reply])
    session.turn_count += 1
    db.flush()
    return learner_message, reply, resource


def update_streaming_reply(
    db: Session,
    *,
    reply: TutoringMessage,
    content: str | None = None,
    status: str | None = None,
    sources: list[dict[str, str]] | None = None,
    scope_status: str | None = None,
    assessment: dict | None = None,
    error_code: str | None = None,
) -> None:
    metadata = dict(reply.metadata_json or {})
    if status:
        metadata["stream_status"] = status
    if sources is not None:
        metadata["sources"] = sources
    if scope_status is not None:
        metadata["scope_status"] = scope_status
    if assessment is not None:
        metadata["assessment"] = assessment
    if error_code:
        metadata["error_code"] = error_code
    if content is not None:
        reply.content = content
    reply.metadata_json = metadata
    db.add(reply)
    db.commit()


def add_learner_message(
    db: Session,
    *,
    session: TutoringSession,
    profile: LearnerProfile,
    content: str,
    evidence: list[dict] | None = None,
    prepared_learner_message: TutoringMessage | None = None,
    prepared_reply: TutoringMessage | None = None,
) -> tuple[TutoringMessage, TutoringMessage, Feedback, GenerationTask | None, dict]:
    if session.status != "active":
        raise ValueError("tutoring session is not active")
    resource = db.get(LearningResource, session.resource_id) if session.resource_id else None
    learner = db.get(Learner, session.learner_id)
    if learner is None:
        raise ValueError("learner not found")
    if resource is None:
        raise ValueError("tutoring session resource not found")
    source_task = db.get(GenerationTask, resource.generation_task_id)
    if (
        source_task is None
        or source_task.domain_code != profile.domain_code
        or source_task.domain_code != learner.target_domain
    ):
        raise ValueError("tutoring_domain_mismatch")
    domain = db.scalar(select(Domain).where(Domain.domain_code == source_task.domain_code))
    if domain is None or not domain.name.strip():
        raise ValueError("tutoring_domain_not_found")

    if prepared_learner_message is not None:
        if (
            prepared_learner_message.session_id != session.id
            or prepared_learner_message.sender != "learner"
            or prepared_reply is None
            or prepared_reply.session_id != session.id
            or prepared_reply.sender != "tutoring_agent"
        ):
            raise ValueError("invalid prepared tutoring messages")
        learner_message = prepared_learner_message
    else:
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
        decision_reason="pending_v3_tutoring",
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
    # Natural-language conversation is never self-validating evidence. Only an
    # explicit, externally scored assessment may be supplied through evidence.
    safe_evidence = _supporting_evidence(evidence or [])
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
            "session_id": session.public_id,
            "resource_id": resource.public_id,
            "turn_count": session.turn_count,
            "evidence_count": len(safe_evidence),
        },
        output_summary_json={},
        prompt_version=PROMPT_VERSION,
        prompt_hash=prompt_hash("tutoring"),
        contract_version=AGENT_CONTRACT_VERSION,
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
    resource_context, tutoring_sources, tutoring_scope, _ = build_resource_tutoring_context(
        db, session=session, resource=resource, question=content
    )
    with collect_model_calls() as collector:
        output_model = TutoringAgent(
            domain_display_name=domain.name,
            resource_context=resource_context,
        ).execute(request)
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
    contextual_answer = TutoringAnswer(
        answer=output_model.reply,
        sources=tutoring_sources,
        scope_status=tutoring_scope,
        assessment=None,
    )
    output["reply"] = contextual_answer.answer
    output["sources"] = contextual_answer.sources
    output["scope_status"] = contextual_answer.scope_status
    assessment, assessment_unavailable = _formal_assessment(
        db,
        session=session,
        learner=learner,
        resource=resource,
        feedback=feedback,
        needed=output_model.feedback_intent.value in {"too_hard", "too_easy"},
    )
    output["assessment"] = assessment
    output["assessment_unavailable"] = assessment_unavailable
    output["session_id"] = session.public_id
    reply = prepared_reply or TutoringMessage(
        public_id=public_id("msg"),
        session_id=session.id,
        sender="tutoring_agent",
        message_type="hint" if session.turn_count == 1 else "explanation",
        content="",
    )
    reply.message_type = "hint" if session.turn_count == 1 else "explanation"
    reply.content = contextual_answer.answer
    reply.metadata_json = {
        "sources": contextual_answer.sources,
        "scope_status": contextual_answer.scope_status,
        "assessment": assessment,
        "assessment_unavailable": assessment_unavailable,
        "stream_status": "completed",
    }
    reply.feedback_id = feedback.id
    db.add(reply)
    db.flush()

    task = None
    has_confirmed_assessment = any(
        item.evidence_type.value in {"scored_quiz", "validated_behavior"}
        and item.confirmed
        and item.confidence >= 0.7
        for item in safe_evidence
    )
    # Resource correctness is independently reviewable and never changes mastery.
    if action == "review" or (
        has_confirmed_assessment
        and output_model.needs_generation
        and action in {"challenge", "explain", "regenerate"}
    ):
        task = create_feedback_task(
            db,
            learner=learner,
            profile=profile,
            resource=resource,
            feedback=feedback,
            resource_types=[resource.resource_type],
        )
    return learner_message, reply, feedback, task, output


def execute_tutoring_turn(
    db: Session,
    *,
    session: TutoringSession,
    profile: LearnerProfile,
    content: str,
    evidence: list[dict] | None = None,
    prepared_learner_message: TutoringMessage | None = None,
    prepared_reply: TutoringMessage | None = None,
) -> TutoringTurnResult:
    learner_message, reply, feedback, task, output = add_learner_message(
        db,
        session=session,
        profile=profile,
        content=content,
        evidence=evidence,
        prepared_learner_message=prepared_learner_message,
        prepared_reply=prepared_reply,
    )
    return TutoringTurnResult(learner_message, reply, feedback, task, output)


def _assessment_message(
    db: Session, *, session: TutoringSession, assessment_id: str
) -> tuple[TutoringMessage, dict[str, Any]]:
    messages = db.scalars(
        select(TutoringMessage)
        .where(TutoringMessage.session_id == session.id)
        .order_by(TutoringMessage.id.desc())
    )
    for message in messages:
        assessment = (message.metadata_json or {}).get("assessment")
        if isinstance(assessment, dict) and assessment.get("assessment_id") == assessment_id:
            return message, assessment
    raise ValueError("tutoring_assessment_not_found")


def _profile_evidence_gate(
    db: Session, *, session: TutoringSession, records: list[AnswerRecord]
) -> bool:
    high_by_knowledge: dict[int, list[AnswerRecord]] = {}
    high_scores: list[AnswerRecord] = []
    failed_scores: list[AnswerRecord] = []
    for record in records:
        if record.score >= 0.75:
            high_scores.append(record)
            high_by_knowledge.setdefault(record.knowledge_item_id, []).append(record)
        elif record.score < 0.4:
            failed_scores.append(record)
    three_same_knowledge = any(len(items) >= 3 for items in high_by_knowledge.values())
    two_independent_with_application = len(high_scores) >= 2 and any(
        question is not None and question.difficulty >= 3
        for item in high_scores
        for question in [db.get(DiagnosticQuestion, item.question_id)]
    )
    session_feedback = list(
        db.scalars(select(Feedback).where(Feedback.tutoring_session_id == session.id))
    )
    resource_error_reported = any(item.feedback_intent == "incorrect" for item in session_feedback)
    remedial_explanations = sum(item.recommended_action == "explain" for item in session_feedback)
    downward_gate = (
        len(failed_scores) >= 2 and remedial_explanations >= 1 and not resource_error_reported
    )
    return three_same_knowledge or two_independent_with_application or downward_gate


def submit_assessment_answer(
    db: Session,
    *,
    session: TutoringSession,
    profile: LearnerProfile,
    assessment_id: str,
    answer: Any,
) -> tuple[AnswerRecord, Feedback, GenerationTask | None, dict[str, Any]]:
    message, assessment = _assessment_message(db, session=session, assessment_id=assessment_id)
    question = db.scalar(
        select(DiagnosticQuestion).where(
            DiagnosticQuestion.public_id == assessment.get("question_id")
        )
    )
    feedback = db.get(Feedback, int(assessment.get("feedback_id") or 0))
    learner = db.get(Learner, session.learner_id)
    resource = db.get(LearningResource, session.resource_id)
    if question is None or feedback is None or learner is None or resource is None:
        raise ValueError("tutoring_assessment_source_missing")
    if assessment.get("learner_id") != learner.public_id or learner.id != profile.learner_id:
        raise ValueError("tutoring_assessment_learner_mismatch")
    source_task = db.get(GenerationTask, resource.generation_task_id)
    if (
        source_task is None
        or question.domain_code != source_task.domain_code
        or question.knowledge_item_id
        != int(
            message.metadata_json["assessment"].get("knowledge_item_id", question.knowledge_item_id)
        )
    ):
        raise ValueError("tutoring_assessment_domain_mismatch")

    existing = next(
        (
            record
            for record in db.scalars(
                select(AnswerRecord).where(AnswerRecord.learner_id == learner.id)
            )
            if (record.answer_summary_json or {}).get("assessment_id") == assessment_id
        ),
        None,
    )
    task = db.scalar(select(GenerationTask).where(GenerationTask.source_feedback_id == feedback.id))
    if existing is not None:
        summary = existing.answer_summary_json or {}
        return (
            existing,
            feedback,
            task,
            {
                "confirmed": bool(summary.get("confirmed")),
                "profile_update_required": bool(feedback.profile_update_required),
                "decision_reason": feedback.decision_reason,
            },
        )

    try:
        selected = int(answer)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_single_choice_answer") from exc
    correct = int((question.answer_key_json or {}).get("correct_option", -1))
    if selected < 0 or selected >= len(question.options_json or []):
        raise ValueError("invalid_single_choice_answer")
    is_correct = selected == correct
    score = 1.0 if is_correct else 0.0
    evidence_id = f"answer_record:pending:{assessment_id}"
    record = AnswerRecord(
        learner_id=learner.id,
        question_id=question.id,
        knowledge_item_id=question.knowledge_item_id,
        score=score,
        is_correct=is_correct,
        answer_summary_json={
            "evidence_type": "tutoring_validation",
            "contract_evidence_type": "scored_quiz",
            "assessment_id": assessment_id,
            "difficulty": question.difficulty,
            "confidence": 0.9,
            "confirmed": True,
            "feedback_id": feedback.id,
            "tutoring_session_id": session.id,
            "consumed_by_profile_id": None,
        },
    )
    db.add(record)
    db.flush()
    evidence_id = f"answer_record:{record.id}"
    summary = dict(record.answer_summary_json or {})
    summary["evidence_id"] = evidence_id
    record.answer_summary_json = summary
    assessment = dict(assessment)
    assessment.update({"status": "scored", "score": score, "is_correct": is_correct})
    metadata = dict(message.metadata_json or {})
    metadata["assessment"] = assessment
    message.metadata_json = metadata

    knowledge = db.get(KnowledgeItem, question.knowledge_item_id)
    evidence = {
        "evidence_id": evidence_id,
        "evidence_type": "scored_quiz",
        "summary": "导学正式验证题已由服务端评分",
        "knowledge_id": knowledge.public_id,
        "source_ref_id": question.public_id,
        "confidence": 0.9,
        "confirmed": True,
    }
    feedback.profile_change_evidence_json = [
        *list(feedback.profile_change_evidence_json or []),
        evidence,
    ]
    feedback.recommended_action = "challenge" if is_correct else "explain"
    feedback.triggered_action = feedback.recommended_action
    feedback.decision_reason = "验证证据已记录，等待统一画像分析"
    feedback.decision_confidence = 0.9

    session_records = [
        item
        for item in db.scalars(select(AnswerRecord).where(AnswerRecord.learner_id == learner.id))
        if (item.answer_summary_json or {}).get("tutoring_session_id") == session.id
        and (item.answer_summary_json or {}).get("confirmed") is True
    ]
    gate_passed = _profile_evidence_gate(db, session=session, records=session_records)
    task = None
    if gate_passed:
        task = create_feedback_task(
            db,
            learner=learner,
            profile=profile,
            resource=resource,
            feedback=feedback,
            resource_types=[resource.resource_type],
        )
    return (
        record,
        feedback,
        task,
        {
            "confirmed": True,
            "profile_update_required": False,
            "decision_reason": feedback.decision_reason,
        },
    )


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
                "sources": (item.metadata_json or {}).get("sources", []),
                "scope_status": (item.metadata_json or {}).get("scope_status"),
                "assessment": (item.metadata_json or {}).get("assessment"),
                "stream_status": (item.metadata_json or {}).get("stream_status", "completed"),
                "error_code": (item.metadata_json or {}).get("error_code"),
            }
            for item in messages
        ],
    }
