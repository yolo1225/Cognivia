"""Frozen helpers used only while replaying historical Alembic revisions."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Iterable

from app.models import KnowledgeItem
from app.rag.candidate_chunker import CandidateChunk, chunk_knowledge_item
from app.services.knowledge_version_service import knowledge_item_content_hash as _knowledge_item_content_hash


QUESTION_CERTIFICATION_RULE_VERSION = "question-cert-v2"
_SPACE_RE = re.compile(r"\s+")


def knowledge_item_content_hash(item: KnowledgeItem) -> str:
    return _knowledge_item_content_hash(item)


def candidate_chunks_for_item(item: KnowledgeItem) -> list[CandidateChunk]:
    return chunk_knowledge_item(
        knowledge_id=item.public_id,
        name=item.name,
        category=item.category,
        difficulty=item.difficulty,
        tags=list(item.tags_json or []),
        content_md=item.content_md,
    )


def candidate_source_locator(item: KnowledgeItem, chunk: CandidateChunk) -> str:
    if item.source_document_id:
        return f"document:{item.source_document_id}#chunk={chunk.chunk_index}"
    return f"knowledge:{item.public_id}#chunk={chunk.chunk_index}"


def resolve_question_source_binding(
    item: KnowledgeItem,
    *,
    source_quote: object,
    chunks: Iterable[CandidateChunk] | None = None,
) -> dict[str, list[str] | str]:
    quote = _SPACE_RE.sub("", str(source_quote or "")).strip()
    available = list(chunks if chunks is not None else candidate_chunks_for_item(item))
    if not quote or not available:
        raise ValueError(f"legacy_question_source_unavailable:{item.public_id}")
    def rank(chunk: CandidateChunk) -> tuple[float, int, int]:
        content = _SPACE_RE.sub("", chunk.content).strip()
        match = SequenceMatcher(None, quote, content, autojunk=False).find_longest_match().size
        return (match / min(len(quote), len(content)), match, -chunk.chunk_index)
    chosen = max(available, key=rank)
    return {
        "source_ref_ids": [chosen.chunk_id],
        "source_locator": candidate_source_locator(item, chosen),
    }
