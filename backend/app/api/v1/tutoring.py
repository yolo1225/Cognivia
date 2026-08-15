import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.config import settings
from app.core.security import Principal, get_current_user, principal_learner, require_resource, require_tutoring
from app.core.db import SessionLocal
from app.models import Learner, LearningResource, TutoringMessage, TutoringSession
from app.schemas.common import ApiResponse, ok
from app.services.learner_service import get_or_create_demo_learner
from app.services.profile_service import default_profile_for_learner
from app.services.llm_service import ModelGatewayError, gateway
from app.services.resource_tutoring_service import SYSTEM_PROMPT
from app.services.tutoring_service import (add_learner_message, create_session, create_streaming_messages,
    serialize_session, stream_context_for_message, update_streaming_reply)
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
    if not content:
        raise HTTPException(status_code=422, detail="content is required")
    learner = db.get(Learner, session.learner_id)
    if learner is None:
        raise HTTPException(status_code=404, detail="Learner not found")
    profile = default_profile_for_learner(db, learner)
    try:
        _, reply, feedback, task, output = add_learner_message(
            db,
            session=session,
            profile=profile,
            content=content,
            evidence=list((payload or {}).get("evidence") or []),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    if task:
        background_tasks.add_task(run_generation_task, task.public_id)
    return ok(
        {
            "session_id": session.public_id,
            "reply": {
                "message_id": reply.public_id,
                "message_type": reply.message_type,
                "content": reply.content,
                "sources": output.get("sources", []),
                "scope_status": output.get("scope_status"),
                "assessment": output.get("assessment"),
            },
            "feedback_intent": output["feedback_intent"],
            "recommended_action": feedback.recommended_action,
            "profile_update_required": feedback.feedback_intent in {"too_hard", "too_easy"}
            and any(
                item.get("type") in {"scored_quiz", "diagnostic_result", "validated_behavior"}
                and (
                    float(item.get("confidence", 0) or 0) >= 0.7
                    or item.get("confirmed") is True
                )
                for item in (feedback.profile_change_evidence_json or [])
                if isinstance(item, dict)
            ),
            "decision_reason": feedback.decision_reason,
            "task_id": task.public_id if task else None,
        }
    )


@router.post("/sessions/{session_id}/messages/stream")
def stream_tutoring_message(
    session_id: str, payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db), principal: Principal = Depends(get_current_user),
) -> StreamingResponse:
    session = require_tutoring(db, principal, session_id)
    content = str((payload or {}).get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=422, detail="content is required")
    learner_message, reply, resource = create_streaming_messages(db, session=session, content=content)
    db.commit()
    payload_context, sources, scope_status, assessment = stream_context_for_message(
        db, session=session, resource=resource, content=content
    )

    def generate():
        accumulated = ""
        yield _event("accepted", {"session_id": session_id, "learner_message_id": learner_message.public_id, "reply_message_id": reply.public_id})
        try:
            for delta in gateway.stream_text(model=settings.primary_llm_model, system_prompt=SYSTEM_PROMPT, payload=payload_context):
                with SessionLocal() as stream_db:
                    current = stream_db.get(TutoringMessage, reply.id)
                    if current is None or (current.metadata_json or {}).get("stream_status") == "paused":
                        yield _event("paused", {"reply_message_id": reply.public_id, "content": accumulated})
                        return
                    accumulated += delta
                    update_streaming_reply(stream_db, reply=current, content=accumulated)
                yield _event("delta", {"reply_message_id": reply.public_id, "content": delta})
            with SessionLocal() as stream_db:
                current = stream_db.get(TutoringMessage, reply.id)
                if current is not None:
                    update_streaming_reply(stream_db, reply=current, content=accumulated, status="completed", sources=sources, scope_status=scope_status, assessment=assessment)
            yield _event("completed", {"reply_message_id": reply.public_id, "content": accumulated, "sources": sources, "scope_status": scope_status, "assessment": assessment, "task_id": None})
        except ModelGatewayError as exc:
            with SessionLocal() as stream_db:
                current = stream_db.get(TutoringMessage, reply.id)
                if current is not None:
                    update_streaming_reply(stream_db, reply=current, content=accumulated, status="interrupted" if accumulated else "failed", error_code=type(exc).__name__)
            yield _event("error", {"reply_message_id": reply.public_id, "code": type(exc).__name__, "recoverable": bool(accumulated)})
        except Exception:
            with SessionLocal() as stream_db:
                current = stream_db.get(TutoringMessage, reply.id)
                if current is not None:
                    update_streaming_reply(stream_db, reply=current, content=accumulated, status="interrupted" if accumulated else "failed", error_code="stream_failed")
            yield _event("error", {"reply_message_id": reply.public_id, "code": "stream_failed", "recoverable": bool(accumulated)})

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
