from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.contracts import (
    AnalyzeProfileInput,
    EvidenceRef,
    EvidenceType,
    KnowledgeAssessment,
    LearningPathNodeSnapshot,
    LearningPathSnapshot,
    RecommendedAction,
    TaskContext,
)
from app.agents.observability import collect_model_calls
from app.agents.profile_analysis_agent import ProfileAnalysisAgent
from app.agents.prompt_registry import PROMPT_VERSION, prompt_hash
from app.core.compatibility import AGENT_CONTRACT_VERSION
from app.models import (
    AgentMessageRecord,
    AgentRun,
    AnswerRecord,
    DiagnosticQuestion,
    Feedback,
    GenerationTask,
    KnowledgeItem,
    Learner,
    LearnerProfile,
    LearningAdjustmentProposal,
    LearningPath,
    LearningResource,
    PathNodeAssessment,
    TutoringMessage,
    TutoringSession,
)
from app.services.contract_mapping import profile_snapshot
from app.services.domain_runtime_service import load_domain_runtime
from app.services.feedback_service import create_feedback_task
from app.services.learning_path_service import _advance_path_node, normalize_learning_path
from app.services.profile_revision_service import persist_profile_revision
from app.services.profile_semantics_service import apply_confirmed_knowledge_semantics
from app.services.node_generation_target_service import (
    bind_node_generation_targets,
    resolve_node_generation_basis,
)
from app.services.profile_service import public_id


OPEN_PROPOSAL_STATUSES = {"collecting", "pending_validation"}
INTENT_HYPOTHESES = {"too_easy": "mastery_up", "too_hard": "support_down"}


def _active_context(
    db: Session,
    *,
    session: TutoringSession,
    profile: LearnerProfile,
    resource: LearningResource,
) -> tuple[Learner, LearningPath, GenerationTask, dict[str, Any]]:
    learner = db.get(Learner, session.learner_id)
    task = db.get(GenerationTask, resource.generation_task_id)
    path = db.scalar(
        select(LearningPath)
        .where(
            LearningPath.learner_id == session.learner_id,
            LearningPath.domain_code == profile.domain_code,
            LearningPath.status == "active",
        )
        .order_by(LearningPath.created_at.desc(), LearningPath.id.desc())
    )
    if learner is None or task is None or path is None:
        raise ValueError("learning_adjustment_context_missing")
    payload = normalize_learning_path(path)
    node_id = payload.get("current_node_id")
    node = (payload.get("node_states") or {}).get(node_id) if node_id else None
    if (
        not isinstance(node, dict)
        or task.learning_path_id != path.id
        or task.path_node_id != node_id
        or profile.id != path.profile_id
    ):
        raise ValueError("learning_adjustment_context_stale")
    return learner, path, task, node


def _pending_proposal(
    db: Session, *, learner_id: int, path_id: int, node_id: str
) -> LearningAdjustmentProposal | None:
    return db.scalar(
        select(LearningAdjustmentProposal)
        .where(
            LearningAdjustmentProposal.learner_id == learner_id,
            LearningAdjustmentProposal.learning_path_id == path_id,
            LearningAdjustmentProposal.path_node_id == node_id,
            LearningAdjustmentProposal.status.in_(OPEN_PROPOSAL_STATUSES),
        )
        .order_by(LearningAdjustmentProposal.id.desc())
    )


def _qualifying_feedback(
    db: Session,
    *,
    learner_id: int,
    task_id: int,
) -> tuple[str | None, list[Feedback]]:
    # Conversations remain resource-scoped, while normalized learner-turn
    # evidence is aggregated across resources in the same learning package.
    rows = list(
        db.scalars(
            select(Feedback)
            .join(LearningResource, LearningResource.id == Feedback.resource_id)
            .where(
                Feedback.learner_id == learner_id,
                LearningResource.generation_task_id == task_id,
                Feedback.tutoring_message_id.is_not(None),
                Feedback.feedback_intent.in_(INTENT_HYPOTHESES),
                Feedback.decision_confidence >= 0.4,
                Feedback.evidence_status == "eligible",
            )
            .order_by(Feedback.id.desc())
        )
    )
    if len(rows) < 2:
        return None, []
    latest_intent = rows[0].feedback_intent
    if rows[1].feedback_intent != latest_intent:
        rows[0].evidence_status = "conflict"
        rows[1].evidence_status = "conflict"
        db.flush()
        return None, []
    return INTENT_HYPOTHESES.get(str(latest_intent)), list(reversed(rows[:2]))


