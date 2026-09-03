from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AnswerRecord,
    DiagnosticQuestion,
    GenerationTask,
    KnowledgeItem,
    Learner,
    LearnerProfile,
    LearningPath,
    LearningResource,
    MistakeReviewItem,
    ResourceQuizAttempt,
)
from app.services.mistake_review_service import RETIRED_STATUS, _upsert_item


OBJECTIVE_TYPES = {"single_choice", "multiple_choice"}
INVALIDATION_STATUS = "invalidated"


def _normalize(value: str) -> str:
    return re.sub(r"[\s,，、;；]+", "", re.sub(r"^[A-Za-z][.、:：)\s]+", "", value.strip().lower()))


def _resource_owner(db: Session, resource: LearningResource, learner_id: int) -> GenerationTask:
    task = db.get(GenerationTask, resource.generation_task_id)
    if task is None or task.learner_id != learner_id or resource.resource_type != "graded_quiz":
        raise ValueError("QUIZ_RESOURCE_NOT_FOUND")
    return task


def _questions(resource: LearningResource) -> list[dict[str, Any]]:
    payload = resource.structured_content_json or {}
    questions = payload.get("questions") if isinstance(payload, dict) else None
    if not isinstance(questions, list):
        raise ValueError("QUIZ_CONTENT_UNAVAILABLE")
    return [item for item in questions if isinstance(item, dict)]


def _serialize(attempt: ResourceQuizAttempt) -> dict[str, Any]:
    system = dict((attempt.answers_json or {}).get("_system") or {})
    return {
        "attempt_id": attempt.public_id,
        "resource_version": attempt.resource_version,
        "status": attempt.status,
        "current_question_id": attempt.current_question_id,
        "answers": attempt.answers_json or {},
        "objective_correct": attempt.objective_correct,
        "objective_total": attempt.objective_total,
        "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else None,
        "requires_regeneration": attempt.status == INVALIDATION_STATUS,
        "invalidation_reason": system.get("invalidation_reason"),
        "invalidation_message": system.get("invalidation_message"),
    }


def _formal_question_for_payload(
    db: Session, *, task: GenerationTask, question_payload: dict[str, Any]
) -> DiagnosticQuestion | None:
    public_ids = list(
        dict.fromkeys(
            str(value)
            for value in [
                question_payload.get("question_id"),
                *(question_payload.get("reference_question_ids") or []),
            ]
            if str(value)
        )
    )
    if not public_ids:
        return None
    rows = list(
        db.scalars(
            select(DiagnosticQuestion)
            .where(
                DiagnosticQuestion.domain_code == task.domain_code,
                DiagnosticQuestion.public_id.in_(public_ids),
                DiagnosticQuestion.status == "active",
            )
            .order_by(DiagnosticQuestion.id)
        )
    )
    return rows[0] if rows else None


def _formal_evidence_issue(
    db: Session, *, task: GenerationTask, questions: list[dict[str, Any]]
) -> str | None:
    if not task.path_node_id:
        return None
    for question in questions:
        if str(question.get("question_type") or "") not in OBJECTIVE_TYPES:
            continue
        if _formal_question_for_payload(db, task=task, question_payload=question) is None:
            return "当前测试引用的正式题已停用或不可用，请重新生成当前节点测试。"
    return None


def _invalidate_attempt(attempt: ResourceQuizAttempt, *, reason: str) -> None:
    payload = dict(attempt.answers_json or {})
    payload["_system"] = {
        "invalidation_reason": "FORMAL_QUESTION_UNAVAILABLE",
        "invalidation_message": reason,
        "invalidated_at": datetime.now(UTC).isoformat(),
    }
    attempt.answers_json = payload
    attempt.status = INVALIDATION_STATUS


