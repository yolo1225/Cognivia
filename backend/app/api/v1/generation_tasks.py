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
from app.core.security import Principal, get_current_user, principal_learner, require_admin, require_task
from app.models import (
    AgentMessageRecord,
    AgentRun,
    Feedback,
    GenerationTask,
    GraphCheckpoint,
    Learner,
    LearnerProfile,
    LearningResource,
    ReviewReport,
)
from app.schemas.common import ApiResponse, ok
from app.services.feedback_service import (
    FeedbackSourceCompatibilityError,
    create_feedback_task,
    require_v6_feedback_source,
)
from app.services.learning_package_service import package_member_rows
from app.services.domain_runtime_service import DomainRuntimeError, require_ready_domain
from app.services.evaluation_case_service import contains_evaluation_marker
from app.services.profile_service import (
    is_initial_profile_ready,
    latest_profile_for_learner,
    profile_source,
    public_id,
)
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
    package_rows = package_member_rows(db, task) if task.status == "completed" else []
    if package_rows:
        resources = []
        for member, resource in package_rows:
            payload = _resource_summary(resource)
            payload["membership_type"] = member.membership_type
            payload["freshness_status"] = member.freshness_status
            resources.append(payload)
    else:
        resources = [
            _resource_summary(item)
            for item in db.scalars(
                select(LearningResource)
                .where(LearningResource.generation_task_id == task.id)
                .order_by(LearningResource.id)
            )
        ]
    source_feedback = None
    if task.source_feedback_id is not None:
        feedback = db.get(Feedback, task.source_feedback_id)
        if feedback is not None:
            source_feedback = {
                "feedback_type": feedback.feedback_type,
                "triggered_action": feedback.triggered_action,
                "recommended_action": feedback.recommended_action,
                "comment": feedback.comment,
                "rating": feedback.rating,
            }
    source_resource = None
    if task.source_resource_id is not None:
        resource = db.get(LearningResource, task.source_resource_id)
        if resource is not None:
            source_resource = {
                "resource_id": resource.public_id,
                "title": resource.title,
                "resource_type": resource.resource_type,
                "version": resource.version,
            }
    latest_failed_run = None
    if task.status == "failed":
        latest_failed_run = db.scalar(
            select(AgentRun)
            .where(AgentRun.generation_task_id == task.id)
            .where(AgentRun.status == "failed")
            .order_by(AgentRun.id.desc())
        )
    failure_output = (
        latest_failed_run.output_summary_json or {} if latest_failed_run is not None else {}
    )
    return {
        "task_id": task.public_id,
        "thread_id": task.public_id,
        "status": task.status,
        "domain_code": task.domain_code,
        "progress": task.progress,
        "trigger_type": task.trigger_type,
        "event_type": task.event_type,
        "source_task_id": (
            db.get(GenerationTask, task.source_task_id).public_id if task.source_task_id else None
        ),
        "is_current_package": task.is_current_package,
        "execution_mode": task.execution_mode,
        "learner_id": learner.public_id if learner else None,
        **_profile_summary(db, task),
        "revision_count": task.revision_count,
        "decision": task.decision,
        "failure_reason": task.failure_reason or None,
        "failure_details": {
            "failed_step": failure_output.get("failed_step"),
            "field_paths": list(failure_output.get("field_paths") or [])[:20],
            "recoverable": bool(failure_output.get("recoverable")),
        }
        if task.status == "failed"
        else None,
        "package_coverage": task.package_coverage_json or {},
        "package_quality": task.package_quality_json or None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "resources": resources,
        "inherited_resource_count": sum(
            1 for item in resources if item.get("membership_type") == "inherited"
        ),
        "source_feedback": source_feedback,
        "source_resource": source_resource,
    }


