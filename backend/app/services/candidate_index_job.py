"""Persisted, incremental candidate index rebuild job.

The rebuild is triggered from the admin UI and runs through FastAPI
``BackgroundTasks`` inside the single API process. Job records are persisted in
``index_build_jobs`` so the status survives page refreshes and restarts; a job
still marked ``running`` at startup is marked ``interrupted`` because the
in-process task dies with the process.

The build itself is incremental-first: it reuses unchanged vectors and only
embeds changed/new chunks, falling back to a full reset when the manifest is
missing or the embedding model changed (the only cases that require it).
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import IndexBuildJob
from app.rag.candidate_index import CandidateIndexError

logger = logging.getLogger(__name__)

STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_INTERRUPTED = "interrupted"

_start_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(UTC)


def serialize_job(job: IndexBuildJob) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "status": job.status,
        "running": job.status == STATUS_RUNNING,
        "domain_code": job.domain_code,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "message": job.message,
        "result": job.result_json,
    }


def latest_job(db: Session, domain_code: str | None = None) -> IndexBuildJob | None:
    statement = select(IndexBuildJob).order_by(IndexBuildJob.id.desc())
    if domain_code:
        statement = statement.where(IndexBuildJob.domain_code == domain_code)
    return db.scalar(statement)


def try_start(db: Session, domain_code: str) -> IndexBuildJob | None:
    """Create a ``running`` job, or return None if one is already running."""
    with _start_lock:
        running = db.scalar(select(IndexBuildJob).where(IndexBuildJob.status == STATUS_RUNNING))
        if running is not None:
            return None
        job = IndexBuildJob(
            domain_code=domain_code,
            status=STATUS_RUNNING,
            started_at=_now(),
            message="",
            result_json=None,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job


def mark_interrupted_on_startup() -> None:
    """Mark any stale ``running`` job as interrupted after a restart."""
    try:
        with SessionLocal() as db:
            stale = list(
                db.scalars(select(IndexBuildJob).where(IndexBuildJob.status == STATUS_RUNNING))
            )
            for job in stale:
                job.status = STATUS_INTERRUPTED
                job.finished_at = _now()
                job.message = "服务重启，重建任务中断"
            if stale:
                db.commit()
    except Exception:
        logger.warning("index build job startup cleanup skipped", exc_info=True)


def _build(domain_code: str) -> dict[str, Any]:
    from app.scripts.build_chroma_candidate_index import build_candidate_index

    try:
        return build_candidate_index(domain_code=domain_code, reset=False, live=True)
    except CandidateIndexError as exc:
        if "run with --reset" in str(exc):
            logger.info(
                "candidate index incremental build unavailable; falling back to full reset domain=%s",
                domain_code,
            )
            return build_candidate_index(domain_code=domain_code, reset=True, live=True)
        raise


def run_rebuild(job_id: int, domain_code: str) -> None:
    """Background entrypoint: run the build and persist its outcome."""
    try:
        result = _build(domain_code)
        with SessionLocal() as db:
            job = db.get(IndexBuildJob, job_id)
            if job is not None:
                job.status = STATUS_SUCCESS
                job.finished_at = _now()
                job.message = "候选索引重建完成"
                job.result_json = result
                db.commit()
        logger.info(
            "candidate index rebuild finished domain=%s mode=%s items=%s chunks=%s duration_ms=%s",
            domain_code,
            result.get("mode"),
            result.get("indexed_items"),
            result.get("indexed_chunks"),
            result.get("duration_ms"),
        )
    except Exception as exc:
        with SessionLocal() as db:
            job = db.get(IndexBuildJob, job_id)
            if job is not None:
                job.status = STATUS_FAILED
                job.finished_at = _now()
                job.message = f"{type(exc).__name__}: {exc}"
                db.commit()
        logger.warning(
            "candidate index rebuild failed domain=%s error_type=%s",
            domain_code,
            type(exc).__name__,
        )


def status(db: Session, domain_code: str | None = None) -> dict[str, Any]:
    job = latest_job(db, domain_code)
    if job is None:
        return {
            "job_id": None,
            "status": "idle",
            "running": False,
            "domain_code": "",
            "started_at": None,
            "finished_at": None,
            "message": "",
            "result": None,
        }
    return serialize_job(job)
