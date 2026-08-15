"""V3 worker persistence bridge for the unified graph runtime."""

from __future__ import annotations

import pytest
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
from app.agents.review_agent import ReviewBatchCache
from app.workers import generation_worker


class _Runtime:
    def __init__(self) -> None:
        self.review_batch_cache = ReviewBatchCache()

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
        "finalize_task": lambda _state: finalize_task_output_to_patch(
            flow["finalize_task"]["output"]
        ),
    }


def test_v3_worker_persists_checkpoint_runs_messages_resources_and_review(
    monkeypatch, tmp_path
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'v3-worker.db'}")
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
            public_id="task_v3_worker",
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
            status="pending",
            decision="pending",
            resource_types_json=["lecture", "practice_guide", "graded_quiz"],
            learning_goal="生成 RAG 学习资源",
        )
        db.add(task)
        db.commit()

    monkeypatch.setattr(generation_worker, "SessionLocal", sessions)
    monkeypatch.setattr(generation_worker, "build_nodes", lambda _runtime: _node_overrides())
    monkeypatch.setattr(
        generation_worker.AgentRuntime,
        "production",
        classmethod(lambda _cls, **_kwargs: _Runtime()),
    )

    result = generation_worker.run_generation_task("task_v3_worker")

    assert result["status"] == "completed", result
    assert result["decision"] == "completed"
    with sessions() as db:
        task = db.scalar(select(GenerationTask).where(GenerationTask.public_id == "task_v3_worker"))
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
    assert len(resources) == 3 and all(item.review_status == "passed" for item in resources)
    assert len(reports) == 3 and all(
        item.review_rule_version == "atomic-claims-20260814" for item in reports
    )

    repeated = generation_worker.run_generation_task("task_v3_worker")
    assert repeated["status"] == "completed"
    with sessions() as db:
        task = db.scalar(
            select(GenerationTask).where(GenerationTask.public_id == "task_v3_worker")
        )
        assert len(list(db.scalars(
            select(LearningResource).where(LearningResource.generation_task_id == task.id)
        ))) == 3
        assert len(list(db.scalars(
            select(ReviewReport).where(ReviewReport.task_id == task.id)
        ))) == 3
        assert len(list(db.scalars(
            select(AgentRun).where(AgentRun.generation_task_id == task.id)
        ))) == 6


def test_failed_review_resumes_from_checkpoint_without_regeneration(
    monkeypatch, tmp_path
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'v3-worker-resume.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        learner = Learner(public_id="learner_resume", target_domain="ai_app_dev")
        db.add(learner)
        db.flush()
        profile = LearnerProfile(
            public_id="profile_resume",
            learner_id=learner.id,
            domain_code="ai_app_dev",
            ability_profile_json={"profile_type": "beginner"},
            weak_knowledge_json=[],
        )
        db.add(profile)
        db.flush()
        db.add(
            GenerationTask(
                public_id="task_v3_resume",
                learner_id=learner.id,
                profile_id=profile.id,
                domain_code="ai_app_dev",
                status="pending",
                decision="pending",
                resource_types_json=["lecture", "practice_guide", "graded_quiz"],
                learning_goal="验证审核节点恢复",
            )
        )
        db.commit()

    nodes = _node_overrides()
    original_generate = nodes["generate_resource"]
    original_review = nodes["review_resource"]
    calls = {"generate": 0, "review": 0}

    def generate(state):
        calls["generate"] += 1
        return original_generate(state)

    def review(state):
        calls["review"] += 1
        if calls["review"] == 1:
            raise RuntimeError("review_model_call_failed")
        return original_review(state)

    nodes["generate_resource"] = generate
    nodes["review_resource"] = review
    monkeypatch.setattr(generation_worker, "SessionLocal", sessions)
    monkeypatch.setattr(generation_worker, "build_nodes", lambda _runtime: nodes)
    monkeypatch.setattr(
        generation_worker.AgentRuntime,
        "production",
        classmethod(lambda _cls, **_kwargs: _Runtime()),
    )

    failed = generation_worker.run_generation_task("task_v3_resume")
    resumed = generation_worker.run_generation_task("task_v3_resume")

    assert failed["status"] == "failed"
    assert resumed["status"] == "completed", resumed
    assert calls == {"generate": 1, "review": 2}
    with sessions() as db:
        task = db.scalar(
            select(GenerationTask).where(GenerationTask.public_id == "task_v3_resume")
        )
        runs = list(
            db.scalars(
                select(AgentRun)
                .where(AgentRun.generation_task_id == task.id)
                .order_by(AgentRun.id)
            )
        )
        assert [run.agent_name for run in runs].count("content_generation_agent") == 1
        assert [run.status for run in runs if run.agent_name == "review_validation_agent"] == [
            "failed",
            "completed",
        ]


def test_failed_review_run_preserves_and_reloads_completed_batch_cache(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'review-batch-cache.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    flow = initial_generation_flow_example()
    review_input = flow["review_resource"]["input"]
    primary_review = flow["review_resource"]["output"].reports[0].primary_review

    with sessions() as db:
        learner = Learner(public_id="learner_batch_cache", target_domain="ai_app_dev")
        db.add(learner)
        db.flush()
        profile = LearnerProfile(
            public_id="profile_batch_cache",
            learner_id=learner.id,
            domain_code="ai_app_dev",
            ability_profile_json={"profile_type": "beginner"},
            weak_knowledge_json=[],
        )
        db.add(profile)
        db.flush()
        task = GenerationTask(
            public_id="task_batch_cache",
            learner_id=learner.id,
            profile_id=profile.id,
            status="running",
            decision="pending",
            resource_types_json=["lecture"],
        )
        db.add(task)
        db.commit()

        runtime = _Runtime()

        def fail_after_one_batch(_state):
            runtime.review_batch_cache.put(
                resource_type=review_input.resources[0].resource_type,
                claim_set_hash="claim-set-hash",
                evidence_packet_hash="evidence-packet-hash",
                role="primary_review_model",
                requested_model="primary-model",
                actual_model="primary-model",
                recheck=False,
                batch_id="initial-batch-1",
                review=primary_review,
            )
            runtime.review_batch_cache.persist()
            raise RuntimeError("review_model_call_failed")

        wrapped = generation_worker._observable_node(
            db,
            task,
            profile,
            "review_resource",
            fail_after_one_batch,
            runtime,
        )
        with pytest.raises(RuntimeError, match="review_model_call_failed"):
            wrapped({})

        failed_run = db.scalar(
            select(AgentRun)
            .where(AgentRun.generation_task_id == task.id)
            .where(AgentRun.agent_name == "review_validation_agent")
        )
        snapshot = failed_run.output_summary_json["review_batch_cache"]
        reloaded = generation_worker._load_review_batch_cache(db, task)

    assert failed_run.status == "failed"
    assert snapshot["entry_count"] == 1
    assert reloaded.snapshot()["entry_count"] == 1
