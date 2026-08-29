from __future__ import annotations

from datetime import UTC
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Feedback, GenerationTask, LearningPath, LearningResource
from app.services.learner_service import get_or_create_demo_learner
from app.services.profile_service import default_profile_for_learner


def _iso(value: Any) -> str | None:
    if not value:
        return None
    if getattr(value, "tzinfo", None) is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def serialize_resource(
    resource: LearningResource,
    generation_task: GenerationTask | None = None,
    knowledge_names: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    source_details = []
    source_detail_keys: set[str] = set()
    for stored_source in resource.sources_json or []:
        source = dict(stored_source)
        knowledge_id = str(source.get("knowledge_id") or "").strip()
        source["name"] = (
            str(source.get("name") or "").strip()
            or (knowledge_names or {}).get(knowledge_id)
            or "关联知识点"
        )
        # A resource can cite several chunks from one knowledge item. Learners only
        # need to see each knowledge point once, while the raw sources remain stored
        # for review and export.
        source_key = f"name:{source['name'].casefold()}" if source["name"] != "关联知识点" else f"id:{knowledge_id}"
        if source_key in source_detail_keys:
            continue
        source_detail_keys.add(source_key)
        source_details.append(source)
    return {
        "resource_id": resource.public_id,
        "resource_type": resource.resource_type,
        "title": resource.title,
        "content": resource.content_md,
        "difficulty": resource.difficulty,
        "learner_profile_type": resource.learner_profile_type,
        "review_status": resource.review_status,
        "sources": [item.get("knowledge_id") for item in (resource.sources_json or [])],
        "source_details": source_details,
        "version": resource.version,
        "generation_task_id": generation_task.public_id if generation_task else None,
        "generation_task_status": generation_task.status if generation_task else None,
        "generation_decision": generation_task.decision if generation_task else None,
        "generated_at": _iso(resource.created_at),
        "task_created_at": _iso(generation_task.created_at) if generation_task else None,
        "structured_content": resource.structured_content_json or None,
    }


def list_resources(db: Session) -> list[dict[str, Any]]:
    rows = list(
        db.execute(
            select(LearningResource, GenerationTask)
            .join(GenerationTask, GenerationTask.id == LearningResource.generation_task_id)
            .order_by(GenerationTask.created_at.desc(), LearningResource.id.asc())
            .limit(30)
        )
    )
    return [serialize_resource(resource, task) for resource, task in rows]


def submit_feedback(
    db: Session,
    *,
    resource_id: str,
    learner_id: str = "learner_001",
    feedback_type: str = "confusing",
    rating: int = 3,
    comment: str = "",
) -> dict[str, Any]:
    learner = get_or_create_demo_learner(db, learner_id)
    resource = db.scalar(select(LearningResource).where(LearningResource.public_id == resource_id))
    if resource is None:
        raise ValueError(f"Resource not found: {resource_id}")

    action = {
        "too_easy": "challenge_task",
        "too_hard": "remedial_explanation",
        "incorrect": "revision_required",
        "confusing": "remedial_explanation",
    }.get(feedback_type, "profile_update")
    feedback = Feedback(
        resource_id=resource.id,
        learner_id=learner.id,
        rating=rating,
        feedback_type=feedback_type,
        feedback_summary_json={
            "comment_summary": comment[:120],
            "resource_type": resource.resource_type,
        },
        triggered_action=action,
    )
    db.add(feedback)

    profile = default_profile_for_learner(db, learner)
    ability_profile = dict(profile.ability_profile_json or {})
    if feedback_type in {"too_hard", "confusing"}:
        ability_profile["practice"] = max(20, int(ability_profile.get("practice", 50)) - 3)
    elif feedback_type == "too_easy":
        ability_profile["problem_solving"] = min(
            95, int(ability_profile.get("problem_solving", 50)) + 3
        )
    ability_profile["last_feedback_action"] = action
    profile.ability_profile_json = ability_profile

    path = db.scalar(
        select(LearningPath)
        .where(LearningPath.learner_id == learner.id)
        .order_by(LearningPath.id.desc())
    )
    if path is not None:
        path.needs_refresh = True
        path.path_json = {
            **(path.path_json or {}),
            "last_feedback_action": action,
            "feedback_resource_id": resource.public_id,
        }

    db.commit()
    return {
        "resource_id": resource.public_id,
        "feedback_status": "accepted",
        "triggered_agent": "tutoring_agent",
        "triggered_action": action,
        "profile_id": profile.public_id,
        "learning_path_needs_refresh": True,
    }
