from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    DiagnosticQuestion,
    Domain,
    IndexBuildJob,
    KnowledgeDocument,
    KnowledgeChunk,
    KnowledgeImportCandidate,
    KnowledgeImportRun,
    KnowledgeItem,
    KnowledgeItemSource,
    KnowledgeRelation,
)
from app.agents.domain_evidence_policy import classify_evidence_capabilities
from app.rag.candidate_index import CandidateIndexBuilder
from app.rag.candidate_index import knowledge_item_source_content_hash
from app.rag.candidate_manifest import (
    CandidateIndexManifest,
    CandidateManifestStore,
)
from app.rag.database_manifest_store import DatabaseManifestStore
from app.rag.embedding_provider import OpenAICompatibleEmbeddingProvider
from app.rag.vector_store import VectorStore
from app.services.domain_api_service import default_ability_weights
from app.services.question_source_binding_service import (
    bind_domain_question_sources,
    candidate_chunks_for_item,
    candidate_source_locator,
)
from app.services.question_certification_service import (
    QUESTION_CERTIFICATION_RULE_VERSION,
    mark_question_certifications_stale,
    normalize_evidence_text,
)


class KnowledgeImportPublishError(ValueError):
    pass


def activate_import_candidate(
    db: Session,
    document: KnowledgeDocument,
    job: IndexBuildJob,
    *,
    builder: CandidateIndexBuilder | None = None,
) -> dict[str, object]:
    """Publish staged rows and switch the candidate manifest as one coordinated unit."""
    domain = db.scalar(
        select(Domain)
        .where(Domain.domain_code == document.domain_code)
        .with_for_update()
    )
    if job.source_document_id != document.id or job.status != "success":
        raise KnowledgeImportPublishError("导入没有对应的成功候选构建任务")
    result = dict(job.result_json or {})
    manifest_payload = result.get("candidate_manifest")
    smoke = dict(result.get("smoke_test") or {})
    if not isinstance(manifest_payload, dict):
        raise KnowledgeImportPublishError("候选构建缺少 manifest")
    if not (
        smoke.get("passed")
        and smoke.get("index_version") == manifest_payload.get("index_version")
        and smoke.get("active_collection") == manifest_payload.get("active_collection")
    ):
        raise KnowledgeImportPublishError("候选索引尚未通过当前版本的检索冒烟")

    items = list(
        db.scalars(
            select(KnowledgeItem).where(
                KnowledgeItem.source_document_id == document.id,
                KnowledgeItem.status == "staged",
            )
        )
    )
    if not items:
        has_updates = db.scalar(
            select(KnowledgeImportCandidate.id).where(
                KnowledgeImportCandidate.document_id == document.id,
                KnowledgeImportCandidate.candidate_type == "knowledge_item",
                KnowledgeImportCandidate.status == "approved",
            )
        )
        if has_updates is None:
            raise KnowledgeImportPublishError("导入没有待发布知识")
    candidates = list(
        db.scalars(
            select(KnowledgeImportCandidate).where(
                KnowledgeImportCandidate.document_id == document.id,
                KnowledgeImportCandidate.status == "approved",
            )
        )
    )
    knowledge_map: dict[str, KnowledgeItem] = {}
    for candidate in candidates:
        if candidate.candidate_type != "knowledge_item":
            continue
        payload = candidate.payload_json or {}
        target = db.scalar(
            select(KnowledgeItem).where(
                KnowledgeItem.public_id == payload.get("target_public_id")
            )
        )
        if target is None:
            continue
        knowledge_map[candidate.public_id] = target
        if payload.get("action") in {"update", "merge"}:
            target.name = str(payload["name"])[:255]
            target.category = str(payload.get("category") or "未分类")[:64]
            target.difficulty = int(payload["difficulty"])
            target.tags_json = payload.get("tags") or []
            target.evidence_capabilities_json = classify_evidence_capabilities(
                str(payload.get("content") or "")
            )
            target.content_md = payload["content"]
            target.source_title = str(payload.get("source_title") or document.source_title)[:255]
            target.source_url = payload.get("source_url")
            target.license_note = str(payload.get("license_note") or document.license_note)[:255]
            target.ability_weights_json = payload.get("ability_weights") or default_ability_weights()
            target.needs_reembedding = False
    relation_candidates = [
        item for item in candidates if item.candidate_type == "knowledge_relation"
    ]
    question_candidates = [
        item for item in candidates if item.candidate_type == "diagnostic_question"
    ]
    mapped_item_ids = {item.id for item in knowledge_map.values()}
    mark_question_certifications_stale(
        db,
        domain_code=document.domain_code,
        knowledge_ids={item.public_id for item in knowledge_map.values()},
    )
    if relation_candidates and mapped_item_ids:
        db.execute(
            delete(KnowledgeRelation).where(
                KnowledgeRelation.source_document_id == document.id,
                KnowledgeRelation.source_item_id.in_(mapped_item_ids),
                KnowledgeRelation.target_item_id.in_(mapped_item_ids),
            )
        )
    if question_candidates and mapped_item_ids:
        existing_questions = list(db.scalars(
            select(DiagnosticQuestion).where(
                DiagnosticQuestion.knowledge_item_id.in_(mapped_item_ids)
            )
        ))
        item_by_id = {item.id: item for item in knowledge_map.values()}
        for question in existing_questions:
            answer_key = dict(question.answer_key_json or {})
            item = item_by_id[question.knowledge_item_id]
            is_same_import = answer_key.get("import_document_id") == document.public_id
            is_legacy_import = answer_key.get("source_ref_ids") == [item.public_id]
            if (is_same_import or is_legacy_import) and question.status == "active":
                question.status = "disabled"
                question.disabled_at = datetime.now(UTC).replace(tzinfo=None)
                question.disabled_reason = "superseded_by_import"
        db.flush()
    for candidate in candidates:
        payload = candidate.payload_json or {}
        if candidate.candidate_type == "knowledge_relation":
            source = knowledge_map.get(payload.get("source_candidate_id"))
            target = knowledge_map.get(payload.get("target_candidate_id"))
            if source and target and db.scalar(
                select(KnowledgeRelation.id).where(
                    KnowledgeRelation.source_item_id == source.id,
                    KnowledgeRelation.target_item_id == target.id,
                    KnowledgeRelation.relation_type == payload.get("relation_type", "related_to"),
                )
            ) is None:
                db.add(KnowledgeRelation(
                    source_item_id=source.id,
                    target_item_id=target.id,
                    relation_type=payload.get("relation_type", "related_to"),
                    confidence=candidate.confidence,
                    evidence_json={"chunk_ids": payload.get("evidence_chunk_ids") or [], "reason": payload.get("reason")},
                    generation_method=payload.get("generation_method", "hybrid"),
                    source_document_id=document.id,
                ))
        elif candidate.candidate_type == "diagnostic_question":
            item = knowledge_map.get(payload.get("knowledge_candidate_id"))
            if item is None:
                continue
            if (
                payload.get("certification_status") != "certified"
                or payload.get("certification_rule_version")
                != QUESTION_CERTIFICATION_RULE_VERSION
            ):
                raise KnowledgeImportPublishError(
                    f"题目尚未通过正式认证：{candidate.public_id}"
                )
            question_type = payload.get("question_type", "short_answer")
            options = payload.get("options") or []
            answer = payload["answer"]
            source_chunks = [dict(value) for value in payload.get("source_chunks") or []]
            related_candidate_ids = [
                str(value)
                for value in payload.get("related_knowledge_candidate_ids") or []
            ]
            source_items = [
                item,
                *[
                    knowledge_map[value]
                    for value in related_candidate_ids
                    if value in knowledge_map
                ],
            ]
            source_item_by_public_id = {value.public_id: value for value in source_items}
            exact_sources: dict[str, dict[str, object]] = {}
            for source in source_chunks:
                source_item = source_item_by_public_id.get(
                    str(source.get("knowledge_id") or "")
                )
                if source_item is None:
                    raise KnowledgeImportPublishError(
                        f"题目引用了未声明的关联知识点：{candidate.public_id}"
                    )
                chunks = {
                    value.chunk_id: value for value in candidate_chunks_for_item(source_item)
                }
                source_ref_id = str(source.get("chunk_id") or "")
                chunk = chunks.get(source_ref_id)
                if (
                    chunk is None
                    or source.get("source_locator")
                    != candidate_source_locator(source_item, chunk)
                    or source.get("source_content_hash")
                    != knowledge_item_source_content_hash(source_item)
                ):
                    raise KnowledgeImportPublishError(
                        f"题目精确来源已变化：{candidate.public_id}"
                    )
                exact_sources[source_ref_id] = {
                    "source_ref_id": source_ref_id,
                    "source_locator": source.get("source_locator"),
                    "knowledge_id": source_item.public_id,
                    "source_content_hash": source.get("source_content_hash"),
                    "content": chunk.content,
                }
            evidence_quotes = [
                dict(value)
                for value in payload.get("evidence_quotes") or []
                if isinstance(value, dict)
            ]
            for evidence in evidence_quotes:
                source = exact_sources.get(str(evidence.get("source_ref_id") or ""))
                if (
                    source is None
                    or normalize_evidence_text(evidence.get("quote"))
                    not in normalize_evidence_text(source.get("content"))
                ):
                    raise KnowledgeImportPublishError(
                        f"题目精确引文无法定位：{candidate.public_id}"
                    )
            source_ref_ids = list(exact_sources)
            answer_key = {
                ("correct_option" if question_type == "single_choice" else "answer"): answer,
                "explanation": payload.get("explanation", ""),
                "question_slot": payload.get("question_slot"),
                "quiz_level": payload.get("quiz_level"),
                "question_bank_purpose": "diagnosis_mastery_and_resource_quiz",
                "source_ref_ids": source_ref_ids,
                "source_locators": {
                    source_ref_id: exact_sources[source_ref_id]["source_locator"]
                    for source_ref_id in source_ref_ids
                },
                "source_content_hashes": {
                    source_ref_id: exact_sources[source_ref_id]["source_content_hash"]
                    for source_ref_id in source_ref_ids
                },
                "evidence_quotes": evidence_quotes,
                "chunker_version": payload.get("chunker_version"),
                "source_quote": payload.get("source_quote", ""),
                "import_document_id": document.public_id,
                "import_candidate_id": candidate.public_id,
            }
            if question_type != "single_choice":
                answer_key["rubric"] = payload.get("rubric") or []
            db.add(DiagnosticQuestion(
                public_id=f"dq_{uuid4().hex[:12]}", domain_code=document.domain_code,
                knowledge_item_id=item.id,
                related_knowledge_ids_json=[
                    knowledge_map[candidate_id].public_id
                    for candidate_id in payload.get("related_knowledge_candidate_ids") or []
                    if candidate_id in knowledge_map and candidate_id != payload.get("knowledge_candidate_id")
                ],
                question_type=question_type, stem=payload["stem"],
                options_json=options, answer_key_json=answer_key,
                difficulty=int(payload.get("difficulty", 2)),
                status="active",
                certification_status="certified",
                certification_rule_version=QUESTION_CERTIFICATION_RULE_VERSION,
                certification_report_json=payload.get("certification_report") or {},
                source_content_hash=str(payload.get("source_content_hash") or ""),
                certified_at=(
                    datetime.fromisoformat(str(payload["certified_at"]))
                    if payload.get("certified_at")
                    else datetime.now(UTC).replace(tzinfo=None)
                ),
            ))
    for item in items:
        item.status = "published"
        item.needs_reembedding = False
    for source in db.scalars(
        select(KnowledgeItemSource).where(
            KnowledgeItemSource.document_id == document.id,
            KnowledgeItemSource.status == "staged",
        )
    ):
        source.status = "published"
    for candidate in db.scalars(
        select(KnowledgeImportCandidate).where(
            KnowledgeImportCandidate.document_id == document.id,
            KnowledgeImportCandidate.status == "approved",
        )
    ):
        candidate.status = "published"
    document.status = "ready"
    document.error_summary = None
    document.embedding_model = str(result.get("embedding_model") or "") or None
    document.indexed_at = job.finished_at
    run = db.scalar(
        select(KnowledgeImportRun).where(KnowledgeImportRun.document_id == document.id)
        .order_by(KnowledgeImportRun.id.desc())
    )
    if run is not None:
        proposed_directions = list(
            ((run.artifact_manifest_json or {}).get("projected_readiness") or {}).get(
                "proposed_learning_directions"
            )
            or []
        )
        if domain is not None and proposed_directions:
            config = dict(domain.config_json or {})
            configured = list(config.get("learning_directions") or [])
            if configured:
                proposed_by_value = {
                    str(item.get("value")): item for item in proposed_directions
                }
                for item in configured:
                    proposal = proposed_by_value.get(str(item.get("value")))
                    if proposal is not None:
                        item["match_tags"] = list(proposal.get("match_tags") or [])
                config["learning_directions"] = configured
            else:
                config["learning_directions"] = proposed_directions
            domain.config_json = config
        run.status = "ready"
        run.current_step = "ready"
        run.finished_at = datetime.now(UTC)

    active_builder = builder or CandidateIndexBuilder(
        db=db,
        chroma_client=VectorStore().client,
        embedding_provider=OpenAICompatibleEmbeddingProvider(),
    )
    previous = None
    manifest_switched = False
    try:
        previous = active_builder.activate_candidate(manifest_payload)
        manifest_switched = True
        db.commit()
    except Exception as exc:
        db.rollback()
        if manifest_switched:
            active_builder.restore_manifest(document.domain_code, previous)
        if isinstance(exc, KnowledgeImportPublishError):
            raise
        raise KnowledgeImportPublishError(f"候选索引发布失败：{type(exc).__name__}") from exc

    try:
        deleted = active_builder.cleanup_after_activation(manifest_payload)
    except Exception:
        deleted = 0
    return {
        "import_id": document.public_id,
        "status": "ready",
        "index_version": manifest_payload["index_version"],
        "active_collection": manifest_payload["active_collection"],
        "old_collections_deleted": deleted,
    }


