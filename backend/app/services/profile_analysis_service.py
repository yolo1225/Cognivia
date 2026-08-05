"""Pure deterministic implementation for V2 profile-analysis decisions."""

from __future__ import annotations

from collections import defaultdict
from statistics import fmean

from app.agents.contracts import (
    AffectedScope,
    AnalyzeProfileInput,
    AnalyzeProfileOutput,
    AbilityScores,
    EvidenceRef,
    EvidenceType,
    GenerationStrategy,
    KnowledgeAssessment,
    MasteryType,
    ProfileSnapshot,
    ProfileType,
    RecommendedAction,
    RetrievalPlan,
    WeakKnowledge,
)
from app.agents.profile_analysis_config import AI_APP_DEV_PROFILE_V1, ProfileAnalysisConfig


class ProfileAnalysisError(ValueError):
    """A controlled semantic error that must not fall back to an LLM."""


def analyze_profile(
    node_input: AnalyzeProfileInput,
    config: ProfileAnalysisConfig = AI_APP_DEV_PROFILE_V1,
) -> AnalyzeProfileOutput:
    if node_input.task_id != node_input.context.task_id:
        raise ProfileAnalysisError("task_id_context_mismatch")

    catalog = config.knowledge_catalog
    evidence = _deduplicate_evidence(node_input)
    assessments = _effective_assessments(node_input, evidence)
    action = node_input.recommended_action

    if _update_allowed(action, assessments):
        profile, changed_dimensions, changed_knowledge_ids, masteries = _updated_profile(
            node_input.current_profile, assessments, catalog, config
        )
    else:
        profile = node_input.current_profile
        changed_dimensions = []
        changed_knowledge_ids = []
        masteries = {}

    profile_update_required = bool(changed_dimensions)
    if not profile_update_required:
        profile = node_input.current_profile

    selected_evidence = _selected_evidence(evidence, assessments)
    needs_generation = _needs_generation(action, node_input.context.trigger_type.value)
    retrieval_plan = _build_retrieval_plan(
        profile=profile,
        context_goal=node_input.context.learning_goal,
        resource_types=node_input.context.resource_types,
        action=action,
        needs_generation=needs_generation,
        catalog=catalog,
        config=config,
        evidence_by_id={item.evidence_id: item for item in evidence},
        confirmed_high_mastery=any(
            mastery >= config.mastery_thresholds[2] for mastery in masteries.values()
        ),
    )
    affected_scope = _affected_scope(changed_knowledge_ids, catalog)
    reason = _decision_reason(action, profile_update_required, bool(assessments))
    confidence = (
        round(fmean([item.confidence for item in selected_evidence]), 3)
        if selected_evidence
        else 0.0
    )

    return AnalyzeProfileOutput(
        task_id=node_input.task_id,
        profile=profile,
        profile_update_required=profile_update_required,
        changed_dimensions=changed_dimensions,
        evidence_refs=selected_evidence,
        confidence=confidence,
        decision_reason=reason,
        affected_scope=affected_scope,
        retrieval_plan=retrieval_plan,
        needs_generation=needs_generation,
    )


def _deduplicate_evidence(node_input: AnalyzeProfileInput) -> list[EvidenceRef]:
    source = [*node_input.feedback_evidence]
    if node_input.diagnostic_summary:
        source.extend(node_input.diagnostic_summary.evidence)
    deduplicated: dict[str, EvidenceRef] = {}
    for item in source:
        existing = deduplicated.get(item.evidence_id)
        if existing is None:
            deduplicated[item.evidence_id] = item
        elif existing.model_dump(mode="json") != item.model_dump(mode="json"):
            raise ProfileAnalysisError("evidence_id_conflict")
    return list(deduplicated.values())


def _effective_assessments(
    node_input: AnalyzeProfileInput, evidence: list[EvidenceRef]
) -> list[KnowledgeAssessment]:
    evidence_by_id = {item.evidence_id: item for item in evidence}
    allowed_types = {
        EvidenceType.DIAGNOSTIC_RESULT,
        EvidenceType.SCORED_QUIZ,
        EvidenceType.VALIDATED_BEHAVIOR,
        EvidenceType.MANUAL_REVIEW,
    }
    effective: list[KnowledgeAssessment] = []
    for assessment in node_input.knowledge_assessments:
        evidence_ref = evidence_by_id.get(assessment.evidence_id)
        if (
            assessment.attempted
            and assessment.score is not None
            and evidence_ref is not None
            and evidence_ref.confirmed
            and evidence_ref.evidence_type in allowed_types
        ):
            effective.append(assessment)
    return effective


