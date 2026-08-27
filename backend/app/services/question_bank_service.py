from __future__ import annotations

from collections import defaultdict
import re
from typing import Callable, Iterable, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.contracts import (
    GenerateResourceInput,
    GradedQuizContent,
    QuestionType,
    QuizLevel,
    QuizQuestion,
    RevisionPlan,
    RetrievedQuestion,
    ResourceType,
    SourceRef,
)
from app.models import DiagnosticQuestion, KnowledgeItem
from app.services.question_certification_service import (
    QUESTION_CERTIFICATION_RULE_VERSION,
)


MIN_PRIMARY_QUESTIONS_PER_KNOWLEDGE = 1
MIN_DOMAIN_QUESTION_BANK_SIZE = 60
MAX_SHORT_ANSWER_RUBRIC_POINTS = 8
QuestionCandidate = TypeVar("QuestionCandidate")


class QuestionBankError(ValueError):
    def __init__(self, code: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or {}


def expected_quiz_question_count(knowledge_count: int) -> int:
    """Return the preferred (never mandatory) resource-quiz length for a unit."""

    return min(8, max(3, int(knowledge_count) + 2))


def _profile_level_score(profile_type: str, quiz_level: str) -> int:
    preferred = {
        "beginner": {"foundation": 3, "improvement": 1, "challenge": 0},
        "intermediate": {"foundation": 1, "improvement": 3, "challenge": 1},
        "advanced": {"foundation": 0, "improvement": 2, "challenge": 3},
        "practice_oriented": {"foundation": 2, "improvement": 3, "challenge": 1},
    }
    return preferred.get(profile_type, preferred["intermediate"]).get(quiz_level, 0)


def select_graded_quiz_candidates(
    candidates: Iterable[QuestionCandidate],
    target_ids: Iterable[str],
    *,
    knowledge_id: Callable[[QuestionCandidate], str],
    related_knowledge_ids: Callable[[QuestionCandidate], Iterable[str]],
    quiz_level: Callable[[QuestionCandidate], str],
    require_complete: bool,
    question_id: Callable[[QuestionCandidate], str] | None = None,
    excluded_question_ids: Iterable[str] = (),
    difficulty: Callable[[QuestionCandidate], int] | None = None,
    question_type: Callable[[QuestionCandidate], str] | None = None,
    focus_knowledge_ids: Iterable[str] = (),
    target_difficulty: int = 3,
    profile_type: str = "intermediate",
) -> list[QuestionCandidate]:
    """Select a profile-specific certified quiz without inventing filler items.

    Primary knowledge alignment always outranks relation-only alignment.  The
    caller has already applied the active+certified gate; this selector only
    determines the pedagogical structure of the current learning unit.
    """

    target_set = {str(value) for value in target_ids if str(value)}
    excluded_ids = {str(value) for value in excluded_question_ids if str(value)}
    focus_set = {str(value) for value in focus_knowledge_ids if str(value)}
    scored: list[tuple[QuestionCandidate, int, int, int, str]] = []
    for candidate in candidates:
        if question_id is not None and question_id(candidate) in excluded_ids:
            continue
        primary_id = str(knowledge_id(candidate))
        related_ids = {str(value) for value in related_knowledge_ids(candidate)}
        primary_hit = primary_id in target_set
        related_hit = bool(related_ids & target_set)
        if not primary_hit and not related_hit:
            continue
        try:
            level = QuizLevel(quiz_level(candidate))
        except ValueError:
            continue
        item_difficulty = difficulty(candidate) if difficulty else target_difficulty
        # A primary focus hit is deliberately stronger than any relation hit.
        alignment = 30 if primary_hit else 10
        focus = 8 if primary_id in focus_set else 3 if related_ids & focus_set else 0
        proximity = -abs(int(item_difficulty) - target_difficulty)
        scored.append((candidate, alignment, focus, proximity, level.value))

    selected: list[QuestionCandidate] = []
    covered: set[str] = set()
    selected_types: set[str] = set()
    desired_count = expected_quiz_question_count(len(target_set))
    remaining = list(scored)
    while remaining and len(selected) < desired_count:
        def rank(value: tuple[QuestionCandidate, int, int, int, str]) -> tuple:
            item, alignment, focus, proximity, level = value
            primary_id = str(knowledge_id(item))
            related_ids = {str(part) for part in related_knowledge_ids(item)}
            expands_coverage = int(bool(({primary_id, *related_ids} & target_set) - covered))
            kind = question_type(item) if question_type else ""
            balances_type = int(bool(kind) and kind not in selected_types)
            item_id = question_id(item) if question_id else str(id(item))
            return (
                alignment,
                focus,
                proximity,
                expands_coverage,
                balances_type,
                _profile_level_score(profile_type, level),
                # Keep primary targets and stable IDs deterministic on ties.
                -len(related_ids),
                item_id,
            )

        chosen_row = max(remaining, key=rank)
        remaining.remove(chosen_row)
        chosen = chosen_row[0]
        selected.append(chosen)
        covered.update({str(knowledge_id(chosen)), *(str(value) for value in related_knowledge_ids(chosen))})
        if question_type:
            selected_types.add(question_type(chosen))
    if require_complete and len(selected) < 3:
        raise QuestionBankError(
            "graded_quiz_question_bank_insufficient",
            details={
                "available_question_count": len(selected),
                "minimum_question_count": 3,
                "expected_question_count": desired_count,
                "target_knowledge_ids": sorted(target_set),
                "target_difficulty": target_difficulty,
            },
        )
    return selected


_QUIZ_QUESTION_PATH_RE = re.compile(r"(?:^|\.)questions\[(\d+)](?:\.|$)")


def quiz_revision_question_indexes(revision_plan: RevisionPlan | None) -> list[int]:
    """Return the quiz positions explicitly rejected by the review plan."""

    if revision_plan is None or ResourceType.GRADED_QUIZ not in revision_plan.resource_types:
        return []
    indexes: list[int] = []
    for path in revision_plan.field_paths_by_resource.get(ResourceType.GRADED_QUIZ, []):
        match = _QUIZ_QUESTION_PATH_RE.search(str(path))
        if match is not None:
            indexes.append(int(match.group(1)))
    return list(dict.fromkeys(indexes))


def _eligible_question_values(
    question_type: str,
    options: list,
    answer_key: dict,
) -> bool:
    if not str(answer_key.get("explanation") or "").strip():
        return False
    if not list(answer_key.get("source_ref_ids") or []):
        return False
    if answer_key.get("quiz_level") not in {level.value for level in QuizLevel}:
        return False
    if question_type == QuestionType.SINGLE_CHOICE.value:
        correct = answer_key.get("correct_option")
        return (
            len(options) == 4
            and len({str(option).strip() for option in options}) == 4
            and isinstance(correct, int)
            and 0 <= correct < len(options)
        )
    if question_type == QuestionType.SHORT_ANSWER.value:
        rubric = list(answer_key.get("rubric") or [])
        return (
            bool(str(answer_key.get("answer") or "").strip())
            and 2 <= len(rubric) <= MAX_SHORT_ANSWER_RUBRIC_POINTS
        )
    return False


def is_question_bank_eligible(question: DiagnosticQuestion) -> bool:
    return (
        getattr(question, "status", None) == "active"
        and getattr(question, "certification_status", None) == "certified"
        and getattr(question, "certification_rule_version", None)
        == QUESTION_CERTIFICATION_RULE_VERSION
        and bool(getattr(question, "source_content_hash", None))
        and bool(str(question.stem or "").strip())
        and _eligible_question_values(
            str(question.question_type),
            list(question.options_json or []),
            dict(question.answer_key_json or {}),
        )
    )


def question_bank_coverage(
    db: Session,
    *,
    domain_code: str,
    knowledge_ids: Iterable[str] | None = None,
) -> dict[str, object]:
    item_query = select(KnowledgeItem).where(
        KnowledgeItem.domain_code == domain_code,
        KnowledgeItem.status == "published",
    )
    requested = [str(value) for value in (knowledge_ids or []) if str(value)]
    if requested:
        item_query = item_query.where(KnowledgeItem.public_id.in_(requested))
    items = list(db.scalars(item_query.order_by(KnowledgeItem.id)))
    item_by_id = {item.id: item for item in items}
    counts = {
        item.public_id: {"single_choice": 0, "short_answer": 0, "total": 0}
        for item in items
    }
    distribution = {
        "question_types": defaultdict(int),
        "quiz_levels": defaultdict(int),
        "difficulty_levels": defaultdict(int),
        "eligible_total": 0,
    }
    for knowledge_id in requested:
        counts.setdefault(
            knowledge_id,
            {"single_choice": 0, "short_answer": 0, "total": 0},
        )
    if item_by_id:
        questions = db.scalars(
            select(DiagnosticQuestion).where(
                DiagnosticQuestion.domain_code == domain_code,
                DiagnosticQuestion.status == "active",
                DiagnosticQuestion.certification_status == "certified",
                DiagnosticQuestion.certification_rule_version
                == QUESTION_CERTIFICATION_RULE_VERSION,
                DiagnosticQuestion.knowledge_item_id.in_(item_by_id),
            )
        )
        for question in questions:
            if not is_question_bank_eligible(question):
                continue
            knowledge_id = item_by_id[question.knowledge_item_id].public_id
            counts[knowledge_id][question.question_type] += 1
            counts[knowledge_id]["total"] += 1
            distribution["question_types"][question.question_type] += 1
            distribution["quiz_levels"][str((question.answer_key_json or {}).get("quiz_level"))] += 1
            distribution["difficulty_levels"][str(question.difficulty)] += 1
            distribution["eligible_total"] += 1
    ready_ids = [
        knowledge_id
        for knowledge_id, values in counts.items()
        if values["total"] >= MIN_PRIMARY_QUESTIONS_PER_KNOWLEDGE
    ]
    return {
        "total_items": len(counts),
        "ready_items": len(ready_ids),
        "ready_knowledge_ids": ready_ids,
        "missing_knowledge_ids": sorted(set(counts) - set(ready_ids)),
        "counts_by_knowledge": counts,
        "distribution": {
            "question_types": dict(distribution["question_types"]),
            "quiz_levels": dict(distribution["quiz_levels"]),
            "difficulty_levels": dict(distribution["difficulty_levels"]),
            "eligible_total": distribution["eligible_total"],
        },
        "requirements": {
            "primary_total": MIN_PRIMARY_QUESTIONS_PER_KNOWLEDGE,
            "domain_total": MIN_DOMAIN_QUESTION_BANK_SIZE,
            "levels": [level.value for level in QuizLevel],
            "question_types": [
                QuestionType.SINGLE_CHOICE.value,
                QuestionType.SHORT_ANSWER.value,
            ],
            "difficulty_levels": [1, 2, 3, 4, 5],
        },
    }


def graded_quiz_preflight(
    db: Session,
    *,
    domain_code: str,
    target_knowledge_ids: Iterable[str],
    focus_knowledge_ids: Iterable[str] = (),
    target_difficulty: int = 3,
    profile_type: str = "intermediate",
) -> dict[str, object]:
    """Check a learning unit before a generation task is created.

    This deliberately uses the same deterministic selector as runtime so a
    successful preflight cannot later fail merely because the former six-slot
    blueprint is unavailable.
    """

    target_ids = list(dict.fromkeys(str(value) for value in target_knowledge_ids if str(value)))
    focus_ids = list(dict.fromkeys(str(value) for value in focus_knowledge_ids if str(value)))
    rows = list(
        db.execute(
            select(DiagnosticQuestion, KnowledgeItem.public_id)
            .join(KnowledgeItem, DiagnosticQuestion.knowledge_item_id == KnowledgeItem.id)
            .where(
                DiagnosticQuestion.domain_code == domain_code,
                DiagnosticQuestion.status == "active",
                DiagnosticQuestion.certification_status == "certified",
                DiagnosticQuestion.certification_rule_version == QUESTION_CERTIFICATION_RULE_VERSION,
            )
            .order_by(DiagnosticQuestion.id)
        )
    )
    eligible = [
        row for row in rows
        if is_question_bank_eligible(row[0])
        and (
            row[1] in target_ids
            or bool(set(row[0].related_knowledge_ids_json or []) & set(target_ids))
        )
    ]
    selected = select_graded_quiz_candidates(
        eligible,
        target_ids,
        knowledge_id=lambda row: row[1],
        related_knowledge_ids=lambda row: row[0].related_knowledge_ids_json or [],
        quiz_level=lambda row: str((row[0].answer_key_json or {}).get("quiz_level") or ""),
        question_id=lambda row: row[0].public_id,
        difficulty=lambda row: row[0].difficulty,
        question_type=lambda row: row[0].question_type,
        focus_knowledge_ids=focus_ids,
        target_difficulty=target_difficulty,
        profile_type=profile_type,
        require_complete=False,
    )
    primary_ids = {row[1] for row in eligible if row[1] in target_ids}
    selected_difficulties = [row[0].difficulty for row in selected]
    missing_targets = sorted(set(target_ids) - primary_ids)
    required = expected_quiz_question_count(len(target_ids))
    matching_target_difficulty = sum(
        abs(row[0].difficulty - target_difficulty) <= 1 for row in eligible
    )
    return {
        "ready": len(selected) >= 3,
        "available_question_count": len(selected),
        "minimum_question_count": 3,
        "expected_question_count": required,
        "target_knowledge_ids": target_ids,
        "focus_knowledge_ids": focus_ids,
        "missing_primary_knowledge_ids": missing_targets,
        "target_difficulty": target_difficulty,
        "matching_target_difficulty_count": matching_target_difficulty,
        "selected_question_ids": [row[0].public_id for row in selected],
        "selected_difficulties": selected_difficulties,
        "selected_question_types": [row[0].question_type for row in selected],
        "warning": (
            "当前学习单元题库密度不足"
            if len(selected) < 3
            else "题量低于期望值，已按正式匹配题生成较短测验"
            if len(selected) < required
            else None
        ),
    }


def _valid_reference_question(question: RetrievedQuestion) -> bool:
    return _eligible_question_values(
        question.question_type.value,
        list(question.options),
        dict(question.answer_key),
    )


def _select_reference_questions(
    request: GenerateResourceInput,
    *,
    excluded_question_ids: Iterable[str] = (),
) -> list[tuple[str, QuizLevel, RetrievedQuestion]]:
    target_ids = list(
        request.requirements.resource_knowledge_targets.get(ResourceType.GRADED_QUIZ, [])
    )
    if not target_ids:
        raise QuestionBankError("graded_quiz_question_bank_scope_invalid")
    selected = select_graded_quiz_candidates(
        (question for question in request.reference_questions if _valid_reference_question(question)),
        target_ids,
        knowledge_id=lambda question: question.knowledge_id,
        related_knowledge_ids=lambda question: question.related_knowledge_ids,
        quiz_level=lambda question: str(question.answer_key.get("quiz_level") or ""),
        require_complete=True,
        question_id=lambda question: question.question_id,
        excluded_question_ids=excluded_question_ids,
        difficulty=lambda question: question.difficulty,
        question_type=lambda question: question.question_type.value,
        focus_knowledge_ids=(
            request.current_path_node.focus_knowledge_ids
            if request.current_path_node is not None
            else []
        ),
        target_difficulty=request.requirements.target_difficulty,
        profile_type=request.profile.profile_type.value,
    )
    return [
        (
            question.knowledge_id,
            QuizLevel(str(question.answer_key["quiz_level"])),
            question,
        )
        for question in selected
    ]


def selected_graded_quiz_source_ref_ids(request: GenerateResourceInput) -> list[str]:
    """Return the exact evidence chunks needed by the deterministic quiz selection."""

    return list(
        dict.fromkeys(
            str(source_ref_id)
            for _, _, question in _select_reference_questions(request)
            for source_ref_id in question.answer_key.get("source_ref_ids") or []
            if str(source_ref_id)
        )
    )


def build_graded_quiz_from_question_bank(
    request: GenerateResourceInput,
    allowed_sources: list[SourceRef],
    *,
    excluded_question_ids: Iterable[str] = (),
) -> GradedQuizContent:
    selected = _select_reference_questions(
        request,
        excluded_question_ids=excluded_question_ids,
    )
    allowed_ids = {source.source_ref_id for source in allowed_sources}
    chunks_by_source_ref = {
        chunk.source.source_ref_id: chunk
        for chunk in request.retrieved_chunks
        if chunk.source.source_ref_id in allowed_ids
    }
    questions: list[QuizQuestion] = []
    for knowledge_id, level, question in selected:
        source_ref_ids = [
            str(value) for value in question.answer_key.get("source_ref_ids") or []
        ]
        source_chunks = [
            chunks_by_source_ref.get(source_ref_id) for source_ref_id in source_ref_ids
        ]
        source_locators = dict(question.answer_key.get("source_locators") or {})
        if len(source_ref_ids) == 1 and not source_locators:
            legacy_locator = str(question.answer_key.get("source_locator") or "")
            if legacy_locator:
                source_locators[source_ref_ids[0]] = legacy_locator
        allowed_knowledge_ids = {knowledge_id, *question.related_knowledge_ids}
        if (
            not 1 <= len(source_ref_ids) <= 3
            or any(source_chunk is None for source_chunk in source_chunks)
            or any(
                source_chunk.knowledge_id not in allowed_knowledge_ids
                or source_chunk.source_locator
                != str(source_locators.get(source_chunk.source.source_ref_id) or "")
                for source_chunk in source_chunks
                if source_chunk is not None
            )
        ):
            raise QuestionBankError("graded_quiz_question_source_missing")
        if question.question_type is QuestionType.SINGLE_CHOICE:
            correct_index = int(question.answer_key["correct_option"])
            correct_answer = question.options[correct_index]
        else:
            correct_answer = str(question.answer_key["answer"]).strip()
        questions.append(
            QuizQuestion(
                question_id=question.question_id,
                level=level,
                question_type=question.question_type,
                prompt=question.stem,
                options=list(question.options),
                correct_answer=correct_answer,
                explanation=str(question.answer_key["explanation"]).strip(),
                knowledge_id=knowledge_id,
                related_knowledge_ids=list(question.related_knowledge_ids),
                difficulty=question.difficulty,
                source_ref_ids=[
                    source_chunk.source.source_ref_id
                    for source_chunk in source_chunks
                    if source_chunk is not None
                ],
                reference_question_ids=[question.question_id],
            )
        )
    node_title = (
        request.current_path_node.title
        if request.current_path_node is not None
        else "当前学习节点"
    )
    return GradedQuizContent(
        title=f"{node_title}分级测验",
        target_audience=f"{request.profile.profile_type.value}学习者",
        learning_objectives=[f"检验对{node_title}的理解、应用与迁移能力"],
        questions=questions,
    )
