from app.agents.claim_policy import (
    ClaimCategory,
    ReviewDisposition,
    RiskLevel,
    capability_violation_for_claim,
    classify_claim,
    sanitize_deterministic_text,
)


def test_all_structured_field_categories_use_one_policy() -> None:
    cases = [
        ("title", "跨领域练习", ClaimCategory.ORGANIZATIONAL_TEXT, RiskLevel.LOW),
        ("instruction", "系统默认执行三次", ClaimCategory.OPERATIONAL_FACT, RiskLevel.HIGH),
        ("code_or_command", "RUN VALVE A", ClaimCategory.CODE_OR_COMMAND, RiskLevel.HIGH),
        ("expected_result", "固定返回 ready", ClaimCategory.FIXED_RESULT, RiskLevel.HIGH),
        ("troubleshooting", "失败时检查阀门", ClaimCategory.ERROR_HANDLING, RiskLevel.HIGH),
        ("factual", "适用于 2.1.0 版本", ClaimCategory.VERSION_BOUNDARY, RiskLevel.HIGH),
        ("quiz_answer", "阀门 A", ClaimCategory.QUIZ_FACT, RiskLevel.HIGH),
        ("factual", "压力变化会影响读数", ClaimCategory.VERIFIABLE_FACT, RiskLevel.NORMAL),
    ]
    for field_group, text, category, risk in cases:
        decision = classify_claim(field_group, text)
        assert decision.category is category
        assert decision.risk_level is risk


def test_chinese_and_english_teaching_actions_are_excluded() -> None:
    for text in (
        "请阅读材料并记录自己的观察结果",
        "学习者提交练习记录并标注引用材料",
        "Please compare the materials and record your observations",
    ):
        decision = classify_claim("instruction", text)
        assert decision.category is ClaimCategory.TEACHING_ACTION
        assert decision.review_disposition is ReviewDisposition.EXCLUDE


def test_quiz_question_only_keeps_an_independent_factual_premise() -> None:
    assert classify_claim(
        "quiz_prompt", "哪一种方法适合当前任务？"
    ).review_disposition is ReviewDisposition.EXCLUDE
    assert classify_claim(
        "quiz_prompt", "系统默认自动重试三次，哪一种说明正确？"
    ).review_disposition is ReviewDisposition.DUAL_REVIEW
    assert classify_claim(
        "quiz_prompt", "当系统需要自动复审时，应采取什么动作？"
    ).review_disposition is ReviewDisposition.EXCLUDE


def test_explicit_capability_validation_is_domain_neutral() -> None:
    assert (
        capability_violation_for_claim(
            "instruction", "执行阀门校准", {"concept"}
        )
        == "operation_evidence_missing"
    )
    assert (
        capability_violation_for_claim(
            "instruction", "执行阀门校准", {"concept", "operation"}
        )
        is None
    )
    assert (
        capability_violation_for_claim(
            "code_or_command", "CALIBRATE VALVE A", {"operation"}
        )
        == "executable_evidence_missing"
    )


def test_deterministic_sanitization_is_sentence_level_and_idempotent() -> None:
    value = "压力变化会影响读数。所有结论均源自所列官方文档。"
    once, codes = sanitize_deterministic_text("summary", value)
    twice, second_codes = sanitize_deterministic_text("summary", once)

    assert once == "压力变化会影响读数"
    assert codes == ["forbidden_meta_claim"]
    assert twice == once
    assert second_codes == []
