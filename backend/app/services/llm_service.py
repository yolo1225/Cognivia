from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterator, Sequence
from typing import Any, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app.core.config import settings


logger = logging.getLogger(__name__)
ResponseModel = TypeVar("ResponseModel", bound=BaseModel)
ResponseAdapter = Callable[[Any], dict[str, Any]]


class ModelGatewayError(RuntimeError):
    """Base error for safe model failures exposed to workers and health checks."""


class ModelConfigurationError(ModelGatewayError):
    pass


class ModelResponseError(ModelGatewayError):
    """Safe structured-output failure; metadata intentionally excludes model content."""

    def __init__(self, message: str, *, metadata: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.metadata = metadata or {}


class ModelOutputTruncatedError(ModelResponseError):
    """The provider stopped because the configured output limit was reached."""


class ModelCallError(ModelGatewayError):
    """Transport/provider failure with payload-safe call metadata."""

    def __init__(self, message: str, *, metadata: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.metadata = metadata or {}


class OpenAICompatibleGateway:
    """Central model gateway with bounded retry and JSON output validation."""

    RETRY_DELAYS = (1, 3, 5)

    def _client(self, *, timeout_seconds: float | None = None) -> OpenAI:
        if not settings.openai_api_key:
            raise ModelConfigurationError("OPENAI_API_KEY is not configured")
        return OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_api_base,
            timeout=timeout_seconds or settings.llm_timeout_seconds,
            # The gateway implements the only permitted retry policy below:
            # initial request plus the three documented backoff retries.
            # Disable the SDK's implicit retries to avoid multiplicative waits.
            max_retries=0,
        )

    def complete_json(
        self,
        *,
        model: str | None,
        system_prompt: str,
        payload: dict[str, Any],
        fixture_factory: Callable[[], dict[str, Any]] | None = None,
        response_model: type[ResponseModel] | None = None,
        response_adapter: ResponseAdapter | None = None,
        max_output_tokens: int | None = None,
        timeout_seconds: float | None = None,
        transport_retry_delays: Sequence[float] | None = None,
        repair_truncated_output: bool = True,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        started_at = time.perf_counter()
        if not model or not settings.openai_api_key:
            if (
                settings.app_env != "production"
                and settings.allow_fixture_llm
                and fixture_factory is not None
            ):
                result = fixture_factory()
                if response_adapter is not None:
                    result = response_adapter(result)
                return self._validate(result, response_model), {
                    "provider_mode": "fixture",
                    "model_name": model or "fixture-model",
                    "tokens_input": 0,
                    "tokens_output": 0,
                    "duration_ms": round((time.perf_counter() - started_at) * 1000),
                }
            raise ModelConfigurationError("model channel is not configured")

        last_error: Exception | None = None
        client = (
            self._client(timeout_seconds=timeout_seconds)
            if timeout_seconds is not None
            else self._client()
        )
        invalid_content: str | None = None
        invalid_fields: list[str] = []
        validation_failures = 0
        tokens_input = 0
        tokens_output = 0
        attempt = 0
        retry_count = 0
        timeout_delays = tuple(
            self.RETRY_DELAYS
            if transport_retry_delays is None
            else transport_retry_delays
        )
        while True:
            attempt += 1
            content = "{}"
            try:
                messages: list[dict[str, str]] = [
                    {
                        "role": "system",
                        "content": _structured_system_prompt(
                            system_prompt, response_model=response_model
                        ),
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ]
                if invalid_content is not None:
                    correction = (
                        "Correct only the listed invalid fields and return the complete JSON object. "
                        "The previous response failed validation at: "
                        + ", ".join(invalid_fields)
                    )
                    if any(field.endswith(".verdict") for field in invalid_fields):
                        correction += (
                            ". Every verdict must be exactly one of: supported, contradicted, "
                            "evidence_insufficient. Do not use unknown or unsupported."
                        )
                    messages.extend(
                        [
                            {"role": "assistant", "content": invalid_content},
                            {
                                "role": "user",
                                "content": correction,
                            },
                        ]
                    )
                request_options: dict[str, Any] = {
                    "model": model,
                    "response_format": _response_format(response_model),
                    "messages": messages,
                }
                if max_output_tokens is not None:
                    request_options["max_tokens"] = max_output_tokens
                response = client.chat.completions.create(**request_options)
                choice = response.choices[0]
                content = choice.message.content or "{}"
                usage = response.usage
                tokens_input += int(getattr(usage, "prompt_tokens", 0) or 0)
                tokens_output += int(getattr(usage, "completion_tokens", 0) or 0)
                finish_reason = str(getattr(choice, "finish_reason", "") or "").lower()
                if finish_reason in {"length", "max_tokens"}:
                    raise ModelOutputTruncatedError(
                        "model output reached the configured token limit"
                    )
                result = json.loads(content)
                if response_adapter is not None:
                    result = response_adapter(result)
                result = self._validate(result, response_model)
                return result, {
                    "provider_mode": "live",
                    "model_name": model,
                    "tokens_input": int(getattr(usage, "prompt_tokens", 0) or 0),
                    "tokens_output": int(getattr(usage, "completion_tokens", 0) or 0),
                    "attempt": attempt,
                    "duration_ms": round((time.perf_counter() - started_at) * 1000),
                }
            except (json.JSONDecodeError, ValidationError, ModelResponseError) as exc:
                validation_fields = _validation_error_fields(exc)
                validation_failures += 1
                truncated = isinstance(exc, ModelOutputTruncatedError)
                error_type = (
                    ModelOutputTruncatedError if truncated else ModelResponseError
                )
                last_error = error_type(
                    f"model returned invalid structured output: {exc}",
                    metadata={
                        "provider_mode": "live",
                        "model_name": model,
                        "tokens_input": tokens_input,
                        "tokens_output": tokens_output,
                        "attempt": attempt,
                        "attempt_count": validation_failures,
                        "status": "failed",
                        "failure_code": (
                            "model_output_truncated"
                            if truncated
                            else "model_structured_output_invalid"
                        ),
                        "finish_reason": "length" if truncated else None,
                        "validation_fields": validation_fields,
                        "duration_ms": round((time.perf_counter() - started_at) * 1000),
                    },
                )
                logger.warning(
                    "Model structured output validation failed model=%s attempt=%s error_type=%s fields=%s",
                    model,
                    attempt,
                    type(exc).__name__,
                    validation_fields,
                )
                if truncated and not repair_truncated_output:
                    break
                if retry_count >= len(self.RETRY_DELAYS):
                    break
                delay = self.RETRY_DELAYS[retry_count]
                retry_count += 1
                # Structured-output failures get a targeted correction while
                # sharing the same bounded 1/3/5-second retry budget as provider
                # and transport failures.
                # Never echo a token-limit-sized partial response into the repair
                # prompt; it makes the second request larger and more likely to
                # time out.  The schema and correction instruction are sufficient.
                invalid_content = "{}" if truncated else content
                invalid_fields = (
                    ["output_truncated_return_complete_concise_json"]
                    if truncated
                    else validation_fields or ["invalid_json"]
                )
                time.sleep(delay)
                continue
            except Exception as exc:  # provider exceptions vary across compatible APIs
                last_error = exc
                logger.warning(
                    "Model call failed model=%s attempt=%s error_type=%s provider_status=%s provider_code=%s",
                    model,
                    attempt,
                    type(exc).__name__,
                    getattr(exc, "status_code", None),
                    getattr(exc, "code", None),
                )
                retry_kind = _provider_retry_kind(exc)
                retry_delays = (
                    self.RETRY_DELAYS if retry_kind == "provider" else timeout_delays
                )
                if retry_kind is not None and retry_count < len(retry_delays):
                    delay = retry_delays[retry_count]
                    retry_count += 1
                    time.sleep(delay)
                    continue
                break
        if isinstance(last_error, ModelResponseError):
            raise last_error
        raise ModelCallError(
            f"model call failed after bounded retries: {last_error}",
            metadata={
                "provider_mode": "live",
                "model_name": model,
                "tokens_input": tokens_input,
                "tokens_output": tokens_output,
                "attempt_count": attempt,
                "status": "failed",
                "failure_code": "model_call_failed",
                "retryable": (
                    _provider_retry_kind(last_error) is not None
                    if last_error is not None
                    else False
                ),
                "error_type": type(last_error).__name__ if last_error else "unknown",
                "duration_ms": round((time.perf_counter() - started_at) * 1000),
            },
        )

    def complete_text(
        self,
        *,
        model: str | None,
        system_prompt: str,
        payload: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        """Call the configured compatible chat model for bounded tutoring prose."""
        started_at = time.perf_counter()
        if not model or not settings.openai_api_key:
            raise ModelConfigurationError("model channel is not configured")
        last_error: Exception | None = None
        client = self._client()
        for attempt in range(1, len(self.RETRY_DELAYS) + 2):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                )
                content = (response.choices[0].message.content or "").strip()
                if not content:
                    raise ModelResponseError("model returned empty text")
                usage = response.usage
                return content, {
                    "provider_mode": "live", "model_name": model,
                    "tokens_input": int(getattr(usage, "prompt_tokens", 0) or 0),
                    "tokens_output": int(getattr(usage, "completion_tokens", 0) or 0),
                    "attempt": attempt,
                    "duration_ms": round((time.perf_counter() - started_at) * 1000),
                }
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Model text call failed model=%s attempt=%s error_type=%s",
                    model,
                    attempt,
                    type(exc).__name__,
                )
                if attempt <= len(self.RETRY_DELAYS):
                    time.sleep(self.RETRY_DELAYS[attempt - 1])
        raise ModelCallError(f"model text call failed after bounded retries: {last_error}")

    def stream_text(
        self, *, model: str | None, system_prompt: str, payload: dict[str, Any]
    ) -> Iterator[str]:
        """Yield OpenAI-compatible text chunks; callers persist partial output."""
        if not model or not settings.openai_api_key:
            raise ModelConfigurationError("model channel is not configured")
        stream = self._client().chat.completions.create(
            model=model,
            stream=True,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        )
        for event in stream:
            content = event.choices[0].delta.content if event.choices else None
            if content:
                yield content

    def stream_json(
        self,
        *,
        model: str | None,
        system_prompt: str,
        payload: dict[str, Any],
        fixture_factory: Callable[[], dict[str, Any]] | None = None,
    ) -> Iterator[str]:
        """Yield a single OpenAI-compatible JSON object as it is generated.

        The caller is responsible for validating the completed object.  Keeping
        that validation at the Agent boundary lets a learner-facing reply be
        forwarded before the final structured fields are available.
        """
        if not model or not settings.openai_api_key:
            if (
                settings.app_env != "production"
                and settings.allow_fixture_llm
                and fixture_factory is not None
            ):
                yield json.dumps(fixture_factory(), ensure_ascii=False)
                return
            raise ModelConfigurationError("model channel is not configured")

        stream = self._client().chat.completions.create(
            model=model,
            stream=True,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": f"Return a valid JSON object.\n\n{system_prompt}",
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        )
        for event in stream:
            content = event.choices[0].delta.content if event.choices else None
            if content:
                yield content

    @staticmethod
    def _validate(
        result: dict[str, Any], response_model: type[ResponseModel] | None
    ) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise ModelResponseError("JSON response must be an object")
        if response_model is None:
            return result
        return response_model.model_validate(
            OpenAICompatibleGateway._normalize_common_shapes(result)
        ).model_dump()

    @staticmethod
    def _normalize_common_shapes(value: Any) -> Any:
        if isinstance(value, list):
            return [OpenAICompatibleGateway._normalize_common_shapes(item) for item in value]
        if isinstance(value, dict):
            normalized = {
                key: OpenAICompatibleGateway._normalize_common_shapes(item)
                for key, item in value.items()
            }
            if "source_ids" in normalized and isinstance(normalized["source_ids"], str):
                normalized["source_ids"] = [normalized["source_ids"]]
            if "source_ref_ids" in normalized and isinstance(normalized["source_ref_ids"], str):
                normalized["source_ref_ids"] = [normalized["source_ref_ids"]]
            if "options" in normalized and normalized["options"] is None:
                normalized["options"] = []
            # Compatible providers often emit ``difficulty`` as a numeric string
            # (``"3"``) or float (``3.0``) even though the contract types it as
            # a 1-5 integer.  Coerce it instead of burning the whole bounded
            # validation-retry budget on a type-only mismatch.
            if "difficulty" in normalized:
                normalized["difficulty"] = _coerce_difficulty(normalized["difficulty"])
            return normalized
        return value

    def configuration_status(self) -> dict[str, Any]:
        generation_ready = bool(settings.primary_llm_model)
        primary_review_ready = bool(settings.primary_review_model)
        secondary_review_ready = bool(settings.secondary_review_model)
        review_models_distinct = bool(
            primary_review_ready
            and secondary_review_ready
            and settings.primary_review_model != settings.secondary_review_model
        )
        gateway_ready = bool(settings.openai_api_key)
        ready_for_live_demo = bool(
            gateway_ready
            and generation_ready
            and primary_review_ready
            and secondary_review_ready
            and review_models_distinct
            and not settings.allow_fixture_llm
        )
        return {
            "status": "ok" if ready_for_live_demo else "degraded",
            "model_gateway": {
                "configured": gateway_ready,
                "base_url_configured": bool(settings.openai_api_base),
            },
            "generation_model": {
                "configured": generation_ready,
                "model_name": settings.primary_llm_model,
            },
            "primary_review_model": {
                "configured": primary_review_ready,
                "model_name": settings.primary_review_model,
            },
            "secondary_review_model": {
                "configured": secondary_review_ready,
                "model_name": settings.secondary_review_model,
            },
            "review_models_distinct": review_models_distinct,
            "fixture_enabled": settings.allow_fixture_llm,
            "evaluation_overrides_enabled": settings.enable_evaluation_overrides,
            "ready_for_live_demo": ready_for_live_demo,
        }


def _coerce_difficulty(value: Any) -> Any:
    """Clamp a provider-returned difficulty to the contract's 1-5 integer.

    Accepts an int, a float with an integer value, or a numeric string. Any
    other value is returned unchanged so the schema validation can still report
    a precise error rather than silently publishing a wrong difficulty.
    """

    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return max(1, min(5, value))
    if isinstance(value, float):
        if not value.is_integer():
            return value
        return max(1, min(5, int(value)))
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return max(1, min(5, int(float(stripped))))
        except ValueError:
            return value
    return value

def _validation_error_fields(exc: Exception) -> list[str]:
    """Expose only failing field paths in ordinary logs, never provider content."""
    if not isinstance(exc, ValidationError):
        return []
    return [
        ".".join(str(part) for part in issue.get("loc", ()))
        for issue in exc.errors(include_input=False)
    ][:20]


def _provider_retry_kind(exc: Exception) -> str | None:
    """Classify compatible-provider failures without exposing response bodies."""

    status = getattr(exc, "status_code", None)
    try:
        status_code = int(status) if status is not None else None
    except (TypeError, ValueError):
        status_code = None
    if status_code == 429 or (status_code is not None and status_code >= 500):
        return "provider"
    if status_code is not None and 400 <= status_code < 500:
        return None
    name = type(exc).__name__.lower()
    code = str(getattr(exc, "code", "") or "").lower()
    if any(
        item in f"{name} {code}"
        for item in ("timeout", "connection", "connect", "network")
    ):
        return "transport"
    # Compatible providers use different transport exception classes. Unknown
    # exceptions remain retryable only within the caller's bounded policy.
    return "transport"


gateway = OpenAICompatibleGateway()


def _response_format(
    response_model: type[BaseModel] | None,
) -> dict[str, Any]:
    if settings.llm_json_schema_mode == "json_schema" and response_model is not None:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": response_model.__name__,
                "strict": True,
                "schema": response_model.model_json_schema(),
            },
        }
    return {"type": "json_object"}


def _structured_system_prompt(
    system_prompt: str,
    *,
    response_model: type[BaseModel] | None,
) -> str:
    if response_model is None or settings.llm_json_schema_mode == "json_schema":
        return f"Return a valid JSON object.\n\n{system_prompt}"
    schema = json.dumps(
        response_model.model_json_schema(), ensure_ascii=False, separators=(",", ":")
    )
    return (
        "Return exactly one JSON object matching this JSON Schema. Do not use Markdown "
        f"or add fields outside the schema.\nJSON Schema: {schema}\n\n{system_prompt}"
    )
