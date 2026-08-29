from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.core.db import get_db
from app.core.security import (
    Principal,
    get_current_user,
    principal_learner,
    require_resource,
    require_task,
)
from app.models import (
    GenerationTask,
    KnowledgeItem,
    Learner,
    LearningPackageResource,
    LearningResource,
    ReviewReport,
)
from app.schemas.common import ApiResponse, ok
from app.services.demo_flow_service import serialize_resource
from app.services.feedback_service import (
    FeedbackSourceCompatibilityError,
    record_quick_feedback,
    require_v6_feedback_source,
    serialize_feedback_decision,
)
from app.services.learner_service import get_or_create_demo_learner
from app.services.profile_service import default_profile_for_learner
from app.rag.readiness import CandidateRagNotReady, RAG_NOT_READY_CODE, require_candidate_rag
from app.services.resource_export_service import export_resource, resolve_export_path
from app.services.resource_quiz_attempt_service import complete as complete_quiz_attempt
from app.services.resource_quiz_attempt_service import current as current_quiz_attempt
from app.services.resource_quiz_attempt_service import current_or_create as create_quiz_attempt
from app.services.resource_quiz_attempt_service import save_answer as save_quiz_answer
from app.workers.generation_worker import run_generation_task
from app.services.learning_package_service import current_package, ensure_package_members

router = APIRouter()


def _quiz_context(
    db: Session, principal: Principal, resource_id: str, learner_id: str | None
) -> tuple[Learner, LearningResource]:
    resource = require_resource(db, principal, resource_id)
    learner_public_id = principal_learner(principal, learner_id)
    learner = db.scalar(select(Learner).where(Learner.public_id == learner_public_id))
    if learner is None:
        raise HTTPException(404, "Learner not found")
    return learner, resource


def _quiz_error(exc: ValueError) -> HTTPException:
    code = str(exc).upper()
    return HTTPException(404 if code.endswith("NOT_FOUND") else 409, code)


