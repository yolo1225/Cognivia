from __future__ import annotations

import hashlib
import json
import logging
from functools import partial
from collections import defaultdict
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app.core.config import settings
from app.models import (
    DiagnosticQuestion,
    KnowledgeDocument,
    KnowledgeImportCandidate,
    KnowledgeImportRun,
    KnowledgeItem,
)
from app.rag.embedding_provider import OpenAICompatibleEmbeddingProvider
from app.rag.candidate_chunker import CHUNKER_VERSION, chunk_knowledge_item
from app.services.knowledge_import_batch_service import (
    execute_json_batch,
    pack_by_tokens,
    prepare_batch,
    run_parallel,
)
from app.services.knowledge_relation_algorithm_service import build_relation_plan
from app.services.llm_service import (
    ModelCallError,
    ModelOutputTruncatedError,
    gateway,
)
from app.services.question_certification_service import (
    canonical_knowledge_content_hash,
    certify_question_candidates,
)


logger = logging.getLogger(__name__)


class ExtractedKnowledge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    category: str
    difficulty: int = Field(ge=1, le=5)
    tags: list[str]
    content: str
    prerequisites: list[str] = []
    ability_weights: dict[str, float]
    ability_weight_confidence: float = Field(ge=0, le=1)


class ExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge: ExtractedKnowledge


class AbilityWeightDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ability_weights: dict[str, float]
    confidence: float = Field(ge=0, le=1)


class AbilityWeightOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: AbilityWeightDecision


class ValidationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted_ids: list[str]


class RelationPairDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pair_id: str
    verdict: Literal["accept", "reject"]
    relation_type: Literal["prerequisite", "depends_on", "related_to", "next_step"] | None = None
    direction: Literal["source_to_target", "target_to_source"] | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    evidence_span_ids: list[str] = []


class RelationPairOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[RelationPairDecision]


class GeneratedEvidenceQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ref_id: str
    quote: str


class GeneratedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_id: str
    # Slots are import-batch identities only. They are not a global six-question
    # template and carry no pedagogical meaning.
    question_slot: int = Field(ge=1, le=99)
    quiz_level: Literal["foundation", "improvement", "challenge"]
    question_type: Literal["single_choice", "short_answer"]
    stem: str
    options: list[str] = []
    answer: int | str
    rubric: list[str]
    explanation: str
    diagnostic_dimension: Literal["概念理解", "机制与因果", "实操场景选择", "错误诊断与修复"]
    evidence_quotes: list[GeneratedEvidenceQuote] = Field(min_length=1, max_length=3)
    difficulty: int = Field(ge=1, le=5)


def question_bank_uses_for_slot(question_slot: int) -> list[str]:
    if question_slot in {4, 5}:
        return ["mastery_validation", "mistake_consolidation"]
    return ["diagnosis", "graded_quiz"]


class QuestionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[GeneratedQuestion]


def _adapt_validation_decision(result: dict) -> dict:
    if "accepted_ids" in result:
        return {"accepted_ids": list(result.get("accepted_ids") or [])}
    records = result.get("valid_records") or []
    return {
        "accepted_ids": [
            str(record["id"])
            for record in records
            if isinstance(record, dict) and record.get("id")
        ]
    }


def _adapt_pair_decisions(result: dict) -> dict:
    raw = result.get("decisions") or result.get("relations") or result.get("pairs") or []
    decisions = []
    for value in raw:
        if not isinstance(value, dict):
            continue
        relation_type = value.get("relation_type") or value.get("relation") or value.get("type")
        verdict = value.get("verdict") or value.get("decision")
        if verdict in {True, "accepted", "valid", "yes"}:
            verdict = "accept"
        elif verdict in {False, "rejected", "invalid", "no"}:
            verdict = "reject"
        decisions.append({
            "pair_id": value.get("pair_id") or value.get("id"),
            "verdict": verdict or ("accept" if relation_type else "reject"),
            "relation_type": relation_type,
            "direction": value.get("direction"),
            "confidence": value.get("confidence", 0.75),
            "evidence_span_ids": value.get("evidence_span_ids") or value.get("evidence_ids") or [],
        })
    return {"decisions": decisions}


