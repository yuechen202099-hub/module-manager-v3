import pytest

from app.services.task_status import TaskState, TaskStatusError, claim_task, release_task


def test_claim_published_task() -> None:
    next_state = claim_task(TaskState(status="published"), reviewer_id=7)

    assert next_state.status == "claimed"
    assert next_state.claimed_by_id == 7
    assert next_state.claimed_at is not None


def test_release_claimed_task_by_current_claimant() -> None:
    next_state = release_task(TaskState(status="claimed", claimed_by_id=7), reviewer_id=7)

    assert next_state.status == "released"
    assert next_state.claimed_by_id is None
    assert next_state.claimed_at is None


def test_released_task_can_be_claimed_again() -> None:
    next_state = claim_task(TaskState(status="released"), reviewer_id=7)

    assert next_state.status == "claimed"
    assert next_state.claimed_by_id == 7
    assert next_state.claimed_at is not None


def test_cannot_claim_draft_task() -> None:
    with pytest.raises(TaskStatusError):
        claim_task(TaskState(status="draft"), reviewer_id=7)


@pytest.mark.parametrize("status", ["claimed", "completed", "cancelled"])
def test_cannot_claim_non_queue_status(status: str) -> None:
    with pytest.raises(TaskStatusError):
        claim_task(TaskState(status=status), reviewer_id=7)


def test_only_current_claimant_can_release() -> None:
    with pytest.raises(TaskStatusError):
        release_task(TaskState(status="claimed", claimed_by_id=8), reviewer_id=7)
