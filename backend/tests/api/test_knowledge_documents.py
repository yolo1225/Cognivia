from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import get_db
from app.main import app
from app.models import Base, Domain
from app.services import knowledge_document_service


def test_document_upload_is_isolated_by_domain(tmp_path, monkeypatch) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with testing_session() as db:
        db.add_all(
            [
                Domain(domain_code="domain_a", name="领域 A", config_json={}),
                Domain(domain_code="domain_b", name="领域 B", config_json={}),
            ]
        )
        db.commit()

    monkeypatch.setattr(knowledge_document_service, "KNOWLEDGE_STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(
        "app.api.v1.knowledge_documents._schedule_import", lambda _run_id: None
    )

    def override_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    payload = b"# RAG document\n\nThis is enough text for a domain knowledge document."
    try:
        first = client.post(
            "/api/v1/knowledge/documents",
            params={"domain_code": "domain_a"},
            content=payload,
            headers={"X-File-Name": "guide.md", "Content-Type": "text/markdown"},
        )
        assert first.status_code == 200
        duplicate = client.post(
            "/api/v1/knowledge/documents",
            params={"domain_code": "domain_a"},
            content=payload,
            headers={"X-File-Name": "copy.md", "Content-Type": "text/markdown"},
        )
        assert duplicate.status_code == 409
        second_domain = client.post(
            "/api/v1/knowledge/documents",
            params={"domain_code": "domain_b"},
            content=payload,
            headers={"X-File-Name": "guide.md", "Content-Type": "text/markdown"},
        )
        assert second_domain.status_code == 200

        domain_a = client.get(
            "/api/v1/knowledge/documents", params={"domain_code": "domain_a"}
        ).json()["data"]
        domain_b = client.get(
            "/api/v1/knowledge/documents", params={"domain_code": "domain_b"}
        ).json()["data"]
        assert [item["domain_code"] for item in domain_a["documents"]] == ["domain_a"]
        assert [item["domain_code"] for item in domain_b["documents"]] == ["domain_b"]
    finally:
        app.dependency_overrides.clear()


def test_document_upload_rejects_invalid_and_oversized_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(knowledge_document_service, "KNOWLEDGE_STORAGE_ROOT", tmp_path)
    try:
        knowledge_document_service.validate_upload("bad.exe", b"content")
        raise AssertionError("invalid extension accepted")
    except knowledge_document_service.KnowledgeDocumentError:
        pass
