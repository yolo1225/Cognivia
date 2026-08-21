from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found, unavailable, validation_error
from app.models import KnowledgeItem
from app.rag.candidate_index import CandidateIndexBuilder
from app.rag.candidate_index_access import CandidateIndexAccess, CandidateIndexUnavailable
from app.rag.embedding_provider import OpenAICompatibleEmbeddingProvider
from app.repositories.knowledge_repo import KnowledgeRepository
from app.schemas.api_requests import KnowledgeItemCreateRequest, KnowledgeItemUpdateRequest
from app.agents.domain_evidence_policy import get_domain_evidence_policy
from app.services.knowledge_update_service import (
    mark_affected_content,
    related_knowledge_ids,
    replace_item_relations,
)


def serialize_knowledge_item(item: KnowledgeItem) -> dict[str, Any]:
    return {
        "knowledge_id": item.public_id,
        "domain_code": item.domain_code,
        "name": item.name,
        "category": item.category,
        "difficulty": item.difficulty,
        "tags": item.tags_json or [],
        "content": item.content_md,
        "source_title": item.source_title,
        "source_url": item.source_url,
        "license_note": item.license_note,
        "needs_reembedding": item.needs_reembedding,
    }


class KnowledgeApiService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = KnowledgeRepository(db)

    def list(self, domain_code: str, category: str | None, limit: int, offset: int) -> dict[str, Any]:
        items, total = self.repository.list(domain_code, category, limit, offset)
        return {"domain_code": domain_code, "items": [serialize_knowledge_item(item) for item in items], "total": total, "limit": limit, "offset": offset, "mvp_target": 50}

    def create(self, payload: KnowledgeItemCreateRequest) -> dict[str, Any]:
        if self.repository.find_by_name(payload.domain_code, payload.name.strip()) is not None:
            raise conflict("KNOWLEDGE_ITEM_ALREADY_EXISTS", f"知识点已存在：{payload.name}")
        capabilities = sorted(
            item.value
            for item in get_domain_evidence_policy(payload.domain_code).classify_content(
                payload.content
            )
        )
        item = self.repository.add(KnowledgeItem(
            public_id=f"ki_{uuid4().hex[:12]}", domain_code=payload.domain_code,
            name=payload.name.strip(), category=payload.category.strip(), difficulty=payload.difficulty,
            tags_json=[tag.strip() for tag in payload.tags if tag.strip()], content_md=payload.content.strip(),
            evidence_capabilities_json=capabilities,
            source_title=payload.source_title.strip(), source_url=payload.source_url,
            license_note=payload.license_note.strip(), needs_reembedding=True,
        ))
        try:
            replace_item_relations(self.db, item=item, relation_type="prerequisite", source_public_ids=payload.prerequisites)
            replace_item_relations(self.db, item=item, relation_type="related", source_public_ids=payload.related)
        except ValueError as exc:
            raise validation_error("KNOWLEDGE_RELATION_INVALID", str(exc)) from exc
        affected_ids = related_knowledge_ids(self.db, item)
        impact = mark_affected_content(self.db, domain_code=item.domain_code, affected_knowledge_ids=affected_ids, reason="manual_import")
        return self._write_result(item, affected_ids, impact)

    def update(self, knowledge_id: str, payload: KnowledgeItemUpdateRequest) -> dict[str, Any]:
        item = self.repository.get(knowledge_id)
        if item is None:
            raise not_found("KNOWLEDGE_ITEM_NOT_FOUND", f"知识点不存在：{knowledge_id}")
        affected_ids = related_knowledge_ids(self.db, item)
        values = payload.model_dump(exclude_unset=True)
        fields = {"name": "name", "category": "category", "difficulty": "difficulty", "content": "content_md", "source_title": "source_title", "source_url": "source_url", "license_note": "license_note"}
        for source, target in fields.items():
            if source in values:
                value = values[source]
                setattr(item, target, value.strip() if isinstance(value, str) else value)
        if "tags" in values:
            item.tags_json = [tag.strip() for tag in values["tags"] if tag.strip()]
        if "content" in values:
            item.evidence_capabilities_json = sorted(
                capability.value
                for capability in get_domain_evidence_policy(item.domain_code).classify_content(
                    item.content_md
                )
            )
        try:
            if payload.prerequisites is not None:
                replace_item_relations(self.db, item=item, relation_type="prerequisite", source_public_ids=payload.prerequisites)
            if payload.related is not None:
                replace_item_relations(self.db, item=item, relation_type="related", source_public_ids=payload.related)
        except ValueError as exc:
            raise validation_error("KNOWLEDGE_RELATION_INVALID", str(exc)) from exc
        item.needs_reembedding = True
        self.db.flush()
        affected_ids.update(related_knowledge_ids(self.db, item))
        impact = mark_affected_content(self.db, domain_code=item.domain_code, affected_knowledge_ids=affected_ids, reason="knowledge_item_updated")
        return self._write_result(item, affected_ids, impact)

    def retrieval_preview(self, query: str, domain_code: str, n_results: int, chroma_client: Any) -> dict[str, Any]:
        try:
            manifest, collection = CandidateIndexAccess(chroma_client).active(domain_code)
            vectors = OpenAICompatibleEmbeddingProvider().embed_texts([query])
            if len(vectors) != 1 or len(vectors[0]) != manifest.embedding_dimensions:
                raise CandidateIndexUnavailable("candidate query embedding dimensions do not match manifest")
            result = collection.query(
                query_embeddings=vectors,
                n_results=min(collection.count(), n_results),
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            raise unavailable("CANDIDATE_RETRIEVAL_UNAVAILABLE", "Candidate V3 检索不可用") from exc
        ids, documents = result.get("ids", [[]])[0], result.get("documents", [[]])[0]
        metadatas, distances = result.get("metadatas", [[]])[0], result.get("distances", [[]])[0]
        matches = [
            {
                "id": str(item_id),
                "knowledge_id": metadatas[index].get("knowledge_id"),
                "name": metadatas[index].get("name"),
                "category": metadatas[index].get("category"),
                "difficulty": metadatas[index].get("difficulty"),
                "source_title": metadatas[index].get("source_title"),
                "similarity": max(0.0, min(1.0, 1.0 - float(distances[index]))),
                "preview": str(documents[index])[:180],
            }
            for index, item_id in enumerate(ids)
        ]
        return {"domain_code": domain_code, "query": query, "matches": matches, "total": len(matches), "embedding_model": manifest.embedding_model, "index_version": manifest.index_version}

    def reindex(self, domain_code: str, chroma_client: Any) -> dict[str, Any]:
        try:
            access = CandidateIndexAccess(chroma_client)
            try:
                access.active(domain_code)
                reset = False
            except CandidateIndexUnavailable:
                reset = True
            result = CandidateIndexBuilder(
                db=self.db,
                chroma_client=chroma_client,
                embedding_provider=OpenAICompatibleEmbeddingProvider(),
            ).build(
                domain_code=domain_code, reset=reset, commit=False
            )
        except Exception as exc:
            raise unavailable("CANDIDATE_INDEX_REBUILD_FAILED", "Candidate V3 索引重建失败") from exc
        return {"affected_domain": domain_code, **result}

    def reindex_status(self, domain_code: str, chroma_client: Any) -> dict[str, Any]:
        pending = int(
            self.db.scalar(
                select(func.count()).select_from(KnowledgeItem).where(
                    KnowledgeItem.domain_code == domain_code,
                    KnowledgeItem.needs_reembedding.is_(True),
                )
            )
            or 0
        )
        try:
            manifest, _ = CandidateIndexAccess(chroma_client).active(domain_code)
        except CandidateIndexUnavailable as exc:
            message = str(exc)
            return {"domain_code": domain_code, "status": "missing" if "missing" in message else "invalid", "pending_reembedding": pending, "reason": message}
        item_count = int(
            self.db.scalar(select(func.count()).select_from(KnowledgeItem).where(KnowledgeItem.domain_code == domain_code)) or 0
        )
        stale = pending > 0 or manifest.indexed_item_count != item_count
        return {
            "domain_code": domain_code,
            "status": "stale" if stale else "ready",
            "pending_reembedding": pending,
            "active_collection": manifest.active_collection,
            "indexed_items": manifest.indexed_item_count,
            "indexed_chunks": manifest.indexed_chunk_count,
            "embedding_model": manifest.embedding_model,
            "index_version": manifest.index_version,
            "last_successful_sync_at": manifest.last_successful_sync_at,
        }

    @staticmethod
    def _write_result(item: KnowledgeItem, affected_ids: set[str], impact: dict[str, int]) -> dict[str, Any]:
        return {"item": serialize_knowledge_item(item), "index_status": "needs_rebuild", "affected_knowledge_ids": sorted(affected_ids), "affected_learning_paths": impact["learning_paths"], "affected_resources": impact["resources"], "next_action": "reindex_candidate"}
