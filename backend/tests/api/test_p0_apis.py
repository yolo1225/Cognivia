from collections.abc import Generator
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.contracts import (
    CONTRACT_VERSION,
    FeedbackIntent,
    InterpretFeedbackOutput,
    RecommendedAction,
)
from app.core.db import get_db
from app.core.security import Principal, get_current_user
from app.main import app
from app.models import (
    Base,
    AgentMessageRecord,
    AgentRun,
    Domain,
    DiagnosticQuestion,
    GenerationTask,
    GraphCheckpoint,
    Learner,
    LearnerProfile,
    LearningResource,
    KnowledgeItem,
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
    db.add(Domain(domain_code="ai_app_dev", name="人工智能应用开发实训", config_json={}))
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


def test_question_bank_status_filter_exposes_only_question_data() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        item = KnowledgeItem(
            public_id="knowledge_certified",
            domain_code="ai_app_dev",
            name="可信题目来源",
            category="测试",
            difficulty=2,
            tags_json=[],
            content_md="可信原文",
            source_title="测试来源",
            license_note="test",
            status="published",
        )
        db.add(item)
        db.flush()
        common = {
            "domain_code": "ai_app_dev",
            "knowledge_item_id": item.id,
            "question_type": "single_choice",
            "stem": "哪项正确？",
            "options_json": ["A", "B", "C", "D"],
            "difficulty": 2,
            "status": "active",
        }
        db.add_all(
            [
                DiagnosticQuestion(
                    public_id="question_active",
                    answer_key_json={
                        "correct_option": 0,
                        "explanation": "题目解析。",
                        "quiz_level": "foundation",
                    },
                    **common,
                ),
                DiagnosticQuestion(
                    public_id="question_stale",
                    answer_key_json={
                        "correct_option": 0,
                        "explanation": "待更新题目解析。",
                        "quiz_level": "foundation",
                    },
                    **{**common, "status": "stale"},
                ),
            ]
        )
        db.commit()
    app.dependency_overrides[get_db] = override(testing_session)
    client = TestClient(app)
    try:
        response = client.get(
            "/api/v1/knowledge/questions",
            params={
                "domain_code": "ai_app_dev",
                "status": "active",
            },
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["total"] == 1
        question = data["items"][0]
        assert question["question_id"] == "question_active"
        assert question["status"] == "active"
        assert "certification_status" not in question
        assert "source_ref_ids" not in question
    finally:
        app.dependency_overrides.clear()


def test_resource_visibility_tutoring_and_feedback_contract(monkeypatch) -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        seed_resource(db)
        db.add(
            KnowledgeItem(
                public_id="AIAPP-K029",
                domain_code="ai_app_dev",
                name="Python 异步并发",
                category="实操技能",
                difficulty=3,
                tags_json=[],
                content_md="asyncio 基础知识。",
                source_title="Python 文档",
                license_note="官方文档",
                status="published",
            )
        )
        db.commit()
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
        assert resources[0]["source_details"] == [
            {"knowledge_id": "AIAPP-K029", "name": "Python 异步并发"}
        ]
        admin_resources = client.get("/api/v1/resources?include_unpublished=true").json()["data"]
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
            assert run.prompt_version == "v6"
            assert run.contract_version == "agent-contract-v10"
            assert len(run.prompt_hash) == 64
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


def test_v5_resource_feedback_requires_full_v6_regeneration(monkeypatch) -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        seed_resource(db)

    rag_checked = False

    def unexpected_rag_check(_domain_code: str):
        nonlocal rag_checked
        rag_checked = True
        raise AssertionError("V5 compatibility must be checked before RAG readiness")

    monkeypatch.setattr(
        "app.api.v1.resources.require_candidate_rag",
        unexpected_rag_check,
    )
    app.dependency_overrides[get_db] = override(testing_session)
    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/resources/resource_visible/feedback",
            json={"feedback_type": "has_error", "rating": 1},
        )
        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "V6_FULL_REGENERATION_REQUIRED"
        assert error["message"] == "V6_FULL_REGENERATION_REQUIRED"
        assert rag_checked is False
        with testing_session() as db:
            assert db.query(GenerationTask).count() == 1
    finally:
        app.dependency_overrides.clear()


def test_task_resource_query_uses_task_owner_when_client_learner_is_stale() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        seed_resource(db)
        task_learner = Learner(
            public_id="learner_task_owner",
            background="test",
            target_domain="ai_app_dev",
            learning_style="mixed",
        )
        db.add(task_learner)
        db.flush()
        profile = LearnerProfile(
            public_id="profile_task_owner",
            learner_id=task_learner.id,
            ability_profile_json={"profile_type": "beginner"},
            weak_knowledge_json=[],
        )
        db.add(profile)
        db.flush()
        task = GenerationTask(
            public_id="task_other_learner",
            learner_id=task_learner.id,
            profile_id=profile.id,
            status="completed",
            decision="completed",
            resource_types_json=["lecture"],
        )
        db.add(task)
        db.flush()
        db.add(
            LearningResource(
                public_id="resource_task_owner",
                generation_task_id=task.id,
                resource_type="lecture",
                title="任务所属学习者的资源",
                content_md="正文",
                difficulty=2,
                sources_json=[{"knowledge_id": "AIAPP-K030"}],
                review_status="passed",
                series_id="resource_task_owner",
                is_current=True,
            )
        )
        db.commit()

    app.dependency_overrides[get_db] = override(testing_session)
    try:
        response = TestClient(app).get(
            "/api/v1/resources",
            params={
                "task_id": "task_other_learner",
                "learner_id": "learner_001",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert [item["resource_id"] for item in response.json()["data"]] == ["resource_task_owner"]


def test_admin_report_requires_own_learner_unless_viewing_task() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        seed_resource(db)
        task_learner = Learner(
            public_id="learner_report_task_owner",
            background="test",
            target_domain="ai_app_dev",
            learning_style="mixed",
        )
        db.add(task_learner)
        db.flush()
        task_profile = LearnerProfile(
            public_id="profile_report_task_owner",
            learner_id=task_learner.id,
            ability_profile_json={"profile_type": "beginner"},
            weak_knowledge_json=[],
        )
        db.add(task_profile)
        db.flush()
        db.add(
            GenerationTask(
                public_id="task_report_owner",
                learner_id=task_learner.id,
                profile_id=task_profile.id,
                status="completed",
                decision="completed",
                resource_types_json=["lecture"],
            )
        )
        db.commit()

    app.dependency_overrides[get_db] = override(testing_session)
    app.dependency_overrides[get_current_user] = lambda: Principal(
        user_id="admin",
        role="admin",
        learner_id="learner_001",
    )
    try:
        client = TestClient(app)
        direct_response = client.get("/api/v1/reports/learners/learner_report_task_owner")
        task_response = client.get(
            "/api/v1/reports/learners/learner_report_task_owner",
            params={"task_id": "task_report_owner"},
        )
    finally:
        app.dependency_overrides.clear()

    assert direct_response.status_code == 403
    assert task_response.status_code == 200
    assert task_response.json()["data"]["learner_id"] == "learner_report_task_owner"


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
                contract_version=CONTRACT_VERSION,
            )
        )
        db.commit()

    scheduled: list[str] = []
    monkeypatch.setattr("app.api.v1.generation_tasks.run_generation_task", scheduled.append)
    monkeypatch.setattr("app.api.v1.generation_tasks.require_candidate_rag", lambda _domain: {})
    app.dependency_overrides[get_db] = override(testing_session)
    try:
        response = TestClient(app).post("/api/v1/generation-tasks/task_retryable/retry")
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "retry_pending"
        assert scheduled == ["task_retryable"]
        with testing_session() as db:
            task = db.scalar(
                select(GenerationTask).where(GenerationTask.public_id == "task_retryable")
            )
            assert task.status == "retry_pending"
            assert task.decision == "pending"
            checkpoint = db.scalar(
                select(GraphCheckpoint).where(GraphCheckpoint.task_id == "task_retryable")
            )
            assert checkpoint is not None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "failure_code",
    [
        "graded_quiz_question_source_missing",
        "graded_quiz_question_bank_insufficient",
    ],
)
def test_question_source_failure_retry_discards_stale_retrieval_checkpoint(
    monkeypatch, failure_code: str
) -> None:
    testing_session = build_test_session()
    task_public_id = f"task_retry_fresh_{failure_code}"
    with testing_session() as db:
        learner, profile, _, _ = seed_resource(db)
        task = GenerationTask(
            public_id=task_public_id,
            learner_id=learner.id,
            profile_id=profile.id,
            status="failed",
            decision="failed",
            progress=40,
            resource_types_json=["lecture", "practice_guide", "graded_quiz"],
            failure_reason=failure_code,
        )
        db.add(task)
        db.flush()
        db.add(
            GraphCheckpoint(
                task_id=task.public_id,
                checkpoint_id="cp_stale_retrieval",
                state_json={"native_checkpoint": True},
                status="saved",
            )
        )
        db.add(
            AgentRun(
                generation_task_id=task.id,
                agent_name="content_generation_agent",
                status="failed",
                input_summary_json={"step": "generate_resource"},
                output_summary_json={
                    "step": "generate_resource",
                    "failure_code": failure_code,
                    "recoverable": True,
                },
                error_message=failure_code,
                contract_version=CONTRACT_VERSION,
            )
        )
        db.commit()

    scheduled: list[str] = []
    monkeypatch.setattr("app.api.v1.generation_tasks.run_generation_task", scheduled.append)
    monkeypatch.setattr("app.api.v1.generation_tasks.require_candidate_rag", lambda _domain: {})
    app.dependency_overrides[get_db] = override(testing_session)
    try:
        response = TestClient(app).post(
            f"/api/v1/generation-tasks/{task_public_id}/retry"
        )
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "retry_pending"
        assert scheduled == [task_public_id]
        with testing_session() as db:
            task = db.scalar(
                select(GenerationTask).where(
                    GenerationTask.public_id == task_public_id
                )
            )
            checkpoint = db.scalar(
                select(GraphCheckpoint).where(
                    GraphCheckpoint.task_id == task_public_id
                )
            )
            assert task.status == "retry_pending"
            assert task.decision == "pending"
            assert task.progress == 0
            assert task.failure_reason == ""
            assert checkpoint is None
    finally:
        app.dependency_overrides.clear()


