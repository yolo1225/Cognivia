from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import (
    Base,
    Domain,
    GenerationTask,
    KnowledgeItem,
    Learner,
    LearnerProfile,
    LearningResource,
    TutoringSession,
)
from app.services import resource_tutoring_service as service


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return Session(engine)


def _resource_context(
    db: Session, *, source_ids: list[str]
) -> tuple[TutoringSession, LearningResource, KnowledgeItem, KnowledgeItem]:
    domain = Domain(domain_code="tutoring_test", name="导学测试", status="ready")
    learner = Learner(public_id="learner_tutoring", target_domain=domain.domain_code)
    db.add_all([domain, learner])
    db.flush()
    profile = LearnerProfile(
        public_id="profile_tutoring",
        learner_id=learner.id,
        domain_code=domain.domain_code,
        ability_profile_json={},
        weak_knowledge_json=[],
    )
    db.add(profile)
    db.flush()
    target = KnowledgeItem(
        public_id="knowledge_target",
        domain_code=domain.domain_code,
        name="目标知识",
        category="RAG",
        content_md="目标知识的旧摘要。",
        source_title="目标资料",
        status="published",
    )
    related = KnowledgeItem(
        public_id="knowledge_related",
        domain_code=domain.domain_code,
        name="关联知识",
        category="RAG",
        content_md="关联知识的旧摘要。",
        source_title="关联资料",
        status="published",
    )
    db.add_all([target, related])
    db.flush()
    task = GenerationTask(
        public_id="task_tutoring",
        learner_id=learner.id,
        profile_id=profile.id,
        domain_code=domain.domain_code,
        status="completed",
        decision="completed",
        resource_types_json=["lecture"],
    )
    db.add(task)
    db.flush()
    resource = LearningResource(
        public_id="resource_tutoring",
        generation_task_id=task.id,
        resource_type="lecture",
        title="导学资源",
        content_md="资源正文只保留与本资源相关的说明。",
        sources_json=[{"knowledge_id": value} for value in source_ids],
        review_status="passed",
    )
    db.add(resource)
    db.flush()
    session = TutoringSession(
        public_id="session_tutoring",
        learner_id=learner.id,
        resource_id=resource.id,
        context_type="resource",
        status="active",
        turn_count=1,
    )
    db.add(session)
    db.flush()
    return session, resource, target, related


class _FakeCollection:
    def __init__(self, result: dict[str, object], *, count: int = 3) -> None:
        self.result = result
        self.count_value = count
        self.query_calls: list[dict[str, object]] = []

    def count(self) -> int:
        return self.count_value

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        return self.result


def _install_candidate_fakes(monkeypatch, collection: _FakeCollection) -> None:
    class FakeAccess:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def active(self, _domain_code: str):
            return SimpleNamespace(embedding_dimensions=3), collection

    class FakeVectorStore:
        client = object()

    class FakeEmbeddingProvider:
        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            assert texts == ["如何验证检索结果？"]
            return [[0.1, 0.2, 0.3]]

    monkeypatch.setattr(service, "CandidateIndexAccess", FakeAccess)
    monkeypatch.setattr(service, "VectorStore", FakeVectorStore)
    monkeypatch.setattr(service, "OpenAICompatibleEmbeddingProvider", FakeEmbeddingProvider)


def test_candidate_search_limits_results_to_current_domain_and_resource_knowledge(monkeypatch) -> None:
    collection = _FakeCollection(
        {
            "ids": [["chunk_ok", "chunk_other_domain", "chunk_wrong_knowledge"]],
            "documents": [["当前候选片段", "其他领域片段", "无关知识片段"]],
            "metadatas": [[
                {
                    "domain_code": "tutoring_test",
                    "knowledge_id": "knowledge_target",
                    "name": "目标知识",
                    "source_title": "当前资料",
                },
                {
                    "domain_code": "other_domain",
                    "knowledge_id": "knowledge_target",
                    "name": "其他领域",
                    "source_title": "其他资料",
                },
                {
                    "domain_code": "tutoring_test",
                    "knowledge_id": "knowledge_unrelated",
                    "name": "无关知识",
                    "source_title": "无关资料",
                },
            ]],
        }
    )
    _install_candidate_fakes(monkeypatch, collection)

    chunks = service._candidate_search(
        _db(),
        domain_code="tutoring_test",
        question="如何验证检索结果？",
        knowledge_ids=["knowledge_target"],
    )

    assert chunks == [{
        "source_ref_id": "chunk_ok",
        "knowledge_id": "knowledge_target",
        "name": "目标知识",
        "content": "当前候选片段",
        "source_title": "当前资料",
    }]
    assert collection.query_calls[0]["where"] == {"knowledge_id": "knowledge_target"}
    assert collection.query_calls[0]["n_results"] == 3


