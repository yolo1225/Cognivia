from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.contract_adapters import (
    analyze_profile_output_to_patch,
    build_analyze_profile_input,
    build_prepare_task_input,
    interpret_feedback_output_to_patch,
    prepare_task_output_to_patch,
)
from app.agents.contracts import FeedbackIntent, InterpretFeedbackOutput, RecommendedAction
from app.agents.contracts import QUALITY_RULE_VERSION
from app.agents.profile_analysis_agent import ProfileAnalysisAgent
from app.agents.orchestrator_agent import OrchestratorAgent
from app.core.db import get_db
from app.main import app
from app.models import (
    AgentRun,
    AnswerRecord,
    Base,
    DiagnosticQuestion,
    Feedback,
    GenerationTask,
    KnowledgeItem,
    Learner,
    LearnerProfile,
    LearningResource,
)
from app.services.resource_tutoring_service import TutoringAnswer
from app.api.v1.generation_tasks import _semantic_events
from app.workers.generation_worker import (
    _feedback_assessments,
    _initial_state,
    _persist_profile_update,
)


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _override(factory: sessionmaker[Session]):
    def get_test_db() -> Generator[Session, None, None]:
        with factory() as db:
            yield db

    return get_test_db


def _seed(db: Session) -> None:
    learner = Learner(
        public_id="learner_001",
        background="test",
        target_domain="ai_app_dev",
        learning_style="mixed",
    )
    db.add(learner)
    db.flush()
    profile = LearnerProfile(
        public_id="profile_m4a",
        learner_id=learner.id,
        domain_code="ai_app_dev",
        ability_profile_json={"profile_type": "beginner"},
        weak_knowledge_json=[],
    )
    db.add(profile)
    knowledge = KnowledgeItem(
        public_id="rag_pipeline_overview",
        domain_code="ai_app_dev",
        name="RAG 验证",
        category="rag_practice",
        difficulty=3,
        tags_json=["rag"],
        content_md="检索增强生成需要可追溯证据。",
        source_title="M4A test source",
        needs_reembedding=False,
    )
    db.add(knowledge)
    db.flush()
    for index in range(2):
        db.add(
            DiagnosticQuestion(
                public_id=f"m4a_q_{index}",
                domain_code="ai_app_dev",
                knowledge_item_id=knowledge.id,
                question_type="single_choice",
                stem=f"验证题 {index}",
                options_json=["正确", "错误"],
                answer_key_json={"correct_option": 0},
                difficulty=3,
            )
        )
    db.flush()
    task = GenerationTask(
        public_id="task_m4a_source",
        learner_id=learner.id,
        profile_id=profile.id,
        domain_code="ai_app_dev",
        status="completed",
        decision="completed",
        resource_types_json=["lecture"],
        package_quality_json={"quality_rule_version": QUALITY_RULE_VERSION},
        package_coverage_json={
            "resource_knowledge_targets": {
                "lecture": ["rag_pipeline_overview"]
            }
        },
        is_current_package=True,
    )
    db.add(task)
    db.flush()
    db.add(
        LearningResource(
            public_id="resource_m4a",
            generation_task_id=task.id,
            resource_type="lecture",
            title="M4A resource",
            content_md="正文",
            difficulty=3,
            sources_json=[{"knowledge_id": knowledge.public_id}],
            review_status="passed",
            series_id="resource_m4a",
            is_current=True,
        )
    )
    db.commit()


