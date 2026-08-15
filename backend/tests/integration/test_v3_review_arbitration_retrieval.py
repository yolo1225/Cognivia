"""Integration proof that V3 review arbitration re-enters the V3 candidate index."""

from __future__ import annotations

from pathlib import Path

import chromadb
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.contracts import (
    EvidenceVerdict,
    GenerateResourceInput,
    GenerationRequirements,
    ModelReview,
    ReviewDecision,
    ReviewResourceInput,
    RetrieveKnowledgeInput,
)
from app.agents.contract_adapters import render_resource_markdown
from app.agents.generation_agent import ContentGenerationAgent
from app.agents.retrieval_agent import KnowledgeRetrievalAgent
from app.agents.review_agent import (
    TaskScopedArbitrationRetriever,
    ReviewValidationAgent,
)
from app.models import Base, KnowledgeItem
from app.rag.candidate_manifest import (
    DISTANCE_METRIC,
    MANIFEST_SCHEMA_VERSION,
    CandidateIndexManifest,
    CandidateManifestStore,
    compute_index_version,
)
from app.rag.retrieval import CandidateRetriever


class DeterministicEmbeddingProvider:
    model_name = "review-arbitration-embedding"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


class RecordingRetrievalAgent(KnowledgeRetrievalAgent):
    def __init__(self, retriever: CandidateRetriever) -> None:
        super().__init__(retriever)
        self.requests: list[RetrieveKnowledgeInput] = []

    def execute(self, request: RetrieveKnowledgeInput):
        self.requests.append(request)
        output = super().execute(request)
        if request.purpose.value == "source_verification":
            output = output.model_copy(
                update={
                    "chunks": [
                        chunk
                        for chunk in output.chunks
                        if chunk.knowledge_id != "rag-basics"
                    ],
                    "covered_knowledge_ids": [
                        knowledge_id
                        for knowledge_id in output.covered_knowledge_ids
                        if knowledge_id != "rag-basics"
                    ],
                }
            )
        return output


class PersistentConflictChannel:
    def __init__(self) -> None:
        self.calls = 0

    def review(self, *, role, model, deterministic_review, **_kwargs) -> ModelReview:
        self.calls += 1
        checks = list(deterministic_review.fact_checks)
        if role == "secondary_review_model":
            checks[0] = checks[0].model_copy(
                update={
                    "verdict": EvidenceVerdict.CONTRADICTED,
                    "supported": False,
                    "determinable": True,
                    "reason": "次审核通道认为证据明确冲突。",
                }
            )
        return deterministic_review.model_copy(
            update={"model_role": role, "model_name": model or role, "fact_checks": checks}
        )


def _retrieval_input() -> RetrieveKnowledgeInput:
    return RetrieveKnowledgeInput.model_validate(
        {
            "task_id": "v3-review-arbitration",
            "context": {
                "task_id": "v3-review-arbitration",
                "session_id": "v3-review-arbitration",
                "trigger_type": "initial_generation",
                "execution_mode": "auto",
                "learner_id": "learner-v3",
                "profile_id": "profile-v3",
                "domain_code": "ai_app_dev",
                "resource_types": ["lecture"],
                "learning_goal": "验证 RAG 来源可追溯性",
            },
            "profile": {
                "profile_id": "profile-v3",
                "profile_version": 1,
                "profile_type": "beginner",
                "ability_scores": {
                    "theory": 30,
                    "practice": 30,
                    "problem_solving": 30,
                    "knowledge_breadth": 30,
                    "learning_speed": 30,
                },
            },
            "retrieval_plan": {
                "strategy": "consolidation",
                "target_difficulty": 2,
                "resource_types": ["lecture"],
                "priority_knowledge_ids": ["rag-basics"],
                "query_terms": ["RAG", "来源"],
                "n_results": 1,
            },
            "purpose": "consolidation_practice",
        }
    )


