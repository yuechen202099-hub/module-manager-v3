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


def _replacement_overview_or_404(project_id: str):
    if project_id != "replacement-project":
        raise HTTPException(status_code=404, detail="Project not found")
    return _replacement_overview()


@router.get("")
def list_projects(request: Request):
    item = _replacement_overview()
    return ok(request, {"total": 1, "items": [item]})


@router.post("")
def create_project(payload: ProjectCreate, request: Request):
    return ok(request, {"id": "draft", "name": payload.name, "description": payload.description, "status": "draft"})


@router.get("/{project_id}/progress")
def get_project_progress(project_id: str, request: Request):
    overview = _replacement_overview_or_404(project_id)
    return ok(
        request,
        {
            "stage": overview["stage"],
            "system_progress": overview["system_progress"],
            "management_progress": overview["management_progress"],
            "management_locked": overview["management_locked"],
        },
    )


@router.get("/{project_id}/delivery")
def get_project_delivery(project_id: str, request: Request):
    overview = _replacement_overview_or_404(project_id)
    return ok(request, overview["delivery"])


@router.get("/{project_id}/field")
def get_project_field(project_id: str, request: Request):
    overview = _replacement_overview_or_404(project_id)
    return ok(request, overview["field"])


@router.get("/{project_id}/review")
def get_project_review(project_id: str, request: Request):
    overview = _replacement_overview_or_404(project_id)
    return ok(request, overview["review"])


@router.get("/{project_id}/risks")
def get_project_risks(project_id: str, request: Request):
    overview = _replacement_overview_or_404(project_id)
    return ok(request, overview["risks"])


@router.get("/{project_id}/tasks")
def get_project_tasks(project_id: str, request: Request):
    overview = _replacement_overview_or_404(project_id)
    return ok(request, overview["tasks"])


@router.get("/{project_id}")
def get_project(project_id: str, request: Request):
    return ok(request, _replacement_overview_or_404(project_id))
