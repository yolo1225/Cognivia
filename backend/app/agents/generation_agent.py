"""
Content Generation Agent
========================
基于学生画像和检索知识生成三种学习资源：
  - lecture（讲义）
  - practice_guide（实操指南）
  - graded_quiz（分级测验）

对外接口保持 V1 兼容（execute(state) → GenerationOutput），
内部使用 V2 合同的结构化内容类型，提高生成质量。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.agents.base import BaseAgent, PromptBudget
from app.agents.contracts import (
    GradedQuizContent,
    LectureContent,
    PracticeGuideContent,
    QuizLevel,
    ResourceType,
    SourceRef,
    StructuredResourceContent,
    structured_source_ref_ids,
)
from app.agents.legacy_contracts import (
    AgentMessage,
    GeneratedResourceDraft,
    GeneratedSourceRef,
    GenerationOutput,
)
from app.agents.legacy_state import AgentGraphState
from app.core.config import settings
from app.services.llm_service import ModelResponseError, gateway

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

GENERATION_AGENT_NAME = "content_generation_agent"

# ---------------------------------------------------------------------------
# 来源校验
# ---------------------------------------------------------------------------


def _normalize_generated_resource_payload(
    result: dict[str, Any], fixture: dict[str, Any]
) -> dict[str, Any]:
    """校验来源白名单并补全 SourceRef 信息。"""
    normalized = dict(result)
    raw_sources = normalized.get("sources")
    if not isinstance(raw_sources, list):
        raw_sources = [] if raw_sources is None else [raw_sources]

    allowed_sources = {
        str(source.get("knowledge_id")): source
        for source in fixture.get("sources", [])
        if isinstance(source, dict) and source.get("knowledge_id")
    }

    source_ids = [
        str(item.get("knowledge_id")) if isinstance(item, dict) else str(item)
        for item in raw_sources
    ]

    unknown_ids = [sid for sid in source_ids if sid not in allowed_sources]
    if unknown_ids:
        raise ModelResponseError(
            f"generated resource cited sources outside retrieval scope: {unknown_ids}"
        )

    normalized["sources"] = [allowed_sources[sid] for sid in source_ids]
    if not normalized["sources"]:
        raise ModelResponseError(
            "generated resource must cite at least one retrieved source"
        )
    return normalized


# ---------------------------------------------------------------------------
# 确定性 Markdown 渲染（V2 合同要求）
# ---------------------------------------------------------------------------


def _source_footer(source_refs: list[dict[str, Any]]) -> str:
    """生成知识来源脚注。"""
    if not source_refs:
        return ""
    lines = ["\n## 知识来源\n"]
    seen: set[str] = set()
    for ref in source_refs:
        sid = ref.get("source_ref_id") or f"{ref.get('knowledge_id')}::chunk::0"
        if sid in seen:
            continue
        seen.add(sid)
        title = ref.get("source_title", "知识库")
        license_note = ref.get("license_note", "team-authored")
        url = ref.get("source_url")
        url_part = f" ({url})" if url else ""
        lines.append(f"- [{sid}] {title} ({license_note}){url_part}")
    return "\n".join(lines)


def render_lecture_md(structured: dict[str, Any], sources: list[dict[str, Any]]) -> str:
    """确定性渲染讲义 Markdown。"""
    title = structured.get("title", "讲义")
    parts = [
        f"# {title}",
        "",
        f"## 适配对象\n{structured.get('target_audience', '学习者')}",
        "",
    ]

    objectives = structured.get("learning_objectives", [])
    if objectives:
        parts.append("## 学习目标\n")
        parts.extend(f"- {o}" for o in objectives)
        parts.append("")

    prereqs = structured.get("prerequisite_knowledge", [])
    if prereqs:
        parts.append("## 前置知识\n")
        parts.extend(f"- {p}" for p in prereqs)
        parts.append("")

    concepts = structured.get("core_concepts", [])
    if concepts:
        parts.append("## 核心概念\n")
        for c in concepts:
            parts.append(f"### {c.get('title', '概念')}")
            parts.append("")
            parts.append(c.get("explanation", ""))
            parts.append("")
            example = c.get("example")
            if example:
                parts.append(f"**示例**：{example}")
                parts.append("")
            refs = c.get("source_ref_ids", [])
            if refs:
                parts.append(f"来源：{', '.join(refs)}")
                parts.append("")

    misconceptions = structured.get("misconceptions", [])
    if misconceptions:
        parts.append("## 常见误区\n")
        for m in misconceptions:
            parts.append(f"- **误区**：{m.get('misconception', '')}")
            parts.append(f"  **纠正**：{m.get('correction', '')}")
            refs = m.get("source_ref_ids", [])
            if refs:
                parts.append(f"  来源：{', '.join(refs)}")
        parts.append("")

    parts.append(f"## 小结\n{structured.get('summary', '')}")
    parts.append("")
    parts.append(_source_footer(sources))
    return "\n".join(parts)


def render_practice_md(structured: dict[str, Any], sources: list[dict[str, Any]]) -> str:
    """确定性渲染实操指南 Markdown。"""
    title = structured.get("title", "实操指南")
    parts = [
        f"# {title}",
        "",
        f"## 适配对象\n{structured.get('target_audience', '学习者')}",
        "",
    ]

    objectives = structured.get("learning_objectives", [])
    if objectives:
        parts.append("## 学习目标\n")
        parts.extend(f"- {o}" for o in objectives)
        parts.append("")

    env = structured.get("environment_requirements", [])
    if env:
        parts.append("## 环境准备\n")
        parts.extend(f"- {e}" for e in env)
        parts.append("")

    steps = structured.get("steps", [])
    if steps:
        parts.append("## 操作步骤\n")
        for s in sorted(steps, key=lambda x: x.get("order", 1)):
            parts.append(f"### {s.get('order', '?')}. {s.get('title', '步骤')}")
            parts.append("")
            parts.append(s.get("instruction", ""))
            parts.append("")
            code = s.get("code_or_command")
            if code:
                parts.append(f"```text\n{code}\n```")
                parts.append("")
            parts.append(f"**预期结果**：{s.get('expected_result', '')}")
            parts.append("")
            troubleshoot = s.get("troubleshooting")
            if troubleshoot:
                parts.append(f"**排错**：{troubleshoot}")
                parts.append("")
            refs = s.get("source_ref_ids", [])
            if refs:
                parts.append(f"来源：{', '.join(refs)}")
                parts.append("")

    criteria = structured.get("acceptance_criteria", [])
    if criteria:
        parts.append("## 验收标准\n")
        parts.extend(f"- {c}" for c in criteria)
        parts.append("")

    parts.append(_source_footer(sources))
    return "\n".join(parts)


def render_quiz_md(structured: dict[str, Any], sources: list[dict[str, Any]]) -> str:
    """确定性渲染分级测验 Markdown（教师版，含答案）。"""
    title = structured.get("title", "分级测验")
    parts = [
        f"# {title}",
        "",
        f"## 适配对象\n{structured.get('target_audience', '学习者')}",
        "",
    ]

    objectives = structured.get("learning_objectives", [])
    if objectives:
        parts.append("## 学习目标\n")
        parts.extend(f"- {o}" for o in objectives)
        parts.append("")

    questions = structured.get("questions", [])
    level_labels = {"foundation": "## 基础巩固\n", "improvement": "## 能力提升\n", "challenge": "## 挑战突破\n"}
    for level_key, label in level_labels.items():
        level_qs = [q for q in questions if q.get("level") == level_key]
        if not level_qs:
            continue
        parts.append(label)
        for q in level_qs:
            parts.append(f"### {q.get('question_id', '?')}")
            parts.append("")
            parts.append(q.get("prompt", ""))
            parts.append("")
            opts = q.get("options", [])
            if opts:
                for i, opt in enumerate(opts):
                    parts.append(f"{chr(ord('A') + i)}. {opt}")
                parts.append("")
            parts.append(f"**参考答案**：{q.get('correct_answer', '')}")
            parts.append("")
            parts.append(f"**解析**：{q.get('explanation', '')}")
            parts.append("")
            parts.append(f"知识点：{q.get('knowledge_id', '')} | 难度：{q.get('difficulty', '?')}")
            parts.append("")
            refs = q.get("source_ref_ids", [])
            if refs:
                parts.append(f"来源：{', '.join(refs)}")
                parts.append("")

    parts.append(_source_footer(sources))
    return "\n".join(parts)


def render_resource_markdown(
    resource_type: str, structured: dict[str, Any], sources: list[dict[str, Any]]
) -> str:
    """根据资源类型选用对应的确定性渲染器。"""
    renderers = {
        "lecture": render_lecture_md,
        "practice_guide": render_practice_md,
        "graded_quiz": render_quiz_md,
    }
    renderer = renderers.get(resource_type)
    if renderer is None:
        raise ValueError(f"unsupported resource type for markdown rendering: {resource_type}")
    return renderer(structured, sources)


# ---------------------------------------------------------------------------
# 上下文构建（保留，避免破坏节点的 import）
# ---------------------------------------------------------------------------


def _display_text(value: Any) -> Any:
    """修复 Latin-1 误编码的 UTF-8 文本。"""
    if not isinstance(value, str):
        return value
    try:
        repaired = value.encode("latin1").decode("utf-8")
    except UnicodeError:
        return value
    return repaired if repaired else value


def _unique_non_empty(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def build_generation_context(state: AgentGraphState) -> dict[str, Any]:
    """从 V1 state 构建生成上下文。"""
    profile = state.get("profile", {})
    retrieval_plan = state.get("retrieval_plan", {})
    revision_plan = state.get("revision_plan") or {}
    strategy = retrieval_plan.get("strategy") or "consolidation"
    target_difficulty = int(retrieval_plan.get("target_difficulty") or 2)
    resource_types = state.get("resource_types", [])
    if revision_plan.get("revision_required"):
        resource_types = revision_plan.get("revision_resource_types") or resource_types

    tone_by_strategy = {
        "remedial": "基础解释 + 小步练习",
        "consolidation": "知识串联 + 任务检查点",
        "challenge": "扩展边界 + 综合挑战",
    }
    ability_profile = {
        key: value
        for key, value in profile.items()
        if key not in {"profile_id", "profile_type", "weak_knowledge", "learning_path_id"}
    }

    return {
        "profile": {
            "profile_id": profile.get("profile_id") or state.get("profile_id"),
            "profile_type": profile.get("profile_type", "beginner"),
            "ability_profile": ability_profile,
            "weak_knowledge": profile.get("weak_knowledge", []),
        },
        "retrieval_plan": retrieval_plan,
        "revision_plan": revision_plan,
        "sources": state.get("retrieved_chunks", []),
        "resource_types": resource_types,
        "generation_requirements": {
            "difficulty": target_difficulty,
            "strategy": strategy,
            "must_include_sources": True,
            "tone": tone_by_strategy.get(strategy, tone_by_strategy["consolidation"]),
            "source_policy": "cite_retrieved_knowledge_only",
            "missing_requirements": revision_plan.get("missing_requirements", []),
        },
    }


# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------


def _source_lines(sources: list[dict[str, Any]]) -> str:
    """格式化知识来源列表。"""
    if not sources:
        return "（无可用来源）"
    return "\n".join(
        f"- [{item.get('knowledge_id', '?')}] {_display_text(item['name'])} "
        f"（{item.get('matched_plan', 'semantic')}）：{_display_text(item.get('content', ''))}"
        for item in sources
    )


def _revision_requirement_block(requirements: dict[str, Any]) -> str:
    missing = _unique_non_empty(requirements.get("missing_requirements", []))
    if not missing:
        return ""
    return "\n## 修订要求\n" + "\n".join(f"- {item}" for item in missing) + "\n"


# ---------------------------------------------------------------------------
# Content Generation Agent
# ---------------------------------------------------------------------------


class ContentGenerationAgent(BaseAgent):
    """内容生成智能体。

    V1 对外的 execute(state) → GenerationOutput 接口保持不变，
    内部升级为 V2 风格的结构化生成 + 确定性 Markdown 渲染。
    """

    name = GENERATION_AGENT_NAME
    system_prompt_path = "app/agents/prompts/generation_agent.md"

    # ------------------------------------------------------------------
    # V1 接口（nodes.py 调用）
    # ------------------------------------------------------------------

    async def run(self, message: AgentMessage) -> dict[str, Any]:
        return {
            "agent_name": self.name,
            "status": "ready_for_stateful_execution",
            "payload_keys": sorted(message.payload.keys()),
        }

    def execute(self, state: AgentGraphState) -> dict[str, Any]:
        """V1 graph node 入口。返回 GenerationOutput。"""
        ctx = build_generation_context(state)
        sources = ctx["sources"]
        requirements = ctx["generation_requirements"]
        profile = ctx["profile"]
        revision_plan = ctx.get("revision_plan") or {}
        target_resource_types = set(ctx["resource_types"])

        # 保留不参与本次生成的已通过资源
        preserved_drafts = [
            r
            for r in state.get("passed_resources", [])
            if r.get("resource_type") not in target_resource_types
        ]

        # 并行生成
        fixture_drafts: list[dict[str, Any]] = []
        for rt in ctx["resource_types"]:
            fixture = self._build_fixture(rt, profile, requirements, sources)
            fixture_drafts.append(fixture)

        def generate_one(fixture: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
            payload = self._build_payload(fixture["resource_type"], profile, requirements, sources)
            budget = PromptBudget(12_000, 4_000).validate(str(payload))

            result, metadata = gateway.complete_json(
                model=settings.primary_llm_model,
                system_prompt=self.system_prompt(),
                payload=payload,
                fixture_factory=lambda: fixture,
                response_model=GeneratedResourceDraft,
                response_adapter=lambda r: _normalize_generated_resource_payload(r, fixture),
            )

            # 使用确定性渲染器生成 Markdown
            structured = result.get("structured_content") or {}
            if structured and result.get("use_structured"):
                content_md = render_resource_markdown(
                    fixture["resource_type"], structured, result.get("sources", [])
                )
            else:
                content_md = str(result.get("content") or fixture["content"])

            normalized = {
                **fixture,
                "title": str(result.get("title") or fixture["title"]),
                "content": content_md,
                "difficulty": int(result.get("difficulty") or fixture["difficulty"]),
                "sources": result.get("sources") or fixture["sources"],
            }
            return normalized, {
                **metadata,
                "resource_type": fixture["resource_type"],
                "budget": budget,
            }

        with ThreadPoolExecutor(max_workers=max(1, len(fixture_drafts))) as executor:
            generated = list(executor.map(generate_one, fixture_drafts))

        drafts = [*preserved_drafts, *[item[0] for item in generated]]
        model_calls = [item[1] for item in generated]

        return GenerationOutput(
            generation_context=ctx,
            draft_resources=drafts,
            trace={
                "resource_count": len(drafts),
                "generated_resource_count": len(ctx["resource_types"]),
                "preserved_resource_count": len(state.get("passed_resources", [])),
                "resource_types": ctx["resource_types"],
                "strategy": requirements["strategy"],
                "difficulty": requirements["difficulty"],
                "source_count": len(sources),
                "revision_required": bool(revision_plan.get("revision_required")),
                "model_calls": model_calls,
            },
        ).model_dump()

    # ------------------------------------------------------------------
    # Payload 构建
    # ------------------------------------------------------------------

    def _build_payload(
        self,
        resource_type: str,
        profile: dict[str, Any],
        requirements: dict[str, Any],
        sources: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """构建发给 LLM 的结构化 payload（V2 风格）。"""
        return {
            "task": {
                "resource_type": resource_type,
                "strategy": requirements["strategy"],
                "target_difficulty": requirements["difficulty"],
                "adaptation_notes": requirements.get("missing_requirements", []),
            },
            "profile": {
                "profile_id": profile.get("profile_id"),
                "profile_type": profile.get("profile_type", "beginner"),
                "ability_scores": profile.get("ability_profile", {}),
                "weak_knowledge": profile.get("weak_knowledge", []),
            },
            "retrieved_knowledge": [
                {
                    "knowledge_id": s.get("knowledge_id"),
                    "name": _display_text(s.get("name", "")),
                    "difficulty": s.get("difficulty", 2),
                    "content": s.get("content", ""),
                    "source_title": _display_text(s.get("source_title", "")),
                    "source_ref_id": s.get("source_ref_id")
                    or f"{s.get('knowledge_id')}::chunk::0",
                }
                for s in sources
            ],
            "source_whitelist": [
                s.get("source_ref_id") or f"{s.get('knowledge_id')}::chunk::0"
                for s in sources
            ],
            "required_knowledge_ids": [
                s.get("knowledge_id") for s in sources if s.get("knowledge_id")
            ],
            "revision_notes": (
                requirements.get("missing_requirements", [])
            ),
        }

    # ------------------------------------------------------------------
    # Fixture（LLM 不可用时的回退）
    # ------------------------------------------------------------------

    def _build_fixture(
        self,
        resource_type: str,
        profile: dict[str, Any],
        requirements: dict[str, Any],
        sources: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """构建最小合法 fixture。"""
        first = sources[0] if sources else {"name": "AI 应用开发", "knowledge_id": "unknown", "content": ""}
        strategy = requirements.get("strategy", "consolidation")
        strategy_label = {"remedial": "补救", "consolidation": "巩固", "challenge": "挑战"}.get(strategy, "学习")
        title = f"{_display_text(first.get('name', 'AI 应用开发'))} - {strategy_label}{resource_type}"
        title = str(title)
        source_id = first.get("source_ref_id") or f"{first.get('knowledge_id', 'unknown')}::chunk::0"
        knowledge_id = str(first.get("knowledge_id", "unknown"))
        content = str(first.get("content", ""))

        source_refs = [
            {
                "knowledge_id": s.get("knowledge_id"),
                "name": _display_text(s.get("name", "")),
                "source_title": _display_text(s.get("source_title", "")),
                "matched_plan": s.get("matched_plan", "semantic"),
                "used_for": s.get("used_for"),
                "source_ref_id": s.get("source_ref_id") or f"{s.get('knowledge_id')}::chunk::0",
            }
            for s in sources[:3]
        ]

        if resource_type == "lecture":
            structured = {
                "resource_type": "lecture",
                "title": title,
                "target_audience": profile.get("profile_type", "beginner"),
                "learning_objectives": [f"理解 {_display_text(first.get('name', ''))}"],
                "prerequisite_knowledge": [],
                "core_concepts": [
                    {
                        "title": _display_text(first.get("name", "核心概念")),
                        "explanation": content[:500] if content else "详见来源知识",
                        "example": None,
                        "source_ref_ids": [source_id],
                    }
                ],
                "misconceptions": [],
                "summary": f"学习了 {_display_text(first.get('name', ''))} 的核心概念",
            }
            content_md = render_lecture_md(structured, source_refs)
            return {
                "resource_type": "lecture",
                "title": title,
                "content": content_md,
                "difficulty": requirements.get("difficulty", 2),
                "sources": source_refs[:1],
                "structured_content": structured,
                "use_structured": True,
            }

        elif resource_type == "practice_guide":
            structured = {
                "resource_type": "practice_guide",
                "title": title,
                "target_audience": profile.get("profile_type", "beginner"),
                "learning_objectives": [f"实操掌握 {_display_text(first.get('name', ''))}"],
                "environment_requirements": ["Python 3.12"],
                "steps": [
                    {
                        "order": 1,
                        "title": f"学习 {_display_text(first.get('name', ''))}",
                        "instruction": content[:500] if content else "参见来源知识",
                        "code_or_command": None,
                        "expected_result": "能够复述核心概念并完成操作",
                        "troubleshooting": None,
                        "source_ref_ids": [source_id],
                    }
                ],
                "acceptance_criteria": ["能够独立完成核心操作"],
            }
            content_md = render_practice_md(structured, source_refs)
            return {
                "resource_type": "practice_guide",
                "title": title,
                "content": content_md,
                "difficulty": requirements.get("difficulty", 2),
                "sources": source_refs[:1],
                "structured_content": structured,
                "use_structured": True,
            }

        else:  # graded_quiz
            structured = {
                "resource_type": "graded_quiz",
                "title": title,
                "target_audience": profile.get("profile_type", "beginner"),
                "learning_objectives": [f"检测对 {_display_text(first.get('name', ''))} 的掌握程度"],
                "questions": [
                    {
                        "question_id": f"Q{i+1}",
                        "level": level,
                        "question_type": "short_answer",
                        "prompt": f"关于 {_display_text(first.get('name', ''))}，请说明第{i+1}个关键点",
                        "options": [],
                        "correct_answer": content[:200] if content else "详见来源知识",
                        "explanation": f"详见 {_display_text(first.get('name', ''))}",
                        "knowledge_id": knowledge_id,
                        "difficulty": min(5, (requirements.get("difficulty", 2) or 2) + (i // 2)),
                        "source_ref_ids": [source_id],
                    }
                    for i, level in enumerate(
                        ["foundation"] * 2 + ["improvement"] * 2 + ["challenge"] * 2
                    )
                ],
            }
            content_md = render_quiz_md(structured, source_refs)
            return {
                "resource_type": "graded_quiz",
                "title": title,
                "content": content_md,
                "difficulty": requirements.get("difficulty", 2),
                "sources": source_refs[:1],
                "structured_content": structured,
                "use_structured": True,
            }
