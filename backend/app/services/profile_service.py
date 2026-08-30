from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AnswerRecord,
    DiagnosticQuestion,
    DiagnosticSession,
    Learner,
    LearnerProfile,
    LearningPath,
)
from app.services.knowledge_extraction_service import normalize_knowledge_name

RADAR_KEYS = ["theory", "practice", "problem_solving", "breadth", "learning_speed"]
RESOURCE_TYPES = ["lecture", "practice_guide", "graded_quiz"]
MOJIBAKE_MARKERS = ("Ã", "Â", "å", "æ", "ç", "è", "é", "ð", "\x80", "\x81")
_PATH_UNSET = object()


def public_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def clean_display_text(value: str) -> str:
    if not value or not any(marker in value for marker in MOJIBAKE_MARKERS):
        return normalize_knowledge_name(value)
    try:
        repaired = value.encode("latin1").decode("utf-8")
    except UnicodeError:
        return normalize_knowledge_name(value)
    return normalize_knowledge_name(repaired if repaired else value)


def clean_display_payload(value: Any) -> Any:
    if isinstance(value, str):
        return clean_display_text(value)
    if isinstance(value, list):
        return [clean_display_payload(item) for item in value]
    if isinstance(value, dict):
        return {
            clean_display_text(key) if isinstance(key, str) else key: clean_display_payload(item)
            for key, item in value.items()
        }
    return value


def classify_profile_level(score: float) -> str:
    if score < 60:
        return "beginner"
    if score < 85:
        return "intermediate"
    return "advanced"


def score_single_choice_answer(question: DiagnosticQuestion, answer: Any) -> tuple[float, bool]:
    answer_key = question.answer_key_json or {}
    expected = answer_key.get("correct_option")
    try:
        selected = int(answer)
    except (TypeError, ValueError):
        selected = -1
    is_correct = selected == expected
    return (1.0 if is_correct else 0.0), is_correct


def _bounded(value: float, low: int = 20, high: int = 95) -> int:
    return max(low, min(high, round(value)))


def _category_value(
    category_scores: dict[str, list[float]], keywords: tuple[str, ...], fallback: float
) -> float:
    values: list[float] = []
    for category, scores in category_scores.items():
        if any(keyword.lower() in category.lower() for keyword in keywords):
            values.extend(scores)
    if not values:
        return fallback
    return sum(values) / len(values) * 100


def build_ability_profile(
    score_percent: float,
    category_scores: dict[str, list[float]],
    *,
    average_difficulty: float,
    profile_type: str | None = None,
) -> dict[str, Any]:
    base_type = profile_type or classify_profile_level(score_percent)
    category_mastery = {
        category: round(sum(scores) / len(scores) * 100, 1)
        for category, scores in sorted(category_scores.items())
        if scores
    }

    theory = _category_value(
        category_scores, ("理论", "基础", "prompt", "embedding"), score_percent
    )
    practice = _category_value(
        category_scores, ("实操", "实践", "应用", "rag", "agent"), score_percent - 4
    )
    problem_solving = _bounded((score_percent * 0.7) + (average_difficulty * 8))
    breadth = _bounded((sum(category_mastery.values()) / max(1, len(category_mastery))) - 6)
    learning_speed = _bounded(score_percent + 4)

    ability = {
        "profile_type": base_type,
        "theory": _bounded(theory),
        "practice": _bounded(practice),
        "problem_solving": problem_solving,
        "breadth": breadth,
        "learning_speed": learning_speed,
        "category_mastery": category_mastery,
    }
    if ability["practice"] >= ability["theory"] + 10 and score_percent >= 60:
        ability["profile_type"] = "practice_oriented"
    return ability


def build_learning_path_payload(
    *,
    profile_type: str,
    score_percent: float,
    weak_knowledge: list[dict[str, Any]],
) -> dict[str, Any]:
    from app.services.learning_path_service import normalize_path_payload

    return normalize_path_payload(
        build_learning_path_raw_payload(
            profile_type=profile_type,
            score_percent=score_percent,
            weak_knowledge=weak_knowledge,
        )
    )


