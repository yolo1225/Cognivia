from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import (
    Base,
    DiagnosticQuestion,
    KnowledgeDocument,
    KnowledgeChunk,
    KnowledgeImportCandidate,
    KnowledgeImportRun,
    KnowledgeItem,
    KnowledgeItemSource,
)
from app.services.knowledge_document_service import delete_document
from app.services.knowledge_extraction_service import normalize_knowledge_name, replace_candidates
from app.services.knowledge_import_publish_service import (
    KnowledgeImportPublishError,
    approve_candidates,
    publish_approved,
    smoke_domain_index,
    smoke_import_index,
)
from app.services.knowledge_import_validation_service import validate_import
from app.services.knowledge_parser_service import parse_document, replace_chunks
from app.services.knowledge_model_import_service import (
    _adapt_question_output,
    _adapt_validation_decision,
    _validate_candidate_batch,
    repair_curriculum_relations,
)
from app.services.llm_service import ModelCallError, ModelOutputTruncatedError
from app.services.knowledge_import_orchestrator import (
    _input_version,
    _merge_learning_direction_mappings,
    _suggest_learning_directions,
)
from app.services.knowledge_graph_quality_service import evaluate_graph_quality
from app.services.knowledge_import_batch_service import pack_by_tokens, prepare_batch
from app.services.knowledge_relation_algorithm_service import build_relation_plan


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False)()


def _document(tmp_path: Path) -> KnowledgeDocument:
    path = tmp_path / "guide.md"
    path.write_text(
        "# RAG 基础\n\n检索增强生成需要可靠来源。\n\n## 检索\n\n向量检索返回相关知识切片。",
        encoding="utf-8",
    )
    return KnowledgeDocument(
        public_id="kdoc_test",
        domain_code="ai_app_dev",
        original_name=path.name,
        stored_path=path.name,
        file_type="markdown",
        mime_type="text/markdown",
        size_bytes=path.stat().st_size,
        sha256="a" * 64,
        status="parsing",
        source_title="测试教材",
        license_note="test",
        uploaded_by="tester",
    )


def test_import_normalizes_source_library_prefix_from_knowledge_name() -> None:
    assert normalize_knowledge_name(
        "AI 机器学习基础知识库 (ai_ml_basics) / 77. Bahdanau 注意力机制"
    ) == "Bahdanau 注意力机制"
    assert normalize_knowledge_name("向量检索") == "向量检索"


def test_multisection_document_creates_traceable_candidates(tmp_path, monkeypatch) -> None:
    from app.services import knowledge_document_service

    monkeypatch.setattr(knowledge_document_service, "KNOWLEDGE_STORAGE_ROOT", tmp_path)
    db = _session()
    document = _document(tmp_path)
    db.add(document)
    db.commit()
    sections = parse_document(document)
    candidates = replace_candidates(db, document, sections)
    db.commit()
    assert len(sections) == 2
    assert sum(item.candidate_type == "knowledge_item" for item in candidates) == 2
    assert all(item.source_locator_json.get("checksum") for item in candidates)
    knowledge = next(item for item in candidates if item.candidate_type == "knowledge_item")
    assert set(knowledge.payload_json["ability_weights"]) == {
        "theory",
        "practice",
        "problem_solving",
        "knowledge_breadth",
        "learning_speed",
    }
    assert validate_import(db, document.id)["invalid"] == 0


