from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AnswerRecord,
    DiagnosticQuestion,
    Feedback,
    GenerationTask,
    KnowledgeItem,
    KnowledgeRelation,
    Learner,
    LearnerProfile,
    LearningPath,
    LearningResource,
    PathNodeAssessment,
)
from app.services.feedback_service import (
    FeedbackSourceCompatibilityError,
    create_feedback_task,
)

DEFAULT_COMPLETION_CONDITION = {"type": "scored_quiz_score", "threshold": 0.8}


def _ordered_knowledge_ids(payload: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for stage in payload.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        for value in stage.get("knowledge_ids") or []:
            knowledge_id = str(value)
            if knowledge_id and knowledge_id not in result:
                result.append(knowledge_id)
    return result


def node_id_for(knowledge_id: str) -> str:
    return f"knowledge:{knowledge_id}"


def normalize_path_payload(
    payload: dict[str, Any] | None,
    *,
    previous_payload: dict[str, Any] | None = None,
    prerequisites_by_knowledge: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    normalized = dict(payload or {})
    knowledge_ids = _ordered_knowledge_ids(normalized)
    title_by_knowledge: dict[str, str] = {}
    for stage in normalized.get("stages") or []:
        if isinstance(stage, dict):
            for value in stage.get("knowledge_ids") or []:
                title_by_knowledge.setdefault(str(value), str(stage.get("name") or value))
    prior = previous_payload or normalized
    prior_states = prior.get("node_states") if isinstance(prior, dict) else {}
    prior_states = prior_states if isinstance(prior_states, dict) else {}
    prior_by_knowledge = {
        str(state.get("knowledge_id")): state
        for state in prior_states.values()
        if isinstance(state, dict) and state.get("knowledge_id")
    }

    states: dict[str, dict[str, Any]] = {}
    for index, knowledge_id in enumerate(knowledge_ids):
        path_node_id = node_id_for(knowledge_id)
        inherited = prior_by_knowledge.get(knowledge_id, {})
        inherited_status = str(inherited.get("status") or "")
        if inherited_status == "completed":
            status = "completed"
        else:
            status = "locked"
        states[path_node_id] = {
            "path_node_id": path_node_id,
            "knowledge_id": knowledge_id,
            "title": title_by_knowledge.get(knowledge_id, knowledge_id),
            "path_order": index + 1,
            "status": status,
            "completed_at": inherited.get("completed_at") if status == "completed" else None,
            "completion_evidence_ids": (
                list(inherited.get("completion_evidence_ids") or [])
                if status == "completed"
                else []
            ),
            "completion_condition": dict(
                inherited.get("completion_condition") or DEFAULT_COMPLETION_CONDITION
            ),
        }

    completed_knowledge = {
        state["knowledge_id"] for state in states.values() if state["status"] == "completed"
    }
    preferred_current_knowledge = next(
        (
            str(state.get("knowledge_id"))
            for state in prior_states.values()
            if isinstance(state, dict) and state.get("status") == "current"
        ),
        None,
    )
    if prerequisites_by_knowledge is None:
        eligible = [state for state in states.values() if state["status"] != "completed"]
    else:
        active_knowledge_ids = set(knowledge_ids)
        eligible = []
        for state in states.values():
            if state["status"] != "completed":
                prerequisites = prerequisites_by_knowledge.get(state["knowledge_id"], set())
                in_path_prerequisites = prerequisites & active_knowledge_ids
                if in_path_prerequisites.issubset(completed_knowledge):
                    eligible.append(state)

    # The graph may expose several eligible roots, but the learner workflow is
    # deliberately a single mainline. Preserve the prior current node when it
    # remains eligible; otherwise choose the earliest path position.
    current = next(
        (
            state
            for state in eligible
            if state["knowledge_id"] == preferred_current_knowledge
        ),
        eligible[0] if eligible else None,
    )
    if current is not None:
        current["status"] = "current"

    active_knowledge = set(knowledge_ids)
    retired = dict(prior.get("retired_node_states") or {}) if isinstance(prior, dict) else {}
    for key, state in prior_states.items():
        if isinstance(state, dict) and str(state.get("knowledge_id")) not in active_knowledge:
            retired[key] = state

    current_ids = [key for key, state in states.items() if state["status"] == "current"]
    normalized["node_states"] = states
    normalized["current_node_id"] = current_ids[0] if current_ids else None
    normalized["retired_node_states"] = retired
    return normalized


def normalize_path_for_domain(
    db: Session,
    *,
    domain_code: str,
    payload: dict[str, Any] | None,
    previous_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    knowledge_ids = _ordered_knowledge_ids(payload or {})
    if not knowledge_ids:
        return normalize_path_payload(payload, previous_payload=previous_payload)
    items = list(
        db.scalars(
            select(KnowledgeItem).where(
                KnowledgeItem.domain_code == domain_code,
                KnowledgeItem.public_id.in_(knowledge_ids),
            )
        )
    )
    public_by_id = {item.id: item.public_id for item in items}
    prerequisites: dict[str, set[str]] = {knowledge_id: set() for knowledge_id in knowledge_ids}
    if public_by_id:
        relations = db.scalars(
            select(KnowledgeRelation).where(
                KnowledgeRelation.relation_type == "prerequisite",
                KnowledgeRelation.source_item_id.in_(public_by_id),
                KnowledgeRelation.target_item_id.in_(public_by_id),
            )
        )
        for relation in relations:
            prerequisites[public_by_id[relation.target_item_id]].add(
                public_by_id[relation.source_item_id]
            )
    return normalize_path_payload(
        payload,
        previous_payload=previous_payload,
        prerequisites_by_knowledge=prerequisites,
    )


def normalize_learning_path(path: LearningPath) -> dict[str, Any]:
    if isinstance((path.path_json or {}).get("node_states"), dict):
        return path.path_json
    normalized = normalize_path_payload(path.path_json or {})
    if normalized != (path.path_json or {}):
        path.path_json = normalized
    return normalized


def serialize_learning_path(path: LearningPath) -> dict[str, Any]:
    payload = normalize_learning_path(path)
    states = payload.get("node_states") or {}
    return {
        **payload,
        "path_id": path.public_id,
        "nodes": sorted(states.values(), key=lambda item: int(item.get("path_order") or 0)),
    }


def _path_and_learner(db: Session, path_id: str) -> tuple[LearningPath, Learner]:
    path = db.scalar(
        select(LearningPath).where(LearningPath.public_id == path_id).with_for_update()
    )
    learner = db.get(Learner, path.learner_id) if path else None
    if path is None or learner is None:
        raise ValueError("learning_path_not_found")
    return path, learner


def _eligible_evidence(
    db: Session,
    *,
    path: LearningPath,
    learner: Learner,
    node: dict[str, Any],
    requested_ids: list[str] | None,
) -> list[AnswerRecord]:
    knowledge = db.scalar(
        select(KnowledgeItem).where(
            KnowledgeItem.public_id == node["knowledge_id"],
            KnowledgeItem.domain_code == path.domain_code,
        )
    )
    if knowledge is None:
        return []
    records = list(
        db.scalars(
            select(AnswerRecord)
            .join(DiagnosticQuestion, DiagnosticQuestion.id == AnswerRecord.question_id)
            .where(
                AnswerRecord.learner_id == learner.id,
                AnswerRecord.knowledge_item_id == knowledge.id,
                DiagnosticQuestion.domain_code == path.domain_code,
                AnswerRecord.scoring_status == "scored",
            )
            .order_by(AnswerRecord.id.desc())
        )
    )
    allowed = set(requested_ids or [])
    result = []
    for record in records:
        evidence_id = f"answer_record:{record.id}"
        summary = record.answer_summary_json or {}
        if allowed and evidence_id not in allowed:
            continue
        if summary.get("confirmed") is not True:
            continue
        if summary.get("contract_evidence_type") != "scored_quiz":
            continue
        result.append(record)
    return result


def _verify_node_evidence(
    db: Session,
    *,
    path: LearningPath,
    learner: Learner,
    node_id: str,
    node: dict[str, Any],
    evidence_ids: list[str] | None,
) -> dict[str, Any]:
    condition = node.get("completion_condition") or DEFAULT_COMPLETION_CONDITION
    threshold = float(condition.get("threshold") or 0.8)
    records = _eligible_evidence(
        db,
        path=path,
        learner=learner,
        node=node,
        requested_ids=evidence_ids,
    )
    passing = [record for record in records if float(record.score) >= threshold]
    return {
        "path_id": path.public_id,
        "node_id": node_id,
        "verified": bool(passing),
        "reason": "threshold_met" if passing else "verified_evidence_not_found",
        "threshold": threshold,
        "best_score": max((float(record.score) for record in records), default=None),
        "evidence_ids": [f"answer_record:{record.id}" for record in passing],
        "node": node,
    }


def verify_path_node(
    db: Session,
    *,
    path_id: str,
    node_id: str,
    learner_public_id: str,
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    path, learner = _path_and_learner(db, path_id)
    if learner.public_id != learner_public_id:
        raise ValueError("learning_path_not_found")
    payload = normalize_path_for_domain(
        db,
        domain_code=path.domain_code,
        payload=path.path_json or {},
        previous_payload=path.path_json or {},
    )
    path.path_json = payload
    node = (payload.get("node_states") or {}).get(node_id)
    if not isinstance(node, dict):
        raise ValueError("learning_path_node_not_found")
    return _verify_node_evidence(
        db,
        path=path,
        learner=learner,
        node_id=node_id,
        node=node,
        evidence_ids=evidence_ids,
    )


def complete_path_node(
    db: Session,
    *,
    path_id: str,
    node_id: str,
    learner_public_id: str,
    evidence_ids: list[str],
) -> dict[str, Any]:
    path, learner = _path_and_learner(db, path_id)
    if learner.public_id != learner_public_id:
        raise ValueError("learning_path_not_found")
    payload = normalize_path_for_domain(
        db,
        domain_code=path.domain_code,
        payload=path.path_json or {},
        previous_payload=path.path_json or {},
    )
    path.path_json = payload
    states = payload.get("node_states") or {}
    node = states.get(node_id)
    if not isinstance(node, dict):
        raise ValueError("learning_path_node_not_found")
    if node.get("status") == "completed":
        return {"path": serialize_learning_path(path), "completed_node_id": node_id}
    if node.get("status") != "current":
        raise ValueError("learning_path_node_locked")
    verification = _verify_node_evidence(
        db,
        path=path,
        learner=learner,
        node_id=node_id,
        node=node,
        evidence_ids=evidence_ids,
    )
    if not verification["verified"]:
        raise ValueError("learning_path_evidence_not_verified")

    _advance_path_node(
        db,
        path=path,
        node_id=node_id,
        evidence_ids=verification["evidence_ids"],
    )
    db.commit()
    return {"path": serialize_learning_path(path), "completed_node_id": node_id}


def _advance_path_node(
    db: Session,
    *,
    path: LearningPath,
    node_id: str,
    evidence_ids: list[str],
) -> None:
    payload = path.path_json or {}
    node = (payload.get("node_states") or {}).get(node_id)
    if not isinstance(node, dict) or node.get("status") != "current":
        raise ValueError("learning_path_node_locked")
    node["status"] = "completed"
    node["completed_at"] = datetime.now(UTC).isoformat()
    node["completion_evidence_ids"] = list(dict.fromkeys(evidence_ids))
    payload = normalize_path_for_domain(
        db,
        domain_code=path.domain_code,
        payload=payload,
        previous_payload=payload,
    )
    states = payload.get("node_states") or {}
    path.status = (
        "completed"
        if states and all(state.get("status") == "completed" for state in states.values())
        else "active"
    )
    path.path_json = payload


def _serialize_assessment(
    assessment: PathNodeAssessment,
    question: DiagnosticQuestion,
) -> dict[str, Any]:
    return {
        "assessment_id": assessment.public_id,
        "path_id": None,
        "node_id": assessment.path_node_id,
        "question_id": question.public_id,
        "question_type": question.question_type,
        "difficulty": question.difficulty,
        "stem": question.stem,
        "options": question.options_json or [],
        "status": assessment.status,
        "score": assessment.score,
        "passed": assessment.passed,
    }


def start_path_node_assessment(
    db: Session,
    *,
    path_id: str,
    node_id: str,
    learner_public_id: str,
) -> dict[str, Any]:
    path, learner = _path_and_learner(db, path_id)
    if learner.public_id != learner_public_id:
        raise ValueError("learning_path_not_found")
    payload = normalize_path_for_domain(
        db,
        domain_code=path.domain_code,
        payload=path.path_json or {},
        previous_payload=path.path_json or {},
    )
    path.path_json = payload
    node = (payload.get("node_states") or {}).get(node_id)
    if not isinstance(node, dict):
        raise ValueError("learning_path_node_not_found")
    if node.get("status") != "current" or payload.get("current_node_id") != node_id:
        raise ValueError("learning_path_node_locked")

    existing = db.scalar(
        select(PathNodeAssessment)
        .where(
            PathNodeAssessment.learning_path_id == path.id,
            PathNodeAssessment.path_node_id == node_id,
            PathNodeAssessment.learner_id == learner.id,
            PathNodeAssessment.status == "pending",
        )
        .order_by(PathNodeAssessment.id.desc())
    )
    if existing is not None:
        question = db.get(DiagnosticQuestion, existing.question_id)
        if question is not None:
            result = _serialize_assessment(existing, question)
            result["path_id"] = path.public_id
            return result

    knowledge = db.scalar(
        select(KnowledgeItem).where(
            KnowledgeItem.public_id == node.get("knowledge_id"),
            KnowledgeItem.domain_code == path.domain_code,
        )
    )
    if knowledge is None:
        raise ValueError("learning_path_assessment_unavailable")
    questions = list(
        db.scalars(
            select(DiagnosticQuestion)
            .where(
                DiagnosticQuestion.knowledge_item_id == knowledge.id,
                DiagnosticQuestion.domain_code == path.domain_code,
                DiagnosticQuestion.question_type == "single_choice",
            )
            .order_by(DiagnosticQuestion.difficulty, DiagnosticQuestion.id)
        )
    )
    if not questions:
        raise ValueError("learning_path_assessment_unavailable")
    attempted = set(
        db.scalars(
            select(PathNodeAssessment.question_id).where(
                PathNodeAssessment.learning_path_id == path.id,
                PathNodeAssessment.path_node_id == node_id,
                PathNodeAssessment.learner_id == learner.id,
            )
        )
    )
    question = next((item for item in questions if item.id not in attempted), questions[0])
    assessment = PathNodeAssessment(
        public_id=f"pathval_{uuid4().hex[:12]}",
        learning_path_id=path.id,
        path_node_id=node_id,
        learner_id=learner.id,
        question_id=question.id,
        status="pending",
        result_json={},
    )
    db.add(assessment)
    db.commit()
    result = _serialize_assessment(assessment, question)
    result["path_id"] = path.public_id
    return result


def _current_node_resource(
    db: Session, *, path: LearningPath, node_id: str
) -> LearningResource | None:
    return db.scalar(
        select(LearningResource)
        .join(GenerationTask, GenerationTask.id == LearningResource.generation_task_id)
        .where(
            GenerationTask.learning_path_id == path.id,
            GenerationTask.path_node_id == node_id,
            GenerationTask.status == "completed",
            LearningResource.is_current.is_(True),
            LearningResource.review_status == "passed",
        )
        .order_by(LearningResource.id.desc())
    )


def _maybe_create_remedial_task(
    db: Session,
    *,
    path: LearningPath,
    learner: Learner,
    node_id: str,
) -> GenerationTask | None:
    assessments = list(
        db.scalars(
            select(PathNodeAssessment)
            .where(
                PathNodeAssessment.learning_path_id == path.id,
                PathNodeAssessment.path_node_id == node_id,
                PathNodeAssessment.learner_id == learner.id,
                PathNodeAssessment.status == "scored",
                PathNodeAssessment.passed.is_(False),
            )
            .order_by(PathNodeAssessment.id.desc())
            .limit(2)
        )
    )
    if len(assessments) < 2:
        return None
    resource = _current_node_resource(db, path=path, node_id=node_id)
    profile = db.get(LearnerProfile, path.profile_id) if path.profile_id else None
    if resource is None or profile is None:
        return None
    evidence = []
    for item in assessments:
        if item.answer_record_id is None:
            continue
        question = db.get(DiagnosticQuestion, item.question_id)
        knowledge = db.get(KnowledgeItem, question.knowledge_item_id) if question else None
        evidence.append(
            {
                "evidence_id": f"answer_record:{item.answer_record_id}",
                "evidence_type": "scored_quiz",
                "knowledge_id": knowledge.public_id if knowledge else None,
                "source_ref_id": question.public_id if question else None,
                "confidence": 0.9,
                "confirmed": True,
            }
        )
    feedback = Feedback(
        resource_id=resource.id,
        learner_id=learner.id,
        feedback_type="path_node_assessment",
        feedback_summary_json={"node_id": node_id, "assessment_count": len(evidence)},
        triggered_action="explain",
        comment="节点验证未达到通过阈值",
        feedback_intent="too_hard",
        recommended_action="explain",
        profile_update_required=False,
        profile_change_evidence_json=evidence,
        decision_confidence=0.9,
        decision_reason="连续两次节点验证未通过，进入统一画像分析与补救资源流程",
    )
    db.add(feedback)
    db.flush()
    try:
        task = create_feedback_task(
            db,
            learner=learner,
            profile=profile,
            resource=resource,
            feedback=feedback,
            resource_types=["lecture", "practice_guide", "graded_quiz"],
        )
    except FeedbackSourceCompatibilityError:
        return None
    task.learning_path_id = path.id
    task.path_node_id = node_id
    return task


def answer_path_node_assessment(
    db: Session,
    *,
    path_id: str,
    node_id: str,
    assessment_id: str,
    learner_public_id: str,
    answer: Any,
) -> tuple[dict[str, Any], GenerationTask | None]:
    path, learner = _path_and_learner(db, path_id)
    if learner.public_id != learner_public_id:
        raise ValueError("learning_path_not_found")
    assessment = db.scalar(
        select(PathNodeAssessment)
        .where(PathNodeAssessment.public_id == assessment_id)
        .with_for_update()
    )
    if (
        assessment is None
        or assessment.learning_path_id != path.id
        or assessment.path_node_id != node_id
        or assessment.learner_id != learner.id
    ):
        raise ValueError("learning_path_assessment_not_found")
    if assessment.status == "scored":
        return dict(assessment.result_json or {}), None

    payload = normalize_path_for_domain(
        db,
        domain_code=path.domain_code,
        payload=path.path_json or {},
        previous_payload=path.path_json or {},
    )
    path.path_json = payload
    node = (payload.get("node_states") or {}).get(node_id)
    if not isinstance(node, dict) or node.get("status") != "current":
        raise ValueError("path_node_changed")
    question = db.get(DiagnosticQuestion, assessment.question_id)
    if question is None:
        raise ValueError("learning_path_assessment_unavailable")
    try:
        selected = int(answer)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_single_choice_answer") from exc
    if selected < 0 or selected >= len(question.options_json or []):
        raise ValueError("invalid_single_choice_answer")
    correct = int((question.answer_key_json or {}).get("correct_option", -1))
    score = 1.0 if selected == correct else 0.0
    threshold = float((node.get("completion_condition") or {}).get("threshold") or 0.8)
    passed = score >= threshold
    record = AnswerRecord(
        learner_id=learner.id,
        question_id=question.id,
        knowledge_item_id=question.knowledge_item_id,
        session_id=assessment.public_id,
        answer_text=str(selected),
        score=score,
        is_correct=passed,
        scoring_status="scored",
        scoring_method="deterministic",
        confidence=0.9,
        answer_summary_json={
            "assessment_id": assessment.public_id,
            "evidence_type": "path_node_validation",
            "contract_evidence_type": "scored_quiz",
            "path_id": path.public_id,
            "path_node_id": node_id,
            "confirmed": True,
            "confidence": 0.9,
            "consumed_by_profile_id": None,
        },
    )
    db.add(record)
    db.flush()
    evidence_id = f"answer_record:{record.id}"
    if passed:
        _advance_path_node(db, path=path, node_id=node_id, evidence_ids=[evidence_id])
    current_node_id = (path.path_json or {}).get("current_node_id")
    result = {
        "assessment_id": assessment.public_id,
        "path_id": path.public_id,
        "node_id": node_id,
        "score": score,
        "threshold": threshold,
        "passed": passed,
        "evidence_id": evidence_id,
        "completed_node_id": node_id if passed else None,
        "current_node_id": current_node_id,
        "path_completed": path.status == "completed",
        "profile_adjustment_task_id": None,
    }
    assessment.answer_record_id = record.id
    assessment.status = "scored"
    assessment.score = score
    assessment.passed = passed
    assessment.result_json = result
    task = None if passed else _maybe_create_remedial_task(
        db, path=path, learner=learner, node_id=node_id
    )
    if task is not None:
        result["profile_adjustment_task_id"] = task.public_id
        assessment.result_json = result
    db.commit()
    return result, task
