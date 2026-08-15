from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.contracts import (
    FeedbackIntent,
    InterpretFeedbackOutput,
    RecommendedAction,
)
from app.core.db import get_db
from app.main import app
from app.models import (
    Base,
    AgentMessageRecord,
    AgentRun,
    GenerationTask,
    GraphCheckpoint,
    Learner,
    LearnerProfile,
    LearningResource,
)


def build_test_session() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def override(testing_session: sessionmaker[Session]):
    def get_test_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    return get_test_db


def seed_resource(db: Session):
    learner = Learner(
        public_id="learner_001",
        background="test",
        target_domain="ai_app_dev",
        learning_style="mixed",
    )
    db.add(learner)
    db.flush()
    profile = LearnerProfile(
        public_id="profile_001",
        learner_id=learner.id,
        ability_profile_json={"profile_type": "beginner"},
        weak_knowledge_json=[],
    )
    db.add(profile)
    db.flush()
    task = GenerationTask(
        public_id="task_visible",
        learner_id=learner.id,
        profile_id=profile.id,
        status="completed",
        decision="completed",
        resource_types_json=["lecture"],
    )
    db.add(task)
    db.flush()
    visible = LearningResource(
        public_id="resource_visible",
        generation_task_id=task.id,
        resource_type="lecture",
        title="通过资源",
        content_md="正文",
        difficulty=2,
        sources_json=[{"knowledge_id": "AIAPP-K029"}],
        review_status="passed",
        series_id="resource_visible",
        is_current=True,
    )
    hidden = LearningResource(
        public_id="resource_hidden",
        generation_task_id=task.id,
        resource_type="lecture",
        title="未发布草稿",
        content_md="草稿",
        difficulty=2,
        sources_json=[],
        review_status="revision_required",
        series_id="resource_hidden",
        is_current=True,
    )
    db.add_all([visible, hidden])
    db.commit()
    return learner, profile, task, visible


def test_resource_visibility_tutoring_and_feedback_contract(monkeypatch) -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        seed_resource(db)
    monkeypatch.setattr("app.api.v1.resources.run_generation_task", lambda task_id: None)
    monkeypatch.setattr("app.api.v1.tutoring.run_generation_task", lambda task_id: None)
    monkeypatch.setattr(
        "app.services.tutoring_service.TutoringAgent.execute",
        lambda _self, request: InterpretFeedbackOutput(
            task_id=request.task_id,
            feedback_intent=FeedbackIntent.TOO_HARD,
            recommended_action=RecommendedAction.ASK_FOLLOW_UP,
            reply="你能指出具体卡住的概念或步骤吗？",
            evidence=[],
            needs_generation=False,
            decision_reason="首次困难反馈先进行追问。",
        ),
    )
    app.dependency_overrides[get_db] = override(testing_session)
    client = TestClient(app)
    try:
        resources = client.get("/api/v1/resources").json()["data"]
        assert [item["resource_id"] for item in resources] == ["resource_visible"]
        admin_resources = client.get(
            "/api/v1/resources?include_unpublished=true"
        ).json()["data"]
        assert {item["resource_id"] for item in admin_resources} == {
            "resource_visible",
            "resource_hidden",
        }

        session_response = client.post(
            "/api/v1/tutoring/sessions", json={"resource_id": "resource_visible"}
        )
        session_id = session_response.json()["data"]["session_id"]
        reused_session = client.post(
            "/api/v1/tutoring/sessions", json={"resource_id": "resource_visible"}
        ).json()["data"]
        assert reused_session["session_id"] == session_id
        message = client.post(
            f"/api/v1/tutoring/sessions/{session_id}/messages",
            json={"content": "这部分太难，我看不懂"},
        ).json()["data"]
        assert message["profile_update_required"] is False
        assert message["task_id"] is None
        with testing_session() as db:
            run = db.query(AgentRun).filter_by(agent_name="tutoring_agent").one()
            messages = db.query(AgentMessageRecord).filter_by(session_id=session_id).all()
            assert run.prompt_version == "v3"
            assert run.status == "completed"
            assert {item.message_type for item in messages} >= {"command", "result"}

        feedback = client.post(
            "/api/v1/resources/resource_visible/feedback",
            json={"feedback_type": "too_hard", "rating": 2},
        ).json()["data"]
        assert feedback["profile_update_required"] is False
        assert feedback["task_id"] is None
    finally:
        app.dependency_overrides.clear()


