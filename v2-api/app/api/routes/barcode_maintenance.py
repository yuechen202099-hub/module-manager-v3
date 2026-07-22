from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.routes.auth import require_admin
from app.api.routes.exports import use_team_context
from app.core.responses import ok
from app.services.barcode_maintenance_worker import (
    enqueue_verification_jobs,
    maintenance_status,
    set_maintenance_paused,
)
from app.services.state_repository import StateBackendNotReady


router = APIRouter(
    prefix="/barcode-maintenance",
    dependencies=[Depends(use_team_context)],
)


class MaintenanceEnqueueRequest(BaseModel):
    group_ids: list[str] = Field(default_factory=list)


def _actor(payload: dict) -> str:
    return str(payload.get("username") or payload.get("sub") or "admin").strip() or "admin"


def _run_control(operation):
    try:
        return operation()
    except StateBackendNotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/status")
def status(request: Request, admin: dict = Depends(require_admin)):
    del admin
    return ok(request, _run_control(maintenance_status))


@router.post("/pause")
def pause(request: Request, admin: dict = Depends(require_admin)):
    return ok(request, _run_control(lambda: set_maintenance_paused(True, _actor(admin))))


@router.post("/resume")
def resume(request: Request, admin: dict = Depends(require_admin)):
    return ok(request, _run_control(lambda: set_maintenance_paused(False, _actor(admin))))


@router.post("/enqueue")
def enqueue(
    payload: MaintenanceEnqueueRequest,
    request: Request,
    admin: dict = Depends(require_admin),
):
    return ok(
        request,
        _run_control(lambda: enqueue_verification_jobs(payload.group_ids, _actor(admin))),
    )
