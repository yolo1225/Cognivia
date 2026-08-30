"""Staging helpers for incremental domain maintenance.

The active domain remains readable while a change set is prepared.  The model
is intentionally small: it records the operator-visible unit of work and
links documents, import runs and question workbooks without introducing a full
domain-version hierarchy.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    AnswerRecord,
    DiagnosticQuestion,
    Domain,
    DomainChangeSet,
    IndexBuildJob,
    KnowledgeDocument,
    KnowledgeImportRun,
    KnowledgeItem,
    KnowledgeItemSource,
    KnowledgeRelation,
    QuestionImportRow,
    QuestionImportRun,
)
from app.services.question_import_service import knowledge_catalog_fingerprint


OPEN_STATUSES = {"preparing", "ready_for_questions", "questions_preparing"}
CANCELLABLE_STATUSES = OPEN_STATUSES | {"ready_to_activate"}


class DomainChangeSetError(ValueError):
    pass


def active_catalog_fingerprint(db: Session, domain_code: str) -> str:
    items = list(
        db.scalars(
            select(KnowledgeItem)
            .where(
                KnowledgeItem.domain_code == domain_code,
                KnowledgeItem.status == "published",
            )
            .order_by(KnowledgeItem.public_id)
        )
    )
    return knowledge_catalog_fingerprint(items)


def create_change_set(
    db: Session,
    *,
    domain_code: str,
    mode: str = "append",
    created_by: str = "demo_admin",
) -> DomainChangeSet:
    if mode not in {"append", "replace"}:
        raise DomainChangeSetError("DOMAIN_CHANGE_SET_MODE_INVALID")
    if db.scalar(select(Domain).where(Domain.domain_code == domain_code)) is None:
        raise DomainChangeSetError("DOMAIN_NOT_FOUND")
    change_set = DomainChangeSet(
        public_id=f"dcs_{uuid4().hex[:16]}",
        domain_code=domain_code,
        status="preparing",
        mode=mode,
        base_catalog_fingerprint=active_catalog_fingerprint(db, domain_code),
        summary_json={"documents": [], "question_runs": []},
        created_by=created_by[:64],
    )
    db.add(change_set)
    db.flush()
    return change_set


def get_change_set(db: Session, public_id: str, *, domain_code: str | None = None) -> DomainChangeSet:
    statement = select(DomainChangeSet).where(DomainChangeSet.public_id == public_id)
    if domain_code:
        statement = statement.where(DomainChangeSet.domain_code == domain_code)
    change_set = db.scalar(statement)
    if change_set is None:
        raise DomainChangeSetError("DOMAIN_CHANGE_SET_NOT_FOUND")
    return change_set


def latest_open_change_set(db: Session, domain_code: str) -> DomainChangeSet | None:
    return db.scalar(
        select(DomainChangeSet)
        .where(
            DomainChangeSet.domain_code == domain_code,
            DomainChangeSet.status.in_(OPEN_STATUSES),
        )
        .order_by(DomainChangeSet.id.desc())
        .limit(1)
    )


def update_change_set_summary(
    change_set: DomainChangeSet,
    *,
    document_id: str | None = None,
    question_run_id: str | None = None,
    target_catalog_fingerprint: str | None = None,
    status: str | None = None,
    error_summary: str | None = None,
) -> None:
    summary = dict(change_set.summary_json or {})
    if document_id:
        summary["documents"] = list(dict.fromkeys([*(summary.get("documents") or []), document_id]))
    if question_run_id:
        summary["question_runs"] = list(
            dict.fromkeys([*(summary.get("question_runs") or []), question_run_id])
        )
    change_set.summary_json = summary
    if target_catalog_fingerprint is not None:
        change_set.target_catalog_fingerprint = target_catalog_fingerprint
    if status is not None:
        change_set.status = status
    if error_summary is not None:
        change_set.error_summary = error_summary


def serialize_change_set(change_set: DomainChangeSet) -> dict[str, object]:
    return {
        "change_set_id": change_set.public_id,
        "domain_code": change_set.domain_code,
        "status": change_set.status,
        "mode": change_set.mode,
        "base_catalog_fingerprint": change_set.base_catalog_fingerprint,
        "target_catalog_fingerprint": change_set.target_catalog_fingerprint,
        "summary": change_set.summary_json or {},
        "error_summary": change_set.error_summary,
        "activated_at": change_set.activated_at.isoformat() if change_set.activated_at else None,
        "created_at": change_set.created_at.isoformat() if change_set.created_at else None,
    }


def activate_change_set(db: Session, change_set: DomainChangeSet) -> dict[str, object]:
    """Activate a validated incremental update after its staged questions are complete.

    Current MVP keeps one source document per change set.  That preserves the
    existing isolated-index CAS boundary while still allowing question work to
    be split into any number of XLSX batches.
    """
    if change_set.status != "ready_to_activate":
        raise DomainChangeSetError("DOMAIN_CHANGE_SET_NOT_READY_TO_ACTIVATE")
    if active_catalog_fingerprint(db, change_set.domain_code) != change_set.base_catalog_fingerprint:
        raise DomainChangeSetError("DOMAIN_CHANGE_SET_BASE_CATALOG_CHANGED")
    documents = list(
        db.scalars(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.change_set_id == change_set.id)
            .order_by(KnowledgeDocument.id)
        )
    )
    if len(documents) != 1:
        raise DomainChangeSetError("DOMAIN_CHANGE_SET_REQUIRES_SINGLE_DOCUMENT")
    document = documents[0]
    run = db.scalar(
        select(KnowledgeImportRun)
        .where(KnowledgeImportRun.document_id == document.id)
        .order_by(KnowledgeImportRun.id.desc())
        .limit(1)
    )
    if run is None or run.status not in {"ready_for_questions", "ready_to_publish"}:
        raise DomainChangeSetError("DOMAIN_CHANGE_SET_IMPORT_NOT_READY")

    from app.services import candidate_index_job
    from app.services.domain_api_service import DomainApiService
    from app.services.knowledge_import_publish_service import activate_import_candidate
    from app.services.question_import_service import question_gap_slots

    if question_gap_slots(db, change_set.domain_code, change_set_id=change_set.id):
        raise DomainChangeSetError("DOMAIN_CHANGE_SET_QUESTION_GAPS_REMAIN")
    job = candidate_index_job.latest_job(
        db, change_set.domain_code, source_document_id=document.id
    )
    if job is None:
        raise DomainChangeSetError("DOMAIN_CHANGE_SET_INDEX_MISSING")
    result: dict[str, object] | None = None
    try:
        result = activate_import_candidate(db, document, job, commit=False)
        staged_questions = list(
            db.scalars(
                select(DiagnosticQuestion).where(
                    DiagnosticQuestion.domain_code == change_set.domain_code,
                    DiagnosticQuestion.status == "staged",
                )
            )
        )
        promoted = 0
        for question in staged_questions:
            answer = dict(question.answer_key_json or {})
            if str(answer.get("pending_change_set_id") or "") != str(change_set.id):
                continue
            answer.pop("pending_change_set_id", None)
            question.answer_key_json = answer
            question.status = "active"
            promoted += 1
        db.flush()
        readiness = DomainApiService(db).readiness(change_set.domain_code)
        if not readiness["passed"]:
            raise DomainChangeSetError("DOMAIN_CHANGE_SET_ACTIVATION_READINESS_FAILED")
        domain = db.scalar(select(Domain).where(Domain.domain_code == change_set.domain_code))
        if domain is not None:
            domain.status = "ready"
        change_set.status = "activated"
        change_set.activated_at = datetime.now(UTC)
        change_set.target_catalog_fingerprint = active_catalog_fingerprint(db, change_set.domain_code)
        change_set.error_summary = None
        db.commit()
    except Exception:
        db.rollback()
        if result is not None:
            builder = result.get("_builder")
            previous = result.get("_previous_manifest")
            if builder is not None:
                try:
                    builder.restore_manifest(change_set.domain_code, previous)
                except Exception:
                    pass
        raise
    if result is None:
        raise DomainChangeSetError("DOMAIN_CHANGE_SET_ACTIVATION_RESULT_MISSING")
    builder = result.pop("_builder", None)
    result.pop("_previous_manifest", None)
    manifest_payload = result.pop("_manifest_payload", None)
    try:
        result["old_collections_deleted"] = (
            builder.cleanup_after_activation(manifest_payload)
            if builder is not None and isinstance(manifest_payload, dict)
            else 0
        )
    except Exception:
        result["old_collections_deleted"] = 0
    return {
        **serialize_change_set(change_set),
        "promoted_question_count": promoted,
        "readiness": readiness,
        "activation": result,
    }


def cancel_change_set(db: Session, change_set: DomainChangeSet) -> dict[str, object]:
    """Discard all staged assets of an incremental change before activation.

    The active catalog and manifest are intentionally untouched. Import runs and
    source documents remain as withdrawn audit records, while their temporary
    knowledge, question and candidate-index assets are removed.
    """
    if change_set.status not in CANCELLABLE_STATUSES:
        raise DomainChangeSetError("DOMAIN_CHANGE_SET_NOT_CANCELLABLE")

    documents = list(
        db.scalars(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.change_set_id == change_set.id)
            .order_by(KnowledgeDocument.id)
        )
    )
    document_ids = [document.id for document in documents]
    staged_items = list(
        db.scalars(
            select(KnowledgeItem).where(
                KnowledgeItem.source_document_id.in_(document_ids),
                KnowledgeItem.status == "staged",
            )
        )
    ) if document_ids else []
    staged_item_ids = [item.id for item in staged_items]
    staged_questions = list(
        db.scalars(
            select(DiagnosticQuestion).where(
                DiagnosticQuestion.domain_code == change_set.domain_code,
                DiagnosticQuestion.status == "staged",
            )
        )
    )
    staged_questions = [
        question
        for question in staged_questions
        if str((question.answer_key_json or {}).get("pending_change_set_id") or "")
        == str(change_set.id)
    ]
    staged_question_ids = [question.id for question in staged_questions]
    if staged_question_ids and db.scalar(
        select(AnswerRecord.id).where(AnswerRecord.question_id.in_(staged_question_ids)).limit(1)
    ) is not None:
        raise DomainChangeSetError("DOMAIN_CHANGE_SET_STAGED_QUESTION_REFERENCED")

    question_runs = list(
        db.scalars(select(QuestionImportRun).where(QuestionImportRun.change_set_id == change_set.id))
    )
    for run in question_runs:
        run.status = "cancelled"
        run.error_summary = "关联知识变更已取消，题库导入不再可发布"
        for row in db.scalars(select(QuestionImportRow).where(QuestionImportRow.run_id == run.id)):
            row.status = "cancelled"
            row.validation_errors_json = ["DOMAIN_CHANGE_SET_CANCELLED"]

    candidate_manifests: list[dict[str, object]] = []
    if document_ids:
        for job in db.scalars(
            select(IndexBuildJob).where(IndexBuildJob.source_document_id.in_(document_ids))
        ):
            manifest = (job.result_json or {}).get("candidate_manifest")
            if isinstance(manifest, dict):
                candidate_manifests.append(manifest)
            job.message = "关联知识变更已取消，候选索引已废弃"

        db.execute(delete(KnowledgeRelation).where(KnowledgeRelation.source_document_id.in_(document_ids)))
        if staged_item_ids:
            db.execute(
                delete(KnowledgeItemSource).where(KnowledgeItemSource.knowledge_item_id.in_(staged_item_ids))
            )
        for question in staged_questions:
            db.delete(question)
        for item in staged_items:
            db.delete(item)
        for document in documents:
            document.status = "withdrawn"
            document.deleted_at = datetime.now(UTC)
            document.error_summary = "待启用知识变更已取消，未影响正式知识库"

    summary = dict(change_set.summary_json or {})
    summary["cancelled"] = {
        "documents": [document.public_id for document in documents],
        "staged_knowledge_items": len(staged_items),
        "staged_questions": len(staged_questions),
        "question_runs": [run.public_id for run in question_runs],
    }
    change_set.summary_json = summary
    change_set.status = "cancelled"
    change_set.error_summary = "已取消，暂存资产已撤回"
    db.commit()
    return {
        **serialize_change_set(change_set),
        "staged_knowledge_items_removed": len(staged_items),
        "staged_questions_removed": len(staged_questions),
        "question_runs_cancelled": len(question_runs),
        "candidate_manifests": candidate_manifests,
    }


def catalog_snapshot_hash(items: list[dict[str, object]]) -> str:
    encoded = json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()
