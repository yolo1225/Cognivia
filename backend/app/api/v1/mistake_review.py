from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import Principal, get_current_user, principal_learner
from app.schemas.common import ApiResponse, ok
from app.models import Learner
from app.services.mistake_review_service import (
    answer_attempt,
    learner_by_public_id,
    list_items,
    require_item,
    serialize_item,
    start_attempt,
    summary,
)

router = APIRouter()


def _raise(exc: ValueError) -> HTTPException:
    code = str(exc).upper()
    messages = {
        "MISTAKE_REVIEW_ITEM_RETIRED": "原题已停用，无法继续错题巩固；请使用当前题库完成补测。",
        "CONSOLIDATION_QUESTION_RETIRED": "原题已停用，无法继续错题巩固；请使用当前题库完成补测。",
    }
    return HTTPException(404 if code.endswith("NOT_FOUND") else 409, messages.get(code, code))


def _learner(
    db: Session, principal: Principal, requested: str | None = None
) -> Learner:
    return learner_by_public_id(db, principal_learner(principal, requested))


@router.get("/summary", response_model=ApiResponse)
def get_summary(
    domain_code: str = Query(...),
    learner_id: str | None = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    learner = _learner(db, principal, learner_id)
    return ok(summary(db, learner=learner, domain_code=domain_code))


@router.get("/items", response_model=ApiResponse)
def get_items(
    domain_code: str = Query(...),
    learner_id: str | None = Query(None),
    status: str | None = Query(None),
    source_type: str | None = Query(None),
    knowledge_id: str | None = Query(None),
    difficulty: int | None = Query(None, ge=1, le=5),
    priority_scope: Literal["current_node", "all"] | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    learner = _learner(db, principal, learner_id)
    return ok(list_items(
        db, learner=learner, domain_code=domain_code, status=status, source_type=source_type,
        knowledge_id=knowledge_id, difficulty=difficulty, priority_scope=priority_scope,
        page=page, page_size=page_size,
    ))


@router.get("/items/{item_id}", response_model=ApiResponse)
def get_item(
    item_id: str,
    learner_id: str | None = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    learner = _learner(db, principal, learner_id)
    try:
        return ok(serialize_item(db, require_item(db, learner=learner, item_id=item_id), include_detail=True))
    except ValueError as exc:
        raise _raise(exc) from exc


@router.post("/items/{item_id}/start", response_model=ApiResponse)
def start(
    item_id: str,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    learner = _learner(db, principal, (payload or {}).get("learner_id"))
    try:
        return ok(start_attempt(db, learner=learner, item_id=item_id))
    except ValueError as exc:
        raise _raise(exc) from exc


@router.post("/items/{item_id}/attempts/{attempt_id}/answer", response_model=ApiResponse)
def answer(
    item_id: str,
    attempt_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    learner = _learner(db, principal, payload.get("learner_id"))
    try:
        return ok(answer_attempt(
            db, learner=learner, item_id=item_id, attempt_id=attempt_id, answer=payload.get("answer")
        ))
    except ValueError as exc:
        raise _raise(exc) from exc