def test_structured_markdown_preserves_exact_metadata(tmp_path, monkeypatch) -> None:
    from app.services import knowledge_document_service

    monkeypatch.setattr(knowledge_document_service, "KNOWLEDGE_STORAGE_ROOT", tmp_path)
    path = tmp_path / "structured.md"
    path.write_text(
        "# 领域知识（共 1 条）\n\n"
        "## 向量检索\n\n"
        "- **knowledge_id:** `rag.vector-search`\n"
        "- **category:** retrieval\n"
        "- **difficulty:** 3\n"
        "- **tags:** `rag`, `vector`\n"
        "- **source:** [课程规范](https://example.test/spec)\n"
        "- **license:** CC-BY-4.0\n"
        "- **prerequisites:** `embedding.basic`\n\n"
        "向量检索根据查询与知识切片的相似度返回候选证据。\n",
        encoding="utf-8",
    )
    document = KnowledgeDocument(
        public_id="kdoc_structured",
        domain_code="ai_app_dev",
        original_name=path.name,
        stored_path=path.name,
        file_type="markdown",
        mime_type="text/markdown",
        size_bytes=path.stat().st_size,
        sha256="b" * 64,
        status="parsing",
        source_title="上传文件",
        license_note="unknown",
        uploaded_by="tester",
    )

    sections = parse_document(document)

    assert len(sections) == 1
    assert sections[0]["heading_path"] == ["领域知识（共 1 条）", "向量检索"]
    assert sections[0]["metadata"] == {
        "knowledge_id": "rag.vector-search",
        "category": "retrieval",
        "difficulty": 3,
        "tags": ["rag", "vector"],
        "source_title": "课程规范",
        "source_url": "https://example.test/spec",
        "license": "CC-BY-4.0",
        "prerequisites": ["embedding.basic"],
    }
    assert "共 1 条" not in sections[0]["text"]


def test_source_withdrawal_keeps_shared_item_and_evidence_file(tmp_path, monkeypatch) -> None:
    from app.services import knowledge_document_service

    monkeypatch.setattr(knowledge_document_service, "KNOWLEDGE_STORAGE_ROOT", tmp_path)
    db = _session()
    documents = []
    for index in (1, 2):
        folder = tmp_path / f"kdoc_{index}"
        folder.mkdir()
        path = folder / "source.md"
        path.write_text(f"证据来源 {index}", encoding="utf-8")
        document = KnowledgeDocument(
            public_id=f"kdoc_{index}", domain_code="ai_app_dev",
            original_name=path.name, stored_path=f"kdoc_{index}/source.md",
            file_type="markdown", mime_type="text/markdown",
            size_bytes=path.stat().st_size, sha256=str(index) * 64,
            status="ready", source_title=f"来源 {index}", license_note="test",
            uploaded_by="tester",
        )
        db.add(document)
        documents.append(document)
    db.flush()
    item = KnowledgeItem(
        public_id="knowledge_shared", external_id="shared-1", domain_code="ai_app_dev",
        name="共享知识", category="test", difficulty=2, content_md="共享内容",
        source_title="来源 1", status="published",
    )
    db.add(item)
    db.flush()
    paths = []
    for index, document in enumerate(documents):
        chunk = KnowledgeChunk(
            public_id=f"chunk_{index}", document_id=document.id,
            domain_code=document.domain_code, chunk_index=0,
            heading_path_json=["共享知识"], content=f"证据来源 {index + 1}",
            checksum=str(index + 1) * 64,
        )
        db.add(chunk)
        db.flush()
        db.add(KnowledgeItemSource(
            knowledge_item_id=item.id, chunk_id=chunk.id, document_id=document.id,
            source_quote_hash=chunk.checksum, is_primary=index == 0, status="published",
        ))
        paths.append(tmp_path / document.stored_path)
    db.commit()

    first = delete_document(db, documents[0])
    assert first["knowledge_needs_attention"] == 0
    assert item.status == "published"
    assert paths[0].exists()

    second = delete_document(db, documents[1])
    assert second["knowledge_needs_attention"] == 1
    assert item.status == "needs_attention"
    assert paths[1].exists()


def test_learning_directions_are_suggested_from_imported_categories_and_tags() -> None:
    candidates = [
        SimpleNamespace(
            candidate_type="knowledge_item",
            payload_json={"category": "模型基础", "tags": ["llm", "prompt"]},
        ),
        SimpleNamespace(
            candidate_type="knowledge_item",
            payload_json={"category": "模型基础", "tags": ["llm", "api"]},
        ),
        SimpleNamespace(
            candidate_type="diagnostic_question",
            payload_json={"category": "ignored", "tags": ["ignored"]},
        ),
    ]

    first = _suggest_learning_directions(candidates)
    second = _suggest_learning_directions(candidates)

    assert first == second
    assert first == [{
        "value": first[0]["value"],
        "label": "模型基础",
        "description": "围绕模型基础相关知识形成的学习方向",
        "match_tags": ["llm", "prompt", "api"],
    }]
    assert str(first[0]["value"]).startswith("direction_")


