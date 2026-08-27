from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AnswerRecord,
    Feedback,
    GenerationTask,
    KnowledgeItem,
    Learner,
    LearnerProfile,
    LearningPath,
    LearningResource,
)
from app.services.learning_path_service import normalize_path_for_domain
from app.services.mistake_review_service import summary as mistake_summary
from app.services.profile_service import build_learning_path_raw_payload


ABILITY_DIMENSIONS = [
    ("theory", "理论基础"),
    ("practice", "实操能力"),
    ("problem_solving", "问题解决"),
    ("breadth", "知识广度"),
    ("learning_speed", "学习速度"),
]


def _ability_values(profile: LearnerProfile) -> list[float]:
    ability = profile.ability_profile_json or {}
    return [max(0.0, min(100.0, float(ability.get(key) or 0))) for key, _ in ABILITY_DIMENSIONS]


def _weak_map(profile: LearnerProfile) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in profile.weak_knowledge_json or []:
        item = raw if isinstance(raw, dict) else {"knowledge_id": str(raw), "name": str(raw)}
        knowledge_id = str(item.get("knowledge_id") or item.get("id") or "")
        if knowledge_id:
            result[knowledge_id] = item
    return result


def build_learning_progress_comparison(
    db: Session,
    *,
    learner: Learner,
    current_profile: LearnerProfile | None,
    path: LearningPath | None,
) -> dict[str, Any]:
    if current_profile is None or not current_profile.diagnosis_completed:
        return {"available": False, "unavailable_reason": "INITIAL_DIAGNOSIS_REQUIRED"}
    profiles = list(
        db.scalars(
            select(LearnerProfile)
            .where(
                LearnerProfile.learner_id == learner.id,
                LearnerProfile.domain_code == current_profile.domain_code,
                LearnerProfile.diagnosis_completed.is_(True),
                LearnerProfile.profile_source != "default_seed",
            )
            .order_by(LearnerProfile.profile_version, LearnerProfile.id)
        )
    )
    if not profiles:
        return {"available": False, "unavailable_reason": "FORMAL_BASELINE_NOT_FOUND"}
    baseline = profiles[0]
    before = _ability_values(baseline)
    after = _ability_values(current_profile)
    ability_changes = [
        {
            "key": key,
            "label": label,
            "before": round(before[index], 1),
            "after": round(after[index], 1),
            "delta": round(after[index] - before[index], 1),
        }
        for index, (key, label) in enumerate(ABILITY_DIMENSIONS)
    ]
    baseline_weak = _weak_map(baseline)
    current_weak = _weak_map(current_profile)
    confirmed_records = list(
        db.scalars(
            select(AnswerRecord)
            .join(KnowledgeItem, KnowledgeItem.id == AnswerRecord.knowledge_item_id)
            .where(AnswerRecord.learner_id == learner.id, KnowledgeItem.domain_code == current_profile.domain_code)
        )
    )
    confirmed_knowledge_db_ids = {
        record.knowledge_item_id
        for record in confirmed_records
        if (record.answer_summary_json or {}).get("evidence_type")
        == "mistake_consolidation"
        and (record.answer_summary_json or {}).get("governance_status") == "consumed"
        and (record.answer_summary_json or {}).get("consumed_by_profile_id")
        == current_profile.id
    }
    consolidated_knowledge_ids = set(
        db.scalars(
            select(KnowledgeItem.public_id).where(
                KnowledgeItem.id.in_(confirmed_knowledge_db_ids),
                KnowledgeItem.domain_code == current_profile.domain_code,
            )
        )
    ) if confirmed_knowledge_db_ids else set()

    def change_item(knowledge_id: str, source: dict[str, Any], target: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "knowledge_id": knowledge_id,
            "name": source.get("name") or (target or {}).get("name") or knowledge_id,
            "before_level": source.get("weakness_level"),
            "after_level": (target or {}).get("weakness_level"),
        }

    changes: dict[str, list[dict[str, Any]]] = {
        "consolidated": [], "improving": [], "unchanged": [], "new_weakness": []
    }
    for knowledge_id, item in baseline_weak.items():
        current = current_weak.get(knowledge_id)
        if current is None and knowledge_id in consolidated_knowledge_ids:
            changes["consolidated"].append(change_item(knowledge_id, item, None))
        elif current is not None and float(current.get("weakness_level") or 0) < float(item.get("weakness_level") or 0):
            changes["improving"].append(change_item(knowledge_id, item, current))
        else:
            changes["unchanged"].append(change_item(knowledge_id, item, current))
    for knowledge_id, item in current_weak.items():
        if knowledge_id not in baseline_weak:
            changes["new_weakness"].append(change_item(knowledge_id, item, item))

    nodes = list(((path.path_json or {}).get("node_states") or {}).values()) if path else []
    if not nodes and path:
        nodes = list((path.path_json or {}).get("nodes") or [])
    total = len(nodes)
    completed = sum(isinstance(node, dict) and node.get("status") == "completed" for node in nodes)
    current = sum(isinstance(node, dict) and node.get("status") == "current" for node in nodes)
    locked = sum(isinstance(node, dict) and node.get("status") == "locked" for node in nodes)
    skipped = sum(isinstance(node, dict) and node.get("status") == "skipped" for node in nodes)
    consolidation = mistake_summary(db, learner=learner, domain_code=current_profile.domain_code)
    timeline = [
        {
            "type": "initial_diagnosis" if profile.id == baseline.id else "profile_change",
            "title": "首次诊断形成初始画像" if profile.id == baseline.id else f"画像更新至 V{profile.profile_version}",
            "occurred_at": (profile.profile_changed_at or profile.created_at).isoformat(),
            "profile_version": profile.profile_version,
            "confidence": profile.confidence,
            "reason": profile.decision_reason,
            "evidence_refs": list(profile.evidence_refs_json or [])[:5],
        }
        for profile in profiles
        if profile.id == baseline.id or profile.id == current_profile.id or profile.previous_profile_id is not None
    ]
    for record in confirmed_records:
        governance = dict((record.answer_summary_json or {}).get("governance_result") or {})
        if (record.answer_summary_json or {}).get("evidence_type") != "mistake_consolidation":
            continue
        evidence = dict(governance.get("evidence") or {})
        profile_result = dict(governance.get("profile_result") or {})
        path_result = dict(governance.get("path_result") or {})
        timeline.append(
            {
                "type": "mistake_consolidation",
                "title": "错题巩固正式验证",
                "occurred_at": record.created_at.isoformat(),
                "profile_version": profile_result.get("resulting_profile_version"),
                "confidence": record.confidence,
                "reason": evidence.get("governance_reason"),
                "governance_status": evidence.get("governance_status", "pending"),
                "evidence_refs": [f"answer_record:{record.id}"],
                "path_result": path_result,
            }
        )
    return {
        "available": True,
        "unavailable_reason": None,
        "period": {
            "started_at": baseline.created_at.isoformat(),
            "updated_at": (current_profile.profile_changed_at or current_profile.updated_at).isoformat(),
        },
        "baseline": {
            "profile_id": baseline.public_id,
            "profile_version": baseline.profile_version,
            "radar": before,
            "weak_knowledge_count": len(baseline_weak),
        },
        "current": {
            "profile_id": current_profile.public_id,
            "profile_version": current_profile.profile_version,
            "radar": after,
            "weak_knowledge_count": len(current_weak),
        },
        "ability_changes": ability_changes,
        "average_ability_delta": round(sum(item["delta"] for item in ability_changes) / 5, 1),
        "knowledge_changes": changes,
        "path_progress": {
            "total": total,
            "completed": completed,
            "current": current,
            "locked": locked,
            "skipped": skipped,
            "completion_rate": round(completed / total * 100, 1) if total else None,
        },
        "mistake_consolidation": consolidation,
        "timeline": sorted(timeline, key=lambda item: item["occurred_at"]),
    }


