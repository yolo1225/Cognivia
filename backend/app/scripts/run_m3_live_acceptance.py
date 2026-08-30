from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import (
    DiagnosticQuestion,
    Domain,
    GenerationTask,
    KnowledgeDocument,
    KnowledgeItem,
    Learner,
    LearnerProfile,
    LearningPath,
    LearningResource,
)
from app.rag.readiness import candidate_rag_status
from app.services import candidate_index_job
from app.services.diagnostic_service import (
    create_diagnostic_session,
    submit_diagnostic_session,
)
from app.services.domain_api_service import DomainApiService
from app.services.domain_runtime_service import DomainRuntimeError, require_ready_domain
from app.services.knowledge_document_service import create_document
from app.services.knowledge_import_publish_service import (
    activate_import_candidate,
    smoke_import_index,
)
from app.services.knowledge_import_orchestrator import create_import_run, resolve_run, run_import
from app.services.profile_service import public_id
from app.workers.generation_worker import run_generation_task


DOMAIN_CODE = "m3_live_acceptance"
LEARNER_ID = "learner_m3_live_acceptance"
REPORT_PATH = Path(__file__).resolve().parents[3] / "reports" / "m3-live-acceptance.json"

SECTIONS = (
    ("变量与数据类型", "变量用于保存程序运行中的数据；字符串、整数和布尔值是常见类型。"),
    ("条件分支", "条件分支根据布尔表达式选择执行路径，应覆盖正常分支和边界分支。"),
    ("循环与迭代", "循环用于重复处理数据，必须设置清晰的终止条件并避免无限循环。"),
    ("函数参数", "函数通过参数接收输入，通过返回值输出结果；调用前应校验参数类型。"),
    ("异常处理", "异常处理捕获可预期错误，记录必要上下文，并向调用者返回明确失败原因。"),
    ("单元测试", "单元测试以独立用例验证函数行为，通常包含正常、边界和失败场景。"),
    ("HTTP 请求", "HTTP 请求由方法、地址、请求头和请求体组成，响应包含状态码与数据。"),
    ("JSON 数据", "JSON 使用对象和数组表达结构化数据，字段类型与必填规则应保持稳定。"),
    ("API 调试", "API 调试应检查请求参数、响应状态码、错误信息和服务端日志摘要。"),
    ("应用部署", "应用部署需要固定依赖、配置环境变量、执行健康检查并保留回滚方案。"),
)


def _document_content() -> bytes:
    lines = ["# Python Web 应用开发最小实训知识包", ""]
    for index, (title, body) in enumerate(SECTIONS, start=1):
        lines.extend(
            [
                f"## {index}. {title}",
                "",
                body,
                f"学习者应能解释{title}，并在一个最小 Web 应用任务中完成对应操作。",
                "",
            ]
        )
    return "\n".join(lines).encode("utf-8")


def _create_domain_and_import() -> tuple[str, dict]:
    with SessionLocal() as db:
        if db.scalar(select(Domain).where(Domain.domain_code == DOMAIN_CODE)) is not None:
            raise RuntimeError(f"acceptance_domain_already_exists:{DOMAIN_CODE}")
        domain = DomainApiService(db).create(
            domain_code=DOMAIN_CODE,
            name="Python Web 应用开发验收领域",
            description="M3 可停用真实验收领域",
            learning_directions=[
                {
                    "value": "web_practice",
                    "label": "Web 实践",
                    "description": "完成最小 API 开发与调试",
                    "match_tags": ["m3-acceptance", "web"],
                }
            ],
        )
        assert domain["status"] == "draft"
        document = create_document(
            db,
            domain_code=DOMAIN_CODE,
            original_name="m3-live-acceptance.md",
            content=_document_content(),
            mime_type="text/markdown",
            source_title="M3 Python Web 应用开发验收知识包",
            license_note="项目内部验收材料",
            uploaded_by="m3_acceptance",
        )
        run = create_import_run(db, document)
        document_id = document.public_id
        run_id = run.public_id

    run_import(run_id)
    with SessionLocal() as db:
        run, document = resolve_run(db, run_id)
        if run.status != "ready_to_publish":
            raise RuntimeError(f"orchestrated_import_failed:{run.status}:{run.error_summary}")
        job = candidate_index_job.latest_job(
            db, DOMAIN_CODE, source_document_id=document.id
        )
        if job is None:
            raise RuntimeError("orchestrated_import_index_missing")
        activated = activate_import_candidate(db, document, job)
        return document_id, {
            "run_id": run_id,
            "input_version": run.input_version,
            "status": run.status,
            "published": activated,
        }


