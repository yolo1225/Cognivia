from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found, unavailable, validation_error
from app.models import KnowledgeItem
from app.rag.embeddings import embed_texts, embedding_model_name
from app.rag.vector_store import VectorStore
from app.repositories.knowledge_repo import KnowledgeRepository
from app.schemas.api_requests import KnowledgeItemCreateRequest, KnowledgeItemUpdateRequest
from app.scripts.build_chroma_index import build_index
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
        item = self.repository.add(KnowledgeItem(
            public_id=f"ki_{uuid4().hex[:12]}", domain_code=payload.domain_code,
            name=payload.name.strip(), category=payload.category.strip(), difficulty=payload.difficulty,
            tags_json=[tag.strip() for tag in payload.tags if tag.strip()], content_md=payload.content.strip(),
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

    def search(self, query: str, domain_code: str, n_results: int, vector_store: VectorStore) -> dict[str, Any]:
        result = vector_store.query(domain_code=domain_code, query_embeddings=embed_texts([query]), n_results=n_results)
        ids, documents = result.get("ids", [[]])[0], result.get("documents", [[]])[0]
        metadatas, distances = result.get("metadatas", [[]])[0], result.get("distances", [[]])[0]
        matches = [
            {"id": item_id, "knowledge_id": metadatas[index].get("knowledge_id"), "name": metadatas[index].get("name"), "category": metadatas[index].get("category"), "difficulty": metadatas[index].get("difficulty"), "source_title": metadatas[index].get("source_title"), "distance": distances[index], "preview": documents[index][:180]}
            for index, item_id in enumerate(ids)
        ]
        return {"domain_code": domain_code, "query": query, "matches": matches, "total": len(matches), "embedding_model": embedding_model_name()}

    def rebuild_index(self, domain_code: str, vector_store: VectorStore) -> dict[str, Any]:
        try:
            result = build_index(
                domain_code=domain_code,
                only_pending=True,
                db_session=self.db,
                vector_store=vector_store,
                commit=False,
            )
        except Exception as exc:
            raise unavailable("VECTOR_INDEX_REBUILD_FAILED", "向量索引重建失败") from exc
        return {"status": "completed", "affected_domain": domain_code, **result}

    @staticmethod
    def _write_result(item: KnowledgeItem, affected_ids: set[str], impact: dict[str, int]) -> dict[str, Any]:
        return {"item": serialize_knowledge_item(item), "index_status": "needs_rebuild", "affected_knowledge_ids": sorted(affected_ids), "affected_learning_paths": impact["learning_paths"], "affected_resources": impact["resources"], "next_action": "rebuild_vector_index"}
