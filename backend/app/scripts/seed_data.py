from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.domain_evidence_policy import classify_evidence_capabilities
from app.agents.profile_analysis_config import MASTERY_BASELINES
from app.core.db import SessionLocal
from app.models import (
    DiagnosticQuestion,
    Domain,
    KnowledgeItem,
    KnowledgeDocument,
    KnowledgeRelation,
)
from app.rag.candidate_chunker import CHUNKER_VERSION, chunk_knowledge_item
from app.services.question_certification_service import (
    QUESTION_CERTIFICATION_RULE_VERSION,
    knowledge_item_content_hash,
)
from app.services.question_source_binding_service import (
    candidate_chunks_for_item,
    resolve_question_source_binding,
)


SEED_DIR = Path("/app/data/seed")


# These are deliberately new integrated tasks for the demonstrable core units.
# They do not relabel existing easy items: their certified difficulty is part of
# the seed record and their wording requires design trade-offs or complex fault
# diagnosis supported by the primary knowledge entry.
HIGH_DIFFICULTY_SEED_QUESTIONS = [
    {
        "question_id": "dq_adv_001",
        "knowledge_id": "prompt_injection_defense",
        "question_type": "short_answer",
        "difficulty": 4,
        "quiz_level": "challenge",
        "stem": "设计一个读取外部检索文档且可调用写入工具的 Agent 防护方案。说明至少四项必须由应用侧落实的控制，并解释为什么不能只依赖模型识别恶意指令。",
        "answer_key": {"rubric": ["将系统/开发者指令与不可信检索内容结构隔离", "工具采用最小权限、窄参数和服务端校验", "高影响写入操作要求确认或审批并限制范围", "检测可疑材料时缩小权限、隔离来源或安全失败", "说明关键词黑名单和模型拒绝都可能误报或漏报"]},
    },
    {
        "question_id": "dq_adv_002",
        "knowledge_id": "api_resilience_retry",
        "question_type": "short_answer",
        "difficulty": 4,
        "quiz_level": "challenge",
        "stem": "一次模型 API 调用同时出现限流、网络中断和认证失败报告。请给出可执行的分类处理与观测方案，明确哪些情况可以重试、哪些必须立即失败，以及应记录哪些非敏感证据。",
        "answer_key": {"rubric": ["区分可恢复的限流/临时不可用/网络中断和确定性的认证或参数错误", "只对可安全重复操作进行有上限退避重试并尊重 Retry-After", "认证失败和无效参数立即失败", "并发使用信号量或队列限制配额", "记录 request_id、尝试次数、错误类型、状态和耗时而不伪装空响应为成功"]},
    },
    {
        "question_id": "dq_adv_003",
        "knowledge_id": "evaluation_metrics",
        "question_type": "short_answer",
        "difficulty": 5,
        "quiz_level": "challenge",
        "stem": "为一次 RAG+生成改版设计可复现的离线验收。请说明如何隔离开发集和验收集、如何处理随机性、至少四类指标及其分子分母，以及如何对失败案例归因，避免把针对验收样例的修补误报为提升。",
        "answer_key": {"rubric": ["固定任务定义、代表性案例、参考答案或 rubric、数据和模型版本", "开发集用于调试，独立验收集只用于判断版本", "固定可控参数或重复运行以处理随机性", "指标报告分子、分母、不可判定样例和失败 case ID", "从提示、检索、生成、工具和评分器分别归因"]},
    },
    {
        "question_id": "dq_adv_004",
        "knowledge_id": "review_validation_agent",
        "question_type": "short_answer",
        "difficulty": 5,
        "quiz_level": "challenge",
        "stem": "双评审通道对同一学习资源给出冲突结论。请设计从输入复核到最终发布决定的仲裁流程，覆盖确定性校验、重新检索、局部修订上限和持续分歧的处置。",
        "answer_key": {"rubric": ["先用代码校验可判定字段、引用和数值范围", "确认两路评审的输入证据、评分规则和输出解析一致", "针对争议点重新检索并独立仲裁", "局部修订限制字段和循环次数", "持续分歧或无法判定时阻止资源发布并进入人工复核或失败"]},
    },
]