def approve_candidates(
    db: Session, document: KnowledgeDocument, candidate_ids: list[str] | None = None
) -> int:
    candidates = list(
        db.scalars(
            select(KnowledgeImportCandidate).where(
                KnowledgeImportCandidate.document_id == document.id
            )
        )
    )
    selected = set(candidate_ids or [item.public_id for item in candidates])
    by_id = {item.public_id: item for item in candidates}
    missing_dependencies: set[str] = set()
    for item in candidates:
        if item.public_id not in selected:
            continue
        payload = item.payload_json or {}
        references = []
        if item.candidate_type == "knowledge_relation":
            references = [
                payload.get("source_candidate_id"),
                payload.get("target_candidate_id"),
            ]
        elif item.candidate_type == "diagnostic_question":
            references = [payload.get("knowledge_candidate_id")]
        missing_dependencies.update(
            reference
            for reference in references
            if reference in by_id and reference not in selected
        )
    if missing_dependencies:
        raise KnowledgeImportPublishError(
            "候选批准缺少引用依赖：" + ", ".join(sorted(missing_dependencies)[:5])
        )
    blocked = [
        item.public_id
        for item in candidates
        if item.public_id in selected and item.validation_errors_json
    ]
    if blocked:
        raise KnowledgeImportPublishError(f"存在未通过校验的候选：{', '.join(blocked[:5])}")
    count = 0
    for item in candidates:
        if item.public_id in selected:
            item.status = "approved"
            count += 1
    db.flush()
    return count


