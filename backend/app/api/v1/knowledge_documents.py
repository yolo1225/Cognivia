from __future__ import annotations

from collections import Counter
from urllib.parse import unquote

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Domain, KnowledgeDocument
from app.schemas.common import ApiResponse, ok
from app.services.knowledge_document_service import (
    MAX_FILE_BYTES,
    KnowledgeDocumentError,
    create_document,
    delete_document,
    retry_document,
    serialize_document,
)
from app.services.knowledge_import_orchestrator import create_import_run, schedule_import
from app.services import candidate_index_job

router = APIRouter()


def process_knowledge_document(run_id: str) -> None:
    """Compatibility scheduling hook retained for existing tests and callers."""
    schedule_import(run_id)


def _get_document(db: Session, document_id: str) -> KnowledgeDocument:
    document = db.scalar(
        select(KnowledgeDocument).where(KnowledgeDocument.public_id == document_id)
    )
    if document is None or document.status == "deleted":
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    return document


@router.get("", response_model=ApiResponse)
def list_documents(domain_code: str = Query(...), db: Session = Depends(get_db)) -> ApiResponse:
    documents = list(
        db.scalars(
            select(KnowledgeDocument)
            .where(
                KnowledgeDocument.domain_code == domain_code,
                KnowledgeDocument.status != "deleted",
            )
            .order_by(KnowledgeDocument.created_at.desc(), KnowledgeDocument.id.desc())
        )
    )
    statuses = Counter(document.status for document in documents)
    return ok(
        {
            "domain_code": domain_code,
            "documents": [serialize_document(document) for document in documents],
            "summary": {
                "total": len(documents),
                "ready": statuses["ready"],
                "processing": sum(
                    statuses[value]
                    for value in (
                        "queued", "parsing", "extracting", "graph_generation",
                        "graph_review", "question_generation", "question_review",
                        "question_repair", "validating", "staging", "indexing",
                        "smoke_testing", "publishing",
                    )
                ),
                "failed": statuses["failed"],
                "chunks": sum(
                    document.chunk_count for document in documents if document.status == "ready"
                ),
            },
        }
    )


@router.post("", response_model=ApiResponse)
async def upload_document(
    request: Request,
    domain_code: str = Query(...),
    source_title: str = Query(""),
    license_note: str = Query(""),
    uploaded_by: str = Query("demo_admin"),
    x_file_name: str = Header(...),
    db: Session = Depends(get_db),
) -> ApiResponse:
    if db.scalar(select(Domain).where(Domain.domain_code == domain_code)) is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="单个文件不能超过 20MB")
    try:
        document = create_document(
            db,
            domain_code=domain_code,
            original_name=unquote(x_file_name),
            content=bytes(content),
            mime_type=request.headers.get("content-type", "application/octet-stream"),
            source_title=source_title,
            license_note=license_note,
            uploaded_by=uploaded_by,
        )
    except KnowledgeDocumentError as exc:
        code = 409 if "已存在" in str(exc) else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    run = create_import_run(db, document)
    process_knowledge_document(run.public_id)
    return ok({**serialize_document(document), "import_id": run.public_id, "run_id": run.public_id, "input_version": run.input_version})


@router.get("/{document_id}", response_model=ApiResponse)
def get_document(document_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(serialize_document(_get_document(db, document_id)))


@router.post("/{document_id}/retry", response_model=ApiResponse)
def retry_failed_document(
    document_id: str,
    db: Session = Depends(get_db),
) -> ApiResponse:
    document = _get_document(db, document_id)
    try:
        retry_document(db, document)
    except KnowledgeDocumentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    run = create_import_run(db, document)
    process_knowledge_document(run.public_id)
    return ok({**serialize_document(document), "import_id": run.public_id, "run_id": run.public_id, "input_version": run.input_version})


@router.delete("/{document_id}", response_model=ApiResponse)
def remove_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ApiResponse:
    document = _get_document(db, document_id)
    try:
        result = delete_document(db, document)
    except KnowledgeDocumentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    job = candidate_index_job.try_start(db, document.domain_code)
    if job is not None:
        background_tasks.add_task(candidate_index_job.run_rebuild, job.id, document.domain_code)
        result["index_rebuild_job_id"] = job.id
    else:
        result["index_rebuild_pending"] = True
    return ok(result)
