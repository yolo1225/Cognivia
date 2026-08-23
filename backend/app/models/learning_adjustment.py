from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class LearningAdjustmentProposal(TimestampMixin, Base):
    __tablename__ = "learning_adjustment_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"), index=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("learner_profiles.id"), index=True)
    learning_path_id: Mapped[int] = mapped_column(ForeignKey("learning_paths.id"), index=True)
    path_node_id: Mapped[str] = mapped_column(String(128), index=True)
    tutoring_session_id: Mapped[int] = mapped_column(
        ForeignKey("tutoring_sessions.id"), index=True
    )
    source_resource_id: Mapped[int] = mapped_column(ForeignKey("learning_resources.id"))
    hypothesis_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="collecting", index=True)
    trigger_source: Mapped[str] = mapped_column(String(32), default="automatic")
    source_feedback_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    evidence_summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    validation_result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    resulting_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("learner_profiles.id"), nullable=True
    )
    resulting_learning_path_id: Mapped[int | None] = mapped_column(
        ForeignKey("learning_paths.id"), nullable=True
    )
    resource_recommendation_json: Mapped[dict] = mapped_column(JSON, default=dict)
    resource_decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    generation_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("generation_tasks.id"), nullable=True
    )
