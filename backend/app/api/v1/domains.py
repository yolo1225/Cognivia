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
from app.rag.vector_store import VectorStore
from app.schemas.common import ApiResponse, ok

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
    knowledge_count = (
        db.scalar(
            select(func.count()).select_from(KnowledgeItem).where(KnowledgeItem.domain_code == domain_code)
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
    documents = list(
        db.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.domain_code == domain_code,
                KnowledgeDocument.status != "deleted",
            )
        )
    )
    vector_store = VectorStore()
    vector_count = vector_store.get_collection(domain_code).count()

    targets = {
        "knowledge_items": 50,
        "diagnostic_questions": 60,
        "vector_chunks": knowledge_count,
    }
    issues = []
    if knowledge_count < targets["knowledge_items"]:
        issues.append(
            {
                "level": "warning",
                "message": "知识点数量未达到 M1 目标",
                "actual": knowledge_count,
                "target": targets["knowledge_items"],
            }
        )
    if question_count < targets["diagnostic_questions"]:
        issues.append(
            {
                "level": "warning",
                "message": "诊断题数量未达到 M1 目标",
                "actual": question_count,
                "target": targets["diagnostic_questions"],
            }
        )
    ready_document_count = sum(item.status == "ready" for item in documents)
    failed_document_count = sum(item.status == "failed" for item in documents)
    processing_document_count = sum(
        item.status in {"queued", "parsing", "indexing"} for item in documents
    )
    if ready_document_count == 0:
        issues.append(
            {
                "level": "warning",
                "message": "当前领域没有已完成索引的知识库文件",
                "actual": 0,
                "target": 1,
            }
        )
    if failed_document_count or processing_document_count:
        issues.append(
            {
                "level": "warning",
                "message": "知识库存在处理失败或尚未完成的文件",
                "actual": failed_document_count + processing_document_count,
                "target": 0,
            }
        )
    if vector_count < targets["vector_chunks"]:
        issues.append(
            {
                "level": "warning",
                "message": "ChromaDB 向量数量少于知识切片数量",
                "actual": vector_count,
                "target": targets["vector_chunks"],
            }
        )

    return ok(
        {
            "domain_code": domain_code,
            "passed": not issues,
            "counts": {
                "knowledge_items": knowledge_count,
                "diagnostic_questions": question_count,
                "chroma_vectors": vector_count,
            },
            "targets": targets,
            "issues": issues,
        }
    )
