from __future__ import annotations

import argparse
import json
from typing import Any

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import AgentRun, GenerationTask, Learner, LearnerProfile, LearningResource
from app.services.profile_service import public_id
from app.workers.generation_worker import run_generation_task


CASES = (
    ("learner_001", ("lecture",), "核心概念讲解与常见误区"),
    ("learner_001", ("graded_quiz",), "基础知识诊断与巩固"),
    ("learner_001", ("practice_guide",), "基础实践与结果验证"),
    ("learner_003", ("lecture", "graded_quiz"), "概念复习与分层测验"),
    ("learner_003", ("practice_guide",), "API 调用实践与错误边界"),
    (
        "learner_admin_initial",
        ("lecture", "practice_guide", "graded_quiz"),
        "人工智能应用开发综合训练",
    ),
)


def _latest_profile(db: Any, learner_id: int) -> LearnerProfile | None:
    return db.scalar(
        select(LearnerProfile)
        .where(LearnerProfile.learner_id == learner_id)
        .where(LearnerProfile.diagnosis_completed.is_(True))
        .order_by(LearnerProfile.profile_version.desc(), LearnerProfile.id.desc())
    )


def _create_task(learner_public_id: str, resource_types: tuple[str, ...], goal: str) -> str:
    with SessionLocal() as db:
        learner = db.scalar(select(Learner).where(Learner.public_id == learner_public_id))
        if learner is None:
            raise RuntimeError(f"acceptance_learner_missing:{learner_public_id}")
        profile = _latest_profile(db, learner.id)
        if profile is None:
            raise RuntimeError(f"acceptance_profile_missing:{learner_public_id}")
        task = GenerationTask(
            public_id=public_id("task"),
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
            status="pending",
            resource_types_json=list(resource_types),
            revision_count=0,
            decision="pending",
            trigger_type="initial_generation",
            execution_mode="auto",
            learning_goal=goal,
            progress=0,
        )
        db.add(task)
        db.commit()
        return task.public_id


def _task_summary(task_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        task = db.scalar(select(GenerationTask).where(GenerationTask.public_id == task_id))
        if task is None:
            raise RuntimeError(f"acceptance_task_missing:{task_id}")
        resources = list(
            db.scalars(
                select(LearningResource)
                .where(LearningResource.generation_task_id == task.id)
                .order_by(LearningResource.id)
            )
        )
        review_run = db.scalar(
            select(AgentRun)
            .where(AgentRun.generation_task_id == task.id)
            .where(AgentRun.agent_name == "review_validation_agent")
            .where(AgentRun.status == "completed")
            .order_by(AgentRun.id.desc())
        )
        review_summary = (review_run.output_summary_json or {}) if review_run else {}
        reviews = review_summary.get("resource_reviews", [])
        return {
            "task_id": task.public_id,
            "status": task.status,
            "decision": task.decision,
            "revision_count": task.revision_count,
            "resources": [
                {
                    "resource_type": item.resource_type,
                    "review_status": item.review_status,
                }
                for item in resources
            ],
            "review_observability": [
                {
                    "resource_type": item.get("resource_type"),
                    "decision": item.get("decision"),
                    "claim_counts": item.get("claim_counts", {}),
                    "observability": item.get("observability", {}),
                }
                for item in reviews
            ],
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    results: list[dict[str, Any]] = []
    for learner_id, resource_types, goal in CASES:
        task_id = _create_task(learner_id, resource_types, goal)
        run_generation_task(task_id)
        summary = _task_summary(task_id)
        results.append(summary)
        print(json.dumps(summary, ensure_ascii=False), flush=True)

    completed = sum(item["status"] == "completed" for item in results)
    failed = sum(item["status"] == "failed" for item in results)
    report = {
        "case_count": len(results),
        "completed": completed,
        "failed": failed,
        "acceptance_target_met": completed >= 5 and failed == 0,
        "tasks": results,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
