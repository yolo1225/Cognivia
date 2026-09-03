"""Versioned, deterministic configuration for profile analysis.

This module intentionally contains configuration only. The Profile Analysis
Agent will consume it in a later phase; no V1 runtime path imports this module.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from math import isclose
from pathlib import Path
from typing import Mapping

from app.agents.runtime_limits import MAX_EVIDENCE_CHUNKS


ABILITY_DIMENSIONS = (
    "theory",
    "practice",
    "problem_solving",
    "knowledge_breadth",
    "learning_speed",
)


@dataclass(frozen=True)
class ProfileAnalysisConfig:
    version: str
    seed_sha256: str
    prior_mastery: float
    prior_weight: float
    mastery_thresholds: tuple[float, float, float]
    minimum_effective_change: int
    max_ability_change_per_update: int
    max_weakness_level_change_per_update: int
    default_n_results: int
    multi_priority_remedial_n_results: int
    maximum_n_results: int
    ability_weights: Mapping[str, Mapping[str, float]]
    knowledge_catalog: Mapping[str, "KnowledgeProfileMetadata"]
    mastery_baselines: Mapping[str, float]
    minimum_category_coverage_for_practice_oriented: int = 3
    # Subsequent revisions use a deliberately slower evidence policy than the
    # initial diagnostic batch.  These values are product rules, not Agent
    # contract fields, so they can evolve without changing V10.
    subsequent_rule_version: str = "profile-evidence-v2"
    knowledge_min_distinct_questions: int = 2
    knowledge_min_effective_weight: float = 1.4
    ability_min_new_knowledge: int = 2
    ability_min_score_delta: int = 5
    breadth_min_new_knowledge: int = 2
    initial_diagnostic_min_answers: int = 10

    def difficulty_weight(self, difficulty: int) -> float:
        if difficulty < 1 or difficulty > 5:
            raise ValueError("difficulty must be between 1 and 5")
        return 1 + 0.15 * (difficulty - 3)


@dataclass(frozen=True)
class KnowledgeProfileMetadata:
    name: str
    category: str
    prerequisite_ids: tuple[str, ...]


AI_APP_DEV_PROFILE_V2_SEED_SHA256 = (
    "d3688e028c74927b84f946d64e0733508ef6b5bf5df91416e900e7d35a8a4e4b"
)
MASTERY_BASELINES = {
    "known": 0.90,
    "partial_mastery": 0.70,
    "confused": 0.50,
    "unmastered": 0.20,
    "unassessed": 0.50,
}


def _seed_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "seed" / "knowledge_items.json"


def _load_knowledge_catalog(
    *, expected_seed_sha256: str
) -> tuple[dict[str, KnowledgeProfileMetadata], dict[str, dict[str, float]], str]:
    seed_bytes = _seed_path().read_bytes()
    payload = json.loads(seed_bytes.decode("utf-8"))
    canonical_seed = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    seed_sha256 = hashlib.sha256(canonical_seed).hexdigest()
    if seed_sha256 != expected_seed_sha256:
        raise ValueError(
            "ai_app_dev profile configuration fingerprint mismatch; "
            "create a new configuration version and re-review fixtures"
        )
    catalog = {
        item["knowledge_id"]: KnowledgeProfileMetadata(
            name=item["name"],
            category=item["category"],
            prerequisite_ids=tuple(item.get("prerequisites", [])),
        )
        for item in payload
    }
    ability_weights = {
        item["knowledge_id"]: {
            dimension: float(item["ability_weights"][dimension])
            for dimension in ABILITY_DIMENSIONS
        }
        for item in payload
    }
    return catalog, ability_weights, seed_sha256


def validate_ai_app_dev_profile_config(
    knowledge_ids: set[str], config: ProfileAnalysisConfig
) -> None:
    mapped_ids = set(config.ability_weights)
    if mapped_ids != knowledge_ids:
        missing = sorted(knowledge_ids - mapped_ids)
        unknown = sorted(mapped_ids - knowledge_ids)
        raise ValueError(f"ability mapping mismatch: missing={missing}, unknown={unknown}")
    if set(config.knowledge_catalog) != knowledge_ids:
        raise ValueError("knowledge catalog does not match seed knowledge IDs")
    for knowledge_id, metadata in config.knowledge_catalog.items():
        if not metadata.name or not metadata.category:
            raise ValueError(f"{knowledge_id} has incomplete catalog metadata")
        if any(
            prerequisite_id not in knowledge_ids for prerequisite_id in metadata.prerequisite_ids
        ):
            raise ValueError(f"{knowledge_id} has an unknown prerequisite")
    for knowledge_id, weights in config.ability_weights.items():
        if set(weights) != set(ABILITY_DIMENSIONS):
            raise ValueError(f"{knowledge_id} does not define every ability dimension")
        if any(weight < 0 for weight in weights.values()):
            raise ValueError(f"{knowledge_id} contains a negative ability weight")
        if not isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
            raise ValueError(f"{knowledge_id} ability weights must sum to 1")
    if set(config.mastery_baselines) != {
        "known",
        "partial_mastery",
        "confused",
        "unmastered",
        "unassessed",
    }:
        raise ValueError("mastery baselines must cover every mastery type")


def load_ai_app_dev_profile_v2() -> ProfileAnalysisConfig:
    catalog, ability_weights, seed_sha256 = _load_knowledge_catalog(
        expected_seed_sha256=AI_APP_DEV_PROFILE_V2_SEED_SHA256
    )
    config = ProfileAnalysisConfig(
        version="ai_app_dev_profile_v2",
        seed_sha256=seed_sha256,
        prior_mastery=0.5,
        prior_weight=1.0,
        mastery_thresholds=(0.40, 0.60, 0.80),
        minimum_effective_change=5,
        max_ability_change_per_update=10,
        max_weakness_level_change_per_update=1,
        default_n_results=12,
        multi_priority_remedial_n_results=15,
        maximum_n_results=MAX_EVIDENCE_CHUNKS,
        ability_weights=ability_weights,
        knowledge_catalog=catalog,
        mastery_baselines=MASTERY_BASELINES,
    )
    validate_ai_app_dev_profile_config(set(catalog), config)
    return config


AI_APP_DEV_PROFILE_V2 = load_ai_app_dev_profile_v2()
