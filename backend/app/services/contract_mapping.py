"""Persistence-to-contract mappings shared by V3 service entry points."""

from __future__ import annotations

from app.agents.contracts import (
    AbilityScores,
    ProfileSnapshot,
    ProfileType,
    WeakKnowledge,
)
from app.models import LearnerProfile


def profile_snapshot(profile: LearnerProfile) -> ProfileSnapshot:
    raw = dict(profile.ability_profile_json or {})
    profile_type = raw.get("profile_type", ProfileType.BEGINNER.value)
    if profile_type not in {item.value for item in ProfileType}:
        profile_type = ProfileType.BEGINNER.value
    scores = raw.get("ability_scores", raw)

    def bounded_score(key: str, fallback: int = 50) -> int:
        try:
            value = int(scores.get(key, fallback))
        except (TypeError, ValueError):
            value = fallback
        return max(0, min(100, value))

    weak: list[WeakKnowledge] = []
    for item in profile.weak_knowledge_json or []:
        if not isinstance(item, dict) or not item.get("knowledge_id"):
            continue
        mastery = item.get("mastery_type") or item.get("weakness_type") or "partial_mastery"
        if mastery not in {"known", "partial_mastery", "confused", "unmastered", "unassessed"}:
            mastery = "partial_mastery"
        weak.append(
            WeakKnowledge(
                knowledge_id=str(item["knowledge_id"]),
                name=str(item.get("name") or item["knowledge_id"]),
                category=str(item.get("category") or "general"),
                weakness_level=max(1, min(5, int(item.get("weakness_level", 3)))),
                mastery_type=mastery,
                prerequisite_ids=list(
                    item.get("prerequisite_ids") or item.get("prerequisites") or []
                ),
                evidence_ids=list(item.get("evidence_ids") or []),
                reason=str(item.get("reason") or "历史画像识别的薄弱知识"),
            )
        )
    return ProfileSnapshot(
        profile_id=profile.public_id,
        profile_version=max(1, profile.profile_version),
        profile_type=ProfileType(profile_type),
        ability_scores=AbilityScores(
            theory=bounded_score("theory"),
            practice=bounded_score("practice"),
            problem_solving=bounded_score("problem_solving"),
            knowledge_breadth=bounded_score("knowledge_breadth", bounded_score("breadth")),
            learning_speed=bounded_score("learning_speed"),
        ),
        weak_knowledge=weak,
        blind_spot_ids=list(raw.get("blind_spot_ids") or []),
    )


def ability_profile_payload(snapshot: ProfileSnapshot) -> dict[str, object]:
    return {
        "profile_type": snapshot.profile_type.value,
        "theory": snapshot.ability_scores.theory,
        "practice": snapshot.ability_scores.practice,
        "problem_solving": snapshot.ability_scores.problem_solving,
        "breadth": snapshot.ability_scores.knowledge_breadth,
        "knowledge_breadth": snapshot.ability_scores.knowledge_breadth,
        "learning_speed": snapshot.ability_scores.learning_speed,
        "blind_spot_ids": list(snapshot.blind_spot_ids),
    }

