"""Explicit, opt-in V4 evaluation profile lookup for local live acceptance."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.contracts import AbilityScores, MasteryType, ProfileSnapshot, ProfileType, WeakKnowledge
from app.core.config import settings
from app.models import Learner, LearnerProfile, LearningPath
from app.services.profile_service import build_learning_path_from_snapshot


CASE_MARKER = re.compile(r"\[\[evaluation_case:(V4-EVAL-\d{3})\]\]")
PROJECT_ROOT = Path(__file__).resolve().parents[3]
CASES_PATH = PROJECT_ROOT / "data" / "evaluation_cases" / "v4" / "p0_cases.json"


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
                reason="V4 版本化评测画像中的待巩固知识点",
            )
            for knowledge_id in weak_ids
        ],
        blind_spot_ids=[str(item) for item in weak_ids],
    )


def contains_evaluation_marker(value: str) -> bool:
    return CASE_MARKER.search(str(value or "")) is not None


def prepare_evaluation_case(db: Session, case_id: str) -> dict[str, str]:
    """Materialize a server-owned, isolated evaluation identity and profile."""
    case = _cases().get(case_id)
    if case is None:
        raise ValueError("evaluation_case_not_found")
    snapshot = case.get("profile_snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("evaluation_case_profile_invalid")
    abilities = snapshot.get("ability_scores")
    weak_ids = snapshot.get("weak_knowledge")
    if not isinstance(abilities, dict) or not isinstance(weak_ids, list):
        raise ValueError("evaluation_case_profile_invalid")

    learner_public_id = f"evaluation_{case_id.lower().replace('-', '_')}"
    profile_public_id = f"evaluation_profile_{case_id.lower().replace('-', '_')}"
    path_public_id = f"evaluation_path_{case_id.lower().replace('-', '_')}"
    learner = db.scalar(select(Learner).where(Learner.public_id == learner_public_id))
    learner_values = {
        "background": "隔离评测身份",
        "education_level": "职业教育",
        "major": "人工智能应用开发",
        "target_domain": "ai_app_dev",
        "experience_years": 0,
        "learning_style": "mixed",
        "direction_tags_json": ["ai_application_engineering"],
        "is_evaluation": True,
    }
    if learner is None:
        learner = Learner(
            public_id=learner_public_id,
            **learner_values,
        )
        db.add(learner)
        db.flush()
    else:
        for key, value in learner_values.items():
            setattr(learner, key, value)

    ability_profile = {
        "profile_type": str(snapshot.get("profile_type") or "beginner"),
        "theory": int(abilities.get("theory", 0)),
        "practice": int(abilities.get("practice", 0)),
        "problem_solving": int(abilities.get("problem_solving", 0)),
        "breadth": int(abilities.get("knowledge_breadth", 0)),
        "learning_speed": int(abilities.get("learning_speed", 0)),
        "category_mastery": {},
        "blind_spot_ids": [str(item) for item in weak_ids],
    }
    weak_knowledge = [
        {
            "knowledge_id": str(knowledge_id),
            "name": str(knowledge_id),
            "category": "evaluation",
            "weakness_level": 3,
            "mastery_type": "partial_mastery",
            "prerequisite_ids": [],
            "evidence_ids": [f"evaluation:{case_id}:{knowledge_id}"],
            "reason": "版本化评测画像",
        }
        for knowledge_id in weak_ids
    ]
    profile = db.scalar(
        select(LearnerProfile).where(LearnerProfile.public_id == profile_public_id)
    )
    profile_values = {
        "learner_id": learner.id,
        "domain_code": "ai_app_dev",
        "ability_profile_json": ability_profile,
        "weak_knowledge_json": weak_knowledge,
        "profile_version": 1,
        "profile_source": "evaluation_fixture",
        "diagnosis_completed": True,
        "changed_dimensions_json": ["evaluation_fixture"],
        "evidence_refs_json": [],
        "confidence": 1.0,
        "context_snapshot_json": {
            "education_level": learner.education_level,
            "major": learner.major,
            "background": learner.background,
            "experience_years": learner.experience_years,
            "learning_style": learner.learning_style,
            "target_domain": learner.target_domain,
            "direction_tags": list(learner.direction_tags_json or []),
            "confirmed_at": "2026-08-20T00:00:00+00:00",
            "evaluation_case_id": case_id,
        },
        "decision_reason": "evaluation-case-v4",
    }
    if profile is None:
        profile = LearnerProfile(public_id=profile_public_id, **profile_values)
        db.add(profile)
        db.flush()
    else:
        for key, value in profile_values.items():
            setattr(profile, key, value)

    path = db.scalar(select(LearningPath).where(LearningPath.public_id == path_public_id))
    path_values = {
        "learner_id": learner.id,
        "profile_id": profile.id,
        "domain_code": "ai_app_dev",
        "status": "active",
        "path_json": build_learning_path_from_snapshot(ability_profile, weak_knowledge),
        "needs_refresh": False,
    }
    if path is None:
        db.add(LearningPath(public_id=path_public_id, **path_values))
    else:
        for key, value in path_values.items():
            setattr(path, key, value)
    db.flush()
    return {
        "case_id": case_id,
        "learner_id": learner.public_id,
        "profile_id": profile.public_id,
        "domain_code": "ai_app_dev",
    }