def _adapt_question_output(result: object) -> dict:
    """Normalize provider question payloads without assuming an object wrapper.

    Some OpenAI-compatible providers return the requested array directly even
    when the prompt asks for ``{"questions": [...]}``. Treat that as a valid
    candidate payload and let the existing deterministic field validation apply.
    """
    if isinstance(result, list):
        raw = result
    elif isinstance(result, dict):
        raw = result.get("questions") or result.get("items") or []
    else:
        raw = []
    questions = []
    next_slot_by_knowledge: dict[str, int] = {}
    for value in raw:
        if not isinstance(value, dict):
            continue
        item = dict(value)
        knowledge_id = item.get("knowledge_id") or item.get("knowledge_candidate_id")
        stem = item.get("stem") or item.get("question") or item.get("question_text")
        question_type = item.get("question_type") or item.get("type")
        question_type = {
            "choice": "single_choice",
            "multiple_choice": "single_choice",
            "single-choice": "single_choice",
            "short": "short_answer",
            "short-answer": "short_answer",
        }.get(str(question_type), question_type)
        options = item.get("options") or []
        answer = item.get("answer")
        rubric = item.get("rubric") or item.get("scoring_points") or []
        if isinstance(rubric, str):
            rubric = [rubric]
        if question_type == "short_answer" and isinstance(answer, list):
            answer_parts = [str(part).strip() for part in answer if str(part).strip()]
            answer = "；".join(answer_parts)
            rubric = rubric or answer_parts[:4]
        if question_type == "short_answer" and answer is None and rubric:
            answer = "；".join(str(part).strip() for part in rubric if str(part).strip())
        if question_type == "single_choice" and isinstance(answer, str):
            normalized = answer.strip()
            if normalized.upper() in {"A", "B", "C", "D"}:
                answer = ord(normalized.upper()) - ord("A")
            elif normalized in options:
                answer = options.index(normalized)
            elif normalized.isdigit():
                answer = int(normalized)
        if not knowledge_id or not stem or question_type not in {
            "single_choice", "short_answer"
        }:
            continue
        knowledge_id = str(knowledge_id)
        fallback_slot = next_slot_by_knowledge.get(knowledge_id, 1)
        try:
            question_slot = int(item.get("question_slot") or item.get("slot") or fallback_slot)
        except (TypeError, ValueError):
            question_slot = fallback_slot
        next_slot_by_knowledge[knowledge_id] = max(fallback_slot, question_slot) + 1
        if not 1 <= question_slot <= 99:
            continue
        if question_type == "short_answer" and not isinstance(answer, str):
            continue
        if question_type == "single_choice" and not isinstance(answer, int):
            continue
        if not rubric:
            rubric = [str(answer)]
        dimension = item.get("diagnostic_dimension") or item.get("dimension")
        dimension = {
            "concept": "概念理解",
            "mechanism": "机制与因果",
            "scenario": "实操场景选择",
            "troubleshooting": "错误诊断与修复",
        }.get(str(dimension), dimension)
        if dimension not in {"概念理解", "机制与因果", "实操场景选择", "错误诊断与修复"}:
            dimension = "概念理解"
        quiz_level = str(item.get("quiz_level") or item.get("level") or "")
        if quiz_level not in {"foundation", "improvement", "challenge"}:
            quiz_level = "foundation"
        try:
            difficulty = int(item.get("difficulty") or 0)
        except (TypeError, ValueError):
            difficulty = 0
        if not 1 <= difficulty <= 5:
            difficulty = {"foundation": 2, "improvement": 3, "challenge": 4}[quiz_level]
        explanation = item.get("explanation") or item.get("analysis")
        if not explanation:
            explanation = str(answer or "依据给定来源摘录作答")
        questions.append({
            "knowledge_id": knowledge_id,
            "question_slot": question_slot,
            "quiz_level": quiz_level,
            "question_type": question_type,
            "stem": str(stem),
            "options": options,
            "answer": answer,
            "rubric": rubric,
            "explanation": str(explanation),
            "diagnostic_dimension": dimension,
            "difficulty": difficulty,
            "evidence_quotes": [
                (
                    {
                        "source_ref_id": value.get("source_ref_id")
                        or value.get("chunk_id")
                        or value.get("source_id")
                        or "",
                        "quote": value.get("quote")
                        or value.get("text")
                        or value.get("evidence")
                        or "",
                    }
                    if isinstance(value, dict)
                    else {
                        "source_ref_id": item.get("source_ref_id") or "",
                        "quote": value,
                    }
                )
                for value in (
                    item.get("evidence_quotes")
                    or ([item.get("evidence_quote")] if item.get("evidence_quote") else [])
                )
            ],
        })
    return {"questions": questions}


def enrich_unstructured_sections(sections: list[dict]) -> list[dict]:
    enriched: list[dict] = []
    for index, section in enumerate(sections):
        result, _ = gateway.complete_json(
            model=settings.primary_llm_model,
            system_prompt=(
                "你是领域知识抽取器。只能依据输入原文抽取一个主要知识点，不补充外部事实。"
                "name 使用清晰中文名称，content 保留来源可支持的完整说明。"
                "同时输出 theory、practice、problem_solving、knowledge_breadth、learning_speed "
                "五维权重；前四维之和必须为1，learning_speed必须为0，并给出置信度。"
            ),
            payload={"heading_path": section["heading_path"], "content": section["text"]},
            response_model=ExtractionOutput,
            max_output_tokens=1800,
        )
        knowledge = result["knowledge"]
        section = dict(section)
        section["heading_path"] = [str(knowledge["name"])]
        section["text"] = str(knowledge["content"])
        section["checksum"] = hashlib.sha256(section["text"].encode()).hexdigest()
        section["metadata"] = {
            "knowledge_id": f"generated_{index}_{section['checksum'][:12]}",
            "category": knowledge["category"],
            "difficulty": knowledge["difficulty"],
            "tags": knowledge["tags"],
            "prerequisites": knowledge.get("prerequisites") or [],
            "ability_weights": knowledge.get("ability_weights"),
            "ability_weight_source": "model",
            "ability_weight_confidence": knowledge.get("ability_weight_confidence", 0.0),
        }
        enriched.append(section)
    return enriched


