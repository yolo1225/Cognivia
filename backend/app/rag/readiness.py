from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import DiagnosticQuestion, KnowledgeItem
from app.rag.candidate_index import database_source_snapshot
from app.rag.candidate_index_access import CandidateIndexAccess, CandidateIndexUnavailable
from app.rag.vector_store import VectorStore
from app.scripts.validate_rag_seed import source_data_version
from app.services.question_bank_service import (
    MIN_DOMAIN_QUESTION_BANK_SIZE,
    is_question_bank_eligible,
)
from app.services.question_certification_service import (
    QUESTION_CERTIFICATION_RULE_VERSION,
)


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
            item_by_id = {item.id: item for item in items}
            questions = list(
                db.scalars(
                    select(DiagnosticQuestion)
                    .where(
                        DiagnosticQuestion.domain_code == domain_code,
                        DiagnosticQuestion.status == "active",
                        DiagnosticQuestion.certification_status == "certified",
                        DiagnosticQuestion.certification_rule_version
                        == QUESTION_CERTIFICATION_RULE_VERSION,
                        DiagnosticQuestion.knowledge_item_id.in_(item_by_id),
                    )
                    .order_by(DiagnosticQuestion.id)
                )
            )
        indexed = collection.get(include=["metadatas"])
        source_metadata = {
            str(source_ref_id): dict(metadata or {})
            for source_ref_id, metadata in zip(
                list(indexed.get("ids") or []),
                list(indexed.get("metadatas") or []),
                strict=True,
            )
        }
        invalid_question_source_ids = []
        ineligible_question_ids = [
            question.public_id for question in questions if not is_question_bank_eligible(question)
        ]
        covered_item_ids = {question.knowledge_item_id for question in questions}
        missing_question_item_ids = sorted(set(item_by_id) - covered_item_ids)
        question_types = {question.question_type for question in questions}
        quiz_levels = {
            str((question.answer_key_json or {}).get("quiz_level") or "")
            for question in questions
        }
        difficulty_levels = {question.difficulty for question in questions}
        for question in questions:
            answer = dict(question.answer_key_json or {})
            source_ref_ids = [str(value) for value in answer.get("source_ref_ids") or []]
            item = item_by_id[question.knowledge_item_id]
            locators = dict(answer.get("source_locators") or {})
            source_hashes = dict(answer.get("source_content_hashes") or {})
            metadata_rows = [source_metadata.get(value) for value in source_ref_ids]
            if (
                not 1 <= len(source_ref_ids) <= 3
                or any(metadata is None for metadata in metadata_rows)
                or str(metadata_rows[0].get("knowledge_id") or "") != item.public_id
                or any(
                    str(metadata.get("source_locator") or "")
                    != str(locators.get(source_ref_id) or "")
                    or str(metadata.get("item_content_hash") or "")
                    != str(source_hashes.get(source_ref_id) or "")
                    for source_ref_id, metadata in zip(
                        source_ref_ids, metadata_rows, strict=True
                    )
                    if metadata is not None
                )
            ):
                invalid_question_source_ids.append(question.public_id)
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
    if ineligible_question_ids:
        return {
            "ready": False,
            "domain_code": domain_code,
            "reason": "question_bank_question_invalid",
            "invalid_question_ids": ineligible_question_ids[:20],
            "invalid_question_count": len(ineligible_question_ids),
        }
    if len(questions) < MIN_DOMAIN_QUESTION_BANK_SIZE:
        return {
            "ready": False,
            "domain_code": domain_code,
            "reason": "question_bank_total_insufficient",
            "eligible_question_count": len(questions),
            "required_question_count": MIN_DOMAIN_QUESTION_BANK_SIZE,
        }
    if missing_question_item_ids:
        return {
            "ready": False,
            "domain_code": domain_code,
            "reason": "question_bank_knowledge_coverage_insufficient",
            "missing_knowledge_count": len(missing_question_item_ids),
        }
    required_types = {"single_choice", "short_answer"}
    required_levels = {"foundation", "improvement", "challenge"}
    required_difficulties = {1, 2, 3, 4, 5}
    if (
        not required_types.issubset(question_types)
        or not required_levels.issubset(quiz_levels)
        or not required_difficulties.issubset(difficulty_levels)
    ):
        return {
            "ready": False,
            "domain_code": domain_code,
            "reason": "question_bank_distribution_insufficient",
            "missing_question_types": sorted(required_types - question_types),
            "missing_quiz_levels": sorted(required_levels - quiz_levels),
            "missing_difficulty_levels": sorted(required_difficulties - difficulty_levels),
        }
    if invalid_question_source_ids:
        return {
            "ready": False,
            "domain_code": domain_code,
            "reason": "question_source_binding_invalid",
            "invalid_question_ids": invalid_question_source_ids[:20],
            "invalid_question_count": len(invalid_question_source_ids),
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
