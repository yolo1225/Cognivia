from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AnswerRecord,
    Feedback,
    Learner,
    LearnerProfile,
    LearningAdjustmentProposal,
    LearningPath,
    LearningResource,
    KnowledgeItem,
    DiagnosticQuestion,
)
from app.services.profile_service import public_id
from app.services.tutoring_service import create_session


REQUIRED_EVIDENCE_COUNT = 2


def _base_result(record: AnswerRecord) -> dict[str, Any]:
    evidence_ref = f"answer_record:{record.id}"
    return {
        "evidence": {
            "evidence_ref": evidence_ref,
            "governance_status": "pending",
            "eligible_evidence_count": 1,
            "required_evidence_count": REQUIRED_EVIDENCE_COUNT,
            "governance_reason": "WAITING_FOR_CORROBORATING_EVIDENCE",
        },
        "profile_result": {
            "evaluated": False,
            "profile_updated": False,
            "previous_profile_id": None,
            "resulting_profile_id": None,
            "resulting_profile_version": None,
            "decision_reason": None,
        },
        "path_result": {
            "updated": False,
            "completed_node_id": None,
            "current_node_id": None,
            "resulting_path_id": None,
        },
    }


def _save_governance(
    record: AnswerRecord, *, status: str, reason: str, result: dict[str, Any]
) -> None:
    payload = dict(record.answer_summary_json or {})
    payload.update(
        {
            "governance_status": status,
            "governance_reason": reason,
            "evaluated_at": datetime.now(UTC).isoformat(),
            "governance_result": result,
        }
    )
    record.answer_summary_json = payload


def stored_governance_result(record: AnswerRecord | None) -> dict[str, Any] | None:
    if record is None:
        return None
    value = (record.answer_summary_json or {}).get("governance_result")
    return dict(value) if isinstance(value, dict) else None


def _eligible_records(
    db: Session, *, learner: Learner, record: AnswerRecord, profile: LearnerProfile
) -> list[AnswerRecord]:
    since = profile.profile_changed_at or profile.created_at
    rows = list(
        db.scalars(
            select(AnswerRecord)
            .where(
                AnswerRecord.learner_id == learner.id,
                AnswerRecord.knowledge_item_id == record.knowledge_item_id,
                AnswerRecord.created_at > since,
                AnswerRecord.scoring_status == "scored",
                AnswerRecord.confidence >= 0.9,
            )
            .order_by(AnswerRecord.created_at, AnswerRecord.id)
            .with_for_update()
        )
    )
    eligible: list[AnswerRecord] = []
    seen_questions: set[int] = set()
    for candidate in rows:
        summary = candidate.answer_summary_json or {}
        if summary.get("consumed_by_profile_id") is not None:
            continue
        if summary.get("governance_status") in {"no_change", "rejected"}:
            continue
        if summary.get("contract_evidence_type") != "scored_quiz":
            continue
        if summary.get("confirmed") is not True:
            continue
        if candidate.question_id in seen_questions:
            continue
        seen_questions.add(candidate.question_id)
        eligible.append(candidate)
    return eligible


