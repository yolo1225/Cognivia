from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    AnswerRecord,
    DiagnosticQuestion,
    GenerationTask,
    KnowledgeItem,
    Learner,
    LearnerProfile,
    LearningPath,
    LearningResource,
    MistakeReviewItem,
    ResourceQuizAttempt,
)
from app.models.base import Base
from app.services.node_mastery_service import (
    FORMAL_EVIDENCE_CONFIDENCE_FLOOR,
    affected_resource_types,
    build_node_gate,
)
from app.services.mistake_evidence_service import evaluate_mistake_evidence
from app.services.resource_quiz_attempt_service import backfill_completed_attempt_evidence
from app.services.learning_path_service import unit_node_id_for


def _knowledge(public_id: str) -> KnowledgeItem:
    return KnowledgeItem(
        public_id=public_id,
        domain_code="ai_app_dev",
        name=public_id,
        category="core",
        difficulty=3,
        content_md="content",
        source_title="source",
    )


def _record(
    db,
    *,
    learner: Learner,
    knowledge: KnowledgeItem,
    question_id: str,
    evidence_type: str,
    confidence: float = 1.0,
) -> AnswerRecord:
    question = DiagnosticQuestion(
        public_id=question_id,
        domain_code="ai_app_dev",
        knowledge_item_id=knowledge.id,
        question_type="single_choice",
        stem=question_id,
        options_json=["A", "B"],
        answer_key_json={"correct_option": 1},
        difficulty=3,
        status="active",
    )
    db.add(question)
    db.flush()
    record = AnswerRecord(
        learner_id=learner.id,
        question_id=question.id,
        knowledge_item_id=knowledge.id,
        session_id=f"session_{question_id}",
        score=1,
        is_correct=True,
        confidence=confidence,
        answer_summary_json={
            "evidence_type": evidence_type,
            "contract_evidence_type": "scored_quiz",
            "confirmed": True,
            "consumed_by_profile_id": None,
        },
    )
    db.add(record)
    db.flush()
    return record


def test_node_gate_uses_current_core_scope_and_requires_all_conditions() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        next_node_id = unit_node_id_for(["future"])
        learner = Learner(public_id="learner_gate", target_domain="ai_app_dev")
        db.add(learner)
        db.flush()
        profile = LearnerProfile(
            public_id="profile_gate",
            learner_id=learner.id,
            domain_code="ai_app_dev",
            profile_source="initial_diagnosis",
            diagnosis_completed=True,
        )
        db.add(profile)
        db.flush()
        current_a, current_b, future = (
            _knowledge("current_a"),
            _knowledge("current_b"),
            _knowledge("future"),
        )
        db.add_all([current_a, current_b, future])
        db.flush()
        path = LearningPath(
            public_id="path_gate",
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
            status="active",
            path_json={
                "stages": [
                    {
                        "name": "learning path",
                        "knowledge_ids": ["current_a", "current_b", "future"],
                    }
                ],
                "current_node_id": "unit:current",
                "node_states": {
                    "unit:current": {
                        "path_node_id": "unit:current",
                        "status": "current",
                        "knowledge_ids": ["current_a", "current_b"],
                        "focus_knowledge_ids": ["current_a", "current_b"],
                        "target_difficulty": 3,
                    },
                    next_node_id: {
                        "path_node_id": next_node_id,
                        "status": "locked",
                        "knowledge_ids": ["future"],
                        "focus_knowledge_ids": ["future"],
                        "target_difficulty": 3,
                        "path_order": 2,
                    }
                },
            },
        )
        db.add(path)
        db.flush()
        task = GenerationTask(
            public_id="task_gate",
            learner_id=learner.id,
            profile_id=profile.id,
            learning_path_id=path.id,
            path_node_id="unit:current",
            domain_code="ai_app_dev",
            status="completed",
            resource_types_json=["lecture", "practice_guide", "graded_quiz"],
            resource_knowledge_targets_json={
                "lecture": ["current_a"],
                "practice_guide": ["current_b"],
                "graded_quiz": ["current_a", "current_b"],
            },
        )
        db.add(task)
        db.flush()
        quiz = LearningResource(
            public_id="quiz_gate",
            generation_task_id=task.id,
            resource_type="graded_quiz",
            title="quiz",
            content_md="quiz",
            review_status="passed",
        )
        db.add(quiz)
        db.flush()
        db.add(ResourceQuizAttempt(
            public_id="quiz_attempt_gate",
            learner_id=learner.id,
            resource_id=quiz.id,
            status="completed",
        ))
        db.add(MistakeReviewItem(
            public_id="future_mistake",
            learner_id=learner.id,
            domain_code="ai_app_dev",
            knowledge_item_id=future.id,
            source_type="initial_diagnostic",
            source_record_id="future:1",
            question_type="single_choice",
            status="pending",
        ))
        blocking = MistakeReviewItem(
            public_id="current_mistake",
            learner_id=learner.id,
            domain_code="ai_app_dev",
            knowledge_item_id=current_a.id,
            source_type="initial_diagnostic",
            source_record_id="current:1",
            question_type="single_choice",
            status="pending",
        )
        db.add(blocking)
        profile.ability_profile_json = {
            "knowledge_state_v1": {
                "items": {
                    "current_a": {"status": "known"},
                    "current_b": {"status": "known"},
                }
            }
        }
        db.flush()
        profile_only = build_node_gate(db, path=path, profile=profile, package_task=task)
        assert profile_only["mastered_knowledge_count"] == 0
        assert profile_only["can_advance"] is False

        records = []
        for knowledge in (current_a, current_b):
            records.append(_record(
                db,
                learner=learner,
                knowledge=knowledge,
                question_id=f"{knowledge.public_id}_quiz",
                evidence_type="graded_quiz",
            ))
            records.append(_record(
                db,
                learner=learner,
                knowledge=knowledge,
                question_id=f"{knowledge.public_id}_validation",
                evidence_type="path_validation",
            ))
        db.flush()

        blocked = build_node_gate(db, path=path, profile=profile, package_task=task)
        assert blocked["mastered_knowledge_count"] == 2
        assert blocked["blocking_mistake_count"] == 1
        assert blocked["can_advance"] is False

        blocking.status = "consolidated"
        db.flush()
        ready = build_node_gate(db, path=path, profile=profile, package_task=task)
        assert ready["blocking_mistake_count"] == 0
        assert ready["quiz_completed"] is True
        assert ready["can_advance"] is True

        # A local resource replacement must not erase a completed formal quiz
        # from the same active path node.
        replacement_task = GenerationTask(
            public_id="task_gate_replacement",
            learner_id=learner.id,
            profile_id=profile.id,
            learning_path_id=path.id,
            path_node_id="unit:current",
            domain_code="ai_app_dev",
            status="completed",
            resource_types_json=["lecture"],
        )
        db.add(replacement_task)
        db.flush()
        assert build_node_gate(
            db, path=path, profile=profile, package_task=replacement_task
        )["quiz_completed"] is True

        # A profile can be revised before the final blocking mistake is cleared.
        # Evidence consumed by that current profile must still support route progress.
        for record in records:
            payload = dict(record.answer_summary_json or {})
            payload["consumed_by_profile_id"] = profile.id
            record.answer_summary_json = payload
        final_record = _record(
            db,
            learner=learner,
            knowledge=current_a,
            question_id="current_a_final_mistake_check",
            evidence_type="mistake_correction",
        )
        db.flush()
        result = evaluate_mistake_evidence(
            db,
            learner=learner,
            item=blocking,
            record=final_record,
            resource=quiz,
        )
        assert result["profile_result"]["profile_updated"] is False
        assert result["path_result"]["completed_node_id"] == "unit:current"
        assert result["path_result"]["current_node_id"] == next_node_id
        recommendation = result["resource_recommendation"]
        assert recommendation["path_id"] == "path_gate"
        assert recommendation["path_node_id"] == next_node_id
        assert recommendation["resource_types"] == ["lecture", "practice_guide", "graded_quiz"]
        assert recommendation["decision_type"] == "next_stage"
        assert recommendation["mode"] == "next_node"


