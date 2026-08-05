from app.models import GenerationTask


TERMINAL_STATUSES = {"completed", "failed", "rejected", "no_change"}
ALLOWED_TRANSITIONS = {
    "pending": {"running", "failed"},
    "running": {"completed", "failed", "waiting_human", "revision_required", "no_change"},
    "waiting_human": {"running", "failed", "rejected"},
    "revision_required": {"running", "failed", "waiting_human"},
}


def transition_task(
    task: GenerationTask,
    *,
    status: str,
    decision: str | None = None,
    progress: int | None = None,
) -> None:
    if task.status in TERMINAL_STATUSES and status != task.status:
        raise ValueError(f"terminal_task_status_cannot_transition:{task.status}->{status}")
    if status != task.status and status not in ALLOWED_TRANSITIONS.get(task.status, set()):
        raise ValueError(f"invalid_task_status_transition:{task.status}->{status}")
    task.status = status
    if decision is not None:
        task.decision = decision
    if progress is not None:
        task.progress = progress
