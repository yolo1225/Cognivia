from sqlalchemy import func, select

from app.models import KnowledgeItem
from app.repositories.base import Repository


class KnowledgeRepository(Repository):
    def get(self, public_id: str) -> KnowledgeItem | None:
        return self.db.scalar(select(KnowledgeItem).where(KnowledgeItem.public_id == public_id))

    def find_by_name(self, domain_code: str, name: str) -> KnowledgeItem | None:
        return self.db.scalar(
            select(KnowledgeItem).where(
                KnowledgeItem.domain_code == domain_code,
                KnowledgeItem.name == name,
            )
        )

    def list(self, domain_code: str, category: str | None, limit: int, offset: int) -> tuple[list[KnowledgeItem], int]:
        filters = [KnowledgeItem.domain_code == domain_code]
        if category:
            filters.append(KnowledgeItem.category == category)
        total = int(self.db.scalar(select(func.count()).select_from(KnowledgeItem).where(*filters)) or 0)
        items = list(
            self.db.scalars(
                select(KnowledgeItem)
                .where(*filters)
                .order_by(KnowledgeItem.category, KnowledgeItem.public_id)
                .offset(offset)
                .limit(limit)
            )
        )
        return items, total

    def add(self, item: KnowledgeItem) -> KnowledgeItem:
        self.db.add(item)
        self.db.flush()
        return item