def publish_approved(db: Session, document: KnowledgeDocument) -> dict[str, int]:
    candidates = list(
        db.scalars(
            select(KnowledgeImportCandidate).where(
                KnowledgeImportCandidate.document_id == document.id,
                KnowledgeImportCandidate.status == "approved",
            )
        )
    )
    if not candidates:
        raise KnowledgeImportPublishError("没有已批准候选")
    knowledge_map: dict[str, KnowledgeItem] = {}
    import_run = db.scalar(
        select(KnowledgeImportRun)
        .where(KnowledgeImportRun.document_id == document.id)
        .order_by(KnowledgeImportRun.id.desc())
    )
    for candidate in candidates:
        if candidate.candidate_type != "knowledge_item":
            continue
        payload = candidate.payload_json
        item = db.scalar(
            select(KnowledgeItem).where(
                KnowledgeItem.public_id == payload.get("target_public_id")
            )
        )
        if item is None and payload.get("action") == "create":
            item = KnowledgeItem(
            public_id=str(payload["target_public_id"]),
            domain_code=document.domain_code,
            external_id=payload.get("external_id"),
            name=str(payload["name"])[:255],
            category=str(payload.get("category") or "未分类")[:64],
            difficulty=int(payload["difficulty"]),
            tags_json=payload.get("tags") or [],
            evidence_capabilities_json=classify_evidence_capabilities(
                str(payload.get("content") or "")
            ),
            content_md=payload["content"],
            source_title=str(payload.get("source_title") or document.source_title)[:255],
            source_url=payload.get("source_url"),
            license_note=str(payload.get("license_note") or document.license_note)[:255],
            needs_reembedding=True,
            source_document_id=document.id,
            ability_weights_json=payload.get("ability_weights") or default_ability_weights(),
            source_locator_json=candidate.source_locator_json or {},
            status="staged",
            )
            db.add(item)
            db.flush()
        if item is None:
            continue
        knowledge_map[candidate.public_id] = item
        for chunk_public_id in payload.get("source_chunk_ids") or []:
            chunk = db.scalar(select(KnowledgeChunk).where(KnowledgeChunk.public_id == chunk_public_id))
            if chunk is None:
                continue
            source = db.scalar(select(KnowledgeItemSource).where(
                KnowledgeItemSource.knowledge_item_id == item.id,
                KnowledgeItemSource.chunk_id == chunk.id,
            ))
            if source is None:
                db.add(KnowledgeItemSource(
                    knowledge_item_id=item.id, chunk_id=chunk.id, document_id=document.id,
                    import_run_id=import_run.id if import_run else None,
                    source_quote_hash=hashlib.sha256(str(payload.get("source_quote") or "").encode()).hexdigest(),
                    is_primary=not bool(db.scalar(select(KnowledgeItemSource.id).where(KnowledgeItemSource.knowledge_item_id == item.id))),
                    status="staged",
                ))
    for candidate in candidates:
        candidate.status = "approved"
    document.status = "index_pending"
    document.knowledge_item_count = len(knowledge_map)
    db.commit()
    return {
        "knowledge_items": len(knowledge_map),
        "relations": sum(item.candidate_type == "knowledge_relation" for item in candidates),
        "questions": sum(item.candidate_type == "diagnostic_question" for item in candidates),
    }


