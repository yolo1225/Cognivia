from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import api_error_response
from app.core.security import Principal, get_current_user, require_admin
from app.models import (
    DiagnosticQuestion,
    GenerationTask,
    KnowledgeItem,
    KnowledgeDocument,
    KnowledgeRelation,
    LearningResource,
)
from app.schemas.common import ApiResponse, ok
from app.services.domain_api_service import DomainApiService, DomainServiceError

router = APIRouter()


class LearningDirectionBody(BaseModel):
    value: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    label: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=255)
    match_tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("value", "label", "description", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return str(value).strip()

    @field_validator("match_tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        normalized = [str(item).strip().lower() for item in value if str(item).strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("duplicate match_tags")
        return normalized


class DomainCreateBody(BaseModel):
    domain_code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=500)
    learning_directions: list[LearningDirectionBody] = Field(min_length=1, max_length=6)

    @field_validator("domain_code", "name", "description", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return str(value).strip()

    @field_validator("learning_directions")
    @classmethod
    def unique_directions(cls, value: list[LearningDirectionBody]) -> list[LearningDirectionBody]:
        keys = [item.value for item in value]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate learning direction")
        return value


class DomainPatchBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    learning_directions: list[LearningDirectionBody] | None = Field(
        default=None, min_length=1, max_length=6
    )

    @field_validator("name", "description", mode="before")
    @classmethod
    def strip_optional_text(cls, value: Any) -> Any:
        return str(value).strip() if value is not None else None

    @field_validator("learning_directions")
    @classmethod
    def unique_optional_directions(
        cls, value: list[LearningDirectionBody] | None
    ) -> list[LearningDirectionBody] | None:
        if value is not None and len({item.value for item in value}) != len(value):
            raise ValueError("duplicate learning direction")
        return value


def _service_error(exc: DomainServiceError) -> HTTPException:
    code = str(exc)
    status = 404 if code == "DOMAIN_NOT_FOUND" else 409
    return HTTPException(status_code=status, detail=code)


@router.get("/{domain_code}/stats", response_model=ApiResponse)
def get_domain_stats(
    domain_code: str,
    db: Session = Depends(get_db),
) -> ApiResponse:
    knowledge_count = (
        db.scalar(
            select(func.count())
            .select_from(KnowledgeItem)
            .where(KnowledgeItem.domain_code == domain_code)
        )
        or 0
    )
    question_count = (
        db.scalar(
            select(func.count())
            .select_from(DiagnosticQuestion)
            .where(DiagnosticQuestion.domain_code == domain_code)
        )
        or 0
    )
    relation_count = (
        db.scalar(
            select(func.count())
            .select_from(KnowledgeRelation)
            .join(KnowledgeItem, KnowledgeItem.id == KnowledgeRelation.source_item_id)
            .where(KnowledgeItem.domain_code == domain_code)
        )
        or 0
    )
    pending_embedding_count = (
        db.scalar(
            select(func.count())
            .select_from(KnowledgeItem)
            .where(
                KnowledgeItem.domain_code == domain_code,
                KnowledgeItem.needs_reembedding.is_(True),
            )
        )
        or 0
    )
    documents = list(
        db.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.domain_code == domain_code,
                KnowledgeDocument.status != "deleted",
            )
        )
    )
    published_resource_count = (
        db.scalar(
            select(func.count())
            .select_from(LearningResource)
            .join(GenerationTask, GenerationTask.id == LearningResource.generation_task_id)
            .where(
                GenerationTask.domain_code == domain_code,
                LearningResource.is_current.is_(True),
                LearningResource.review_status == "passed",
            )
        )
        or 0
    )
    return ok(
        {
            "domain_code": domain_code,
            "knowledge_items": knowledge_count,
            "diagnostic_questions": question_count,
            "knowledge_relations": relation_count,
            "pending_embeddings": pending_embedding_count,
            "knowledge_documents": len(documents),
            "ready_documents": sum(item.status == "ready" for item in documents),
            "failed_documents": sum(item.status == "failed" for item in documents),
            "document_chunks": sum(
                item.chunk_count for item in documents if item.status == "ready"
            ),
            "published_resources": published_resource_count,
        }
    )


@router.get("", response_model=ApiResponse)
def list_domains(
    db: Session = Depends(get_db), principal: Principal = Depends(get_current_user)
) -> ApiResponse:
    return ok(DomainApiService(db).list(ready_only=principal.role != "admin"))


@router.post("", response_model=ApiResponse)
def create_domain(
    payload: DomainCreateBody,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_admin),
) -> ApiResponse:
    try:
        return ok(
            DomainApiService(db).create(
                domain_code=payload.domain_code,
                name=payload.name,
                description=payload.description,
                learning_directions=[item.model_dump() for item in payload.learning_directions],
            )
        )
    except DomainServiceError as exc:
        raise _service_error(exc) from exc


@router.get("/{domain_code}/validate", response_model=ApiResponse)
def validate_domain_config(
    domain_code: str,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_admin),
) -> ApiResponse:
    return ok(DomainApiService(db).validate(domain_code))


@router.get("/{domain_code}/readiness", response_model=ApiResponse)
def get_domain_readiness(
    domain_code: str,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_admin),
) -> ApiResponse:
    try:
        return ok(DomainApiService(db).readiness(domain_code))
    except DomainServiceError as exc:
        raise _service_error(exc) from exc


@router.post("/{domain_code}/publish", response_model=ApiResponse)
def publish_domain(
    domain_code: str,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_admin),
) -> ApiResponse:
    service = DomainApiService(db)
    try:
        return ok(service.publish(domain_code))
    except DomainServiceError as exc:
        if str(exc) == "DOMAIN_READINESS_FAILED":
            return api_error_response(
                status_code=409,
                code=str(exc),
                message="领域尚未通过发布门禁",
                details={"readiness": service.readiness(domain_code)},
            )
        raise _service_error(exc) from exc


@router.post("/{domain_code}/disable", response_model=ApiResponse)
def disable_domain(
    domain_code: str,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_admin),
) -> ApiResponse:
    try:
        return ok(DomainApiService(db).disable(domain_code))
    except DomainServiceError as exc:
        raise _service_error(exc) from exc


@router.get("/{domain_code}", response_model=ApiResponse)
def get_domain(
    domain_code: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    service = DomainApiService(db)
    try:
        detail = service.detail(domain_code)
    except DomainServiceError as exc:
        raise _service_error(exc) from exc
    if principal.role != "admin" and detail["status"] != "ready":
        raise HTTPException(status_code=404, detail="DOMAIN_NOT_FOUND")
    return ok(detail)


@router.patch("/{domain_code}", response_model=ApiResponse)
def patch_domain(
    domain_code: str,
    payload: DomainPatchBody,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_admin),
) -> ApiResponse:
    values = payload.model_dump(exclude_unset=True)
    if "learning_directions" in values:
        values["learning_directions"] = [
            item.model_dump() if isinstance(item, LearningDirectionBody) else item
            for item in (payload.learning_directions or [])
        ]
    try:
        return ok(DomainApiService(db).update(domain_code, **values))
    except DomainServiceError as exc:
        raise _service_error(exc) from exc
