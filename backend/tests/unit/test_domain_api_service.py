from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    Base,
    DiagnosticQuestion,
    Domain,
    IndexBuildJob,
    KnowledgeItem,
    KnowledgeRelation,
)
from app.services.domain_api_service import (
    DomainApiService,
    mark_domain_preparing,
    readiness_policy,
)


WEIGHTS = {
    "theory": 0.3,
    "practice": 0.25,
    "problem_solving": 0.2,
    "knowledge_breadth": 0.25,
    "learning_speed": 0.0,
}


def build_db(*, knowledge_count: int = 10, question_count: int = 10) -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(
        Domain(
            domain_code="test_domain",
            name="测试领域",
            status="preparing",
            config_json={
                "learning_directions": [{"value": "general", "label": "综合"}],
                "readiness_policy": {
                    "minimum_published_knowledge": 10,
                    "minimum_diagnostic_questions": 10,
                },
            },
        )
    )
    items = []
    for index in range(knowledge_count):
        item = KnowledgeItem(
            public_id=f"item_{index}",
            domain_code="test_domain",
            name=f"知识 {index}",
            category="practice" if index % 2 else "theory",
            difficulty=2,
            content_md="traceable evidence",
            source_title="test source",
            ability_weights_json=WEIGHTS,
            evidence_capabilities_json=["concept", "operation"] if index % 2 else ["concept"],
            status="published",
        )
        db.add(item)
        db.flush()
        items.append(item)
    distribution = [
        ("single_choice", False),
        ("single_choice", False),
        ("single_choice", False),
        ("single_choice", True),
        ("single_choice", True),
        ("single_choice", True),
        ("short_answer", False),
        ("short_answer", False),
        ("short_answer", True),
        ("short_answer", True),
    ]
    theory = next(
        (item for item in items if "operation" not in item.evidence_capabilities_json), None
    )
    practice = next(
        (item for item in items if "operation" in item.evidence_capabilities_json), None
    )
    if question_count >= 10:
        for item in items:
            for slot in range(1, 9):
                question_type = "single_choice" if slot <= 5 else "short_answer"
                question_bank_uses = (
                    ["diagnosis", "graded_quiz"]
                    if slot <= 3
                    else ["mastery_validation", "mistake_consolidation"]
                    if question_type == "single_choice"
                    else ["diagnosis", "graded_quiz"]
                )
                db.add(
                    DiagnosticQuestion(
                        public_id=f"question_{item.id}_{slot}",
                        domain_code="test_domain",
                        knowledge_item_id=item.id,
                        question_type=question_type,
                        stem=f"question {item.id}-{slot}",
                        options_json=["A", "B", "C", "D"]
                        if question_type == "single_choice"
                        else [],
                        answer_key_json={
                            **(
                                {"correct_option": 0}
                                if question_type == "single_choice"
                                else {"answer": "A", "rubric": ["x", "y"]}
                            ),
                            "explanation": "source-backed",
                            "source_ref_ids": [item.public_id],
                            "question_slot": slot,
                            "question_bank_uses": question_bank_uses,
                            "quiz_level": (
                                "foundation"
                                if slot <= 2
                                else "improvement"
                                if slot <= 4
                                else "challenge"
                            ),
                        },
                        difficulty=min(5, slot),
                        status="active",
                        certification_status="certified",
                        certification_rule_version="question-cert-v1",
                        source_content_hash="sha256:" + "a" * 64,
                    )
                )
    else:
        for index, (question_type, operation) in enumerate(distribution[:question_count]):
            item = practice if operation else theory
            if item is None:
                break
            db.add(
                DiagnosticQuestion(
                    public_id=f"question_{index}",
                    domain_code="test_domain",
                    knowledge_item_id=item.id,
                    question_type=question_type,
                    stem=f"question {index}",
                    options_json=["A", "B"] if question_type == "single_choice" else [],
                    answer_key_json={"correct_option": 0}
                    if question_type == "single_choice"
                    else {"rubric": ["x"]},
                    difficulty=2,
                    status="active",
                    certification_status="certified",
                    certification_rule_version="question-cert-v1",
                    source_content_hash="sha256:" + "b" * 64,
                )
            )
    db.add(
        IndexBuildJob(
            domain_code="test_domain",
            status="success",
            finished_at=datetime.now(UTC),
            result_json={"smoke_test": {"passed": True, "index_version": "index-v1"}},
        )
    )
    db.commit()
    return db


