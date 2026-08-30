from __future__ import annotations

import hashlib
import logging
import re
from functools import partial
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app.core.config import settings
from app.models import (
    KnowledgeDocument,
    KnowledgeImportCandidate,
    KnowledgeImportRun,
    KnowledgeItem,
)
from app.rag.embedding_provider import OpenAICompatibleEmbeddingProvider
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


logger = logging.getLogger(__name__)
_DEPENDENCY_CUES = ("需要先", "前提", "基于", "依赖", "建立在", "掌握后", "理解后")


def _explicit_dependency_sentence(text: str, name: str) -> str | None:
    for sentence in re.split(r"(?<=[。！？!?；;])\s*", text):
        if name and name.casefold() in sentence.casefold() and any(cue in sentence for cue in _DEPENDENCY_CUES):
            return sentence.strip()[:300]
    return None


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


def generate_cross_document_relations(
    db: Session,
    document: KnowledgeDocument,
    candidates: list[KnowledgeImportCandidate],
) -> list[KnowledgeImportCandidate]:
    """Propose only evidence-backed links from an import delta to existing nodes.

    These are deliberately local candidates, not a domain-wide regeneration:
    explicit dependency language wins; shared tags provide a low-confidence
    `related_to` bridge when no dependency is asserted in the new source.
    """
    incoming = [item for item in candidates if item.candidate_type == "knowledge_item"]
    existing = list(
        db.scalars(
            select(KnowledgeItem).where(
                KnowledgeItem.domain_code == document.domain_code,
                KnowledgeItem.status == "published",
            )
        )
    )
    if not incoming or not existing:
        return []
    already = {
        (
            str((item.payload_json or {}).get("source_candidate_id") or ""),
            str((item.payload_json or {}).get("target_existing_knowledge_id") or ""),
        )
        for item in db.scalars(
            select(KnowledgeImportCandidate).where(
                KnowledgeImportCandidate.document_id == document.id,
                KnowledgeImportCandidate.candidate_type == "knowledge_relation",
            )
        )
    }
    created: list[KnowledgeImportCandidate] = []
    for candidate in incoming:
        payload = dict(candidate.payload_json or {})
        text = str(payload.get("content") or "")
        tags = {str(value).casefold() for value in payload.get("tags") or [] if str(value)}
        suggestions: list[tuple[KnowledgeItem, str, str, float, str]] = []
        for item in existing:
            name = str(item.name or "").strip()
            explicit = _explicit_dependency_sentence(text, name)
            if explicit:
                suggestions.append((item, "depends_on", explicit, 0.86, "cross_document_explicit"))
                continue
            overlap = tags & {str(value).casefold() for value in item.tags_json or [] if str(value)}
            if overlap:
                quote = str(payload.get("source_quote") or text[:280]).strip()[:300]
                suggestions.append((item, "related_to", quote, 0.72, "cross_document_retrieval"))
        for item, relation_type, quote, confidence, method in suggestions[:3]:
            key = (candidate.public_id, item.public_id)
            if key in already:
                continue
            stable = hashlib.sha256(
                f"{document.public_id}:{candidate.public_id}:{item.public_id}:{relation_type}".encode()
            ).hexdigest()[:16]
            relation = KnowledgeImportCandidate(
                public_id=f"kic_{stable}",
                document_id=document.id,
                domain_code=document.domain_code,
                candidate_type="knowledge_relation",
                payload_json={
                    "source_candidate_id": candidate.public_id,
                    "target_existing_knowledge_id": item.public_id,
                    "relation_type": relation_type,
                    "reason": "新导入知识与领域既有知识的局部关联候选",
                    "source_quote": quote,
                    "source_excerpt": text[:500],
                    "target_excerpt": item.content_md[:500],
                    "generation_method": method,
                    "evidence_kind": "text_quote" if method.endswith("explicit") else "curriculum_rule",
                    "score_components": {"tag_overlap": round(len(tags & set(item.tags_json or [])) / max(1, len(tags)), 4)},
                },
                source_locator_json={
                    "chunk_id": (payload.get("source_chunk_ids") or [None])[0],
                    "checksum": payload.get("after_checksum"),
                },
                confidence=confidence,
                status="pending",
                validation_errors_json=[],
            )
            db.add(relation)
            created.append(relation)
            already.add(key)
    db.flush()
    return created


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
        if item.candidate_type == "knowledge_relation"
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
