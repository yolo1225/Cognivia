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
from app.services.profile_knowledge_state_service import STATE_KEY
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


def _knowledge_state_map(profile: LearnerProfile) -> dict[str, dict[str, Any]]:
    """Return the persisted evidence state, with no mutation of legacy profiles."""
    payload = (profile.ability_profile_json or {}).get(STATE_KEY)
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, dict):
        return {}
    return {
        str(knowledge_id): dict(item)
        for knowledge_id, item in items.items()
        if isinstance(item, dict)
    }


_KNOWLEDGE_STATUS_RANK = {
    "unassessed": 0,
    "unmastered": 1,
    "confused": 2,
    "partial_mastery": 3,
    "known": 4,
}


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
    baseline_states = _knowledge_state_map(baseline)
    current_states = _knowledge_state_map(current_profile)
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
            "before_status": source.get("status"),
            "after_status": (target or {}).get("status"),
            "before_mastery_score": source.get("mastery_score"),
            "after_mastery_score": (target or {}).get("mastery_score"),
            "before_evidence_count": source.get("evidence_count", 0),
            "after_evidence_count": (target or {}).get("evidence_count", 0),
        }

    changes: dict[str, list[dict[str, Any]]] = {
        "consolidated": [], "improving": [], "new_evidence": [], "unchanged": [], "new_weakness": []
    }
    if baseline_states or current_states:
        for knowledge_id in sorted(set(baseline_states) | set(current_states)):
            before_state = baseline_states.get(knowledge_id, {"knowledge_id": knowledge_id, "status": "unassessed"})
            after_state = current_states.get(knowledge_id, before_state)
            before_status = str(before_state.get("status") or "unassessed")
            after_status = str(after_state.get("status") or "unassessed")
            before_mastery = float(before_state.get("mastery_score") or 0)
            after_mastery = float(after_state.get("mastery_score") or 0)
            before_evidence = int(before_state.get("evidence_count") or 0)
            after_evidence = int(after_state.get("evidence_count") or 0)
            item = change_item(knowledge_id, before_state, after_state)
            if before_status == "unassessed" and after_status in {"partial_mastery", "known"} and after_evidence > before_evidence:
                changes["new_evidence"].append(item)
            elif after_status == "known" and before_status != "known":
                changes["consolidated"].append(item)
            elif (
                _KNOWLEDGE_STATUS_RANK.get(after_status, 0) < _KNOWLEDGE_STATUS_RANK.get(before_status, 0)
                or (after_status in {"unmastered", "confused"} and before_status == "unassessed")
                or (after_mastery + 0.08 < before_mastery)
            ):
                changes["new_weakness"].append(item)
            elif (
                _KNOWLEDGE_STATUS_RANK.get(after_status, 0) > _KNOWLEDGE_STATUS_RANK.get(before_status, 0)
                or after_mastery > before_mastery + 0.08
            ):
                changes["improving"].append(item)
            elif before_state != after_state:
                changes["unchanged"].append(item)
    else:
        # Historical profiles have no detailed evidence state. Preserve the
        # previous weak-list comparison without calling new evidence a weakness.
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
        if (record.answer_summary_json or {}).get("evidence_type") not in {
            "mistake_correction",
            "mistake_consolidation",
        }:
            continue
        evidence = dict(governance.get("evidence") or {})
        profile_result = dict(governance.get("profile_result") or {})
        path_result = dict(governance.get("path_result") or {})
        timeline.append(
            {
                "type": "mistake_consolidation",
                "title": "错题原题修正",
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


_JOURNEY_RESOURCE_TYPE_LABELS = {
    "lecture": "个性化讲义",
    "practice_guide": "实操指南",
    "graded_quiz": "分阶测试",
}


def _journey_path_nodes(path: LearningPath | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = path.path_json or {}
    states = list((payload.get("node_states") or {}).values())
    return [item for item in states if isinstance(item, dict)] or [
        item for item in (payload.get("nodes") or []) if isinstance(item, dict)
    ]


def _journey_resource_summary(resource: LearningResource) -> dict[str, Any]:
    return {
        "resource_id": resource.public_id,
        "title": resource.title,
        "resource_type": resource.resource_type,
        "resource_type_label": _JOURNEY_RESOURCE_TYPE_LABELS.get(
            resource.resource_type, resource.resource_type
        ),
        "difficulty": resource.difficulty,
    }


def _journey_resources_action(task_id: str) -> dict[str, str]:
    return {
        "type": "view_resources",
        "label": "查看学习资源",
        "route": f"/resources?task_id={task_id}",
    }


def _journey_continue_action() -> dict[str, str]:
    return {"type": "continue_learning", "label": "继续学习", "route": "/report"}


def build_learning_journey(
    db: Session,
    *,
    learner: Learner,
    domain_code: str,
) -> dict[str, Any]:
    """Build a learner-safe journey from business outcomes, never agent runtime records."""
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
    tasks = list(
        db.scalars(
            select(GenerationTask)
            .where(
                GenerationTask.learner_id == learner.id,
                GenerationTask.domain_code == domain_code,
            )
            .order_by(GenerationTask.created_at, GenerationTask.id)
        )
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
    task_resources: dict[int, list[LearningResource]] = {task.id: [] for task in tasks}
    if task_resources:
        for resource in db.scalars(
            select(LearningResource)
            .where(LearningResource.generation_task_id.in_(task_resources))
            .where(LearningResource.review_status == "passed")
            .order_by(LearningResource.id)
        ):
            task_resources[resource.generation_task_id].append(resource)

    node_by_path_and_id = {
        (path.id, str(node.get("path_node_id"))): node
        for path in paths
        for node in _journey_path_nodes(path)
        if node.get("path_node_id")
    }
    task_by_feedback = {
        task.source_feedback_id: task
        for task in tasks
        if task.source_feedback_id is not None
    }
    profile_by_feedback = {
        profile.trigger_feedback_id: profile
        for profile in profiles
        if profile.trigger_feedback_id is not None
    }

    knowledge_ids: set[str] = set()
    for feedback in feedback_rows:
        knowledge_ids.update(str(item) for item in feedback.affected_knowledge_ids_json or [])
    for task in tasks:
        for targets in (task.resource_knowledge_targets_json or {}).values():
            if isinstance(targets, list):
                knowledge_ids.update(str(item) for item in targets)
    knowledge_names = {
        item.public_id: item.name
        for item in db.scalars(
            select(KnowledgeItem).where(
                KnowledgeItem.domain_code == domain_code,
                KnowledgeItem.public_id.in_(knowledge_ids),
            )
        )
    } if knowledge_ids else {}

    def related_knowledge(*sources: list[str]) -> list[str]:
        values: list[str] = []
        for source in sources:
            for item in source or []:
                name = knowledge_names.get(str(item))
                if name and name not in values:
                    values.append(name)
        return values[:5]

    def task_node(task: GenerationTask) -> dict[str, Any] | None:
        if task.learning_path_id is None or not task.path_node_id:
            return None
        return node_by_path_and_id.get((task.learning_path_id, task.path_node_id))

    def task_event_time(task: GenerationTask, *, fallback: datetime) -> datetime:
        """Use immutable business output time instead of mutable task.updated_at.

        Publishing a newer package marks every older task as non-current. That
        maintenance update advances their ``updated_at`` values and must not move
        historical generation milestones to the top of the learner journey.
        """
        resources = task_resources.get(task.id, [])
        if resources:
            return max(resource.created_at for resource in resources)
        return fallback

    milestones: list[dict[str, Any]] = []
    if profiles:
        initial = profiles[0]
        initial_path = next((path for path in paths if path.profile_id == initial.id), None)
        milestones.append(
            {
                "milestone_id": f"initial_profile:{initial.public_id}",
                "type": "initial_diagnosis",
                "status": "completed",
                "occurred_at": (initial.profile_changed_at or initial.created_at).isoformat(),
                "title": "完成首次诊断，建立学习路线",
                "summary": "系统已根据诊断结果确定当前学习起点，并生成个性化学习路线。",
                "outcome": f"已形成能力画像 V{initial.profile_version}" + (" 和学习路线。" if initial_path else "。"),
                "knowledge_names": [],
                "resources": [],
                "actions": [_journey_continue_action()] if initial_path else [],
            }
        )

    feedback_node_ids: set[str] = set()
    for feedback in feedback_rows:
        task = task_by_feedback.get(feedback.id)
        profile = profile_by_feedback.get(feedback.id)
        has_result = task is not None or profile is not None
        if not has_result:
            continue
        affected_nodes = [str(item) for item in feedback.affected_path_node_ids_json or []]
        feedback_node_ids.update(affected_nodes)
        is_mastery = feedback.feedback_type == "mastery_check" and feedback.profile_update_required
        title = (
            "掌握验证通过，学习路线已推进"
            if is_mastery
            else {
                "too_hard": "根据反馈补充学习支持",
                "too_easy": "根据反馈增加挑战任务",
                "confusing": "根据反馈调整讲解方式",
                "incorrect": "根据反馈安排内容复核",
            }.get(feedback.feedback_type, "学习反馈已形成调整")
        )
        task_status = (
            "in_progress"
            if task and task.status in {"pending", "retry_pending", "running", "revision_required"}
            else "failed"
            if task and task.status == "failed"
            else "completed"
        )
        resource_items = [_journey_resource_summary(item) for item in task_resources.get(task.id, [])] if task else []
        if is_mastery:
            completed_node = next(
                (
                    node.get("title") or node_id
                    for node_id in affected_nodes
                    if (node := node_by_path_and_id.get((task.learning_path_id, node_id)) if task else None)
                ),
                "原学习节点",
            )
            next_node = task_node(task) if task else None
            next_title = next_node.get("title") if next_node else "下一学习节点"
            package_state = (
                "学习包已完成，可开始下一节点学习。"
                if task and task.status == "completed" and task.decision == "completed" and resource_items
                else "学习包生成失败，可从报告页重新生成。"
                if task and task.status == "failed"
                else "历史任务未生成资源，可从报告页重新生成。"
                if task and task.decision == "no_change" and not resource_items
                else "正在生成下一节点学习包。"
                if task
                else "等待你确认生成下一节点学习包。"
            )
            outcome = (
                f"画像已更新至 V{profile.profile_version if profile else '—'}；已完成「{completed_node}」，"
                f"已解锁「{next_title}」。{package_state}"
            )
        else:
            outcome = (
                f"已生成 {len(resource_items)} 份适配资源。"
                if task and task.status == "completed" and resource_items
                else "资源生成失败，可稍后重试。"
                if task and task.status == "failed"
                else "系统正在为当前学习节点准备适配资源。"
                if task
                else f"能力画像已更新至 V{profile.profile_version}。"
                if profile
                else "已记录本次学习调整。"
            )
        actions = [_journey_resources_action(task.public_id)] if task else []
        if is_mastery:
            actions.append(_journey_continue_action())
        milestones.append(
            {
                "milestone_id": f"feedback:{feedback.id}",
                "type": "feedback_adjustment",
                "status": task_status,
                "occurred_at": (
                    task_event_time(task, fallback=feedback.created_at)
                    if task and task.status == "completed"
                    else feedback.created_at
                ).isoformat(),
                "title": title,
                "summary": "系统结合你的学习反馈与正式学习证据，决定是否调整当前资源和学习路线。",
                "outcome": outcome,
                "knowledge_names": related_knowledge(list(feedback.affected_knowledge_ids_json or [])),
                "resources": resource_items,
                "actions": actions,
            }
        )

    for task in tasks:
        if task.source_feedback_id is not None:
            continue
        node = task_node(task)
        resource_items = [_journey_resource_summary(item) for item in task_resources.get(task.id, [])]
        status = "in_progress" if task.status in {"pending", "retry_pending", "running", "revision_required"} else "failed" if task.status == "failed" else "completed"
        if task.event_type == "knowledge_refresh":
            journey_type = "knowledge_refresh"
            title = "知识更新后已刷新学习资源"
            summary = "相关知识更新后，系统保留未受影响内容，并只更新当前需要调整的资源。"
        elif status == "in_progress":
            journey_type = "resource_generation"
            title = "正在为当前节点准备学习资源"
            summary = "系统正在根据当前能力画像和学习目标准备适配资源。"
        else:
            journey_type = "resource_generation"
            title = f"为「{node.get('title')}」生成学习资源" if node else "生成个性化学习包"
            summary = "已基于当前能力画像和学习目标生成可用的学习资源。"
        outcome = (
            f"当前可学习 {len(resource_items)} 份资源。"
            if status == "completed"
            else "资源准备完成后会出现在学习资源页。"
        )
        targets = [
            str(item)
            for values in (task.resource_knowledge_targets_json or {}).values()
            if isinstance(values, list)
            for item in values
        ]
        milestones.append(
            {
                "milestone_id": f"task:{task.public_id}",
                "type": journey_type,
                "status": status,
                "occurred_at": task_event_time(
                    task,
                    fallback=task.created_at,
                ).isoformat(),
                "title": title,
                "summary": summary,
                "outcome": outcome,
                "knowledge_names": related_knowledge(targets),
                "resources": resource_items,
                "actions": [_journey_resources_action(task.public_id)],
            }
        )

    seen_completed_nodes: set[tuple[str, str]] = set()
    for path in paths:
        for node in _journey_path_nodes(path):
            node_id = str(node.get("path_node_id") or "")
            completed_at = node.get("completed_at")
            if not node_id or not completed_at or node.get("status") != "completed":
                continue
            key = (node_id, str(completed_at))
            if key in seen_completed_nodes or node_id in feedback_node_ids:
                continue
            seen_completed_nodes.add(key)
            milestones.append(
                {
                    "milestone_id": f"path_completed:{path.public_id}:{node_id}",
                    "type": "path_progress",
                    "status": "completed",
                    "occurred_at": str(completed_at),
                    "title": f"完成学习节点：{node.get('title') or node_id}",
                    "summary": "掌握验证已通过，系统已将学习路线推进到下一节点。",
                    "outcome": "可以继续下一阶段学习。",
                    "knowledge_names": [],
                    "resources": [],
                    "actions": [_journey_continue_action()],
                }
            )

    for profile in profiles[1:]:
        if profile.trigger_feedback_id is not None:
            continue
        milestones.append(
            {
                "milestone_id": f"profile_update:{profile.public_id}",
                "type": "profile_update",
                "status": "completed",
                "occurred_at": (profile.profile_changed_at or profile.created_at).isoformat(),
                "title": "学习证据更新了能力画像",
                "summary": "系统根据新的正式学习证据更新了你的能力判断与后续建议。",
                "outcome": f"能力画像已更新至 V{profile.profile_version}。",
                "knowledge_names": [],
                "resources": [],
                "actions": [_journey_continue_action()],
            }
        )

    latest_path = paths[-1] if paths else None
    current_nodes = _journey_path_nodes(latest_path)
    improved_knowledge = 0
    for before, after in zip(profiles, profiles[1:]):
        before_weak = _weak_map(before)
        after_weak = _weak_map(after)
        improved_knowledge += sum(
            1
            for knowledge_id, item in before_weak.items()
            if knowledge_id not in after_weak
            or float(after_weak[knowledge_id].get("weakness_level") or 0)
            < float(item.get("weakness_level") or 0)
        )
    feedback_adjustments = sum(
        1
        for feedback in feedback_rows
        if feedback.id in task_by_feedback or feedback.id in profile_by_feedback
    )
    available_resources = sum(
        1
        for resources in task_resources.values()
        for resource in resources
    )
    completed_nodes = sum(node.get("status") == "completed" for node in current_nodes)
    return {
        "learner_id": learner.public_id,
        "domain_code": domain_code,
        "overview": {
            "path_total": len(current_nodes),
            "path_completed": completed_nodes,
            "path_completion_rate": round(completed_nodes / len(current_nodes) * 100, 1) if current_nodes else None,
            "improved_knowledge_count": improved_knowledge,
            "feedback_adjustment_count": feedback_adjustments,
            "available_resource_count": available_resources,
        },
        "milestones": sorted(
            milestones,
            key=lambda item: (item["occurred_at"], item["milestone_id"]),
            reverse=True,
        ),
    }


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
