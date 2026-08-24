from __future__ import annotations

import hashlib
import logging
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from threading import Thread
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import object_session

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import (
    DiagnosticQuestion,
    Domain,
    IndexBuildJob,
    KnowledgeDocument,
    KnowledgeImportCandidate,
    KnowledgeImportRun,
    KnowledgeItem,
    KnowledgeRelation,
)
from app.services import candidate_index_job
from app.services.knowledge_extraction_service import replace_candidates
from app.services.knowledge_import_publish_service import (
    approve_candidates,
    publish_approved,
    smoke_domain_index,
    smoke_import_index,
)
from app.services.knowledge_import_validation_service import validate_import
from app.services.knowledge_parser_service import parse_document, replace_chunks
from app.services.knowledge_model_import_service import (
    enrich_unstructured_sections,
    generate_model_relations,
    generate_model_questions,
    repair_curriculum_relations,
    validate_model_candidates,
)
from app.services.knowledge_graph_quality_service import evaluate_graph_quality
from app.services.knowledge_import_batch_service import batch_progress


logger = logging.getLogger(__name__)
TERMINAL_STATUSES = {"ready", "ready_to_publish", "needs_attention", "failed", "deleted"}


def _input_version(document: KnowledgeDocument) -> str:
    payload = ":".join(
        (
            "knowledge-import-v2",
            document.sha256,
            str(settings.enable_knowledge_import_models),
            settings.primary_llm_model or "",
            settings.primary_review_model or "",
            settings.embedding_model or "",
        )
    )
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def create_import_run(db, document: KnowledgeDocument) -> KnowledgeImportRun:
    run = KnowledgeImportRun(
        public_id=f"kir_{uuid4().hex[:16]}",
        document_id=document.id,
        domain_code=document.domain_code,
        current_step="queued",
        status="queued",
        input_version=_input_version(document),
        artifact_manifest_json={},
        step_state_json={"next_event_id": 1, "events": []},
    )
    db.add(run)
    document.status = "queued"
    document.error_summary = None
    db.commit()
    db.refresh(run)
    return run


def latest_run(db, document_id: int) -> KnowledgeImportRun | None:
    return db.scalar(
        select(KnowledgeImportRun)
        .where(KnowledgeImportRun.document_id == document_id)
        .order_by(KnowledgeImportRun.id.desc())
    )


def resolve_run(db, identifier: str) -> tuple[KnowledgeImportRun, KnowledgeDocument]:
    run = db.scalar(select(KnowledgeImportRun).where(KnowledgeImportRun.public_id == identifier))
    if run is None:
        document = db.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.public_id == identifier)
        )
        if document is not None:
            run = latest_run(db, document.id)
    else:
        document = db.get(KnowledgeDocument, run.document_id)
    if run is None or document is None:
        raise ValueError("Knowledge import not found")
    return run, document


def _event(db, run: KnowledgeImportRun, status: str, **payload) -> None:
    state = dict(run.step_state_json or {})
    events = list(state.get("events") or [])
    event_id = int(state.get("next_event_id") or 1)
    events.append(
        {
            "event_id": event_id,
            "run_id": run.public_id,
            "step": run.current_step,
            "attempt": run.attempt_count,
            "status": status,
            "timestamp": datetime.now(UTC).isoformat(),
            **payload,
        }
    )
    state["events"] = events[-100:]
    state["next_event_id"] = event_id + 1
    run.step_state_json = state
    db.commit()


def _step(db, run: KnowledgeImportRun, document: KnowledgeDocument, name: str) -> None:
    run.current_step = name
    document.status = name
    run.lease_expires_at = datetime.now(UTC) + timedelta(
        seconds=settings.knowledge_import_batch_lease_seconds
    )
    _event(db, run, "running")


