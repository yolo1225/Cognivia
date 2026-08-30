"""M2 database-backed domain runtime configuration.

Revision ID: 20260820_0019
Revises: 20260819_0018
"""

import json
from pathlib import Path

from alembic import op
import sqlalchemy as sa

from app.agents.profile_analysis_config import MASTERY_BASELINES


revision = "20260820_0019"
down_revision = "20260819_0018"
branch_labels = None
depends_on = None


def _ai_app_dev_ability_weights() -> dict[str, dict[str, float]]:
    """Keep this historical migration independent from runtime configuration."""

    seed_path = Path(__file__).resolve().parents[3] / "data" / "seed" / "knowledge_items.json"
    payload = json.loads(seed_path.read_text(encoding="utf-8"))
    return {
        str(item["knowledge_id"]): dict(item["ability_weights"])
        for item in payload
    }


def upgrade() -> None:
    bind = op.get_bind()
    for knowledge_id, weights in _ai_app_dev_ability_weights().items():
        bind.execute(
            sa.text(
                "UPDATE knowledge_items SET ability_weights_json=:weights "
                "WHERE public_id=:knowledge_id AND domain_code='ai_app_dev'"
            ),
            {"weights": json.dumps(weights), "knowledge_id": knowledge_id},
        )
    operation_questions = (
        (
            "dq_056",
            "python_api_basics",
            "调用一个 Python API 后，至少应检查哪些结果来确认请求成功且响应可用？",
            ["状态码", "响应结构", "必需字段", "异常处理"],
            2,
        ),
        (
            "dq_057",
            "prompt_context_design",
            "为一次模型调用组装上下文时，应按什么步骤控制信息范围并验证输出？",
            ["明确任务", "选择必要上下文", "限制无关信息", "验证输出"],
            3,
        ),
    )
    for question_id, knowledge_id, stem, rubric, difficulty in operation_questions:
        bind.execute(
            sa.text(
                "UPDATE diagnostic_questions SET "
                "knowledge_item_id=(SELECT id FROM knowledge_items "
                "WHERE public_id=:knowledge_id AND domain_code='ai_app_dev'), "
                "stem=:stem, options_json=:options, answer_key_json=:answer_key, "
                "difficulty=:difficulty, updated_at=CURRENT_TIMESTAMP "
                "WHERE public_id=:question_id AND domain_code='ai_app_dev'"
            ),
            {
                "question_id": question_id,
                "knowledge_id": knowledge_id,
                "stem": stem,
                "options": json.dumps([]),
                "answer_key": json.dumps({"rubric": rubric}, ensure_ascii=False),
                "difficulty": difficulty,
            },
        )
    row = bind.execute(
        sa.text("SELECT config_json FROM domains WHERE domain_code='ai_app_dev'")
    ).scalar_one_or_none()
    config = dict(row or {}) if isinstance(row, dict) else json.loads(row or "{}")
    config["profile_policy"] = {
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
    }
    config["learning_directions"] = [
        {
            "value": "llm_application",
            "label": "大模型应用开发",
            "description": "模型调用、接口与应用流程",
            "match_tags": ["llm", "model", "api", "workflow", "overview"],
        },
        {
            "value": "prompt_engineering",
            "label": "Prompt 工程",
            "description": "指令、上下文与结构化输出",
            "match_tags": ["prompt", "context", "structured", "json"],
        },
        {
            "value": "rag_knowledge_base",
            "label": "RAG 知识库构建",
            "description": "检索、向量和知识管理",
            "match_tags": ["rag", "retrieval", "embedding", "vector", "knowledge-base"],
        },
        {
            "value": "agent_orchestration",
            "label": "Agent 编排",
            "description": "工具调用、多智能体与工作流",
            "match_tags": ["agent", "tool", "orchestration", "workflow", "planning"],
        },
    ]
    bind.execute(
        sa.text("UPDATE domains SET config_json=:config WHERE domain_code='ai_app_dev'"),
        {"config": json.dumps(config, ensure_ascii=False)},
    )


def downgrade() -> None:
    # Runtime data is intentionally retained; removing it would make the active domain unusable.
    pass
