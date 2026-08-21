from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import Principal, require_admin
from app.schemas.common import ApiResponse, ok
from app.services.evaluation_case_service import prepare_evaluation_case
from app.services.evaluation_service import load_evaluation_summary

router = APIRouter()


@router.get("/summary", response_model=ApiResponse)
def get_evaluation_summary(
    mode: Literal["live", "baseline"] = Query(default="live"),
) -> ApiResponse:
    return ok(load_evaluation_summary(mode))


@router.post("/cases/{case_id}/prepare", response_model=ApiResponse, include_in_schema=False)
def prepare_case(
    case_id: str,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_admin),
) -> ApiResponse:
    if not settings.enable_evaluation_runner:
        raise HTTPException(status_code=404, detail="evaluation_runner_disabled")
    try:
        result = prepare_evaluation_case(db, case_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return ok(result)
