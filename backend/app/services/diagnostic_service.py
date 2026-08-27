from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import logging
import random
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.contracts import (
    AnalyzeProfileInput,
    DiagnosticSummary,
    EvidenceRef,
    EvidenceType,
    KnowledgeAssessment,
    TaskContext,
)
from app.agents.profile_analysis_agent import ProfileAnalysisAgent
from app.agents.prompt_registry import PROMPT_VERSION, prompt_hash
from app.core.compatibility import AGENT_CONTRACT_VERSION
from app.core.config import settings
from app.core.db import SessionLocal
from app.models import (
    AgentMessageRecord,
    AgentRun,
    AnswerRecord,
    DiagnosticQuestion,
    DiagnosticSession,
    Domain,
    KnowledgeItem,
    Learner,
    LearnerProfile,
    LearningPath,
)
from app.services.learner_service import get_or_create_demo_learner
from app.services.learning_path_service import normalize_path_for_domain, serialize_learning_path
from app.services.domain_runtime_service import (
    DomainRuntime,
    practice_generation_mode_for_items,
    require_ready_domain,
)
from app.services.diagnostic_scoring_service import score_short_answer_batch
from app.services.llm_service import ModelGatewayError
from app.services.mistake_review_service import sync_existing_mistakes
from app.services.question_certification_service import (
    QUESTION_CERTIFICATION_RULE_VERSION,
)
from app.services.profile_service import (
    build_learning_path_from_snapshot,
    default_profile_for_learner,
    is_initial_profile_ready,
    latest_path_for_profile,
    public_id,
    score_single_choice_answer,
)
from app.services.contract_mapping import ability_profile_payload, profile_snapshot

PROFILE_AGENT_NAME = "profile_analysis_agent"
logger = logging.getLogger(__name__)


class DiagnosticScoringPending(RuntimeError):
    pass


SCORING_STATUSES = {"scoring", "pending_scoring"}


