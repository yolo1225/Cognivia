from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AnswerRecord,
    DiagnosticQuestion,
    DiagnosticSession,
    GenerationTask,
    KnowledgeItem,
    Learner,
    LearningResource,
    MistakeReviewAttempt,
    MistakeReviewItem,
    PathNodeAssessment,
)
from app.services.knowledge_extraction_service import normalize_knowledge_name
from app.services.question_certification_service import (
    QUESTION_CERTIFICATION_RULE_VERSION,
)


VERIFIED_STATUSES = {"consolidated", "needs_more_practice"}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _serialize_attempt(attempt: MistakeReviewAttempt) -> dict[str, Any]:
    return {
        "attempt_id": attempt.public_id,
        "status": attempt.status,
        "score": attempt.score,
        "threshold": attempt.threshold,
        "confidence": attempt.confidence,
        "scoring_method": attempt.scoring_method,
        "evidence_ref": attempt.evidence_ref,
        "completed_at": _iso(attempt.completed_at),
    }


def learner_by_public_id(db: Session, learner_id: str) -> Learner:
    learner = db.scalar(select(Learner).where(Learner.public_id == learner_id))
    if learner is None:
        raise ValueError("LEARNER_NOT_FOUND")
    return learner


def _upsert_item(
    db: Session,
    *,
    learner_id: int,
    domain_code: str,
    knowledge_item_id: int,
    source_type: str,
    source_record_id: str,
    question_type: str,
    difficulty: int,
    summary: dict[str, Any],
    source_resource_id: int | None = None,
    uncertain: bool = False,
    wrong_at: datetime | None = None,
) -> MistakeReviewItem:
    item = db.scalar(
        select(MistakeReviewItem).where(
            MistakeReviewItem.learner_id == learner_id,
            MistakeReviewItem.domain_code == domain_code,
            MistakeReviewItem.source_type == source_type,
            MistakeReviewItem.source_record_id == source_record_id,
        )
    )
    if item is None:
        item = MistakeReviewItem(
            public_id=f"mistake_{uuid4().hex[:12]}",
            learner_id=learner_id,
            domain_code=domain_code,
            knowledge_item_id=knowledge_item_id,
            source_type=source_type,
            source_record_id=source_record_id,
            source_resource_id=source_resource_id,
            question_type=question_type,
            difficulty=difficulty,
            status="verification_pending" if uncertain else "pending",
            error_summary_json=summary,
            last_wrong_at=wrong_at or datetime.now(UTC),
        )
        db.add(item)
    elif item.status != "consolidated":
        item.error_summary_json = summary
        item.last_wrong_at = wrong_at or item.last_wrong_at or datetime.now(UTC)
        if uncertain:
            item.status = "verification_pending"
    return item


def sync_existing_mistakes(db: Session, *, learner: Learner, domain_code: str) -> None:
    diagnostic_rows = list(
        db.execute(
            select(AnswerRecord, DiagnosticQuestion)
            .join(DiagnosticQuestion, DiagnosticQuestion.id == AnswerRecord.question_id)
            .join(DiagnosticSession, DiagnosticSession.public_id == AnswerRecord.session_id)
            .where(
                AnswerRecord.learner_id == learner.id,
                DiagnosticSession.domain_code == domain_code,
                DiagnosticQuestion.domain_code == domain_code,
                AnswerRecord.is_correct.is_(False),
            )
        )
    )
    for record, question in diagnostic_rows:
        _upsert_item(
            db,
            learner_id=learner.id,
            domain_code=domain_code,
            knowledge_item_id=record.knowledge_item_id,
            source_type="initial_diagnostic",
            source_record_id=str(record.id),
            question_type=question.question_type,
            difficulty=question.difficulty,
            uncertain=bool(record.scoring_uncertain or record.scoring_status != "scored"),
            wrong_at=record.created_at,
            summary={
                "question_id": question.public_id,
                "score": record.score,
                "comment": record.ai_comment or "本题未达到掌握标准",
                "scoring_method": record.scoring_method,
            },
        )

    path_rows = list(
        db.execute(
            select(PathNodeAssessment, DiagnosticQuestion)
            .join(DiagnosticQuestion, DiagnosticQuestion.id == PathNodeAssessment.question_id)
            .where(
                PathNodeAssessment.learner_id == learner.id,
                DiagnosticQuestion.domain_code == domain_code,
                PathNodeAssessment.status == "scored",
                PathNodeAssessment.passed.is_(False),
            )
        )
    )
    for assessment, question in path_rows:
        _upsert_item(
            db,
            learner_id=learner.id,
            domain_code=domain_code,
            knowledge_item_id=question.knowledge_item_id,
            source_type="path_assessment",
            source_record_id=assessment.public_id,
            question_type=question.question_type,
            difficulty=question.difficulty,
            wrong_at=assessment.updated_at,
            summary={
                "question_id": question.public_id,
                "score": assessment.score,
                "comment": "路径节点验证未达到通过阈值",
                "path_node_id": assessment.path_node_id,
            },
        )


