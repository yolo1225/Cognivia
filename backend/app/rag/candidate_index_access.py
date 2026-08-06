from __future__ import annotations

from typing import Any

from app.rag.candidate_manifest import CandidateIndexManifest, CandidateManifestError, CandidateManifestStore


class CandidateIndexUnavailable(RuntimeError):
    """The active candidate index cannot be used safely."""


class CandidateIndexAccess:
    """Read-only access to the manifest-selected V2 candidate collection."""

    def __init__(self, chroma_client: Any, manifest_store: CandidateManifestStore | None = None) -> None:
        self.client = chroma_client
        self.manifests = manifest_store or CandidateManifestStore()

    def active(self, domain_code: str) -> tuple[CandidateIndexManifest, Any]:
        try:
            manifest = self.manifests.load(domain_code, collection_exists=self._collection_exists)
        except CandidateManifestError as exc:
            raise CandidateIndexUnavailable(f"candidate manifest is invalid: {exc}") from exc
        if manifest is None:
            raise CandidateIndexUnavailable("candidate manifest is missing")
        try:
            collection = self.client.get_collection(name=manifest.active_collection)
        except Exception as exc:
            raise CandidateIndexUnavailable("candidate active collection is unavailable") from exc
        if collection.count() != manifest.indexed_chunk_count:
            raise CandidateIndexUnavailable("candidate collection count does not match manifest")
        metadata = dict(getattr(collection, "metadata", None) or {})
        expected = {
            "domain_code": manifest.domain_code,
            "embedding_model": manifest.embedding_model,
            "embedding_dimensions": manifest.embedding_dimensions,
            "distance_metric": manifest.distance_metric,
            "index_version": manifest.index_version,
            "chunker_version": manifest.chunker_version,
        }
        for key, value in expected.items():
            if metadata.get(key) != value:
                raise CandidateIndexUnavailable(
                    f"candidate collection metadata mismatch: {key}"
                )
        return manifest, collection

    def _collection_exists(self, name: str) -> bool:
        try:
            self.client.get_collection(name=name)
        except Exception:
            return False
        return True
