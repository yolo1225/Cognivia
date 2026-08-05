from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.dependencies import require_idempotency_key
from app.core.db import get_db
from app.core.errors import not_found
from app.schemas.api_requests import ResourceExportRequest, ResourceFeedbackRequest
from app.schemas.common import ApiResponse, ok
from app.services.idempotency_service import execute_idempotent
from app.services.resource_api_service import ResourceApiService
from app.services.resource_export_service import resolve_export_path
from app.workers.generation_worker import run_generation_task

router = APIRouter()


@router.get("", response_model=ApiResponse)
def list_resources(include_unpublished: bool = Query(False, description="Administrator view"), db: Session = Depends(get_db)) -> ApiResponse:
    return ok(ResourceApiService(db).list(include_unpublished))


@router.post("/{resource_id}/feedback", response_model=ApiResponse)
def submit_resource_feedback(resource_id: str, background_tasks: BackgroundTasks, payload: ResourceFeedbackRequest, idempotency_key: str = Depends(require_idempotency_key), db: Session = Depends(get_db)) -> ApiResponse:
    service = ResourceApiService(db)
    result, replayed = execute_idempotent(
        db,
        scope=f"resource.feedback:{resource_id}",
        request_key=idempotency_key,
        operation=lambda: service.submit_feedback(resource_id, payload),
    )
    task_id = result.get("task_id")
    if task_id and not replayed:
        background_tasks.add_task(run_generation_task, task_id)
    return ok(result)


@router.get("/{resource_id}/versions", response_model=ApiResponse)
def list_resource_versions(resource_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(ResourceApiService(db).versions(resource_id))


@router.post("/{resource_id}/export", response_model=ApiResponse)
def create_resource_export(resource_id: str, payload: ResourceExportRequest, idempotency_key: str = Depends(require_idempotency_key), db: Session = Depends(get_db)) -> ApiResponse:
    service = ResourceApiService(db)
    result, _ = execute_idempotent(db, scope=f"resource.export:{resource_id}", request_key=idempotency_key, operation=lambda: (service.export(resource_id, payload), "resource_export", resource_id))
    return ok(result)


@router.get("/exports/{file_name}", include_in_schema=False)
def download_resource_export(file_name: str) -> FileResponse:
    try:
        path = resolve_export_path(file_name)
    except FileNotFoundError as exc:
        raise not_found("RESOURCE_EXPORT_NOT_FOUND", "导出文件不存在。") from exc
    return FileResponse(path, filename=path.name)
