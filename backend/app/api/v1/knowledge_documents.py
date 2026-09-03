from __future__ import annotations

from collections import Counter
from urllib.parse import unquote

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Domain, DomainChangeSet, KnowledgeDocument
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
from app.services.domain_change_set_service import (
    DomainChangeSetError,
    create_change_set,
    get_change_set,
    update_change_set_summary,
)
from app.services import candidate_index_job

router = APIRouter()


def _schedule_import(run_id: str) -> None:
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
                        "graph_review", "validating", "staging", "indexing",
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
    change_set_id: str | None = Query(default=None),
    import_mode: str = Query(default="append", pattern="^(append|replace)$"),
    replaces_document_id: str | None = Query(default=None),
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
    change_set: DomainChangeSet | None = None
    replace_target: KnowledgeDocument | None = None
    try:
        if change_set_id:
            change_set = get_change_set(db, change_set_id, domain_code=domain_code)
        elif db.scalar(select(Domain).where(Domain.domain_code == domain_code)).status == "ready":
            # Candidate-index activation is isolated per source document. Keep
            # automatic maintenance units equally small and let their question
            # workbooks be split into as many batches as needed.
            change_set = create_change_set(
                db, domain_code=domain_code, mode=import_mode, created_by=uploaded_by
            )
        if replaces_document_id:
            replace_target = db.scalar(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.public_id == replaces_document_id,
                    KnowledgeDocument.domain_code == domain_code,
                    KnowledgeDocument.status != "deleted",
                )
            )
            if replace_target is None:
                raise KnowledgeDocumentError("未找到可替换的来源文档")
        document = create_document(
            db,
            domain_code=domain_code,
            original_name=unquote(x_file_name),
            content=bytes(content),
            mime_type=request.headers.get("content-type", "application/octet-stream"),
            source_title=source_title,
            license_note=license_note,
            uploaded_by=uploaded_by,
            change_set=change_set,
            import_mode=import_mode,
            replaces_document=replace_target,
        )
        if change_set is not None:
            update_change_set_summary(change_set, document_id=document.public_id)
            db.commit()
    except (KnowledgeDocumentError, DomainChangeSetError) as exc:
        code = 409 if "已存在" in str(exc) else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    run = create_import_run(db, document)
    _schedule_import(run.public_id)
    return ok({
        **serialize_document(document),
        "import_id": run.public_id,
        "run_id": run.public_id,
        "input_version": run.input_version,
        "change_set_id": change_set.public_id if change_set else None,
    })


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
    _schedule_import(run.public_id)
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
    candidate_manifests = result.pop("candidate_manifests", [])
    if result.get("change_set_cancelled"):
        background_tasks.add_task(
            candidate_index_job.discard_change_set_candidates, candidate_manifests
        )
        result["candidate_index_cleanup_scheduled"] = bool(candidate_manifests)
    else:
        job = candidate_index_job.try_start(db, document.domain_code)
        if job is not None:
            background_tasks.add_task(candidate_index_job.run_rebuild, job.id, document.domain_code)
            result["index_rebuild_job_id"] = job.id
        else:
            result["index_rebuild_pending"] = True
    return ok(result)
