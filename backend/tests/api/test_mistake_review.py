from collections.abc import Generator
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import get_db
from app.core.security import Principal, get_current_user
from app.main import app
from app.models import (
    AnswerRecord,
    Base,
    DiagnosticQuestion,
    DiagnosticSession,
    GenerationTask,
    KnowledgeItem,
    Learner,
    LearnerProfile,
    LearningPath,
    LearningResource,
    MistakeReviewItem,
)
from app.services.mistake_review_service import sync_existing_mistakes


def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def override_db(factory: sessionmaker[Session]):
    def dependency() -> Generator[Session, None, None]:
        with factory() as db:
            yield db
    return dependency


def seed(factory: sessionmaker[Session]) -> None:
    with factory() as db:
        learner = Learner(public_id="learner_mistake", target_domain="ai_app_dev")
        db.add(learner)
        db.flush()
        knowledge = KnowledgeItem(
            public_id="knowledge_rag",
            domain_code="ai_app_dev",
            name="RAG检索",
            category="RAG",
            difficulty=2,
            content_md="content",
            source_title="source",
        )
        db.add(knowledge)
        db.flush()
        original = DiagnosticQuestion(
            public_id="question_original",
            domain_code="ai_app_dev",
            knowledge_item_id=knowledge.id,
            question_type="single_choice",
            stem="原题",
            options_json=["错误", "正确"],
            answer_key_json={"correct_option": 1},
            difficulty=2,
            status="active",
            certification_status="certified",
            certification_rule_version="question-cert-v1",
            source_content_hash="sha256:" + "d" * 64,
        )
        alternative = DiagnosticQuestion(
            public_id="question_alternative",
            domain_code="ai_app_dev",
            knowledge_item_id=knowledge.id,
            question_type="single_choice",
            stem="相似题",
            options_json=["错误", "正确"],
            answer_key_json={"correct_option": 1, "explanation": "应选择正确项"},
            difficulty=2,
            status="active",
            certification_status="certified",
            certification_rule_version="question-cert-v1",
            source_content_hash="sha256:" + "e" * 64,
        )
        corroborating = DiagnosticQuestion(
            public_id="question_corroborating",
            domain_code="ai_app_dev",
            knowledge_item_id=knowledge.id,
            question_type="single_choice",
            stem="另一道相似题",
            options_json=["错误", "正确"],
            answer_key_json={"correct_option": 1},
            difficulty=2,
            status="active",
            certification_status="certified",
            certification_rule_version="question-cert-v1",
            source_content_hash="sha256:" + "f" * 64,
        )
        db.add_all([original, alternative, corroborating])
        db.flush()
        db.add(DiagnosticSession(
            public_id="diagnostic_1",
            learner_id=learner.id,
            domain_code="ai_app_dev",
            status="scored",
            question_ids_json=[original.public_id],
        ))
        db.flush()
        db.add(AnswerRecord(
            learner_id=learner.id,
            question_id=original.id,
            knowledge_item_id=knowledge.id,
            session_id="diagnostic_1",
            answer_text="0",
            score=0,
            is_correct=False,
            scoring_status="scored",
            scoring_method="deterministic",
            confidence=1,
        ))
        profile = LearnerProfile(
            public_id="profile_mistake",
            learner_id=learner.id,
            domain_code="ai_app_dev",
            profile_source="initial_diagnosis",
            diagnosis_completed=True,
        )
        db.add(profile)
        db.flush()
        db.add(LearningPath(
            public_id="path_mistake",
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
            status="active",
            path_json={
                "current_node_id": "knowledge:knowledge_rag",
                "node_states": {
                    "knowledge:knowledge_rag": {
                        "knowledge_id": "knowledge_rag",
                        "status": "current",
                        "path_order": 1,
                    }
                },
            },
        ))
        task = GenerationTask(
            public_id="task_quiz",
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
            status="completed",
        )
        db.add(task)
        db.flush()
        db.add(LearningResource(
            public_id="resource_quiz",
            generation_task_id=task.id,
            resource_type="graded_quiz",
            title="分阶测试",
            content_md="quiz",
            difficulty=2,
            review_status="passed",
            sources_json=[{"knowledge_id": "knowledge_rag"}],
            structured_content_json={
                "questions": [{
                    "question_id": "generated_q1",
                    "question_type": "single_choice",
                    "prompt": "生成题",
                    "options": ["错误", "正确"],
                    "correct_answer": "正确",
                    "knowledge_id": "knowledge_rag",
                    "difficulty": 2,
                }]
            },
        ))
        db.commit()
        sync_existing_mistakes(db, learner=learner, domain_code="ai_app_dev")
        db.commit()


