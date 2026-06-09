from pydantic import BaseModel

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile

from app.core.responses import ok
from app.services.ezcodes_scheduler import sync_manager
from app.services.local_simulation import (
    bootstrap_local_simulation,
    associate_unmatched_record,
    claim_task,
    classify_photo,
    clear_scan_data,
    delete_unmatched_record,
    get_group,
    get_task_progress,
    get_state,
    import_scan_template_xlsx,
    import_url_scan_rows,
    list_audit_events,
    list_catalog_rows,
    list_groups,
    list_task_groups,
    list_tasks,
    list_unmatched_records,
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


class UrlImportRequest(BaseModel):
    rows: list[dict]


class UnmatchedAssociateRequest(BaseModel):
    actor: str = "local-reviewer"
    target_group_id: str = ""
    target_meter_no: str = ""
    updates: dict = {}


class UnmatchedDeleteRequest(BaseModel):
    actor: str = "local-reviewer"
    reason: str = ""


@router.post("/bootstrap")
def bootstrap(request: Request):
    state = bootstrap_local_simulation()
    return ok(request, {"summary": state["summary"], "paths": state["paths"]})


@router.post("/scan/clear")
def clear_scan(request: Request):
    state = clear_scan_data()
    return ok(request, {"summary": state["summary"], "paths": state["paths"]})


@router.post("/scan/import-url-rows")
def import_url_rows(payload: UrlImportRequest, request: Request):
    result = import_url_scan_rows(payload.rows)
    return ok(request, result)


@router.post("/scan/import-template-xlsx")
async def import_template_xlsx(request: Request, file: UploadFile = File(...)):
    content = await file.read()
    result = import_scan_template_xlsx(content)
    result["filename"] = file.filename
    return ok(request, result)


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


@router.get("/catalog/{catalog_type}")
def catalog_rows(
    catalog_type: str,
    request: Request,
    query: str = "",
    terminal: str = "",
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    try:
        result = list_catalog_rows(catalog_type, query=query, terminal=terminal, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, result)


@router.get("/unmatched")
def unmatched_records(
    request: Request,
    query: str = "",
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    return ok(request, list_unmatched_records(query=query, limit=limit, offset=offset))


@router.post("/unmatched/{unmatched_id}/associate")
def associate_unmatched(unmatched_id: str, payload: UnmatchedAssociateRequest, request: Request):
    try:
        result = associate_unmatched_record(
            unmatched_id,
            actor=payload.actor,
            target_group_id=payload.target_group_id,
            target_meter_no=payload.target_meter_no,
            updates=payload.updates,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unmatched record not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, result)


@router.post("/unmatched/{unmatched_id}/delete")
def delete_unmatched(unmatched_id: str, payload: UnmatchedDeleteRequest, request: Request):
    try:
        record = delete_unmatched_record(unmatched_id, actor=payload.actor, reason=payload.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unmatched record not found") from exc
    return ok(request, record)


@router.get("/audit-log")
def audit_log(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    return ok(request, list_audit_events(limit=limit, offset=offset))


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
    scan_only: bool = Query(default=True),
):
    try:
        result = list_task_groups(task_id, limit=limit, offset=offset, status=status, scan_only=scan_only)
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
    try:
        loaded = sync_manager.load_group_photo_urls(group_id)
        group = loaded["group"]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc
    except ValueError as exc:
        if "not configured" not in str(exc):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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
