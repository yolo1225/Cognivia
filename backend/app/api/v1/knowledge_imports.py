from __future__ import annotations

import json
from collections import Counter
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, get_db
from app.models import KnowledgeDocument, KnowledgeImportCandidate
from app.rag.readiness import candidate_rag_status
from app.schemas.common import ApiResponse, ok
from app.services import candidate_index_job
from app.services.knowledge_import_publish_service import (
    KnowledgeImportPublishError,
    approve_candidates,
    ensure_import_source_locators,
    publish_approved,
    smoke_import_index,
)
from app.services.knowledge_import_validation_service import validate_import

router = APIRouter()


def _run_import_index(job_id: int, domain_code: str, document_id: int) -> None:
    candidate_index_job.run_rebuild(job_id, domain_code)
    with SessionLocal() as db:
        job = db.get(candidate_index_job.IndexBuildJob, job_id)
        document = db.get(KnowledgeDocument, document_id)
        if document is None or job is None:
            return
        if job.status == candidate_index_job.STATUS_FAILED:
            document.status = "index_pending"
            document.error_summary = job.message
        else:
            document.error_summary = None
        db.commit()


class CandidatePatch(BaseModel):
    payload: dict[str, Any] | None = None
    status: str | None = Field(default=None, pattern="^(pending|rejected|needs_edit)$")


class ApproveRequest(BaseModel):
    candidate_ids: list[str] | None = None


def _document(db: Session, import_id: str) -> KnowledgeDocument:
    document = db.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.public_id == import_id, KnowledgeDocument.status != "deleted"
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Knowledge import not found")
    return document


def _serialize(candidate: KnowledgeImportCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.public_id,
        "candidate_type": candidate.candidate_type,
        "payload": candidate.payload_json or {},
        "source_locator": candidate.source_locator_json or {},
        "confidence": candidate.confidence,
        "status": candidate.status,
        "validation_errors": candidate.validation_errors_json or [],
    }