def _update_allowed(
    action: RecommendedAction | None, assessments: list[KnowledgeAssessment]
) -> bool:
    if action in {
        RecommendedAction.ASK_FOLLOW_UP,
        RecommendedAction.NO_CHANGE,
        RecommendedAction.REVIEW,
    }:
        return False
    return bool(assessments)


def _updated_profile(
    profile: ProfileSnapshot,
    assessments: list[KnowledgeAssessment],
    catalog,
    config: ProfileAnalysisConfig,
) -> tuple[ProfileSnapshot, list[str], list[str], dict[str, float]]:
    by_knowledge: dict[str, list[KnowledgeAssessment]] = defaultdict(list)
    for assessment in assessments:
        if assessment.knowledge_id not in catalog:
            raise ProfileAnalysisError("unknown_knowledge_id")
        by_knowledge[assessment.knowledge_id].append(assessment)

    weak_by_id = {item.knowledge_id: item for item in profile.weak_knowledge}
    masteries = {
        knowledge_id: _calculate_mastery(items, weak_by_id.get(knowledge_id), config)
        for knowledge_id, items in by_knowledge.items()
    }
    updated_weak = dict(weak_by_id)
    changed_ids: list[str] = []

    for knowledge_id, mastery in masteries.items():
        current = updated_weak.get(knowledge_id)
        mastery_type = _mastery_type(mastery, config)
        if mastery_type is MasteryType.KNOWN:
            if current is not None:
                updated_weak.pop(knowledge_id)
                changed_ids.append(knowledge_id)
            continue

        metadata = catalog[knowledge_id]
        next_item = WeakKnowledge(
            knowledge_id=knowledge_id,
            name=metadata.name,
            category=metadata.category,
            weakness_level=_bounded_weakness_level(mastery, current, config),
            mastery_type=mastery_type,
            prerequisite_ids=list(metadata.prerequisite_ids),
            evidence_ids=[item.evidence_id for item in by_knowledge[knowledge_id]],
            reason="结构化诊断或计分测验证据",
        )
        if current != next_item:
            updated_weak[knowledge_id] = next_item
            changed_ids.append(knowledge_id)

    ability_scores, ability_changes = _updated_ability_scores(profile, masteries, config)
    blind_spot_ids = list(profile.blind_spot_ids)
    for knowledge_id, mastery in masteries.items():
        if mastery < config.mastery_thresholds[0] and knowledge_id not in blind_spot_ids:
            blind_spot_ids.append(knowledge_id)
            changed_ids.append(knowledge_id)
        elif mastery >= config.mastery_thresholds[0] and knowledge_id in blind_spot_ids:
            blind_spot_ids.remove(knowledge_id)
            changed_ids.append(knowledge_id)

    changed_dimensions = list(ability_changes)
    if updated_weak != weak_by_id:
        changed_dimensions.append("weak_knowledge")
    if blind_spot_ids != profile.blind_spot_ids:
        changed_dimensions.append("blind_spot_ids")

    profile_type = _profile_type(ability_scores, masteries, catalog, config)
    if profile_type != profile.profile_type:
        changed_dimensions.append("profile_type")
    if not changed_dimensions:
        return profile, [], [], masteries

    return (
        ProfileSnapshot(
            profile_id=profile.profile_id,
            profile_version=profile.profile_version + 1,
            profile_type=profile_type,
            ability_scores=ability_scores,
            weak_knowledge=sorted(
                updated_weak.values(), key=lambda item: (-item.weakness_level, item.knowledge_id)
            ),
            blind_spot_ids=blind_spot_ids,
        ),
        changed_dimensions,
        list(dict.fromkeys(changed_ids)),
        masteries,
    )


def _calculate_mastery(
    assessments: list[KnowledgeAssessment],
    current: WeakKnowledge | None,
    config: ProfileAnalysisConfig,
) -> float:
    baseline = _mastery_baseline(current, config)
    numerator = config.prior_weight * baseline
    denominator = config.prior_weight
    for assessment in assessments:
        weight = config.difficulty_weight(assessment.difficulty) * assessment.confidence
        numerator += assessment.score * weight
        denominator += weight
    return numerator / denominator


def _mastery_baseline(item: WeakKnowledge | None, config: ProfileAnalysisConfig) -> float:
    if item is None:
        return config.prior_mastery
    return config.mastery_baselines[item.mastery_type.value]


