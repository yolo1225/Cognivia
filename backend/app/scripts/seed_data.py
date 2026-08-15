from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import (
    DiagnosticQuestion,
    Domain,
    KnowledgeItem,
    KnowledgeDocument,
    KnowledgeRelation,
)
from app.rag.chunker import chunk_markdown


SEED_DIR = Path("/app/data/seed")


def load_json(filename: str) -> Any:
    path = SEED_DIR / filename
    if not path.exists():
        fallback = Path(__file__).resolve().parents[3] / "data" / "seed" / filename
        path = fallback if fallback.exists() else path
    return json.loads(path.read_text(encoding="utf-8"))


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
            "schema_version": payload.get("domain_schema_version", "1.0"),
            "config_json": {
                "resource_types": payload.get("resource_types", []),
                "ability_dimensions": payload.get("ability_dimensions", []),
                "mvp_targets": payload.get("mvp_targets", {}),
            },
        },
    )


def seed_knowledge_items(db: Session) -> dict[str, KnowledgeItem]:
    payloads = load_json("knowledge_items.json")
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
            "chunk_count": sum(len(chunk_markdown(str(item["content"]))) for item in payloads),
            "source_title": "AI 应用开发核心知识包",
            "license_note": "项目内置种子知识",
            "uploaded_by": "system",
        },
    )
    db.flush()
    items: dict[str, KnowledgeItem] = {}
    for payload in payloads:
        public_id = payload["knowledge_id"]
        item = upsert_by_field(
            db,
            KnowledgeItem,
            "public_id",
            public_id,
            {
                "public_id": public_id,
                "domain_code": payload.get("domain_code", "ai_app_dev"),
                "name": payload["name"],
                "category": payload["category"],
                "difficulty": payload.get("difficulty", 1),
                "tags_json": payload.get("tags", []),
                "content_md": payload["content"],
                "source_title": payload.get("source_title", "自建 AI 应用开发实训知识库"),
                "source_url": payload.get("source_url"),
                "license_note": payload.get("license_note", "team-authored"),
                "needs_reembedding": True,
                "source_document_id": seed_document.id,
            },
        )
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
    payloads = load_json("diagnostic_questions.json")
    questions: list[DiagnosticQuestion] = []
    for payload in payloads:
        item = knowledge_items[payload["knowledge_id"]]
        question = upsert_by_field(
            db,
            DiagnosticQuestion,
            "public_id",
            payload["question_id"],
            {
                "public_id": payload["question_id"],
                "domain_code": payload.get("domain_code", item.domain_code),
                "knowledge_item_id": item.id,
                "question_type": payload["question_type"],
                "stem": payload["stem"],
                "options_json": payload.get("options", []),
                "answer_key_json": payload.get("answer_key", {}),
                "difficulty": payload.get("difficulty", item.difficulty),
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
            "domains": db.scalar(select(Domain).where(Domain.domain_code == "ai_app_dev")) is not None,
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
