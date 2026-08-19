from app.models import DiagnosticQuestion
from app.services import diagnostic_scoring_service as service


def _question() -> DiagnosticQuestion:
    return DiagnosticQuestion(
        public_id="question_short_1",
        domain_code="ai_app_dev",
        knowledge_item_id=1,
        question_type="short_answer",
        stem="说明向量检索的作用",
        options_json=[],
        answer_key_json={"rubric": ["语义表示", "相似度检索"]},
        difficulty=2,
    )


def test_legacy_rubric_is_normalized() -> None:
    rubric = service.normalize_rubric(_question())
    assert [item.criterion_id for item in rubric] == ["criterion_1", "criterion_2"]
    assert sum(item.max_score for item in rubric) == 1


def test_single_question_provider_shape_is_wrapped_as_batch() -> None:
    assert service._adapt_batch_response({"question_id": "q1"}) == {
        "results": [{"question_id": "q1"}]
    }


def test_semantic_synonym_gets_partial_credit_but_uncertain_result_cannot_pass(monkeypatch) -> None:
    def complete_json(**_kwargs):
        return (
            {
                "results": [
                    {
                        "question_id": "question_short_1",
                        "criteria": [
                            {"criterion_id": "criterion_1", "score": 0.5, "rationale": "概念正确"},
                            {"criterion_id": "criterion_2", "score": 0.5, "rationale": "目的正确"},
                        ],
                        "matched_points": ["能找到意义接近的文本"],
                        "missing_points": [],
                        "factual_errors": [],
                        "total_score": 1,
                        "confidence": 0.9,
                        "ai_comment": "同义表达正确。",
                    }
                ]
            },
            {"model_name": "test-model", "tokens_input": 10, "tokens_output": 10},
        )

    monkeypatch.setattr(service.gateway, "complete_json", complete_json)
    results, _ = service.score_short_answer_batch(
        [(_question(), "它会找到意思最接近的内容，而不是只比较字面。")]
    )
    result = results["question_short_1"]
    assert 0 < result["total_score"] < service.PASS_SCORE
    assert result["scoring_uncertain"] is True
    assert result["is_correct"] is False


def test_keyword_pile_cannot_override_low_model_score(monkeypatch) -> None:
    def complete_json(**_kwargs):
        return (
            {
                "results": [
                    {
                        "question_id": "question_short_1",
                        "criteria": [
                            {"criterion_id": "criterion_1", "score": 0.1, "rationale": "未解释"},
                            {"criterion_id": "criterion_2", "score": 0.1, "rationale": "未解释"},
                        ],
                        "matched_points": [],
                        "missing_points": ["概念关系"],
                        "factual_errors": [],
                        "total_score": 0.2,
                        "confidence": 0.95,
                        "ai_comment": "只堆砌了关键词。",
                    }
                ]
            },
            {"model_name": "test-model"},
        )

    monkeypatch.setattr(service.gateway, "complete_json", complete_json)
    results, _ = service.score_short_answer_batch([(_question(), "语义表示 相似度检索")])
    assert results["question_short_1"]["total_score"] == 0.2
    assert results["question_short_1"]["is_correct"] is False