def _expire_other_package_evidence(
    db: Session, *, learner_id: int, current_task_id: int
) -> None:
    rows = db.scalars(
        select(Feedback)
        .join(LearningResource, LearningResource.id == Feedback.resource_id)
        .where(
            Feedback.learner_id == learner_id,
            Feedback.evidence_status == "eligible",
            LearningResource.generation_task_id != current_task_id,
        )
    )
    for row in rows:
        row.evidence_status = "stale"


def _proposal_trigger_reason(proposal: LearningAdjustmentProposal) -> str:
    if proposal.trigger_source == "automatic":
        return "根据你在本节点多个学习环节中的反馈，建议进行掌握检查"
    return "学习者主动申请掌握检查"


def _serialize_proposal_assessment(
    *,
    proposal: LearningAdjustmentProposal,
    assessment: PathNodeAssessment,
    question: DiagnosticQuestion,
    knowledge: KnowledgeItem | None,
) -> dict[str, Any]:
    payload = {
        "assessment_id": assessment.public_id,
        "adjustment_proposal_id": proposal.public_id,
        "hypothesis_type": proposal.hypothesis_type,
        "trigger_reason": _proposal_trigger_reason(proposal),
        "question_id": question.public_id,
        "knowledge_id": knowledge.public_id if knowledge else "",
        "knowledge_item_id": question.knowledge_item_id,
        "question_type": question.question_type,
        "difficulty": question.difficulty,
        "stem": question.stem,
        "options": question.options_json or [],
        "status": assessment.status,
        "proposal_status": proposal.status,
    }
    if assessment.status == "scored":
        payload.update(dict(assessment.result_json or {}))
        payload["resource_decision"] = proposal.resource_decision
    return payload


def _assessment_for_proposal(
    db: Session,
    *,
    proposal: LearningAdjustmentProposal,
    path: LearningPath,
    node: dict[str, Any],
) -> dict[str, Any]:
    knowledge = db.scalar(
        select(KnowledgeItem).where(
            KnowledgeItem.public_id == node.get("knowledge_id"),
            KnowledgeItem.domain_code == path.domain_code,
        )
    )
    if knowledge is None:
        raise ValueError("learning_adjustment_assessment_unavailable")
    attempted = set(
        db.scalars(
            select(PathNodeAssessment.question_id).where(
                PathNodeAssessment.learner_id == proposal.learner_id,
                PathNodeAssessment.path_node_id == proposal.path_node_id,
            )
        )
    )
    questions = list(
        db.scalars(
            select(DiagnosticQuestion)
            .where(
                DiagnosticQuestion.knowledge_item_id == knowledge.id,
                DiagnosticQuestion.domain_code == path.domain_code,
                DiagnosticQuestion.question_type == "single_choice",
            )
            .order_by(DiagnosticQuestion.difficulty.desc(), DiagnosticQuestion.id)
        )
    )
    if not questions:
        raise ValueError("learning_adjustment_assessment_unavailable")
    question = next((item for item in questions if item.id not in attempted), questions[0])
    assessment = PathNodeAssessment(
        public_id=public_id("pathval"),
        learning_path_id=path.id,
        path_node_id=proposal.path_node_id,
        learner_id=proposal.learner_id,
        question_id=question.id,
        adjustment_proposal_id=proposal.id,
        trigger_source=proposal.trigger_source,
        status="pending",
        result_json={},
    )
    db.add(assessment)
    proposal.status = "pending_validation"
    db.flush()
    return _serialize_proposal_assessment(
        proposal=proposal,
        assessment=assessment,
        question=question,
        knowledge=knowledge,
    )


