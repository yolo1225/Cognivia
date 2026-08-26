from __future__ import annotations

from typing import Any

from app.agents.contracts import (
    AnalyzeProfileOutput,
    EvidenceRef,
    EvidenceType,
    MasteryType,
    WeakKnowledge,
)
from app.models import KnowledgeItem, LearnerProfile
from app.services.contract_mapping import profile_snapshot
from app.services.knowledge_extraction_service import normalize_knowledge_name


def _weak_state(items: list[WeakKnowledge], knowledge_id: str) -> WeakKnowledge | None:
    return next((item for item in items if item.knowledge_id == knowledge_id), None)


def apply_confirmed_knowledge_semantics(
    *,
    original: LearnerProfile,
    analysis: AnalyzeProfileOutput,
    hypothesis_type: str,
    knowledge: KnowledgeItem,
    evidence_id: str,
    path_node_id: str,
) -> tuple[AnalyzeProfileOutput, dict[str, Any]]:
    before = profile_snapshot(original)
    proposed = analysis.profile
    weak_items = list(proposed.weak_knowledge)
    blind_spots = list(proposed.blind_spot_ids)
    before_weak = _weak_state(before.weak_knowledge, knowledge.public_id)

    if hypothesis_type == "mastery_up":
        weak_items = [item for item in weak_items if item.knowledge_id != knowledge.public_id]
        blind_spots = [item for item in blind_spots if item != knowledge.public_id]
        next_state = "known"
        next_level = None
    else:
        proposed_weak = _weak_state(weak_items, knowledge.public_id)
        source = proposed_weak or before_weak
        replacement = WeakKnowledge(
            knowledge_id=knowledge.public_id,
            name=knowledge.name,
            category=knowledge.category,
            weakness_level=max(4, source.weakness_level if source else 4),
            mastery_type=MasteryType.UNMASTERED,
            prerequisite_ids=list(source.prerequisite_ids if source else []),
            evidence_ids=list(
                dict.fromkeys([*(source.evidence_ids if source else []), evidence_id])
            )[-20:],
            reason="导学交互与正式微验证共同确认需要补强",
        )
        weak_items = [
            item for item in weak_items if item.knowledge_id != knowledge.public_id
        ]
        weak_items.append(replacement)
        if knowledge.public_id not in blind_spots:
            blind_spots.append(knowledge.public_id)
        next_state = replacement.mastery_type.value
        next_level = replacement.weakness_level

    semantic_changed = (
        [item.model_dump(mode="json") for item in weak_items]
        != [item.model_dump(mode="json") for item in before.weak_knowledge]
        or blind_spots != before.blind_spot_ids
    )
    update_required = bool(analysis.profile_update_required or semantic_changed)
    next_snapshot = proposed.model_copy(
        update={
            "profile_id": original.public_id,
            "profile_version": (
                max(original.profile_version + 1, proposed.profile_version)
                if update_required
                else original.profile_version
            ),
            "weak_knowledge": weak_items,
            "blind_spot_ids": blind_spots,
        }
    )
    changed_dimensions = list(analysis.changed_dimensions)
    if semantic_changed:
        for dimension in ("weak_knowledge", "blind_spot_ids"):
            if dimension not in changed_dimensions:
                changed_dimensions.append(dimension)

    evidence_refs = list(analysis.evidence_refs)
    if semantic_changed and not any(item.evidence_id == evidence_id for item in evidence_refs):
        evidence_refs.append(
            EvidenceRef(
                evidence_id=evidence_id,
                evidence_type=EvidenceType.SCORED_QUIZ,
                summary="导学交互假设经当前知识点微验证确认",
                knowledge_id=knowledge.public_id,
                confidence=0.9,
                confirmed=True,
            )
        )
    affected_scope = analysis.affected_scope.model_copy(
        update={
            "knowledge_ids": list(
                dict.fromkeys([*analysis.affected_scope.knowledge_ids, knowledge.public_id])
            ),
            "path_node_ids": list(
                dict.fromkeys([*analysis.affected_scope.path_node_ids, path_node_id])
            ),
        }
    )

    normalized = AnalyzeProfileOutput.model_validate(analysis.model_copy(
        update={
            "profile": next_snapshot,
            "profile_update_required": update_required,
            "changed_dimensions": changed_dimensions if update_required else [],
            "evidence_refs": evidence_refs,
            "affected_scope": affected_scope,
        }
    ).model_dump(mode="python"))
    before_scores = before.ability_scores.model_dump(mode="json")
    after_scores = next_snapshot.ability_scores.model_dump(mode="json")
    score_changes = {
        key: {"before": before_scores[key], "after": after_scores[key]}
        for key in before_scores
        if before_scores[key] != after_scores[key]
    }
    return normalized, {
        "knowledge_id": knowledge.public_id,
        "knowledge_name": normalize_knowledge_name(knowledge.name),
        "before_state": before_weak.mastery_type.value if before_weak else "not_weak",
        "after_state": next_state,
        "before_weakness_level": before_weak.weakness_level if before_weak else None,
        "after_weakness_level": next_level,
        "removed_from_weak_knowledge": hypothesis_type == "mastery_up" and before_weak is not None,
        "removed_from_blind_spots": (
            hypothesis_type == "mastery_up"
            and knowledge.public_id in before.blind_spot_ids
        ),
        "evidence_ids": [evidence_id],
        "path_node_id": path_node_id,
        "profile_changed": update_required,
        "ability_score_changes": score_changes,
        "ability_summary": "高层能力保持不变" if not score_changes else "高层能力已更新",
    }
