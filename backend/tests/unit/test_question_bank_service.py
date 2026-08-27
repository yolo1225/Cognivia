from __future__ import annotations

import pytest

from app.services.question_bank_service import (
    QuestionBankError,
    expected_quiz_question_count,
    select_graded_quiz_candidates,
)


def _select(rows: list[dict], *, profile_type: str, target_difficulty: int) -> list[dict]:
    return select_graded_quiz_candidates(
        rows,
        ["K1"],
        knowledge_id=lambda row: row["knowledge_id"],
        related_knowledge_ids=lambda row: row.get("related", []),
        quiz_level=lambda row: row["level"],
        question_id=lambda row: row["id"],
        difficulty=lambda row: row["difficulty"],
        question_type=lambda row: row["type"],
        profile_type=profile_type,
        target_difficulty=target_difficulty,
        require_complete=True,
    )


def test_expected_question_count_is_a_preference_not_a_fixed_template() -> None:
    assert [expected_quiz_question_count(size) for size in range(2, 7)] == [4, 5, 6, 7, 8]


def test_advanced_profile_can_receive_no_foundation_question() -> None:
    rows = [
        {"id": "foundation", "knowledge_id": "K1", "related": [], "level": "foundation", "difficulty": 2, "type": "single_choice"},
        {"id": "improvement", "knowledge_id": "K1", "related": [], "level": "improvement", "difficulty": 3, "type": "short_answer"},
        {"id": "challenge-a", "knowledge_id": "K1", "related": [], "level": "challenge", "difficulty": 4, "type": "single_choice"},
        {"id": "challenge-b", "knowledge_id": "K1", "related": [], "level": "challenge", "difficulty": 5, "type": "short_answer"},
    ]

    selected = _select(rows, profile_type="advanced", target_difficulty=4)

    assert len(selected) == 3
    assert {row["level"] for row in selected} == {"improvement", "challenge"}


def test_primary_knowledge_hit_outranks_relation_only_hit() -> None:
    rows = [
        {"id": "related", "knowledge_id": "K2", "related": ["K1"], "level": "challenge", "difficulty": 4, "type": "short_answer"},
        {"id": "primary-a", "knowledge_id": "K1", "related": [], "level": "foundation", "difficulty": 2, "type": "single_choice"},
        {"id": "primary-b", "knowledge_id": "K1", "related": [], "level": "improvement", "difficulty": 3, "type": "short_answer"},
        {"id": "primary-c", "knowledge_id": "K1", "related": [], "level": "improvement", "difficulty": 3, "type": "single_choice"},
    ]

    selected = _select(rows, profile_type="intermediate", target_difficulty=3)
    assert len(selected) == 3
    assert {row["id"] for row in selected} == {"primary-a", "primary-b", "primary-c"}


def test_fewer_than_three_matching_questions_returns_density_error() -> None:
    rows = [
        {"id": "one", "knowledge_id": "K1", "related": [], "level": "foundation", "difficulty": 1, "type": "single_choice"},
        {"id": "two", "knowledge_id": "K1", "related": [], "level": "foundation", "difficulty": 2, "type": "short_answer"},
    ]

    with pytest.raises(QuestionBankError, match="graded_quiz_question_bank_insufficient"):
        _select(rows, profile_type="beginner", target_difficulty=1)
