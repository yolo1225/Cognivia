from __future__ import annotations

from sqlalchemy import select

from app.models import GenerationTask, LearningResource
from app.repositories.base import Repository


class ResourceRepository(Repository):
    def get(self, public_id: str) -> LearningResource | None:
        return self.db.scalar(select(LearningResource).where(LearningResource.public_id == public_id))

    def list(self, include_unpublished: bool) -> list[tuple[LearningResource, GenerationTask]]:
        statement = (
            select(LearningResource, GenerationTask)
            .join(GenerationTask, GenerationTask.id == LearningResource.generation_task_id)
            .order_by(GenerationTask.created_at.desc(), LearningResource.id.asc())
            .limit(100)
        )
        if not include_unpublished:
            statement = statement.where(LearningResource.is_current.is_(True), LearningResource.review_status == "passed")
        return list(self.db.execute(statement))

    def versions(self, series_id: str) -> list[LearningResource]:
        return list(self.db.scalars(select(LearningResource).where(LearningResource.series_id == series_id).order_by(LearningResource.version.desc())))
