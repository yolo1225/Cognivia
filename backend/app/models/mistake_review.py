from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class MistakeReviewItem(TimestampMixin, Base):
    __tablename__ = "mistake_review_items"
    __table_args__ = (
        UniqueConstraint(
            "learner_id",
            "domain_code",
            "source_type",
            "source_record_id",
            name="uq_mistake_review_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"), index=True)
    domain_code: Mapped[str] = mapped_column(String(64), index=True)
    knowledge_item_id: Mapped[int] = mapped_column(ForeignKey("knowledge_items.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    source_record_id: Mapped[str] = mapped_column(String(128))
    source_resource_id: Mapped[int | None] = mapped_column(
        ForeignKey("learning_resources.id", ondelete="SET NULL"), nullable=True
    )
    question_type: Mapped[str] = mapped_column(String(32))
    difficulty: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    error_summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    latest_attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("mistake_review_attempts.id", use_alter=True, ondelete="SET NULL"), nullable=True
    )
    review_count: Mapped[int] = mapped_column(default=0)
    last_wrong_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consolidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MistakeReviewAttempt(TimestampMixin, Base):
    __tablename__ = "mistake_review_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    mistake_item_id: Mapped[int] = mapped_column(
        ForeignKey("mistake_review_items.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_questions.id"))
    answer_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("answer_records.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), default="created", index=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[float] = mapped_column(Float, default=0.8)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    scoring_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ResourceQuizAttempt(TimestampMixin, Base):
    __tablename__ = "resource_quiz_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"), index=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("learning_resources.id"), index=True)
    resource_version: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(32), default="in_progress", index=True)
    current_question_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    answers_json: Mapped[dict] = mapped_column(JSON, default=dict)
    objective_correct: Mapped[int] = mapped_column(default=0)
    objective_total: Mapped[int] = mapped_column(default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
