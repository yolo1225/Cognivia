from __future__ import annotations

import re
import hashlib
import json
from difflib import SequenceMatcher
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DiagnosticQuestion, KnowledgeItem
from app.rag.candidate_chunker import CHUNKER_VERSION, CandidateChunk, chunk_knowledge_item
from app.services.question_certification_service import (
    ACCEPTED_QUESTION_CERTIFICATION_RULE_VERSIONS,
    knowledge_item_content_hash,
    normalize_evidence_text,
)


MIN_SOURCE_MATCH_CHARS = 24
MIN_SOURCE_MATCH_COVERAGE = 0.5
_SPACE_RE = re.compile(r"\s+")


class QuestionSourceBindingError(ValueError):
    pass


def candidate_source_locator(item: KnowledgeItem, chunk: CandidateChunk) -> str:
    if item.source_document_id:
        return f"document:{item.source_document_id}#chunk={chunk.chunk_index}"
    return f"knowledge:{item.public_id}#chunk={chunk.chunk_index}"


def candidate_chunks_for_item(item: KnowledgeItem) -> list[CandidateChunk]:
    return chunk_knowledge_item(
        knowledge_id=item.public_id,
        name=item.name,
        category=item.category,
        difficulty=item.difficulty,
        tags=list(item.tags_json or []),
        content_md=item.content_md,
    )


def _normalized_source_text(value: object) -> str:
    return _SPACE_RE.sub("", str(value or "")).strip()


def _source_match_score(source_quote: str, chunk: CandidateChunk) -> tuple[float, int]:
    quote = _normalized_source_text(source_quote)
    content = _normalized_source_text(chunk.content)
    if not quote or not content:
        return (0.0, 0)
    if quote in content:
        return (1.0, len(quote))
    if content in quote:
        return (1.0, len(content))
    match_size = SequenceMatcher(None, quote, content, autojunk=False).find_longest_match().size
    return (match_size / min(len(quote), len(content)), match_size)


def resolve_question_source_binding(
    item: KnowledgeItem,
    *,
    source_quote: object,
    chunks: Iterable[CandidateChunk] | None = None,
) -> dict[str, list[str] | str]:
    available = list(chunks if chunks is not None else candidate_chunks_for_item(item))
    if not available:
        raise QuestionSourceBindingError(f"question_source_chunks_missing:{item.public_id}")
    quote = _normalized_source_text(source_quote)
    if not quote:
        raise QuestionSourceBindingError(f"question_source_quote_missing:{item.public_id}")
    scored = [(_source_match_score(quote, chunk), chunk) for chunk in available]
    (coverage, match_chars), chosen = max(
        scored,
        key=lambda value: (value[0][0], value[0][1], -value[1].chunk_index),
    )
    if coverage < MIN_SOURCE_MATCH_COVERAGE or match_chars < MIN_SOURCE_MATCH_CHARS:
        raise QuestionSourceBindingError(f"question_source_quote_unmatched:{item.public_id}")
    return {
        "source_ref_ids": [chosen.chunk_id],
        "source_locator": candidate_source_locator(item, chosen),
    }


