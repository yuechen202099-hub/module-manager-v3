from fastapi import APIRouter, Request

from app.core.responses import ok
from app.services.task_status import TaskState, claim_task, release_task

router = APIRouter()


@router.get("/projects/{project_id}/tasks")
def list_project_tasks(project_id: int, request: Request):
    return ok(request, {"project_id": project_id, "items": []})


@router.post("/projects/{project_id}/tasks/publish")
def publish_tasks(project_id: int, request: Request):
    return ok(request, {"project_id": project_id, "status": "published", "created_tasks": 0})


@router.post("/tasks/{task_id}/claim")
def claim(task_id: int, request: Request):
    next_state = claim_task(TaskState(status="published"), reviewer_id=1)
    return ok(
        request,
        {
            "task_id": task_id,
            "status": next_state.status,
            "claimed_by_id": next_state.claimed_by_id,
            "claimed_at": next_state.claimed_at.isoformat() if next_state.claimed_at else None,
        },
    )


@router.post("/tasks/{task_id}/release")
def release(task_id: int, request: Request):
    next_state = release_task(TaskState(status="claimed", claimed_by_id=1), reviewer_id=1)
    return ok(request, {"task_id": task_id, "status": next_state.status})


@router.get("/tasks/{task_id}")
def get_task(task_id: int, request: Request):
    return ok(request, {"id": task_id, "status": "placeholder"})


@router.get("/tasks/{task_id}/groups")
def list_task_groups(task_id: int, request: Request):
    return ok(request, {"task_id": task_id, "items": []})