def maybe_create_automatic_assessment(
    db: Session,
    *,
    session: TutoringSession,
    profile: LearnerProfile,
    resource: LearningResource,
) -> dict[str, Any] | None:
    learner, path, task, node = _active_context(
        db, session=session, profile=profile, resource=resource
    )
    _expire_other_package_evidence(db, learner_id=learner.id, current_task_id=task.id)
    pending = _pending_proposal(
        db,
        learner_id=learner.id,
        path_id=path.id,
        node_id=str((path.path_json or {}).get("current_node_id")),
    )
    if pending is not None:
        existing = db.scalar(
            select(PathNodeAssessment).where(
                PathNodeAssessment.adjustment_proposal_id == pending.id,
                PathNodeAssessment.status == "pending",
            )
        )
        if existing is None:
            return None
        question = db.get(DiagnosticQuestion, existing.question_id)
        if question is None:
            return None
        knowledge = db.get(KnowledgeItem, question.knowledge_item_id)
        return _serialize_proposal_assessment(
            proposal=pending,
            assessment=existing,
            question=question,
            knowledge=knowledge,
        )
    hypothesis, evidence_rows = _qualifying_feedback(
        db, learner_id=learner.id, task_id=task.id
    )
    if hypothesis is None:
        return None
    evidence_intent = str(evidence_rows[-1].feedback_intent)
    evidence_resource_ids = {row.resource_id for row in evidence_rows}
    supporting_rows = list(
        db.scalars(
            select(Feedback).where(
                Feedback.learner_id == learner.id,
                Feedback.resource_id.in_(evidence_resource_ids),
                Feedback.tutoring_message_id.is_(None),
                Feedback.feedback_intent == evidence_intent,
                Feedback.evidence_status == "supporting_only",
            )
        )
    )
    proposal = LearningAdjustmentProposal(
        public_id=public_id("adjust"),
        learner_id=learner.id,
        profile_id=profile.id,
        learning_path_id=path.id,
        path_node_id=str((path.path_json or {}).get("current_node_id")),
        tutoring_session_id=session.id,
        source_resource_id=resource.id,
        hypothesis_type=hypothesis,
        status="collecting",
        trigger_source="automatic",
        source_feedback_ids_json=[item.id for item in evidence_rows],
        evidence_summary_json={
            "signal_count": len(evidence_rows),
            "intent": evidence_intent,
            "minimum_confidence": min(item.decision_confidence for item in evidence_rows),
            "generation_task_id": task.public_id,
            "tutoring_session_ids": sorted(
                {item.tutoring_session_id for item in evidence_rows if item.tutoring_session_id}
            ),
            "resource_ids": sorted({item.resource_id for item in evidence_rows}),
            "resource_types": sorted(
                {
                    item.resource_type
                    for item in db.scalars(
                        select(LearningResource).where(
                            LearningResource.id.in_(
                                {row.resource_id for row in evidence_rows}
                            )
                        )
                    )
                }
            ),
            "supporting_feedback_ids": [item.id for item in supporting_rows],
        },
        validation_result_json={},
        resource_recommendation_json={},
    )
    db.add(proposal)
    db.flush()
    for row in evidence_rows:
        row.evidence_status = "consumed"
        row.adjustment_proposal_id = proposal.id
    for row in supporting_rows:
        row.evidence_status = "consumed"
        row.adjustment_proposal_id = proposal.id
    return _assessment_for_proposal(db, proposal=proposal, path=path, node=node)


def node_adjustment_context(db: Session, *, session: TutoringSession) -> dict[str, Any]:
    resource = db.get(LearningResource, session.resource_id) if session.resource_id else None
    task = db.get(GenerationTask, resource.generation_task_id) if resource else None
    if resource is None or task is None:
        return {
            "node_adjustment_state": "none",
            "pending_assessment": None,
            "node_adjustment_result": None,
            "evidence_scope": None,
        }
    task_proposal = db.scalar(
        select(LearningAdjustmentProposal)
        .join(
            LearningResource,
            LearningResource.id == LearningAdjustmentProposal.source_resource_id,
        )
        .where(
            LearningAdjustmentProposal.learner_id == session.learner_id,
            LearningResource.generation_task_id == task.id,
        )
        .order_by(LearningAdjustmentProposal.id.desc())
    )
    if task_proposal is not None and task_proposal.status in {
        "resource_pending",
        "resource_started",
        "resource_skipped",
    }:
        scored_assessment = db.scalar(
            select(PathNodeAssessment).where(
                PathNodeAssessment.adjustment_proposal_id == task_proposal.id,
                PathNodeAssessment.status == "scored",
            )
        )
        question = (
            db.get(DiagnosticQuestion, scored_assessment.question_id)
            if scored_assessment
            else None
        )
        result = (
            _serialize_proposal_assessment(
                proposal=task_proposal,
                assessment=scored_assessment,
                question=question,
                knowledge=(
                    db.get(KnowledgeItem, question.knowledge_item_id) if question else None
                ),
            )
            if scored_assessment is not None and question is not None
            else dict(task_proposal.validation_result_json or {})
        )
        return {
            "node_adjustment_state": "confirmed",
            "pending_assessment": None,
            "node_adjustment_result": result,
            "evidence_scope": {
                "path_node_id": task_proposal.path_node_id,
                "path_node_title": None,
                "generation_task_id": task.public_id,
            },
        }
    path = db.scalar(
        select(LearningPath)
        .where(
            LearningPath.learner_id == session.learner_id,
            LearningPath.domain_code == task.domain_code,
            LearningPath.status == "active",
        )
        .order_by(LearningPath.created_at.desc(), LearningPath.id.desc())
    )
    payload = normalize_learning_path(path) if path else {}
    node_id = payload.get("current_node_id")
    node = (payload.get("node_states") or {}).get(node_id) if node_id else None
    if (
        path is None
        or not isinstance(node, dict)
        or task.learning_path_id != path.id
        or task.path_node_id != node_id
        or not task.is_current_package
        or not resource.is_current
    ):
        return {
            "node_adjustment_state": "none",
            "pending_assessment": None,
            "node_adjustment_result": None,
            "evidence_scope": None,
        }
    proposal = db.scalar(
        select(LearningAdjustmentProposal)
        .where(
            LearningAdjustmentProposal.learner_id == session.learner_id,
            LearningAdjustmentProposal.learning_path_id == path.id,
            LearningAdjustmentProposal.path_node_id == node_id,
        )
        .order_by(LearningAdjustmentProposal.id.desc())
    )
    pending_assessment = None
    state = "collecting"
    if proposal is not None and proposal.status == "pending_validation":
        assessment = db.scalar(
            select(PathNodeAssessment).where(
                PathNodeAssessment.adjustment_proposal_id == proposal.id,
                PathNodeAssessment.status == "pending",
            )
        )
        question = db.get(DiagnosticQuestion, assessment.question_id) if assessment else None
        knowledge = db.get(KnowledgeItem, question.knowledge_item_id) if question else None
        if assessment is not None and question is not None:
            pending_assessment = _serialize_proposal_assessment(
                proposal=proposal,
                assessment=assessment,
                question=question,
                knowledge=knowledge,
            )
            state = "pending_validation"
    return {
        "node_adjustment_state": state,
        "pending_assessment": pending_assessment,
        "node_adjustment_result": None,
        "evidence_scope": {
            "path_node_id": node_id,
            "path_node_title": node.get("title") or node.get("knowledge_id"),
            "generation_task_id": task.public_id,
        },
    }


