from __future__ import annotations

import sys
from pathlib import Path

import pytest


TEST_SCRIPT_DIR = Path(__file__).resolve().parents[3] / "test_script"
if str(TEST_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_SCRIPT_DIR))

import demo_acceptance  # noqa: E402


def _resources() -> list[dict]:
    return [
        {
            "resource_id": "res-lecture",
            "resource_type": "lecture",
            "review_status": "passed",
            "sources": ["kid-1"],
            "source_details": [{"knowledge_id": "kid-1"}],
            "difficulty": "beginner",
            "quality_metrics": {"passed": True},
        },
        {
            "resource_id": "res-practice",
            "resource_type": "practice_guide",
            "review_status": "passed",
            "sources": ["kid-2"],
            "source_details": [{"knowledge_id": "kid-2"}],
            "difficulty": "beginner",
            "quality_metrics": {"passed": True},
        },
        {
            "resource_id": "res-quiz",
            "resource_type": "graded_quiz",
            "review_status": "passed",
            "sources": ["kid-3"],
            "source_details": [{"knowledge_id": "kid-3"}],
            "difficulty": "beginner",
            "quality_metrics": {"passed": True},
        },
    ]


def _runs(*, include_secondary: bool = True) -> list[dict]:
    roles = ["primary_review_model"]
    if include_secondary:
        roles.append("secondary_review_model")
    return [
        {
            "input_summary": {"step": "analyze_profile"},
            "output_summary": {"profile_update_required": False},
            "duration_ms": 12,
        },
        {
            "input_summary": {"step": "review_resource"},
            "output_summary": {
                "model_calls": [{"role": role} for role in roles],
                "arbitration": [{"required": True}, {"required": False}],
            },
            "duration_ms": 20,
        },
    ]


def test_stage0_task_evidence_requires_resources_sources_quality_and_dual_review(monkeypatch):
    def fake_api(_base_url, _method, path, *_args):
        if path.endswith("/internal-trace"):
            return {
                "thread_id": "task-1",
                "runs": [
                    {
            "contract_version": "agent-contract-v8",
                        "prompt_hash": "a" * 64,
                    }
                ],
                "messages": [{"sender": "orchestrator_agent"}],
                "reviews": [{"arbitration": {"required": True}}],
            }
        return _resources()

    monkeypatch.setattr(demo_acceptance, "_api_json", fake_api)

    evidence = demo_acceptance._stage0_task_evidence(
        "http://example.test/api/v1",
        {"task_id": "task-1", "thread_id": "task-1", "status": "completed", "revision_count": 0},
        _runs(),
        expect_three_resources=True,
    )

    assert evidence["resource_types"] == ["graded_quiz", "lecture", "practice_guide"]
    assert evidence["review_model_roles"] == ["primary_review_model", "secondary_review_model"]
    assert evidence["profile_update_required"] == [False]
    assert evidence["arbitration_count"] == 1
    assert evidence["duration_ms"] == 32


def test_stage0_task_evidence_rejects_missing_secondary_review(monkeypatch):
    monkeypatch.setattr(demo_acceptance, "_api_json", lambda *_args: _resources())

    with pytest.raises(AssertionError, match="primary and secondary"):
        demo_acceptance._stage0_task_evidence(
            "http://example.test/api/v1",
            {"task_id": "task-1", "thread_id": "task-1", "status": "completed"},
            _runs(include_secondary=False),
            expect_three_resources=True,
        )


def test_stage0_error_reporting_redacts_embedded_response_payloads():
    error = AssertionError(
        "first subjective feedback must not change profile: "
        "{'reply': {'content': '完整资源正文不能进入报告'}}"
    )

    summary = demo_acceptance._report_error(error)

    assert summary == "first subjective feedback must not change profile"
    assert "完整资源正文" not in summary


def test_current_resource_uses_current_v6_successor_instead_of_stale_baseline(
    monkeypatch,
):
    stale = {
        "resource_id": "res-baseline-v1",
        "resource_type": "lecture",
        "review_status": "passed",
        "package_quality": {"quality_rule_version": "quality-v6-20260818"},
    }
    current = {
        "resource_id": "res-successor-v2",
        "resource_type": "lecture",
        "review_status": "passed",
        "package_quality": {"quality_rule_version": "quality-v6-20260818"},
    }
    monkeypatch.setattr(
        demo_acceptance,
        "_api_json",
        lambda *_args: [current, stale],
    )

    selected = demo_acceptance._current_resource(
        "http://example.test/api/v1", "learner-1"
    )

    assert selected["resource_id"] == "res-successor-v2"


def test_current_resource_rejects_legacy_current_package(monkeypatch):
    monkeypatch.setattr(
        demo_acceptance,
        "_api_json",
        lambda *_args: [
            {
                "resource_id": "res-legacy",
                "resource_type": "lecture",
                "review_status": "passed",
                "package_quality": None,
            }
        ],
    )

    with pytest.raises(AssertionError, match="current passed V6"):
        demo_acceptance._current_resource(
            "http://example.test/api/v1", "learner-1"
        )