def test_learning_direction_overflow_keeps_long_tail_tags() -> None:
    candidates = [
        SimpleNamespace(
            candidate_type="knowledge_item",
            payload_json={"category": f"分类 {index}", "tags": [f"tag-{index}"]},
        )
        for index in range(7)
    ]

    directions = _suggest_learning_directions(candidates)

    assert len(directions) == 6
    assert any("tag-6" in direction["match_tags"] for direction in directions)
    assert all(direction["label"] != "综合扩展" for direction in directions)


def test_direction_mapping_merge_preserves_manual_identity_and_covers_new_tags() -> None:
    configured = [{
        "value": "manual-a",
        "label": "人工方向",
        "description": "保留人工名称",
        "match_tags": ["existing"],
    }]
    merged = _merge_learning_direction_mappings(configured, [{
        "value": "generated-a",
        "label": "自动方向",
        "match_tags": ["existing", "new-topic"],
    }])

    assert merged[0]["value"] == "manual-a"
    assert merged[0]["label"] == "人工方向"
    assert merged[0]["description"] == "保留人工名称"
    assert set(merged[0]["match_tags"]) == {"existing", "new-topic"}


def test_sparse_graph_cannot_pass_all_node_quality_gate() -> None:
    item_tags = {f"node-{index}": {"shared"} for index in range(114)}
    edges = [
        {
            "source": f"node-{index}",
            "target": f"node-{index + 1}",
            "relation_type": "prerequisite",
            "evidence_complete": True,
        }
        for index in range(10)
    ]
    quality = evaluate_graph_quality(
        item_tags=item_tags,
        edges=edges,
        directions=[{"value": "all", "label": "全部", "match_tags": ["shared"]}],
    )

    assert quality["path_participating_nodes"] == 11
    assert quality["isolated_nodes"] == 103
    assert quality["quality_gate_passed"] is False
    assert {issue["code"] for issue in quality["blocking_issues"]} >= {
        "PATH_PARTICIPATION_LOW",
        "ISOLATED_NODES_HIGH",
    }


def test_related_to_does_not_count_as_learning_path() -> None:
    quality = evaluate_graph_quality(
        item_tags={"a": {"x"}, "b": {"x"}},
        edges=[{
            "source": "a", "target": "b", "relation_type": "related_to",
            "evidence_complete": True,
        }],
        directions=[{"value": "x", "label": "X", "match_tags": ["x"]}],
    )

    assert quality["directional_relations"] == 0
    assert quality["related_relations"] == 1
    assert quality["path_participating_nodes"] == 0


def test_question_adapter_normalizes_live_provider_aliases_and_nulls() -> None:
    adapted = _adapt_question_output({"items": [{
        "knowledge_candidate_id": "knowledge-1",
        "type": "short-answer",
        "question_text": "说明该机制的两个关键作用。",
        "answer": ["作用一", "作用二"],
        "rubric": None,
        "analysis": None,
        "dimension": "mechanism",
        "evidence_ids": [],
    }, {
        "knowledge_id": "knowledge-2",
        "type": "single-choice",
        "question": "哪项表述正确？",
        "options": ["甲", "乙", "丙", "丁"],
        "answer": "B",
        "rubric": ["选择唯一正确项"],
        "dimension": "concept",
    }, {
        "knowledge_id": "knowledge-3",
        "type": "short_answer",
        "stem": None,
        "answer": ["无题干记录应被过滤"],
    }]})

    assert len(adapted["questions"]) == 2
    assert adapted["questions"][0]["answer"] == "作用一；作用二"
    assert adapted["questions"][0]["rubric"] == ["作用一", "作用二"]
    assert adapted["questions"][0]["evidence_span_ids"] == ["span_1"]
    assert adapted["questions"][1]["answer"] == 1