def _candidate_agent(tmp_path: Path) -> RecordingRetrievalAgent:
    source_version = "sha256:" + "3" * 64
    index_version = compute_index_version(
        domain_code="ai_app_dev",
        source_data_version=source_version,
        embedding_model="review-arbitration-embedding",
        embedding_dimensions=3,
        distance_metric=DISTANCE_METRIC,
        chunker_version="candidate-heading-v3",
    )
    collection_name = "knowledge_ai_app_dev_review_arbitration"
    client = chromadb.Client()
    collection = client.create_collection(
        name=collection_name,
        configuration={"hnsw": {"space": "cosine"}},
        metadata={
            "domain_code": "ai_app_dev",
            "embedding_model": "review-arbitration-embedding",
            "embedding_dimensions": 3,
            "distance_metric": DISTANCE_METRIC,
            "index_version": index_version,
            "chunker_version": "candidate-heading-v3",
        },
        embedding_function=None,
    )
    records = [
        ("rag-basics", "RAG 资源必须保留可追溯来源。"),
        ("rag-validation", "审核时必须重新检索来源并比较证据。"),
    ]
    collection.add(
        ids=[f"{knowledge_id}::chunk::0" for knowledge_id, _ in records],
        documents=[content for _, content in records],
        embeddings=[[1.0, 0.0, 0.0], [0.9, 0.1, 0.0]],
        metadatas=[
            {
                "domain_code": "ai_app_dev",
                "knowledge_id": knowledge_id,
                "name": knowledge_id,
                "category": "RAG",
                "difficulty": 2,
                "source_title": "RAG 审核规范",
                "source_url": "https://example.com/rag-review",
                "license_note": "team-authored",
                "chunk_index": 0,
                "embedding_model": "review-arbitration-embedding",
                "embedding_dimensions": 3,
            }
            for knowledge_id, _ in records
        ],
    )
    manifest_store = CandidateManifestStore(root=tmp_path)
    manifest_store.write(
        CandidateIndexManifest(
            schema_version=MANIFEST_SCHEMA_VERSION,
            active_collection=collection_name,
            previous_collection=None,
            domain_code="ai_app_dev",
            embedding_model="review-arbitration-embedding",
            embedding_dimensions=3,
            distance_metric=DISTANCE_METRIC,
            chunker_version="candidate-heading-v3",
            index_version=index_version,
            source_data_version=source_version,
            last_successful_sync_at="2026-08-01T12:00:00+00:00",
            indexed_item_count=len(records),
            indexed_chunk_count=len(records),
        )
    )
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    db = sessions()
    for knowledge_id, content in records:
        db.add(
            KnowledgeItem(
                public_id=knowledge_id,
                domain_code="ai_app_dev",
                name=knowledge_id,
                category="RAG",
                difficulty=2,
                tags_json=[],
                content_md=content,
                source_title="RAG 审核规范",
                source_url="https://example.com/rag-review",
                license_note="team-authored",
            )
        )
    db.commit()
    return RecordingRetrievalAgent(
        CandidateRetriever(
            db=db,
            chroma_client=client,
            embedding_provider=DeterministicEmbeddingProvider(),
            manifest_store=manifest_store,
        )
    )


def test_v3_review_arbitration_retrieves_real_candidate_evidence(tmp_path: Path) -> None:
    retrieval_agent = _candidate_agent(tmp_path)
    try:
        initial_request = _retrieval_input()
        initial_output = retrieval_agent.execute(initial_request)
        assert [chunk.knowledge_id for chunk in initial_output.chunks] == ["rag-basics"]

        requirements = GenerationRequirements(
            resource_types=["lecture"],
            target_difficulty=2,
            strategy="consolidation",
            required_knowledge_ids=["rag-basics"],
            source_whitelist=[initial_output.chunks[0].source.source_ref_id],
        )
        generated = ContentGenerationAgent(renderer=render_resource_markdown).execute(
            GenerateResourceInput(
                task_id=initial_request.task_id,
                context=initial_request.context,
                profile=initial_request.profile,
                retrieved_chunks=initial_output.chunks,
                requirements=requirements,
            )
        )
        review_request = ReviewResourceInput(
            task_id=initial_request.task_id,
            context=initial_request.context,
            resources=generated.resources,
            requirements=requirements,
            evidence=initial_output.chunks,
        )
        conflict_channel = PersistentConflictChannel()
        output = ReviewValidationAgent(
            channel=conflict_channel,
            evidence_retriever=TaskScopedArbitrationRetriever(
                retrieval_agent=retrieval_agent,
                original_request=initial_request,
            ),
        ).execute(review_request)

        report = output.reports[0]
        assert conflict_channel.calls == 4
        assert len(retrieval_agent.requests) == 2
        refreshed_request = retrieval_agent.requests[1]
        assert refreshed_request.purpose.value == "source_verification"
        assert refreshed_request.retrieval_plan.priority_knowledge_ids[0] == "rag-basics"
        assert refreshed_request.retrieval_plan.n_results == 2
        assert report.arbitration.retrieval_performed
        assert report.arbitration.additional_source_ref_ids == ["rag-validation::chunk::0"]
        assert report.arbitration.disagreement_remains
        assert report.decision is ReviewDecision.REVISION_REQUIRED
    finally:
        retrieval_agent.close()