def _mastery_type(mastery: float, config: ProfileAnalysisConfig) -> MasteryType:
    low, middle, high = config.mastery_thresholds
    if mastery < low:
        return MasteryType.UNMASTERED
    if mastery < middle:
        return MasteryType.CONFUSED
    if mastery < high:
        return MasteryType.PARTIAL_MASTERY
    return MasteryType.KNOWN


def _bounded_weakness_level(
    mastery: float, current: WeakKnowledge | None, config: ProfileAnalysisConfig
) -> int:
    target = max(1, min(5, int((1 - mastery) * 5 + 0.5)))
    if current is None:
        return target
    return max(
        1,
        min(
            5,
            current.weakness_level
            + max(
                -config.max_weakness_level_change_per_update,
                min(config.max_weakness_level_change_per_update, target - current.weakness_level),
            ),
        ),
    )


def _updated_ability_scores(
    profile: ProfileSnapshot, masteries: dict[str, float], config: ProfileAnalysisConfig
) -> tuple[AbilityScores, list[str]]:
    current = profile.ability_scores.model_dump()
    next_scores = dict(current)
    changes: list[str] = []
    for dimension in ("theory", "practice", "problem_solving"):
        pairs = [
            (mastery, config.ability_weights[knowledge_id][dimension])
            for knowledge_id, mastery in masteries.items()
            if config.ability_weights[knowledge_id][dimension] > 0
        ]
        if not pairs:
            continue
        target = round(sum(mastery * weight for mastery, weight in pairs) / sum(weight for _, weight in pairs) * 100)
        delta = max(
            -config.max_ability_change_per_update,
            min(config.max_ability_change_per_update, target - current[dimension]),
        )
        if abs(delta) < config.minimum_effective_change:
            continue
        next_scores[dimension] = max(0, min(100, current[dimension] + delta))
        changes.append(f"ability_scores.{dimension}")

    # A single batch has no evidence of historical category coverage.  Preserve it.
    return AbilityScores(**next_scores), changes


def _profile_type(scores: AbilityScores, masteries: dict[str, float], catalog, config: ProfileAnalysisConfig) -> ProfileType:
    covered_categories = {catalog[knowledge_id].category for knowledge_id in masteries}
    if (
        len(covered_categories) >= config.minimum_category_coverage_for_practice_oriented
        and scores.practice - scores.theory >= 10
        and scores.practice >= 60
    ):
        return ProfileType.PRACTICE_ORIENTED
    average = fmean(scores.model_dump().values())
    if average < 60:
        return ProfileType.BEGINNER
    if average >= 85:
        return ProfileType.ADVANCED
    return ProfileType.INTERMEDIATE


def _needs_generation(action: RecommendedAction | None, trigger_type: str) -> bool:
    if action in {RecommendedAction.ASK_FOLLOW_UP, RecommendedAction.NO_CHANGE}:
        return False
    if action is RecommendedAction.EXPLAIN:
        return True
    return trigger_type == "initial_generation" or action in {
        RecommendedAction.CHALLENGE,
        RecommendedAction.REVIEW,
        RecommendedAction.REGENERATE,
    }


