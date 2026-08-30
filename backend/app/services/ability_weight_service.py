from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.agents.profile_analysis_config import ABILITY_DIMENSIONS


MIN_MODEL_WEIGHT_CONFIDENCE = 0.75


def normalize_ability_weights(value: object) -> dict[str, float] | None:
    if not isinstance(value, Mapping) or set(value) != set(ABILITY_DIMENSIONS):
        return None
    try:
        weights = {key: float(value[key]) for key in ABILITY_DIMENSIONS}
    except (TypeError, ValueError):
        return None
    if any(weight < 0 or weight > 1 for weight in weights.values()):
        return None
    if abs(weights["learning_speed"]) > 1e-9:
        return None
    if abs(sum(weights[key] for key in ABILITY_DIMENSIONS[:-1]) - 1) > 1e-6:
        return None
    return weights


def ability_weight_gate(payload: Mapping[str, Any]) -> list[str]:
    weights = normalize_ability_weights(payload.get("ability_weights"))
    if weights is None:
        return ["能力权重不合法或缺失"]
    source = str(payload.get("ability_weight_source") or "")
    if source not in {"explicit", "model", "admin"}:
        return ["能力权重缺少可追溯来源"]
    try:
        confidence = float(payload.get("ability_weight_confidence"))
    except (TypeError, ValueError):
        return ["能力权重置信度缺失"]
    if not 0 <= confidence <= 1:
        return ["能力权重置信度不合法"]
    if source == "model" and confidence < MIN_MODEL_WEIGHT_CONFIDENCE:
        return ["模型生成的能力权重置信度不足"]
    return []
