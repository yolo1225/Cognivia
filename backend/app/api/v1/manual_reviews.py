from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import require_idempotency_key
from app.core.db import get_db
from app.schemas.api_requests import ManualReviewDecisionRequest
from app.schemas.common import ApiResponse, ok
from app.services.idempotency_service import execute_idempotent
from app.services.manual_review_api_service import ManualReviewApiService
from app.workers.generation_worker import run_generation_task

router = APIRouter()


@router.get("", response_model=ApiResponse)
def list_manual_reviews(status: str | None = Query(None), db: Session = Depends(get_db)) -> ApiResponse:
    return ok(ManualReviewApiService(db).list(status))


@router.get("/{review_id}", response_model=ApiResponse)
def get_manual_review(review_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(ManualReviewApiService(db).detail(review_id))


@router.post("/{review_id}/decision", response_model=ApiResponse)
def decide_manual_review(review_id: str, background_tasks: BackgroundTasks, payload: ManualReviewDecisionRequest, idempotency_key: str = Depends(require_idempotency_key), db: Session = Depends(get_db)) -> ApiResponse:
    service = ManualReviewApiService(db)
    result, replayed = execute_idempotent(db, scope=f"manual_review.decision:{review_id}", request_key=idempotency_key, operation=lambda: service.decide(review_id, payload))
    if not replayed:
        background_tasks.add_task(run_generation_task, result["task_id"])
    return ok(result)
