from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AnswerRecord,
    DiagnosticQuestion,
    GenerationTask,
    KnowledgeItem,
    LearnerProfile,
    LearningPath,
    MistakeReviewItem,
    ResourceQuizAttempt,
)
from app.services.learning_package_service import package_member_rows
REQUIRED_EVIDENCE_COUNT = 2
# MySQL FLOAT stores 0.9 as a value marginally below the decimal literal.
# Keep the product threshold at 90%, while accepting that representational drift.
FORMAL_EVIDENCE_CONFIDENCE_FLOOR = 0.899
FORMAL_EVIDENCE_TYPES = {
    "graded_quiz",
    "mistake_consolidation",
    "path_validation",
    "tutoring_validation",
}
CORROBORATING_EVIDENCE_TYPES = {
    "mistake_consolidation",
    "path_validation",
    "tutoring_validation",
}
UNRESOLVED_MISTAKE_STATUSES = {
    "pending",
    "reviewing",
    "verification_pending",
    "needs_more_practice",
}
RESOURCE_TYPE_ORDER = ("lecture", "practice_guide", "graded_quiz")


def node_core_knowledge_ids(node: dict[str, Any]) -> list[str]:
    values = (
        node.get("focus_knowledge_ids")
        or node.get("knowledge_ids")
        or ([node.get("knowledge_id")] if node.get("knowledge_id") else [])
    )
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _formal_positive_records(
    db: Session,
    *,
    learner_id: int,
    domain_code: str,
    core_ids: list[str],
    profile: LearnerProfile,
) -> dict[str, list[tuple[AnswerRecord, DiagnosticQuestion]]]:
    knowledge_by_id = {
        item.id: item.public_id
        for item in db.scalars(
            select(KnowledgeItem).where(
                KnowledgeItem.domain_code == domain_code,
                KnowledgeItem.public_id.in_(core_ids),
            )
        )
    }
    if not knowledge_by_id:
        return {}
    rows = list(
        db.execute(
            select(AnswerRecord, DiagnosticQuestion)
            .join(DiagnosticQuestion, DiagnosticQuestion.id == AnswerRecord.question_id)
            .where(
                AnswerRecord.learner_id == learner_id,
                AnswerRecord.knowledge_item_id.in_(knowledge_by_id),
                AnswerRecord.scoring_status == "scored",
                AnswerRecord.is_correct.is_(True),
                AnswerRecord.confidence >= FORMAL_EVIDENCE_CONFIDENCE_FLOOR,
                DiagnosticQuestion.status == "active",
                DiagnosticQuestion.certification_status == "certified",
            )
            .order_by(AnswerRecord.created_at, AnswerRecord.id)
        )
    )
    grouped: dict[str, list[tuple[AnswerRecord, DiagnosticQuestion]]] = defaultdict(list)
    seen: dict[str, set[int]] = defaultdict(set)
    for record, question in rows:
        summary = record.answer_summary_json or {}
        evidence_type = str(summary.get("evidence_type") or "")
        if (
            summary.get("contract_evidence_type") != "scored_quiz"
            or summary.get("confirmed") is not True
            or evidence_type not in FORMAL_EVIDENCE_TYPES
        ):
            continue
        consumed_by = summary.get("consumed_by_profile_id")
        if consumed_by not in {None, profile.id}:
            continue
        knowledge_id = knowledge_by_id.get(record.knowledge_item_id)
        if not knowledge_id or question.id in seen[knowledge_id]:
            continue
        seen[knowledge_id].add(question.id)
        grouped[knowledge_id].append((record, question))
    return grouped


def _quiz_completed(
    db: Session,
    *,
    learner_id: int,
    package_task: GenerationTask | None,
) -> bool:
    if package_task is None:
        return False
    quiz_ids = [
        resource.id
        for _member, resource in package_member_rows(db, package_task)
        if resource.resource_type == "graded_quiz"
    ]
    if not quiz_ids:
        return False
    return db.scalar(
        select(ResourceQuizAttempt.id).where(
            ResourceQuizAttempt.learner_id == learner_id,
            ResourceQuizAttempt.resource_id.in_(quiz_ids),
            ResourceQuizAttempt.status == "completed",
        )
    ) is not None


