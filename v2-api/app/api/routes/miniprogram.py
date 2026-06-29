from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.api.routes.auth import (
    bearer_payload,
    demo_login_user,
    environment_admin_login,
    request_client_ip,
    request_device,
)
from app.api.routes.local_test import (
    current_request_team,
    display_name_for_actor,
    is_all_zero_construction_code,
    response_payload,
    state_repository,
    use_team_context,
    validate_construction_upload_group_before_file_save,
)
from app.core.responses import error_response, ok
from app.core.security import create_access_token
from app.services.account_store import authenticate_user, get_user, normalize_team_id, public_user
from app.services.photo_storage import normalize_suffix, save_image_bytes
from app.services.wechat_binding_store import bind_code_to_user, get_binding_for_code

router = APIRouter(prefix="/miniprogram", dependencies=[Depends(use_team_context)])

GROUP_FILTER_STATUS = {
    "todo": None,
    "uploaded": "uploaded",
    "exception": "exception",
    "all": None,
}
ALLOWED_NON_IDLE_EVENTS = {"group_draft_completed", "group_draft_deleted", "group_uploaded"}
_upload_lock = threading.RLock()
_pending_upload_batches: dict[str, dict[str, Any]] = {}


class WechatLoginRequest(BaseModel):
    code: str


class WechatBindRequest(BaseModel):
    code: str
    username: str
    password: str


class HeartbeatRequest(BaseModel):
    task_id: str | int | None = None
    occurred_at: str = ""


class NonIdleEventRequest(BaseModel):
    event_type: str
    task_id: str | int | None = None
    group_id: str = ""
    client_batch_id: str = ""
    occurred_at: str = ""


def authenticate_any_user(username: str, password: str, request: Request) -> dict[str, Any] | None:
    ip = request_client_ip(request)
    device = request_device(request)
    return (
        authenticate_user(username, password, ip=ip, device=device)
        or environment_admin_login(username, password)
        or demo_login_user(username, password)
    )


def public_miniprogram_user(user: dict[str, Any]) -> dict[str, Any]:
    if "status" in user:
        visible = public_user(user)
    else:
        visible = {
            "username": user["username"],
            "name": user.get("name") or user["username"],
            "roles": list(user.get("roles") or []),
            "team_id": normalize_team_id(user.get("team_id")),
            "status": "active",
            "home": user.get("home") or "/app?page=construction",
        }
    visible["home"] = "/pages/tasks/index"
    return visible


def miniprogram_auth_payload(user: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        **user,
        "username": user["username"],
        "team_id": normalize_team_id(user.get("team_id")),
        "home": "/pages/tasks/index",
    }
    return {
        "access_token": create_access_token(normalized),
        "token_type": "bearer",
        "openid": binding["openid"],
        "team_id": normalized["team_id"],
        "user": public_miniprogram_user(normalized),
    }


def require_constructor_payload(request: Request) -> dict[str, Any]:
    payload = bearer_payload(request.headers.get("authorization"))
    if "constructor" not in set(payload.get("roles") or []):
        raise HTTPException(status_code=403, detail="Constructor role required")
    return payload


def user_for_binding(binding: dict[str, Any]) -> dict[str, Any] | None:
    user = get_user(binding["username"])
    if user:
        return user
    # Demo accounts are not stored in the user file, but they are useful for
    # local acceptance tests and the existing demo flow.
    demo_user = demo_login_user(binding["username"], "construct123")
    if demo_user and "constructor" in set(demo_user.get("roles") or []):
        return demo_user
    return None


def map_task(raw: dict[str, Any]) -> dict[str, Any]:
    renovation_count = int(raw.get("renovation_count") or raw.get("groups") or raw.get("total_groups") or 0)
    uploaded_count = int(raw.get("construction_uploaded_count") or raw.get("uploaded_count") or 0)
    unbuilt_count = int(
        raw.get("construction_unbuilt_count")
        or raw.get("unconstructed_groups")
        or max(renovation_count - uploaded_count, 0)
    )
    exception_count = int(raw.get("construction_exception_count") or raw.get("exception_groups") or 0)
    return {
        "id": raw.get("id"),
        "title": raw.get("title") or raw.get("name") or raw.get("terminal") or f"任务 {raw.get('id')}",
        "terminal": raw.get("terminal") or "",
        "total_groups": renovation_count,
        "uploaded_count": uploaded_count,
        "unbuilt_count": unbuilt_count,
        "exception_count": exception_count,
        "updated_at": raw.get("updated_at") or raw.get("created_at") or "",
        "source": "assigned",
    }


def map_group(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": raw.get("id") or "",
        "task_id": raw.get("task_id"),
        "meter_no": raw.get("meter_no") or "",
        "address": raw.get("address") or raw.get("installation_address") or "",
        "collector": raw.get("collector") or "",
        "module_asset_no": raw.get("module_asset_no") or raw.get("asset_no") or "",
        "construction_collector": raw.get("construction_collector") or "",
        "construction_module_asset_no": raw.get("construction_module_asset_no") or "",
        "construction_status": raw.get("construction_status") or raw.get("status") or "",
        "exception_note": raw.get("exception_note") or "",
        "photo_count": int(raw.get("photo_count") or 0),
    }


