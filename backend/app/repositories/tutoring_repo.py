from sqlalchemy import select

from app.models import LearningResource, TutoringSession
from app.repositories.base import Repository


class TutoringRepository(Repository):
    def session(self, public_id: str) -> TutoringSession | None:
        return self.db.scalar(select(TutoringSession).where(TutoringSession.public_id == public_id))

    def resource(self, public_id: str) -> LearningResource | None:
        return self.db.scalar(select(LearningResource).where(LearningResource.public_id == public_id))
