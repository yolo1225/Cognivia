from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.contracts import QUALITY_RULE_VERSION
from app.models import (
    Feedback,
    GenerationTask,
    Learner,
    LearnerProfile,
    LearningPackageResource,
    LearningResource,
)
from app.services.profile_service import public_id


V6_FULL_REGENERATION_REQUIRED = "V6_FULL_REGENERATION_REQUIRED"


class FeedbackSourceCompatibilityError(ValueError):
    def __init__(self) -> None:
        super().__init__(V6_FULL_REGENERATION_REQUIRED)


RECOMMENDED_ACTIONS = {
    "too_hard": "explain",
    "too_easy": "challenge",
    "confusing": "explain",
    "incorrect": "review",
    "has_error": "review",
    "helpful": "no_change",
}


def decide_feedback_action(feedback_type: str) -> str:
    return RECOMMENDED_ACTIONS.get(feedback_type, "no_change")


def require_v6_feedback_source(
    db: Session,
    *,
    learner: Learner,
    resource: LearningResource,
) -> GenerationTask:
    source_package = db.scalar(
        select(GenerationTask)
        .join(
            LearningPackageResource,
            LearningPackageResource.package_task_id == GenerationTask.id,
        )
        .where(
            GenerationTask.learner_id == learner.id,
            GenerationTask.is_current_package.is_(True),
            LearningPackageResource.resource_id == resource.id,
        )
        .order_by(GenerationTask.id.desc())
    )
    source_task = source_package or db.get(GenerationTask, resource.generation_task_id)
    if (
        source_task is None
        or (source_task.package_quality_json or {}).get("quality_rule_version")
        != QUALITY_RULE_VERSION
    ):
        raise FeedbackSourceCompatibilityError
    return source_task


def create_feedback_task(
    db: Session,
    *,
    learner: Learner,
    profile: LearnerProfile,
    resource: LearningResource,
    feedback: Feedback,
    resource_types: list[str] | None = None,
) -> GenerationTask:
    existing = db.scalar(
        select(GenerationTask)
        .where(
            GenerationTask.source_feedback_id == feedback.id,
            GenerationTask.event_type == "resource_feedback",
        )
        .order_by(GenerationTask.id.desc())
    )
    if existing is not None:
        return existing
    source_task = require_v6_feedback_source(
        db,
        learner=learner,
        resource=resource,
    )
    resource_task = db.get(GenerationTask, resource.generation_task_id)
    if (
        resource_task is None
        or resource_task.domain_code != source_task.domain_code
        or profile.domain_code != source_task.domain_code
        or learner.target_domain != source_task.domain_code
    ):
        raise ValueError("feedback_domain_mismatch")
    inherited_goal = source_task.learning_goal.strip()
    feedback_goal = f"根据资源 {resource.public_id} 的反馈执行辅导或复核"
    learning_goal = f"{inherited_goal}\n{feedback_goal}" if inherited_goal else feedback_goal
    task = GenerationTask(
        public_id=public_id("task"),
        learner_id=learner.id,
        profile_id=profile.id,
        learning_path_id=source_task.learning_path_id,
        path_node_id=source_task.path_node_id,
        domain_code=source_task.domain_code,
        status="pending",
        resource_types_json=resource_types or [resource.resource_type],
        revision_count=0,
        decision="pending",
        trigger_type="resource_feedback",
        execution_mode="auto",
        learning_goal=learning_goal[:512],
        source_resource_id=resource.id,
        source_feedback_id=feedback.id,
        source_task_id=source_task.id,
        event_type="resource_feedback",
        progress=0,
    )
    db.add(task)
    db.flush()
    return task


def record_quick_feedback(
    db: Session,
    *,
    learner: Learner,
    profile: LearnerProfile,
    resource: LearningResource,
    feedback_type: str,
    rating: int | None,
    comment: str,
) -> tuple[Feedback, GenerationTask | None]:
    action = decide_feedback_action(feedback_type)
    feedback = Feedback(
        resource_id=resource.id,
        learner_id=learner.id,
        rating=rating,
        feedback_type="text_selection"
        if feedback_type in {"incorrect", "has_error"}
        else "quick_tag",
        feedback_summary_json={"tag": feedback_type, "comment_summary": comment[:120]},
        triggered_action=action,
        comment=comment[:2000],
        feedback_intent="incorrect" if feedback_type == "has_error" else feedback_type,
        recommended_action=action,
        profile_update_required=False,
        profile_change_evidence_json=[{"type": "quick_feedback", "value": feedback_type}],
        decision_confidence=0.35,
        decision_reason="快捷标签或评分仅作为辅助证据，不直接修改能力画像",
    )
    db.add(feedback)
    db.flush()
    task = None
    if action == "review":
        task = create_feedback_task(
            db,
            learner=learner,
            profile=profile,
            resource=resource,
            feedback=feedback,
            resource_types=[resource.resource_type],
        )
    return feedback, task


def serialize_feedback_decision(feedback: Feedback, task: GenerationTask | None) -> dict[str, Any]:
    return {
        "feedback_id": str(feedback.id),
        "resource_id": str(feedback.resource_id),
        "feedback_status": "accepted",
        "feedback_intent": feedback.feedback_intent,
        "recommended_action": feedback.recommended_action,
        "profile_update_required": feedback.profile_update_required,
        "decision_reason": feedback.decision_reason,
        "affected_knowledge_ids": feedback.affected_knowledge_ids_json or [],
        "affected_path_node_ids": feedback.affected_path_node_ids_json or [],
        "affected_resource_ids": feedback.affected_resource_ids_json or [],
        "task_id": task.public_id if task else None,
    }
