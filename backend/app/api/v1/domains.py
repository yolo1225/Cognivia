from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import (
    DiagnosticQuestion,
    Domain,
    GenerationTask,
    KnowledgeItem,
    KnowledgeDocument,
    KnowledgeRelation,
    LearningResource,
)
from app.schemas.common import ApiResponse, ok
from app.services.domain_api_service import DomainApiService

router = APIRouter()


@router.get("/{domain_code}/stats", response_model=ApiResponse)
def get_domain_stats(
    domain_code: str,
    db: Session = Depends(get_db),
) -> ApiResponse:
    knowledge_count = (
        db.scalar(
            select(func.count()).select_from(KnowledgeItem).where(
                KnowledgeItem.domain_code == domain_code
            )
        )
        or 0
    )
    question_count = (
        db.scalar(
            select(func.count()).select_from(DiagnosticQuestion).where(
                DiagnosticQuestion.domain_code == domain_code
            )
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
            select(func.count()).select_from(KnowledgeItem).where(
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
def list_domains(db: Session = Depends(get_db)) -> ApiResponse:
    domains = list(db.scalars(select(Domain).order_by(Domain.domain_code)))
    return ok(
        [
            {
                "domain_code": domain.domain_code,
                "name": domain.name,
                "domain_schema_version": domain.schema_version,
                "status": "active",
                "config": domain.config_json,
            }
            for domain in domains
        ]
    )


@router.get("/{domain_code}/validate", response_model=ApiResponse)
def validate_domain_config(
    domain_code: str,
    db: Session = Depends(get_db),
) -> ApiResponse:
    return ok(DomainApiService(db).validate(domain_code))
