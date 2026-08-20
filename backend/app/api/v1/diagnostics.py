from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import Principal, get_current_user, self_service_learner
from app.schemas.common import ApiResponse, fail, ok
from app.services.diagnostic_service import (
    DiagnosticScoringPending,
    create_diagnostic_session,
    submit_diagnostic_session,
)

router = APIRouter()


@router.post("/sessions", response_model=ApiResponse)
def create_session(
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    payload = payload or {}
    if not str(payload.get("domain_code") or "").strip():
        raise HTTPException(status_code=422, detail="domain_code is required")
    try:
        result = create_diagnostic_session(
            db,
            learner_id=self_service_learner(principal, payload.get("learner_id")),
            domain_code=str(payload.get("domain_code") or ""),
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
    if not str(payload.get("domain_code") or "").strip():
        raise HTTPException(status_code=422, detail="domain_code is required")
    try:
        result = submit_diagnostic_session(
            db,
            session_id=session_id,
            learner_id=self_service_learner(principal, payload.get("learner_id")),
            domain_code=str(payload.get("domain_code") or ""),
            answers=payload.get("answers", []),
        )
    except DiagnosticScoringPending:
        body = fail(
            "DIAGNOSTIC_SCORING_PENDING",
            "AI 评分暂未完成，请保留当前答案后重试。",
            {"session_id": session_id, "retryable": True},
        )
        return JSONResponse(status_code=503, content=body.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc).upper()) from exc
    return ok(result)