def test_curriculum_repair_connects_only_deficient_nodes_without_model_calls(
    tmp_path,
) -> None:
    db = _session()
    document = _document(tmp_path)
    db.add(document)
    db.flush()
    candidates = []
    for index in range(8):
        candidate = KnowledgeImportCandidate(
            public_id=f"repair-{index}",
            document_id=document.id,
            domain_code=document.domain_code,
            candidate_type="knowledge_item",
            payload_json={
                "name": f"知识 {index}",
                "difficulty": 1 + index // 3,
                "tags": ["repair-direction"],
                "content": f"知识 {index} 的定义、机制与应用。",
                "source_quote": f"知识 {index} 的定义。",
                "source_chunk_ids": [f"chunk-{index}"],
                "after_checksum": str(index),
            },
            source_locator_json={"chunk_id": f"chunk-{index}", "checksum": str(index)},
        )
        db.add(candidate)
        candidates.append(candidate)
    db.flush()
    directions = [{
        "value": "repair",
        "label": "修复方向",
        "match_tags": ["repair-direction"],
    }]

    repaired = repair_curriculum_relations(
        db,
        document,
        candidates,
        directions,
        {item.public_id for item in candidates},
        repair_round=1,
    )
    quality = evaluate_graph_quality(
        item_tags={item.public_id: {"repair-direction"} for item in candidates},
        edges=[{
            "source": item.payload_json["source_candidate_id"],
            "target": item.payload_json["target_candidate_id"],
            "relation_type": item.payload_json["relation_type"],
            "evidence_complete": bool(item.payload_json["source_quote"]),
        } for item in repaired],
        directions=directions,
    )

    assert len(repaired) == 7
    assert all(item.payload_json["evidence_kind"] == "curriculum_rule" for item in repaired)
    assert all(item.payload_json["generation_method"] == "curriculum_repair" for item in repaired)
    assert quality["quality_gate_passed"] is True


def test_candidate_review_adaptively_splits_on_provider_input_limit(monkeypatch) -> None:
    sizes: list[int] = []

    def complete_json(**kwargs):
        records = kwargs["payload"]["records"]
        sizes.append(len(records))
        if len(records) > 2:
            raise ModelCallError("provider input too long")
        return {"accepted_ids": [record["id"] for record in records]}, {}

    monkeypatch.setattr(
        "app.services.knowledge_model_import_service.gateway.complete_json",
        complete_json,
    )
    candidates = [
        KnowledgeImportCandidate(
            public_id=f"question-{index}",
            document_id=1,
            domain_code="demo",
            candidate_type="diagnostic_question",
            payload_json={"stem": "题干", "source_quote": "来源"},
        )
        for index in range(8)
    ]

    assert _validate_candidate_batch(candidates) == {item.public_id for item in candidates}
    assert sizes[0] == 8
    assert max(sizes[1:]) <= 4


def test_single_truncated_candidate_review_is_filtered(monkeypatch) -> None:
    def complete_json(**_kwargs):
        raise ModelOutputTruncatedError("review output truncated")

    monkeypatch.setattr(
        "app.services.knowledge_model_import_service.gateway.complete_json",
        complete_json,
    )
    candidate = KnowledgeImportCandidate(
        public_id="question-1",
        document_id=1,
        domain_code="demo",
        candidate_type="diagnostic_question",
        payload_json={"stem": "题干", "source_quote": "来源"},
    )

    assert _validate_candidate_batch([candidate]) == set()


def test_dynamic_import_batches_respect_token_and_record_limits() -> None:
    records = [{"id": str(index), "text": "知识内容" * 120} for index in range(15)]

    batches = pack_by_tokens(records, max_records=6, target_tokens=900, envelope_tokens=100)

    assert sum(len(batch) for batch in batches) == 15
    assert max(len(batch) for batch in batches) <= 6
    assert len(batches) > 2


