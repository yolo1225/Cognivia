from sqlalchemy import JSON, Boolean, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DiagnosticQuestion(TimestampMixin, Base):
    __tablename__ = "diagnostic_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    domain_code: Mapped[str] = mapped_column(String(64), default="ai_app_dev")
    knowledge_item_id: Mapped[int] = mapped_column(ForeignKey("knowledge_items.id"))
    question_type: Mapped[str] = mapped_column(String(32))
    stem: Mapped[str] = mapped_column(Text)
    options_json: Mapped[list] = mapped_column(JSON, default=list)
    answer_key_json: Mapped[dict] = mapped_column(JSON, default=dict)
    difficulty: Mapped[int] = mapped_column(default=1)


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
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    scoring_uncertain: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
