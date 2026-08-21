from __future__ import annotations

import argparse
import json

from app.core.db import SessionLocal
from app.rag.candidate_index import CandidateIndexBuilder
from app.rag.embedding_provider import OpenAICompatibleEmbeddingProvider
from app.rag.vector_store import VectorStore
from app.services.model_config_service import reload_from_db


def build_candidate_index(
    *,
    domain_code: str,
    reset: bool,
    live: bool,
    activate: bool = True,
    staged_document_id: int | None = None,
) -> dict:
    if not live:
        raise RuntimeError("--live is required; candidate indexing never falls back to mock vectors")
    # This CLI runs in its own process, so it must load DB-persisted model
    # overrides before constructing the embedding provider. This lets an admin
    # configure models through the web UI and then rebuild the index here.
    reload_from_db()
    provider = OpenAICompatibleEmbeddingProvider()
    with SessionLocal() as db:
        builder = CandidateIndexBuilder(
            db=db,
            chroma_client=VectorStore().client,
            embedding_provider=provider,
        )
        if activate:
            return builder.build(domain_code=domain_code, reset=reset)
        return builder.build_candidate(
            domain_code=domain_code,
            reset=reset,
            staged_document_id=staged_document_id,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the isolated real-embedding Chroma candidate index."
    )
    parser.add_argument("--domain-code", default="ai_app_dev")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if not args.live:
            raise RuntimeError("--live is required; candidate indexing never falls back to mock vectors")
        from app.services import candidate_index_job

        with SessionLocal() as db:
            job = candidate_index_job.try_start(db, args.domain_code)
            if job is None:
                raise RuntimeError("another candidate index rebuild is already running")
            job_id = job.id
        candidate_index_job.run_rebuild(job_id, args.domain_code, reset=args.reset)
        with SessionLocal() as db:
            completed = db.get(candidate_index_job.IndexBuildJob, job_id)
            if completed is None or completed.status != candidate_index_job.STATUS_SUCCESS:
                message = completed.message if completed is not None else "job record is missing"
                raise RuntimeError(message)
            result = dict(completed.result_json or {})
    except Exception as exc:
        error = {"status": "failed", "error_type": type(exc).__name__, "message": str(exc)}
        if args.json:
            print(json.dumps(error, ensure_ascii=False, indent=2))
        else:
            print(f"Candidate index build failed: {type(exc).__name__}: {exc}")
        raise SystemExit(1) from exc
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "Candidate index complete: "
            f"{result['indexed_items']} items, {result['indexed_chunks']} chunks, "
            f"active={result['active_collection']}."
        )


if __name__ == "__main__":
    main()
