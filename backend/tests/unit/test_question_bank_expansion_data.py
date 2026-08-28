from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from app.scripts.augment_question_bank import (
    QUIZ_USES,
    RESERVE_USES,
    build_records,
    validate_records,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SEED_DIR = PROJECT_ROOT / "data" / "seed"


def _load(name: str) -> list[dict]:
    return list(json.loads((SEED_DIR / name).read_text(encoding="utf-8")))


def test_expansion_is_deterministic_and_matches_checked_in_data() -> None:
    knowledge = _load("knowledge_items.json")
    records = build_records()

    validate_records(
        records,
        knowledge_ids=[str(item["knowledge_id"]) for item in knowledge],
    )
    assert records == _load("question_bank_expansion.json")
    assert len(records) == 199
    assert Counter(
        tuple(record["answer_key"]["question_bank_uses"]) for record in records
    ) == Counter({tuple(QUIZ_USES): 99, tuple(RESERVE_USES): 100})


def test_combined_static_question_bank_has_three_quiz_and_two_reserve_questions() -> None:
    knowledge_ids = [str(item["knowledge_id"]) for item in _load("knowledge_items.json")]
    existing = _load("diagnostic_questions.json")
    expansion = _load("question_bank_expansion.json")
    combined = [
        *(
            question
            for question in existing
            if question["question_type"] == "single_choice"
        ),
        *expansion,
    ]

    quiz_counts: Counter[str] = Counter()
    reserve_counts: Counter[str] = Counter()
    for question in combined:
        uses = set(question.get("answer_key", {}).get("question_bank_uses") or QUIZ_USES)
        if "graded_quiz" in uses:
            quiz_counts[str(question["knowledge_id"])] += 1
        if uses & set(RESERVE_USES):
            reserve_counts[str(question["knowledge_id"])] += 1

    assert len(combined) == 250
    assert len({question["question_id"] for question in combined}) == len(combined)
    assert all(quiz_counts[knowledge_id] == 3 for knowledge_id in knowledge_ids)
    assert all(reserve_counts[knowledge_id] == 2 for knowledge_id in knowledge_ids)
    by_knowledge: dict[str, list[dict]] = {knowledge_id: [] for knowledge_id in knowledge_ids}
    for question in combined:
        by_knowledge[str(question["knowledge_id"])].append(question)
    for knowledge_id, questions in by_knowledge.items():
        assert sorted(question["difficulty"] for question in questions) == [1, 2, 3, 4, 5]
        quiz_difficulties = sorted(
            question["difficulty"]
            for question in questions
            if "graded_quiz" in set(question.get("answer_key", {}).get("question_bank_uses") or QUIZ_USES)
        )
        reserve_difficulties = sorted(
            question["difficulty"]
            for question in questions
            if set(question.get("answer_key", {}).get("question_bank_uses") or [])
            & set(RESERVE_USES)
        )
        assert quiz_difficulties == [1, 3, 5], knowledge_id
        assert reserve_difficulties == [2, 4], knowledge_id
