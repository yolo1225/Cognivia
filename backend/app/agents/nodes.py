"""V3 LangGraph node adapters.

The V3 state only carries contract models. Database sessions, model clients and
retrieval clients live in ``AgentRuntime`` and are captured by node closures.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

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
    RetrieveKnowledgeOutput,
    ReviewResourceInput,
)
from app.agents.state import AgentGraphState
from app.agents.generation_agent import ContentGenerationAgent
from app.agents.orchestrator_agent import OrchestratorAgent
from app.agents.profile_analysis_agent import ProfileAnalysisAgent
from app.agents.retrieval_agent import KnowledgeRetrievalAgent
from app.agents.review_agent import (
    ReviewBatchCache,
    ReviewValidationAgent,
    TaskScopedArbitrationRetriever,
    build_review_resource_output,
)
from app.agents.tutoring_agent import TutoringAgent


NodeFunc = Callable[[AgentGraphState], AgentGraphState]
GRAPH_STATE = AgentGraphState


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
        cls, review_batch_cache: ReviewBatchCache | None = None
    ) -> "AgentRuntime":
        cache = review_batch_cache or ReviewBatchCache()
        return cls(
            profile_agent=ProfileAnalysisAgent(),
            tutoring_agent=TutoringAgent(),
            retrieval_agent_factory=KnowledgeRetrievalAgent.production,
            # Rendering is a composition concern.  The V3 generator only
            # receives this deterministic callable and never imports adapters.
            generation_agent=ContentGenerationAgent(renderer=render_resource_markdown),
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
    chunks = [
        chunk for chunk in node_input.retrieved_chunks if chunk.knowledge_id in target_ids
    ]
    source_ids = [chunk.source.source_ref_id for chunk in chunks]
    requirements = requirements.model_copy(update={"source_whitelist": source_ids})
    return node_input.model_copy(
        update={"retrieved_chunks": chunks, "requirements": requirements}
    )


def _partial_review_input(
    node_input: ReviewResourceInput,
    resource_types: list[ResourceType],
) -> ReviewResourceInput:
    requirements = _partial_requirements(node_input.requirements, resource_types)
    resources = [
        resource
        for resource in node_input.resources
        if resource.resource_type in resource_types
    ]
    cited = {
        source.source_ref_id for resource in resources for source in resource.source_refs
    }
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
        return prepare_task_output_to_patch(runtime.orchestrator.execute(build_prepare_task_input(state)))

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
            cited_source_ids = {
                source.source_ref_id
                for resource in (generated.resources if generated is not None else [])
                if resource.resource_type in active_types
                for source in resource.source_refs
            }
            chunks = [
                chunk
                for chunk in previous.chunks
                if chunk.source.source_ref_id in cited_source_ids
            ]
            known = {chunk.source.source_ref_id for chunk in chunks}
            chunks.extend(
                chunk for chunk in fresh.chunks if chunk.source.source_ref_id not in known
            )
            known = {chunk.source.source_ref_id for chunk in chunks}
            chunks.extend(
                chunk
                for chunk in previous.chunks
                if chunk.source.source_ref_id not in known
            )
            chunks = chunks[:12]
            covered = list(
                dict.fromkeys([*fresh.covered_knowledge_ids, *previous.covered_knowledge_ids])
            )
            fresh = RetrieveKnowledgeOutput(
                task_id=fresh.task_id,
                query_text=fresh.query_text,
                chunks=chunks,
                covered_knowledge_ids=covered,
                missing_knowledge_ids=[
                    item for item in fresh.missing_knowledge_ids if item not in covered
                ],
                warnings=list(dict.fromkeys([*fresh.warnings, *previous.warnings])),
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
            changed = runtime.generation_agent.revise(
                partial_input,
                [previous_by_type[item] for item in active_types],
                _audited_revision_claims(state),
            )
            changed_by_type = {item.resource_type: item for item in changed.resources}
            output = GenerateResourceOutput(
                task_id=node_input.task_id,
                resources=[
                    changed_by_type.get(item, previous_by_type[item])
                    for item in node_input.requirements.resource_types
                ],
            )
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
        return finalize_task_output_to_patch(
            runtime.orchestrator.execute(node_input)
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
