"""One-way cleanup of obsolete generation and review runtime data."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, delete, func, inspect, select, update
from sqlalchemy.orm import Session

from app.models import (
    AgentMessageRecord,
    AgentRun,
    AnswerRecord,
    DiagnosticQuestion,
    DiagnosticSession,
    Domain,
    EvaluationCase,
    GenerationTask,
    GraphCheckpoint,
    IndexBuildJob,
    KnowledgeDocument,
    KnowledgeItem,
    KnowledgeRelation,
    KnowledgeUpdateImpact,
    Learner,
    LearnerProfile,
    LearningPackageResource,
    LearningPath,
    LearningResource,
    ReviewReport,
    TutoringMessage,
    TutoringSession,
    User,
)
from app.models.feedback import Feedback
from app.rag.candidate_manifest import candidate_index_root


ACTIVE_GENERATION_STATUSES = {"pending", "running", "retry_pending"}
PRESERVED_MODELS = (
    User,
    Learner,
    DiagnosticSession,
    DiagnosticQuestion,
    AnswerRecord,
    LearnerProfile,
    LearningPath,
    Domain,
    KnowledgeItem,
    KnowledgeRelation,
    KnowledgeDocument,
    IndexBuildJob,
    EvaluationCase,
)


class GenerationRuntimeCleanupBlocked(RuntimeError):
    pass


def _row_counts(db: Session, models: tuple[type, ...]) -> dict[str, int]:
    return {
        model.__tablename__: int(db.scalar(select(func.count()).select_from(model)) or 0)
        for model in models
    }


def _manifest_hashes(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(root.glob("*/manifest.json"))
        if path.is_file()
    }


def _delete_exports(export_dir: Path | None) -> int:
    if export_dir is None or not export_dir.exists():
        return 0
    deleted = 0
    for path in export_dir.glob("res_*"):
        if path.is_file():
            path.unlink()
            deleted += 1
    return deleted


def clear_generation_runtime(
    db: Session,
    *,
    services_stopped: bool = False,
    export_dir: Path | None = None,
    manifest_root: Path | None = None,
) -> dict[str, Any]:
    """Delete obsolete generation runtime rows while proving preserved state is unchanged."""
    active_count = int(
        db.scalar(
            select(func.count())
            .select_from(GenerationTask)
            .where(GenerationTask.status.in_(ACTIVE_GENERATION_STATUSES))
        )
        or 0
    )
    if active_count and not services_stopped:
        raise GenerationRuntimeCleanupBlocked(
            f"active_generation_tasks_exist:{active_count}; stop services and acknowledge it"
        )

    root = manifest_root or candidate_index_root()
    preserved_before = _row_counts(db, PRESERVED_MODELS)
    manifests_before = _manifest_hashes(root)
    task_rows = list(db.execute(select(GenerationTask.id, GenerationTask.public_id)))
    task_ids = [row.id for row in task_rows]
    task_public_ids = [row.public_id for row in task_rows]
    resource_ids = list(db.scalars(select(LearningResource.id)))
    feedback_ids = (
        list(db.scalars(select(Feedback.id).where(Feedback.resource_id.in_(resource_ids))))
        if resource_ids
        else []
    )
    feedback_session_ids = (
        list(
            db.scalars(
                select(Feedback.tutoring_session_id).where(
                    Feedback.id.in_(feedback_ids),
                    Feedback.tutoring_session_id.is_not(None),
                )
            )
        )
        if feedback_ids
        else []
    )
    resource_session_ids = (
        list(
            db.scalars(
                select(TutoringSession.id).where(TutoringSession.resource_id.in_(resource_ids))
            )
        )
        if resource_ids
        else []
    )
    session_ids = sorted(set(feedback_session_ids) | set(resource_session_ids))

    deleted: dict[str, int] = {}

    def execute_delete(name: str, statement: Any) -> None:
        result = db.execute(statement)
        deleted[name] = max(0, int(result.rowcount or 0))

    if feedback_ids:
        db.execute(
            update(LearnerProfile)
            .where(LearnerProfile.trigger_feedback_id.in_(feedback_ids))
            .values(trigger_feedback_id=None)
        )
    if task_ids:
        db.execute(
            update(GenerationTask)
            .where(GenerationTask.id.in_(task_ids))
            .values(source_resource_id=None, source_feedback_id=None, source_task_id=None)
        )
        db.execute(
            update(KnowledgeUpdateImpact)
            .where(KnowledgeUpdateImpact.resolved_by_task_id.in_(task_ids))
            .values(resolved_by_task_id=None)
        )
    if resource_ids:
        db.execute(
            update(LearningResource)
            .where(LearningResource.id.in_(resource_ids))
            .values(previous_resource_id=None)
        )
    if feedback_ids:
        db.execute(
            update(Feedback)
            .where(Feedback.id.in_(feedback_ids))
            .values(tutoring_session_id=None, tutoring_message_id=None)
        )
        db.execute(
            update(TutoringMessage)
            .where(TutoringMessage.feedback_id.in_(feedback_ids))
            .values(feedback_id=None)
        )

    inspector = inspect(db.get_bind())
    if "manual_review_tasks" in inspector.get_table_names() and task_ids:
        manual_review_tasks = Table(
            "manual_review_tasks", MetaData(), autoload_with=db.get_bind()
        )
        execute_delete(
            "manual_review_tasks",
            delete(manual_review_tasks).where(manual_review_tasks.c.task_id.in_(task_ids)),
        )
    else:
        deleted["manual_review_tasks"] = 0

    execute_delete("knowledge_update_impacts", delete(KnowledgeUpdateImpact))
    execute_delete("learning_package_resources", delete(LearningPackageResource))
    execute_delete("review_reports", delete(ReviewReport))
    execute_delete("agent_runs", delete(AgentRun))
    if task_public_ids:
        execute_delete(
            "agent_messages",
            delete(AgentMessageRecord).where(AgentMessageRecord.task_id.in_(task_public_ids)),
        )
        execute_delete(
            "graph_checkpoints",
            delete(GraphCheckpoint).where(GraphCheckpoint.task_id.in_(task_public_ids)),
        )
    else:
        deleted["agent_messages"] = 0
        deleted["graph_checkpoints"] = 0
    if feedback_ids:
        execute_delete("resource_feedback", delete(Feedback).where(Feedback.id.in_(feedback_ids)))
    else:
        deleted["resource_feedback"] = 0
    if session_ids:
        execute_delete(
            "tutoring_messages",
            delete(TutoringMessage).where(TutoringMessage.session_id.in_(session_ids)),
        )
        execute_delete(
            "tutoring_sessions",
            delete(TutoringSession).where(TutoringSession.id.in_(session_ids)),
        )
    else:
        deleted["tutoring_messages"] = 0
        deleted["tutoring_sessions"] = 0
    execute_delete("learning_resources", delete(LearningResource))
    execute_delete("generation_tasks", delete(GenerationTask))
    db.flush()

    preserved_after = _row_counts(db, PRESERVED_MODELS)
    manifests_after = _manifest_hashes(root)
    if preserved_after != preserved_before:
        db.rollback()
        raise RuntimeError("preserved_table_counts_changed")
    if manifests_after != manifests_before:
        db.rollback()
        raise RuntimeError("candidate_manifest_changed")

    deleted["export_files"] = _delete_exports(export_dir)
    return {
        "active_task_count": active_count,
        "deleted": deleted,
        "preserved_counts": preserved_after,
        "candidate_manifest_hashes": manifests_after,
    }
