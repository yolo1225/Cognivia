"""Knowledge document upload lifecycle and background import entrypoint."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    KnowledgeDocument,
    KnowledgeImportCandidate,
    KnowledgeItem,
)
from app.services.knowledge_update_service import mark_affected_content

KNOWLEDGE_STORAGE_ROOT = Path(__file__).resolve().parents[3] / "storage" / "knowledge"
MAX_FILE_BYTES = 20 * 1024 * 1024
FILE_TYPES = {".pdf": "pdf", ".md": "markdown", ".markdown": "markdown", ".txt": "text"}


class KnowledgeDocumentError(ValueError):
    pass


def _safe_file_name(name: str) -> str:
    normalized = Path(name).name.strip()
    if not normalized:
        raise KnowledgeDocumentError("文件名不能为空")
    return re.sub(r"[^\w.\-\u4e00-\u9fff]", "_", normalized)[:255]


def validate_upload(name: str, content: bytes) -> tuple[str, str]:
    safe_name = _safe_file_name(name)
    file_type = FILE_TYPES.get(Path(safe_name).suffix.lower())
    if file_type is None:
        raise KnowledgeDocumentError("仅支持 PDF、Markdown 和 TXT 文件")
    if not content:
        raise KnowledgeDocumentError("不能上传空文件")
    if len(content) > MAX_FILE_BYTES:
        raise KnowledgeDocumentError("单个文件不能超过 20MB")
    return safe_name, file_type


def create_document(
    db: Session,
    *,
    domain_code: str,
    original_name: str,
    content: bytes,
    mime_type: str,
    source_title: str,
    license_note: str,
    uploaded_by: str,
) -> KnowledgeDocument:
    safe_name, file_type = validate_upload(original_name, content)
    digest = hashlib.sha256(content).hexdigest()
    duplicate = db.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.domain_code == domain_code,
            KnowledgeDocument.sha256 == digest,
            KnowledgeDocument.status.not_in({"deleted", "withdrawn"}),
        )
    )
    if duplicate is not None:
        raise KnowledgeDocumentError("当前领域已存在内容相同的文件")

    public_id = f"kdoc_{uuid4().hex[:16]}"
    directory = (KNOWLEDGE_STORAGE_ROOT / domain_code / public_id).resolve()
    root = KNOWLEDGE_STORAGE_ROOT.resolve()
    if root not in directory.parents:
        raise KnowledgeDocumentError("领域存储路径非法")
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / safe_name
    path.write_bytes(content)
    document = KnowledgeDocument(
        public_id=public_id,
        domain_code=domain_code,
        original_name=safe_name,
        stored_path=str(path.relative_to(root)),
        file_type=file_type,
        mime_type=mime_type or "application/octet-stream",
        size_bytes=len(content),
        sha256=digest,
        status="queued",
        source_title=(source_title.strip() or safe_name)[:255],
        license_note=(license_note.strip() or "管理员上传")[:255],
        uploaded_by=(uploaded_by.strip() or "demo_admin")[:64],
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def _document_path(document: KnowledgeDocument) -> Path:
    if not document.stored_path:
        raise KnowledgeDocumentError("系统知识包没有物理文件")
    root = KNOWLEDGE_STORAGE_ROOT.resolve()
    path = (root / document.stored_path).resolve()
    if root not in path.parents:
        raise KnowledgeDocumentError("文档存储路径非法")
    return path


def retry_document(db: Session, document: KnowledgeDocument) -> None:
    if document.file_type == "seed_package":
        raise KnowledgeDocumentError("系统知识包不需要重新处理")
    if document.status not in {
        "failed", "needs_attention", "interrupted", "queued", "review_pending", "ready"
    }:
        raise KnowledgeDocumentError("只有已发布、失败或排队中的文件可以重新处理")
    document.status = "queued"
    document.error_summary = None
    db.commit()


def delete_document(db: Session, document: KnowledgeDocument) -> dict[str, object]:
    if document.file_type == "seed_package":
        raise KnowledgeDocumentError("系统内置知识包不能删除")
    processing_statuses = {
        "queued", "parsing", "extracting", "graph_generation", "graph_review",
        "question_generation", "question_review", "question_repair", "validating",
        "staging", "indexing", "smoke_testing", "publishing",
    }
    if document.status in processing_statuses:
        from app.models import KnowledgeImportBatch, KnowledgeImportRun

        latest_run = db.scalar(
            select(KnowledgeImportRun)
            .where(KnowledgeImportRun.document_id == document.id)
            .order_by(KnowledgeImportRun.id.desc())
            .limit(1)
        )
        if latest_run is None or latest_run.status != "cancel_requested":
            raise KnowledgeDocumentError("文件正在处理中，请先中断任务后再删除")
        latest_run.status = "cancelled"
        latest_run.current_step = "cancelled"
        latest_run.error_code = "import_cancelled"
        latest_run.error_summary = "导入已取消"
        latest_run.lease_owner = None
        latest_run.lease_expires_at = None
        latest_run.finished_at = datetime.now(UTC)
        for batch in db.scalars(
            select(KnowledgeImportBatch).where(
                KnowledgeImportBatch.run_id == latest_run.id,
                KnowledgeImportBatch.status.in_(("pending", "running")),
            )
        ):
            batch.status = "cancelled"
            batch.error_code = "import_cancelled"
            batch.error_summary = "导入已取消"
            batch.lease_owner = None
            batch.lease_expires_at = None
        document.status = "cancelled"
        document.error_summary = "导入已取消"
        db.flush()
    from app.models import (
        AnswerRecord,
        DiagnosticQuestion,
        KnowledgeChunk,
        KnowledgeImportBatch,
        KnowledgeImportRun,
        KnowledgeItemSource,
        KnowledgeRelation,
        PathNodeAssessment,
    )

    sources = list(db.scalars(select(KnowledgeItemSource).where(
        KnowledgeItemSource.document_id == document.id,
        KnowledgeItemSource.status.in_(("staged", "published")),
    )))
    item_ids = {source.knowledge_item_id for source in sources}
    items = list(db.scalars(select(KnowledgeItem).where(KnowledgeItem.id.in_(item_ids)))) if item_ids else []
    db.execute(delete(KnowledgeImportCandidate).where(KnowledgeImportCandidate.document_id == document.id))
    db.execute(delete(KnowledgeImportBatch).where(KnowledgeImportBatch.run_id.in_(
        select(KnowledgeImportRun.id).where(KnowledgeImportRun.document_id == document.id)
    )))
    db.execute(delete(KnowledgeImportRun).where(KnowledgeImportRun.document_id == document.id))
    shared_item_ids: set[int] = set()
    exclusive_item_ids: set[int] = set()
    if items:
        mark_affected_content(
            db,
            domain_code=document.domain_code,
            affected_knowledge_ids={item.public_id for item in items},
            reason="knowledge_document_deleted",
        )
        for item in items:
            remaining = db.scalar(select(KnowledgeItemSource.id).where(
                KnowledgeItemSource.knowledge_item_id == item.id,
                KnowledgeItemSource.document_id != document.id,
                KnowledgeItemSource.status.in_(("staged", "published")),
            ))
            (shared_item_ids if remaining is not None else exclusive_item_ids).add(item.id)
        db.flush()
    if exclusive_item_ids:
        question_ids = set(db.scalars(select(DiagnosticQuestion.id).where(
            DiagnosticQuestion.knowledge_item_id.in_(exclusive_item_ids)
        )))
        if question_ids:
            db.execute(delete(PathNodeAssessment).where(PathNodeAssessment.question_id.in_(question_ids)))
            db.execute(delete(AnswerRecord).where(AnswerRecord.question_id.in_(question_ids)))
            db.execute(delete(DiagnosticQuestion).where(DiagnosticQuestion.id.in_(question_ids)))
        db.execute(delete(KnowledgeRelation).where(
            (KnowledgeRelation.source_item_id.in_(exclusive_item_ids))
            | (KnowledgeRelation.target_item_id.in_(exclusive_item_ids))
        ))
        db.execute(delete(KnowledgeItem).where(KnowledgeItem.id.in_(exclusive_item_ids)))
    if shared_item_ids:
        db.execute(delete(KnowledgeItemSource).where(
            KnowledgeItemSource.document_id == document.id,
            KnowledgeItemSource.knowledge_item_id.in_(shared_item_ids),
        ))
    db.execute(delete(KnowledgeItemSource).where(KnowledgeItemSource.document_id == document.id))
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id))
    document.status = "deleted"
    document.deleted_at = datetime.now(UTC)
    document.error_summary = None
    db.commit()
    stored_path = (KNOWLEDGE_STORAGE_ROOT / str(document.stored_path or "")).resolve()
    root = KNOWLEDGE_STORAGE_ROOT.resolve()
    if stored_path.is_file() and root in stored_path.parents:
        stored_path.unlink()
    return {
        "document_id": document.public_id,
        "status": "deleted",
        "sources_retracted": len(sources),
        "knowledge_deleted": len(exclusive_item_ids),
        "knowledge_preserved_shared": len(shared_item_ids),
        "affected_knowledge": len(items),
    }


def serialize_document(document: KnowledgeDocument) -> dict[str, object]:
    return {
        "document_id": document.public_id,
        "domain_code": document.domain_code,
        "original_name": document.original_name,
        "file_type": document.file_type,
        "mime_type": document.mime_type,
        "size_bytes": document.size_bytes,
        "status": document.status,
        "error_summary": document.error_summary,
        "knowledge_item_count": document.knowledge_item_count,
        "chunk_count": document.chunk_count,
        "embedding_model": document.embedding_model,
        "source_title": document.source_title,
        "license_note": document.license_note,
        "uploaded_by": document.uploaded_by,
        "is_system": document.file_type == "seed_package",
        "indexed_at": document.indexed_at.isoformat() if document.indexed_at else None,
        "created_at": document.created_at.isoformat() if document.created_at else None,
    }
