from app.agents.contract_adapters import (
    analyze_profile_output_to_patch,
    finalize_task_output_to_patch,
    generate_resource_output_to_patch,
    prepare_task_output_to_patch,
    retrieve_knowledge_output_to_patch,
    review_resource_output_to_patch,
)
from app.agents.contract_examples import initial_generation_flow_example
from app.agents.contracts import ReviewDecision
from app.agents.graphs import build_learning_graph


def test_v3_graph_executes_initial_generation_with_contract_owned_state() -> None:
    flow = initial_generation_flow_example()
    prepare = flow["prepare_task"]
    analyze = flow["analyze_profile"]
    retrieve = flow["retrieve_knowledge"]
    generate = flow["generate_resource"]
    review = flow["review_resource"]
    finalize = flow["finalize_task"]

    graph = build_learning_graph(
        {
            "prepare_task": lambda _state: prepare_task_output_to_patch(prepare["output"]),
            "analyze_profile": lambda _state: analyze_profile_output_to_patch(analyze["output"]),
            "retrieve_knowledge": lambda _state: retrieve_knowledge_output_to_patch(retrieve["output"]),
            "generate_resource": lambda _state: generate_resource_output_to_patch(
                generate["input"], generate["output"]
            ),
            "review_resource": lambda _state: review_resource_output_to_patch(
                review["input"], review["output"]
            ),
            "finalize_task": lambda _state: finalize_task_output_to_patch(finalize["output"]),
        }
    )

    state = graph.invoke(
        {
            "contract_version": "agent-contract-v3",
            "task_request": prepare["input"].request,
            "current_profile": analyze["input"].current_profile,
            "diagnostic_summary": analyze["input"].diagnostic_summary,
        }
    )

    assert state["finalize_task"].decision.value == "completed"
    assert state["review_resource"].reports[0].passed


def test_v3_graph_stops_after_two_revisions_using_prior_finalize_output() -> None:
    flow = initial_generation_flow_example()
    prepare = flow["prepare_task"]
    analyze = flow["analyze_profile"]
    retrieve = flow["retrieve_knowledge"]
    generate = flow["generate_resource"]
    review = flow["review_resource"]
    revision_report = review["output"].reports[0].model_copy(
        update={
                "decision": ReviewDecision.REVISION_REQUIRED,
                "passed": False,
                "quality_metrics": review["output"].reports[0].quality_metrics.model_copy(
                    update={
                        "evaluated_claim_count": 20,
                        "verifiable_claim_count": 20,
                        "contradicted_claim_count": 1,
                        "hallucinated_claim_count": 1,
                        "hallucination_rate": 5,
                        "passed": False,
                    }
                ),
        }
    )
    failed_package = review["output"].package_quality.model_copy(
        update={
            "evaluated_claim_count": 20,
            "verifiable_claim_count": 20,
            "contradicted_claim_count": 1,
            "hallucinated_claim_count": 1,
            "hallucination_rate": 5,
            "passed": False,
        }
    )
    revision_output = review["output"].model_copy(
        update={
            "reports": [revision_report, *review["output"].reports[1:]],
            "package_passed": False,
            "package_quality": failed_package,
        }
    )

    graph = build_learning_graph(
        {
            "prepare_task": lambda _state: prepare_task_output_to_patch(prepare["output"]),
            "analyze_profile": lambda _state: analyze_profile_output_to_patch(analyze["output"]),
            "retrieve_knowledge": lambda _state: retrieve_knowledge_output_to_patch(retrieve["output"]),
            "generate_resource": lambda _state: generate_resource_output_to_patch(
                generate["input"], generate["output"]
            ),
            "review_resource": lambda _state: review_resource_output_to_patch(
                review["input"], revision_output
            ),
        }
    )

    state = graph.invoke(
        {
            "contract_version": "agent-contract-v9",
            "task_request": prepare["input"].request,
            "current_profile": analyze["input"].current_profile,
            "diagnostic_summary": analyze["input"].diagnostic_summary,
        }
    )

    assert state["finalize_task"].decision.value == "failed"
    assert state["finalize_task"].revision_count == 2