def request_mastery_assessment(
    db: Session,
    *,
    session: TutoringSession,
    profile: LearnerProfile,
) -> dict[str, Any]:
    resource = db.get(LearningResource, session.resource_id) if session.resource_id else None
    if resource is None:
        raise ValueError("tutoring_session_resource_not_found")
    learner, path, _task, node = _active_context(
        db, session=session, profile=profile, resource=resource
    )
    pending = _pending_proposal(
        db,
        learner_id=learner.id,
        path_id=path.id,
        node_id=str((path.path_json or {}).get("current_node_id")),
    )
    if pending is not None:
        raise ValueError("learning_adjustment_already_pending")
    proposal = LearningAdjustmentProposal(
        public_id=public_id("adjust"),
        learner_id=learner.id,
        profile_id=profile.id,
        learning_path_id=path.id,
        path_node_id=str((path.path_json or {}).get("current_node_id")),
        tutoring_session_id=session.id,
        source_resource_id=resource.id,
        hypothesis_type="mastery_up",
        status="collecting",
        trigger_source="manual",
        source_feedback_ids_json=[],
        evidence_summary_json={"signal_count": 1, "intent": "mastery_check_requested"},
        validation_result_json={},
        resource_recommendation_json={},
    )
    db.add(proposal)
    db.flush()
    assessment = _assessment_for_proposal(db, proposal=proposal, path=path, node=node)
    db.add(
        TutoringMessage(
            public_id=public_id("msg"),
            session_id=session.id,
            sender="tutoring_agent",
            message_type="assessment",
            content="学习者主动申请掌握检查",
            metadata_json={"assessment": assessment, "stream_status": "completed"},
        )
    )
    db.flush()
    return assessment


def _path_snapshots(
    path: LearningPath, profile: LearnerProfile
) -> tuple[LearningPathSnapshot, LearningPathNodeSnapshot | None]:
    payload = normalize_learning_path(path)
    snapshot = profile_snapshot(profile)
    average = sum(snapshot.ability_scores.model_dump().values()) / 5
    difficulty = max(1, min(5, round(average / 20)))
    nodes = [
        LearningPathNodeSnapshot(
            path_node_id=str(node["path_node_id"]),
            knowledge_id=str(node["knowledge_id"]),
            title=str(node.get("title") or node["knowledge_id"]),
            path_order=int(node.get("path_order") or 1),
            target_difficulty=difficulty,
            learning_objective=f"掌握 {node.get('title') or node['knowledge_id']}",
        )
        for node in (payload.get("node_states") or {}).values()
        if isinstance(node, dict)
    ]
    current_id = payload.get("current_node_id")
    current = next((item for item in nodes if item.path_node_id == current_id), None)
    return LearningPathSnapshot(
        path_id=path.public_id,
        nodes=sorted(nodes, key=lambda item: item.path_order),
        current_node_id=current.path_node_id if current else None,
    ), current


