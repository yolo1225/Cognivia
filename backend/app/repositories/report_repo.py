from sqlalchemy import select

from app.models import Feedback, GenerationTask, Learner, LearningPath, LearningResource, ReviewReport
from app.repositories.base import Repository


class ReportRepository(Repository):
    def learner(self, public_id: str) -> Learner | None:
        return self.db.scalar(select(Learner).where(Learner.public_id == public_id))

    def latest_path(self, learner_id: int) -> LearningPath | None:
        return self.db.scalar(select(LearningPath).where(LearningPath.learner_id == learner_id).order_by(LearningPath.id.desc()))

    def resources(self, learner_id: int) -> list[tuple[LearningResource, GenerationTask]]:
        return list(self.db.execute(select(LearningResource, GenerationTask).join(GenerationTask, GenerationTask.id == LearningResource.generation_task_id).where(GenerationTask.learner_id == learner_id).order_by(LearningResource.id.desc())))

    def reviews(self, learner_id: int) -> list[ReviewReport]:
        return list(self.db.scalars(select(ReviewReport).join(LearningResource, LearningResource.id == ReviewReport.resource_id).join(GenerationTask, GenerationTask.id == LearningResource.generation_task_id).where(GenerationTask.learner_id == learner_id).order_by(ReviewReport.id.desc())))

    def feedback(self, learner_id: int) -> list[tuple[Feedback, LearningResource]]:
        return list(self.db.execute(select(Feedback, LearningResource).join(LearningResource, LearningResource.id == Feedback.resource_id).where(Feedback.learner_id == learner_id).order_by(Feedback.id.desc())))
