from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from threading import BoundedSemaphore
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import KnowledgeImportBatch, KnowledgeImportRun
from app.services.llm_service import ResponseAdapter, gateway


ResponseModel = TypeVar("ResponseModel", bound=BaseModel)
PROMPT_VERSION = "knowledge-import-v2"
_GLOBAL_SEMAPHORE = BoundedSemaphore(max(1, settings.knowledge_import_model_concurrency))
_GENERATION_SEMAPHORE = BoundedSemaphore(
    max(1, settings.knowledge_import_generation_concurrency)
)
_REVIEW_SEMAPHORE = BoundedSemaphore(max(1, settings.knowledge_import_review_concurrency))


def estimate_tokens(value: object) -> int:
    """Conservative dependency-free estimate for mixed Chinese/Latin JSON."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    cjk = sum("\u3400" <= char <= "\u9fff" for char in text)
    return cjk + max(1, (len(text) - cjk + 3) // 4)


def pack_by_tokens(
    records: Sequence[dict[str, Any]],
    *,
    max_records: int,
    target_tokens: int | None = None,
    envelope_tokens: int = 800,
) -> list[list[dict[str, Any]]]:
    target = target_tokens or settings.knowledge_import_batch_target_tokens
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_tokens = envelope_tokens
    for record in records:
        record_tokens = estimate_tokens(record) + 24
        if current and (
            len(current) >= max_records or current_tokens + record_tokens > target
        ):
            batches.append(current)
            current = []
            current_tokens = envelope_tokens
        current.append(record)
        current_tokens += record_tokens
    if current:
        batches.append(current)
    return batches


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def prepare_batch(
    db: Session,
    run: KnowledgeImportRun,
    *,
    step: str,
    batch_key: str,
    payload: dict[str, Any],
    model_name: str | None,
    prompt_version: str = PROMPT_VERSION,
) -> KnowledgeImportBatch:
    input_hash = _canonical_hash(
        {"payload": payload, "model": model_name, "prompt_version": prompt_version}
    )
    batch = db.scalar(
        select(KnowledgeImportBatch).where(
            KnowledgeImportBatch.run_id == run.id,
            KnowledgeImportBatch.step == step,
            KnowledgeImportBatch.batch_key == batch_key,
            KnowledgeImportBatch.input_hash == input_hash,
        )
    )
    if batch is None:
        batch = KnowledgeImportBatch(
            run_id=run.id,
            step=step,
            batch_key=batch_key,
            input_hash=input_hash,
            prompt_version=prompt_version,
            model_name=model_name,
            status="pending",
            artifact_json={},
        )
        db.add(batch)
        db.flush()
    return batch


def execute_json_batch(
    batch_id: int,
    *,
    model: str | None,
    system_prompt: str,
    payload: dict[str, Any],
    response_model: type[ResponseModel],
    response_adapter: ResponseAdapter | None = None,
    max_output_tokens: int,
    role: str,
    repair_truncated_output: bool = False,
) -> dict[str, Any]:
    owner = f"batch_{batch_id}_{datetime.now(UTC).timestamp():.0f}"
    with SessionLocal() as db:
        batch = db.get(KnowledgeImportBatch, batch_id)
        if batch is None:
            raise RuntimeError("knowledge import batch not found")
        if batch.status == "succeeded" and batch.artifact_json:
            result = dict(batch.artifact_json)
            batch.reuse_count += 1
            db.commit()
            return result
        now = datetime.now(UTC)
        if batch.lease_owner and batch.lease_expires_at and batch.lease_expires_at > now:
            raise RuntimeError("knowledge import batch is already running")
        batch.status = "running"
        batch.attempt_count += 1
        batch.lease_owner = owner
        batch.lease_expires_at = now + timedelta(
            seconds=settings.knowledge_import_batch_lease_seconds
        )
        batch.error_code = None
        batch.error_summary = None
        run = db.get(KnowledgeImportRun, batch.run_id)
        if run is not None:
            run.lease_expires_at = now + timedelta(
                seconds=settings.knowledge_import_batch_lease_seconds
            )
        db.commit()

    role_semaphore = _REVIEW_SEMAPHORE if role == "review" else _GENERATION_SEMAPHORE
    try:
        with _GLOBAL_SEMAPHORE, role_semaphore:
            result, metadata = gateway.complete_json(
                model=model,
                system_prompt=system_prompt,
                payload=payload,
                response_model=response_model,
                response_adapter=response_adapter,
                max_output_tokens=max_output_tokens,
                repair_truncated_output=repair_truncated_output,
            )
        with SessionLocal() as db:
            batch = db.get(KnowledgeImportBatch, batch_id)
            if batch is None:
                raise RuntimeError("knowledge import batch disappeared")
            batch.status = "succeeded"
            batch.artifact_json = result
            batch.artifact_hash = _canonical_hash(result)
            batch.model_name = str(metadata.get("model_name") or model or "") or None
            batch.tokens_input = int(metadata.get("tokens_input") or 0)
            batch.tokens_output = int(metadata.get("tokens_output") or 0)
            batch.duration_ms = int(metadata.get("duration_ms") or 0)
            batch.lease_owner = None
            batch.lease_expires_at = None
            run = db.get(KnowledgeImportRun, batch.run_id)
            if run is not None:
                run.lease_expires_at = datetime.now(UTC) + timedelta(
                    seconds=settings.knowledge_import_batch_lease_seconds
                )
            db.commit()
        return result
    except Exception as exc:
        with SessionLocal() as db:
            batch = db.get(KnowledgeImportBatch, batch_id)
            if batch is not None:
                batch.status = "failed"
                batch.error_code = type(exc).__name__
                batch.error_summary = str(exc)[:1000]
                batch.lease_owner = None
                batch.lease_expires_at = None
                db.commit()
        raise


def batch_progress(db: Session, run_id: int) -> dict[str, int]:
    rows = db.execute(
        select(KnowledgeImportBatch.status, func.count(KnowledgeImportBatch.id))
        .where(KnowledgeImportBatch.run_id == run_id)
        .group_by(KnowledgeImportBatch.status)
    ).all()
    counts = {str(status): int(count) for status, count in rows}
    total = sum(counts.values())
    aggregates = db.execute(
        select(
            func.coalesce(func.sum(KnowledgeImportBatch.tokens_input), 0),
            func.coalesce(func.sum(KnowledgeImportBatch.tokens_output), 0),
            func.coalesce(func.sum(KnowledgeImportBatch.duration_ms), 0),
            func.coalesce(func.sum(KnowledgeImportBatch.reuse_count), 0),
        ).where(KnowledgeImportBatch.run_id == run_id)
    ).one()
    completed = counts.get("succeeded", 0)
    average_ms = int(aggregates[2]) / completed if completed else 0
    remaining = max(0, total - completed - counts.get("failed", 0))
    return {
        "completed_batches": completed,
        "failed_batches": counts.get("failed", 0),
        "running_batches": counts.get("running", 0),
        "total_batches": total,
        "reused_batches": int(aggregates[3]),
        "model_calls": sum(counts.values()),
        "tokens_input": int(aggregates[0]),
        "tokens_output": int(aggregates[1]),
        "model_duration_ms": int(aggregates[2]),
        "eta_seconds": int(
            remaining * average_ms / max(1, settings.knowledge_import_model_concurrency) / 1000
        ),
    }


def run_parallel(
    jobs: Sequence[Callable[[], Any]], *, max_workers: int
) -> list[Any]:
    if not jobs:
        return []
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(len(jobs), max(1, max_workers))) as executor:
        futures = [executor.submit(job) for job in jobs]
        results: list[Any] = []
        for future in futures:
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(exc)
        return results
