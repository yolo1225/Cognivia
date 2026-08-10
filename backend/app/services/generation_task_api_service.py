from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.errors import not_found
from app.models import AgentRun, GenerationTask, Learner, LearnerProfile, LearningResource
from app.repositories.generation_task_repo import GenerationTaskRepository
from app.schemas.api_requests import GenerationTaskCreateRequest
from app.services.profile_service import default_profile_for_learner, profile_source, public_id


ACTIVE_TASK_STATUSES = {"pending", "running", "waiting_human"}
TERMINAL_TASK_STATUSES = {"completed", "failed", "revision_required", "waiting_human", "no_change", "rejected"}
SENSITIVE_KEYS = {"content", "content_md", "draft_resources", "profile", "answers"}
STEP_LABELS = {"prepare_task": "任务准备", "interpret_feedback": "反馈识别", "analyze_profile": "画像分析", "retrieve_knowledge": "知识检索", "generate_resource": "资源生成", "review_resource": "双模型审核", "human_review": "人工复核", "finalize_task": "确定性收尾"}


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items() if key not in SENSITIVE_KEYS}
    if isinstance(value, list):
        return [_safe(item) for item in value[:30]]
    return value


class GenerationTaskApiService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = GenerationTaskRepository(db)

    def _get_or_create_learner(self, learner_public_id: str) -> Learner:
        learner = self.repository.learner(learner_public_id)
        if learner is not None:
            return learner
        learner = Learner(public_id=learner_public_id, background="MVP 演示学习者", target_domain="ai_app_dev", experience_years=0, learning_style="mixed")
        self.db.add(learner)
        self.db.flush()
        return learner

    @staticmethod
    def _resource_summary(resource: LearningResource) -> dict[str, Any]:
        return {"resource_id": resource.public_id, "resource_type": resource.resource_type, "title": resource.title, "difficulty": resource.difficulty, "review_status": resource.review_status, "version": resource.version, "is_current": resource.is_current, "sources": [item.get("knowledge_id") for item in (resource.sources_json or [])]}

    def _profile_summary(self, task: GenerationTask) -> dict[str, Any]:
        profile = self.db.get(LearnerProfile, task.profile_id)
        if profile is None:
            return {"profile_id": None, "profile_version": None, "profile_source": None, "profile_changed_dimensions": []}
        return {"profile_id": profile.public_id, "profile_version": profile.profile_version, "profile_source": profile_source(profile), "profile_changed_dimensions": profile.changed_dimensions_json or []}

    def detail(self, task: GenerationTask) -> dict[str, Any]:
        learner = self.db.get(Learner, task.learner_id)
        return {"task_id": task.public_id, "thread_id": task.public_id, "status": task.status, "progress": task.progress, "trigger_type": task.trigger_type, "execution_mode": task.execution_mode, "learner_id": learner.public_id if learner else None, **self._profile_summary(task), "revision_count": task.revision_count, "decision": task.decision, "resources": [self._resource_summary(item) for item in self.repository.resources(task.id)]}

    def create(self, payload: GenerationTaskCreateRequest) -> tuple[dict[str, Any], str, str]:
        learner = self._get_or_create_learner(payload.learner_id)
        profile = self.repository.profile(payload.profile_id) if payload.profile_id else default_profile_for_learner(self.db, learner)
        if profile is None:
            raise not_found("LEARNER_PROFILE_NOT_FOUND", "学习者画像不存在。")
        learner = self.db.get(Learner, profile.learner_id) or learner
        task = self.repository.add(GenerationTask(public_id=public_id("task"), learner_id=learner.id, profile_id=profile.id, domain_code=payload.domain_code, status="pending", resource_types_json=list(payload.resource_types), revision_count=0, decision="pending", trigger_type=payload.trigger_type, execution_mode=payload.execution_mode, learning_goal=payload.learning_goal, progress=0))
        result = {"task_id": task.public_id, "thread_id": task.public_id, "status": task.status, "trigger_type": task.trigger_type, "execution_mode": task.execution_mode, "resource_types": list(payload.resource_types), "agent_graph": "unified_learning_graph_v2", **self._profile_summary(task), "decision": task.decision, "agent_trace": [], "resources": []}
        return result, "generation_task", task.public_id

    def active(self, learner_id: str) -> dict[str, Any] | None:
        task = self.repository.active_task(learner_id, ACTIVE_TASK_STATUSES)
        return self.detail(task) if task is not None else None

    def get(self, task_id: str) -> dict[str, Any]:
        task = self.repository.task(task_id)
        if task is None:
            raise not_found("GENERATION_TASK_NOT_FOUND", "生成任务不存在。")
        return self.detail(task)

    def runs(self, task_id: str) -> list[dict[str, Any]]:
        task = self.repository.task(task_id)
        if task is None:
            raise not_found("GENERATION_TASK_NOT_FOUND", "生成任务不存在。")
        return [{"run_id": run.id, "task_id": task.public_id, "agent_name": run.agent_name, "status": run.status, "input_summary": _safe(run.input_summary_json or {}), "output_summary": _safe(run.output_summary_json or {}), "model_name": run.model_name, "prompt_version": run.prompt_version, "tokens_input": run.tokens_input, "tokens_output": run.tokens_output, "duration_ms": run.duration_ms, "error": run.error_message} for run in self.repository.runs(task.id)]


