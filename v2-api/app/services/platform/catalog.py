from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading
from typing import Any

from app.core.config import settings
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
    work_item_schema: dict[str, Any] | None = None

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
_DRAFT_PROJECTS_LOADED = False
_DRAFT_PROJECT_STORE_PATH_OVERRIDE: Path | None = None
_DRAFT_PROJECTS_LOCK = threading.RLock()

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


_VALID_FIELD_SOURCES = {"import", "field_collection", "review", "system"}
_VALID_CAPTURE_METHODS = {"manual", "scan", "photo", "select", "datetime", "location", "system", "none"}
_VALID_DATA_TYPES = {"text", "number", "datetime", "image", "enum", "duration", "location", "boolean"}

_PLATFORM_REQUIRED_FIELDS: tuple[dict[str, Any], ...] = (
    {"key": "work_order_id", "label": "工单编号", "data_type": "text", "source": "system", "capture_method": "system", "required": True, "kpi_enabled": False},
    {"key": "installer", "label": "安装人员", "data_type": "text", "source": "field_collection", "capture_method": "manual", "required": True, "kpi_enabled": True},
    {"key": "collector", "label": "采集人员", "data_type": "text", "source": "field_collection", "capture_method": "manual", "required": False, "kpi_enabled": True},
    {"key": "dispatcher", "label": "派工人员", "data_type": "text", "source": "system", "capture_method": "system", "required": False, "kpi_enabled": True},
    {"key": "reviewer", "label": "审阅人员", "data_type": "text", "source": "review", "capture_method": "manual", "required": False, "kpi_enabled": True},
    {"key": "dispatched_at", "label": "派工时间", "data_type": "datetime", "source": "system", "capture_method": "system", "required": False, "kpi_enabled": True},
    {"key": "started_at", "label": "安装时间", "data_type": "datetime", "source": "field_collection", "capture_method": "datetime", "required": False, "kpi_enabled": True},
    {"key": "completed_at", "label": "完成时间", "data_type": "datetime", "source": "field_collection", "capture_method": "datetime", "required": True, "kpi_enabled": True},
    {"key": "uploaded_at", "label": "上传时间", "data_type": "datetime", "source": "system", "capture_method": "system", "required": False, "kpi_enabled": True},
    {"key": "reviewed_at", "label": "审阅时间", "data_type": "datetime", "source": "review", "capture_method": "datetime", "required": False, "kpi_enabled": True},
    {"key": "online_duration_minutes", "label": "在线时长（分钟）", "data_type": "duration", "source": "system", "capture_method": "system", "required": False, "kpi_enabled": True},
    {"key": "location", "label": "现场位置", "data_type": "location", "source": "field_collection", "capture_method": "location", "required": False, "kpi_enabled": False},
    {"key": "photo_count", "label": "照片数量", "data_type": "number", "source": "system", "capture_method": "system", "required": True, "kpi_enabled": True},
    {"key": "scan_count", "label": "扫码次数", "data_type": "number", "source": "system", "capture_method": "system", "required": False, "kpi_enabled": True},
    {"key": "manual_input_count", "label": "手工录入次数", "data_type": "number", "source": "system", "capture_method": "system", "required": False, "kpi_enabled": True},
    {"key": "exception_status", "label": "异常状态", "data_type": "enum", "source": "review", "capture_method": "select", "required": False, "kpi_enabled": True, "options": ["正常", "异常", "已闭环"]},
)

_DEFAULT_DASHBOARD_METRICS: tuple[dict[str, str], ...] = (
    {"key": "total_work_orders", "label": "工单总数"},
    {"key": "collected_work_orders", "label": "已采集工单"},
    {"key": "completed_work_orders", "label": "已完成工单"},
    {"key": "exception_work_orders", "label": "异常工单"},
    {"key": "average_online_duration", "label": "平均在线时长"},
    {"key": "average_completion_duration", "label": "平均完工时长"},
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_draft_store_path() -> Path:
    if _DRAFT_PROJECT_STORE_PATH_OVERRIDE is not None:
        return _DRAFT_PROJECT_STORE_PATH_OVERRIDE
    configured = settings.platform_project_drafts_path.strip()
    if configured:
        return Path(configured)
    return Path.cwd() / "data" / "platform-project-drafts.json"


def configure_project_draft_store_path(path: Path | str | None) -> None:
    global _DRAFT_PROJECTS_LOADED, _DRAFT_PROJECT_STORE_PATH_OVERRIDE
    with _DRAFT_PROJECTS_LOCK:
        _DRAFT_PROJECT_STORE_PATH_OVERRIDE = Path(path) if path is not None else None
        _DRAFT_PROJECTS.clear()
        _DRAFT_PROJECTS_LOADED = False


def _project_definition_to_store(project: ProjectDefinition) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "status": project.status,
        "adapter": project.adapter,
        "module_ids": list(project.module_ids),
        "description": project.description,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "work_item_schema": _normalize_work_item_schema(project.work_item_schema),
    }


