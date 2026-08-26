from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Literal, NamedTuple
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.responses import error_response, ok
from app.core.security import decode_access_token
from app.database import SessionLocal
from app.models import CollectorPhoto, Project
from app.services.collector_transfer import (
    CollectorAllocationConflictError,
    CollectorDirectConflictError,
    CollectorPhotoConflictError,
    CollectorRunBlockedError,
    CollectorScanProvenanceError,
    CollectorSnapshotChangedError,
    CollectorTerminalSourceBlockedError,
    CollectorWorkbenchIncompleteError,
    PoolInsufficientError,
    TerminalNoConstructedMeterError,
    TerminalNotFoundError,
    TerminalReviewRequiredError,
    TerminalSourceChangedError,
    normalize_identifier,
)
from app.services.photo_storage import delete_saved_image, save_image_bytes


router = APIRouter(prefix="/collector-transfer")


class CreateTransferRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=64)
    name: str = Field(default="采集器盘点", min_length=1, max_length=200)


class InventoryScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=64)
    collector_no: str = Field(min_length=1, max_length=255)


class WorkbenchItemStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completed: bool


class OpenGlobalTerminalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    terminal_key: str = Field(min_length=1, max_length=2048)
    project_id: str = Field(min_length=1, max_length=64)
    terminal_code: str = Field(min_length=1, max_length=255)
    source_revision: str = Field(default="", max_length=64)


class OpenReviewWorkbenchTerminalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    terminal_key: str = Field(min_length=1, max_length=2048)
    source_revision: str = Field(default="", max_length=64)


class RequestIdentity(NamedTuple):
    team_id: str
    actor: str
    roles: frozenset[str]


def roles_from_payload(payload: Mapping[str, object]) -> frozenset[str]:
    values: list[object] = [payload.get("role")]
    raw_roles = payload.get("roles")
    if isinstance(raw_roles, (list, tuple, set, frozenset)):
        values.extend(raw_roles)
    elif raw_roles is not None:
        values.append(raw_roles)
    return frozenset(
        role
        for role in (
            normalize_identifier(value).lower()
            for value in values
        )
        if role
    )


def request_identity(request: Request) -> RequestIdentity:
    payload = getattr(request.state, "auth", None) or {}
    if not payload:
        authorization = normalize_identifier(request.headers.get("Authorization"))
        if not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Authentication required")
        try:
            payload = decode_access_token(authorization.split(" ", 1)[1].strip())
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Invalid access token") from exc
        request.state.auth = payload
    team_id = normalize_identifier(payload.get("team_id"))
    actor = normalize_identifier(payload.get("username") or payload.get("sub"))
    if not team_id or not actor:
        raise HTTPException(status_code=401, detail="Authenticated team and actor are required")
    return RequestIdentity(team_id, actor, roles_from_payload(payload))


class CollectorForbiddenError(ValueError):
    """An authenticated user lacks the administrator role for a mutation."""


def require_admin(request: Request) -> RequestIdentity:
    identity = request_identity(request)
    if "admin" not in identity.roles:
        raise CollectorForbiddenError("administrator role is required")
    return identity


@contextmanager
def service_for_request(request: Request) -> Iterator[object]:
    from app.services.collector_transfer import PostgresCollectorTransferService

    identity = require_admin(request)
    with SessionLocal() as session:
        try:
            yield PostgresCollectorTransferService(
                session=session,
                team_id=identity.team_id,
                actor=identity.actor,
            )
        except BaseException:
            session.rollback()
            raise


