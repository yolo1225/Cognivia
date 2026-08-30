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
    node_id_for as atomic_node_id_for,
    unit_node_id_for,
    normalize_path_payload,
    normalize_path_for_domain,
    verify_path_node,
)


def _unit_id(knowledge_id: str) -> str:
    return unit_node_id_for([knowledge_id])


node_id_for = _unit_id


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
    assert old["current_node_id"] == atomic_node_id_for("k1")
    old["node_states"][atomic_node_id_for("k1")]["status"] = "completed"
    old["node_states"][atomic_node_id_for("k1")]["completion_evidence_ids"] = ["answer_record:1"]
    refreshed = normalize_path_payload(
        {"stages": [{"name": "新路径", "knowledge_ids": ["k1", "k3"]}]},
        previous_payload=old,
    )
    assert refreshed["node_states"][atomic_node_id_for("k1")]["status"] == "completed"
    assert refreshed["node_states"][atomic_node_id_for("k3")]["status"] == "current"
    assert atomic_node_id_for("k2") in refreshed["retired_node_states"]


def test_profile_revision_keeps_completed_prefix_and_current_order() -> None:
    previous = normalize_path_payload(
        {"stages": [{"name": "old", "knowledge_ids": ["k1", "k2", "k3"]}]}
    )
    previous["node_states"][atomic_node_id_for("k1")].update(
        {
            "status": "completed",
            "completed_at": "2026-08-23T00:00:00+00:00",
            "completion_evidence_ids": ["answer_record:1"],
        }
    )
    previous["node_states"][atomic_node_id_for("k2")]["status"] = "current"
    previous["node_states"][atomic_node_id_for("k3")]["status"] = "locked"

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
    previous["node_states"][atomic_node_id_for("mastered")].update(
        {"status": "completed", "completion_evidence_ids": ["answer_record:2"]}
    )
    previous["node_states"][atomic_node_id_for("next")]["status"] = "current"

    revised = normalize_path_payload(
        {"stages": [{"name": "new", "knowledge_ids": ["next"]}]},
        previous_payload=previous,
        prerequisites_by_knowledge={"mastered": set(), "next": set()},
    )

    assert revised["stages"][0]["knowledge_ids"] == ["mastered", "next"]
    assert atomic_node_id_for("mastered") not in revised["retired_node_states"]
    assert revised["current_node_id"] == atomic_node_id_for("next")


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
    previous["node_states"][atomic_node_id_for("done")]["status"] = "completed"
    previous["node_states"][atomic_node_id_for("current")]["status"] = "current"

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
    assert atomic_node_id_for("remove") in revised["retired_node_states"]


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
        status="active",
        certification_status="certified",
        certification_rule_version="question-cert-v1",
        source_content_hash="sha256:" + "1" * 64,
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
    path.path_json = normalize_path_for_domain(
        db, domain_code="ai_app_dev", payload=path.path_json
    )
    path.path_json["node_states"][_unit_id("k1")]["completion_condition"][
        "question_count_min"
    ] = 1
    path.path_json["node_states"][_unit_id("k1")]["completion_condition"][
        "threshold"
    ] = 0.5
    db.commit()
    evidence_id = f"answer_record:{record.id}"

    verified = verify_path_node(
        db,
        path_id=path.public_id,
        node_id=_unit_id("k1"),
        learner_public_id=learner.public_id,
    )
    assert verified["verified"] is True
    completed = complete_path_node(
        db,
        path_id=path.public_id,
        node_id=_unit_id("k1"),
        learner_public_id=learner.public_id,
        evidence_ids=[evidence_id],
    )
    assert completed["path"]["current_node_id"] == node_id_for("k2")
    repeated = complete_path_node(
        db,
        path_id=path.public_id,
        node_id=_unit_id("k1"),
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
        status="active",
        certification_status="certified",
        certification_rule_version="question-cert-v1",
        source_content_hash="sha256:" + "2" * 64,
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
    path.path_json = normalize_path_for_domain(
        db, domain_code="ai_app_dev", payload=path.path_json
    )
    path.path_json["node_states"][_unit_id("k1")]["completion_condition"][
        "question_count_min"
    ] = 1
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
        node_id=_unit_id("k1"),
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


def test_unit_refresh_preserves_completed_and_current_units() -> None:
    db = _db()
    items = [
        KnowledgeItem(
            public_id=f"k{index}",
            domain_code="ai_app_dev",
            name=f"K{index}",
            category="test",
            difficulty=2,
            content_md="content",
            source_title="source",
            license_note="test",
            status="published",
        )
        for index in range(1, 7)
    ]
    db.add_all(items)
    db.commit()
    previous = normalize_path_for_domain(
        db,
        domain_code="ai_app_dev",
        payload={"stages": [{"name": "old", "knowledge_ids": [item.public_id for item in items]}]},
    )
    states = sorted(previous["node_states"].values(), key=lambda item: item["path_order"])
    completed, current = states[:2]
    completed.update(
        {
            "status": "completed",
            "completed_at": "2026-08-26T01:00:00+00:00",
            "completion_evidence_ids": ["answer_record:1"],
        }
    )
    current["status"] = "current"
    previous["current_node_id"] = current["path_node_id"]

    revised = normalize_path_for_domain(
        db,
        domain_code="ai_app_dev",
        payload={"stages": [{"name": "new", "knowledge_ids": ["k5", "k6", "k3", "k4"]}]},
        previous_payload=previous,
    )
    repeated = normalize_path_for_domain(
        db,
        domain_code="ai_app_dev",
        payload=revised,
        previous_payload=revised,
    )

    assert revised["node_states"][completed["path_node_id"]]["status"] == "completed"
    assert revised["node_states"][completed["path_node_id"]]["completion_evidence_ids"] == [
        "answer_record:1"
    ]
    assert revised["current_node_id"] == current["path_node_id"]
    assert repeated["current_node_id"] == current["path_node_id"]
