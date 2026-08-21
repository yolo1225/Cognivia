import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, get_db
from app.core.security import Principal, get_current_user, self_service_learner
from app.schemas.common import ApiResponse, ok
from app.services.diagnostic_service import (
    create_diagnostic_session,
    get_current_diagnostic_session,
    get_diagnostic_session_status,
    prepare_diagnostic_submission,
    retry_diagnostic_session,
    run_diagnostic_scoring_job,
)

router = APIRouter()


@router.post("/sessions", response_model=ApiResponse)
def create_session(
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    payload = payload or {}
    if not str(payload.get("domain_code") or "").strip():
        raise HTTPException(status_code=422, detail="domain_code is required")
    try:
        result = create_diagnostic_session(
            db,
            learner_id=self_service_learner(principal, payload.get("learner_id")),
            domain_code=str(payload.get("domain_code") or ""),
            question_count=payload.get("question_count", 10),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc).upper()) from exc
    return ok(result)


@router.post("/sessions/{session_id}/submit", response_model=ApiResponse)
def submit_session(
    session_id: str,
    payload: dict[str, Any],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    if not str(payload.get("domain_code") or "").strip():
        raise HTTPException(status_code=422, detail="domain_code is required")
    try:
        result, started = prepare_diagnostic_submission(
            db,
            session_id=session_id,
            learner_id=self_service_learner(principal, payload.get("learner_id")),
            domain_code=str(payload.get("domain_code") or ""),
            answers=payload.get("answers", []),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc).upper()) from exc
    if started:
        background_tasks.add_task(run_diagnostic_scoring_job, session_id)
    body = ok(
        {
            **result,
            "status_url": f"/api/v1/diagnostics/sessions/{session_id}",
            "events_url": f"/api/v1/diagnostics/sessions/{session_id}/events",
        }
    )
    return JSONResponse(status_code=202, content=body.model_dump(mode="json"))


@router.get("/sessions/current", response_model=ApiResponse)
def get_current_session(
    learner_id: str | None = None,
    domain_code: str = "",
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    if not domain_code.strip():
        raise HTTPException(status_code=422, detail="domain_code is required")
    return ok(
        get_current_diagnostic_session(
            db,
            learner_id=self_service_learner(principal, learner_id),
            domain_code=domain_code,
        )
    )


@router.get("/sessions/{session_id}", response_model=ApiResponse)
def get_session_status(
    session_id: str,
    learner_id: str | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    try:
        return ok(
            get_diagnostic_session_status(
                db,
                session_id=session_id,
                learner_id=self_service_learner(principal, learner_id),
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc).upper()) from exc


@router.post("/sessions/{session_id}/retry", response_model=ApiResponse)
def retry_session(
    session_id: str,
    background_tasks: BackgroundTasks,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    try:
        result, started = retry_diagnostic_session(
            db,
            session_id=session_id,
            learner_id=self_service_learner(principal, (payload or {}).get("learner_id")),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc).upper()) from exc
    if started:
        background_tasks.add_task(run_diagnostic_scoring_job, session_id)
    return ok(result)


def _event(name: str, payload: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _session_events(session_id: str, learner_id: str) -> AsyncIterator[str]:
    previous: tuple[str, int, str | None] | None = None
    while True:
        with SessionLocal() as db:
            try:
                payload = get_diagnostic_session_status(
                    db, session_id=session_id, learner_id=learner_id
                )
            except ValueError:
                yield _event("failed", {"session_id": session_id, "error_code": "NOT_FOUND"})
                return
        marker = (payload["status"], payload["progress"], payload.get("error_code"))
        if marker != previous:
            previous = marker
            yield _event("status", payload)
        if payload["status"] == "scored":
            yield _event("completed", payload)
            return
        if payload["status"] in {"pending_scoring", "failed"}:
            yield _event("pending" if payload["status"] == "pending_scoring" else "failed", payload)
            return
        await asyncio.sleep(0.5)


@router.get("/sessions/{session_id}/events")
def session_events(
    session_id: str,
    learner_id: str | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> StreamingResponse:
    resolved_learner = self_service_learner(principal, learner_id)
    try:
        get_diagnostic_session_status(
            db, session_id=session_id, learner_id=resolved_learner
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc).upper()) from exc
    return StreamingResponse(
        _session_events(session_id, resolved_learner),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