@router.post("/{resource_id}/quiz-attempts", response_model=ApiResponse)
def start_resource_quiz_attempt(
    resource_id: str,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    learner, resource = _quiz_context(db, principal, resource_id, (payload or {}).get("learner_id"))
    try:
        return ok(create_quiz_attempt(db, learner=learner, resource=resource))
    except ValueError as exc:
        raise _quiz_error(exc) from exc


@router.get("/{resource_id}/quiz-attempts/current", response_model=ApiResponse)
def get_current_resource_quiz_attempt(
    resource_id: str,
    learner_id: str | None = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    learner, resource = _quiz_context(db, principal, resource_id, learner_id)
    try:
        return ok(current_quiz_attempt(db, learner=learner, resource=resource))
    except ValueError as exc:
        raise _quiz_error(exc) from exc


@router.put("/{resource_id}/quiz-attempts/{attempt_id}/answers/{question_id}", response_model=ApiResponse)
def put_resource_quiz_answer(
    resource_id: str,
    attempt_id: str,
    question_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    learner, resource = _quiz_context(db, principal, resource_id, payload.get("learner_id"))
    try:
        return ok(save_quiz_answer(
            db, learner=learner, resource=resource, attempt_id=attempt_id,
            question_id=question_id, answer=payload.get("answer"),
            self_checked=bool(payload.get("self_checked")),
        ))
    except ValueError as exc:
        raise _quiz_error(exc) from exc


@router.post("/{resource_id}/quiz-attempts/{attempt_id}/complete", response_model=ApiResponse)
def finish_resource_quiz_attempt(
    resource_id: str,
    attempt_id: str,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    learner, resource = _quiz_context(db, principal, resource_id, (payload or {}).get("learner_id"))
    try:
        return ok(complete_quiz_attempt(
            db, learner=learner, resource=resource, attempt_id=attempt_id
        ))
    except ValueError as exc:
        raise _quiz_error(exc) from exc


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
    if task_id:
        task = require_task(db, principal, task_id)
        task_learner = db.get(Learner, task.learner_id)
        if task_learner is None:
            raise HTTPException(404, "Task learner not found")
        # A task is always owned by one learner. Ignore stale client selection
        # so task-detail navigation cannot combine different owners and hide data.
        learner_id = task_learner.public_id
    elif principal.role != "admin":
        learner_id = principal.learner_id
    package_task = task if task_id else None
    if package_task is None and learner_id:
        selected_learner = db.scalar(select(Learner).where(Learner.public_id == learner_id))
        if selected_learner is not None:
            package_task = current_package(
                db,
                learner_id=selected_learner.id,
                domain_code=domain_code or selected_learner.target_domain,
            )
    creation_task = aliased(GenerationTask)
    if package_task is not None:
        ensure_package_members(db, package_task)
        statement = (
            select(LearningResource, creation_task)
            .join(
                LearningPackageResource,
                LearningPackageResource.resource_id == LearningResource.id,
            )
            .join(creation_task, creation_task.id == LearningResource.generation_task_id)
            .where(LearningPackageResource.package_task_id == package_task.id)
            .order_by(LearningPackageResource.sort_order, LearningPackageResource.id)
            .limit(100)
        )
    else:
        statement = (
            select(LearningResource, creation_task)
            .join(creation_task, creation_task.id == LearningResource.generation_task_id)
            .order_by(creation_task.created_at.desc(), LearningResource.id.asc())
            .limit(100)
        )
    if not include_unpublished:
        statement = statement.where(LearningResource.review_status == "passed")
    if learner_id:
        statement = statement.join(Learner, Learner.id == creation_task.learner_id).where(
            Learner.public_id == learner_id
        )
    if domain_code:
        statement = statement.where(creation_task.domain_code == domain_code)
    rows = list(db.execute(statement))
    knowledge_ids = {
        str(source.get("knowledge_id") or "").strip()
        for resource, _task in rows
        for source in (resource.sources_json or [])
        if str(source.get("knowledge_id") or "").strip()
    }
    knowledge_names = dict(
        db.execute(
            select(KnowledgeItem.public_id, KnowledgeItem.name).where(
                KnowledgeItem.public_id.in_(knowledge_ids)
            )
        ).all()
    ) if knowledge_ids else {}
    resource_ids = [resource.id for resource, _ in rows]
    reports = (
        list(
            db.scalars(
                select(ReviewReport)
                .where(ReviewReport.resource_id.in_(resource_ids))
                .order_by(ReviewReport.id.desc())
            )
        )
        if resource_ids
        else []
    )
    report_by_resource = {}
    for report in reports:
        report_by_resource.setdefault(report.resource_id, report)
    data = []
    for resource, task in rows:
        item = serialize_resource(resource, task, knowledge_names=knowledge_names)
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
        "quality_rule_version": report.quality_rule_version,
        "evaluated_claim_count": report.evaluated_claim_count,
        "contradicted_claim_count": report.contradicted_claim_count,
        "evidence_insufficient_claim_count": report.evidence_insufficient_claim_count,
        "unresolved_claim_count": report.unresolved_claim_count,
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
    allowed_types = {"too_hard", "too_easy", "confusing", "incorrect", "has_error", "helpful"}
    feedback_type = str(payload.get("feedback_type", "confusing"))
    if feedback_type not in allowed_types:
        raise HTTPException(status_code=422, detail="unsupported quick feedback type")
    resource = require_resource(db, principal, resource_id)
    requested_learner = payload.get("learner_id")
    if principal.role == "admin" and not requested_learner:
        task_owner = db.get(GenerationTask, resource.generation_task_id)
        learner = db.get(Learner, task_owner.learner_id)
    else:
        learner = get_or_create_demo_learner(db, principal_learner(principal, requested_learner))
    if resource is None:
        raise HTTPException(status_code=404, detail=f"Resource not found: {resource_id}")
    if feedback_type in {"incorrect", "has_error"}:
        try:
            source_task = require_v6_feedback_source(
                db,
                learner=learner,
                resource=resource,
            )
        except FeedbackSourceCompatibilityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            require_candidate_rag(source_task.domain_code)
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
def list_resource_versions(
    resource_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
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
