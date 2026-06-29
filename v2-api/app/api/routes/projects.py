from fastapi import APIRouter, HTTPException, Request

from app.core.responses import ok
from app.schemas.project import ProjectCreate
from app.services.platform.overview import build_replacement_project_overview
from app.services.state_repository import get_state_repository

router = APIRouter(prefix="/projects")


def _replacement_overview():
    repository = get_state_repository()
    summary_payload = repository.summary()
    task_status = repository.task_status()
    return build_replacement_project_overview(
        summary=summary_payload.get("summary", {}),
        task_status=task_status,
    )


@router.get("")
def list_projects(request: Request):
    item = _replacement_overview()
    return ok(request, {"total": 1, "items": [item]})


@router.post("")
def create_project(payload: ProjectCreate, request: Request):
    return ok(request, {"id": "draft", "name": payload.name, "description": payload.description, "status": "draft"})


@router.get("/{project_id}")
def get_project(project_id: str, request: Request):
    if project_id != "replacement-project":
        raise HTTPException(status_code=404, detail="Project not found")
    return ok(request, _replacement_overview())