def test_readiness_passes_with_runtime_and_matching_smoke(monkeypatch) -> None:
    db = build_db()
    monkeypatch.setattr(
        "app.services.domain_api_service.candidate_rag_status",
        lambda _domain: {"ready": True, "index_version": "index-v1", "indexed_chunk_count": 10},
    )
    monkeypatch.setattr(
        "app.services.domain_runtime_service.candidate_rag_status",
        lambda _domain: {"ready": True, "index_version": "index-v1", "indexed_chunk_count": 10},
    )

    result = DomainApiService(db).readiness("test_domain")

    assert result["passed"] is True
    assert result["generation_ready"] is True
    assert result["issues"] == []
    assert result["evidence_coverage"] == {
        "total_items": 10,
        "capabilities": {
            "concept": 10,
            "operation": 5,
            "command": 0,
            "code_example": 0,
            "expected_result": 0,
            "error_handling": 0,
            "version_boundary": 0,
        },
        "practice_generation_mode": "safe_conceptual",
    }
    assert result["passed"] is True


def test_readiness_reports_candidate_failure_without_external_smoke(monkeypatch) -> None:
    db = build_db()
    monkeypatch.setattr(
        "app.services.domain_api_service.candidate_rag_status",
        lambda _domain: {"ready": False, "reason": "candidate_index_stale"},
    )
    monkeypatch.setattr(
        "app.services.domain_runtime_service.candidate_rag_status",
        lambda _domain: {"ready": False, "reason": "candidate_index_stale"},
    )

    result = DomainApiService(db).readiness("test_domain")

    assert result["passed"] is False
    assert "Candidate RAG" in {issue["message"] for issue in result["issues"]}


def test_practice_mode_requires_operation_and_expected_result(monkeypatch) -> None:
    db = build_db()
    concept_item = next(
        item
        for item in db.query(KnowledgeItem).filter_by(domain_code="test_domain")
        if "operation" not in (item.evidence_capabilities_json or [])
    )
    for item in db.query(KnowledgeItem).filter_by(domain_code="test_domain"):
        item.evidence_capabilities_json = ["concept"]
    concept_item.evidence_capabilities_json = ["concept", "expected_result"]
    db.commit()
    monkeypatch.setattr(
        "app.services.domain_api_service.candidate_rag_status",
        lambda _domain: {"ready": True, "index_version": "index-v1", "indexed_chunk_count": 10},
    )
    monkeypatch.setattr(
        "app.services.domain_runtime_service.candidate_rag_status",
        lambda _domain: {"ready": True, "index_version": "index-v1", "indexed_chunk_count": 10},
    )

    result = DomainApiService(db).readiness("test_domain")

    assert result["evidence_coverage"]["capabilities"]["expected_result"] == 1
    assert result["evidence_coverage"]["capabilities"]["operation"] == 0
    assert result["evidence_coverage"]["practice_generation_mode"] == "safe_conceptual"


def test_readiness_keeps_domain_data_thresholds_as_blockers(monkeypatch) -> None:
    db = build_db(knowledge_count=9, question_count=9)
    monkeypatch.setattr(
        "app.services.domain_api_service.candidate_rag_status",
        lambda _domain: {"ready": True, "index_version": "index-v1", "indexed_chunk_count": 9},
    )
    monkeypatch.setattr(
        "app.services.domain_runtime_service.candidate_rag_status",
        lambda _domain: {"ready": True, "index_version": "index-v1", "indexed_chunk_count": 9},
    )

    result = DomainApiService(db).readiness("test_domain")

    assert result["passed"] is False
    assert {"已发布知识点", "可用诊断题"}.issubset({issue["message"] for issue in result["issues"]})


