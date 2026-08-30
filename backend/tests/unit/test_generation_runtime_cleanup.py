from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.models import (
    AgentMessageRecord,
    AgentRun,
    AnswerRecord,
    Base,
    DiagnosticQuestion,
    DiagnosticSession,
    Domain,
    GenerationTask,
    GraphCheckpoint,
    KnowledgeDocument,
    KnowledgeItem,
    KnowledgeUpdateImpact,
    Learner,
    LearnerProfile,
    LearningPackageResource,
    LearningPath,
    LearningResource,
    ReviewReport,
    TutoringMessage,
    TutoringSession,
    User,
)
from app.models.feedback import Feedback
from app.services.generation_runtime_cleanup_service import (
    GenerationRuntimeCleanupBlocked,
    clear_generation_runtime,
)


def _session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'cleanup.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return Session(engine)


def _seed(db: Session) -> dict[str, int]:
    learner = Learner(public_id="learner_cleanup")
    db.add(learner)
    db.flush()
    user = User(
        public_id="user_cleanup",
        username="cleanup",
        password_hash="hash",
        role="learner",
        display_name="Cleanup",
        learner_id=learner.id,
    )
    domain = Domain(domain_code="cleanup_domain", name="Cleanup", status="ready")
    document = KnowledgeDocument(
        public_id="doc_cleanup",
        domain_code="cleanup_domain",
        original_name="source.md",
        file_type="markdown",
        sha256="a" * 64,
    )
    db.add_all([user, domain, document])
    db.flush()
    knowledge = KnowledgeItem(
        public_id="knowledge_cleanup",
        domain_code="cleanup_domain",
        name="Concept",
        category="concept",
        content_md="Evidence",
        source_title="source",
        source_document_id=document.id,
        status="published",
    )
    profile = LearnerProfile(
        public_id="profile_cleanup",
        learner_id=learner.id,
        domain_code="cleanup_domain",
        diagnosis_completed=True,
    )
    db.add_all([knowledge, profile])
    db.flush()
    path = LearningPath(
        public_id="path_cleanup",
        learner_id=learner.id,
        profile_id=profile.id,
        domain_code="cleanup_domain",
    )
    question = DiagnosticQuestion(
        public_id="question_cleanup",
        domain_code="cleanup_domain",
        knowledge_item_id=knowledge.id,
        question_type="single_choice",
        stem="Question",
    )
    db.add_all([path, question])
    db.flush()
    diagnostic = DiagnosticSession(
        public_id="diagnostic_cleanup",
        learner_id=learner.id,
        domain_code="cleanup_domain",
        status="scored",
        profile_id=profile.id,
        learning_path_id=path.id,
    )
    answer = AnswerRecord(
        learner_id=learner.id,
        question_id=question.id,
        knowledge_item_id=knowledge.id,
        session_id=diagnostic.public_id,
        score=1,
        is_correct=True,
        confidence=1,
    )
    task = GenerationTask(
        public_id="task_cleanup",
        learner_id=learner.id,
        profile_id=profile.id,
        domain_code="cleanup_domain",
        status="running",
    )
    db.add_all([diagnostic, answer, task])
    db.flush()
    resource = LearningResource(
        public_id="resource_cleanup",
        generation_task_id=task.id,
        resource_type="lecture",
        title="Resource",
        content_md="Body",
    )
    db.add(resource)
    db.flush()
    task.source_resource_id = resource.id
    resource.previous_resource_id = resource.id
    tutoring_session = TutoringSession(
        public_id="tutoring_cleanup",
        learner_id=learner.id,
        resource_id=resource.id,
    )
    db.add(tutoring_session)
    db.flush()
    tutoring_message = TutoringMessage(
        public_id="message_cleanup",
        session_id=tutoring_session.id,
        sender="learner",
        message_type="text",
        content="Question",
    )
    db.add(tutoring_message)
    db.flush()
    feedback = Feedback(
        resource_id=resource.id,
        learner_id=learner.id,
        feedback_type="comment",
        tutoring_session_id=tutoring_session.id,
        tutoring_message_id=tutoring_message.id,
    )
    db.add(feedback)
    db.flush()
    tutoring_message.feedback_id = feedback.id
    profile.trigger_feedback_id = feedback.id
    task.source_feedback_id = feedback.id
    db.add_all(
        [
            ReviewReport(resource_id=resource.id, task_id=task.id),
            LearningPackageResource(package_task_id=task.id, resource_id=resource.id),
            KnowledgeUpdateImpact(
                public_id="impact_cleanup",
                package_task_id=task.id,
                resolved_by_task_id=task.id,
            ),
            AgentRun(generation_task_id=task.id, agent_name="review", status="completed"),
            AgentRun(agent_name="legacy_review", status="completed"),
            AgentMessageRecord(
                session_id=task.public_id,
                task_id=task.public_id,
                sender="a",
                receiver="b",
                message_type="event",
            ),
            GraphCheckpoint(
                task_id=task.public_id,
                checkpoint_id="checkpoint_cleanup",
            ),
        ]
    )
    db.commit()
    return {
        model.__tablename__: int(db.scalar(select(func.count()).select_from(model)) or 0)
        for model in (
            User,
            Learner,
            DiagnosticSession,
            DiagnosticQuestion,
            AnswerRecord,
            LearnerProfile,
            LearningPath,
            Domain,
            KnowledgeItem,
            KnowledgeDocument,
        )
    }


def test_cleanup_refuses_active_tasks_until_services_are_stopped(tmp_path: Path) -> None:
    with _session(tmp_path) as db:
        _seed(db)
        with pytest.raises(GenerationRuntimeCleanupBlocked):
            clear_generation_runtime(db, manifest_root=tmp_path / "candidate-index")


def test_cleanup_is_idempotent_and_preserves_learning_state(tmp_path: Path) -> None:
    with _session(tmp_path) as db:
        preserved = _seed(db)
        manifest = tmp_path / "candidate-index" / "cleanup_domain" / "manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{"index_version":"kept"}', encoding="utf-8")
        export_dir = tmp_path / "exports"
        export_dir.mkdir()
        (export_dir / "res_cleanup.md").write_text("old", encoding="utf-8")
        (export_dir / "learning_package_task_cleanup.zip").write_bytes(b"old")
        (export_dir / ".gitkeep").write_text("", encoding="utf-8")

        first = clear_generation_runtime(
            db,
            services_stopped=True,
            export_dir=export_dir,
            manifest_root=tmp_path / "candidate-index",
        )
        db.commit()
        second = clear_generation_runtime(
            db,
            services_stopped=True,
            export_dir=export_dir,
            manifest_root=tmp_path / "candidate-index",
        )
        db.commit()

        assert first["deleted"]["generation_tasks"] == 1
        assert first["deleted"]["learning_resources"] == 1
        assert first["deleted"]["agent_runs"] == 2
        assert first["deleted"]["export_files"] == 2
        assert sum(second["deleted"].values()) == 0
        assert {
            table: first["preserved_counts"][table] for table in preserved
        } == preserved
        assert all(
            int(db.scalar(select(func.count()).select_from(model)) or 0) == 0
            for model in (
                GenerationTask,
                LearningResource,
                ReviewReport,
                LearningPackageResource,
                KnowledgeUpdateImpact,
                AgentRun,
                AgentMessageRecord,
                GraphCheckpoint,
                Feedback,
                TutoringMessage,
                TutoringSession,
            )
        )
        assert manifest.read_text(encoding="utf-8") == '{"index_version":"kept"}'
        assert (export_dir / ".gitkeep").exists()