def _retire_attempt_mistakes(db: Session, *, attempt: ResourceQuizAttempt, reason: str) -> None:
    """Keep an invalidated quiz from leaving unresolved path blockers behind."""

    items = db.scalars(
        select(MistakeReviewItem).where(
            MistakeReviewItem.learner_id == attempt.learner_id,
            MistakeReviewItem.source_type == "graded_quiz",
            MistakeReviewItem.source_record_id.like(f"{attempt.public_id}:%"),
            MistakeReviewItem.status != "consolidated",
        )
    )
    for item in items:
        summary = dict(item.error_summary_json or {})
        summary.update(
            {
                "retired_reason": "FORMAL_QUESTION_UNAVAILABLE",
                "retired_message": reason,
            }
        )
        item.error_summary_json = summary
        item.status = RETIRED_STATUS


def _latest_attempt(
    db: Session, *, learner_id: int, resource: LearningResource
) -> ResourceQuizAttempt | None:
    return db.scalar(
        select(ResourceQuizAttempt)
        .where(
            ResourceQuizAttempt.learner_id == learner_id,
            ResourceQuizAttempt.resource_id == resource.id,
            ResourceQuizAttempt.resource_version == resource.version,
        )
        .order_by(ResourceQuizAttempt.id.desc())
    )


def current_or_create(
    db: Session, *, learner: Learner, resource: LearningResource
) -> dict[str, Any]:
    task = _resource_owner(db, resource, learner.id)
    attempt = _latest_attempt(db, learner_id=learner.id, resource=resource)
    if attempt is None:
        attempt = ResourceQuizAttempt(
            public_id=f"quiztry_{uuid4().hex[:12]}",
            learner_id=learner.id,
            resource_id=resource.id,
            resource_version=resource.version,
            status="in_progress",
            answers_json={},
        )
        db.add(attempt)
        issue = _formal_evidence_issue(db, task=task, questions=_questions(resource))
        if issue:
            _invalidate_attempt(attempt, reason=issue)
            _retire_attempt_mistakes(db, attempt=attempt, reason=issue)
        db.commit()
    return _serialize(attempt)


def current(db: Session, *, learner: Learner, resource: LearningResource) -> dict[str, Any] | None:
    _resource_owner(db, resource, learner.id)
    attempt = _latest_attempt(db, learner_id=learner.id, resource=resource)
    return _serialize(attempt) if attempt else None


def _judge(question: dict[str, Any], answer: Any) -> bool | None:
    question_type = str(question.get("question_type") or "")
    if question_type not in OBJECTIVE_TYPES:
        return None
    selected = answer if isinstance(answer, list) else [answer]
    chosen = [_normalize(str(value)) for value in selected if str(value).strip()]
    correct_raw = str(question.get("correct_answer") or "")
    correct = [_normalize(part) for part in re.split(r"[、,，;；]", correct_raw) if part.strip()]
    if question_type == "single_choice":
        return bool(chosen) and chosen[0] == _normalize(correct_raw)
    return bool(chosen) and len(chosen) == len(correct) and all(value in chosen for value in correct)


def save_answer(
    db: Session,
    *,
    learner: Learner,
    resource: LearningResource,
    attempt_id: str,
    question_id: str,
    answer: Any,
    self_checked: bool = False,
) -> dict[str, Any]:
    task = _resource_owner(db, resource, learner.id)
    attempt = db.scalar(
        select(ResourceQuizAttempt).where(ResourceQuizAttempt.public_id == attempt_id).with_for_update()
    )
    if attempt is None or attempt.learner_id != learner.id or attempt.resource_id != resource.id:
        raise ValueError("QUIZ_ATTEMPT_NOT_FOUND")
    if attempt.status == INVALIDATION_STATUS:
        raise ValueError("QUIZ_ATTEMPT_REQUIRES_REGENERATION")
    if attempt.status == "completed":
        raise ValueError("QUIZ_ATTEMPT_COMPLETED")
    question = next((item for item in _questions(resource) if str(item.get("question_id")) == question_id), None)
    if question is None:
        raise ValueError("QUIZ_QUESTION_NOT_FOUND")
    correct = _judge(question, answer)
    answers = dict(attempt.answers_json or {})
    answers[question_id] = {
        "answer": answer,
        "checked": True,
        "correct": correct,
        "self_checked": bool(self_checked) if correct is None else False,
        "synced_at": datetime.now(UTC).isoformat(),
    }
    attempt.answers_json = answers
    attempt.current_question_id = question_id
    objective = [value for value in answers.values() if value.get("correct") is not None]
    attempt.objective_total = len(objective)
    attempt.objective_correct = sum(value.get("correct") is True for value in objective)
    if correct is False:
        knowledge = db.scalar(
            select(KnowledgeItem).where(
                KnowledgeItem.domain_code == task.domain_code,
                KnowledgeItem.public_id == str(question.get("knowledge_id") or ""),
            )
        )
        if knowledge is not None:
            formal_question = _formal_question_for_payload(
                db, task=task, question_payload=question
            )
            _upsert_item(
                db,
                learner_id=learner.id,
                domain_code=task.domain_code,
                knowledge_item_id=knowledge.id,
                source_type="graded_quiz",
                source_record_id=f"{attempt.public_id}:{question_id}",
                source_resource_id=resource.id,
                question_type=str(question.get("question_type") or ""),
                difficulty=int(question.get("difficulty") or resource.difficulty),
                summary={
                    "question_id": question_id,
                    "formal_question_id": (
                        formal_question.public_id if formal_question is not None else None
                    ),
                    "reference_question_ids": list(question.get("reference_question_ids") or []),
                    "score": 0,
                    "comment": "分阶测试客观题未达到掌握标准",
                    "question": {
                        "stem": str(question.get("prompt") or ""),
                        "options": question.get("options") or [],
                    },
                },
            )
    db.commit()
    return {**_serialize(attempt), "question_id": question_id, "correct": correct, "synced": True}


