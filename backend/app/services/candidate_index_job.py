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
from app.models import Domain, IndexBuildJob
from app.rag.candidate_index import CandidateIndexBuilder, CandidateIndexError
from app.rag.embedding_provider import OpenAICompatibleEmbeddingProvider
from app.rag.vector_store import VectorStore

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
        "source_document_id": job.source_document_id,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "message": job.message,
        "result": job.result_json,
    }


def latest_job(
    db: Session,
    domain_code: str | None = None,
    *,
    source_document_id: int | None = None,
) -> IndexBuildJob | None:
    statement = select(IndexBuildJob).order_by(IndexBuildJob.id.desc())
    if domain_code:
        statement = statement.where(IndexBuildJob.domain_code == domain_code)
    if source_document_id is not None:
        statement = statement.where(IndexBuildJob.source_document_id == source_document_id)
    return db.scalar(statement)


def try_start(
    db: Session,
    domain_code: str,
    *,
    source_document_id: int | None = None,
) -> IndexBuildJob | None:
    """Create a ``running`` job, or return None if one is already running."""
    with _start_lock:
        domain = db.scalar(
            select(Domain).where(Domain.domain_code == domain_code).with_for_update()
        )
        if domain is None:
            raise CandidateIndexError(f"domain does not exist: {domain_code}")
        running = db.scalar(
            select(IndexBuildJob).where(
                IndexBuildJob.domain_code == domain_code,
                IndexBuildJob.status == STATUS_RUNNING,
            )
        )
        if running is not None:
            return None
        job = IndexBuildJob(
            domain_code=domain_code,
            source_document_id=source_document_id,
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


def _build(
    domain_code: str,
    *,
    reset: bool = False,
    staged_document_id: int | None = None,
) -> dict[str, Any]:
    from app.scripts.build_chroma_candidate_index import build_candidate_index

    try:
        return build_candidate_index(
            domain_code=domain_code,
            reset=reset,
            live=True,
            activate=False,
            staged_document_id=staged_document_id,
        )
    except CandidateIndexError as exc:
        if "run with --reset" in str(exc):
            logger.info(
                "candidate index incremental build unavailable; falling back to full reset domain=%s",
                domain_code,
            )
            return build_candidate_index(
                domain_code=domain_code,
                reset=True,
                live=True,
                activate=False,
                staged_document_id=staged_document_id,
            )
        raise


def _builder(db: Session) -> CandidateIndexBuilder:
    return CandidateIndexBuilder(
        db=db,
        chroma_client=VectorStore().client,
        embedding_provider=OpenAICompatibleEmbeddingProvider(),
    )


def run_rebuild(job_id: int, domain_code: str, *, reset: bool = False) -> None:
    """Automatic build, smoke and activation for a normal rebuild."""
    result: dict[str, Any] | None = None
    activated = False
    try:
        from app.services.question_source_binding_service import (
            bind_domain_question_sources,
        )

        with SessionLocal() as db:
            bind_domain_question_sources(db, domain_code=domain_code)
            db.commit()
        result = _build(domain_code, reset=reset)
        with SessionLocal() as db:
            from app.services.knowledge_import_publish_service import smoke_domain_index

            manifest_payload = result["candidate_manifest"]
            smoke = smoke_domain_index(
                db,
                domain_code,
                manifest_payload=manifest_payload,
            )
            result["smoke_test"] = {
                **smoke,
                "index_version": result.get("index_version"),
                "active_collection": manifest_payload.get("active_collection"),
                "checked_at": _now().isoformat(),
            }
            job = db.get(IndexBuildJob, job_id)
            if job is None:
                raise CandidateIndexError("index build job disappeared")
            previous = None
            try:
                if result["status"] != "unchanged":
                    previous = _builder(db).activate_candidate(manifest_payload)
                    activated = True
                job.status = STATUS_SUCCESS
                job.finished_at = _now()
                job.message = "候选索引重建完成"
                job.result_json = result
                db.commit()
            except Exception:
                db.rollback()
                if activated:
                    _builder(db).restore_manifest(domain_code, previous)
                    activated = False
                raise
            if result["status"] != "unchanged":
                try:
                    result["old_collections_deleted"] = _builder(
                        db
                    ).cleanup_after_activation(manifest_payload)
                    job = db.get(IndexBuildJob, job_id)
                    if job is not None:
                        job.result_json = result
                        db.commit()
                except Exception:
                    logger.warning("candidate cleanup failed domain=%s", domain_code, exc_info=True)
        logger.info(
            "candidate index rebuild finished domain=%s mode=%s items=%s chunks=%s duration_ms=%s",
            domain_code,
            result.get("mode"),
            result.get("indexed_items"),
            result.get("indexed_chunks"),
            result.get("duration_ms"),
        )
    except Exception as exc:
        if result is not None and result.get("status") != "unchanged" and not activated:
            try:
                with SessionLocal() as cleanup_db:
                    _builder(cleanup_db).discard_candidate(result["candidate_manifest"])
            except Exception:
                logger.warning("candidate discard failed domain=%s", domain_code, exc_info=True)
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


def run_import_build(
    job_id: int,
    domain_code: str,
    source_document_id: int,
    *,
    reset: bool = False,
) -> None:
    """Build an import candidate but leave smoke and activation to admin actions."""
    result: dict[str, Any] | None = None
    try:
        result = _build(
            domain_code,
            reset=reset,
            staged_document_id=source_document_id,
        )
        with SessionLocal() as db:
            job = db.get(IndexBuildJob, job_id)
            if job is None or job.source_document_id != source_document_id:
                raise CandidateIndexError("import index build job disappeared")
            job.status = STATUS_SUCCESS
            job.finished_at = _now()
            job.message = "导入候选索引构建完成，等待冒烟"
            job.result_json = result
            db.commit()
    except Exception as exc:
        if result is not None and result.get("status") != "unchanged":
            try:
                with SessionLocal() as cleanup_db:
                    _builder(cleanup_db).discard_candidate(result["candidate_manifest"])
            except Exception:
                logger.warning("import candidate discard failed", exc_info=True)
        with SessionLocal() as db:
            job = db.get(IndexBuildJob, job_id)
            if job is not None:
                job.status = STATUS_FAILED
                job.finished_at = _now()
                job.message = f"{type(exc).__name__}: {exc}"
                db.commit()
        logger.warning(
            "import candidate build failed domain=%s source_document_id=%s error_type=%s",
            domain_code,
            source_document_id,
            type(exc).__name__,
        )


def discard_change_set_candidates(manifests: list[dict[str, Any]]) -> None:
    """Best-effort cleanup for unactivated import collections after cancellation."""
    if not manifests:
        return
    try:
        with SessionLocal() as db:
            builder = _builder(db)
            seen: set[str] = set()
            for manifest in manifests:
                collection = str(manifest.get("active_collection") or "")
                if not collection or collection in seen:
                    continue
                seen.add(collection)
                try:
                    builder.discard_candidate(manifest)
                except Exception:
                    logger.warning(
                        "cancelled import candidate cleanup failed collection=%s",
                        collection,
                        exc_info=True,
                    )
    except Exception:
        logger.warning("cancelled import candidate cleanup setup failed", exc_info=True)


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
