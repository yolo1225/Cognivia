from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.contracts import FeedbackIntent, InterpretFeedbackOutput, RecommendedAction
from app.agents.contracts import QUALITY_RULE_VERSION
from app.core.db import get_db
from app.core.security import Principal, get_current_user
from app.main import app
from app.models import (
    AgentRun,
    AnswerRecord,
    Base,
    DiagnosticQuestion,
    Domain,
    Feedback,
    GenerationTask,
    KnowledgeItem,
    Learner,
    LearnerProfile,
    LearningPath,
    LearningAdjustmentProposal,
    LearningResource,
    MistakeReviewItem,
)
from app.api.v1.generation_tasks import _semantic_events
from app.services.learning_path_service import unit_node_id_for


RAG_NODE_ID = unit_node_id_for(["rag_pipeline_overview"])
NEXT_NODE_ID = unit_node_id_for(["distractor_knowledge"])


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
    distractor = KnowledgeItem(
        public_id="distractor_knowledge",
        domain_code="ai_app_dev",
        name="干扰知识点",
        category="rag_practice",
        difficulty=1,
        tags_json=[],
        content_md="干扰内容。",
        source_title="M4A test source",
        needs_reembedding=False,
    )
    db.add(distractor)
    db.flush()
    db.add(
        DiagnosticQuestion(
            public_id="m4a_distractor_q",
            domain_code="ai_app_dev",
            knowledge_item_id=distractor.id,
            question_type="single_choice",
            stem="低难度干扰题",
            options_json=["正确", "错误"],
            answer_key_json={"correct_option": 0},
            difficulty=1,
            status="active",
        )
    )
    for index in range(3):
        db.add(
            DiagnosticQuestion(
                public_id=f"m4a_q_{index}",
                domain_code="ai_app_dev",
                knowledge_item_id=knowledge.id,
                question_type="single_choice",
                stem=f"验证题 {index}",
                options_json=["正确", f"错误选项 {index}"],
                answer_key_json={
                    "correct_option": 0,
                    "question_bank_uses": ["mastery_validation"],
                },
                difficulty=3,
                status="active",
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
        resource_types_json=["lecture", "practice_guide", "graded_quiz"],
        package_quality_json={"quality_rule_version": QUALITY_RULE_VERSION},
        package_coverage_json={
            "resource_knowledge_targets": {"lecture": ["rag_pipeline_overview"]}
        },
        is_current_package=True,
    )
    db.add(task)
    db.flush()
    path = LearningPath(
            public_id="path_m4a",
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
            status="active",
            path_json={
                "stages": [
                    {"name": "RAG 验证", "knowledge_ids": ["rag_pipeline_overview"]},
                    {"name": "后续节点", "knowledge_ids": ["distractor_knowledge"]},
                ],
                "current_node_id": RAG_NODE_ID,
                "node_states": {
                    RAG_NODE_ID: {
                        "path_node_id": RAG_NODE_ID,
                        "knowledge_ids": ["rag_pipeline_overview"],
                        "focus_knowledge_ids": [],
                        "title": "RAG 验证",
                        "status": "current",
                        "path_order": 1,
                        "prerequisite_knowledge_ids": [],
                        "learning_objective": "掌握 RAG 验证",
                        "recommendation_reason": "根据当前学习目标安排。",
                    },
                    NEXT_NODE_ID: {
                        "path_node_id": NEXT_NODE_ID,
                        "knowledge_ids": ["distractor_knowledge"],
                        "focus_knowledge_ids": [],
                        "title": "后续节点",
                        "status": "locked",
                        "path_order": 2,
                        "prerequisite_knowledge_ids": ["rag_pipeline_overview"],
                        "learning_objective": "掌握后续节点",
                        "recommendation_reason": "根据前置关系安排。",
                    },
                },
                "path_version": "dynamic-units-v1",
            },
        )
    db.add(path)
    db.flush()
    task.learning_path_id = path.id
    task.path_node_id = RAG_NODE_ID
    db.add(
        LearningResource(
            public_id="resource_m4a",
            generation_task_id=task.id,
            resource_type="lecture",
            title="M4A resource",
            content_md="正文",
            difficulty=3,
            sources_json=[
                {"knowledge_id": knowledge.public_id},
                {"knowledge_id": distractor.public_id},
            ],
            review_status="passed",
            series_id="resource_m4a",
            is_current=True,
        )
    )
    db.add(
        LearningResource(
            public_id="resource_m4a_practice",
            generation_task_id=task.id,
            resource_type="practice_guide",
            title="M4A practice resource",
            content_md="实训正文",
            difficulty=3,
            sources_json=[{"knowledge_id": knowledge.public_id}],
            review_status="passed",
            series_id="resource_m4a_practice",
            is_current=True,
        )
    )
    db.commit()


def test_m4a_stream_and_non_stream_share_real_turn_and_validation(monkeypatch) -> None:
    factory = _session_factory()
    with factory() as db:
        _seed(db)
    calls = 0
    evidence_counts: list[int] = []

    def execute(_self, request):
        nonlocal calls
        calls += 1
        evidence_counts.append(len(request.feedback.supporting_evidence))
        return InterpretFeedbackOutput(
            task_id=request.task_id,
            feedback_intent=FeedbackIntent.TOO_EASY,
            recommended_action=RecommendedAction.ASK_FOLLOW_UP,
            reply="请先完成正式验证题。",
            evidence=[],
            needs_generation=False,
            decision_reason="主观反馈不能直接更新画像。",
        )

    def stream_execute(self, request, on_reply_delta):
        output = execute(self, request)
        on_reply_delta(output.reply)
        return output

    monkeypatch.setattr("app.services.tutoring_service.TutoringAgent.execute", execute)
    monkeypatch.setattr(
        "app.services.tutoring_service.TutoringAgent.stream_execute", stream_execute
    )
    monkeypatch.setattr(
        "app.services.learning_adjustment_service._analyze_profile",
        lambda _db, *, proposal, profile, path, **_kwargs: (
            profile,
            None,
            None,
            {"profile_changed": False, "ability_score_changes": {}},
        ),
    )
    monkeypatch.setattr(
        "app.services.learning_adjustment_service.graded_quiz_preflight",
        lambda *_args, **_kwargs: {"ready": True},
    )
    monkeypatch.setattr("app.api.v1.tutoring.run_generation_task", lambda _task_id: None)
    monkeypatch.setattr("app.api.v1.learning_adjustments.run_generation_task", lambda _task_id: None)
    app.dependency_overrides[get_db] = _override(factory)
    app.dependency_overrides[get_current_user] = lambda: Principal(
        "learner_user", "learner", "learner_001"
    )
    client = TestClient(app)
    try:
        session_id = client.post(
            "/api/v1/tutoring/sessions", json={"resource_id": "resource_m4a"}
        ).json()["data"]["session_id"]
        first = client.post(
            f"/api/v1/tutoring/sessions/{session_id}/messages",
            json={
                "content": "太简单了",
                "evidence": [
                    {
                        "evidence_id": "sync_support",
                        "type": "validated_behavior",
                        "summary": "同步入口证据透传验证",
                        "confidence": 0.5,
                        "confirmed": False,
                    }
                ],
            },
        ).json()["data"]
        assert first["profile_update_required"] is False
        assert first["task_id"] is None
        assert first["reply"]["assessment"] is None

        stream = client.post(
            f"/api/v1/tutoring/sessions/{session_id}/messages/stream",
            json={
                "content": "还是太简单了",
                "evidence": [
                    {
                        "evidence_id": "stream_support",
                        "type": "validated_behavior",
                        "summary": "流式入口证据透传验证",
                        "confidence": 0.5,
                        "confirmed": False,
                    }
                ],
            },
        )
        assert stream.status_code == 200
        assert "event: accepted" in stream.text
        assert "event: agent_status" in stream.text
        assert stream.text.count("event: delta") == 1
        assert "event: completed" in stream.text
        assert stream.text.index("event: accepted") < stream.text.index("event: delta")
        assert stream.text.index("event: delta") < stream.text.index("event: completed")
        current = client.get(f"/api/v1/tutoring/sessions/{session_id}").json()["data"]
        second_assessment = next((
            message["assessment"]
            for message in reversed(current["messages"])
            if message.get("assessment") and message["assessment"]["status"] == "pending"
        ), None)
        assert second_assessment is not None
        second_answer = client.post(
            f"/api/v1/tutoring/sessions/{session_id}/assessments/{second_assessment['assessment_id']}/answers",
            json={"answer": 0},
        ).json()["data"]
        assert second_answer["decision"] == "evidence_recorded"
        assert second_answer["current_node_id"] == RAG_NODE_ID
        assert second_answer["completed_node_id"] is None
        assert second_answer["node_gate"]["can_advance"] is False
        assert second_answer["task_id"] is None
        repeated = client.post(
            f"/api/v1/tutoring/sessions/{session_id}/assessments/{second_assessment['assessment_id']}/answers",
            json={"answer": 0},
        ).json()["data"]
        assert repeated["answer_record_id"] == second_answer["answer_record_id"]
        with factory() as db:
            assert db.query(AnswerRecord).count() == 1
            tutoring_runs = db.query(AgentRun).filter_by(agent_name="tutoring_agent").all()
            assert len(tutoring_runs) == 2
            assert all(
                run.input_summary_json["session_id"] == session_id for run in tutoring_runs
            )
            assert db.query(Feedback).count() == 2
            assert db.query(LearnerProfile).count() == 1
        assert calls == 2
        assert evidence_counts == [1, 1]
    finally:
        app.dependency_overrides.clear()


def test_manual_mastery_check_reports_when_current_node_has_no_choice_question() -> None:
    factory = _session_factory()
    with factory() as db:
        _seed(db)
        db.query(DiagnosticQuestion).filter_by(question_type="single_choice").delete()
        db.commit()
    app.dependency_overrides[get_db] = _override(factory)
    app.dependency_overrides[get_current_user] = lambda: Principal(
        "learner_user", "learner", "learner_001"
    )
    client = TestClient(app)
    try:
        session_id = client.post(
            "/api/v1/tutoring/sessions", json={"resource_id": "resource_m4a"}
        ).json()["data"]["session_id"]
        response = client.post(f"/api/v1/tutoring/sessions/{session_id}/mastery-check")
        assert response.status_code == 409
        assert response.json()["error"] == {
            "code": "MASTERY_CHECK_QUESTION_UNAVAILABLE",
            "message": "当前知识点缺少可判分的单选验证题，请联系管理员补题后重试。",
            "details": None,
        }
    finally:
        app.dependency_overrides.clear()


def test_mistake_tutoring_session_is_isolated_and_restored() -> None:
    factory = _session_factory()
    with factory() as db:
        _seed(db)
        learner = db.query(Learner).filter_by(public_id="learner_001").one()
        knowledge = db.query(KnowledgeItem).filter_by(public_id="rag_pipeline_overview").one()
        resource = db.query(LearningResource).filter_by(public_id="resource_m4a").one()
        db.add(
            MistakeReviewItem(
                public_id="mistake_m4a",
                learner_id=learner.id,
                domain_code="ai_app_dev",
                knowledge_item_id=knowledge.id,
                source_type="graded_quiz",
                source_record_id="quiz:m4a:0",
                source_resource_id=resource.id,
                question_type="single_choice",
                difficulty=3,
                status="pending",
                error_summary_json={},
            )
        )
        db.commit()
    app.dependency_overrides[get_db] = _override(factory)
    app.dependency_overrides[get_current_user] = lambda: Principal(
        "learner_user", "learner", "learner_001"
    )
    client = TestClient(app)
    try:
        resource_session = client.post(
            "/api/v1/tutoring/sessions", json={"resource_id": "resource_m4a"}
        ).json()["data"]
        mistake_payload = {
            "resource_id": "resource_m4a",
            "context_type": "mistake_review",
            "context_id": "mistake_m4a",
        }
        mistake_session = client.post(
            "/api/v1/tutoring/sessions", json=mistake_payload
        ).json()["data"]
        restored = client.post(
            "/api/v1/tutoring/sessions", json=mistake_payload
        ).json()["data"]

        assert resource_session["session_id"] != mistake_session["session_id"]
        assert restored["session_id"] == mistake_session["session_id"]
        assert restored["context_type"] == "mistake_review"
        assert restored["context_id"] == "mistake_m4a"
    finally:
        app.dependency_overrides.clear()


def test_mastery_retry_uses_an_unseen_question_and_hides_answer_disclosure() -> None:
    factory = _session_factory()
    with factory() as db:
        _seed(db)
    app.dependency_overrides[get_db] = _override(factory)
    app.dependency_overrides[get_current_user] = lambda: Principal(
        "learner_user", "learner", "learner_001"
    )
    client = TestClient(app)
    try:
        session_id = client.post(
            "/api/v1/tutoring/sessions", json={"resource_id": "resource_m4a"}
        ).json()["data"]["session_id"]
        first = client.post(
            f"/api/v1/tutoring/sessions/{session_id}/mastery-check"
        ).json()["data"]
        result = client.post(
            f"/api/v1/tutoring/sessions/{session_id}/assessments/{first['assessment_id']}/answers",
            json={"answer": 1},
        ).json()["data"]
        assert result["is_correct"] is False
        assert result["submitted_option"] == 1
        assert "correct_option" not in result
        assert "correct_answer" not in result
        assert "explanation" not in result

        restored = client.get(f"/api/v1/tutoring/sessions/{session_id}").json()["data"]
        scored = next(
            message["assessment"]
            for message in restored["messages"]
            if message.get("assessment", {}).get("assessment_id") == first["assessment_id"]
        )
        assert scored["status"] == "scored"
        assert scored["stem"] == first["stem"]
        assert scored["options"] == first["options"]
        assert scored["submitted_option"] == 1
        assert "correct_answer" not in scored
        assert "explanation" not in scored

        retry = client.post(
            f"/api/v1/tutoring/sessions/{session_id}/mastery-check"
        ).json()["data"]
        assert retry["question_id"] != first["question_id"]
        corrected = client.post(
            f"/api/v1/tutoring/sessions/{session_id}/assessments/{retry['assessment_id']}/answers",
            json={"answer": 0},
        ).json()["data"]
        assert corrected["is_correct"] is True
        assert corrected["submitted_option"] == 0
        assert corrected["correct_answer"] == first["options"][0]
        assert "explanation" in corrected
    finally:
        app.dependency_overrides.clear()


def test_learning_adjustment_conflict_does_not_trigger_assessment(monkeypatch) -> None:
    factory = _session_factory()
    with factory() as db:
        _seed(db)
    intents = iter([FeedbackIntent.TOO_EASY, FeedbackIntent.TOO_HARD])

    def execute(_self, request):
        intent = next(intents)
        return InterpretFeedbackOutput(
            task_id=request.task_id,
            feedback_intent=intent,
            recommended_action=RecommendedAction.ASK_FOLLOW_UP,
            reply="继续收集学习证据。",
            evidence=[],
            needs_generation=False,
            decision_reason="当前交互信号需要进一步确认。",
        )

    monkeypatch.setattr("app.services.tutoring_service.TutoringAgent.execute", execute)
    app.dependency_overrides[get_db] = _override(factory)
    app.dependency_overrides[get_current_user] = lambda: Principal(
        "learner_user", "learner", "learner_001"
    )
    client = TestClient(app)
    try:
        session_id = client.post(
            "/api/v1/tutoring/sessions", json={"resource_id": "resource_m4a"}
        ).json()["data"]["session_id"]
        first = client.post(
            f"/api/v1/tutoring/sessions/{session_id}/messages",
            json={"content": "内容太简单"},
        ).json()["data"]
        second = client.post(
            f"/api/v1/tutoring/sessions/{session_id}/messages",
            json={"content": "这部分其实太难"},
        ).json()["data"]
        assert first["reply"]["assessment"] is None
        assert second["reply"]["assessment"] is None
        with factory() as db:
            assert [
                item.evidence_status
                for item in db.query(Feedback).order_by(Feedback.id).all()
            ] == ["conflict", "conflict"]
    finally:
        app.dependency_overrides.clear()


def test_node_evidence_aggregates_across_resources_and_allows_cross_session_answer(
    monkeypatch,
) -> None:
    factory = _session_factory()
    with factory() as db:
        _seed(db)

    def execute(_self, request):
        return InterpretFeedbackOutput(
            task_id=request.task_id,
            feedback_intent=FeedbackIntent.TOO_EASY,
            recommended_action=RecommendedAction.ASK_FOLLOW_UP,
            reply="建议完成节点掌握检查。",
            evidence=[],
            needs_generation=False,
            decision_reason="本轮反馈已纳入节点学习判断。",
        )

    monkeypatch.setattr("app.services.tutoring_service.TutoringAgent.execute", execute)
    monkeypatch.setattr(
        "app.services.learning_adjustment_service._analyze_profile",
        lambda _db, *, proposal, profile, path, **_kwargs: (
            profile,
            None,
            None,
            {"profile_changed": False, "ability_score_changes": {}},
        ),
    )
    app.dependency_overrides[get_db] = _override(factory)
    app.dependency_overrides[get_current_user] = lambda: Principal(
        "learner_user", "learner", "learner_001"
    )
    client = TestClient(app)
    try:
        lecture_session = client.post(
            "/api/v1/tutoring/sessions", json={"resource_id": "resource_m4a"}
        ).json()["data"]["session_id"]
        practice_session = client.post(
            "/api/v1/tutoring/sessions",
            json={"resource_id": "resource_m4a_practice"},
        ).json()["data"]["session_id"]

        first = client.post(
            f"/api/v1/tutoring/sessions/{lecture_session}/messages",
            json={"content": "讲义内容我已经掌握了"},
        ).json()["data"]
        assert first["node_adjustment_state"] == "collecting"
        assert first["evidence_accepted"] is True

        second = client.post(
            f"/api/v1/tutoring/sessions/{practice_session}/messages",
            json={"content": "实训步骤也很简单"},
        ).json()["data"]
        assessment = second["reply"]["assessment"]
        assert assessment is not None
        assert second["node_adjustment_state"] == "pending_validation"

        lecture_state = client.get(
            f"/api/v1/tutoring/sessions/{lecture_session}"
        ).json()["data"]
        assert lecture_state["pending_assessment"] is None
        practice_state = client.get(
            f"/api/v1/tutoring/sessions/{practice_session}"
        ).json()["data"]
        assert practice_state["pending_assessment"]["assessment_id"] == assessment[
            "assessment_id"
        ]

        cross_session_answer = client.post(
            f"/api/v1/tutoring/sessions/{lecture_session}/assessments/{assessment['assessment_id']}/answers",
            json={"answer": 0},
        )
        assert cross_session_answer.status_code == 409

        answered = client.post(
            f"/api/v1/tutoring/sessions/{practice_session}/assessments/{assessment['assessment_id']}/answers",
            json={"answer": 0},
        )
        assert answered.status_code == 200, answered.json()
        assert answered.json()["data"]["decision"] == "evidence_recorded"

        lecture_after_answer = client.get(
            f"/api/v1/tutoring/sessions/{lecture_session}"
        ).json()["data"]
        assert lecture_after_answer["node_adjustment_result"] is None

        with factory() as db:
            feedback = db.query(Feedback).order_by(Feedback.id).all()
            assert [item.evidence_status for item in feedback] == ["consumed", "consumed"]
            proposal = db.query(LearningAdjustmentProposal).one()
            assert proposal.evidence_summary_json["resource_types"] == [
                "lecture",
                "practice_guide",
            ]
            assert len(proposal.evidence_summary_json["tutoring_session_ids"]) == 2
    finally:
        app.dependency_overrides.clear()


def test_quick_feedback_is_supporting_only_and_cannot_complete_the_threshold(
    monkeypatch,
) -> None:
    factory = _session_factory()
    with factory() as db:
        _seed(db)

    def execute(_self, request):
        return InterpretFeedbackOutput(
            task_id=request.task_id,
            feedback_intent=FeedbackIntent.TOO_EASY,
            recommended_action=RecommendedAction.ASK_FOLLOW_UP,
            reply="继续收集自然语言学习反馈。",
            evidence=[],
            needs_generation=False,
            decision_reason="快捷反馈不能代替独立学习回合。",
        )

    monkeypatch.setattr("app.services.tutoring_service.TutoringAgent.execute", execute)
    app.dependency_overrides[get_db] = _override(factory)
    app.dependency_overrides[get_current_user] = lambda: Principal(
        "learner_user", "learner", "learner_001"
    )
    client = TestClient(app)
    try:
        for _ in range(2):
            response = client.post(
                "/api/v1/resources/resource_m4a/feedback",
                json={"feedback_type": "too_easy"},
            )
            assert response.status_code == 200
        session_id = client.post(
            "/api/v1/tutoring/sessions", json={"resource_id": "resource_m4a"}
        ).json()["data"]["session_id"]
        turn = client.post(
            f"/api/v1/tutoring/sessions/{session_id}/messages",
            json={"content": "这部分我已经会了"},
        ).json()["data"]
        assert turn["reply"]["assessment"] is None
        with factory() as db:
            assert db.query(LearningAdjustmentProposal).count() == 0
            assert [
                item.evidence_status
                for item in db.query(Feedback).order_by(Feedback.id).all()
            ] == ["supporting_only", "supporting_only", "eligible"]
    finally:
        app.dependency_overrides.clear()


def test_support_hypothesis_wrong_answer_confirms_need_without_advancing(monkeypatch) -> None:
    factory = _session_factory()
    with factory() as db:
        _seed(db)

    def execute(_self, request):
        return InterpretFeedbackOutput(
            task_id=request.task_id,
            feedback_intent=FeedbackIntent.TOO_HARD,
            recommended_action=RecommendedAction.ASK_FOLLOW_UP,
            reply="再确认一下当前知识点。",
            evidence=[],
            needs_generation=False,
            decision_reason="两次学习反馈方向一致。",
        )

    monkeypatch.setattr("app.services.tutoring_service.TutoringAgent.execute", execute)
    monkeypatch.setattr(
        "app.services.learning_adjustment_service._analyze_profile",
        lambda _db, *, proposal, profile, path, **_kwargs: (
            profile,
            None,
            None,
            {"profile_changed": False, "ability_score_changes": {}},
        ),
    )
    app.dependency_overrides[get_db] = _override(factory)
    app.dependency_overrides[get_current_user] = lambda: Principal(
        "learner_user", "learner", "learner_001"
    )
    client = TestClient(app)
    try:
        session_id = client.post(
            "/api/v1/tutoring/sessions", json={"resource_id": "resource_m4a"}
        ).json()["data"]["session_id"]
        client.post(
            f"/api/v1/tutoring/sessions/{session_id}/messages",
            json={"content": "这部分太难"},
        )
        second = client.post(
            f"/api/v1/tutoring/sessions/{session_id}/messages",
            json={"content": "仍然无法理解"},
        ).json()["data"]
        assessment = second["reply"]["assessment"]
        assert assessment["hypothesis_type"] == "support_down"
        result = client.post(
            f"/api/v1/tutoring/sessions/{session_id}/assessments/{assessment['assessment_id']}/answers",
            json={"answer": 1},
        ).json()["data"]
        assert result["decision"] == "confirmed_support_need"
        assert result["current_node_id"] == RAG_NODE_ID
        assert result["resource_recommendation"] is None
        assert result["task_id"] is None
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


def test_path_refresh_event_requires_persisted_path_ids() -> None:
    factory = _session_factory()
    with factory() as db:
        _seed(db)
        task = db.query(GenerationTask).filter_by(public_id="task_m4a_source").one()
        without_path = _semantic_events(
            task,
            {
                "status": "completed",
                "step": "analyze_profile",
                "payload": {"profile_update_required": True},
            },
        )
        with_path = _semantic_events(
            task,
            {
                "status": "completed",
                "step": "analyze_profile",
                "payload": {
                    "profile_update_required": True,
                    "path_refresh": {
                        "old_path_id": "path_old",
                        "new_path_id": "path_new",
                    },
                },
            },
        )

        assert [name for name, _payload in without_path] == [
            "profile_update_decided",
            "profile_updated",
        ]
        assert [name for name, _payload in with_path] == [
            "profile_update_decided",
            "profile_updated",
            "path_refresh_completed",
        ]
        assert with_path[-1][1]["old_path_id"] == "path_old"
        assert with_path[-1][1]["new_path_id"] == "path_new"