def test_import_batch_identity_reuses_same_input(tmp_path) -> None:
    db = _session()
    document = _document(tmp_path)
    db.add(document)
    db.flush()
    run = KnowledgeImportRun(
        public_id="run-batch",
        document_id=document.id,
        domain_code=document.domain_code,
        current_step="graph_generation",
        status="running",
        input_version="sha256:" + "a" * 64,
        artifact_manifest_json={},
        step_state_json={},
    )
    db.add(run)
    db.flush()

    first = prepare_batch(
        db, run, step="graph_relation", batch_key="relations_0000",
        payload={"pairs": [{"pair_id": "p1"}]}, model_name="model-a",
    )
    second = prepare_batch(
        db, run, step="graph_relation", batch_key="relations_0000",
        payload={"pairs": [{"pair_id": "p1"}]}, model_name="model-a",
    )

    assert first.id == second.id


def test_curriculum_graph_is_branching_and_covers_module_nodes() -> None:
    candidates = []
    for index in range(12):
        candidates.append(KnowledgeImportCandidate(
            public_id=f"k-{index}", document_id=1, domain_code="demo",
            candidate_type="knowledge_item", payload_json={
                "name": f"{index + 1}. 知识{index}",
                "category": "模块A",
                "difficulty": 1 + index // 4,
                "tags": ["module-a", f"topic-{index % 3}"],
                "content": f"知识{index}的定义、机制与应用说明。",
                "source_quote": f"知识{index}的定义。",
            }, source_locator_json={"chunk_id": f"chunk-{index}", "checksum": str(index)},
        ))

    deterministic, model_pairs = build_relation_plan(candidates)

    assert len(deterministic) == 11
    assert model_pairs == []
    nodes = {
        endpoint for relation in deterministic
        for endpoint in (relation["source_id"], relation["target_id"])
    }
    assert nodes == {candidate.public_id for candidate in candidates}
    outdegree = Counter(relation["source_id"] for relation in deterministic)
    assert max(outdegree.values()) <= 4
    assert all(relation["evidence_kind"] == "curriculum_rule" for relation in deterministic)


def test_only_explicit_dependency_mentions_become_fact_model_pairs() -> None:
    first = KnowledgeImportCandidate(
        public_id="a", document_id=1, domain_code="demo", candidate_type="knowledge_item",
        payload_json={
            "name": "概念A", "category": "模块A", "difficulty": 1, "tags": ["a"],
            "content": "概念A是基础定义。", "source_quote": "概念A是基础定义。",
        }, source_locator_json={"chunk_id": "ca", "checksum": "a"},
    )
    second = KnowledgeImportCandidate(
        public_id="b", document_id=1, domain_code="demo", candidate_type="knowledge_item",
        payload_json={
            "name": "概念B", "category": "模块B", "difficulty": 2, "tags": ["b"],
            "content": "概念B需要先掌握概念A，随后才能应用。", "source_quote": "概念B需要先掌握概念A。",
        }, source_locator_json={"chunk_id": "cb", "checksum": "b"},
    )

    deterministic, model_pairs = build_relation_plan([first, second])

    assert deterministic == []
    assert len(model_pairs) == 1
    assert model_pairs[0]["source_id"] == "b"
    assert model_pairs[0]["target_id"] == "a"
    assert "需要先掌握" in model_pairs[0]["evidence_spans"][0]["text"]


def test_import_input_version_fits_persisted_column(tmp_path) -> None:
    document = _document(tmp_path)
    version = _input_version(document)
    column_length = KnowledgeImportRun.__table__.c.input_version.type.length

    assert version.startswith("sha256:")
    assert len(version) == 71
    assert column_length is not None and len(version) <= column_length


