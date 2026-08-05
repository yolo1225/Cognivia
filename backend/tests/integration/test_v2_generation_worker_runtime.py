"""V2 worker persistence bridge for the unified graph runtime."""

from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.agents.contract_adapters import (
    analyze_profile_output_to_patch,
    finalize_task_output_to_patch,
    generate_resource_output_to_patch,
    prepare_task_output_to_patch,
    retrieve_knowledge_output_to_patch,
    review_resource_output_to_patch,
)
from app.agents.contract_examples import initial_generation_flow_example
from app.models import (
    AgentMessageRecord,
    AgentRun,
    Base,
    GenerationTask,
    GraphCheckpoint,
    Learner,
    LearnerProfile,
    LearningResource,
    ReviewReport,
)
from app.workers import generation_worker


class _Runtime:
    def close(self) -> None:
        pass


def _node_overrides():
    flow = initial_generation_flow_example()
    return {
        "prepare_task": lambda _state: prepare_task_output_to_patch(
            flow["prepare_task"]["output"]
        ),
        "interpret_feedback": lambda _state: {},
        "analyze_profile": lambda _state: analyze_profile_output_to_patch(
            flow["analyze_profile"]["output"]
        ),
        "retrieve_knowledge": lambda _state: retrieve_knowledge_output_to_patch(
            flow["retrieve_knowledge"]["output"]
        ),
        "generate_resource": lambda _state: generate_resource_output_to_patch(
            flow["generate_resource"]["input"], flow["generate_resource"]["output"]
        ),
        "review_resource": lambda _state: review_resource_output_to_patch(
            flow["review_resource"]["input"], flow["review_resource"]["output"]
        ),
        "human_review": lambda _state: {},
        "finalize_task": lambda _state: finalize_task_output_to_patch(
            flow["finalize_task"]["output"]
        ),
    }


def test_v2_worker_persists_checkpoint_runs_messages_resources_and_review(
    monkeypatch, tmp_path
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'v2-worker.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        learner = Learner(public_id="learner_worker", target_domain="ai_app_dev")
        db.add(learner)
        db.flush()
        profile = LearnerProfile(
            public_id="profile_worker",
            learner_id=learner.id,
            domain_code="ai_app_dev",
            ability_profile_json={
                "profile_type": "beginner",
                "theory": 45,
                "practice": 45,
                "problem_solving": 45,
                "breadth": 45,
                "learning_speed": 45,
            },
            weak_knowledge_json=[],
        )
        db.add(profile)
        db.flush()
        task = GenerationTask(
            public_id="task_v2_worker",
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
            status="pending",
            decision="pending",
            resource_types_json=["lecture"],
            learning_goal="生成 RAG 学习资源",
        )
        db.add(task)
        db.commit()

    monkeypatch.setattr(generation_worker, "SessionLocal", sessions)
    monkeypatch.setattr(generation_worker, "build_nodes", lambda _runtime: _node_overrides())
    monkeypatch.setattr(
        generation_worker.V2Runtime,
        "production",
        classmethod(lambda _cls: _Runtime()),
    )

    result = generation_worker.run_generation_task("task_v2_worker")

    assert result["status"] == "completed"
    assert result["decision"] == "completed"
    with sessions() as db:
        task = db.scalar(select(GenerationTask).where(GenerationTask.public_id == "task_v2_worker"))
        checkpoint = db.scalar(select(GraphCheckpoint).where(GraphCheckpoint.task_id == task.public_id))
        runs = list(db.scalars(select(AgentRun).where(AgentRun.generation_task_id == task.id)))
        messages = list(
            db.scalars(select(AgentMessageRecord).where(AgentMessageRecord.task_id == task.public_id))
        )
        resources = list(
            db.scalars(select(LearningResource).where(LearningResource.generation_task_id == task.id))
        )
        reports = list(db.scalars(select(ReviewReport).where(ReviewReport.task_id == task.id)))

    assert task.progress == 100
    assert checkpoint is not None and checkpoint.state_json["native_checkpoint"] is True
    assert len(runs) == 6 and all(run.status == "completed" for run in runs)
    assert len(messages) >= len(runs)
    assert len(resources) == 1 and resources[0].review_status == "passed"
    assert len(reports) == 1 and reports[0].review_rule_version == "review-v2"