def service_error_response(request: Request, exc: Exception):
    if isinstance(exc, CollectorForbiddenError):
        return error_response(
            request,
            code="forbidden",
            message="仅管理员可以执行该操作。",
            status_code=403,
        )
    if isinstance(exc, TerminalNotFoundError):
        return error_response(
            request,
            code="terminal_not_found",
            message="请求的终端不存在。",
            status_code=404,
        )
    if isinstance(exc, TerminalNoConstructedMeterError):
        return error_response(
            request,
            code="terminal_has_no_constructed_meter",
            message="该终端没有已施工表计，不能进入翻拍工作台。",
            status_code=409,
        )
    if isinstance(exc, TerminalReviewRequiredError):
        blockers = [
            {
                "group_id": meter.group_id,
                "codes": list(meter.blockers),
            }
            for meter in exc.meters
        ]
        return error_response(
            request,
            code="terminal_review_required",
            message="该终端仍有资料组未通过正式审阅。",
            details={
                "group_ids": [item["group_id"] for item in blockers],
                "blockers": blockers,
            },
            status_code=409,
        )
    if isinstance(exc, TerminalSourceChangedError):
        return error_response(
            request,
            code="terminal_source_changed",
            message="终端来源资料已变化，请刷新后重试。",
            status_code=409,
        )
    if isinstance(exc, PoolInsufficientError):
        return error_response(
            request,
            code="pool_insufficient",
            message="采集器池数量不足，本次没有进行任何分配。",
            details={"required": exc.required, "available": exc.available},
            status_code=409,
        )
    if isinstance(exc, CollectorAllocationConflictError):
        return error_response(
            request,
            code="allocation_conflict",
            message="采集器或需求已被其他分配占用，本次操作已回滚。",
            status_code=409,
        )
    if isinstance(exc, CollectorDirectConflictError):
        return error_response(
            request,
            code="direct_conflict",
            message="同号实物已被另一个有效终端占用。",
            status_code=409,
        )
    if isinstance(exc, CollectorSnapshotChangedError):
        return error_response(
            request,
            code="snapshot_changed",
            message="终端来源或快照进度已变化，请刷新后重试。",
            status_code=409,
        )
    if isinstance(exc, CollectorTerminalSourceBlockedError):
        return error_response(
            request,
            code="terminal_source_blocked",
            message="终端来源资料不满足翻拍要求。",
            status_code=409,
        )
    if isinstance(exc, CollectorRunBlockedError):
        return error_response(
            request,
            code="run_blocked",
            message="批次存在资料阻断，不能执行随机分配。",
            status_code=409,
        )
    if isinstance(exc, CollectorPhotoConflictError):
        return error_response(
            request,
            code="photo_conflict",
            message="该照片已绑定其他采集器，本次操作已回滚。",
            status_code=409,
        )
    if isinstance(exc, CollectorScanProvenanceError):
        return error_response(
            request,
            code="scan_provenance_required",
            message="请先在当前批次扫描该实物采集器，再上传照片。",
            status_code=409,
        )
    if isinstance(exc, CollectorWorkbenchIncompleteError):
        return error_response(
            request,
            code="workbench_incomplete",
            message="翻拍工作项资料不完整或存在阻断，不能标记完成。",
            details={"reasons": list(exc.reasons)},
            status_code=409,
        )
    if isinstance(exc, KeyError):
        return error_response(
            request,
            code="not_found",
            message="请求的采集器中转资源不存在。",
            status_code=404,
        )
    return error_response(
        request,
        code="invalid_request",
        message=str(exc) or "请求参数或当前业务状态无效。",
        status_code=400,
    )


def call_service(request: Request, operation):
    try:
        with service_for_request(request) as service:
            result = operation(service)
    except (KeyError, ValueError) as exc:
        return service_error_response(request, exc)
    return ok(request, result)


def call_admin_service(request: Request, operation):
    try:
        require_admin(request)
    except CollectorForbiddenError as exc:
        return service_error_response(request, exc)
    return call_service(request, operation)

@router.get("/projects")
def list_transfer_projects(request: Request):
    try:
        identity = require_admin(request)
    except CollectorForbiddenError as exc:
        return service_error_response(request, exc)
    with SessionLocal() as session:
        projects = session.scalars(
            select(Project)
            .where(Project.team_id == identity.team_id, Project.status == "active")
            .order_by(Project.created_at, Project.id)
        ).all()
    return ok(
        request,
        {
            "items": [
                {
                    "id": str(project.id),
                    "name": project.name,
                    "status": project.status,
                    "updated_at": project.updated_at.isoformat() if project.updated_at else None,
                }
                for project in projects
            ]
        },
    )