def ensure_import_source_locators(db: Session, document: KnowledgeDocument) -> int:
    """Bind imported questions to their deterministic final Candidate chunks."""
    items = list(
        db.scalars(select(KnowledgeItem).where(KnowledgeItem.source_document_id == document.id))
    )
    if not items:
        return 0
    return bind_domain_question_sources(
        db,
        domain_code=document.domain_code,
        items=items,
    )


def _smoke_context(
    db: Session,
    domain_code: str,
    *,
    client: object | None,
    manifest_store: CandidateManifestStore | DatabaseManifestStore | None,
    manifest_payload: dict[str, object] | None,
) -> tuple[object, CandidateIndexManifest]:
    vector_client = client or VectorStore().client
    store = manifest_store or DatabaseManifestStore(db)
    manifest = (
        CandidateIndexManifest.from_dict(manifest_payload)
        if manifest_payload is not None
        else store.load(
            domain_code,
            collection_exists=lambda name: _collection_exists(vector_client, name),
        )
    )
    if manifest is None:
        raise KnowledgeImportPublishError("Candidate 活动 manifest 不存在")
    return vector_client.get_collection(name=manifest.active_collection), manifest


def _smoke_matches(
    collection: object,
    manifest: CandidateIndexManifest,
    query_specs: list[tuple[str, str]],
    provider: OpenAICompatibleEmbeddingProvider | None,
) -> dict[str, tuple[list[str], list[dict]]]:
    vectors = (provider or OpenAICompatibleEmbeddingProvider()).embed_texts(
        [query for _, query in query_specs]
    )
    matches: dict[str, tuple[list[str], list[dict]]] = {}
    for (query_type, _), vector in zip(query_specs, vectors, strict=True):
        result = collection.query(
            query_embeddings=[vector],
            n_results=min(5, manifest.indexed_chunk_count),
            include=["metadatas", "distances"],
        )
        metadatas = list((result.get("metadatas") or [[]])[0])
        matches[query_type] = (
            [str(metadata.get("knowledge_id", "")) for metadata in metadatas],
            metadatas,
        )
    return matches