def _knowledge(db: Session, item: MistakeReviewItem) -> KnowledgeItem | None:
    return db.get(KnowledgeItem, item.knowledge_item_id)


def _recommended_resource(db: Session, item: MistakeReviewItem) -> LearningResource | None:
    if item.source_resource_id:
        resource = db.get(LearningResource, item.source_resource_id)
        if resource and resource.review_status == "passed":
            return resource
    knowledge = _knowledge(db, item)
    if knowledge is None:
        return None
    rows = list(
        db.scalars(
            select(LearningResource)
            .join(GenerationTask, GenerationTask.id == LearningResource.generation_task_id)
            .where(
                GenerationTask.learner_id == item.learner_id,
                GenerationTask.domain_code == item.domain_code,
                LearningResource.review_status == "passed",
                LearningResource.is_current.is_(True),
            )
            .order_by(LearningResource.id.desc())
        )
    )
    for resource in rows:
        source_ids = {
            str(source.get("knowledge_id")) if isinstance(source, dict) else str(source)
            for source in (resource.sources_json or [])
        }
        if knowledge.public_id in source_ids:
            return resource
    return None


def serialize_item(db: Session, item: MistakeReviewItem, *, include_detail: bool = False) -> dict[str, Any]:
    knowledge = _knowledge(db, item)
    resource = _recommended_resource(db, item)
    summary = dict(item.error_summary_json or {})
    data = {
        "item_id": item.public_id,
        "knowledge_id": knowledge.public_id if knowledge else None,
        "knowledge_name": normalize_knowledge_name(knowledge.name) if knowledge else "知识点已不可用",
        "category": knowledge.category if knowledge else "",
        "source_type": item.source_type,
        "question_type": item.question_type,
        "difficulty": item.difficulty,
        "status": item.status,
        "last_score": summary.get("score"),
        "error_summary": summary.get("comment") or "需要进一步巩固",
        "last_wrong_at": _iso(item.last_wrong_at),
        "review_count": item.review_count,
        "consolidated_at": _iso(item.consolidated_at),
        "recommended_resource": (
            {"resource_id": resource.public_id, "title": resource.title, "resource_type": resource.resource_type}
            if resource
            else None
        ),
    }
    if include_detail:
        question_id = summary.get("question_id")
        question = db.scalar(
            select(DiagnosticQuestion).where(DiagnosticQuestion.public_id == question_id)
        ) if question_id else None
        attempts = list(
            db.scalars(
                select(MistakeReviewAttempt)
                .where(MistakeReviewAttempt.mistake_item_id == item.id)
                .order_by(MistakeReviewAttempt.id.desc())
            )
        )
        data.update(
            {
                "question": ({"stem": question.stem, "options": question.options_json} if question else summary.get("question")),
                "scoring_comment": summary.get("comment"),
                "attempts": [_serialize_attempt(attempt) for attempt in attempts],
                "has_profile_evidence": any(attempt.evidence_ref for attempt in attempts),
                "tutoring_available": resource is not None,
                "evidence_governance": _latest_governance(db, attempts),
            }
        )
    return data


