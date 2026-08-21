from __future__ import annotations

from typing import Any

from app.agents.contracts import RetrieveKnowledgeInput, RetrieveKnowledgeOutput
from app.agents.prompt_registry import get_prompt
from app.core.config import Settings
from app.core.db import SessionLocal
from app.rag.candidate_manifest import CandidateManifestStore
from app.rag.embedding_provider import OpenAICompatibleEmbeddingProvider
from app.rag.retrieval import CandidateRetriever
from app.rag.vector_store import VectorStore


RETRIEVAL_AGENT_NAME = "knowledge_retrieval_agent_v3"
SYSTEM_PROMPT = get_prompt("retrieval")


class KnowledgeRetrievalAgent:
    """Standalone V3 retrieval boundary; it deliberately does not inherit legacy BaseAgent."""

    name = RETRIEVAL_AGENT_NAME
    system_prompt = SYSTEM_PROMPT

    def __init__(self, retriever: CandidateRetriever) -> None:
        self._retriever = retriever

    @classmethod
    def production(cls, *, mode: str = "full") -> "KnowledgeRetrievalAgent":
        settings = Settings()
        return cls(
            CandidateRetriever(
                db=SessionLocal(),
                chroma_client=VectorStore().client,
                embedding_provider=OpenAICompatibleEmbeddingProvider(
                    base_url=settings.openai_api_base,
                    api_key=settings.openai_api_key,
                    model=settings.embedding_model,
                    timeout_seconds=settings.llm_timeout_seconds,
                ),
                manifest_store=CandidateManifestStore(),
                mode=mode,
            )
        )

    def execute(self, request: RetrieveKnowledgeInput) -> RetrieveKnowledgeOutput:
        return self._retriever.execute(request)

    def close(self) -> None:
        self._retriever.db.close()

    def __enter__(self) -> "KnowledgeRetrievalAgent":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
