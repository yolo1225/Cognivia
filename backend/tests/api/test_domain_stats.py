from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import get_db
from app.main import app
from app.models import (
    Base,
    DiagnosticQuestion,
    GenerationTask,
    KnowledgeItem,
    Learner,
    LearnerProfile,
    LearningResource,
)


def test_domain_stats_return_real_database_counts() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    with testing_session() as db:
        knowledge = KnowledgeItem(
            public_id="knowledge_001",
            domain_code="ai_app_dev",
            name="测试知识点",
            category="测试",
            difficulty=1,
            tags_json=[],
            content_md="测试内容",
            source_title="测试来源",
        )
        learner = Learner(
            public_id="learner_001",
            background="test",
            target_domain="ai_app_dev",
            learning_style="mixed",
        )
        db.add_all([knowledge, learner])
        db.flush()
        profile = LearnerProfile(
            public_id="profile_001",
            learner_id=learner.id,
            ability_profile_json={},
            weak_knowledge_json=[],
        )
        question = DiagnosticQuestion(
            public_id="question_001",
            domain_code="ai_app_dev",
            knowledge_item_id=knowledge.id,
            question_type="single_choice",
            stem="测试题目",
            options_json=["A", "B"],
            answer_key_json={"correct_option": 0},
            difficulty=1,
        )
        db.add_all([profile, question])
        db.flush()
        task = GenerationTask(
            public_id="task_001",
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
        )
        db.add(task)
        db.flush()
        db.add_all(
            [
                LearningResource(
                    public_id="resource_published",
                    generation_task_id=task.id,
                    resource_type="lecture",
                    title="已发布",
                    content_md="正文",
                    review_status="passed",
                    is_current=True,
                ),
                LearningResource(
                    public_id="resource_draft",
                    generation_task_id=task.id,
                    resource_type="lecture",
                    title="草稿",
                    content_md="正文",
                    review_status="pending",
                    is_current=True,
                ),
            ]
        )
        db.commit()

    def override_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get("/api/v1/domains/ai_app_dev/stats")
        assert response.status_code == 200
        assert response.json()["data"] == {
            "domain_code": "ai_app_dev",
            "knowledge_items": 1,
            "diagnostic_questions": 1,
            "knowledge_relations": 0,
            "pending_embeddings": 1,
            "knowledge_documents": 0,
            "ready_documents": 0,
            "failed_documents": 0,
            "document_chunks": 0,
            "published_resources": 1,
        }
    finally:
        app.dependency_overrides.clear()
