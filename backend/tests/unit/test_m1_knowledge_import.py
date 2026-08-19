from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, KnowledgeDocument, KnowledgeImportCandidate, KnowledgeItem
from app.services.knowledge_extraction_service import replace_candidates
from app.services.knowledge_import_publish_service import approve_candidates, publish_approved
from app.services.knowledge_import_validation_service import validate_import
from app.services.knowledge_parser_service import parse_document


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False)()


def _document(tmp_path: Path) -> KnowledgeDocument:
    path = tmp_path / "guide.md"
    path.write_text(
        "# RAG 基础\n\n检索增强生成需要可靠来源。\n\n## 检索\n\n向量检索返回相关知识切片。",
        encoding="utf-8",
    )
    return KnowledgeDocument(
        public_id="kdoc_test",
        domain_code="ai_app_dev",
        original_name=path.name,
        stored_path=path.name,
        file_type="markdown",
        mime_type="text/markdown",
        size_bytes=path.stat().st_size,
        sha256="a" * 64,
        status="parsing",
        source_title="测试教材",
        license_note="test",
        uploaded_by="tester",
    )


def test_multisection_document_creates_traceable_candidates(tmp_path, monkeypatch) -> None:
    from app.services import knowledge_document_service

    monkeypatch.setattr(knowledge_document_service, "KNOWLEDGE_STORAGE_ROOT", tmp_path)
    db = _session()
    document = _document(tmp_path)
    db.add(document)
    db.commit()
    sections = parse_document(document)
    candidates = replace_candidates(db, document, sections)
    db.commit()
    assert len(sections) == 2
    assert sum(item.candidate_type == "knowledge_item" for item in candidates) == 2
    assert all(item.source_locator_json.get("checksum") for item in candidates)
    assert validate_import(db, document.id)["invalid"] == 0


def test_invalid_source_and_self_relation_block_approval(tmp_path, monkeypatch) -> None:
    from app.services import knowledge_document_service

    monkeypatch.setattr(knowledge_document_service, "KNOWLEDGE_STORAGE_ROOT", tmp_path)
    db = _session()
    document = _document(tmp_path)
    db.add(document)
    db.commit()
    candidates = replace_candidates(db, document, parse_document(document))
    db.commit()
    relation = next(item for item in candidates if item.candidate_type == "knowledge_relation")
    relation.payload_json = {
        **relation.payload_json,
        "target_candidate_id": relation.payload_json["source_candidate_id"],
    }
    relation.source_locator_json = {}
    db.commit()
    assert validate_import(db, document.id)["invalid"] >= 1
    assert db.get(KnowledgeImportCandidate, relation.id).status == "needs_edit"


def test_approved_candidates_publish_multiple_items(tmp_path, monkeypatch) -> None:
    from app.services import knowledge_document_service

    monkeypatch.setattr(knowledge_document_service, "KNOWLEDGE_STORAGE_ROOT", tmp_path)
    db = _session()
    document = _document(tmp_path)
    db.add(document)
    db.commit()
    replace_candidates(db, document, parse_document(document))
    db.commit()
    assert validate_import(db, document.id)["invalid"] == 0
    approve_candidates(db, document)
    result = publish_approved(db, document)
    assert result == {"knowledge_items": 2, "relations": 1, "questions": 2}
    items = list(db.scalars(select(KnowledgeItem)))
    assert len(items) == 2
    assert all(item.status == "published" and item.source_locator_json for item in items)
