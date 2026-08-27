from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, get_db
from app.models import Domain, KnowledgeDocument, KnowledgeImportCandidate, KnowledgeImportRun
from app.rag.candidate_index import CandidateIndexBuilder
from app.rag.embedding_provider import OpenAICompatibleEmbeddingProvider
from app.rag.vector_store import VectorStore
from app.schemas.common import ApiResponse, ok
from app.services import candidate_index_job
from app.services.knowledge_import_publish_service import (
    KnowledgeImportPublishError,
    activate_import_candidate,
    approve_candidates,
    ensure_import_source_locators,
    publish_approved,
    smoke_domain_index,
    smoke_import_index,
)
from app.services.knowledge_import_validation_service import validate_import
from app.services.ability_weight_service import normalize_ability_weights
from app.services.knowledge_import_orchestrator import resolve_run, serialize_run

router = APIRouter()


def _run_import_index(job_id: int, domain_code: str, document_id: int) -> None:
    candidate_index_job.run_import_build(job_id, domain_code, document_id)
    with SessionLocal() as db:
        job = db.get(candidate_index_job.IndexBuildJob, job_id)
        document = db.get(KnowledgeDocument, document_id)
        if document is None or job is None:
            return
        if job.status == candidate_index_job.STATUS_FAILED:
            document.status = "index_pending"
            document.error_summary = job.message
        else:
            document.error_summary = None
        db.commit()


class CandidatePatch(BaseModel):
    payload: dict[str, Any] | None = None
    status: str | None = Field(default=None, pattern="^(pending|rejected|needs_edit)$")


class ApproveRequest(BaseModel):
    candidate_ids: list[str] | None = None


class ConfirmPublishRequest(BaseModel):
    input_version: str
    index_version: str


