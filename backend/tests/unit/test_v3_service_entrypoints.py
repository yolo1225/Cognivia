from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import (
    AgentMessageRecord,
    AgentRun,
    AnswerRecord,
    Base,
    DiagnosticQuestion,
    Domain,
    KnowledgeItem,
    KnowledgeRelation,
    Learner,
    LearnerProfile,
    LearningPath,
)
from app.services.diagnostic_service import create_diagnostic_session, submit_diagnostic_session


@pytest.fixture(autouse=True)
def ready_candidate_rag(monkeypatch):
    monkeypatch.setattr(
        "app.services.domain_runtime_service.candidate_rag_status",
        lambda domain_code: {"ready": True, "domain_code": domain_code},
    )


def build_test_session() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def certified_question(**values) -> DiagnosticQuestion:
    answer_key = dict(values.get("answer_key_json") or {})
    answer_key.setdefault("question_bank_uses", ["diagnosis"])
    values["answer_key_json"] = answer_key
    return DiagnosticQuestion(
        status="active",
        certification_status="certified",
        certification_rule_version="question-cert-v1",
        source_content_hash="sha256:" + "a" * 64,
        **values,
    )


def seed_diagnostic_fixture(
    db: Session,
) -> tuple[Learner, DiagnosticQuestion, DiagnosticQuestion]:
    db.add(Domain(domain_code="ai_app_dev", name="AI", status="ready", config_json={}))
    learner = Learner(
        public_id="learner_001",
        background="computer science student",
        target_domain="ai_app_dev",
        experience_years=0,
        learning_style="mixed",
        education_level="本科",
        major="计算机科学",
        direction_tags_json=["rag_knowledge_base"],
    )
    db.add(learner)
    db.flush()
    embedding = KnowledgeItem(
        public_id="embedding_basics",
        domain_code="ai_app_dev",
        name="Embedding Basics",
        category="theory_foundation",
        difficulty=2,
        tags_json=["embedding"],
        evidence_capabilities_json=["concept"],
        content_md="Embedding represents semantic meaning with vectors.",
        source_title="team knowledge base",
        license_note="team-authored",
        needs_reembedding=False,
        ability_weights_json={
            "theory": 0.45,
            "practice": 0.25,
            "problem_solving": 0.2,
            "knowledge_breadth": 0.1,
            "learning_speed": 0.0,
        },
    )
    rag = KnowledgeItem(
        public_id="rag_chunking",
        domain_code="ai_app_dev",
        name="RAG Chunking Strategy",
        category="rag_practice",
        difficulty=3,
        tags_json=["rag"],
        evidence_capabilities_json=["concept", "operation"],
        content_md="Chunking balances semantic completeness and retrieval granularity.",
        source_title="team knowledge base",
        license_note="team-authored",
        needs_reembedding=False,
        ability_weights_json={
            "theory": 0.2,
            "practice": 0.45,
            "problem_solving": 0.25,
            "knowledge_breadth": 0.1,
            "learning_speed": 0.0,
        },
    )
    db.add_all([embedding, rag])
    db.flush()
    db.add(
        KnowledgeRelation(
            source_item_id=rag.id,
            target_item_id=embedding.id,
            relation_type="prerequisite",
        )
    )
    choice = certified_question(
        public_id="q_choice",
        domain_code="ai_app_dev",
        knowledge_item_id=rag.id,
        question_type="single_choice",
        stem="What is the core goal of RAG chunking?",
        options_json=["random split", "semantic completeness", "delete context"],
        answer_key_json={"correct_option": 1},
        difficulty=3,
    )
    short = certified_question(
        public_id="q_short",
        domain_code="ai_app_dev",
        knowledge_item_id=embedding.id,
        question_type="short_answer",
        stem="Explain the purpose of Embedding.",
        options_json=[],
        answer_key_json={"rubric": ["vector", "semantic"]},
        difficulty=2,
    )
    db.add_all([choice, short])
    db.flush()
    for index in range(3):
        db.add(
            certified_question(
                public_id=f"q_seed_concept_choice_{index}",
                domain_code="ai_app_dev",
                knowledge_item_id=embedding.id,
                question_type="single_choice",
                stem=f"Concept choice {index}",
                options_json=["A", "B"],
                answer_key_json={"correct_option": 0},
                difficulty=2,
            )
        )
    for index in range(2):
        db.add(
            certified_question(
                public_id=f"q_seed_practice_choice_{index}",
                domain_code="ai_app_dev",
                knowledge_item_id=rag.id,
                question_type="single_choice",
                stem=f"Practice choice {index}",
                options_json=["A", "B"],
                answer_key_json={"correct_option": 0},
                difficulty=3,
            )
        )
    db.add(
        certified_question(
            public_id="q_seed_concept_short",
            domain_code="ai_app_dev",
            knowledge_item_id=embedding.id,
            question_type="short_answer",
            stem="Concept short answer",
            options_json=[],
            answer_key_json={"rubric": ["answer"]},
            difficulty=2,
        )
    )
    for index in range(2):
        db.add(
            certified_question(
                public_id=f"q_seed_practice_short_{index}",
                domain_code="ai_app_dev",
                knowledge_item_id=rag.id,
                question_type="short_answer",
                stem=f"Practice short answer {index}",
                options_json=[],
                answer_key_json={"rubric": ["answer"]},
                difficulty=3,
            )
        )
    db.flush()
    return learner, choice, short


