from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import DomainIndexManifest
from app.rag.candidate_manifest import (
    CandidateIndexManifest,
    CandidateManifestError,
    CandidateManifestStore,
)


class DatabaseManifestStore:
    """MySQL-backed active index pointer with read-only file compatibility."""

    def __init__(
        self, db: Session | None = None, fallback: CandidateManifestStore | None = None
    ) -> None:
        self.db = db
        self.fallback = fallback or CandidateManifestStore()

    @staticmethod
    def _manifest(row: DomainIndexManifest) -> CandidateIndexManifest:
        updated = row.updated_at or datetime.now(UTC)
        return CandidateIndexManifest(
            schema_version="candidate-index-manifest-v1",
            active_collection=row.active_collection,
            previous_collection=row.previous_collection,
            domain_code=row.domain_code,
            embedding_model=row.embedding_model,
            embedding_dimensions=row.embedding_dimensions,
            distance_metric=row.distance_metric,
            chunker_version=row.chunker_version,
            index_version=row.index_version,
            source_data_version=row.source_data_version,
            last_successful_sync_at=updated.isoformat(),
            indexed_item_count=row.indexed_item_count,
            indexed_chunk_count=row.indexed_chunk_count,
        )

    def load(
        self,
        domain_code: str,
        *,
        collection_exists: Callable[[str], bool] | None = None,
    ) -> CandidateIndexManifest | None:
        owns = self.db is None
        db = self.db or SessionLocal()
        try:
            row = db.scalar(
                select(DomainIndexManifest).where(
                    DomainIndexManifest.domain_code == domain_code,
                    DomainIndexManifest.status == "active",
                )
            )
            if row is None:
                legacy = self.fallback.load(domain_code, collection_exists=collection_exists)
                if legacy is None:
                    return None
                self._upsert(db, legacy)
                if owns:
                    db.commit()
                else:
                    db.flush()
                return legacy
            manifest = self._manifest(row)
            manifest.validate()
            if collection_exists and not collection_exists(manifest.active_collection):
                raise CandidateManifestError("manifest active_collection does not exist")
            return manifest
        finally:
            if owns:
                db.close()

    def _upsert(self, db: Session, manifest: CandidateIndexManifest) -> None:
        row = db.scalar(
            select(DomainIndexManifest).where(
                DomainIndexManifest.domain_code == manifest.domain_code
            )
        )
        if row is None:
            row = DomainIndexManifest(domain_code=manifest.domain_code)
            db.add(row)
        row.active_collection = manifest.active_collection
        row.previous_collection = manifest.previous_collection
        row.index_version = manifest.index_version
        row.source_data_version = manifest.source_data_version
        row.embedding_model = manifest.embedding_model
        row.embedding_dimensions = manifest.embedding_dimensions
        row.distance_metric = manifest.distance_metric
        row.chunker_version = manifest.chunker_version
        row.indexed_item_count = manifest.indexed_item_count
        row.indexed_chunk_count = manifest.indexed_chunk_count
        row.status = "active"

    def write(self, manifest: CandidateIndexManifest) -> None:
        manifest.validate()
        owns = self.db is None
        db = self.db or SessionLocal()
        try:
            self._upsert(db, manifest)
            if owns:
                db.commit()
            else:
                db.flush()
        finally:
            if owns:
                db.close()

    def remove(self, domain_code: str) -> None:
        owns = self.db is None
        db = self.db or SessionLocal()
        try:
            row = db.scalar(
                select(DomainIndexManifest).where(
                    DomainIndexManifest.domain_code == domain_code
                )
            )
            if row is not None:
                db.delete(row)
            if owns:
                db.commit()
            else:
                db.flush()
        finally:
            if owns:
                db.close()
