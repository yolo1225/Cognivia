from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class IndexBuildJob(TimestampMixin, Base):
    """Persisted record of a candidate index rebuild attempt."""

    __tablename__ = "index_build_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain_code: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
