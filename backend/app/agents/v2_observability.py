"""Task-scoped, non-contract telemetry for V2 model invocations."""

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
        call = {
            "provider_mode": str(metadata.get("provider_mode") or "unknown"),
            "model_name": str(metadata.get("model_name") or "unknown")[:128],
            "tokens_input": max(0, int(metadata.get("tokens_input") or 0)),
            "tokens_output": max(0, int(metadata.get("tokens_output") or 0)),
            "duration_ms": max(0, int(metadata.get("duration_ms") or 0)),
            **{key: value for key, value in context.items() if value is not None},
        }
        with self._lock:
            self._calls.append(call)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._calls]


_collector: ContextVar[ModelCallCollector | None] = ContextVar(
    "v2_model_call_collector", default=None
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
