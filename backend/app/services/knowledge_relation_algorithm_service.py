from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any

from app.models import KnowledgeImportCandidate


_NUMBER_PREFIX = re.compile(r"^\s*\d+(?:\.\d+)*[.、\s]+")
_DEPENDENCY_CUES = (
    "需要先", "前提", "基于", "依赖", "建立在", "掌握后", "理解后",
    "用于解决", "核心改进", "整合了", "基石", "基础",
)
_ROLE_ORDER = {
    "definition": 0,
    "mechanism": 1,
    "tool": 2,
    "application": 3,
    "troubleshooting": 4,
}


def display_name(payload: dict[str, Any]) -> str:
    return _NUMBER_PREFIX.sub("", str(payload.get("name") or "")).strip()


def pedagogic_role(payload: dict[str, Any]) -> str:
    text = f"{payload.get('name', '')} {str(payload.get('content') or '')[:500]}".lower()
    if any(token in text for token in ("错误", "异常", "排查", "调试", "故障")):
        return "troubleshooting"
    if any(token in text for token in ("应用", "场景", "实践", "实现", "使用")):
        return "application"
    if any(token in text for token in ("工具", "框架", "算法", "方法", "模型")):
        return "tool"
    if any(token in text for token in ("机制", "原理", "过程", "工作流")):
        return "mechanism"
    return "definition"


def _lexical_tokens(payload: dict[str, Any]) -> set[str]:
    tags = {str(tag).casefold() for tag in payload.get("tags") or [] if str(tag).strip()}
    name = display_name(payload).casefold()
    latin = set(re.findall(r"[a-z0-9][a-z0-9+_.-]{1,}", name))
    chinese = {name[index:index + 2] for index in range(max(0, len(name) - 1))}
    return tags | latin | chinese


def _cosine(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _sentence_with_mention(text: str, name: str) -> str | None:
    for sentence in re.split(r"(?<=[。！？!?；;])\s*", text):
        if name and name.casefold() in sentence.casefold() and any(cue in sentence for cue in _DEPENDENCY_CUES):
            return sentence.strip()[:300]
    return None


def _rank(payload: dict[str, Any]) -> tuple[int, int, str]:
    role = pedagogic_role(payload)
    return (
        int(payload.get("difficulty") or 2),
        _ROLE_ORDER[role],
        display_name(payload).casefold(),
    )


def build_relation_plan(
    knowledge: list[KnowledgeImportCandidate],
    *,
    vectors: dict[str, list[float]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build a short, branching curriculum forest plus evidence-bound fact pairs."""
    payloads = {item.public_id: item.payload_json or {} for item in knowledge}
    vectors = vectors or {}
    tokens = {item_id: _lexical_tokens(payload) for item_id, payload in payloads.items()}
    groups: dict[str, list[str]] = defaultdict(list)
    for item_id, payload in payloads.items():
        groups[str(payload.get("category") or "综合学习")].append(item_id)

    deterministic: list[dict[str, Any]] = []
    outdegree: dict[str, int] = defaultdict(int)
    depth: dict[str, int] = defaultdict(int)
    used_pairs: set[frozenset[str]] = set()

    # A maximum-score branching forest is intentionally used instead of a
    # document-order chain. Each module remains shallow and explainable.
    for category, item_ids in sorted(groups.items()):
        ordered = sorted(item_ids, key=lambda item_id: _rank(payloads[item_id]))
        for position, target_id in enumerate(ordered[1:], start=1):
            target = payloads[target_id]
            eligible = [
                source_id for source_id in ordered[:position]
                if outdegree[source_id] < 4 and depth[source_id] < 7
            ] or ordered[:position]
            scored: list[tuple[float, str, dict[str, float]]] = []
            for source_id in eligible:
                source = payloads[source_id]
                semantic = max(
                    _cosine(vectors.get(source_id), vectors.get(target_id)),
                    _jaccard(tokens[source_id], tokens[target_id]),
                )
                tag_score = _jaccard(
                    {str(tag).casefold() for tag in source.get("tags") or []},
                    {str(tag).casefold() for tag in target.get("tags") or []},
                )
                difficulty = 1.0 if abs(_rank(source)[0] - _rank(target)[0]) <= 1 else 0.0
                role_order = 1.0 if _rank(source)[1] <= _rank(target)[1] else 0.0
                components = {
                    "semantic": round(semantic, 4),
                    "same_category": 1.0,
                    "tag_overlap": round(tag_score, 4),
                    "difficulty_progression": difficulty,
                    "pedagogic_role_order": role_order,
                }
                score = (
                    semantic * 0.45 + 0.20 + tag_score * 0.15
                    + difficulty * 0.10 + role_order * 0.10
                )
                scored.append((score, source_id, components))
            score, source_id, components = max(scored, key=lambda value: (value[0], value[1]))
            pair_key = frozenset((source_id, target_id))
            if pair_key in used_pairs:
                continue
            used_pairs.add(pair_key)
            outdegree[source_id] += 1
            depth[target_id] = depth[source_id] + 1
            deterministic.append({
                "source_id": source_id,
                "target_id": target_id,
                "relation_type": "next_step",
                "confidence": round(max(0.7, min(0.95, score)), 4),
                "reason": f"同一知识模块“{category}”内的教学推荐顺序",
                "source_quote": str(payloads[source_id].get("source_quote") or "")[:300],
                "evidence_kind": "curriculum_rule",
                "score_components": components,
            })

    # Only pairs with an exact named mention and a dependency cue are sent to
    # the model as possible factual relationships.
    model_pairs: list[dict[str, Any]] = []
    pair_index = 0
    for source_id, source in payloads.items():
        source_text = str(source.get("content") or "")
        for target_id, target in payloads.items():
            if source_id == target_id:
                continue
            quote = _sentence_with_mention(source_text, display_name(target))
            if not quote:
                continue
            pair_key = frozenset((source_id, target_id))
            if pair_key in used_pairs:
                continue
            used_pairs.add(pair_key)
            pair_index += 1
            model_pairs.append({
                "pair_id": f"pair_{pair_index:04d}",
                "source_id": source_id,
                "target_id": target_id,
                "source_name": display_name(source),
                "target_name": display_name(target),
                "evidence_spans": [{"id": "span_1", "text": quote}],
            })
    return deterministic, model_pairs
