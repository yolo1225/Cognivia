"""V3 generation worker and observability bridge."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.checkpointer import MySQLLangGraphCheckpointer
from app.agents.contracts import (
    ConversationSummary,
    FeedbackContext,
    FeedbackIntent,
    FinalizeTaskOutput,
    LearningPathNodeSnapshot,
    LearningPathSnapshot,
    ResourceSummary,
    TaskRequest,
)
from app.services.evaluation_case_service import evaluation_profile_override
from app.agents.graphs import build_learning_graph
from app.agents.observability import collect_model_calls
from app.agents.nodes import GRAPH_STATE, AgentRuntime, build_nodes
from app.agents.review_agent import ReviewBatchCache
from app.core.compatibility import AGENT_CONTRACT_VERSION
from app.core.db import SessionLocal
from app.models import (
    AgentMessageRecord,
    AgentRun,
    Feedback,
    GenerationTask,
    GraphCheckpoint,
    KnowledgeUpdateImpact,
    Learner,
    LearnerProfile,
    LearningPath,
    LearningResource,
    TutoringMessage,
    TutoringSession,
)
from app.services.generation_service import persist_generated_resources
from app.services.profile_service import build_learning_path_from_snapshot, public_id
from app.services.contract_mapping import ability_profile_payload, profile_snapshot


NodeFunc = Callable[[GRAPH_STATE], GRAPH_STATE]
NODE_AGENT_NAMES = {
    "prepare_task": "orchestrator_agent",
    "interpret_feedback": "tutoring_agent",
    "analyze_profile": "profile_analysis_agent",
    "retrieve_knowledge": "knowledge_retrieval_agent",
    "generate_resource": "content_generation_agent",
    "review_resource": "review_validation_agent",
    "finalize_task": "orchestrator_agent",
}
NODE_PROGRESS = {
    "prepare_task": 5,
    "interpret_feedback": 15,
    "analyze_profile": 25,
    "retrieve_knowledge": 40,
    "generate_resource": 60,
    "review_resource": 78,
    "finalize_task": 95,
}
RECOVERABLE_CHECKPOINT_FAILURES = {
    "generated_structured_output_invalid",
    "generated_structure_validation_failed",
    # Read-only compatibility for checkpoints created before V6 error typing.
    "invalid_generate_resource_output",
    "generation_execution_failed",
    "review_model_call_failed",
    "review_output_truncated",
    "review_structured_output_invalid",
    "review_execution_failed",
}
INTERRUPTED_TASK_STATUSES = {"running", "retry_pending"}


def _message(
    db: Session,
    task: GenerationTask,
    sender: str,
    payload: dict[str, Any],
    *,
    message_type: str = "observation",
) -> None:
    db.add(
        AgentMessageRecord(
            session_id=task.public_id,
            task_id=task.public_id,
            sender=sender,
            receiver="orchestrator_agent",
            message_type=message_type,
            payload_summary_json=payload,
        )
    )


def _resource_summary(resource: LearningResource) -> dict[str, Any]:
    return {
        "resource_id": resource.public_id,
        "resource_type": resource.resource_type,
        "title": resource.title,
        "difficulty": resource.difficulty,
        "review_status": resource.review_status,
        "sources": [item.get("knowledge_id") for item in (resource.sources_json or [])],
    }


def _initial_state(
    db: Session,
    task: GenerationTask,
    learner: Learner,
    profile: LearnerProfile,
    feedback: Feedback | None,
) -> GRAPH_STATE:
    resource = (
        db.get(LearningResource, task.source_resource_id) if task.source_resource_id else None
    )
    session = (
        db.get(TutoringSession, feedback.tutoring_session_id)
        if feedback is not None and feedback.tutoring_session_id
        else None
    )
    message = (
        db.get(TutoringMessage, feedback.tutoring_message_id)
        if feedback is not None and feedback.tutoring_message_id
        else None
    )
    if task.trigger_type == "resource_feedback" and (feedback is None or resource is None):
        raise ValueError("resource_feedback_task_missing_source_references")
    inherited_targets: dict[str, list[str]] = {}
    if task.source_task_id:
        source_task = db.get(GenerationTask, task.source_task_id)
        if source_task is None:
            raise ValueError("source_package_not_found")
        if (source_task.package_quality_json or {}).get("quality_rule_version") != "quality-v6-20260818":
            raise ValueError("v6_full_regeneration_required")
        stored_targets = (source_task.package_coverage_json or {}).get(
            "resource_knowledge_targets"
        ) or {}
        inherited_targets = {
            resource_type: list(stored_targets.get(resource_type) or [])
            for resource_type in (task.resource_types_json or [])
        }
        if any(not values for values in inherited_targets.values()):
            raise ValueError("v6_source_target_mapping_missing")
    request = TaskRequest(
        task_id=task.public_id,
        session_id=task.public_id,
        trigger_type=task.trigger_type,
        execution_mode=task.execution_mode,
        learner_id=learner.public_id,
        profile_id=profile.public_id,
        domain_code=task.domain_code,
        resource_types=task.resource_types_json or ["lecture"],
        learning_goal=task.learning_goal or "根据诊断结果生成个性化学习资源",
        resource_knowledge_targets=inherited_targets,
        resource_id=resource.public_id if resource else None,
        feedback_id=str(feedback.id) if feedback else None,
        tutoring_session_id=session.public_id if session else None,
        tutoring_message_id=message.public_id if message else None,
    )
    evaluation_profile = evaluation_profile_override(request.learning_goal)
    active_profile = evaluation_profile or profile_snapshot(profile)
    # An evaluation case owns its complete non-persistent profile snapshot.
    # Mixing it with a persisted learner path would override the case's target
    # difficulty and make the live metric depend on unrelated fixture history.
    learning_path = None
    if evaluation_profile is None:
        learning_path = db.scalar(
            select(LearningPath)
            .where(
                LearningPath.learner_id == learner.id,
                LearningPath.domain_code == task.domain_code,
                LearningPath.status == "active",
            )
            .order_by(LearningPath.created_at.desc(), LearningPath.id.desc())
        )
    path_snapshot, current_path_node = _learning_path_snapshot(learning_path, active_profile)
    state: GRAPH_STATE = {
        "contract_version": AGENT_CONTRACT_VERSION,
        "task_request": request,
        "current_profile": active_profile,
        "revision_plan": None,
    }
    if path_snapshot is not None:
        state["learning_path"] = path_snapshot
    if current_path_node is not None:
        state["current_path_node"] = current_path_node
    if feedback is not None and resource is not None:
        quick_tag = feedback.feedback_intent or feedback.feedback_type
        state["feedback_context"] = FeedbackContext(
            resource=ResourceSummary(
                resource_id=resource.public_id,
                resource_type=resource.resource_type,
                title=resource.title,
                difficulty=resource.difficulty,
                source_ref_ids=[
                    item.get("source_ref_id")
                    for item in (resource.sources_json or [])
                    if item.get("source_ref_id")
                ],
            ),
            conversation=ConversationSummary(
                tutoring_session_id=session.public_id if session else task.public_id,
                turn_count=max(1, session.turn_count if session else 1),
                latest_message_summary=(
                    message.content if message else feedback.comment or "学习者提交资源反馈"
                )[:500],
            ),
            feedback_summary=(feedback.comment or feedback.feedback_type or "学习者反馈")[:500],
            quick_tag=quick_tag
            if quick_tag in {item.value for item in FeedbackIntent}
            else FeedbackIntent.OTHER,
            rating=feedback.rating,
        )
    return state


def _learning_path_snapshot(
    path: LearningPath | None, profile,
) -> tuple[LearningPathSnapshot | None, LearningPathNodeSnapshot | None]:
    if path is None:
        return None, None
    payload = path.path_json or {}
    difficulty = max(1, min(5, round(sum(profile.ability_scores.model_dump().values()) / 60)))
    nodes: list[LearningPathNodeSnapshot] = []
    for stage_index, stage in enumerate(payload.get("stages") or [], start=1):
        for knowledge_index, knowledge_id in enumerate(stage.get("knowledge_ids") or [], start=1):
            nodes.append(
                LearningPathNodeSnapshot(
                    path_node_id=f"{path.public_id}:{stage_index}:{knowledge_index}",
                    knowledge_id=str(knowledge_id),
                    title=str(stage.get("name") or knowledge_id),
                    path_order=len(nodes) + 1,
                    target_difficulty=difficulty,
                    learning_objective=str(stage.get("description") or f"掌握 {knowledge_id}"),
                )
            )
    current = nodes[0] if nodes else None
    return (
        LearningPathSnapshot(
            path_id=path.public_id,
            nodes=nodes,
            current_node_id=current.path_node_id if current else None,
        ),
        current,
    )


def _compact_review_channel(channel: dict[str, Any]) -> dict[str, Any]:
    return {
        "model_role": channel["model_role"],
        "model_name": channel["model_name"],
        "scores": channel["scores"],
        "passed": channel["passed"],
        "fact_checks": [
            {
                "claim_id": item.get("claim_id"),
                "field_path": item.get("field_path"),
                "verdict": item.get("verdict"),
                "supported": item["supported"],
                "source_ref_ids": item["source_ref_ids"],
                "determinable": item["determinable"],
            }
            for item in channel["fact_checks"]
        ],
        "unable_to_determine": channel["unable_to_determine"],
    }


def _verdict_by_claim(channel: dict[str, Any] | None) -> dict[str, str | None]:
    if not channel:
        return {}
    return {
        str(item.get("claim_id")): item.get("verdict")
        for item in channel.get("fact_checks", [])
        if item.get("claim_id")
    }


def _disputed_claim_ids(
    primary: dict[str, Any] | None, secondary: dict[str, Any] | None
) -> set[str]:
    primary_verdicts = _verdict_by_claim(primary)
    secondary_verdicts = _verdict_by_claim(secondary)
    return {
        claim_id
        for claim_id in primary_verdicts.keys() & secondary_verdicts.keys()
        if primary_verdicts[claim_id] != secondary_verdicts[claim_id]
    }


def _field_type(field_path: str | None) -> str:
    root = (field_path or "unknown").split("[", 1)[0].split(".", 1)[0]
    return root or "unknown"


def _review_observability(report: dict[str, Any]) -> dict[str, Any]:
    primary = report["primary_review"]
    secondary = report["secondary_review"]
    arbitration = report["arbitration"]
    initial_disputed = _disputed_claim_ids(primary, secondary)
    remaining_disputed = _disputed_claim_ids(
        arbitration.get("primary_recheck"), arbitration.get("secondary_recheck")
    )
    field_by_claim = {
        str(item.get("claim_id")): _field_type(item.get("field_path"))
        for item in primary.get("fact_checks", [])
        if item.get("claim_id")
    }
    disputed_field_types: dict[str, int] = {}
    for claim_id in remaining_disputed or initial_disputed:
        field_type = field_by_claim.get(claim_id, "unknown")
        disputed_field_types[field_type] = disputed_field_types.get(field_type, 0) + 1

    tendencies: dict[str, dict[str, int | float]] = {}
    for channel in (primary, secondary):
        checks = channel.get("fact_checks", [])
        supported = sum(item.get("verdict") == "supported" for item in checks)
        tendencies[channel["model_role"]] = {
            "supported": supported,
            "total": len(checks),
            "supported_rate": round(supported / len(checks), 4) if checks else 0.0,
        }
    return {
        "initial_disputed_count": len(initial_disputed),
        "remaining_disputed_count": len(remaining_disputed),
        "disputed_field_types": disputed_field_types,
        "evidence_capability_insufficient_count": sum(
            not item.get("source_ref_ids") for item in primary.get("fact_checks", [])
        ),
        "model_supported_tendency": tendencies,
    }


def _compact_review_report(report: dict[str, Any]) -> dict[str, Any]:
    arbitration = report["arbitration"]
    return {
        "resource_type": report["resource_type"],
        "decision": report["decision"],
        "passed": report["passed"],
        "quality_metrics": report["quality_metrics"],
        "final_scores": report["final_scores"],
        "evidence_ref_ids": report["evidence_ref_ids"],
        "claim_set_hash": report.get("claim_set_hash"),
        "claim_counts": {
            "supported": len(report.get("supported_claim_ids", [])),
            "contradicted": len(report.get("contradicted_claim_ids", [])),
            "evidence_insufficient": len(report.get("undetermined_claim_ids", [])),
            "unable_to_determine": len(report.get("undetermined_claim_ids", [])),
            "unresolved": len(report.get("unresolved_claim_ids", [])),
        },
        "observability": _review_observability(report),
        "primary_review": _compact_review_channel(report["primary_review"]),
        "secondary_review": _compact_review_channel(report["secondary_review"]),
        "arbitration": {
            "required": arbitration["required"],
            "retrieval_performed": arbitration["retrieval_performed"],
            "query_terms": arbitration["query_terms"],
            "additional_source_ref_ids": arbitration["additional_source_ref_ids"],
            "disputed_claim_ids": arbitration.get("disputed_claim_ids", []),
            "disagreement_remains": arbitration["disagreement_remains"],
            "primary_recheck": (
                _compact_review_channel(arbitration["primary_recheck"])
                if arbitration["primary_recheck"]
                else None
            ),
            "secondary_recheck": (
                _compact_review_channel(arbitration["secondary_recheck"])
                if arbitration["secondary_recheck"]
                else None
            ),
        },
    }


def _summary(step: str, patch: GRAPH_STATE) -> dict[str, Any]:
    output = patch.get(step)
    if output is None:
        return {"step": step}
    payload = output.model_dump(mode="json")
    if step == "generate_resource":
        return {
            "step": step,
            "resource_types": [item["resource_type"] for item in payload["resources"]],
        }
    if step == "review_resource":
        reports = [_compact_review_report(item) for item in payload["reports"]]
        return {
            "step": step,
            "decisions": [item["decision"] for item in reports],
            "package_quality": payload["package_quality"],
            "arbitration": [
                {
                    "required": item["arbitration"]["required"],
                    "retrieval_performed": item["arbitration"]["retrieval_performed"],
                    "disagreement_remains": item["arbitration"]["disagreement_remains"],
                    "query_terms": item["arbitration"]["query_terms"],
                    "additional_source_ref_ids": item["arbitration"]["additional_source_ref_ids"],
                }
                for item in reports
            ],
            "resource_reviews": reports,
        }
    if step == "analyze_profile":
        return {
            "step": step,
            "profile_id": payload["profile"]["profile_id"],
            "profile_update_required": payload["profile_update_required"],
            "needs_generation": payload["needs_generation"],
        }
    if step == "finalize_task":
        return {
            "step": step,
            "decision": payload["decision"],
            "revision_count": payload["revision_count"],
        }
    return {"step": step, "task_id": payload.get("task_id")}


def _apply_model_call_metrics(
    run: AgentRun, output: dict[str, Any], model_calls: list[dict[str, Any]]
) -> None:
    if not model_calls:
        return
    modes = {str(item["provider_mode"]) for item in model_calls}
    names = list(dict.fromkeys(str(item["model_name"]) for item in model_calls))
    run.llm_calls = len(model_calls)
    run.tokens_input = sum(int(item["tokens_input"]) for item in model_calls)
    run.tokens_output = sum(int(item["tokens_output"]) for item in model_calls)
    run.tokens_used = run.tokens_input + run.tokens_output
    run.model_name = ",".join(names)[:128]
    output["model_calls"] = model_calls
    output["provider_mode"] = modes.pop() if len(modes) == 1 else "mixed"


def _failure_code(exc: Exception) -> str:
    """Persist controlled error codes without copying arbitrary provider payloads."""
    value = str(exc).strip()
    if value and len(value) <= 128 and value.replace("_", "").isalnum():
        return value
    return type(exc).__name__


def _finalization_failure_code(result: FinalizeTaskOutput | None) -> str:
    """Map a valid final decision to a stable, machine-readable terminal reason."""
    if result is None:
        return "generation_failed"
    if result.decision.value == "failed" and result.revision_count >= 2:
        return "revision_exhausted"
    if result.decision.value == "rejected":
        return "resource_rejected"
    return "generation_incomplete"


def _restore_refresh_impact(db: Session, task: GenerationTask) -> None:
    if task.event_type != "knowledge_refresh" or not task.source_task_id:
        return
    impact = db.scalar(
        select(KnowledgeUpdateImpact)
        .where(
            KnowledgeUpdateImpact.package_task_id == task.source_task_id,
            KnowledgeUpdateImpact.resolved_by_task_id == task.id,
            KnowledgeUpdateImpact.status == "refreshing",
        )
        .order_by(KnowledgeUpdateImpact.id.desc())
    )
    if impact is not None:
        impact.status = "pending"
        impact.resolved_by_task_id = None


def _persist_profile_update(
    db: Session, task: GenerationTask, original: LearnerProfile, state: GRAPH_STATE
) -> LearnerProfile:
    analysis = state.get("analyze_profile")
    if analysis is None or not analysis.profile_update_required:
        return original
    snapshot = analysis.profile
    if (
        snapshot.profile_id == original.public_id
        and snapshot.profile_version <= original.profile_version
    ):
        return original
    next_profile = LearnerProfile(
        public_id=public_id("profile"),
        learner_id=original.learner_id,
        domain_code=original.domain_code,
        ability_profile_json=ability_profile_payload(snapshot),
        weak_knowledge_json=[item.model_dump(mode="json") for item in snapshot.weak_knowledge],
        profile_version=snapshot.profile_version,
        previous_profile_id=original.id,
        profile_source="feedback_revision",
        diagnosis_completed=True,
        changed_dimensions_json=analysis.changed_dimensions,
        evidence_refs_json=[item.model_dump(mode="json") for item in analysis.evidence_refs],
        confidence=analysis.confidence,
        context_snapshot_json=original.context_snapshot_json or {},
        trigger_feedback_id=task.source_feedback_id,
        decision_reason=analysis.decision_reason,
        profile_changed_at=datetime.now(UTC),
    )
    db.add(next_profile)
    db.flush()
    task.profile_id = next_profile.id
    for path in db.scalars(select(LearningPath).where(LearningPath.profile_id == original.id)):
        path.needs_refresh = True
    db.add(
        LearningPath(
            public_id=public_id("path"),
            learner_id=original.learner_id,
            profile_id=next_profile.id,
            domain_code=original.domain_code,
            status="active",
            path_json=build_learning_path_from_snapshot(
                next_profile.ability_profile_json, next_profile.weak_knowledge_json
            ),
            needs_refresh=False,
        )
    )
    return next_profile


def _observable_node(
    db: Session,
    task: GenerationTask,
    profile: LearnerProfile,
    step: str,
    node: NodeFunc,
    runtime: AgentRuntime,
) -> NodeFunc:
    agent_name = NODE_AGENT_NAMES[step]

    def wrapped(state: GRAPH_STATE) -> GRAPH_STATE:
        started = time.perf_counter()
        initial_output: dict[str, Any] = {"step": step}
        if step == "review_resource":
            initial_output["review_batch_cache"] = runtime.review_batch_cache.snapshot()
        run = AgentRun(
            generation_task_id=task.id,
            agent_name=agent_name,
            status="running",
            input_summary_json={"task_id": task.public_id, "step": step},
            output_summary_json=initial_output,
            prompt_version="v6",
        )
        db.add(run)
        _message(
            db,
            task,
            agent_name,
            {"step": step, "status": "running", "contract_version": "agent-contract-v6"},
        )
        db.commit()
        if step == "review_resource":

            def persist_review_cache(snapshot: dict[str, Any]) -> None:
                current = dict(run.output_summary_json or {})
                current["review_batch_cache"] = snapshot
                run.output_summary_json = current
                db.add(run)
                db.commit()

            runtime.review_batch_cache.set_persist_callback(persist_review_cache)
        model_calls: list[dict[str, Any]] = []
        try:
            with collect_model_calls() as collector:
                patch = node(state)
            model_calls = collector.snapshot()
            next_state = {**state, **patch}
            if step == "analyze_profile":
                _persist_profile_update(db, task, profile, next_state)
            if step == "finalize_task":
                persist_generated_resources(
                    db, task, db.get(LearnerProfile, task.profile_id) or profile, next_state
                )
            output = _summary(step, patch)
            if step == "review_resource":
                output["review_batch_cache"] = runtime.review_batch_cache.snapshot()
            _apply_model_call_metrics(run, output, model_calls)
            run.status = "completed"
            run.output_summary_json = output
            run.duration_ms = round((time.perf_counter() - started) * 1000)
            task.progress = max(task.progress, NODE_PROGRESS[step])
            _message(
                db,
                task,
                agent_name,
                {
                    "step": step,
                    "status": "completed",
                    "output": output,
                    "contract_version": "agent-contract-v6",
                },
                message_type="result",
            )
            db.commit()
            return patch
        except Exception as exc:
            if "collector" in locals():
                model_calls = collector.snapshot()
            run.status = "failed"
            run.error_message = str(exc)
            output = {
                "step": step,
                "error": type(exc).__name__,
                "failure_code": _failure_code(exc),
                "failed_step": step,
                "recoverable": step
                in {
                    "retrieve_knowledge",
                    "generate_resource",
                    "review_resource",
                },
                "resource_types": list(
                    dict.fromkeys(
                        str(item.get("resource_type"))
                        for item in model_calls
                        if item.get("resource_type")
                    )
                ),
                "model_roles": list(
                    dict.fromkeys(str(item.get("role")) for item in model_calls if item.get("role"))
                ),
            }
            field_paths = getattr(exc, "field_paths", None)
            if isinstance(field_paths, list) and field_paths:
                output["field_paths"] = [str(path)[:200] for path in field_paths[:20]]
            if step == "review_resource":
                output["review_batch_cache"] = runtime.review_batch_cache.snapshot()
            _apply_model_call_metrics(run, output, model_calls)
            run.output_summary_json = output
            run.duration_ms = round((time.perf_counter() - started) * 1000)
            error_payload = {
                "step": step,
                "status": "failed",
                "error": type(exc).__name__,
                "failure_code": _failure_code(exc),
            }
            if output.get("field_paths"):
                error_payload["field_paths"] = output["field_paths"]
            _message(
                db,
                task,
                agent_name,
                error_payload,
                message_type="error",
            )
            db.commit()
            raise
        finally:
            if step == "review_resource":
                runtime.review_batch_cache.set_persist_callback(None)

    return wrapped


def _build_graph(
    db: Session,
    task: GenerationTask,
    profile: LearnerProfile,
    checkpointer: MySQLLangGraphCheckpointer,
    runtime: AgentRuntime,
):
    return build_learning_graph(
        {
            step: _observable_node(db, task, profile, step, node, runtime)
            for step, node in build_nodes(runtime).items()
        },
        checkpointer=checkpointer,
        runtime=runtime,
    )


def _load_review_batch_cache(db: Session, task: GenerationTask) -> ReviewBatchCache:
    runs = db.scalars(
        select(AgentRun)
        .where(AgentRun.generation_task_id == task.id)
        .where(AgentRun.agent_name == "review_validation_agent")
        .order_by(AgentRun.id.desc())
    )
    for run in runs:
        output = run.output_summary_json or {}
        snapshot = output.get("review_batch_cache")
        if isinstance(snapshot, dict) and snapshot.get("entries"):
            return ReviewBatchCache(snapshot)
    return ReviewBatchCache()


def recover_interrupted_generation_tasks() -> list[str]:
    """Claim interrupted tasks for one checkpoint-backed startup recovery."""

    claimed: list[str] = []
    with SessionLocal() as db:
        tasks = list(
            db.scalars(
                select(GenerationTask)
                .where(GenerationTask.status.in_(INTERRUPTED_TASK_STATUSES))
                .order_by(GenerationTask.id)
            )
        )
        for task in tasks:
            checkpoint = db.scalar(
                select(GraphCheckpoint).where(GraphCheckpoint.task_id == task.public_id)
            )
            checkpoint_payload = dict(checkpoint.state_json or {}) if checkpoint else {}
            recovery_count = int(checkpoint_payload.get("auto_recovery_count") or 0)
            has_native_checkpoint = bool(checkpoint_payload.get("native_checkpoint"))
            running_runs = list(
                db.scalars(
                    select(AgentRun)
                    .where(AgentRun.generation_task_id == task.id)
                    .where(AgentRun.status == "running")
                    .order_by(AgentRun.id)
                )
            )
            failure_code = (
                "checkpoint_recovery_exhausted"
                if has_native_checkpoint and recovery_count >= 1
                else "checkpoint_missing_after_interruption"
            )
            for run in running_runs:
                output = dict(run.output_summary_json or {})
                output.update(
                    {
                        "error": "ProcessInterrupted",
                        "failure_code": "persistence_interrupted",
                        "failed_step": (run.input_summary_json or {}).get("step"),
                        "recoverable": has_native_checkpoint and recovery_count < 1,
                    }
                )
                run.status = "failed"
                run.error_message = "persistence_interrupted"
                run.output_summary_json = output

            if has_native_checkpoint and recovery_count < 1:
                checkpoint_payload["auto_recovery_count"] = recovery_count + 1
                checkpoint.state_json = checkpoint_payload
                checkpoint.status = "recovery_scheduled"
                task.status = "retry_pending"
                task.decision = "pending"
                task.failure_reason = ""
                claimed.append(task.public_id)
                _message(
                    db,
                    task,
                    "generation_worker",
                    {
                        "task_id": task.public_id,
                        "status": "checkpoint_auto_recovery",
                        "failure_code": "persistence_interrupted",
                        "retry_count": recovery_count + 1,
                    },
                    message_type="event",
                )
            else:
                task.status = "failed"
                task.decision = "failed"
                task.failure_reason = failure_code
                _restore_refresh_impact(db, task)
                _message(
                    db,
                    task,
                    "generation_worker",
                    {
                        "task_id": task.public_id,
                        "status": "failed",
                        "failure_code": failure_code,
                        "failed_step": "generation_worker",
                    },
                    message_type="error",
                )
        db.commit()
    return claimed


def run_generation_task(task_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        task = db.scalar(select(GenerationTask).where(GenerationTask.public_id == task_id))
        if task is None:
            return {"task_id": task_id, "status": "not_found"}
        if task.status == "completed" and task.decision in {"completed", "no_change"}:
            resources = list(
                db.scalars(
                    select(LearningResource)
                    .where(LearningResource.generation_task_id == task.id)
                    .order_by(LearningResource.id)
                )
            )
            return {
                "task_id": task.public_id,
                "status": task.status,
                "decision": task.decision,
                "resources": [_resource_summary(item) for item in resources],
            }
        learner, profile = db.get(Learner, task.learner_id), db.get(LearnerProfile, task.profile_id)
        if learner is None or profile is None:
            task.status = task.decision = "failed"
            db.commit()
            return {"task_id": task_id, "status": "failed"}
        feedback = db.get(Feedback, task.source_feedback_id) if task.source_feedback_id else None
        resume_failed = task.status in {"failed", "retry_pending"}
        task.status = "running"
        task.decision = "pending"
        db.commit()
        review_batch_cache = _load_review_batch_cache(db, task)
        runtime = AgentRuntime.production(review_batch_cache=review_batch_cache)
        checkpointer = MySQLLangGraphCheckpointer(SessionLocal)
        try:
            graph = _build_graph(db, task, profile, checkpointer, runtime)
            graph_config = {"configurable": {"thread_id": task.public_id}}
            graph_input: GRAPH_STATE | None = _initial_state(
                db, task, learner, profile, feedback
            )
            if resume_failed and checkpointer.get_tuple(graph_config) is not None:
                # A failed LangGraph node leaves the last successful checkpoint
                # intact. Invoking with None resumes that node and preserves the
                # generated resources already present in state.
                graph_input = None
            final = None
            for checkpoint_attempt in range(2):
                try:
                    final = graph.invoke(graph_input, config=graph_config)
                    break
                except Exception as exc:
                    failure_code = _failure_code(exc)
                    can_resume = (
                        checkpoint_attempt == 0
                        and failure_code in RECOVERABLE_CHECKPOINT_FAILURES
                        and checkpointer.get_tuple(graph_config) is not None
                    )
                    if not can_resume:
                        raise
                    _message(
                        db,
                        task,
                        "generation_worker",
                        {
                            "task_id": task.public_id,
                            "status": "checkpoint_retry",
                            "failure_code": failure_code,
                            "retry_count": 1,
                        },
                        message_type="event",
                    )
                    db.commit()
                    graph_input = None
            if final is None:  # pragma: no cover - loop either returns or raises
                raise RuntimeError("checkpoint_resume_failed")
            result = final.get("finalize_task")
            task.revision_count = result.revision_count if result else 0
            task.decision = result.decision.value if result else "failed"
            if task.decision in {"completed", "no_change"}:
                task.status = "completed"
                task.progress = 100
                checkpointer.mark_status(task.public_id, "resolved")
            else:
                task.status = "failed"
                task.failure_reason = _finalization_failure_code(result)
                _restore_refresh_impact(db, task)
            db.commit()
            resources = list(
                db.scalars(
                    select(LearningResource)
                    .where(LearningResource.generation_task_id == task.id)
                    .order_by(LearningResource.id)
                )
            )
            return {
                "task_id": task.public_id,
                "status": task.status,
                "decision": task.decision,
                "resources": [_resource_summary(item) for item in resources],
            }
        except Exception as exc:
            task.status = task.decision = "failed"
            task.failure_reason = _failure_code(exc)
            _restore_refresh_impact(db, task)
            _message(
                db,
                task,
                "generation_worker",
                {
                    "task_id": task.public_id,
                    "status": "failed",
                    "error": type(exc).__name__,
                    "failure_code": _failure_code(exc),
                    "failed_step": "generation_worker",
                },
                message_type="error",
            )
            db.commit()
            return {"task_id": task.public_id, "status": "failed", "error": type(exc).__name__}
        finally:
            runtime.close()