def build_learning_path_raw_payload(
    *,
    profile_type: str,
    score_percent: float,
    weak_knowledge: list[dict[str, Any]],
) -> dict[str, Any]:
    prerequisite_ids: list[str] = []
    for item in weak_knowledge:
        for prerequisite in item.get("prerequisites", []):
            if prerequisite not in prerequisite_ids:
                prerequisite_ids.append(prerequisite)

    priority_ids = [item["knowledge_id"] for item in weak_knowledge[:5]]
    stages = []
    if prerequisite_ids:
        stages.append(
            {
                "name": "补齐前置知识",
                "description": "先补足薄弱知识点依赖的基础概念。",
                "knowledge_ids": prerequisite_ids[:5],
            }
        )
    stages.append(
        {
            "name": "攻克薄弱知识点",
            "description": "围绕诊断错题和低分题对应知识点集中练习。",
            "knowledge_ids": priority_ids,
        }
    )
    stages.append(
        {
            "name": "生成个性化资源",
            "description": "生成讲义、实操指南和分阶测试题。",
            "resource_types": RESOURCE_TYPES,
        }
    )
    stages.append(
        {
            "name": "反馈后更新画像",
            "description": "根据太难、太简单、有错误等反馈调整学习路径。",
            "trigger": "resource_feedback",
        }
    )
    return {
        "profile_type": profile_type,
        "score": score_percent,
        "stages": stages,
    }


def build_learning_path_from_snapshot(
    ability_profile: dict[str, Any],
    weak_knowledge: list[dict[str, Any]],
) -> dict[str, Any]:
    scores = [
        float(ability_profile[key])
        for key in RADAR_KEYS
        if isinstance(ability_profile.get(key), (int, float))
    ]
    score_percent = round(sum(scores) / len(scores), 1) if scores else 0.0
    return build_learning_path_payload(
        profile_type=str(ability_profile.get("profile_type") or "beginner"),
        score_percent=score_percent,
        weak_knowledge=weak_knowledge,
    )


def profile_source(profile: LearnerProfile) -> str:
    explicit = getattr(profile, "profile_source", None)
    if explicit:
        return explicit
    if profile.trigger_feedback_id:
        return "validated_feedback"
    if profile.decision_reason == "diagnostic_result":
        return "diagnostic_result"
    if profile.previous_profile_id:
        return "profile_revision"
    return "default_profile"


def latest_profile_for_learner(
    db: Session, learner: Learner, domain_code: str | None = None
) -> LearnerProfile | None:
    selected_domain = str(domain_code or learner.target_domain).strip()
    statement = (
        select(LearnerProfile)
        .where(
            LearnerProfile.learner_id == learner.id,
            LearnerProfile.domain_code == selected_domain,
        )
    )
    if not learner.is_evaluation:
        # Compatibility guard for databases that predate isolated evaluation
        # learners. Legacy evaluation fixtures must never become the active
        # profile of a normal learner, even if they have the greatest row id.
        statement = statement.where(
            LearnerProfile.profile_source != "evaluation_fixture",
            LearnerProfile.public_id.not_like("evaluation_%"),
        )
    return db.scalar(statement.order_by(LearnerProfile.id.desc()))


def is_initial_profile_ready(profile: LearnerProfile | None) -> bool:
    context = profile.context_snapshot_json if profile else {}
    return bool(
        profile
        and profile.diagnosis_completed
        and context.get("education_level")
        and context.get("major")
        and context.get("direction_tags")
        and context.get("confirmed_at")
    )


def latest_path_for_profile(db: Session, profile: LearnerProfile) -> LearningPath | None:
    return db.scalar(
        select(LearningPath)
        .where(LearningPath.profile_id == profile.id)
        .order_by(LearningPath.id.desc())
    )


def default_profile_for_learner(db: Session, learner: Learner) -> LearnerProfile:
    profile = latest_profile_for_learner(db, learner)
    if profile is not None:
        return profile
    profile = LearnerProfile(
        public_id=public_id("profile"),
        learner_id=learner.id,
        domain_code=learner.target_domain,
        ability_profile_json=build_ability_profile(
            55,
            defaultdict(list),
            average_difficulty=2,
            profile_type="beginner",
        ),
        weak_knowledge_json=[],
        profile_source="default_seed",
        diagnosis_completed=False,
    )
    db.add(profile)
    db.flush()
    return profile


def radar_values(ability_profile: dict[str, Any] | None) -> list[int]:
    ability_profile = ability_profile or {}
    return [int(ability_profile.get(key, 0) or 0) for key in RADAR_KEYS]


def profile_ability_level(ability_profile: dict[str, Any] | None) -> int:
    values = radar_values(ability_profile)
    average = sum(values) / max(1, len(values))
    return max(1, min(5, round(average / 20)))


