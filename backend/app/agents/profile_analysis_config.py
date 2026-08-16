"""Versioned, deterministic configuration for the V3 profile-analysis algorithm.

This module intentionally contains configuration only.  The V3 Profile Analysis
Agent will consume it in a later phase; no V1 runtime path imports this module.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from math import isclose
from pathlib import Path
from typing import Mapping


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

    def difficulty_weight(self, difficulty: int) -> float:
        if difficulty < 1 or difficulty > 5:
            raise ValueError("difficulty must be between 1 and 5")
        return 1 + 0.15 * (difficulty - 3)


@dataclass(frozen=True)
class KnowledgeProfileMetadata:
    name: str
    category: str
    prerequisite_ids: tuple[str, ...]


def _weights(
    theory: float, practice: float, problem_solving: float, breadth: float
) -> dict[str, float]:
    return {
        "theory": theory,
        "practice": practice,
        "problem_solving": problem_solving,
        "knowledge_breadth": breadth,
        # Learning speed is derived from longitudinal behaviour, never one item score.
        "learning_speed": 0.0,
    }


# Every ID comes from data/seed/knowledge_items.json.  Keep this explicit so a
# new knowledge item cannot silently acquire a guessed ability mapping.
AI_APP_DEV_ABILITY_WEIGHTS: dict[str, dict[str, float]] = {
    "ai_app_dev_overview": _weights(0.50, 0.10, 0.20, 0.20),
    "python_api_basics": _weights(0.25, 0.45, 0.20, 0.10),
    "http_rest_basics": _weights(0.25, 0.45, 0.20, 0.10),
    "git_collaboration": _weights(0.15, 0.55, 0.20, 0.10),
    "data_schema_design": _weights(0.30, 0.35, 0.25, 0.10),
    "prompt_basic": _weights(0.40, 0.30, 0.20, 0.10),
    "prompt_context_design": _weights(0.30, 0.35, 0.25, 0.10),
    "prompt_output_format": _weights(0.25, 0.45, 0.20, 0.10),
    "prompt_evaluation": _weights(0.25, 0.25, 0.40, 0.10),
    "llm_api_calling": _weights(0.20, 0.50, 0.20, 0.10),
    "openai_compatible_api": _weights(0.20, 0.50, 0.20, 0.10),
    "token_context_budget": _weights(0.30, 0.30, 0.30, 0.10),
    "streaming_responses": _weights(0.20, 0.50, 0.20, 0.10),
    "function_calling_tools": _weights(0.20, 0.40, 0.30, 0.10),
    "structured_output_validation": _weights(0.20, 0.40, 0.30, 0.10),
    "embedding_basics": _weights(0.45, 0.25, 0.20, 0.10),
    "vector_similarity": _weights(0.40, 0.25, 0.25, 0.10),
    "rag_pipeline_overview": _weights(0.35, 0.30, 0.25, 0.10),
    "rag_chunking": _weights(0.20, 0.45, 0.25, 0.10),
    "metadata_filtering": _weights(0.20, 0.45, 0.25, 0.10),
    "retrieval_reranking": _weights(0.20, 0.35, 0.35, 0.10),
    "citation_traceability": _weights(0.25, 0.25, 0.40, 0.10),
    "hallucination_guardrails": _weights(0.25, 0.25, 0.40, 0.10),
    "knowledge_base_ingestion": _weights(0.20, 0.45, 0.25, 0.10),
    "document_parsing": _weights(0.20, 0.50, 0.20, 0.10),
    "fastapi_endpoint_design": _weights(0.20, 0.50, 0.20, 0.10),
    "pydantic_schema_validation": _weights(0.25, 0.40, 0.25, 0.10),
    "sqlalchemy_modeling": _weights(0.25, 0.40, 0.25, 0.10),
    "alembic_migrations": _weights(0.20, 0.50, 0.20, 0.10),
    "mysql_indexing": _weights(0.20, 0.40, 0.30, 0.10),
    "chromadb_collections": _weights(0.25, 0.45, 0.20, 0.10),
    "frontend_vue_state": _weights(0.15, 0.55, 0.20, 0.10),
    "frontend_api_client": _weights(0.15, 0.55, 0.20, 0.10),
    "agent_role_design": _weights(0.35, 0.25, 0.30, 0.10),
    "langgraph_stategraph": _weights(0.25, 0.40, 0.25, 0.10),
    "orchestrator_workflow": _weights(0.20, 0.35, 0.35, 0.10),
    "python_async_concurrency": _weights(0.20, 0.50, 0.20, 0.10),
    "knowledge_retrieval_agent": _weights(0.25, 0.35, 0.30, 0.10),
    "content_generation_agent": _weights(0.25, 0.35, 0.30, 0.10),
    "review_validation_agent": _weights(0.25, 0.30, 0.35, 0.10),
    "automated_testing": _weights(0.25, 0.40, 0.25, 0.10),
    "docker_containerization": _weights(0.20, 0.50, 0.20, 0.10),
    "secret_management": _weights(0.25, 0.35, 0.30, 0.10),
    "observability_tracing": _weights(0.20, 0.45, 0.25, 0.10),
    "prompt_injection_defense": _weights(0.25, 0.25, 0.40, 0.10),
    "api_resilience_retry": _weights(0.20, 0.40, 0.30, 0.10),
    "evaluation_metrics": _weights(0.30, 0.25, 0.35, 0.10),
    "privacy_log_policy": _weights(0.30, 0.30, 0.30, 0.10),
    "sse_progress_events": _weights(0.15, 0.55, 0.20, 0.10),
    "llm_judge_reliability": _weights(0.30, 0.25, 0.35, 0.10),
}


AI_APP_DEV_PROFILE_V1_SEED_SHA256 = (
    "d761650e26845c9d0a7acf93ee05d2e0804df3ae9ae2679f3d23ae1fde757da7"
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


def _load_knowledge_catalog() -> tuple[dict[str, KnowledgeProfileMetadata], str]:
    seed_bytes = _seed_path().read_bytes()
    payload = json.loads(seed_bytes.decode("utf-8"))
    canonical_seed = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    seed_sha256 = hashlib.sha256(canonical_seed).hexdigest()
    if seed_sha256 != AI_APP_DEV_PROFILE_V1_SEED_SHA256:
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
    return catalog, seed_sha256


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


def load_ai_app_dev_profile_v1() -> ProfileAnalysisConfig:
    catalog, seed_sha256 = _load_knowledge_catalog()
    config = ProfileAnalysisConfig(
        version="ai_app_dev_profile_v1",
        seed_sha256=seed_sha256,
        prior_mastery=0.5,
        prior_weight=1.0,
        mastery_thresholds=(0.40, 0.60, 0.80),
        minimum_effective_change=5,
        max_ability_change_per_update=10,
        max_weakness_level_change_per_update=1,
        default_n_results=8,
        multi_priority_remedial_n_results=10,
        maximum_n_results=12,
        ability_weights=AI_APP_DEV_ABILITY_WEIGHTS,
        knowledge_catalog=catalog,
        mastery_baselines=MASTERY_BASELINES,
    )
    validate_ai_app_dev_profile_config(set(catalog), config)
    return config


AI_APP_DEV_PROFILE_V1 = load_ai_app_dev_profile_v1()