InventoryStatus = Literal["direct", "available", "reserved", "used", "awaiting_photo"]
GlobalTerminalState = Literal["ready", "needs_replacement", "pool_shortage", "blocked"]


def saved_image_is_registered(
    *,
    team_id: str,
    project_id: str,
    stored: dict[str, object],
) -> bool:
    sha256 = normalize_identifier(stored.get("sha256"))
    object_key = normalize_identifier(stored.get("storage_key") or stored.get("url"))
    try:
        project_uuid = UUID(normalize_identifier(project_id))
    except (ValueError, TypeError, AttributeError):
        return False
    if not sha256 or not object_key:
        return False
    with SessionLocal() as session:
        return (
            session.scalar(
                select(CollectorPhoto.id).where(
                    CollectorPhoto.team_id == team_id,
                    CollectorPhoto.project_id == project_uuid,
                    CollectorPhoto.sha256 == sha256,
                    CollectorPhoto.object_key == object_key,
                )
            )
            is not None
        )


def cleanup_unregistered_saved_images(
    *,
    team_id: str,
    project_id: str,
    saved_objects: list[dict[str, object]],
) -> None:
    for stored in saved_objects:
        if stored.get("created_new") and not saved_image_is_registered(
            team_id=team_id,
            project_id=project_id,
            stored=stored,
        ):
            delete_saved_image(stored)


@router.post("/runs")
def create_run(payload: CreateTransferRunRequest, request: Request):
    return call_service(
        request,
        lambda service: service.create_run(project_id=payload.project_id, name=payload.name),
    )


@router.get("/runs")
def list_runs(request: Request, project_id: str | None = Query(default=None)):
    return call_service(request, lambda service: service.list_runs(project_id=project_id))


@router.get("/runs/{run_id}")
def run_detail(run_id: str, request: Request):
    return call_service(request, lambda service: service.list_workbench(run_id=run_id))


@router.post("/inventory/scan")
def scan_inventory(payload: InventoryScanRequest, request: Request):
    return call_service(
        request,
        lambda service: service.scan_inventory(
            project_id=payload.project_id,
            collector_no=payload.collector_no,
        ),
    )


@router.get("/inventory")
def list_inventory(
    request: Request,
    project_id: str = Query(min_length=1, max_length=64),
    status: InventoryStatus | None = Query(default=None),
):
    return call_service(
        request,
        lambda service: service.list_inventory(project_id=project_id, status=status),
    )


@router.post("/runs/{run_id}/allocate")
def allocate_collectors(run_id: str, request: Request):
    return call_admin_service(
        request,
        lambda service: service.allocate(run_id=run_id),
    )


@router.post("/assignments/{assignment_id}/rollback")
def rollback_assignment(assignment_id: str, request: Request):
    return call_admin_service(
        request,
        lambda service: service.rollback_assignment(assignment_id=assignment_id),
    )


@router.get("/workbench/terminals")
def list_global_terminals(
    request: Request,
    query: str = Query(default="", max_length=255),
    state: GlobalTerminalState | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    include_blocked: bool = Query(default=False),
):
    if include_blocked:
        try:
            require_admin(request)
        except CollectorForbiddenError as exc:
            return service_error_response(request, exc)
    return call_service(
        request,
        lambda service: service.list_global_terminals(
            query=query,
            state=state,
            page=page,
            page_size=page_size,
            include_blocked=include_blocked,
        ),
    )


@router.post("/workbench/terminals/open")
def open_global_terminal(payload: OpenGlobalTerminalRequest, request: Request):
    return call_service(
        request,
        lambda service: service.open_global_terminal(
            project_id=payload.project_id,
            terminal_code=payload.terminal_code,
            source_revision=payload.source_revision,
            terminal_key_value=payload.terminal_key,
        ),
    )


