from __future__ import annotations

import json
import re
from pathlib import Path

from app.agents import prompt_registry
from app.agents.contract_examples import (
    agent_message_example,
    dump_example,
    feedback_flow_example,
    initial_generation_flow_example,
)
from app.agents.contracts import AgentContractSchema


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ACTIVE_DOCUMENTS = (
    PROJECT_ROOT / "README.md",
    PROJECT_ROOT / "AGENTS.md",
    PROJECT_ROOT / "需求文档-领域知识个性化生成与多智能体协同决策系统.md",
    PROJECT_ROOT / "设计文档-人工智能应用开发实训多智能体个性化知识生成系统.md",
    PROJECT_ROOT / "docs" / "agent-contract-v10.md",
    PROJECT_ROOT / "docs" / "api-v1.md",
    PROJECT_ROOT / "docs" / "competition-requirements-checklist.md",
    PROJECT_ROOT / "docs" / "current-iteration-plan.md",
    PROJECT_ROOT / "docs" / "deployment.md",
    PROJECT_ROOT / "docs" / "design.md",
    PROJECT_ROOT / "docs" / "project-conventions.md",
    PROJECT_ROOT / "docs" / "requirements.md",
    PROJECT_ROOT / "docs" / "领域知识库自动导入与知识图谱构建实施方案.md",
    PROJECT_ROOT / "test_script" / "README.md",
)
PROMPT_DOCUMENTS = tuple((PROJECT_ROOT / "backend" / "app" / "agents" / "prompts").glob("*.md"))
SUPERSEDED_CONTRACT = re.compile(r"agent-contract-v(?:[1-9])(?:\D|$)", re.IGNORECASE)
REMOVED_GENERATION_PATHS = (
    "generation.coverage_repair",
    "generation.content_policy_repair",
    "generation_coverage_repair",
    "generation_content_policy_repair",
    "generated_content_policy_invalid",
    "required_practice_evidence_missing",
)
SOFT_GAP_HARD_FAILURES = (
    "generation_missing_target_evidence error",
    "generated_coverage_incomplete error",
)
REMOVED_DOCUMENT_PATHS = (
    *(PROJECT_ROOT / "docs" / f"agent-contract-v{version}.md" for version in (3, 5, 6, 7, 8, 9)),
    *(PROJECT_ROOT / "docs" / "contracts" / f"v{version}" for version in (3, 5, 6, 7, 8, 9)),
    PROJECT_ROOT / "docs" / "agent-contract-v6-governance-decision.md",
    PROJECT_ROOT / "docs" / "v6-failure-classification.md",
    PROJECT_ROOT / "docs" / "contract-change-request-generation-evidence-precondition.md",
    PROJECT_ROOT / "docs" / "领域迁移与多智能体闭环综合优化方案.md",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_active_documentation_uses_only_v10_runtime_rules() -> None:
    for path in (*ACTIVE_DOCUMENTS, *PROMPT_DOCUMENTS):
        content = _read(path)
        assert not SUPERSEDED_CONTRACT.search(content), path
        for removed in REMOVED_GENERATION_PATHS:
            assert removed not in content, (path, removed)
        for invalid_rule in SOFT_GAP_HARD_FAILURES:
            assert invalid_rule not in content, (path, invalid_rule)


def test_active_documentation_states_graph_and_publication_invariants() -> None:
    design = _read(
        PROJECT_ROOT / "设计文档-人工智能应用开发实训多智能体个性化知识生成系统.md"
    )
    contract = " ".join(
        _read(PROJECT_ROOT / "docs" / "agent-contract-v10.md").split()
    ).lower()
    assert "retrieve_knowledge -> generate_resource" in design
    assert "generate_resource -> review_resource" in design
    assert "最多两轮" in design
    assert "幻觉率 `< 5%`" in design
    assert "难度匹配率 `>= 85%`" in design
    assert "核心知识覆盖率 `>= 90%`" in design
    assert "empty supplemental retrieval result does not fail" in contract
    assert "publication remains atomic" in contract


def test_active_documentation_local_links_exist() -> None:
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for document in ACTIVE_DOCUMENTS:
        for raw_target in link_pattern.findall(_read(document)):
            target = raw_target.strip().strip("<>").split("#", 1)[0]
            if not target or re.match(r"^[a-z]+://", target, re.IGNORECASE):
                continue
            resolved = (document.parent / target).resolve()
            assert resolved.exists(), (document, raw_target)


def test_removed_generation_prompts_are_not_registered() -> None:
    assert "generation.coverage_repair" not in prompt_registry.PROMPT_FILES
    assert "generation.content_policy_repair" not in prompt_registry.PROMPT_FILES
    assert "generation.coverage_repair" not in prompt_registry.NODE_PROMPT_KEYS[
        "generate_resource"
    ]
    assert "generation.content_policy_repair" not in prompt_registry.NODE_PROMPT_KEYS[
        "generate_resource"
    ]


def test_superseded_design_documents_are_absent() -> None:
    remaining = [
        path
        for path in REMOVED_DOCUMENT_PATHS
        if path.is_file() or (path.is_dir() and any(path.rglob("*")))
    ]
    assert not remaining


def test_v10_schema_matches_executable_contract() -> None:
    schema_path = (
        PROJECT_ROOT
        / "docs"
        / "contracts"
        / "v10"
        / "agent-contract-v10.schema.json"
    )
    assert json.loads(_read(schema_path)) == AgentContractSchema.model_json_schema()


def test_v10_examples_match_executable_examples() -> None:
    examples_path = (
        PROJECT_ROOT
        / "docs"
        / "contracts"
        / "v10"
        / "agent-contract-v10.examples.json"
    )
    expected = dump_example(
        {
            "agent_message": agent_message_example(),
            "initial_generation": initial_generation_flow_example(),
            "resource_feedback": feedback_flow_example(),
        }
    )
    assert json.loads(_read(examples_path)) == expected
