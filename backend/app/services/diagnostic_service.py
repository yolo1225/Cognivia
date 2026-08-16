from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from hashlib import sha256
import random
import time
from typing import Any

from sqlalchemy import select
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
from app.models import (
    AgentMessageRecord,
    AgentRun,
    AnswerRecord,
    DiagnosticQuestion,
    KnowledgeItem,
    LearnerProfile,
    LearningPath,
)
from app.services.learner_service import get_or_create_demo_learner
from app.services.profile_service import (
    build_learning_path_from_snapshot,
    default_profile_for_learner,
    is_initial_profile_ready,
    latest_path_for_profile,
    public_id,
    score_answer,
)
from app.services.contract_mapping import ability_profile_payload, profile_snapshot

PROFILE_AGENT_NAME = "profile_analysis_agent"


def _question_payload(question: DiagnosticQuestion) -> dict[str, Any]:
    return {
        "question_id": question.public_id,
        "knowledge_id": question.knowledge_item_id,
        "question_type": question.question_type,
        "stem": question.stem,
        "options": question.options_json or [],
        "difficulty": question.difficulty,
    }


_DIRECTION_KEYWORDS = {
    "llm_application": {"llm", "model", "api", "workflow", "overview"},
    "prompt_engineering": {"prompt", "context", "structured", "json"},
    "rag_knowledge_base": {"rag", "retrieval", "embedding", "vector", "knowledge"},
    "agent_orchestration": {"agent", "tool", "orchestration", "workflow", "planning"},
}
_PRACTICE_KEYWORDS = {"rag", "agent", "工程", "后端", "前端", "系统", "向量", "模型调用", "实操", "应用"}


def _is_practice_question(question: DiagnosticQuestion, knowledge: KnowledgeItem) -> bool:
    text = " ".join(
        [knowledge.category, knowledge.name, question.stem, *[str(tag) for tag in (knowledge.tags_json or [])]]
    ).lower()
    return any(keyword.lower() in text for keyword in _PRACTICE_KEYWORDS)


def _direction_score(knowledge: KnowledgeItem, direction_tags: list[str]) -> int:
    text = " ".join([knowledge.category, knowledge.name, *[str(tag) for tag in (knowledge.tags_json or [])]]).lower()
    return sum(
        1
        for direction in direction_tags
        for keyword in _DIRECTION_KEYWORDS.get(direction, set())
        if keyword in text
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
) -> list[DiagnosticQuestion]:
    if int(question_count) != 10:
        raise ValueError("initial_diagnostic_requires_ten_questions")

    buckets: dict[tuple[str, bool], list[tuple[DiagnosticQuestion, KnowledgeItem, int]]] = {
        ("single_choice", False): [],
        ("single_choice", True): [],
        ("short_answer", False): [],
        ("short_answer", True): [],
    }
    for question in available_questions:
        knowledge = knowledge_rows.get(question.knowledge_item_id)
        if knowledge is None or question.question_type not in {"single_choice", "short_answer"}:
            continue
        buckets[(question.question_type, _is_practice_question(question, knowledge))].append(
            (question, knowledge, _direction_score(knowledge, direction_tags))
        )

    targets = {
        ("single_choice", False): 3,
        ("single_choice", True): 3,
        ("short_answer", False): 2,
        ("short_answer", True): 2,
    }
    selected: list[DiagnosticQuestion] = []
    for bucket, target in targets.items():
        selected.extend(question for question, _, _ in _take_questions(buckets[bucket], target))
    random.shuffle(selected)
    return selected


def _initial_context_snapshot(learner, *, confirmed_at: str | None = None) -> dict[str, Any]:
    direction_tags = list(learner.direction_tags_json or [])
    if not learner.education_level or not learner.major or not direction_tags:
        raise ValueError("initial_context_required")
    if learner.target_domain != "ai_app_dev":
        raise ValueError("initial_context_domain_unsupported")
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


def _diagnostic_session_message(db: Session, session_id: str) -> AgentMessageRecord | None:
    rows = db.scalars(
        select(AgentMessageRecord)
        .where(AgentMessageRecord.session_id == session_id)
        .order_by(AgentMessageRecord.id)
    )
    return next(
        (
            row
            for row in rows
            if (row.payload_summary_json or {}).get("event") == "diagnostic_session_created"
        ),
        None,
    )


def _assert_unsubmitted_session(db: Session, session_id: str) -> None:
    submitted = any(
        (row.payload_summary_json or {}).get("event") == "diagnostic_session_submitted"
        for row in db.scalars(
            select(AgentMessageRecord).where(AgentMessageRecord.session_id == session_id)
        )
    )
    if submitted:
        raise ValueError("diagnostic_session_already_submitted")