def _analyze_profile(
    db: Session,
    *,
    proposal: LearningAdjustmentProposal,
    profile: LearnerProfile,
    path: LearningPath,
    resource: LearningResource,
    feedback: Feedback,
    record: AnswerRecord,
    question: DiagnosticQuestion,
) -> tuple[LearnerProfile, LearningPath | None, Any, dict[str, Any]]:
    evidence_id = f"answer_record:{record.id}"
    knowledge = db.get(KnowledgeItem, question.knowledge_item_id)
    learner = db.get(Learner, proposal.learner_id)
    if knowledge is None or learner is None:
        raise ValueError("learning_adjustment_knowledge_missing")
    evidence = EvidenceRef(
        evidence_id=evidence_id,
        evidence_type=EvidenceType.SCORED_QUIZ,
        summary="导学微验证已由服务端评分",
        knowledge_id=knowledge.public_id,
        source_ref_id=question.public_id,
        confidence=0.9,
        confirmed=True,
    )
    assessment = KnowledgeAssessment(
        assessment_id=proposal.public_id,
        evidence_id=evidence_id,
        knowledge_id=knowledge.public_id,
        score=float(record.score),
        difficulty=question.difficulty,
        attempted=True,
        confidence=0.9,
    )
    path_snapshot, current_node = _path_snapshots(path, profile)
    context = TaskContext(
        task_id=proposal.public_id,
        session_id=proposal.public_id,
        trigger_type="resource_feedback",
        execution_mode="auto",
        learner_id=learner.public_id,
        profile_id=profile.public_id,
        domain_code=profile.domain_code,
        resource_types=[resource.resource_type],
        learning_goal="根据导学交互和正式微验证更新学习画像",
        resource_id=resource.public_id,
        feedback_id=str(feedback.id),
        tutoring_session_id=str(proposal.tutoring_session_id),
    )
    runtime = load_domain_runtime(db, profile.domain_code)
    if runtime.profile_config is None:
        raise ValueError("profile_runtime_not_ready")
    run = AgentRun(
        generation_task_id=None,
        agent_name="profile_analysis_agent",
        status="running",
        input_summary_json={
            "proposal_id": proposal.public_id,
            "knowledge_id": knowledge.public_id,
            "hypothesis_type": proposal.hypothesis_type,
        },
        output_summary_json={},
        prompt_version=PROMPT_VERSION,
        prompt_hash=prompt_hash("profile"),
        contract_version=AGENT_CONTRACT_VERSION,
    )
    db.add(run)
    db.add(
        AgentMessageRecord(
            session_id=proposal.public_id,
            task_id=proposal.public_id,
            sender="orchestrator_agent",
            receiver="profile_analysis_agent",
            message_type="command",
            payload_summary_json={"hypothesis_type": proposal.hypothesis_type},
        )
    )
    started_at = time.perf_counter()
    with collect_model_calls() as collector:
        analysis = ProfileAnalysisAgent(runtime.profile_config).execute(
            AnalyzeProfileInput(
                task_id=proposal.public_id,
                context=context,
                current_profile=profile_snapshot(profile),
                learning_path=path_snapshot,
                current_path_node=current_node,
                feedback_evidence=[evidence],
                recommended_action=(
                    RecommendedAction.CHALLENGE
                    if proposal.hypothesis_type == "mastery_up"
                    else RecommendedAction.EXPLAIN
                ),
                knowledge_assessments=[assessment],
            )
        )
    calls = collector.snapshot()
    run.status = "completed"
    run.output_summary_json = {
        "proposal_id": proposal.public_id,
        "profile_update_required": analysis.profile_update_required,
        "changed_dimensions": analysis.changed_dimensions,
    }
    run.llm_calls = len(calls)
    run.tokens_input = sum(item["tokens_input"] for item in calls)
    run.tokens_output = sum(item["tokens_output"] for item in calls)
    run.tokens_used = run.tokens_input + run.tokens_output
    run.model_name = calls[0]["model_name"] if calls else None
    run.duration_ms = round((time.perf_counter() - started_at) * 1000)
    db.add(
        AgentMessageRecord(
            session_id=proposal.public_id,
            task_id=proposal.public_id,
            sender="profile_analysis_agent",
            receiver="orchestrator_agent",
            message_type="result",
            payload_summary_json={
                "profile_update_required": analysis.profile_update_required,
                "changed_dimensions": analysis.changed_dimensions,
            },
        )
    )
    analysis, change_summary = apply_confirmed_knowledge_semantics(
        original=profile,
        analysis=analysis,
        hypothesis_type=proposal.hypothesis_type,
        knowledge=knowledge,
        evidence_id=evidence_id,
        path_node_id=proposal.path_node_id,
    )
    next_profile, next_path = persist_profile_revision(
        db,
        original=profile,
        analysis=analysis,
        trigger_feedback_id=feedback.id,
    )
    change_summary["original_profile_id"] = profile.public_id
    change_summary["original_profile_version"] = profile.profile_version
    change_summary["resulting_profile_id"] = next_profile.public_id
    change_summary["resulting_profile_version"] = next_profile.profile_version
    return next_profile, next_path, analysis, change_summary


