from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import get_db
from app.core.security import Principal, get_current_user
from app.main import app
from app.models import Base, Domain, Learner, LearnerProfile


def build_test_session() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def override_db(testing_session: sessionmaker[Session]):
    def get_test_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    return get_test_db


def seed_domains(db: Session) -> None:
    db.add_all(
        [
            Domain(
                domain_code="ready_domain",
                name="可用领域",
                status="ready",
                config_json={"learning_directions": [{"value": "general", "label": "综合"}]},
            ),
            Domain(
                domain_code="draft_domain",
                name="草稿领域",
                status="draft",
                config_json={"learning_directions": [{"value": "general", "label": "综合"}]},
            ),
        ]
    )
    db.commit()


def test_domain_list_visibility_and_learner_cannot_manage_domains() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        seed_domains(db)
    app.dependency_overrides[get_db] = override_db(testing_session)
    principal = Principal("learner_user", "learner", "learner_001")
    app.dependency_overrides[get_current_user] = lambda: principal
    client = TestClient(app)
    try:
        response = client.get("/api/v1/domains")
        assert response.status_code == 200
        assert [item["domain_code"] for item in response.json()["data"]] == ["ready_domain"]

        payload = {
            "domain_code": "new_domain",
            "name": "新领域",
            "learning_directions": [{"value": "general", "label": "综合"}],
        }
        assert client.post("/api/v1/domains", json=payload).status_code == 403
        assert (
            client.patch("/api/v1/domains/draft_domain", json={"name": "修改"}).status_code == 403
        )
        assert client.get("/api/v1/domains/draft_domain/readiness").status_code == 403
        assert client.get("/api/v1/domains/draft_domain/validate").status_code == 403
        assert client.post("/api/v1/domains/draft_domain/publish").status_code == 403
        assert client.post("/api/v1/domains/ready_domain/disable").status_code == 403

        app.dependency_overrides[get_current_user] = lambda: Principal("admin", "admin")
        admin_domains = client.get("/api/v1/domains").json()["data"]
        assert {item["domain_code"] for item in admin_domains} == {
            "ready_domain",
            "draft_domain",
        }
    finally:
        app.dependency_overrides.clear()


def test_publish_failure_uses_structured_readiness_error(monkeypatch) -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        seed_domains(db)
    monkeypatch.setattr(
        "app.services.domain_api_service.candidate_rag_status",
        lambda _domain: {"ready": False, "reason": "candidate_manifest_missing"},
    )
    app.dependency_overrides[get_db] = override_db(testing_session)
    app.dependency_overrides[get_current_user] = lambda: Principal("admin", "admin")
    client = TestClient(app)
    try:
        response = client.post("/api/v1/domains/draft_domain/publish")
        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "DOMAIN_READINESS_FAILED"
        readiness = error["details"]["readiness"]
        assert readiness["passed"] is False
        assert {item["key"] for item in readiness["checks"]} >= {
            "published_knowledge",
            "diagnostic_questions",
            "candidate_rag_ready",
            "retrieval_smoke_passed",
        }
    finally:
        app.dependency_overrides.clear()


def test_target_domain_switch_restores_domain_specific_profile() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        db.add_all(
            [
                Domain(domain_code="domain_a", name="领域 A", status="ready", config_json={}),
                Domain(domain_code="domain_b", name="领域 B", status="ready", config_json={}),
            ]
        )
        learner = Learner(
            public_id="learner_switch",
            target_domain="domain_a",
            direction_tags_json=["old_direction"],
        )
        db.add(learner)
        db.flush()
        db.add_all(
            [
                LearnerProfile(
                    public_id="profile_a",
                    learner_id=learner.id,
                    domain_code="domain_a",
                    ability_profile_json={"profile_type": "beginner"},
                    weak_knowledge_json=[],
                    diagnosis_completed=True,
                ),
                LearnerProfile(
                    public_id="profile_b",
                    learner_id=learner.id,
                    domain_code="domain_b",
                    ability_profile_json={"profile_type": "advanced"},
                    weak_knowledge_json=[],
                    diagnosis_completed=True,
                ),
            ]
        )
        db.commit()

    app.dependency_overrides[get_db] = override_db(testing_session)
    app.dependency_overrides[get_current_user] = lambda: Principal(
        "learner_user", "learner", "learner_switch"
    )
    client = TestClient(app)
    try:
        switched = client.put(
            "/api/v1/learners/learner_switch/target-domain",
            json={"domain_code": "domain_b"},
        ).json()["data"]
        assert switched["target_domain"] == "domain_b"
        assert switched["latest_profile_id"] == "profile_b"
        assert switched["direction_tags"] == []

        restored = client.put(
            "/api/v1/learners/learner_switch/target-domain",
            json={"domain_code": "domain_a"},
        ).json()["data"]
        assert restored["latest_profile_id"] == "profile_a"
    finally:
        app.dependency_overrides.clear()