def create_diagnostic_session(
    db: Session,
    *,
    learner_id: str = "learner_001",
    domain_code: str = "ai_app_dev",
    question_count: int = 10,
) -> dict[str, Any]:
    learner = get_or_create_demo_learner(db, learner_id)
    if domain_code != "ai_app_dev":
        raise ValueError("initial_context_domain_unsupported")
    context_snapshot = _initial_context_snapshot(learner)
    profile = default_profile_for_learner(db, learner)
    if is_initial_profile_ready(profile):
        raise ValueError("initial_profile_already_ready")
    available_questions = list(
        db.scalars(
            select(DiagnosticQuestion)
            .where(DiagnosticQuestion.domain_code == domain_code)
            .order_by(DiagnosticQuestion.difficulty, DiagnosticQuestion.public_id)
        )
    )
    knowledge_rows = {
        item.id: item
        for item in db.scalars(
            select(KnowledgeItem).where(
                KnowledgeItem.id.in_({question.knowledge_item_id for question in available_questions})
            )
        )
    }
    questions = _sample_diagnostic_questions(
        available_questions, knowledge_rows, context_snapshot["direction_tags"], question_count
    )
    practice_count = sum(
        1 for question in questions if _is_practice_question(question, knowledge_rows[question.knowledge_item_id])
    )
    session_id = public_id("diag")
    selection_summary = {
        "direction_tags": context_snapshot["direction_tags"],
        "single_choice_count": 6,
        "short_answer_count": 4,
        "theory_count": len(questions) - practice_count,
        "practice_count": practice_count,
    }
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
    domain_code: str = "ai_app_dev",
    answers: list[dict[str, Any]],
) -> dict[str, Any]:
    learner = get_or_create_demo_learner(db, learner_id)
    session_message = _diagnostic_session_message(db, session_id)
    if session_message is None:
        raise ValueError("diagnostic_session_not_found")
    _assert_unsubmitted_session(db, session_id)
    session_payload = session_message.payload_summary_json or {}
    if session_payload.get("learner_id") != learner.public_id or session_payload.get("domain_code") != domain_code:
        raise ValueError("diagnostic_session_access_denied")
    context_snapshot = session_payload.get("context_snapshot")
    selected_question_ids = session_payload.get("question_ids")
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
            .where(DiagnosticQuestion.public_id.in_(question_ids))
            .where(DiagnosticQuestion.domain_code == domain_code)
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
        prompt_version="v3",
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
                    KnowledgeItem.id.in_({question.knowledge_item_id for question in questions})
                )
            )
        }
        current_profile = default_profile_for_learner(db, learner)
        current_snapshot = profile_snapshot(current_profile)
        evidence_refs: list[EvidenceRef] = []
        assessments: list[KnowledgeAssessment] = []
        correct_count = 0
        answered_count = 0
        total_score = 0.0
        category_scores: dict[str, list[float]] = defaultdict(list)

        for question in questions:
            knowledge = knowledge_rows.get(question.knowledge_item_id)
            if knowledge is None:
                raise ValueError("diagnostic_question_missing_knowledge_item")
            answer = answer_by_question_id.get(question.public_id)
            attempted = answer is not None and str(answer).strip() != ""
            score, is_correct = score_answer(question, answer) if attempted else (0.0, False)
            evidence_id = f"diag_{sha256(f'{session_id}:{question.public_id}'.encode()).hexdigest()[:32]}"
            assessment_id = f"assess_{sha256(evidence_id.encode()).hexdigest()[:32]}"
            evidence_refs.append(
                EvidenceRef(
                    evidence_id=evidence_id,
                    evidence_type=EvidenceType.DIAGNOSTIC_RESULT,
                    summary="诊断题已完成结构化评分" if attempted else "诊断题未作答",
                    knowledge_id=knowledge.public_id,
                    confidence=0.9,
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
                    confidence=0.9,
                )
            )
            db.add(
                AnswerRecord(
                    learner_id=learner.id,
                    question_id=question.id,
                    knowledge_item_id=knowledge.id,
                    score=score,
                    is_correct=is_correct,
                    answer_summary_json={
                        "session_id": session_id,
                        "question_id": question.public_id,
                        "answer_type": question.question_type,
                        "score": round(score, 2),
                        "attempted": attempted,
                    },
                )
            )
            if attempted:
                answered_count += 1
                total_score += score
                correct_count += int(is_correct)
                category_scores[knowledge.category].append(score)

        score_percent = round(total_score / len(questions) * 100, 1)
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
        analysis = ProfileAnalysisAgent().execute(
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
            "profile_type": analysis.profile.profile_type.value,
            "ability_profile": active_profile.ability_profile_json,
            "weak_knowledge": active_profile.weak_knowledge_json,
            "learning_path_id": path.public_id,
            "learning_path": path.path_json,
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
        db.commit()
        return {
            **result,
            "agent_run_id": run.id,
            "agent_name": PROFILE_AGENT_NAME,
        }
    except Exception as exc:
        run.status = "failed"
        error_code = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        run.error_message = error_code[:1000]
        run.output_summary_json = {"session_id": session_id, "error_code": error_code}
        run.duration_ms = round((time.perf_counter() - started_at) * 1000)
        _message(
            db,
            session_id=session_id,
            message_type="error",
            payload={"session_id": session_id, "status": "failed", "error_code": error_code},
        )
        db.commit()
        raise
