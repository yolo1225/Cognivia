from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import require_idempotency_key
from app.core.db import get_db
from app.schemas.api_requests import TutoringMessageRequest, TutoringSessionCreateRequest
from app.schemas.common import ApiResponse, ok
from app.services.idempotency_service import execute_idempotent
from app.services.tutoring_api_service import TutoringApiService
from app.workers.generation_worker import run_generation_task

router = APIRouter()


@router.post("/sessions", response_model=ApiResponse)
def start_tutoring_session(payload: TutoringSessionCreateRequest, idempotency_key: str = Depends(require_idempotency_key), db: Session = Depends(get_db)) -> ApiResponse:
    service = TutoringApiService(db)
    result, _ = execute_idempotent(db, scope="tutoring.session.create", request_key=idempotency_key, operation=lambda: service.create_session(payload))
    return ok(result)


@router.post("/sessions/{session_id}/messages", response_model=ApiResponse)
def post_tutoring_message(session_id: str, background_tasks: BackgroundTasks, payload: TutoringMessageRequest, idempotency_key: str = Depends(require_idempotency_key), db: Session = Depends(get_db)) -> ApiResponse:
    service = TutoringApiService(db)
    result, replayed = execute_idempotent(db, scope=f"tutoring.message:{session_id}", request_key=idempotency_key, operation=lambda: service.add_message(session_id, payload))
    if result.get("task_id") and not replayed:
        background_tasks.add_task(run_generation_task, result["task_id"])
    return ok(result)


@router.get("/sessions/{session_id}", response_model=ApiResponse)
def get_tutoring_session(session_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(TutoringApiService(db).session_detail(session_id))
