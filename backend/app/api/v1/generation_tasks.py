from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, get_db
from app.core.security import Principal, get_current_user, principal_learner, require_task
from app.models import (
    AgentRun,
    Feedback,
    GenerationTask,
    GraphCheckpoint,
    Learner,
    LearnerProfile,
    LearningResource,
)
from app.schemas.common import ApiResponse, ok
from app.services.feedback_service import create_feedback_task
from app.services.profile_service import latest_profile_for_learner, profile_source, public_id
from app.rag.readiness import CandidateRagNotReady, RAG_NOT_READY_CODE, require_candidate_rag
from app.workers.generation_worker import run_generation_task

router = APIRouter()
RESOURCE_TYPES = {"lecture", "practice_guide", "graded_quiz"}
TRIGGER_TYPES = {"initial_generation", "resource_feedback"}
EXECUTION_MODES = {"auto", "assisted"}
TERMINAL_TASK_STATUSES = {"completed", "failed", "revision_required", "no_change", "rejected"}
ACTIVE_TASK_STATUSES = {"pending", "retry_pending", "running"}
SENSITIVE_KEYS = {"content", "content_md", "draft_resources", "profile", "answers"}

STEP_LABELS = {
    "prepare_task": "任务准备",
    "interpret_feedback": "反馈识别",
    "analyze_profile": "画像分析",
    "retrieve_knowledge": "知识检索",
    "generate_resource": "资源生成",
    "review_resource": "双模型审核",
    "finalize_task": "确定性收尾",
}


def _get_or_create_learner(db: Session, learner_public_id: str) -> Learner:
    learner = db.scalar(select(Learner).where(Learner.public_id == learner_public_id))
    if learner:
        return learner
    raise HTTPException(status_code=404, detail="LEARNER_NOT_FOUND")


def _resource_summary(resource: LearningResource) -> dict[str, Any]:
    return {
        "resource_id": resource.public_id,
        "resource_type": resource.resource_type,
        "title": resource.title,
        "difficulty": resource.difficulty,
        "review_status": resource.review_status,
        "version": resource.version,
        "is_current": resource.is_current,
        "sources": [item.get("knowledge_id") for item in (resource.sources_json or [])],
        "knowledge_coverage": resource.knowledge_coverage_json or {},
    }


def _profile_summary(db: Session, task: GenerationTask) -> dict[str, Any]:
    profile = db.get(LearnerProfile, task.profile_id)
    if profile is None:
        return {
            "profile_id": None,
            "profile_version": None,
            "profile_source": None,
            "profile_changed_dimensions": [],
        }
    return {
        "profile_id": profile.public_id,
        "profile_version": profile.profile_version,
        "profile_source": profile_source(profile),
        "profile_changed_dimensions": profile.changed_dimensions_json or [],
    }


def _task_detail_summary(db: Session, task: GenerationTask) -> dict[str, Any]:
    learner = db.get(Learner, task.learner_id)
    resources = list(
        db.scalars(
            select(LearningResource)
            .where(LearningResource.generation_task_id == task.id)
            .order_by(LearningResource.id)
        )
    )
    return {
        "task_id": task.public_id,
        "thread_id": task.public_id,
        "status": task.status,
        "progress": task.progress,
        "trigger_type": task.trigger_type,
        "execution_mode": task.execution_mode,
        "learner_id": learner.public_id if learner else None,
        **_profile_summary(db, task),
        "revision_count": task.revision_count,
        "decision": task.decision,
        "package_coverage": task.package_coverage_json or {},
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "resources": [_resource_summary(item) for item in resources],
    }