def test_mistake_review_lists_and_consolidates() -> None:
    factory = session_factory()
    seed(factory)
    app.dependency_overrides[get_db] = override_db(factory)
    app.dependency_overrides[get_current_user] = lambda: Principal(
        "user", "learner", "learner_mistake"
    )
    client = TestClient(app)
    try:
        response = client.get("/api/v1/mistake-review/items?domain_code=ai_app_dev")
        assert response.status_code == 200
        item = response.json()["data"]["items"][0]
        assert item["source_type"] == "initial_diagnostic"

        started = client.post(f"/api/v1/mistake-review/items/{item['item_id']}/start", json={})
        assert started.status_code == 200
        attempt = started.json()["data"]
        assert attempt["question"]["question_id"] == "question_alternative"

        resumed = client.post(f"/api/v1/mistake-review/items/{item['item_id']}/start", json={})
        assert resumed.status_code == 200
        assert resumed.json()["data"]["attempt_id"] == attempt["attempt_id"]

        answered = client.post(
            f"/api/v1/mistake-review/items/{item['item_id']}/attempts/{attempt['attempt_id']}/answer",
            json={"answer": 1},
        )
        assert answered.status_code == 200
        assert answered.json()["data"]["passed"] is True
        assert answered.json()["data"]["evidence"]["governance_status"] == "pending"
        assert answered.json()["data"]["profile_result"]["profile_updated"] is False
        repeated = client.post(
            f"/api/v1/mistake-review/items/{item['item_id']}/attempts/{attempt['attempt_id']}/answer",
            json={"answer": 1},
        )
        assert repeated.status_code == 200
        assert repeated.json()["data"]["evidence_ref"] == answered.json()["data"]["evidence_ref"]
        assert repeated.json()["data"]["evidence"] == answered.json()["data"]["evidence"]

        summary = client.get("/api/v1/mistake-review/summary?domain_code=ai_app_dev")
        assert summary.json()["data"]["consolidation_rate"] == 100.0
    finally:
        app.dependency_overrides.clear()


def test_admin_can_review_selected_learner_mistakes() -> None:
    factory = session_factory()
    seed(factory)
    app.dependency_overrides[get_db] = override_db(factory)
    app.dependency_overrides[get_current_user] = lambda: Principal("admin", "admin")
    client = TestClient(app)
    try:
        missing_context = client.get("/api/v1/mistake-review/summary?domain_code=ai_app_dev")
        assert missing_context.status_code == 422

        response = client.get(
            "/api/v1/mistake-review/items"
            "?domain_code=ai_app_dev&learner_id=learner_mistake"
        )
        assert response.status_code == 200
        assert response.json()["data"]["items"][0]["source_type"] == "initial_diagnostic"
    finally:
        app.dependency_overrides.clear()


def test_two_distinct_passes_are_evaluated_once(monkeypatch) -> None:
    factory = session_factory()
    seed(factory)
    calls = 0

    def fake_analyze(db, *, profile, path, **kwargs):
        nonlocal calls
        calls += 1
        return profile, None, SimpleNamespace(decision_reason="正式证据充分，画像保持不变"), {}

    monkeypatch.setattr("app.services.learning_adjustment_service._analyze_profile", fake_analyze)
    app.dependency_overrides[get_db] = override_db(factory)
    app.dependency_overrides[get_current_user] = lambda: Principal(
        "user", "learner", "learner_mistake"
    )
    client = TestClient(app)
    try:
        item = client.get(
            "/api/v1/mistake-review/items?domain_code=ai_app_dev"
        ).json()["data"]["items"][0]
        results = []
        for _ in range(2):
            attempt = client.post(
                f"/api/v1/mistake-review/items/{item['item_id']}/start", json={}
            ).json()["data"]
            results.append(client.post(
                f"/api/v1/mistake-review/items/{item['item_id']}/attempts/{attempt['attempt_id']}/answer",
                json={"answer": 1},
            ).json()["data"])
        assert results[0]["evidence"]["governance_status"] == "pending"
        assert results[1]["evidence"]["governance_status"] == "no_change"
        assert results[1]["profile_result"]["evaluated"] is True
        repeated = client.post(
            f"/api/v1/mistake-review/items/{item['item_id']}/attempts/{attempt['attempt_id']}/answer",
            json={"answer": 1},
        ).json()["data"]
        assert repeated["evidence"] == results[1]["evidence"]
        assert calls == 1
    finally:
        app.dependency_overrides.clear()


def test_resource_quiz_attempt_is_server_scored_and_creates_mistake() -> None:
    factory = session_factory()
    seed(factory)
    app.dependency_overrides[get_db] = override_db(factory)
    app.dependency_overrides[get_current_user] = lambda: Principal(
        "user", "learner", "learner_mistake"
    )
    client = TestClient(app)
    try:
        started = client.post("/api/v1/resources/resource_quiz/quiz-attempts", json={})
        assert started.status_code == 200
        attempt_id = started.json()["data"]["attempt_id"]
        answer = client.put(
            f"/api/v1/resources/resource_quiz/quiz-attempts/{attempt_id}/answers/generated_q1",
            json={"answer": ["错误"]},
        )
        assert answer.status_code == 200
        assert answer.json()["data"]["correct"] is False
        listed = client.get(
            "/api/v1/mistake-review/items"
            "?domain_code=ai_app_dev&source_type=graded_quiz"
        )
        quiz_item = listed.json()["data"]["items"][0]
        detail = client.get(f"/api/v1/mistake-review/items/{quiz_item['item_id']}")
        assert detail.status_code == 200
        assert detail.json()["data"]["question"]["stem"] == "生成题"
        assert detail.json()["data"]["question"]["options"] == ["错误", "正确"]
        with factory() as db:
            mistake = db.scalar(
                select(MistakeReviewItem).where(MistakeReviewItem.source_type == "graded_quiz")
            )
            assert mistake is not None
    finally:
        app.dependency_overrides.clear()
