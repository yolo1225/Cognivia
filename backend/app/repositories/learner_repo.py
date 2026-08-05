from sqlalchemy import select

from app.models import Learner
from app.repositories.base import Repository


class LearnerRepository(Repository):
    def list(self) -> list[Learner]:
        return list(self.db.scalars(select(Learner).order_by(Learner.public_id)))

    def get(self, public_id: str) -> Learner | None:
        return self.db.scalar(select(Learner).where(Learner.public_id == public_id))

    def add(self, learner: Learner) -> Learner:
        self.db.add(learner)
        self.db.flush()
        return learner
