from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DomainChangeSet(TimestampMixin, Base):
    """A staged domain update, kept separate from the active learner runtime."""

    __tablename__ = "domain_change_sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    domain_code: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="preparing", index=True)
    mode: Mapped[str] = mapped_column(String(16), default="append")
    base_catalog_fingerprint: Mapped[str] = mapped_column(String(80), default="")
    target_catalog_fingerprint: Mapped[str | None] = mapped_column(String(80), nullable=True)
    summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="demo_admin")
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_domain_change_sets_domain_status", "domain_code", "status"),)