def pending_upload_key(actor: str, group_id: str, client_batch_id: str) -> str:
    return f"{actor}:{group_id}:{client_batch_id}"


async def save_upload_file_record(
    *,
    group_id: str,
    request: Request,
    file: UploadFile,
    client_batch_id: str,
    client_completed_at: str,
    client_photo_id: str,
    photo_slot: str,
) -> dict[str, Any]:
    filename = file.filename or "photo.jpg"
    try:
        normalize_suffix(filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded image is empty")
    try:
        stored = save_image_bytes(
            scope="construction",
            filename=filename,
            content=content,
            content_type=file.content_type or "",
            team_id=current_request_team(request),
            group_id=group_id,
            key_hint=f"{group_id}-{client_batch_id[:16] or 'batch'}-{client_photo_id[:16]}",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "url": stored["url"],
        "sha256": stored["sha256"],
        "client_photo_id": client_photo_id,
        "client_completed_at": client_completed_at,
        "slot": photo_slot,
        "filename": filename,
        "storage_type": stored["storage_type"],
        "storage_key": stored["storage_key"],
        "storage_bucket": stored.get("storage_bucket", ""),
        "storage_source": stored["storage_source"],
    }


@router.post("/auth/bind")
def bind_wechat(payload: WechatBindRequest, request: Request):
    user = authenticate_any_user(payload.username, payload.password, request)
    if user is None:
        return error_response(request, "invalid_credentials", "Username or password is incorrect.", status_code=401)
    if "constructor" not in set(user.get("roles") or []):
        raise HTTPException(status_code=403, detail="Only constructor accounts can bind miniprogram login")
    binding = bind_code_to_user(payload.code, user)
    return ok(request, miniprogram_auth_payload(user, binding))


@router.post("/auth/login")
def login_wechat(payload: WechatLoginRequest, request: Request):
    try:
        binding = get_binding_for_code(payload.code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not binding:
        return error_response(request, "wechat_not_bound", "Wechat account is not bound.", status_code=404)
    user = user_for_binding(binding)
    if user is None or "constructor" not in set(user.get("roles") or []):
        raise HTTPException(status_code=403, detail="Bound constructor account is not available")
    return ok(request, miniprogram_auth_payload(user, binding))


@router.get("/tasks")
def tasks(request: Request):
    payload = require_constructor_payload(request)
    username = str(payload.get("sub") or "").strip()
    items = [map_task(item) for item in state_repository().list_construction_tasks(actor=username, include_closed=False)]
    return ok(request, {"items": items})


def require_assigned_task(task_id: int, actor: str) -> None:
    assigned_task_ids = {
        int(item.get("id"))
        for item in state_repository().list_construction_tasks(actor=actor, include_closed=False)
        if item.get("id") is not None
    }
    if int(task_id) not in assigned_task_ids:
        raise HTTPException(status_code=404, detail="Task not found")


@router.get("/tasks/{task_id}/groups")
def task_groups(task_id: int, request: Request, filter: str = "todo"):
    payload = require_constructor_payload(request)
    actor = str(payload.get("sub") or "").strip()
    require_assigned_task(task_id, actor)
    if filter not in GROUP_FILTER_STATUS:
        raise HTTPException(status_code=400, detail="Unsupported group filter")
    if filter == "exception":
        result = state_repository().list_exception_groups(limit=1000, offset=0)
        items = [map_group(item) for item in result.get("items", []) if item.get("task_id") == task_id]
        return ok(request, {"total": len(items), "items": items})
    result = state_repository().list_construction_task_groups(
        task_id,
        limit=1000,
        offset=0,
        status=GROUP_FILTER_STATUS[filter],
        summary_only=True,
    )
    items = [map_group(item) for item in result.get("items", [])]
    return ok(request, {"total": result.get("total", len(items)), "items": items})


@router.post("/groups/{group_id}/upload-batch")
async def upload_group_batch(
    group_id: str,
    request: Request,
    client_batch_id: str = Form(default=""),
    client_completed_at: str = Form(default=""),
    collector: str = Form(default=""),
    module_asset_no: str = Form(default=""),
    exception_note: str = Form(default=""),
    photo_slots: list[str] = Form(default=[]),
    client_photo_ids: list[str] = Form(default=[]),
    files: list[UploadFile] = File(default=[]),
):
    payload = require_constructor_payload(request)
    actor = str(payload.get("sub") or "").strip()
    if is_all_zero_construction_code(group_id):
        raise HTTPException(status_code=400, detail="No work order: 00000000 placeholder group cannot upload")
    validate_construction_upload_group_before_file_save(group_id)
    if not files:
        raise HTTPException(status_code=400, detail="At least one image file is required")
    records: list[dict[str, Any]] = []
    for index, file in enumerate(files):
        filename = file.filename or f"photo-{index + 1}.jpg"
        try:
            normalize_suffix(filename)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        content = await file.read()
        if not content:
            continue
        client_photo_id = client_photo_ids[index] if index < len(client_photo_ids) else f"photo-{index + 1}"
        slot = photo_slots[index] if index < len(photo_slots) else "other"
        try:
            stored = save_image_bytes(
                scope="construction",
                filename=filename,
                content=content,
                content_type=file.content_type or "",
                team_id=current_request_team(request),
                group_id=group_id,
                key_hint=f"{group_id}-{client_batch_id[:16] or 'batch'}-{client_photo_id[:16]}",
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        records.append(
            {
                "url": stored["url"],
                "sha256": stored["sha256"],
                "client_photo_id": client_photo_id,
                "client_completed_at": client_completed_at,
                "slot": slot,
                "filename": filename,
                "storage_type": stored["storage_type"],
                "storage_key": stored["storage_key"],
                "storage_bucket": stored.get("storage_bucket", ""),
                "storage_source": stored["storage_source"],
            }
        )
    if not records:
        raise HTTPException(status_code=400, detail="Uploaded images are empty")
    try:
        result = state_repository().upload_construction_group_batch(
            group_id,
            actor=actor,
            client_batch_id=client_batch_id,
            collector=collector,
            module_asset_no=module_asset_no,
            photos=records,
            creator=display_name_for_actor(request, actor),
            client_completed_at=client_completed_at,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response = {**response_payload(result), "uploaded_urls": [item["url"] for item in records]}
    if exception_note.strip() and isinstance(response.get("group"), dict):
        response["group"]["exception_note"] = exception_note.strip()
    return ok(request, response)


@router.post("/groups/{group_id}/upload-file")
async def upload_group_file(
    group_id: str,
    request: Request,
    client_batch_id: str = Form(default=""),
    client_completed_at: str = Form(default=""),
    collector: str = Form(default=""),
    module_asset_no: str = Form(default=""),
    photo_slot: str = Form(default="other"),
    client_photo_id: str = Form(default=""),
    expected_count: int = Form(default=1),
    commit: bool = Form(default=False),
    file: UploadFile = File(...),
):
    payload = require_constructor_payload(request)
    actor = str(payload.get("sub") or "").strip()
    if is_all_zero_construction_code(group_id):
        raise HTTPException(status_code=400, detail="No work order: 00000000 placeholder group cannot upload")
    validate_construction_upload_group_before_file_save(group_id)
    client_batch_id = client_batch_id.strip()
    if not client_batch_id:
        raise HTTPException(status_code=400, detail="client_batch_id is required")
    client_photo_id = client_photo_id.strip() or photo_slot
    record = await save_upload_file_record(
        group_id=group_id,
        request=request,
        file=file,
        client_batch_id=client_batch_id,
        client_completed_at=client_completed_at,
        client_photo_id=client_photo_id,
        photo_slot=photo_slot,
    )
    key = pending_upload_key(actor, group_id, client_batch_id)
    with _upload_lock:
        batch = _pending_upload_batches.setdefault(
            key,
            {
                "group_id": group_id,
                "actor": actor,
                "client_batch_id": client_batch_id,
                "client_completed_at": client_completed_at,
                "collector": collector,
                "module_asset_no": module_asset_no,
                "records": {},
            },
        )
        batch["client_completed_at"] = client_completed_at or batch.get("client_completed_at", "")
        batch["collector"] = collector or batch.get("collector", "")
        batch["module_asset_no"] = module_asset_no or batch.get("module_asset_no", "")
        batch["records"][client_photo_id] = record
        records = list(batch["records"].values())
        should_commit = commit or len(records) >= max(expected_count, 1)
        if not should_commit:
            return ok(
                request,
                {
                    "status": "staged",
                    "staged_count": len(records),
                    "expected_count": expected_count,
                    "uploaded_url": record["url"],
                },
            )
        del _pending_upload_batches[key]
    try:
        result = state_repository().upload_construction_group_batch(
            group_id,
            actor=actor,
            client_batch_id=client_batch_id,
            collector=collector,
            module_asset_no=module_asset_no,
            photos=records,
            creator=display_name_for_actor(request, actor),
            client_completed_at=client_completed_at,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(
        request,
        {
            "status": "committed",
            **response_payload(result),
            "uploaded_urls": [item["url"] for item in records],
        },
    )


@router.post("/activity/heartbeat")
def heartbeat(payload: HeartbeatRequest, request: Request):
    auth_payload = require_constructor_payload(request)
    try:
        event = state_repository().record_construction_activity_event(
            event_type="construction_heartbeat",
            actor=str(auth_payload.get("sub") or ""),
            task_id=payload.task_id,
            occurred_at=payload.occurred_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, event)


@router.post("/activity/non-idle-events")
def non_idle_event(payload: NonIdleEventRequest, request: Request):
    if payload.event_type not in ALLOWED_NON_IDLE_EVENTS:
        raise HTTPException(status_code=400, detail="Unsupported construction non-idle event")
    auth_payload = require_constructor_payload(request)
    try:
        event = state_repository().record_construction_activity_event(
            event_type=payload.event_type,
            actor=str(auth_payload.get("sub") or ""),
            task_id=payload.task_id,
            group_id=payload.group_id,
            client_batch_id=payload.client_batch_id,
            occurred_at=payload.occurred_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, event)