def test_resource_tutoring_context_uses_current_candidate_chunks_for_associated_knowledge(monkeypatch) -> None:
    db = _db()
    session, resource, target, related = _resource_context(
        db, source_ids=["knowledge_target", "knowledge_related"]
    )
    calls: list[list[str]] = []

    def candidate_search(**kwargs):
        calls.append(kwargs["knowledge_ids"])
        return [{
            "source_ref_id": "chunk_current",
            "knowledge_id": target.public_id,
            "name": target.name,
            "content": "当前 Candidate 中的证据。",
            "source_title": "当前资料",
        }]

    monkeypatch.setattr(service, "_candidate_search", lambda _db, **kwargs: candidate_search(**kwargs))
    payload, sources, scope, assessment = service.build_resource_tutoring_context(
        db, session=session, resource=resource, question="如何验证检索结果？"
    )

    assert calls == [[target.public_id, related.public_id]]
    assert scope == "resource_context"
    assert payload["candidate_evidence_available"] is True
    assert payload["knowledge_sources"][0]["source_ref_id"] == "chunk_current"
    assert sources == [{
        "knowledge_id": target.public_id,
        "name": target.name,
        "source_title": "当前资料",
    }]
    assert assessment is None


def test_resource_tutoring_context_uses_domain_candidate_search_without_resource_association(monkeypatch) -> None:
    db = _db()
    session, resource, target, _related = _resource_context(db, source_ids=[])
    calls: list[list[str]] = []

    def candidate_search(**kwargs):
        calls.append(kwargs["knowledge_ids"])
        return [{
            "source_ref_id": "chunk_domain",
            "knowledge_id": target.public_id,
            "name": target.name,
            "content": "领域当前 Candidate 证据。",
            "source_title": "当前领域资料",
        }]

    monkeypatch.setattr(service, "_candidate_search", lambda _db, **kwargs: candidate_search(**kwargs))
    payload, sources, scope, _assessment = service.build_resource_tutoring_context(
        db, session=session, resource=resource, question="如何验证检索结果？"
    )

    assert calls == [[]]
    assert scope == "knowledge_base"
    assert payload["candidate_evidence_available"] is True
    assert sources[0]["source_title"] == "当前领域资料"


def test_resource_tutoring_context_does_not_repeat_empty_domain_candidate_search(monkeypatch) -> None:
    db = _db()
    session, resource, _target, _related = _resource_context(db, source_ids=[])
    calls: list[list[str]] = []

    def candidate_search(**kwargs):
        calls.append(kwargs["knowledge_ids"])
        return []

    monkeypatch.setattr(service, "_candidate_search", lambda _db, **kwargs: candidate_search(**kwargs))
    payload, sources, scope, _assessment = service.build_resource_tutoring_context(
        db, session=session, resource=resource, question="如何验证检索结果？"
    )

    assert calls == [[]]
    assert scope == "uncovered"
    assert payload["candidate_evidence_available"] is False
    assert sources == []


def test_resource_tutoring_context_does_not_present_old_knowledge_summary_as_candidate_evidence(monkeypatch) -> None:
    db = _db()
    session, resource, target, _related = _resource_context(
        db, source_ids=["knowledge_target"]
    )
    monkeypatch.setattr(service, "_candidate_search", lambda *_args, **_kwargs: [])

    payload, sources, scope, _assessment = service.build_resource_tutoring_context(
        db, session=session, resource=resource, question="如何验证检索结果？"
    )

    assert scope == "resource_context"
    assert payload["candidate_evidence_available"] is False
    assert payload["knowledge_sources"] == []
    assert sources == [{
        "knowledge_id": target.public_id,
        "name": target.name,
        "source_title": target.source_title,
    }]