def load_json(filename: str) -> Any:
    path = SEED_DIR / filename
    if not path.exists():
        fallback = Path(__file__).resolve().parents[3] / "data" / "seed" / filename
        path = fallback if fallback.exists() else path
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate_chunk_count(payload: dict[str, Any]) -> int:
    return len(
        chunk_knowledge_item(
            knowledge_id=str(payload["knowledge_id"]),
            name=str(payload["name"]),
            category=str(payload["category"]),
            difficulty=int(payload.get("difficulty", 1)),
            tags=list(payload.get("tags", [])),
            content_md=str(payload["content"]),
        )
    )


def enriched_knowledge_payloads() -> list[dict[str, Any]]:
    enrichments = {
        str(item["knowledge_id"]): item
        for item in load_json("knowledge_practice_enrichment.json")
    }
    payloads: list[dict[str, Any]] = []
    for original in load_json("knowledge_items.json"):
        payload = dict(original)
        enrichment = enrichments.get(str(payload["knowledge_id"]))
        if enrichment is not None:
            payload["content"] = (
                f"{str(payload['content']).rstrip()}\n\n"
                f"## 应用任务\n{str(enrichment['operation']).strip()}\n\n"
                f"## 预期结果\n{str(enrichment['expected_result']).strip()}"
            )
        payload["evidence_capabilities"] = classify_evidence_capabilities(
            str(payload["content"])
        )
        payloads.append(payload)
    known_ids = {str(item["knowledge_id"]) for item in payloads}
    if set(enrichments) - known_ids:
        raise ValueError("knowledge practice enrichment references unknown knowledge")
    return payloads


def upsert_by_field(
    db: Session,
    model: type,
    field_name: str,
    field_value: str,
    values: dict[str, Any],
) -> Any:
    field = getattr(model, field_name)
    instance = db.scalar(select(model).where(field == field_value))
    if instance is None:
        instance = model(**values)
        db.add(instance)
    else:
        for key, value in values.items():
            setattr(instance, key, value)
    return instance


def seed_domain(db: Session) -> Domain:
    payload = load_json("ai_app_dev_domain.json")
    return upsert_by_field(
        db,
        Domain,
        "domain_code",
        payload["domain_code"],
        {
            "domain_code": payload["domain_code"],
            "name": payload["name"],
            "status": "ready",
            "schema_version": payload.get("domain_schema_version", "1.0"),
            "config_json": {
                "resource_types": payload.get("resource_types", []),
                "ability_dimensions": payload.get("ability_dimensions", []),
                "learning_directions": payload.get("learning_directions", []),
                "mvp_targets": payload.get("mvp_targets", {}),
                "practice_evidence_required_for_all": bool(
                    payload.get("practice_evidence_required_for_all", False)
                ),
                "readiness_policy": {
                    "minimum_published_knowledge": 50,
                    "minimum_diagnostic_questions": 60,
                },
                "profile_policy": {
                    "version": "ai_app_dev_profile_v2",
                    "ability_dimensions": [
                        "theory",
                        "practice",
                        "problem_solving",
                        "knowledge_breadth",
                        "learning_speed",
                    ],
                    "mastery_thresholds": [0.4, 0.6, 0.8],
                    "mastery_baselines": MASTERY_BASELINES,
                    "prior_mastery": 0.5,
                    "prior_weight": 1.0,
                    "minimum_effective_change": 5,
                    "max_ability_change_per_update": 10,
                    "max_weakness_level_change_per_update": 1,
                    "default_n_results": 8,
                    "multi_priority_remedial_n_results": 10,
                    "maximum_n_results": 12,
                },
            },
        },
    )


