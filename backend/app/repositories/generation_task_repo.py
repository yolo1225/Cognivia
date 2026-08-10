from sqlalchemy import select

from app.models import AgentRun, GenerationTask, Learner, LearnerProfile, LearningResource
from app.repositories.base import Repository


class GenerationTaskRepository(Repository):
    def task(self, public_id: str) -> GenerationTask | None:
        return self.db.scalar(select(GenerationTask).where(GenerationTask.public_id == public_id))

    def learner(self, public_id: str) -> Learner | None:
        return self.db.scalar(select(Learner).where(Learner.public_id == public_id))

    def profile(self, public_id: str) -> LearnerProfile | None:
        return self.db.scalar(select(LearnerProfile).where(LearnerProfile.public_id == public_id))

    def active_task(self, learner_id: str, statuses: set[str]) -> GenerationTask | None:
        return self.db.scalar(
            select(GenerationTask)
            .join(Learner, Learner.id == GenerationTask.learner_id)
            .where(Learner.public_id == learner_id, GenerationTask.status.in_(statuses))
            .order_by(GenerationTask.created_at.desc(), GenerationTask.id.desc())
        )

    def resources(self, task_id: int) -> list[LearningResource]:
        return list(self.db.scalars(select(LearningResource).where(LearningResource.generation_task_id == task_id).order_by(LearningResource.id)))

    def runs(self, task_id: int) -> list[AgentRun]:
        return list(self.db.scalars(select(AgentRun).where(AgentRun.generation_task_id == task_id).order_by(AgentRun.id)))

    def add(self, task: GenerationTask) -> GenerationTask:
        self.db.add(task)
        self.db.flush()
        return task