def complete_candidate_ability_weights(
    candidates: list[KnowledgeImportCandidate],
) -> None:
    """Fill only missing weights; explicit package data always wins."""
    from app.services.ability_weight_service import normalize_ability_weights

    for candidate in candidates:
        if candidate.candidate_type != "knowledge_item":
            continue
        payload = dict(candidate.payload_json or {})
        if normalize_ability_weights(payload.get("ability_weights")) is not None:
            continue
        try:
            result, _ = gateway.complete_json(
                model=settings.primary_llm_model,
                system_prompt=(
                    "你是跨领域教学能力映射器。只根据给定知识内容判断学习证据主要支持的能力。"
                    "输出 theory、practice、problem_solving、knowledge_breadth、learning_speed 五个权重。"
                    "前四项非负且之和必须为1，learning_speed必须为0。不得使用领域外知识。"
                ),
                payload={
                    "name": payload.get("name"),
                    "category": payload.get("category"),
                    "difficulty": payload.get("difficulty"),
                    "evidence_capabilities": payload.get("evidence_capabilities") or [],
                    "content": str(payload.get("content") or "")[:5000],
                },
                response_model=AbilityWeightOutput,
                max_output_tokens=600,
            )
            decision = result["result"]
            weights = normalize_ability_weights(decision.get("ability_weights"))
            if weights is None:
                continue
            payload["ability_weights"] = weights
            payload["ability_weight_source"] = "model"
            payload["ability_weight_confidence"] = float(decision.get("confidence") or 0.0)
            candidate.payload_json = payload
        except (ModelCallError, ModelOutputTruncatedError, ValueError, KeyError, TypeError):
            logger.warning(
                "knowledge ability weight generation failed",
                extra={"candidate_id": candidate.public_id},
                exc_info=True,
            )


def _persist_relation_records(
    db: Session,
    document: KnowledgeDocument,
    knowledge: list[KnowledgeImportCandidate],
    records: list[dict],
    *,
    repair_round: int = 0,
) -> list[KnowledgeImportCandidate]:
    payloads = {item.public_id: item.payload_json or {} for item in knowledge}
    valid_ids = set(payloads)
    existing = {
        (
            str((item.payload_json or {}).get("source_candidate_id")),
            str((item.payload_json or {}).get("target_candidate_id")),
            str((item.payload_json or {}).get("relation_type")),
        )
        for item in db.query(KnowledgeImportCandidate).filter(
            KnowledgeImportCandidate.document_id == document.id,
            KnowledgeImportCandidate.candidate_type == "knowledge_relation",
        )
    }
    created = []
    for relation in records:
        if relation["source_id"] not in valid_ids or relation["target_id"] not in valid_ids:
            continue
        key = (relation["source_id"], relation["target_id"], relation["relation_type"])
        if key in existing or relation["source_id"] == relation["target_id"] or float(relation["confidence"]) < 0.7:
            continue
        source_text = str(payloads[relation["source_id"]].get("content") or "")
        target_text = str(payloads[relation["target_id"]].get("content") or "")
        source_excerpt = source_text[:500]
        target_excerpt = target_text[:500]
        source_quote = str(relation.get("source_quote") or "").strip()
        if source_quote not in f"{source_text}\n{target_text}":
            source_quote = source_excerpt[:300] or target_excerpt[:300]
        stable = hashlib.sha256(
            f"{document.public_id}:{relation['source_id']}:{relation['target_id']}:{relation['relation_type']}".encode()
        ).hexdigest()[:16]
        candidate = KnowledgeImportCandidate(
            public_id=f"kic_{stable}", document_id=document.id, domain_code=document.domain_code,
            candidate_type="knowledge_relation", payload_json={
                "source_candidate_id": relation["source_id"],
                "target_candidate_id": relation["target_id"],
                "relation_type": relation["relation_type"],
                "reason": relation["reason"],
                "source_quote": source_quote,
                "source_excerpt": source_excerpt,
                "target_excerpt": target_excerpt,
                "model_quote": relation.get("source_quote"),
                "generation_method": relation.get("generation_method") or (
                    "model_repair" if repair_round else "model"
                ),
                "repair_round": repair_round,
                "evidence_kind": relation.get("evidence_kind", "text_quote"),
                "score_components": relation.get("score_components") or {},
                "review_verdict": relation.get("review_verdict"),
            }, source_locator_json={
                "chunk_id": (payloads[relation["source_id"]].get("source_chunk_ids") or [None])[0],
                "checksum": payloads[relation["source_id"]].get("after_checksum"),
            }, confidence=float(relation["confidence"]),
            status="pending", validation_errors_json=[],
        )
        db.add(candidate)
        created.append(candidate)
        existing.add(key)
    db.flush()
    return created