def _build_and_smoke(document_id: str) -> dict:
    with SessionLocal() as db:
        document = db.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.public_id == document_id)
        )
        job = candidate_index_job.try_start(db, DOMAIN_CODE)
        if document is None or job is None:
            raise RuntimeError("candidate_index_job_not_started")
        document.status = "indexing"
        db.commit()
        job_id = job.id
    candidate_index_job.run_rebuild(job_id, DOMAIN_CODE)
    with SessionLocal() as db:
        job = db.get(candidate_index_job.IndexBuildJob, job_id)
        document = db.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.public_id == document_id)
        )
        if job is None or job.status != candidate_index_job.STATUS_SUCCESS or document is None:
            raise RuntimeError(f"candidate_index_failed:{job.message if job else 'missing'}")
        retrieval = smoke_import_index(db, document)
        rag = candidate_rag_status(DOMAIN_CODE)
        result = dict(job.result_json or {})
        result["smoke_test"] = {
            "passed": True,
            "index_version": rag.get("index_version"),
            "active_collection": rag.get("active_collection"),
            "import_id": document.public_id,
            "checked_at": datetime.now(UTC).isoformat(),
            "checks": retrieval.get("checks", {}),
        }
        job.result_json = result
        document.status = "ready"
        document.embedding_model = result.get("embedding_model")
        document.indexed_at = job.finished_at
        db.commit()
        return {"job_id": job_id, "rag": rag, "retrieval": retrieval}


def _publish_domain() -> dict:
    with SessionLocal() as db:
        service = DomainApiService(db)
        readiness = service.readiness(DOMAIN_CODE)
        if not readiness["passed"]:
            raise RuntimeError(
                f"readiness_failed:{readiness['issues']}:{readiness['runtime_reasons']}"
            )
        published = (
            {"domain": service.detail(DOMAIN_CODE), "readiness": readiness}
            if readiness["status"] == "ready"
            else service.publish(DOMAIN_CODE)
        )
        return {"readiness": readiness, "published": published}


def _diagnose_learner() -> dict:
    with SessionLocal() as db:
        learner = db.scalar(select(Learner).where(Learner.public_id == LEARNER_ID))
        if learner is None:
            learner = Learner(
                public_id=LEARNER_ID,
                background="本科｜软件工程",
                education_level="本科",
                major="软件工程",
                target_domain=DOMAIN_CODE,
                experience_years=1,
                learning_style="mixed",
                direction_tags_json=["web_practice"],
            )
            db.add(learner)
            db.commit()
        completed_profile = db.scalar(
            select(LearnerProfile)
            .where(
                LearnerProfile.learner_id == learner.id,
                LearnerProfile.domain_code == DOMAIN_CODE,
                LearnerProfile.diagnosis_completed.is_(True),
            )
            .order_by(LearnerProfile.id.desc())
        )
        if completed_profile is not None:
            completed_path = db.scalar(
                select(LearningPath)
                .where(
                    LearningPath.learner_id == learner.id,
                    LearningPath.domain_code == DOMAIN_CODE,
                )
                .order_by(LearningPath.id.desc())
            )
            if completed_path is None:
                raise RuntimeError("completed_profile_path_missing")
            return {
                "session": {
                    "session_id": "resumed",
                    "question_count": 10,
                    "selection_summary": {
                        "single_choice_count": 6,
                        "short_answer_count": 4,
                        "theory_count": 5,
                        "practice_count": 5,
                    },
                },
                "result": {"resumed": True},
                "profile_id": completed_profile.public_id,
                "path_id": completed_path.public_id,
            }
        session = create_diagnostic_session(
            db, learner_id=LEARNER_ID, domain_code=DOMAIN_CODE, question_count=10
        )
        question_rows = {
            item.public_id: item
            for item in db.scalars(
                select(DiagnosticQuestion).where(
                    DiagnosticQuestion.public_id.in_(
                        [question["question_id"] for question in session["questions"]]
                    )
                )
            )
        }
        answers = []
        for question in session["questions"]:
            row = question_rows[question["question_id"]]
            answer_key = row.answer_key_json or {}
            answer = (
                answer_key["correct_option"]
                if row.question_type == "single_choice"
                else answer_key["answer"]
            )
            answers.append({"question_id": row.public_id, "answer": answer})
        result = submit_diagnostic_session(
            db,
            session_id=session["session_id"],
            learner_id=LEARNER_ID,
            domain_code=DOMAIN_CODE,
            answers=answers,
        )
        profile = db.scalar(
            select(LearnerProfile)
            .where(
                LearnerProfile.learner_id == learner.id,
                LearnerProfile.domain_code == DOMAIN_CODE,
                LearnerProfile.diagnosis_completed.is_(True),
            )
            .order_by(LearnerProfile.id.desc())
        )
        path = db.scalar(
            select(LearningPath)
            .where(
                LearningPath.learner_id == learner.id,
                LearningPath.domain_code == DOMAIN_CODE,
            )
            .order_by(LearningPath.id.desc())
        )
        if profile is None or path is None:
            raise RuntimeError("diagnostic_did_not_create_profile_and_path")
        return {
            "session": session,
            "result": result,
            "profile_id": profile.public_id,
            "path_id": path.public_id,
        }


