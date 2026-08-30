"""Task-scoped, non-contract telemetry for model invocations."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from typing import Any


class ModelCallCollector:
    """Thread-safe collector used only by the composition/worker boundary."""

    def __init__(self) -> None:
        self._calls: list[dict[str, Any]] = []
        self._lock = Lock()

    def record(self, metadata: dict[str, Any], **context: Any) -> None:
        call: dict[str, Any] = {
            "provider_mode": str(metadata.get("provider_mode") or "unknown"),
            "model_name": str(metadata.get("model_name") or "unknown")[:128],
            "tokens_input": max(0, int(metadata.get("tokens_input") or 0)),
            "tokens_output": max(0, int(metadata.get("tokens_output") or 0)),
            "duration_ms": max(0, int(metadata.get("duration_ms") or 0)),
            **{key: value for key, value in context.items() if value is not None},
        }
        if metadata.get("status"):
            call["status"] = str(metadata["status"])
            call["attempt_count"] = max(
                1, int(metadata.get("attempt_count") or metadata.get("attempt") or 1)
            )
        if metadata.get("validation_fields"):
            call["validation_fields"] = [
                str(value)[:160] for value in metadata["validation_fields"]
            ][:20]
        with self._lock:
            self._calls.append(call)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._calls]


_collector: ContextVar[ModelCallCollector | None] = ContextVar(
    "v3_model_call_collector", default=None
)


@contextmanager
def collect_model_calls() -> Iterator[ModelCallCollector]:
    collector = ModelCallCollector()
    token = _collector.set(collector)
    try:
        yield collector
    finally:
        _collector.reset(token)


def record_model_call(metadata: dict[str, Any], **context: Any) -> None:
    collector = _collector.get()
    if collector is not None:
        collector.record(metadata, **context)