def diagnostic_summary_for_learner(
    db: Session, learner: Learner, domain_code: str | None = None
) -> dict[str, Any]:
    selected_domain = str(domain_code or learner.target_domain).strip()
    diagnostic_session = db.scalar(
        select(DiagnosticSession)
        .where(
            DiagnosticSession.learner_id == learner.id,
            DiagnosticSession.domain_code == selected_domain,
            DiagnosticSession.status == "scored",
        )
        .order_by(DiagnosticSession.updated_at.desc(), DiagnosticSession.id.desc())
    )
    latest_session_id = diagnostic_session.public_id if diagnostic_session else None
    records = (
        list(
            db.scalars(
                select(AnswerRecord)
                .join(DiagnosticQuestion, DiagnosticQuestion.id == AnswerRecord.question_id)
                .where(
                    AnswerRecord.learner_id == learner.id,
                    DiagnosticQuestion.domain_code == selected_domain,
                    AnswerRecord.session_id == latest_session_id,
                )
                .order_by(AnswerRecord.id)
            )
        )
        if latest_session_id
        else []
    )
    total_count = len(records)
    correct_count = sum(record.is_correct is True for record in records)
    total_score = sum(float(record.score or 0) for record in records)
    persisted_result = dict(diagnostic_session.result_json or {}) if diagnostic_session else {}
    # The scored session result is authoritative. Path quizzes, mistake review,
    # and tutoring checks also create AnswerRecord rows but are not diagnostics.
    total_count = int(persisted_result.get("question_count") or total_count)
    correct_count = int(persisted_result.get("correct_count") or correct_count)
    score_percent = (
        float(persisted_result["score"])
        if persisted_result.get("score") is not None
        else round(total_score / total_count * 100, 1) if total_count else 0
    )
    return {
        "answer_count": total_count,
        "correct_count": correct_count,
        # This is the learner-facing overall score: choice and short-answer
        # partial scores are added together, then divided by the question count.
        "total_score": score_percent,
        "accuracy": round(correct_count / total_count * 100, 1) if total_count else 0,
        "latest_session_id": latest_session_id,
    }


def serialize_profile_detail(
    db: Session,
    learner: Learner,
    profile: LearnerProfile | None = None,
    path: LearningPath | None | object = _PATH_UNSET,
) -> dict[str, Any]:
    profile = profile or latest_profile_for_learner(db, learner)
    if profile is None:
        return {
            "learner_id": learner.public_id,
            "domain_code": learner.target_domain,
            "background": clean_display_text(learner.background),
            "education_level": learner.education_level,
            "major": learner.major,
            "direction_tags": learner.direction_tags_json or [],
            "learning_style": learner.learning_style,
            "experience_years": learner.experience_years,
            "profile_status": "not_started",
            "profile_id": None,
            "profile_type": "not_started",
            "ability_profile": {},
            "radar": [0, 0, 0, 0, 0],
            "category_mastery": {},
            "weak_knowledge": [],
            "context_snapshot": {},
            "learning_path": None,
            "diagnostic_summary": diagnostic_summary_for_learner(
                db, learner, learner.target_domain
            ),
        }

    ability_profile = profile.ability_profile_json or {}
    if path is _PATH_UNSET:
        path = latest_path_for_profile(db, profile)
    if path:
        from app.services.learning_path_service import serialize_learning_path

        learning_path = serialize_learning_path(path)
    else:
        learning_path = None
    return {
        "learner_id": learner.public_id,
        "domain_code": profile.domain_code,
        "background": clean_display_text(learner.background),
        "education_level": learner.education_level,
        "major": learner.major,
        "direction_tags": learner.direction_tags_json or [],
        "learning_style": learner.learning_style,
        "experience_years": learner.experience_years,
        "profile_status": "ready" if is_initial_profile_ready(profile) else "not_started",
        "profile_id": profile.public_id,
        "profile_type": ability_profile.get("profile_type", "beginner"),
        "ability_profile": clean_display_payload(ability_profile),
        "radar": radar_values(ability_profile),
        "category_mastery": clean_display_payload(ability_profile.get("category_mastery", {})),
        "weak_knowledge": clean_display_payload(profile.weak_knowledge_json or []),
        "context_snapshot": clean_display_payload(profile.context_snapshot_json or {}),
        "learning_path": clean_display_payload(learning_path),
        "diagnostic_summary": diagnostic_summary_for_learner(db, learner, profile.domain_code),
    }
