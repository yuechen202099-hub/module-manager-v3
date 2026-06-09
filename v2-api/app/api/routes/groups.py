from fastapi import APIRouter, Request

from app.core.responses import ok
from app.schemas.review import ExceptionCreate, GroupReviewUpdate

router = APIRouter(prefix="/groups")


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

