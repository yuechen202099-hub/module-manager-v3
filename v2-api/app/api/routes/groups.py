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
    source_page: str = ""


class GroupBulkArchiveRequest(BaseModel):
    group_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class DataCenterGroupPatchRequest(BaseModel):
    patch: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    source_page: str = "data_center"


class DataCenterPhotoClassifyRequest(BaseModel):
    category: str = ""
    reason: str = ""
    source_page: str = "data_center"


class DataCenterPhotoBarcodeRescanRequest(BaseModel):
    category: str = ""
    reason: str = ""
    source_page: str = "data_center"


class DataCenterPhotoRegionScanRequest(BaseModel):
    barcode_type: Literal["meter", "collector", "module"]
    region: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    source_page: str = "data_center"


class DataCenterManualConfirmRequest(BaseModel):
    meter_no: str = ""
    module_asset_no: str = ""
    collector: str = ""
    reason: str = ""
    photo_ids: list[str] = Field(default_factory=list)
    source_page: str = "data_center"


class DataCenterReturnExceptionRequest(BaseModel):
    category: str = "other"
    note: str = ""
    reason: str = ""
    source_page: str = "data_center"


class DataCenterUnmatchedFinalizeRequest(BaseModel):
    terminal: str = ""
    meter_no: str = ""
    candidate_key: str = ""
    expected_version: int = 1
    source_page: str = "data_center"


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


@router.patch("/data-center/groups/{group_id}")
def update_data_center_group(
    group_id: str,
    payload: DataCenterGroupPatchRequest,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    token = _with_admin_team(admin_payload)
    try:
        result = state_repository().update_data_center_group(
            group_id,
            patch=payload.patch,
            actor=_admin_actor(admin_payload),
            reason=payload.reason,
            source_page=payload.source_page,
        )
        invalidate_task_snapshot_for_team(_admin_team_id(admin_payload))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        local_simulation.reset_current_team(token)
    return ok(request, resolve_group_collection_for_response(result))


@router.post("/data-center/groups/{group_id}/photos/{photo_id}/classify")
def classify_data_center_group_photo(
    group_id: str,
    photo_id: str,
    payload: DataCenterPhotoClassifyRequest,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    token = _with_admin_team(admin_payload)
    try:
        result = state_repository().classify_data_center_group_photo(
            group_id,
            photo_id,
            payload.category,
            actor=_admin_actor(admin_payload),
            reason=payload.reason,
            source_page=payload.source_page,
        )
        invalidate_task_snapshot_for_team(_admin_team_id(admin_payload))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Photo or group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        local_simulation.reset_current_team(token)
    return ok(request, resolve_group_collection_for_response(result))


@router.post("/data-center/groups/{group_id}/photos/{photo_id}/barcode-rescan")
def rescan_data_center_group_photo_barcode(
    group_id: str,
    photo_id: str,
    payload: DataCenterPhotoBarcodeRescanRequest,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    token = _with_admin_team(admin_payload)
    try:
        result = state_repository().rescan_data_center_group_photo_barcode(
            group_id,
            photo_id,
            actor=_admin_actor(admin_payload),
            category=payload.category,
            reason=payload.reason,
            source_page=payload.source_page,
        )
        invalidate_task_snapshot_for_team(_admin_team_id(admin_payload))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Photo or group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        local_simulation.reset_current_team(token)
    return ok(request, resolve_group_collection_for_response(result))


@router.post("/data-center/groups/{group_id}/photos/{photo_id}/region-scan")
def scan_data_center_group_photo_region(
    group_id: str,
    photo_id: str,
    payload: DataCenterPhotoRegionScanRequest,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    token = _with_admin_team(admin_payload)
    try:
        result = state_repository().scan_data_center_group_photo_region(
            group_id,
            photo_id,
            barcode_type=payload.barcode_type,
            region=payload.region,
            actor=_admin_actor(admin_payload),
            reason=payload.reason,
            source_page=payload.source_page,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Photo or group not found") from exc
    except ValueError as exc:
        detail = "Image recognition unavailable" if "unavailable" in str(exc).lower() else str(exc)
        raise HTTPException(status_code=422, detail=detail) from exc
    finally:
        local_simulation.reset_current_team(token)
    return ok(request, result)


@router.post("/data-center/groups/{group_id}/barcode-manual-confirm")
def manual_confirm_data_center_group_barcode(
    group_id: str,
    payload: DataCenterManualConfirmRequest,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    token = _with_admin_team(admin_payload)
    try:
        result = state_repository().manual_confirm_group_barcode(
            group_id,
            actor=_admin_actor(admin_payload),
            reason=payload.reason,
            source_page=payload.source_page,
            meter_no=payload.meter_no,
            module_asset_no=payload.module_asset_no,
            collector=payload.collector,
            photo_ids=payload.photo_ids,
        )
        invalidate_task_snapshot_for_team(_admin_team_id(admin_payload))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        local_simulation.reset_current_team(token)
    return ok(request, resolve_group_collection_for_response(result))


@router.patch("/data-center/groups/{group_id}/return-exception")
def return_data_center_group_exception_order(
    group_id: str,
    payload: DataCenterReturnExceptionRequest,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    token = _with_admin_team(admin_payload)
    try:
        result = state_repository().return_data_center_group_to_exception_order(
            group_id,
            actor=_admin_actor(admin_payload),
            category=payload.category,
            note=payload.note,
            reason=payload.reason,
            source_page=payload.source_page,
        )
        invalidate_task_snapshot_for_team(_admin_team_id(admin_payload))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        local_simulation.reset_current_team(token)
    return ok(request, resolve_group_collection_for_response(result))


@router.post("/data-center/unmatched/{unmatched_id}/finalize-to-group")
def finalize_data_center_unmatched_to_group(
    unmatched_id: str,
    payload: DataCenterUnmatchedFinalizeRequest,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    token = _with_admin_team(admin_payload)
    try:
        result = state_repository().finalize_unmatched_to_group(
            unmatched_id,
            actor=_admin_actor(admin_payload),
            terminal=payload.terminal,
            meter_no=payload.meter_no,
            candidate_key=payload.candidate_key,
            expected_version=payload.expected_version,
            source_page=payload.source_page,
        )
        invalidate_task_snapshot_for_team(_admin_team_id(admin_payload))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unmatched record not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        local_simulation.reset_current_team(token)
    return ok(request, resolve_group_collection_for_response(result))


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
            source_page=payload.source_page,
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
            source_page=payload.source_page,
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

