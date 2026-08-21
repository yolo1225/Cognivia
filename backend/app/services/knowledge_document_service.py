"""Knowledge document upload lifecycle and background import entrypoint."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import (
    DiagnosticQuestion,
    KnowledgeDocument,
    KnowledgeImportCandidate,
    KnowledgeItem,
    KnowledgeRelation,
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
            KnowledgeDocument.status != "deleted",
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


def process_knowledge_document(document_id: str) -> None:
    with SessionLocal() as db:
        document = db.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.public_id == document_id)
        )
        if document is None or document.status == "deleted":
            return
        try:
            document.status = "parsing"
            document.error_summary = None
            db.commit()
            from app.services.knowledge_extraction_service import replace_candidates
            from app.services.knowledge_import_validation_service import validate_import
            from app.services.knowledge_parser_service import parse_document

            sections = parse_document(document)
            candidates = replace_candidates(db, document, sections)
            document.status = "validating"
            document.chunk_count = len(sections)
            db.commit()
            result = validate_import(db, document.id)
            document = db.get(KnowledgeDocument, document.id)
            document.status = "review_pending"
            document.error_summary = (
                None if not result["invalid"] else f"{result['invalid']} 个候选需要修改"
            )
            document.knowledge_item_count = sum(
                item.candidate_type == "knowledge_item" for item in candidates
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            failed = db.scalar(
                select(KnowledgeDocument).where(KnowledgeDocument.public_id == document_id)
            )
            if failed is not None and failed.status != "deleted":
                failed.status = "failed"
                failed.error_summary = str(exc)[:1000]
                db.commit()


def retry_document(db: Session, document: KnowledgeDocument) -> None:
    if document.file_type == "seed_package":
        raise KnowledgeDocumentError("系统知识包不需要重新处理")
    if document.status not in {"failed", "queued", "review_pending"}:
        raise KnowledgeDocumentError("只有失败或排队中的文件可以重新处理")
    document.status = "queued"
    document.error_summary = None
    db.commit()


def delete_document(db: Session, document: KnowledgeDocument) -> None:
    if document.file_type == "seed_package":
        raise KnowledgeDocumentError("系统内置知识包不能删除")
    if document.status in {"parsing", "indexing"}:
        raise KnowledgeDocumentError("文件正在处理中，暂时不能删除")
    items = list(
        db.scalars(select(KnowledgeItem).where(KnowledgeItem.source_document_id == document.id))
    )
    db.execute(
        delete(KnowledgeImportCandidate).where(KnowledgeImportCandidate.document_id == document.id)
    )
    if items:
        item_ids = [item.id for item in items]
        db.execute(
            delete(DiagnosticQuestion).where(DiagnosticQuestion.knowledge_item_id.in_(item_ids))
        )
        db.execute(
            delete(KnowledgeRelation).where(
                (KnowledgeRelation.source_item_id.in_(item_ids))
                | (KnowledgeRelation.target_item_id.in_(item_ids))
            )
        )
        mark_affected_content(
            db,
            domain_code=document.domain_code,
            affected_knowledge_ids={item.public_id for item in items},
            reason="knowledge_document_deleted",
        )
        for item in items:
            db.delete(item)
        db.flush()
    path = _document_path(document)
    if path.exists():
        path.unlink()
    if path.parent.exists():
        path.parent.rmdir()
    document.status = "deleted"
    document.deleted_at = datetime.now(UTC)
    document.error_summary = None
    db.commit()


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
