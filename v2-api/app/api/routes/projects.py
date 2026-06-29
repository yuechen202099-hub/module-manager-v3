from fastapi import APIRouter, HTTPException, Request

from app.core.responses import ok
from app.schemas.project import ProjectCreate
from app.services.platform.catalog import (
    ProjectConfigurationError,
    ProjectNotFound,
    ProjectValidationError,
    create_project_draft,
    get_project_overview,
    get_project_section,
    list_project_modules,
    list_project_overviews,
)

router = APIRouter(prefix="/projects")


def _project_overview_or_404(project_id: str):
    try:
        return get_project_overview(project_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")


def _project_section_or_404(project_id: str, section: str):
    try:
        return get_project_section(project_id, section)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    except KeyError:
        raise HTTPException(status_code=404, detail="Project section not found")


@router.get("")
def list_projects(request: Request):
    try:
        items = list_project_overviews()
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, {"total": len(items), "items": items})


@router.post("")
def create_project(payload: ProjectCreate, request: Request):
    try:
        project = create_project_draft(
            name=payload.name,
            description=payload.description or "",
            module_ids=payload.module_ids,
        )
    except ProjectValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, project)


@router.get("/{project_id}/progress")
def get_project_progress(project_id: str, request: Request):
    return ok(request, _project_section_or_404(project_id, "progress"))


@router.get("/{project_id}/delivery")
def get_project_delivery(project_id: str, request: Request):
    return ok(request, _project_section_or_404(project_id, "delivery"))


@router.get("/{project_id}/field")
def get_project_field(project_id: str, request: Request):
    return ok(request, _project_section_or_404(project_id, "field"))


@router.get("/{project_id}/review")
def get_project_review(project_id: str, request: Request):
    return ok(request, _project_section_or_404(project_id, "review"))


@router.get("/{project_id}/risks")
def get_project_risks(project_id: str, request: Request):
    return ok(request, _project_section_or_404(project_id, "risks"))


@router.get("/{project_id}/tasks")
def get_project_tasks(project_id: str, request: Request):
    return ok(request, _project_section_or_404(project_id, "tasks"))


@router.get("/{project_id}/modules")
def list_project_module_definitions(project_id: str, request: Request):
    try:
        items = list_project_modules(project_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, {"project_id": project_id, "total": len(items), "items": items})


@router.get("/{project_id}/modules/{module_id}")
def get_project_module(project_id: str, module_id: str, request: Request):
    return ok(request, _project_section_or_404(project_id, module_id))


@router.get("/{project_id}")
def get_project(project_id: str, request: Request):
    return ok(request, _project_overview_or_404(project_id))
