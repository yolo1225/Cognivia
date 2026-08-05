from sqlalchemy import JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class IdempotencyRecord(TimestampMixin, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("scope", "request_key", name="uq_idempotency_scope_request_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(96), index=True)
    request_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), default="processing")
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_public_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
