from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.v1.learners import InitialContextUpdate
from app.models import DiagnosticQuestion, KnowledgeItem, Learner, LearnerProfile
from app.services.diagnostic_service import _initial_context_snapshot, _sample_diagnostic_questions
from app.services.profile_service import is_initial_profile_ready


def _question(
    index: int, question_type: str, practice: bool
) -> tuple[DiagnosticQuestion, KnowledgeItem]:
    category = "RAG 实操" if practice else "Prompt 理论"
    knowledge = KnowledgeItem(
        id=index,
        public_id=f"knowledge_{index}",
        name=f"知识点 {index}",
        category=category,
        tags_json=["rag"] if practice else ["prompt"],
        evidence_capabilities_json=["concept", "operation", "expected_result"]
        if practice
        else ["concept"],
        content_md="content",
        source_title="source",
    )
    question = DiagnosticQuestion(
        id=index,
        public_id=f"question_{index}",
        knowledge_item_id=index,
        question_type=question_type,
        stem=f"题目 {index}",
        options_json=[],
        answer_key_json={
            "question_bank_uses": ["diagnosis"],
            "assessment_dimension": "operation" if practice else "theory",
        },
        difficulty=2,
    )
    return question, knowledge


def test_initial_context_requires_nonempty_unique_direction_tags() -> None:
    payload = {
        "education_level": "本科",
        "major": "软件工程",
        "experience_years": 1,
        "learning_style": "mixed",
        "direction_tags": ["rag_knowledge_base"],
    }
    assert InitialContextUpdate.model_validate(payload).direction_tags == ["rag_knowledge_base"]

    with pytest.raises(ValidationError):
        InitialContextUpdate.model_validate({**payload, "direction_tags": []})
    with pytest.raises(ValidationError):
        InitialContextUpdate.model_validate({**payload, "education_level": "其他"})
    assert InitialContextUpdate.model_validate(
        {**payload, "direction_tags": ["domain_specific_direction"]}
    ).direction_tags == ["domain_specific_direction"]
    with pytest.raises(ValidationError):
        InitialContextUpdate.model_validate(
            {**payload, "direction_tags": ["rag_knowledge_base"] * 2}
        )


def test_initial_diagnostic_has_required_type_and_scenario_distribution() -> None:
    available: list[DiagnosticQuestion] = []
    knowledge_rows: dict[int, KnowledgeItem] = {}
    for question_type, practice, count in [
        ("single_choice", False, 3),
        ("single_choice", True, 3),
        ("short_answer", False, 2),
        ("short_answer", True, 2),
    ]:
        for _ in range(count):
            index = len(available) + 1
            question, knowledge = _question(index, question_type, practice)
            available.append(question)
            knowledge_rows[index] = knowledge

    selected = _sample_diagnostic_questions(
        available,
        knowledge_rows,
        ["rag_knowledge_base", "prompt_engineering"],
        10,
    )

    assert len(selected) == 10
    assert sum(item.question_type == "single_choice" for item in selected) == 6
    assert sum(item.question_type == "short_answer" for item in selected) == 4
    assert sum("实操" in knowledge_rows[item.knowledge_item_id].category for item in selected) == 5


def test_safe_conceptual_diagnostic_uses_six_choice_and_four_short_answer() -> None:
    available: list[DiagnosticQuestion] = []
    knowledge_rows: dict[int, KnowledgeItem] = {}
    for question_type, count in (("single_choice", 6), ("short_answer", 4)):
        for _ in range(count):
            index = len(available) + 1
            question, knowledge = _question(index, question_type, False)
            available.append(question)
            knowledge_rows[index] = knowledge

    selected = _sample_diagnostic_questions(
        available,
        knowledge_rows,
        ["prompt_engineering"],
        10,
    )

    assert len(selected) == 10
    assert sum(item.question_type == "single_choice" for item in selected) == 6
    assert sum(item.question_type == "short_answer" for item in selected) == 4


def test_context_snapshot_is_required_and_profile_readiness_requires_it() -> None:
    learner = Learner(
        id=1,
        public_id="learner_001",
        education_level="本科",
        major="软件工程",
        background="本科｜软件工程",
        experience_years=2,
        learning_style="mixed",
        target_domain="ai_app_dev",
        direction_tags_json=["agent_orchestration"],
    )
    snapshot = _initial_context_snapshot(learner)
    assert snapshot["direction_tags"] == ["agent_orchestration"]
    assert snapshot["confirmed_at"]

    ready = LearnerProfile(
        public_id="profile_ready",
        learner_id=1,
        profile_source="diagnostic",
        diagnosis_completed=True,
        context_snapshot_json=snapshot,
    )
    assert is_initial_profile_ready(ready)

    ready.profile_source = "feedback_revision"
    assert is_initial_profile_ready(ready)

    ready.context_snapshot_json = {}
    assert not is_initial_profile_ready(ready)
    learner.direction_tags_json = []
    with pytest.raises(ValueError, match="initial_context_required"):
        _initial_context_snapshot(learner)
