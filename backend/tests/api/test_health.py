from fastapi.testclient import TestClient
from contextlib import nullcontext
from types import SimpleNamespace

from app.main import app
from app.core.config import settings


def test_health_response_shape():
    client = TestClient(app)
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "1.0"
    assert body["data"]["status"] == "ok"
    assert body["error"] is None


def test_dependency_health_hides_key_and_reports_model_readiness(monkeypatch):
    monkeypatch.setattr("app.api.v1.health.check_database_connection", lambda: {"status": "ok"})
    monkeypatch.setattr(
        "app.api.v1.health.get_vector_store",
        lambda: type("Store", (), {"health_check": lambda self: {"status": "ok"}})(),
    )
    monkeypatch.setattr(settings, "openai_api_key", "secret-key")
    monkeypatch.setattr(settings, "primary_llm_model", "generation-model")
    monkeypatch.setattr(settings, "primary_review_model", "review-model-a")
    monkeypatch.setattr(settings, "secondary_review_model", "review-model-b")
    monkeypatch.setattr(settings, "allow_fixture_llm", False)
    monkeypatch.setattr(settings, "enable_evaluation_overrides", False)

    response = TestClient(app).get("/api/v1/health/dependencies")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["ready_for_live_demo"] is True
    assert data["review_models_distinct"] is True
    assert data["evaluation_overrides_enabled"] is False
    assert "secret-key" not in response.text


def test_dependency_health_reports_requested_domain_runtime(monkeypatch):
    monkeypatch.setattr("app.api.v1.health.SessionLocal", lambda: nullcontext(object()))

    def runtime(_db, domain_code):
        ready = domain_code == "ready_domain"
        return SimpleNamespace(
            readiness_payload=lambda: {
                "domain_code": domain_code,
                "display_name": domain_code,
                "profile_ready": ready,
                "diagnostic_ready": ready,
                "rag_ready": ready,
                "generation_ready": ready,
                "reasons": [] if ready else ["diagnostic_distribution_insufficient"],
                "knowledge_item_count": 2 if ready else 1,
                "diagnostic_question_count": 10 if ready else 2,
                "relation_count": 1 if ready else 0,
                "rag": {"ready": ready, "domain_code": domain_code},
            }
        )

    monkeypatch.setattr("app.api.v1.health.load_domain_runtime", runtime)
    client = TestClient(app)
    ready = client.get("/api/v1/health/dependencies?domain_code=ready_domain").json()["data"]
    blocked = client.get("/api/v1/health/dependencies?domain_code=blocked_domain").json()["data"]

    assert ready["domain_runtime"]["generation_ready"] is True
    assert ready["rag"]["domain_code"] == "ready_domain"
    assert blocked["domain_runtime"]["generation_ready"] is False
    assert blocked["rag"]["domain_code"] == "blocked_domain"
