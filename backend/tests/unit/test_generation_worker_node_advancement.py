from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, GenerationTask, Learner, LearnerProfile, LearningResource
from app.workers.generation_worker import _node_advancement_package_failure


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _result(decision: str) -> SimpleNamespace:
    return SimpleNamespace(decision=SimpleNamespace(value=decision))


def test_node_advancement_never_completes_without_all_three_passed_resources() -> None:
    factory = _session_factory()
    with factory() as db:
        learner = Learner(public_id="learner_node_package", target_domain="ai_app_dev")
        db.add(learner)
        db.flush()
        profile = LearnerProfile(
            public_id="profile_node_package",
            learner_id=learner.id,
            domain_code="ai_app_dev",
        )
        db.add(profile)
        db.flush()
        task = GenerationTask(
            public_id="task_node_package",
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
            event_type="node_advancement",
            resource_types_json=["lecture", "practice_guide", "graded_quiz"],
        )
        db.add(task)
        db.flush()

        assert _node_advancement_package_failure(db, task, _result("no_change")) == "node_package_not_generated"

        db.add(
            LearningResource(
                public_id="resource_node_lecture",
                generation_task_id=task.id,
                resource_type="lecture",
                title="讲义",
                content_md="content",
                review_status="passed",
            )
        )
        db.flush()
        assert _node_advancement_package_failure(db, task, _result("completed")) == "node_package_resources_incomplete"

        for resource_type in ("practice_guide", "graded_quiz"):
            db.add(
                LearningResource(
                    public_id=f"resource_node_{resource_type}",
                    generation_task_id=task.id,
                    resource_type=resource_type,
                    title=resource_type,
                    content_md="content",
                    review_status="passed",
                )
            )
        db.flush()
        assert _node_advancement_package_failure(db, task, _result("completed")) is None
