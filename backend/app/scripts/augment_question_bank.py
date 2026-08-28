"""Build the checked-in ai_app_dev question-bank expansion offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SEED_DIR = PROJECT_ROOT / "data" / "seed"
OUTPUT_PATH = SEED_DIR / "question_bank_expansion.json"
QUIZ_USES = ["diagnosis", "graded_quiz"]
RESERVE_USES = ["mastery_validation", "mistake_consolidation"]


def _load(name: str) -> list[dict[str, Any]]:
    return list(json.loads((SEED_DIR / name).read_text(encoding="utf-8")))


def _question_id(knowledge_id: str, slot: int) -> str:
    digest = hashlib.sha256(
        f"ai_app_dev:{knowledge_id}:question-bank-v3:{slot}".encode()
    ).hexdigest()[:16]
    return f"dq_qb_{digest}"


def _level(difficulty: int) -> str:
    return "foundation" if difficulty <= 2 else "improvement" if difficulty <= 3 else "challenge"


def _variant_stem(name: str, heading: str, slot: int) -> str:
    templates = {
        2: "根据“{name}”资料，在“{heading}”环节，下列哪项是必须落实的要求？",
        3: "团队正在执行“{name}”的“{heading}”步骤。下列哪项做法与资料一致？",
        4: "对“{name}”进行排查时，若重点检查“{heading}”，应优先确认哪项事实或处理？",
        5: "为通过“{name}”的“{heading}”验收，下列哪项结论最能作为可追溯依据？",
    }
    return templates[slot].format(name=name, heading=heading)


_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$\n(.*?)(?=^##\s+|\Z)", re.MULTILINE | re.DOTALL)
_SENTENCE_RE = re.compile(r"^\s*(?:\d+\.\s*)?(.+?[。！？])")


def _section_facts(content: str) -> list[tuple[str, str]]:
    facts: list[tuple[str, str]] = []
    for heading, body in _SECTION_RE.findall(content):
        clean_body = re.sub(r"```.*?```", "", body, flags=re.DOTALL).strip()
        sentence = _SENTENCE_RE.search(clean_body)
        fact = (sentence.group(1) if sentence else clean_body[:180]).strip()
        if len(fact) >= 16:
            facts.append((heading.strip(), fact))
    if len(facts) >= 4:
        return facts

    # Older seed entries use prose rather than Markdown sections. Their
    # independently stated requirements are still valid source facts.
    prose = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
    for sentence in re.findall(r"[^。！？]+[。！？]", prose):
        fact = re.sub(r"\s+", " ", sentence).strip()
        if len(fact) < 16 or any(existing == fact for _heading, existing in facts):
            continue
        facts.append((f"资料要点 {len(facts) + 1}", fact))
    return facts


def _fact_indexes(facts: list[tuple[str, str]]) -> dict[int, int]:
    if len(facts) < 4:
        raise ValueError("knowledge_requires_four_independent_facts")
    selected: dict[int, int] = {}
    used: set[int] = set()

    def choose(slot: int, keywords: tuple[str, ...]) -> None:
        candidates = [
            index for index, (heading, _fact) in enumerate(facts)
            if index not in used and any(keyword in heading for keyword in keywords)
        ]
        index = candidates[0] if candidates else next(index for index in range(len(facts)) if index not in used)
        selected[slot] = index
        used.add(index)

    choose(2, ("要求", "结构", "输入", "语义", "概念", "原理", "定义"))
    choose(3, ("操作", "步骤", "实现", "流程", "实践"))
    choose(4, ("错误", "失败", "边界", "风险", "处理", "安全"))
    choose(5, ("验收", "预期", "评测", "结果", "监控"))
    return selected


def _source_quote(content: str, fact: str) -> str:
    if len(fact) >= 24:
        return fact
    start = content.find(fact)
    if start < 0:
        return fact
    paragraph = content[start:].split("\n\n", 1)[0].strip()
    return paragraph[:240]


def _scenario_options(
    facts: list[tuple[str, str]],
    correct_index: int,
    slot: int,
    used_option_sets: set[tuple[str, ...]],
) -> tuple[list[str], int]:
    correct = facts[correct_index][1]
    pool = [fact for index, (_heading, fact) in enumerate(facts) if index != correct_index]
    variants = list(combinations(pool, 3))
    for offset in range(len(variants)):
        distractors = list(variants[(slot + offset) % len(variants)])
        if len({correct, *distractors}) != 4:
            continue
        # Prefix the applicable requirement so prose-only source entries with
        # exactly four facts still produce distinct, scenario-specific choices.
        ordered = distractors
        position = (slot - 1) % 4
        ordered.insert(position, f"应落实：{correct}")
        fingerprint = tuple(sorted(ordered))
        if fingerprint not in used_option_sets:
            used_option_sets.add(fingerprint)
            return ordered, position
    raise ValueError("question_requires_unique_option_set")


def build_records() -> list[dict[str, Any]]:
    knowledge = _load("knowledge_items.json")
    records: list[dict[str, Any]] = []
    for item in knowledge:
        knowledge_id = str(item["knowledge_id"])
        facts = _section_facts(str(item["content"]))
        indexes = _fact_indexes(facts)
        slots = [2, 4, 5] if knowledge_id == "python_async_concurrency" else [2, 3, 4, 5]
        used_option_sets: set[tuple[str, ...]] = set()
        for slot in slots:
            fact_index = indexes[slot]
            heading, correct_text = facts[fact_index]
            variant_options, answer = _scenario_options(
                facts, fact_index, slot, used_option_sets
            )
            uses = QUIZ_USES if slot in {3, 5} else RESERVE_USES
            difficulty = slot
            reserve_role = (
                "consolidation" if slot == 2 else "mastery_transfer" if slot == 4 else None
            )
            records.append(
                {
                    "question_id": _question_id(knowledge_id, slot),
                    "knowledge_id": knowledge_id,
                    "question_type": "single_choice",
                    "difficulty": difficulty,
                    "quiz_level": _level(difficulty),
                    "stem": _variant_stem(str(item["name"]), heading, slot),
                    "options": variant_options,
                    "answer_key": {
                        "correct_option": answer,
                        "explanation": (
                            f"正确选项是“{correct_text}”。它满足“{item['name']}”资料中的核心要求，"
                            "其余选项忽略了必要约束、验证步骤或风险控制。"
                        ),
                        "question_slot": slot,
                        "question_bank_uses": uses,
                        "reserve_role": reserve_role,
                        "assessment_focus": {
                            2: "common_misconception_correction",
                            3: "constrained_application",
                            4: "diagnosis_and_transfer",
                            5: "integrated_tradeoff",
                        }[slot],
                        "source_quote": _source_quote(str(item["content"]), correct_text),
                    },
                    "certification_method": "curated_seed_exact_evidence",
                }
            )
    validate_records(records, knowledge_ids=[str(item["knowledge_id"]) for item in knowledge])
    return records


def validate_records(records: list[dict[str, Any]], *, knowledge_ids: list[str]) -> None:
    if len(records) != 199:
        raise ValueError(f"expected_199_records:{len(records)}")
    ids = [str(record["question_id"]) for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate_question_id")
    signatures = [(str(record["stem"]), tuple(record["options"])) for record in records]
    if len(signatures) != len(set(signatures)):
        raise ValueError("duplicate_stem_options")
    option_sets = [
        (str(record["knowledge_id"]), tuple(sorted(str(value).strip() for value in record["options"])))
        for record in records
    ]
    if len(option_sets) != len(set(option_sets)):
        raise ValueError("duplicate_option_set_within_knowledge")
    uses = Counter(
        use for record in records for use in record["answer_key"]["question_bank_uses"]
    )
    expected_uses = Counter(
        {
            "diagnosis": 99,
            "graded_quiz": 99,
            "mastery_validation": 100,
            "mistake_consolidation": 100,
        }
    )
    if uses != expected_uses:
        raise ValueError(f"invalid_use_distribution:{dict(uses)}")
    by_knowledge = Counter(str(record["knowledge_id"]) for record in records)
    if set(by_knowledge) != set(knowledge_ids):
        raise ValueError("knowledge_coverage_mismatch")
    if any(count not in {3, 4} for count in by_knowledge.values()):
        raise ValueError(f"invalid_knowledge_density:{dict(by_knowledge)}")
    for record in records:
        answer_key = dict(record["answer_key"])
        options = list(record["options"])
        answer = answer_key.get("correct_option")
        if (
            record.get("question_type") != "single_choice"
            or len(options) != 4
            or len({str(value).strip() for value in options}) != 4
            or not isinstance(answer, int)
            or not 0 <= answer < 4
            or not str(answer_key.get("explanation") or "").strip()
            or len(str(answer_key.get("source_quote") or "").strip()) < 24
            or answer_key.get("reserve_role") not in {None, "consolidation", "mastery_transfer"}
        ):
            raise ValueError(f"invalid_record:{record.get('question_id')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build checked-in question-bank expansion data.")
    parser.add_argument("--check", action="store_true", help="Validate an existing output without rewriting it.")
    args = parser.parse_args()
    records = build_records()
    if args.check:
        existing = list(json.loads(OUTPUT_PATH.read_text(encoding="utf-8")))
        if existing != records:
            raise SystemExit("question_bank_expansion_out_of_date")
    else:
        OUTPUT_PATH.write_text(
            json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps({"records": len(records), "output": str(OUTPUT_PATH)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