def build_learning_history(
    db: Session,
    *,
    learner: Learner,
    domain_code: str,
) -> list[dict[str, Any]]:
    """Return a safe, cross-path timeline without learner message bodies."""
    events: list[dict[str, Any]] = []
    seen_completed: set[tuple[str, tuple[str, ...], str | None]] = set()
    paths = list(
        db.scalars(
            select(LearningPath)
            .where(
                LearningPath.learner_id == learner.id,
                LearningPath.domain_code == domain_code,
            )
            .order_by(LearningPath.created_at, LearningPath.id)
        )
    )
    for path in paths:
        payload = path.path_json or {}
        states = [
            *(payload.get("node_states") or {}).values(),
            *(payload.get("retired_node_states") or {}).values(),
        ]
        for node in states:
            if not isinstance(node, dict) or node.get("status") != "completed":
                continue
            completed_at = node.get("completed_at")
            if not completed_at:
                continue
            evidence_refs = tuple(str(value) for value in node.get("completion_evidence_ids") or [])
            key = (str(node.get("path_node_id") or ""), evidence_refs, str(completed_at))
            if not key[0] or key in seen_completed:
                continue
            seen_completed.add(key)
            events.append(
                {
                    "event_id": f"path_node_completed:{path.public_id}:{key[0]}",
                    "type": "path_node_completed",
                    "title": f"完成学习节点：{node.get('title') or key[0]}",
                    "occurred_at": str(completed_at),
                    "path_id": path.public_id,
                    "path_node_id": key[0],
                    "task_id": None,
                    "feedback_id": None,
                    "profile_version": None,
                    "reason": "掌握验证已通过，学习路线已推进。",
                    "evidence_refs": list(evidence_refs),
                }
            )

    profiles = list(
        db.scalars(
            select(LearnerProfile)
            .where(
                LearnerProfile.learner_id == learner.id,
                LearnerProfile.domain_code == domain_code,
                LearnerProfile.diagnosis_completed.is_(True),
                LearnerProfile.profile_source != "default_seed",
            )
            .order_by(LearnerProfile.profile_version, LearnerProfile.id)
        )
    )
    for profile in profiles:
        occurred_at = profile.profile_changed_at or profile.created_at
        events.append(
            {
                "event_id": f"profile:{profile.public_id}",
                "type": "initial_diagnosis" if profile.previous_profile_id is None else "profile_updated",
                "title": (
                    "首次诊断形成初始画像"
                    if profile.previous_profile_id is None
                    else f"画像更新至 V{profile.profile_version}"
                ),
                "occurred_at": occurred_at.isoformat(),
                "path_id": None,
                "path_node_id": None,
                "task_id": None,
                "feedback_id": None,
                "profile_version": profile.profile_version,
                "reason": profile.decision_reason,
                "evidence_refs": list(profile.evidence_refs_json or [])[:5],
            }
        )

    feedback_rows = list(
        db.scalars(
            select(Feedback)
            .join(LearningResource, LearningResource.id == Feedback.resource_id)
            .join(GenerationTask, GenerationTask.id == LearningResource.generation_task_id)
            .where(
                Feedback.learner_id == learner.id,
                GenerationTask.domain_code == domain_code,
            )
            .order_by(Feedback.created_at, Feedback.id)
        )
    )
    for feedback in feedback_rows:
        intent = feedback.feedback_intent or feedback.feedback_type
        title = (
            "掌握验证已确认"
            if feedback.feedback_type == "mastery_check" and feedback.profile_update_required
            else "导学反馈已记录"
        )
        events.append(
            {
                "event_id": f"feedback:{feedback.id}",
                "type": "mastery_check" if feedback.feedback_type == "mastery_check" else "feedback_received",
                "title": title,
                "occurred_at": feedback.created_at.isoformat(),
                "path_id": None,
                "path_node_id": None,
                "task_id": None,
                "feedback_id": str(feedback.id),
                "profile_version": None,
                "reason": f"识别意图：{intent or '待澄清'}；建议动作：{feedback.recommended_action or '继续导学'}。",
                "evidence_refs": [],
            }
        )

    tasks = list(
        db.scalars(
            select(GenerationTask)
            .where(
                GenerationTask.learner_id == learner.id,
                GenerationTask.domain_code == domain_code,
                GenerationTask.event_type == "resource_feedback",
            )
            .order_by(GenerationTask.created_at, GenerationTask.id)
        )
    )
    for task in tasks:
        events.append(
            {
                "event_id": f"feedback_task_created:{task.public_id}",
                "type": "feedback_task_created",
                "title": "反馈驱动资源任务已创建",
                "occurred_at": task.created_at.isoformat(),
                "path_id": None,
                "path_node_id": task.path_node_id,
                "task_id": task.public_id,
                "feedback_id": str(task.source_feedback_id) if task.source_feedback_id else None,
                "profile_version": None,
                "reason": "导学证据已确认，系统为受影响学习节点生成资源。",
                "evidence_refs": [],
            }
        )
        if task.status == "completed":
            events.append(
                {
                    "event_id": f"feedback_task_completed:{task.public_id}",
                    "type": "feedback_task_completed",
                    "title": "反馈驱动资源已完成审核",
                    "occurred_at": task.updated_at.isoformat(),
                    "path_id": None,
                    "path_node_id": task.path_node_id,
                    "task_id": task.public_id,
                    "feedback_id": str(task.source_feedback_id) if task.source_feedback_id else None,
                    "profile_version": None,
                    "reason": "资源已完成生成与审核，可继续当前学习节点。",
                    "evidence_refs": [],
                }
            )
    return sorted(events, key=lambda item: (item["occurred_at"], item["event_id"]))