def generate_model_relations(
    db: Session,
    document: KnowledgeDocument,
    candidates: list[KnowledgeImportCandidate],
    run: KnowledgeImportRun,
) -> list[KnowledgeImportCandidate]:
    knowledge = [item for item in candidates if item.candidate_type == "knowledge_item"]
    vectors: dict[str, list[float]] = {}
    try:
        texts = [
            f"{(item.payload_json or {}).get('name', '')}\n"
            f"{str((item.payload_json or {}).get('content') or '')[:700]}"
            for item in knowledge
        ]
        embedded = OpenAICompatibleEmbeddingProvider().embed_texts(texts)
        vectors = {
            item.public_id: list(vector)
            for item, vector in zip(knowledge, embedded, strict=True)
        }
    except Exception:
        logger.warning(
            "knowledge relation embedding recall unavailable; using lexical fallback",
            exc_info=True,
        )

    deterministic, fact_pairs = build_relation_plan(knowledge, vectors=vectors)
    records = [
        {**record, "generation_method": "curriculum_rule"}
        for record in deterministic
    ]
    pair_batches = pack_by_tokens(fact_pairs, max_records=32, envelope_tokens=1200)
    prepared: list[tuple[int, list[dict]]] = []
    model_name = settings.primary_llm_model
    for index, batch in enumerate(pair_batches):
        payload = {"pairs": batch}
        model_batch = prepare_batch(
            db,
            run,
            step="graph_relation",
            batch_key=f"relations_{index:04d}",
            payload=payload,
            model_name=model_name,
        )
        prepared.append((model_batch.id, batch))
    db.commit()

    jobs = [
        partial(
            execute_json_batch,
            batch_id,
            model=model_name,
            system_prompt=(
                "你是课程关系判定器。每个 pair 已提供精确证据片段。仅当片段明确支持依赖、前置、"
                "后继或语义相关时接受；不得使用外部常识补证。只返回 pair_id、accept/reject、关系类型、"
                "方向、置信度和 evidence_span_ids。prerequisite 表示 source 是 target 的前置；"
                "depends_on 表示 source 依赖 target；next_step 是教学推荐；related_to 不参与路径。"
            ),
            payload={"pairs": batch},
            response_model=RelationPairOutput,
            response_adapter=_adapt_pair_decisions,
            max_output_tokens=1800,
            role="generation",
        )
        for batch_id, batch in prepared
    ]
    results = run_parallel(
        jobs, max_workers=settings.knowledge_import_generation_concurrency
    )
    pair_map = {pair["pair_id"]: pair for pair in fact_pairs}
    for result in results:
        if not isinstance(result, dict):
            continue
        for decision in result.get("decisions") or []:
            if (
                decision.get("verdict") != "accept"
                or float(decision.get("confidence") or 0) < 0.7
            ):
                continue
            pair = pair_map.get(str(decision.get("pair_id")))
            if pair is None or not decision.get("relation_type"):
                continue
            source_id, target_id = pair["source_id"], pair["target_id"]
            if decision.get("direction") == "target_to_source":
                source_id, target_id = target_id, source_id
            span_ids = set(decision.get("evidence_span_ids") or [])
            quote = next(
                (
                    span["text"]
                    for span in pair["evidence_spans"]
                    if span["id"] in span_ids
                ),
                "",
            )
            if not quote:
                continue
            records.append({
                "source_id": source_id,
                "target_id": target_id,
                "relation_type": decision["relation_type"],
                "reason": "模型根据原文中的显式依赖表达完成关系判定",
                "source_quote": quote,
                "confidence": float(decision["confidence"]),
                "evidence_kind": "text_quote",
                "score_components": {"explicit_dependency_cue": 1.0},
                "generation_method": "model",
            })
    return _persist_relation_records(db, document, knowledge, records)


def repair_curriculum_relations(
    db: Session,
    document: KnowledgeDocument,
    candidates: list[KnowledgeImportCandidate],
    directions: list[dict[str, object]],
    focus_ids: set[str],
    repair_round: int,
) -> list[KnowledgeImportCandidate]:
    knowledge = [item for item in candidates if item.candidate_type == "knowledge_item"]
    by_id = {item.public_id: item for item in knowledge}
    tags = {
        item.public_id: {str(tag).casefold() for tag in (item.payload_json or {}).get("tags") or []}
        for item in knowledge
    }
    existing_pairs = {
        frozenset((
            str((item.payload_json or {}).get("source_candidate_id")),
            str((item.payload_json or {}).get("target_candidate_id")),
        ))
        for item in candidates if item.candidate_type == "knowledge_relation"
    }
    records: list[dict] = []
    for direction in directions:
        direction_tags = {str(value).casefold() for value in direction.get("match_tags") or []}
        node_ids = [item_id for item_id, values in tags.items() if values & direction_tags]
        node_ids.sort(key=lambda item_id: (
            int((by_id[item_id].payload_json or {}).get("difficulty") or 2),
            str((by_id[item_id].payload_json or {}).get("name") or ""),
        ))
        targeted = [item_id for item_id in node_ids if item_id in focus_ids]
        if not targeted:
            continue
        anchors = node_ids[:4]
        proposed = list(zip(anchors, anchors[1:]))
        for index, target_id in enumerate(targeted):
            if target_id in anchors or not anchors:
                continue
            proposed.append((anchors[index % len(anchors)], target_id))
        for source_id, target_id in proposed:
            pair = frozenset((source_id, target_id))
            if source_id == target_id or pair in existing_pairs:
                continue
            source_payload = by_id[source_id].payload_json or {}
            records.append({
                "source_id": source_id,
                "target_id": target_id,
                "relation_type": "next_step",
                "confidence": 0.72,
                "reason": f"学习方向“{direction.get('label') or direction.get('value')}”的局部路径修复",
                "source_quote": str(source_payload.get("source_quote") or "")[:300],
                "evidence_kind": "curriculum_rule",
                "score_components": {"direction_repair": 1.0},
                "generation_method": "curriculum_repair",
            })
            existing_pairs.add(pair)
    return _persist_relation_records(
        db, document, knowledge, records, repair_round=repair_round
    )


