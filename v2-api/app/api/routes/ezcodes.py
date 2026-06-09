from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from fastapi import APIRouter, Body, HTTPException, Request

from app.core.responses import ok
from app.services.ezcodes_sync import (
    EZCODES_CLOUD_API_ENDPOINT,
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


class EzcodesRawConfigRequest(BaseModel):
    payload: dict[str, Any]
    persist: bool = True


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


def credentials_from_raw_payload(payload: dict[str, Any]) -> EzcodesCredentials:
    access_token = str(payload.get("access_token") or "").strip()
    query = payload.get("query") if isinstance(payload.get("query"), dict) else {}
    team_value = query.get("teamId") if isinstance(query, dict) else None
    team_id = ""
    if isinstance(team_value, dict):
        team_id = str(team_value.get("$eq") or "").strip()
    elif team_value:
        team_id = str(team_value).strip()
    env_id = str(payload.get("env") or EZCODES_ENV_ID).strip()
    endpoint = str(payload.get("endpoint") or "").strip() or EZCODES_CLOUD_API_ENDPOINT
    if not access_token:
        raise EzcodesError("access_token is missing.")
    if not team_id:
        raise EzcodesError("query.teamId.$eq is missing.")
    return EzcodesCredentials(access_token=access_token, team_id=team_id, env_id=env_id, endpoint=endpoint)


def persist_ezcodes_env(credentials: EzcodesCredentials) -> None:
    env_path = Path(__file__).resolve().parents[3] / ".env"
    existing = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, value = line.split("=", 1)
                existing[key] = value
    existing.update(
        {
            "EZCODES_TEAM_ID": credentials.team_id,
            "EZCODES_ACCESS_TOKEN": credentials.access_token,
            "EZCODES_ENV_ID": credentials.env_id,
            "EZCODES_ENDPOINT": credentials.endpoint,
            "EZCODES_SYNC_ENABLED": "true",
        }
    )
    lines = [f"{key}={value}" for key, value in existing.items()]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mask_token(token: str) -> str:
    if len(token) <= 12:
        return "***"
    return f"{token[:6]}...{token[-6:]}"


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


@router.post("/config/raw")
def configure_ezcodes_from_raw(project_id: int, payload: EzcodesRawConfigRequest, request: Request):
    try:
        credentials = credentials_from_raw_payload(payload.payload)
        sync_manager.configure_credentials(credentials)
        if payload.persist:
            persist_ezcodes_env(credentials)
    except EzcodesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(
        request,
        {
            "project_id": project_id,
            "configured": True,
            "persisted": payload.persist,
            "team_id": credentials.team_id,
            "env_id": credentials.env_id,
            "token": mask_token(credentials.access_token),
            "sync": sync_manager.status(),
        },
    )


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