def answer_adjustment_assessment(
    db: Session,
    *,
    session: TutoringSession,
    profile: LearnerProfile,
    assessment_id: str,
    answer: Any,
) -> tuple[AnswerRecord, Feedback, dict[str, Any]]:
    assessment = db.scalar(
        select(PathNodeAssessment)
        .where(PathNodeAssessment.public_id == assessment_id)
        .with_for_update()
    )
    proposal = (
        db.get(LearningAdjustmentProposal, assessment.adjustment_proposal_id)
        if assessment and assessment.adjustment_proposal_id
        else None
    )
    if assessment is None or proposal is None or proposal.learner_id != session.learner_id:
        raise ValueError("learning_adjustment_assessment_not_found")
    feedback = db.get(Feedback, (proposal.source_feedback_ids_json or [None])[-1])
    if feedback is None:
        feedback = Feedback(
            resource_id=proposal.source_resource_id,
            learner_id=proposal.learner_id,
            feedback_type="mastery_check",
            feedback_summary_json={"proposal_id": proposal.public_id},
            triggered_action="ask_follow_up",
            comment="主动申请掌握检查",
            tutoring_session_id=session.id,
            feedback_intent="too_easy",
            recommended_action="ask_follow_up",
            decision_confidence=0.4,
            decision_reason="等待正式微验证",
        )
        db.add(feedback)
        db.flush()
        proposal.source_feedback_ids_json = [feedback.id]
    if assessment.status == "scored" and assessment.answer_record_id:
        record = db.get(AnswerRecord, assessment.answer_record_id)
        if record is None:
            raise ValueError("learning_adjustment_answer_missing")
        return record, feedback, dict(assessment.result_json or {})
    if proposal.status != "pending_validation":
        raise ValueError("learning_adjustment_proposal_stale")
    question = db.get(DiagnosticQuestion, assessment.question_id)
    path = db.get(LearningPath, proposal.learning_path_id)
    resource = db.get(LearningResource, proposal.source_resource_id)
    submitting_resource = (
        db.get(LearningResource, session.resource_id) if session.resource_id else None
    )
    if question is None or path is None or resource is None or path.status != "active":
        proposal.status = "stale"
        raise ValueError("learning_adjustment_proposal_stale")
    if (
        submitting_resource is None
        or submitting_resource.generation_task_id != resource.generation_task_id
        or (path.path_json or {}).get("current_node_id") != proposal.path_node_id
    ):
        raise ValueError("learning_adjustment_assessment_context_stale")
    try:
        selected = int(answer)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_single_choice_answer") from exc
    if selected < 0 or selected >= len(question.options_json or []):
        raise ValueError("invalid_single_choice_answer")
    correct = int((question.answer_key_json or {}).get("correct_option", -1))
    is_correct = selected == correct
    score = 1.0 if is_correct else 0.0
    confirmed = (
        proposal.hypothesis_type == "mastery_up" and is_correct
    ) or (proposal.hypothesis_type == "support_down" and not is_correct)
    record = AnswerRecord(
        learner_id=proposal.learner_id,
        question_id=question.id,
        knowledge_item_id=question.knowledge_item_id,
        session_id=assessment.public_id,
        answer_text=str(selected),
        score=score,
        is_correct=is_correct,
        scoring_status="scored",
        scoring_method="deterministic",
        confidence=0.9,
        answer_summary_json={
            "assessment_id": assessment.public_id,
            "adjustment_proposal_id": proposal.public_id,
            "contract_evidence_type": "scored_quiz",
            "confirmed": confirmed,
            "confidence": 0.9,
            "consumed_by_profile_id": None,
        },
    )
    db.add(record)
    db.flush()
    evidence_id = f"answer_record:{record.id}"
    decision = "hypothesis_rejected"
    profile_changed = False
    resulting_profile = profile
    resulting_path = path
    completed_node_id = None
    profile_change_summary = None
    if confirmed:
        if proposal.hypothesis_type == "mastery_up":
            _advance_path_node(
                db,
                path=path,
                node_id=proposal.path_node_id,
                evidence_ids=[evidence_id],
            )
            completed_node_id = proposal.path_node_id
            decision = "confirmed_mastery"
        else:
            decision = "confirmed_support_need"
        resulting_profile, revised_path, _analysis, profile_change_summary = _analyze_profile(
            db,
            proposal=proposal,
            profile=profile,
            path=path,
            resource=resource,
            feedback=feedback,
            record=record,
            question=question,
        )
        profile_changed = resulting_profile.id != profile.id
        if revised_path is not None:
            resulting_path = revised_path
        current_node_id = (resulting_path.path_json or {}).get("current_node_id")
        profile_change_summary = dict(profile_change_summary or {})
        profile_change_summary.update(
            {
                "interaction_evidence_ids": [
                    f"feedback:{feedback_id}"
                    for feedback_id in (proposal.source_feedback_ids_json or [])
                ],
                "completed_node_id": completed_node_id,
                "current_node_id": current_node_id,
            }
        )
        recommendation = {
            "proposal_id": proposal.public_id,
            "path_id": resulting_path.public_id,
            "path_node_id": current_node_id,
            "resource_types": (
                ["lecture", "practice_guide", "graded_quiz"]
                if proposal.hypothesis_type == "mastery_up"
                else [resource.resource_type]
            ),
            "mode": "next_node" if proposal.hypothesis_type == "mastery_up" else "remedial",
        }
        proposal.status = "resource_pending"
        proposal.resulting_profile_id = resulting_profile.id
        proposal.resulting_learning_path_id = resulting_path.id
        proposal.resource_recommendation_json = recommendation
    else:
        current_node_id = (path.path_json or {}).get("current_node_id")
        recommendation = None
        proposal.status = "rejected"
    result = {
        "adjustment_proposal_id": proposal.public_id,
        "hypothesis_type": proposal.hypothesis_type,
        "decision": decision,
        "score": score,
        "is_correct": is_correct,
        "confirmed": confirmed,
        "profile_changed": profile_changed,
        "resulting_profile_id": resulting_profile.public_id,
        "resulting_path_id": resulting_path.public_id,
        "completed_node_id": completed_node_id,
        "current_node_id": current_node_id,
        "resource_recommendation": recommendation,
        "profile_change_summary": profile_change_summary,
        "decision_reason": {
            "confirmed_mastery": "已确认掌握，学习路线已推进",
            "confirmed_support_need": "已确认需要补强，当前学习节点保持不变",
            "hypothesis_rejected": "验证结果与近期反馈不一致，画像和路线保持不变",
        }[decision],
    }
    assessment.answer_record_id = record.id
    assessment.status = "scored"
    assessment.score = score
    assessment.passed = confirmed
    assessment.result_json = result
    proposal.validation_result_json = result
    for pending_feedback in db.scalars(
        select(Feedback)
        .join(LearningResource, LearningResource.id == Feedback.resource_id)
        .where(
            Feedback.learner_id == proposal.learner_id,
            Feedback.evidence_status == "eligible",
            LearningResource.generation_task_id == resource.generation_task_id,
        )
    ):
        pending_feedback.evidence_status = "stale"
    knowledge = db.get(KnowledgeItem, question.knowledge_item_id)
    feedback.profile_change_evidence_json = [
        *list(feedback.profile_change_evidence_json or []),
        {
            "evidence_id": evidence_id,
            "evidence_type": "scored_quiz",
            "knowledge_id": knowledge.public_id if knowledge else None,
            "confirmed": confirmed,
            "confidence": 0.9,
        },
    ]
    feedback.profile_update_required = profile_changed
    feedback.decision_reason = result["decision_reason"]
    feedback.decision_confidence = 0.9
    message = None
    for candidate in db.scalars(
        select(TutoringMessage)
        .where(TutoringMessage.session_id == session.id)
        .order_by(TutoringMessage.id.desc())
    ):
        metadata = dict(candidate.metadata_json or {})
        embedded = metadata.get("assessment") or {}
        if embedded.get("assessment_id") == assessment.public_id:
            message = candidate
            break
    if message is not None:
        metadata = dict(message.metadata_json or {})
        metadata["assessment"] = {
            **dict(metadata.get("assessment") or {}),
            **result,
            "status": "scored",
        }
        message.metadata_json = metadata
    db.commit()
    return record, feedback, result


