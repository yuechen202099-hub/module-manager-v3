from fastapi import APIRouter, Request

from app.core.responses import ok
from app.schemas.project import ProjectCreate

router = APIRouter(prefix="/projects")


@router.get("")
def list_projects(request: Request):
    return ok(request, {"items": []})


@router.post("")
def create_project(payload: ProjectCreate, request: Request):
    return ok(request, {"id": 0, "name": payload.name, "description": payload.description, "status": "draft"})


@router.get("/{project_id}")
def get_project(project_id: int, request: Request):
    return ok(request, {"id": project_id, "status": "placeholder"})

