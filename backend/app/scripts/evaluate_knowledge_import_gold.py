from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "knowledge_import_gold_v1" / "manifest.json"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve(manifest_path: Path, value: str) -> Path:
    return (manifest_path.parent / value).resolve()


def build_gold(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = _load(manifest_path)
    items = _load(_resolve(manifest_path, manifest["normalization_source"]))
    questions = _load(_resolve(manifest_path, manifest["question_source"]))
    normalized = {
        item["knowledge_id"]: {
            "name": item["name"],
            "category": item["category"],
            "difficulty": item["difficulty"],
            "tags": item.get("tags", []),
        }
        for item in items[: int(manifest["normalization_limit"])]
    }
    relations: dict[str, dict[str, str]] = {}
    for item in items:
        for relation_type, field in (("prerequisite", "prerequisites"), ("related_to", "related")):
            for target in item.get(field, []):
                relation_id = f"{target}->{item['knowledge_id']}:{relation_type}"
                relations[relation_id] = {
                    "source": target,
                    "target": item["knowledge_id"],
                    "relation_type": relation_type,
                }
                if len(relations) >= int(manifest["relation_limit"]):
                    break
            if len(relations) >= int(manifest["relation_limit"]):
                break
        if len(relations) >= int(manifest["relation_limit"]):
            break
    question_gold = {
        item["question_id"]: {
            "knowledge_id": item["knowledge_id"],
            "answer_key": item["answer_key"],
        }
        for item in questions[: int(manifest["question_limit"])]
    }
    return {
        "manifest": manifest,
        "normalization": normalized,
        "relations": relations,
        "questions": question_gold,
    }


def _score(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    failed = [sample_id for sample_id, value in expected.items() if actual.get(sample_id) != value]
    numerator = len(expected) - len(failed)
    denominator = len(expected)
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 4) if denominator else 0.0,
        "failure_ids": failed,
    }


def evaluate(predictions: dict[str, Any], manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    gold = build_gold(manifest_path)
    manifest = gold["manifest"]
    normalization = _score(gold["normalization"], predictions.get("normalization", {}))
    relation_direction = _score(gold["relations"], predictions.get("relations", {}))
    questions = _score(gold["questions"], predictions.get("questions", {}))
    predicted_relations = predictions.get("relations", {})
    correct_relations = sum(
        gold["relations"].get(sample_id) == value
        for sample_id, value in predicted_relations.items()
    )
    relation_precision = {
        "numerator": correct_relations,
        "denominator": len(predicted_relations),
        "rate": round(correct_relations / len(predicted_relations), 4)
        if predicted_relations
        else 0.0,
        "failure_ids": [
            sample_id
            for sample_id, value in predicted_relations.items()
            if gold["relations"].get(sample_id) != value
        ],
    }
    passed = bool(
        relation_precision["rate"] >= manifest["relation_precision_threshold"]
        and relation_direction["rate"] >= manifest["direction_accuracy_threshold"]
    )
    return {
        "sample_version": manifest["sample_version"],
        "passed": passed,
        "normalization_accuracy": normalization,
        "relation_precision": relation_precision,
        "direction_accuracy": relation_direction,
        "question_accuracy": questions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate knowledge import predictions.")
    parser.add_argument("--predictions", type=Path, help="Prediction JSON; omit for gold self-check.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    gold = build_gold(args.manifest)
    predictions = _load(args.predictions) if args.predictions else {
        key: gold[key] for key in ("normalization", "relations", "questions")
    }
    result = evaluate(predictions, args.manifest)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