def test_chunk_replacement_reuses_identical_evidence_on_retry(tmp_path, monkeypatch) -> None:
    from app.services import knowledge_document_service

    monkeypatch.setattr(knowledge_document_service, "KNOWLEDGE_STORAGE_ROOT", tmp_path)
    db = _session()
    document = _document(tmp_path)
    db.add(document)
    db.commit()
    sections = parse_document(document)
    first = replace_chunks(db, document, sections)
    db.commit()
    first_ids = [chunk.id for chunk in first]

    second = replace_chunks(db, document, parse_document(document))
    db.commit()

    assert [chunk.id for chunk in second] == first_ids
    assert len(list(db.scalars(select(KnowledgeChunk)))) == len(first_ids)


def test_relation_candidate_keeps_both_endpoint_excerpts_for_review(tmp_path) -> None:
    db = _session()
    document = _document(tmp_path)
    db.add(document)
    db.commit()
    candidates = [
        KnowledgeImportCandidate(
            public_id="source", document_id=document.id, domain_code=document.domain_code,
            candidate_type="knowledge_item",
            payload_json={"content": "来源节点的完整定义和适用条件。", "source_chunk_ids": ["chunk-a"]},
            source_locator_json={"chunk_id": "chunk-a", "checksum": "a"},
            confidence=1.0, status="pending", validation_errors_json=[],
        ),
        KnowledgeImportCandidate(
            public_id="target", document_id=document.id, domain_code=document.domain_code,
            candidate_type="knowledge_item",
            payload_json={"content": "目标节点依赖来源节点才能理解。", "source_chunk_ids": ["chunk-b"]},
            source_locator_json={"chunk_id": "chunk-b", "checksum": "b"},
            confidence=1.0, status="pending", validation_errors_json=[],
        ),
    ]
    db.add_all(candidates)
    db.commit()
    from app.services.knowledge_model_import_service import _persist_relation_records

    created = _persist_relation_records(db, document, candidates, [{
        "source_id": "source", "target_id": "target", "relation_type": "prerequisite",
        "reason": "需要先理解定义", "source_quote": "模型改写而非原文", "confidence": 0.9,
    }])

    payload = created[0].payload_json
    assert payload["source_excerpt"] == "来源节点的完整定义和适用条件。"
    assert payload["target_excerpt"] == "目标节点依赖来源节点才能理解。"
    assert payload["source_quote"] in payload["source_excerpt"]


def test_review_valid_records_are_mapped_to_accepted_ids() -> None:
    assert _adapt_validation_decision({
        "valid_records": [{"id": "relation_a", "reason": "supported"}, {"reason": "missing"}]
    }) == {"accepted_ids": ["relation_a"]}


def test_invalid_source_and_self_relation_block_approval(tmp_path, monkeypatch) -> None:
    from app.services import knowledge_document_service

    monkeypatch.setattr(knowledge_document_service, "KNOWLEDGE_STORAGE_ROOT", tmp_path)
    db = _session()
    document = _document(tmp_path)
    db.add(document)
    db.commit()
    candidates = replace_candidates(db, document, parse_document(document))
    db.commit()
    knowledge = next(item for item in candidates if item.candidate_type == "knowledge_item")
    relation = KnowledgeImportCandidate(
        public_id="kic_self", document_id=document.id, domain_code=document.domain_code,
        candidate_type="knowledge_relation", payload_json={
            "source_candidate_id": knowledge.public_id,
            "target_candidate_id": knowledge.public_id,
            "relation_type": "prerequisite",
        }, source_locator_json={}, confidence=1.0, status="pending", validation_errors_json=[],
    )
    db.add(relation)
    db.commit()
    assert validate_import(db, document.id)["invalid"] >= 1
    assert db.get(KnowledgeImportCandidate, relation.id).status == "needs_edit"


def test_approved_candidates_publish_multiple_items(tmp_path, monkeypatch) -> None:
    from app.services import knowledge_document_service

    monkeypatch.setattr(knowledge_document_service, "KNOWLEDGE_STORAGE_ROOT", tmp_path)
    db = _session()
    document = _document(tmp_path)
    db.add(document)
    db.commit()
    replace_candidates(db, document, parse_document(document))
    db.commit()
    assert validate_import(db, document.id)["invalid"] == 0
    approve_candidates(db, document)
    result = publish_approved(db, document)
    assert result == {"knowledge_items": 2, "relations": 0, "questions": 2}
    items = list(db.scalars(select(KnowledgeItem)))
    assert len(items) == 2
    assert all(item.status == "staged" and item.source_locator_json for item in items)
    assert list(db.scalars(select(DiagnosticQuestion))) == []


