from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import Base, DiagnosticQuestion, KnowledgeItem, KnowledgeRelation
from app.rag.candidate_index import (
    CandidateIndexBuilder,
    CandidateIndexError,
    database_source_snapshot,
)
from app.rag.candidate_chunker import chunk_knowledge_item
from app.rag.candidate_manifest import CandidateManifestStore
from app.scripts.seed_data import load_json, seed_knowledge_items
from app.scripts.validate_rag_seed import source_data_version


EXPECTED_SOURCE_VERSION = (
    "sha256:a02334aa3f59325c21cfa48ecb58cf36b3e4056f5fffea01f890943c8508e5ba"
)


class FakeProvider:
    def __init__(self, model_name: str = "test-embedding", dimensions: int = 3) -> None:
        self._model_name = model_name
        self.dimensions = dimensions
        self.calls: list[list[str]] = []

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [
            [float((len(text) + index + offset) % 17) for offset in range(self.dimensions)]
            for index, text in enumerate(texts)
        ]


class FakeCollection:
    def __init__(self, name: str, *, metadata=None, configuration=None) -> None:
        self.name = name
        self.metadata = metadata or {}
        self.configuration = configuration or {}
        self.records: dict[str, dict[str, Any]] = {}

    def add(self, *, ids, embeddings, documents, metadatas) -> None:
        for index, item_id in enumerate(ids):
            if item_id in self.records:
                raise ValueError("duplicate ID")
            self.records[item_id] = {
                "embedding": list(embeddings[index]),
                "document": documents[index],
                "metadata": dict(metadatas[index]),
            }

    def get(self, *, include) -> dict[str, Any]:
        ids = sorted(self.records)
        return {
            "ids": ids,
            "embeddings": [self.records[item_id]["embedding"] for item_id in ids],
            "documents": [self.records[item_id]["document"] for item_id in ids],
            "metadatas": [self.records[item_id]["metadata"] for item_id in ids],
        }

    def count(self) -> int:
        return len(self.records)


class FakeChromaClient:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {
            "knowledge_ai_app_dev": FakeCollection("knowledge_ai_app_dev")
        }

    def create_collection(
        self, *, name, configuration, metadata, embedding_function
    ) -> FakeCollection:
        assert embedding_function is None
        assert configuration == {"hnsw": {"space": "cosine"}}
        if name in self.collections:
            raise ValueError("collection exists")
        collection = FakeCollection(
            name, metadata=metadata, configuration=configuration
        )
        self.collections[name] = collection
        return collection

    def get_collection(self, *, name) -> FakeCollection:
        if name not in self.collections:
            raise ValueError("collection missing")
        return self.collections[name]

    def delete_collection(self, *, name) -> None:
        if name not in self.collections:
            raise ValueError("collection missing")
        del self.collections[name]

    def list_collections(self) -> list[FakeCollection]:
        return list(self.collections.values())


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _item(item_id: str, content: str, *, needs_reembedding: bool = False) -> KnowledgeItem:
    return KnowledgeItem(
        public_id=item_id,
        domain_code="ai_app_dev",
        name=f"名称 {item_id}",
        category="测试",
        difficulty=2,
        tags_json=["tag"],
        content_md=content,
        source_title="Official source",
        source_url="https://example.com/source",
        license_note="Official documentation summary",
        needs_reembedding=needs_reembedding,
    )


def test_database_snapshot_reproduces_frozen_seed_version() -> None:
    sessions = _session_factory()
    with sessions() as db:
        seed_knowledge_items(db)
        db.flush()
        items = list(db.scalars(select(KnowledgeItem).order_by(KnowledgeItem.public_id)))

        assert source_data_version(database_source_snapshot(db, items)) == EXPECTED_SOURCE_VERSION


def test_llm_api_common_error_chunk_keeps_explicit_error_semantics() -> None:
    payload = next(
        item for item in load_json("knowledge_items.json") if item["knowledge_id"] == "llm_api_calling"
    )
    chunks = chunk_knowledge_item(
        knowledge_id=payload["knowledge_id"],
        name=payload["name"],
        category=payload["category"],
        difficulty=payload["difficulty"],
        tags=payload["tags"],
        content_md=payload["content"],
    )

    common_error_chunks = [chunk for chunk in chunks if "常见错误" in chunk.heading_path]

    assert common_error_chunks
    assert any(
        "常见错误包括：把兼容接口当作行为完全一致" in chunk.content
        for chunk in common_error_chunks
    )


