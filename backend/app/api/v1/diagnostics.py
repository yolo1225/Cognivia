from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import Principal, get_current_user, self_service_learner
from app.schemas.common import ApiResponse, ok
from app.services.diagnostic_service import create_diagnostic_session, submit_diagnostic_session

router = APIRouter()


@router.post("/sessions", response_model=ApiResponse)
def create_session(payload: dict[str, Any] | None = None, db: Session = Depends(get_db), principal: Principal = Depends(get_current_user)) -> ApiResponse:
    payload = payload or {}
    try:
        result = create_diagnostic_session(
            db,
            learner_id=self_service_learner(principal, payload.get("learner_id")),
            domain_code=payload.get("domain_code", "ai_app_dev"),
            question_count=payload.get("question_count", 10),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc).upper()) from exc
    return ok(result)


@router.post("/sessions/{session_id}/submit", response_model=ApiResponse)
def submit_session(
    session_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    try:
        result = submit_diagnostic_session(
            db,
            session_id=session_id,
            learner_id=self_service_learner(principal, payload.get("learner_id")),
            domain_code=payload.get("domain_code", "ai_app_dev"),
            answers=payload.get("answers", []),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc).upper()) from exc
    return ok(result)
