from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import Principal, require_admin
from app.models import DomainChangeSet
from app.schemas.common import ApiResponse, ok
from app.services.domain_change_set_service import (
    DomainChangeSetError,
    activate_change_set,
    create_change_set,
    get_change_set,
    serialize_change_set,
)


router = APIRouter()


class ChangeSetCreateBody(BaseModel):
    domain_code: str = Field(min_length=1, max_length=64)
    mode: str = Field(default="append", pattern="^(append|replace)$")


def _error(exc: DomainChangeSetError) -> HTTPException:
    status = 404 if str(exc) in {"DOMAIN_NOT_FOUND", "DOMAIN_CHANGE_SET_NOT_FOUND"} else 409
    return HTTPException(status_code=status, detail=str(exc))


@router.get("", response_model=ApiResponse)
def list_change_sets(
    domain_code: str = Query(...),
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_admin),
) -> ApiResponse:
    rows = list(
        db.scalars(
            select(DomainChangeSet)
            .where(DomainChangeSet.domain_code == domain_code)
            .order_by(DomainChangeSet.id.desc())
            .limit(50)
        )
    )
    return ok({"domain_code": domain_code, "change_sets": [serialize_change_set(row) for row in rows]})


@router.post("", response_model=ApiResponse)
def create_domain_change_set(
    payload: ChangeSetCreateBody,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_admin),
) -> ApiResponse:
    try:
        change_set = create_change_set(
            db,
            domain_code=payload.domain_code,
            mode=payload.mode,
            created_by=principal.user_id,
        )
        db.commit()
        db.refresh(change_set)
    except DomainChangeSetError as exc:
        raise _error(exc) from exc
    return ok(serialize_change_set(change_set))


@router.get("/{change_set_id}", response_model=ApiResponse)
def get_domain_change_set(
    change_set_id: str,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_admin),
) -> ApiResponse:
    try:
        return ok(serialize_change_set(get_change_set(db, change_set_id)))
    except DomainChangeSetError as exc:
        raise _error(exc) from exc


@router.post("/{change_set_id}/activate", response_model=ApiResponse)
def activate_domain_change_set(
    change_set_id: str,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_admin),
) -> ApiResponse:
    try:
        return ok(activate_change_set(db, get_change_set(db, change_set_id)))
    except DomainChangeSetError as exc:
        raise _error(exc) from exc
