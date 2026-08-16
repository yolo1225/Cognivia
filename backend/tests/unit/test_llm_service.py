from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from typing import Literal

from app.core.config import settings
from app.services.llm_service import (
    ModelCallError,
    ModelOutputTruncatedError,
    ModelResponseError,
    OpenAICompatibleGateway,
)


def test_gateway_disables_sdk_retries_to_preserve_bounded_retry_policy(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("app.services.llm_service.OpenAI", fake_openai)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    OpenAICompatibleGateway()._client()

    assert captured["max_retries"] == 0


class _StructuredResponse(BaseModel):
    value: int


class _VerdictItem(BaseModel):
    verdict: Literal["supported", "contradicted", "unable_to_determine"]


class _VerdictResponse(BaseModel):
    fact_checks: list[_VerdictItem]


def test_structured_failure_gets_one_targeted_correction(monkeypatch) -> None:
    requests: list[dict[str, object]] = []
    responses = iter(['{"wrong": 1}', '{"still_wrong": 2}'])

    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=next(responses)))],
            usage=None,
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    gateway = OpenAICompatibleGateway()
    monkeypatch.setattr(gateway, "_client", lambda: client)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    with pytest.raises(ModelResponseError):
        gateway.complete_json(
            model="test-model",
            system_prompt="Return value.",
            payload={"input": 1},
            response_model=_StructuredResponse,
        )

    assert len(requests) == 2
    correction = requests[1]["messages"][-1]["content"]
    assert "value" in correction
    assert requests[1]["messages"][-2]["content"] == '{"wrong": 1}'


def test_verdict_failure_correction_lists_exact_allowed_values(monkeypatch) -> None:
    requests: list[dict[str, object]] = []
    responses = iter(
        [
            '{"fact_checks":[{"verdict":"unsupported"}]}',
            '{"fact_checks":[{"verdict":"unknown"}]}',
        ]
    )

    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=next(responses)))],
            usage=None,
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    gateway = OpenAICompatibleGateway()
    monkeypatch.setattr(gateway, "_client", lambda: client)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    with pytest.raises(ModelResponseError) as captured:
        gateway.complete_json(
            model="review-model",
            system_prompt="Review claims.",
            payload={"claims": [1]},
            response_model=_VerdictResponse,
        )

    correction = requests[1]["messages"][-1]["content"]
    assert "supported, contradicted, unable_to_determine" in correction
    assert "Do not use unknown or unsupported" in correction
    assert captured.value.metadata["validation_fields"] == ["fact_checks.0.verdict"]


def test_truncated_json_is_detected_and_partial_output_is_not_echoed(monkeypatch) -> None:
    requests: list[dict[str, object]] = []
    oversized = "{" + ("x" * 20_000)

    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=oversized), finish_reason="length"
                )
            ],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=3000),
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    gateway = OpenAICompatibleGateway()
    monkeypatch.setattr(gateway, "_client", lambda: client)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    with pytest.raises(ModelOutputTruncatedError) as captured:
        gateway.complete_json(
            model="test-model",
            system_prompt="Return value.",
            payload={"input": 1},
            response_model=_StructuredResponse,
            max_output_tokens=3000,
        )

    assert len(requests) == 2
    assert requests[1]["messages"][-2]["content"] == "{}"
    assert captured.value.metadata["failure_code"] == "model_output_truncated"
    assert captured.value.metadata["tokens_output"] == 6000


def test_review_truncation_is_returned_immediately_for_batch_split(monkeypatch) -> None:
    calls = 0

    def create(**_kwargs):
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="{}"), finish_reason="length"
                )
            ],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=1400),
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    gateway = OpenAICompatibleGateway()
    monkeypatch.setattr(gateway, "_client", lambda **_kwargs: client)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    with pytest.raises(ModelOutputTruncatedError):
        gateway.complete_json(
            model="review-model",
            system_prompt="Review claims.",
            payload={"claims": [1]},
            response_model=_StructuredResponse,
            max_output_tokens=1400,
            repair_truncated_output=False,
        )

    assert calls == 1


def test_review_timeout_uses_one_transport_retry(monkeypatch) -> None:
    calls = 0
    sleeps: list[float] = []

    def create(**_kwargs):
        nonlocal calls
        calls += 1
        raise TimeoutError("provider timeout")

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    gateway = OpenAICompatibleGateway()
    monkeypatch.setattr(gateway, "_client", lambda **_kwargs: client)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr("app.services.llm_service.time.sleep", sleeps.append)

    with pytest.raises(ModelCallError) as captured:
        gateway.complete_json(
            model="review-model",
            system_prompt="Review claims.",
            payload={"claims": [1]},
            transport_retry_delays=(1,),
            timeout_seconds=45,
        )

    assert calls == 2
    assert sleeps == [1]
    assert captured.value.metadata["attempt_count"] == 2
    assert captured.value.metadata["retryable"] is True


def test_authentication_failure_is_not_retried(monkeypatch) -> None:
    calls = 0

    class AuthenticationFailure(Exception):
        status_code = 401

    def create(**_kwargs):
        nonlocal calls
        calls += 1
        raise AuthenticationFailure("unauthorized")

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    gateway = OpenAICompatibleGateway()
    monkeypatch.setattr(gateway, "_client", lambda **_kwargs: client)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    with pytest.raises(ModelCallError) as captured:
        gateway.complete_json(
            model="review-model",
            system_prompt="Review claims.",
            payload={"claims": [1]},
            transport_retry_delays=(1,),
        )

    assert calls == 1
    assert captured.value.metadata["retryable"] is False


def test_provider_5xx_uses_bounded_1_3_5_backoff(monkeypatch) -> None:
    calls = 0
    sleeps: list[float] = []

    class ProviderUnavailable(Exception):
        status_code = 503

    def create(**_kwargs):
        nonlocal calls
        calls += 1
        raise ProviderUnavailable("unavailable")

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    gateway = OpenAICompatibleGateway()
    monkeypatch.setattr(gateway, "_client", lambda **_kwargs: client)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr("app.services.llm_service.time.sleep", sleeps.append)

    with pytest.raises(ModelCallError):
        gateway.complete_json(
            model="review-model",
            system_prompt="Review claims.",
            payload={"claims": [1]},
            transport_retry_delays=(1,),
        )

    assert calls == 4
    assert sleeps == [1, 3, 5]