def test_m4a_stream_and_non_stream_share_real_turn_and_validation(monkeypatch) -> None:
    factory = _session_factory()
    with factory() as db:
        _seed(db)
    calls = 0

    def execute(_self, request):
        nonlocal calls
        calls += 1
        return InterpretFeedbackOutput(
            task_id=request.task_id,
            feedback_intent=FeedbackIntent.TOO_EASY,
            recommended_action=RecommendedAction.ASK_FOLLOW_UP,
            reply="请先完成正式验证题。",
            evidence=[],
            needs_generation=False,
            decision_reason="主观反馈不能直接更新画像。",
        )

    monkeypatch.setattr("app.services.tutoring_service.TutoringAgent.execute", execute)
    monkeypatch.setattr(
        "app.services.tutoring_service.answer_resource_question",
        lambda *_args, **_kwargs: TutoringAnswer(
            answer="请完成验证。", sources=[], scope_status="resource", assessment=None
        ),
    )
    monkeypatch.setattr("app.api.v1.tutoring.run_generation_task", lambda _task_id: None)
    app.dependency_overrides[get_db] = _override(factory)
    client = TestClient(app)
    try:
        session_id = client.post(
            "/api/v1/tutoring/sessions", json={"resource_id": "resource_m4a"}
        ).json()["data"]["session_id"]
        first = client.post(
            f"/api/v1/tutoring/sessions/{session_id}/messages",
            json={"content": "太简单了"},
        ).json()["data"]
        assert first["profile_update_required"] is False
        assert first["task_id"] is None
        first_assessment = first["reply"]["assessment"]
        assert first_assessment["question_id"] == "m4a_q_0"

        first_answer = client.post(
            f"/api/v1/tutoring/sessions/{session_id}/assessments/{first_assessment['assessment_id']}/answers",
            json={"answer": 0},
        ).json()["data"]
        assert first_answer["is_correct"] is True
        assert first_answer["task_id"] is None
        repeated = client.post(
            f"/api/v1/tutoring/sessions/{session_id}/assessments/{first_assessment['assessment_id']}/answers",
            json={"answer": 0},
        ).json()["data"]
        assert repeated["answer_record_id"] == first_answer["answer_record_id"]

        stream = client.post(
            f"/api/v1/tutoring/sessions/{session_id}/messages/stream",
            json={"content": "我可以再验证一次"},
        )
        assert stream.status_code == 200
        assert "event: accepted" in stream.text
        assert "event: agent_status" in stream.text
        assert "event: completed" in stream.text
        current = client.get(f"/api/v1/tutoring/sessions/{session_id}").json()["data"]
        second_assessment = next(
            message["assessment"]
            for message in reversed(current["messages"])
            if message.get("assessment") and message["assessment"]["status"] == "pending"
        )
        second_answer = client.post(
            f"/api/v1/tutoring/sessions/{session_id}/assessments/{second_assessment['assessment_id']}/answers",
            json={"answer": 0},
        ).json()["data"]
        assert second_answer["task_id"] is not None
        with factory() as db:
            assert db.query(AnswerRecord).count() == 2
            assert db.query(AgentRun).filter_by(agent_name="tutoring_agent").count() == 2
            assert db.query(Feedback).count() == 2
            feedback_task = db.query(GenerationTask).filter_by(event_type="resource_feedback").one()
            feedback = db.get(Feedback, feedback_task.source_feedback_id)
            learner = db.query(Learner).filter_by(public_id="learner_001").one()
            evidence, assessments = _feedback_assessments(
                db, feedback_task, learner, feedback
            )
            assert len(evidence) == len(assessments) == 2
            original_profile = db.get(LearnerProfile, feedback_task.profile_id)
            state = _initial_state(
                db, feedback_task, learner, original_profile, feedback
            )
            state.update(
                prepare_task_output_to_patch(
                    OrchestratorAgent().execute(build_prepare_task_input(state))
                )
            )
            state.update(
                interpret_feedback_output_to_patch(
                    InterpretFeedbackOutput(
                        task_id=feedback_task.public_id,
                        feedback_intent=FeedbackIntent.TOO_EASY,
                        recommended_action=RecommendedAction.CHALLENGE,
                        reply="验证证据满足画像分析门禁。",
                        evidence=evidence,
                        needs_generation=True,
                        decision_reason="两次独立高置信验证通过。",
                    )
                )
            )
            analysis = ProfileAnalysisAgent().execute(
                build_analyze_profile_input(
                    state, knowledge_assessments=assessments
                )
            )
            assert analysis.profile_update_required is True
            state.update(analyze_profile_output_to_patch(analysis))
            next_profile = _persist_profile_update(
                db, feedback_task, original_profile, state
            )
            db.flush()
            assert next_profile.id != original_profile.id
            assert next_profile.profile_version == original_profile.profile_version + 1
            assert feedback.profile_update_required is True
            assert feedback.affected_knowledge_ids_json
            assert feedback.affected_resource_ids_json == ["resource_m4a"]
            consumed = [
                (record.answer_summary_json or {}).get("consumed_by_profile_id")
                for record in db.query(AnswerRecord).order_by(AnswerRecord.id)
            ]
            assert consumed == [next_profile.id, next_profile.id]
            evidence, assessments = _feedback_assessments(
                db, feedback_task, learner, feedback
            )
            assert len(evidence) == len(assessments) == 0
        assert calls == 2
    finally:
        app.dependency_overrides.clear()


def test_m4a_arbitration_events_read_the_review_array() -> None:
    factory = _session_factory()
    with factory() as db:
        _seed(db)
        task = db.query(GenerationTask).filter_by(public_id="task_m4a_source").one()
        events = _semantic_events(
            task,
            {
                "status": "completed",
                "step": "review_resource",
                "payload": {"arbitration": [{"required": True}]},
            },
        )
        assert [name for name, _payload in events] == [
            "review_disagreement",
            "review_retrieval_started",
        ]
        assert (
            _semantic_events(
                task,
                {
                    "status": "completed",
                    "step": "review_resource",
                    "payload": {"arbitration": [{"required": False}]},
                },
            )
            == []
        )
