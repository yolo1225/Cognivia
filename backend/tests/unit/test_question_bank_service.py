from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import AnswerRecord, DiagnosticQuestion, KnowledgeItem, Learner
from app.models.base import Base
from app.services.question_bank_service import (
    QuestionBankError,
    expected_quiz_question_count,
    question_assessment_fingerprint,
    select_mastery_question,
    select_graded_quiz_candidates,
)
from app.services.question_certification_service import QUESTION_CERTIFICATION_RULE_VERSION


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


def test_choice_fingerprint_rejects_option_order_as_new_assessment() -> None:
    first = DiagnosticQuestion(
        knowledge_item_id=7,
        options_json=["Alpha", "Beta", "Gamma", "Delta"],
    )
    reordered = DiagnosticQuestion(
        knowledge_item_id=7,
        options_json=[" delta ", "gamma", "beta", "alpha"],
    )
    different_knowledge = DiagnosticQuestion(
        knowledge_item_id=8,
        options_json=["Delta", "Gamma", "Beta", "Alpha"],
    )

    assert question_assessment_fingerprint(first) == question_assessment_fingerprint(reordered)
    assert question_assessment_fingerprint(first) != question_assessment_fingerprint(different_knowledge)


def test_mastery_retry_stays_on_unmet_knowledge_and_reuses_only_failed_question() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        learner = Learner(public_id="retry_learner", target_domain="ai_app_dev")
        completed = KnowledgeItem(public_id="completed", domain_code="ai_app_dev", name="completed", category="test", difficulty=3, content_md="content", source_title="source")
        unmet = KnowledgeItem(public_id="unmet", domain_code="ai_app_dev", name="unmet", category="test", difficulty=3, content_md="content", source_title="source")
        db.add_all([learner, completed, unmet])
        db.flush()

        def question(public_id: str, knowledge: KnowledgeItem) -> DiagnosticQuestion:
            return DiagnosticQuestion(
                public_id=public_id,
                domain_code="ai_app_dev",
                knowledge_item_id=knowledge.id,
                question_type="single_choice",
                stem=public_id,
                options_json=["A", "B", "C", "D"],
                answer_key_json={"correct_option": 0, "question_bank_uses": ["mastery_validation"]},
                difficulty=4,
                status="active",
                certification_status="certified",
                certification_rule_version=QUESTION_CERTIFICATION_RULE_VERSION,
            )

        completed_question = question("completed_question", completed)
        failed_question = question("failed_question", unmet)
        db.add_all([completed_question, failed_question])
        db.flush()
        db.add(AnswerRecord(
            learner_id=learner.id,
            question_id=failed_question.id,
            knowledge_item_id=unmet.id,
            session_id="failed_attempt",
            is_correct=False,
            scoring_status="scored",
        ))
        db.flush()

        selected, knowledge = select_mastery_question(
            db,
            learner_id=learner.id,
            domain_code="ai_app_dev",
            knowledge_ids=["completed", "unmet"],
            target_difficulty=3,
            use="mastery_validation",
            node_gate={
                "knowledge_progress": [
                    {"knowledge_id": "completed", "mastered": True},
                    {"knowledge_id": "unmet", "mastered": False},
                ]
            },
        )

        assert knowledge.public_id == "unmet"
        assert selected.public_id == "failed_question"


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