def test_failed_generation_task_can_schedule_checkpoint_retry(monkeypatch) -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner, profile, _, _ = seed_resource(db)
        task = GenerationTask(
            public_id="task_retryable",
            learner_id=learner.id,
            profile_id=profile.id,
            status="failed",
            decision="failed",
            progress=60,
            resource_types_json=["lecture"],
        )
        db.add(task)
        db.flush()
        db.add(
            GraphCheckpoint(
                task_id=task.public_id,
                checkpoint_id="cp_retryable",
                state_json={"native_checkpoint": True},
                status="saved",
            )
        )
        db.add(
            AgentRun(
                generation_task_id=task.id,
                agent_name="review_validation_agent",
                status="failed",
                input_summary_json={"step": "review_resource"},
                output_summary_json={
                    "step": "review_resource",
                    "failure_code": "review_model_call_failed",
                    "recoverable": True,
                },
                error_message="review_model_call_failed",
            )
        )
        db.commit()

    scheduled: list[str] = []
    monkeypatch.setattr(
        "app.api.v1.generation_tasks.run_generation_task", scheduled.append
    )
    monkeypatch.setattr(
        "app.api.v1.generation_tasks.require_candidate_rag", lambda _domain: {}
    )
    app.dependency_overrides[get_db] = override(testing_session)
    try:
        response = TestClient(app).post(
            "/api/v1/generation-tasks/task_retryable/retry"
        )
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "retry_pending"
        assert scheduled == ["task_retryable"]
        with testing_session() as db:
            task = db.scalar(
                select(GenerationTask).where(
                    GenerationTask.public_id == "task_retryable"
                )
            )
            assert task.status == "retry_pending"
            assert task.decision == "pending"
    finally:
        app.dependency_overrides.clear()


def test_active_generation_task_returns_latest_non_terminal_task_for_learner() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner = Learner(
            public_id="learner_active",
            background="test",
            target_domain="ai_app_dev",
            learning_style="mixed",
        )
        other_learner = Learner(
            public_id="learner_other",
            background="test",
            target_domain="ai_app_dev",
            learning_style="mixed",
        )
        db.add_all([learner, other_learner])
        db.flush()
        profile = LearnerProfile(
            public_id="profile_active",
            learner_id=learner.id,
            ability_profile_json={"profile_type": "beginner"},
            weak_knowledge_json=[],
        )
        other_profile = LearnerProfile(
            public_id="profile_other",
            learner_id=other_learner.id,
            ability_profile_json={"profile_type": "beginner"},
            weak_knowledge_json=[],
        )
        db.add_all([profile, other_profile])
        db.flush()
        db.add_all(
            [
                GenerationTask(
                    public_id="task_active_old",
                    learner_id=learner.id,
                    profile_id=profile.id,
                    status="pending",
                    decision="pending",
                    resource_types_json=["lecture"],
                ),
                GenerationTask(
                    public_id="task_active_latest",
                    learner_id=learner.id,
                    profile_id=profile.id,
                    status="running",
                    decision="pending",
                    resource_types_json=["lecture"],
                ),
                GenerationTask(
                    public_id="task_active_completed",
                    learner_id=learner.id,
                    profile_id=profile.id,
                    status="completed",
                    decision="completed",
                    resource_types_json=["lecture"],
                ),
            ]
        )
        learner_db_id = learner.id
        db.commit()

    app.dependency_overrides[get_db] = override(testing_session)
    try:
        client = TestClient(app)
        active = client.get(
            "/api/v1/generation-tasks/active",
            params={"learner_id": "learner_active"},
        )
        assert active.status_code == 200
        assert active.json()["data"]["task_id"] == "task_active_latest"
        assert client.get(
            "/api/v1/generation-tasks/active",
            params={"learner_id": "learner_other"},
        ).json()["data"] is None

        with testing_session() as db:
            db.query(GenerationTask).filter(
                GenerationTask.learner_id == learner_db_id,
                GenerationTask.status.in_({"pending", "retry_pending", "running"}),
            ).update(
                {"status": "completed", "decision": "completed"},
                synchronize_session=False,
            )
            db.commit()
        assert client.get(
            "/api/v1/generation-tasks/active",
            params={"learner_id": "learner_active"},
        ).json()["data"] is None
    finally:
        app.dependency_overrides.clear()