def test_retry_discards_checkpoint_from_previous_contract_version(monkeypatch) -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner, profile, _, _ = seed_resource(db)
        task = GenerationTask(
            public_id="task_retry_v7_checkpoint",
            learner_id=learner.id,
            profile_id=profile.id,
            status="failed",
            decision="failed",
            progress=25,
            resource_types_json=["lecture", "practice_guide", "graded_quiz"],
            failure_reason="ValidationError",
        )
        db.add(task)
        db.flush()
        db.add(
            GraphCheckpoint(
                task_id=task.public_id,
                checkpoint_id="cp_v7",
                state_json={"native_checkpoint": True},
                status="saved",
            )
        )
        db.add(
            AgentRun(
                generation_task_id=task.id,
                agent_name="knowledge_retrieval_agent",
                status="failed",
                input_summary_json={"step": "retrieve_knowledge"},
                output_summary_json={
                    "failure_code": "ValidationError",
                    "recoverable": True,
                },
                error_message="ValidationError",
                contract_version="agent-contract-v7",
            )
        )
        db.commit()

    scheduled: list[str] = []
    monkeypatch.setattr("app.api.v1.generation_tasks.run_generation_task", scheduled.append)
    monkeypatch.setattr("app.api.v1.generation_tasks.require_candidate_rag", lambda _domain: {})
    app.dependency_overrides[get_db] = override(testing_session)
    try:
        response = TestClient(app).post(
            "/api/v1/generation-tasks/task_retry_v7_checkpoint/retry"
        )
        assert response.status_code == 200
        successor_id = response.json()["data"]["task_id"]
        assert successor_id != "task_retry_v7_checkpoint"
        assert response.json()["data"]["status"] == "pending"
        assert scheduled == [successor_id]
        with testing_session() as db:
            task = db.scalar(
                select(GenerationTask).where(
                    GenerationTask.public_id == "task_retry_v7_checkpoint"
                )
            )
            checkpoint = db.scalar(
                select(GraphCheckpoint).where(
                    GraphCheckpoint.task_id == "task_retry_v7_checkpoint"
                )
            )
            successor = db.scalar(
                select(GenerationTask).where(GenerationTask.public_id == successor_id)
            )
            assert task.status == "failed"
            assert checkpoint is not None
            assert successor is not None
            assert successor.source_task_id == task.id
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
        assert (
            client.get(
                "/api/v1/generation-tasks/active",
                params={"learner_id": "learner_other"},
            ).json()["data"]
            is None
        )

        with testing_session() as db:
            db.query(GenerationTask).filter(
                GenerationTask.learner_id == learner_db_id,
                GenerationTask.status.in_({"pending", "retry_pending", "running"}),
            ).update(
                {"status": "completed", "decision": "completed"},
                synchronize_session=False,
            )
            db.commit()
        assert (
            client.get(
                "/api/v1/generation-tasks/active",
                params={"learner_id": "learner_active"},
            ).json()["data"]
            is None
        )
    finally:
        app.dependency_overrides.clear()