def test_readiness_rejects_prerequisite_cycle_and_cross_domain_relation(monkeypatch) -> None:
    db = build_db()
    items = list(db.query(KnowledgeItem).filter_by(domain_code="test_domain").limit(2))
    foreign = KnowledgeItem(
        public_id="foreign_item",
        domain_code="foreign_domain",
        name="外部知识",
        category="theory",
        difficulty=1,
        content_md="foreign",
        source_title="foreign source",
        ability_weights_json=WEIGHTS,
        status="published",
    )
    db.add(foreign)
    db.flush()
    db.add_all(
        [
            KnowledgeRelation(
                source_item_id=items[0].id,
                target_item_id=items[1].id,
                relation_type="prerequisite",
            ),
            KnowledgeRelation(
                source_item_id=items[1].id,
                target_item_id=items[0].id,
                relation_type="prerequisite",
            ),
            KnowledgeRelation(
                source_item_id=items[0].id,
                target_item_id=foreign.id,
                relation_type="related",
            ),
        ]
    )
    db.commit()
    monkeypatch.setattr(
        "app.services.domain_api_service.candidate_rag_status",
        lambda _domain: {"ready": True, "index_version": "index-v1", "indexed_chunk_count": 10},
    )
    monkeypatch.setattr(
        "app.services.domain_runtime_service.candidate_rag_status",
        lambda _domain: {"ready": True, "index_version": "index-v1", "indexed_chunk_count": 10},
    )

    result = DomainApiService(db).readiness("test_domain")
    checks = {item["key"]: item for item in result["checks"]}

    assert checks["invalid_relations"]["passed"] is False
    assert checks["prerequisite_cycles"]["passed"] is False


def test_readiness_policy_cannot_be_lowered_below_server_minimum() -> None:
    primary = Domain(
        domain_code="ai_app_dev",
        name="主领域",
        config_json={
            "readiness_policy": {
                "minimum_published_knowledge": 1,
                "minimum_diagnostic_questions": 1,
            }
        },
    )
    secondary = Domain(
        domain_code="secondary",
        name="第二领域",
        config_json={
            "readiness_policy": {
                "minimum_published_knowledge": 1,
                "minimum_diagnostic_questions": 1,
            }
        },
    )

    assert readiness_policy(primary) == {
        "minimum_published_knowledge": 10,
        "minimum_diagnostic_questions": 10,
    }
    assert readiness_policy(secondary) == {
        "minimum_published_knowledge": 10,
        "minimum_diagnostic_questions": 10,
    }


def test_readiness_policy_uses_domain_configuration_without_code_branch() -> None:
    primary_named_domain = Domain(
        domain_code="ai_app_dev",
        name="主领域",
        config_json={
            "readiness_policy": {
                "minimum_published_knowledge": 17,
                "minimum_diagnostic_questions": 23,
            }
        },
    )
    differently_named_domain = Domain(
        domain_code="imported_industry_domain",
        name="导入领域",
        config_json={
            "readiness_policy": {
                "minimum_published_knowledge": 50,
                "minimum_diagnostic_questions": 60,
            }
        },
    )

    assert readiness_policy(primary_named_domain) == {
        "minimum_published_knowledge": 17,
        "minimum_diagnostic_questions": 23,
    }
    assert readiness_policy(differently_named_domain) == {
        "minimum_published_knowledge": 50,
        "minimum_diagnostic_questions": 60,
    }


def test_formal_data_change_moves_draft_or_ready_to_preparing() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    draft = Domain(domain_code="draft_domain", name="草稿", status="draft", config_json={})
    ready = Domain(domain_code="ready_domain", name="已发布", status="ready", config_json={})
    disabled = Domain(
        domain_code="disabled_domain", name="已停用", status="disabled", config_json={}
    )
    db.add_all([draft, ready, disabled])
    db.commit()

    for domain in (draft, ready, disabled):
        mark_domain_preparing(db, domain.domain_code)
    db.commit()

    assert draft.status == "preparing"
    assert ready.status == "preparing"
    assert disabled.status == "disabled"