def test_git_operation_chunk_contains_staging_and_commit_commands() -> None:
    payload = next(
        item for item in load_json("knowledge_items.json") if item["knowledge_id"] == "git_collaboration"
    )
    chunks = chunk_knowledge_item(
        knowledge_id=payload["knowledge_id"],
        name=payload["name"],
        category=payload["category"],
        difficulty=payload["difficulty"],
        tags=payload["tags"],
        content_md=payload["content"],
    )

    operation_chunks = [chunk for chunk in chunks if "操作步骤" in chunk.heading_path]

    assert operation_chunks
    operation_text = "\n".join(chunk.content for chunk in operation_chunks)
    assert "git add <file1> <file2>" in operation_text
    assert 'git commit -m "<intent-based message>"' in operation_text


def test_reseeding_unchanged_items_does_not_require_reembedding() -> None:
    sessions = _session_factory()
    with sessions() as db:
        seeded = seed_knowledge_items(db)
        db.commit()
        for item in seeded.values():
            item.needs_reembedding = False
        db.commit()

        seed_knowledge_items(db)
        db.commit()

        pending = list(
            db.scalars(
                select(KnowledgeItem).where(KnowledgeItem.needs_reembedding.is_(True))
            )
        )
        assert pending == []


def test_full_then_incremental_build_reuses_vectors_and_removes_orphans(
    tmp_path: Path,
) -> None:
    sessions = _session_factory()
    client = FakeChromaClient()
    store = CandidateManifestStore(root=tmp_path)
    clock = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
    provider = FakeProvider()
    with sessions() as db:
        db.add_all([_item("item-a", "甲" * 900), _item("item-b", "乙" * 200)])
        db.commit()
        first = CandidateIndexBuilder(
            db=db,
            chroma_client=client,
            embedding_provider=provider,
            manifest_store=store,
            now=lambda: clock,
        ).build(reset=True)

        first_manifest = store.load("ai_app_dev")
        assert first["status"] == "built"
        assert first["mode"] == "full"
        assert first["indexed_items"] == 2
        assert first["indexed_chunks"] == 3
        assert first_manifest is not None
        assert first_manifest.active_collection == first["active_collection"]
        assert "knowledge_ai_app_dev" in client.collections
        client.collections["knowledge_other_domain_candidate_legacy"] = FakeCollection("knowledge_other_domain_candidate_legacy")

        item_a = db.scalar(select(KnowledgeItem).where(KnowledgeItem.public_id == "item-a"))
        item_b = db.scalar(select(KnowledgeItem).where(KnowledgeItem.public_id == "item-b"))
        assert item_a is not None and item_b is not None
        item_a.content_md += "变更。"
        item_a.needs_reembedding = True
        item_a.updated_at = clock + timedelta(seconds=1)
        db.delete(item_b)
        db.commit()

        provider.calls.clear()
        second = CandidateIndexBuilder(
            db=db,
            chroma_client=client,
            embedding_provider=provider,
            manifest_store=store,
            now=lambda: clock + timedelta(seconds=2),
        ).build(reset=False)

        second_manifest = store.load("ai_app_dev")
        assert second["mode"] == "incremental"
        assert second["reembedded_items"] == 1
        assert second["orphan_items_removed"] == 1
        assert second["indexed_items"] == 1
        assert provider.calls and all("名称 item-a" in text for text in provider.calls[0])
        assert second_manifest is not None
        assert second_manifest.active_collection == second["active_collection"]
        assert second_manifest.previous_collection == first["active_collection"]
        candidate_names = [name for name in client.collections if "_candidate_" in name]
        assert set(candidate_names) == {
            second_manifest.active_collection,
            second_manifest.previous_collection,
            "knowledge_other_domain_candidate_legacy",
        }
        assert item_a.needs_reembedding is False
        assert "knowledge_ai_app_dev" in client.collections
        assert "knowledge_other_domain_candidate_legacy" in client.collections


def test_unchanged_incremental_build_does_not_call_provider(tmp_path: Path) -> None:
    sessions = _session_factory()
    client = FakeChromaClient()
    store = CandidateManifestStore(root=tmp_path)
    clock = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
    with sessions() as db:
        item = _item("item-a", "稳定内容。" * 30)
        # Keep ORM timestamps aligned with the builder's injected clock.
        item.created_at = clock - timedelta(seconds=1)
        item.updated_at = clock - timedelta(seconds=1)
        db.add(item)
        db.commit()
        first_provider = FakeProvider()
        CandidateIndexBuilder(
            db=db,
            chroma_client=client,
            embedding_provider=first_provider,
            manifest_store=store,
            now=lambda: clock,
        ).build(reset=True)

        second_provider = FakeProvider()
        result = CandidateIndexBuilder(
            db=db,
            chroma_client=client,
            embedding_provider=second_provider,
            manifest_store=store,
            now=lambda: clock + timedelta(seconds=1),
        ).build(reset=False)

        assert result["status"] == "unchanged"
        assert second_provider.calls == []


