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
    answer_path_node_assessment,
    complete_path_node,
    node_id_for,
    normalize_path_payload,
    normalize_path_for_domain,
    start_path_node_assessment,
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


def test_profile_revision_keeps_completed_prefix_and_current_order() -> None:
    previous = normalize_path_payload(
        {"stages": [{"name": "old", "knowledge_ids": ["k1", "k2", "k3"]}]}
    )
    previous["node_states"][node_id_for("k1")].update(
        {
            "status": "completed",
            "completed_at": "2026-08-23T00:00:00+00:00",
            "completion_evidence_ids": ["answer_record:1"],
        }
    )
    previous["node_states"][node_id_for("k2")]["status"] = "current"
    previous["node_states"][node_id_for("k3")]["status"] = "locked"

    revised = normalize_path_payload(
        {"stages": [{"name": "new", "knowledge_ids": ["k3", "k2"]}]},
        previous_payload=previous,
        prerequisites_by_knowledge={"k1": set(), "k2": set(), "k3": set()},
    )

    ordered = sorted(
        revised["node_states"].values(), key=lambda state: state["path_order"]
    )
    assert [state["knowledge_id"] for state in ordered] == ["k1", "k2", "k3"]
    assert [state["status"] for state in ordered] == ["completed", "current", "locked"]
    assert ordered[0]["completion_evidence_ids"] == ["answer_record:1"]


def test_removed_completed_knowledge_remains_visible_in_mainline() -> None:
    previous = normalize_path_payload(
        {"stages": [{"name": "old", "knowledge_ids": ["mastered", "next"]}]}
    )
    previous["node_states"][node_id_for("mastered")].update(
        {"status": "completed", "completion_evidence_ids": ["answer_record:2"]}
    )
    previous["node_states"][node_id_for("next")]["status"] = "current"

    revised = normalize_path_payload(
        {"stages": [{"name": "new", "knowledge_ids": ["next"]}]},
        previous_payload=previous,
        prerequisites_by_knowledge={"mastered": set(), "next": set()},
    )

    assert revised["stages"][0]["knowledge_ids"] == ["mastered", "next"]
    assert node_id_for("mastered") not in revised["retired_node_states"]
    assert revised["current_node_id"] == node_id_for("next")


def test_new_current_prerequisite_is_inserted_and_becomes_current() -> None:
    db = _db()
    items = [
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
        for knowledge_id in ("done", "prerequisite", "current", "future")
    ]
    db.add_all(items)
    db.flush()
    db.add(
        KnowledgeRelation(
            source_item_id=items[1].id,
            target_item_id=items[2].id,
            relation_type="prerequisite",
        )
    )
    db.commit()
    previous = normalize_path_for_domain(
        db,
        domain_code="ai_app_dev",
        payload={
            "stages": [
                {"name": "old", "knowledge_ids": ["done", "current", "future"]}
            ]
        },
    )
    previous["node_states"][node_id_for("done")]["status"] = "completed"
    previous["node_states"][node_id_for("current")]["status"] = "current"
    previous["node_states"][node_id_for("future")]["status"] = "locked"

    revised = normalize_path_for_domain(
        db,
        domain_code="ai_app_dev",
        payload={"stages": [{"name": "new", "knowledge_ids": ["current", "future"]}]},
        previous_payload=previous,
    )

    assert revised["stages"][0]["knowledge_ids"] == [
        "done",
        "prerequisite",
        "current",
        "future",
    ]
    assert revised["current_node_id"] == node_id_for("prerequisite")
    assert revised["revision_summary"]["inserted_knowledge_ids"] == ["prerequisite"]


def test_future_nodes_preserve_relative_order_and_retire_removed_nodes() -> None:
    previous = normalize_path_payload(
        {
            "stages": [
                {"name": "old", "knowledge_ids": ["done", "current", "keep", "remove"]}
            ]
        }
    )
    previous["node_states"][node_id_for("done")]["status"] = "completed"
    previous["node_states"][node_id_for("current")]["status"] = "current"

    revised = normalize_path_payload(
        {"stages": [{"name": "new", "knowledge_ids": ["new", "keep", "current"]}]},
        previous_payload=previous,
        prerequisites_by_knowledge={
            "done": set(),
            "current": set(),
            "keep": set(),
            "new": {"keep"},
        },
    )

    assert revised["stages"][0]["knowledge_ids"] == [
        "done",
        "current",
        "keep",
        "new",
    ]
    assert node_id_for("remove") in revised["retired_node_states"]


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


def test_prerequisites_keep_nodes_locked_and_choose_first_successor() -> None:
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
    assert completed["node_states"][node_id_for("k3")]["status"] == "locked"
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


def test_node_assessment_scores_idempotently_and_advances_only_on_pass() -> None:
    db = _db()
    learner = Learner(public_id="learner_assessment", target_domain="ai_app_dev")
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
    db.add_all([learner, first, second])
    db.flush()
    db.add(
        DiagnosticQuestion(
            public_id="q_assessment",
            domain_code="ai_app_dev",
            knowledge_item_id=first.id,
            question_type="single_choice",
            stem="验证题",
            options_json=["错误", "正确"],
            answer_key_json={"correct_option": 1},
            difficulty=2,
        )
    )
    path = LearningPath(
        public_id="path_assessment",
        learner_id=learner.id,
        domain_code="ai_app_dev",
        path_json={"stages": [{"name": "path", "knowledge_ids": ["k1", "k2"]}]},
    )
    db.add(path)
    db.commit()

    first_assessment = start_path_node_assessment(
        db,
        path_id=path.public_id,
        node_id=node_id_for("k1"),
        learner_public_id=learner.public_id,
    )
    failed, remedial_task = answer_path_node_assessment(
        db,
        path_id=path.public_id,
        node_id=node_id_for("k1"),
        assessment_id=first_assessment["assessment_id"],
        learner_public_id=learner.public_id,
        answer=0,
    )
    assert failed["passed"] is False
    assert remedial_task is None
    assert path.path_json["current_node_id"] == node_id_for("k1")

    second_assessment = start_path_node_assessment(
        db,
        path_id=path.public_id,
        node_id=node_id_for("k1"),
        learner_public_id=learner.public_id,
    )
    passed, remedial_task = answer_path_node_assessment(
        db,
        path_id=path.public_id,
        node_id=node_id_for("k1"),
        assessment_id=second_assessment["assessment_id"],
        learner_public_id=learner.public_id,
        answer=1,
    )
    repeated, repeated_task = answer_path_node_assessment(
        db,
        path_id=path.public_id,
        node_id=node_id_for("k1"),
        assessment_id=second_assessment["assessment_id"],
        learner_public_id=learner.public_id,
        answer=0,
    )
    assert passed["passed"] is True
    assert remedial_task is None
    assert repeated == passed
    assert repeated_task is None
    assert path.path_json["current_node_id"] == node_id_for("k2")
