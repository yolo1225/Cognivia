"""Deterministic helpers for keeping model payloads within MVP budgets."""

from __future__ import annotations

import json
import re
from typing import Any


def estimate_tokens(value: Any) -> int:
    """Estimate CJK at 1 token/char, other text at 1/4, plus 15 percent."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    cjk_count = len(re.findall(r"[\u3400-\u9fff]", text))
    other_count = len(text) - cjk_count
    return int((cjk_count + ((other_count + 3) // 4)) * 1.15) + 1


def bounded_text(value: str, max_chars: int = 4000) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip() + "…"
