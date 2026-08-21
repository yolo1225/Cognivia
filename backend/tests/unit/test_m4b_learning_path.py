from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import (
    AnswerRecord,
    Base,
    DiagnosticQuestion,
    KnowledgeItem,
    KnowledgeRelation,
    Learner,
    LearningPath,
)
from app.services.learning_path_service import (
    complete_path_node,
    node_id_for,
    normalize_path_payload,
    normalize_path_for_domain,
    verify_path_node,
)


def _db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_old_path_is_upgraded_and_refresh_inherits_completion() -> None:
    old = normalize_path_payload(
        {"stages": [{"name": "基础", "knowledge_ids": ["k1", "k2"]}]}
    )
    assert old["current_node_id"] == node_id_for("k1")
    old["node_states"][node_id_for("k1")]["status"] = "completed"
    old["node_states"][node_id_for("k1")]["completion_evidence_ids"] = ["answer_record:1"]
    refreshed = normalize_path_payload(
        {"stages": [{"name": "新路径", "knowledge_ids": ["k1", "k3"]}]},
        previous_payload=old,
    )
    assert refreshed["node_states"][node_id_for("k1")]["status"] == "completed"
    assert refreshed["node_states"][node_id_for("k3")]["status"] == "current"
    assert node_id_for("k2") in refreshed["retired_node_states"]


def test_verified_server_evidence_completes_and_unlocks_next_node() -> None:
    db = _db()
    learner = Learner(public_id="learner_path", target_domain="ai_app_dev")
    knowledge = KnowledgeItem(
        public_id="k1",
        domain_code="ai_app_dev",
        name="K1",
        category="test",
        difficulty=2,
        tags_json=[],
        content_md="content",
        source_title="source",
        license_note="test",
        needs_reembedding=False,
    )
    db.add_all([learner, knowledge])
    db.flush()
    question = DiagnosticQuestion(
        public_id="q1",
        domain_code="ai_app_dev",
        knowledge_item_id=knowledge.id,
        question_type="single_choice",
        stem="question",
        options_json=[],
        answer_key_json={},
        difficulty=2,
    )
    db.add(question)
    db.flush()
    record = AnswerRecord(
        learner_id=learner.id,
        question_id=question.id,
        knowledge_item_id=knowledge.id,
        score=0.9,
        is_correct=True,
        scoring_status="scored",
        answer_summary_json={"confirmed": True, "contract_evidence_type": "scored_quiz"},
    )
    path = LearningPath(
        public_id="path_1",
        learner_id=learner.id,
        domain_code="ai_app_dev",
        path_json={"stages": [{"name": "path", "knowledge_ids": ["k1", "k2"]}]},
    )
    db.add_all([record, path])
    db.commit()
    evidence_id = f"answer_record:{record.id}"

    verified = verify_path_node(
        db,
        path_id=path.public_id,
        node_id=node_id_for("k1"),
        learner_public_id=learner.public_id,
    )
    assert verified["verified"] is True
    completed = complete_path_node(
        db,
        path_id=path.public_id,
        node_id=node_id_for("k1"),
        learner_public_id=learner.public_id,
        evidence_ids=[evidence_id],
    )
    assert completed["path"]["current_node_id"] == node_id_for("k2")
    repeated = complete_path_node(
        db,
        path_id=path.public_id,
        node_id=node_id_for("k1"),
        learner_public_id=learner.public_id,
        evidence_ids=[evidence_id],
    )
    assert repeated["completed_node_id"] == node_id_for("k1")


def test_prerequisites_keep_nodes_locked_and_unlock_all_successors() -> None:
    db = _db()
    learner = Learner(public_id="learner_branch", target_domain="ai_app_dev")
    items = [
        KnowledgeItem(
            public_id=knowledge_id,
            domain_code="ai_app_dev",
            name=knowledge_id,
            category="test",
            difficulty=2,
            content_md=f"content {knowledge_id}",
            source_title="source",
            license_note="test",
            status="published",
        )
        for knowledge_id in ("k1", "k2", "k3")
    ]
    db.add_all([learner, *items])
    db.flush()
    db.add_all(
        [
            KnowledgeRelation(
                source_item_id=items[0].id,
                target_item_id=items[1].id,
                relation_type="prerequisite",
            ),
            KnowledgeRelation(
                source_item_id=items[0].id,
                target_item_id=items[2].id,
                relation_type="prerequisite",
            ),
        ]
    )
    question = DiagnosticQuestion(
        public_id="q_branch",
        domain_code="ai_app_dev",
        knowledge_item_id=items[0].id,
        question_type="single_choice",
        stem="question",
        options_json=["A"],
        answer_key_json={"correct_option": 0},
        difficulty=2,
    )
    db.add(question)
    db.flush()
    record = AnswerRecord(
        learner_id=learner.id,
        question_id=question.id,
        knowledge_item_id=items[0].id,
        score=0.9,
        is_correct=True,
        scoring_status="scored",
        answer_summary_json={"confirmed": True, "contract_evidence_type": "scored_quiz"},
    )
    path = LearningPath(
        public_id="path_branch",
        learner_id=learner.id,
        domain_code="ai_app_dev",
        path_json={"stages": [{"name": "path", "knowledge_ids": ["k1", "k2", "k3"]}]},
    )
    db.add_all([record, path])
    db.commit()

    initial = normalize_path_for_domain(
        db,
        domain_code="ai_app_dev",
        payload=path.path_json,
    )
    assert initial["node_states"][node_id_for("k1")]["status"] == "current"
    assert initial["node_states"][node_id_for("k2")]["status"] == "locked"
    assert initial["node_states"][node_id_for("k3")]["status"] == "locked"

    completed = complete_path_node(
        db,
        path_id=path.public_id,
        node_id=node_id_for("k1"),
        learner_public_id=learner.public_id,
        evidence_ids=[f"answer_record:{record.id}"],
    )["path"]

    assert completed["node_states"][node_id_for("k2")]["status"] == "current"
    assert completed["node_states"][node_id_for("k3")]["status"] == "current"
    assert completed["current_node_id"] == node_id_for("k2")


def test_prerequisite_refresh_inherits_completed_knowledge() -> None:
    db = _db()
    first, second = [
        KnowledgeItem(
            public_id=knowledge_id,
            domain_code="ai_app_dev",
            name=knowledge_id,
            category="test",
            difficulty=2,
            content_md="content",
            source_title="source",
            license_note="test",
            status="published",
        )
        for knowledge_id in ("k1", "k2")
    ]
    db.add_all([first, second])
    db.flush()
    db.add(
        KnowledgeRelation(
            source_item_id=first.id,
            target_item_id=second.id,
            relation_type="prerequisite",
        )
    )
    db.commit()
    previous = normalize_path_for_domain(
        db,
        domain_code="ai_app_dev",
        payload={"stages": [{"name": "old", "knowledge_ids": ["k1", "k2"]}]},
    )
    previous["node_states"][node_id_for("k1")]["status"] = "completed"
    previous["node_states"][node_id_for("k1")]["completion_evidence_ids"] = [
        "answer_record:1"
    ]

    refreshed = normalize_path_for_domain(
        db,
        domain_code="ai_app_dev",
        payload={"stages": [{"name": "new", "knowledge_ids": ["k1", "k2"]}]},
        previous_payload=previous,
    )

    assert refreshed["node_states"][node_id_for("k1")]["status"] == "completed"
    assert refreshed["node_states"][node_id_for("k2")]["status"] == "current"
