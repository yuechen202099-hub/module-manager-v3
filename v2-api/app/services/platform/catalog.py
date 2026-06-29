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


@dataclass(frozen=True)
class ProjectModuleDefinition:
    id: str
    name: str
    priority: int

    def as_dict(self, project_id: str) -> dict[str, str | int]:
        return {
            "id": self.id,
            "name": self.name,
            "priority": self.priority,
            "endpoint": f"/projects/{project_id}/modules/{self.id}",
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

_PROJECT_MODULES = (
    ProjectModuleDefinition(id="progress", name="项目进度", priority=10),
    ProjectModuleDefinition(id="delivery", name="项目交付能力", priority=20),
    ProjectModuleDefinition(id="field", name="现场施工数据采集", priority=30),
    ProjectModuleDefinition(id="review", name="审阅功能", priority=40),
    ProjectModuleDefinition(id="risks", name="风险预警", priority=50),
    ProjectModuleDefinition(id="tasks", name="任务执行", priority=60),
)

_PROJECT_MODULE_BY_ID = {module.id: module for module in _PROJECT_MODULES}


def list_project_definitions() -> list[dict[str, str]]:
    return [project.as_dict() for project in _PROJECTS]


def list_project_overviews() -> list[dict[str, Any]]:
    return [get_project_overview(project.id) for project in _PROJECTS]


def get_project_definition(project_id: str) -> ProjectDefinition:
    try:
        return _PROJECT_BY_ID[project_id]
    except KeyError as exc:
        raise ProjectNotFound(project_id) from exc


def list_project_modules(project_id: str) -> list[dict[str, str | int]]:
    get_project_definition(project_id)
    return [module.as_dict(project_id) for module in _PROJECT_MODULES]


def get_project_module_definition(project_id: str, module_id: str) -> ProjectModuleDefinition:
    get_project_definition(project_id)
    try:
        return _PROJECT_MODULE_BY_ID[module_id]
    except KeyError as exc:
        raise KeyError(module_id) from exc


def get_project_overview(project_id: str) -> dict[str, Any]:
    definition = get_project_definition(project_id)
    if definition.adapter == "replacement":
        repository = get_state_repository()
        summary_payload = repository.summary()
        task_status = repository.task_status()
        overview = build_replacement_project_overview(
            summary=summary_payload.get("summary", {}),
            task_status=task_status,
        )
        overview["modules"] = list_project_modules(project_id)
        return overview
    raise ProjectNotFound(project_id)


def get_project_section(project_id: str, section: str) -> dict[str, Any]:
    get_project_module_definition(project_id, section)
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
