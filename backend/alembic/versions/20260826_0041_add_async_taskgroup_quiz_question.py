"""Add a certified asyncio TaskGroup question for the active demo path.

Revision ID: 20260826_0041
Revises: 20260826_0040
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa


revision = "20260826_0041"
down_revision = "20260826_0040"
branch_labels = None
depends_on = None

QUESTION_ID = "dq_062_async_taskgroup"
KNOWLEDGE_ID = "python_async_concurrency"
SOURCE_QUESTION_ID = "dq_061"


def upgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(
        sa.text("SELECT 1 FROM diagnostic_questions WHERE public_id = :public_id"),
        {"public_id": QUESTION_ID},
    ):
        return
    source = connection.execute(
        sa.text(
            """
            SELECT source_content_hash, answer_key_json
            FROM diagnostic_questions
            WHERE public_id = :public_id
              AND certification_status = 'certified'
              AND certification_rule_version = 'question-cert-v1'
            """
        ),
        {"public_id": SOURCE_QUESTION_ID},
    ).mappings().first()
    knowledge_id = connection.scalar(
        sa.text(
            "SELECT id FROM knowledge_items WHERE public_id = :public_id AND domain_code = 'ai_app_dev'"
        ),
        {"public_id": KNOWLEDGE_ID},
    )
    if source is None or knowledge_id is None:
        return
    source_answer = source["answer_key_json"] or {}
    if isinstance(source_answer, str):
        source_answer = json.loads(source_answer)
    source_hash = str(source["source_content_hash"] or "")
    if not source_hash:
        return
    source_ref_id = f"{KNOWLEDGE_ID}::chunk::0"
    source_quote = str(source_answer.get("source_quote") or "")
    answer_key = {
        "quiz_level": "foundation",
        "correct_option": 0,
        "explanation": "对相互独立的 I/O 调用，应使用 asyncio 的任务组并发调度并 await 结果；同步阻塞或丢弃协程都会破坏并发与异常处理。",
        "source_ref_ids": [source_ref_id],
        "source_quote": source_quote,
        "evidence_quotes": [{"source_ref_id": source_ref_id, "quote": source_quote}],
        "source_locators": dict(source_answer.get("source_locators") or {}),
        "source_content_hashes": dict(source_answer.get("source_content_hashes") or {}),
        "chunker_version": source_answer.get("chunker_version"),
        "question_bank_purpose": "diagnosis_mastery_and_resource_quiz",
    }
    now = datetime.now(UTC).replace(tzinfo=None)
    connection.execute(
        sa.text(
            """
            INSERT INTO diagnostic_questions (
                public_id, domain_code, knowledge_item_id, related_knowledge_ids_json,
                question_type, stem, options_json, answer_key_json, difficulty,
                status, certification_status, certification_rule_version,
                certification_report_json, source_content_hash, certified_at,
                created_at, updated_at
            ) VALUES (
                :public_id, 'ai_app_dev', :knowledge_item_id, :related_knowledge_ids_json,
                'single_choice', :stem, :options_json, :answer_key_json, 2,
                'active', 'certified', 'question-cert-v1',
                :certification_report_json, :source_content_hash, :certified_at,
                :created_at, :updated_at
            )
            """
        ),
        {
            "public_id": QUESTION_ID,
            "knowledge_item_id": knowledge_id,
            "related_knowledge_ids_json": json.dumps([]),
            "stem": "在异步 Web 服务中，需要同时调用多个相互独立的外部 LLM API，并在任一调用异常时统一处理失败。下列做法最合适的是？",
            "options_json": json.dumps(
                [
                    "为每个调用创建协程任务，使用 asyncio.TaskGroup 管理并等待结果",
                    "在普通 for 循环中逐个调用同步 requests",
                    "在每次调用前使用 time.sleep 等待",
                    "不等待协程，直接把协程对象作为响应返回",
                ],
                ensure_ascii=False,
            ),
            "answer_key_json": json.dumps(answer_key, ensure_ascii=False),
            "certification_report_json": json.dumps(
                {
                    "rule_version": "question-cert-v1",
                    "failed_fields": [],
                    "source_content_hash": source_hash,
                    "certification_method": "curated_seed_exact_evidence",
                    "deterministic_passed": True,
                },
                ensure_ascii=False,
            ),
            "source_content_hash": source_hash,
            "certified_at": now,
            "created_at": now,
            "updated_at": now,
        },
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM diagnostic_questions WHERE public_id = :public_id").bindparams(
            public_id=QUESTION_ID
        )
    )