@router.post("/review-workbench/terminals/open")
def open_review_workbench_terminal(
    payload: OpenReviewWorkbenchTerminalRequest,
    request: Request,
):
    return call_admin_service(
        request,
        lambda service: service.open_review_workbench_terminal(
            terminal_key_value=payload.terminal_key,
            source_revision=payload.source_revision,
        ),
    )


@router.get("/workbench/terminals/{terminal_id}")
def global_terminal_detail(terminal_id: str, request: Request):
    return call_service(
        request,
        lambda service: service.global_terminal_detail(terminal_id=terminal_id),
    )


@router.post("/workbench/terminals/{terminal_id}/replace-missing")
def replace_terminal_missing(terminal_id: str, request: Request):
    return call_admin_service(
        request,
        lambda service: service.replace_terminal_missing(terminal_id=terminal_id),
    )


@router.post("/workbench/terminals/{terminal_id}/refresh")
def refresh_global_terminal(terminal_id: str, request: Request):
    return call_admin_service(
        request,
        lambda service: service.refresh_global_terminal(terminal_id=terminal_id),
    )


@router.get("/runs/{run_id}/workbench")
def list_workbench(run_id: str, request: Request):
    return call_service(request, lambda service: service.list_workbench(run_id=run_id))


@router.get("/runs/{run_id}/workbench/{terminal_id}")
def terminal_workbench(run_id: str, terminal_id: str, request: Request):
    return call_service(
        request,
        lambda service: service.terminal_workbench(run_id=run_id, terminal_id=terminal_id),
    )


@router.patch("/workbench/items/{item_id}")
def set_workbench_item_status(item_id: str, payload: WorkbenchItemStatusRequest, request: Request):
    return call_service(
        request,
        lambda service: service.set_workbench_item_status(
            item_id=item_id,
            completed=payload.completed,
        ),
    )


@router.post("/inventory")
async def register_inventory(
    request: Request,
    project_id: str = Form(min_length=1, max_length=64),
    collector_no: str = Form(min_length=1, max_length=255),
    file: UploadFile = File(...),
):
    try:
        identity = require_admin(request)
    except CollectorForbiddenError as exc:
        return service_error_response(request, exc)
    submitted_fields = set((await request.form()).keys())
    unexpected_fields = sorted(submitted_fields - {"project_id", "collector_no", "file"})
    if unexpected_fields:
        return error_response(
            request,
            code="validation_error",
            message="请求包含未允许的字段。",
            details={"unexpected_fields": unexpected_fields},
            status_code=422,
        )
    normalized_project_id = normalize_identifier(project_id)
    normalized_collector_no = normalize_identifier(collector_no)
    if not normalized_project_id:
        return service_error_response(request, ValueError("project_id is required"))
    if not normalized_collector_no:
        return service_error_response(request, ValueError("collector_no is required"))
    content = await file.read()
    filename = normalize_identifier(file.filename) or f"{normalized_collector_no}.jpg"
    try:
        stored = save_image_bytes(
            scope="collector-inventory",
            filename=filename,
            content=content,
            content_type=file.content_type or "",
            team_id=identity.team_id,
            group_id=normalized_project_id,
            key_hint=f"{normalized_collector_no}-{normalized_project_id}",
            cleanup_safe=True,
        )
    except ValueError as exc:
        return service_error_response(request, exc)
    try:
        with service_for_request(request) as service:
            result = service.register_inventory(
                project_id=normalized_project_id,
                collector_no=normalized_collector_no,
                original_filename=filename,
                stored=stored,
                byte_size=len(content),
            )
    except (KeyError, ValueError) as exc:
        cleanup_unregistered_saved_images(
            team_id=identity.team_id,
            project_id=normalized_project_id,
            saved_objects=[stored],
        )
        return service_error_response(request, exc)
    except Exception:
        cleanup_unregistered_saved_images(
            team_id=identity.team_id,
            project_id=normalized_project_id,
            saved_objects=[stored],
        )
        raise
    cleanup_unregistered_saved_images(
        team_id=identity.team_id,
        project_id=normalized_project_id,
        saved_objects=[stored],
    )
    return ok(request, result)