def smoke_import_index(
    db: Session,
    document: KnowledgeDocument,
    *,
    provider: OpenAICompatibleEmbeddingProvider | None = None,
    client: object | None = None,
    manifest_store: CandidateManifestStore | DatabaseManifestStore | None = None,
    manifest_payload: dict[str, object] | None = None,
) -> dict[str, object]:
    items = list(
        db.scalars(
            select(KnowledgeItem)
            .where(KnowledgeItem.source_document_id == document.id)
            .order_by(KnowledgeItem.id)
        )
    )
    if not items:
        raise KnowledgeImportPublishError("导入没有可用于检索冒烟的知识点")
    collection, manifest = _smoke_context(
        db,
        document.domain_code,
        client=client,
        manifest_store=manifest_store,
        manifest_payload=manifest_payload,
    )
    target = items[0]
    query_specs: list[tuple[str, str, str]] = [
        ("name", target.name, target.public_id),
        ("definition", target.content_md[:300], target.public_id),
    ]
    domain = db.scalar(select(Domain).where(Domain.domain_code == document.domain_code))
    directions = list((domain.config_json if domain else {}).get("learning_directions") or [])
    for direction in directions[:6]:
        tags = {str(tag).casefold() for tag in direction.get("match_tags") or []}
        representative = next(
            (
                item for item in items
                if tags & {str(tag).casefold() for tag in item.tags_json or []}
            ),
            None,
        )
        if representative is not None:
            query_specs.append((
                f"direction:{direction.get('value')}",
                representative.content_md[:300],
                representative.public_id,
            ))
    matches = _smoke_matches(
        collection,
        manifest,
        [(query_type, query) for query_type, query, _ in query_specs],
        provider,
    )
    imported_ids = {item.public_id for item in items}
    checks: dict[str, dict[str, object]] = {}
    for query_type, _, expected_id in query_specs:
        matched_ids, _ = matches[query_type]
        passed = expected_id in matched_ids and not any(
            knowledge_id not in imported_ids for knowledge_id in matched_ids
        )
        checks[query_type] = {
            "passed": passed,
            "expected_knowledge_id": expected_id,
            "matched_knowledge_ids": matched_ids,
        }
    hit_count = sum(bool(check["passed"]) for check in checks.values())
    hit_rate = hit_count / len(checks) if checks else 0.0
    if hit_rate < 0.9:
        raise KnowledgeImportPublishError("导入知识 Top-K 检索命中率低于 90%")
    return {
        "passed": True,
        "hit_rate": round(hit_rate, 4),
        "query_count": len(checks),
        "failed_queries": [key for key, check in checks.items() if not check["passed"]],
        "active_collection": manifest.active_collection,
        "target_knowledge_id": target.public_id,
        "checks": checks,
    }


