from fastapi import APIRouter, Query

from app.core.db import SessionLocal, check_database_connection
from app.rag.vector_store import get_vector_store
from app.schemas.common import ApiResponse, ok
from app.services.domain_runtime_service import load_domain_runtime
from app.services.llm_service import gateway
from app.core.config import settings

router = APIRouter()


@router.get("/health", response_model=ApiResponse)
def health_check() -> ApiResponse:
    return ok({"status": "ok", "service": "backend", "api_prefix": "/api/v1"})


@router.get("/health/dependencies", response_model=ApiResponse)
def dependency_health_check(
    domain_code: str = Query("ai_app_dev", min_length=1, max_length=64),
) -> ApiResponse:
    database = _check_dependency("database", check_database_connection)
    chroma = _check_dependency("chroma", get_vector_store().health_check)
    models = gateway.configuration_status()
    try:
        with SessionLocal() as db:
            domain_runtime = load_domain_runtime(db, domain_code).readiness_payload()
    except Exception as exc:
        domain_runtime = {
            "domain_code": domain_code,
            "profile_ready": False,
            "diagnostic_ready": False,
            "rag_ready": False,
            "generation_ready": False,
            "reasons": [str(exc)],
            "rag": {"ready": False, "domain_code": domain_code, "reason": str(exc)},
        }
    overall_status = (
        "ok" if database["status"] == chroma["status"] == models["status"] == "ok" else "degraded"
    )
    return ok(
        {
            "status": overall_status,
            "database": database,
            "chroma": chroma,
            "domain_runtime": domain_runtime,
            "rag": domain_runtime["rag"],
            "evaluation_runner_enabled": settings.enable_evaluation_runner,
            "evaluation_overrides_enabled": settings.enable_evaluation_overrides,
            **models,
        }
    )


def _check_dependency(name: str, checker) -> dict:
    try:
        return checker()
    except Exception as exc:
        return {"status": "degraded", "dependency": name, "error": str(exc)}