def decide_proposal_resource(
    db: Session,
    *,
    proposal_id: str,
    learner_public_id: str,
    decision: str,
) -> tuple[dict[str, Any], GenerationTask | None]:
    proposal = db.scalar(
        select(LearningAdjustmentProposal)
        .where(LearningAdjustmentProposal.public_id == proposal_id)
        .with_for_update()
    )
    learner = db.get(Learner, proposal.learner_id) if proposal else None
    if proposal is None or learner is None or learner.public_id != learner_public_id:
        raise ValueError("learning_adjustment_proposal_not_found")
    existing = db.get(GenerationTask, proposal.generation_task_id) if proposal.generation_task_id else None
    if proposal.status == "resource_started" and existing is not None:
        return {"proposal_id": proposal.public_id, "decision": "generate", "task_id": existing.public_id}, existing
    if proposal.status == "resource_skipped":
        return {"proposal_id": proposal.public_id, "decision": "skip", "task_id": None}, None
    if proposal.status != "resource_pending":
        raise ValueError("learning_adjustment_proposal_stale")
    recommendation = proposal.resource_recommendation_json or {}
    path = db.get(LearningPath, proposal.resulting_learning_path_id or proposal.learning_path_id)
    profile = db.get(LearnerProfile, proposal.resulting_profile_id or proposal.profile_id)
    current_node_id = (path.path_json or {}).get("current_node_id") if path else None
    if path is None or profile is None or path.status != "active" or current_node_id != recommendation.get("path_node_id"):
        proposal.status = "stale"
        db.commit()
        raise ValueError("learning_adjustment_proposal_stale")
    if decision == "skip":
        proposal.status = "resource_skipped"
        proposal.resource_decision = "skip"
        db.commit()
        return {"proposal_id": proposal.public_id, "decision": "skip", "task_id": None}, None
    if decision != "generate":
        raise ValueError("invalid_resource_decision")
    resource_types = list(recommendation.get("resource_types") or [])
    if recommendation.get("mode") == "remedial":
        resource = db.get(LearningResource, proposal.source_resource_id)
        feedback = db.get(Feedback, (proposal.source_feedback_ids_json or [None])[-1])
        if resource is None or feedback is None:
            raise ValueError("learning_adjustment_source_missing")
        task = create_feedback_task(
            db,
            learner=learner,
            profile=profile,
            resource=resource,
            feedback=feedback,
            resource_types=resource_types,
        )
        task.learning_path_id = path.id
        task.path_node_id = current_node_id
    else:
        task = GenerationTask(
            public_id=public_id("task"),
            learner_id=learner.id,
            profile_id=profile.id,
            learning_path_id=path.id,
            path_node_id=current_node_id,
            domain_code=path.domain_code,
            status="pending",
            resource_types_json=resource_types,
            decision="pending",
            trigger_type="initial_generation",
            execution_mode="auto",
            learning_goal=f"为学习路线当前节点 {current_node_id} 生成学习资源",
            event_type="generation",
            progress=0,
        )
        db.add(task)
        db.flush()
    basis = resolve_node_generation_basis(
        db,
        path=path,
        path_node_id=current_node_id,
        profile=profile,
        resource_types=resource_types,
    )
    bind_node_generation_targets(task, basis)
    proposal.status = "resource_started"
    proposal.resource_decision = "generate"
    proposal.generation_task_id = task.id
    db.commit()
    return {"proposal_id": proposal.public_id, "decision": "generate", "task_id": task.public_id}, task