@router.post("", response_model=ApiResponse)
def create_generation_task(
    background_tasks: BackgroundTasks,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    payload = payload or {}
    learning_goal = str(payload.get("learning_goal") or "个性化学习资源生成")[:512]
    if contains_evaluation_marker(learning_goal):
        raise HTTPException(status_code=422, detail="EVALUATION_MARKER_RESERVED")
    trigger_type = str(payload.get("trigger_type", "initial_generation"))
    execution_mode = str(payload.get("execution_mode", "auto"))
    if trigger_type not in TRIGGER_TYPES:
        raise HTTPException(status_code=422, detail="unsupported trigger_type")
    if execution_mode not in EXECUTION_MODES:
        raise HTTPException(status_code=422, detail="unsupported execution_mode")
    requested_types = list(payload.get("resource_types") or RESOURCE_TYPES)
    if not requested_types or any(item not in RESOURCE_TYPES for item in requested_types):
        raise HTTPException(status_code=422, detail="unsupported resource type")
    domain_code = str(payload.get("domain_code") or "").strip()
    if not domain_code:
        raise HTTPException(status_code=422, detail="domain_code is required")
    try:
        domain_runtime = require_ready_domain(db, domain_code)
    except DomainRuntimeError as exc:
        raise HTTPException(status_code=409, detail=f"DOMAIN_RUNTIME_NOT_READY:{exc}") from exc
    if not domain_runtime.generation_ready:
        raise HTTPException(
            status_code=503,
            detail=f"DOMAIN_GENERATION_NOT_READY:{','.join(domain_runtime.reasons)}",
        )

    learner = _get_or_create_learner(db, principal_learner(principal, payload.get("learner_id")))
    profile_id = payload.get("profile_id")
    if profile_id:
        profile = db.scalar(select(LearnerProfile).where(LearnerProfile.public_id == profile_id))
        if profile is None:
            raise HTTPException(status_code=404, detail="Learner profile not found")
        if profile.learner_id != learner.id:
            raise HTTPException(status_code=404, detail="Learner profile not found")
        learner = db.get(Learner, profile.learner_id) or learner
    else:
        profile = latest_profile_for_learner(db, learner, domain_code)
    if not is_initial_profile_ready(profile):
        raise HTTPException(status_code=409, detail="PROFILE_NOT_READY")
    if profile.domain_code != domain_code or learner.target_domain != domain_code:
        raise HTTPException(status_code=409, detail="DOMAIN_CONTEXT_MISMATCH")
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
        learning_goal=learning_goal,
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
    existing = db.scalar(
        select(GenerationTask)
        .where(GenerationTask.source_feedback_id == feedback.id)
        .order_by(GenerationTask.id.desc())
    )
    if existing is not None:
        return ok(_task_detail_summary(db, existing))
    resource = db.get(LearningResource, feedback.resource_id)
    if resource is None or feedback.recommended_action not in {
        "review",
        "challenge",
        "explain",
        "regenerate",
    }:
        raise HTTPException(status_code=409, detail="GENERATION_NOT_RECOMMENDED")
    try:
        source_task = require_v6_feedback_source(
            db,
            learner=learner,
            resource=resource,
        )
    except FeedbackSourceCompatibilityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    profile = latest_profile_for_learner(db, learner, source_task.domain_code)
    if not is_initial_profile_ready(profile):
        raise HTTPException(status_code=409, detail="PROFILE_NOT_READY")
    try:
        require_candidate_rag(source_task.domain_code)
    except CandidateRagNotReady as exc:
        raise HTTPException(status_code=503, detail=f"{RAG_NOT_READY_CODE}:{exc}") from exc
    task = create_feedback_task(
        db,
        learner=learner,
        profile=profile,
        resource=resource,
        feedback=feedback,
        resource_types=[resource.resource_type],
    )
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
def get_generation_task(
    task_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_user)
) -> ApiResponse:
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
    checkpoint = db.scalar(select(GraphCheckpoint).where(GraphCheckpoint.task_id == task.public_id))
    latest_failure = db.scalar(
        select(AgentRun)
        .where(AgentRun.generation_task_id == task.id)
        .where(AgentRun.status == "failed")
        .order_by(AgentRun.id.desc())
    )
    recoverable = bool(
        latest_failure and (latest_failure.output_summary_json or {}).get("recoverable")
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
def get_agent_runs(
    task_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_user)
) -> ApiResponse:
    task = require_task(db, principal, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Generation task not found")
    runs = list(
        db.scalars(
            select(AgentRun).where(AgentRun.generation_task_id == task.id).order_by(AgentRun.id)
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
                "prompt_hash": run.prompt_hash,
                "contract_version": run.contract_version,
                "tokens_input": run.tokens_input,
                "tokens_output": run.tokens_output,
                "duration_ms": run.duration_ms,
                "error": run.error_message,
            }
            for run in runs
        ]
    )


