from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    AnswerRecord,
    Base,
    DiagnosticQuestion,
    Domain,
    KnowledgeItem,
    KnowledgeRelation,
    Learner,
    LearnerProfile,
)
from app.services.diagnostic_service import create_diagnostic_session, submit_diagnostic_session
from app.agents.profile_analysis_config import AI_APP_DEV_PROFILE_V2
from app.scripts.seed_data import seed_domain, seed_knowledge_items
from app.services.domain_runtime_service import DomainRuntimeError, load_profile_analysis_config


DIMENSIONS = ("theory", "practice", "problem_solving", "knowledge_breadth", "learning_speed")


def _weights(theory: float = 0.4) -> dict[str, float]:
    return {
        "theory": theory,
        "practice": 0.3,
        "problem_solving": 0.2,
        "knowledge_breadth": round(0.1 - (theory - 0.4), 10),
        "learning_speed": 0.0,
    }


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _domain(db: Session, code: str) -> Domain:
    row = Domain(
        domain_code=code,
        name=code,
        status="ready",
        config_json={
            "profile_policy": {"version": f"{code}_v1", "ability_dimensions": list(DIMENSIONS)}
        },
    )
    db.add(row)
    return row


def _item(
    db: Session,
    code: str,
    public_id: str,
    weights: dict | None = None,
    capabilities: list[str] | None = None,
) -> KnowledgeItem:
    row = KnowledgeItem(
        public_id=public_id,
        domain_code=code,
        name=public_id,
        category=f"{code}_category",
        difficulty=2,
        content_md="evidence",
        source_title="test",
        ability_weights_json=weights if weights is not None else _weights(),
        evidence_capabilities_json=capabilities or ["concept"],
        status="published",
    )
    db.add(row)
    db.flush()
    return row


def test_loads_two_domains_without_shared_catalog_or_weights() -> None:
    db = _db()
    _domain(db, "domain_a")
    _domain(db, "domain_b")
    first = _item(db, "domain_a", "shared_name", _weights(0.4))
    second = _item(db, "domain_a", "a_next", _weights(0.5))
    _item(db, "domain_b", "b_only", _weights(0.3))
    db.add(
        KnowledgeRelation(
            source_item_id=first.id, target_item_id=second.id, relation_type="prerequisite"
        )
    )
    db.commit()

    a = load_profile_analysis_config(db, "domain_a")
    b = load_profile_analysis_config(db, "domain_b")

    assert set(a.knowledge_catalog) == {"shared_name", "a_next"}
    assert a.knowledge_catalog["a_next"].prerequisite_ids == ("shared_name",)
    assert set(b.knowledge_catalog) == {"b_only"}
    assert a.ability_weights["shared_name"] != b.ability_weights["b_only"]


def test_rejects_missing_weights_and_cross_domain_relation() -> None:
    db = _db()
    _domain(db, "domain_a")
    _domain(db, "domain_b")
    missing = _item(db, "domain_a", "missing", {})
    other = _item(db, "domain_b", "other")
    db.commit()
    try:
        load_profile_analysis_config(db, "domain_a")
    except DomainRuntimeError as exc:
        assert str(exc) == "ability_weights_missing:missing"
    else:
        raise AssertionError("missing weights must be rejected")

    missing.ability_weights_json = _weights()
    db.add(
        KnowledgeRelation(
            source_item_id=missing.id, target_item_id=other.id, relation_type="prerequisite"
        )
    )
    db.commit()
    try:
        load_profile_analysis_config(db, "domain_a")
    except DomainRuntimeError as exc:
        assert str(exc) == "cross_domain_knowledge_relation"
    else:
        raise AssertionError("cross-domain relations must be rejected")


