from dataclasses import dataclass
from datetime import datetime, timezone


class TaskStatusError(ValueError):
    pass


@dataclass(frozen=True)
class TaskState:
    status: str
    claimed_by_id: int | None = None
    claimed_at: datetime | None = None


def claim_task(state: TaskState, reviewer_id: int) -> TaskState:
    if state.status not in {"published", "released"}:
        raise TaskStatusError(f"Task with status {state.status!r} cannot be claimed.")
    return TaskState(status="claimed", claimed_by_id=reviewer_id, claimed_at=datetime.now(timezone.utc))


def release_task(state: TaskState, reviewer_id: int) -> TaskState:
    if state.status != "claimed" or state.claimed_by_id != reviewer_id:
        raise TaskStatusError("Only the current claimant can release a claimed task.")
    return TaskState(status="released")

