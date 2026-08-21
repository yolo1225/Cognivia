from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents.contracts import QUALITY_RULE_VERSION
from app.models import (
    Base,
    Domain,
    Feedback,
    GenerationTask,
    KnowledgeItem,
    Learner,
    LearnerProfile,
    LearningPackageResource,
    LearningResource,
)
from app.services.feedback_service import create_feedback_task
from app.services.resource_tutoring_service import _resource_knowledge


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_resource_tutoring_and_feedback_inherit_source_domain() -> None:
    db = _db()
    db.add_all(
        [
            Domain(domain_code="domain_a", name="领域 A", config_json={}),
            Domain(domain_code="domain_b", name="领域 B", config_json={}),
        ]
    )
    learner = Learner(public_id="learner_a", target_domain="domain_a")
    db.add(learner)
    db.flush()
    profile = LearnerProfile(
        public_id="profile_a",
        learner_id=learner.id,
        domain_code="domain_a",
        ability_profile_json={},
        weak_knowledge_json=[],
    )
    db.add(profile)
    knowledge_a = KnowledgeItem(
        public_id="knowledge_a",
        domain_code="domain_a",
        name="A",
        category="A",
        content_md="A evidence",
        source_title="A source",
    )
    knowledge_b = KnowledgeItem(
        public_id="knowledge_b",
        domain_code="domain_b",
        name="B",
        category="B",
        content_md="B evidence",
        source_title="B source",
    )
    db.add_all([knowledge_a, knowledge_b])
    db.flush()
    task = GenerationTask(
        public_id="task_a",
        learner_id=learner.id,
        profile_id=profile.id,
        domain_code="domain_a",
        status="completed",
        decision="completed",
        resource_types_json=["lecture"],
        package_quality_json={"quality_rule_version": QUALITY_RULE_VERSION},
        is_current_package=True,
    )
    db.add(task)
    db.flush()
    resource = LearningResource(
        public_id="resource_a",
        generation_task_id=task.id,
        resource_type="lecture",
        title="A resource",
        content_md="content",
        sources_json=[
            {"knowledge_id": "knowledge_a"},
            {"knowledge_id": "knowledge_b"},
        ],
        review_status="passed",
        is_current=True,
    )
    db.add(resource)
    db.flush()
    db.add(
        LearningPackageResource(
            package_task_id=task.id,
            resource_id=resource.id,
            membership_type="generated",
            freshness_status="current",
            sort_order=1,
        )
    )
    feedback = Feedback(
        resource_id=resource.id,
        learner_id=learner.id,
        feedback_type="tutoring_message",
        feedback_summary_json={},
        triggered_action="review",
        comment="check",
    )
    db.add(feedback)
    db.flush()

    assert [item.public_id for item in _resource_knowledge(db, resource)] == ["knowledge_a"]
    feedback_task = create_feedback_task(
        db,
        learner=learner,
        profile=profile,
        resource=resource,
        feedback=feedback,
    )
    assert feedback_task.domain_code == "domain_a"


def test_feedback_rejects_profile_from_another_domain() -> None:
    db = _db()
    learner = Learner(public_id="learner_a", target_domain="domain_a")
    db.add(learner)
    db.flush()
    profile = LearnerProfile(
        public_id="profile_b",
        learner_id=learner.id,
        domain_code="domain_b",
        ability_profile_json={},
        weak_knowledge_json=[],
    )
    db.add(profile)
    db.flush()
    task = GenerationTask(
        public_id="task_a",
        learner_id=learner.id,
        profile_id=profile.id,
        domain_code="domain_a",
        status="completed",
        decision="completed",
        resource_types_json=["lecture"],
        package_quality_json={"quality_rule_version": QUALITY_RULE_VERSION},
        is_current_package=True,
    )
    db.add(task)
    db.flush()
    resource = LearningResource(
        public_id="resource_a",
        generation_task_id=task.id,
        resource_type="lecture",
        title="A",
        content_md="A",
        review_status="passed",
    )
    db.add(resource)
    db.flush()
    db.add(
        LearningPackageResource(
            package_task_id=task.id,
            resource_id=resource.id,
            membership_type="generated",
            freshness_status="current",
            sort_order=1,
        )
    )
    feedback = Feedback(
        resource_id=resource.id,
        learner_id=learner.id,
        feedback_type="quick_tag",
        feedback_summary_json={},
        triggered_action="review",
        comment="check",
    )
    db.add(feedback)
    db.flush()

    try:
        create_feedback_task(
            db,
            learner=learner,
            profile=profile,
            resource=resource,
            feedback=feedback,
        )
    except ValueError as exc:
        assert str(exc) == "feedback_domain_mismatch"
    else:
        raise AssertionError("cross-domain profile must be rejected")
