from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.core.security import decode_access_token
from app.schemas.export import ExceptionMetersExportRequest, FinalDeliveryExportRequest, TaskDetailExportRequest
from app.services.state_repository import get_state_repository
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


@router.post("/task-detail")
def export_task_detail(payload: TaskDetailExportRequest, request: Request):
    try:
        content = get_state_repository().build_task_detail_export(payload.task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    filename = f"task-detail-{payload.task_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
    return excel_response(content, filename)


@router.post("/final-delivery")
def export_final_delivery(payload: FinalDeliveryExportRequest, request: Request):
    try:
        content = get_state_repository().build_final_delivery_export(
            task_id=payload.task_id,
            terminal=payload.terminal,
            review_scope=payload.review_scope,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    scope = payload.task_id or payload.terminal or "terminal"
    filename = f"final-delivery-{scope}-{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
    return excel_response(content, filename)


@router.post("/exception-meters")
def export_exception_meters(payload: ExceptionMetersExportRequest, request: Request):
    reviewer = scoped_exception_reviewer(payload.reviewer.strip(), request)
    content = get_state_repository().build_exception_meter_export(reviewer=reviewer)
    filename = f"exception-meters-{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
    return excel_response(content, filename)


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
