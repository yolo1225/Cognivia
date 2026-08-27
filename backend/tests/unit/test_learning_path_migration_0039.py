import importlib.util
from pathlib import Path
from types import ModuleType


def _migration() -> ModuleType:
    path = (
        Path(__file__).parents[2]
        / "alembic"
        / "versions"
        / "20260826_0039_restore_learning_path_history_and_feedback_tasks.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0039", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migration_0040() -> ModuleType:
    path = (
        Path(__file__).parents[2]
        / "alembic"
        / "versions"
        / "20260826_0040_retire_obsolete_feedback_packages.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0040", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repair_restores_completed_history_and_advances_current_node() -> None:
    completed = {
        "node_states": {
            "unit:done": {
                "path_node_id": "unit:done",
                "knowledge_ids": ["k1", "k2"],
                "title": "已完成单元",
                "status": "completed",
                "completed_at": "2026-08-26T01:00:00+00:00",
                "completion_evidence_ids": ["answer_record:1"],
                "path_order": 1,
            }
        }
    }
    active = {
        "stages": [{"name": "主线", "knowledge_ids": ["k1", "k2", "k3"]}],
        "node_states": {
            "unit:done": {
                "path_node_id": "unit:done",
                "knowledge_ids": ["k1", "k2"],
                "status": "current",
                "path_order": 1,
            },
            "unit:next": {
                "path_node_id": "unit:next",
                "knowledge_ids": ["k3"],
                "status": "locked",
                "path_order": 2,
            },
        },
    }

    repaired, changed = _migration()._repair_path(active, [completed])

    assert changed is True
    assert repaired["current_node_id"] == "unit:next"
    assert repaired["node_states"]["unit:done"]["status"] == "completed"
    assert repaired["node_states"]["unit:next"]["status"] == "current"
    repeated, repeated_changed = _migration()._repair_path(repaired, [completed])
    assert repeated_changed is False
    assert repeated == repaired


def test_retired_feedback_package_only_matches_a_completed_target_node() -> None:
    migration = _migration_0040()
    payload = {
        "node_states": {
            "unit:done": {"status": "completed"},
            "unit:current": {"status": "current"},
        }
    }

    assert migration._targets_completed_node(payload, "unit:done") is True
    assert migration._targets_completed_node(payload, "unit:current") is False
    assert migration._targets_completed_node(payload, "unit:missing") is False
