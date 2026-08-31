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
from app.services.domain_runtime_service import (
    DomainRuntimeError,
    load_domain_runtime,
    load_profile_analysis_config,
)


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
                    answer_key_json={
                        "correct_option": 0,
                        "question_bank_uses": ["diagnosis"],
                        "assessment_dimension": "operation" if suffix == "practice" else "theory",
                    },
                    difficulty=2,
                    status="active",
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
                    answer_key_json={
                        "rubric": ["x"],
                        "question_bank_uses": ["diagnosis"],
                        "assessment_dimension": "operation" if suffix == "practice" else "theory",
                    },
                    difficulty=2,
                    status="active",
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


def test_safe_conceptual_runtime_does_not_require_operation_question_buckets(
    monkeypatch,
) -> None:
    db = _db()
    _domain(db, "concept_domain")
    concept = _item(db, "concept_domain", "concept_only")
    for index in range(6):
        db.add(
            DiagnosticQuestion(
                public_id=f"concept_choice_{index}",
                domain_code="concept_domain",
                knowledge_item_id=concept.id,
                question_type="single_choice",
                stem=f"choice {index}",
                options_json=["A", "B"],
                answer_key_json={
                    "correct_option": 0,
                    "question_bank_uses": ["diagnosis"],
                },
                difficulty=2,
                status="active",
            )
        )
    for index in range(4):
        db.add(
            DiagnosticQuestion(
                public_id=f"concept_short_{index}",
                domain_code="concept_domain",
                knowledge_item_id=concept.id,
                question_type="short_answer",
                stem=f"short {index}",
                answer_key_json={
                    "rubric": ["x"],
                    "question_bank_uses": ["diagnosis"],
                },
                difficulty=2,
                status="active",
            )
        )
    db.commit()
    monkeypatch.setattr(
        "app.services.domain_runtime_service.candidate_rag_status",
        lambda code: {"ready": True, "domain_code": code},
    )

    runtime = load_domain_runtime(db, "concept_domain")

    assert runtime.practice_generation_mode == "safe_conceptual"
    assert runtime.diagnostic_ready is True
    assert not any("operation" in reason for reason in runtime.reasons)


def test_initial_diagnostic_readiness_uses_only_shared_eligible_inventory(monkeypatch) -> None:
    db = _db()
    _domain(db, "inventory_domain")
    assessed = _item(db, "inventory_domain", "assessed")
    _item(db, "inventory_domain", "unassessed")
    for index, question_type in enumerate(["single_choice"] * 6 + ["short_answer"] * 4):
        db.add(
            DiagnosticQuestion(
                public_id=f"eligible_{index}",
                domain_code="inventory_domain",
                knowledge_item_id=assessed.id,
                question_type=question_type,
                stem=f"eligible {index}",
                options_json=["A", "B"] if question_type == "single_choice" else [],
                answer_key_json={
                    "correct_option": 0,
                    "rubric": ["x"],
                    "question_bank_uses": ["diagnosis"],
                },
                difficulty=2,
                status="active",
            )
        )
    # This active question is deliberately not part of the initial-diagnosis inventory.
    db.add(
        DiagnosticQuestion(
            public_id="other_purpose",
            domain_code="inventory_domain",
            knowledge_item_id=assessed.id,
            question_type="single_choice",
            stem="other purpose",
            options_json=["A", "B"],
            answer_key_json={"correct_option": 0, "question_bank_uses": ["graded_quiz"]},
            difficulty=2,
            status="active",
        )
    )
    db.commit()
    monkeypatch.setattr(
        "app.services.domain_runtime_service.candidate_rag_status",
        lambda code: {"ready": True, "domain_code": code},
    )

    ready = load_domain_runtime(db, "inventory_domain")

    assert ready.diagnostic_ready is True
    assert ready.diagnostic_inventory["eligible_count"] == 10
    assert ready.diagnostic_inventory["reason"] is None

    db.query(DiagnosticQuestion).filter_by(public_id="eligible_9").one().status = "disabled"
    db.commit()
    unavailable = load_domain_runtime(db, "inventory_domain")

    assert unavailable.diagnostic_ready is False
    assert unavailable.diagnostic_inventory["eligible_count"] == 9
    assert unavailable.diagnostic_inventory["reason"] == "首次诊断至少需要 10 道可用诊断题"


def test_provisional_diagnostic_still_projects_weakness_and_path(monkeypatch) -> None:
    db = _db()
    _domain(db, "provisional_domain")
    theory = _item(db, "provisional_domain", "theory")
    practice = _item(
        db,
        "provisional_domain",
        "practice",
        capabilities=["concept", "operation", "expected_result"],
    )
    db.add(
        Learner(
            public_id="provisional_learner",
            target_domain="provisional_domain",
            education_level="本科",
            major="软件工程",
            direction_tags_json=["general"],
        )
    )
    for index, question_type in enumerate(["single_choice"] * 6 + ["short_answer"] * 4):
        item = practice if index == 0 else theory
        db.add(
            DiagnosticQuestion(
                public_id=f"provisional_{index}",
                domain_code="provisional_domain",
                knowledge_item_id=item.id,
                question_type=question_type,
                stem=f"provisional {index}",
                options_json=["A", "B"] if question_type == "single_choice" else [],
                answer_key_json={
                    "correct_option": 0,
                    "rubric": ["x"],
                    "question_bank_uses": ["diagnosis"],
                },
                difficulty=2,
                status="active",
            )
        )
    db.commit()
    monkeypatch.setattr(
        "app.services.domain_runtime_service.candidate_rag_status",
        lambda code: {"ready": True, "domain_code": code},
    )
    monkeypatch.setattr(
        "app.services.diagnostic_service.score_short_answer_batch",
        lambda items, **_kwargs: (
            {
                question.public_id: {
                    "question_id": question.public_id,
                    "total_score": 0.0,
                    "is_correct": False,
                    "rubric_version": "test-v1",
                    "confidence": 1.0,
                    "scoring_uncertain": False,
                    "ai_comment": "未通过",
                    "criteria": [],
                    "matched_points": [],
                    "missing_points": ["x"],
                    "factual_errors": [],
                }
                for question, _answer in items
            },
            {"tokens_input": 0, "tokens_output": 0, "model_name": "fixture"},
        ),
    )

    session = create_diagnostic_session(
        db,
        learner_id="provisional_learner",
        domain_code="provisional_domain",
        question_count=10,
    )
    result = submit_diagnostic_session(
        db,
        session_id=session["session_id"],
        learner_id="provisional_learner",
        domain_code="provisional_domain",
        answers=[
            {
                "question_id": question["question_id"],
                "answer": 1 if question["question_type"] == "single_choice" else "错误回答",
            }
            for question in session["questions"]
        ],
    )

    assert result["evidence_sufficient"] is False
    assert result["profile_reliability_status"] == "provisional"
    assert result["profile_id"]
    assert result["weak_knowledge"]
    assert result["learning_path_id"]
