from __future__ import annotations

from pathlib import Path
import sys

import pytest

from app.agents.contract_adapters import render_resource_markdown
from app.agents.contract_examples import initial_generation_flow_example
from app.agents.contracts import QuestionType, ResourceType, RetrievedQuestion
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


def test_live_stage_acceptance_uses_quality_gates_for_bounded_runs() -> None:
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "test_script"))
    import run_live

    summary = {
        "case_count": 6,
        "evaluated_case_count": 6,
        "metrics": {
            "hallucination_rate": {"ratio": 0.0},
            "evidence_insufficient_claims": {"count": 0},
            "unresolved_claims": {"count": 0},
            "difficulty_match_accuracy": {"ratio": 1.0},
            "core_knowledge_coverage": {"ratio": 1.0},
            "review_decision_accuracy": {"ratio": 1.0},
            "profile_decision_accuracy": {"ratio": 1.0},
        },
    }

    accepted = run_live._stage_acceptance(summary, 6)
    assert accepted["accepted"]
    summary["metrics"]["evidence_insufficient_claims"]["count"] = 1
    accepted_with_diagnostic = run_live._stage_acceptance(summary, 6)
    assert accepted_with_diagnostic["accepted"]
    assert accepted_with_diagnostic["failed_checks"] == []
    assert "no_evidence_insufficient" in accepted_with_diagnostic["diagnostic_findings"]


def test_live_prior_stage_requires_recorded_acceptance(tmp_path, monkeypatch) -> None:
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "test_script"))
    import run_live

    monkeypatch.setattr(run_live, "RUN_DIR", tmp_path)
    current = {
        "full_suite_case_sha256": "sha256:full-suite",
        "model_configuration": {"generation_model": "generation-a"},
        "knowledge_base_versions": ["kb-v4"],
        "rag_configuration": {"index_version": "index-v6"},
    }
    (tmp_path / "old-valid.json").write_text(
        '{"stage":"smoke","valid":true}', encoding="utf-8"
    )
    assert not run_live._prior_stage_exists("regression", **current)
    (tmp_path / "accepted.json").write_text(
        __import__("json").dumps(
            {
                "stage": "smoke",
                "valid": True,
                "stage_acceptance": {"accepted": True},
                **current,
            }
        ),
        encoding="utf-8",
    )
    assert run_live._prior_stage_exists("regression", **current)


def test_live_runner_resumes_only_matching_incomplete_checkpoint(
    tmp_path, monkeypatch
) -> None:
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "test_script"))
    import run_live

    monkeypatch.setattr(run_live, "RUN_DIR", tmp_path)
    run_id = "live-regression-20260818T120000Z"
    model_configuration = {
        "generation_model": "generation-a",
        "primary_review_model": "review-a",
        "secondary_review_model": "review-b",
        "fixture_enabled": False,
        "evaluation_overrides_enabled": True,
    }
    rag_configuration = {"index_version": "index-v6"}
    payload = {
        "run_id": run_id,
        "run_mode": "live",
        "stage": "regression",
        "diagnostic_case_id": None,
        "complete": False,
        "model_configuration": model_configuration,
        "knowledge_base_versions": ["kb-v4"],
        "rag_configuration": rag_configuration,
        "case_set_sha256": "sha256:regression",
        "full_suite_case_sha256": "sha256:full-suite",
        "results": [{"case_id": "V4-EVAL-001"}],
    }
    (tmp_path / f"{run_id}.json").write_text(
        __import__("json").dumps(payload), encoding="utf-8"
    )

    path, resumed = run_live._resume_run(
        run_id,
        stage="regression",
        diagnostic_case_id=None,
        selected_case_ids={"V4-EVAL-001", "V4-EVAL-002"},
        model_configuration=model_configuration,
        knowledge_base_versions=["kb-v4"],
        rag_configuration=rag_configuration,
        case_set_sha256="sha256:regression",
        full_suite_case_sha256="sha256:full-suite",
    )

    assert path == tmp_path / f"{run_id}.json"
    assert resumed["results"] == [{"case_id": "V4-EVAL-001"}]

    with pytest.raises(SystemExit, match="model_configuration"):
        run_live._resume_run(
            run_id,
            stage="regression",
            diagnostic_case_id=None,
            selected_case_ids={"V4-EVAL-001", "V4-EVAL-002"},
            model_configuration={**model_configuration, "generation_model": "generation-b"},
            knowledge_base_versions=["kb-v4"],
            rag_configuration=rag_configuration,
            case_set_sha256="sha256:regression",
            full_suite_case_sha256="sha256:full-suite",
        )


def test_v3_generation_and_review_collect_safe_model_call_metadata() -> None:
    flow = initial_generation_flow_example()
    request = flow["generate_resource"]["input"]
    target_id = request.requirements.resource_knowledge_targets[ResourceType.GRADED_QUIZ][0]
    source_locator = next(
        chunk.source_locator
        for chunk in request.retrieved_chunks
        if chunk.knowledge_id == target_id
    )
    source_ref_id = next(
        chunk.source.source_ref_id
        for chunk in request.retrieved_chunks
        if chunk.knowledge_id == target_id and chunk.source_locator == source_locator
    )
    reference_questions = []
    for slot in range(1, 7):
        is_choice = slot % 2 == 1
        reference_questions.append(
            RetrievedQuestion(
                question_id=f"formal-{target_id}-{slot}",
                knowledge_id=target_id,
                question_type=(
                    QuestionType.SINGLE_CHOICE if is_choice else QuestionType.SHORT_ANSWER
                ),
                stem=f"正式题库题目 {slot}",
                options=["正确项", "干扰项一", "干扰项二", "干扰项三"] if is_choice else [],
                answer_key={
                    **(
                        {"correct_option": 0}
                        if is_choice
                        else {"answer": "来源支持的答案", "rubric": ["要点一", "要点二"]}
                    ),
                    "explanation": "依据知识库材料作答。",
                    "source_ref_ids": [source_ref_id],
                    "source_locator": source_locator,
                        "question_slot": slot,
                        "question_bank_uses": ["graded_quiz"],
                        "quiz_level": (
                        "foundation"
                        if slot <= 2
                        else "improvement"
                        if slot <= 4
                        else "challenge"
                    ),
                },
                explanation="依据知识库材料作答。",
                difficulty=min(5, slot),
            )
        )
    request = request.model_copy(update={"reference_questions": reference_questions})
    generation = ContentGenerationAgent(
        generator=OpenAICompatibleStructuredGenerator(model_gateway=_Gateway()),
        renderer=render_resource_markdown,
    )
    with collect_model_calls() as collector:
        generation.execute(request)
    generation_calls = collector.snapshot()
    assert {item["resource_type"] for item in generation_calls} == {
        "lecture",
        "practice_guide",
    }
    assert len(generation_calls) >= 2
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
                            "quality_metrics": {
                                "evaluated_claim_count": 2,
                                "contradicted_claim_count": 0,
                                "evidence_insufficient_claim_count": 0,
                                "unresolved_claim_count": 0,
                                "hallucinated_claim_count": 0,
                                "difficulty_match_score": 100,
                                "covered_core_knowledge_count": 1,
                                "target_core_knowledge_count": 1,
                            },
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