def test_reset_rebuilds_when_manifest_points_to_missing_collection(tmp_path: Path) -> None:
    sessions = _session_factory()
    client = FakeChromaClient()
    store = CandidateManifestStore(root=tmp_path)
    with sessions() as db:
        db.add(_item("item-a", "恢复索引的知识内容。" * 30))
        db.commit()
        first = CandidateIndexBuilder(
            db=db,
            chroma_client=client,
            embedding_provider=FakeProvider(),
            manifest_store=store,
        ).build(reset=True)
        client.delete_collection(name=first["active_collection"])

        result = CandidateIndexBuilder(
            db=db,
            chroma_client=client,
            embedding_provider=FakeProvider(),
            manifest_store=store,
        ).build(reset=True)

        manifest = store.load(
            "ai_app_dev", collection_exists=lambda name: name in client.collections
        )
        assert result["status"] == "built"
        assert manifest is not None
        assert manifest.active_collection == result["active_collection"]
        assert manifest.previous_collection is None


def test_index_integrity_rejects_duplicate_content_blocks(tmp_path: Path) -> None:
    sessions = _session_factory()
    with sessions() as db:
        db.add_all([
            _item("item-a", "完全相同的知识内容块。"),
            _item("item-b", "完全相同的知识内容块。"),
        ])
        db.commit()

        with pytest.raises(CandidateIndexError, match="duplicate candidate chunk content"):
            CandidateIndexBuilder(
                db=db,
                chroma_client=FakeChromaClient(),
                embedding_provider=FakeProvider(),
                manifest_store=CandidateManifestStore(root=tmp_path),
            ).build(reset=True)


def test_index_integrity_rejects_question_without_explanation(tmp_path: Path) -> None:
    sessions = _session_factory()
    with sessions() as db:
        item = _item("item-a", "用于题目校验的知识内容。")
        db.add(item)
        db.flush()
        db.add(
            DiagnosticQuestion(
                public_id="question-a",
                domain_code="ai_app_dev",
                knowledge_item_id=item.id,
                question_type="single_choice",
                stem="哪一项正确？",
                options_json=["正确", "错误"],
                answer_key_json={"correct_option": 0},
                difficulty=1,
            )
        )
        db.commit()

        with pytest.raises(CandidateIndexError, match="has no explanation"):
            CandidateIndexBuilder(
                db=db,
                chroma_client=FakeChromaClient(),
                embedding_provider=FakeProvider(),
                manifest_store=CandidateManifestStore(root=tmp_path),
            ).build(reset=True)


def test_index_integrity_rejects_cross_domain_relation(tmp_path: Path) -> None:
    sessions = _session_factory()
    with sessions() as db:
        local = _item("item-a", "本领域知识内容。")
        external = _item("item-b", "其他领域知识内容。")
        external.domain_code = "other_domain"
        db.add_all([local, external])
        db.flush()
        db.add(
            KnowledgeRelation(
                source_item_id=external.id,
                target_item_id=local.id,
                relation_type="prerequisite",
            )
        )
        db.commit()

        with pytest.raises(CandidateIndexError, match="orphan or cross-domain"):
            CandidateIndexBuilder(
                db=db,
                chroma_client=FakeChromaClient(),
                embedding_provider=FakeProvider(),
                manifest_store=CandidateManifestStore(root=tmp_path),
            ).build(reset=True)


def test_incremental_build_rejects_model_change_without_touching_active(
    tmp_path: Path,
) -> None:
    sessions = _session_factory()
    client = FakeChromaClient()
    store = CandidateManifestStore(root=tmp_path)
    clock = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
    with sessions() as db:
        db.add(_item("item-a", "测试内容。" * 30))
        db.commit()
        CandidateIndexBuilder(
            db=db,
            chroma_client=client,
            embedding_provider=FakeProvider("model-a"),
            manifest_store=store,
            now=lambda: clock,
        ).build(reset=True)
        original = store.load("ai_app_dev")

        with pytest.raises(CandidateIndexError, match="--reset"):
            CandidateIndexBuilder(
                db=db,
                chroma_client=client,
                embedding_provider=FakeProvider("model-b"),
                manifest_store=store,
                now=lambda: clock + timedelta(seconds=1),
            ).build(reset=False)

        assert store.load("ai_app_dev") == original