def validate_question_source_binding(
    item: KnowledgeItem,
    question: DiagnosticQuestion,
    chunks: Iterable[CandidateChunk] | dict[str, list[CandidateChunk]],
) -> None:
    if isinstance(chunks, dict):
        chunks_by_knowledge = chunks
        available = {
            chunk.chunk_id: chunk
            for values in chunks.values()
            for chunk in values
        }
    else:
        values = list(chunks)
        chunks_by_knowledge = {item.public_id: values}
        available = {chunk.chunk_id: chunk for chunk in values}
    answer = dict(question.answer_key_json or {})
    source_ref_ids = [str(value) for value in answer.get("source_ref_ids") or []]
    if question.certification_status == "certified":
        if (
            not 1 <= len(source_ref_ids) <= 3
            or any(source_ref_id not in available for source_ref_id in source_ref_ids)
        ):
            raise QuestionSourceBindingError(
                f"question_source_ref_invalid:{question.public_id}"
            )
        locators = dict(answer.get("source_locators") or {})
        evidence_quotes = [
            dict(value)
            for value in answer.get("evidence_quotes") or []
            if isinstance(value, dict)
        ]
        if not 1 <= len(evidence_quotes) <= 3:
            raise QuestionSourceBindingError(
                f"question_source_quote_missing:{question.public_id}"
            )
        for source_ref_id in source_ref_ids:
            chunk = available[source_ref_id]
            chunk_item_id = chunk.knowledge_id
            if chunk_item_id not in chunks_by_knowledge:
                raise QuestionSourceBindingError(
                    f"question_source_knowledge_invalid:{question.public_id}"
                )
            expected_suffix = f"#chunk={chunk.chunk_index}"
            if not str(locators.get(source_ref_id) or "").endswith(expected_suffix):
                raise QuestionSourceBindingError(
                    f"question_source_locator_invalid:{question.public_id}"
                )
        for evidence in evidence_quotes:
            source_ref_id = str(evidence.get("source_ref_id") or "")
            chunk = available.get(source_ref_id)
            if (
                chunk is None
                or normalize_evidence_text(evidence.get("quote"))
                not in normalize_evidence_text(chunk.content)
            ):
                raise QuestionSourceBindingError(
                    f"question_source_quote_binding_mismatch:{question.public_id}"
                )
        return
    if len(source_ref_ids) != 1 or source_ref_ids[0] not in available:
        raise QuestionSourceBindingError(
            f"question_source_ref_invalid:{question.public_id}"
        )
    source_chunk = available[source_ref_ids[0]]
    expected_locator = candidate_source_locator(item, source_chunk)
    if str(answer.get("source_locator") or "") != expected_locator:
        raise QuestionSourceBindingError(
            f"question_source_locator_invalid:{question.public_id}"
        )
    resolved = resolve_question_source_binding(
        item,
        source_quote=answer.get("source_quote"),
        chunks=available.values(),
    )
    if resolved["source_ref_ids"] != source_ref_ids:
        raise QuestionSourceBindingError(
            f"question_source_quote_binding_mismatch:{question.public_id}"
        )


def bind_domain_question_sources(
    db: Session,
    *,
    domain_code: str,
    items: Iterable[KnowledgeItem] | None = None,
) -> int:
    domain_items = list(
        items
        if items is not None
        else db.scalars(
            select(KnowledgeItem)
            .where(
                KnowledgeItem.domain_code == domain_code,
                KnowledgeItem.status == "published",
            )
            .order_by(KnowledgeItem.public_id)
        )
    )
    item_by_id = {item.id: item for item in domain_items}
    if not item_by_id:
        return 0
    chunks_by_knowledge = {
        item.public_id: candidate_chunks_for_item(item) for item in domain_items
    }
    item_by_public_id = {item.public_id: item for item in domain_items}
    questions = list(
        db.scalars(
            select(DiagnosticQuestion)
            .where(
                DiagnosticQuestion.domain_code == domain_code,
                DiagnosticQuestion.status == "active",
                DiagnosticQuestion.knowledge_item_id.in_(item_by_id),
            )
            .order_by(DiagnosticQuestion.id)
        )
    )
    changed = 0
    for question in questions:
        item = item_by_id[question.knowledge_item_id]
        answer = dict(question.answer_key_json or {})
        if question.certification_status == "certified":
            try:
                validate_question_source_binding(
                    item,
                    question,
                    chunks_by_knowledge,
                )
                source_hashes = dict(answer.get("source_content_hashes") or {})
                expected_hashes = {
                    source_ref_id: knowledge_item_content_hash(
                        item_by_public_id[source_ref_id.split("::chunk::", 1)[0]]
                    )
                    for source_ref_id in answer.get("source_ref_ids") or []
                    if source_ref_id.split("::chunk::", 1)[0] in item_by_public_id
                }
                aggregate_hash = "sha256:" + hashlib.sha256(
                    json.dumps(
                        expected_hashes, sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest()
                if (
                    source_hashes != expected_hashes
                    or question.source_content_hash != aggregate_hash
                    or answer.get("chunker_version") != CHUNKER_VERSION
                    or question.certification_rule_version
                    not in ACCEPTED_QUESTION_CERTIFICATION_RULE_VERSIONS
                ):
                    raise QuestionSourceBindingError(
                        f"question_source_hash_stale:{question.public_id}"
                    )
            except QuestionSourceBindingError:
                question.certification_status = "stale"
                question.certified_at = None
                changed += 1
            continue
        binding = resolve_question_source_binding(
            item,
            source_quote=answer.get("source_quote"),
            chunks=chunks_by_knowledge[item.public_id],
        )
        if (
            answer.get("source_ref_ids") != binding["source_ref_ids"]
            or answer.get("source_locator") != binding["source_locator"]
        ):
            answer.update(binding)
            question.answer_key_json = answer
            changed += 1
    db.flush()
    return changed
