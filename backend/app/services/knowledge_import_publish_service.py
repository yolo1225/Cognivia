from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    DiagnosticQuestion,
    Domain,
    IndexBuildJob,
    KnowledgeDocument,
    KnowledgeImportCandidate,
    KnowledgeItem,
    KnowledgeRelation,
)
from app.agents.domain_evidence_policy import normalize_evidence_capabilities
from app.rag.candidate_index import CandidateIndexBuilder
from app.rag.candidate_manifest import (
    CandidateIndexManifest,
    CandidateManifestStore,
)
from app.rag.embedding_provider import OpenAICompatibleEmbeddingProvider
from app.rag.vector_store import VectorStore
from app.services.domain_api_service import default_ability_weights


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
    db.scalar(
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
        raise KnowledgeImportPublishError("导入没有待发布知识")
    for item in items:
        item.status = "published"
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
    for candidate in candidates:
        if candidate.candidate_type != "knowledge_item":
            continue
        payload = candidate.payload_json
        item = KnowledgeItem(
            public_id=f"ki_{uuid4().hex[:12]}",
            domain_code=document.domain_code,
            name=str(payload["name"])[:255],
            category=str(payload.get("category") or "未分类")[:64],
            difficulty=int(payload["difficulty"]),
            tags_json=payload.get("tags") or [],
            evidence_capabilities_json=normalize_evidence_capabilities(
                payload.get("evidence_capabilities")
            ),
            content_md=payload["content"],
            source_title=document.source_title,
            source_url=None,
            license_note=document.license_note,
            needs_reembedding=True,
            source_document_id=document.id,
            ability_weights_json=payload.get("ability_weights") or default_ability_weights(),
            source_locator_json=candidate.source_locator_json or {},
            status="staged",
        )
        db.add(item)
        db.flush()
        knowledge_map[candidate.public_id] = item
    relation_count = 0
    question_count = 0
    for candidate in candidates:
        payload = candidate.payload_json
        if candidate.candidate_type == "knowledge_relation":
            source = knowledge_map.get(payload.get("source_candidate_id"))
            target = knowledge_map.get(payload.get("target_candidate_id"))
            if source and target:
                db.add(
                    KnowledgeRelation(
                        source_item_id=source.id,
                        target_item_id=target.id,
                        relation_type=payload.get("relation_type", "related"),
                    )
                )
                relation_count += 1
        elif candidate.candidate_type == "diagnostic_question":
            item = knowledge_map.get(payload.get("knowledge_candidate_id"))
            if item:
                question_type = payload.get("question_type", "short_answer")
                options = payload.get("options") or []
                if question_type == "single_choice":
                    raw_answer = payload["answer"]
                    correct_option = (
                        raw_answer if isinstance(raw_answer, int) else options.index(raw_answer)
                    )
                    answer_key = {
                        "correct_option": correct_option,
                        "explanation": payload.get("explanation", ""),
                        "source_locator": f"knowledge:{item.public_id}#chunk=0",
                        "source_ref_ids": [item.public_id],
                    }
                else:
                    answer_key = {
                        "answer": payload["answer"],
                        "rubric": payload.get("rubric") or [],
                        "explanation": payload.get("explanation", ""),
                        "source_locator": f"knowledge:{item.public_id}#chunk=0",
                        "source_ref_ids": [item.public_id],
                    }
                db.add(
                    DiagnosticQuestion(
                        public_id=f"dq_{uuid4().hex[:12]}",
                        domain_code=document.domain_code,
                        knowledge_item_id=item.id,
                        question_type=question_type,
                        stem=payload["stem"],
                        options_json=options,
                        answer_key_json=answer_key,
                        difficulty=int(payload.get("difficulty", 2)),
                    )
                )
                question_count += 1
    for candidate in candidates:
        candidate.status = "approved"
    document.status = "index_pending"
    document.knowledge_item_count = len(knowledge_map)
    db.commit()
    return {
        "knowledge_items": len(knowledge_map),
        "relations": relation_count,
        "questions": question_count,
    }


def ensure_import_source_locators(db: Session, document: KnowledgeDocument) -> int:
    """Backfill traceability for imports materialized before the M1 locator fix."""
    items = list(
        db.scalars(select(KnowledgeItem).where(KnowledgeItem.source_document_id == document.id))
    )
    by_id = {item.id: item for item in items}
    if not by_id:
        return 0
    changed = 0
    questions = list(
        db.scalars(
            select(DiagnosticQuestion).where(DiagnosticQuestion.knowledge_item_id.in_(by_id))
        )
    )
    for question in questions:
        item = by_id[question.knowledge_item_id]
        answer = dict(question.answer_key_json or {})
        expected = f"knowledge:{item.public_id}#chunk=0"
        if answer.get("source_locator") != expected:
            answer["source_locator"] = expected
            answer["source_ref_ids"] = [item.public_id]
            question.answer_key_json = answer
            changed += 1
    if changed:
        db.flush()
    return changed


def smoke_import_index(
    db: Session,
    document: KnowledgeDocument,
    *,
    provider: OpenAICompatibleEmbeddingProvider | None = None,
    client: object | None = None,
    manifest_store: CandidateManifestStore | None = None,
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
    store = manifest_store or CandidateManifestStore()
    vector_client = client or VectorStore().client
    manifest = (
        CandidateIndexManifest.from_dict(manifest_payload)
        if manifest_payload is not None
        else store.load(
            document.domain_code,
            collection_exists=lambda name: _collection_exists(vector_client, name),
        )
    )
    if manifest is None:
        raise KnowledgeImportPublishError("Candidate 活动 manifest 不存在")
    collection = vector_client.get_collection(name=manifest.active_collection)
    target = items[0]
    queries = {"name": target.name, "definition": target.content_md[:300]}
    vectors = (provider or OpenAICompatibleEmbeddingProvider()).embed_texts(list(queries.values()))
    imported_ids = {item.public_id for item in items}
    checks: dict[str, dict[str, object]] = {}
    for (query_type, _), vector in zip(queries.items(), vectors, strict=True):
        result = collection.query(
            query_embeddings=[vector],
            n_results=min(5, manifest.indexed_chunk_count),
            include=["metadatas", "distances"],
        )
        metadatas = (result.get("metadatas") or [[]])[0]
        matched_ids = [str(metadata.get("knowledge_id", "")) for metadata in metadatas]
        passed = any(knowledge_id in imported_ids for knowledge_id in matched_ids)
        checks[query_type] = {"passed": passed, "matched_knowledge_ids": matched_ids}
    if not all(bool(check["passed"]) for check in checks.values()):
        raise KnowledgeImportPublishError("名称或释义检索未命中本次导入知识")
    return {
        "passed": True,
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
    manifest_store: CandidateManifestStore | None = None,
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

    store = manifest_store or CandidateManifestStore()
    vector_client = client or VectorStore().client
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

    collection = vector_client.get_collection(name=manifest.active_collection)
    target = items[0]
    queries = {"name": target.name, "definition": target.content_md[:300]}
    vectors = (provider or OpenAICompatibleEmbeddingProvider()).embed_texts(list(queries.values()))
    domain_ids = {item.public_id for item in items}
    checks: dict[str, dict[str, object]] = {}
    for (query_type, _), vector in zip(queries.items(), vectors, strict=True):
        result = collection.query(
            query_embeddings=[vector],
            n_results=min(5, manifest.indexed_chunk_count),
            include=["metadatas", "distances"],
        )
        metadatas = (result.get("metadatas") or [[]])[0]
        matched_ids = [str(metadata.get("knowledge_id", "")) for metadata in metadatas]
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
