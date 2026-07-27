"""Shared, deterministic loading and integrity checks for Profile V2 fixtures."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from app.agents.profile_analysis_config import AI_APP_DEV_PROFILE_V1, ProfileAnalysisConfig


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FIXTURE_DIR = PROJECT_ROOT / "backend" / "tests" / "fixtures" / "profile_v2"
CASE_FILES = ("development_cases.json", "acceptance_cases.json")
ACCEPTANCE_MANIFEST_FILE = "acceptance_baseline_manifest.json"
ACCEPTANCE_BASELINE_VERSION = "ai_app_dev_profile_v1_acceptance_2"
CANONICAL_HASH_ALGORITHM = "canonical-json-sha256-v1"


class ProfileV2FixtureError(ValueError):
    """Raised when a checked-in Profile V2 fixture is malformed or unreviewed."""


@dataclass(frozen=True)
class RenderedProfileV2Case:
    """One rendered case plus its non-sensitive evaluation scenario."""

    case_id: str
    scenario: str
    payload: dict[str, Any]
    expected: dict[str, Any]


def canonical_json_sha256(value: Any) -> str:
    """Hash JSON content independently of whitespace and platform line endings."""
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileV2FixtureError(f"invalid_profile_v2_fixture:{path.name}") from exc
    if not isinstance(value, dict):
        raise ProfileV2FixtureError(f"invalid_profile_v2_fixture_shape:{path.name}")
    return value


def render_fixture_value(value: Any, values: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: render_fixture_value(item, values) for key, item in value.items()}
    if isinstance(value, list):
        return [render_fixture_value(item, values) for item in value]
    if not isinstance(value, str):
        return value
    if value.startswith("$") and value[1:] in values:
        return values[value[1:]]

    rendered = value
    for key, replacement in values.items():
        rendered = rendered.replace(f"${key}", str(replacement))
    return rendered


def all_case_documents(
    fixture_dir: Path = DEFAULT_FIXTURE_DIR,
) -> list[dict[str, Any]]:
    return [load_json(fixture_dir / filename) for filename in CASE_FILES]


def rendered_cases(
    fixture_dir: Path = DEFAULT_FIXTURE_DIR,
    config: ProfileAnalysisConfig = AI_APP_DEV_PROFILE_V1,
) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Preserve the established tuple API used by algorithm and boundary tests."""
    return [
        (case.case_id, case.payload, case.expected)
        for case in rendered_case_records(fixture_dir=fixture_dir, config=config)
    ]


def rendered_case_records(
    fixture_dir: Path = DEFAULT_FIXTURE_DIR,
    config: ProfileAnalysisConfig = AI_APP_DEV_PROFILE_V1,
) -> list[RenderedProfileV2Case]:
    """Render fixtures while preserving scenario metadata for offline evaluation."""
    rendered: list[RenderedProfileV2Case] = []
    for document in all_case_documents(fixture_dir):
        if document.get("fixture_version") != config.version:
            raise ProfileV2FixtureError("profile_v2_fixture_version_mismatch")
        templates = document.get("templates")
        cases = document.get("cases")
        if not isinstance(templates, dict) or not isinstance(cases, list):
            raise ProfileV2FixtureError("invalid_profile_v2_fixture_shape")
        for case in cases:
            if not isinstance(case, dict):
                raise ProfileV2FixtureError("invalid_profile_v2_case")
            case_id = case.get("case_id")
            scenario = case.get("scenario")
            template_name = case.get("template")
            values = case.get("values")
            expected = case.get("expected")
            if (
                not isinstance(case_id, str)
                or not isinstance(scenario, str)
                or not isinstance(template_name, str)
                or not isinstance(values, dict)
                or not isinstance(expected, dict)
                or template_name not in templates
            ):
                raise ProfileV2FixtureError("invalid_profile_v2_case")
            rendered.append(
                RenderedProfileV2Case(
                    case_id=case_id,
                    scenario=scenario,
                    payload=render_fixture_value(
                        deepcopy(templates[template_name]),
                        {**values, "case_id": case_id},
                    ),
                    expected=expected,
                )
            )
    return rendered

def validate_acceptance_manifest(
    fixture_dir: Path = DEFAULT_FIXTURE_DIR,
    config: ProfileAnalysisConfig = AI_APP_DEV_PROFILE_V1,
) -> dict[str, Any]:
    acceptance = load_json(fixture_dir / "acceptance_cases.json")
    manifest = load_json(fixture_dir / ACCEPTANCE_MANIFEST_FILE)
    expected_hashes = manifest.get("case_sha256")

    if manifest.get("baseline_version") != ACCEPTANCE_BASELINE_VERSION:
        raise ProfileV2FixtureError("acceptance_baseline_version_mismatch")
    if manifest.get("fixture_version") != acceptance.get("fixture_version"):
        raise ProfileV2FixtureError("acceptance_fixture_version_mismatch")
    if manifest.get("config_version") != config.version:
        raise ProfileV2FixtureError("acceptance_config_version_mismatch")
    if manifest.get("seed_sha256") != config.seed_sha256:
        raise ProfileV2FixtureError("acceptance_seed_fingerprint_mismatch")
    if manifest.get("fixture_hash_algorithm") != CANONICAL_HASH_ALGORITHM:
        raise ProfileV2FixtureError("acceptance_hash_algorithm_mismatch")
    if manifest.get("fixture_canonical_sha256") != canonical_json_sha256(acceptance):
        raise ProfileV2FixtureError("acceptance_fixture_hash_mismatch")
    if not isinstance(expected_hashes, dict):
        raise ProfileV2FixtureError("acceptance_case_hashes_missing")

    cases = acceptance.get("cases")
    if not isinstance(cases, list):
        raise ProfileV2FixtureError("invalid_acceptance_fixture_shape")
    actual_ids = {case.get("case_id") for case in cases if isinstance(case, dict)}
    if set(expected_hashes) != actual_ids or len(actual_ids) != len(cases):
        raise ProfileV2FixtureError("acceptance_case_ids_mismatch")
    for case in cases:
        if not isinstance(case, dict):
            raise ProfileV2FixtureError("invalid_acceptance_case")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or expected_hashes.get(case_id) != canonical_json_sha256(case):
            raise ProfileV2FixtureError("acceptance_case_hash_mismatch")
    return acceptance
