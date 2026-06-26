from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.responses import ok
from app.api.routes.auth import require_admin
from app.schemas.review import ExceptionCreate, GroupReviewUpdate
from app.services import local_simulation
from app.services.state_repository import StateBackendNotReady, get_state_repository

router = APIRouter(prefix="/groups")


def state_repository():
    try:
        return get_state_repository()
    except StateBackendNotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/search")
def search_groups(
    request: Request,
    admin_payload: dict = Depends(require_admin),
    query: str = "",
    terminal: str = "",
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    if not query.strip() and not terminal.strip():
        return ok(request, {"total": 0, "terminals": [], "items": []})
    team_id = str(admin_payload.get("team_id") or "").strip()
    token = local_simulation.set_current_team(team_id)
    try:
        result = state_repository().search_group_targets(query=query, terminal=terminal, limit=limit, offset=offset)
    finally:
        local_simulation.reset_current_team(token)
    return ok(request, result)


@router.get("/{group_id}")
def get_group(group_id: int, request: Request):
    return ok(request, {"id": group_id, "status": "placeholder", "photos": []})


@router.patch("/{group_id}/review")
def update_group_review(group_id: int, payload: GroupReviewUpdate, request: Request):
    return ok(request, {"group_id": group_id, "status": payload.status, "comment": payload.comment})


@router.post("/{group_id}/exceptions")
def create_exception(group_id: int, payload: ExceptionCreate, request: Request):
    return ok(request, {"group_id": group_id, "kind": payload.kind, "description": payload.description, "status": "open"})


@router.post("/{group_id}/photos/sign-upload")
def sign_photo_upload(group_id: int, request: Request):
    return ok(request, {"group_id": group_id, "upload_url": "", "object_key": ""})


@router.post("/{group_id}/photos/complete-upload")
def complete_photo_upload(group_id: int, request: Request):
    return ok(request, {"group_id": group_id, "status": "completed"})

