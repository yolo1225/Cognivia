from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnswerRecord, DiagnosticQuestion, KnowledgeItem, Learner, LearningPath

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
    completed_prefix = True
    for index, knowledge_id in enumerate(knowledge_ids):
        path_node_id = node_id_for(knowledge_id)
        inherited = prior_by_knowledge.get(knowledge_id, {})
        inherited_status = str(inherited.get("status") or "")
        if inherited_status == "completed":
            status = "completed"
        elif completed_prefix:
            status = "current"
            completed_prefix = False
        else:
            status = "locked"
        if status != "completed":
            completed_prefix = False
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


def normalize_learning_path(path: LearningPath) -> dict[str, Any]:
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
    payload = normalize_learning_path(path)
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
    payload = normalize_learning_path(path)
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

    node["status"] = "completed"
    node["completed_at"] = datetime.now(UTC).isoformat()
    node["completion_evidence_ids"] = verification["evidence_ids"]
    ordered = sorted(states.values(), key=lambda item: int(item.get("path_order") or 0))
    next_node = next((item for item in ordered if item.get("status") == "locked"), None)
    if next_node:
        next_node["status"] = "current"
        payload["current_node_id"] = next_node["path_node_id"]
    else:
        payload["current_node_id"] = None
        path.status = "completed"
    path.path_json = payload
    db.commit()
    return {"path": serialize_learning_path(path), "completed_node_id": node_id}
