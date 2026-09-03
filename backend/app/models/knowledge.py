from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class KnowledgeItem(TimestampMixin, Base):
    __tablename__ = "knowledge_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    domain_code: Mapped[str] = mapped_column(String(64), default="ai_app_dev", index=True)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
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

    __table_args__ = (
        UniqueConstraint("domain_code", "external_id", name="uq_knowledge_items_domain_external"),
    )


class KnowledgeDocument(TimestampMixin, Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    domain_code: Mapped[str] = mapped_column(String(64), index=True)
    change_set_id: Mapped[int | None] = mapped_column(
        ForeignKey("domain_change_sets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    import_mode: Mapped[str] = mapped_column(String(16), default="append", index=True)
    replaces_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
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
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict)
    generation_method: Mapped[str] = mapped_column(String(64), default="manual")
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="SET NULL"), nullable=True, index=True
    )


class KnowledgeChunk(TimestampMixin, Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    domain_code: Mapped[str] = mapped_column(String(64), index=True)
    chunk_index: Mapped[int]
    heading_path_json: Mapped[list] = mapped_column(JSON, default=list)
    page_start: Mapped[int | None] = mapped_column(nullable=True)
    page_end: Mapped[int | None] = mapped_column(nullable=True)
    content: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    previous_chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_chunks.id", ondelete="SET NULL"), nullable=True
    )
    next_chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_chunks.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunks_document_index"),
    )


class KnowledgeItemSource(TimestampMixin, Base):
    __tablename__ = "knowledge_item_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    knowledge_item_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_items.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_chunks.id", ondelete="RESTRICT"), index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="RESTRICT"), index=True
    )
    import_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_import_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_quote_hash: Mapped[str] = mapped_column(String(64))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="staged", index=True)

    __table_args__ = (
        UniqueConstraint("knowledge_item_id", "chunk_id", name="uq_knowledge_item_sources_item_chunk"),
    )


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


class KnowledgeImportRun(TimestampMixin, Base):
    __tablename__ = "knowledge_import_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    domain_code: Mapped[str] = mapped_column(String(64), index=True)
    change_set_id: Mapped[int | None] = mapped_column(
        ForeignKey("domain_change_sets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    current_step: Mapped[str] = mapped_column(String(64), default="queued")
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    input_version: Mapped[str] = mapped_column(String(80), index=True)
    artifact_manifest_json: Mapped[dict] = mapped_column(JSON, default=dict)
    step_state_json: Mapped[dict] = mapped_column(JSON, default=dict)
    attempt_count: Mapped[int] = mapped_column(default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_import_runs_domain_status", "domain_code", "status"),)


class KnowledgeImportBatch(TimestampMixin, Base):
    __tablename__ = "knowledge_import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_import_runs.id", ondelete="CASCADE"), index=True
    )
    step: Mapped[str] = mapped_column(String(64), index=True)
    batch_key: Mapped[str] = mapped_column(String(128))
    input_hash: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(default=0)
    reuse_count: Mapped[int] = mapped_column(default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    artifact_json: Mapped[dict] = mapped_column(JSON, default=dict)
    artifact_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tokens_input: Mapped[int] = mapped_column(default=0)
    tokens_output: Mapped[int] = mapped_column(default=0)
    duration_ms: Mapped[int] = mapped_column(default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "run_id", "step", "batch_key", "input_hash",
            name="uq_knowledge_import_batch_input",
        ),
        Index("ix_import_batches_run_step_status", "run_id", "step", "status"),
    )


class DomainIndexManifest(TimestampMixin, Base):
    __tablename__ = "domain_index_manifests"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    active_collection: Mapped[str] = mapped_column(String(255))
    previous_collection: Mapped[str | None] = mapped_column(String(255), nullable=True)
    index_version: Mapped[str] = mapped_column(String(80), index=True)
    source_data_version: Mapped[str] = mapped_column(String(80))
    embedding_model: Mapped[str] = mapped_column(String(255))
    embedding_dimensions: Mapped[int]
    distance_metric: Mapped[str] = mapped_column(String(32), default="cosine")
    chunker_version: Mapped[str] = mapped_column(String(64))
    indexed_item_count: Mapped[int] = mapped_column(default=0)
    indexed_chunk_count: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
