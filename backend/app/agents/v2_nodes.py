"""V2 LangGraph node adapters.

The V2 state only carries contract models. Database sessions, model clients and
retrieval clients live in ``V2Runtime`` and are captured by node closures.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from langgraph.types import interrupt

from app.agents.contract_adapters import (
    analyze_profile_output_to_patch,
    build_analyze_profile_input,
    build_finalize_task_input,
    build_generate_resource_input,
    build_human_review_input,
    build_interpret_feedback_input,
    build_prepare_task_input,
    build_retrieve_knowledge_input,
    build_review_resource_input,
    finalize_task_output_to_patch,
    generate_resource_output_to_patch,
    human_review_output_to_patch,
    interpret_feedback_output_to_patch,
    prepare_task_output_to_patch,
    retrieve_knowledge_output_to_patch,
    review_resource_output_to_patch,
    render_resource_markdown,
)
from app.agents.contracts import HumanDecision, HumanReviewInput
from app.agents.state import AgentGraphState
from app.agents.v2_generation_agent import V2ContentGenerationAgent
from app.agents.v2_orchestrator_agent import (
    HumanReviewSubmission,
    V2OrchestratorAgent,
)
from app.agents.v2_profile_analysis_agent import V2ProfileAnalysisAgent
from app.agents.v2_retrieval_agent import V2KnowledgeRetrievalAgent
from app.agents.v2_review_agent import TaskScopedV2ArbitrationRetriever, V2ReviewValidationAgent
from app.agents.v2_tutoring_agent import V2TutoringAgent


NodeFunc = Callable[[AgentGraphState], AgentGraphState]
V2_GRAPH_STATE = AgentGraphState


class InterruptHumanReviewProvider:
    """Bridge a LangGraph interrupt/resume value to the V2 human-review contract."""

    def get_submission(self, request: HumanReviewInput) -> HumanReviewSubmission:
        resumed = interrupt(
            {
                "task_id": request.task_id,
                "status": "waiting_human",
                "allowed_decisions": [item.value for item in request.allowed_decisions],
            }
        )
        if isinstance(resumed, str):
            payload: dict[str, Any] = {"decision": resumed}
        elif isinstance(resumed, dict):
            payload = dict(resumed)
        else:
            raise ValueError("human_review_resume_payload_invalid")
        payload.setdefault("review_comment", "管理员已处理人工复核任务。")
        payload.setdefault("operator_id", "admin")
        payload.setdefault("reviewed_at", datetime.now(UTC))
        return HumanReviewSubmission.model_validate(payload)


@dataclass
class V2Runtime:
    profile_agent: V2ProfileAnalysisAgent
    tutoring_agent: V2TutoringAgent
    retrieval_agent_factory: Callable[[], V2KnowledgeRetrievalAgent]
    generation_agent: V2ContentGenerationAgent
    review_agent_factory: Callable[[TaskScopedV2ArbitrationRetriever], V2ReviewValidationAgent]
    orchestrator: V2OrchestratorAgent
    _retrieval_agent: V2KnowledgeRetrievalAgent | None = None

    @classmethod
    def production(cls) -> "V2Runtime":
        return cls(
            profile_agent=V2ProfileAnalysisAgent(),
            tutoring_agent=V2TutoringAgent(),
            retrieval_agent_factory=V2KnowledgeRetrievalAgent.production,
            # Rendering is a composition concern.  The V2 generator only
            # receives this deterministic callable and never imports adapters.
            generation_agent=V2ContentGenerationAgent(renderer=render_resource_markdown),
            review_agent_factory=lambda evidence_retriever: V2ReviewValidationAgent(
                evidence_retriever=evidence_retriever
            ),
            orchestrator=V2OrchestratorAgent(
                human_review_provider=InterruptHumanReviewProvider()
            ),
        )

    def close(self) -> None:
        if self._retrieval_agent is not None:
            self._retrieval_agent.close()

    def retrieval_agent(self) -> V2KnowledgeRetrievalAgent:
        if self._retrieval_agent is None:
            self._retrieval_agent = self.retrieval_agent_factory()
        return self._retrieval_agent


def build_nodes(runtime: V2Runtime) -> dict[str, NodeFunc]:
    def active_revision_plan(state: AgentGraphState):
        """Read the last orchestrator decision without adding mutable V2 State.

        ``revision_plan`` is intentionally a task input field, not owned by a
        node patch.  After a finalize decision, its V2 output is therefore the
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
            runtime.profile_agent.execute(build_analyze_profile_input(state))
        )

    def retrieve_knowledge(state: AgentGraphState) -> AgentGraphState:
        node_input = build_retrieve_knowledge_input(state)
        revision_plan = active_revision_plan(state)
        if revision_plan is not None:
            node_input = node_input.model_copy(update={"revision_plan": revision_plan})
        return retrieve_knowledge_output_to_patch(
            runtime.retrieval_agent().execute(node_input)
        )

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
        return generate_resource_output_to_patch(
            node_input, runtime.generation_agent.execute(node_input)
        )

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
        evidence_retriever = TaskScopedV2ArbitrationRetriever(
            retrieval_agent=runtime.retrieval_agent(),
            original_request=build_retrieve_knowledge_input(state),
        )
        agent = runtime.review_agent_factory(evidence_retriever)
        return review_resource_output_to_patch(node_input, agent.execute(node_input))

    def finalize_task(state: AgentGraphState) -> AgentGraphState:
        node_input = build_finalize_task_input(state)
        previous = state.get("finalize_task")
        if previous is not None:
            node_input = node_input.model_copy(
                update={"revision_count": max(node_input.revision_count, previous.revision_count)}
            )
        return finalize_task_output_to_patch(
            runtime.orchestrator.execute(node_input)
        )

    def human_review(state: AgentGraphState) -> AgentGraphState:
        return human_review_output_to_patch(
            runtime.orchestrator.execute(build_human_review_input(state))
        )

    return {
        "prepare_task": prepare_task,
        "interpret_feedback": interpret_feedback,
        "analyze_profile": analyze_profile,
        "retrieve_knowledge": retrieve_knowledge,
        "generate_resource": generate_resource,
        "review_resource": review_resource,
        "finalize_task": finalize_task,
        "human_review": human_review,
    }


def route_after_prepare(state: AgentGraphState) -> str:
    return state["prepare_task"].next_node


def route_after_profile(state: AgentGraphState) -> str:
    return "retrieve_knowledge" if state["analyze_profile"].needs_generation else "finalize_task"


def route_after_finalize(state: AgentGraphState) -> str:
    decision = state["finalize_task"].decision.value
    if decision == "revision_required":
        return "retrieve_knowledge"
    if decision == "manual_review_required":
        return "human_review"
    return "end"


def route_after_human_review(state: AgentGraphState) -> str:
    decision = state["human_review"].decision
    return "retrieve_knowledge" if decision == HumanDecision.REQUEST_REVISION else "finalize_task"