def _build_retrieval_plan(
    *,
    profile: ProfileSnapshot,
    context_goal: str,
    resource_types,
    action: RecommendedAction | None,
    needs_generation: bool,
    catalog,
    config: ProfileAnalysisConfig,
    evidence_by_id: dict[str, EvidenceRef],
    confirmed_high_mastery: bool,
) -> RetrievalPlan:
    weak = _prioritized_weak_knowledge(profile.weak_knowledge, context_goal, evidence_by_id)
    # An explicit, valid knowledge ID in a learner's goal is a scoped learning
    # request, not profile evidence.  It must be retrieved alongside the
    # personalized priority instead of being ignored merely because it is not
    # already listed as a historical weak point.
    requested_ids = [
        knowledge_id
        for knowledge_id in catalog
        if knowledge_id.casefold() in context_goal.casefold()
    ]
    if action is RecommendedAction.CHALLENGE and confirmed_high_mastery:
        strategy = GenerationStrategy.CHALLENGE
    elif weak and (
        weak[0].weakness_level >= 4
        or weak[0].mastery_type in {MasteryType.UNMASTERED, MasteryType.CONFUSED}
    ):
        strategy = GenerationStrategy.REMEDIAL
    else:
        strategy = GenerationStrategy.CONSOLIDATION

    priority_ids = (
        list(dict.fromkeys([*requested_ids, *(item.knowledge_id for item in weak)]))[:20]
        if needs_generation
        else []
    )
    prerequisite_ids: list[str] = []
    for item in weak:
        if item.knowledge_id not in priority_ids:
            continue
        for prerequisite_id in item.prerequisite_ids:
            if prerequisite_id not in priority_ids and prerequisite_id not in prerequisite_ids:
                prerequisite_ids.append(prerequisite_id)
                if len(prerequisite_ids) == 20:
                    break
        if len(prerequisite_ids) == 20:
            break
    if not needs_generation:
        prerequisite_ids = []

    relevant_score = _relevant_ability_score(profile, priority_ids, config)
    base = max(1, min(5, int(relevant_score / 20 + 0.5)))
    adjustment = {
        GenerationStrategy.REMEDIAL: -1,
        GenerationStrategy.CONSOLIDATION: 0,
        GenerationStrategy.CHALLENGE: 1,
    }[strategy]
    difficulty = max(1, min(5, base + adjustment))
    terms = [context_goal]
    for knowledge_id in priority_ids:
        metadata = catalog[knowledge_id]
        terms.extend([metadata.name, metadata.category])
    terms.extend(prerequisite_ids)
    terms.append(
        {
            GenerationStrategy.REMEDIAL: "补救解释",
            GenerationStrategy.CONSOLIDATION: "巩固练习",
            GenerationStrategy.CHALLENGE: "挑战任务",
        }[strategy]
    )
    query_terms = list(dict.fromkeys(term for term in terms if term))[:30] or ["ai_app_dev"]
    unique_resource_types = list(dict.fromkeys(resource_types))
    if action in {RecommendedAction.REVIEW, RecommendedAction.REGENERATE}:
        n_results = config.maximum_n_results
    elif strategy is GenerationStrategy.REMEDIAL and len(priority_ids) > 1:
        n_results = config.multi_priority_remedial_n_results
    else:
        n_results = config.default_n_results
    return RetrievalPlan(
        strategy=strategy,
        target_difficulty=difficulty,
        resource_types=unique_resource_types,
        priority_knowledge_ids=priority_ids,
        prerequisite_knowledge_ids=prerequisite_ids,
        query_terms=query_terms,
        n_results=n_results,
    )


def _prioritized_weak_knowledge(
    weak_knowledge: list[WeakKnowledge], context_goal: str, evidence_by_id: dict[str, EvidenceRef]
) -> list[WeakKnowledge]:
    normalized_goal = context_goal.casefold()

    def sort_key(item: WeakKnowledge) -> tuple[float, str]:
        confidence = max(
            (evidence_by_id[evidence_id].confidence for evidence_id in item.evidence_ids if evidence_id in evidence_by_id),
            default=0.0,
        )
        relevant = 1.0 if any(
            token and token.casefold() in normalized_goal
            for token in (item.knowledge_id, item.name, item.category)
        ) else 0.5
        return (-(item.weakness_level * confidence * relevant), item.knowledge_id)

    return sorted(weak_knowledge, key=sort_key)


def _relevant_ability_score(
    profile: ProfileSnapshot, priority_ids: list[str], config: ProfileAnalysisConfig
) -> int:
    if not priority_ids:
        return round(fmean(profile.ability_scores.model_dump().values()))
    weights = config.ability_weights[priority_ids[0]]
    dimension = max((key for key in ("theory", "practice", "problem_solving")), key=weights.get)
    return getattr(profile.ability_scores, dimension)


def _affected_scope(changed_ids: list[str], catalog) -> AffectedScope:
    knowledge_ids = list(changed_ids)
    for knowledge_id in changed_ids:
        for prerequisite_id in catalog[knowledge_id].prerequisite_ids:
            if prerequisite_id not in knowledge_ids:
                knowledge_ids.append(prerequisite_id)
    return AffectedScope(knowledge_ids=knowledge_ids, path_node_ids=[], resource_ids=[])


def _selected_evidence(
    evidence: list[EvidenceRef], assessments: list[KnowledgeAssessment]
) -> list[EvidenceRef]:
    assessment_ids = {item.evidence_id for item in assessments}
    return [item for item in evidence if item.evidence_id in assessment_ids] or evidence


def _decision_reason(action: RecommendedAction | None, updated: bool, has_assessment: bool) -> str:
    if action is RecommendedAction.REVIEW:
        return "资源复核不改变学习者画像"
    if action in {RecommendedAction.ASK_FOLLOW_UP, RecommendedAction.NO_CHANGE}:
        return "当前动作不允许更新画像"
    if not has_assessment:
        return "缺少可计算的已确认结构化评估"
    return "已根据已确认结构化评估更新画像" if updated else "变化未达到最小有效阈值"
