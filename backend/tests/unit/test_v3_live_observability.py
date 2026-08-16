from __future__ import annotations

from pathlib import Path
import sys

from app.agents.contract_adapters import render_resource_markdown
from app.agents.contract_examples import initial_generation_flow_example
from app.agents.generation_agent import (
    OpenAICompatibleStructuredGenerator,
    ContentGenerationAgent,
)
from app.agents.observability import collect_model_calls
from app.agents.review_agent import OpenAICompatibleReviewChannel, ReviewValidationAgent
from app.models import AgentRun
from app.workers.generation_worker import _apply_model_call_metrics, _summary


class _Gateway:
    def complete_json(self, *, fixture_factory, **_kwargs):
        return fixture_factory(), {
            "provider_mode": "live",
            "model_name": "test-live-model",
            "tokens_input": 12,
            "tokens_output": 8,
            "duration_ms": 15,
        }


def test_v3_generation_and_review_collect_safe_model_call_metadata() -> None:
    flow = initial_generation_flow_example()
    generation = ContentGenerationAgent(
        generator=OpenAICompatibleStructuredGenerator(model_gateway=_Gateway()),
        renderer=render_resource_markdown,
    )
    with collect_model_calls() as collector:
        generation.execute(flow["generate_resource"]["input"])
    generation_calls = collector.snapshot()
    assert {item["resource_type"] for item in generation_calls} == {
        "lecture",
        "practice_guide",
        "graded_quiz",
    }
    assert len(generation_calls) == 3
    assert all(item["role"] == "generation_model" for item in generation_calls)
    assert all(item["provider_mode"] == "live" for item in generation_calls)

    review = ReviewValidationAgent(channel=OpenAICompatibleReviewChannel(_Gateway()))
    with collect_model_calls() as collector:
        review.execute(flow["review_resource"]["input"])
    review_calls = collector.snapshot()
    assert {item["role"] for item in review_calls} == {
        "primary_review_model",
        "secondary_review_model",
    }
    assert all(item["provider_mode"] == "live" for item in review_calls)
    assert {item["resource_type"] for item in review_calls} == {
        "lecture",
        "practice_guide",
        "graded_quiz",
    }
    assert all(item["estimated_input_tokens"] <= 10_000 for item in review_calls)
    assert all("truncated_evidence_count" in item for item in review_calls)


def test_v3_worker_summary_persists_safe_review_evidence_and_metrics() -> None:
    flow = initial_generation_flow_example()
    summary = _summary("review_resource", {"review_resource": flow["review_resource"]["output"]})
    assert summary["resource_reviews"]
    serialized = str(summary)
    assert "RAG 资源需保留来源标识" not in serialized
    assert "检索证据明确支持该声明" not in serialized
    assert "claim_id" in serialized
    run = AgentRun(agent_name="review_validation_agent", status="running")
    _apply_model_call_metrics(
        run,
        summary,
        [
            {
                "provider_mode": "live",
                "model_name": "review-a",
                "tokens_input": 3,
                "tokens_output": 2,
                "duration_ms": 4,
                "role": "primary_review_model",
            },
            {
                "provider_mode": "live",
                "model_name": "review-b",
                "tokens_input": 5,
                "tokens_output": 7,
                "duration_ms": 8,
                "role": "secondary_review_model",
            },
        ],
    )
    assert run.llm_calls == 2
    assert run.tokens_used == 17
    assert run.model_name == "review-a,review-b"
    assert summary["provider_mode"] == "live"


def test_live_runner_consumes_v3_review_summary_and_rejects_non_live_calls() -> None:
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "test_script"))
    import run_live

    flow = initial_generation_flow_example()
    summary = _summary("review_resource", {"review_resource": flow["review_resource"]["output"]})
    summary["model_calls"] = [
        {
            "provider_mode": "live",
            "model_name": "review-a",
            "tokens_input": 1,
            "tokens_output": 1,
            "duration_ms": 1,
            "role": "primary_review_model",
        }
    ]
    summary["provider_mode"] = "live"
    case = {
        "resource_type": "lecture",
        "target_difficulty": 2,
        "target_core_knowledge_ids": ["AIAPP-K029"],
    }
    task = {"decision": "completed", "resources": [{"resource_type": "lecture", "difficulty": 2}]}
    runs = [{"input_summary": {"step": "review_resource"}, "output_summary": summary, "duration_ms": 10}]
    observed = run_live._observed_result(case, task, runs, 10)
    assert observed["provider_mode"] == "live"
    assert observed["determinable"]
    assert observed["profile_decision"] == "not_evaluated"
    summary["model_calls"][0]["provider_mode"] = "fixture"
    assert not run_live._observed_result(case, task, runs, 10)["determinable"]


def test_live_runner_resolves_v3_source_reference_to_knowledge_id() -> None:
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "test_script"))
    import run_live

    case = {
        "resource_type": "lecture",
        "target_difficulty": 2,
        "target_core_knowledge_ids": ["ai_app_dev_overview"],
    }
    task = {"decision": "completed", "resources": [{"resource_type": "lecture", "difficulty": 2}]}
    runs = [
        {
            "input_summary": {"step": "analyze_profile"},
            "output_summary": {"profile_update_required": False},
            "duration_ms": 1,
        },
        {
            "input_summary": {"step": "review_resource"},
            "output_summary": {
                "model_calls": [{"provider_mode": "live"}],
                "resource_reviews": [
                    {
                        "resource_type": "lecture",
                        "decision": "passed",
                        "final_scores": {"difficulty_match": 100},
                        "evidence_ref_ids": ["ai_app_dev_overview::chunk::0"],
                        "primary_review": {"fact_checks": [{"supported": True, "source_ref_ids": ["ai_app_dev_overview::chunk::0"]}]},
                        "secondary_review": {"fact_checks": [{"supported": True, "source_ref_ids": ["ai_app_dev_overview::chunk::0"]}]},
                    }
                ],
            },
            "duration_ms": 1,
        },
    ]
    observed = run_live._observed_result(case, task, runs, 2)
    assert observed["covered_core_knowledge_count"] == 1
    assert observed["profile_decision"] == "no_change"
