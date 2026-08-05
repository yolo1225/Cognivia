from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import require_idempotency_key
from app.core.db import get_db
from app.schemas.api_requests import (
    DiagnosticSessionCreateRequest,
    DiagnosticSessionSubmitRequest,
)
from app.schemas.common import ApiResponse, ok
from app.services.diagnostic_service import create_diagnostic_session, submit_diagnostic_session
from app.services.idempotency_service import execute_idempotent

router = APIRouter()


@router.post("/sessions", response_model=ApiResponse)
def create_session(
    payload: DiagnosticSessionCreateRequest,
    idempotency_key: str = Depends(require_idempotency_key),
    db: Session = Depends(get_db),
) -> ApiResponse:
    result, _ = execute_idempotent(
        db,
        scope="diagnostic_session.create",
        request_key=idempotency_key,
        operation=lambda: (
            create_diagnostic_session(
                db,
                learner_id=payload.learner_id,
                domain_code=payload.domain_code,
                question_count=payload.question_count,
            ),
            "diagnostic_session",
            None,
        ),
    )
    return ok(result)


@router.post("/sessions/{session_id}/submit", response_model=ApiResponse)
def submit_session(
    session_id: str,
    payload: DiagnosticSessionSubmitRequest,
    idempotency_key: str = Depends(require_idempotency_key),
    db: Session = Depends(get_db),
) -> ApiResponse:
    result, _ = execute_idempotent(
        db,
        scope=f"diagnostic_session.submit:{session_id}",
        request_key=idempotency_key,
        operation=lambda: (
            submit_diagnostic_session(
                db,
                session_id=session_id,
                learner_id=payload.learner_id,
                domain_code=payload.domain_code,
                answers=[item.model_dump() for item in payload.answers],
                commit=False,
            ),
            "diagnostic_session",
            session_id,
        ),
    )
    return ok(result)
