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


def test_scores_provider_shape_is_normalized_to_results() -> None:
    payload = {"scores": [{"question_id": "q1"}], "summary": "ok"}
    assert service._adapt_batch_response(payload) == {
        "scores": [{"question_id": "q1"}],
        "results": [{"question_id": "q1"}],
        "summary": "ok",
    }


def test_missing_criteria_are_not_fabricated() -> None:
    payload = {
        "scores": [
            {
                "question_id": "q1",
                "total_score": 0.8,
                "confidence": 0.9,
                "ai_comment": "总体正确。",
            }
        ]
    }
    adapted = service._adapt_batch_response(
        payload,
        {
            "q1": [
                {
                    "criterion_id": "criterion_1",
                    "description": "核心概念",
                    "max_score": 1.0,
                    "required_concepts": [],
                    "equivalent_expressions": [],
                }
            ]
        },
    )
    assert "criteria" not in adapted["results"][0]


def test_partial_batch_retries_only_invalid_questions(monkeypatch) -> None:
    second = _question()
    second.public_id = "question_short_2"
    calls = []

    def complete_json(**kwargs):
        question_ids = [item["question_id"] for item in kwargs["payload"]["questions"]]
        calls.append(question_ids)
        results = []
        for question_id in question_ids:
            item = {
                "question_id": question_id,
                "criteria": [
                    {"criterion_id": "criterion_1", "score": 0.4, "rationale": "有效依据"}
                ],
                "matched_points": ["语义表示"],
                "missing_points": [],
                "factual_errors": [],
                "total_score": 0.8,
                "ai_comment": "回答有效。",
            }
            if question_id != "question_short_2" or len(calls) > 1:
                item["confidence"] = 0.9
            results.append(item)
        return {"results": results}, {"model_name": "test-model", "attempt": 1}

    monkeypatch.setattr(service.gateway, "complete_json", complete_json)
    monkeypatch.setattr(service.time, "sleep", lambda _seconds: None)
    results, metadata = service.score_short_answer_batch(
        [(_question(), "语义表示"), (second, "语义表示")]
    )

    assert calls == [
        ["question_short_1", "question_short_2"],
        ["question_short_2"],
    ]
    assert set(results) == {"question_short_1", "question_short_2"}
    assert metadata["llm_calls"] == 2


def test_all_invalid_questions_remain_pending_after_four_calls(monkeypatch) -> None:
    calls = []

    def complete_json(**kwargs):
        calls.append([item["question_id"] for item in kwargs["payload"]["questions"]])
        return {
            "results": [
                {
                    "question_id": "question_short_1",
                    "criteria": [],
                    "matched_points": [],
                    "missing_points": [],
                    "factual_errors": [],
                    "total_score": 0.5,
                }
            ]
        }, {"model_name": "test-model", "attempt": 1}

    monkeypatch.setattr(service.gateway, "complete_json", complete_json)
    monkeypatch.setattr(service.time, "sleep", lambda _seconds: None)
    results, metadata = service.score_short_answer_batch([(_question(), "语义表示")])

    assert results == {}
    assert len(calls) == 4
    assert metadata["failed_question_ids"] == ["question_short_1"]
    assert set(metadata["validation_fields"]["question_short_1"]) >= {
        "confidence",
        "ai_comment",
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
