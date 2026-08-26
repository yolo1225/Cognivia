from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import GenerationTask, KnowledgeItem, Learner, LearningResource, ResourceQuizAttempt
from app.services.mistake_review_service import _upsert_item


OBJECTIVE_TYPES = {"single_choice", "multiple_choice"}


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
    return {
        "attempt_id": attempt.public_id,
        "resource_version": attempt.resource_version,
        "status": attempt.status,
        "current_question_id": attempt.current_question_id,
        "answers": attempt.answers_json or {},
        "objective_correct": attempt.objective_correct,
        "objective_total": attempt.objective_total,
        "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else None,
    }


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
    _resource_owner(db, resource, learner.id)
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
    _resource_owner(db, resource, learner.id)
    attempt = db.scalar(
        select(ResourceQuizAttempt).where(ResourceQuizAttempt.public_id == attempt_id).with_for_update()
    )
    if attempt is None or attempt.learner_id != learner.id or attempt.resource_id != resource.id:
        raise ValueError("QUIZ_ATTEMPT_NOT_FOUND")
    attempt.status = "completed"
    attempt.completed_at = attempt.completed_at or datetime.now(UTC)
    db.commit()
    return _serialize(attempt)