def summary(db: Session, *, learner: Learner, domain_code: str) -> dict[str, Any]:
    items = list(
        db.scalars(
            select(MistakeReviewItem).where(
                MistakeReviewItem.learner_id == learner.id,
                MistakeReviewItem.domain_code == domain_code,
            )
        )
    )
    consolidated = sum(item.status == "consolidated" for item in items)
    verified = sum(item.status in VERIFIED_STATUSES for item in items)
    pending = sum(item.status in {"pending", "verification_pending", "needs_more_practice"} for item in items)
    in_progress = sum(item.status == "reviewing" for item in items)
    counts: dict[int, int] = {}
    for item in items:
        if item.status != "consolidated":
            counts[item.knowledge_item_id] = counts.get(item.knowledge_item_id, 0) + 1
    focus = db.get(KnowledgeItem, max(counts, key=counts.get)) if counts else None
    return {
        "total": len(items),
        "pending": pending,
        "in_progress": in_progress,
        "consolidated": consolidated,
        "verified": verified,
        "consolidation_rate": round(consolidated / verified * 100, 1) if verified else None,
        "focus_knowledge": ({"knowledge_id": focus.public_id, "name": normalize_knowledge_name(focus.name)} if focus else None),
    }


def list_items(
    db: Session,
    *,
    learner: Learner,
    domain_code: str,
    status: str | None,
    source_type: str | None,
    knowledge_id: str | None,
    difficulty: int | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    statement = select(MistakeReviewItem).where(
        MistakeReviewItem.learner_id == learner.id,
        MistakeReviewItem.domain_code == domain_code,
    )
    if status:
        statement = statement.where(MistakeReviewItem.status == status)
    if source_type:
        statement = statement.where(MistakeReviewItem.source_type == source_type)
    if difficulty is not None:
        statement = statement.where(MistakeReviewItem.difficulty == difficulty)
    if knowledge_id:
        statement = statement.join(KnowledgeItem).where(KnowledgeItem.public_id == knowledge_id)
    count = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = list(
        db.scalars(
            statement.order_by(MistakeReviewItem.last_wrong_at.desc(), MistakeReviewItem.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return {"items": [serialize_item(db, item) for item in rows], "total": count, "page": page, "page_size": page_size}


def require_item(db: Session, *, learner: Learner, item_id: str) -> MistakeReviewItem:
    item = db.scalar(select(MistakeReviewItem).where(MistakeReviewItem.public_id == item_id))
    if item is None or item.learner_id != learner.id:
        raise ValueError("MISTAKE_REVIEW_ITEM_NOT_FOUND")
    return item


def start_attempt(db: Session, *, learner: Learner, item_id: str) -> dict[str, Any]:
    item = require_item(db, learner=learner, item_id=item_id)
    if item.latest_attempt_id:
        current_attempt = db.get(MistakeReviewAttempt, item.latest_attempt_id)
        current_question = (
            db.get(DiagnosticQuestion, current_attempt.question_id)
            if current_attempt and current_attempt.status == "created"
            else None
        )
        if current_attempt and current_question:
            return {
                "attempt_id": current_attempt.public_id,
                "item_id": item.public_id,
                "question": {
                    "question_id": current_question.public_id,
                    "stem": current_question.stem,
                    "options": current_question.options_json,
                    "difficulty": current_question.difficulty,
                    "question_type": current_question.question_type,
                },
                "recommended_resource": serialize_item(db, item).get("recommended_resource"),
            }
    attempted = set(
        db.scalars(
            select(MistakeReviewAttempt.question_id).where(MistakeReviewAttempt.mistake_item_id == item.id)
        )
    )
    original_question_id = (item.error_summary_json or {}).get("question_id")
    questions = list(
        db.scalars(
            select(DiagnosticQuestion)
            .where(
                DiagnosticQuestion.domain_code == item.domain_code,
                DiagnosticQuestion.knowledge_item_id == item.knowledge_item_id,
                DiagnosticQuestion.question_type == "single_choice",
                DiagnosticQuestion.status == "active",
                DiagnosticQuestion.certification_status == "certified",
                DiagnosticQuestion.certification_rule_version
                == QUESTION_CERTIFICATION_RULE_VERSION,
            )
            .order_by(func.abs(DiagnosticQuestion.difficulty - item.difficulty), DiagnosticQuestion.id)
        )
    )
    question = next(
        (q for q in questions if q.id not in attempted and q.public_id != original_question_id),
        None,
    )
    if question is None:
        raise ValueError("CONSOLIDATION_QUESTION_UNAVAILABLE")
    attempt = MistakeReviewAttempt(
        public_id=f"consolidation_{uuid4().hex[:12]}",
        mistake_item_id=item.id,
        question_id=question.id,
        status="created",
        threshold=0.8,
    )
    db.add(attempt)
    db.flush()
    item.latest_attempt_id = attempt.id
    item.status = "reviewing"
    item.review_count += 1
    db.commit()
    return {
        "attempt_id": attempt.public_id,
        "item_id": item.public_id,
        "question": {
            "question_id": question.public_id,
            "stem": question.stem,
            "options": question.options_json,
            "difficulty": question.difficulty,
            "question_type": question.question_type,
        },
        "recommended_resource": serialize_item(db, item).get("recommended_resource"),
    }


def answer_attempt(
    db: Session, *, learner: Learner, item_id: str, attempt_id: str, answer: Any
) -> dict[str, Any]:
    item = require_item(db, learner=learner, item_id=item_id)
    attempt = db.scalar(
        select(MistakeReviewAttempt).where(MistakeReviewAttempt.public_id == attempt_id).with_for_update()
    )
    if attempt is None or attempt.mistake_item_id != item.id:
        raise ValueError("CONSOLIDATION_ATTEMPT_NOT_FOUND")
    question = db.get(DiagnosticQuestion, attempt.question_id)
    if question is None or question.question_type != "single_choice":
        raise ValueError("CONSOLIDATION_QUESTION_UNAVAILABLE")
    if attempt.status in {"passed", "failed", "uncertain"}:
        from app.services.mistake_evidence_service import stored_governance_result

        stored_record = db.get(AnswerRecord, attempt.answer_record_id) if attempt.answer_record_id else None
        return {
            **_serialize_attempt(attempt),
            "passed": attempt.status == "passed",
            "explanation": (question.answer_key_json or {}).get("explanation")
            or "请结合关联资源继续巩固。",
            **(stored_governance_result(stored_record) or {}),
        }
    try:
        selected = int(answer)
    except (TypeError, ValueError) as exc:
        raise ValueError("INVALID_SINGLE_CHOICE_ANSWER") from exc
    if selected < 0 or selected >= len(question.options_json or []):
        raise ValueError("INVALID_SINGLE_CHOICE_ANSWER")
    correct = int((question.answer_key_json or {}).get("correct_option", -1))
    score = 1.0 if selected == correct else 0.0
    passed = score >= attempt.threshold
    record = AnswerRecord(
        learner_id=learner.id,
        question_id=question.id,
        knowledge_item_id=question.knowledge_item_id,
        session_id=attempt.public_id,
        answer_text=str(selected),
        score=score,
        is_correct=passed,
        scoring_status="scored",
        scoring_method="deterministic",
        confidence=1.0,
        answer_summary_json={
            "evidence_type": "mistake_consolidation",
            "contract_evidence_type": "scored_quiz",
            "mistake_item_id": item.public_id,
            "confirmed": True,
            "confidence": 1.0,
            "governance_status": "pending",
            "governance_reason": "WAITING_FOR_CORROBORATING_EVIDENCE",
            "evaluated_at": None,
            "consumed_by_profile_id": None,
        },
    )
    db.add(record)
    db.flush()
    evidence_ref = f"answer_record:{record.id}"
    attempt.answer_record_id = record.id
    attempt.status = "passed" if passed else "failed"
    attempt.score = score
    attempt.confidence = 1.0
    attempt.scoring_method = "deterministic"
    attempt.evidence_ref = evidence_ref
    attempt.completed_at = datetime.now(UTC)
    item.status = "consolidated" if passed else "needs_more_practice"
    item.consolidated_at = datetime.now(UTC) if passed else None
    from app.services.mistake_evidence_service import evaluate_mistake_evidence

    governance = evaluate_mistake_evidence(
        db,
        learner=learner,
        item=item,
        record=record,
        resource=_recommended_resource(db, item),
    )
    db.commit()
    return {
        "attempt_id": attempt.public_id,
        "status": attempt.status,
        "score": score,
        "threshold": attempt.threshold,
        "passed": passed,
        "confidence": 1.0,
        "scoring_method": "deterministic",
        "evidence_ref": evidence_ref,
        "explanation": (question.answer_key_json or {}).get("explanation") or "请结合关联资源继续巩固。",
        **governance,
    }


def _latest_governance(
    db: Session, attempts: list[MistakeReviewAttempt]
) -> dict[str, Any] | None:
    from app.services.mistake_evidence_service import stored_governance_result

    for attempt in attempts:
        if attempt.answer_record_id:
            result = stored_governance_result(db.get(AnswerRecord, attempt.answer_record_id))
            if result is not None:
                return result
    return None
