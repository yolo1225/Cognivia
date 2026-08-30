from types import SimpleNamespace

from app.services.ability_weight_service import ability_weight_gate, normalize_ability_weights
from app.services.knowledge_model_import_service import complete_candidate_ability_weights


VALID_WEIGHTS = {
    "theory": 0.4,
    "practice": 0.2,
    "problem_solving": 0.2,
    "knowledge_breadth": 0.2,
    "learning_speed": 0.0,
}


def _candidate(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(
        public_id="candidate_1",
        candidate_type="knowledge_item",
        payload_json=payload,
    )


def test_explicit_valid_weights_pass_and_are_not_overwritten(monkeypatch) -> None:
    candidate = _candidate({
        "ability_weights": dict(VALID_WEIGHTS),
        "ability_weight_source": "explicit",
        "ability_weight_confidence": 1.0,
    })

    def unexpected_call(**_kwargs):
        raise AssertionError("explicit weights must not invoke the model")

    monkeypatch.setattr(
        "app.services.knowledge_model_import_service.gateway.complete_json",
        unexpected_call,
    )
    complete_candidate_ability_weights([candidate])

    assert candidate.payload_json["ability_weights"] == VALID_WEIGHTS
    assert ability_weight_gate(candidate.payload_json) == []


def test_model_completes_missing_weights(monkeypatch) -> None:
    candidate = _candidate({"name": "向量检索", "content": "基于相似度召回证据"})
    monkeypatch.setattr(
        "app.services.knowledge_model_import_service.gateway.complete_json",
        lambda **_kwargs: (
            {"result": {"ability_weights": dict(VALID_WEIGHTS), "confidence": 0.9}},
            {},
        ),
    )

    complete_candidate_ability_weights([candidate])

    assert candidate.payload_json["ability_weight_source"] == "model"
    assert candidate.payload_json["ability_weight_confidence"] == 0.9
    assert ability_weight_gate(candidate.payload_json) == []


def test_invalid_or_low_confidence_model_weights_are_blocked() -> None:
    invalid = {**VALID_WEIGHTS, "learning_speed": 0.1}
    assert normalize_ability_weights(invalid) is None
    assert ability_weight_gate({
        "ability_weights": invalid,
        "ability_weight_source": "model",
        "ability_weight_confidence": 0.9,
    })
    assert ability_weight_gate({
        "ability_weights": VALID_WEIGHTS,
        "ability_weight_source": "model",
        "ability_weight_confidence": 0.74,
    }) == ["模型生成的能力权重置信度不足"]


def test_admin_weights_pass_only_with_fixed_dimensions() -> None:
    assert ability_weight_gate({
        "ability_weights": VALID_WEIGHTS,
        "ability_weight_source": "admin",
        "ability_weight_confidence": 1.0,
    }) == []
    assert ability_weight_gate({
        "ability_weights": {**VALID_WEIGHTS, "learning_speed": 0.01},
        "ability_weight_source": "admin",
        "ability_weight_confidence": 1.0,
    }) == ["能力权重不合法或缺失"]