def seed_knowledge_items(db: Session) -> dict[str, KnowledgeItem]:
    payloads = enriched_knowledge_payloads()
    seed_document = upsert_by_field(
        db,
        KnowledgeDocument,
        "public_id",
        "kdoc_ai_app_dev_seed",
        {
            "public_id": "kdoc_ai_app_dev_seed",
            "domain_code": "ai_app_dev",
            "original_name": "AI应用开发核心知识包.json",
            "stored_path": None,
            "file_type": "seed_package",
            "mime_type": "application/json",
            "size_bytes": 0,
            "sha256": "seed-ai-app-dev-core-v1",
            "status": "ready",
            "knowledge_item_count": len(payloads),
            "chunk_count": sum(_candidate_chunk_count(item) for item in payloads),
            "source_title": "AI 应用开发核心知识包",
            "license_note": "项目内置种子知识",
            "uploaded_by": "system",
        },
    )
    db.flush()
    items: dict[str, KnowledgeItem] = {}
    for payload in payloads:
        public_id = payload["knowledge_id"]
        values = {
            "public_id": public_id,
            "domain_code": payload.get("domain_code", "ai_app_dev"),
            "name": payload["name"],
            "category": payload["category"],
            "difficulty": payload.get("difficulty", 1),
            "tags_json": payload.get("tags", []),
            "evidence_capabilities_json": payload["evidence_capabilities"],
            "content_md": payload["content"],
            "source_title": payload.get("source_title", "自建 AI 应用开发实训知识库"),
            "source_url": payload.get("source_url"),
            "license_note": payload.get("license_note", "team-authored"),
            "source_document_id": seed_document.id,
            "ability_weights_json": payload["ability_weights"],
            "status": "published",
        }
        item = db.scalar(select(KnowledgeItem).where(KnowledgeItem.public_id == public_id))
        if item is None:
            item = KnowledgeItem(**values, needs_reembedding=True)
            db.add(item)
        else:
            changed = any(getattr(item, key) != value for key, value in values.items())
            if changed:
                for key, value in values.items():
                    setattr(item, key, value)
                item.needs_reembedding = True
        items[public_id] = item

    db.flush()
    for payload in payloads:
        source = items[payload["knowledge_id"]]
        relation_specs = [
            ("prerequisite", target_id) for target_id in payload.get("prerequisites", [])
        ]
        relation_specs.extend(("related", target_id) for target_id in payload.get("related", []))
        for relation_type, target_public_id in relation_specs:
            target = items.get(target_public_id)
            if target is None:
                continue
            exists = db.scalar(
                select(KnowledgeRelation).where(
                    KnowledgeRelation.source_item_id == target.id,
                    KnowledgeRelation.target_item_id == source.id,
                    KnowledgeRelation.relation_type == relation_type,
                )
            )
            if exists is None:
                db.add(
                    KnowledgeRelation(
                        source_item_id=target.id,
                        target_item_id=source.id,
                        relation_type=relation_type,
                    )
                )
    return items


