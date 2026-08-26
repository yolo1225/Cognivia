from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    GenerationTask,
    KnowledgeItem,
    KnowledgeRelation,
    LearnerProfile,
    LearningPath,
)
from app.services.learning_path_service import normalize_learning_path


def resolve_node_generation_basis(
    db: Session,
    *,
    path: LearningPath,
    path_node_id: str,
    profile: LearnerProfile,
    resource_types: list[str],
) -> dict[str, Any]:
    payload = normalize_learning_path(path)
    node = (payload.get("node_states") or {}).get(path_node_id)
    if (
        not isinstance(node, dict)
        or node.get("status") != "current"
        or payload.get("current_node_id") != path_node_id
    ):
        raise ValueError("path_node_changed")
    core_ids = [str(value) for value in node.get("knowledge_ids") or []]
    cores = list(db.scalars(
        select(KnowledgeItem).where(
            KnowledgeItem.public_id.in_(core_ids),
            KnowledgeItem.domain_code == path.domain_code,
        )
    ))
    core_by_public_id = {item.public_id: item for item in cores}
    cores = [core_by_public_id[value] for value in core_ids if value in core_by_public_id]
    if len(cores) != len(core_ids) or not cores:
        raise ValueError("path_node_knowledge_not_found")
    prerequisite_items = list(
        db.scalars(
            select(KnowledgeItem)
            .join(
                KnowledgeRelation,
                KnowledgeRelation.source_item_id == KnowledgeItem.id,
            )
            .where(
                KnowledgeRelation.target_item_id.in_([item.id for item in cores]),
                KnowledgeRelation.relation_type == "prerequisite",
                KnowledgeItem.domain_code == path.domain_code,
            )
            .order_by(KnowledgeItem.id)
        )
    )
    targets = {resource_type: list(core_ids) for resource_type in resource_types}
    return {
        "path_id": path.public_id,
        "path_node_id": path_node_id,
        "path_node_title": str(node.get("title") or cores[0].name),
        "path_node_order": int(node.get("path_order") or 1),
        "core_knowledge": [
            {"knowledge_id": item.public_id, "name": item.name} for item in cores
        ],
        "focus_knowledge_ids": list(node.get("focus_knowledge_ids") or []),
        "prerequisite_knowledge": [
            {"knowledge_id": item.public_id, "name": item.name}
            for item in prerequisite_items
        ],
        "profile_id": profile.public_id,
        "profile_version": profile.profile_version,
        "resource_knowledge_targets": targets,
    }


def bind_node_generation_targets(task: GenerationTask, basis: dict[str, Any]) -> None:
    task.resource_knowledge_targets_json = dict(
        basis.get("resource_knowledge_targets") or {}
    )


def generation_basis_for_task(
    db: Session, task: GenerationTask
) -> dict[str, Any] | None:
    if not task.learning_path_id or not task.path_node_id:
        return None
    path = db.get(LearningPath, task.learning_path_id)
    profile = db.get(LearnerProfile, task.profile_id)
    if path is None or profile is None:
        return None
    try:
        basis = resolve_node_generation_basis(
            db,
            path=path,
            path_node_id=task.path_node_id,
            profile=profile,
            resource_types=list(task.resource_types_json or []),
        )
    except ValueError:
        payload = normalize_learning_path(path)
        node = (payload.get("node_states") or {}).get(task.path_node_id) or {}
        targets = dict(task.resource_knowledge_targets_json or {})
        core_ids = next(iter(targets.values()), [])
        cores = list(db.scalars(
            select(KnowledgeItem).where(
                KnowledgeItem.public_id.in_(core_ids),
                KnowledgeItem.domain_code == path.domain_code,
            )
        )) if core_ids else []
        prerequisite_items = list(
            db.scalars(
                select(KnowledgeItem)
                .join(
                    KnowledgeRelation,
                    KnowledgeRelation.source_item_id == KnowledgeItem.id,
                )
                .where(
                    KnowledgeRelation.target_item_id.in_([item.id for item in cores]),
                    KnowledgeRelation.relation_type == "prerequisite",
                    KnowledgeItem.domain_code == path.domain_code,
                )
                .order_by(KnowledgeItem.id)
            )
        ) if cores else []
        return {
            "path_id": path.public_id,
            "path_node_id": task.path_node_id,
            "path_node_title": node.get("title"),
            "path_node_order": node.get("path_order"),
            "core_knowledge": [
                {"knowledge_id": item.public_id, "name": item.name} for item in cores
            ],
            "focus_knowledge_ids": list(node.get("focus_knowledge_ids") or []),
            "prerequisite_knowledge": [
                {"knowledge_id": item.public_id, "name": item.name}
                for item in prerequisite_items
            ],
            "profile_id": profile.public_id,
            "profile_version": profile.profile_version,
            "resource_knowledge_targets": targets,
        }
    basis["resource_knowledge_targets"] = dict(
        task.resource_knowledge_targets_json or basis["resource_knowledge_targets"]
    )
    return basis