def _generate_resources(profile_id: str) -> dict:
    with SessionLocal() as db:
        learner = db.scalar(select(Learner).where(Learner.public_id == LEARNER_ID))
        profile = db.scalar(select(LearnerProfile).where(LearnerProfile.public_id == profile_id))
        if learner is None or profile is None:
            raise RuntimeError("generation_context_missing")
        task = GenerationTask(
            public_id=public_id("task"),
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code=DOMAIN_CODE,
            status="pending",
            resource_types_json=["lecture", "practice_guide", "graded_quiz"],
            revision_count=0,
            decision="pending",
            trigger_type="initial_generation",
            execution_mode="auto",
            learning_goal=(
                "严格依据检索原文生成基础学习资源；实操指南只设计原文明确支持的纸面检查、"
                "请求要素核对和错误定位步骤，不引入框架、命令、端口或新的 API 路径"
            ),
            progress=0,
        )
        db.add(task)
        db.commit()
        task_id = task.public_id
    worker_result = run_generation_task(task_id)
    with SessionLocal() as db:
        task = db.scalar(select(GenerationTask).where(GenerationTask.public_id == task_id))
        resources = list(
            db.scalars(
                select(LearningResource)
                .where(LearningResource.generation_task_id == task.id)
                .order_by(LearningResource.id)
            )
        )
        if task.status != "completed" or task.decision != "completed" or len(resources) != 3:
            raise RuntimeError(
                f"three_resource_generation_failed:status={task.status},decision={task.decision},"
                f"revision_count={task.revision_count},failure={task.failure_reason},"
                f"resources={len(resources)}"
            )
        domain_ids = set(
            db.scalars(
                select(KnowledgeItem.public_id).where(KnowledgeItem.domain_code == DOMAIN_CODE)
            )
        )
        source_ids = {
            str(source.get("knowledge_id") or source.get("source_ref_id") or "")
            for resource in resources
            for source in (resource.sources_json or [])
            if isinstance(source, dict)
        }
        foreign_ids = sorted(source_id for source_id in source_ids if source_id not in domain_ids)
        if foreign_ids:
            raise RuntimeError(f"cross_domain_resource_sources:{foreign_ids}")
        return {
            "task_id": task_id,
            "worker_result": worker_result,
            "revision_count": task.revision_count,
            "resource_ids": [resource.public_id for resource in resources],
            "resource_types": sorted(resource.resource_type for resource in resources),
            "source_ids": sorted(source_ids),
        }


def _disable_and_verify_history(task_id: str) -> dict:
    with SessionLocal() as db:
        disabled = DomainApiService(db).disable(DOMAIN_CODE)
        blocked = False
        try:
            require_ready_domain(db, DOMAIN_CODE)
        except DomainRuntimeError:
            blocked = True
        task = db.scalar(select(GenerationTask).where(GenerationTask.public_id == task_id))
        resources = list(
            db.scalars(
                select(LearningResource).where(LearningResource.generation_task_id == task.id)
            )
        )
        if not blocked or task is None or len(resources) != 3:
            raise RuntimeError("disabled_gate_or_history_readability_failed")
        return {
            "domain_status": disabled["status"],
            "new_task_blocked": blocked,
            "historical_task_status": task.status,
            "historical_resource_count": len(resources),
        }


def _resume_import_state() -> tuple[str, dict]:
    with SessionLocal() as db:
        document = db.scalar(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.domain_code == DOMAIN_CODE)
            .order_by(KnowledgeDocument.id.desc())
        )
        if document is None:
            raise RuntimeError("acceptance_document_missing")
        return document.public_id, {
            "resumed": True,
            "document_status": document.status,
            "published": {
                "knowledge_items": document.knowledge_item_count,
                "questions": len(
                    list(
                        db.scalars(
                            select(DiagnosticQuestion.id).where(
                                DiagnosticQuestion.domain_code == DOMAIN_CODE
                            )
                        )
                    )
                ),
            },
        }


def run(*, resume: bool = False) -> dict:
    started_at = datetime.now(UTC)
    document_id, imported = _resume_import_state() if resume else _create_domain_and_import()
    if candidate_rag_status(DOMAIN_CODE).get("ready"):
        indexed = {"resumed": True, "rag": candidate_rag_status(DOMAIN_CODE)}
    else:
        indexed = _build_and_smoke(document_id)
    published = _publish_domain()
    diagnosed = _diagnose_learner()
    generated = _generate_resources(diagnosed["profile_id"])
    disabled = _disable_and_verify_history(generated["task_id"])
    report = {
        "status": "passed",
        "domain_code": DOMAIN_CODE,
        "learner_id": LEARNER_ID,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "document_id": document_id,
        "import": imported,
        "index": indexed,
        "publish": {
            "readiness_passed": published["readiness"]["passed"],
            "counts": published["readiness"]["counts"],
            "issues": published["readiness"]["issues"],
        },
        "diagnosis": {
            "session_id": diagnosed["session"]["session_id"],
            "question_count": diagnosed["session"]["question_count"],
            "selection_summary": diagnosed["session"]["selection_summary"],
            "profile_id": diagnosed["profile_id"],
            "path_id": diagnosed["path_id"],
        },
        "generation": generated,
        "disable": disabled,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the real M3 domain lifecycle acceptance.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    report = run(resume=args.resume)
    print(
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.json
        else "M3 live acceptance passed"
    )


if __name__ == "__main__":
    main()
