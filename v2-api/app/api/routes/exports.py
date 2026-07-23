from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from app.core.security import decode_access_token
from app.core.responses import ok
from app.api.routes.auth import require_admin
from app.schemas.export_center import ExportJobCreateRequest
from app.schemas.export import ExceptionMetersExportRequest, FinalDeliveryExportRequest, TaskDetailExportRequest
from app.services import export_center
from app.services.state_repository import StateBackendNotReady
from app.services.state_repository import get_state_repository
from app.services.final_delivery_export import (
    DeliveryPackageValidationError,
    LeasedDeliveryPackage,
)
from app.services.delivery_package_queue import DeliveryPackageNotReady
from app.services.local_simulation import (
    reset_current_team,
    set_current_team,
)


async def use_team_context(request: Request):
    team_id = request.headers.get("X-Team-Id") or request.query_params.get("team_id") or ""
    payload = getattr(request.state, "auth", None)
    if not payload:
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            try:
                payload = decode_access_token(authorization.split(" ", 1)[1].strip())
            except ValueError:
                payload = {}
    if payload:
        team_id = (payload or {}).get("team_id") or team_id
        request.state.auth = payload
    token = set_current_team(team_id)
    try:
        yield
    finally:
        reset_current_team(token)


router = APIRouter(prefix="/exports", dependencies=[Depends(use_team_context)])


def state_repository():
    try:
        return get_state_repository()
    except StateBackendNotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def actor_from_auth(auth: dict) -> str:
    return str(auth.get("username") or auth.get("sub") or "")


class LeasedFileResponse(Response):
    def __init__(self, response: FileResponse, package: LeasedDeliveryPackage):
        self.response = response
        self.package = package
        self.status_code = response.status_code
        self.media_type = response.media_type
        self.background = response.background
        self.raw_headers = response.raw_headers

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        try:
            await self.response(scope, receive, send)
        finally:
            self.package.release()


@router.post("/task-detail")
def export_task_detail(payload: TaskDetailExportRequest, request: Request, auth: dict = Depends(require_admin)):
    try:
        content = state_repository().build_task_detail_export(payload.task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    filename = f"task-detail-{payload.task_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
    return excel_response(content, filename)


@router.post("/final-delivery")
def export_final_delivery(
    payload: FinalDeliveryExportRequest,
    request: Request,
    auth: dict = Depends(require_admin),
):
    try:
        package = state_repository().request_final_delivery_export(
            task_id=payload.task_id,
            terminal=payload.terminal,
            review_scope=payload.review_scope,
            requested_by=str(auth.get("sub") or ""),
        )
    except DeliveryPackageNotReady as exc:
        raise HTTPException(
            status_code=202,
            detail={
                "code": "formal_delivery_not_ready",
                "message": "正式交付包正在后台生成，请稍后重试。",
                "job_id": exc.job_id,
                "status": exc.status,
            },
        ) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    except DeliveryPackageValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "formal_delivery_invalid", "groups": exc.errors},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    scope = payload.task_id or payload.terminal or "terminal"
    filename = f"V3.1.1-final-delivery-{scope}-{datetime.now().strftime('%Y%m%d%H%M%S')}.zip"
    try:
        return LeasedFileResponse(
            FileResponse(
                package.path,
                media_type="application/zip",
                filename=filename,
            ),
            package,
        )
    except BaseException:
        package.release()
        raise


@router.post("/exception-meters")
def export_exception_meters(
    payload: ExceptionMetersExportRequest,
    request: Request,
    auth: dict = Depends(require_admin),
):
    reviewer = scoped_exception_reviewer(payload.reviewer.strip(), request)
    content = state_repository().build_exception_meter_export(reviewer=reviewer)
    filename = f"exception-meters-{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
    return excel_response(content, filename)


@router.post("/project-outside")
def export_project_outside(request: Request, auth: dict = Depends(require_admin)):
    content = state_repository().build_project_outside_export()
    filename = f"project-outside-{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
    return excel_response(content, filename)


@router.get("/catalog")
def export_catalog(request: Request, auth: dict = Depends(require_admin)):
    return ok(request, {"items": list(export_center.EXPORT_CATALOG)})


@router.get("/terminal-readiness")
def terminal_readiness(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20),
    query: str = "",
    auth: dict = Depends(require_admin),
):
    try:
        normalized_page_size = export_center.normalize_export_page_size(page_size)
        data = state_repository().list_terminal_delivery_readiness(
            page=page,
            page_size=normalized_page_size,
            query=query,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ok(request, data)


@router.get("/jobs")
def export_jobs(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20),
    job_type: str = "",
    auth: dict = Depends(require_admin),
):
    try:
        normalized_page_size = export_center.normalize_export_page_size(page_size)
        data = state_repository().list_export_jobs(
            page=page,
            page_size=normalized_page_size,
            job_type=job_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ok(request, data)


@router.post("/jobs")
def create_export_job(payload: ExportJobCreateRequest, request: Request, auth: dict = Depends(require_admin)):
    actor = actor_from_auth(auth)
    repository = state_repository()
    try:
        job = repository.create_export_job(
            job_type=payload.job_type,
            filters=payload.filters,
            actor=actor,
        )
        if job.get("created", True):
            repository.append_audit_event(
                "export_job_created",
                actor,
                {
                    "job_id": job["id"],
                    "job_type": payload.job_type,
                    "filters": payload.filters,
                },
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    data = {key: value for key, value in job.items() if key != "content"}
    return ok(request, data)


@router.get("/jobs/{job_id}/download")
def download_export_job(job_id: str, request: Request, auth: dict = Depends(require_admin)):
    actor = actor_from_auth(auth)
    repository = state_repository()
    try:
        download = repository.open_export_job_download(job_id, actor=actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Export job not found") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail="Export job is not ready") from exc
    if "path" in download:
        opened = export_center.open_validated_export_stream(
            download["path"],
            media_type=download.get("media_type") or "application/octet-stream",
            filename=download["file_name"],
        )
        return StreamingResponse(
            opened.iter_bytes(),
            media_type=opened.media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{opened.file_name}"',
                "Content-Length": str(opened.size_bytes),
            },
        )
    return Response(
        content=download["content"],
        media_type=download.get("media_type") or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{download["file_name"]}"'},
    )


def scoped_exception_reviewer(requested_reviewer: str, request: Request) -> str:
    payload = getattr(request.state, "auth", None) or {}
    roles = payload.get("roles") or []
    if roles and "admin" not in roles:
        return str(payload.get("sub") or requested_reviewer)
    return requested_reviewer


def excel_response(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
