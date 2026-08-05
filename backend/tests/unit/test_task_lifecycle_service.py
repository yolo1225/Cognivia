import pytest

from app.models import GenerationTask
from app.services.task_lifecycle_service import transition_task


def test_task_lifecycle_accepts_review_resume_and_rejects_terminal_reentry() -> None:
    task = GenerationTask(
        public_id="task_lifecycle",
        learner_id=1,
        profile_id=1,
        domain_code="ai_app_dev",
        status="pending",
        decision="pending",
    )

    transition_task(task, status="running")
    transition_task(task, status="waiting_human", decision="manual_review_required")
    transition_task(task, status="running", decision="pending")
    transition_task(task, status="completed", decision="completed", progress=100)

    assert task.status == "completed"
    assert task.progress == 100
    with pytest.raises(ValueError, match="terminal_task_status_cannot_transition"):
        transition_task(task, status="running")
