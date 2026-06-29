from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.platform.adapters.replacement import build_replacement_project_overview
from app.services.state_repository import get_state_repository


class ProjectNotFound(KeyError):
    """Raised when a platform project id is not registered."""


@dataclass(frozen=True)
class ProjectDefinition:
    id: str
    name: str
    status: str
    adapter: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "adapter": self.adapter,
        }


_PROJECTS = (
    ProjectDefinition(
        id="replacement-project",
        name="更换模块项目",
        status="active",
        adapter="replacement",
    ),
)

_PROJECT_BY_ID = {project.id: project for project in _PROJECTS}


def list_project_definitions() -> list[dict[str, str]]:
    return [project.as_dict() for project in _PROJECTS]


def list_project_overviews() -> list[dict[str, Any]]:
    return [get_project_overview(project.id) for project in _PROJECTS]


def get_project_definition(project_id: str) -> ProjectDefinition:
    try:
        return _PROJECT_BY_ID[project_id]
    except KeyError as exc:
        raise ProjectNotFound(project_id) from exc


def get_project_overview(project_id: str) -> dict[str, Any]:
    definition = get_project_definition(project_id)
    if definition.adapter == "replacement":
        repository = get_state_repository()
        summary_payload = repository.summary()
        task_status = repository.task_status()
        return build_replacement_project_overview(
            summary=summary_payload.get("summary", {}),
            task_status=task_status,
        )
    raise ProjectNotFound(project_id)


def get_project_section(project_id: str, section: str) -> dict[str, Any]:
    overview = get_project_overview(project_id)
    if section == "progress":
        return {
            "stage": overview["stage"],
            "system_progress": overview["system_progress"],
            "management_progress": overview["management_progress"],
            "management_locked": overview["management_locked"],
        }
    if section in {"delivery", "field", "review", "risks", "tasks"}:
        return overview[section]
    raise KeyError(section)
