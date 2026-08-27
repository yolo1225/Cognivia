from __future__ import annotations

import hashlib
import math
from copy import deepcopy
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
    LearningPath,
    LearningResource,
    LearnerProfile,
    PathNodeAssessment,
)
from app.services.knowledge_extraction_service import normalize_knowledge_name
from app.services.feedback_service import FeedbackSourceCompatibilityError, create_feedback_task
from app.services.mistake_review_service import sync_existing_mistakes
from app.services.question_certification_service import (
    QUESTION_CERTIFICATION_RULE_VERSION,
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


def unit_node_id_for(knowledge_ids: list[str]) -> str:
    digest = hashlib.sha256("|".join(knowledge_ids).encode()).hexdigest()[:16]
    return f"unit:{digest}"


def _balanced_units(knowledge_ids: list[str]) -> list[list[str]]:
    """Partition a topological sequence into stable 2-5 item learning units."""
    if not knowledge_ids:
        return []
    target_count = min(7, max(4, math.ceil(len(knowledge_ids) / 3)))
    target_count = min(target_count, len(knowledge_ids))
    base, remainder = divmod(len(knowledge_ids), target_count)
    sizes = [base + (1 if index < remainder else 0) for index in range(target_count)]
    units: list[list[str]] = []
    cursor = 0
    for size in sizes:
        units.append(knowledge_ids[cursor:cursor + min(6, size)])
        cursor += size
    if cursor < len(knowledge_ids):
        units[-1].extend(knowledge_ids[cursor:])
    return units


def _state_order(states: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        (state for state in states.values() if isinstance(state, dict)),
        key=lambda state: int(state.get("path_order") or 0),
    )


def _stable_topological_order(
    knowledge_ids: list[str],
    *,
    prerequisites_by_knowledge: dict[str, set[str]],
) -> list[str]:
    pending = list(dict.fromkeys(knowledge_ids))
    ordered: list[str] = []
    while pending:
        pending_set = set(pending)
        candidate = next(
            (
                knowledge_id
                for knowledge_id in pending
                if not (
                    prerequisites_by_knowledge.get(knowledge_id, set())
                    & pending_set
                )
            ),
            None,
        )
        if candidate is None:
            # Domain readiness rejects prerequisite cycles. Preserve the prior
            # relative order as a defensive fallback for legacy data.
            ordered.extend(pending)
            break
        ordered.append(candidate)
        pending.remove(candidate)
    return ordered


def _prerequisite_closure(
    knowledge_id: str,
    *,
    prerequisites_by_knowledge: dict[str, set[str]],
    completed: set[str],
) -> list[str]:
    closure: set[str] = set()

    def visit(target_id: str) -> None:
        for prerequisite_id in sorted(prerequisites_by_knowledge.get(target_id, set())):
            if prerequisite_id in completed or prerequisite_id in closure:
                continue
            closure.add(prerequisite_id)
            visit(prerequisite_id)

    visit(knowledge_id)
    return _stable_topological_order(
        list(closure),
        prerequisites_by_knowledge=prerequisites_by_knowledge,
    )


def _set_primary_stage_knowledge_ids(
    normalized: dict[str, Any], knowledge_ids: list[str]
) -> None:
    stages = [dict(stage) for stage in normalized.get("stages") or [] if isinstance(stage, dict)]
    target = next((stage for stage in stages if "knowledge_ids" in stage), None)
    if target is None:
        target = {
            "name": "学习主线",
            "description": "根据当前画像与学习证据持续修订。",
        }
        stages.insert(0, target)
    target["knowledge_ids"] = knowledge_ids
    normalized["stages"] = stages


def normalize_path_payload(
    payload: dict[str, Any] | None,
    *,
    previous_payload: dict[str, Any] | None = None,
    prerequisites_by_knowledge: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    normalized = dict(payload or {})
    recommended_ids = _ordered_knowledge_ids(normalized)
    title_by_knowledge: dict[str, str] = {}
    for stage in normalized.get("stages") or []:
        if isinstance(stage, dict):
            for value in stage.get("knowledge_ids") or []:
                title_by_knowledge.setdefault(str(value), str(stage.get("name") or value))
    prior = previous_payload or normalized
    prior_states = prior.get("node_states") if isinstance(prior, dict) else {}
    prior_states = prior_states if isinstance(prior_states, dict) else {}
    if not recommended_ids and not prior_states:
        normalized["node_states"] = {}
        normalized["current_node_id"] = None
        normalized["retired_node_states"] = dict(normalized.get("retired_node_states") or {})
        return normalized
    prior_ordered = _state_order(prior_states)
    prior_by_knowledge = {
        str(state.get("knowledge_id")): state
        for state in prior_ordered
        if isinstance(state, dict) and state.get("knowledge_id")
    }

    completed_ids = [
        str(state["knowledge_id"])
        for state in prior_ordered
        if state.get("status") == "completed" and state.get("knowledge_id")
    ]
    completed = set(completed_ids)
    preferred_current_knowledge = next(
        (
            str(state.get("knowledge_id"))
            for state in prior_ordered
            if state.get("status") == "current" and state.get("knowledge_id")
        ),
        None,
    )
    previous_future_ids = [
        str(state["knowledge_id"])
        for state in prior_ordered
        if state.get("status") not in {"completed", "current"}
        and state.get("knowledge_id") in recommended_ids
    ]
    new_future_ids = [
        knowledge_id
        for knowledge_id in recommended_ids
        if knowledge_id not in completed
        and knowledge_id != preferred_current_knowledge
        and knowledge_id not in previous_future_ids
    ]

    prerequisites = prerequisites_by_knowledge or {}
    inserted_prerequisites: list[str] = []
    if preferred_current_knowledge:
        inserted_prerequisites = _prerequisite_closure(
            preferred_current_knowledge,
            prerequisites_by_knowledge=prerequisites,
            completed=completed,
        )
    future_seed = [
        knowledge_id
        for knowledge_id in [*previous_future_ids, *new_future_ids]
        if knowledge_id not in inserted_prerequisites
    ]
    prefix_after_completed = [
        *inserted_prerequisites,
        *([preferred_current_knowledge] if preferred_current_knowledge else []),
    ]
    ordered_future = _stable_topological_order(
        future_seed,
        prerequisites_by_knowledge=prerequisites,
    )
    knowledge_ids = list(
        dict.fromkeys([*completed_ids, *prefix_after_completed, *ordered_future])
    )
    if not prior_states:
        knowledge_ids = _stable_topological_order(
            recommended_ids,
            prerequisites_by_knowledge=prerequisites,
        )
    _set_primary_stage_knowledge_ids(normalized, knowledge_ids)
    primary_stage = next(
        (
            stage
            for stage in normalized.get("stages") or []
            if isinstance(stage, dict) and "knowledge_ids" in stage
        ),
        {},
    )
    primary_title = str(primary_stage.get("name") or "学习主线")
    for knowledge_id in knowledge_ids:
        inherited = prior_by_knowledge.get(knowledge_id, {})
        title_by_knowledge.setdefault(
            knowledge_id, str(inherited.get("title") or primary_title)
        )

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

    current = next(
        (state for state in states.values() if state["status"] != "completed"),
        None,
    )
    if current is not None:
        current["status"] = "current"

    if inserted_prerequisites and current is not None:
        normalized["revision_summary"] = {
            "type": "prerequisite_inserted",
            "message": "发现新的必要前置知识，路线已调整",
            "inserted_knowledge_ids": inserted_prerequisites,
            "previous_current_node_id": node_id_for(preferred_current_knowledge),
            "current_node_id": current["path_node_id"],
        }
    elif (normalized.get("revision_summary") or {}).get("type") == "prerequisite_inserted":
        normalized.pop("revision_summary", None)

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
    recommended_ids = _ordered_knowledge_ids(payload or {})
    previous_states = (previous_payload or {}).get("node_states") or {}
    prior_ids = list(dict.fromkeys(
        str(knowledge_id)
        for state in previous_states.values()
        if isinstance(state, dict)
        for knowledge_id in (
            state.get("knowledge_ids") or [state.get("knowledge_id")]
        )
        if knowledge_id
    ))
    if not recommended_ids and not prior_ids:
        return normalize_path_payload(payload, previous_payload=previous_payload)
    items = list(
        db.scalars(
            select(KnowledgeItem).where(
                KnowledgeItem.domain_code == domain_code,
            )
        )
    )
    public_by_id = {item.id: item.public_id for item in items}
    prerequisites: dict[str, set[str]] = {
        knowledge_id: set() for knowledge_id in public_by_id.values()
    }
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
    prior_retired = (previous_payload or {}).get("retired_node_states") or {}
    prior_all_states = [
        *[state for state in previous_states.values() if isinstance(state, dict)],
        *[state for state in prior_retired.values() if isinstance(state, dict)],
    ]
    completed_states_by_node: dict[str, dict[str, Any]] = {}
    for state in sorted(
        prior_all_states,
        key=lambda item: (
            str(item.get("completed_at") or ""),
            int(item.get("path_order") or 0),
        ),
    ):
        if state.get("status") != "completed" or not state.get("path_node_id"):
            continue
        completed_states_by_node.setdefault(str(state["path_node_id"]), state)
    completed_states = list(completed_states_by_node.values())
    completed_ids = list(dict.fromkeys(
        str(knowledge_id)
        for state in completed_states
        for knowledge_id in (state.get("knowledge_ids") or [state.get("knowledge_id")])
        if knowledge_id
    ))
    prior_current = next(
        (
            state
            for state in _state_order(previous_states)
            if state.get("status") == "current"
        ),
        None,
    )
    prior_current_ids = [
        str(value)
        for value in (prior_current or {}).get("knowledge_ids")
        or [(prior_current or {}).get("knowledge_id")]
        if value
    ]
    expanded_ids = list(completed_ids)
    for knowledge_id in [*recommended_ids, *prior_current_ids]:
        expanded_ids.extend(
            _prerequisite_closure(
                knowledge_id,
                prerequisites_by_knowledge=prerequisites,
                completed=set(completed_ids),
            )
        )
        expanded_ids.append(knowledge_id)
    expanded_ids = _stable_topological_order(
        list(dict.fromkeys(expanded_ids)),
        prerequisites_by_knowledge=prerequisites,
    )
    normalized_input = deepcopy(payload or {})
    _set_primary_stage_knowledge_ids(normalized_input, expanded_ids)
    normalized = normalize_path_payload(
        normalized_input,
        prerequisites_by_knowledge=prerequisites,
    )
    names_by_public_id = {item.public_id: normalize_knowledge_name(item.name) for item in items}
    categories_by_public_id = {item.public_id: item.category for item in items}
    weak_ids = {
        str(value)
        for stage in normalized.get("stages") or []
        if isinstance(stage, dict) and "薄弱" in str(stage.get("name") or "")
        for value in stage.get("knowledge_ids") or []
    }
    completed_knowledge = set(completed_ids)
    current_prerequisites = {
        prerequisite
        for knowledge_id in prior_current_ids
        for prerequisite in prerequisites.get(knowledge_id, set())
        if prerequisite not in completed_knowledge and prerequisite not in prior_current_ids
    }
    keep_prior_current = bool(
        prior_current
        and prior_current_ids
        and not current_prerequisites
        and all(knowledge_id in expanded_ids for knowledge_id in prior_current_ids)
        and not (set(prior_current_ids) & completed_knowledge)
    )
    remaining_ids = [
        knowledge_id for knowledge_id in expanded_ids if knowledge_id not in completed_knowledge
    ]
    future_units: list[list[str]] = []
    if keep_prior_current:
        future_units.append(prior_current_ids)
        remaining_ids = [
            knowledge_id
            for knowledge_id in remaining_ids
            if knowledge_id not in set(prior_current_ids)
        ]
    future_units.extend(_balanced_units(remaining_ids))

    unit_states: dict[str, dict[str, Any]] = {}
    for index, state in enumerate(completed_states, start=1):
        preserved = deepcopy(state)
        preserved["path_order"] = index
        preserved["status"] = "completed"
        preserved["completed_at"] = preserved.get("completed_at")
        preserved["completion_evidence_ids"] = list(
            preserved.get("completion_evidence_ids") or []
        )
        unit_states[str(preserved["path_node_id"])] = preserved

    for offset, member_ids in enumerate(future_units, start=len(unit_states) + 1):
        node_id = unit_node_id_for(member_ids)
        focus_ids = [value for value in member_ids if value in weak_ids][:3]
        categories = list(dict.fromkeys(
            categories_by_public_id.get(value, "") for value in member_ids
            if categories_by_public_id.get(value)
        ))
        member_names = [names_by_public_id.get(value, value) for value in member_ids]
        title = categories[0] if len(categories) == 1 else "与".join(member_names[:2])
        prerequisite_ids = sorted({
            prerequisite
            for value in member_ids
            for prerequisite in prerequisites.get(value, set())
            if prerequisite not in member_ids
        })
        inherited_current = (
            prior_current
            if keep_prior_current
            and tuple(member_ids) == tuple(prior_current_ids)
            else {}
        )
        unit_states[node_id] = {
            "path_node_id": node_id,
            "knowledge_ids": member_ids,
            "knowledge_items": [
                {
                    "knowledge_id": value,
                    "name": names_by_public_id.get(value, value),
                    "category": categories_by_public_id.get(value, ""),
                }
                for value in member_ids
            ],
            "focus_knowledge_ids": focus_ids,
            "title": title,
            "path_order": offset,
            "status": "locked",
            "completed_at": None,
            "completion_evidence_ids": [],
            "completion_condition": dict(inherited_current.get("completion_condition") or {
                "type": "unit_quiz_score",
                "threshold": 0.8,
                "focus_threshold": 0.6,
                "question_count_min": 3,
                "question_count_max": 5,
            }),
            "learning_objective": f"综合掌握{'、'.join(member_names)}",
            "recommendation_reason": (
                "包含当前诊断出的重点薄弱知识，并按前置关系组织学习。"
                if focus_ids else "根据知识前置关系与学习目标组合为连续学习单元。"
            ),
            "prerequisite_knowledge_ids": prerequisite_ids,
        }
    current = next((state for state in unit_states.values() if state["status"] != "completed"), None)
    if current is not None:
        current["status"] = "current"
    normalized["node_states"] = unit_states
    normalized["current_node_id"] = current["path_node_id"] if current else None
    normalized["path_version"] = "dynamic-units-v1"
    inserted_prerequisites = [
        value
        for value in expanded_ids
        if value not in completed_ids
        and value not in recommended_ids
        and value not in prior_current_ids
    ]
    if inserted_prerequisites:
        normalized["revision_summary"] = {
            "type": "prerequisite_inserted",
            "message": "发现新的必要前置知识，路线已局部调整",
            "inserted_knowledge_ids": inserted_prerequisites,
            "current_node_id": normalized["current_node_id"],
        }
    else:
        normalized.pop("revision_summary", None)
    retired = {
        key: value
        for key, value in prior_retired.items()
        if key not in unit_states
        and isinstance(value, dict)
        and value.get("status") != "completed"
    }
    for key, value in previous_states.items():
        if key not in unit_states and isinstance(value, dict) and value.get("status") != "completed":
            retired[key] = value
    normalized["retired_node_states"] = retired
    return normalized


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
    knowledge_ids = [str(value) for value in node.get("knowledge_ids") or []]
    knowledge_rows = list(db.scalars(
        select(KnowledgeItem).where(
            KnowledgeItem.public_id.in_(knowledge_ids),
            KnowledgeItem.domain_code == path.domain_code,
        )
    ))
    if not knowledge_rows:
        return []
    records = list(
        db.scalars(
            select(AnswerRecord)
            .join(DiagnosticQuestion, DiagnosticQuestion.id == AnswerRecord.question_id)
            .where(
                AnswerRecord.learner_id == learner.id,
                AnswerRecord.knowledge_item_id.in_([item.id for item in knowledge_rows]),
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
    records = records[: int(condition.get("question_count_max") or 5)]
    focus_threshold = float(condition.get("focus_threshold") or 0.6)
    minimum_count = int(condition.get("question_count_min") or 3)
    average_score = (
        sum(float(record.score) for record in records) / len(records) if records else 0.0
    )
    focus_ids = set(node.get("focus_knowledge_ids") or [])
    questions_by_id = {
        item.id: item
        for item in db.scalars(
            select(DiagnosticQuestion).where(
                DiagnosticQuestion.id.in_([record.question_id for record in records])
            )
        )
    }
    primary_ids_by_item_id = {
        item.id: item.public_id
        for item in db.scalars(
            select(KnowledgeItem).where(
                KnowledgeItem.domain_code == path.domain_code,
                KnowledgeItem.id.in_([record.knowledge_item_id for record in records]),
            )
        )
    }
    unit_ids = set(str(value) for value in node.get("knowledge_ids") or [])
    focus_scores = {
        public_id: [
            float(record.score)
            for record in records
            if (
                question := questions_by_id.get(record.question_id)
            ) is not None
            and public_id
            in _question_unit_coverage(
                question,
                primary_knowledge_id=primary_ids_by_item_id.get(
                    record.knowledge_item_id
                ),
                unit_knowledge_ids=unit_ids,
            )
        ]
        for public_id in focus_ids
    }
    focus_passed = all(
        scores and sum(scores) / len(scores) >= focus_threshold
        for scores in focus_scores.values()
    )
    verified = len(records) >= minimum_count and average_score >= threshold and focus_passed
    return {
        "path_id": path.public_id,
        "node_id": node_id,
        "verified": verified,
        "reason": "threshold_met" if verified else "unit_threshold_not_met",
        "threshold": threshold,
        "focus_threshold": focus_threshold,
        "question_count": len(records),
        "average_score": average_score,
        "focus_scores": {
            key: sum(values) / len(values) if values else None
            for key, values in focus_scores.items()
        },
        "best_score": max((float(record.score) for record in records), default=None),
        "evidence_ids": [f"answer_record:{record.id}" for record in records] if verified else [],
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

    _advance_path_node(db, path=path, node_id=node_id, evidence_ids=verification["evidence_ids"])
    db.commit()
    return {"path": serialize_learning_path(path), "completed_node_id": node_id}


def _advance_path_node(
    db: Session, *, path: LearningPath, node_id: str, evidence_ids: list[str]
) -> None:
    payload = path.path_json or {}
    node = (payload.get("node_states") or {}).get(node_id)
    if not isinstance(node, dict) or node.get("status") != "current":
        raise ValueError("learning_path_node_locked")
    node["status"] = "completed"
    node["completed_at"] = datetime.now(UTC).isoformat()
    node["completion_evidence_ids"] = list(dict.fromkeys(evidence_ids))
    payload = normalize_path_for_domain(
        db, domain_code=path.domain_code, payload=payload, previous_payload=payload
    )
    states = payload.get("node_states") or {}
    path.status = "completed" if states and all(
        state.get("status") == "completed" for state in states.values()
    ) else "active"
    path.path_json = payload


def _serialize_assessment(assessment: PathNodeAssessment, question: DiagnosticQuestion) -> dict[str, Any]:
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


def _question_unit_coverage(
    question: DiagnosticQuestion,
    *,
    primary_knowledge_id: str | None,
    unit_knowledge_ids: set[str],
) -> set[str]:
    declared = {
        str(value) for value in (question.related_knowledge_ids_json or []) if value
    }
    if primary_knowledge_id:
        declared.add(primary_knowledge_id)
    return declared & unit_knowledge_ids


def start_path_node_assessment(
    db: Session, *, path_id: str, node_id: str, learner_public_id: str
) -> dict[str, Any]:
    path, learner = _path_and_learner(db, path_id)
    if learner.public_id != learner_public_id:
        raise ValueError("learning_path_not_found")
    payload = normalize_path_for_domain(
        db, domain_code=path.domain_code, payload=path.path_json or {}, previous_payload=path.path_json or {}
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
    knowledge_ids = [str(value) for value in node.get("knowledge_ids") or []]
    knowledge_rows = list(db.scalars(
        select(KnowledgeItem).where(
            KnowledgeItem.public_id.in_(knowledge_ids),
            KnowledgeItem.domain_code == path.domain_code,
        )
    ))
    if not knowledge_rows:
        raise ValueError("learning_path_assessment_unavailable")
    questions = list(db.scalars(
        select(DiagnosticQuestion)
        .join(KnowledgeItem, KnowledgeItem.id == DiagnosticQuestion.knowledge_item_id)
        .where(
            DiagnosticQuestion.domain_code == path.domain_code,
            KnowledgeItem.domain_code == path.domain_code,
            DiagnosticQuestion.question_type == "single_choice",
            DiagnosticQuestion.status == "active",
            DiagnosticQuestion.certification_status == "certified",
            DiagnosticQuestion.certification_rule_version
            == QUESTION_CERTIFICATION_RULE_VERSION,
        )
        .order_by(DiagnosticQuestion.difficulty, DiagnosticQuestion.id)
    ))
    if not questions:
        raise ValueError("learning_path_assessment_unavailable")
    attempted = set(db.scalars(select(PathNodeAssessment.question_id).where(
        PathNodeAssessment.learning_path_id == path.id,
        PathNodeAssessment.path_node_id == node_id,
        PathNodeAssessment.learner_id == learner.id,
    )))
    public_id_by_item_id = {item.id: item.public_id for item in knowledge_rows}
    unit_ids = set(knowledge_ids)
    eligible = [
        item
        for item in questions
        if _question_unit_coverage(
            item,
            primary_knowledge_id=public_id_by_item_id.get(item.knowledge_item_id),
            unit_knowledge_ids=unit_ids,
        )
    ]
    attempted_questions = [item for item in eligible if item.id in attempted]
    covered_before = {
        knowledge_id
        for item in attempted_questions
        for knowledge_id in _question_unit_coverage(
            item,
            primary_knowledge_id=public_id_by_item_id.get(item.knowledge_item_id),
            unit_knowledge_ids=unit_ids,
        )
    }
    focus_ids = set(node.get("focus_knowledge_ids") or []) & unit_ids
    unattempted = [item for item in eligible if item.id not in attempted]
    unattempted.sort(
        key=lambda item: (
            not bool(
                _question_unit_coverage(
                    item,
                    primary_knowledge_id=public_id_by_item_id.get(item.knowledge_item_id),
                    unit_knowledge_ids=unit_ids,
                )
                & (focus_ids - covered_before)
            ),
            not bool(
                _question_unit_coverage(
                    item,
                    primary_knowledge_id=public_id_by_item_id.get(item.knowledge_item_id),
                    unit_knowledge_ids=unit_ids,
                )
                - covered_before
            ),
            item.difficulty,
            item.id,
        )
    )
    question = unattempted[0] if unattempted else None
    if question is None:
        raise ValueError("learning_path_assessment_unavailable")
    assessment = PathNodeAssessment(
        public_id=f"pathval_{uuid4().hex[:12]}", learning_path_id=path.id,
        path_node_id=node_id, learner_id=learner.id, question_id=question.id,
        status="pending", result_json={},
    )
    db.add(assessment)
    db.commit()
    result = _serialize_assessment(assessment, question)
    result["path_id"] = path.public_id
    return result


def _current_node_resource(db: Session, *, path: LearningPath, node_id: str) -> LearningResource | None:
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
    db: Session, *, path: LearningPath, learner: Learner, node_id: str
) -> GenerationTask | None:
    assessments = list(db.scalars(
        select(PathNodeAssessment)
        .where(
            PathNodeAssessment.learning_path_id == path.id,
            PathNodeAssessment.path_node_id == node_id,
            PathNodeAssessment.learner_id == learner.id,
            PathNodeAssessment.status == "scored",
            PathNodeAssessment.passed.is_(False),
        )
        .order_by(PathNodeAssessment.id.desc()).limit(2)
    ))
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
        evidence.append({
            "evidence_id": f"answer_record:{item.answer_record_id}",
            "evidence_type": "scored_quiz",
            "knowledge_id": knowledge.public_id if knowledge else None,
            "source_ref_id": question.public_id if question else None,
            "confidence": 0.9,
            "confirmed": True,
        })
    feedback = Feedback(
        resource_id=resource.id, learner_id=learner.id, feedback_type="path_node_assessment",
        feedback_summary_json={"node_id": node_id, "assessment_count": len(evidence)},
        triggered_action="explain", comment="节点验证未达到通过阈值", feedback_intent="too_hard",
        recommended_action="explain", profile_update_required=False,
        profile_change_evidence_json=evidence, decision_confidence=0.9,
        decision_reason="连续两次节点验证未通过，进入统一画像分析与补救资源流程",
    )
    db.add(feedback)
    db.flush()
    try:
        task = create_feedback_task(
            db, learner=learner, profile=profile, resource=resource, feedback=feedback,
            resource_types=["lecture", "practice_guide", "graded_quiz"],
        )
    except FeedbackSourceCompatibilityError:
        return None
    task.learning_path_id = path.id
    task.path_node_id = node_id
    return task


def answer_path_node_assessment(
    db: Session, *, path_id: str, node_id: str, assessment_id: str,
    learner_public_id: str, answer: Any,
) -> tuple[dict[str, Any], GenerationTask | None]:
    path, learner = _path_and_learner(db, path_id)
    if learner.public_id != learner_public_id:
        raise ValueError("learning_path_not_found")
    assessment = db.scalar(select(PathNodeAssessment).where(
        PathNodeAssessment.public_id == assessment_id
    ).with_for_update())
    if assessment is None or assessment.learning_path_id != path.id or assessment.path_node_id != node_id or assessment.learner_id != learner.id:
        raise ValueError("learning_path_assessment_not_found")
    if assessment.status == "scored":
        return dict(assessment.result_json or {}), None
    payload = normalize_path_for_domain(
        db, domain_code=path.domain_code, payload=path.path_json or {}, previous_payload=path.path_json or {}
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
        learner_id=learner.id, question_id=question.id, knowledge_item_id=question.knowledge_item_id,
        session_id=assessment.public_id, answer_text=str(selected), score=score, is_correct=passed,
        scoring_status="scored", scoring_method="deterministic", confidence=0.9,
        answer_summary_json={
            "assessment_id": assessment.public_id, "evidence_type": "path_node_validation",
            "contract_evidence_type": "scored_quiz", "path_id": path.public_id,
            "path_node_id": node_id, "confirmed": True, "confidence": 0.9,
            "consumed_by_profile_id": None,
        },
    )
    db.add(record)
    db.flush()
    evidence_id = f"answer_record:{record.id}"
    verification = _verify_node_evidence(
        db,
        path=path,
        learner=learner,
        node_id=node_id,
        node=node,
        evidence_ids=None,
    )
    unit_passed = bool(verification["verified"])
    if unit_passed:
        _advance_path_node(
            db, path=path, node_id=node_id, evidence_ids=verification["evidence_ids"]
        )
    result = {
        "assessment_id": assessment.public_id, "path_id": path.public_id, "node_id": node_id,
        "score": score, "threshold": threshold, "passed": passed, "evidence_id": evidence_id,
        "unit_verification": verification,
        "completed_node_id": node_id if unit_passed else None,
        "current_node_id": (path.path_json or {}).get("current_node_id"),
        "path_completed": path.status == "completed", "profile_adjustment_task_id": None,
    }
    assessment.answer_record_id = record.id
    assessment.status, assessment.score, assessment.passed = "scored", score, passed
    from app.models import MistakeReviewItem
    from app.services.mistake_evidence_service import evaluate_mistake_evidence
    from app.services.mistake_review_service import _recommended_resource

    mistake_item = db.scalar(
        select(MistakeReviewItem)
        .where(
            MistakeReviewItem.learner_id == learner.id,
            MistakeReviewItem.domain_code == path.domain_code,
            MistakeReviewItem.knowledge_item_id == question.knowledge_item_id,
        )
        .order_by(MistakeReviewItem.id.desc())
    )
    if mistake_item is not None:
        result["mistake_evidence_governance"] = evaluate_mistake_evidence(
            db,
            learner=learner,
            item=mistake_item,
            record=record,
            resource=_recommended_resource(db, mistake_item),
        )
    task = None if passed else _maybe_create_remedial_task(db, path=path, learner=learner, node_id=node_id)
    if task is not None:
        result["profile_adjustment_task_id"] = task.public_id
    assessment.result_json = dict(result)
    sync_existing_mistakes(db, learner=learner, domain_code=path.domain_code)
    db.commit()
    return result, task
