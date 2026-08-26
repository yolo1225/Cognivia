import hashlib
import json

from app.rag.candidate_chunker import CHUNKER_VERSION
from app.services.question_certification_service import (
    deterministic_certification_issues,
)


def _payload(*, level: str = "challenge") -> dict:
    source_chunks = [
        {
            "chunk_id": "ki_main::chunk::0",
            "chunk_index": 0,
            "knowledge_id": "ki_main",
            "knowledge_candidate_id": "candidate_main",
            "source_locator": "document:1#chunk=0",
            "source_content_hash": "sha256:" + "a" * 64,
            "chunker_version": CHUNKER_VERSION,
            "content": "主知识点说明了步骤一，并要求验证输出结果。",
        },
        {
            "chunk_id": "ki_related::chunk::1",
            "chunk_index": 1,
            "knowledge_id": "ki_related",
            "knowledge_candidate_id": "candidate_related",
            "source_locator": "document:1#chunk=1",
            "source_content_hash": "sha256:" + "b" * 64,
            "chunker_version": CHUNKER_VERSION,
            "content": "关联知识点说明异常时应先检查输入参数。",
        },
    ]
    source_hash = "sha256:" + hashlib.sha256(
        json.dumps(
            {
                value["chunk_id"]: value["source_content_hash"]
                for value in source_chunks
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return {
        "candidate_id": "question_1",
        "knowledge_id": "candidate_main",
        "quiz_level": level,
        "question_type": "single_choice",
        "stem": "执行步骤一后出现异常，首先应检查什么？",
        "options": ["输入参数", "删除索引", "跳过验证", "修改领域"],
        "answer": 0,
        "rubric": [],
        "explanation": "来源要求异常时先检查输入参数。",
        "difficulty": 4,
        "source_chunks": source_chunks,
        "related_knowledge_candidate_ids": ["candidate_related"],
        "source_content_hash": source_hash,
        "evidence_quotes": [
            {
                "source_ref_id": "ki_main::chunk::0",
                "quote": "步骤一，并要求验证输出结果",
            },
            {
                "source_ref_id": "ki_related::chunk::1",
                "quote": "异常时应先检查输入参数",
            },
        ],
    }


def test_accepts_multi_chunk_challenge_with_explicit_quote_bindings() -> None:
    assert deterministic_certification_issues(_payload()) == []


def test_rejects_quote_bound_to_the_wrong_chunk() -> None:
    payload = _payload()
    payload["evidence_quotes"][1]["source_ref_id"] = "ki_main::chunk::0"

    issues = deterministic_certification_issues(payload)

    assert issues[0].fields == ["evidence_quotes"]


def test_rejects_cross_chunk_concatenated_quote() -> None:
    payload = _payload()
    payload["evidence_quotes"] = [
        {
            "source_ref_id": "ki_main::chunk::0",
            "quote": "验证输出结果异常时应先检查输入参数",
        }
    ]

    issues = deterministic_certification_issues(payload)

    assert issues[0].fields == ["evidence_quotes"]


def test_foundation_question_cannot_bind_multiple_chunks() -> None:
    issues = deterministic_certification_issues(_payload(level="foundation"))

    assert "source_chunks" in issues[0].fields


def test_rejects_source_hash_or_chunker_version_change() -> None:
    payload = _payload()
    payload["source_content_hash"] = "not-a-hash"
    payload["source_chunks"][0]["chunker_version"] = "old-chunker"

    issues = deterministic_certification_issues(payload)

    assert "source_content_hash" in issues[0].fields
    assert "chunker_version" in issues[0].fields
