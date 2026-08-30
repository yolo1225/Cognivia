from collections.abc import Generator
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import get_db
from app.core.security import Principal, get_current_user
from app.main import app
from app.models import (
    Base,
    Feedback,
    GenerationTask,
    Learner,
    LearnerProfile,
    LearningPath,
    LearningResource,
    ReviewReport,
)
from app.services.report_service import build_learning_progress_comparison


def build_test_session() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def make_override(testing_session: sessionmaker[Session]):
    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    return override_get_db


def test_report_returns_empty_loop_summary_for_new_learner() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        db.add(
            Learner(
                public_id="learner_report_empty",
                background="new learner",
                target_domain="ai_app_dev",
                experience_years=0,
                learning_style="mixed",
            )
        )
        db.commit()

    app.dependency_overrides[get_db] = make_override(testing_session)
    app.dependency_overrides[get_current_user] = lambda: Principal(
        "test_learner", "learner", "learner_report_empty"
    )
    try:
        response = TestClient(app).get("/api/v1/reports/learners/learner_report_empty")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["loop_status"]["profile"] == "pending"
    assert data["loop_status"]["generation"] == "pending"
    assert data["resource_summary"]["total"] == 0
    assert data["review_summary"]["total_reports"] == 0
    assert data["feedback_summary"]["total"] == 0
    assert data["next_actions"][0]["type"] == "diagnosis"


def test_report_persists_path_normalization_without_refresh_flag() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner = Learner(
            public_id="learner_report_normalized_path",
            target_domain="ai_app_dev",
        )
        db.add(learner)
        db.flush()
        profile = LearnerProfile(
            public_id="profile_report_normalized_path",
            learner_id=learner.id,
            domain_code="ai_app_dev",
            ability_profile_json={"profile_type": "beginner"},
            weak_knowledge_json=[],
            diagnosis_completed=True,
            profile_source="diagnostic",
        )
        db.add(profile)
        db.flush()
        db.add(
            LearningPath(
                public_id="path_report_normalized_path",
                learner_id=learner.id,
                profile_id=profile.id,
                domain_code="ai_app_dev",
                path_json={"stages": [{"name": "Stage 1", "knowledge_ids": ["k1"]}]},
                needs_refresh=False,
            )
        )
        db.commit()

    app.dependency_overrides[get_db] = make_override(testing_session)
    app.dependency_overrides[get_current_user] = lambda: Principal(
        "test_learner", "learner", "learner_report_normalized_path"
    )
    try:
        response = TestClient(app).get("/api/v1/reports/learners/learner_report_normalized_path")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["data"]["node_gate"]["can_advance"] is False
    assert response.json()["data"]["node_gate"]["reason"] == "GRADED_QUIZ_REQUIRED"
    with testing_session() as db:
        path = db.scalar(
            select(LearningPath).where(
                LearningPath.public_id == "path_report_normalized_path"
            )
        )
        assert path is not None
        assert path.path_json["current_node_id"]
        assert path.path_json["node_states"]