def test_choice_answer_and_prerequisite_cycle_are_blocked(tmp_path, monkeypatch) -> None:
    from app.services import knowledge_document_service

    monkeypatch.setattr(knowledge_document_service, "KNOWLEDGE_STORAGE_ROOT", tmp_path)
    db = _session()
    document = _document(tmp_path)
    db.add(document)
    db.commit()
    candidates = replace_candidates(db, document, parse_document(document))
    db.commit()
    knowledge = [item for item in candidates if item.candidate_type == "knowledge_item"]
    question = next(item for item in candidates if item.candidate_type == "diagnostic_question")
    question.payload_json = {
        **question.payload_json,
        "question_type": "choice",
        "options": ["A", "B"],
        "answer": "C",
    }
    db.add_all([
        KnowledgeImportCandidate(
            public_id="kic_cycle",
            document_id=document.id,
            domain_code=document.domain_code,
            candidate_type="knowledge_relation",
            payload_json={
                "source_candidate_id": knowledge[1].public_id,
                "target_candidate_id": knowledge[0].public_id,
                "relation_type": "prerequisite",
            },
            source_locator_json=knowledge[0].source_locator_json,
            confidence=0.8,
            status="pending",
            validation_errors_json=[],
        ),
        KnowledgeImportCandidate(
            public_id="kic_cycle_reverse", document_id=document.id,
            domain_code=document.domain_code, candidate_type="knowledge_relation",
            payload_json={"source_candidate_id": knowledge[0].public_id,
                          "target_candidate_id": knowledge[1].public_id,
                          "relation_type": "prerequisite"},
            source_locator_json=knowledge[0].source_locator_json,
            confidence=0.8, status="pending", validation_errors_json=[],
        ),
    ])
    db.commit()
    result = validate_import(db, document.id)
    assert result["invalid"] >= 2
    assert "选择题答案不在选项中" in question.validation_errors_json
    assert any(
        "前置关系存在环" in item.validation_errors_json
        for item in db.scalars(
            select(KnowledgeImportCandidate).where(
                KnowledgeImportCandidate.candidate_type == "knowledge_relation"
            )
        )
    )


def test_zero_choice_index_is_a_valid_answer(tmp_path, monkeypatch) -> None:
    from app.services import knowledge_document_service

    monkeypatch.setattr(knowledge_document_service, "KNOWLEDGE_STORAGE_ROOT", tmp_path)
    db = _session()
    document = _document(tmp_path)
    db.add(document)
    db.commit()
    candidates = replace_candidates(db, document, parse_document(document))
    question = next(item for item in candidates if item.candidate_type == "diagnostic_question")
    question.payload_json = {
        **question.payload_json,
        "question_type": "single_choice",
        "options": ["正确答案", "干扰项"],
        "answer": 0,
        "explanation": "第一项与来源章节一致",
    }
    db.commit()

    assert validate_import(db, document.id)["invalid"] == 0
    assert question.validation_errors_json == []


def test_partial_approval_requires_referenced_knowledge(tmp_path, monkeypatch) -> None:
    from app.services import knowledge_document_service

    monkeypatch.setattr(knowledge_document_service, "KNOWLEDGE_STORAGE_ROOT", tmp_path)
    db = _session()
    document = _document(tmp_path)
    db.add(document)
    db.commit()
    candidates = replace_candidates(db, document, parse_document(document))
    db.commit()
    assert validate_import(db, document.id)["invalid"] == 0
    question = next(item for item in candidates if item.candidate_type == "diagnostic_question")
    try:
        approve_candidates(db, document, [question.public_id])
        raise AssertionError("approval accepted without referenced knowledge candidate")
    except KnowledgeImportPublishError as exc:
        assert "引用依赖" in str(exc)


