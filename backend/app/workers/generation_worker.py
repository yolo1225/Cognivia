"""V2 generation worker and observability bridge."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langgraph.errors import GraphInterrupt
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.checkpointer import MySQLLangGraphCheckpointer
from app.agents.contracts import (
    ConversationSummary,
    FeedbackContext,
    FeedbackIntent,
    ResourceSummary,
    TaskRequest,
)
from app.services.evaluation_case_service import evaluation_profile_override
from app.agents.graphs import build_learning_graph
from app.agents.v2_observability import collect_model_calls
from app.agents.v2_nodes import V2_GRAPH_STATE, V2Runtime, build_nodes
from app.core.compatibility import AGENT_CONTRACT_VERSION
from app.core.db import SessionLocal
from app.models import (
    AgentMessageRecord,
    AgentRun,
    Feedback,
    GenerationTask,
    Learner,
    LearnerProfile,
    LearningPath,
    LearningResource,
    ManualReviewTask,
    TutoringMessage,
    TutoringSession,
)
from app.services.generation_service import persist_generated_resources
from app.services.profile_service import build_learning_path_from_snapshot, public_id
from app.services.task_lifecycle_service import transition_task
from app.services.v2_contract_mapping import ability_profile_payload, profile_snapshot


NodeFunc = Callable[[V2_GRAPH_STATE], V2_GRAPH_STATE]
NODE_AGENT_NAMES = {
    "prepare_task": "orchestrator_agent",
    "interpret_feedback": "tutoring_agent",
    "analyze_profile": "profile_analysis_agent",
    "retrieve_knowledge": "knowledge_retrieval_agent",
    "generate_resource": "content_generation_agent",
    "review_resource": "review_validation_agent",
    "human_review": "orchestrator_agent",
    "finalize_task": "orchestrator_agent",
}
NODE_PROGRESS = {
    "prepare_task": 5,
    "interpret_feedback": 15,
    "analyze_profile": 25,
    "retrieve_knowledge": 40,
    "generate_resource": 60,
    "review_resource": 78,
    "human_review": 82,
    "finalize_task": 95,
}


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
) -> V2_GRAPH_STATE:
    resource = db.get(LearningResource, task.source_resource_id) if task.source_resource_id else None
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
        resource_id=resource.public_id if resource else None,
        feedback_id=str(feedback.id) if feedback else None,
        tutoring_session_id=session.public_id if session else None,
        tutoring_message_id=message.public_id if message else None,
    )
    active_profile = evaluation_profile_override(request.learning_goal) or profile_snapshot(profile)
    state: V2_GRAPH_STATE = {
        "contract_version": AGENT_CONTRACT_VERSION,
        "task_request": request,
        "current_profile": active_profile,
        "revision_plan": None,
    }
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


def _compact_review_channel(channel: dict[str, Any]) -> dict[str, Any]:
    return {
        "model_role": channel["model_role"],
        "model_name": channel["model_name"],
        "scores": channel["scores"],
        "passed": channel["passed"],
        "fact_checks": [
            {
                "supported": item["supported"],
                "source_ref_ids": item["source_ref_ids"],
                "determinable": item["determinable"],
            }
            for item in channel["fact_checks"]
        ],
        "unable_to_determine": channel["unable_to_determine"],
    }


def _compact_review_report(report: dict[str, Any]) -> dict[str, Any]:
    arbitration = report["arbitration"]
    return {
        "resource_type": report["resource_type"],
        "decision": report["decision"],
        "passed": report["passed"],
        "manual_review_required": report["manual_review_required"],
        "final_scores": report["final_scores"],
        "evidence_ref_ids": report["evidence_ref_ids"],
        "primary_review": _compact_review_channel(report["primary_review"]),
        "secondary_review": _compact_review_channel(report["secondary_review"]),
        "arbitration": {
            "required": arbitration["required"],
            "retrieval_performed": arbitration["retrieval_performed"],
            "query_terms": arbitration["query_terms"],
            "additional_source_ref_ids": arbitration["additional_source_ref_ids"],
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


def _summary(step: str, patch: V2_GRAPH_STATE) -> dict[str, Any]:
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
            "manual_review_required": any(
                item["manual_review_required"] for item in reports
            ),
            "arbitration": [
                {
                    "required": item["arbitration"]["required"],
                    "retrieval_performed": item["arbitration"]["retrieval_performed"],
                    "disagreement_remains": item["arbitration"]["disagreement_remains"],
                    "query_terms": item["arbitration"]["query_terms"],
                    "additional_source_ref_ids": item["arbitration"][
                        "additional_source_ref_ids"
                    ],
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


def _persist_profile_update(
    db: Session, task: GenerationTask, original: LearnerProfile, state: V2_GRAPH_STATE
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
        changed_dimensions_json=analysis.changed_dimensions,
        evidence_refs_json=[item.model_dump(mode="json") for item in analysis.evidence_refs],
        confidence=analysis.confidence,
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
    db: Session, task: GenerationTask, profile: LearnerProfile, step: str, node: NodeFunc
) -> NodeFunc:
    agent_name = NODE_AGENT_NAMES[step]

    def wrapped(state: V2_GRAPH_STATE) -> V2_GRAPH_STATE:
        started = time.perf_counter()
        run = AgentRun(
            generation_task_id=task.id,
            agent_name=agent_name,
            status="running",
            input_summary_json={"task_id": task.public_id, "step": step},
            output_summary_json={"step": step},
            prompt_version="v2",
        )
        db.add(run)
        _message(
            db,
            task,
            agent_name,
            {"step": step, "status": "running", "contract_version": "agent-contract-v2"},
        )
        db.commit()
        model_calls: list[dict[str, Any]] = []
        try:
            with collect_model_calls() as collector:
                patch = node(state)
            model_calls = collector.snapshot()
            next_state = {**state, **patch}
            if step == "analyze_profile":
                _persist_profile_update(db, task, profile, next_state)
            if (
                step == "finalize_task"
                and next_state["finalize_task"].decision.value == "completed"
            ):
                persist_generated_resources(
                    db, task, db.get(LearnerProfile, task.profile_id) or profile, next_state
                )
            output = _summary(step, patch)
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
                    "contract_version": "agent-contract-v2",
                },
                message_type="result",
            )
            db.commit()
            return patch
        except GraphInterrupt:
            if "collector" in locals():
                model_calls = collector.snapshot()
            run.status = "completed"
            run.output_summary_json = {"step": step, "decision": "manual_review_required"}
            _apply_model_call_metrics(run, run.output_summary_json, model_calls)
            run.duration_ms = round((time.perf_counter() - started) * 1000)
            _message(
                db,
                task,
                agent_name,
                {"step": step, "status": "waiting_human"},
                message_type="decision",
            )
            db.commit()
            raise
        except Exception as exc:
            if "collector" in locals():
                model_calls = collector.snapshot()
            run.status = "failed"
            run.error_message = str(exc)
            output = {"step": step, "error": type(exc).__name__}
            _apply_model_call_metrics(run, output, model_calls)
            run.output_summary_json = output
            run.duration_ms = round((time.perf_counter() - started) * 1000)
            _message(
                db,
                task,
                agent_name,
                {"step": step, "status": "failed", "error": type(exc).__name__},
                message_type="error",
            )
            db.commit()
            raise

    return wrapped


def _build_graph(
    db: Session,
    task: GenerationTask,
    profile: LearnerProfile,
    checkpointer: MySQLLangGraphCheckpointer,
    runtime: V2Runtime,
):
    return build_learning_graph(
        {
            step: _observable_node(db, task, profile, step, node)
            for step, node in build_nodes(runtime).items()
        },
        checkpointer=checkpointer,
        runtime=runtime,
    )


def run_generation_task(task_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        task = db.scalar(select(GenerationTask).where(GenerationTask.public_id == task_id))
        if task is None:
            return {"task_id": task_id, "status": "not_found"}
        learner, profile = db.get(Learner, task.learner_id), db.get(LearnerProfile, task.profile_id)
        if learner is None or profile is None:
            transition_task(task, status="failed", decision="failed")
            db.commit()
            return {"task_id": task_id, "status": "failed"}
        feedback = db.get(Feedback, task.source_feedback_id) if task.source_feedback_id else None
        resume = task.status == "waiting_human"
        transition_task(task, status="running", decision="pending")
        db.commit()
        runtime = V2Runtime.production()
        checkpointer = MySQLLangGraphCheckpointer(SessionLocal)
        try:
            graph = _build_graph(db, task, profile, checkpointer, runtime)
            graph_input: V2_GRAPH_STATE | Command = _initial_state(
                db, task, learner, profile, feedback
            )
            if resume:
                manual = db.scalar(
                    select(ManualReviewTask)
                    .where(ManualReviewTask.task_id == task.id)
                    .where(ManualReviewTask.status == "resolved")
                    .order_by(ManualReviewTask.id.desc())
                )
                if manual is None or not manual.decision:
                    transition_task(
                        task,
                        status="waiting_human",
                        decision="manual_review_required",
                    )
                    db.commit()
                    return {"task_id": task.public_id, "status": task.status}
                graph_input = Command(
                    resume={
                        "decision": manual.decision,
                        "review_comment": manual.review_comment or "管理员已处理。",
                        "operator_id": manual.reviewed_by or "admin",
                        "reviewed_at": datetime.now(UTC).isoformat(),
                    }
                )
            final = graph.invoke(
                graph_input, config={"configurable": {"thread_id": task.public_id}}
            )
            result = final.get("finalize_task")
            task.revision_count = result.revision_count if result else 0
            decision = result.decision.value if result else "failed"
            if decision in {"completed", "no_change"}:
                transition_task(task, status="completed", decision=decision, progress=100)
                checkpointer.mark_status(task.public_id, "resolved")
            elif decision == "manual_review_required":
                transition_task(task, status="waiting_human", decision=decision)
                checkpointer.mark_status(task.public_id, "waiting_human")
                if (
                    db.scalar(select(ManualReviewTask).where(ManualReviewTask.task_id == task.id))
                    is None
                ):
                    db.add(
                        ManualReviewTask(
                            public_id=f"mr_{task.public_id}",
                            task_id=task.id,
                            trigger_reason="model_disagreement",
                            status="pending",
                        )
                    )
            else:
                transition_task(
                    task,
                    status="failed" if decision == "rejected" else decision,
                    decision=decision,
                )
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
        except GraphInterrupt:
            transition_task(task, status="waiting_human", decision="manual_review_required")
            checkpointer.mark_status(task.public_id, "waiting_human")
            if (
                db.scalar(select(ManualReviewTask).where(ManualReviewTask.task_id == task.id))
                is None
            ):
                db.add(
                    ManualReviewTask(
                        public_id=f"mr_{task.public_id}",
                        task_id=task.id,
                        trigger_reason="model_disagreement",
                        status="pending",
                    )
                )
            db.commit()
            return {"task_id": task.public_id, "status": task.status, "decision": task.decision}
        except Exception as exc:
            transition_task(task, status="failed", decision="failed")
            _message(
                db,
                task,
                "generation_worker",
                {"task_id": task.public_id, "status": "failed", "error": type(exc).__name__},
                message_type="error",
            )
            db.commit()
            return {"task_id": task.public_id, "status": "failed", "error": type(exc).__name__}
        finally:
            runtime.close()