def complete(
    db: Session, *, learner: Learner, resource: LearningResource, attempt_id: str
) -> dict[str, Any]:
    task = _resource_owner(db, resource, learner.id)
    attempt = db.scalar(
        select(ResourceQuizAttempt).where(ResourceQuizAttempt.public_id == attempt_id).with_for_update()
    )
    if attempt is None or attempt.learner_id != learner.id or attempt.resource_id != resource.id:
        raise ValueError("QUIZ_ATTEMPT_NOT_FOUND")
    questions = _questions(resource)
    objective_questions = [
        question for question in questions
        if str(question.get("question_type") or "") in OBJECTIVE_TYPES
    ]
    issue = _formal_evidence_issue(db, task=task, questions=objective_questions)
    if issue:
        _invalidate_attempt(attempt, reason=issue)
        _retire_attempt_mistakes(db, attempt=attempt, reason=issue)
        db.commit()
        return {
            **_serialize(attempt),
            "evidence_result": {"materialized_count": 0, "evidence_ids": [], "governance_results": []},
            "node_gate": _node_gate_for_attempt(db, learner=learner, task=task),
        }
    answers = attempt.answers_json or {}
    if any(
        not isinstance(answers.get(str(question.get("question_id") or "")), dict)
        or answers[str(question.get("question_id") or "" )].get("correct") is None
        for question in objective_questions
    ):
        raise ValueError("QUIZ_ATTEMPT_INCOMPLETE")
    attempt.status = "completed"
    attempt.completed_at = attempt.completed_at or datetime.now(UTC)
    evidence_records = _materialize_objective_evidence(
        db,
        learner=learner,
        resource=resource,
        task=task,
        attempt=attempt,
        questions=objective_questions,
    )
    governance_results = _evaluate_materialized_evidence(
        db,
        learner=learner,
        resource=resource,
        records=evidence_records,
    )
    node_gate = _node_gate_for_attempt(
        db,
        learner=learner,
        task=task,
    )
    db.commit()
    return {
        **_serialize(attempt),
        "evidence_result": {
            "materialized_count": len(evidence_records),
            "evidence_ids": [f"answer_record:{record.id}" for record in evidence_records],
            "governance_results": governance_results,
        },
        "node_gate": node_gate,
    }


