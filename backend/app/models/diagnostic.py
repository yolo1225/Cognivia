from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DiagnosticQuestion(TimestampMixin, Base):
    __tablename__ = "diagnostic_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    domain_code: Mapped[str] = mapped_column(String(64), default="ai_app_dev")
    knowledge_item_id: Mapped[int] = mapped_column(ForeignKey("knowledge_items.id"))
    related_knowledge_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    question_type: Mapped[str] = mapped_column(String(32))
    stem: Mapped[str] = mapped_column(Text)
    options_json: Mapped[list] = mapped_column(JSON, default=list)
    answer_key_json: Mapped[dict] = mapped_column(JSON, default=dict)
    difficulty: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    certification_status: Mapped[str] = mapped_column(
        String(32), default="pending", index=True
    )
    certification_rule_version: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    certification_report_json: Mapped[dict] = mapped_column(JSON, default=dict)
    source_content_hash: Mapped[str | None] = mapped_column(String(71), nullable=True)
    certified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    disabled_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)


class DiagnosticSession(TimestampMixin, Base):
    __tablename__ = "diagnostic_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"), index=True)
    domain_code: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="created", index=True)
    question_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    context_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    selection_summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    answer_hash: Mapped[str | None] = mapped_column(String(71), nullable=True)
    progress: Mapped[int] = mapped_column(default=0)
    scoring_attempts: Mapped[int] = mapped_column(default=0)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("learner_profiles.id"), nullable=True
    )
    learning_path_id: Mapped[int | None] = mapped_column(
        ForeignKey("learning_paths.id"), nullable=True
    )
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AnswerRecord(TimestampMixin, Base):
    __tablename__ = "answer_records"
    __table_args__ = (
        UniqueConstraint("session_id", "question_id", name="uq_answer_records_session_question"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"))
    question_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_questions.id"))
    knowledge_item_id: Mapped[int] = mapped_column(ForeignKey("knowledge_items.id"))
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[float] = mapped_column(default=0)
    is_correct: Mapped[bool] = mapped_column(default=False)
    scoring_status: Mapped[str] = mapped_column(String(32), default="scored", index=True)
    scoring_method: Mapped[str] = mapped_column(String(32), default="deterministic")
    rubric_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scoring_detail_json: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    scoring_uncertain: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_summary_json: Mapped[dict] = mapped_column(JSON, default=dict)


class PathNodeAssessment(TimestampMixin, Base):
    __tablename__ = "path_node_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    learning_path_id: Mapped[int] = mapped_column(ForeignKey("learning_paths.id"), index=True)
    path_node_id: Mapped[str] = mapped_column(String(128), index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_questions.id"))
    answer_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("answer_records.id"), nullable=True
    )
    adjustment_proposal_id: Mapped[int | None] = mapped_column(
        ForeignKey("learning_adjustment_proposals.id"), nullable=True, index=True
    )
    trigger_source: Mapped[str] = mapped_column(String(32), default="legacy")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
