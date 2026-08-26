from __future__ import annotations

import pytest

from app.models import DiagnosticQuestion, KnowledgeItem
from app.services.question_source_binding_service import (
    QuestionSourceBindingError,
    candidate_chunks_for_item,
    resolve_question_source_binding,
    validate_question_source_binding,
)


def _document_item() -> KnowledgeItem:
    return KnowledgeItem(
        public_id="document-backed-knowledge",
        domain_code="test-domain",
        name="文档知识点",
        category="测试",
        difficulty=2,
        tags_json=["source"],
        content_md=(
            "# 基础说明\n\n"
            + "基础背景用于填充前置片段。" * 90
            + "\n\n# 精确来源\n\n"
            + "这里是题目必须引用的唯一可信事实，发布时必须定位到当前片段。" * 8
        ),
        source_title="可信文档",
        license_note="test",
        source_document_id=7,
        status="published",
    )


def test_document_question_binds_stable_chunk_id_and_document_locator() -> None:
    item = _document_item()
    chunks = candidate_chunks_for_item(item)
    source_chunk = next(chunk for chunk in chunks if "唯一可信事实" in chunk.content)

    binding = resolve_question_source_binding(
        item,
        source_quote="这里是题目必须引用的唯一可信事实，发布时必须定位到当前片段。",
        chunks=chunks,
    )

    assert binding["source_ref_ids"] == [source_chunk.chunk_id]
    assert binding["source_locator"] == (
        f"document:7#chunk={source_chunk.chunk_index}"
    )


def test_validation_rejects_locator_that_does_not_match_bound_chunk() -> None:
    item = _document_item()
    chunks = candidate_chunks_for_item(item)
    binding = resolve_question_source_binding(
        item,
        source_quote="这里是题目必须引用的唯一可信事实，发布时必须定位到当前片段。",
        chunks=chunks,
    )
    question = DiagnosticQuestion(
        public_id="question-invalid-locator",
        domain_code=item.domain_code,
        knowledge_item_id=1,
        question_type="single_choice",
        stem="测试题",
        options_json=["A", "B", "C", "D"],
        answer_key_json={
            "correct_option": 0,
            "explanation": "可信解析",
            "source_quote": "这里是题目必须引用的唯一可信事实，发布时必须定位到当前片段。",
            "source_ref_ids": binding["source_ref_ids"],
            "source_locator": "knowledge:document-backed-knowledge#chunk=0",
        },
        difficulty=2,
        status="active",
    )

    with pytest.raises(QuestionSourceBindingError, match="source_locator_invalid"):
        validate_question_source_binding(item, question, chunks)
