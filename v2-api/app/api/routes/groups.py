from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError

from app.core.responses import ok
from app.api.routes.auth import require_admin, require_production_reviewer_or_admin
from app.schemas.data_center import DataCenterQuery
from app.schemas.review import ExceptionCreate, GroupReviewUpdate
from app.services import local_simulation
from app.services.photo_storage import resolve_group_collection_for_response
from app.services.state_repository import StateBackendNotReady, get_state_repository
from app.services.task_snapshot_cache import invalidate_task_snapshot_for_team

router = APIRouter(prefix="/groups")


class GroupMetadataUpdateRequest(BaseModel):
    updates: dict[str, Any] = Field(default_factory=dict)


class GroupResetRequest(BaseModel):
    reason: str = ""


class GroupBulkArchiveRequest(BaseModel):
    group_ids: list[str] = Field(default_factory=list)
    reason: str = ""


def state_repository():
    try:
        return get_state_repository()
    except StateBackendNotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/search")
def search_groups(
    request: Request,
    admin_payload: dict = Depends(require_admin),
    query: str = "",
    terminal: str = "",
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    if not query.strip() and not terminal.strip():
        return ok(request, {"total": 0, "terminals": [], "items": []})
    team_id = str(admin_payload.get("team_id") or "").strip()
    token = local_simulation.set_current_team(team_id)
    try:
        result = state_repository().search_group_targets(query=query, terminal=terminal, limit=limit, offset=offset)
    finally:
        local_simulation.reset_current_team(token)
    return ok(request, resolve_group_collection_for_response(result))


@router.post("/bulk-archive")
def bulk_archive_groups(
    payload: GroupBulkArchiveRequest,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    token = _with_admin_team(admin_payload)
    try:
        result = state_repository().bulk_archive_groups(
            payload.group_ids,
            actor=_admin_actor(admin_payload),
            reason=payload.reason,
        )
        invalidate_task_snapshot_for_team(_admin_team_id(admin_payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        local_simulation.reset_current_team(token)
    return ok(request, resolve_group_collection_for_response(result))


def _admin_actor(admin_payload: dict) -> str:
    return str(admin_payload.get("username") or admin_payload.get("sub") or "admin").strip() or "admin"


def _admin_team_id(admin_payload: dict) -> str:
    return str(admin_payload.get("team_id") or "").strip()


def _with_admin_team(admin_payload: dict):
    return local_simulation.set_current_team(_admin_team_id(admin_payload))


def data_center_query(
    data_type: Literal["all", "group", "unmatched"] = "all",
    construction_status: Literal["all", "unconstructed", "in_progress", "completed"] = "all",
    archive_status: Literal["all", "unarchived", "pending", "archived"] = "all",
    barcode_status: Literal["all", "passed", "manual", "mismatched", "unreadable", "ineligible"] = "all",
    classification_status: Literal["all", "complete", "incomplete"] = "all",
    exception_status: str = "",
    installer: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    terminal: str = "",
    query: str = "",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20),
    sort: Literal["updated_desc", "updated_asc", "terminal_asc"] = "updated_desc",
) -> DataCenterQuery:
    try:
        return DataCenterQuery(
            data_type=data_type,
            construction_status=construction_status,
            archive_status=archive_status,
            barcode_status=barcode_status,
            classification_status=classification_status,
            exception_status=exception_status,
            installer=installer,
            date_from=date_from,
            date_to=date_to,
            terminal=terminal,
            query=query,
            page=page,
            page_size=page_size,
            sort=sort,
        )
    except ValidationError as exc:
        detail = [
            {
                "loc": ["query", *error.get("loc", ())],
                "msg": str(error.get("msg") or ""),
                "type": str(error.get("type") or "value_error"),
            }
            for error in exc.errors()
        ]
        raise HTTPException(status_code=422, detail=detail) from exc


@router.get("/data-center")
def list_data_center(
    request: Request,
    query: DataCenterQuery = Depends(data_center_query),
    admin_payload: dict = Depends(require_admin),
):
    token = _with_admin_team(admin_payload)
    try:
        result = state_repository().list_data_center_rows(query)
    finally:
        local_simulation.reset_current_team(token)
    return ok(request, result)


@router.get("/data-center/{kind}/{item_id}")
def data_center_detail(
    kind: Literal["group", "unmatched"],
    item_id: str,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    token = _with_admin_team(admin_payload)
    try:
        result = state_repository().get_data_center_detail(kind=kind, item_id=item_id)
    finally:
        local_simulation.reset_current_team(token)
    if result is None:
        raise HTTPException(status_code=404, detail="Data center item not found")
    return ok(request, result)


@router.patch("/{group_id}/metadata")
def update_group_metadata(
    group_id: str,
    payload: GroupMetadataUpdateRequest,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    token = _with_admin_team(admin_payload)
    try:
        result = state_repository().update_group_metadata(
            group_id,
            actor=_admin_actor(admin_payload),
            updates=payload.updates,
            audit_action="admin_group_metadata_update",
        )
        invalidate_task_snapshot_for_team(_admin_team_id(admin_payload))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        local_simulation.reset_current_team(token)
    return ok(request, result)


@router.patch("/{group_id}/reset-unconstructed")
def reset_group_unconstructed(
    group_id: str,
    payload: GroupResetRequest,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    token = _with_admin_team(admin_payload)
    try:
        result = state_repository().reset_group_to_unconstructed(
            group_id,
            actor=_admin_actor(admin_payload),
            reason=payload.reason,
            force=True,
        )
        invalidate_task_snapshot_for_team(_admin_team_id(admin_payload))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        local_simulation.reset_current_team(token)
    return ok(request, result)


@router.patch("/{group_id}/reset-unreviewed")
def reset_group_unreviewed(
    group_id: str,
    payload: GroupResetRequest,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    token = _with_admin_team(admin_payload)
    try:
        result = state_repository().reset_group_to_unreviewed(
            group_id,
            actor=_admin_actor(admin_payload),
            reason=payload.reason,
            force=True,
        )
        invalidate_task_snapshot_for_team(_admin_team_id(admin_payload))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        local_simulation.reset_current_team(token)
    return ok(request, result)


@router.get("/{group_id}")
def get_group(group_id: int, request: Request):
    return ok(request, {"id": group_id, "status": "placeholder", "photos": []})


@router.patch("/{group_id}/review")
def update_group_review(
    group_id: int,
    payload: GroupReviewUpdate,
    request: Request,
    _reviewer_payload: dict = Depends(require_production_reviewer_or_admin),
):
    return ok(request, {"group_id": group_id, "status": payload.status, "comment": payload.comment})


@router.post("/{group_id}/exceptions")
def create_exception(
    group_id: int,
    payload: ExceptionCreate,
    request: Request,
    _reviewer_payload: dict = Depends(require_production_reviewer_or_admin),
):
    return ok(request, {"group_id": group_id, "kind": payload.kind, "description": payload.description, "status": "open"})


@router.post("/{group_id}/photos/sign-upload")
def sign_photo_upload(group_id: int, request: Request):
    return ok(request, {"group_id": group_id, "upload_url": "", "object_key": ""})


@router.post("/{group_id}/photos/complete-upload")
def complete_photo_upload(group_id: int, request: Request):
    return ok(request, {"group_id": group_id, "status": "completed"})

