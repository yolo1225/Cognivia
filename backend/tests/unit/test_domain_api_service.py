from app.services.domain_api_service import DomainApiService


class FakeRepository:
    def __init__(self, knowledge_count: int = 50, question_count: int = 60) -> None:
        self.knowledge_count_value = knowledge_count
        self.question_count_value = question_count

    def knowledge_count(self, _domain_code: str) -> int:
        return self.knowledge_count_value

    def question_count(self, _domain_code: str) -> int:
        return self.question_count_value

    def evidence_capability_counts(self, _domain_code: str) -> tuple[int, int]:
        return self.knowledge_count_value, min(8, self.knowledge_count_value)


def build_service(knowledge_count: int = 50, question_count: int = 60) -> DomainApiService:
    service = DomainApiService.__new__(DomainApiService)
    service.repository = FakeRepository(knowledge_count, question_count)
    return service


def test_validation_passes_with_ready_candidate_index_even_without_legacy_collection(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.domain_api_service.candidate_rag_status",
        lambda _domain_code: {
            "ready": True,
            "active_collection": "knowledge_ai_app_dev_candidate_v3",
            "indexed_chunk_count": 93,
        },
    )

    result = build_service().validate("ai_app_dev")

    assert result["passed"] is True
    assert result["counts"]["chroma_vectors"] == 93
    assert result["issues"] == []
    assert result["rag"]["ready"] is True


def test_validation_reports_candidate_reason_without_document_status(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.domain_api_service.candidate_rag_status",
        lambda _domain_code: {"ready": False, "reason": "candidate_index_stale"},
    )

    result = build_service().validate("ai_app_dev")

    assert result["passed"] is False
    assert result["counts"]["chroma_vectors"] == 0
    assert result["issues"] == [
        {
            "level": "warning",
            "message": "Candidate RAG 索引不可用",
            "actual": "candidate_index_stale",
            "target": "ready",
        }
    ]


def test_validation_keeps_mvp_data_thresholds_as_blockers(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.domain_api_service.candidate_rag_status",
        lambda _domain_code: {"ready": True, "indexed_chunk_count": 40},
    )

    result = build_service(knowledge_count=49, question_count=59).validate("ai_app_dev")

    assert result["passed"] is False
    assert {issue["message"] for issue in result["issues"]} == {
        "知识点数量未达到 M1 目标",
        "诊断题数量未达到 M1 目标",
    }
