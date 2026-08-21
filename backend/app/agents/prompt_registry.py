"""Load and fingerprint the production Agent prompts from one registry."""

from __future__ import annotations

import hashlib
from pathlib import Path


PROMPT_VERSION = "v6"
PROMPT_DIR = Path(__file__).with_name("prompts")

PROMPT_FILES: dict[str, str] = {
    "orchestrator": "orchestrator_agent.md",
    "profile": "profile_agent.md",
    "retrieval": "retrieval_agent.md",
    "generation": "generation_agent.md",
    "generation.revision": "generation_revision.md",
    "generation.source_repair": "generation_source_repair.md",
    "generation.coverage_repair": "generation_coverage_repair.md",
    "generation.content_policy_repair": "generation_content_policy_repair.md",
    "generation.quiz_repair": "generation_quiz_repair.md",
    "review": "review_agent.md",
    "review.primary": "review_primary.md",
    "review.secondary": "review_secondary.md",
    "tutoring": "tutoring_agent.md",
}

NODE_PROMPT_KEYS: dict[str, tuple[str, ...]] = {
    "prepare_task": ("orchestrator",),
    "interpret_feedback": ("tutoring",),
    "analyze_profile": ("profile",),
    "retrieve_knowledge": ("retrieval",),
    "generate_resource": (
        "generation",
        "generation.revision",
        "generation.source_repair",
        "generation.coverage_repair",
        "generation.content_policy_repair",
        "generation.quiz_repair",
    ),
    "review_resource": ("review", "review.primary", "review.secondary"),
    "finalize_task": ("orchestrator",),
}


def get_prompt(key: str) -> str:
    try:
        filename = PROMPT_FILES[key]
    except KeyError as exc:
        raise RuntimeError(f"production_prompt_not_registered:{key}") from exc
    path = PROMPT_DIR / filename
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"production_prompt_missing:{key}:{filename}") from exc
    if not content:
        raise RuntimeError(f"production_prompt_empty:{key}:{filename}")
    return content


def prompt_hash(*keys: str) -> str:
    digest = hashlib.sha256()
    for key in keys:
        digest.update(key.encode("utf-8"))
        digest.update(b"\0")
        digest.update(get_prompt(key).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def node_prompt_hash(step: str) -> str:
    try:
        keys = NODE_PROMPT_KEYS[step]
    except KeyError as exc:
        raise RuntimeError(f"production_node_prompt_not_registered:{step}") from exc
    return prompt_hash(*keys)


def validate_production_prompts() -> None:
    for key in PROMPT_FILES:
        get_prompt(key)
    for step in NODE_PROMPT_KEYS:
        node_prompt_hash(step)