def test_affected_resource_types_follow_knowledge_targets() -> None:
    task = GenerationTask(
        resource_knowledge_targets_json={
            "lecture": ["concept"],
            "practice_guide": ["practice"],
            "graded_quiz": ["concept", "practice"],
        }
    )
    assert affected_resource_types(
        package_task=task,
        affected_knowledge_ids=["practice"],
        fallback_resource_type="lecture",
    ) == ["practice_guide", "graded_quiz"]
    assert affected_resource_types(
        package_task=task,
        affected_knowledge_ids=["legacy"],
        fallback_resource_type="lecture",
    ) == ["lecture"]


def test_formal_evidence_confidence_floor_only_tolerates_float_storage_drift() -> None:
    assert 0.89 < FORMAL_EVIDENCE_CONFIDENCE_FLOOR < 0.9


def test_completed_quiz_evidence_backfill_is_idempotent() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        learner = Learner(public_id="learner_backfill", target_domain="ai_app_dev")
        knowledge = _knowledge("backfill_knowledge")
        db.add_all([learner, knowledge])
        db.flush()
        question = DiagnosticQuestion(
            public_id="backfill_reference_question",
            domain_code="ai_app_dev",
            knowledge_item_id=knowledge.id,
            question_type="single_choice",
            stem="backfill question",
            options_json=["A", "B"],
            answer_key_json={"correct_option": 0},
            difficulty=3,
        )
        profile = LearnerProfile(
            public_id="profile_backfill",
            learner_id=learner.id,
            domain_code="ai_app_dev",
            diagnosis_completed=True,
            profile_source="diagnostic",
        )
        db.add_all([question, profile])
        db.flush()
        task = GenerationTask(
            public_id="task_backfill",
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
            status="completed",
            resource_types_json=["graded_quiz"],
        )
        db.add(task)
        db.flush()
        resource = LearningResource(
            public_id="quiz_backfill",
            generation_task_id=task.id,
            resource_type="graded_quiz",
            title="quiz",
            content_md="quiz",
            version=1,
            review_status="passed",
            structured_content_json={
                "questions": [
                    {
                        "question_id": "generated_backfill_question",
                        "reference_question_ids": [question.public_id],
                        "question_type": "single_choice",
                        "knowledge_id": knowledge.public_id,
                    }
                ]
            },
        )
        db.add(resource)
        db.flush()
        db.add(
            ResourceQuizAttempt(
                public_id="attempt_backfill",
                learner_id=learner.id,
                resource_id=resource.id,
                resource_version=1,
                status="completed",
                answers_json={
                    "generated_backfill_question": {
                        "answer": 0,
                        "correct": True,
                    }
                },
            )
        )
        db.flush()

        assert backfill_completed_attempt_evidence(db) == 1
        assert backfill_completed_attempt_evidence(db) == 0
        rows = db.query(AnswerRecord).all()
        assert len(rows) == 1
        assert rows[0].answer_text == "0"
        assert rows[0].answer_summary_json["quiz_attempt_id"] == "attempt_backfill"
