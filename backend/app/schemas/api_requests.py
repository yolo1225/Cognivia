from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GenerationTaskCreateRequest(StrictRequest):
    learner_id: str = Field(default="learner_001", min_length=3, max_length=64)
    profile_id: str | None = Field(default=None, max_length=64)
    domain_code: str = Field(default="ai_app_dev", min_length=1, max_length=64)
    trigger_type: Literal["initial_generation", "resource_feedback"] = "initial_generation"
    execution_mode: Literal["auto", "assisted"] = "auto"
    learning_goal: str = Field(default="个性化学习资源生成", min_length=1, max_length=512)
    resource_types: list[Literal["lecture", "practice_guide", "graded_quiz"]] = Field(
        default_factory=lambda: ["lecture", "practice_guide", "graded_quiz"], min_length=1
    )


class DiagnosticSessionCreateRequest(StrictRequest):
    learner_id: str = Field(default="learner_001", min_length=3, max_length=64)
    domain_code: str = Field(default="ai_app_dev", min_length=1, max_length=64)
    question_count: int = Field(default=10, ge=1, le=60)


class DiagnosticAnswerRequest(StrictRequest):
    question_id: str = Field(min_length=1, max_length=64)
    answer: str | None = Field(default=None, max_length=4000)


class DiagnosticSessionSubmitRequest(StrictRequest):
    learner_id: str = Field(default="learner_001", min_length=3, max_length=64)
    domain_code: str = Field(default="ai_app_dev", min_length=1, max_length=64)
    answers: list[DiagnosticAnswerRequest] = Field(min_length=1, max_length=60)


class LearnerCreateRequest(StrictRequest):
    learner_id: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    background: str = Field(default="", max_length=255)
    target_domain: str = Field(default="ai_app_dev", min_length=1, max_length=64)
    experience_years: int = Field(default=0, ge=0, le=50)
    learning_style: Literal["theory", "practice", "mixed"] = "mixed"

    @field_validator("learner_id", "background", "target_domain", "learning_style", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return str(value).strip()


class ResourceFeedbackRequest(StrictRequest):
    learner_id: str = Field(default="learner_001", min_length=3, max_length=64)
    feedback_type: Literal["too_hard", "too_easy", "confusing", "incorrect", "has_error", "helpful"]
    rating: int | None = Field(default=None, ge=1, le=5)
    selected_text: str | None = Field(default=None, max_length=2000)
    comment: str | None = Field(default=None, max_length=2000)


class ResourceExportRequest(StrictRequest):
    format: Literal["markdown", "pdf"] = "markdown"
    audience: Literal["learner", "teacher"] = "learner"


class TutoringSessionCreateRequest(StrictRequest):
    learner_id: str = Field(default="learner_001", min_length=3, max_length=64)
    resource_id: str = Field(min_length=1, max_length=64)


class TutoringMessageRequest(StrictRequest):
    content: str = Field(min_length=1, max_length=2000)
    evidence: list[dict] = Field(default_factory=list, max_length=50)


class KnowledgeItemCreateRequest(StrictRequest):
    domain_code: str = Field(default="ai_app_dev", min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    category: str = Field(default="未分类", min_length=1, max_length=64)
    difficulty: int = Field(default=2, ge=1, le=5)
    tags: list[str] = Field(default_factory=list)
    content: str = Field(min_length=10)
    source_title: str = Field(default="教师手动导入", min_length=1, max_length=255)
    source_url: str | None = Field(default=None, max_length=512)
    license_note: str = Field(default="manual-import", max_length=255)
    prerequisites: list[str] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)


class KnowledgeItemUpdateRequest(StrictRequest):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    difficulty: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] | None = None
    content: str | None = Field(default=None, min_length=10)
    source_title: str | None = Field(default=None, min_length=1, max_length=255)
    source_url: str | None = Field(default=None, max_length=512)
    license_note: str | None = Field(default=None, max_length=255)
    prerequisites: list[str] | None = None
    related: list[str] | None = None
