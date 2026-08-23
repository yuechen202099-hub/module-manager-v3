from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.config import settings
from app.core.responses import error_response, ok
from app.database import SessionLocal
from app.models import CollectorPhoto
from app.services.collector_transfer import (
    CollectorAllocationConflictError,
    PoolInsufficientError,
    collector_no_from_photo_filename,
    normalize_identifier,
    read_collector_numbers_from_workbook,
)
from app.services.photo_storage import delete_saved_image, save_image_bytes


router = APIRouter(prefix="/collector-transfer")


class CreateTransferRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=64)
    name: str = Field(default="采集器盘点", min_length=1, max_length=200)


class ScanCollectorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collector_no: str = Field(min_length=1, max_length=255)


class WorkbenchItemStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completed: bool


def request_identity(request: Request) -> tuple[str, str]:
    payload = getattr(request.state, "auth", None) or {}
    if payload:
        team_id = normalize_identifier(payload.get("team_id"))
        actor = normalize_identifier(payload.get("username") or payload.get("sub"))
    elif settings.app_env.lower() not in {"prod", "production"}:
        team_id = normalize_identifier(request.headers.get("X-Team-Id"))
        actor = "local-test"
    else:
        team_id = ""
        actor = ""
    if not team_id:
        raise HTTPException(status_code=400, detail="Team context is required")
    return team_id, actor or "authenticated-user"


@contextmanager
def service_for_request(request: Request) -> Iterator[object]:
    from app.services.collector_transfer import PostgresCollectorTransferService

    team_id, actor = request_identity(request)
    with SessionLocal() as session:
        try:
            yield PostgresCollectorTransferService(session=session, team_id=team_id, actor=actor)
        except BaseException:
            session.rollback()
            raise


def service_error_response(request: Request, exc: Exception):
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


def saved_image_is_registered(*, team_id: str, stored: dict[str, object]) -> bool:
    sha256 = normalize_identifier(stored.get("sha256"))
    object_key = normalize_identifier(stored.get("storage_key") or stored.get("url"))
    if not sha256 or not object_key:
        return False
    with SessionLocal() as session:
        return (
            session.scalar(
                select(CollectorPhoto.id).where(
                    CollectorPhoto.team_id == team_id,
                    CollectorPhoto.sha256 == sha256,
                    CollectorPhoto.object_key == object_key,
                    CollectorPhoto.is_active.is_(True),
                )
            )
            is not None
        )


def cleanup_unregistered_saved_images(
    *,
    team_id: str,
    saved_objects: list[dict[str, object]],
) -> None:
    for stored in saved_objects:
        if stored.get("created_new") and not saved_image_is_registered(
            team_id=team_id,
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


@router.post("/runs/{run_id}/scan")
def scan_collector(run_id: str, payload: ScanCollectorRequest, request: Request):
    return call_service(
        request,
        lambda service: service.scan_collector(run_id=run_id, collector_no=payload.collector_no),
    )


@router.post("/runs/{run_id}/allocate")
def allocate_collectors(run_id: str, request: Request):
    return call_service(request, lambda service: service.allocate(run_id=run_id))


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


@router.post("/runs/{run_id}/collectors/{collector_id}/photo")
async def upload_collector_photo(
    run_id: str,
    collector_id: str,
    request: Request,
    file: UploadFile = File(...),
):
    team_id, _actor = request_identity(request)
    content = await file.read()
    filename = normalize_identifier(file.filename) or f"{collector_id}.jpg"
    try:
        stored = save_image_bytes(
            scope="collector-transfer",
            filename=filename,
            content=content,
            content_type=file.content_type or "",
            team_id=team_id,
            group_id=run_id,
            key_hint=f"{collector_id}-{run_id}",
            cleanup_safe=True,
        )
    except ValueError as exc:
        return service_error_response(request, exc)
    try:
        with service_for_request(request) as service:
            result = service.register_photo(
                run_id=run_id,
                collector_id=collector_id,
                original_filename=filename,
                stored=stored,
                byte_size=len(content),
            )
    except (KeyError, ValueError) as exc:
        cleanup_unregistered_saved_images(team_id=team_id, saved_objects=[stored])
        return service_error_response(request, exc)
    except Exception:
        cleanup_unregistered_saved_images(team_id=team_id, saved_objects=[stored])
        raise
    return ok(request, result)


@router.post("/runs/{run_id}/inventory/import")
async def import_inventory(
    run_id: str,
    request: Request,
    workbook: UploadFile | None = File(default=None),
    photos: list[UploadFile] = File(default=[]),
):
    team_id, _actor = request_identity(request)
    try:
        rows = read_collector_numbers_from_workbook(await workbook.read()) if workbook is not None else ()
    except ValueError as exc:
        return service_error_response(request, exc)
    saved_objects: list[dict[str, object]] = []
    photos_by_collector: dict[str, dict[str, object]] = {}
    try:
        for photo_file in photos:
            filename = normalize_identifier(photo_file.filename)
            collector_no = collector_no_from_photo_filename(filename)
            if not collector_no:
                continue
            content = await photo_file.read()
            stored = save_image_bytes(
                scope="collector-transfer",
                filename=filename,
                content=content,
                content_type=photo_file.content_type or "",
                team_id=team_id,
                group_id=run_id,
                key_hint=f"{collector_no}-{run_id}-{uuid4().hex[:12]}",
                cleanup_safe=True,
            )
            saved_objects.append(stored)
            photos_by_collector.setdefault(
                collector_no,
                {
                    "original_filename": filename,
                    "stored": stored,
                    "byte_size": len(content),
                },
            )
        row_collectors = {collector_no for _row_number, collector_no in rows}
        next_row_number = max((row_number for row_number, _collector_no in rows), default=1) + 1
        combined_rows = list(rows)
        for collector_no in sorted(set(photos_by_collector) - row_collectors):
            combined_rows.append((next_row_number, collector_no))
            next_row_number += 1
        if not combined_rows:
            raise ValueError("Excel 或按采集器号命名的照片至少提供一项")
        with service_for_request(request) as service:
            result = service.import_inventory(
                run_id=run_id,
                rows=tuple(combined_rows),
                photos_by_collector=photos_by_collector,
            )
        cleanup_unregistered_saved_images(team_id=team_id, saved_objects=saved_objects)
    except (KeyError, ValueError) as exc:
        cleanup_unregistered_saved_images(team_id=team_id, saved_objects=saved_objects)
        return service_error_response(request, exc)
    except Exception:
        cleanup_unregistered_saved_images(team_id=team_id, saved_objects=saved_objects)
        raise
    return ok(request, result)
