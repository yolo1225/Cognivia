from sqlalchemy.orm import Session

from app.rag.vector_store import VectorStore
from app.repositories.domain_repo import DomainRepository


class DomainApiService:
    def __init__(self, db: Session) -> None:
        self.repository = DomainRepository(db)

    def list(self) -> list[dict]:
        return [
            {
                "domain_code": domain.domain_code,
                "name": domain.name,
                "domain_schema_version": domain.schema_version,
                "status": "active",
                "config": domain.config_json,
            }
            for domain in self.repository.list()
        ]

    def validate(self, domain_code: str, vector_store: VectorStore) -> dict:
        knowledge_count = self.repository.knowledge_count(domain_code)
        question_count = self.repository.question_count(domain_code)
        vector_count = vector_store.get_collection(domain_code).count()
        targets = {
            "knowledge_items": 50,
            "diagnostic_questions": 60,
            "vector_chunks": knowledge_count,
        }
        issues = []
        for key, message, actual, target in (
            ("knowledge_items", "知识点数量未达到 M1 目标", knowledge_count, targets["knowledge_items"]),
            ("diagnostic_questions", "诊断题数量未达到 M1 目标", question_count, targets["diagnostic_questions"]),
            ("vector_chunks", "ChromaDB 向量数量少于知识切片数量", vector_count, targets["vector_chunks"]),
        ):
            if actual < target:
                issues.append({"level": "warning", "message": message, "actual": actual, "target": target})
        return {
            "domain_code": domain_code,
            "passed": not issues,
            "counts": {
                "knowledge_items": knowledge_count,
                "diagnostic_questions": question_count,
                "chroma_vectors": vector_count,
            },
            "targets": targets,
            "issues": issues,
        }
