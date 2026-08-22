import json
from queue import Queue
from threading import Thread
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import get_db
from app.core.security import Principal, get_current_user, principal_learner, require_resource, require_tutoring
from app.models import Learner, TutoringMessage, TutoringSession
from app.schemas.common import ApiResponse, ok
from app.services.learner_service import get_or_create_demo_learner
from app.services.profile_service import default_profile_for_learner
from app.services.tutoring_service import (
    create_streaming_messages,
    create_session,
    execute_tutoring_turn,
    serialize_session,
    submit_assessment_answer,
    update_streaming_reply,
)
from app.workers.generation_worker import run_generation_task

router = APIRouter()


def _event(name: str, payload: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/sessions", response_model=ApiResponse)
def start_tutoring_session(
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    payload = payload or {}
    resource_id = payload.get("resource_id")
    resource = require_resource(db,principal,resource_id)
    requested_learner = payload.get("learner_id")
    if principal.role == "admin" and not requested_learner:
        from app.models import GenerationTask
        task = db.get(GenerationTask, resource.generation_task_id)
        learner = db.get(Learner, task.learner_id)
    else:
        learner = get_or_create_demo_learner(
            db, principal_learner(principal, requested_learner)
        )
    if resource is None:
        raise HTTPException(status_code=404, detail="A published resource is required")
    if resource.review_status != "passed" or not resource.is_current:
        raise HTTPException(status_code=409, detail="Only a current passed resource can be tutored")
    session = create_session(db, learner=learner, resource=resource)
    db.commit()
    db.refresh(session)
    return ok(serialize_session(db, session))


@router.post("/sessions/{session_id}/messages", response_model=ApiResponse)
def post_tutoring_message(
    session_id: str,
    background_tasks: BackgroundTasks,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    session = require_tutoring(db,principal,session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Tutoring session not found")
    content = str((payload or {}).get("content") or "").strip()
    evidence = (payload or {}).get("evidence") or []
    if not content:
        raise HTTPException(status_code=422, detail="content is required")
    if not isinstance(evidence, list):
        raise HTTPException(status_code=422, detail="evidence must be a list")
    learner = db.get(Learner, session.learner_id)
    if learner is None:
        raise HTTPException(status_code=404, detail="Learner not found")
    profile = default_profile_for_learner(db, learner)
    try:
        result = execute_tutoring_turn(
            db,
            session=session,
            profile=profile,
            content=content,
            evidence=evidence[:50],
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    if result.task:
        background_tasks.add_task(run_generation_task, result.task.public_id)
    return ok(result.serialize())


@router.post("/sessions/{session_id}/messages/stream")
def stream_tutoring_message(
    session_id: str, background_tasks: BackgroundTasks, payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db), principal: Principal = Depends(get_current_user),
) -> StreamingResponse:
    session = require_tutoring(db, principal, session_id)
    content = str((payload or {}).get("content") or "").strip()
    evidence = (payload or {}).get("evidence") or []
    if not content:
        raise HTTPException(status_code=422, detail="content is required")
    if not isinstance(evidence, list):
        raise HTTPException(status_code=422, detail="evidence must be a list")
    stream_session_factory = sessionmaker(
        bind=db.get_bind(), autocommit=False, autoflush=False
    )
    learner_message, reply, _resource = create_streaming_messages(
        db, session=session, content=content
    )
    db.commit()
    learner_message_id = learner_message.public_id
    reply_id = reply.public_id

    def generate():
        accumulated = ""
        yield _event(
            "accepted",
            {
                "session_id": session_id,
                "learner_message_id": learner_message_id,
                "reply_message_id": reply_id,
            },
        )
        yield _event("agent_status", {"agent": "tutoring_agent", "status": "running"})
        events: Queue[tuple[str, Any]] = Queue()

        def run_turn() -> None:
            try:
                with stream_session_factory() as stream_db:
                    current_session = stream_db.scalar(
                        select(TutoringSession).where(TutoringSession.public_id == session_id)
                    )
                    if current_session is None:
                        raise ValueError("Tutoring session not found")
                    learner = stream_db.get(Learner, current_session.learner_id)
                    profile = default_profile_for_learner(stream_db, learner)
                    prepared_learner_message = stream_db.scalar(
                        select(TutoringMessage).where(
                            TutoringMessage.public_id == learner_message_id
                        )
                    )
                    prepared_reply = stream_db.scalar(
                        select(TutoringMessage).where(TutoringMessage.public_id == reply_id)
                    )
                    result = execute_tutoring_turn(
                        stream_db,
                        session=current_session,
                        profile=profile,
                        content=content,
                        evidence=evidence[:50],
                        prepared_learner_message=prepared_learner_message,
                        prepared_reply=prepared_reply,
                        on_reply_delta=lambda delta: events.put(("delta", delta)),
                    )
                    serialized = result.serialize()
                    stream_db.commit()
                events.put(("completed", serialized))
            except ValueError as exc:
                events.put(("error", (str(exc), bool(accumulated))))
            except Exception:
                events.put(("error", ("tutoring_turn_failed", bool(accumulated))))

        Thread(target=run_turn, daemon=True).start()
        while True:
            event_name, event_payload = events.get()
            if event_name == "delta":
                delta = str(event_payload)
                accumulated += delta
                yield _event("delta", {"reply_message_id": reply_id, "content": delta})
                continue
            if event_name == "completed":
                serialized = event_payload
                task_id = serialized["task_id"]
                if task_id:
                    background_tasks.add_task(run_generation_task, task_id)
                reply_payload = serialized["reply"]
                yield _event("agent_status", {"agent": "tutoring_agent", "status": "completed"})
                yield _event("completed", {"reply_message_id": reply_id, "content": reply_payload["content"], "sources": reply_payload["sources"], "scope_status": reply_payload["scope_status"], "assessment": reply_payload["assessment"], "assessment_unavailable": reply_payload["assessment_unavailable"], "feedback_id": serialized["feedback_id"], "feedback_intent": serialized["feedback_intent"], "recommended_action": serialized["recommended_action"], "profile_update_required": serialized["profile_update_required"], "decision_reason": serialized["decision_reason"], "task_id": task_id})
                return
            error_code, recoverable = event_payload
            with stream_session_factory() as stream_db:
                current_reply = stream_db.scalar(
                    select(TutoringMessage).where(TutoringMessage.public_id == reply_id)
                )
                if current_reply is not None:
                    update_streaming_reply(
                        stream_db,
                        reply=current_reply,
                        content=accumulated,
                        status="interrupted" if accumulated else "failed",
                        error_code=error_code,
                    )
            yield _event("error", {"reply_message_id": reply_id, "code": error_code, "recoverable": recoverable})
            return

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/sessions/{session_id}/assessments/{assessment_id}/answers", response_model=ApiResponse)
def answer_tutoring_assessment(
    session_id: str,
    assessment_id: str,
    background_tasks: BackgroundTasks,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    session = require_tutoring(db, principal, session_id)
    learner = db.get(Learner, session.learner_id)
    profile = default_profile_for_learner(db, learner)
    if "answer" not in (payload or {}):
        raise HTTPException(status_code=422, detail="answer is required")
    try:
        record, feedback, task, decision = submit_assessment_answer(
            db,
            session=session,
            profile=profile,
            assessment_id=assessment_id,
            answer=(payload or {})["answer"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    if task:
        background_tasks.add_task(run_generation_task, task.public_id)
    return ok({
        "answer_record_id": str(record.id),
        "score": record.score,
        "is_correct": record.is_correct,
        "confirmed": decision["confirmed"],
        "feedback_id": str(feedback.id),
        "profile_update_required": decision["profile_update_required"],
        "decision_reason": decision["decision_reason"],
        "task_id": task.public_id if task else None,
    })


@router.post("/sessions/{session_id}/messages/{reply_message_id}/pause", response_model=ApiResponse)
def pause_tutoring_message(session_id: str, reply_message_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_user)) -> ApiResponse:
    session = require_tutoring(db, principal, session_id)
    reply = db.scalar(select(TutoringMessage).where(TutoringMessage.public_id == reply_message_id, TutoringMessage.session_id == session.id, TutoringMessage.sender == "tutoring_agent"))
    if reply is None:
        raise HTTPException(status_code=404, detail="Tutoring reply not found")
    status = (reply.metadata_json or {}).get("stream_status", "completed")
    if status == "streaming":
        update_streaming_reply(db, reply=reply, status="paused")
        status = "paused"
    return ok({"reply_message_id": reply.public_id, "stream_status": status, "content": reply.content})


@router.get("/sessions/{session_id}", response_model=ApiResponse)
def get_tutoring_session(session_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_user)) -> ApiResponse:
    session = require_tutoring(db,principal,session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Tutoring session not found")
    return ok(serialize_session(db, session))
