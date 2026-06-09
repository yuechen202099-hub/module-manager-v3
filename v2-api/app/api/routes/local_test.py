from pydantic import BaseModel

from fastapi import APIRouter, HTTPException, Query, Request

from app.core.responses import ok
from app.services.local_simulation import (
    bootstrap_local_simulation,
    claim_task,
    classify_photo,
    get_group,
    get_task_progress,
    get_state,
    list_groups,
    list_task_groups,
    list_tasks,
    release_task,
    review_group,
    save_exception_note,
)

router = APIRouter(prefix="/local-test")


class ClaimRequest(BaseModel):
    reviewer: str = "local-reviewer"


class ReviewRequest(BaseModel):
    status: str
    reviewer: str = "local-reviewer"
    note: str = ""
    exception_note: str = ""


class ExceptionNoteRequest(BaseModel):
    reviewer: str = "local-reviewer"
    note: str


class PhotoClassifyRequest(BaseModel):
    category: str
    reviewer: str = "local-reviewer"


@router.post("/bootstrap")
def bootstrap(request: Request):
    state = bootstrap_local_simulation()
    return ok(request, {"summary": state["summary"], "paths": state["paths"]})


@router.get("/summary")
def summary(request: Request):
    state = get_state()
    return ok(request, {"summary": state["summary"], "paths": state["paths"]})


@router.get("/groups")
def groups(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    status: str | None = None,
):
    return ok(request, list_groups(limit=limit, offset=offset, status=status))


@router.get("/tasks")
def tasks(request: Request):
    return ok(request, {"items": list_tasks()})


@router.get("/tasks/{task_id}/groups")
def task_groups(
    task_id: int,
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    status: str | None = None,
):
    try:
        result = list_task_groups(task_id, limit=limit, offset=offset, status=status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    return ok(request, result)


@router.get("/tasks/{task_id}/progress")
def task_progress(task_id: int, request: Request):
    try:
        progress = get_task_progress(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    return ok(request, progress)


@router.post("/tasks/{task_id}/claim")
def claim(task_id: int, payload: ClaimRequest, request: Request):
    try:
        task = claim_task(task_id, payload.reviewer)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, task)


@router.post("/tasks/{task_id}/release")
def release(task_id: int, payload: ClaimRequest, request: Request):
    try:
        task = release_task(task_id, payload.reviewer)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, task)


@router.get("/groups/{group_id}")
def group_detail(group_id: str, request: Request):
    group = get_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return ok(request, group)


@router.patch("/groups/{group_id}/review")
def save_review(group_id: str, payload: ReviewRequest, request: Request):
    try:
        group = review_group(
            group_id,
            payload.status,
            payload.reviewer,
            payload.note,
            payload.exception_note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, group)


@router.post("/groups/{group_id}/exception")
def mark_exception(group_id: str, payload: ExceptionNoteRequest, request: Request):
    try:
        group = save_exception_note(group_id, payload.reviewer, payload.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, group)


@router.patch("/groups/{group_id}/photos/{photo_id}/category")
def save_photo_category(group_id: str, photo_id: str, payload: PhotoClassifyRequest, request: Request):
    try:
        photo = classify_photo(group_id, photo_id, payload.category, payload.reviewer)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Photo or group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, photo)
