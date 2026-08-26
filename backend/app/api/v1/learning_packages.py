from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import Principal, get_current_user, principal_learner, require_task
from app.models import GenerationTask, Learner
from app.rag.readiness import CandidateRagNotReady, RAG_NOT_READY_CODE, require_candidate_rag
from app.schemas.common import ApiResponse, ok
from app.services.learning_package_service import (
    current_package,
    dismiss_impact,
    latest_impact,
    package_member_rows,
    serialize_package,
)
from app.services.learning_package_export_service import export_learning_package
from app.services.profile_service import public_id
from app.workers.generation_worker import run_generation_task


router = APIRouter()


@router.get("/current", response_model=ApiResponse)
def get_current_learning_package(
    learner_id: str | None = Query(None),
    domain_code: str = Query(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    learner_public_id = principal_learner(principal, learner_id)
    learner = db.scalar(select(Learner).where(Learner.public_id == learner_public_id))
    if learner is None:
        raise HTTPException(status_code=404, detail="LEARNER_NOT_FOUND")
    task = current_package(db, learner_id=learner.id, domain_code=domain_code)
    return ok(serialize_package(db, task) if task is not None else None)


@router.get("/{task_id}", response_model=ApiResponse)
def get_learning_package(
    task_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    task = require_task(db, principal, task_id)
    return ok(serialize_package(db, task, include_resolved_impact=True))


@router.post("/{task_id}/export", response_model=ApiResponse)
def create_learning_package_export(
    task_id: str,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    task = require_task(db, principal, task_id)
    try:
        return ok(
            export_learning_package(
                db,
                task,
                str((payload or {}).get("format", "markdown")),
            )
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = (
            409
            if detail.startswith("learning_package_")
            else 422
        )
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.post("/{task_id}/knowledge-impact/dismiss", response_model=ApiResponse)
def dismiss_knowledge_impact(
    task_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    task = require_task(db, principal, task_id)
    impact = latest_impact(db, task)
    if impact is None or impact.status not in {"pending", "dismissed"}:
        raise HTTPException(status_code=409, detail="NO_PENDING_KNOWLEDGE_IMPACT")
    dismiss_impact(db, impact)
    db.commit()
    return ok(serialize_package(db, task))


@router.post("/{task_id}/knowledge-refresh", response_model=ApiResponse)
def refresh_affected_resources(
    task_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    source_task = require_task(db, principal, task_id)
    if not source_task.is_current_package:
        raise HTTPException(status_code=409, detail="PACKAGE_IS_NOT_CURRENT")
    if (source_task.package_quality_json or {}).get(
        "quality_rule_version"
    ) != "quality-v6-20260818":
        raise HTTPException(
            status_code=409,
            detail="V6_FULL_REGENERATION_REQUIRED",
        )
    impact = latest_impact(db, source_task)
    if impact is None or impact.status not in {"pending", "dismissed"}:
        raise HTTPException(status_code=409, detail="NO_PENDING_KNOWLEDGE_IMPACT")
    try:
        require_candidate_rag(source_task.domain_code)
    except CandidateRagNotReady as exc:
        raise HTTPException(status_code=503, detail=f"{RAG_NOT_READY_CODE}:{exc}") from exc
    existing = db.scalar(
        select(GenerationTask)
        .where(
            GenerationTask.source_task_id == source_task.id,
            GenerationTask.event_type == "knowledge_refresh",
            GenerationTask.status.in_(["pending", "retry_pending", "running"]),
        )
        .order_by(GenerationTask.id.desc())
    )
    if existing is not None:
        return ok({"task_id": existing.public_id, "status": existing.status})

    affected_ids = set(impact.affected_resource_ids_json or [])
    affected_types = sorted(
        {
            resource.resource_type
            for _member, resource in package_member_rows(db, source_task)
            if resource.public_id in affected_ids
        }
    )
    if not affected_types:
        raise HTTPException(status_code=409, detail="AFFECTED_RESOURCES_NOT_FOUND")
    task = GenerationTask(
        public_id=public_id("task"),
        learner_id=source_task.learner_id,
        profile_id=source_task.profile_id,
        learning_path_id=source_task.learning_path_id,
        path_node_id=source_task.path_node_id,
        domain_code=source_task.domain_code,
        status="pending",
        resource_types_json=affected_types,
        resource_knowledge_targets_json={
            resource_type: list(
                (source_task.resource_knowledge_targets_json or {}).get(resource_type)
                or (source_task.package_coverage_json or {})
                .get("resource_knowledge_targets", {})
                .get(resource_type, [])
            )
            for resource_type in affected_types
        },
        revision_count=0,
        decision="pending",
        trigger_type="initial_generation",
        event_type="knowledge_refresh",
        execution_mode="auto",
        learning_goal=f"知识更新后局部刷新 {len(affected_types)} 类资源",
        source_task_id=source_task.id,
        progress=0,
    )
    db.add(task)
    db.flush()
    impact.status = "refreshing"
    impact.resolved_by_task_id = task.id
    db.commit()
    background_tasks.add_task(run_generation_task, task.public_id)
    return ok(
        {
            "task_id": task.public_id,
            "thread_id": task.public_id,
            "status": task.status,
            "event_type": task.event_type,
            "source_task_id": source_task.public_id,
            "resource_types": affected_types,
        }
    )
