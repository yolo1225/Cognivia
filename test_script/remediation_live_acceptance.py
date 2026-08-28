from __future__ import annotations

# ruff: noqa: E402

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.core.config import settings
from app.models import (
    AgentRun,
    AnswerRecord,
    DiagnosticQuestion,
    GenerationTask,
    IndexBuildJob,
    KnowledgeDocument,
    KnowledgeImportCandidate,
    KnowledgeItem,
    Learner,
    LearnerProfile,
    LearningResource,
)
from app.rag.readiness import candidate_rag_status
from app.services import candidate_index_job
from app.services.diagnostic_service import (
    create_diagnostic_session,
    get_diagnostic_session_status,
    prepare_diagnostic_submission,
    retry_diagnostic_session,
    run_diagnostic_scoring_job,
)
from app.services.domain_api_service import DomainApiService
from app.services.knowledge_document_service import create_document, process_knowledge_document
from app.services.knowledge_import_publish_service import (
    KnowledgeImportPublishError,
    activate_import_candidate,
    approve_candidates,
    publish_approved,
    smoke_domain_index,
    smoke_import_index,
)
from app.services.knowledge_import_validation_service import validate_import
from run_live import HTTP_OPENER, _api_json, _authenticate, _csrf_token


REPORT_PATH = ROOT / "reports" / "demo" / "remediation-live-latest.json"
WEIGHTS = {
    "theory": 0.3,
    "practice": 0.25,
    "problem_solving": 0.2,
    "knowledge_breadth": 0.25,
    "learning_speed": 0.0,
}


def _diagnostic_acceptance(run_suffix: str) -> dict:
    learner_id = f"learner_diag_live_{run_suffix}"
    with SessionLocal() as db:
        learner = Learner(
            public_id=learner_id,
            background="本科软件工程，具备基础编程经验",
            education_level="本科",
            major="软件工程",
            target_domain="ai_app_dev",
            experience_years=1,
            learning_style="mixed",
            direction_tags_json=["rag_knowledge_base"],
            is_evaluation=True,
        )
        db.add(learner)
        db.commit()
        session = create_diagnostic_session(
            db,
            learner_id=learner_id,
            domain_code="ai_app_dev",
            question_count=10,
        )
        question_rows = {
            question.public_id: question
            for question in db.scalars(
                select(DiagnosticQuestion).where(
                    DiagnosticQuestion.public_id.in_(
                        [item["question_id"] for item in session["questions"]]
                    )
                )
            )
        }
        answers = []
        for item in session["questions"]:
            question = question_rows[item["question_id"]]
            key = question.answer_key_json or {}
            answer = (
                key.get("correct_option", 0)
                if question.question_type == "single_choice"
                else key.get("answer")
                or key.get("reference_answer")
                or key.get("explanation")
                or "按输入、处理、输出和异常边界说明该知识点。"
            )
            answers.append({"question_id": question.public_id, "answer": answer})
        submitted, started = prepare_diagnostic_submission(
            db,
            session_id=session["session_id"],
            learner_id=learner_id,
            domain_code="ai_app_dev",
            answers=answers,
        )
        if not started or submitted["status"] != "scoring":
            raise AssertionError("diagnostic scoring lease was not started")

    run_diagnostic_scoring_job(session["session_id"])
    with SessionLocal() as db:
        status = get_diagnostic_session_status(
            db,
            session_id=session["session_id"],
            learner_id=learner_id,
        )
        if status["status"] == "pending_scoring":
            _result, retry_started = retry_diagnostic_session(
                db,
                session_id=session["session_id"],
                learner_id=learner_id,
            )
            if not retry_started:
                raise AssertionError("pending diagnostic retry did not start")
    if status["status"] == "pending_scoring":
        run_diagnostic_scoring_job(session["session_id"])

    with SessionLocal() as db:
        status = get_diagnostic_session_status(
            db,
            session_id=session["session_id"],
            learner_id=learner_id,
        )
        if status["status"] != "scored":
            raise AssertionError(f"live diagnostic did not score: {status['status']}")
        repeated, repeated_started = prepare_diagnostic_submission(
            db,
            session_id=session["session_id"],
            learner_id=learner_id,
            domain_code="ai_app_dev",
            answers=answers,
        )
        if repeated_started or repeated["status"] != "scored":
            raise AssertionError("completed diagnostic was not idempotent")
        changed = [dict(item) for item in answers]
        changed[-1]["answer"] = str(changed[-1]["answer"]) + " changed"
        conflict = False
        try:
            prepare_diagnostic_submission(
                db,
                session_id=session["session_id"],
                learner_id=learner_id,
                domain_code="ai_app_dev",
                answers=changed,
            )
        except ValueError as exc:
            conflict = str(exc) == "diagnostic_answers_changed"
        if not conflict:
            raise AssertionError("changed diagnostic answers were not rejected")
        record_count = db.scalar(
            select(func.count()).select_from(AnswerRecord).where(
                AnswerRecord.session_id == session["session_id"]
            )
        )
        runs = list(
            db.scalars(
                select(AgentRun).where(
                    AgentRun.agent_name == "profile_analysis_agent",
                    AgentRun.input_summary_json["session_id"].as_string()
                    == session["session_id"],
                )
            )
        )
        live_runs = [run for run in runs if run.model_name and run.llm_calls > 0]
        if record_count != 10 or not live_runs:
            raise AssertionError("diagnostic persistence or live model evidence is missing")
        profile = db.scalar(
            select(LearnerProfile).where(
                LearnerProfile.public_id == status["result"]["profile_id"]
            )
        )
        source = db.scalar(
            select(KnowledgeItem)
            .where(
                KnowledgeItem.domain_code == "ai_app_dev",
                KnowledgeItem.status == "published",
            )
            .order_by(KnowledgeItem.id)
        )
        if profile is None or source is None:
            raise AssertionError("diagnostic profile or tutoring source is missing")
        task = GenerationTask(
            public_id=f"task_tutor_live_{run_suffix}",
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
            status="completed",
            resource_types_json=["lecture"],
            decision="completed",
            trigger_type="initial_generation",
            execution_mode="auto",
            learning_goal="流式导学验收",
            is_current_package=True,
            progress=100,
            package_quality_json={"quality_rule_version": "quality-v8-official-gates"},
        )
        db.add(task)
        db.flush()
        resource = LearningResource(
            public_id=f"resource_tutor_live_{run_suffix}",
            generation_task_id=task.id,
            resource_type="lecture",
            title="流式导学验收讲义",
            content_md=(
                f"# {source.name}\n\n{source.content_md}\n\n"
                "学习时先确认输入和目标，再核对关键步骤、输出与常见错误。"
            ),
            difficulty=2,
            learner_profile_type="evaluation",
            sources_json=[
                {
                    "knowledge_id": source.public_id,
                    "source_ref_id": source.public_id,
                    "source_title": source.source_title,
                }
            ],
            review_status="passed",
            series_id=f"series_tutor_live_{run_suffix}",
            is_current=True,
        )
        db.add(resource)
        db.commit()
        return {
            "session_id": session["session_id"],
            "status": status["status"],
            "scoring_attempts": status["scoring_attempts"],
            "answer_record_count": record_count,
            "llm_calls": sum(run.llm_calls for run in live_runs),
            "model_names": sorted({run.model_name for run in live_runs}),
            "idempotent": True,
            "changed_answers_rejected": True,
            "learner_id": learner_id,
            "resource_id": resource.public_id,
        }