def _generate_question_records(
    db: Session,
    run: KnowledgeImportRun,
    knowledge: list[KnowledgeImportCandidate],
    *,
    step: str,
    missing_slots_by_knowledge: dict[str, list[int]] | None = None,
    existing_question_ids_by_knowledge: dict[str, list[str]] | None = None,
    related_ids_by_knowledge: dict[str, list[str]] | None = None,
    repair_fields_by_slot: dict[tuple[str, int], list[str]] | None = None,
) -> list[dict]:
    source_records: list[tuple[str, str, int, dict]] = []
    by_id = {item.public_id: item for item in knowledge}

    def projected_chunks(candidate: KnowledgeImportCandidate) -> tuple[list, str]:
        candidate_payload = candidate.payload_json or {}
        target_id = str(candidate_payload.get("target_public_id") or "")
        chunks = chunk_knowledge_item(
            knowledge_id=target_id,
            name=str(candidate_payload.get("name") or ""),
            category=str(candidate_payload.get("category") or "未分类"),
            difficulty=int(candidate_payload.get("difficulty") or 2),
            tags=[str(value) for value in candidate_payload.get("tags") or []],
            content_md=str(candidate_payload.get("content") or ""),
        )
        content_hash = canonical_knowledge_content_hash(
            knowledge_id=target_id,
            domain_code=candidate.domain_code,
            name=str(candidate_payload.get("name") or ""),
            category=str(candidate_payload.get("category") or "未分类"),
            difficulty=int(candidate_payload.get("difficulty") or 2),
            tags=[str(value) for value in candidate_payload.get("tags") or []],
            evidence_capabilities=[
                str(value)
                for value in candidate_payload.get("evidence_capabilities") or []
            ],
            content=str(candidate_payload.get("content") or ""),
            source_title=str(candidate_payload.get("source_title") or ""),
            source_url=candidate_payload.get("source_url"),
            license_note=str(candidate_payload.get("license_note") or ""),
        )
        return chunks, content_hash

    projected = {
        candidate.public_id: projected_chunks(candidate) for candidate in knowledge
    }
    for item in knowledge:
        required_slots = sorted((missing_slots_by_knowledge or {}).get(item.public_id, [1]))
        if not required_slots:
            continue
        payload = item.payload_json or {}
        for slot in required_slots:
            # Density is assigned per knowledge item.  Only central items receive
            # later slots, whose evidence budget permits genuinely integrated work.
            tier = "foundation" if slot == 1 else "improvement" if slot == 2 else "challenge"
            related_limit = 0 if tier == "foundation" else 1 if tier == "improvement" else 2
            related_ids = [
                candidate_id
                for candidate_id in (related_ids_by_knowledge or {}).get(item.public_id, [])
                if candidate_id in by_id
            ][:related_limit]
            source_candidate_ids = [item.public_id, *related_ids]
            source_chunks: list[dict[str, object]] = []
            for source_index, candidate_id in enumerate(source_candidate_ids):
                source_candidate = by_id[candidate_id]
                source_payload = source_candidate.payload_json or {}
                chunks, source_content_hash = projected[candidate_id]
                chunk = chunks[(slot - 1 + source_index) % len(chunks)]
                source_chunks.append({
                    "chunk_id": chunk.chunk_id,
                    "chunk_index": chunk.chunk_index,
                    "source_locator": (
                        f"document:{source_candidate.document_id}#chunk={chunk.chunk_index}"
                    ),
                    "knowledge_id": str(source_payload.get("target_public_id") or ""),
                    "knowledge_candidate_id": candidate_id,
                    "content": chunk.content,
                    "content_checksum": hashlib.sha256(
                        chunk.embedding_text.encode("utf-8")
                    ).hexdigest(),
                    "source_content_hash": source_content_hash,
                    "chunker_version": CHUNKER_VERSION,
                })
            source_records.append((item.public_id, tier, slot, {
                "knowledge_id": item.public_id,
                "name": payload.get("name"),
                "difficulty": int(payload.get("difficulty") or 2),
                "evidence_capabilities": payload.get("evidence_capabilities") or [],
                "source_chunks": source_chunks,
                "required_question_slots": [slot],
                "required_question_type": "single_choice",
                "existing_question_ids": (existing_question_ids_by_knowledge or {}).get(
                    item.public_id, []
                ),
                "certification_failed_fields": (repair_fields_by_slot or {}).get(
                    (item.public_id, slot), []
                ),
            }))
    prepared: list[tuple[int, dict]] = []
    model_name = settings.primary_llm_model
    for knowledge_id, tier, slot, record in source_records:
        payload = {"knowledge": [record]}
        payload_hash = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()[:10]
        model_batch = prepare_batch(
            db,
            run,
            step=step,
            batch_key=f"questions_{knowledge_id}_{tier}_{slot}_{payload_hash}"[:128],
            payload=payload,
            model_name=model_name,
        )
        prepared.append((model_batch.id, record))
    db.commit()
    jobs = [
        partial(
            execute_json_batch,
            batch_id,
            model=model_name,
            system_prompt=(
                "你是正式题库生成器。只生成每个 knowledge 记录中 required_question_slots 指定的本批次题目；"
                "题槽仅用于幂等去重，不代表固定的题型、层级或全局六题模板。不得考查标题记忆，只能使用 source_chunks，"
                "不得补充外部事实。基础题只使用给定的主知识点 Chunk；提升题可综合1到2个给定 Chunk；"
                "挑战题可综合1到3个给定 Chunk。每题必须返回 evidence_quotes，包含1到3个"
                "{source_ref_id, quote}对象；quote 必须来自对应 source_ref_id 的 Chunk content，"
                "且可在规范化空白后连续精确匹配，禁止跨 Chunk 拼接。单选题必须有四个同层次"
                "且仅一个正确的选项，answer使用从0开始的索引。每个槽位必须返回一道"
                "single_choice，rubric必须返回空数组；不得返回简答题或空 questions 数组。"
                "difficulty必须按题目实际认知操作标注1到5，"
                "不得因教学层级直接抬高难度。已有题目 ID 仅用于去重。只有包含"
                "题槽1至3用于诊断和分阶测验，题槽4至5专用于掌握验证和错题巩固；不同题槽必须使用"
                "不同情境或认知操作，不能只替换措辞。"
                "operation或troubleshooting证据能力时才能生成实操或排错题。"
                "questions 数组的题槽集合必须与 required_question_slots 完全一致；证据不足以支撑提升或挑战题时，"
                "降低认知复杂度并基于当前 Chunk 生成不同情境的可判分单选题，不得伪造外部事实或省略题目。"
                "若 certification_failed_fields 非空，必须只针对这些失败字段修正，同时保持题目仍由"
                "当前 source_chunks 和精确引文支持。"
            ),
            payload={"knowledge": [record]},
            response_model=QuestionOutput,
            response_adapter=_adapt_question_output,
            max_output_tokens=2800,
            role="generation",
            expected_question_slots=list(record["required_question_slots"]),
        )
        for batch_id, record in prepared
    ]
    results = run_parallel(
        jobs, max_workers=settings.knowledge_import_generation_concurrency
    )
    output: list[dict] = []
    for result, (_, _, _, record) in zip(results, source_records, strict=True):
        if not isinstance(result, dict):
            continue
        source_chunks = [dict(value) for value in record["source_chunks"]]
        for question in result.get("questions") or []:
            if question.get("question_type") != record["required_question_type"]:
                continue
            output.append({**question, **{
                "source_chunks": source_chunks,
                "related_knowledge_candidate_ids": [
                    str(value["knowledge_candidate_id"])
                    for value in source_chunks[1:]
                ],
            }})
    return output