def test_name_and_definition_smoke_must_hit_imported_knowledge(tmp_path, monkeypatch) -> None:
    from app.services import knowledge_document_service

    monkeypatch.setattr(knowledge_document_service, "KNOWLEDGE_STORAGE_ROOT", tmp_path)
    db = _session()
    document = _document(tmp_path)
    db.add(document)
    db.commit()
    replace_candidates(db, document, parse_document(document))
    db.commit()
    validate_import(db, document.id)
    approve_candidates(db, document)
    publish_approved(db, document)
    target = db.scalar(
        select(KnowledgeItem)
        .where(KnowledgeItem.source_document_id == document.id)
        .order_by(KnowledgeItem.id)
    )

    class Provider:
        def embed_texts(self, texts):
            return [[1.0, 0.0] for _ in texts]

    class Collection:
        def query(self, **_kwargs):
            return {
                "metadatas": [[{"knowledge_id": target.public_id}]],
                "distances": [[0.0]],
            }

    class Client:
        def get_collection(self, **_kwargs):
            return Collection()

    class Store:
        def load(self, *_args, **_kwargs):
            return SimpleNamespace(active_collection="candidate", indexed_chunk_count=2)

    result = smoke_import_index(
        db,
        document,
        provider=Provider(),
        client=Client(),
        manifest_store=Store(),
    )
    assert result["passed"] is True
    assert result["checks"]["name"]["passed"] is True
    assert result["checks"]["definition"]["passed"] is True


def test_domain_smoke_requires_target_hit_and_domain_isolation() -> None:
    db = _session()
    target = KnowledgeItem(
        public_id="knowledge_target",
        domain_code="test_domain",
        name="目标知识",
        category="test",
        difficulty=1,
        content_md="目标知识的释义",
        source_title="test",
        status="published",
    )
    db.add(target)
    db.commit()

    class Provider:
        def embed_texts(self, texts):
            return [[1.0, 0.0] for _ in texts]

    class Collection:
        def query(self, **_kwargs):
            return {
                "metadatas": [[{
                    "knowledge_id": target.public_id,
                    "domain_code": target.domain_code,
                }]],
                "distances": [[0.0]],
            }

    class Client:
        def get_collection(self, **_kwargs):
            return Collection()

    class Store:
        def load(self, *_args, **_kwargs):
            return SimpleNamespace(active_collection="candidate", indexed_chunk_count=1)

    result = smoke_domain_index(
        db,
        "test_domain",
        provider=Provider(),
        client=Client(),
        manifest_store=Store(),
    )

    assert result["passed"] is True
    assert result["checks"]["name"]["foreign_knowledge_ids"] == []


def test_domain_smoke_rejects_cross_domain_result() -> None:
    db = _session()
    db.add(
        KnowledgeItem(
            public_id="knowledge_target",
            domain_code="test_domain",
            name="目标知识",
            category="test",
            difficulty=1,
            content_md="目标知识的释义",
            source_title="test",
            status="published",
        )
    )
    db.commit()

    class Provider:
        def embed_texts(self, texts):
            return [[1.0, 0.0] for _ in texts]

    class Collection:
        def query(self, **_kwargs):
            return {
                "metadatas": [[
                    {"knowledge_id": "knowledge_target", "domain_code": "test_domain"},
                    {"knowledge_id": "foreign", "domain_code": "other_domain"},
                ]],
                "distances": [[0.0, 0.1]],
            }

    class Client:
        def get_collection(self, **_kwargs):
            return Collection()

    class Store:
        def load(self, *_args, **_kwargs):
            return SimpleNamespace(active_collection="candidate", indexed_chunk_count=2)

    try:
        smoke_domain_index(
            db,
            "test_domain",
            provider=Provider(),
            client=Client(),
            manifest_store=Store(),
        )
        raise AssertionError("cross-domain retrieval result must be rejected")
    except KnowledgeImportPublishError as exc:
        assert "跨领域" in str(exc)
