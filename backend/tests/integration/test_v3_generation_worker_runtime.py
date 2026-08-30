"""V3 worker persistence bridge for the unified graph runtime."""

from __future__ import annotations

import pytest
from types import SimpleNamespace
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
from app.agents.contracts import (
    CONTRACT_VERSION,
    AbilityScores,
    FinalizeTaskOutput,
    TaskDecision,
)
from app.agents.generation_agent import GenerationError
from app.agents.profile_analysis_config import AI_APP_DEV_PROFILE_V2
from app.models import (
    AgentMessageRecord,
    AgentRun,
    Base,
    GenerationTask,
    GraphCheckpoint,
    Learner,
    LearnerProfile,
    LearningPath,
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


@pytest.mark.parametrize(("ability_score", "expected_difficulty"), [(45, 2), (60, 3), (80, 4)])
def test_learning_path_snapshot_maps_average_ability_to_five_level_difficulty(
    ability_score: int,
    expected_difficulty: int,
) -> None:
    path = LearningPath(
        public_id=f"path_difficulty_{ability_score}",
        learner_id=1,
        path_json={
            "stages": [{"name": "当前单元", "knowledge_ids": ["knowledge_target"]}],
            "node_states": {
                "unit:knowledge_target": {
                    "path_node_id": "unit:knowledge_target",
                    "knowledge_ids": ["knowledge_target"],
                    "focus_knowledge_ids": ["knowledge_target"],
                    "title": "当前单元",
                    "path_order": 1,
                    "status": "current",
                    "learning_objective": "掌握当前单元",
                    "recommendation_reason": "根据当前画像安排。",
                    "prerequisite_knowledge_ids": [],
                }
            },
            "current_node_id": "unit:knowledge_target",
            "path_version": "dynamic-units-v1",
        },
    )
    profile = SimpleNamespace(
        ability_scores=AbilityScores(
            theory=ability_score,
            practice=ability_score,
            problem_solving=ability_score,
            knowledge_breadth=ability_score,
            learning_speed=ability_score,
        )
    )

    _snapshot, current = generation_worker._learning_path_snapshot(path, profile)

    assert current is not None
    assert current.target_difficulty == expected_difficulty


def test_worker_maps_final_decisions_to_stable_terminal_failure_codes() -> None:
    exhausted = FinalizeTaskOutput(
        task_id="task_failure_codes",
        decision=TaskDecision.FAILED,
        revision_count=2,
        decision_reason="自动定向修订已达到上限。",
    )
    rejected = exhausted.model_copy(update={"decision": TaskDecision.REJECTED, "revision_count": 0})

    assert generation_worker._finalization_failure_code(exhausted) == "revision_exhausted"
    assert generation_worker._finalization_failure_code(rejected) == "resource_rejected"
    assert generation_worker._finalization_failure_code(None) == "generation_failed"


def _node_overrides():
    flow = initial_generation_flow_example()
    return {
        "prepare_task": lambda _state: prepare_task_output_to_patch(flow["prepare_task"]["output"]),
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
    monkeypatch.setattr(
        generation_worker,
        "load_domain_runtime",
        lambda *_: SimpleNamespace(
            generation_ready=True,
            profile_config=AI_APP_DEV_PROFILE_V2,
            display_name="人工智能应用开发实训",
            reasons=(),
        ),
    )
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
        checkpoint = db.scalar(
            select(GraphCheckpoint).where(GraphCheckpoint.task_id == task.public_id)
        )
        runs = list(db.scalars(select(AgentRun).where(AgentRun.generation_task_id == task.id)))
        messages = list(
            db.scalars(
                select(AgentMessageRecord)
                .where(AgentMessageRecord.task_id == task.public_id)
                .order_by(AgentMessageRecord.id)
            )
        )
        resources = list(
            db.scalars(
                select(LearningResource).where(LearningResource.generation_task_id == task.id)
            )
        )
        reports = list(db.scalars(select(ReviewReport).where(ReviewReport.task_id == task.id)))

    assert task.progress == 100
    assert checkpoint is not None and checkpoint.state_json["native_checkpoint"] is True
    assert len(runs) == 6 and all(run.status == "completed" for run in runs)
    assert len(messages) >= len(runs)
    assert all(
            run.contract_version == "agent-contract-v10" and len(run.prompt_hash) == 64
        for run in runs
    )
    result_receivers = [
        message.receiver for message in messages if message.message_type == "result"
    ]
    assert result_receivers == [
        "profile_analysis_agent",
        "knowledge_retrieval_agent",
        "content_generation_agent",
        "review_validation_agent",
        "orchestrator_agent",
        "orchestrator_agent",
    ]
    assert len(resources) == 3 and all(item.review_status == "passed" for item in resources)
    assert len(reports) == 3 and all(
        item.review_rule_version == "review-v5-claim-policy" for item in reports
    )

    repeated = generation_worker.run_generation_task("task_v3_worker")
    assert repeated["status"] == "completed"
    with sessions() as db:
        task = db.scalar(select(GenerationTask).where(GenerationTask.public_id == "task_v3_worker"))
        assert (
            len(
                list(
                    db.scalars(
                        select(LearningResource).where(
                            LearningResource.generation_task_id == task.id
                        )
                    )
                )
            )
            == 3
        )
        assert (
            len(list(db.scalars(select(ReviewReport).where(ReviewReport.task_id == task.id)))) == 3
        )
        assert (
            len(list(db.scalars(select(AgentRun).where(AgentRun.generation_task_id == task.id))))
            == 6
        )


def test_failed_review_resumes_from_checkpoint_without_regeneration(monkeypatch, tmp_path) -> None:
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
    monkeypatch.setattr(
        generation_worker,
        "load_domain_runtime",
        lambda *_: SimpleNamespace(
            generation_ready=True,
            profile_config=AI_APP_DEV_PROFILE_V2,
            display_name="人工智能应用开发实训",
            reasons=(),
        ),
    )
    monkeypatch.setattr(generation_worker, "build_nodes", lambda _runtime: nodes)
    monkeypatch.setattr(
        generation_worker.AgentRuntime,
        "production",
        classmethod(lambda _cls, **_kwargs: _Runtime()),
    )

    resumed = generation_worker.run_generation_task("task_v3_resume")

    assert resumed["status"] == "completed", resumed
    assert calls == {"generate": 1, "review": 2}
    with sessions() as db:
        task = db.scalar(select(GenerationTask).where(GenerationTask.public_id == "task_v3_resume"))
        runs = list(
            db.scalars(
                select(AgentRun).where(AgentRun.generation_task_id == task.id).order_by(AgentRun.id)
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


def test_generation_validation_failure_persists_sanitized_field_paths(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'generation-field-paths.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        learner = Learner(public_id="learner_field_paths", target_domain="ai_app_dev")
        db.add(learner)
        db.flush()
        profile = LearnerProfile(
            public_id="profile_field_paths",
            learner_id=learner.id,
            domain_code="ai_app_dev",
            ability_profile_json={"profile_type": "beginner"},
            weak_knowledge_json=[],
        )
        db.add(profile)
        db.flush()
        task = GenerationTask(
            public_id="task_field_paths",
            learner_id=learner.id,
            profile_id=profile.id,
            status="running",
            decision="pending",
            resource_types_json=["graded_quiz"],
        )
        db.add(task)
        db.commit()

        def fail_validation(_state):
            raise GenerationError(
                "generated_structure_validation_failed",
                field_paths=[
                    "structured_content.questions.5.options",
                    "x" * 500,
                ],
            )

        wrapped = generation_worker._observable_node(
            db,
            task,
            profile,
            "generate_resource",
            fail_validation,
            _Runtime(),
        )
        with pytest.raises(GenerationError, match="generated_structure_validation_failed"):
            wrapped({})

        run = db.scalar(select(AgentRun).where(AgentRun.generation_task_id == task.id))
        message = db.scalar(
            select(AgentMessageRecord)
            .where(AgentMessageRecord.task_id == task.public_id)
            .where(AgentMessageRecord.message_type == "error")
        )

    expected = ["structured_content.questions.5.options", "x" * 200]
    assert run.output_summary_json["failure_code"] == ("generated_structure_validation_failed")
    assert run.output_summary_json["field_paths"] == expected
    assert message.payload_summary_json["field_paths"] == expected


def test_interrupted_task_is_claimed_for_one_startup_recovery(monkeypatch, tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'startup-recovery.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        learner = Learner(public_id="learner_startup_recovery", target_domain="ai_app_dev")
        db.add(learner)
        db.flush()
        profile = LearnerProfile(
            public_id="profile_startup_recovery",
            learner_id=learner.id,
            domain_code="ai_app_dev",
            ability_profile_json={"profile_type": "beginner"},
            weak_knowledge_json=[],
        )
        db.add(profile)
        db.flush()
        task = GenerationTask(
            public_id="task_startup_recovery",
            learner_id=learner.id,
            profile_id=profile.id,
            status="running",
            decision="pending",
            resource_types_json=["lecture"],
        )
        db.add(task)
        db.flush()
        db.add(
            GraphCheckpoint(
                task_id=task.public_id,
                checkpoint_id="checkpoint-startup",
                state_json={"native_checkpoint": True},
                status="saved",
            )
        )
        db.add(
            AgentRun(
                generation_task_id=task.id,
                agent_name="review_validation_agent",
                status="running",
                input_summary_json={"step": "review_resource"},
                output_summary_json={"review_batch_cache": {"entries": []}},
                contract_version=CONTRACT_VERSION,
            )
        )
        db.commit()

    monkeypatch.setattr(generation_worker, "SessionLocal", sessions)

    assert generation_worker.recover_interrupted_generation_tasks() == ["task_startup_recovery"]
    with sessions() as db:
        task = db.scalar(
            select(GenerationTask).where(GenerationTask.public_id == "task_startup_recovery")
        )
        checkpoint = db.scalar(
            select(GraphCheckpoint).where(GraphCheckpoint.task_id == "task_startup_recovery")
        )
        run = db.scalar(select(AgentRun).where(AgentRun.generation_task_id == task.id))
        assert task.status == "retry_pending"
        assert checkpoint.state_json["auto_recovery_count"] == 1
        assert run.status == "failed"
        assert run.output_summary_json["failure_code"] == "persistence_interrupted"
        assert run.output_summary_json["recoverable"] is True

    assert generation_worker.recover_interrupted_generation_tasks() == []
    with sessions() as db:
        task = db.scalar(
            select(GenerationTask).where(GenerationTask.public_id == "task_startup_recovery")
        )
        assert task.status == "failed"
        assert task.failure_reason == "checkpoint_recovery_exhausted"


def test_startup_recovery_discards_old_contract_checkpoint(monkeypatch, tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'stale-contract-recovery.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        learner = Learner(public_id="learner_stale_contract", target_domain="ai_app_dev")
        db.add(learner)
        db.flush()
        profile = LearnerProfile(
            public_id="profile_stale_contract",
            learner_id=learner.id,
            domain_code="ai_app_dev",
            ability_profile_json={"profile_type": "beginner"},
            weak_knowledge_json=[],
        )
        db.add(profile)
        db.flush()
        task = GenerationTask(
            public_id="task_stale_contract",
            learner_id=learner.id,
            profile_id=profile.id,
            status="running",
            decision="pending",
            progress=78,
            resource_types_json=["lecture"],
        )
        db.add(task)
        db.flush()
        db.add(
            GraphCheckpoint(
                task_id=task.public_id,
                checkpoint_id="checkpoint-v7",
                state_json={"native_checkpoint": True},
                status="saved",
            )
        )
        db.add(
            AgentRun(
                generation_task_id=task.id,
                agent_name="review_validation_agent",
                status="running",
                input_summary_json={"step": "review_resource"},
                output_summary_json={},
                contract_version="agent-contract-v7",
            )
        )
        db.commit()

    monkeypatch.setattr(generation_worker, "SessionLocal", sessions)

    assert generation_worker.recover_interrupted_generation_tasks() == [
        "task_stale_contract"
    ]
    with sessions() as db:
        task = db.scalar(
            select(GenerationTask).where(GenerationTask.public_id == "task_stale_contract")
        )
        checkpoint = db.scalar(
            select(GraphCheckpoint).where(GraphCheckpoint.task_id == "task_stale_contract")
        )
        assert checkpoint is None
        assert task.status == "retry_pending"
        assert task.progress == 0
        assert task.failure_reason == ""
