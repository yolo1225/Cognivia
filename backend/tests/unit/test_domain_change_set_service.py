from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import (
    Base,
    DiagnosticQuestion,
    Domain,
    DomainChangeSet,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeImportCandidate,
    KnowledgeItem,
    KnowledgeItemSource,
    QuestionImportRow,
    QuestionImportRun,
)
from app.services.knowledge_document_service import delete_document
from app.services.knowledge_model_import_service import generate_cross_document_relations


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_delta_relation_candidates_can_link_to_existing_domain_knowledge() -> None:
    db = _db()
    existing = KnowledgeItem(
        public_id="ki_existing", domain_code="incremental", name="向量检索",
        category="RAG", difficulty=2, tags_json=["rag", "retrieval"],
        content_md="向量检索用于从知识库中召回相关内容。",
        source_title="既有资料", license_note="test", status="published",
    )
    document = KnowledgeDocument(
        public_id="kdoc_delta", domain_code="incremental", original_name="delta.md",
        file_type="markdown", mime_type="text/markdown", sha256="d" * 64,
        source_title="新增资料", license_note="test", status="extracting",
    )
    db.add_all([existing, document])
    db.flush()
    candidate = KnowledgeImportCandidate(
        public_id="kic_new", document_id=document.id, domain_code="incremental",
        candidate_type="knowledge_item",
        payload_json={
            "name": "检索链路设计", "tags": ["rag", "retrieval"],
            "content": "检索链路设计依赖向量检索，先完成召回再组织回答。",
            "source_quote": "检索链路设计依赖向量检索。",
            "source_chunk_ids": ["kic_new::chunk::000"], "after_checksum": "new",
        },
        source_locator_json={"chunk_id": "kic_new::chunk::000", "checksum": "new"},
        status="pending", validation_errors_json=[],
    )
    db.add(candidate)
    db.commit()

    relations = generate_cross_document_relations(db, document, [candidate])

    assert len(relations) == 1
    payload = relations[0].payload_json
    assert payload["source_candidate_id"] == candidate.public_id
    assert payload["target_existing_knowledge_id"] == existing.public_id
    assert payload["relation_type"] == "depends_on"
    assert payload["generation_method"] == "cross_document_explicit"


def test_deleting_unactivated_change_document_cancels_only_staged_assets() -> None:
    db = _db()
    domain = Domain(domain_code="incremental", name="增量测试", status="ready")
    change_set = DomainChangeSet(
        public_id="dcs_cancel", domain_code="incremental", status="ready_to_activate",
        mode="append", base_catalog_fingerprint="base", summary_json={"documents": ["kdoc_delta"]},
    )
    document = KnowledgeDocument(
        public_id="kdoc_delta", domain_code="incremental", change_set_id=None,
        original_name="delta.md", file_type="markdown", mime_type="text/markdown",
        sha256="e" * 64, status="ready_for_questions", source_title="新增资料", license_note="test",
    )
    active_item = KnowledgeItem(
        public_id="ki_active", domain_code="incremental", name="正式知识", category="基础",
        difficulty=1, content_md="仍在正式领域的知识。", source_title="既有资料",
        license_note="test", status="published",
    )
    db.add_all([domain, change_set, document, active_item])
    db.flush()
    document.change_set_id = change_set.id
    chunk = KnowledgeChunk(
        public_id="kchunk_delta", document_id=document.id, domain_code="incremental",
        chunk_index=0, heading_path_json=["新增知识"], content="待启用来源正文", checksum="f" * 64,
    )
    staged_item = KnowledgeItem(
        public_id="ki_staged", domain_code="incremental", name="待启用知识", category="基础",
        difficulty=2, content_md="尚未进入正式领域的知识。", source_title="新增资料",
        license_note="test", source_document_id=document.id, status="staged",
    )
    db.add_all([chunk, staged_item])
    db.flush()
    db.add(KnowledgeItemSource(
        knowledge_item_id=staged_item.id, chunk_id=chunk.id, document_id=document.id,
        source_quote_hash="a" * 64, status="staged",
    ))
    question = DiagnosticQuestion(
        public_id="dq_staged", external_id="staged-question", domain_code="incremental",
        knowledge_item_id=staged_item.id, question_type="single_choice", stem="待启用题目",
        options_json=["A", "B"], answer_key_json={"pending_change_set_id": change_set.id},
        difficulty=2, status="staged", certification_status="certified",
    )
    question_run = QuestionImportRun(
        public_id="qir_cancel", domain_code="incremental", template_version="v1",
        knowledge_catalog_fingerprint="catalog", question_inventory_fingerprint="inventory",
        change_set_id=change_set.id, original_name="questions.xlsx", file_sha256="b" * 64,
        status="published",
    )
    db.add_all([question, question_run])
    db.flush()
    row = QuestionImportRow(
        public_id="qrow_cancel", run_id=question_run.id, row_number=2,
        question_external_id="staged-question", slot_key="slot", knowledge_ref="ki_staged",
        status="published",
    )
    db.add(row)
    db.commit()

    result = delete_document(db, document)

    assert result["change_set_cancelled"] is True
    assert result["staged_knowledge_items_removed"] == 1
    assert result["staged_questions_removed"] == 1
    assert db.get(KnowledgeItem, staged_item.id) is None
    assert db.get(DiagnosticQuestion, question.id) is None
    assert db.get(KnowledgeItem, active_item.id).status == "published"
    assert db.get(KnowledgeDocument, document.id).status == "withdrawn"
    assert db.get(DomainChangeSet, change_set.id).status == "cancelled"
    assert db.get(QuestionImportRun, question_run.id).status == "cancelled"
    assert db.get(QuestionImportRow, row.id).status == "cancelled"
    assert db.scalar(select(KnowledgeItemSource.id).where(KnowledgeItemSource.knowledge_item_id == staged_item.id)) is None
