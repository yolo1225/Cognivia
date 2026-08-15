from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import Principal, get_current_user, principal_learner, require_resource
from app.models import GenerationTask, Learner, LearningResource, ReviewReport
from app.schemas.common import ApiResponse, ok
from app.services.demo_flow_service import serialize_resource
from app.services.feedback_service import record_quick_feedback, serialize_feedback_decision
from app.services.learner_service import get_or_create_demo_learner
from app.services.profile_service import default_profile_for_learner
from app.rag.readiness import CandidateRagNotReady, RAG_NOT_READY_CODE, require_candidate_rag
from app.services.resource_export_service import export_resource, resolve_export_path
from app.workers.generation_worker import run_generation_task

router = APIRouter()


@router.get("", response_model=ApiResponse)
def list_resources(
    include_unpublished: bool = Query(False, description="Administrator view"),
    task_id: str | None = Query(None),
    learner_id: str | None = Query(None),
    domain_code: str | None = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    if include_unpublished and principal.role != "admin":
        raise HTTPException(403, "需要管理员权限")
    if principal.role != "admin":
        learner_id = principal.learner_id
    statement = (
        select(LearningResource, GenerationTask)
        .join(GenerationTask, GenerationTask.id == LearningResource.generation_task_id)
        .order_by(GenerationTask.created_at.desc(), LearningResource.id.asc())
        .limit(100)
    )
    if not include_unpublished:
        statement = statement.where(
            LearningResource.is_current.is_(True),
            LearningResource.review_status == "passed",
        )
    if task_id:
        statement = statement.where(GenerationTask.public_id == task_id)
    if learner_id:
        statement = statement.join(Learner, Learner.id == GenerationTask.learner_id).where(
            Learner.public_id == learner_id
        )
    if domain_code:
        statement = statement.where(GenerationTask.domain_code == domain_code)
    rows = list(db.execute(statement))
    resource_ids = [resource.id for resource, _ in rows]
    reports = list(
        db.scalars(
            select(ReviewReport)
            .where(ReviewReport.resource_id.in_(resource_ids))
            .order_by(ReviewReport.id.desc())
        )
    ) if resource_ids else []
    report_by_resource = {}
    for report in reports:
        report_by_resource.setdefault(report.resource_id, report)
    data = []
    for resource, task in rows:
        item = serialize_resource(resource, task)
        item["quality_metrics"] = _quality_metrics(report_by_resource.get(resource.id))
        item["package_quality"] = task.package_quality_json or None
        item["package_status"] = task.status
        item["failure_reason"] = task.failure_reason or None
        data.append(item)
    return ok(data)


def _quality_metrics(report: ReviewReport | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "verifiable_claim_count": report.verifiable_claim_count,
        "hallucinated_claim_count": report.hallucinated_claim_count,
        "hallucination_rate": report.hallucination_rate,
        "difficulty_match_score": report.difficulty_match_score,
        "covered_core_knowledge_count": report.covered_core_knowledge_count,
        "target_core_knowledge_count": report.target_core_knowledge_count,
        "core_knowledge_coverage": report.core_knowledge_coverage,
        "passed": report.quality_passed,
        "revision_count": report.revision_count,
    }


@router.post("/{resource_id}/feedback", response_model=ApiResponse)
def submit_resource_feedback(
    resource_id: str,
    background_tasks: BackgroundTasks,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    payload = payload or {}
    allowed_types = {
        "too_hard", "too_easy", "confusing", "incorrect", "has_error", "helpful"
    }
    feedback_type = str(payload.get("feedback_type", "confusing"))
    if feedback_type not in allowed_types:
        raise HTTPException(status_code=422, detail="unsupported quick feedback type")
    resource = require_resource(db, principal, resource_id)
    requested_learner = payload.get("learner_id")
    if principal.role == "admin" and not requested_learner:
        task_owner = db.get(GenerationTask, resource.generation_task_id)
        learner = db.get(Learner, task_owner.learner_id)
    else:
        learner = get_or_create_demo_learner(
            db, principal_learner(principal, requested_learner)
        )
    if resource is None:
        raise HTTPException(status_code=404, detail=f"Resource not found: {resource_id}")
    if feedback_type in {"incorrect", "has_error"}:
        source_task = db.get(GenerationTask, resource.generation_task_id)
        try:
            require_candidate_rag(source_task.domain_code if source_task else "ai_app_dev")
        except CandidateRagNotReady as exc:
            raise HTTPException(status_code=503, detail=f"{RAG_NOT_READY_CODE}:{exc}") from exc
    profile = default_profile_for_learner(db, learner)
    feedback, task = record_quick_feedback(
        db,
        learner=learner,
        profile=profile,
        resource=resource,
        feedback_type=feedback_type,
        rating=payload.get("rating"),
        comment=str(payload.get("selected_text") or payload.get("comment") or ""),
    )
    db.commit()
    if task:
        background_tasks.add_task(run_generation_task, task.public_id)
    result = serialize_feedback_decision(feedback, task)
    result["resource_id"] = resource.public_id
    return ok(result)


@router.get("/{resource_id}/versions", response_model=ApiResponse)
def list_resource_versions(resource_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_user)) -> ApiResponse:
    resource = require_resource(db, principal, resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail=f"Resource not found: {resource_id}")
    series_id = resource.series_id or resource.public_id
    versions = list(
        db.scalars(
            select(LearningResource)
            .where(LearningResource.series_id == series_id)
            .order_by(LearningResource.version.desc())
        )
    )
    return ok(
        [
            {
                "resource_id": item.public_id,
                "series_id": series_id,
                "version": item.version,
                "is_current": item.is_current,
                "review_status": item.review_status,
                "adaptation_reason": item.adaptation_reason,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in versions
        ]
    )


@router.post("/{resource_id}/export", response_model=ApiResponse)
def create_resource_export(
    resource_id: str,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    resource = require_resource(db, principal, resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail=f"Resource not found: {resource_id}")
    if resource.review_status != "passed":
        raise HTTPException(status_code=409, detail="unapproved resource cannot be exported")
    try:
        export_payload = payload or {}
        return ok(
            export_resource(
                db,
                resource,
                str(export_payload.get("format", "markdown")),
                str(export_payload.get("audience", "learner")),
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/exports/{file_name}", include_in_schema=False)
def download_resource_export(file_name: str) -> FileResponse:
    try:
        path = resolve_export_path(file_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="export not found") from exc
    return FileResponse(path, filename=path.name)