@router.get("/{import_id}", response_model=ApiResponse)
def get_import(import_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    document = _document(db, import_id)
    candidates = list(
        db.scalars(
            select(KnowledgeImportCandidate).where(
                KnowledgeImportCandidate.document_id == document.id
            )
        )
    )
    return ok(
        {
            "import_id": document.public_id,
            "domain_code": document.domain_code,
            "status": document.status,
            "error_summary": document.error_summary,
            "candidate_counts": dict(Counter(item.candidate_type for item in candidates)),
            "review_counts": dict(Counter(item.status for item in candidates)),
        }
    )


@router.get("/{import_id}/candidates", response_model=ApiResponse)
def list_candidates(import_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    document = _document(db, import_id)
    candidates = list(
        db.scalars(
            select(KnowledgeImportCandidate)
            .where(KnowledgeImportCandidate.document_id == document.id)
            .order_by(KnowledgeImportCandidate.id)
        )
    )
    return ok({"import_id": import_id, "candidates": [_serialize(item) for item in candidates]})


@router.patch("/{import_id}/candidates/{candidate_id}", response_model=ApiResponse)
def patch_candidate(
    import_id: str, candidate_id: str, payload: CandidatePatch, db: Session = Depends(get_db)
) -> ApiResponse:
    document = _document(db, import_id)
    candidate = db.scalar(
        select(KnowledgeImportCandidate).where(
            KnowledgeImportCandidate.document_id == document.id,
            KnowledgeImportCandidate.public_id == candidate_id,
        )
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Knowledge import candidate not found")
    if candidate.status in {"approved", "published"}:
        raise HTTPException(status_code=409, detail="已批准或发布的候选不可修改")
    if payload.payload is not None:
        candidate.payload_json = payload.payload
    if payload.status is not None:
        candidate.status = payload.status
    candidate.validation_errors_json = []
    db.commit()
    db.refresh(candidate)
    return ok(_serialize(candidate))


@router.post("/{import_id}/validate", response_model=ApiResponse)
def validate_candidates(import_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    document = _document(db, import_id)
    if document.status in {"index_pending", "indexing", "ready"}:
        raise HTTPException(status_code=409, detail="当前导入阶段不允许重新校验")
    return ok(validate_import(db, document.id))


@router.post("/{import_id}/approve", response_model=ApiResponse)
def approve_import(
    import_id: str, payload: ApproveRequest, db: Session = Depends(get_db)
) -> ApiResponse:
    document = _document(db, import_id)
    if document.status != "review_pending":
        raise HTTPException(status_code=409, detail="只有待复核导入可以批准")
    result = validate_import(db, document.id)
    if result["invalid"]:
        raise HTTPException(status_code=422, detail="存在未通过校验的候选")
    try:
        approved = approve_candidates(db, document, payload.candidate_ids)
        published = publish_approved(db, document)
    except KnowledgeImportPublishError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ok({"approved": approved, **published, "next_action": "build-index"})


@router.post("/{import_id}/build-index", response_model=ApiResponse)
def build_index(
    import_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> ApiResponse:
    document = _document(db, import_id)
    previous_job = candidate_index_job.latest_job(db)
    failed_retry = bool(
        document.status == "indexing"
        and previous_job
        and previous_job.domain_code == document.domain_code
        and previous_job.status
        in {
            candidate_index_job.STATUS_FAILED,
            candidate_index_job.STATUS_INTERRUPTED,
        }
    )
    if document.status != "index_pending" and not failed_retry:
        raise HTTPException(status_code=409, detail="导入尚未批准或已进入其他阶段")
    ensure_import_source_locators(db, document)
    job = candidate_index_job.try_start(db, document.domain_code)
    if job is None:
        raise HTTPException(status_code=409, detail="候选索引正在重建")
    document.status = "indexing"
    db.commit()
    background_tasks.add_task(_run_import_index, job.id, document.domain_code, document.id)
    return ok({"job_id": job.id, "status": "running", "domain_code": document.domain_code})


@router.post("/{import_id}/smoke-test", response_model=ApiResponse)
def smoke_test(import_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    document = _document(db, import_id)
    job = candidate_index_job.latest_job(db)
    passed = bool(
        job
        and job.domain_code == document.domain_code
        and job.status == candidate_index_job.STATUS_SUCCESS
        and candidate_rag_status(document.domain_code).get("ready")
    )
    if not passed:
        raise HTTPException(status_code=409, detail="Candidate 索引尚未通过构建与就绪检查")
    try:
        retrieval = smoke_import_index(db, document)
    except KnowledgeImportPublishError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    document.status = "smoke_passed"
    document.error_summary = None
    db.commit()
    return ok(
        {
            **retrieval,
            "rag": candidate_rag_status(document.domain_code),
        }
    )


@router.post("/{import_id}/publish", response_model=ApiResponse)
def publish_import(import_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    document = _document(db, import_id)
    if document.status != "smoke_passed":
        raise HTTPException(status_code=409, detail="检索冒烟尚未通过，不能发布")
    job = candidate_index_job.latest_job(db)
    if (
        not job
        or job.domain_code != document.domain_code
        or job.status != candidate_index_job.STATUS_SUCCESS
        or not candidate_rag_status(document.domain_code).get("ready")
    ):
        raise HTTPException(status_code=409, detail="索引构建或冒烟未通过，不能发布")
    document.status = "ready"
    document.error_summary = None
    document.embedding_model = (job.result_json or {}).get("embedding_model")
    document.indexed_at = job.finished_at
    db.commit()
    return ok({"import_id": import_id, "status": "ready"})


@router.get("/{import_id}/events")
def import_events(import_id: str, db: Session = Depends(get_db)) -> StreamingResponse:
    document = _document(db, import_id)
    payload = {
        "event_type": "import_status",
        "import_id": import_id,
        "status": document.status,
        "error_summary": document.error_summary,
    }
    return StreamingResponse(
        iter([f"event: import_status\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"]),
        media_type="text/event-stream",
    )
