from app.scripts.evaluate_knowledge_import_gold import build_gold, evaluate


def test_knowledge_import_gold_has_required_sample_sizes_and_metrics() -> None:
    gold = build_gold()
    assert len(gold["normalization"]) == 50
    assert 50 <= len(gold["relations"]) <= 100
    assert len(gold["questions"]) == 30

    result = evaluate({key: gold[key] for key in ("normalization", "relations", "questions")})

    assert result["sample_version"] == "knowledge-import-gold-v1"
    assert result["passed"] is True
    for metric in (
        "normalization_accuracy",
        "relation_precision",
        "direction_accuracy",
        "question_accuracy",
    ):
        assert result[metric]["numerator"] == result[metric]["denominator"]
        assert result[metric]["rate"] == 1.0
        assert result[metric]["failure_ids"] == []
