from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any

from app.services.platform.adapters.replacement import build_replacement_project_overview
from app.services.state_repository import get_state_repository


class ProjectNotFound(KeyError):
    """Raised when a platform project id is not registered."""


class ProjectConfigurationError(RuntimeError):
    """Raised when a registered platform project has an invalid definition."""


class ProjectValidationError(ValueError):
    """Raised when a project draft request is invalid."""


@dataclass(frozen=True)
class ProjectDefinition:
    id: str
    name: str
    status: str
    adapter: str
    module_ids: tuple[str, ...]
    description: str = ""
    created_at: str = ""
    updated_at: str = ""

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

_DRAFT_PROJECTS: dict[str, ProjectDefinition] = {}

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

_PINYIN_SLUGS = {
    "线路巡检项目": "xian-lu-xun-jian-xiang-mu",
    "审阅专项": "shen-yue-zhuan-xiang",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify_project_name(name: str) -> str:
    normalized = re.sub(r"\s+", " ", name.strip())
    if normalized in _PINYIN_SLUGS:
        return _PINYIN_SLUGS[normalized]
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    if ascii_slug:
        return ascii_slug
    return "draft-project"


def _unique_project_id(base_id: str) -> str:
    existing_ids = {project.id for project in _PROJECTS} | set(_DRAFT_PROJECTS)
    if base_id not in existing_ids:
        return base_id
    index = 2
    while f"{base_id}-{index}" in existing_ids:
        index += 1
    return f"{base_id}-{index}"


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
    return [project.as_dict() for project in _PROJECTS] + [
        project.as_dict() for project in _DRAFT_PROJECTS.values()
    ]


def list_project_overviews() -> list[dict[str, Any]]:
    project_ids = [project.id for project in _PROJECTS] + list(_DRAFT_PROJECTS)
    return [get_project_overview(project_id) for project_id in project_ids]


def get_project_definition(project_id: str) -> ProjectDefinition:
    if project_id in _PROJECT_BY_ID:
        return _PROJECT_BY_ID[project_id]
    if project_id in _DRAFT_PROJECTS:
        return _DRAFT_PROJECTS[project_id]
    raise ProjectNotFound(project_id)


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
    if definition.adapter == "draft":
        return _build_draft_project_overview(definition)
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
    if get_project_definition(project_id).adapter == "draft":
        return _empty_sections()[section]
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


def _empty_sections() -> dict[str, dict[str, Any]]:
    return {
        "progress": {
            "stage": "准备中",
            "system_progress": 0,
            "management_progress": 0,
            "management_locked": False,
        },
        "delivery": {
            "status": "preparing",
            "total_items": 0,
            "completed_items": 0,
            "latest_record": "",
        },
        "field": {
            "photo_rows_linked": 0,
            "unconstructed_groups": 0,
            "exception_count": 0,
        },
        "review": {
            "reviewed_groups": 0,
            "review_rate": 0,
            "pending_groups": 0,
        },
        "risks": {
            "total": 0,
            "field_exceptions": 0,
            "unconstructed_groups": 0,
            "delivery_blockers": 0,
        },
        "tasks": {
            "total": 0,
            "uploaded": 0,
            "reviewing": 0,
            "archived": 0,
            "upload_rate": 0,
            "review_rate": 0,
        },
    }


def _build_draft_project_overview(definition: ProjectDefinition) -> dict[str, Any]:
    sections = _empty_sections()
    overview: dict[str, Any] = {
        "id": definition.id,
        "name": definition.name,
        "description": definition.description,
        "status": definition.status,
        "total_groups": 0,
        "completed_groups": 0,
        "exception_groups": 0,
        "updated_at": definition.updated_at or definition.created_at,
    }
    overview.update(sections["progress"])
    for section_id in ("delivery", "field", "review", "risks", "tasks"):
        overview[section_id] = sections[section_id]
    return _apply_project_definition(overview, definition)


def create_project_draft(*, name: str, description: str = "", module_ids: list[str]) -> dict[str, Any]:
    normalized_name = re.sub(r"\s+", " ", name.strip())
    if not normalized_name:
        raise ProjectValidationError("Project name is required")
    deduped_module_ids = list(dict.fromkeys(module_id.strip() for module_id in module_ids if module_id.strip()))
    if not deduped_module_ids:
        raise ProjectValidationError("At least one project module is required")
    unknown_modules = [module_id for module_id in deduped_module_ids if module_id not in _PROJECT_MODULE_BY_ID]
    if unknown_modules:
        raise ProjectValidationError(f"Unknown project module: {unknown_modules[0]}")
    now = _now_iso()
    project_id = _unique_project_id(_slugify_project_name(normalized_name))
    _DRAFT_PROJECTS[project_id] = ProjectDefinition(
        id=project_id,
        name=normalized_name,
        status="draft",
        adapter="draft",
        module_ids=tuple(deduped_module_ids),
        description=description.strip(),
        created_at=now,
        updated_at=now,
    )
    return get_project_overview(project_id)


def reset_project_drafts() -> None:
    _DRAFT_PROJECTS.clear()