def _submit(
    db: Session,
    learner: Learner,
    choice: DiagnosticQuestion,
    short: DiagnosticQuestion,
    *,
    session_id: str,
    choice_answer: object = 1,
    short_answer: object = "Embedding uses vector representation for semantic meaning.",
) -> dict:
    created = create_diagnostic_session(
        db,
        learner_id=learner.public_id,
        domain_code="ai_app_dev",
        question_count=10,
    )
    answers = []
    questions = {question.public_id: question for question in db.query(DiagnosticQuestion).all()}
    for selected in created["questions"]:
        question = questions[selected["question_id"]]
        if question.public_id == choice.public_id:
            answer = choice_answer
        elif question.public_id == short.public_id:
            answer = short_answer
        elif question.question_type == "single_choice":
            answer = question.answer_key_json["correct_option"]
        else:
            answer = "answer"
        answers.append({"question_id": question.public_id, "answer": answer})
    return submit_diagnostic_session(
        db,
        session_id=created["session_id"],
        learner_id=learner.public_id,
        domain_code="ai_app_dev",
        answers=answers,
    )


def test_create_diagnostic_session_rejects_non_standard_question_count(monkeypatch) -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner, choice, _ = seed_diagnostic_fixture(db)
        extra = certified_question(
            public_id="q_extra",
            domain_code="ai_app_dev",
            knowledge_item_id=choice.knowledge_item_id,
            question_type="single_choice",
            stem="Which question is sampled from beyond the old fixed prefix?",
            options_json=["A", "B"],
            answer_key_json={"correct_option": 0},
            difficulty=5,
        )
        db.add(extra)
        db.flush()
        sampled_pool: list[str] = []

        def select_last_questions(population, *, k):
            if k == 0:
                return []
            sampled_pool.extend(question.public_id for question in population)
            return population[-k:]

        monkeypatch.setattr("app.services.diagnostic_service.random.sample", select_last_questions)
        monkeypatch.setattr("app.services.diagnostic_service.random.shuffle", lambda _: None)
        with pytest.raises(ValueError, match="initial_diagnostic_requires_ten_questions"):
            create_diagnostic_session(
                db,
                learner_id=learner.public_id,
                domain_code="ai_app_dev",
                question_count=1,
            )

    assert sampled_pool == []


