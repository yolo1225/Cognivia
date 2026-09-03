"""Internal learner-state facts and V9-compatible profile projections.

The full state intentionally lives outside the frozen Agent contract.  Agent
consumers continue to receive the existing ProfileSnapshot projection.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from math import sqrt, tanh
from typing import Any, Iterable, Mapping

from app.agents.contracts import (
    AbilityScores,
    AnalyzeProfileOutput,
    EvidenceRef,
    EvidenceType,
    KnowledgeAssessment,
    MasteryType,
    ProfileSnapshot,
    ProfileType,
    WeakKnowledge,
)
from app.agents.profile_analysis_config import ProfileAnalysisConfig


STATE_KEY = "knowledge_state_v1"
# Keep the storage key stable for existing profiles.  The payload version is
# upgraded lazily when the next formal evidence arrives; historical payloads
# remain readable and are never backfilled.
STATE_VERSION = "knowledge-state-v2"
LEGACY_STATE_VERSION = "knowledge-state-v1"
MIN_EFFECTIVE_WEIGHT = 0.7
KNOWN_EFFECTIVE_WEIGHT = 1.5
WEAK_PROJECTION_CONFIDENCE = 0.35
BLIND_SPOT_CONFIDENCE = 0.5
LEARNING_SPEED_MIN_KNOWLEDGE = 2
LEARNING_SPEED_MIN_EFFECTIVE_WEIGHT = 1.4
LEARNING_SPEED_RELIABLE_KNOWLEDGE = 5
LEARNING_SPEED_EFFICIENCY_BASELINE = 0.25

_ALLOWED_EVIDENCE = {
    EvidenceType.DIAGNOSTIC_RESULT,
    EvidenceType.SCORED_QUIZ,
}
_SOURCE_RELIABILITY = {
    EvidenceType.DIAGNOSTIC_RESULT: 1.0,
    EvidenceType.SCORED_QUIZ: 1.0,
}


def _bounded_score(value: float) -> int:
    return max(0, min(100, round(value)))


def _background_prior(context: Mapping[str, Any]) -> float:
    education = str(context.get("education_level") or "")
    major = str(context.get("major") or "").lower()
    experience = max(0.0, min(10.0, float(context.get("experience_years") or 0)))
    relevant_major = any(
        marker in major
        for marker in ("软件", "计算机", "人工智能", "数据", "信息", "automation", "computer")
    )
    education_bonus = 4 if education in {"本科", "硕士及以上"} else 2 if education == "专科" else 0
    return min(72.0, 42.0 + education_bonus + (5 if relevant_major else 0) + experience * 2)


def _previous_items(payload: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, Mapping) or payload.get("version") not in {
        STATE_VERSION,
        LEGACY_STATE_VERSION,
    }:
        return {}
    items = payload.get("items")
    return {
        str(key): dict(value)
        for key, value in (items.items() if isinstance(items, Mapping) else [])
        if isinstance(value, Mapping)
    }


def _status(
    *,
    mastery: float,
    effective_weight: float,
    core_evidence_count: int,
    core_effective_weight: float,
    confusion_tag_counts: Mapping[str, int],
    config: ProfileAnalysisConfig,
) -> str:
    if effective_weight < MIN_EFFECTIVE_WEIGHT:
        return "unassessed"
    if mastery < 0.4:
        return "unmastered"
    # Mistake correction is useful corroboration but can never establish
    # "known" on its own.  A confirmed status always needs independent core
    # formal questions.
    if (
        mastery >= 0.8
        and effective_weight >= KNOWN_EFFECTIVE_WEIGHT
        and core_evidence_count >= config.knowledge_min_distinct_questions
        and core_effective_weight >= config.knowledge_min_effective_weight
    ):
        return "known"
    if any(count >= 2 for count in confusion_tag_counts.values()):
        return "confused"
    return "partial_mastery"


def build_knowledge_state(
    *,
    config: ProfileAnalysisConfig,
    assessments: Iterable[KnowledgeAssessment],
    evidence: Iterable[EvidenceRef],
    previous_state: Mapping[str, Any] | None = None,
    excluded_evidence_ids: set[str] | None = None,
    confusion_tags_by_evidence: Mapping[str, list[str]] | None = None,
    evidence_class_by_id: Mapping[str, str] | None = None,
    assessed_at: str | None = None,
) -> dict[str, Any]:
    """Accumulate de-duplicated formal evidence across every domain knowledge item."""

    previous = _previous_items(previous_state)
    evidence_by_id = {item.evidence_id: item for item in evidence}
    excluded = excluded_evidence_ids or set()
    tags_by_evidence = confusion_tags_by_evidence or {}
    classes_by_evidence = evidence_class_by_id or {}
    now = assessed_at or datetime.now(UTC).isoformat()
    items: dict[str, dict[str, Any]] = {}

    for knowledge_id, metadata in config.knowledge_catalog.items():
        old = previous.get(knowledge_id, {})
        items[knowledge_id] = {
            "knowledge_id": knowledge_id,
            "name": metadata.name,
            "category": metadata.category,
            "prerequisite_ids": list(metadata.prerequisite_ids),
            "success_weight": float(old.get("success_weight") or 0.0),
            "failure_weight": float(old.get("failure_weight") or 0.0),
            "effective_weight": float(old.get("effective_weight") or 0.0),
            "evidence_count": int(old.get("evidence_count") or 0),
            "core_evidence_count": int(old.get("core_evidence_count") or 0),
            "auxiliary_evidence_count": int(old.get("auxiliary_evidence_count") or 0),
            "core_effective_weight": float(old.get("core_effective_weight") or 0.0),
            "evidence_ids": list(old.get("evidence_ids") or [])[-20:],
            "core_question_ids": list(old.get("core_question_ids") or [])[-20:],
            "confusion_tags": list(old.get("confusion_tags") or [])[-10:],
            "confusion_tag_counts": dict(old.get("confusion_tag_counts") or {}),
            "last_assessed_at": old.get("last_assessed_at"),
        }

    accepted_ids: list[str] = []
    accepted_core_knowledge_ids: set[str] = set()
    for assessment in assessments:
        item = items.get(assessment.knowledge_id)
        source = evidence_by_id.get(assessment.evidence_id)
        if item is None or assessment.evidence_id in item["evidence_ids"]:
            continue
        if (
            not assessment.attempted
            or assessment.score is None
            or source is None
            or not source.confirmed
            or source.evidence_type not in _ALLOWED_EVIDENCE
            or assessment.evidence_id in excluded
        ):
            continue
        confidence = min(float(assessment.confidence), float(source.confidence))
        if confidence <= 0:
            continue
        weight = (
            config.difficulty_weight(assessment.difficulty)
            * confidence
            * _SOURCE_RELIABILITY[source.evidence_type]
        )
        item["success_weight"] += float(assessment.score) * weight
        item["failure_weight"] += (1 - float(assessment.score)) * weight
        item["effective_weight"] += weight
        item["evidence_count"] += 1
        evidence_class = str(classes_by_evidence.get(assessment.evidence_id) or "core")
        if evidence_class == "auxiliary":
            item["auxiliary_evidence_count"] += 1
        else:
            item["core_evidence_count"] += 1
            item["core_effective_weight"] += weight
            source_ref_id = str(source.source_ref_id or assessment.evidence_id)
            if source_ref_id not in item["core_question_ids"]:
                item["core_question_ids"] = [*item["core_question_ids"], source_ref_id][-20:]
            accepted_core_knowledge_ids.add(assessment.knowledge_id)
        item["evidence_ids"] = [*item["evidence_ids"], assessment.evidence_id][-20:]
        new_tags = [str(tag) for tag in tags_by_evidence.get(assessment.evidence_id, []) if str(tag)]
        for tag in set(new_tags):
            item["confusion_tag_counts"][tag] = int(item["confusion_tag_counts"].get(tag, 0)) + 1
        item["confusion_tags"] = list(dict.fromkeys([*item["confusion_tags"], *new_tags]))[-10:]
        item["last_assessed_at"] = now
        accepted_ids.append(assessment.evidence_id)

    status_counts: Counter[str] = Counter()
    assessed_categories: set[str] = set()
    total_effective_weight = 0.0
    for item in items.values():
        effective_weight = float(item["effective_weight"])
        mastery = (0.5 + float(item["success_weight"])) / (1 + effective_weight)
        item["mastery_score"] = round(mastery, 4)
        item["confidence"] = round(min(1.0, effective_weight / 2), 4)
        item["status"] = _status(
            mastery=mastery,
            effective_weight=effective_weight,
            core_evidence_count=int(item["core_evidence_count"]),
            core_effective_weight=float(item["core_effective_weight"]),
            confusion_tag_counts=item["confusion_tag_counts"],
            config=config,
        )
        item["success_weight"] = round(float(item["success_weight"]), 6)
        item["failure_weight"] = round(float(item["failure_weight"]), 6)
        item["effective_weight"] = round(effective_weight, 6)
        item["core_effective_weight"] = round(float(item["core_effective_weight"]), 6)
        status_counts[item["status"]] += 1
        if item["status"] != "unassessed":
            assessed_categories.add(str(item["category"]))
            total_effective_weight += effective_weight

    assessed_count = len(items) - status_counts["unassessed"]
    categories = {str(item.category) for item in config.knowledge_catalog.values()}
    return {
        "version": STATE_VERSION,
        "generated_at": now,
        "items": items,
        "accepted_evidence_ids": list(dict.fromkeys(accepted_ids)),
        "accepted_core_knowledge_ids": sorted(accepted_core_knowledge_ids),
        "rule_version": config.subsequent_rule_version,
        "coverage": {
            "knowledge_total": len(items),
            "assessed_count": assessed_count,
            "assessed_rate": round(assessed_count / len(items), 4) if items else 0.0,
            "category_total": len(categories),
            "assessed_category_count": len(assessed_categories),
            "category_rate": round(len(assessed_categories) / len(categories), 4) if categories else 0.0,
            "effective_weight": round(total_effective_weight, 4),
        },
        "status_counts": dict(status_counts),
    }


def _ability_scores(
    *,
    state: Mapping[str, Any],
    previous_state: Mapping[str, Any] | None,
    config: ProfileAnalysisConfig,
    context: Mapping[str, Any],
) -> tuple[AbilityScores, dict[str, str], dict[str, Any]]:
    items = list((state.get("items") or {}).values())
    prior = _background_prior(context)
    scores: dict[str, int] = {}
    statuses: dict[str, str] = {}
    for dimension in ("theory", "practice", "problem_solving"):
        weighted = [
            (
                float(item["mastery_score"]),
                float(config.ability_weights[item["knowledge_id"]][dimension])
                * float(item["confidence"]),
            )
            for item in items
            if item["status"] != "unassessed"
            and float(config.ability_weights[item["knowledge_id"]][dimension]) > 0
        ]
        denominator = sum(weight for _, weight in weighted)
        if denominator <= 0:
            scores[dimension] = _bounded_score(prior)
            statuses[dimension] = "insufficient_evidence"
            continue
        observed = sum(mastery * weight for mastery, weight in weighted) / denominator * 100
        evidence_share = 0.85 * min(1.0, float(state["coverage"]["effective_weight"]) / 4)
        scores[dimension] = _bounded_score(observed * evidence_share + prior * (1 - evidence_share))
        statuses[dimension] = "assessed" if evidence_share >= 0.5 else "provisional"

    knowledge_total = max(1, int(state["coverage"]["knowledge_total"]))
    assessed_rate = float(state["coverage"]["assessed_rate"])
    category_rate = float(state["coverage"]["category_rate"])
    confirmed_mastery = sum(
        float(item["mastery_score"]) * float(item["confidence"])
        for item in items
        if item["status"] != "unassessed"
    ) / knowledge_total
    scores["knowledge_breadth"] = _bounded_score(
        100 * (0.35 * assessed_rate + 0.25 * category_rate + 0.40 * confirmed_mastery)
    )
    statuses["knowledge_breadth"] = "assessed" if assessed_rate >= 0.2 else "provisional"

    speed_score, speed_status, speed_evidence = _learning_speed_score(
        state=state,
        previous_state=previous_state,
    )
    scores["learning_speed"] = speed_score
    statuses["learning_speed"] = speed_status
    return AbilityScores(**scores), statuses, speed_evidence


def _learning_speed_score(
    *, state: Mapping[str, Any], previous_state: Mapping[str, Any] | None
) -> tuple[int, str, dict[str, Any]]:
    """Measure normalized mastery gain per new formal learning opportunity.

    Calendar time and raw answer speed are deliberately excluded until reliable
    active-learning duration is available.  The compatible integer projection
    remains 50 while longitudinal evidence is insufficient.
    """

    old_items = _previous_items(previous_state)
    accepted_ids = set(str(value) for value in (state.get("accepted_evidence_ids") or []))
    gains: list[tuple[str, float, float]] = []
    for raw_item in (state.get("items") or {}).values():
        item = dict(raw_item)
        knowledge_id = str(item.get("knowledge_id") or "")
        old = old_items.get(knowledge_id)
        if old is None or int(item.get("evidence_count") or 0) <= int(old.get("evidence_count") or 0):
            continue
        effective_weight = max(
            0.0,
            float(item.get("effective_weight") or 0) - float(old.get("effective_weight") or 0),
        )
        if effective_weight <= 0:
            continue
        before = float(old.get("mastery_score", 0.5))
        after = float(item.get("mastery_score", 0.5))
        normalized_gain = max(-1.0, min(1.0, (after - before) / max(1 - before, 0.1)))
        gains.append((knowledge_id, normalized_gain, effective_weight))

    total_weight = sum(weight for _, _, weight in gains)
    evidence = {
        "version": "learning-speed-opportunity-v1",
        "opportunity_count": len(accepted_ids),
        "changed_knowledge_count": len(gains),
        "effective_weight": round(total_weight, 4),
        "knowledge_ids": sorted(knowledge_id for knowledge_id, _, _ in gains),
    }
    if (
        not old_items
        or len(gains) < LEARNING_SPEED_MIN_KNOWLEDGE
        or len(accepted_ids) < LEARNING_SPEED_MIN_KNOWLEDGE
        or total_weight < LEARNING_SPEED_MIN_EFFECTIVE_WEIGHT
    ):
        return 50, "insufficient_longitudinal_evidence", evidence

    weighted_gain = sum(gain * weight for _, gain, weight in gains) / total_weight
    efficiency = weighted_gain / sqrt(max(len(accepted_ids), 1))
    raw_score = 50 + 30 * tanh(efficiency / LEARNING_SPEED_EFFICIENCY_BASELINE)
    reliability = min(1.0, len(gains) / LEARNING_SPEED_RELIABLE_KNOWLEDGE)
    score = max(20, min(95, round(50 + (raw_score - 50) * reliability)))
    evidence.update({
        "normalized_gain": round(weighted_gain, 4),
        "learning_efficiency": round(efficiency, 4),
        "reliability": round(reliability, 4),
    })
    return score, "assessed", evidence


def _weak_projection(state: Mapping[str, Any]) -> tuple[list[WeakKnowledge], list[str]]:
    weak: list[WeakKnowledge] = []
    blind_spots: list[str] = []
    mastery_mapping = {
        "unmastered": MasteryType.UNMASTERED,
        "confused": MasteryType.CONFUSED,
        "partial_mastery": MasteryType.PARTIAL_MASTERY,
    }
    for item in (state.get("items") or {}).values():
        status = str(item["status"])
        confidence = float(item["confidence"])
        if status not in mastery_mapping or confidence < WEAK_PROJECTION_CONFIDENCE:
            continue
        mastery = float(item["mastery_score"])
        weak.append(
            WeakKnowledge(
                knowledge_id=str(item["knowledge_id"]),
                name=str(item["name"]),
                category=str(item["category"]),
                weakness_level=max(1, min(5, round((1 - mastery) * 5))),
                mastery_type=mastery_mapping[status],
                prerequisite_ids=list(item.get("prerequisite_ids") or []),
                evidence_ids=list(item.get("evidence_ids") or [])[-20:],
                reason="累计正式证据识别的知识状态",
            )
        )
        if status == "unmastered" and confidence >= BLIND_SPOT_CONFIDENCE:
            blind_spots.append(str(item["knowledge_id"]))
    return sorted(weak, key=lambda value: (-value.weakness_level, value.knowledge_id)), blind_spots


def project_analysis_with_knowledge_state(
    *,
    analysis: AnalyzeProfileOutput,
    state: Mapping[str, Any],
    previous_state: Mapping[str, Any] | None,
    config: ProfileAnalysisConfig,
    context: Mapping[str, Any],
) -> tuple[AnalyzeProfileOutput, dict[str, Any]]:
    """Project cumulative evidence only after a material confirmation threshold.

    The Agent output remains V10-compatible.  This service owns the later
    evidence policy, keeping observed interaction signals out of confirmed
    profile state and preventing a new profile version for every answer.
    """

    accepted_ids = set(state.get("accepted_evidence_ids") or [])
    if not accepted_ids:
        return analysis.model_copy(
            update={
                "profile": analysis.profile.model_copy(update={"profile_version": max(1, analysis.profile.profile_version - int(analysis.profile_update_required))}),
                "profile_update_required": False,
                "changed_dimensions": [],
                "evidence_refs": [],
                "confidence": 0.0,
                "decision_reason": "缺少足够的已确认正式评估证据",
                "affected_scope": analysis.affected_scope.model_copy(update={"knowledge_ids": [], "path_node_ids": [], "resource_ids": []}),
            }
        ), {"dimension_status": {}, "profile_type": analysis.profile.profile_type.value}

    abilities, dimension_status, learning_speed_evidence = _ability_scores(
        state=state,
        previous_state=previous_state,
        config=config,
        context=context,
    )
    weak, blind_spots = _weak_projection(state)
    old_items = _previous_items(previous_state)
    new_core_ids = set(str(value) for value in state.get("accepted_core_knowledge_ids") or [])
    changed_knowledge_ids = {
        knowledge_id
        for knowledge_id, item in (state.get("items") or {}).items()
        if knowledge_id in new_core_ids
        and len(set(item.get("core_question_ids") or [])) >= config.knowledge_min_distinct_questions
        and float(item.get("core_effective_weight") or 0) >= config.knowledge_min_effective_weight
        and (
            str(item.get("status")) != str((old_items.get(knowledge_id) or {}).get("status"))
            or abs(float(item.get("mastery_score") or 0.5) - float((old_items.get(knowledge_id) or {}).get("mastery_score") or 0.5)) >= 0.05
        )
    }
    initial_batch = (
        not old_items
        and len(accepted_ids) >= config.initial_diagnostic_min_answers
        and all(
            item.evidence_type == EvidenceType.DIAGNOSTIC_RESULT
            for item in analysis.evidence_refs
            if item.evidence_id in accepted_ids
        )
    )

    before_scores = analysis.profile.ability_scores
    score_values = abilities.model_dump()
    confirmed_values = before_scores.model_dump()
    changed_ability_dimensions: list[str] = []
    for dimension in ("theory", "practice", "problem_solving", "learning_speed"):
        if (
            len(new_core_ids) >= config.ability_min_new_knowledge
            and dimension_status.get(dimension) == "assessed"
            and abs(int(score_values[dimension]) - int(confirmed_values[dimension])) >= config.ability_min_score_delta
        ):
            confirmed_values[dimension] = score_values[dimension]
            changed_ability_dimensions.append(dimension)

    newly_assessed = {
        knowledge_id
        for knowledge_id, item in (state.get("items") or {}).items()
        if knowledge_id in new_core_ids
        and str(item.get("status")) != "unassessed"
        and str((old_items.get(knowledge_id) or {}).get("status") or "unassessed") == "unassessed"
    }
    old_categories = {
        str(item.get("category"))
        for item in old_items.values()
        if str(item.get("status")) != "unassessed"
    }
    new_categories = {
        str((state.get("items") or {}).get(knowledge_id, {}).get("category"))
        for knowledge_id in newly_assessed
    } - old_categories
    breadth_confirmed = (
        len(newly_assessed) >= config.breadth_min_new_knowledge or bool(new_categories)
    )
    if breadth_confirmed:
        confirmed_values["knowledge_breadth"] = score_values["knowledge_breadth"]
        changed_ability_dimensions.append("knowledge_breadth")
    confirmed_abilities = AbilityScores(**confirmed_values)
    supported = [
        getattr(confirmed_abilities, key)
        for key in ("theory", "practice", "problem_solving", "knowledge_breadth", "learning_speed")
        if dimension_status.get(key) not in {"insufficient_evidence", "insufficient_longitudinal_evidence"}
    ]
    average = sum(supported) / len(supported) if supported else 0
    profile_type = (
        ProfileType.PRACTICE_ORIENTED
        if confirmed_abilities.practice >= confirmed_abilities.theory + 10 and confirmed_abilities.practice >= 60
        else ProfileType.ADVANCED
        if average >= 85
        else ProfileType.INTERMEDIATE
        if average >= 60
        else ProfileType.BEGINNER
    )
    before = analysis.profile
    profile = ProfileSnapshot(
        profile_id=before.profile_id,
        profile_version=before.profile_version,
        profile_type=profile_type,
        ability_scores=confirmed_abilities,
        weak_knowledge=weak,
        blind_spot_ids=blind_spots,
    )
    evidence_refs = [item for item in analysis.evidence_refs if item.evidence_id in accepted_ids]
    changed_dimensions = []
    if changed_knowledge_ids or initial_batch:
        changed_dimensions.append("knowledge_state")
    if changed_ability_dimensions:
        changed_dimensions.append("ability_scores")
    if (weak != before.weak_knowledge) and (changed_knowledge_ids or initial_batch):
        changed_dimensions.append("weak_knowledge")
    if blind_spots != before.blind_spot_ids and (changed_knowledge_ids or initial_batch):
        changed_dimensions.append("blind_spot_ids")
    if profile_type != before.profile_type and (changed_ability_dimensions or initial_batch):
        changed_dimensions.append("profile_type")
    confidence = round(
        sum(float(item["confidence"]) for item in (state.get("items") or {}).values())
        / max(1, int(state["coverage"]["assessed_count"])),
        3,
    )
    profile_update_required = bool(initial_batch or changed_knowledge_ids or changed_ability_dimensions)
    if not profile_update_required:
        # Do not expose unconfirmed state as a changed profile.  It remains in
        # the private cumulative payload and becomes visible after independent
        # formal corroboration.
        profile = before
        changed_dimensions = []
    normalized = AnalyzeProfileOutput.model_validate(
        analysis.model_copy(
            update={
                "profile": profile,
                "profile_update_required": profile_update_required,
                "changed_dimensions": changed_dimensions,
                "evidence_refs": evidence_refs,
                "confidence": confidence,
                "decision_reason": (
                    "初始诊断已形成画像"
                    if initial_batch
                    else "已根据累计独立正式证据更新学情画像"
                    if profile_update_required
                    else "正式证据已累计，尚不足以调整画像"
                ),
            }
        ).model_dump(mode="python")
    )
    return normalized, {
        "dimension_status": dimension_status,
        "profile_type": profile_type.value,
        "learning_speed_evidence": learning_speed_evidence,
        "evidence_status": (
            "confirmed" if profile_update_required else "accumulating"
        ),
        "changed_knowledge_ids": sorted(changed_knowledge_ids),
        "new_core_knowledge_ids": sorted(new_core_ids),
    }


def public_knowledge_state(state: Mapping[str, Any] | None, *, derived_legacy: bool = False) -> dict[str, Any]:
    """Return a privacy-safe report projection without posterior accumulator details."""

    if not isinstance(state, Mapping) or state.get("version") not in {
        STATE_VERSION,
        LEGACY_STATE_VERSION,
    }:
        return {
            "version": STATE_VERSION,
            "derived_legacy": True,
            "knowledge_states": [],
            "status_counts": {},
            "coverage": {},
        }
    return {
        "version": STATE_VERSION,
        "derived_legacy": derived_legacy,
        "knowledge_states": [
            {
                key: item.get(key)
                for key in (
                    "knowledge_id",
                    "name",
                    "category",
                    "status",
                    "mastery_score",
                    "confidence",
                    "evidence_count",
                    "last_assessed_at",
                    "confusion_tags",
                    "prerequisite_ids",
                )
            }
            for item in (state.get("items") or {}).values()
        ],
        "status_counts": dict(state.get("status_counts") or {}),
        "coverage": dict(state.get("coverage") or {}),
    }