def _project_definition_from_store(raw_project: Any) -> ProjectDefinition | None:
    if not isinstance(raw_project, dict):
        return None
    project_id = str(raw_project.get("id") or "").strip()
    name = str(raw_project.get("name") or "").strip()
    if not project_id or not name:
        return None
    raw_module_ids = raw_project.get("module_ids")
    if not isinstance(raw_module_ids, list):
        raise ProjectConfigurationError(f"Project {project_id} must define module_ids")
    module_ids = tuple(
        module_id
        for module_id in (str(raw_module_id or "").strip() for raw_module_id in raw_module_ids)
        if module_id
    )
    if not module_ids:
        raise ProjectConfigurationError(f"Project {project_id} must define at least one module")
    unknown_modules = [module_id for module_id in module_ids if module_id not in _PROJECT_MODULE_BY_ID]
    if unknown_modules:
        raise ProjectConfigurationError(
            f"Project {project_id} references unknown module {unknown_modules[0]}"
        )
    return ProjectDefinition(
        id=project_id,
        name=name,
        status=str(raw_project.get("status") or "draft").strip() or "draft",
        adapter="draft",
        module_ids=module_ids,
        description=str(raw_project.get("description") or "").strip(),
        created_at=str(raw_project.get("created_at") or "").strip(),
        updated_at=str(raw_project.get("updated_at") or "").strip(),
        work_item_schema=_normalize_work_item_schema(raw_project.get("work_item_schema")),
    )


def _load_project_drafts_unlocked() -> None:
    global _DRAFT_PROJECTS_LOADED
    if _DRAFT_PROJECTS_LOADED:
        return
    path = _project_draft_store_path()
    if not path.exists():
        _DRAFT_PROJECTS_LOADED = True
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectConfigurationError(f"Project draft store is unreadable: {path}") from exc
    raw_projects = payload.get("projects") if isinstance(payload, dict) else None
    if not isinstance(raw_projects, list):
        raise ProjectConfigurationError(f"Project draft store has invalid format: {path}")
    loaded_projects: dict[str, ProjectDefinition] = {}
    for raw_project in raw_projects:
        project = _project_definition_from_store(raw_project)
        if project is not None:
            loaded_projects[project.id] = project
    _DRAFT_PROJECTS.clear()
    _DRAFT_PROJECTS.update(loaded_projects)
    _DRAFT_PROJECTS_LOADED = True


def _save_project_drafts_unlocked() -> None:
    path = _project_draft_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "updated_at": _now_iso(),
        "projects": [
            _project_definition_to_store(_DRAFT_PROJECTS[project_id])
            for project_id in sorted(_DRAFT_PROJECTS)
        ],
    }
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _slugify_project_name(name: str) -> str:
    normalized = re.sub(r"\s+", " ", name.strip())
    if normalized in _PINYIN_SLUGS:
        return _PINYIN_SLUGS[normalized]
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    if ascii_slug:
        return ascii_slug
    return "draft-project"


def _slugify_field_key(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)
    return slug or fallback


def _normalize_field_definition(
    raw_field: Any,
    *,
    fallback_key: str,
    fallback_label: str,
    default_source: str,
    default_capture_method: str,
    default_required: bool,
    default_kpi_enabled: bool = False,
) -> dict[str, Any]:
    raw = raw_field if isinstance(raw_field, dict) else {}
    label = str(raw.get("label") or fallback_label).strip() or fallback_label
    key = _slugify_field_key(str(raw.get("key") or label), fallback_key)
    data_type = str(raw.get("data_type") or "text").strip()
    source = str(raw.get("source") or default_source).strip()
    capture_method = str(raw.get("capture_method") or default_capture_method).strip()
    if data_type not in _VALID_DATA_TYPES:
        raise ProjectValidationError(f"Unsupported field data type: {data_type}")
    if source not in _VALID_FIELD_SOURCES:
        raise ProjectValidationError(f"Unsupported field source: {source}")
    if capture_method not in _VALID_CAPTURE_METHODS:
        raise ProjectValidationError(f"Unsupported capture method: {capture_method}")
    field = {
        "key": key,
        "label": label,
        "data_type": data_type,
        "source": source,
        "capture_method": capture_method,
        "required": bool(raw.get("required", default_required)),
        "kpi_enabled": bool(raw.get("kpi_enabled", default_kpi_enabled)),
    }
    parent_key = str(raw.get("parent_key") or "").strip()
    if parent_key:
        field["parent_key"] = _slugify_field_key(parent_key, parent_key)
    options = raw.get("options")
    if isinstance(options, list):
        clean_options = [str(option).strip() for option in options if str(option).strip()]
        if clean_options:
            field["options"] = clean_options
    return field


