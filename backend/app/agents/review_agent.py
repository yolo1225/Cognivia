"""
Review Validation Agent — 双视角 + 确定性验证
==============================================

两个 LLM 视角（事实核查员 / 教学评估员）独立审核每份资源。
关键设计：
1. **确定性验证引擎** — 不依赖 LLM，用句级来源重叠度做客观评分
2. **后验交叉验证**   — LLM 审核结果与确定性评分交叉比对，差异过大时报警
3. **分层兜底**       — LLM 正常 → LLM 评分；LLM 异常 → 确定性评分
4. **语言无关**       — 分词逻辑同时覆盖中文（字级 bigram）和英文（词级）
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.agents.base import BaseAgent, PromptBudget
from app.agents.legacy_contracts import AgentMessage, ModelReview, ReviewOutput
from app.agents.generation_agent import build_generation_context
from app.agents.legacy_state import AgentGraphState
from app.core.config import settings
from app.services.llm_service import gateway

logger = logging.getLogger(__name__)

REVIEW_AGENT_NAME = "review_validation_agent"

# ---------------------------------------------------------------------------
# 质量阈值
# ---------------------------------------------------------------------------
FACTUAL_THRESHOLD = 90
SOURCE_THRESHOLD = 90
DIFFICULTY_THRESHOLD = 85
COVERAGE_THRESHOLD = 90

# 交叉验证阈值：LLM 评分与确定性评分差异超过此值 → 标记为可疑
CROSS_CHECK_MAX_DELTA = 25


# ===========================================================================
# 确定性验证引擎（语言无关，不依赖 LLM）
# ===========================================================================

def _tokenize(text: str) -> list[str]:
    """语言无关分词：中文用字级 bigram，英文用词级。"""
    if not text:
        return []
    # 检测是否主要为中文
    cjk_count = sum(1 for ch in text if '一' <= ch <= '鿿')
    if cjk_count > len(text) * 0.3:
        # 中文：字级 unigram + bigram
        chars = re.sub(r'[^一-鿿\w]', '', text)
        unigrams = list(chars)
        bigrams = [chars[i:i+2] for i in range(len(chars)-1)]
        return unigrams + bigrams
    else:
        # 英文/混合：词级（小写、去标点）
        words = re.findall(r'[a-zA-Z0-9]+', text.lower())
        return words


def _jaccard_similarity(tokens_a: list[str], tokens_b: list[str]) -> float:
    """Jaccard 相似度。"""
    if not tokens_a or not tokens_b:
        return 0.0
    set_a, set_b = set(tokens_a), set(tokens_b)
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def _split_sentences(text: str) -> list[str]:
    """中英文通用分句。"""
    if not text:
        return []
    # 按中英文标点分割
    raw = re.split(r'[。！？.!?\n]+', text)
    return [s.strip() for s in raw if len(s.strip()) > 10]


def _has_source_overlap(sentence: str, source_texts: list[str], threshold: float = 0.15) -> bool:
    """句子是否与任一来源有足够重叠。"""
    sent_tokens = _tokenize(sentence)
    if len(sent_tokens) < 3:
        return False
    for src in source_texts:
        src_tokens = _tokenize(src)
        if _jaccard_similarity(sent_tokens, src_tokens) >= threshold:
            return True
    return False


def _count_explicit_refs(content: str, sources: list[dict[str, Any]]) -> int:
    """统计内容中显式引用了多少个来源（按 knowledge_id / name / source_ref_id 匹配）。"""
    if not content or not sources:
        return 0
    content_lower = content.lower()
    count = 0
    for s in sources:
        candidates = [
            str(s.get("knowledge_id", "")),
            str(s.get("name", "")),
            str(s.get("source_ref_id", "")),
            str(s.get("source_title", "")),
        ]
        if any(c.lower() in content_lower for c in candidates if c):
            count += 1
    return count


def _deterministic_review(
    draft: dict[str, Any],
    context: dict[str, Any],
    role: str,
) -> dict[str, Any]:
    """纯确定性审核 —— 不调 LLM，基于句级来源重叠 + 显式引用计数。

    这是 fixture 的高精度版本，也用作交叉验证的基准线。
    """
    content = str(draft.get("content", ""))
    sources = list(context.get("sources") or [])
    source_texts = [str(s.get("content", "")) for s in sources]
    requirements = context.get("generation_requirements") or {}
    draft_sources = draft.get("sources") or []

    # ---- 1. 来源可追溯评分（句级重叠） ----
    sentences = _split_sentences(content)
    if sentences:
        supported_sentences = sum(
            1 for sent in sentences if _has_source_overlap(sent, source_texts)
        )
        source_trace_score = min(100, round(supported_sentences / len(sentences) * 100))
    else:
        source_trace_score = 0 if not source_texts else 100  # 无内容 → 0；无来源 → N/A=100

    # ---- 2. 显式引用检查 ----
    declared_count = len(draft_sources)
    matched_count = _count_explicit_refs(content, sources)
    ref_ratio = min(1.0, matched_count / max(declared_count, 1))

    # ---- 3. 事实准确评分 ----
    # 综合句级重叠 + 显式引用
    if source_trace_score >= 90 and ref_ratio >= 0.8:
        factual_score = min(100, source_trace_score)
    elif source_trace_score >= 70:
        factual_score = min(85, source_trace_score)
    elif source_trace_score >= 50:
        factual_score = max(50, source_trace_score - 10)
    else:
        factual_score = max(30, source_trace_score)

    # ---- 4. 难度匹配评分 ----
    expected = int(requirements.get("difficulty") or 1)
    actual = int(draft.get("difficulty") or 0)
    diff = abs(actual - expected)
    difficulty_score = {0: 95, 1: 80, 2: 60}.get(diff, 40)

    # ---- 5. 知识覆盖评分（策略相关，双语） ----
    strategy = str(requirements.get("strategy", "consolidation"))
    coverage_keywords: dict[str, list[str]] = {
        "remedial": [
            "前置知识", "基础", "误区", "入门", "prerequisite", "basic",
            "fundamental", "common mistake", "remedial", "beginner",
        ],
        "challenge": [
            "挑战", "扩展", "综合", "进阶", "challenge", "advanced",
            "comprehensive", "extension", "expert",
        ],
        "consolidation": [
            "巩固", "练习", "示例", "小结", "检查", "practice", "exercise",
            "example", "summary", "consolidation", "review",
        ],
    }
    keywords = coverage_keywords.get(strategy, coverage_keywords["consolidation"])
    content_lower = content.lower()
    hits = sum(1 for kw in keywords if kw.lower() in content_lower)
    coverage_score = min(100, 50 + hits * 12)  # 每命中一个关键词 +12 分，基础 50

    # ---- 6. 综合裁决 ----
    passed = (
        factual_score >= FACTUAL_THRESHOLD
        and source_trace_score >= SOURCE_THRESHOLD
        and difficulty_score >= DIFFICULTY_THRESHOLD
        and coverage_score >= COVERAGE_THRESHOLD
    )

    # 构建 fact_checks
    fact_checks: list[dict[str, Any]] = []
    for i, sent in enumerate(sentences[:6]):
        supported = _has_source_overlap(sent, source_texts)
        supporting_ids = [
            str(s.get("knowledge_id", ""))
            for s in sources
            if _has_source_overlap(sent, [str(s.get("content", ""))])
        ]
        fact_checks.append({
            "claim": sent[:200],
            "supported": supported,
            "source_ids": supporting_ids[:3],
            "reason": (
                "deterministic: sentence matches source content"
                if supported
                else "deterministic: no source overlap found"
            ),
            "determinable": True,
        })

    if not fact_checks:
        fact_checks.append({
            "claim": "（内容为空或无法解析为句子）",
            "supported": False,
            "source_ids": [],
            "reason": "deterministic: no parseable content",
            "determinable": True,
        })

    unsupported = [fc["claim"] for fc in fact_checks if fc["supported"] is False]

    return {
        "model_role": role,
        "factual_score": factual_score,
        "source_trace_score": source_trace_score,
        "difficulty_match_score": difficulty_score,
        "coverage_score": coverage_score,
        "passed": passed,
        "issues": (
            []
            if passed
            else [
                f"来源可追溯度 {source_trace_score}（需 ≥{SOURCE_THRESHOLD}）",
                f"显式引用 {matched_count}/{declared_count}",
                f"难度偏差 {diff} 级",
                f"策略覆盖 {coverage_score}（需 ≥{COVERAGE_THRESHOLD}）",
            ]
        ),
        "evidence_refs": [str(s.get("knowledge_id", "")) for s in sources[:8]],
        "fact_checks": fact_checks,
        "unsupported_claims": unsupported,
        "verified_claim_count": len(fact_checks) - len(unsupported),
        "source_coverage": source_trace_score,
        "unable_to_determine": [],
        "provider_mode": "deterministic",
    }


# ===========================================================================
# 交叉验证：LLM 评分 vs 确定性评分
# ===========================================================================

def _cross_validate(
    model_review: dict[str, Any],
    deterministic: dict[str, Any],
    role: str,
    valid_source_ids: set[str] | None = None,
) -> dict[str, Any]:
    """比对 LLM 评分与确定性评分，差异过大时标记并降权。

    Args:
        model_review: LLM 返回的审核结果
        deterministic: 确定性引擎计算的基准分
        role: 审查视角名称
        valid_source_ids: 合法的 knowledge_id 集合（用于过滤 LLM 编造的 ID）

    Returns:
        如果差异可接受 → 返回 model_review（不变）
        如果差异过大    → 返回 model_review 但附加 warning + 向确定性靠拢
    """
    warnings: list[str] = []
    adjusted = dict(model_review)

    score_pairs = [
        ("factual_score", "factual_score"),
        ("source_trace_score", "source_trace_score"),
        ("difficulty_match_score", "difficulty_match_score"),
        ("coverage_score", "coverage_score"),
    ]

    big_gaps = 0
    for model_key, det_key in score_pairs:
        model_val = float(model_review.get(model_key, 0))
        det_val = float(deterministic.get(det_key, 0))
        delta = abs(model_val - det_val)
        if delta > CROSS_CHECK_MAX_DELTA:
            big_gaps += 1
            warnings.append(
                f"[{role}] {model_key}: LLM={model_val} vs DET={det_val} (Δ={delta:.0f})"
            )

    if big_gaps >= 2:
        # 两个以上维度差异过大 → LLM 评审可能不可靠，向确定性靠拢
        logger.warning(
            "Cross-validation flag: %s has %d dimensions with large delta. "
            "Blending toward deterministic scores. Warnings: %s",
            role, big_gaps, warnings,
        )
        llm_weight = max(0.3, 1.0 - big_gaps * 0.25)
        det_weight = 1.0 - llm_weight
        for model_key, det_key in score_pairs:
            model_val = float(model_review.get(model_key, 0))
            det_val = float(deterministic.get(det_key, 0))
            adjusted[model_key] = round(model_val * llm_weight + det_val * det_weight)

        # 重新判定 passed
        adjusted["passed"] = (
            adjusted.get("factual_score", 0) >= FACTUAL_THRESHOLD
            and adjusted.get("source_trace_score", 0) >= SOURCE_THRESHOLD
            and adjusted.get("difficulty_match_score", 0) >= DIFFICULTY_THRESHOLD
            and adjusted.get("coverage_score", 0) >= COVERAGE_THRESHOLD
        )
        adjusted.setdefault("issues", [])
        if isinstance(adjusted["issues"], list):
            adjusted["issues"].append(
                f"交叉验证警告：{big_gaps} 个维度与确定性评分偏差 >{CROSS_CHECK_MAX_DELTA}，已自动修正"
            )

    # 校验 fact_checks 中的 source_ids 是否真实存在
    # （DeepSeek 偶尔编造 source_id）
    if valid_source_ids:
        for fc in adjusted.get("fact_checks", []):
            if isinstance(fc, dict):
                fc["source_ids"] = [
                    sid for sid in fc.get("source_ids", [])
                    if str(sid) in valid_source_ids
                ]

    return adjusted


# ===========================================================================
# DeepSeek 结构适配器
# ===========================================================================

def _normalize_deepseek_review_structure(result: dict[str, Any]) -> dict[str, Any]:
    """在 Pydantic 校验前规范化各种 LLM 的 JSON 格式漂移。

    处理:
    - 嵌套容器（``{"review": {...}}`` 等）
    - 数字写成字符串（``"90"`` → ``90``）
    - 布尔写成字符串（``"true"`` → ``True``）
    - content 写成数组
    - 缺失字段补默认值
    """
    normalized = dict(result)

    # -- 1. 解包嵌套容器 ---------------------------------------------------
    for key in ("review", "result", "data", "resource", "output", "review_result",
                "review_data", "assessment", "evaluation"):
        inner = normalized.get(key)
        if isinstance(inner, dict):
            for k, v in inner.items():
                if k not in normalized or normalized[k] in (None, "", [], {}):
                    normalized[k] = v
            break

    # -- 2. 数字字段规范化 --------------------------------------------------
    _int_fields = (
        "factual_score", "source_trace_score", "difficulty_match_score",
        "coverage_score", "source_coverage", "verified_claim_count",
        "factual_accuracy", "source_traceability", "difficulty_match",
        "core_knowledge_coverage", "overall_score",
    )
    for field in _int_fields:
        val = normalized.get(field)
        if isinstance(val, str):
            cleaned = val.strip().rstrip('%')
            try:
                normalized[field] = int(float(cleaned))
            except ValueError:
                try:
                    normalized[field] = float(cleaned)
                except ValueError:
                    normalized.pop(field, None)
        elif isinstance(val, float):
            if field in ("verified_claim_count",):
                normalized[field] = int(val)
            elif val == int(val):
                normalized[field] = int(val)

    # -- 3. 布尔字段规范化 --------------------------------------------------
    if "passed" in normalized and isinstance(normalized["passed"], str):
        v = normalized["passed"].strip().lower()
        normalized["passed"] = v in ("true", "yes", "1", "pass", "y")

    # -- 4. fact_checks 保证为数组 -----------------------------------------
    raw_fc = normalized.get("fact_checks")
    if raw_fc is None:
        normalized["fact_checks"] = []
    elif isinstance(raw_fc, dict):
        normalized["fact_checks"] = [raw_fc]
    elif not isinstance(raw_fc, list):
        normalized["fact_checks"] = []

    for fc in normalized.get("fact_checks", []):
        if not isinstance(fc, dict):
            continue
        # source_ids: 单值 → 列表
        sid = fc.get("source_ids")
        if isinstance(sid, str):
            fc["source_ids"] = [sid] if sid else []
        elif not isinstance(sid, list):
            fc["source_ids"] = []
        # determinable: 字符串 → 布尔
        if isinstance(fc.get("determinable"), str):
            fc["determinable"] = fc["determinable"].strip().lower() in ("true", "yes", "1")
        # supported: 字符串 → 布尔
        if isinstance(fc.get("supported"), str):
            fc["supported"] = fc["supported"].strip().lower() in ("true", "yes", "1")

    # -- 5. 数组字段保证 ----------------------------------------------------
    for field in ("issues", "evidence_refs", "unsupported_claims", "unable_to_determine"):
        val = normalized.get(field)
        if val is None:
            normalized[field] = []
        elif isinstance(val, str):
            normalized[field] = [val] if val else []
        elif not isinstance(val, list):
            normalized[field] = []

    # -- 6. 缺失字段补默认值 ------------------------------------------------
    defaults = {
        "factual_score": 0, "source_trace_score": 0,
        "difficulty_match_score": 0, "coverage_score": 0,
        "source_coverage": 0, "verified_claim_count": 0,
        "passed": False, "issues": [], "evidence_refs": [],
        "fact_checks": [], "unsupported_claims": [], "unable_to_determine": [],
    }
    for k, v in defaults.items():
        if k not in normalized:
            normalized[k] = v

    return normalized


# ===========================================================================
# 通用工具
# ===========================================================================

def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _normalize_model_review_payload(result: dict[str, Any]) -> dict[str, Any]:
    """规范化列表字段：单值 → 数组。"""
    normalized = dict(result)
    for field in ("issues", "evidence_refs", "unsupported_claims", "unable_to_determine"):
        normalized[field] = _as_list(normalized.get(field))
    fact_checks: list[dict[str, Any]] = []
    for item in _as_list(normalized.get("fact_checks")):
        if not isinstance(item, dict):
            continue
        fc = dict(item)
        fc["source_ids"] = [str(v) for v in _as_list(fc.get("source_ids"))]
        fact_checks.append(fc)
    normalized["fact_checks"] = fact_checks
    return normalized


def _adapt_review_response(result: dict[str, Any]) -> dict[str, Any]:
    """完整适配链：结构规范化 → 字段规范化。"""
    result = _normalize_deepseek_review_structure(result)
    result = _normalize_model_review_payload(result)
    return result


def _average(review: ModelReview) -> float:
    return sum((
        review.factual_score,
        review.source_trace_score,
        review.difficulty_match_score,
        review.coverage_score,
    )) / 4


# ===========================================================================
# Payload 构建 & 双视角 Prompt
# ===========================================================================

_PERSPECTIVE_INSTRUCTIONS: dict[str, str] = {
    "primary_review_model": (
        "## 你的角色：严格的事实核查员\n\n"
        "你是**事实准确性**和**来源可追溯性**的守门人。你的审查必须严格、精确、有据可查。\n\n"
        "### 审查流程\n"
        "1. 逐条阅读资源中的关键论断\n"
        "2. 在「检索到的知识来源」中寻找每条论断的依据\n"
        "3. 找不到依据的论断 → unsupported\n"
        "4. 不确定的 → unable_to_determine\n\n"
        "### 评分准则\n"
        "- factual_score: 有依据的论断占比 × 100\n"
        "- source_trace_score: 显式标注了来源的论断占比 × 100\n"
        "- 任何编造、臆测、超出来源范围的内容 → 严重扣分\n"
        "- **宁严勿宽**：不确定就是不确定，不要猜测\n\n"
        "### 输出前自查\n"
        "1. fact_checks 中每个 claim 是否真的在来源中存在？\n"
        "2. source_ids 是否全部来自输入的 retrieved_sources？\n"
        "3. 如果没有足够证据 → passed 必须是 false\n"
        "4. 所有数字字段必须是数字类型，不是字符串\n"
    ),
    "secondary_review_model": (
        "## 你的角色：教学适用性评估员\n\n"
        "你是**教学效果**和**学习者适配性**的评估专家。你的审查关注资源是否真能帮助学习者。\n\n"
        "### 审查流程\n"
        "1. 评估资源难度是否匹配目标学习者水平\n"
        "2. 检查知识覆盖是否全面、结构是否合理\n"
        "3. 判断教学模式是否符合策略要求（remedial/consolidation/challenge）\n"
        "4. 提出**建设性**的改进建议\n\n"
        "### 评分准则\n"
        "- difficulty_match_score: 难度精确匹配=95，偏差1级=80，偏差2级=60\n"
        "- coverage_score: 覆盖了策略要求的所有要素=95+，缺少关键要素则扣分\n"
        "- 内容太简单或太难都是问题\n"
        "- **建设性反馈**：指出问题同时给出改进方向\n\n"
        "### 输出前自查\n"
        "1. 评分是否和 issues 中的反馈一致？\n"
        "2. 如果指出问题但给了高分 → 矛盾，修正评分\n"
        "3. 所有数字字段必须是数字类型，不是字符串\n"
    ),
}


def _model_payload(
    draft: dict[str, Any], context: dict[str, Any], *, recheck: bool, role: str
) -> dict[str, Any]:
    perspective = _PERSPECTIVE_INSTRUCTIONS.get(
        role, _PERSPECTIVE_INSTRUCTIONS["primary_review_model"]
    )
    return {
        "review_instructions": perspective,
        "review_context": {
            "perspective_role": role,
            "is_recheck": recheck,
            "recheck_note": (
                "这是第二轮审核。请特别关注初轮审核中指出的问题是否已修复。"
                if recheck else ""
            ),
        },
        "resource_under_review": {
            "resource_type": draft.get("resource_type"),
            "title": draft.get("title", ""),
            "difficulty": draft.get("difficulty"),
            "content": str(draft.get("content", "")),
            "declared_sources": draft.get("sources", []),
        },
        "learner_profile": context.get("profile", {}),
        "target_requirements": {
            "difficulty": (context.get("generation_requirements") or {}).get("difficulty", 1),
            "strategy": (context.get("generation_requirements") or {}).get("strategy", "consolidation"),
        },
        "retrieved_sources": [
            {
                "knowledge_id": str(s.get("knowledge_id", "")),
                "name": str(s.get("name", "")),
                "content": str(s.get("content", "")),
                "source_title": str(s.get("source_title", "")),
            }
            for s in (context.get("sources") or [])
        ],
        "output_schema": ModelReview.model_json_schema(),
    }


# ===========================================================================
# Review Agent
# ===========================================================================

class ReviewValidationAgent(BaseAgent):
    """双视角 + 确定性交叉验证审核智能体。

    - 两个 LLM 视角独立审核（事实核查员 / 教学评估员）
    - 确定性验证引擎并行计算基准分
    - LLM 评分与基准分交叉比对，差异过大时自动修正
    - LLM 不可用时降级为确定性评分
    """

    name = REVIEW_AGENT_NAME
    system_prompt_path = "app/agents/prompts/review_agent.md"

    # ------------------------------------------------------------------
    # V1 接口
    # ------------------------------------------------------------------

    async def run(self, message: AgentMessage) -> dict[str, Any]:
        return {
            "agent_name": self.name,
            "status": "ready",
            "payload_keys": sorted(message.payload.keys()),
        }

    # ------------------------------------------------------------------
    # 单通道 LLM 调用（含降级 + 交叉验证）
    # ------------------------------------------------------------------

    def _call_channel(
        self,
        *,
        role: str,
        model: str | None,
        draft: dict[str, Any],
        context: dict[str, Any],
        conflict_mode: str | None,
        recheck: bool,
        det_scores: dict[str, Any] | None = None,
    ) -> tuple[ModelReview, dict[str, Any]]:
        payload = _model_payload(draft, context, recheck=recheck, role=role)
        budget = PromptBudget(10_000, 3_000).validate(str(payload))

        # 确定性评分作为 fixture 和交叉验证基准
        if det_scores is None:
            det_scores = _deterministic_review(draft, context, role)

        result, metadata = gateway.complete_json(
            model=model,
            system_prompt=self.system_prompt(),
            payload=payload,
            fixture_factory=lambda: det_scores,  # 降级时直接用确定性评分
            response_model=ModelReview,
            response_adapter=_adapt_review_response,
        )

        # 如果是 live 模式，做交叉验证
        if metadata.get("provider_mode") == "live":
            valid_ids = set(
                str(s.get("knowledge_id", ""))
                for s in (context.get("sources") or [])
            )
            result = _cross_validate(result, det_scores, role, valid_source_ids=valid_ids)

        result["model_role"] = role
        result["provider_mode"] = metadata["provider_mode"]
        return ModelReview.model_validate(result), {
            **metadata,
            "model_role": role,
            "budget": budget,
        }

    # ------------------------------------------------------------------
    # 双视角审查
    # ------------------------------------------------------------------

    def _review_pair(
        self,
        draft: dict[str, Any],
        context: dict[str, Any],
        conflict_mode: str | None,
        *,
        recheck: bool,
    ) -> tuple[ModelReview, ModelReview, list[dict[str, Any]]]:
        """并行调用两个审查视角。

        先计算确定性基准分（只算一次，两个视角共享），
        然后两个 LLM 视角各自审查并交叉验证。
        """
        # 确定性基准分（两个视角共用，只算一次）
        det_primary = _deterministic_review(draft, context, "primary_review_model")
        det_secondary = _deterministic_review(draft, context, "secondary_review_model")

        calls = (
            ("primary_review_model", settings.primary_review_model, det_primary),
            ("secondary_review_model", settings.secondary_review_model, det_secondary),
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    self._call_channel,
                    role=role,
                    model=model,
                    draft=draft,
                    context=context,
                    conflict_mode=conflict_mode,
                    recheck=recheck,
                    det_scores=det,
                )
                for role, model, det in calls
            ]
            results = [future.result() for future in futures]
        return results[0][0], results[1][0], [results[0][1], results[1][1]]

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def execute(self, state: AgentGraphState) -> dict[str, Any]:
        context = state.get("generation_context") or build_generation_context(state)
        conflict_mode = state.get("force_review_conflict")
        reports: list[dict[str, Any]] = []
        all_model_calls: list[dict[str, Any]] = []

        for draft in state.get("draft_resources", []):
            # ---- 第一轮：双视角独立审查 ----
            primary, secondary, calls = self._review_pair(
                draft, context, conflict_mode, recheck=False
            )
            all_model_calls.extend(calls)

            disagreement = abs(_average(primary) - _average(secondary)) > 10 or (
                primary.passed != secondary.passed
            )

            arbitration: dict[str, Any] = {
                "required": disagreement,
                "initial_scores": {
                    "primary": primary.model_dump(),
                    "secondary": secondary.model_dump(),
                },
                "retrieved_evidence_refs": [],
                "recheck_scores": None,
            }

            final_primary, final_secondary = primary, secondary

            if disagreement:
                arbitration["action"] = "retrieve_sources_and_recheck"
                arbitration["retrieved_evidence_refs"] = [
                    item.get("knowledge_id") for item in context.get("sources", [])
                ]
                final_primary, final_secondary, recheck_calls = self._review_pair(
                    draft, context, conflict_mode, recheck=True
                )
                all_model_calls.extend(recheck_calls)
                arbitration["recheck_scores"] = {
                    "primary": final_primary.model_dump(),
                    "secondary": final_secondary.model_dump(),
                }

            # ---- 最终裁决 ----
            persistent_disagreement = abs(
                _average(final_primary) - _average(final_secondary)
            ) > 10 or final_primary.passed != final_secondary.passed
            manual_review_required = disagreement and persistent_disagreement

            factual = min(final_primary.factual_score, final_secondary.factual_score)
            source = min(final_primary.source_trace_score, final_secondary.source_trace_score)
            difficulty = min(
                final_primary.difficulty_match_score, final_secondary.difficulty_match_score
            )
            coverage = min(final_primary.coverage_score, final_secondary.coverage_score)

            passed = (
                final_primary.passed and final_secondary.passed and not manual_review_required
            )
            failed = source == 0 or difficulty < 50

            decision = (
                "manual_review_required"
                if manual_review_required
                else "passed"
                if passed
                else "rejected"
                if failed
                else "revision_required"
            )

            reports.append({
                "resource_type": draft.get("resource_type"),
                "factual_accuracy": factual,
                "source_traceability": source,
                "difficulty_match": difficulty,
                "core_knowledge_coverage": coverage,
                "overall_score": round((factual + source + difficulty + coverage) / 4, 1),
                "primary_review": primary.model_dump(),
                "secondary_review": secondary.model_dump(),
                "arbitration": arbitration,
                "passed": passed,
                "manual_review_required": manual_review_required,
                "decision": decision,
                "revision_required": decision == "revision_required",
                "failure_level": "failed" if failed else "revision" if not passed else "none",
                "review_notes": [*final_primary.issues, *final_secondary.issues],
            })

        if not reports:
            reports.append({
                "resource_type": None,
                "factual_accuracy": 0,
                "source_traceability": 0,
                "difficulty_match": 0,
                "core_knowledge_coverage": 0,
                "overall_score": 0,
                "passed": False,
                "manual_review_required": False,
                "decision": "rejected",
                "revision_required": False,
                "failure_level": "failed",
                "review_notes": ["没有可审核的草稿资源。"],
            })

        return ReviewOutput(
            review_reports=reports,
            trace={
                "passed": all(r.get("passed") for r in reports),
                "report_count": len(reports),
                "revision_required_count": sum(
                    1 for r in reports if r.get("revision_required")
                ),
                "failed_count": sum(
                    1 for r in reports if r.get("failure_level") == "failed"
                ),
                "manual_review_required": any(
                    r.get("manual_review_required") for r in reports
                ),
                "average_score": round(
                    sum(r.get("overall_score", 0) for r in reports) / max(len(reports), 1), 1
                ),
                "resource_reviews": reports,
                "model_calls": all_model_calls,
            },
        ).model_dump()


# ---------------------------------------------------------------------------
# 兼容性辅助
# ---------------------------------------------------------------------------

def review_draft_resource(
    draft: dict[str, Any], generation_context: dict[str, Any]
) -> dict[str, Any]:
    """测试用兼容辅助。"""
    output = ReviewValidationAgent().execute({
        "draft_resources": [draft],
        "generation_context": generation_context,
    })
    return output["review_reports"][0]
