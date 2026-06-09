from pydantic import BaseModel, Field

from fastapi import APIRouter, Body, HTTPException, Request

from app.core.responses import ok
from app.services.ezcodes_sync import (
    EZCODES_ENV_ID,
    EzcodesBackend,
    EzcodesCloudBaseBackend,
    EzcodesCredentials,
    EzcodesError,
    build_target_sync_plan,
    download_scan_data_preview,
)
from app.services.ezcodes_scheduler import EzcodesSyncOptions, sync_manager

router = APIRouter(prefix="/projects/{project_id}/scan/ezcodes")


class EzcodesCredentialsRequest(BaseModel):
    access_token: str = Field(min_length=1)
    team_id: str = Field(min_length=1)
    env_id: str = EZCODES_ENV_ID
    endpoint: str | None = None


class EzcodesSyncPreviewRequest(BaseModel):
    credentials: EzcodesCredentialsRequest


class EzcodesDownloadTestRequest(BaseModel):
    credentials: EzcodesCredentialsRequest
    max_files: int = Field(default=3, ge=1, le=20)
    max_records_per_file: int = Field(default=10, ge=1, le=100)


_backend: EzcodesBackend = EzcodesCloudBaseBackend()


def set_ezcodes_backend(backend: EzcodesBackend) -> None:
    global _backend
    _backend = backend
    sync_manager.set_backend(backend)


def build_credentials(payload: EzcodesCredentialsRequest) -> EzcodesCredentials:
    credential_kwargs = {
        "access_token": payload.access_token,
        "team_id": payload.team_id,
        "env_id": payload.env_id,
    }
    if payload.endpoint:
        credential_kwargs["endpoint"] = payload.endpoint
    return EzcodesCredentials(**credential_kwargs)


@router.post("/preview")
def preview_ezcodes_sync(project_id: int, payload: EzcodesSyncPreviewRequest, request: Request):
    credentials = build_credentials(payload.credentials)
    try:
        plan = build_target_sync_plan(_backend, credentials)
    except EzcodesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, {"project_id": project_id, "plan": plan})


@router.post("/download-test")
def download_ezcodes_scan_test(project_id: int, payload: EzcodesDownloadTestRequest, request: Request):
    credentials = build_credentials(payload.credentials)
    try:
        result = download_scan_data_preview(
            _backend,
            credentials,
            max_files=payload.max_files,
            max_records_per_file=payload.max_records_per_file,
        )
    except EzcodesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, {"project_id": project_id, "result": result})


@router.get("/sync/status")
def ezcodes_sync_status(project_id: int, request: Request):
    return ok(request, {"project_id": project_id, "sync": sync_manager.status()})


@router.post("/sync")
def trigger_ezcodes_sync(
    project_id: int,
    request: Request,
    payload: EzcodesDownloadTestRequest | None = Body(default=None),
):
    credentials = build_credentials(payload.credentials) if payload else None
    options = None
    if payload:
        options = EzcodesSyncOptions(
            max_files=payload.max_files,
            max_records_per_file=payload.max_records_per_file,
        )
    try:
        result = sync_manager.trigger(credentials=credentials, options=options, trigger="manual")
    except EzcodesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, {"project_id": project_id, "sync": result})