def _document(db: Session, import_id: str) -> KnowledgeDocument:
    try:
        _, document = resolve_run(db, import_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Knowledge import not found")
    return document


def _run(db: Session, import_id: str) -> tuple[KnowledgeImportRun, KnowledgeDocument]:
    try:
        return resolve_run(db, import_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Knowledge import not found") from exc


def _serialize(candidate: KnowledgeImportCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.public_id,
        "candidate_type": candidate.candidate_type,
        "payload": candidate.payload_json or {},
        "source_locator": candidate.source_locator_json or {},
        "confidence": candidate.confidence,
        "status": candidate.status,
        "validation_errors": candidate.validation_errors_json or [],
    }


@router.get("/{import_id}", response_model=ApiResponse)
def get_import(import_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    run, document = _run(db, import_id)
    candidates = list(
        db.scalars(
            select(KnowledgeImportCandidate).where(
                KnowledgeImportCandidate.document_id == document.id
            )
        )
    )
    return ok(
        {
            **serialize_run(run),
            "document_public_id": document.public_id,
            "candidate_counts": dict(Counter(item.candidate_type for item in candidates)),
            "review_counts": dict(Counter(item.status for item in candidates)),
        }
    )


@router.post("/{import_id}/cancel", response_model=ApiResponse)
def cancel_import(import_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    run, document = _run(db, import_id)
    if run.status in {"ready", "ready_to_publish", "needs_attention", "failed", "cancelled", "deleted"}:
        raise HTTPException(status_code=409, detail="当前导入已结束，无法中断")
    run.status = "cancel_requested"
    run.error_code = "import_cancel_requested"
    run.error_summary = "已请求中断，正在等待当前模型调用结束"
    document.error_summary = run.error_summary
    db.commit()
    return ok({**serialize_run(run), "cancel_requested": True})
@router.get("/{import_id}/summary", response_model=ApiResponse)
def import_summary(import_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    run, document = _run(db, import_id)
    candidates = list(db.scalars(select(KnowledgeImportCandidate).where(
        KnowledgeImportCandidate.document_id == document.id
    )))
    counts = Counter(item.candidate_type for item in candidates)
    relations = [item for item in candidates if item.candidate_type == "knowledge_relation"]
    factual_relations = [
        item for item in relations
        if (item.payload_json or {}).get("evidence_kind") == "text_quote"
    ]
    recommended_relations = [
        item for item in relations
        if (item.payload_json or {}).get("evidence_kind") == "curriculum_rule"
    ]
    artifacts = dict(run.artifact_manifest_json or {})
    readiness = artifacts.get("projected_readiness") or {}
    smoke = artifacts.get("smoke_test") or {}
    retrieval_checks = ((smoke.get("checks") or {}).get("import") or {})
    retrieval_hit_rate = (
        sum(bool(check.get("passed")) for check in retrieval_checks.values())
        / len(retrieval_checks)
        if retrieval_checks else 0.0
    )
    return ok({
        **serialize_run(run),
        "document_public_id": document.public_id,
        "knowledge_items": counts["knowledge_item"],
        "diagnostic_questions": counts["diagnostic_question"],
        "relations_generated": len(relations),
        "relations_accepted": sum(not item.validation_errors_json for item in relations),
        "relations_filtered": sum(bool(item.validation_errors_json) for item in relations),
        "factual_relations": len(factual_relations),
        "recommended_relations": len(recommended_relations),
        "source_traceability": (
            sum(bool((item.source_locator_json or {}).get("chunk_id")) for item in candidates)
            / len(candidates) if candidates else 0
        ),
        "directional_relations": readiness.get("directional_relations", 0),
        "related_relations": readiness.get("related_relations", 0),
        "path_participating_nodes": readiness.get("path_participating_nodes", 0),
        "path_participation_ratio": readiness.get("path_participation_ratio", 0),
        "isolated_nodes": readiness.get("isolated_nodes", 0),
        "isolated_node_ratio": readiness.get("isolated_node_ratio", 0),
        "cycle_count": readiness.get("cycle_count", 0),
        "unresolved_relation_conflicts": readiness.get("unresolved_relation_conflicts", 0),
        "question_knowledge_coverage": readiness.get("question_knowledge_coverage", 0),
        "ability_weights_ready": readiness.get("ability_weights_ready", 0),
        "ability_weights_missing": readiness.get("ability_weights_missing", 0),
        "ability_weight_blocking_ids": readiness.get("ability_weight_blocking_ids", []),
        "retrieval_hit_rate": retrieval_hit_rate,
        "repair_rounds": artifacts.get("repair_rounds", 0),
        "quality_gate_passed": readiness.get("quality_gate_passed", False),
        "blocking_issues": readiness.get("blocking_issues", []),
        "direction_metrics": readiness.get("direction_metrics", []),
        "projected_readiness": readiness,
        "candidate_manifest": artifacts.get("candidate_manifest"),
        "smoke_test": artifacts.get("smoke_test"),
        "quality_baseline_version": artifacts.get("quality_baseline_version", "knowledge-import-gold-v1"),
    })


@router.get("/{import_id}/graph-preview", response_model=ApiResponse)
def graph_preview(import_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    run, document = _run(db, import_id)
    candidates = list(db.scalars(select(KnowledgeImportCandidate).where(
        KnowledgeImportCandidate.document_id == document.id
    )))
    readiness = (run.artifact_manifest_json or {}).get("projected_readiness") or {}
    isolated_ids = set(readiness.get("isolated_node_ids") or [])
    domain = db.scalar(select(Domain).where(Domain.domain_code == document.domain_code))
    directions = list(readiness.get("proposed_learning_directions") or [])
    if not directions:
        directions = list((domain.config_json if domain else {}).get("learning_directions") or [])
    nodes = []
    edges = []
    for candidate in candidates:
        payload = candidate.payload_json or {}
        if candidate.candidate_type == "knowledge_item":
            target_id = payload.get("target_public_id")
            tags = {str(tag).casefold() for tag in payload.get("tags") or []}
            node_directions = [
                str(direction.get("value"))
                for direction in directions
                if tags & {str(tag).casefold() for tag in direction.get("match_tags") or []}
            ]
            nodes.append({
                "id": candidate.public_id,
                "knowledge_id": payload.get("target_public_id"),
                "name": payload.get("name"),
                "category": payload.get("category"),
                "difficulty": payload.get("difficulty"),
                "tags": payload.get("tags") or [],
                "action": payload.get("action"),
                "source_chunk_ids": payload.get("source_chunk_ids") or [],
                "directions": node_directions,
                "isolated": target_id in isolated_ids,
                "path_participating": target_id not in isolated_ids,
                "source_complete": bool((candidate.source_locator_json or {}).get("chunk_id")),
            })
        elif candidate.candidate_type == "knowledge_relation":
            edges.append({
                "id": candidate.public_id,
                "source": payload.get("source_candidate_id"),
                "target": payload.get("target_candidate_id"),
                "relation_type": payload.get("relation_type"),
                "confidence": candidate.confidence,
                "accepted": not bool(candidate.validation_errors_json),
                "reason": payload.get("reason"),
                "evidence": payload.get("source_quote") or payload.get("evidence_chunk_ids") or [],
                "review_result": "accepted" if not candidate.validation_errors_json else "filtered",
                "evidence_kind": payload.get("evidence_kind") or "text_quote",
                "score_components": payload.get("score_components") or {},
                "generation_method": payload.get("generation_method"),
                "review_verdict": payload.get("review_verdict"),
                "filter_reasons": candidate.validation_errors_json or [],
            })
    return ok({"import_id": import_id, "nodes": nodes, "edges": edges})


@router.post("/{import_id}/confirm-publish", response_model=ApiResponse)
def confirm_publish(
    import_id: str, payload: ConfirmPublishRequest, db: Session = Depends(get_db)
) -> ApiResponse:
    run, document = _run(db, import_id)
    if run.status == "ready":
        return ok({**serialize_run(run), "status": "ready"})
    if run.status != "ready_to_publish":
        readiness = (run.artifact_manifest_json or {}).get("projected_readiness") or {}
        raise HTTPException(status_code=409, detail={
            "message": "导入尚未通过自动质量门禁",
            "blocking_issues": readiness.get("blocking_issues") or [],
        })
    artifacts = dict(run.artifact_manifest_json or {})
    manifest = artifacts.get("candidate_manifest") or {}
    if payload.input_version != run.input_version or payload.index_version != manifest.get("index_version"):
        raise HTTPException(status_code=409, detail="导入预览版本已变化，请刷新后重新确认")
    job = candidate_index_job.latest_job(
        db, document.domain_code, source_document_id=document.id
    )
    if job is None:
        raise HTTPException(status_code=409, detail="候选索引任务不存在")
    run.status = "publishing"
    run.current_step = "publishing"
    document.status = "publishing"
    db.flush()
    try:
        result = activate_import_candidate(db, document, job)
    except KnowledgeImportPublishError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ok({**result, "run_id": run.public_id, "input_version": run.input_version})


@router.get("/{import_id}/candidates", response_model=ApiResponse)
def list_candidates(import_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    document = _document(db, import_id)
    candidates = list(
        db.scalars(
            select(KnowledgeImportCandidate)
            .where(KnowledgeImportCandidate.document_id == document.id)
            .order_by(KnowledgeImportCandidate.id)
        )
    )
    return ok({"import_id": import_id, "candidates": [_serialize(item) for item in candidates]})


@router.patch("/{import_id}/candidates/{candidate_id}", response_model=ApiResponse)
def patch_candidate(
    import_id: str, candidate_id: str, payload: CandidatePatch, db: Session = Depends(get_db)
) -> ApiResponse:
    document = _document(db, import_id)
    candidate = db.scalar(
        select(KnowledgeImportCandidate).where(
            KnowledgeImportCandidate.document_id == document.id,
            KnowledgeImportCandidate.public_id == candidate_id,
        )
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Knowledge import candidate not found")
    if candidate.status in {"approved", "published"}:
        raise HTTPException(status_code=409, detail="已批准或发布的候选不可修改")
    if payload.payload is not None:
        next_payload = dict(payload.payload)
        if candidate.candidate_type == "knowledge_item":
            next_weights = normalize_ability_weights(next_payload.get("ability_weights"))
            if next_weights is not None:
                next_payload["ability_weights"] = next_weights
                next_payload["ability_weight_source"] = "admin"
                next_payload["ability_weight_confidence"] = 1.0
        candidate.payload_json = next_payload
    if payload.status is not None:
        candidate.status = payload.status
    candidate.validation_errors_json = []
    db.commit()
    db.refresh(candidate)
    return ok(_serialize(candidate))


@router.post("/{import_id}/validate", response_model=ApiResponse)
def validate_candidates(import_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    document = _document(db, import_id)
    if document.status in {"index_pending", "indexing", "ready"}:
        raise HTTPException(status_code=409, detail="当前导入阶段不允许重新校验")
    return ok(validate_import(db, document.id))


@router.post("/{import_id}/approve", response_model=ApiResponse)
def approve_import(
    import_id: str, payload: ApproveRequest, db: Session = Depends(get_db)
) -> ApiResponse:
    document = _document(db, import_id)
    if document.status != "review_pending":
        raise HTTPException(status_code=409, detail="只有待复核导入可以批准")
    result = validate_import(db, document.id)
    if result["invalid"]:
        raise HTTPException(status_code=422, detail="存在未通过校验的候选")
    try:
        approved = approve_candidates(db, document, payload.candidate_ids)
        published = publish_approved(db, document)
    except KnowledgeImportPublishError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ok({"approved": approved, **published, "next_action": "build-index"})


@router.post("/{import_id}/build-index", response_model=ApiResponse)
def build_index(
    import_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> ApiResponse:
    document = _document(db, import_id)
    previous_job = candidate_index_job.latest_job(
        db,
        document.domain_code,
        source_document_id=document.id,
    )
    failed_retry = bool(
        document.status == "indexing"
        and previous_job
        and previous_job.domain_code == document.domain_code
        and previous_job.status
        in {
            candidate_index_job.STATUS_FAILED,
            candidate_index_job.STATUS_INTERRUPTED,
        }
    )
    if document.status != "index_pending" and not failed_retry:
        raise HTTPException(status_code=409, detail="导入尚未批准或已进入其他阶段")
    ensure_import_source_locators(db, document)
    job = candidate_index_job.try_start(
        db,
        document.domain_code,
        source_document_id=document.id,
    )
    if job is None:
        raise HTTPException(status_code=409, detail="候选索引正在重建")
    document.status = "indexing"
    db.commit()
    background_tasks.add_task(_run_import_index, job.id, document.domain_code, document.id)
    return ok({"job_id": job.id, "status": "running", "domain_code": document.domain_code})


@router.post("/{import_id}/smoke-test", response_model=ApiResponse)
def smoke_test(import_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    document = _document(db, import_id)
    job = candidate_index_job.latest_job(
        db,
        document.domain_code,
        source_document_id=document.id,
    )
    result = dict(job.result_json or {}) if job else {}
    manifest_payload = result.get("candidate_manifest")
    passed = bool(
        job
        and job.domain_code == document.domain_code
        and job.source_document_id == document.id
        and job.status == candidate_index_job.STATUS_SUCCESS
        and isinstance(manifest_payload, dict)
    )
    if not passed:
        raise HTTPException(status_code=409, detail="Candidate 索引尚未通过构建与就绪检查")
    try:
        retrieval = smoke_import_index(
            db,
            document,
            manifest_payload=manifest_payload,
        )
        isolation = smoke_domain_index(
            db,
            document.domain_code,
            manifest_payload=manifest_payload,
            staged_document_id=document.id,
        )
    except Exception as exc:
        builder = CandidateIndexBuilder(
            db=db,
            chroma_client=VectorStore().client,
            embedding_provider=OpenAICompatibleEmbeddingProvider(),
        )
        try:
            builder.discard_candidate(manifest_payload)
        except Exception:
            pass
        job.status = candidate_index_job.STATUS_FAILED
        job.finished_at = datetime.now(UTC)
        job.message = str(exc)
        document.status = "index_pending"
        message = str(exc) if isinstance(exc, KnowledgeImportPublishError) else "候选索引冒烟失败"
        document.error_summary = message
        db.commit()
        raise HTTPException(status_code=409, detail=message) from exc
    result["smoke_test"] = {
        "passed": True,
        "index_version": manifest_payload.get("index_version"),
        "active_collection": manifest_payload.get("active_collection"),
        "import_id": document.public_id,
        "checked_at": datetime.now(UTC).isoformat(),
        "checks": {
            "import": retrieval.get("checks", {}),
            "domain": isolation.get("checks", {}),
        },
    }
    job.result_json = result
    document.status = "smoke_passed"
    document.error_summary = None
    db.commit()
    return ok(
        {
            **retrieval,
            "candidate_manifest": manifest_payload,
        }
    )


@router.post("/{import_id}/publish", response_model=ApiResponse)
def publish_import(import_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    document = _document(db, import_id)
    if document.status != "smoke_passed":
        raise HTTPException(status_code=409, detail="检索冒烟尚未通过，不能发布")
    job = candidate_index_job.latest_job(
        db,
        document.domain_code,
        source_document_id=document.id,
    )
    if (
        not job
        or job.domain_code != document.domain_code
        or job.source_document_id != document.id
        or job.status != candidate_index_job.STATUS_SUCCESS
    ):
        raise HTTPException(status_code=409, detail="索引构建或冒烟未通过，不能发布")
    try:
        published = activate_import_candidate(db, document, job)
    except KnowledgeImportPublishError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ok(published)


@router.get("/{import_id}/events")
def import_events(
    import_id: str,
    last_event_id: int = 0,
    last_event_id_header: int | None = Header(default=None, alias="Last-Event-ID"),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    run, _ = _run(db, import_id)
    cursor = last_event_id_header if last_event_id_header is not None else last_event_id
    events = [
        event
        for event in (run.step_state_json or {}).get("events", [])
        if int(event.get("event_id", 0)) > cursor
    ]
    if not events:
        events = [{
            **serialize_run(run),
            "event_id": cursor + 1,
        }]
    return StreamingResponse(
        iter([
            f"id: {event['event_id']}\nevent: import_status\ndata: "
            f"{json.dumps(event, ensure_ascii=False)}\n\n"
            for event in events
        ]),
        media_type="text/event-stream",
    )
