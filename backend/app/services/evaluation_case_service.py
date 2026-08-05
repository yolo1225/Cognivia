"""Explicit, opt-in V2 evaluation profile lookup for local live acceptance."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from app.agents.contracts import AbilityScores, MasteryType, ProfileSnapshot, ProfileType, WeakKnowledge
from app.core.config import settings


CASE_MARKER = re.compile(r"\[\[evaluation_case:(V2-EVAL-\d{3})\]\]")
PROJECT_ROOT = Path(__file__).resolve().parents[3]
CASES_PATH = PROJECT_ROOT / "data" / "evaluation_cases" / "v2" / "p0_cases.json"


@lru_cache
def _cases() -> dict[str, dict[str, object]]:
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    return {str(item["case_id"]): item for item in payload["cases"]}


def evaluation_profile_override(learning_goal: str) -> ProfileSnapshot | None:
    """Return a non-persistent evaluation profile only when locally enabled."""
    if not settings.enable_evaluation_overrides:
        return None
    match = CASE_MARKER.search(learning_goal)
    if match is None:
        return None
    case = _cases().get(match.group(1))
    if case is None:
        raise ValueError("evaluation_case_not_found")
    snapshot = case["profile_snapshot"]
    if not isinstance(snapshot, dict):
        raise ValueError("evaluation_case_profile_invalid")
    abilities = snapshot["ability_scores"]
    if not isinstance(abilities, dict):
        raise ValueError("evaluation_case_ability_invalid")
    weak_ids = snapshot.get("weak_knowledge", [])
    if not isinstance(weak_ids, list):
        raise ValueError("evaluation_case_weak_knowledge_invalid")
    return ProfileSnapshot(
        profile_id=str(snapshot["profile_id"]),
        profile_version=1,
        profile_type=ProfileType(str(snapshot["profile_type"])),
        ability_scores=AbilityScores.model_validate(abilities),
        weak_knowledge=[
            WeakKnowledge(
                knowledge_id=str(knowledge_id),
                name=str(knowledge_id),
                category="evaluation",
                weakness_level=3,
                mastery_type=MasteryType.PARTIAL_MASTERY,
                reason="V2 版本化评测画像中的待巩固知识点",
            )
            for knowledge_id in weak_ids
        ],
        blind_spot_ids=[str(item) for item in weak_ids],
    )