@router.get("/{task_id}/internal-trace", response_model=ApiResponse, include_in_schema=False)
def get_internal_trace(
    task_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_admin),
) -> ApiResponse:
    task = require_task(db, principal, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Generation task not found")
    runs = list(
        db.scalars(
            select(AgentRun).where(AgentRun.generation_task_id == task.id).order_by(AgentRun.id)
        )
    )
    messages = list(
        db.scalars(
            select(AgentMessageRecord)
            .where(AgentMessageRecord.task_id == task.public_id)
            .order_by(AgentMessageRecord.id)
        )
    )
    resources = list(
        db.scalars(
            select(LearningResource).where(LearningResource.generation_task_id == task.id)
        )
    )
    resource_ids = {item.id: item.public_id for item in resources}
    reports = list(
        db.scalars(
            select(ReviewReport).where(ReviewReport.task_id == task.id).order_by(ReviewReport.id)
        )
    )
    return ok(
        {
            "task_id": task.public_id,
            "thread_id": task.public_id,
            "decision": task.decision,
            "revision_count": task.revision_count,
            "runs": [
                {
                    "run_id": run.id,
                    "agent_name": run.agent_name,
                    "status": run.status,
                    "step": (run.input_summary_json or {}).get("step"),
                    "contract_version": run.contract_version,
                    "prompt_version": run.prompt_version,
                    "prompt_hash": run.prompt_hash,
                    "model_name": run.model_name,
                    "provider_mode": (run.output_summary_json or {}).get("provider_mode"),
                    "duration_ms": run.duration_ms,
                }
                for run in runs
            ],
            "messages": [
                {
                    "message_id": message.id,
                    "sender": message.sender,
                    "receiver": message.receiver,
                    "message_type": message.message_type,
                    "payload_summary": _safe(message.payload_summary_json or {}),
                    "timestamp": message.created_at.isoformat() if message.created_at else None,
                }
                for message in messages
            ],
            "reviews": [
                {
                    "review_report_id": report.id,
                    "resource_id": resource_ids.get(report.resource_id),
                    "passed": report.passed,
                    "decision": report.decision,
                    "primary": _safe(report.primary_review_json or {}),
                    "secondary": _safe(report.secondary_review_json or {}),
                    "arbitration": _safe(report.arbitration_json or {}),
                    "review_rule_version": report.review_rule_version,
                    "quality_rule_version": report.quality_rule_version,
                }
                for report in reports
            ],
        }
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


def _serialize_agent_status_event(task: GenerationTask, run: AgentRun, step: str) -> dict[str, Any]:
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
            f"第 {generation_round} 轮（修订轮次 {generation_round}）："
            f"{STEP_LABELS.get(step, step)}完成"
        )
    return payload


def _semantic_events(
    task: GenerationTask, payload: dict[str, Any]
) -> list[tuple[str, dict[str, Any]]]:
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
        events.append(
            (
                "profile_updated" if output.get("profile_update_required") else "profile_unchanged",
                base,
            )
        )
        path_refresh = output.get("path_refresh")
        if (
            output.get("profile_update_required")
            and isinstance(path_refresh, dict)
            and path_refresh.get("new_path_id")
        ):
            events.append(
                (
                    "path_refresh_completed",
                    {
                        **base,
                        "old_path_id": path_refresh.get("old_path_id"),
                        "new_path_id": path_refresh["new_path_id"],
                    },
                )
            )
    elif step == "review_resource" and any(
        isinstance(item, dict) and item.get("required") is True
        for item in (output.get("arbitration") or [])
    ):
        events.extend([("review_disagreement", base), ("review_retrieval_started", base)])
    return events


def _review_trace_events(
    db: Session, task: GenerationTask, payload: dict[str, Any]
) -> list[tuple[str, dict[str, Any]]]:
    if payload.get("step") != "review_resource" or payload.get("status") != "completed":
        return []
    resources = {
        item.id: item.public_id
        for item in db.scalars(
            select(LearningResource).where(LearningResource.generation_task_id == task.id)
        )
    }
    events: list[tuple[str, dict[str, Any]]] = []
    reports = list(
        db.scalars(
            select(ReviewReport).where(ReviewReport.task_id == task.id).order_by(ReviewReport.id)
        )
    )
    for report in reports:
        arbitration = report.arbitration_json or {}
        if arbitration.get("required") is not True:
            continue
        base = {
            "task_id": task.public_id,
            "resource_id": resources.get(report.resource_id),
            "review_report_id": report.id,
            "revision_count": task.revision_count,
        }
        events.extend(
            [
                ("review_disagreement", base),
                ("arbitration_started", base),
                ("review_retrieval_started", base),
                (
                    "review_retrieval_completed",
                    {**base, "retrieval_performed": arbitration.get("retrieval_performed", False)},
                ),
                (
                    "arbitration_completed",
                    {
                        **base,
                        "disagreement_remains": arbitration.get(
                            "disagreement_remains", False
                        ),
                    },
                ),
            ]
        )
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
                    if payload.get("step") == "review_resource" and name in {
                        "review_disagreement",
                        "review_retrieval_started",
                    }:
                        continue
                    semantic_key = (name, run.id, run.status)
                    if semantic_key not in emitted:
                        emitted.add(semantic_key)
                        yield _json_event(name, semantic_payload)
                for name, semantic_payload in _review_trace_events(db, task, payload):
                    semantic_key = (name, run.id, str(semantic_payload.get("review_report_id")))
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
async def stream_generation_events(
    task_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_user)
) -> StreamingResponse:
    require_task(db, principal, task_id)
    return StreamingResponse(
        _task_events(task_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
