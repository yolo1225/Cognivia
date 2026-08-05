from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import require_idempotency_key
from app.core.db import get_db
from app.schemas.api_requests import LearnerCreateRequest
from app.schemas.common import ApiResponse, ok
from app.services.idempotency_service import execute_idempotent
from app.services.learner_api_service import LearnerApiService

router = APIRouter()


@router.get("", response_model=ApiResponse)
def list_learners(db: Session = Depends(get_db)) -> ApiResponse:
    return ok(LearnerApiService(db).list())


@router.post("", response_model=ApiResponse)
def create_learner(
    payload: LearnerCreateRequest,
    idempotency_key: str = Depends(require_idempotency_key),
    db: Session = Depends(get_db),
) -> ApiResponse:
    service = LearnerApiService(db)
    result, _ = execute_idempotent(
        db,
        scope="learner.create",
        request_key=idempotency_key,
        operation=lambda: (service.create(payload), "learner", payload.learner_id),
    )
    return ok(result)


@router.get("/{learner_id}/profile", response_model=ApiResponse)
def get_learner_profile(learner_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(LearnerApiService(db).profile(learner_id))
