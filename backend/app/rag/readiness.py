from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import KnowledgeItem
from app.rag.candidate_index import database_source_snapshot
from app.rag.candidate_index_access import CandidateIndexAccess, CandidateIndexUnavailable
from app.rag.vector_store import VectorStore
from app.scripts.validate_rag_seed import source_data_version


RAG_NOT_READY_CODE = "CANDIDATE_RAG_NOT_READY"


class CandidateRagNotReady(RuntimeError):
    """Raised when candidate RAG cannot safely serve a generation request."""


def candidate_rag_status(domain_code: str) -> dict[str, Any]:
    """Return a non-throwing readiness result for the active candidate index."""
    missing_config = [
        name
        for name, value in (
            ("OPENAI_API_BASE", settings.openai_api_base),
            ("OPENAI_API_KEY", settings.openai_api_key),
            ("EMBEDDING_MODEL", settings.embedding_model),
        )
        if not value
    ]
    if missing_config:
        return {
            "ready": False,
            "domain_code": domain_code,
            "reason": "embedding_configuration_missing",
            "missing": missing_config,
        }

    try:
        manifest, collection = CandidateIndexAccess(VectorStore().client).active(domain_code)
        with SessionLocal() as db:
            items = list(
                db.scalars(
                    select(KnowledgeItem)
                    .where(
                        KnowledgeItem.domain_code == domain_code,
                        KnowledgeItem.status == "published",
                    )
                    .order_by(KnowledgeItem.public_id)
                )
            )
            if not items:
                return {
                    "ready": False,
                    "domain_code": domain_code,
                    "reason": "knowledge_items_missing",
                }
            current_source_version = source_data_version(database_source_snapshot(db, items))
    except CandidateIndexUnavailable as exc:
        return {"ready": False, "domain_code": domain_code, "reason": str(exc)}
    except Exception as exc:
        return {
            "ready": False,
            "domain_code": domain_code,
            "reason": f"candidate_index_check_failed:{type(exc).__name__}",
        }

    if manifest.embedding_model != settings.embedding_model:
        return {
            "ready": False,
            "domain_code": domain_code,
            "reason": "embedding_model_mismatch",
            "expected_embedding_model": manifest.embedding_model,
            "configured_embedding_model": settings.embedding_model,
        }
    if manifest.source_data_version != current_source_version:
        return {
            "ready": False,
            "domain_code": domain_code,
            "reason": "candidate_index_stale",
            "index_source_version": manifest.source_data_version,
            "current_source_version": current_source_version,
        }
    return {
        "ready": True,
        "domain_code": domain_code,
        "active_collection": manifest.active_collection,
        "indexed_chunk_count": manifest.indexed_chunk_count,
        "index_version": manifest.index_version,
        "source_data_version": manifest.source_data_version,
        "embedding_model": manifest.embedding_model,
        "embedding_dimensions": manifest.embedding_dimensions,
    }


def require_candidate_rag(domain_code: str) -> dict[str, Any]:
    status = candidate_rag_status(domain_code)
    if not status["ready"]:
        reason = str(status.get("reason", "candidate_index_unavailable"))
        raise CandidateRagNotReady(reason)
    return status
