from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.rag.readiness import candidate_rag_status
from app.schemas.common import ApiResponse, ok
from app.services import model_config_service as service
from app.services.llm_service import gateway

router = APIRouter()


def _index_rebuild_hint(domain_code: str) -> dict:
    """Whether the active candidate vector index needs a rebuild."""
    status = candidate_rag_status(domain_code)
    return {
        "ready": bool(status.get("ready")),
        "reason": status.get("reason"),
    }


class ModelSettingsBody(BaseModel):
    openai_api_base: str = Field(default="", max_length=1024)
    primary_llm_model: str = Field(default="", max_length=255)
    primary_review_model: str = Field(default="", max_length=255)
    secondary_review_model: str = Field(default="", max_length=255)
    embedding_model: str = Field(default="", max_length=255)
    openai_api_key: str | None = Field(default=None, max_length=1024)
    clear_openai_api_key: bool = False


@router.get("", response_model=ApiResponse)
def get_settings(domain_code: str = Query(..., min_length=1, max_length=64)) -> ApiResponse:
    service.reload_from_db()
    return ok(
        {
            "settings": service.effective_config(),
            "status": gateway.configuration_status(),
            "index": _index_rebuild_hint(domain_code),
        }
    )


@router.put("", response_model=ApiResponse)
def update_settings(
    body: ModelSettingsBody,
    domain_code: str = Query(..., min_length=1, max_length=64),
    db: Session = Depends(get_db),
) -> ApiResponse:
    service.save_config(db, **body.model_dump())
    return ok(
        {
            "settings": service.effective_config(),
            "status": gateway.configuration_status(),
            "index": _index_rebuild_hint(domain_code),
        }
    )


@router.post("/test", response_model=ApiResponse)
def test_connection(body: ModelSettingsBody) -> ApiResponse:
    return ok(service.test_connection(**body.model_dump()))
