"""Deterministic current-resource matching after a confirmed profile revision."""

from __future__ import annotations

from typing import Any

from app.models import GenerationTask, LearningPath, LearningResource
from app.services.node_mastery_service import affected_resource_types, node_core_knowledge_ids


DECISION_TYPES = {
    "remedial",
    "challenge",
    "no_generation",
    "future_path_reprioritize",
    "next_stage",
}


def decide_resource_matching(
    *,
    proposal_id: str,
    path: LearningPath,
    node_gate: dict[str, Any] | None,
    package_task: GenerationTask | None,
    source_resource: LearningResource | None,
    affected_knowledge_ids: list[str],
    hypothesis_type: str,
    node_advanced: bool = False,
) -> dict[str, Any]:
    """Return one persisted decision, independent from formal route gates."""
    payload = path.path_json or {}
    node_id = payload.get("current_node_id")
    current_node = ((payload.get("node_states") or {}).get(node_id) or {})
    current_ids = set(node_core_knowledge_ids(current_node))
    affected = list(dict.fromkeys(str(value) for value in affected_knowledge_ids if value))
    current_affected = [value for value in affected if value in current_ids]
    source_type = source_resource.resource_type if source_resource is not None else "lecture"
    base = {
        "proposal_id": proposal_id,
        "path_id": path.public_id,
        "path_node_id": node_id,
        "affected_knowledge_ids": affected,
        "node_gate": dict(node_gate or {}),
        "current_resource_handling": "keep_current",
        "requires_confirmation": False,
        # Kept for old clients while decision_type becomes authoritative.
        "mode": "remedial",
        "resource_types": [],
    }
    if node_advanced:
        return {
            **base,
            "decision_type": "next_stage",
            "mode": "next_node",
            "resource_types": ["lecture", "practice_guide", "graded_quiz"],
            "requires_confirmation": True,
            "current_resource_handling": "archive_for_review",
            "reason": "当前节点正式门禁已满足，路线已进入下一阶段。",
        }
    if current_affected and hypothesis_type == "support_down":
        types = (
            affected_resource_types(
                package_task=package_task,
                affected_knowledge_ids=current_affected,
                fallback_resource_type=source_type,
            )
            if package_task is not None
            else [source_type]
        )
        return {
            **base,
            "decision_type": "remedial",
            "resource_types": types,
            "requires_confirmation": True,
            "current_resource_handling": "keep_for_review",
            "reason": "当前节点的已确认能力变化显示需要补充针对性讲解或练习。",
        }
    if current_affected and hypothesis_type == "mastery_up":
        return {
            **base,
            "decision_type": "challenge",
            "resource_types": ["graded_quiz"],
            "requires_confirmation": True,
            "current_resource_handling": "keep_current",
            "reason": "当前节点能力提升，但正式路线门禁尚未全部满足，可选择挑战练习。",
        }
    if affected:
        return {
            **base,
            "decision_type": "future_path_reprioritize",
            "current_resource_handling": "keep_current",
            "reason": "本次变化只影响后续未解锁知识的优先级，当前学习资源保持不变。",
        }
    return {
        **base,
        "decision_type": "no_generation",
        "current_resource_handling": "keep_current",
        "reason": "画像变化不影响当前节点资源匹配，继续使用现有学习包。",
    }
