from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import Principal, require_admin
from app.models import Domain, QuestionImportRun
from app.schemas.common import ApiResponse, ok
from app.services.question_import_service import (
    QuestionImportError,
    build_question_template,
    create_import_run,
    publish_import_run,
    queue_import_validation,
    schedule_import_row_retries,
    schedule_import_validation,
    serialize_row,
    serialize_run,
    set_row_source_binding,
)


router = APIRouter()


class SourceBindingBody(BaseModel):
    source_ref_ids: list[str] = Field(min_length=1, max_length=3)
    quotes: dict[str, str] = Field(default_factory=dict)


def _run(db: Session, run_id: str) -> QuestionImportRun:
    run = db.scalar(select(QuestionImportRun).where(QuestionImportRun.public_id == run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="QUESTION_IMPORT_NOT_FOUND")
    return run


def _error(exc: QuestionImportError) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


@router.get("/template")
def download_template(
    domain_code: str = Query(...),
    knowledge_id: list[str] | None = Query(default=None),
    change_set_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_admin),
) -> Response:
    if db.scalar(select(Domain).where(Domain.domain_code == domain_code)) is None:
        raise HTTPException(status_code=404, detail="DOMAIN_NOT_FOUND")
    try:
        content, _fingerprint, count = build_question_template(
            db,
            domain_code,
            knowledge_refs=set(knowledge_id or []) or None,
            change_set_id=change_set_id,
        )
    except QuestionImportError as exc:
        raise _error(exc) from exc
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{domain_code}-question-bank-template.xlsx"',
            "X-Question-Slot-Count": str(count),
        },
    )


@router.post("", response_model=ApiResponse)
async def upload_question_import(
    request: Request,
    domain_code: str = Query(...),
    change_set_id: str | None = Query(default=None),
    x_file_name: str = Header(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_admin),
) -> ApiResponse:
    if db.scalar(select(Domain).where(Domain.domain_code == domain_code)) is None:
        raise HTTPException(status_code=404, detail="DOMAIN_NOT_FOUND")
    content = await request.body()
    if not content:
        raise HTTPException(status_code=422, detail="QUESTION_IMPORT_FILE_EMPTY")
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="QUESTION_IMPORT_FILE_TOO_LARGE")
    try:
        run = create_import_run(
            db,
            domain_code=domain_code,
            original_name=unquote(x_file_name),
            content=content,
            created_by=principal.user_id,
            change_set_id=change_set_id,
            validate_immediately=False,
        )
    except QuestionImportError as exc:
        raise _error(exc) from exc
    schedule_import_validation(run.public_id)
    return ok(serialize_run(db, run))


@router.get("/{run_id}", response_model=ApiResponse)
def get_question_import(
    run_id: str,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_admin),
) -> ApiResponse:
    return ok(serialize_run(db, _run(db, run_id)))


@router.get("/{run_id}/rows", response_model=ApiResponse)
def list_question_import_rows(
    run_id: str,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_admin),
) -> ApiResponse:
    run = _run(db, run_id)
    from app.models import QuestionImportRow

    rows = list(
        db.scalars(
            select(QuestionImportRow)
            .where(QuestionImportRow.run_id == run.id)
            .order_by(QuestionImportRow.row_number)
        )
    )
    return ok({"run_id": run_id, "rows": [serialize_row(row) for row in rows]})


@router.patch("/{run_id}/rows/{row_id}/source-binding", response_model=ApiResponse)
def patch_source_binding(
    run_id: str,
    row_id: str,
    payload: SourceBindingBody,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_admin),
) -> ApiResponse:
    try:
        row = set_row_source_binding(
            db,
            run=_run(db, run_id),
            row_id=row_id,
            source_ref_ids=payload.source_ref_ids,
            quotes=payload.quotes,
        )
        db.commit()
        run = queue_import_validation(db, _run(db, run_id))
        schedule_import_validation(run.public_id)
    except QuestionImportError as exc:
        raise _error(exc) from exc
    return ok(serialize_row(row))


@router.post("/{run_id}/validate", response_model=ApiResponse)
def validate_question_import(
    run_id: str,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_admin),
) -> ApiResponse:
    run = _run(db, run_id)
    from app.models import QuestionImportRow

    has_service_errors = db.scalar(
        select(QuestionImportRow.id).where(
            QuestionImportRow.run_id == run.id,
            QuestionImportRow.status == "certification_service_error",
        ).limit(1)
    ) is not None
    if has_service_errors:
        run.status = "validating"
        run.error_summary = None
        db.commit()
        schedule_import_row_retries(run.public_id, {"certification_service_error"})
        return ok(serialize_run(db, run))
    try:
        run = queue_import_validation(db, run)
    except QuestionImportError as exc:
        raise _error(exc) from exc
    schedule_import_validation(run.public_id)
    return ok(serialize_run(db, run))


@router.post("/{run_id}/confirm-publish", response_model=ApiResponse)
def confirm_question_import(
    run_id: str,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_admin),
) -> ApiResponse:
    try:
        return ok(publish_import_run(db, _run(db, run_id)))
    except QuestionImportError as exc:
        raise _error(exc) from exc
