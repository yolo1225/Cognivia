"""Build V4 quality cases with evidence-capability-safe practice targets."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SEED_PATH = ROOT / "data" / "seed" / "knowledge_items.json"
OUTPUT_PATH = ROOT / "data" / "evaluation_cases" / "v4" / "p0_cases.json"


def main() -> None:
    knowledge = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    operational = [
        item
        for item in knowledge
        if "operation" in item.get("evidence_capabilities", [])
    ]
    if len(knowledge) < 50 or len(operational) < 2:
        raise ValueError("V4 cases require 50 knowledge items and operation evidence")

    profiles = (
        ("beginner", 45, 2),
        ("intermediate", 60, 3),
        ("advanced", 80, 4),
    )
    resource_types = ("lecture", "practice_guide", "graded_quiz")
    cases: list[dict[str, object]] = []
    operation_index = 0
    for index, item in enumerate(knowledge[:50], start=1):
        resource_type = resource_types[(index - 1) % len(resource_types)]
        if resource_type == "practice_guide":
            first = operational[operation_index % len(operational)]
            second = operational[(operation_index + 1) % len(operational)]
            operation_index += 2
        else:
            first = item
            second = knowledge[index % len(knowledge)]
        target_ids = [first["knowledge_id"], second["knowledge_id"]]
        profile_type, score, difficulty = profiles[(index - 1) % len(profiles)]
        scenario_type = (
            "initial_generation"
            if index <= 40
            else "feedback_revision"
            if index <= 45
            else "challenge_task"
        )
        generates_reviewed_resource = scenario_type != "challenge_task"
        cases.append(
            {
                "case_id": f"V4-EVAL-{index:03d}",
                "scenario_type": scenario_type,
                "profile_snapshot": {
                    "profile_id": f"evaluation-profile-{profile_type}-{index:03d}",
                    "profile_type": profile_type,
                    "ability_scores": {
                        "theory": score,
                        "practice": score,
                        "problem_solving": score,
                        "knowledge_breadth": score,
                        "learning_speed": score,
                    },
                    "weak_knowledge": target_ids,
                },
                "resource_type": resource_type,
                "target_difficulty": difficulty,
                "target_core_knowledge_ids": target_ids,
                "gold_standard": {
                    "required_source_ids": target_ids,
                    "required_evidence_capability": (
                        "operation" if resource_type == "practice_guide" else "concept"
                    ),
                    "acceptance_note": "验证 V6 唯一目标覆盖、证据能力和双模型审核。",
                },
                "expected_review_conclusion": (
                    "passed" if generates_reviewed_resource else "no_change"
                ),
                "expected_profile_decision": "no_change",
                "knowledge_base_version": "ai_app_dev-kb-2026.08-v4",
                "observed_result": {
                    "evaluated_claim_count": 4 if generates_reviewed_resource else 0,
                    "contradicted_claim_count": 0,
                    "evidence_insufficient_claim_count": 0,
                    "unresolved_claim_count": 0,
                    "generated_fact_count": 4 if generates_reviewed_resource else 0,
                    "hallucinated_fact_count": 0,
                    "difficulty_matched": True if generates_reviewed_resource else None,
                    "covered_core_knowledge_count": (
                        len(target_ids) if generates_reviewed_resource else 0
                    ),
                    "target_core_knowledge_count": (
                        len(target_ids) if generates_reviewed_resource else 0
                    ),
                    "review_conclusion": (
                        "passed" if generates_reviewed_resource else "no_change"
                    ),
                    "profile_decision": "no_change",
                    "latency_ms": 1200 + index * 15,
                    "agent_latency_ms": {},
                    "determinable": True,
                },
            }
        )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(
            {
                "schema_version": "v4",
                "knowledge_base_version": "ai_app_dev-kb-2026.08-v4",
                "script_version": "v6-live-evaluator-3.0",
                "observed_result_policy": (
                    "Embedded observations are deterministic fixtures only; "
                    "formal acceptance requires a separate live run."
                ),
                "cases": cases,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