def _event(name: str, event_id: int, payload: dict[str, Any]) -> str:
    return f"id: {event_id}\nevent: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _agent_event(task: GenerationTask, run: AgentRun) -> dict[str, Any]:
    output = _safe(run.output_summary_json or {})
    step = str((run.input_summary_json or {}).get("step") or output.get("step") or run.agent_name)
    return {"event_id": run.id, "task_id": task.public_id, "event_type": "agent_status", "step": step, "status": run.status, "agent_name": run.agent_name, "generation_round": (run.input_summary_json or {}).get("generation_round"), "event_message": f"{STEP_LABELS.get(step, step)}{'完成' if run.status == 'completed' else '运行中' if run.status == 'running' else '失败'}", "payload": output, "timestamp": run.updated_at.isoformat() if run.updated_at else datetime.now(UTC).isoformat()}


def _semantic_event_names(payload: dict[str, Any]) -> list[str]:
    if payload["status"] != "completed":
        return []
    step = payload["step"]
    output = payload["payload"]
    if step == "prepare_task":
        return ["trigger_routed"]
    if step == "interpret_feedback":
        return ["feedback_classified"]
    if step == "analyze_profile":
        names = ["profile_update_decided"]
        names.append("profile_updated" if output.get("profile_update_required") else "profile_unchanged")
        if output.get("profile_update_required"):
            names.extend(["path_refresh_started", "path_refresh_completed"])
        return names
    if step == "review_resource" and output.get("manual_review_required"):
        return ["review_disagreement", "review_retrieval_started"]
    if step == "human_review":
        return ["manual_review_required" if output.get("decision") == "manual_review_required" else "manual_review_resolved"]
    return []


async def stream_task_events(task_id: str) -> AsyncIterator[str]:
    emitted: set[tuple[int, str]] = set()
    event_id = 0
    while True:
        with SessionLocal() as db:
            repository = GenerationTaskRepository(db)
            task = repository.task(task_id)
            if task is None:
                event_id += 1
                yield _event("task_failed", event_id, {"event_id": event_id, "task_id": task_id, "status": "not_found", "timestamp": datetime.now(UTC).isoformat()})
                return
            for run in repository.runs(task.id):
                key = (run.id, run.status)
                if key in emitted:
                    continue
                emitted.add(key)
                payload = _agent_event(task, run)
                event_id = max(event_id + 1, run.id)
                payload["event_id"] = event_id
                yield _event("agent_status", event_id, payload)
                for name in _semantic_event_names(payload):
                    event_id += 1
                    semantic_payload = {
                        "event_id": event_id,
                        "task_id": task.public_id,
                        "event_type": name,
                        "status": run.status,
                        "step": payload["step"],
                        "timestamp": payload["timestamp"],
                        **payload["payload"],
                    }
                    yield _event(name, event_id, semantic_payload)
            if task.status in TERMINAL_TASK_STATUSES:
                if task.status in {"completed", "no_change"}:
                    for resource in repository.resources(task.id):
                        event_id += 1
                        yield _event(
                            "resource_created",
                            event_id,
                            {
                                "event_id": event_id,
                                "task_id": task.public_id,
                                "event_type": "resource_created",
                                "status": task.status,
                                "timestamp": datetime.now(UTC).isoformat(),
                                **GenerationTaskApiService._resource_summary(resource),
                            },
                        )
                event_id += 1
                name = "task_completed" if task.status in {"completed", "no_change"} else "manual_review_required" if task.status == "waiting_human" else "task_failed"
                yield _event(name, event_id, {"event_id": event_id, "task_id": task.public_id, "event_type": name, "step": "task", "status": task.status, "decision": task.decision, "progress": task.progress, "timestamp": datetime.now(UTC).isoformat()})
                return
        await asyncio.sleep(0.35)