def _candidate_graph_data(
    candidates: list[KnowledgeImportCandidate], *, use_target_public_ids: bool
) -> tuple[dict[str, set[str]], list[dict[str, object]]]:
    id_map: dict[str, str] = {}
    item_tags: dict[str, set[str]] = {}
    for item in candidates:
        if item.candidate_type != "knowledge_item":
            continue
        payload = item.payload_json or {}
        target_id = (
            str(payload.get("target_public_id") or "")
            if use_target_public_ids
            else item.public_id
        )
        if not target_id:
            continue
        id_map[item.public_id] = target_id
        item_tags[target_id] = set(payload.get("tags") or [])
    edges: list[dict[str, object]] = []
    for item in candidates:
        if item.candidate_type != "knowledge_relation" or item.validation_errors_json:
            continue
        payload = item.payload_json or {}
        source = id_map.get(str(payload.get("source_candidate_id") or ""))
        target = id_map.get(str(payload.get("target_candidate_id") or ""))
        if not source or not target:
            continue
        edges.append({
            "source": source,
            "target": target,
            "relation_type": payload.get("relation_type"),
            "evidence_complete": bool(
                payload.get("source_quote")
                or payload.get("evidence_chunk_ids")
                or (item.source_locator_json or {}).get("chunk_id")
            ),
        })
    return item_tags, edges


def _projected_readiness(db, document: KnowledgeDocument) -> dict[str, object]:
    domain = db.scalar(select(Domain).where(Domain.domain_code == document.domain_code))
    candidates = list(db.scalars(select(KnowledgeImportCandidate).where(
        KnowledgeImportCandidate.document_id == document.id,
        KnowledgeImportCandidate.status == "approved",
    )))
    published_items = list(db.scalars(select(KnowledgeItem).where(
        KnowledgeItem.domain_code == document.domain_code,
        KnowledgeItem.status == "published",
    )))
    staged_items = list(db.scalars(select(KnowledgeItem).where(
        KnowledgeItem.domain_code == document.domain_code,
        KnowledgeItem.status == "staged",
    )))
    existing_question_count = int(db.scalar(
        select(func.count(DiagnosticQuestion.id)).where(
            DiagnosticQuestion.domain_code == document.domain_code
        )
    ) or 0)
    question_count = existing_question_count + sum(
        item.candidate_type == "diagnostic_question" for item in candidates
    )
    item_tags = {item.public_id: set(item.tags_json or []) for item in published_items}
    candidate_tags, graph_edges = _candidate_graph_data(
        candidates, use_target_public_ids=True
    )
    item_tags.update(candidate_tags)
    item_db_to_public = {item.id: item.public_id for item in published_items}
    for relation in db.scalars(
        select(KnowledgeRelation).where(
            (KnowledgeRelation.source_document_id.is_(None))
            | (KnowledgeRelation.source_document_id != document.id)
        )
    ):
        source = item_db_to_public.get(relation.source_item_id)
        target = item_db_to_public.get(relation.target_item_id)
        if source and target:
            graph_edges.append({
                "source": source,
                "target": target,
                "relation_type": relation.relation_type,
                "evidence_complete": bool(
                    relation.evidence_json or relation.source_document_id
                ),
            })
    configured_directions = list(
        (domain.config_json if domain else {}).get("learning_directions") or []
    )
    directions = _merge_learning_direction_mappings(
        configured_directions, _suggest_learning_directions(candidates)
    )
    graph_quality = evaluate_graph_quality(
        item_tags=item_tags, edges=graph_edges, directions=directions
    )

    knowledge_candidate_ids = {
        item.public_id for item in candidates if item.candidate_type == "knowledge_item"
    }
    covered_knowledge_ids = {
        str((item.payload_json or {}).get("knowledge_candidate_id"))
        for item in candidates
        if item.candidate_type == "diagnostic_question"
        and (item.payload_json or {}).get("knowledge_candidate_id") in knowledge_candidate_ids
    }
    imported_knowledge_count = len(knowledge_candidate_ids)
    question_coverage = (
        len(covered_knowledge_ids) / imported_knowledge_count if imported_knowledge_count else 0.0
    )
    source_items = [
        item for item in candidates
        if item.candidate_type in {"knowledge_item", "knowledge_relation", "diagnostic_question"}
    ]
    source_traceability = (
        sum(bool((item.source_locator_json or {}).get("chunk_id")) for item in source_items)
        / len(source_items)
        if source_items else 0.0
    )

    minimum_items, minimum_questions = ((50, 60) if document.domain_code == "ai_app_dev" else (10, 10))
    checks = {
        "knowledge_items": len({
            item.public_id for item in [*published_items, *staged_items]
        }),
        "diagnostic_questions": question_count,
        "path_coverage": graph_quality["path_participation_ratio"],
        "question_knowledge_coverage": round(question_coverage, 4),
        "source_traceability": round(source_traceability, 4),
        "proposed_learning_directions": directions,
        **graph_quality,
    }
    if question_coverage < 1.0:
        checks["blocking_issues"].append({
            "code": "QUESTION_COVERAGE_INCOMPLETE",
            "message": "存在没有有效诊断题的导入知识点",
            "actual": round(question_coverage, 4),
        })
    if source_traceability < 1.0:
        checks["blocking_issues"].append({
            "code": "SOURCE_TRACEABILITY_INCOMPLETE",
            "message": "存在无法定位来源的候选资产",
            "actual": round(source_traceability, 4),
        })
    checks["passed"] = bool(
        checks["knowledge_items"] >= minimum_items
        and question_count >= minimum_questions
        and not checks["blocking_issues"]
    )
    checks["quality_gate_passed"] = checks["passed"]
    return checks


