"""Build the versioned V2 live-evaluation case set from the active seed catalog."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SEED_PATH = ROOT / "data" / "seed" / "knowledge_items.json"
OUTPUT_PATH = ROOT / "data" / "evaluation_cases" / "v2" / "p0_cases.json"


def main() -> None:
    knowledge = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    cases = []
    profile_levels = (
        ("beginner", 45, 2),
        ("intermediate", 60, 3),
        ("advanced", 80, 4),
    )
    resource_types = ("lecture", "practice_guide", "graded_quiz")
    for index, item in enumerate(knowledge, start=1):
        next_item = knowledge[index % len(knowledge)]
        profile_type, score, difficulty = profile_levels[(index - 1) % len(profile_levels)]
        case_id = f"V2-EVAL-{index:03d}"
        target_ids = [item["knowledge_id"], next_item["knowledge_id"]]
        cases.append(
            {
                "case_id": case_id,
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
                "resource_type": resource_types[(index - 1) % len(resource_types)],
                "target_difficulty": difficulty,
                "target_core_knowledge_ids": target_ids,
                "gold_standard": {
                    "required_source_ids": [item["knowledge_id"]],
                    "acceptance_note": "验证真实 V2 检索、生成、双模型审核与来源闭环。",
                },
                "expected_review_conclusion": "passed",
                "expected_profile_decision": "no_change",
                "knowledge_base_version": "ai_app_dev-kb-2026.07-v2",
            }
        )
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(
            {
                "schema_version": "v2",
                "knowledge_base_version": "ai_app_dev-kb-2026.07-v2",
                "script_version": "v2-live-evaluator-1.0",
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