def refresh_learning_path(
    *,
    db: Session,
    path: LearningPath,
    profile: LearnerProfile,
    profile_detail: dict[str, Any],
) -> dict[str, Any]:
    raw_weak = profile_detail.get("weak_knowledge") or []
    weak_knowledge = [
        item
        if isinstance(item, dict)
        else {"knowledge_id": str(item), "name": str(item), "prerequisites": []}
        for item in raw_weak
    ]
    diagnostic = profile_detail.get("diagnostic_summary") or {}
    ability = profile.ability_profile_json or {}
    previous_payload = dict(path.path_json or {})
    payload = build_learning_path_raw_payload(
        profile_type=str(
            profile_detail.get("profile_type")
            or ability.get("profile_type")
            or "beginner"
        ),
        score_percent=float(diagnostic.get("score_percent") or 0),
        weak_knowledge=weak_knowledge,
    )
    payload = normalize_path_for_domain(
        db,
        domain_code=path.domain_code,
        payload=payload,
        previous_payload=previous_payload,
    )
    payload["refresh_reason"] = previous_payload.get(
        "knowledge_update_reason", "profile_or_knowledge_changed"
    )
    payload["refreshed_at"] = datetime.now(UTC).isoformat()
    path.path_json = payload
    path.profile_id = profile.id
    path.needs_refresh = False
    return payload
