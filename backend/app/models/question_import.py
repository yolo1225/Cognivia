from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class QuestionImportRun(TimestampMixin, Base):
    __tablename__ = "question_import_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    domain_code: Mapped[str] = mapped_column(String(64), index=True)
    template_version: Mapped[str] = mapped_column(String(64))
    knowledge_catalog_fingerprint: Mapped[str] = mapped_column(String(80), index=True)
    # The catalog hash protects source content.  This separate snapshot protects
    # the question inventory: another completed workbook can make a slot stale
    # without changing any knowledge item.
    question_inventory_fingerprint: Mapped[str] = mapped_column(String(80), default="", index=True)
    scope_json: Mapped[list] = mapped_column(JSON, default=list)
    change_set_id: Mapped[int | None] = mapped_column(
        ForeignKey("domain_change_sets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    original_name: Mapped[str] = mapped_column(String(255))
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", index=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    valid_row_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(64), default="demo_admin")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_question_import_runs_domain_status", "domain_code", "status"),)


class QuestionImportRow(TimestampMixin, Base):
    __tablename__ = "question_import_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("question_import_runs.id", ondelete="CASCADE"), index=True
    )
    row_number: Mapped[int] = mapped_column(Integer)
    question_external_id: Mapped[str] = mapped_column(String(128), index=True)
    slot_key: Mapped[str] = mapped_column(String(160))
    knowledge_ref: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    validation_errors_json: Mapped[list] = mapped_column(JSON, default=list)

    __table_args__ = (
        UniqueConstraint("run_id", "row_number", name="uq_question_import_rows_run_number"),
        UniqueConstraint("run_id", "question_external_id", name="uq_question_import_rows_run_external"),
    )