def _stream_tutoring_acceptance(
    base_url: str,
    username: str,
    password: str,
    *,
    learner_id: str,
    resource_id: str,
) -> dict:
    _authenticate(base_url, username, password)
    session = _api_json(
        base_url,
        "POST",
        "/tutoring/sessions",
        {"learner_id": learner_id, "resource_id": resource_id},
    )
    with SessionLocal() as db:
        before_id = db.scalar(select(func.max(AgentRun.id))) or 0
    payload = json.dumps(
        {"content": "请结合当前资源解释最关键的概念，并指出一个常见误区。"},
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if csrf := _csrf_token():
        headers["X-CSRF-Token"] = csrf
    request = Request(
        f"{base_url.rstrip('/')}/tutoring/sessions/{session['session_id']}/messages/stream",
        data=payload,
        method="POST",
        headers=headers,
    )
    events: list[tuple[str, dict]] = []
    current_event = "message"
    with HTTP_OPENER.open(request, timeout=360) as response:
        if response.status != 200:
            raise AssertionError(f"stream returned {response.status}")
        for raw in response:
            line = raw.decode("utf-8").strip()
            if line.startswith("event:"):
                current_event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                events.append((current_event, json.loads(line.split(":", 1)[1].strip())))
    completed = next((item for name, item in events if name == "completed"), None)
    if completed is None or any(name == "error" for name, _item in events):
        raise AssertionError("streaming tutoring did not complete")
    delta_text = "".join(item.get("content", "") for name, item in events if name == "delta")
    if delta_text != completed.get("content"):
        raise AssertionError("streamed deltas differ from the committed reply")
    with SessionLocal() as db:
        runs = list(
            db.scalars(
                select(AgentRun).where(
                    AgentRun.id > before_id,
                    AgentRun.agent_name == "tutoring_agent",
                )
            )
        )
        runs = [
            run
            for run in runs
            if (run.input_summary_json or {}).get("session_id") == session["session_id"]
        ]
        if len(runs) != 1 or runs[0].llm_calls != 1 or not runs[0].model_name:
            raise AssertionError("streaming tutoring did not use exactly one live model call")
        return {
            "session_id": session["session_id"],
            "event_order": [name for name, _item in events],
            "delta_count": sum(name == "delta" for name, _item in events),
            "reply_length": len(delta_text),
            "llm_calls": runs[0].llm_calls,
            "model_name": runs[0].model_name,
            "feedback_intent": completed.get("feedback_intent"),
            "recommended_action": completed.get("recommended_action"),
        }


def _import_content() -> bytes:
    lines = ["# 原子索引发布验收知识包", ""]
    topics = [
        ("API 输入校验", "使用 Pydantic 校验请求字段、类型和业务约束，在进入模型前拒绝无效输入。"),
        ("训练数据清洗", "识别重复样本、缺失值和标签噪声，并记录可复现的数据清洗规则。"),
        ("提示词结构约束", "通过明确字段定义和完整 JSON 示例约束模型输出，减少格式漂移。"),
        ("向量知识入库", "切分知识正文、生成 embedding，并将来源元数据与向量记录共同写入索引。"),
        ("领域元数据过滤", "检索时使用 domain_code 过滤候选，防止其他领域知识进入当前回答。"),
        ("候选结果重排序", "结合语义距离与业务相关性对召回结果重排，优先保留高质量证据。"),
        ("结构化输出校验", "逐项验证模型返回字段，只重试校验失败的条目并保留已成功结果。"),
        ("双模型审核仲裁", "比较两个审核通道的事实与来源评分，在显著分歧时重新检索并仲裁。"),
        ("幂等任务重试", "使用规范化请求哈希识别重复提交，确保重试不会重复写入业务记录。"),
        ("原子发布回滚", "先验证候选产物再切换活动版本，提交失败时恢复旧 manifest 和数据状态。"),
    ]
    for index, (name, definition) in enumerate(topics, start=1):
        lines.extend(
            [
                f"## {index}. {name}",
                "",
                definition,
                f"执行{name}任务时，应记录来源、核对结果并保留可重试状态。",
                "",
            ]
        )
    return "\n".join(lines).encode("utf-8")


def _import_acceptance(run_suffix: str) -> dict:
    domain_code = f"atomic_accept_{run_suffix}"
    with SessionLocal() as db:
        DomainApiService(db).create(
            domain_code=domain_code,
            name="原子索引发布验收领域",
            description="本轮修复的隔离验收领域",
            learning_directions=[
                {
                    "value": "atomic_flow",
                    "label": "原子发布",
                    "description": "验证候选构建和发布",
                    "match_tags": ["atomic", "validation"],
                }
            ],
        )
        document = create_document(
            db,
            domain_code=domain_code,
            original_name="atomic-index-acceptance.md",
            content=_import_content(),
            mime_type="text/markdown",
            source_title="原子索引发布验收材料",
            license_note="项目内部验收材料",
            uploaded_by="remediation_acceptance",
        )
        document_id = document.public_id
    process_knowledge_document(document_id)
    with SessionLocal() as db:
        document = db.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.public_id == document_id)
        )
        candidates = list(
            db.scalars(
                select(KnowledgeImportCandidate)
                .where(KnowledgeImportCandidate.document_id == document.id)
                .order_by(KnowledgeImportCandidate.id)
            )
        )
        knowledge = [item for item in candidates if item.candidate_type == "knowledge_item"]
        questions = [
            item for item in candidates if item.candidate_type == "diagnostic_question"
        ]
        if len(knowledge) != 10 or len(questions) != 10:
            raise AssertionError("import extraction did not create 10 knowledge items and questions")
        knowledge_index = {item.public_id: index for index, item in enumerate(knowledge)}
        for index, item in enumerate(knowledge):
            payload = dict(item.payload_json or {})
            payload["ability_weights"] = dict(WEIGHTS)
            payload["tags"] = ["atomic", "validation"]
            payload["evidence_capabilities"] = (
                ["definition", "operation"] if index in {3, 4, 5, 8, 9} else ["definition"]
            )
            item.payload_json = payload
        for item in questions:
            payload = dict(item.payload_json or {})
            index = knowledge_index[payload["knowledge_candidate_id"]]
            if index < 6:
                correct = f"验收知识点 {index + 1} 的正确处理要求"
                payload.update(
                    {
                        "question_type": "single_choice",
                        "options": [correct, "与本知识点无关"],
                        "answer": correct,
                    }
                )
            else:
                payload["question_type"] = "short_answer"
            item.payload_json = payload
        db.commit()
        validation = validate_import(db, document.id)
        if validation["invalid"]:
            raise AssertionError(f"import candidates invalid: {validation['invalid']}")
        approve_candidates(db, document)
        publish_approved(db, document)
        staged_count = db.scalar(
            select(func.count()).select_from(KnowledgeItem).where(
                KnowledgeItem.source_document_id == document.id,
                KnowledgeItem.status == "staged",
            )
        )
        if staged_count != 10 or candidate_rag_status(domain_code).get("ready"):
            raise AssertionError("staged import leaked into the active index")
        job = candidate_index_job.try_start(
            db,
            domain_code,
            source_document_id=document.id,
        )
        document.status = "indexing"
        db.commit()
        job_id = job.id
        source_document_id = document.id
    candidate_index_job.run_import_build(job_id, domain_code, source_document_id)
    with SessionLocal() as db:
        job = db.get(IndexBuildJob, job_id)
        document = db.get(KnowledgeDocument, source_document_id)
        if job is None or job.status != "success":
            raise AssertionError(f"candidate build failed: {job.message if job else 'missing'}")
        failed_publish_rolled_back = False
        try:
            activate_import_candidate(db, document, job)
        except KnowledgeImportPublishError:
            db.rollback()
            staged_count = db.scalar(
                select(func.count()).select_from(KnowledgeItem).where(
                    KnowledgeItem.source_document_id == document.id,
                    KnowledgeItem.status == "staged",
                )
            )
            failed_publish_rolled_back = staged_count == 10 and not candidate_rag_status(
                domain_code
            ).get("ready")
        if not failed_publish_rolled_back:
            raise AssertionError("failed publish changed staged data or active manifest")
        result = dict(job.result_json or {})
        manifest = result["candidate_manifest"]
        imported = smoke_import_index(db, document, manifest_payload=manifest)
        isolated = smoke_domain_index(
            db,
            domain_code,
            manifest_payload=manifest,
            staged_document_id=document.id,
        )
        result["smoke_test"] = {
            "passed": True,
            "index_version": manifest["index_version"],
            "active_collection": manifest["active_collection"],
            "import_id": document.public_id,
            "checked_at": datetime.now(UTC).isoformat(),
            "checks": {
                "import": imported["checks"],
                "domain": isolated["checks"],
            },
        }
        job.result_json = result
        document.status = "smoke_passed"
        db.commit()
        activated = activate_import_candidate(db, document, job)
        readiness = DomainApiService(db).readiness(domain_code)
        if not readiness["passed"]:
            raise AssertionError(f"published domain readiness failed: {readiness['issues']}")
        DomainApiService(db).publish(domain_code)
        DomainApiService(db).disable(domain_code)
        return {
            "domain_code": domain_code,
            "document_id": document_id,
            "job_id": job_id,
            "failed_publish_rolled_back": failed_publish_rolled_back,
            "candidate_smoke_passed": True,
            "activated_index_version": activated["index_version"],
            "published_knowledge_count": readiness["counts"]["knowledge_items"],
            "diagnostic_question_count": readiness["counts"]["diagnostic_questions"],
            "domain_disabled_after_acceptance": True,
        }


def main() -> None:
    password = os.getenv("EVALUATION_PASSWORD") or settings.initial_admin_password
    if not password:
        raise SystemExit("EVALUATION_PASSWORD is required")
    suffix = datetime.now(UTC).strftime("%m%d%H%M%S")
    base_url = os.getenv("ACCEPTANCE_BASE_URL", "http://localhost:8000/api/v1")
    diagnostic = _diagnostic_acceptance(suffix)
    report = {
        "status": "passed",
        "provider_mode": "live",
        "started_at": datetime.now(UTC).isoformat(),
        "diagnostic": diagnostic,
        "tutoring_stream": _stream_tutoring_acceptance(
            base_url,
            os.getenv("EVALUATION_USERNAME", "admin"),
            password,
            learner_id=diagnostic["learner_id"],
            resource_id=diagnostic["resource_id"],
        ),
        "candidate_import": _import_acceptance(suffix),
        "finished_at": datetime.now(UTC).isoformat(),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
