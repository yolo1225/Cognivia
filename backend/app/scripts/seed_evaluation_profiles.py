"""Seed three idempotent, diagnosis-ready learner profiles for live evaluation.

This script creates business fixtures only. It deliberately does not create
authentication users; the live evaluation authenticates as the configured
administrator and supplies the learner public ID explicitly.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import Learner, LearnerProfile, LearningPath
from app.services.profile_service import build_learning_path_from_snapshot


EVALUATION_PROFILE_VERSION = "evaluation-profile-v6-20260818"
CONFIRMED_AT = "2026-08-18T00:00:00+00:00"

EVALUATION_PROFILES: tuple[dict[str, Any], ...] = (
    {
        "learner_id": "learner_001",
        "profile_id": "evaluation_profile_beginner_v6",
        "path_id": "evaluation_path_beginner_v6",
        "profile_type": "beginner",
        "score": 45,
        "education_level": "本科在读",
        "major": "计算机科学与技术",
        "experience_years": 0,
        "learning_style": "guided",
        "direction_tags": ["python_api", "prompt_engineering"],
        "weak_knowledge_ids": ["ai_app_dev_overview", "python_api_basics"],
    },
    {
        "learner_id": "learner_003",
        "profile_id": "evaluation_profile_intermediate_v6",
        "path_id": "evaluation_path_intermediate_v6",
        "profile_type": "intermediate",
        "score": 60,
        "education_level": "本科",
        "major": "软件工程",
        "experience_years": 1,
        "learning_style": "mixed",
        "direction_tags": ["rag_knowledge_base", "api_engineering"],
        "weak_knowledge_ids": ["http_rest_basics", "git_collaboration"],
    },
    {
        "learner_id": "learner_002",
        "profile_id": "evaluation_profile_advanced_v6",
        "path_id": "evaluation_path_advanced_v6",
        "profile_type": "advanced",
        "score": 80,
        "education_level": "硕士",
        "major": "人工智能",
        "experience_years": 3,
        "learning_style": "practice_oriented",
        "direction_tags": ["agent_orchestration", "quality_evaluation"],
        "weak_knowledge_ids": ["prompt_basic", "prompt_context_design"],
    },
)


def _weak_knowledge(knowledge_ids: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "knowledge_id": knowledge_id,
            "name": knowledge_id,
            "category": "evaluation",
            "weakness_level": 3,
            "mastery_type": "partial_mastery",
            "prerequisite_ids": [],
            "evidence_ids": [f"evaluation:{knowledge_id}"],
            "reason": "V6 评测画像中的待巩固知识点",
        }
        for knowledge_id in knowledge_ids
    ]


def _ability_profile(profile_type: str, score: int) -> dict[str, Any]:
    return {
        "profile_type": profile_type,
        "theory": score,
        "practice": score,
        "problem_solving": score,
        "breadth": score,
        "learning_speed": score,
        "category_mastery": {},
        "blind_spot_ids": [],
    }


def seed_evaluation_profiles(db: Session) -> dict[str, int]:
    learner_count = 0
    profile_count = 0
    path_count = 0
    for fixture in EVALUATION_PROFILES:
        learner = db.scalar(
            select(Learner).where(Learner.public_id == fixture["learner_id"])
        )
        learner_values = {
            "background": (
                f"{fixture['education_level']}｜{fixture['major']}｜"
                f"{fixture['experience_years']}年相关经验"
            ),
            "education_level": fixture["education_level"],
            "major": fixture["major"],
            "target_domain": "ai_app_dev",
            "experience_years": fixture["experience_years"],
            "learning_style": fixture["learning_style"],
            "direction_tags_json": fixture["direction_tags"],
        }
        if learner is None:
            learner = Learner(public_id=fixture["learner_id"], **learner_values)
            db.add(learner)
            db.flush()
        else:
            for key, value in learner_values.items():
                setattr(learner, key, value)
        learner_count += 1

        ability_profile = _ability_profile(fixture["profile_type"], fixture["score"])
        weak_knowledge = _weak_knowledge(fixture["weak_knowledge_ids"])
        context_snapshot = {
            "education_level": fixture["education_level"],
            "major": fixture["major"],
            "direction_tags": fixture["direction_tags"],
            "background": learner_values["background"],
            "experience_years": fixture["experience_years"],
            "learning_style": fixture["learning_style"],
            "confirmed_at": CONFIRMED_AT,
            "fixture_version": EVALUATION_PROFILE_VERSION,
        }
        profile = db.scalar(
            select(LearnerProfile).where(
                LearnerProfile.public_id == fixture["profile_id"]
            )
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
            "evidence_refs_json": [
                {
                    "evidence_id": f"evaluation:{fixture['learner_id']}",
                    "evidence_type": "diagnostic_result",
                    "summary": "脱敏评测画像基线",
                    "confidence": 1.0,
                    "confirmed": True,
                }
            ],
            "confidence": 1.0,
            "context_snapshot_json": context_snapshot,
            "decision_reason": EVALUATION_PROFILE_VERSION,
        }
        if profile is None:
            profile = LearnerProfile(public_id=fixture["profile_id"], **profile_values)
            db.add(profile)
            db.flush()
        else:
            for key, value in profile_values.items():
                setattr(profile, key, value)
        profile_count += 1

        path_payload = build_learning_path_from_snapshot(ability_profile, weak_knowledge)
        path = db.scalar(
            select(LearningPath).where(LearningPath.public_id == fixture["path_id"])
        )
        path_values = {
            "learner_id": learner.id,
            "profile_id": profile.id,
            "domain_code": "ai_app_dev",
            "status": "active",
            "path_json": path_payload,
            "needs_refresh": False,
        }
        if path is None:
            db.add(LearningPath(public_id=fixture["path_id"], **path_values))
        else:
            for key, value in path_values.items():
                setattr(path, key, value)
        path_count += 1

    return {
        "learners": learner_count,
        "profiles": profile_count,
        "learning_paths": path_count,
    }


def run_seed() -> dict[str, int]:
    with SessionLocal() as db:
        summary = seed_evaluation_profiles(db)
        db.commit()
        return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed three diagnosis-ready learner profiles for live evaluation."
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()
    summary = run_seed()
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            "Evaluation profile seed complete: "
            f"{summary['learners']} learners, {summary['profiles']} profiles, "
            f"{summary['learning_paths']} learning paths."
        )


if __name__ == "__main__":
    main()