def build_node_gate(
    db: Session,
    *,
    path: LearningPath,
    profile: LearnerProfile,
    package_task: GenerationTask | None = None,
) -> dict[str, Any]:
    payload = path.path_json or {}
    node_id = payload.get("current_node_id")
    node = (payload.get("node_states") or {}).get(node_id) if node_id else None
    if not isinstance(node, dict):
        return {
            "status": "unavailable",
            "can_advance": False,
            "reason": "CURRENT_NODE_UNAVAILABLE",
            "path_node_id": node_id,
            "knowledge_progress": [],
            "blocking_mistake_count": 0,
            "quiz_completed": False,
        }
    core_ids = node_core_knowledge_ids(node)
    grouped = _formal_positive_records(
        db,
        learner_id=profile.learner_id,
        domain_code=path.domain_code,
        core_ids=core_ids,
        profile=profile,
    )
    target_difficulty = int(node.get("target_difficulty") or 3)
    progress: list[dict[str, Any]] = []
    mastered_ids: list[str] = []
    for knowledge_id in core_ids:
        records = grouped.get(knowledge_id, [])
        evidence_types = {
            str((record.answer_summary_json or {}).get("evidence_type") or "")
            for record, _question in records
        }
        has_corroboration = bool(evidence_types & CORROBORATING_EVIDENCE_TYPES)
        has_target_difficulty = any(
            int(question.difficulty or 1) >= target_difficulty for _record, question in records
        )
        evidence_ready = (
            len(records) >= REQUIRED_EVIDENCE_COUNT
            and has_corroboration
            and has_target_difficulty
        )
        # A profile classification does not replace current-node completion evidence.
        mastered = evidence_ready
        if mastered:
            mastered_ids.append(knowledge_id)
        progress.append(
            {
                "knowledge_id": knowledge_id,
                "mastered": mastered,
                "eligible_evidence_count": len(records),
                "required_evidence_count": REQUIRED_EVIDENCE_COUNT,
                "has_corroborating_evidence": has_corroboration,
                "has_target_difficulty_evidence": has_target_difficulty,
                "evidence_ids": [f"answer_record:{record.id}" for record, _ in records],
            }
        )
    unresolved = list(
        db.scalars(
            select(MistakeReviewItem).join(
                KnowledgeItem, KnowledgeItem.id == MistakeReviewItem.knowledge_item_id
            ).where(
                MistakeReviewItem.learner_id == profile.learner_id,
                MistakeReviewItem.domain_code == path.domain_code,
                KnowledgeItem.public_id.in_(core_ids),
                MistakeReviewItem.status.in_(UNRESOLVED_MISTAKE_STATUSES),
            )
        )
    ) if core_ids else []
    quiz_completed = _quiz_completed(
        db,
        learner_id=profile.learner_id,
        package_task=package_task,
    )
    unmastered_ids = [item for item in core_ids if item not in mastered_ids]
    can_advance = bool(core_ids) and not unmastered_ids and not unresolved and quiz_completed
    reason = (
        "NODE_REQUIREMENTS_MET"
        if can_advance
        else "GRADED_QUIZ_REQUIRED"
        if not quiz_completed
        else "BLOCKING_MISTAKES_REMAIN"
        if unresolved
        else "CORE_KNOWLEDGE_EVIDENCE_INSUFFICIENT"
    )
    return {
        "status": "completed" if can_advance else "in_progress",
        "can_advance": can_advance,
        "reason": reason,
        "path_node_id": node_id,
        "core_knowledge_count": len(core_ids),
        "mastered_knowledge_count": len(mastered_ids),
        "mastered_knowledge_ids": mastered_ids,
        "unmastered_knowledge_ids": unmastered_ids,
        "knowledge_progress": progress,
        "blocking_mistake_count": len(unresolved),
        "blocking_mistake_ids": [item.public_id for item in unresolved],
        "quiz_completed": quiz_completed,
    }


def affected_resource_types(
    *,
    package_task: GenerationTask,
    affected_knowledge_ids: list[str],
    fallback_resource_type: str,
) -> list[str]:
    affected = set(affected_knowledge_ids)
    targets = package_task.resource_knowledge_targets_json or {}
    selected = [
        resource_type
        for resource_type in RESOURCE_TYPE_ORDER
        if affected & set(str(value) for value in targets.get(resource_type) or [])
    ]
    return selected or [fallback_resource_type]
