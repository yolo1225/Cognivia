from sqlalchemy import func, select

from app.models import DiagnosticQuestion, Domain, KnowledgeItem
from app.repositories.base import Repository


class DomainRepository(Repository):
    def list(self) -> list[Domain]:
        return list(self.db.scalars(select(Domain).order_by(Domain.domain_code)))

    def knowledge_count(self, domain_code: str) -> int:
        return int(
            self.db.scalar(
                select(func.count()).select_from(KnowledgeItem).where(KnowledgeItem.domain_code == domain_code)
            )
            or 0
        )

    def question_count(self, domain_code: str) -> int:
        return int(
            self.db.scalar(
                select(func.count()).select_from(DiagnosticQuestion).where(DiagnosticQuestion.domain_code == domain_code)
            )
            or 0
        )
