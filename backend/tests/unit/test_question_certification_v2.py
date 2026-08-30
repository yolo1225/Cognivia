from __future__ import annotations

from app.services import question_certification_service as service


def _payload() -> dict:
    content = "感知机是线性二分类模型，无法解决线性不可分问题。"
    return {
        "knowledge_candidate_id": "ki_perceptron",
        "related_knowledge_candidate_ids": [],
        "question_type": "single_choice",
        "stem": "关于感知机，哪项判断正确？",
        "options": ["BPE 合并符号", "使用分词", "训练词表", "不能解决线性不可分问题"],
        "answer": 3,
        "explanation": "来源明确说明感知机无法解决线性不可分问题。",
        "rubric": [],
        "difficulty": 2,
        "quiz_level": "foundation",
        "question_bank_uses": ["diagnosis"],
        "source_chunks": [{
            "chunk_id": "ki_perceptron::chunk::0",
            "chunk_index": 0,
            "knowledge_candidate_id": "ki_perceptron",
            "knowledge_id": "ki_perceptron",
            "source_locator": "knowledge:ki_perceptron#chunk=0",
            "content": content,
            "source_content_hash": "sha256:" + "a" * 64,
            "chunker_version": service.CHUNKER_VERSION,
        }],
        "source_content_hash": "sha256:" + __import__("hashlib").sha256(
            b'{"ki_perceptron::chunk::0":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
        ).hexdigest(),
        "evidence_quotes": [{
            "source_ref_id": "ki_perceptron::chunk::0",
            "quote": content,
        }],
    }


def test_cross_knowledge_distractors_can_pass_with_warning(monkeypatch) -> None:
    monkeypatch.setattr(
        service.gateway,
        "complete_json",
        lambda **_kwargs: ({
            "decisions": [{
                "question_id": "q1", "verdict": "pass", "failed_fields": [],
                "reason": "", "warnings": ["干扰项区分度较低"],
            }]
        }, {"provider_mode": "live"}),
    )
    result = service.certify_question_payloads([("q1", _payload())])["q1"]
    assert result.issue_kind == "valid"
    assert result.warnings == ["干扰项区分度较低"]


def test_ambiguous_option_is_content_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        service.gateway,
        "complete_json",
        lambda **_kwargs: ({
            "decisions": [{
                "question_id": "q1", "verdict": "fail", "failed_fields": ["options"],
                "reason": "选项 B 在题干语境下也可能成立", "warnings": [],
            }]
        }, {}),
    )
    result = service.certify_question_payloads([("q1", _payload())])["q1"]
    assert result.issue_kind == "content_rejected"
    assert result.issue_fields == ["options"]
    assert "选项 B" in result.issue_reason


def test_missing_decision_is_service_error(monkeypatch) -> None:
    monkeypatch.setattr(
        service.gateway,
        "complete_json",
        lambda **_kwargs: ({"decisions": []}, {}),
    )
    result = service.certify_question_payloads([("q1", _payload())])["q1"]
    assert result.issue_kind == "certification_service_error"
    assert result.report["service_error"] == "missing_decision"


def test_failed_decision_requires_fields_and_reason() -> None:
    try:
        service.CertificationDecision(
            question_id="q1", verdict="fail", failed_fields=[], reason=""
        )
    except ValueError:
        pass
    else:
        raise AssertionError("a failed decision must be actionable")


def test_strict_adapter_keeps_valid_sibling_and_drops_invalid_decision() -> None:
    adapted = service._strict_decision_adapter({
        "decisions": [
            {"question_id": "q1", "verdict": "pass", "failed_fields": [], "warnings": []},
            {"question_id": "q2", "verdict": "fail", "failed_fields": ["unknown"], "reason": "bad"},
        ]
    })
    assert [value["question_id"] for value in adapted["decisions"]] == ["q1"]


def test_known_provider_field_aliases_are_canonicalized() -> None:
    decision = service.CertificationDecision(
        question_id="q1",
        verdict="fail",
        failed_fields=["correct_answer", "source_chunks"],
        reason="答案缺少来源",
    )
    assert decision.failed_fields == ["answer", "source"]


def test_single_failed_field_string_is_normalized_to_list() -> None:
    decision = service.CertificationDecision(
        question_id="q1",
        verdict="fail",
        failed_fields="options",
        reason="存在歧义",
    )
    assert decision.failed_fields == ["options"]


def test_comma_separated_failed_fields_are_normalized() -> None:
    decision = service.CertificationDecision(
        question_id="q1",
        verdict="fail",
        failed_fields="answer, explanation, rubric",
        reason="答案与解析缺少支持",
    )
    assert decision.failed_fields == ["answer", "explanation", "rubric"]


def test_source_unsupported_distractors_become_warning() -> None:
    decision = service.CertificationDecision(
        question_id="q1",
        verdict="fail",
        failed_fields=["options"],
        reason="部分干扰项与题干无关且未在提供的 source_chunks 中出现",
    )
    result = service._apply_distractor_policy(decision, _payload())
    assert result.verdict == "pass"
    assert result.warnings


def test_ambiguous_distractors_remain_rejected() -> None:
    decision = service.CertificationDecision(
        question_id="q1",
        verdict="fail",
        failed_fields=["options"],
        reason="选项与来源无关，而且选项 B 也可能成立，存在歧义",
    )
    result = service._apply_distractor_policy(decision, _payload())
    assert result.verdict == "fail"
