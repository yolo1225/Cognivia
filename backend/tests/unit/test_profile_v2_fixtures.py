\
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.agents.contracts import AnalyzeProfileInput, GenerationStrategy, ProfileType
from app.agents.profile_analysis_config import (
    AI_APP_DEV_PROFILE_V1,
    validate_ai_app_dev_profile_config,
)
from app.services.profile_v2_fixture_service import (
    CANONICAL_HASH_ALGORITHM,
    DEFAULT_FIXTURE_DIR,
    ProfileV2FixtureError,
    all_case_documents,
    canonical_json_sha256,
    rendered_cases,
    validate_acceptance_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = DEFAULT_FIXTURE_DIR
EXPECTED_KEYS = {
    "profile_update_required",
    "changed_dimensions",
    "profile_type",
    "weak_knowledge_ids",
    "retrieval_strategy",
    "target_difficulty",
    "priority_knowledge_ids",
    "prerequisite_knowledge_ids",
    "needs_generation",
}


def _all_case_documents() -> list[dict[str, Any]]:
    return all_case_documents(FIXTURE_DIR)


def _rendered_cases() -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    return rendered_cases(FIXTURE_DIR)


def _seed_knowledge_ids() -> set[str]:
    items = json.loads(
        (PROJECT_ROOT / "data" / "seed" / "knowledge_items.json").read_text(encoding="utf-8")
    )
    return {item["knowledge_id"] for item in items}


def test_ai_app_dev_profile_config_maps_every_seed_knowledge_item() -> None:
    knowledge_ids = _seed_knowledge_ids()
    assert len(knowledge_ids) == 50
    validate_ai_app_dev_profile_config(knowledge_ids, AI_APP_DEV_PROFILE_V1)

    config = AI_APP_DEV_PROFILE_V1
    assert config.prior_mastery == 0.5
    assert config.prior_weight == 1.0
    assert config.mastery_thresholds == (0.40, 0.60, 0.80)
    assert config.minimum_effective_change == 5
    assert config.max_ability_change_per_update == 10
    assert config.max_weakness_level_change_per_update == 1
    assert (
        config.default_n_results,
        config.multi_priority_remedial_n_results,
        config.maximum_n_results,
    ) == (8, 10, 12)
    assert config.difficulty_weight(1) == pytest.approx(0.7)
    assert config.difficulty_weight(5) == pytest.approx(1.3)


def test_profile_v2_case_distribution_and_unique_ids() -> None:
    documents = _all_case_documents()
    development, acceptance = documents
    assert len(development["cases"]) == 30
    assert len(acceptance["cases"]) == 20

    cases = [case for document in documents for case in document["cases"]]
    assert len({case["case_id"] for case in cases}) == 50
    assert {case["scenario"] for case in development["cases"]} == {
        "initial_diagnostic",
        "weakness_prerequisite",
        "single_feedback_no_change",
        "confirmed_assessment_update",
        "resource_incorrect_review",
    }


@pytest.mark.parametrize(("case_id", "payload", "expected"), _rendered_cases())
def test_profile_v2_cases_build_valid_contract_inputs(
    case_id: str,
    payload: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    node_input = AnalyzeProfileInput.model_validate(payload)
    assert node_input.task_id == case_id
    assert node_input.context.task_id == case_id

    assert set(expected) == EXPECTED_KEYS
    assert expected["profile_type"] == ProfileType(expected["profile_type"]).value
    assert expected["retrieval_strategy"] == GenerationStrategy(expected["retrieval_strategy"]).value
    assert 1 <= expected["target_difficulty"] <= 5
    assert len(expected["priority_knowledge_ids"]) <= 20
    assert len(expected["prerequisite_knowledge_ids"]) <= 20
    assert not set(expected["priority_knowledge_ids"]) & set(
        expected["prerequisite_knowledge_ids"]
    )
    assert set(expected["weak_knowledge_ids"]).issubset(_seed_knowledge_ids())
    assert set(expected["priority_knowledge_ids"]).issubset(_seed_knowledge_ids())
    assert set(expected["prerequisite_knowledge_ids"]).issubset(_seed_knowledge_ids())

    if not expected["profile_update_required"]:
        assert expected["changed_dimensions"] == []
    if not expected["needs_generation"]:
        assert not expected["priority_knowledge_ids"]


def test_acceptance_fixture_matches_reviewed_manifest() -> None:
    manifest = json.loads(
        (FIXTURE_DIR / "acceptance_baseline_manifest.json").read_text(encoding="utf-8")
    )
    acceptance = validate_acceptance_manifest(FIXTURE_DIR)

    assert manifest["fixture_hash_algorithm"] == CANONICAL_HASH_ALGORITHM
    assert manifest["fixture_canonical_sha256"] == canonical_json_sha256(acceptance)


def test_acceptance_manifest_ignores_line_endings(tmp_path: Path) -> None:
    for name in ("acceptance_cases.json", "acceptance_baseline_manifest.json"):
        source = FIXTURE_DIR / name
        target = tmp_path / name
        if name == "acceptance_cases.json":
            target.write_bytes(source.read_bytes().replace(b"\r\n", b"\n"))
        else:
            target.write_bytes(source.read_bytes())

    validate_acceptance_manifest(tmp_path)


def test_acceptance_manifest_rejects_changed_case_content(tmp_path: Path) -> None:
    for name in ("acceptance_cases.json", "acceptance_baseline_manifest.json"):
        (tmp_path / name).write_bytes((FIXTURE_DIR / name).read_bytes())
    fixture_path = tmp_path / "acceptance_cases.json"
    acceptance = json.loads(fixture_path.read_text(encoding="utf-8"))
    acceptance["cases"][0]["expected"]["target_difficulty"] = 5
    fixture_path.write_text(
        json.dumps(acceptance, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with pytest.raises(ProfileV2FixtureError, match="acceptance_fixture_hash_mismatch"):
        validate_acceptance_manifest(tmp_path)
