from sqlalchemy import select

from app.models import GenerationTask, GraphCheckpoint, ManualReviewTask
from app.repositories.base import Repository


class ManualReviewRepository(Repository):
    def list(self, status: str | None) -> list[tuple[ManualReviewTask, GenerationTask]]:
        statement = select(ManualReviewTask, GenerationTask).join(GenerationTask, GenerationTask.id == ManualReviewTask.task_id).order_by(ManualReviewTask.created_at.desc())
        if status:
            statement = statement.where(ManualReviewTask.status == status)
        return list(self.db.execute(statement))

    def get(self, public_id: str) -> ManualReviewTask | None:
        return self.db.scalar(select(ManualReviewTask).where(ManualReviewTask.public_id == public_id))

    def detail(self, public_id: str) -> tuple[ManualReviewTask, GenerationTask] | None:
        return self.db.execute(select(ManualReviewTask, GenerationTask).join(GenerationTask, GenerationTask.id == ManualReviewTask.task_id).where(ManualReviewTask.public_id == public_id)).first()

    def checkpoint(self, task_public_id: str) -> GraphCheckpoint | None:
        return self.db.scalar(select(GraphCheckpoint).where(GraphCheckpoint.task_id == task_public_id))