def pending_resource_proposals(
    db: Session, *, learner_id: int, domain_code: str
) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(LearningAdjustmentProposal)
            .join(LearningPath, LearningPath.id == LearningAdjustmentProposal.resulting_learning_path_id)
            .where(
                LearningAdjustmentProposal.learner_id == learner_id,
                LearningAdjustmentProposal.status == "resource_pending",
                LearningPath.domain_code == domain_code,
                LearningPath.status == "active",
            )
            .order_by(LearningAdjustmentProposal.id.desc())
        )
    )
    return [
        {
            "proposal_id": item.public_id,
            "hypothesis_type": item.hypothesis_type,
            "status": item.status,
            "resource_recommendation": item.resource_recommendation_json or {},
            "decision": (item.validation_result_json or {}).get("decision"),
        }
        for item in rows
    ]


def recent_profile_changes(
    db: Session, *, learner_id: int, domain_code: str, limit: int = 5
) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(LearningAdjustmentProposal)
            .join(
                LearningPath,
                LearningPath.id == LearningAdjustmentProposal.resulting_learning_path_id,
            )
            .where(
                LearningAdjustmentProposal.learner_id == learner_id,
                LearningAdjustmentProposal.status.in_(
                    {"resource_pending", "resource_started", "resource_skipped"}
                ),
                LearningPath.domain_code == domain_code,
            )
            .order_by(LearningAdjustmentProposal.updated_at.desc(), LearningAdjustmentProposal.id.desc())
            .limit(limit)
        )
    )
    changes: list[dict[str, Any]] = []
    for item in rows:
        validation = dict(item.validation_result_json or {})
        summary = validation.get("profile_change_summary")
        if not isinstance(summary, dict):
            continue
        changes.append(
            {
                "proposal_id": item.public_id,
                "hypothesis_type": item.hypothesis_type,
                "decision": validation.get("decision"),
                "status": item.status,
                "resource_decision": item.resource_decision,
                "profile_change_summary": summary,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
        )
    return changes
