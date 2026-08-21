from pathlib import Path

import pytest

from app.agents import prompt_registry


def test_production_prompt_registry_is_complete_and_stable() -> None:
    prompt_registry.validate_production_prompts()
    assert len(prompt_registry.get_prompt("generation")) > 100
    assert len(prompt_registry.node_prompt_hash("review_resource")) == 64
    assert prompt_registry.node_prompt_hash("review_resource") == prompt_registry.node_prompt_hash(
        "review_resource"
    )


def test_prompt_registry_rejects_missing_and_empty_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(prompt_registry, "PROMPT_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="production_prompt_missing"):
        prompt_registry.get_prompt("tutoring")
    (tmp_path / prompt_registry.PROMPT_FILES["tutoring"]).write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="production_prompt_empty"):
        prompt_registry.get_prompt("tutoring")
