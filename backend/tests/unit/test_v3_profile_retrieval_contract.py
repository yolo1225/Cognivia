from __future__ import annotations

from app.agents.contracts import (
    AnalyzeProfileInput,
    RecommendedAction,
    RetrievalPurpose,
    RetrieveKnowledgeInput,
)
from app.agents.profile_analysis_agent import ProfileAnalysisAgent
from app.services.profile_v3_fixture_service import rendered_cases


PURPOSE_BY_STRATEGY = {
    "remedial": RetrievalPurpose.REMEDIAL_EXPLANATION,
    "consolidation": RetrievalPurpose.CONSOLIDATION_PRACTICE,
    "challenge": RetrievalPurpose.CHALLENGE_TASK,
}


def _to_retrieval_input(
    request: AnalyzeProfileInput,
    *,
    profile,
    retrieval_plan,
) -> RetrieveKnowledgeInput:
    purpose = (
        RetrievalPurpose.SOURCE_VERIFICATION
        if request.recommended_action is RecommendedAction.REVIEW
        else PURPOSE_BY_STRATEGY[retrieval_plan.strategy.value]
    )
    return RetrieveKnowledgeInput.model_validate(
        {
            "task_id": request.task_id,
            "context": request.context.model_dump(mode="python"),
            "profile": profile.model_dump(mode="python"),
            "retrieval_plan": retrieval_plan.model_dump(mode="python"),
            "purpose": purpose,
        }
    )


def test_profile_output_is_directly_consumable_by_v3_retrieval_contract() -> None:
    agent = ProfileAnalysisAgent()

    for case_id, payload, _ in rendered_cases():
        request = AnalyzeProfileInput.model_validate(payload)
        output = agent.execute(request)

        if not output.needs_generation:
            continue
        retrieval_input = _to_retrieval_input(
            request,
            profile=output.profile,
            retrieval_plan=output.retrieval_plan,
        )
        assert retrieval_input.task_id == request.task_id, case_id
        assert retrieval_input.context.task_id == request.context.task_id, case_id
        assert retrieval_input.context.contract_version == "agent-contract-v6", case_id
        assert retrieval_input.profile == output.profile, case_id
        assert retrieval_input.retrieval_plan == output.retrieval_plan, case_id


def test_no_generation_profile_output_does_not_create_retrieval_input() -> None:
    agent = ProfileAnalysisAgent()
    no_generation_task_ids: set[str] = set()
    constructed_task_ids: set[str] = set()

    for _, payload, _ in rendered_cases():
        request = AnalyzeProfileInput.model_validate(payload)
        output = agent.execute(request)
        if not output.needs_generation:
            no_generation_task_ids.add(request.task_id)
            continue
        retrieval_input = _to_retrieval_input(
            request,
            profile=output.profile,
            retrieval_plan=output.retrieval_plan,
        )
        constructed_task_ids.add(retrieval_input.task_id)

    assert no_generation_task_ids
    assert no_generation_task_ids.isdisjoint(constructed_task_ids)


def test_review_uses_source_verification_purpose() -> None:
    review_request = next(
        AnalyzeProfileInput.model_validate(payload)
        for _, payload, _ in rendered_cases()
        if payload.get("recommended_action") == RecommendedAction.REVIEW.value
    )
    output = ProfileAnalysisAgent().execute(review_request)
    retrieval_input = _to_retrieval_input(
        review_request,
        profile=output.profile,
        retrieval_plan=output.retrieval_plan,
    )

    assert retrieval_input.purpose is RetrievalPurpose.SOURCE_VERIFICATION
