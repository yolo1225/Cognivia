from sqlalchemy.orm import Session

from app.rag.readiness import candidate_rag_status
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

    def validate(self, domain_code: str) -> dict:
        knowledge_count = self.repository.knowledge_count(domain_code)
        question_count = self.repository.question_count(domain_code)
        rag = candidate_rag_status(domain_code)
        rag_ready = bool(rag.get("ready"))
        vector_count = int(rag.get("indexed_chunk_count", 0)) if rag_ready else 0
        targets = {
            "knowledge_items": 50,
            "diagnostic_questions": 60,
            "vector_chunks": knowledge_count,
        }
        issues = []
        if not rag_ready:
            issues.append(
                {
                    "level": "warning",
                    "message": "Candidate RAG 索引不可用",
                    "actual": rag.get("reason", "candidate_index_unavailable"),
                    "target": "ready",
                }
            )
        for key, message, actual, target in (
            ("knowledge_items", "知识点数量未达到 M1 目标", knowledge_count, targets["knowledge_items"]),
            ("diagnostic_questions", "诊断题数量未达到 M1 目标", question_count, targets["diagnostic_questions"]),
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
            "rag": rag,
        }
