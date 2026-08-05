from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.rag.vector_store import VectorStore, get_vector_store
from app.schemas.common import ApiResponse, ok
from app.services.domain_api_service import DomainApiService

router = APIRouter()


@router.get("", response_model=ApiResponse)
def list_domains(db: Session = Depends(get_db)) -> ApiResponse:
    return ok(DomainApiService(db).list())


@router.get("/{domain_code}/validate", response_model=ApiResponse)
def validate_domain_config(
    domain_code: str,
    db: Session = Depends(get_db),
    vector_store: VectorStore = Depends(get_vector_store),
) -> ApiResponse:
    return ok(DomainApiService(db).validate(domain_code, vector_store))