def _platform_required_fields() -> list[dict[str, Any]]:
    return [
        _normalize_field_definition(
            field,
            fallback_key=str(field["key"]),
            fallback_label=str(field["label"]),
            default_source=str(field["source"]),
            default_capture_method=str(field["capture_method"]),
            default_required=bool(field["required"]),
            default_kpi_enabled=bool(field["kpi_enabled"]),
        )
        for field in _PLATFORM_REQUIRED_FIELDS
    ]


def _default_work_item_schema() -> dict[str, Any]:
    return _normalize_work_item_schema(None)


def _normalize_work_item_schema(raw_schema: Any) -> dict[str, Any]:
    raw = raw_schema if isinstance(raw_schema, dict) else {}
    primary_field = _normalize_field_definition(
        raw.get("primary_field"),
        fallback_key="work_item",
        fallback_label="工单对象",
        default_source="import",
        default_capture_method="manual",
        default_required=True,
    )
    aggregate_field = _normalize_field_definition(
        raw.get("aggregate_field"),
        fallback_key="work_order_group",
        fallback_label="聚合对象",
        default_source="import",
        default_capture_method="manual",
        default_required=True,
    )
    reserved_keys = {primary_field["key"], aggregate_field["key"]}
    reserved_keys.update(field["key"] for field in _PLATFORM_REQUIRED_FIELDS)
    custom_fields: list[dict[str, Any]] = []
    for raw_field in raw.get("custom_fields", []) if isinstance(raw.get("custom_fields"), list) else []:
        field = _normalize_field_definition(
            raw_field,
            fallback_key=f"custom_field_{len(custom_fields) + 1}",
            fallback_label=f"子字段 {len(custom_fields) + 1}",
            default_source="field_collection",
            default_capture_method="manual",
            default_required=False,
        )
        if field["key"] in reserved_keys:
            raise ProjectValidationError(f"Field key is reserved or duplicated: {field['key']}")
        reserved_keys.add(field["key"])
        custom_fields.append(field)
    return {
        "schema_version": 1,
        "primary_field": primary_field,
        "aggregate_field": aggregate_field,
        "platform_required_fields": _platform_required_fields(),
        "custom_fields": custom_fields,
        "dashboard_metrics": [dict(metric) for metric in _DEFAULT_DASHBOARD_METRICS],
    }


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
    overview["work_item_schema"] = _normalize_work_item_schema(definition.work_item_schema)
    if "progress" not in enabled_module_ids:
        for key in _PROJECT_PROGRESS_KEYS:
            overview.pop(key, None)
    for module_id, section_key in _PROJECT_SECTION_KEYS.items():
        if module_id not in enabled_module_ids:
            overview.pop(section_key, None)
    return overview


def list_project_definitions() -> list[dict[str, str]]:
    with _DRAFT_PROJECTS_LOCK:
        _load_project_drafts_unlocked()
        draft_projects = list(_DRAFT_PROJECTS.values())
    return [project.as_dict() for project in _PROJECTS] + [
        project.as_dict() for project in draft_projects
    ]


def list_project_overviews() -> list[dict[str, Any]]:
    with _DRAFT_PROJECTS_LOCK:
        _load_project_drafts_unlocked()
        project_ids = [project.id for project in _PROJECTS] + list(_DRAFT_PROJECTS)
    return [get_project_overview(project_id) for project_id in project_ids]


def get_project_definition(project_id: str) -> ProjectDefinition:
    if project_id in _PROJECT_BY_ID:
        return _PROJECT_BY_ID[project_id]
    with _DRAFT_PROJECTS_LOCK:
        _load_project_drafts_unlocked()
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


def create_project_draft(
    *,
    name: str,
    description: str = "",
    module_ids: list[str],
    work_item_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with _DRAFT_PROJECTS_LOCK:
        _load_project_drafts_unlocked()
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
        normalized_work_item_schema = _normalize_work_item_schema(work_item_schema)
        _DRAFT_PROJECTS[project_id] = ProjectDefinition(
            id=project_id,
            name=normalized_name,
            status="draft",
            adapter="draft",
            module_ids=tuple(deduped_module_ids),
            description=description.strip(),
            created_at=now,
            updated_at=now,
            work_item_schema=normalized_work_item_schema,
        )
        _save_project_drafts_unlocked()
    return get_project_overview(project_id)


def reset_project_drafts(*, remove_store: bool = False) -> None:
    global _DRAFT_PROJECTS_LOADED
    with _DRAFT_PROJECTS_LOCK:
        _DRAFT_PROJECTS.clear()
        _DRAFT_PROJECTS_LOADED = False
        if remove_store and _DRAFT_PROJECT_STORE_PATH_OVERRIDE is not None:
            path = _project_draft_store_path()
            if path.exists():
                path.unlink()
