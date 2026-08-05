from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import require_idempotency_key
from app.core.db import get_db
from app.schemas.api_requests import GenerationTaskCreateRequest
from app.schemas.common import ApiResponse, ok
from app.services.generation_task_api_service import GenerationTaskApiService, stream_task_events
from app.services.idempotency_service import execute_idempotent
from app.workers.generation_worker import run_generation_task

router = APIRouter()


@router.post("", response_model=ApiResponse)
def create_generation_task(payload: GenerationTaskCreateRequest, background_tasks: BackgroundTasks, idempotency_key: str = Depends(require_idempotency_key), db: Session = Depends(get_db)) -> ApiResponse:
    service = GenerationTaskApiService(db)
    result, replayed = execute_idempotent(db, scope="generation_task.create", request_key=idempotency_key, operation=lambda: service.create(payload))
    if not replayed:
        background_tasks.add_task(run_generation_task, result["task_id"])
    return ok(result)


@router.get("/active", response_model=ApiResponse)
def get_active_generation_task(learner_id: str = "learner_001", db: Session = Depends(get_db)) -> ApiResponse:
    return ok(GenerationTaskApiService(db).active(learner_id))


@router.get("/{task_id}", response_model=ApiResponse)
def get_generation_task(task_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(GenerationTaskApiService(db).get(task_id))


@router.get("/{task_id}/agent-runs", response_model=ApiResponse)
def get_agent_runs(task_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(GenerationTaskApiService(db).runs(task_id))


@router.get("/{task_id}/events")
async def stream_generation_events(task_id: str) -> StreamingResponse:
    return StreamingResponse(stream_task_events(task_id), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
