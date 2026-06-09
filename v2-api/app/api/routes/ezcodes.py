from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Request

from app.core.responses import ok
from app.services.ezcodes_sync import (
    EZCODES_ENV_ID,
    EzcodesBackend,
    EzcodesCredentials,
    EzcodesError,
    EzcodesFile,
    build_target_sync_plan,
)

router = APIRouter(prefix="/projects/{project_id}/scan/ezcodes")


class EzcodesCredentialsRequest(BaseModel):
    access_token: str = Field(min_length=1)
    team_id: str = Field(min_length=1)
    env_id: str = EZCODES_ENV_ID


class EzcodesSyncPreviewRequest(BaseModel):
    credentials: EzcodesCredentialsRequest


class NotConfiguredEzcodesBackend:
    def list_files(self, credentials: EzcodesCredentials, parent_id: str) -> list[EzcodesFile]:
        raise EzcodesError("Ezcodes backend transport is not configured.")

    def list_barcodes(self, credentials: EzcodesCredentials, file_id: str) -> list[dict]:
        raise EzcodesError("Ezcodes backend transport is not configured.")

    def get_temp_file_urls(self, credentials: EzcodesCredentials, file_ids: list[str]) -> dict[str, str]:
        raise EzcodesError("Ezcodes backend transport is not configured.")


_backend: EzcodesBackend = NotConfiguredEzcodesBackend()


def set_ezcodes_backend(backend: EzcodesBackend) -> None:
    global _backend
    _backend = backend


@router.post("/preview")
def preview_ezcodes_sync(project_id: int, payload: EzcodesSyncPreviewRequest, request: Request):
    credentials = EzcodesCredentials(
        access_token=payload.credentials.access_token,
        team_id=payload.credentials.team_id,
        env_id=payload.credentials.env_id,
    )
    try:
        plan = build_target_sync_plan(_backend, credentials)
    except EzcodesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, {"project_id": project_id, "plan": plan})