def smoke_domain_index(
    db: Session,
    domain_code: str,
    *,
    provider: OpenAICompatibleEmbeddingProvider | None = None,
    client: object | None = None,
    manifest_store: CandidateManifestStore | DatabaseManifestStore | None = None,
    manifest_payload: dict[str, object] | None = None,
    staged_document_id: int | None = None,
) -> dict[str, object]:
    """Verify that the active index retrieves its own domain and nothing else."""
    visibility_filter = KnowledgeItem.status == "published"
    if staged_document_id is not None:
        visibility_filter = visibility_filter | (
            (KnowledgeItem.status == "staged")
            & (KnowledgeItem.source_document_id == staged_document_id)
        )
    items = list(
        db.scalars(
            select(KnowledgeItem)
            .where(
                KnowledgeItem.domain_code == domain_code,
                visibility_filter,
            )
            .order_by(KnowledgeItem.id)
        )
    )
    if not items:
        raise KnowledgeImportPublishError("当前领域没有可用于检索验证的已发布知识点")

    collection, manifest = _smoke_context(
        db,
        domain_code,
        client=client,
        manifest_store=manifest_store,
        manifest_payload=manifest_payload,
    )
    target = items[0]
    queries = {"name": target.name, "definition": target.content_md[:300]}
    matches = _smoke_matches(collection, manifest, list(queries.items()), provider)
    domain_ids = {item.public_id for item in items}
    checks: dict[str, dict[str, object]] = {}
    for query_type in queries:
        matched_ids, metadatas = matches[query_type]
        foreign_matches = [
            knowledge_id
            for knowledge_id, metadata in zip(matched_ids, metadatas, strict=True)
            if metadata.get("domain_code") != domain_code or knowledge_id not in domain_ids
        ]
        target_hit = target.public_id in matched_ids
        checks[query_type] = {
            "passed": target_hit and not foreign_matches,
            "target_hit": target_hit,
            "matched_knowledge_ids": matched_ids,
            "foreign_knowledge_ids": foreign_matches,
        }

    if not all(bool(check["passed"]) for check in checks.values()):
        raise KnowledgeImportPublishError("名称或释义检索未命中目标知识，或存在跨领域结果")
    return {
        "passed": True,
        "active_collection": manifest.active_collection,
        "target_knowledge_id": target.public_id,
        "checks": checks,
    }


def _collection_exists(client: object, name: str) -> bool:
    try:
        client.get_collection(name=name)
    except Exception:
        return False
    return True