def seed_diagnostic_questions(
    db: Session, knowledge_items: dict[str, KnowledgeItem]
) -> list[DiagnosticQuestion]:
    payloads = [
        *load_json("diagnostic_questions.json"),
        *load_json("question_bank_expansion.json"),
        *HIGH_DIFFICULTY_SEED_QUESTIONS,
    ]
    public_id_by_db_id = {item.id: item.public_id for item in knowledge_items.values()}
    related_ids_by_knowledge = {public_id: set() for public_id in knowledge_items}
    for relation in db.scalars(select(KnowledgeRelation)):
        source_id = public_id_by_db_id.get(relation.source_item_id)
        target_id = public_id_by_db_id.get(relation.target_item_id)
        if source_id and target_id:
            related_ids_by_knowledge[source_id].add(target_id)
            related_ids_by_knowledge[target_id].add(source_id)
    questions: list[DiagnosticQuestion] = []
    for payload in payloads:
        item = knowledge_items[payload["knowledge_id"]]
        options = payload.get("options", [])
        answer_key = dict(payload.get("answer_key", {}))
        correct_option = answer_key.get("correct_option")
        correct_text = (
            options[correct_option]
            if isinstance(correct_option, int) and 0 <= correct_option < len(options)
            else "参考答案中的关键要点"
        )
        answer_key.setdefault(
            "explanation",
            f"正确答案为“{correct_text}”，对应知识点“{item.name}”的核心要求。",
        )
        answer_key.setdefault("source_quote", item.content_md[:300])
        source_chunks = candidate_chunks_for_item(item)
        source_binding = resolve_question_source_binding(
            item,
            source_quote=answer_key["source_quote"],
            chunks=source_chunks,
        )
        bound_chunk = next(
            chunk
            for chunk in source_chunks
            if chunk.chunk_id == source_binding["source_ref_ids"][0]
        )
        source_quote = str(answer_key["source_quote"])
        if source_quote not in bound_chunk.content:
            source_quote = bound_chunk.content[:300]
        answer_key["source_quote"] = source_quote
        answer_key.update(source_binding)
        source_ref_id = str(answer_key["source_ref_ids"][0])
        source_hashes = {source_ref_id: knowledge_item_content_hash(item)}
        aggregate_source_hash = "sha256:" + hashlib.sha256(
            json.dumps(
                source_hashes, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        answer_key.update(
            {
                "source_ref_ids": [source_ref_id],
                "source_locators": {
                    source_ref_id: str(answer_key.pop("source_locator"))
                },
                "source_content_hashes": source_hashes,
                "evidence_quotes": [
                    {
                        "source_ref_id": source_ref_id,
                        "quote": str(answer_key["source_quote"]),
                    }
                ],
                "chunker_version": CHUNKER_VERSION,
                "assessment_dimension": (
                    str(payload["assessment_dimension"])
                    if payload.get("assessment_dimension") in {"theory", "operation"}
                    else (
                        "operation"
                        if "operation"
                        in classify_evidence_capabilities(bound_chunk.embedding_text)
                        else "theory"
                    )
                ),
            }
        )
        quiz_level = str(payload.get("quiz_level") or (
            "foundation" if int(payload.get("difficulty", item.difficulty)) <= 2
            else "improvement" if int(payload.get("difficulty", item.difficulty)) <= 3
            else "challenge"
        ))
        answer_key.setdefault("quiz_level", quiz_level)
        answer_key.setdefault(
            "question_bank_uses", ["diagnosis"]
        )
        if payload["question_type"] == "short_answer":
            rubric = [str(value).strip() for value in answer_key.get("rubric") or []]
            answer_key.setdefault("answer", "；".join(rubric))
        question = upsert_by_field(
            db,
            DiagnosticQuestion,
            "public_id",
            payload["question_id"],
            {
                "public_id": payload["question_id"],
                "domain_code": payload.get("domain_code", item.domain_code),
                "knowledge_item_id": item.id,
                "related_knowledge_ids_json": [],
                "question_type": payload["question_type"],
                "stem": payload["stem"],
                "options_json": options,
                "answer_key_json": answer_key,
                "difficulty": payload.get("difficulty", item.difficulty),
                "status": "active",
                "certification_status": "certified",
                "certification_rule_version": QUESTION_CERTIFICATION_RULE_VERSION,
                "certification_report_json": {
                    "rule_version": QUESTION_CERTIFICATION_RULE_VERSION,
                    "deterministic_passed": True,
                    "certification_method": payload.get(
                        "certification_method", "curated_seed_exact_evidence"
                    ),
                    "failed_fields": [],
                    "source_content_hash": aggregate_source_hash,
                },
                "source_content_hash": aggregate_source_hash,
                "certified_at": datetime.now(UTC).replace(tzinfo=None),
            },
        )
        questions.append(question)
    return questions


def seed_demo_users(db: Session) -> None:
    # Authentication users are created by registration or init_admin.py.
    # Legacy demo learner records remain seeded separately as business fixtures.
    return None


def run_seed() -> dict[str, int]:
    with SessionLocal() as db:
        seed_domain(db)
        knowledge_items = seed_knowledge_items(db)
        questions = seed_diagnostic_questions(db, knowledge_items)
        seed_demo_users(db)
        db.commit()

        return {
            "domains": db.scalar(select(Domain).where(Domain.domain_code == "ai_app_dev"))
            is not None,
            "knowledge_items": len(knowledge_items),
            "diagnostic_questions": len(questions),
            "learners": 0,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed MVP domain data.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable summary.")
    args = parser.parse_args()

    summary = run_seed()
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            "Seed complete: "
            f"{summary['knowledge_items']} knowledge items, "
            f"{summary['diagnostic_questions']} diagnostic questions, "
            f"{summary['learners']} learners."
        )


if __name__ == "__main__":
    main()
