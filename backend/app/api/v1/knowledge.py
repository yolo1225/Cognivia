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


@router.get("/search", response_model=ApiResponse)
def search_knowledge(query: str = Query(min_length=1), domain_code: str = Query("ai_app_dev"), n_results: int = Query(5, ge=1, le=20), vector_store: VectorStore = Depends(get_vector_store), db: Session = Depends(get_db)) -> ApiResponse:
    return ok(KnowledgeApiService(db).search(query, domain_code, n_results, vector_store))


@router.post("/rebuild-index", response_model=ApiResponse)
def rebuild_vector_index(domain_code: str = Query("ai_app_dev"), idempotency_key: str = Depends(require_idempotency_key), db: Session = Depends(get_db), vector_store: VectorStore = Depends(get_vector_store)) -> ApiResponse:
    service = KnowledgeApiService(db)
    result, _ = execute_idempotent(db, scope=f"knowledge.rebuild_index:{domain_code}", request_key=idempotency_key, operation=lambda: (service.rebuild_index(domain_code, vector_store), "knowledge_index", domain_code))
    return ok(result)
