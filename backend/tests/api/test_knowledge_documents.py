from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import get_db
from app.main import app
from app.models import Base, Domain, KnowledgeDocument, KnowledgeItem
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
        "app.api.v1.knowledge_documents.process_knowledge_document", lambda _document_id: None
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


def test_text_document_is_parsed_into_internal_knowledge_and_marked_ready(
    tmp_path, monkeypatch
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(knowledge_document_service, "KNOWLEDGE_STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(knowledge_document_service, "SessionLocal", testing_session)
    monkeypatch.setattr(knowledge_document_service, "build_index", lambda **_kwargs: {})
    monkeypatch.setattr(
        knowledge_document_service, "_rebuild_candidate_index", lambda *_args: {}
    )
    monkeypatch.setattr(knowledge_document_service, "embedding_model_name", lambda: "test-embed")
    with testing_session() as db:
        document = knowledge_document_service.create_document(
            db,
            domain_code="domain_a",
            original_name="rag-guide.txt",
            content=b"RAG retrieval guide.\n\nThis document contains enough text to be indexed safely.",
            mime_type="text/plain",
            source_title="RAG Guide",
            license_note="test",
            uploaded_by="tester",
        )
        document_id = document.public_id

    knowledge_document_service.process_knowledge_document(document_id)

    with testing_session() as db:
        stored = db.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.public_id == document_id)
        )
        item = db.scalar(
            select(KnowledgeItem).where(KnowledgeItem.source_document_id == stored.id)
        )
        assert stored.status == "ready"
        assert stored.chunk_count >= 1
        assert stored.embedding_model == "test-embed"
        assert item is not None
        assert item.domain_code == "domain_a"
        assert item.source_title == "RAG Guide"
    try:
        knowledge_document_service.validate_upload(
            "large.txt", b"x" * (knowledge_document_service.MAX_FILE_BYTES + 1)
        )
        raise AssertionError("oversized upload accepted")
    except knowledge_document_service.KnowledgeDocumentError:
        pass