@router.post("", response_model=ApiResponse)
def create_generation_task(
    background_tasks: BackgroundTasks,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    payload = payload or {}
    trigger_type = str(payload.get("trigger_type", "initial_generation"))
    execution_mode = str(payload.get("execution_mode", "auto"))
    if trigger_type not in TRIGGER_TYPES:
        raise HTTPException(status_code=422, detail="unsupported trigger_type")
    if execution_mode not in EXECUTION_MODES:
        raise HTTPException(status_code=422, detail="unsupported execution_mode")
    requested_types = list(payload.get("resource_types") or RESOURCE_TYPES)
    if not requested_types or any(item not in RESOURCE_TYPES for item in requested_types):
        raise HTTPException(status_code=422, detail="unsupported resource type")
    domain_code = str(payload.get("domain_code", "ai_app_dev"))
    try:
        require_candidate_rag(domain_code)
    except CandidateRagNotReady as exc:
        raise HTTPException(status_code=503, detail=f"{RAG_NOT_READY_CODE}:{exc}") from exc

    learner = _get_or_create_learner(
        db, principal_learner(principal, payload.get("learner_id"))
    )
    profile_id = payload.get("profile_id")
    if profile_id:
        profile = db.scalar(
            select(LearnerProfile).where(LearnerProfile.public_id == profile_id)
        )
        if profile is None:
            raise HTTPException(status_code=404, detail="Learner profile not found")
        if profile.learner_id != learner.id:
            raise HTTPException(status_code=404, detail="Learner profile not found")
        learner = db.get(Learner, profile.learner_id) or learner
    else:
        profile = latest_profile_for_learner(db, learner)
    if profile is None or not profile.diagnosis_completed:
        raise HTTPException(status_code=409, detail="DIAGNOSIS_REQUIRED")
    task = GenerationTask(
        public_id=public_id("task"),
        learner_id=learner.id,
        profile_id=profile.id,
        domain_code=domain_code,
        status="pending",
        resource_types_json=requested_types,
        revision_count=0,
        decision="pending",
        trigger_type=trigger_type,
        execution_mode=execution_mode,
        learning_goal=str(payload.get("learning_goal") or "个性化学习资源生成")[:512],
        progress=0,
    )
    db.add(task)
    db.commit()
    background_tasks.add_task(run_generation_task, task.public_id)
    return ok(
        {
            "task_id": task.public_id,
            "thread_id": task.public_id,
            "status": task.status,
            "trigger_type": task.trigger_type,
            "execution_mode": task.execution_mode,
            "resource_types": requested_types,
            "agent_graph": "unified_learning_graph_v3",
            **_profile_summary(db, task),
            "decision": task.decision,
            "agent_trace": [],
            "resources": [],
        }
    )


@router.post("/feedback/{feedback_id}/confirm", response_model=ApiResponse)
def confirm_feedback_generation(
    feedback_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    feedback = db.get(Feedback, feedback_id)
    if feedback is None:
        raise HTTPException(status_code=404, detail="FEEDBACK_NOT_FOUND")
    learner = db.get(Learner, feedback.learner_id)
    if learner is None:
        raise HTTPException(status_code=404, detail="LEARNER_NOT_FOUND")
    principal_learner(principal, learner.public_id)
    existing = db.scalar(select(GenerationTask).where(GenerationTask.source_feedback_id == feedback.id).order_by(GenerationTask.id.desc()))
    if existing is not None:
        return ok(_task_detail_summary(db, existing))
    profile = latest_profile_for_learner(db, learner)
    resource = db.get(LearningResource, feedback.resource_id)
    if profile is None or not profile.diagnosis_completed:
        raise HTTPException(status_code=409, detail="DIAGNOSIS_REQUIRED")
    if resource is None or feedback.recommended_action not in {"review", "challenge", "explain", "regenerate"}:
        raise HTTPException(status_code=409, detail="GENERATION_NOT_RECOMMENDED")
    source_task = db.get(GenerationTask, resource.generation_task_id)
    try:
        require_candidate_rag(source_task.domain_code if source_task else "ai_app_dev")
    except CandidateRagNotReady as exc:
        raise HTTPException(status_code=503, detail=f"{RAG_NOT_READY_CODE}:{exc}") from exc
    task = create_feedback_task(db, learner=learner, profile=profile, resource=resource, feedback=feedback, resource_types=[resource.resource_type])
    db.commit()
    background_tasks.add_task(run_generation_task, task.public_id)
    return ok(_task_detail_summary(db, task))


@router.get("/active", response_model=ApiResponse)
def get_active_generation_task(
    learner_id: str | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    learner_id = principal_learner(principal, learner_id)
    task = db.scalar(
        select(GenerationTask)
        .join(Learner, Learner.id == GenerationTask.learner_id)
        .where(Learner.public_id == learner_id)
        .where(GenerationTask.status.in_(ACTIVE_TASK_STATUSES))
        .order_by(GenerationTask.created_at.desc(), GenerationTask.id.desc())
    )
    return ok(_task_detail_summary(db, task) if task is not None else None)


@router.get("", response_model=ApiResponse)
def list_generation_tasks(
    learner_id: str | None = Query(None),
    domain_code: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    if principal.role != "admin":
        learner_id = principal.learner_id
    statement = select(GenerationTask).order_by(
        GenerationTask.created_at.desc(), GenerationTask.id.desc()
    )
    if learner_id:
        statement = statement.join(Learner, Learner.id == GenerationTask.learner_id).where(
            Learner.public_id == learner_id
        )
    if domain_code:
        statement = statement.where(GenerationTask.domain_code == domain_code)
    if status:
        statement = statement.where(GenerationTask.status == status)
    tasks = list(db.scalars(statement.limit(limit)))
    return ok([_task_detail_summary(db, task) for task in tasks])


@router.get("/{task_id}", response_model=ApiResponse)
def get_generation_task(task_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_user)) -> ApiResponse:
    task = require_task(db, principal, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Generation task not found")
    return ok(_task_detail_summary(db, task))


@router.post("/{task_id}/retry", response_model=ApiResponse)
def retry_generation_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    """Resume a recoverable failed node from its existing LangGraph checkpoint."""

    task = require_task(db, principal, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Generation task not found")
    if task.status in {"retry_pending", "running"}:
        return ok(_task_detail_summary(db, task))
    if task.status != "failed":
        raise HTTPException(status_code=409, detail="TASK_NOT_RETRYABLE")
    try:
        require_candidate_rag(task.domain_code)
    except CandidateRagNotReady as exc:
        raise HTTPException(status_code=503, detail=f"{RAG_NOT_READY_CODE}:{exc}") from exc
    checkpoint = db.scalar(
        select(GraphCheckpoint).where(GraphCheckpoint.task_id == task.public_id)
    )
    latest_failure = db.scalar(
        select(AgentRun)
        .where(AgentRun.generation_task_id == task.id)
        .where(AgentRun.status == "failed")
        .order_by(AgentRun.id.desc())
    )
    recoverable = bool(
        latest_failure
        and (latest_failure.output_summary_json or {}).get("recoverable")
    )
    if (
        checkpoint is None
        or not (checkpoint.state_json or {}).get("native_checkpoint")
        or not recoverable
    ):
        raise HTTPException(status_code=409, detail="TASK_CHECKPOINT_NOT_RECOVERABLE")
    task.status = "retry_pending"
    task.decision = "pending"
    db.commit()
    background_tasks.add_task(run_generation_task, task.public_id)
    return ok(_task_detail_summary(db, task))


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items() if key not in SENSITIVE_KEYS}
    if isinstance(value, list):
        return [_safe(item) for item in value[:30]]
    return value


@router.get("/{task_id}/agent-runs", response_model=ApiResponse)
def get_agent_runs(task_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_user)) -> ApiResponse:
    task = require_task(db, principal, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Generation task not found")
    runs = list(
        db.scalars(
            select(AgentRun)
            .where(AgentRun.generation_task_id == task.id)
            .order_by(AgentRun.id)
        )
    )
    return ok(
        [
            {
                "run_id": run.id,
                "task_id": task.public_id,
                "agent_name": run.agent_name,
                "status": run.status,
                "input_summary": _safe(run.input_summary_json or {}),
                "output_summary": _safe(run.output_summary_json or {}),
                "model_name": run.model_name,
                "prompt_version": run.prompt_version,
                "tokens_input": run.tokens_input,
                "tokens_output": run.tokens_output,
                "duration_ms": run.duration_ms,
                "error": run.error_message,
            }
            for run in runs
        ]
    )


def _json_event(name: str, payload: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _agent_payload(task: GenerationTask, run: AgentRun) -> dict[str, Any]:
    output = _safe(run.output_summary_json or {})
    step = str((run.input_summary_json or {}).get("step") or output.get("step") or run.agent_name)
    return {
        "run_id": run.id,
        "task_id": task.public_id,
        "step": step,
        "status": run.status,
        "agent_name": run.agent_name,
        "generation_round": (run.input_summary_json or {}).get("generation_round"),
        "event_message": f"{STEP_LABELS.get(step, step)}{'完成' if run.status == 'completed' else '运行中' if run.status == 'running' else '失败'}",
        "payload": output,
        "timestamp": run.updated_at.isoformat() if run.updated_at else None,
    }


def _serialize_agent_status_event(
    task: GenerationTask, run: AgentRun, step: str
) -> dict[str, Any]:
    """Backward-compatible serializer for existing API/unit consumers."""

    payload = _agent_payload(task, run)
    payload["step"] = step
    generation_round = (run.input_summary_json or {}).get("generation_round") or (
        run.output_summary_json or {}
    ).get("generation_round")
    payload["generation_round"] = generation_round
    payload["is_revision_round"] = bool(generation_round and int(generation_round) > 1)
    if generation_round:
        # Keep the legacy marker in this compatibility-only helper. New SSE
        # consumers use the normal Chinese event message from _agent_payload.
        payload["event_message"] = (
            f"第 {generation_round} 轮（Ек {generation_round} Тж）："
            f"{STEP_LABELS.get(step, step)}完成"
        )
    return payload


def _semantic_events(task: GenerationTask, payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    if payload["status"] != "completed":
        return []
    step, output = payload["step"], payload["payload"]
    base = {"task_id": task.public_id, **output}
    events: list[tuple[str, dict[str, Any]]] = []
    if step == "prepare_task":
        events.append(("trigger_routed", base))
    elif step == "interpret_feedback":
        events.append(("feedback_classified", base))
    elif step == "analyze_profile":
        events.append(("profile_update_decided", base))
        events.append(("profile_updated" if output.get("profile_update_required") else "profile_unchanged", base))
        if output.get("profile_update_required"):
            events.extend(
                [("path_refresh_started", base), ("path_refresh_completed", base)]
            )
    elif step == "review_resource" and output.get("arbitration_required"):
        events.extend([("review_disagreement", base), ("review_retrieval_started", base)])
    return events


async def _task_events(task_id: str) -> AsyncIterator[str]:
    emitted: set[tuple[str, int | str, str]] = set()
    while True:
        with SessionLocal() as db:
            task = db.scalar(select(GenerationTask).where(GenerationTask.public_id == task_id))
            if task is None:
                yield _json_event("task_failed", {"task_id": task_id, "error": "not_found"})
                return
            runs = list(
                db.scalars(
                    select(AgentRun)
                    .where(AgentRun.generation_task_id == task.id)
                    .order_by(AgentRun.id)
                )
            )
            for run in runs:
                key = ("agent_status", run.id, run.status)
                if key in emitted:
                    continue
                emitted.add(key)
                payload = _agent_payload(task, run)
                yield _json_event("agent_status", payload)
                for name, semantic_payload in _semantic_events(task, payload):
                    semantic_key = (name, run.id, run.status)
                    if semantic_key not in emitted:
                        emitted.add(semantic_key)
                        yield _json_event(name, semantic_payload)

            if task.status in TERMINAL_TASK_STATUSES:
                if task.status == "completed":
                    for resource in db.scalars(
                        select(LearningResource).where(
                            LearningResource.generation_task_id == task.id
                        )
                    ):
                        yield _json_event(
                            "resource_created",
                            {"task_id": task.public_id, **_resource_summary(resource)},
                        )
                    name = "task_completed"
                else:
                    name = "task_failed"
                yield _json_event(
                    name,
                    {
                        "task_id": task.public_id,
                        "step": "task",
                        "status": task.status,
                        "decision": task.decision,
                        "progress": task.progress,
                    },
                )
                return
        await asyncio.sleep(0.35)


@router.get("/{task_id}/events")
async def stream_generation_events(task_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_user)) -> StreamingResponse:
    require_task(db, principal, task_id)
    return StreamingResponse(
        _task_events(task_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
