import importlib.util
from pathlib import Path
from types import ModuleType


def _migration() -> ModuleType:
    path = (
        Path(__file__).parents[2]
        / "alembic"
        / "versions"
        / "20260823_0030_stabilize_active_learning_paths.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0030", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_moves_completed_history_before_current_node() -> None:
    payload = {
        "stages": [
            {
                "name": "攻克薄弱知识点",
                "knowledge_ids": ["evaluation", "review", "prompt", "future"],
            }
        ],
        "current_node_id": "knowledge:review",
        "node_states": {
            "knowledge:evaluation": {
                "path_node_id": "knowledge:evaluation",
                "knowledge_id": "evaluation",
                "path_order": 1,
                "status": "locked",
                "completion_evidence_ids": [],
            },
            "knowledge:review": {
                "path_node_id": "knowledge:review",
                "knowledge_id": "review",
                "path_order": 2,
                "status": "current",
                "completion_evidence_ids": [],
            },
            "knowledge:prompt": {
                "path_node_id": "knowledge:prompt",
                "knowledge_id": "prompt",
                "path_order": 3,
                "status": "completed",
                "completed_at": "2026-08-23T00:00:00+00:00",
                "completion_evidence_ids": ["answer_record:92"],
            },
            "knowledge:future": {
                "path_node_id": "knowledge:future",
                "knowledge_id": "future",
                "path_order": 4,
                "status": "locked",
                "completion_evidence_ids": [],
            },
        },
        "retired_node_states": {},
    }

    stabilized, path_status, changed = _migration()._stabilize(payload)
    ordered = sorted(
        stabilized["node_states"].values(), key=lambda state: state["path_order"]
    )

    assert changed is True
    assert path_status == "active"
    assert [state["knowledge_id"] for state in ordered] == [
        "prompt",
        "review",
        "evaluation",
        "future",
    ]
    assert [state["status"] for state in ordered] == [
        "completed",
        "current",
        "locked",
        "locked",
    ]
    assert ordered[0]["completion_evidence_ids"] == ["answer_record:92"]


def test_migration_marks_all_completed_path_completed() -> None:
    payload = {
        "stages": [{"name": "path", "knowledge_ids": ["done"]}],
        "current_node_id": None,
        "node_states": {
            "knowledge:done": {
                "path_node_id": "knowledge:done",
                "knowledge_id": "done",
                "path_order": 1,
                "status": "completed",
                "completion_evidence_ids": ["answer_record:1"],
            }
        },
    }

    _stabilized, path_status, _changed = _migration()._stabilize(payload)

    assert path_status == "completed"
