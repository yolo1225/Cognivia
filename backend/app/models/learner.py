from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Learner(TimestampMixin, Base):
    __tablename__ = "learners"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    background: Mapped[str] = mapped_column(String(255), default="")
    education_level: Mapped[str] = mapped_column(String(64), default="")
    major: Mapped[str] = mapped_column(String(128), default="")
    target_domain: Mapped[str] = mapped_column(String(64), default="ai_app_dev")
    experience_years: Mapped[int] = mapped_column(default=0)
    learning_style: Mapped[str] = mapped_column(String(32), default="mixed")
    direction_tags_json: Mapped[list] = mapped_column(JSON, default=list)


class LearnerProfile(TimestampMixin, Base):
    __tablename__ = "learner_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"))
    domain_code: Mapped[str] = mapped_column(String(64), default="ai_app_dev")
    ability_profile_json: Mapped[dict] = mapped_column(JSON, default=dict)
    weak_knowledge_json: Mapped[list] = mapped_column(JSON, default=list)
    profile_version: Mapped[int] = mapped_column(default=1)
    profile_source: Mapped[str] = mapped_column(String(32), default="default_seed", index=True)
    diagnosis_completed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    previous_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("learner_profiles.id"), nullable=True
    )
    changed_dimensions_json: Mapped[list] = mapped_column(JSON, default=list)
    evidence_refs_json: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    context_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    trigger_feedback_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_feedback.id", use_alter=True), nullable=True
    )
    decision_reason: Mapped[str] = mapped_column(Text, default="initial profile")
    profile_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LearningPath(TimestampMixin, Base):
    __tablename__ = "learning_paths"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"))
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("learner_profiles.id"), nullable=True)
    domain_code: Mapped[str] = mapped_column(String(64), default="ai_app_dev")
    status: Mapped[str] = mapped_column(String(32), default="active")
    path_json: Mapped[dict] = mapped_column(JSON, default=dict)
    needs_refresh: Mapped[bool] = mapped_column(default=False)
