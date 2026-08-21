from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class GenerationTask(TimestampMixin, Base):
    __tablename__ = "generation_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"))
    profile_id: Mapped[int] = mapped_column(ForeignKey("learner_profiles.id"))
    domain_code: Mapped[str] = mapped_column(String(64), default="ai_app_dev")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    resource_types_json: Mapped[list] = mapped_column(JSON, default=list)
    revision_count: Mapped[int] = mapped_column(default=0)
    decision: Mapped[str] = mapped_column(String(32), default="pending")
    trigger_type: Mapped[str] = mapped_column(String(32), default="initial_generation")
    execution_mode: Mapped[str] = mapped_column(String(16), default="auto")
    learning_goal: Mapped[str] = mapped_column(String(512), default="")
    source_resource_id: Mapped[int | None] = mapped_column(
        ForeignKey("learning_resources.id", use_alter=True), nullable=True
    )
    source_feedback_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_feedback.id", use_alter=True), nullable=True
    )
    source_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("generation_tasks.id", use_alter=True), nullable=True
    )
    is_current_package: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), default="generation")
    progress: Mapped[int] = mapped_column(default=0)
    package_coverage_json: Mapped[dict] = mapped_column(JSON, default=dict)
    package_quality_json: Mapped[dict] = mapped_column(JSON, default=dict)
    failure_reason: Mapped[str] = mapped_column(Text, default="")


class LearningResource(TimestampMixin, Base):
    __tablename__ = "learning_resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    generation_task_id: Mapped[int] = mapped_column(ForeignKey("generation_tasks.id"))
    resource_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(255))
    content_md: Mapped[str] = mapped_column(Text)
    difficulty: Mapped[int] = mapped_column(default=1)
    learner_profile_type: Mapped[str] = mapped_column(String(64), default="")
    sources_json: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(default=1)
    review_status: Mapped[str] = mapped_column(String(32), default="pending")
    series_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    previous_resource_id: Mapped[int | None] = mapped_column(
        ForeignKey("learning_resources.id"), nullable=True
    )
    is_current: Mapped[bool] = mapped_column(default=True, index=True)
    adaptation_reason: Mapped[str] = mapped_column(Text, default="")
    knowledge_coverage_json: Mapped[dict] = mapped_column(JSON, default=dict)
    structured_content_json: Mapped[dict] = mapped_column(JSON, default=dict)


class ReviewReport(TimestampMixin, Base):
    __tablename__ = "review_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("learning_resources.id"))
    primary_review_json: Mapped[dict] = mapped_column(JSON, default=dict)
    secondary_review_json: Mapped[dict] = mapped_column(JSON, default=dict)
    arbitration_json: Mapped[dict] = mapped_column(JSON, default=dict)
    passed: Mapped[bool] = mapped_column(default=False)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("generation_tasks.id"), nullable=True)
    factual_score: Mapped[float] = mapped_column(default=0)
    source_trace_score: Mapped[float] = mapped_column(default=0)
    difficulty_match_score: Mapped[float] = mapped_column(default=0)
    coverage_score: Mapped[float] = mapped_column(default=0)
    decision: Mapped[str] = mapped_column(String(32), default="revision_required")
    evidence_refs_json: Mapped[list] = mapped_column(JSON, default=list)
    disagreement_summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    review_rule_version: Mapped[str] = mapped_column(
        String(32), default="review-v5-claim-policy"
    )
    quality_rule_version: Mapped[str] = mapped_column(
        String(32), default="quality-v7-20260821"
    )
    issues_json: Mapped[list] = mapped_column(JSON, default=list)
    suggestions_json: Mapped[list] = mapped_column(JSON, default=list)
    target_knowledge_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    covered_knowledge_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    missing_knowledge_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    verifiable_claim_count: Mapped[int] = mapped_column(default=0)
    evaluated_claim_count: Mapped[int] = mapped_column(default=0)
    contradicted_claim_count: Mapped[int] = mapped_column(default=0)
    evidence_insufficient_claim_count: Mapped[int] = mapped_column(default=0)
    unresolved_claim_count: Mapped[int] = mapped_column(default=0)
    hallucinated_claim_count: Mapped[int] = mapped_column(default=0)
    hallucination_rate: Mapped[float] = mapped_column(default=0)
    covered_core_knowledge_count: Mapped[int] = mapped_column(default=0)
    target_core_knowledge_count: Mapped[int] = mapped_column(default=0)
    core_knowledge_coverage: Mapped[float] = mapped_column(default=0)
    quality_passed: Mapped[bool] = mapped_column(default=False)
    revision_count: Mapped[int] = mapped_column(default=0)
    model_role_version: Mapped[str] = mapped_column(
        String(32), default="review-v5-claim-policy"
    )


class LearningPackageResource(TimestampMixin, Base):
    __tablename__ = "learning_package_resources"
    __table_args__ = (
        UniqueConstraint("package_task_id", "resource_id", name="uq_package_resource"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    package_task_id: Mapped[int] = mapped_column(
        ForeignKey("generation_tasks.id"), index=True
    )
    resource_id: Mapped[int] = mapped_column(ForeignKey("learning_resources.id"), index=True)
    membership_type: Mapped[str] = mapped_column(String(16), default="generated")
    freshness_status: Mapped[str] = mapped_column(String(32), default="current")
    sort_order: Mapped[int] = mapped_column(default=0)


class KnowledgeUpdateImpact(TimestampMixin, Base):
    __tablename__ = "knowledge_update_impacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    package_task_id: Mapped[int] = mapped_column(
        ForeignKey("generation_tasks.id"), index=True
    )
    affected_knowledge_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    affected_resource_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    reason: Mapped[str] = mapped_column(String(255), default="knowledge_item_updated")
    change_sequence: Mapped[int] = mapped_column(default=1)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("generation_tasks.id", use_alter=True), nullable=True
    )
