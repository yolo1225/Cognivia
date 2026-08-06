from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import require_idempotency_key
from app.core.db import get_db
from app.rag.vector_store import VectorStore, get_vector_store
from app.schemas.api_requests import KnowledgeItemCreateRequest, KnowledgeItemUpdateRequest
from app.schemas.common import ApiResponse, ok
from app.services.idempotency_service import execute_idempotent
from app.services.knowledge_api_service import KnowledgeApiService

router = APIRouter()


@router.get("/items", response_model=ApiResponse)
def list_knowledge_items(domain_code: str = Query("ai_app_dev"), category: str | None = Query(None), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db)) -> ApiResponse:
    return ok(KnowledgeApiService(db).list(domain_code, category, limit, offset))


@router.post("/items", response_model=ApiResponse)
def create_knowledge_item(payload: KnowledgeItemCreateRequest, idempotency_key: str = Depends(require_idempotency_key), db: Session = Depends(get_db)) -> ApiResponse:
    service = KnowledgeApiService(db)
    result, _ = execute_idempotent(db, scope="knowledge.create", request_key=idempotency_key, operation=lambda: (service.create(payload), "knowledge_item", None))
    return ok(result)


@router.patch("/items/{knowledge_id}", response_model=ApiResponse)
def update_knowledge_item(knowledge_id: str, payload: KnowledgeItemUpdateRequest, idempotency_key: str = Depends(require_idempotency_key), db: Session = Depends(get_db)) -> ApiResponse:
    service = KnowledgeApiService(db)
    result, _ = execute_idempotent(db, scope=f"knowledge.update:{knowledge_id}", request_key=idempotency_key, operation=lambda: (service.update(knowledge_id, payload), "knowledge_item", knowledge_id))
    return ok(result)


@router.get("/retrieval-preview", response_model=ApiResponse)
def retrieval_preview(
    query: str = Query(min_length=1),
    domain_code: str = Query("ai_app_dev"),
    n_results: int = Query(5, ge=1, le=20),
    vector_store: VectorStore = Depends(get_vector_store),
    db: Session = Depends(get_db),
) -> ApiResponse:
    return ok(KnowledgeApiService(db).retrieval_preview(query, domain_code, n_results, vector_store.client))


@router.post("/reindex", response_model=ApiResponse)
def reindex_candidate(
    domain_code: str = Query("ai_app_dev"),
    idempotency_key: str = Depends(require_idempotency_key),
    db: Session = Depends(get_db),
    vector_store: VectorStore = Depends(get_vector_store),
) -> ApiResponse:
    service = KnowledgeApiService(db)
    result, _ = execute_idempotent(db, scope=f"knowledge.reindex:{domain_code}", request_key=idempotency_key, operation=lambda: (service.reindex(domain_code, vector_store.client), "candidate_index", domain_code))
    return ok(result)


@router.get("/reindex/status", response_model=ApiResponse)
def candidate_reindex_status(
    domain_code: str = Query("ai_app_dev"),
    db: Session = Depends(get_db),
    vector_store: VectorStore = Depends(get_vector_store),
) -> ApiResponse:
    return ok(KnowledgeApiService(db).reindex_status(domain_code, vector_store.client))
