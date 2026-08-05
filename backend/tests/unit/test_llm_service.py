from __future__ import annotations

from app.core.config import settings
from app.services.llm_service import OpenAICompatibleGateway


def test_gateway_disables_sdk_retries_to_preserve_bounded_retry_policy(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("app.services.llm_service.OpenAI", fake_openai)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    OpenAICompatibleGateway()._client()

    assert captured["max_retries"] == 0
