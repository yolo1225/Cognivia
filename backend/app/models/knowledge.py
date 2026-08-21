from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class KnowledgeItem(TimestampMixin, Base):
    __tablename__ = "knowledge_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    domain_code: Mapped[str] = mapped_column(String(64), default="ai_app_dev", index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(64))
    difficulty: Mapped[int] = mapped_column(default=1)
    tags_json: Mapped[list] = mapped_column(JSON, default=list)
    evidence_capabilities_json: Mapped[list] = mapped_column(JSON, default=list)
    content_md: Mapped[str] = mapped_column(Text)
    source_title: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    license_note: Mapped[str] = mapped_column(String(255), default="")
    needs_reembedding: Mapped[bool] = mapped_column(default=True)
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ability_weights_json: Mapped[dict] = mapped_column(JSON, default=dict)
    source_locator_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="published", index=True)


class KnowledgeDocument(TimestampMixin, Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    domain_code: Mapped[str] = mapped_column(String(64), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_type: Mapped[str] = mapped_column(String(32))
    mime_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    knowledge_item_count: Mapped[int] = mapped_column(default=0)
    chunk_count: Mapped[int] = mapped_column(default=0)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_title: Mapped[str] = mapped_column(String(255), default="")
    license_note: Mapped[str] = mapped_column(String(255), default="")
    uploaded_by: Mapped[str] = mapped_column(String(64), default="demo_admin")
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeRelation(TimestampMixin, Base):
    __tablename__ = "knowledge_relations"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_item_id: Mapped[int] = mapped_column(ForeignKey("knowledge_items.id"))
    target_item_id: Mapped[int] = mapped_column(ForeignKey("knowledge_items.id"))
    relation_type: Mapped[str] = mapped_column(String(32))


class KnowledgeImportCandidate(TimestampMixin, Base):
    __tablename__ = "knowledge_import_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    domain_code: Mapped[str] = mapped_column(String(64), index=True)
    candidate_type: Mapped[str] = mapped_column(String(32), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    source_locator_json: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    validation_errors_json: Mapped[list] = mapped_column(JSON, default=list)
