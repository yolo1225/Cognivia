"""V3 LangGraph node adapters.

The V3 state only carries contract models. Database sessions, model clients and
retrieval clients live in ``AgentRuntime`` and are captured by node closures.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from threading import RLock

from app.agents.contract_adapters import (
    analyze_profile_output_to_patch,
    build_analyze_profile_input,
    build_finalize_task_input,
    build_generate_resource_input,
    build_interpret_feedback_input,
    build_prepare_task_input,
    build_retrieve_knowledge_input,
    build_review_resource_input,
    finalize_task_output_to_patch,
    generate_resource_output_to_patch,
    interpret_feedback_output_to_patch,
    prepare_task_output_to_patch,
    retrieve_knowledge_output_to_patch,
    review_resource_output_to_patch,
    render_resource_markdown,
)
from app.agents.contracts import (
    GenerateResourceInput,
    GenerateResourceOutput,
    GenerationRequirements,
    KnowledgeAssessment,
    ResourceType,
    RetrievedChunk,
    RetrieveKnowledgeOutput,
    ReviewResourceInput,
)
from app.agents.state import AgentGraphState
from app.agents.generation_agent import ContentGenerationAgent, GenerationError
from app.agents.claim_policy import RiskLevel
from app.agents.domain_evidence_policy import register_domain_evidence_capabilities
from app.agents.runtime_limits import MAX_EVIDENCE_CHUNKS
from app.agents.orchestrator_agent import (
    DETERMINISTIC_CONVERGENCE_MARKER,
    OrchestratorAgent,
)
from app.agents.profile_analysis_agent import ProfileAnalysisAgent
from app.agents.profile_analysis_config import MASTERY_BASELINES, ProfileAnalysisConfig
from app.agents.retrieval_agent import KnowledgeRetrievalAgent
from app.agents.review_agent import (
    ReviewBatchCache,
    ReviewError,
    ReviewValidationAgent,
    TaskScopedArbitrationRetriever,
    build_review_resource_output,
    extract_atomic_claims,
)
from app.services.question_bank_service import selected_graded_quiz_source_ref_ids
from app.agents.tutoring_agent import TutoringAgent


NodeFunc = Callable[[AgentGraphState], AgentGraphState]
GRAPH_STATE = AgentGraphState
_CONVERGENCE_AUDITS: dict[str, dict[str, object]] = {}
_CONVERGENCE_AUDITS_LOCK = RLock()


def pop_convergence_audit(task_id: str) -> dict[str, object] | None:
    with _CONVERGENCE_AUDITS_LOCK:
        return _CONVERGENCE_AUDITS.pop(task_id, None)


def _structural_profile_config() -> ProfileAnalysisConfig:
    """Graph-inspection runtime; production workers always inject a domain config."""
    return ProfileAnalysisConfig(
        version="structural_runtime",
        seed_sha256="none",
        prior_mastery=0.5,
        prior_weight=1.0,
        mastery_thresholds=(0.4, 0.6, 0.8),
        minimum_effective_change=5,
        max_ability_change_per_update=10,
        max_weakness_level_change_per_update=1,
        default_n_results=12,
        multi_priority_remedial_n_results=15,
        maximum_n_results=MAX_EVIDENCE_CHUNKS,
        ability_weights={},
        knowledge_catalog={},
        mastery_baselines=MASTERY_BASELINES,
    )


@dataclass
class AgentRuntime:
    profile_agent: ProfileAnalysisAgent
    tutoring_agent: TutoringAgent
    retrieval_agent_factory: Callable[[], KnowledgeRetrievalAgent]
    generation_agent: ContentGenerationAgent
    review_agent_factory: Callable[[TaskScopedArbitrationRetriever], ReviewValidationAgent]
    review_batch_cache: ReviewBatchCache
    orchestrator: OrchestratorAgent
    knowledge_assessments: list[KnowledgeAssessment] = field(default_factory=list)
    _retrieval_agent: KnowledgeRetrievalAgent | None = None

    @classmethod
    def production(
        cls,
        profile_config: ProfileAnalysisConfig | None = None,
        domain_code: str | None = None,
        domain_display_name: str | None = None,
        review_batch_cache: ReviewBatchCache | None = None,
        evidence_capabilities_by_knowledge: dict[str, list[str]] | None = None,
    ) -> "AgentRuntime":
        cache = review_batch_cache or ReviewBatchCache()
        if domain_code:
            register_domain_evidence_capabilities(
                domain_code,
                evidence_capabilities_by_knowledge or {},
            )
        return cls(
            profile_agent=ProfileAnalysisAgent(profile_config or _structural_profile_config()),
            tutoring_agent=TutoringAgent(domain_display_name=domain_display_name),
            retrieval_agent_factory=KnowledgeRetrievalAgent.production,
            # Rendering is a composition concern.  The V3 generator only
            # receives this deterministic callable and never imports adapters.
            generation_agent=ContentGenerationAgent(
                renderer=render_resource_markdown,
                evidence_capabilities_by_knowledge=evidence_capabilities_by_knowledge,
            ),
            review_agent_factory=lambda evidence_retriever: ReviewValidationAgent(
                evidence_retriever=evidence_retriever,
                batch_cache=cache,
            ),
            review_batch_cache=cache,
            orchestrator=OrchestratorAgent(),
        )

    def close(self) -> None:
        if self._retrieval_agent is not None:
            self._retrieval_agent.close()

    def retrieval_agent(self) -> KnowledgeRetrievalAgent:
        if self._retrieval_agent is None:
            self._retrieval_agent = self.retrieval_agent_factory()
        return self._retrieval_agent


def _partial_requirements(
    requirements: GenerationRequirements,
    resource_types: list[ResourceType],
) -> GenerationRequirements:
    targets = {
        resource_type: requirements.resource_knowledge_targets[resource_type]
        for resource_type in resource_types
    }
    required_ids = list(
        dict.fromkeys(
            knowledge_id
            for resource_type in resource_types
            for knowledge_id in targets[resource_type]
        )
    )
    return requirements.model_copy(
        update={
            "resource_types": resource_types,
            "required_knowledge_ids": required_ids,
            "resource_knowledge_targets": targets,
        }
    )


def _partial_generation_input(
    node_input: GenerateResourceInput,
    resource_types: list[ResourceType],
) -> GenerateResourceInput:
    requirements = _partial_requirements(node_input.requirements, resource_types)
    target_ids = set(requirements.required_knowledge_ids)
    partial_input = node_input.model_copy(update={"requirements": requirements})
    quiz_source_ids = (
        set(selected_graded_quiz_source_ref_ids(partial_input))
        if ResourceType.GRADED_QUIZ in resource_types
        else set()
    )
    chunks = [
        chunk
        for chunk in node_input.retrieved_chunks
        if chunk.knowledge_id in target_ids or chunk.source.source_ref_id in quiz_source_ids
    ]
    source_ids = [chunk.source.source_ref_id for chunk in chunks]
    requirements = requirements.model_copy(update={"source_whitelist": source_ids})
    return node_input.model_copy(update={"retrieved_chunks": chunks, "requirements": requirements})


def _partial_review_input(
    node_input: ReviewResourceInput,
    resource_types: list[ResourceType],
) -> ReviewResourceInput:
    requirements = _partial_requirements(node_input.requirements, resource_types)
    resources = [
        resource for resource in node_input.resources if resource.resource_type in resource_types
    ]
    cited = {source.source_ref_id for resource in resources for source in resource.source_refs}
    target_ids = set(requirements.required_knowledge_ids)
    evidence = [
        chunk
        for chunk in node_input.evidence
        if chunk.source.source_ref_id in cited or chunk.knowledge_id in target_ids
    ]
    requirements = requirements.model_copy(
        update={"source_whitelist": [chunk.source.source_ref_id for chunk in evidence]}
    )
    return ReviewResourceInput(
        task_id=node_input.task_id,
        context=node_input.context,
        resources=resources,
        requirements=requirements,
        evidence=evidence,
    )


def _merge_revision_retrieval(
    *,
    previous: RetrieveKnowledgeOutput,
    fresh: RetrieveKnowledgeOutput,
    generated: GenerateResourceOutput | None,
    active_types: set[ResourceType],
) -> RetrieveKnowledgeOutput:
    """Merge revision evidence without invalidating inherited resources.

    A partial revision publishes one package containing both revised and inherited
    artifacts.  Sources cited by inherited artifacts therefore remain part of the
    task-scoped evidence set even when the fresh retrieval ranking changes.
    """
    resources = generated.resources if generated is not None else []
    inherited_source_ids = {
        source.source_ref_id
        for resource in resources
        if resource.resource_type not in active_types
        for source in resource.source_refs
    }
    active_source_ids = {
        source.source_ref_id
        for resource in resources
        if resource.resource_type in active_types
        for source in resource.source_refs
    }
    previous_by_source = {
        chunk.source.source_ref_id: chunk for chunk in previous.chunks
    }

    # Inherited citations are immutable in this round and must be retained. Fresh
    # evidence comes next for the resources being revised; their old evidence is a
    # fallback only. Remaining previous chunks provide stable context when capacity
    # permits. Every accepted source still originated from a task retrieval round.
    ordered: list[RetrievedChunk] = []
    seen: set[str] = set()

    def extend(chunks: Iterable[RetrievedChunk]) -> None:
        for chunk in chunks:
            source_id = chunk.source.source_ref_id
            if source_id in seen or len(ordered) >= MAX_EVIDENCE_CHUNKS:
                continue
            ordered.append(chunk)
            seen.add(source_id)

    missing_inherited = inherited_source_ids - previous_by_source.keys()
    if missing_inherited:
        raise ValueError("inherited resource sources are missing from prior retrieval")
    extend(previous_by_source[source_id] for source_id in inherited_source_ids)
    extend(fresh.chunks)
    extend(
        previous_by_source[source_id]
        for source_id in active_source_ids
        if source_id in previous_by_source
    )
    extend(previous.chunks)

    if not inherited_source_ids.issubset(seen):
        raise ValueError("inherited resource sources exceed revision evidence capacity")
    covered = list(
        dict.fromkeys(
            [
                *fresh.covered_knowledge_ids,
                *(chunk.knowledge_id for chunk in ordered),
            ]
        )
    )
    return RetrieveKnowledgeOutput(
        task_id=fresh.task_id,
        query_text=fresh.query_text,
        chunks=ordered,
        covered_knowledge_ids=covered,
        missing_knowledge_ids=[
            item for item in fresh.missing_knowledge_ids if item not in covered
        ],
        warnings=list(dict.fromkeys([*fresh.warnings, *previous.warnings])),
        reference_questions=fresh.reference_questions or previous.reference_questions,
    )


def _audited_revision_claims(
    state: AgentGraphState,
) -> dict[ResourceType, dict[str, list[str]]]:
    previous = state.get("review_resource")
    if previous is None:
        return {}
    result: dict[ResourceType, dict[str, list[str]]] = {}
    for report in previous.reports:
        affected = {
            *report.contradicted_claim_ids,
            *report.undetermined_claim_ids,
            *report.unresolved_claim_ids,
        }
        by_path: dict[str, list[str]] = {}
        reviews = [report.primary_review, report.secondary_review]
        if report.arbitration.primary_recheck is not None:
            reviews.append(report.arbitration.primary_recheck)
        if report.arbitration.secondary_recheck is not None:
            reviews.append(report.arbitration.secondary_recheck)
        for review in reviews:
            for check in review.fact_checks:
                if check.claim_id in affected and check.field_path and check.claim:
                    by_path.setdefault(check.field_path, []).append(check.claim)
        if by_path:
            result[report.resource_type] = by_path
    return result


def _safe_convergence_claims(
    state: AgentGraphState,
) -> dict[ResourceType, dict[str, list[str]]]:
    """Select only removable low/normal-risk unresolved facts from the final review."""
    reviewed = state.get("review_resource")
    generated = state.get("generate_resource")
    if reviewed is None or generated is None:
        return {}
    request = build_review_resource_input(state)
    resources = {resource.resource_type: resource for resource in generated.resources}
    result: dict[ResourceType, dict[str, list[str]]] = {}
    removed_claim_ids: list[str] = []
    removed_field_paths: list[str] = []
    category_counts: Counter[str] = Counter()
    coverage_before: dict[str, float] = {}
    for report in reviewed.reports:
        if (
            report.contradicted_claim_ids
            or report.missing_knowledge_ids
            or report.final_scores.difficulty_match < 85
            or report.final_scores.core_knowledge_coverage < 90
        ):
            continue
        resource = resources.get(report.resource_type)
        if resource is None:
            continue
        candidate_ids = (
            set(report.undetermined_claim_ids) | set(report.unresolved_claim_ids)
        ) - set(report.contradicted_claim_ids)
        canonical = extract_atomic_claims(resource, request)
        category_counts.update(claim.category.value for claim in canonical)
        claims_per_knowledge: Counter[str] = Counter(
            knowledge_id
            for claim in canonical
            for knowledge_id in set(claim.knowledge_ids)
        )
        by_path: dict[str, list[str]] = {}
        for claim in canonical:
            if claim.claim_id not in candidate_ids or claim.risk_level is RiskLevel.HIGH:
                continue
            if any(
                claims_per_knowledge[knowledge_id] <= 1
                for knowledge_id in claim.knowledge_ids
                if knowledge_id in report.target_knowledge_ids
            ):
                continue
            by_path.setdefault(claim.field_path, []).append(claim.claim)
            removed_claim_ids.append(claim.claim_id)
            removed_field_paths.append(claim.field_path)
        if by_path:
            result[report.resource_type] = by_path
            coverage_before[report.resource_type.value] = (
                report.final_scores.core_knowledge_coverage
            )
    with _CONVERGENCE_AUDITS_LOCK:
        _CONVERGENCE_AUDITS[request.task_id] = {
            "removed_claim_ids": sorted(set(removed_claim_ids)),
            "removed_field_paths": sorted(set(removed_field_paths)),
            "category_counts": dict(sorted(category_counts.items())),
            "coverage_before": coverage_before,
        }
    return result


def build_nodes(runtime: AgentRuntime) -> dict[str, NodeFunc]:
    def active_revision_plan(state: AgentGraphState):
        """Read the last orchestrator decision without adding mutable V3 State.

        ``revision_plan`` is intentionally a task input field, not owned by a
        node patch.  After a finalize decision, its V3 output is therefore the
        authoritative source for the next retrieval/generation/review inputs.
        """
        previous = state.get("finalize_task")
        if previous is not None and previous.revision_plan is not None:
            return previous.revision_plan
        return state.get("revision_plan")

    def prepare_task(state: AgentGraphState) -> AgentGraphState:
        return prepare_task_output_to_patch(
            runtime.orchestrator.execute(build_prepare_task_input(state))
        )

    def interpret_feedback(state: AgentGraphState) -> AgentGraphState:
        return interpret_feedback_output_to_patch(
            runtime.tutoring_agent.execute(build_interpret_feedback_input(state))
        )

    def analyze_profile(state: AgentGraphState) -> AgentGraphState:
        return analyze_profile_output_to_patch(
            runtime.profile_agent.execute(
                build_analyze_profile_input(
                    state, knowledge_assessments=runtime.knowledge_assessments
                )
            )
        )

    def retrieve_knowledge(state: AgentGraphState) -> AgentGraphState:
        node_input = build_retrieve_knowledge_input(state)
        revision_plan = active_revision_plan(state)
        if revision_plan is not None:
            node_input = node_input.model_copy(update={"revision_plan": revision_plan})
        fresh = runtime.retrieval_agent().execute(node_input)
        previous = state.get("retrieve_knowledge")
        if revision_plan is not None and previous is not None:
            generated = state.get("generate_resource")
            active_types = set(revision_plan.resource_types)
            fresh = _merge_revision_retrieval(
                previous=previous,
                fresh=fresh,
                generated=generated,
                active_types=active_types,
            )
        return retrieve_knowledge_output_to_patch(fresh)

    def generate_resource(state: AgentGraphState) -> AgentGraphState:
        node_input = build_generate_resource_input(state)
        revision_plan = active_revision_plan(state)
        if revision_plan is not None:
            node_input = node_input.model_copy(
                update={
                    "requirements": node_input.requirements.model_copy(
                        update={"revision_plan": revision_plan}
                    )
                }
            )
        previous = state.get("generate_resource")
        if revision_plan is None or previous is None:
            output = runtime.generation_agent.execute(node_input)
        else:
            active_types = [
                item
                for item in node_input.requirements.resource_types
                if item in revision_plan.resource_types
            ]
            partial_input = _partial_generation_input(node_input, active_types)
            previous_by_type = {item.resource_type: item for item in previous.resources}
            convergence = DETERMINISTIC_CONVERGENCE_MARKER in revision_plan.required_changes
            changed = (
                runtime.generation_agent.converge(
                    partial_input,
                    [previous_by_type[item] for item in active_types],
                    _safe_convergence_claims(state),
                )
                if convergence
                else runtime.generation_agent.revise(
                    partial_input,
                    [previous_by_type[item] for item in active_types],
                    _audited_revision_claims(state),
                )
            )
            changed_by_type = {item.resource_type: item for item in changed.resources}
            output = GenerateResourceOutput(
                task_id=node_input.task_id,
                resources=[
                    changed_by_type.get(item, previous_by_type[item])
                    for item in node_input.requirements.resource_types
                ],
            )
        if revision_plan is not None:
            candidate_state = dict(state)
            candidate_state["generate_resource"] = output
            review_input = build_review_resource_input(candidate_state)
            review_input = review_input.model_copy(
                update={
                    "requirements": review_input.requirements.model_copy(
                        update={"revision_plan": revision_plan}
                    )
                }
            )
            for resource in output.resources:
                if resource.resource_type is not ResourceType.PRACTICE_GUIDE:
                    continue
                try:
                    extract_atomic_claims(resource, review_input)
                except ReviewError as exc:
                    if str(exc) != "review_claim_set_empty":
                        raise
                    raise GenerationError(
                        "revision_claim_set_empty_after_repair"
                    ) from exc
        return generate_resource_output_to_patch(node_input, output)

    def review_resource(state: AgentGraphState) -> AgentGraphState:
        node_input = build_review_resource_input(state)
        revision_plan = active_revision_plan(state)
        if revision_plan is not None:
            node_input = node_input.model_copy(
                update={
                    "requirements": node_input.requirements.model_copy(
                        update={"revision_plan": revision_plan}
                    )
                }
            )
        evidence_retriever = TaskScopedArbitrationRetriever(
            retrieval_agent=runtime.retrieval_agent(),
            original_request=build_retrieve_knowledge_input(state),
        )
        agent = runtime.review_agent_factory(evidence_retriever)
        previous = state.get("review_resource")
        if revision_plan is None or previous is None:
            output = agent.execute(node_input)
        else:
            active_types = [
                item
                for item in node_input.requirements.resource_types
                if item in revision_plan.resource_types
            ]
            partial_input = _partial_review_input(node_input, active_types)
            changed = agent.execute(partial_input)
            changed_by_type = {item.resource_type: item for item in changed.reports}
            previous_by_type = {item.resource_type: item for item in previous.reports}
            reports = [
                changed_by_type.get(item, previous_by_type[item])
                for item in node_input.requirements.resource_types
            ]
            output = build_review_resource_output(
                task_id=node_input.task_id,
                reports=reports,
                required_knowledge_ids=node_input.requirements.required_knowledge_ids,
                revision_count=revision_plan.revision_count,
            )
        return review_resource_output_to_patch(node_input, output)

    def finalize_task(state: AgentGraphState) -> AgentGraphState:
        node_input = build_finalize_task_input(state)
        previous = state.get("finalize_task")
        if previous is not None:
            node_input = node_input.model_copy(
                update={"revision_count": max(node_input.revision_count, previous.revision_count)}
            )
        revision_plan = active_revision_plan(state)
        if revision_plan is not None:
            node_input = node_input.model_copy(
                update={"revision_count": revision_plan.revision_count}
            )
        convergence_attempted = bool(
            revision_plan is not None
            and DETERMINISTIC_CONVERGENCE_MARKER in revision_plan.required_changes
        )
        return finalize_task_output_to_patch(
            runtime.orchestrator.execute(
                node_input,
                deterministic_convergence_attempted=convergence_attempted,
            )
        )

    return {
        "prepare_task": prepare_task,
        "interpret_feedback": interpret_feedback,
        "analyze_profile": analyze_profile,
        "retrieve_knowledge": retrieve_knowledge,
        "generate_resource": generate_resource,
        "review_resource": review_resource,
        "finalize_task": finalize_task,
    }


def route_after_prepare(state: AgentGraphState) -> str:
    return state["prepare_task"].next_node


def route_after_profile(state: AgentGraphState) -> str:
    return "retrieve_knowledge" if state["analyze_profile"].needs_generation else "finalize_task"


def route_after_finalize(state: AgentGraphState) -> str:
    decision = state["finalize_task"].decision.value
    if decision == "revision_required":
        return "retrieve_knowledge"
    return "end"
