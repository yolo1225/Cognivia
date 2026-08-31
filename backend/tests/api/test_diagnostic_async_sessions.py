from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import diagnostics as diagnostics_api
from app.core.db import get_db
from app.core.security import Principal, get_current_user
from app.main import app
from app.models import (
    AnswerRecord,
    Base,
    DiagnosticQuestion,
    DiagnosticSession,
    KnowledgeItem,
    Learner,
)


def _sessions() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _override(factory: sessionmaker[Session]):
    def dependency() -> Generator[Session, None, None]:
        with factory() as db:
            yield db

    return dependency


def _seed(factory: sessionmaker[Session]) -> list[dict[str, str | int]]:
    with factory() as db:
        learner = Learner(public_id="learner_async", target_domain="test_domain")
        db.add(learner)
        db.flush()
        question_ids = []
        answers = []
        for index in range(10):
            item = KnowledgeItem(
                public_id=f"knowledge_{index}",
                domain_code="test_domain",
                name=f"知识 {index}",
                category="test",
                difficulty=2,
                content_md=f"知识内容 {index}",
                source_title="test",
                license_note="test",
                status="published",
            )
            db.add(item)
            db.flush()
            question = DiagnosticQuestion(
                public_id=f"question_{index}",
                domain_code="test_domain",
                knowledge_item_id=item.id,
                question_type="single_choice" if index < 6 else "short_answer",
                stem=f"题目 {index}",
                options_json=["A", "B"] if index < 6 else [],
                answer_key_json={"correct_option": 0} if index < 6 else {"rubric": ["要点"]},
                difficulty=2,
                status="active",
            )
            db.add(question)
            question_ids.append(question.public_id)
            answers.append(
                {
                    "question_id": question.public_id,
                    "answer": 0 if index < 6 else "简答内容",
                }
            )
        db.add(
            DiagnosticSession(
                public_id="diag_async",
                learner_id=learner.id,
                domain_code="test_domain",
                status="created",
                question_ids_json=question_ids,
                context_snapshot_json={},
                selection_summary_json={},
            )
        )
        db.commit()
    return answers


def test_submit_is_async_idempotent_and_rejects_changed_answers(monkeypatch) -> None:
    factory = _sessions()
    answers = _seed(factory)
    background_calls = []
    monkeypatch.setattr(
        diagnostics_api,
        "run_diagnostic_scoring_job",
        lambda session_id: background_calls.append(session_id),
    )
    app.dependency_overrides[get_db] = _override(factory)
    app.dependency_overrides[get_current_user] = lambda: Principal(
        "learner-user", "learner", "learner_async"
    )
    client = TestClient(app)
    payload = {
        "learner_id": "learner_async",
        "domain_code": "test_domain",
        "answers": answers,
    }
    try:
        first = client.post("/api/v1/diagnostics/sessions/diag_async/submit", json=payload)
        repeated = client.post("/api/v1/diagnostics/sessions/diag_async/submit", json=payload)
        changed_answers = [dict(item) for item in answers]
        changed_answers[-1]["answer"] = "修改后的答案"
        changed = client.post(
            "/api/v1/diagnostics/sessions/diag_async/submit",
            json={**payload, "answers": changed_answers},
        )

        assert first.status_code == 202
        assert first.json()["data"]["status"] == "scoring"
        assert repeated.status_code == 202
        assert changed.status_code == 409
        assert "DIAGNOSTIC_ANSWERS_CHANGED" in changed.text
        assert background_calls == ["diag_async"]
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(AnswerRecord)) == 10
            short_confidences = list(
                db.scalars(
                    select(AnswerRecord.confidence)
                    .join(DiagnosticQuestion, DiagnosticQuestion.id == AnswerRecord.question_id)
                    .where(DiagnosticQuestion.question_type == "short_answer")
                )
            )
            assert short_confidences == [None, None, None, None]
    finally:
        app.dependency_overrides.clear()


def test_pending_retry_reuses_session_and_schedules_one_job(monkeypatch) -> None:
    factory = _sessions()
    answers = _seed(factory)
    background_calls = []
    monkeypatch.setattr(
        diagnostics_api,
        "run_diagnostic_scoring_job",
        lambda session_id: background_calls.append(session_id),
    )
    app.dependency_overrides[get_db] = _override(factory)
    app.dependency_overrides[get_current_user] = lambda: Principal(
        "learner-user", "learner", "learner_async"
    )
    client = TestClient(app)
    try:
        client.post(
            "/api/v1/diagnostics/sessions/diag_async/submit",
            json={
                "learner_id": "learner_async",
                "domain_code": "test_domain",
                "answers": answers,
            },
        )
        with factory() as db:
            session = db.scalar(
                select(DiagnosticSession).where(DiagnosticSession.public_id == "diag_async")
            )
            session.status = "pending_scoring"
            session.error_code = "DIAGNOSTIC_SCORING_PENDING"
            db.commit()

        retried = client.post(
            "/api/v1/diagnostics/sessions/diag_async/retry",
            json={"learner_id": "learner_async"},
        )

        assert retried.status_code == 200
        assert retried.json()["data"]["status"] == "scoring"
        assert retried.json()["data"]["scoring_attempts"] == 2
        assert background_calls == ["diag_async", "diag_async"]
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(AnswerRecord)) == 10
    finally:
        app.dependency_overrides.clear()


def test_current_session_restores_latest_diagnostic_for_learner_and_domain() -> None:
    factory = _sessions()
    _seed(factory)
    app.dependency_overrides[get_db] = _override(factory)
    app.dependency_overrides[get_current_user] = lambda: Principal(
        "learner-user", "learner", "learner_async"
    )
    client = TestClient(app)
    try:
        response = client.get(
            "/api/v1/diagnostics/sessions/current",
            params={"learner_id": "learner_async", "domain_code": "test_domain"},
        )
        missing = client.get(
            "/api/v1/diagnostics/sessions/current",
            params={"learner_id": "learner_async", "domain_code": "other_domain"},
        )

        assert response.status_code == 200
        assert response.json()["data"]["session_id"] == "diag_async"
        assert response.json()["data"]["status"] == "created"
        assert missing.status_code == 200
        assert missing.json()["data"] is None
    finally:
        app.dependency_overrides.clear()