def _materialize_objective_evidence(
    db: Session,
    *,
    learner: Learner,
    resource: LearningResource,
    task: GenerationTask,
    attempt: ResourceQuizAttempt,
    questions: list[dict[str, Any]],
) -> list[AnswerRecord]:
    evidence_records: list[AnswerRecord] = []
    answers = attempt.answers_json or {}
    for question_payload in questions:
        question = _formal_question_for_payload(
            db, task=task, question_payload=question_payload
        )
        if question is None:
            continue
        existing = db.scalar(
            select(AnswerRecord).where(
                AnswerRecord.learner_id == learner.id,
                AnswerRecord.session_id == attempt.public_id,
                AnswerRecord.question_id == question.id,
            )
        )
        if existing is None:
            answer_payload = answers.get(str(question_payload.get("question_id") or "")) or {}
            is_correct = answer_payload.get("correct") is True
            answer_value = answer_payload.get("answer")
            existing = AnswerRecord(
                learner_id=learner.id,
                question_id=question.id,
                knowledge_item_id=question.knowledge_item_id,
                session_id=attempt.public_id,
                answer_text=str(answer_value if answer_value is not None else "")[:2000],
                score=1.0 if is_correct else 0.0,
                is_correct=is_correct,
                scoring_status="scored",
                scoring_method="deterministic",
                confidence=1.0,
                answer_summary_json={
                    "evidence_type": "graded_quiz",
                    "evidence_role": "validation",
                    "contract_evidence_type": "scored_quiz",
                    "confirmed": True,
                    "confidence": 1.0,
                    "resource_id": resource.public_id,
                    "resource_version": resource.version,
                    "generation_task_id": task.public_id,
                    "path_node_id": task.path_node_id,
                    "quiz_attempt_id": attempt.public_id,
                    "consumed_by_profile_id": None,
                },
            )
            db.add(existing)
            db.flush()
        evidence_records.append(existing)
    return evidence_records


def _evaluate_materialized_evidence(
    db: Session,
    *,
    learner: Learner,
    resource: LearningResource,
    records: list[AnswerRecord],
) -> list[dict[str, Any]]:
    from app.services.mistake_evidence_service import evaluate_mistake_evidence

    results: list[dict[str, Any]] = []
    for record in records:
        item = db.scalar(
            select(MistakeReviewItem)
            .where(
                MistakeReviewItem.learner_id == learner.id,
                MistakeReviewItem.knowledge_item_id == record.knowledge_item_id,
            )
            .order_by(MistakeReviewItem.id.desc())
        )
        if item is None:
            continue
        results.append(
            evaluate_mistake_evidence(
                db,
                learner=learner,
                item=item,
                record=record,
                resource=resource,
            )
        )
    return results


def _node_gate_for_attempt(
    db: Session,
    *,
    learner: Learner,
    task: GenerationTask,
) -> dict[str, Any] | None:
    path = db.scalar(
        select(LearningPath)
        .where(
            LearningPath.learner_id == learner.id,
            LearningPath.domain_code == task.domain_code,
            LearningPath.status == "active",
        )
        .order_by(LearningPath.created_at.desc(), LearningPath.id.desc())
    )
    profile = db.get(LearnerProfile, path.profile_id) if path else None
    if path is None or profile is None:
        return None
    from app.services.node_mastery_service import build_node_gate

    return build_node_gate(
        db,
        path=path,
        profile=profile,
        package_task=task,
    )


def backfill_completed_attempt_evidence(db: Session) -> int:
    materialized = 0
    attempts = list(
        db.scalars(
            select(ResourceQuizAttempt)
            .where(ResourceQuizAttempt.status == "completed")
            .order_by(ResourceQuizAttempt.id)
        )
    )
    for attempt in attempts:
        learner = db.get(Learner, attempt.learner_id)
        resource = db.get(LearningResource, attempt.resource_id)
        if learner is None or resource is None:
            continue
        try:
            task = _resource_owner(db, resource, learner.id)
            objective_questions = [
                question
                for question in _questions(resource)
                if str(question.get("question_type") or "") in OBJECTIVE_TYPES
            ]
        except ValueError:
            continue
        existing_question_ids = set(
            db.scalars(
                select(AnswerRecord.question_id).where(
                    AnswerRecord.session_id == attempt.public_id
                )
            )
        )
        records = _materialize_objective_evidence(
            db,
            learner=learner,
            resource=resource,
            task=task,
            attempt=attempt,
            questions=objective_questions,
        )
        materialized += sum(
            record.question_id not in existing_question_ids for record in records
        )
    return materialized