def _persist_questions(
    db: Session,
    document: KnowledgeDocument,
    knowledge: list[KnowledgeImportCandidate],
    records: list[dict],
) -> list[KnowledgeImportCandidate]:
    by_id = {item.public_id: item for item in knowledge}
    created: list[KnowledgeImportCandidate] = []
    seen: set[tuple[str, int]] = set()
    existing_public_ids = set(
        db.scalars(
            select(KnowledgeImportCandidate.public_id).where(
                KnowledgeImportCandidate.document_id == document.id,
                KnowledgeImportCandidate.candidate_type == "diagnostic_question",
            )
        )
    )
    for record in records:
        knowledge_id = str(record.get("knowledge_id") or "")
        item = by_id.get(knowledge_id)
        try:
            question_slot = int(record.get("question_slot") or 0)
        except (TypeError, ValueError):
            question_slot = 0
        key = (knowledge_id, question_slot)
        if item is None or not 1 <= question_slot <= 99 or key in seen:
            continue
        payload = item.payload_json or {}
        evidence_quotes = [
            {
                "source_ref_id": str(value.get("source_ref_id") or ""),
                "quote": str(value.get("quote") or "").strip(),
            }
            for value in record.get("evidence_quotes") or []
            if isinstance(value, dict) and str(value.get("quote") or "").strip()
        ]
        source_chunks = [dict(value) for value in record.get("source_chunks") or []]
        source_ref_ids = [str(value.get("chunk_id") or "") for value in source_chunks]
        source_hashes = {
            str(value.get("chunk_id") or ""): str(value.get("source_content_hash") or "")
            for value in source_chunks
        }
        aggregate_source_hash = "sha256:" + hashlib.sha256(
            json.dumps(source_hashes, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        question_type = str(record.get("question_type") or "")
        options = [str(value).strip() for value in record.get("options") or []]
        answer = record.get("answer")
        rubric = [str(value).strip() for value in record.get("rubric") or [] if str(value).strip()]
        explanation = str(record.get("explanation") or "").strip()
        if (
            not evidence_quotes
            or question_type not in {"single_choice", "short_answer"}
            or not explanation
        ):
            continue
        if question_type == "single_choice" and (
            len(options) != 4
            or len(set(options)) != 4
            or not isinstance(answer, int)
            or not 0 <= answer < 4
        ):
            continue
        if question_type == "short_answer" and (
            not isinstance(answer, str) or not answer.strip() or not 2 <= len(rubric) <= 8
        ):
            continue
        stable = hashlib.sha256(
            f"{document.public_id}:diagnostic_question:{knowledge_id}:{question_slot}".encode()
        ).hexdigest()[:16]
        public_id = f"kic_{stable}"
        if public_id in existing_public_ids:
            continue
        candidate = KnowledgeImportCandidate(
            public_id=public_id,
            document_id=document.id,
            domain_code=document.domain_code,
            candidate_type="diagnostic_question",
            payload_json={
                "knowledge_candidate_id": knowledge_id,
                "question_slot": question_slot,
                "question_bank_uses": question_bank_uses_for_slot(question_slot),
                "quiz_level": record.get("quiz_level"),
                "question_type": question_type,
                "stem": str(record.get("stem") or "").strip(),
                "options": options,
                "answer": answer,
                "rubric": rubric,
                "explanation": explanation,
                "difficulty": int(record.get("difficulty") or payload.get("difficulty") or 2),
                "diagnostic_dimension": record.get("diagnostic_dimension"),
                "source_quote": evidence_quotes[0]["quote"],
                "evidence_quotes": evidence_quotes,
                "source_ref_ids": source_ref_ids,
                "source_chunks": source_chunks,
                "source_content_hash": aggregate_source_hash,
                "source_content_hashes": source_hashes,
                "chunker_version": CHUNKER_VERSION,
                "related_knowledge_candidate_ids": record.get(
                    "related_knowledge_candidate_ids"
                ) or [],
                "certification_status": "pending",
                "generation_method": "model_single_chunk_grounded",
            },
            source_locator_json={
                "chunk_ids": source_ref_ids,
                "locators": [value.get("source_locator") for value in source_chunks],
                "checksum": aggregate_source_hash,
            },
            confidence=0.8,
            status="pending",
            validation_errors_json=[],
        )
        db.add(candidate)
        created.append(candidate)
        seen.add(key)
        existing_public_ids.add(public_id)
    db.flush()
    return created


def generate_model_questions(
    db: Session,
    document: KnowledgeDocument,
    candidates: list[KnowledgeImportCandidate],
    run: KnowledgeImportRun,
    *,
    certification_started: Callable[[], None] | None = None,
) -> list[KnowledgeImportCandidate]:
    knowledge = [item for item in candidates if item.candidate_type == "knowledge_item"]
    generated: list[KnowledgeImportCandidate] = []
    for item in list(candidates):
        if item.candidate_type == "diagnostic_question":
            db.delete(item)
            candidates.remove(item)
    db.flush()
    degree = {item.public_id: 0 for item in knowledge}
    related: dict[str, set[str]] = defaultdict(set)
    for relation in candidates:
        if relation.candidate_type != "knowledge_relation":
            continue
        relation_payload = relation.payload_json or {}
        for key in ("source_candidate_id", "target_candidate_id"):
            candidate_id = str(relation_payload.get(key) or "")
            if candidate_id in degree:
                degree[candidate_id] += 1
        source_id = str(relation_payload.get("source_candidate_id") or "")
        target_id = str(relation_payload.get("target_candidate_id") or "")
        if source_id in degree and target_id in degree and source_id != target_id:
            related[source_id].add(target_id)
            related[target_id].add(source_id)
    related_ids_by_knowledge = {
        knowledge_id: sorted(values, key=lambda value: (-degree[value], value))
        for knowledge_id, values in related.items()
    }
    ordered = sorted(
        knowledge,
        key=lambda item: (-degree[item.public_id], item.public_id),
    )
    # Slots 1-3 are the formal quiz pool; slots 4-5 are an isolated validation
    # reserve. This density is a publish-readiness invariant for every item.
    target_slots: dict[str, set[int]] = {
        item.public_id: {1, 2, 3, 4, 5} for item in ordered
    }
    existing_slots: dict[str, set[int]] = defaultdict(set)
    existing_ids: dict[str, list[str]] = defaultdict(list)
    target_id_by_candidate = {
        str((item.payload_json or {}).get("target_public_id") or ""): item.public_id
        for item in knowledge
    }
    published_rows = list(
        db.execute(
            select(DiagnosticQuestion, KnowledgeItem.public_id)
            .join(KnowledgeItem, KnowledgeItem.id == DiagnosticQuestion.knowledge_item_id)
            .where(
                DiagnosticQuestion.domain_code == document.domain_code,
                DiagnosticQuestion.status == "active",
                DiagnosticQuestion.certification_status == "certified",
                KnowledgeItem.public_id.in_(target_id_by_candidate),
            )
            .order_by(DiagnosticQuestion.id)
        )
    )
    for question, public_knowledge_id in published_rows:
        candidate_id = target_id_by_candidate.get(public_knowledge_id)
        if not candidate_id:
            continue
        answer_key = question.answer_key_json or {}
        uses = set(answer_key.get("question_bank_uses") or ["diagnosis", "graded_quiz"])
        allowed_slots = [4, 5] if "mastery_validation" in uses else [1, 2, 3]
        declared_slot = int(answer_key.get("question_slot") or 0)
        slot = declared_slot if declared_slot in allowed_slots else next(
            (value for value in allowed_slots if value not in existing_slots[candidate_id]),
            0,
        )
        if slot:
            existing_slots[candidate_id].add(slot)
        existing_ids[candidate_id].append(question.public_id)
    for item in generated:
        payload = item.payload_json or {}
        knowledge_id = str(payload.get("knowledge_candidate_id") or "")
        existing_slots.setdefault(knowledge_id, set()).add(
            int(payload.get("question_slot") or 0)
        )
        existing_ids.setdefault(knowledge_id, []).append(item.public_id)
    initial_missing = {
        item.public_id: sorted(target_slots[item.public_id] - existing_slots.get(item.public_id, set()))
        for item in knowledge
    }
    initial_records = _generate_question_records(
        db,
        run,
        knowledge,
        step="question_generation",
        missing_slots_by_knowledge=initial_missing,
        existing_question_ids_by_knowledge=existing_ids,
        related_ids_by_knowledge=related_ids_by_knowledge,
    )
    # Persist and review only newly returned records. Empty batches are already
    # marked failed by execute_json_batch and are intentionally not retried as a
    # full six-question request.
    initial_created = _persist_questions(db, document, knowledge, initial_records)
    generated.extend(initial_created)
    if certification_started is not None:
        certification_started()
    accepted, certification_failures = certify_question_candidates(
        db, run, initial_created, round_number=0
    )
    repair_fields_by_slot: dict[tuple[str, int], list[str]] = {}
    for item in list(initial_created):
        if item.public_id not in accepted:
            payload = item.payload_json or {}
            repair_fields_by_slot[
                (
                    str(payload.get("knowledge_candidate_id") or ""),
                    int(payload.get("question_slot") or 0),
                )
            ] = certification_failures.get(item.public_id, [])
            db.delete(item)
            generated.remove(item)
    db.flush()

    stalled_knowledge: set[str] = set()
    for repair_round in range(1, 3):
        slots_by_knowledge: dict[str, set[int]] = {}
        ids_by_knowledge: dict[str, list[str]] = {}
        for item in generated:
            payload = item.payload_json or {}
            knowledge_id = str(payload.get("knowledge_candidate_id") or "")
            slots_by_knowledge.setdefault(knowledge_id, set()).add(
                int(payload.get("question_slot") or 0)
            )
            ids_by_knowledge.setdefault(knowledge_id, []).append(item.public_id)
        missing = [
            item
            for item in knowledge
            if item.public_id not in stalled_knowledge
            and not target_slots[item.public_id].issubset(
                slots_by_knowledge.get(item.public_id, set())
            )
        ]
        if not missing:
            break
        missing_slots = {
            item.public_id: sorted(
                target_slots[item.public_id] - slots_by_knowledge.get(item.public_id, set())
            )
            for item in missing
        }
        repaired = _persist_questions(
            db,
            document,
            missing,
            _generate_question_records(
                db,
                run,
                missing,
                step=f"question_repair_{repair_round}",
                missing_slots_by_knowledge=missing_slots,
                existing_question_ids_by_knowledge=ids_by_knowledge,
                related_ids_by_knowledge=related_ids_by_knowledge,
                repair_fields_by_slot=repair_fields_by_slot,
            ),
        )
        accepted, repair_failures = certify_question_candidates(
            db, run, repaired, round_number=repair_round
        )
        certification_failures.update(repair_failures)
        for item in repaired:
            if item.public_id in accepted:
                generated.append(item)
            else:
                payload = item.payload_json or {}
                repair_fields_by_slot[
                    (
                        str(payload.get("knowledge_candidate_id") or ""),
                        int(payload.get("question_slot") or 0),
                    )
                ] = repair_failures.get(item.public_id, [])
                db.delete(item)
        returned_ids = {
            str((item.payload_json or {}).get("knowledge_candidate_id") or "")
            for item in repaired
            if item.public_id in accepted
        }
        stalled_knowledge.update(set(missing_slots) - returned_ids)
    run.artifact_manifest_json = {
        **(run.artifact_manifest_json or {}),
        "question_certification": {
            "rule_version": "question-cert-v1",
            "certified_count": len(generated),
            "rejected_count": len(certification_failures),
            "failed_fields": {
                question_id: fields
                for question_id, fields in list(certification_failures.items())[:20]
            },
        },
    }
    db.flush()
    return generated


def _validation_record(item: KnowledgeImportCandidate) -> dict:
    payload = item.payload_json or {}
    fields = (
        "source_candidate_id", "target_candidate_id", "relation_type", "reason",
        "source_quote", "source_excerpt", "target_excerpt", "question_type", "stem",
        "options", "answer", "rubric", "explanation",
    )
    compact_payload = {field: payload[field] for field in fields if field in payload}
    for field in ("reason", "source_quote", "source_excerpt", "target_excerpt", "explanation"):
        if field in compact_payload:
            compact_payload[field] = str(compact_payload[field])[:500]
    return {"id": item.public_id, "type": item.candidate_type, "payload": compact_payload}


def _validate_candidate_batch(batch: list[KnowledgeImportCandidate]) -> set[str]:
    try:
        result, _ = gateway.complete_json(
            model=settings.primary_review_model or settings.secondary_review_model or settings.primary_llm_model,
            system_prompt=(
                "你是独立知识导入校验器。只接受能够由 payload 中来源摘录支持、方向明确且答案唯一的记录。"
                "不得因为希望提高覆盖率而接受证据不足的关系。"
            ),
            payload={"records": [_validation_record(item) for item in batch]},
            response_model=ValidationDecision,
            response_adapter=_adapt_validation_decision,
            max_output_tokens=800 if len(batch) <= 4 else 1200,
            repair_truncated_output=False,
        )
        valid_ids = {item.public_id for item in batch}
        return set(result["accepted_ids"]) & valid_ids
    except (ModelCallError, ModelOutputTruncatedError):
        if len(batch) <= 1:
            logger.warning(
                "knowledge import candidate filtered after bounded review failure candidate_id=%s",
                batch[0].public_id,
            )
            return set()
        midpoint = len(batch) // 2
        return _validate_candidate_batch(batch[:midpoint]) | _validate_candidate_batch(batch[midpoint:])


def validate_model_candidates(
    candidates: list[KnowledgeImportCandidate],
    *,
    run: KnowledgeImportRun | None = None,
    step: str = "candidate_review",
) -> set[str]:
    reviewable = [
        item for item in candidates
        if item.candidate_type in {"knowledge_relation", "diagnostic_question"}
    ]
    if run is None:
        accepted: set[str] = set()
        for offset in range(0, len(reviewable), 12):
            accepted.update(_validate_candidate_batch(reviewable[offset : offset + 12]))
        return accepted

    records = [_validation_record(item) for item in reviewable]
    batches = pack_by_tokens(records, max_records=12, envelope_tokens=1000)
    db = object_session(run)
    if db is None:
        raise RuntimeError("knowledge import run is detached")
    prepared: list[tuple[int, list[dict]]] = []
    model_name = (
        settings.primary_review_model
        or settings.secondary_review_model
        or settings.primary_llm_model
    )
    for index, batch in enumerate(batches):
        payload = {"records": batch}
        model_batch = prepare_batch(
            db,
            run,
            step=step,
            batch_key=f"review_{index:04d}",
            payload=payload,
            model_name=model_name,
        )
        prepared.append((model_batch.id, batch))
    db.commit()
    jobs = [
        partial(
            execute_json_batch,
            batch_id,
            model=model_name,
            system_prompt=(
                "你是独立知识导入校验器。只接受能够由 payload 中来源摘录支持、方向明确且答案唯一的记录。"
                "选择题必须只有一个正确选项，简答题评分点必须能从来源判断；不得为了提高覆盖率接受"
                "证据不足的关系或只考标题记忆的题。只返回 accepted_ids。"
            ),
            payload={"records": batch},
            response_model=ValidationDecision,
            response_adapter=_adapt_validation_decision,
            max_output_tokens=1200,
            role="review",
        )
        for batch_id, batch in prepared
    ]
    results = run_parallel(jobs, max_workers=settings.knowledge_import_review_concurrency)
    valid_ids = {item.public_id for item in reviewable}
    accepted: set[str] = set()
    for result in results:
        if not isinstance(result, dict):
            continue
        accepted.update(str(value) for value in result.get("accepted_ids") or [])
    return accepted & valid_ids
