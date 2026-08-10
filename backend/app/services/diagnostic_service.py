from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
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
from app.agents.v2_profile_analysis_agent import V2ProfileAnalysisAgent
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
    latest_path_for_profile,
    public_id,
    score_answer,
)
from app.services.v2_contract_mapping import ability_profile_payload, profile_snapshot

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


def create_diagnostic_session(
    db: Session,
    *,
    learner_id: str = "learner_001",
    domain_code: str = "ai_app_dev",
    question_count: int = 10,
) -> dict[str, Any]:
    learner = get_or_create_demo_learner(db, learner_id)
    questions = list(
        db.scalars(
            select(DiagnosticQuestion)
            .where(DiagnosticQuestion.domain_code == domain_code)
            .order_by(DiagnosticQuestion.difficulty, DiagnosticQuestion.public_id)
            .limit(question_count)
        )
    )
    return {
        "session_id": public_id("diag"),
        "learner_id": learner.public_id,
        "domain_code": domain_code,
        "question_count": len(questions),
        "status": "created",
        "questions": [_question_payload(question) for question in questions],
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
    answer_by_question_id = {item["question_id"]: item.get("answer") for item in answers}
    question_ids = list(answer_by_question_id.keys())
    questions = list(
        db.scalars(
            select(DiagnosticQuestion)
            .where(DiagnosticQuestion.public_id.in_(question_ids))
            .where(DiagnosticQuestion.domain_code == domain_code)
        )
    )
    if not questions:
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
        prompt_version="v2",
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
        analysis = V2ProfileAnalysisAgent().execute(
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
