from __future__ import annotations

from fastapi import HTTPException, Request

from app.services.platform.catalog import ProjectNotFound, get_project_definition


DEFAULT_PROJECT_ID = "replacement-project"


def resolve_request_project_id(request: Request) -> str:
    project_id = str(request.query_params.get("project_id") or "").strip() or DEFAULT_PROJECT_ID
    try:
        get_project_definition(project_id)
    except ProjectNotFound as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    request.state.project_id = project_id
    return project_id


def current_request_project_id(request: Request) -> str:
    return str(getattr(request.state, "project_id", "") or DEFAULT_PROJECT_ID)