def _evidence_based_initial_ability(
    *, assessments: list[KnowledgeAssessment], runtime: DomainRuntime,
    context_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Fuse scored evidence with a deliberately low-weight background prior."""
    config = runtime.profile_config
    if config is None:
        raise ValueError("profile_config_required")
    education = str(context_snapshot.get("education_level") or "")
    major = str(context_snapshot.get("major") or "").lower()
    experience = max(0.0, min(10.0, float(context_snapshot.get("experience_years") or 0)))
    relevant_major = any(marker in major for marker in (
        "软件", "计算机", "人工智能", "数据", "信息", "automation", "computer"
    ))
    education_bonus = 4 if education in {"本科", "硕士及以上"} else 2 if education == "专科" else 0
    background_prior = min(72.0, 42.0 + education_bonus + (5 if relevant_major else 0) + experience * 2)
    dimensions: dict[str, int] = {}
    observed_counts: dict[str, int] = {}
    for dimension in ("theory", "practice", "problem_solving"):
        weighted_scores: list[tuple[float, float]] = []
        for assessment in assessments:
            if not assessment.attempted or assessment.score is None:
                continue
            ability_weight = float(config.ability_weights[assessment.knowledge_id][dimension])
            if ability_weight <= 0:
                continue
            evidence_weight = ability_weight * config.difficulty_weight(assessment.difficulty)
            weighted_scores.append((float(assessment.score), evidence_weight))
        observed_counts[dimension] = len(weighted_scores)
        observed = (
            sum(score * weight for score, weight in weighted_scores)
            / sum(weight for _, weight in weighted_scores) * 100
            if weighted_scores else background_prior
        )
        dimensions[dimension] = round(observed * 0.85 + background_prior * 0.15)
    confidence_values = [float(item.confidence) for item in assessments if item.attempted]
    aggregate = round(sum(dimensions.values()) / len(dimensions))
    return {
        **dimensions,
        "breadth": aggregate,
        "knowledge_breadth": aggregate,
        "learning_speed": 0,
        "evidence_profile": {
            "version": "initial-evidence-v1",
            "ability_dimensions": ["theory", "practice", "problem_solving"],
            "diagnostic_weight": 0.85,
            "background_weight": 0.15,
            "background_prior": round(background_prior, 1),
            "assessed_question_count": len([item for item in assessments if item.attempted]),
            "assessed_knowledge_count": len({item.knowledge_id for item in assessments if item.attempted}),
            "mean_scoring_confidence": round(sum(confidence_values) / len(confidence_values), 2) if confidence_values else 0,
            "observed_counts": observed_counts,
            "learning_speed_status": "insufficient_longitudinal_evidence",
        },
    }


def _answer_hash(question_ids: list[str], answers: list[dict[str, Any]]) -> str:
    by_id = {
        str(item.get("question_id") or ""): (
            None if item.get("answer") is None else str(item.get("answer"))
        )
        for item in answers
    }
    payload = [
        {"question_id": question_id, "answer": by_id.get(question_id)}
        for question_id in question_ids
    ]
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"sha256:{sha256(canonical).hexdigest()}"


def _lease_seconds() -> int:
    return max(300, round(float(settings.llm_timeout_seconds) * 4 + 30))


def _lease_expired(session: DiagnosticSession) -> bool:
    updated_at = session.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - updated_at > timedelta(seconds=_lease_seconds())


def _session_payload(
    session: DiagnosticSession, db: Session | None = None
) -> dict[str, Any]:
    has_pending = _has_pending_short_answers(db, session.public_id) if db is not None else False
    payload = {
        "session_id": session.public_id,
        "status": session.status,
        "domain_code": session.domain_code,
        "progress": session.progress,
        "scoring_attempts": session.scoring_attempts,
        "error_code": session.error_code,
        "retryable": (session.status in {"pending_scoring", "failed"} and has_pending)
        or (session.status == "scoring" and _lease_expired(session)),
        "result": session.result_json if session.status == "scored" else None,
    }
    if db is not None:
        questions = list(
            db.scalars(
                select(DiagnosticQuestion)
                .where(DiagnosticQuestion.public_id.in_(session.question_ids_json or []))
                .order_by(DiagnosticQuestion.id)
            )
        )
        order = {
            question_id: index
            for index, question_id in enumerate(session.question_ids_json or [])
        }
        questions.sort(key=lambda question: order.get(question.public_id, len(order)))
        learner = db.get(Learner, session.learner_id)
        payload.update(
            {
                "learner_id": learner.public_id if learner is not None else None,
                "question_count": len(questions),
                "questions": [_question_payload(question) for question in questions],
                "selection_summary": session.selection_summary_json or {},
            }
        )
    return payload


def _has_pending_short_answers(db: Session, session_id: str) -> bool:
    return (
        db.scalar(
            select(AnswerRecord.id)
            .join(DiagnosticQuestion, DiagnosticQuestion.id == AnswerRecord.question_id)
            .where(
                AnswerRecord.session_id == session_id,
                AnswerRecord.scoring_status.in_({"pending", "pending_scoring"}),
                DiagnosticQuestion.question_type == "short_answer",
            )
            .limit(1)
        )
        is not None
    )


def _load_session_for_learner(
    db: Session, *, session_id: str, learner_id: str, lock: bool = False
) -> DiagnosticSession:
    statement = select(DiagnosticSession).where(DiagnosticSession.public_id == session_id)
    if lock:
        statement = statement.with_for_update()
    session = db.scalar(statement)
    learner = get_or_create_demo_learner(db, learner_id)
    if session is None or session.learner_id != learner.id:
        raise ValueError("diagnostic_session_not_found")
    return session


def get_diagnostic_session_status(
    db: Session, *, session_id: str, learner_id: str
) -> dict[str, Any]:
    return _session_payload(
        _load_session_for_learner(db, session_id=session_id, learner_id=learner_id), db
    )


def get_current_diagnostic_session(
    db: Session, *, learner_id: str, domain_code: str
) -> dict[str, Any] | None:
    """Return the learner's latest diagnostic so onboarding can resume after navigation."""
    learner = get_or_create_demo_learner(db, learner_id)
    session = db.scalar(
        select(DiagnosticSession)
        .where(
            DiagnosticSession.learner_id == learner.id,
            DiagnosticSession.domain_code == domain_code,
        )
        .order_by(DiagnosticSession.updated_at.desc(), DiagnosticSession.id.desc())
        .limit(1)
    )
    return _session_payload(session, db) if session is not None else None


def _question_payload(question: DiagnosticQuestion) -> dict[str, Any]:
    return {
        "question_id": question.public_id,
        "knowledge_id": question.knowledge_item_id,
        "question_type": question.question_type,
        "stem": question.stem,
        "options": question.options_json or [],
        "difficulty": question.difficulty,
    }


def _is_practice_knowledge(knowledge: KnowledgeItem) -> bool:
    return "operation" in (knowledge.evidence_capabilities_json or [])


def _direction_score(
    knowledge: KnowledgeItem,
    direction_tags: list[str],
    runtime: DomainRuntime | None,
) -> int:
    if runtime is None:
        return 0
    configured = {item.value: set(item.match_tags) for item in runtime.learning_directions}
    knowledge_tags = {str(tag).strip().lower() for tag in (knowledge.tags_json or [])}
    return sum(
        len(knowledge_tags & configured.get(direction, set())) for direction in direction_tags
    )


def _take_questions(
    candidates: list[tuple[DiagnosticQuestion, KnowledgeItem, int]],
    count: int,
) -> list[tuple[DiagnosticQuestion, KnowledgeItem, int]]:
    if len(candidates) < count:
        raise ValueError("diagnostic_question_distribution_unavailable")
    ranked = sorted(candidates, key=lambda item: item[2], reverse=True)
    cutoff = ranked[count - 1][2]
    preferred = [item for item in ranked if item[2] >= cutoff]
    return random.sample(preferred, k=count)


def _message(
    db: Session,
    *,
    session_id: str,
    message_type: str,
    payload: dict[str, Any],
) -> None:
    db.add(
        AgentMessageRecord(
            session_id=session_id,
            task_id=session_id,
            sender=PROFILE_AGENT_NAME,
            receiver="orchestrator_agent",
            message_type=message_type,
            payload_summary_json=payload,
        )
    )


def _sample_diagnostic_questions(
    available_questions: list[DiagnosticQuestion],
    knowledge_rows: dict[int, KnowledgeItem],
    direction_tags: list[str],
    question_count: int,
    runtime: DomainRuntime | None = None,
) -> list[DiagnosticQuestion]:
    if int(question_count) != 10:
        raise ValueError("initial_diagnostic_requires_ten_questions")

    evidence_buckets: dict[
        tuple[str, bool], list[tuple[DiagnosticQuestion, KnowledgeItem, int]]
    ] = {
        ("single_choice", False): [],
        ("single_choice", True): [],
        ("short_answer", False): [],
        ("short_answer", True): [],
    }
    for question in available_questions:
        knowledge = knowledge_rows.get(question.knowledge_item_id)
        if knowledge is None or question.question_type not in {"single_choice", "short_answer"}:
            continue
        evidence_buckets[(question.question_type, _is_practice_knowledge(knowledge))].append(
            (question, knowledge, _direction_score(knowledge, direction_tags, runtime))
        )

    selected: list[DiagnosticQuestion] = []
    mode = (
        runtime.practice_generation_mode
        if runtime is not None
        else practice_generation_mode_for_items(list(knowledge_rows.values()))
    )
    if mode == "evidence_backed":
        targets = {
            ("single_choice", False): 3,
            ("single_choice", True): 3,
            ("short_answer", False): 2,
            ("short_answer", True): 2,
        }
        for bucket, target in targets.items():
            selected.extend(
                question
                for question, _, _ in _take_questions(evidence_buckets[bucket], target)
            )
    else:
        type_targets = {"single_choice": 6, "short_answer": 4}
        for question_type, target in type_targets.items():
            candidates = [
                item
                for (bucket_type, _practice), bucket_items in evidence_buckets.items()
                if bucket_type == question_type
                for item in bucket_items
            ]
            selected.extend(question for question, _, _ in _take_questions(candidates, target))
    random.shuffle(selected)
    return selected


def _initial_context_snapshot(
    learner, *, domain_code: str | None = None, confirmed_at: str | None = None
) -> dict[str, Any]:
    domain_code = domain_code or learner.target_domain
    direction_tags = list(learner.direction_tags_json or [])
    if not learner.education_level or not learner.major or not direction_tags:
        raise ValueError("initial_context_required")
    if learner.target_domain != domain_code:
        raise ValueError("learner_domain_mismatch")
    return {
        "education_level": learner.education_level,
        "major": learner.major,
        "background": learner.background,
        "experience_years": learner.experience_years,
        "learning_style": learner.learning_style,
        "target_domain": learner.target_domain,
        "direction_tags": direction_tags,
        "confirmed_at": confirmed_at or datetime.now(UTC).isoformat(),
    }


def prepare_diagnostic_submission(
    db: Session,
    *,
    session_id: str,
    learner_id: str,
    domain_code: str,
    answers: list[dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    """Persist immutable answers and atomically claim an asynchronous scoring lease."""

    session = _load_session_for_learner(
        db, session_id=session_id, learner_id=learner_id, lock=True
    )
    if session.domain_code != domain_code:
        raise ValueError("diagnostic_session_access_denied")
    question_ids = [str(item) for item in (session.question_ids_json or [])]
    answer_by_question_id: dict[str, Any] = {}
    for item in answers:
        question_id = str(item.get("question_id") or "")
        if not question_id or question_id in answer_by_question_id:
            raise ValueError("diagnostic_answers_invalid")
        answer_by_question_id[question_id] = item.get("answer")
    if set(answer_by_question_id) != set(question_ids) or len(answer_by_question_id) != 10:
        raise ValueError("diagnostic_answers_do_not_match_session")

    submitted_hash = _answer_hash(question_ids, answers)
    if session.answer_hash and session.answer_hash != submitted_hash:
        raise ValueError("diagnostic_answers_changed")
    if session.status == "scored":
        return _session_payload(session, db), False
    if session.status == "scoring" and not _lease_expired(session):
        return _session_payload(session, db), False

    learner = get_or_create_demo_learner(db, learner_id)
    questions = list(
        db.scalars(
            select(DiagnosticQuestion)
            .join(KnowledgeItem, DiagnosticQuestion.knowledge_item_id == KnowledgeItem.id)
            .where(
                DiagnosticQuestion.public_id.in_(question_ids),
                DiagnosticQuestion.domain_code == domain_code,
                DiagnosticQuestion.status == "active",
                DiagnosticQuestion.certification_status == "certified",
                DiagnosticQuestion.certification_rule_version
                == QUESTION_CERTIFICATION_RULE_VERSION,
                KnowledgeItem.domain_code == domain_code,
                KnowledgeItem.status == "published",
            )
        )
    )
    if len(questions) != len(question_ids):
        raise ValueError("diagnostic_session_has_no_valid_questions")
    existing = {
        record.question_id: record
        for record in db.scalars(
            select(AnswerRecord).where(
                AnswerRecord.learner_id == learner.id,
                AnswerRecord.session_id == session_id,
            )
        )
    }
    for question in questions:
        answer = answer_by_question_id[question.public_id]
        answer_text = "" if answer is None else str(answer)
        record = existing.get(question.id)
        if record is None:
            db.add(
                AnswerRecord(
                    learner_id=learner.id,
                    question_id=question.id,
                    knowledge_item_id=question.knowledge_item_id,
                    session_id=session_id,
                    answer_text=answer_text,
                    score=0,
                    is_correct=False,
                    scoring_status=(
                        "pending" if question.question_type == "short_answer" else "scored"
                    ),
                    scoring_method=(
                        "ai_rubric"
                        if question.question_type == "short_answer"
                        else "deterministic"
                    ),
                    confidence=None if question.question_type == "short_answer" else 1.0,
                    answer_summary_json={},
                )
            )
        elif record.answer_text != answer_text:
            raise ValueError("diagnostic_answers_changed")

    session.answer_hash = submitted_hash
    session.status = "scoring"
    session.progress = max(session.progress, 10)
    session.error_code = None
    session.scoring_attempts += 1
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        current = _load_session_for_learner(
            db, session_id=session_id, learner_id=learner_id
        )
        if current.answer_hash == submitted_hash and current.status in SCORING_STATUSES | {
            "scored"
        }:
            return _session_payload(current, db), False
        raise
    db.refresh(session)
    return _session_payload(session, db), True


def retry_diagnostic_session(
    db: Session, *, session_id: str, learner_id: str
) -> tuple[dict[str, Any], bool]:
    session = _load_session_for_learner(
        db, session_id=session_id, learner_id=learner_id, lock=True
    )
    if session.status == "scored":
        return _session_payload(session, db), False
    if session.answer_hash is None:
        raise ValueError("diagnostic_answers_required")
    if session.status == "scoring" and not _lease_expired(session):
        return _session_payload(session, db), False
    if session.status not in {"pending_scoring", "failed", "scoring"}:
        raise ValueError("diagnostic_session_not_retryable")
    if not _has_pending_short_answers(db, session_id):
        raise ValueError("diagnostic_session_not_retryable")
    session.status = "scoring"
    session.error_code = None
    session.scoring_attempts += 1
    db.commit()
    db.refresh(session)
    return _session_payload(session, db), True


def create_diagnostic_session(
    db: Session,
    *,
    learner_id: str = "learner_001",
    domain_code: str,
    question_count: int = 10,
) -> dict[str, Any]:
    learner = get_or_create_demo_learner(db, learner_id)
    context_snapshot = _initial_context_snapshot(learner, domain_code=domain_code)
    runtime = require_ready_domain(db, domain_code)
    if not runtime.diagnostic_ready:
        raise ValueError(f"DOMAIN_DIAGNOSTIC_NOT_READY:{','.join(runtime.reasons)}")
    profile = default_profile_for_learner(db, learner)
    if is_initial_profile_ready(profile):
        raise ValueError("initial_profile_already_ready")
    available_questions = list(
        db.scalars(
            select(DiagnosticQuestion)
            .join(KnowledgeItem, DiagnosticQuestion.knowledge_item_id == KnowledgeItem.id)
            .where(DiagnosticQuestion.domain_code == domain_code)
            .where(DiagnosticQuestion.status == "active")
            .where(DiagnosticQuestion.certification_status == "certified")
            .where(
                DiagnosticQuestion.certification_rule_version
                == QUESTION_CERTIFICATION_RULE_VERSION
            )
            .where(KnowledgeItem.domain_code == domain_code)
            .where(KnowledgeItem.status == "published")
            .order_by(DiagnosticQuestion.difficulty, DiagnosticQuestion.public_id)
        )
    )
    knowledge_rows = {
        item.id: item
        for item in db.scalars(
            select(KnowledgeItem).where(
                KnowledgeItem.id.in_(
                    {question.knowledge_item_id for question in available_questions}
                ),
                KnowledgeItem.domain_code == domain_code,
            )
        )
    }
    questions = _sample_diagnostic_questions(
        available_questions,
        knowledge_rows,
        context_snapshot["direction_tags"],
        question_count,
        runtime,
    )
    practice_count = sum(
        1
        for question in questions
        if _is_practice_knowledge(knowledge_rows[question.knowledge_item_id])
    )
    session_id = public_id("diag")
    selection_summary = {
        "direction_tags": context_snapshot["direction_tags"],
        "single_choice_count": 6,
        "short_answer_count": 4,
        "theory_count": len(questions) - practice_count,
        "practice_count": practice_count,
        "practice_generation_mode": runtime.practice_generation_mode,
    }
    db.add(
        DiagnosticSession(
            public_id=session_id,
            learner_id=learner.id,
            domain_code=domain_code,
            status="created",
            question_ids_json=[question.public_id for question in questions],
            context_snapshot_json=context_snapshot,
            selection_summary_json=selection_summary,
            progress=0,
        )
    )
    db.add(
        AgentMessageRecord(
            session_id=session_id,
            task_id=session_id,
            sender="orchestrator_agent",
            receiver=PROFILE_AGENT_NAME,
            message_type="command",
            payload_summary_json={
                "event": "diagnostic_session_created",
                "learner_id": learner.public_id,
                "domain_code": domain_code,
                "question_ids": [question.public_id for question in questions],
                "selection_summary": selection_summary,
                "context_snapshot": context_snapshot,
            },
        )
    )
    db.commit()
    return {
        "session_id": session_id,
        "learner_id": learner.public_id,
        "domain_code": domain_code,
        "question_count": len(questions),
        "status": "created",
        "questions": [_question_payload(question) for question in questions],
        "selection_summary": selection_summary,
    }


def submit_diagnostic_session(
    db: Session,
    *,
    session_id: str,
    learner_id: str = "learner_001",
    domain_code: str,
    answers: list[dict[str, Any]],
) -> dict[str, Any]:
    learner = get_or_create_demo_learner(db, learner_id)
    runtime = require_ready_domain(db, domain_code)
    if not runtime.diagnostic_ready or runtime.profile_config is None:
        raise ValueError(f"DOMAIN_DIAGNOSTIC_NOT_READY:{','.join(runtime.reasons)}")
    session = _load_session_for_learner(
        db, session_id=session_id, learner_id=learner_id
    )
    if session.domain_code != domain_code:
        raise ValueError("diagnostic_session_access_denied")
    if session.answer_hash is None:
        prepare_diagnostic_submission(
            db,
            session_id=session_id,
            learner_id=learner_id,
            domain_code=domain_code,
            answers=answers,
        )
        session = _load_session_for_learner(
            db, session_id=session_id, learner_id=learner_id
        )
    elif session.answer_hash != _answer_hash(list(session.question_ids_json or []), answers):
        raise ValueError("diagnostic_answers_changed")
    if session.status == "scored" and session.result_json:
        return dict(session.result_json)
    context_snapshot = session.context_snapshot_json
    selected_question_ids = session.question_ids_json
    if not isinstance(context_snapshot, dict) or not isinstance(selected_question_ids, list):
        raise ValueError("diagnostic_session_invalid")

    answer_by_question_id: dict[str, Any] = {}
    for item in answers:
        question_id = str(item.get("question_id") or "")
        if not question_id or question_id in answer_by_question_id:
            raise ValueError("diagnostic_answers_invalid")
        answer_by_question_id[question_id] = item.get("answer")
    if set(answer_by_question_id) != set(selected_question_ids) or len(answer_by_question_id) != 10:
        raise ValueError("diagnostic_answers_do_not_match_session")
    question_ids = list(selected_question_ids)
    questions = list(
        db.scalars(
            select(DiagnosticQuestion)
            .join(KnowledgeItem, DiagnosticQuestion.knowledge_item_id == KnowledgeItem.id)
            .where(
                DiagnosticQuestion.public_id.in_(question_ids),
                DiagnosticQuestion.domain_code == domain_code,
                DiagnosticQuestion.status == "active",
                DiagnosticQuestion.certification_status == "certified",
                DiagnosticQuestion.certification_rule_version
                == QUESTION_CERTIFICATION_RULE_VERSION,
                KnowledgeItem.domain_code == domain_code,
                KnowledgeItem.status == "published",
            )
        )
    )
    if len(questions) != 10:
        raise ValueError("diagnostic_session_has_no_valid_questions")

    started_at = time.perf_counter()
    run = AgentRun(
        generation_task_id=None,
        agent_name=PROFILE_AGENT_NAME,
        status="running",
        input_summary_json={
            "session_id": session_id,
            "learner_id": learner.public_id,
            "domain_code": domain_code,
            "profile_mode": "analyze_diagnostic",
            "question_count": len(questions),
            "question_ids": question_ids,
        },
        output_summary_json={},
        llm_calls=0,
        tokens_used=0,
        duration_ms=0,
        prompt_version=PROMPT_VERSION,
        prompt_hash=prompt_hash("profile"),
        contract_version=AGENT_CONTRACT_VERSION,
    )
    db.add(run)
    _message(
        db,
        session_id=session_id,
        message_type="command",
        payload={
            "session_id": session_id,
            "learner_id": learner.public_id,
            "status": "running",
            "question_count": len(questions),
        },
    )
    db.flush()

    try:
        knowledge_rows = {
            item.id: item
            for item in db.scalars(
                select(KnowledgeItem).where(
                    KnowledgeItem.id.in_({question.knowledge_item_id for question in questions}),
                    KnowledgeItem.domain_code == domain_code,
                )
            )
        }
        evidence_refs: list[EvidenceRef] = []
        assessments: list[KnowledgeAssessment] = []
        correct_count = 0
        answered_count = 0
        total_score = 0.0
        category_scores: dict[str, list[float]] = defaultdict(list)
        existing_records = {
            record.question_id: record
            for record in db.scalars(
                select(AnswerRecord).where(
                    AnswerRecord.learner_id == learner.id,
                    AnswerRecord.session_id == session_id,
                )
            )
        }
        records: dict[int, AnswerRecord] = {}
        short_answer_items: list[tuple[DiagnosticQuestion, str]] = []

        for question in questions:
            knowledge = knowledge_rows.get(question.knowledge_item_id)
            if knowledge is None:
                raise ValueError("diagnostic_question_missing_knowledge_item")
            answer = answer_by_question_id.get(question.public_id)
            attempted = answer is not None and str(answer).strip() != ""
            answer_text = str(answer) if attempted else ""
            record = existing_records.get(question.id)
            if record is None:
                record = AnswerRecord(
                    learner_id=learner.id,
                    question_id=question.id,
                    knowledge_item_id=knowledge.id,
                    session_id=session_id,
                    answer_text=answer_text,
                    score=0,
                    is_correct=False,
                    scoring_status="pending"
                    if question.question_type == "short_answer"
                    else "scored",
                    scoring_method=(
                        "ai_rubric" if question.question_type == "short_answer" else "deterministic"
                    ),
                    answer_summary_json={},
                )
                db.add(record)
                db.flush()
            elif record.answer_text != answer_text:
                raise ValueError("diagnostic_answers_changed")
            records[question.id] = record

            if question.question_type == "single_choice":
                score, is_correct = (
                    score_single_choice_answer(question, answer) if attempted else (0.0, False)
                )
                record.score = score
                record.is_correct = is_correct
                record.scoring_status = "scored"
                record.scoring_method = "deterministic"
                record.confidence = 1.0
            elif record.scoring_status != "scored":
                short_answer_items.append((question, answer_text))

        if short_answer_items:
            domain = db.scalar(select(Domain).where(Domain.domain_code == domain_code))
            try:
                scored_answers, scoring_metadata = score_short_answer_batch(
                    short_answer_items,
                    domain_display_name=domain.name if domain is not None else domain_code,
                )
            except (ModelGatewayError, ValueError) as exc:
                scoring_metadata = dict(getattr(exc, "metadata", {}) or {})
                scoring_metadata.setdefault("llm_calls", int(scoring_metadata.get("attempt") or 0))
                scoring_metadata["failed_question_ids"] = [
                    question.public_id for question, _answer in short_answer_items
                ]
                scored_answers = {}
            run.llm_calls = int(scoring_metadata.get("llm_calls") or 0)
            run.tokens_input = int(scoring_metadata.get("tokens_input") or 0)
            run.tokens_output = int(scoring_metadata.get("tokens_output") or 0)
            run.tokens_used = run.tokens_input + run.tokens_output
            run.model_name = str(scoring_metadata.get("model_name") or "") or None
            failed_question_ids = set(scoring_metadata.get("failed_question_ids") or [])
            for question, _answer in short_answer_items:
                result_item = scored_answers.get(question.public_id)
                record = records[question.id]
                if result_item is None:
                    record.scoring_status = "pending_scoring"
                    record.confidence = None
                    failed_question_ids.add(question.public_id)
                    continue
                record.score = float(result_item["total_score"])
                record.is_correct = bool(result_item["is_correct"])
                record.scoring_status = "scored"
                record.scoring_method = "ai_rubric"
                record.rubric_version = str(result_item["rubric_version"])
                record.scoring_detail_json = {
                    **{
                        key: value
                        for key, value in result_item.items()
                        if key
                        not in {
                            "question_id",
                            "total_score",
                            "is_correct",
                            "rubric_version",
                            "confidence",
                            "scoring_uncertain",
                            "ai_comment",
                        }
                    },
                    "model_name": run.model_name,
                }
                record.confidence = float(result_item["confidence"])
                record.scoring_uncertain = bool(result_item["scoring_uncertain"])
                record.ai_comment = str(result_item["ai_comment"])

            if failed_question_ids:
                for question, _answer in short_answer_items:
                    if question.public_id in failed_question_ids:
                        records[question.id].scoring_status = "pending_scoring"
                run.status = "failed"
                run.error_message = "DIAGNOSTIC_SCORING_PENDING"
                run.output_summary_json = {
                    "session_id": session_id,
                    "error_code": "DIAGNOSTIC_SCORING_PENDING",
                    "pending_question_count": len(failed_question_ids),
                    "failed_question_ids": sorted(failed_question_ids),
                    "validation_fields": scoring_metadata.get("validation_fields", {}),
                    "model_calls": scoring_metadata.get("calls", []),
                }
                run.duration_ms = round((time.perf_counter() - started_at) * 1000)
                session.status = "pending_scoring"
                session.error_code = "DIAGNOSTIC_SCORING_PENDING"
                scored_count = sum(
                    record.scoring_status == "scored" for record in records.values()
                )
                session.progress = max(session.progress, round(scored_count / len(records) * 90 + 10))
                db.commit()
                raise DiagnosticScoringPending("DIAGNOSTIC_SCORING_PENDING")

        answer_results: list[dict[str, Any]] = []
        for question in questions:
            knowledge = knowledge_rows[question.knowledge_item_id]
            answer = answer_by_question_id.get(question.public_id)
            attempted = answer is not None and str(answer).strip() != ""
            record = records[question.id]
            score, is_correct = float(record.score), bool(record.is_correct)
            evidence_id = (
                f"diag_{sha256(f'{session_id}:{question.public_id}'.encode()).hexdigest()[:32]}"
            )
            assessment_id = f"assess_{sha256(evidence_id.encode()).hexdigest()[:32]}"
            evidence_refs.append(
                EvidenceRef(
                    evidence_id=evidence_id,
                    evidence_type=EvidenceType.DIAGNOSTIC_RESULT,
                    summary="诊断题已完成结构化评分" if attempted else "诊断题未作答",
                    knowledge_id=knowledge.public_id,
                    confidence=record.confidence,
                    confirmed=True,
                )
            )
            assessments.append(
                KnowledgeAssessment(
                    assessment_id=assessment_id,
                    evidence_id=evidence_id,
                    knowledge_id=knowledge.public_id,
                    score=score if attempted else None,
                    difficulty=question.difficulty,
                    attempted=attempted,
                    confidence=record.confidence,
                )
            )
            record.answer_summary_json = {
                "session_id": session_id,
                "question_id": question.public_id,
                "answer_type": question.question_type,
                "score": round(score, 2),
                "attempted": attempted,
                "scoring_method": record.scoring_method,
                "scoring_uncertain": record.scoring_uncertain,
            }
            detail = record.scoring_detail_json or {}
            answer_results.append(
                {
                    "question_id": question.public_id,
                    "question_type": question.question_type,
                    "score": round(score, 4),
                    "is_correct": is_correct,
                    "scoring_method": record.scoring_method,
                    "ai_comment": record.ai_comment,
                    "criteria": detail.get("criteria", []),
                    "matched_points": detail.get("matched_points", []),
                    "missing_points": detail.get("missing_points", []),
                    "factual_errors": detail.get("factual_errors", []),
                    "confidence": record.confidence,
                    "scoring_uncertain": record.scoring_uncertain,
                }
            )
            if attempted:
                answered_count += 1
                total_score += score
                correct_count += int(is_correct)
                category_scores[knowledge.category].append(score)

        score_percent = round(total_score / len(questions) * 100, 1)
        current_profile = default_profile_for_learner(db, learner)
        current_snapshot = profile_snapshot(current_profile)
        context = TaskContext(
            task_id=session_id,
            session_id=session_id,
            trigger_type="initial_generation",
            execution_mode="auto",
            learner_id=learner.public_id,
            profile_id=current_profile.public_id,
            domain_code=domain_code,
            resource_types=["lecture", "practice_guide", "graded_quiz"],
            learning_goal="根据诊断结果形成学习画像和个性化学习路径",
        )
        analysis = ProfileAnalysisAgent(runtime.profile_config).execute(
            AnalyzeProfileInput(
                task_id=session_id,
                context=context,
                current_profile=current_snapshot,
                diagnostic_summary=DiagnosticSummary(
                    diagnostic_session_id=session_id,
                    question_count=len(questions),
                    answered_count=answered_count,
                    correct_count=correct_count,
                    skipped_count=len(questions) - answered_count,
                    score_percent=score_percent,
                    evidence=evidence_refs,
                ),
                knowledge_assessments=assessments,
            )
        )

        active_profile = current_profile
        if analysis.profile_update_required:
            ability_payload = ability_profile_payload(analysis.profile)
            ability_payload.update(_evidence_based_initial_ability(
                assessments=assessments,
                runtime=runtime,
                context_snapshot=context_snapshot,
            ))
            observed_average = sum(
                int(ability_payload[key])
                for key in ("theory", "practice", "problem_solving")
            ) / 3
            ability_payload["profile_type"] = (
                "practice_oriented"
                if int(ability_payload["practice"]) >= int(ability_payload["theory"]) + 10
                and int(ability_payload["practice"]) >= 60
                else "advanced" if observed_average >= 85
                else "intermediate" if observed_average >= 60
                else "beginner"
            )
            ability_payload["category_mastery"] = {
                category: round(sum(scores) / len(scores) * 100, 1)
                for category, scores in sorted(category_scores.items())
                if scores
            }
            active_profile = LearnerProfile(
                public_id=public_id("profile"),
                learner_id=learner.id,
                domain_code=domain_code,
                ability_profile_json=ability_payload,
                weak_knowledge_json=[
                    item.model_dump(mode="json") for item in analysis.profile.weak_knowledge
                ],
                profile_version=analysis.profile.profile_version,
                previous_profile_id=current_profile.id,
                profile_source="diagnostic",
                diagnosis_completed=True,
                context_snapshot_json=context_snapshot,
                changed_dimensions_json=analysis.changed_dimensions,
                evidence_refs_json=[
                    item.model_dump(mode="json") for item in analysis.evidence_refs
                ],
                confidence=analysis.confidence,
                decision_reason=analysis.decision_reason,
            )
            db.add(active_profile)
            db.flush()
            for path in db.scalars(
                select(LearningPath).where(LearningPath.profile_id == current_profile.id)
            ):
                path.needs_refresh = True

        path = latest_path_for_profile(db, active_profile)
        if path is None:
            path = LearningPath(
                public_id=public_id("path"),
                learner_id=learner.id,
                profile_id=active_profile.id,
                domain_code=domain_code,
                status="active",
                path_json=build_learning_path_from_snapshot(
                    active_profile.ability_profile_json,
                    active_profile.weak_knowledge_json,
                ),
                needs_refresh=False,
            )
            db.add(path)
            db.flush()
            path.path_json = normalize_path_for_domain(
                db,
                domain_code=domain_code,
                payload=path.path_json or {},
            )

        result = {
            "session_id": session_id,
            "learner_id": learner.public_id,
            "status": "scored",
            "score": score_percent,
            "correct_count": correct_count,
            "question_count": len(questions),
            "profile_id": active_profile.public_id,
            "profile_version": active_profile.profile_version,
            "previous_profile_id": current_profile.public_id
            if active_profile.id != current_profile.id
            else None,
            "profile_changed_dimensions": analysis.changed_dimensions,
            "profile_source": "diagnostic_result",
            "profile_type": str(
                (active_profile.ability_profile_json or {}).get("profile_type")
                or analysis.profile.profile_type.value
            ),
            "ability_profile": active_profile.ability_profile_json,
            "weak_knowledge": active_profile.weak_knowledge_json,
            "learning_path_id": path.public_id,
            "learning_path": serialize_learning_path(path),
            "answer_results": answer_results,
            "next_action": "create_generation_task",
        }
        output_summary = {
            "session_id": session_id,
            "learner_id": learner.public_id,
            "profile_id": result["profile_id"],
            "profile_type": result["profile_type"],
            "score": result["score"],
            "weak_knowledge_count": len(result.get("weak_knowledge", [])),
            "learning_path_id": result["learning_path_id"],
            "evidence_question_count": len(questions),
        }
        run.status = "completed"
        run.output_summary_json = output_summary
        run.duration_ms = round((time.perf_counter() - started_at) * 1000)
        _message(
            db,
            session_id=session_id,
            message_type="result",
            payload={**output_summary, "status": "completed"},
        )
        db.add(
            AgentMessageRecord(
                session_id=session_id,
                task_id=session_id,
                sender="orchestrator_agent",
                receiver=PROFILE_AGENT_NAME,
                message_type="result",
                payload_summary_json={
                    "event": "diagnostic_session_submitted",
                    "learner_id": learner.public_id,
                    "profile_id": result["profile_id"],
                },
            )
        )
        final_result = {
            **result,
            "agent_run_id": run.id,
            "agent_name": PROFILE_AGENT_NAME,
        }
        session.status = "scored"
        session.progress = 100
        session.error_code = None
        session.profile_id = active_profile.id
        session.learning_path_id = path.id
        session.result_json = final_result
        sync_existing_mistakes(db, learner=learner, domain_code=domain_code)
        db.commit()
        return final_result
    except DiagnosticScoringPending:
        raise
    except Exception as exc:
        error_code = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        duration_ms = round((time.perf_counter() - started_at) * 1000)
        llm_calls = int(getattr(run, "llm_calls", 0) or 0)
        tokens_input = int(getattr(run, "tokens_input", 0) or 0)
        tokens_output = int(getattr(run, "tokens_output", 0) or 0)
        model_name = getattr(run, "model_name", None)
        db.rollback()
        failure_session = db.scalar(
            select(DiagnosticSession).where(DiagnosticSession.public_id == session_id)
        )
        if failure_session is not None and failure_session.status != "pending_scoring":
            failure_session.status = "failed"
            failure_session.error_code = error_code[:128]
        failure_run = AgentRun(
            generation_task_id=None,
            agent_name=PROFILE_AGENT_NAME,
            status="failed",
            input_summary_json={
                "session_id": session_id,
                "learner_id": learner.public_id,
                "domain_code": domain_code,
                "profile_mode": "analyze_diagnostic",
            },
            output_summary_json={"session_id": session_id, "error_code": error_code},
            error_message=error_code[:1000],
            llm_calls=llm_calls,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            tokens_used=tokens_input + tokens_output,
            model_name=model_name,
            duration_ms=duration_ms,
            prompt_version=PROMPT_VERSION,
            prompt_hash=prompt_hash("profile"),
            contract_version=AGENT_CONTRACT_VERSION,
        )
        db.add(failure_run)
        _message(
            db,
            session_id=session_id,
            message_type="error",
            payload={"session_id": session_id, "status": "failed", "error_code": error_code},
        )
        db.commit()
        raise


def run_diagnostic_scoring_job(session_id: str) -> None:
    """Background entrypoint that rebuilds the immutable submission from stored answers."""

    try:
        with SessionLocal() as db:
            session = db.scalar(
                select(DiagnosticSession).where(DiagnosticSession.public_id == session_id)
            )
            if session is None or session.status != "scoring":
                return
            learner = db.get(Learner, session.learner_id)
            if learner is None:
                raise ValueError("diagnostic_session_learner_not_found")
            rows = list(
                db.execute(
                    select(DiagnosticQuestion, AnswerRecord)
                    .join(AnswerRecord, AnswerRecord.question_id == DiagnosticQuestion.id)
                    .where(AnswerRecord.session_id == session_id)
                )
            )
            answers = [
                {"question_id": question.public_id, "answer": record.answer_text}
                for question, record in rows
            ]
            submit_diagnostic_session(
                db,
                session_id=session_id,
                learner_id=learner.public_id,
                domain_code=session.domain_code,
                answers=answers,
            )
    except DiagnosticScoringPending:
        return
    except Exception:
        logger.exception("diagnostic scoring job failed session_id=%s", session_id)