def _suggest_learning_directions(
    candidates: list[KnowledgeImportCandidate],
) -> list[dict[str, object]]:
    """Build deterministic direction proposals without requiring a model call."""
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for candidate in candidates:
        if candidate.candidate_type != "knowledge_item":
            continue
        payload = candidate.payload_json or {}
        category = str(payload.get("category") or "综合学习").strip() or "综合学习"
        grouped[category].append(payload)
    total = sum(len(values) for values in grouped.values())
    max_size = max(4, (total + 3) // 4)
    topic_groups: list[tuple[list[str], list[dict[str, object]]]] = []
    for category, values in sorted(grouped.items()):
        parts = max(1, (len(values) + max_size - 1) // max_size)
        buckets: list[list[dict[str, object]]] = [[] for _ in range(parts)]
        for item in sorted(values, key=lambda value: str(value.get("external_id") or value.get("name"))):
            tags = {str(tag).casefold() for tag in item.get("tags") or []}
            target = max(
                range(parts),
                key=lambda index: (
                    len(tags & {
                        str(tag).casefold()
                        for existing in buckets[index]
                        for tag in existing.get("tags") or []
                    }),
                    -len(buckets[index]),
                    -index,
                ),
            )
            buckets[target].append(item)
        topic_groups.extend(
            ([category if parts == 1 else f"{category}{index + 1}"], bucket)
            for index, bucket in enumerate(buckets) if bucket
        )

    def group_tags(group: tuple[list[str], list[dict[str, object]]]) -> set[str]:
        return {
            str(tag).casefold()
            for item in group[1]
            for tag in item.get("tags") or []
        }

    while len(topic_groups) > 6:
        best: tuple[float, int, int] | None = None
        for left in range(len(topic_groups)):
            for right in range(left + 1, len(topic_groups)):
                if len(topic_groups[left][1]) + len(topic_groups[right][1]) > max_size:
                    continue
                left_tags, right_tags = group_tags(topic_groups[left]), group_tags(topic_groups[right])
                union = left_tags | right_tags
                similarity = len(left_tags & right_tags) / len(union) if union else 0.0
                candidate = (similarity, left, right)
                if best is None or candidate > best:
                    best = candidate
        if best is None:
            smallest = sorted(range(len(topic_groups)), key=lambda index: len(topic_groups[index][1]))[:2]
            left, right = sorted(smallest)
        else:
            _, left, right = best
        names = [*topic_groups[left][0], *topic_groups[right][0]]
        items = [*topic_groups[left][1], *topic_groups[right][1]]
        topic_groups[left] = (names, items)
        topic_groups.pop(right)
    ordered = [
        ((names[0] if len(names) == 1 else f"{names[0]}等主题"), items)
        for names, items in topic_groups
    ]
    proposals: list[dict[str, object]] = []
    for category, items in ordered:
        tag_counts = Counter(
            str(tag).strip().lower()
            for item in items
            for tag in (item.get("tags") or [])
            if str(tag).strip()
        )
        tags = [tag for tag, _ in tag_counts.most_common()]
        if not tags:
            continue
        stable = hashlib.sha256(category.encode("utf-8")).hexdigest()[:10]
        proposals.append({
            "value": f"direction_{stable}",
            "label": category,
            "description": f"围绕{category}相关知识形成的学习方向",
            "match_tags": tags,
        })
    return proposals


def _merge_learning_direction_mappings(
    configured: list[dict[str, object]],
    suggested: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Preserve configured direction identity while supplementing tag mappings."""
    if not configured:
        return [dict(direction) for direction in suggested]
    merged = [
        {
            **direction,
            "match_tags": list(dict.fromkeys(
                str(tag) for tag in direction.get("match_tags") or []
            )),
        }
        for direction in configured
    ]
    for proposal in suggested:
        proposal_tags = {
            str(tag) for tag in proposal.get("match_tags") or [] if str(tag)
        }
        if not proposal_tags:
            continue
        overlaps = [
            len(proposal_tags & {str(tag) for tag in item.get("match_tags") or []})
            for item in merged
        ]
        best_overlap = max(overlaps, default=0)
        target_index = (
            overlaps.index(best_overlap)
            if best_overlap
            else min(
                range(len(merged)),
                key=lambda index: (len(merged[index].get("match_tags") or []), index),
            )
        )
        current = list(merged[target_index].get("match_tags") or [])
        merged[target_index]["match_tags"] = list(
            dict.fromkeys([*current, *sorted(proposal_tags)])
        )
    return merged


def _candidate_graph_quality(
    candidates: list[KnowledgeImportCandidate],
    directions: list[dict[str, object]],
) -> dict[str, object]:
    item_tags, edges = _candidate_graph_data(
        candidates, use_target_public_ids=False
    )
    return evaluate_graph_quality(item_tags=item_tags, edges=edges, directions=directions)


def _remove_cycle_forming_relations(
    db, candidates: list[KnowledgeImportCandidate]
) -> list[KnowledgeImportCandidate]:
    """Keep the highest-confidence acyclic subset of directional candidates."""
    graph: dict[str, set[str]] = defaultdict(set)
    kept: list[KnowledgeImportCandidate] = []

    def reachable(start: str, target: str) -> bool:
        pending = [start]
        seen: set[str] = set()
        while pending:
            node = pending.pop()
            if node == target:
                return True
            if node in seen:
                continue
            seen.add(node)
            pending.extend(graph[node])
        return False

    relations = sorted(
        (item for item in candidates if item.candidate_type == "knowledge_relation"),
        key=lambda item: (-float(item.confidence or 0), item.public_id),
    )
    rejected: set[str] = set()
    for item in relations:
        payload = item.payload_json or {}
        relation_type = str(payload.get("relation_type") or "")
        if relation_type == "related_to":
            continue
        source = str(payload.get("source_candidate_id") or "")
        target = str(payload.get("target_candidate_id") or "")
        if relation_type == "depends_on":
            source, target = target, source
        if source == target or reachable(target, source):
            rejected.add(item.public_id)
            db.delete(item)
            continue
        graph[source].add(target)
    for item in candidates:
        if item.public_id not in rejected:
            kept.append(item)
    return kept


def run_import(run_id: str) -> None:
    owner = f"worker_{uuid4().hex[:10]}"
    with SessionLocal() as db:
        run = db.scalar(
            select(KnowledgeImportRun).where(KnowledgeImportRun.public_id == run_id).with_for_update()
        )
        if run is None or run.status in TERMINAL_STATUSES:
            return
        now = datetime.now(UTC)
        if run.lease_owner and run.lease_expires_at and run.lease_expires_at > now:
            return
        run.lease_owner = owner
        run.lease_expires_at = now + timedelta(
            seconds=settings.knowledge_import_batch_lease_seconds
        )
        run.status = "running"
        run.attempt_count += 1
        run.error_code = None
        run.error_summary = None
        document = db.get(KnowledgeDocument, run.document_id)
        if document is not None:
            document.error_summary = None
        run.started_at = run.started_at or now
        db.commit()
        if document is None:
            return
        try:
            _step(db, run, document, "parsing")
            sections = parse_document(document)
            if not all(section.get("structured") for section in sections):
                if not settings.enable_knowledge_import_models:
                    raise ValueError("通用文档模型抽取未启用，请上传结构化 Markdown 或启用模型增强")
                sections = enrich_unstructured_sections(sections)
            replace_chunks(db, document, sections)
            db.commit()

            _step(db, run, document, "extracting")
            candidates = replace_candidates(db, document, sections)
            if settings.enable_knowledge_import_models:
                _step(db, run, document, "graph_generation")
                relation_candidates = generate_model_relations(
                    db, document, candidates, run=run
                )
                candidates.extend(relation_candidates)
                factual_relations = [
                    item for item in relation_candidates
                    if (item.payload_json or {}).get("evidence_kind") == "text_quote"
                ]
                accepted = validate_model_candidates(
                    factual_relations, run=run, step="graph_review"
                )
                for candidate in factual_relations:
                    if candidate.public_id not in accepted:
                        db.delete(candidate)
                        candidates.remove(candidate)

                _step(db, run, document, "question_generation")
                generated_questions = generate_model_questions(
                    db, document, candidates, run
                )
                candidates = [
                    item for item in candidates
                    if item.candidate_type != "diagnostic_question"
                ]
                candidates.extend(generated_questions)
                directions = _suggest_learning_directions(candidates)
                candidates = _remove_cycle_forming_relations(db, candidates)
                quality = _candidate_graph_quality(candidates, directions)
                initial_quality = quality
                repair_rounds = 0
                repair_quality: list[dict[str, object]] = []
                while not quality["quality_gate_passed"] and repair_rounds < 2:
                    repair_rounds += 1
                    _step(db, run, document, f"graph_repair_{repair_rounds}")
                    focus_ids = {
                        str(item_id)
                        for item_id in [
                            *(quality.get("deficient_node_ids") or []),
                            *(quality.get("isolated_node_ids") or []),
                            *(quality.get("unmapped_node_ids") or []),
                        ]
                    }
                    repaired = repair_curriculum_relations(
                        db,
                        document,
                        candidates,
                        directions,
                        focus_ids,
                        repair_rounds,
                    )
                    if not repaired:
                        break
                    candidates.extend(repaired)
                    candidates = _remove_cycle_forming_relations(db, candidates)
                    quality = _candidate_graph_quality(candidates, directions)
                    repair_quality.append(quality)
                run.artifact_manifest_json = {
                    **(run.artifact_manifest_json or {}),
                    "repair_rounds": repair_rounds,
                    "initial_graph_quality": initial_quality,
                    "repair_graph_quality": repair_quality,
                    "final_graph_quality": quality,
                }
            db.commit()
            _event(db, run, "completed", counts={"candidates": len(candidates)})

            _step(db, run, document, "validating")
            validation = validate_import(db, document.id)
            if validation["invalid"]:
                raise ValueError(f"{validation['invalid']} 个候选未通过校验")

            _step(db, run, document, "staging")
            approve_candidates(db, document)
            staged = publish_approved(db, document)
            run.artifact_manifest_json = {**(run.artifact_manifest_json or {}), "staged": staged}
            db.commit()

            _step(db, run, document, "indexing")
            job = candidate_index_job.try_start(
                db, document.domain_code, source_document_id=document.id
            )
            if job is None:
                raise RuntimeError("候选索引已有运行任务")
            candidate_index_job.run_import_build(job.id, document.domain_code, document.id)
            # The job uses its own session. End MySQL's repeatable-read snapshot
            # before loading the status committed by that worker session.
            db.commit()
            db.expire_all()
            job = db.get(IndexBuildJob, job.id)
            if job is None or job.status != candidate_index_job.STATUS_SUCCESS:
                raise RuntimeError(job.message if job else "候选索引构建失败")
            result = dict(job.result_json or {})
            manifest = result.get("candidate_manifest")
            if not isinstance(manifest, dict):
                raise RuntimeError("候选索引缺少 manifest")

            _step(db, run, document, "smoke_testing")
            retrieval = smoke_import_index(db, document, manifest_payload=manifest)
            isolation = smoke_domain_index(
                db, document.domain_code, manifest_payload=manifest,
                staged_document_id=document.id,
            )
            result["smoke_test"] = {
                "passed": True,
                "index_version": manifest["index_version"],
                "active_collection": manifest["active_collection"],
                "checks": {"import": retrieval["checks"], "domain": isolation["checks"]},
            }
            job.result_json = result
            readiness = _projected_readiness(db, document)
            run.artifact_manifest_json = {
                **(run.artifact_manifest_json or {}),
                "candidate_manifest": manifest,
                "smoke_test": result["smoke_test"],
                "projected_readiness": readiness,
                "quality_baseline_version": "knowledge-import-gold-v1",
            }
            if not readiness["passed"]:
                run.status = "needs_attention"
                run.current_step = "needs_attention"
                document.status = "needs_attention"
                run.error_code = "PROJECTED_READINESS_FAILED"
                run.error_summary = "预计领域 readiness 未通过"
                document.error_summary = run.error_summary
            else:
                run.status = "ready_to_publish"
                run.current_step = "ready_to_publish"
                document.status = "ready_to_publish"
            run.lease_owner = None
            run.lease_expires_at = None
            run.finished_at = datetime.now(UTC)
            db.commit()
            _event(db, run, run.status, counts=readiness)
        except Exception as exc:
            db.rollback()
            run = db.scalar(select(KnowledgeImportRun).where(KnowledgeImportRun.public_id == run_id))
            document = db.get(KnowledgeDocument, run.document_id) if run else None
            if run:
                run.status = "needs_attention" if isinstance(exc, ValueError) else "failed"
                run.error_code = type(exc).__name__
                run.error_summary = str(exc)[:1000]
                run.lease_owner = None
                run.lease_expires_at = None
                run.finished_at = datetime.now(UTC)
                if document:
                    document.status = run.status
                    document.error_summary = run.error_summary
                db.commit()
                _event(db, run, run.status, error_summary=run.error_summary)
            logger.exception("knowledge import failed run_id=%s", run_id)


def schedule_import(run_id: str) -> None:
    Thread(target=run_import, args=(run_id,), name=f"knowledge-import-{run_id}", daemon=True).start()


def recover_interrupted_imports() -> list[str]:
    now = datetime.now(UTC)
    with SessionLocal() as db:
        runs = list(db.scalars(select(KnowledgeImportRun).where(
            KnowledgeImportRun.status == "running"
        )))
        recovered = []
        for run in runs:
            if run.lease_expires_at is None or run.lease_expires_at <= now:
                run.status = "interrupted"
                run.lease_owner = None
                run.lease_expires_at = None
                recovered.append(run.public_id)
        db.commit()
    for run_id in recovered:
        schedule_import(run_id)
    return recovered


def serialize_run(run: KnowledgeImportRun) -> dict[str, object]:
    events = list((run.step_state_json or {}).get("events") or [])
    db = object_session(run)
    progress = batch_progress(db, run.id) if db is not None else {}
    elapsed_ms = 0
    if run.started_at:
        end = run.finished_at or datetime.now(UTC)
        started = run.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        elapsed_ms = max(0, int((end - started).total_seconds() * 1000))
    return {
        "import_id": run.public_id,
        "run_id": run.public_id,
        "document_id": run.document_id,
        "domain_code": run.domain_code,
        "status": run.status,
        "current_step": run.current_step,
        "attempt": run.attempt_count,
        "input_version": run.input_version,
        "error_code": run.error_code,
        "error_summary": run.error_summary,
        "artifacts": run.artifact_manifest_json or {},
        "events": events,
        "elapsed_ms": elapsed_ms,
        **progress,
    }
