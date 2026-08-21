from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ModelConfig(TimestampMixin, Base):
    """Runtime-editable model gateway configuration (single-row table).

    Non-secret fields live in ``config_json``. The API key is stored in a
    separate column so it can be encrypted at rest instead of appearing in the
    JSON document.
    """

    __tablename__ = "model_configs"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