def evaluate_mistake_evidence(
    db: Session,
    *,
    learner: Learner,
    item: Any,
    record: AnswerRecord,
    resource: LearningResource | None,
) -> dict[str, Any]:
    stored = stored_governance_result(record)
    if stored is not None:
        return stored
    result = _base_result(record)
    profile = db.scalar(
        select(LearnerProfile)
        .where(
            LearnerProfile.learner_id == learner.id,
            LearnerProfile.domain_code == item.domain_code,
            LearnerProfile.diagnosis_completed.is_(True),
            LearnerProfile.profile_source != "default_seed",
        )
        .order_by(LearnerProfile.profile_version.desc(), LearnerProfile.id.desc())
        .with_for_update()
    )
    if profile is None:
        reason = "FORMAL_PROFILE_REQUIRED"
        result["evidence"]["governance_reason"] = reason
        _save_governance(record, status="pending", reason=reason, result=result)
        return result
    path = db.scalar(
        select(LearningPath)
        .where(
            LearningPath.profile_id == profile.id,
            LearningPath.status.in_({"active", "completed"}),
        )
        .order_by(LearningPath.id.desc())
        .with_for_update()
    )
    candidates = _eligible_records(db, learner=learner, record=record, profile=profile)
    result["evidence"]["eligible_evidence_count"] = len(candidates)
    has_mistake = any(
        (candidate.answer_summary_json or {}).get("evidence_type") == "mistake_consolidation"
        for candidate in candidates
    )
    if len(candidates) < REQUIRED_EVIDENCE_COUNT or not has_mistake:
        _save_governance(
            record,
            status="pending",
            reason="WAITING_FOR_CORROBORATING_EVIDENCE",
            result=result,
        )
        return result
    directions = {bool(candidate.is_correct) for candidate in candidates}
    if len(directions) != 1:
        reason = "CONFLICTING_FORMAL_EVIDENCE"
        result["evidence"].update(
            {"governance_status": "conflicted", "governance_reason": reason}
        )
        for candidate in candidates:
            _save_governance(candidate, status="conflicted", reason=reason, result=result)
        return result
    if resource is None or path is None:
        reason = "RELATED_RESOURCE_OR_ACTIVE_PATH_REQUIRED"
        result["evidence"]["governance_reason"] = reason
        _save_governance(record, status="pending", reason=reason, result=result)
        return result

    from app.services.learning_adjustment_service import _analyze_profile

    mastered = directions == {True}
    current_node_id = (path.path_json or {}).get("current_node_id")
    knowledge = db.get(KnowledgeItem, item.knowledge_item_id)
    question = db.get(DiagnosticQuestion, record.question_id)
    if knowledge is None or question is None:
        reason = "FORMAL_EVIDENCE_CONTEXT_MISSING"
        result["evidence"]["governance_reason"] = reason
        _save_governance(record, status="rejected", reason=reason, result=result)
        return result
    completed_node_id = None
    savepoint = db.begin_nested()
    feedback = Feedback(
        resource_id=resource.id,
        learner_id=learner.id,
        feedback_type="mistake_consolidation",
        feedback_summary_json={
            "mistake_item_id": item.public_id,
            "evidence_ids": [f"answer_record:{candidate.id}" for candidate in candidates],
        },
        triggered_action="profile_evidence_evaluation",
        comment="错题巩固组合证据达到画像分析门槛",
        feedback_intent="too_easy" if mastered else "too_hard",
        recommended_action="challenge" if mastered else "explain",
        profile_update_required=False,
        profile_change_evidence_json=[],
        decision_confidence=1.0,
        decision_reason="等待画像分析",
        evidence_status="formal",
    )
    db.add(feedback)
    db.flush()
    tutoring = create_session(db, learner=learner, resource=resource)
    proposal = LearningAdjustmentProposal(
        public_id=public_id("adjustment"),
        learner_id=learner.id,
        profile_id=profile.id,
        learning_path_id=path.id,
        path_node_id=str(current_node_id or f"knowledge:{knowledge.public_id}"),
        tutoring_session_id=tutoring.id,
        source_resource_id=resource.id,
        hypothesis_type="mastery_up" if mastered else "support_down",
        status="confirmed",
        trigger_source="mistake_consolidation",
        source_feedback_ids_json=[feedback.id],
        evidence_summary_json={
            "evidence_ids": [f"answer_record:{candidate.id}" for candidate in candidates]
        },
    )
    db.add(proposal)
    db.flush()
    feedback.adjustment_proposal_id = proposal.id
    try:
        next_profile, next_path, analysis, change_summary = _analyze_profile(
            db,
            proposal=proposal,
            profile=profile,
            path=path,
            resource=resource,
            feedback=feedback,
            record=record,
            question=question,
            evidence_records=candidates,
        )
    except Exception:
        savepoint.rollback()
        record = db.get(AnswerRecord, record.id)
        reason = "PROFILE_ANALYSIS_UNAVAILABLE"
        result["evidence"]["governance_reason"] = reason
        _save_governance(record, status="pending", reason=reason, result=result)
        return result
    savepoint.commit()
    profile_updated = next_profile.id != profile.id
    status = "consumed" if profile_updated else "no_change"
    reason = analysis.decision_reason
    result["evidence"].update(
        {"governance_status": status, "governance_reason": reason}
    )
    result["profile_result"] = {
        "evaluated": True,
        "profile_updated": profile_updated,
        "previous_profile_id": profile.public_id,
        "resulting_profile_id": next_profile.public_id,
        "resulting_profile_version": next_profile.profile_version,
        "decision_reason": reason,
    }
    resulting_path = next_path or path
    # A single mastered knowledge item is valid profile evidence, but a
    # multi-knowledge learning unit advances only through its aggregate check.
    result["path_result"] = {
        "updated": bool(next_path or completed_node_id),
        "completed_node_id": completed_node_id,
        "current_node_id": (resulting_path.path_json or {}).get("current_node_id"),
        "resulting_path_id": resulting_path.public_id,
    }
    proposal.resulting_profile_id = next_profile.id
    proposal.resulting_learning_path_id = resulting_path.id
    proposal.validation_result_json = {
        "profile_change_summary": change_summary,
        **result,
    }
    for candidate in candidates:
        payload = dict(candidate.answer_summary_json or {})
        payload["consumed_by_profile_id"] = next_profile.id if profile_updated else None
        candidate.answer_summary_json = payload
        _save_governance(candidate, status=status, reason=reason, result=result)
    return result
