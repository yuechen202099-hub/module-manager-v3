from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Request

from app.core.responses import ok
from app.services.ezcodes_sync import (
    EZCODES_ENV_ID,
    EzcodesBackend,
    EzcodesCloudBaseBackend,
    EzcodesCredentials,
    EzcodesError,
    build_target_sync_plan,
)

router = APIRouter(prefix="/projects/{project_id}/scan/ezcodes")


class EzcodesCredentialsRequest(BaseModel):
    access_token: str = Field(min_length=1)
    team_id: str = Field(min_length=1)
    env_id: str = EZCODES_ENV_ID
    endpoint: str | None = None


class EzcodesSyncPreviewRequest(BaseModel):
    credentials: EzcodesCredentialsRequest


_backend: EzcodesBackend = EzcodesCloudBaseBackend()


def set_ezcodes_backend(backend: EzcodesBackend) -> None:
    global _backend
    _backend = backend


@router.post("/preview")
def preview_ezcodes_sync(project_id: int, payload: EzcodesSyncPreviewRequest, request: Request):
    credential_kwargs = {
        "access_token": payload.credentials.access_token,
        "team_id": payload.credentials.team_id,
        "env_id": payload.credentials.env_id,
    }
    if payload.credentials.endpoint:
        credential_kwargs["endpoint"] = payload.credentials.endpoint
    credentials = EzcodesCredentials(**credential_kwargs)
    try:
        plan = build_target_sync_plan(_backend, credentials)
    except EzcodesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, {"project_id": project_id, "plan": plan})
