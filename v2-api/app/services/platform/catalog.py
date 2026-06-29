from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.platform.adapters.replacement import build_replacement_project_overview
from app.services.state_repository import get_state_repository


class ProjectNotFound(KeyError):
    """Raised when a platform project id is not registered."""


class ProjectConfigurationError(RuntimeError):
    """Raised when a registered platform project has an invalid definition."""


@dataclass(frozen=True)
class ProjectDefinition:
    id: str
    name: str
    status: str
    adapter: str
    module_ids: tuple[str, ...]

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
    route_path: str

    def as_dict(self, project_id: str) -> dict[str, str | int]:
        return {
            "id": self.id,
            "name": self.name,
            "priority": self.priority,
            "endpoint": f"/projects/{project_id}/modules/{self.id}",
            "route_path": self.route_path,
        }


_PROJECTS = (
    ProjectDefinition(
        id="replacement-project",
        name="更换模块项目",
        status="active",
        adapter="replacement",
        module_ids=("progress", "delivery", "field", "review", "risks", "tasks"),
    ),
)

_PROJECT_BY_ID = {project.id: project for project in _PROJECTS}

_PROJECT_MODULES = (
    ProjectModuleDefinition(id="progress", name="项目进度", priority=10, route_path="/project-board"),
    ProjectModuleDefinition(id="delivery", name="项目交付能力", priority=20, route_path="/project-board"),
    ProjectModuleDefinition(id="field", name="现场施工数据采集", priority=30, route_path="/construction"),
    ProjectModuleDefinition(id="review", name="审阅功能", priority=40, route_path="/task-hall"),
    ProjectModuleDefinition(id="risks", name="风险预警", priority=50, route_path="/project-board"),
    ProjectModuleDefinition(id="tasks", name="任务执行", priority=60, route_path="/claim-tasks"),
)

_PROJECT_MODULE_BY_ID = {module.id: module for module in _PROJECT_MODULES}

_PROJECT_SECTION_KEYS = {
    "delivery": "delivery",
    "field": "field",
    "review": "review",
    "risks": "risks",
    "tasks": "tasks",
}

_PROJECT_PROGRESS_KEYS = ("stage", "system_progress", "management_progress", "management_locked")


def _modules_for_project(definition: ProjectDefinition) -> list[ProjectModuleDefinition]:
    modules = []
    for module_id in definition.module_ids:
        try:
            modules.append(_PROJECT_MODULE_BY_ID[module_id])
        except KeyError as exc:
            raise ProjectConfigurationError(
                f"Project {definition.id} references unknown module {module_id}"
            ) from exc
    return sorted(modules, key=lambda module: module.priority)


def _apply_project_definition(overview: dict[str, Any], definition: ProjectDefinition) -> dict[str, Any]:
    modules = _modules_for_project(definition)
    enabled_module_ids = {module.id for module in modules}
    overview["id"] = definition.id
    overview["name"] = definition.name
    overview["status"] = definition.status
    overview["modules"] = [module.as_dict(definition.id) for module in modules]
    if "progress" not in enabled_module_ids:
        for key in _PROJECT_PROGRESS_KEYS:
            overview.pop(key, None)
    for module_id, section_key in _PROJECT_SECTION_KEYS.items():
        if module_id not in enabled_module_ids:
            overview.pop(section_key, None)
    return overview


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
    definition = get_project_definition(project_id)
    return [module.as_dict(project_id) for module in _modules_for_project(definition)]


def get_project_module_definition(project_id: str, module_id: str) -> ProjectModuleDefinition:
    definition = get_project_definition(project_id)
    module_by_id = {module.id: module for module in _modules_for_project(definition)}
    try:
        return module_by_id[module_id]
    except KeyError:
        raise KeyError(module_id)


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
        return _apply_project_definition(overview, definition)
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
