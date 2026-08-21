from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from demo_acceptance import _assessment_option
from run_live import _api_json, _authenticate


QUALITY_RULE_VERSION = "quality-v6-20260818"


def _current_node(path: dict[str, Any]) -> dict[str, Any]:
    node_id = path.get("current_node_id")
    node = next(
        (item for item in (path.get("nodes") or []) if item.get("path_node_id") == node_id),
        None,
    )
    if not node_id or node is None or node.get("status") != "current":
        raise AssertionError("learning path has no current node")
    return node


def _failed_evidence_id(learner_id: str, knowledge_id: str) -> str:
    """Resolve an existing confirmed failure without exposing answer content."""
    backend_root = Path(__file__).resolve().parents[1] / "backend"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.models import AnswerRecord, KnowledgeItem, Learner

    with SessionLocal() as db:
        learner = db.scalar(select(Learner).where(Learner.public_id == learner_id))
        knowledge = db.scalar(
            select(KnowledgeItem).where(KnowledgeItem.public_id == knowledge_id)
        )
        if learner is None or knowledge is None:
            raise AssertionError("path acceptance learner or knowledge is missing")
        records = db.scalars(
            select(AnswerRecord)
            .where(
                AnswerRecord.learner_id == learner.id,
                AnswerRecord.knowledge_item_id == knowledge.id,
                AnswerRecord.scoring_status == "scored",
                AnswerRecord.score < 0.4,
            )
            .order_by(AnswerRecord.id.desc())
        )
        record = next(
            (
                item
                for item in records
                if (item.answer_summary_json or {}).get("confirmed") is True
                and (item.answer_summary_json or {}).get("contract_evidence_type")
                == "scored_quiz"
            ),
            None,
        )
        if record is None:
            raise AssertionError("current node has no confirmed failed validation evidence")
        return f"answer_record:{record.id}"


def run(base_url: str, learner_id: str) -> dict[str, Any]:
    report = _api_json(base_url, "GET", f"/reports/learners/{learner_id}")
    path = report.get("learning_path") or {}
    node = _current_node(path)
    node_id = str(node["path_node_id"])
    knowledge_id = str(node["knowledge_id"])
    failed_evidence_id = _failed_evidence_id(learner_id, knowledge_id)
    failed_verification = _api_json(
        base_url,
        "POST",
        f"/learning-paths/{path['path_id']}/nodes/{node_id}/verify",
        {"evidence_ids": [failed_evidence_id]},
    )
    if failed_verification.get("verified") or failed_verification.get("best_score") != 0.0:
        raise AssertionError("failed validation unexpectedly completed the path node")

    resources = _api_json(base_url, "GET", f"/resources?learner_id={learner_id}")
    resource = next(
        (
            item
            for item in resources
            if item.get("review_status") == "passed"
            and knowledge_id in (item.get("sources") or [])
            and (item.get("package_quality") or {}).get("quality_rule_version")
            == QUALITY_RULE_VERSION
        ),
        None,
    )
    if resource is None:
        raise AssertionError("current node has no current passed V6 tutoring resource")

    session = _api_json(
        base_url,
        "POST",
        "/tutoring/sessions",
        {"learner_id": learner_id, "resource_id": resource["resource_id"]},
    )
    turn = _api_json(
        base_url,
        "POST",
        f"/tutoring/sessions/{session['session_id']}/messages",
        {"content": "这个当前知识点之前验证失败，请给我补救解释并再次正式验证。"},
        timeout=180,
    )
    assessment = (turn.get("reply") or {}).get("assessment")
    if not assessment or assessment.get("knowledge_id") != knowledge_id:
        raise AssertionError("formal assessment does not match the current path node")
    answer = _api_json(
        base_url,
        "POST",
        f"/tutoring/sessions/{session['session_id']}/assessments/"
        f"{assessment['assessment_id']}/answers",
        {"answer": _assessment_option(str(assessment["question_id"]), correct=True)},
        timeout=180,
    )
    if not answer.get("is_correct") or not answer.get("confirmed"):
        raise AssertionError("controlled server-scored validation did not pass")
    evidence_id = f"answer_record:{answer['answer_record_id']}"
    verified = _api_json(
        base_url,
        "POST",
        f"/learning-paths/{path['path_id']}/nodes/{node_id}/verify",
        {"evidence_ids": [evidence_id]},
    )
    if not verified.get("verified"):
        raise AssertionError("path node did not accept passing structured evidence")
    completed = _api_json(
        base_url,
        "POST",
        f"/learning-paths/{path['path_id']}/nodes/{node_id}/complete",
        {"evidence_ids": [evidence_id]},
    )
    repeated = _api_json(
        base_url,
        "POST",
        f"/learning-paths/{path['path_id']}/nodes/{node_id}/complete",
        {"evidence_ids": [evidence_id]},
    )
    next_node_id = (completed.get("path") or {}).get("current_node_id")
    if next_node_id == node_id:
        raise AssertionError("current path node did not advance")
    if repeated.get("completed_node_id") != node_id:
        raise AssertionError("repeated completion was not idempotent")
    return {
        "status": "passed",
        "learner_id": learner_id,
        "path_id": path["path_id"],
        "failed_evidence_id": failed_evidence_id,
        "failed_validation_rejected": True,
        "passed_evidence_id": evidence_id,
        "completed_node_id": node_id,
        "next_current_node_id": next_node_id,
        "idempotent_completion": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the M4 path progression acceptance.")
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default=os.getenv("EVALUATION_PASSWORD"))
    parser.add_argument("--learner-id", default="learner_admin_initial")
    args = parser.parse_args()
    if not args.password:
        raise SystemExit("set EVALUATION_PASSWORD or pass --password")
    _authenticate(args.base_url, args.username, args.password)
    print(json.dumps(run(args.base_url, args.learner_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