def test_report_summarizes_resources_reviews_feedback_and_path_refresh() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner = Learner(
            public_id="learner_report_ready",
            background="ready learner",
            target_domain="ai_app_dev",
            experience_years=1,
            learning_style="practice",
        )
        db.add(learner)
        db.flush()

        profile = LearnerProfile(
            public_id="profile_report_ready",
            learner_id=learner.id,
            domain_code="ai_app_dev",
            ability_profile_json={
                "profile_type": "intermediate",
                "theory": 70,
                "practice": 75,
                "problem_solving": 68,
                "breadth": 60,
                "learning_speed": 72,
            },
            weak_knowledge_json=[],
            diagnosis_completed=True,
            profile_source="diagnostic",
            context_snapshot_json={
                "education_level": "本科",
                "major": "软件工程",
                "direction_tags": ["rag_knowledge_base"],
                "confirmed_at": "2026-08-18T00:00:00+00:00",
            },
        )
        db.add(profile)
        db.flush()

        task = GenerationTask(
            public_id="task_report_ready",
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
            status="completed",
            resource_types_json=["lecture", "practice_guide", "graded_quiz"],
            decision="passed",
        )
        db.add(task)
        db.flush()

        resources = [
            LearningResource(
                public_id="res_report_lecture",
                generation_task_id=task.id,
                resource_type="lecture",
                title="Lecture",
                content_md="content",
                difficulty=3,
                learner_profile_type="intermediate",
                sources_json=[{"knowledge_id": "ki_1"}, {"knowledge_id": "ki_2"}],
                review_status="passed",
            ),
            LearningResource(
                public_id="res_report_practice",
                generation_task_id=task.id,
                resource_type="practice_guide",
                title="Practice",
                content_md="content",
                difficulty=3,
                learner_profile_type="intermediate",
                sources_json=[{"knowledge_id": "ki_2"}],
                review_status="passed",
            ),
            LearningResource(
                public_id="res_report_rejected",
                generation_task_id=task.id,
                resource_type="graded_quiz",
                title="Rejected quiz",
                content_md="content",
                difficulty=3,
                learner_profile_type="intermediate",
                sources_json=[{"knowledge_id": "ki_3"}],
                review_status="failed",
            ),
            LearningResource(
                public_id="res_report_old_lecture",
                generation_task_id=task.id,
                resource_type="lecture",
                title="Old lecture",
                content_md="content",
                difficulty=2,
                learner_profile_type="intermediate",
                sources_json=[{"knowledge_id": "ki_4"}],
                review_status="passed",
                is_current=False,
            ),
        ]
        db.add_all(resources)
        db.flush()

        db.add_all(
            [
                ReviewReport(resource_id=resources[0].id, passed=False, difficulty_match_score=76.0),
                ReviewReport(resource_id=resources[0].id, passed=True, difficulty_match_score=92.0),
                ReviewReport(resource_id=resources[1].id, passed=True, difficulty_match_score=84.5),
                Feedback(
                    resource_id=resources[0].id,
                    learner_id=learner.id,
                    rating=3,
                    feedback_type="confusing",
                    feedback_summary_json={},
                    triggered_action="remedial_explanation",
                ),
                LearningPath(
                    public_id="path_report_ready",
                    learner_id=learner.id,
                    profile_id=profile.id,
                    domain_code="ai_app_dev",
                    path_json={"stages": [{"name": "Stage 1"}]},
                    needs_refresh=True,
                ),
            ]
        )
        db.commit()

    app.dependency_overrides[get_db] = make_override(testing_session)
    app.dependency_overrides[get_current_user] = lambda: Principal(
        "test_learner", "learner", "learner_report_ready"
    )
    try:
        response = TestClient(app).get("/api/v1/reports/learners/learner_report_ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["loop_status"]["profile"] == "completed"
    assert data["loop_status"]["generation"] == "completed"
    assert data["loop_status"]["review"] == "completed"
    assert data["loop_status"]["feedback"] == "completed"
    assert data["loop_status"]["path_update"] == "refreshed"
    assert data["resource_summary"]["total"] == 2
    assert data["resource_summary"]["by_type"]["lecture"] == 1
    difficulty_scores = {
        resource["resource_id"]: resource["difficulty_match_score"]
        for resource in data["resource_summary"]["recent"]
    }
    assert difficulty_scores == {
        "res_report_practice": 84.5,
        "res_report_lecture": 92.0,
    }
    assert data["review_summary"]["passed"] == 2
    assert data["review_summary"]["source_coverage"] == 2
    assert data["feedback_summary"]["total"] == 1
    assert data["feedback_summary"]["latest_action"] == "remedial_explanation"
    assert data["feedback_summary"]["learning_path_needs_refresh"] is False
    assert data["feedback_summary"]["path_refresh_performed"] is True
    assert "metrics" not in data
    assert "learning_history" not in data
    with testing_session() as db:
        path = db.scalar(select(LearningPath).where(LearningPath.public_id == "path_report_ready"))
        assert path is not None
        assert path.needs_refresh is False
        assert path.path_json["refreshed_at"]


def test_learning_journey_groups_feedback_with_its_resource_adjustment() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner = Learner(public_id="learner_journey", target_domain="ai_app_dev")
        db.add(learner)
        db.flush()
        profile = LearnerProfile(
            public_id="profile_journey",
            learner_id=learner.id,
            domain_code="ai_app_dev",
            diagnosis_completed=True,
            profile_source="diagnostic",
            ability_profile_json={"profile_type": "beginner"},
        )
        db.add(profile)
        db.flush()
        initial_task = GenerationTask(
            public_id="task_journey_initial",
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
            status="completed",
            decision="passed",
        )
        db.add(initial_task)
        db.flush()
        initial_resource = LearningResource(
            public_id="res_journey_initial",
            generation_task_id=initial_task.id,
            resource_type="lecture",
            title="RAG 入门讲义",
            content_md="content",
            difficulty=2,
            review_status="passed",
            is_current=False,
            created_at=datetime(2026, 8, 27, 4, 47, tzinfo=UTC),
        )
        db.add(initial_resource)
        db.flush()
        feedback = Feedback(
            resource_id=initial_resource.id,
            learner_id=learner.id,
            feedback_type="too_hard",
            feedback_summary_json={},
            triggered_action="remedial_explanation",
            affected_knowledge_ids_json=["rag_basics"],
        )
        db.add(feedback)
        db.flush()
        adjustment_task = GenerationTask(
            public_id="task_journey_feedback",
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
            status="completed",
            trigger_type="resource_feedback",
            event_type="resource_feedback",
            source_feedback_id=feedback.id,
            decision="passed",
        )
        db.add(adjustment_task)
        db.flush()
        db.add_all(
            [
                LearningResource(
                    public_id="res_journey_adjustment",
                    generation_task_id=adjustment_task.id,
                    resource_type="practice_guide",
                    title="RAG 补充练习",
                    content_md="content",
                    difficulty=1,
                    review_status="passed",
                ),
                GenerationTask(
                    public_id="task_journey_other_domain",
                    learner_id=learner.id,
                    profile_id=profile.id,
                    domain_code="another_domain",
                    status="completed",
                    decision="passed",
                ),
                LearningPath(
                    public_id="path_journey",
                    learner_id=learner.id,
                    profile_id=profile.id,
                    domain_code="ai_app_dev",
                    path_json={
                        "node_states": {
                            "node_rag": {
                                "path_node_id": "node_rag",
                                "title": "RAG 基础",
                                "status": "completed",
                                "completed_at": "2026-08-27T10:00:00+00:00",
                            }
                        }
                    },
                ),
            ]
        )
        initial_task.updated_at = datetime(2026, 8, 27, 6, 39, tzinfo=UTC)
        db.commit()

    app.dependency_overrides[get_db] = make_override(testing_session)
    app.dependency_overrides[get_current_user] = lambda: Principal(
        "test_learner", "learner", "learner_journey"
    )
    try:
        response = TestClient(app).get("/api/v1/reports/learners/learner_journey/learning-journey")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["domain_code"] == "ai_app_dev"
    assert data["overview"]["available_resource_count"] == 2
    assert data["overview"]["feedback_adjustment_count"] == 1
    feedback_events = [item for item in data["milestones"] if item["type"] == "feedback_adjustment"]
    assert len(feedback_events) == 1
    assert feedback_events[0]["title"] == "根据反馈补充学习支持"
    assert feedback_events[0]["resources"][0]["title"] == "RAG 补充练习"
    assert feedback_events[0]["actions"][0]["route"] == "/resources?task_id=task_journey_feedback"
    initial_generation = next(
        item
        for item in data["milestones"]
        if item["milestone_id"] == "task:task_journey_initial"
    )
    assert initial_generation["occurred_at"] == "2026-08-27T04:47:00"
    assert data["milestones"].index(feedback_events[0]) < data["milestones"].index(
        initial_generation
    )
    assert any(item["type"] == "path_progress" for item in data["milestones"])
    assert all("agent" not in str(item).lower() for item in data["milestones"])
    assert data["milestones"] == sorted(
        data["milestones"], key=lambda item: (item["occurred_at"], item["milestone_id"]), reverse=True
    )


def test_progress_comparison_labels_new_formal_partial_mastery_as_evidence() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner = Learner(public_id="learner_state_diff", target_domain="ai_app_dev")
        db.add(learner)
        db.flush()
        baseline = LearnerProfile(
            public_id="profile_state_v2",
            learner_id=learner.id,
            domain_code="ai_app_dev",
            profile_version=2,
            diagnosis_completed=True,
            profile_source="diagnostic",
            ability_profile_json={
                "theory": 50,
                "practice": 50,
                "problem_solving": 50,
                "breadth": 20,
                "learning_speed": 50,
                "knowledge_state_v1": {
                    "version": "knowledge-state-v1",
                    "items": {
                        "rag_basics": {
                            "knowledge_id": "rag_basics",
                            "name": "RAG 基础",
                            "status": "unassessed",
                            "mastery_score": 0.5,
                            "evidence_count": 0,
                        }
                    },
                },
            },
        )
        db.add(baseline)
        db.flush()
        current = LearnerProfile(
            public_id="profile_state_v3",
            learner_id=learner.id,
            domain_code="ai_app_dev",
            profile_version=3,
            previous_profile_id=baseline.id,
            diagnosis_completed=True,
            profile_source="feedback_revision",
            ability_profile_json={
                "theory": 52,
                "practice": 50,
                "problem_solving": 50,
                "breadth": 22,
                "learning_speed": 50,
                "knowledge_state_v1": {
                    "version": "knowledge-state-v1",
                    "items": {
                        "rag_basics": {
                            "knowledge_id": "rag_basics",
                            "name": "RAG 基础",
                            "status": "partial_mastery",
                            "mastery_score": 0.75,
                            "evidence_count": 1,
                        }
                    },
                },
            },
        )
        db.add(current)
        db.flush()
        path = LearningPath(
            public_id="path_state_diff",
            learner_id=learner.id,
            profile_id=current.id,
            domain_code="ai_app_dev",
            path_json={"node_states": {}},
        )
        db.add(path)
        db.commit()
        result = build_learning_progress_comparison(
            db, learner=learner, current_profile=current, path=path
        )

    changes = result["knowledge_changes"]
    assert [item["knowledge_id"] for item in changes["new_evidence"]] == ["rag_basics"]
    assert changes["new_weakness"] == []
    assert changes["new_evidence"][0]["after_status"] == "partial_mastery"
    assert changes["new_evidence"][0]["after_evidence_count"] == 1


def test_learning_journey_is_empty_and_learner_scoped() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        db.add_all(
            [
                Learner(public_id="learner_journey_empty", target_domain="ai_app_dev"),
                Learner(public_id="learner_journey_other", target_domain="ai_app_dev"),
            ]
        )
        db.commit()

    app.dependency_overrides[get_db] = make_override(testing_session)
    app.dependency_overrides[get_current_user] = lambda: Principal(
        "test_learner", "learner", "learner_journey_empty"
    )
    try:
        response = TestClient(app).get("/api/v1/reports/learners/learner_journey_empty/learning-journey")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["data"]["milestones"] == []
    assert response.json()["data"]["overview"]["available_resource_count"] == 0

    app.dependency_overrides[get_db] = make_override(testing_session)
    app.dependency_overrides[get_current_user] = lambda: Principal(
        "test_learner", "learner", "learner_journey_other"
    )
    try:
        forbidden = TestClient(app).get("/api/v1/reports/learners/learner_journey_empty/learning-journey")
    finally:
        app.dependency_overrides.clear()

    assert forbidden.status_code == 403