def test_second_domain_can_complete_an_isolated_diagnostic_and_profile(monkeypatch) -> None:
    db = _db()
    domain = _domain(db, "industrial_ops")
    domain.config_json = {
        **domain.config_json,
        "learning_directions": [
            {
                "value": "equipment",
                "label": "设备运维",
                "description": "设备安全和操作",
                "match_tags": ["equipment"],
            }
        ],
    }
    theory = _item(db, "industrial_ops", "safety_theory")
    practice = _item(
        db, "industrial_ops", "machine_operation", capabilities=["concept", "operation"]
    )
    practice.category = "设备实操"
    practice.tags_json = ["实操"]
    db.add(
        Learner(
            public_id="industrial_learner",
            target_domain="industrial_ops",
            education_level="本科",
            major="机械工程",
            direction_tags_json=["equipment"],
        )
    )
    for index in range(3):
        for item, suffix in ((theory, "theory"), (practice, "practice")):
            db.add(
                DiagnosticQuestion(
                    public_id=f"choice_{suffix}_{index}",
                    domain_code="industrial_ops",
                    knowledge_item_id=item.id,
                    question_type="single_choice",
                    stem=f"{suffix} choice {index}",
                    options_json=["A", "B"],
                    answer_key_json={"correct_option": 0},
                    difficulty=2,
                )
            )
    for index in range(2):
        for item, suffix in ((theory, "theory"), (practice, "practice")):
            db.add(
                DiagnosticQuestion(
                    public_id=f"short_{suffix}_{index}",
                    domain_code="industrial_ops",
                    knowledge_item_id=item.id,
                    question_type="short_answer",
                    stem=f"{suffix} short {index}",
                    answer_key_json={"rubric": ["x"]},
                    difficulty=2,
                )
            )
    db.commit()
    monkeypatch.setattr(
        "app.services.domain_runtime_service.candidate_rag_status",
        lambda code: {
            "ready": True,
            "domain_code": code,
            "active_collection": f"knowledge_{code}_candidate_test",
            "indexed_chunk_count": 2,
            "index_version": "test-v1",
            "embedding_model": "test-embedding",
        },
    )
    monkeypatch.setattr(
        "app.services.diagnostic_service.score_short_answer_batch",
        lambda items, **_kwargs: (
            {
                question.public_id: {
                    "question_id": question.public_id,
                    "total_score": 1.0,
                    "is_correct": True,
                    "rubric_version": "test-v1",
                    "confidence": 1.0,
                    "scoring_uncertain": False,
                    "ai_comment": "通过",
                    "criteria": [],
                    "matched_points": ["x"],
                    "missing_points": [],
                    "factual_errors": [],
                }
                for question, _answer in items
            },
            {"tokens_input": 0, "tokens_output": 0, "model_name": "fixture"},
        ),
    )

    result = create_diagnostic_session(
        db, learner_id="industrial_learner", domain_code="industrial_ops", question_count=10
    )

    assert result["domain_code"] == "industrial_ops"
    assert result["question_count"] == 10
    assert {item["question_id"] for item in result["questions"]} == {
        row.public_id
        for row in db.query(DiagnosticQuestion).filter_by(domain_code="industrial_ops")
    }
    submitted = submit_diagnostic_session(
        db,
        session_id=result["session_id"],
        learner_id="industrial_learner",
        domain_code="industrial_ops",
        answers=[
            {
                "question_id": item["question_id"],
                "answer": 0 if item["question_type"] == "single_choice" else "x",
            }
            for item in result["questions"]
        ],
    )
    assert submitted["profile_id"]
    assert (
        db.query(LearnerProfile).filter_by(public_id=submitted["profile_id"]).one().domain_code
        == "industrial_ops"
    )
    records = db.query(AnswerRecord).all()
    assert len(records) == 10
    assert {db.get(KnowledgeItem, record.knowledge_item_id).domain_code for record in records} == {
        "industrial_ops"
    }


def test_database_runtime_preserves_main_domain_profile_configuration() -> None:
    db = _db()
    seed_domain(db)
    seed_knowledge_items(db)
    db.commit()

    runtime = load_profile_analysis_config(db, "ai_app_dev")

    assert runtime.version == AI_APP_DEV_PROFILE_V2.version
    assert runtime.ability_weights == AI_APP_DEV_PROFILE_V2.ability_weights
    assert runtime.knowledge_catalog == AI_APP_DEV_PROFILE_V2.knowledge_catalog
    assert runtime.mastery_thresholds == AI_APP_DEV_PROFILE_V2.mastery_thresholds