def test_create_diagnostic_session_stratifies_ten_questions_as_eight_and_two() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner, choice, short = seed_diagnostic_fixture(db)
        for index in range(9):
            db.add(
                certified_question(
                    public_id=f"q_choice_{index}",
                    domain_code="ai_app_dev",
                    knowledge_item_id=choice.knowledge_item_id,
                    question_type="single_choice",
                    stem=f"Choice question {index}",
                    options_json=["A", "B"],
                    answer_key_json={"correct_option": 0},
                    difficulty=(index % 5) + 1,
                )
            )
        for index in range(2):
            db.add(
                certified_question(
                    public_id=f"q_short_{index}",
                    domain_code="ai_app_dev",
                    knowledge_item_id=short.knowledge_item_id,
                    question_type="short_answer",
                    stem=f"Short answer question {index}",
                    options_json=[],
                    answer_key_json={"rubric": ["answer"]},
                    difficulty=index + 1,
                )
            )
        db.flush()
        result = create_diagnostic_session(
            db,
            learner_id=learner.public_id,
            domain_code="ai_app_dev",
            question_count=10,
        )

    question_types = [question["question_type"] for question in result["questions"]]
    assert question_types.count("single_choice") == 6
    assert question_types.count("short_answer") == 4


def test_create_diagnostic_session_returns_standard_ten_questions() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner, choice, short = seed_diagnostic_fixture(db)
        result = create_diagnostic_session(
            db,
            learner_id=learner.public_id,
            domain_code="ai_app_dev",
            question_count=10,
        )

    assert result["question_count"] == 10
    assert {choice.public_id, short.public_id}.issubset(
        {question["question_id"] for question in result["questions"]}
    )


def test_diagnostic_entrypoint_persists_v3_profile_path_and_safe_observability() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner, choice, short = seed_diagnostic_fixture(db)
        result = _submit(db, learner, choice, short, session_id="diag_v3")
        run = db.query(AgentRun).filter_by(agent_name="profile_analysis_agent").one()
        messages = db.query(AgentMessageRecord).filter_by(session_id=result["session_id"]).all()
        answers = db.query(AnswerRecord).all()
        profile = db.query(LearnerProfile).filter_by(public_id=result["profile_id"]).one()
        path = db.query(LearningPath).filter_by(public_id=result["learning_path_id"]).one()

    assert result["status"] == "scored"
    assert result["score"] == 100
    assert result["agent_run_id"] == run.id
    assert run.prompt_version == "v6"
    assert run.contract_version == "agent-contract-v10"
    assert len(run.prompt_hash) == 64
    assert run.status == "completed"
    assert run.input_summary_json["question_count"] == 10
    assert "answers" not in run.input_summary_json
    assert profile.profile_version == result["profile_version"]
    assert path.profile_id == profile.id
    assert len(answers) == 10
    assert {message.message_type for message in messages} >= {"command", "result"}
    assert all("answer" not in message.payload_summary_json for message in messages)


def test_diagnostic_entrypoint_maps_skipped_answer_without_raw_text() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner, choice, short = seed_diagnostic_fixture(db)
        short_id = short.id
        result = _submit(
            db,
            learner,
            choice,
            short,
            session_id="diag_skip",
            choice_answer=0,
            short_answer=None,
        )
        answers = db.query(AnswerRecord).order_by(AnswerRecord.id).all()

    assert result["question_count"] == 10
    assert result["score"] == 80
    skipped = next(item for item in answers if item.question_id == short_id)
    assert skipped.answer_summary_json["attempted"] is False
    assert "answer" not in skipped.answer_summary_json


def test_repeated_initial_diagnostic_is_rejected_after_profile_is_ready() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner, choice, short = seed_diagnostic_fixture(db)
        first = _submit(
            db,
            learner,
            choice,
            short,
            session_id="diag_first",
            choice_answer=0,
            short_answer="unknown",
        )
        with pytest.raises(ValueError, match="initial_profile_already_ready"):
            _submit(db, learner, choice, short, session_id="diag_second")
        old_path = db.query(LearningPath).filter_by(public_id=first["learning_path_id"]).one()

    assert old_path.needs_refresh is False
