from __future__ import annotations

from dataclasses import dataclass, replace
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
    workflow: dict[str, Any] | None = None

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

_DEFAULT_WORKFLOW_NODE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "project_setup",
        "type": "setup",
        "label": "项目建立",
        "required": True,
        "module_id": "progress",
        "order": 10,
    },
    {
        "id": "field_schema",
        "type": "configuration",
        "label": "字段配置",
        "required": True,
        "module_id": "field",
        "order": 20,
    },
    {
        "id": "template_import",
        "type": "import",
        "label": "模板导入",
        "required": False,
        "module_id": "tasks",
        "order": 30,
    },
    {
        "id": "work_order_plan",
        "type": "planning",
        "label": "工单计划",
        "required": False,
        "module_id": "tasks",
        "order": 40,
    },
    {
        "id": "construction_collection",
        "type": "field_collection",
        "label": "现场施工采集",
        "required": False,
        "module_id": "field",
        "order": 50,
    },
    {
        "id": "review",
        "type": "review",
        "label": "审阅",
        "required": False,
        "module_id": "review",
        "order": 60,
    },
    {
        "id": "rework",
        "type": "rework",
        "label": "返工",
        "required": False,
        "module_id": "review",
        "order": 70,
    },
    {
        "id": "exception",
        "type": "exception",
        "label": "异常处理",
        "required": False,
        "module_id": "risks",
        "order": 80,
    },
    {
        "id": "delivery_archive",
        "type": "archive",
        "label": "交付归档",
        "required": False,
        "module_id": "delivery",
        "order": 90,
    },
    {
        "id": "delivery_export",
        "type": "export",
        "label": "交付导出",
        "required": False,
        "module_id": "delivery",
        "order": 100,
    },
)

_DEFAULT_WORKFLOW_NODE_BY_ID = {
    str(node["id"]): node for node in _DEFAULT_WORKFLOW_NODE_DEFINITIONS
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _workflow_actor(actor: str | None) -> str:
    return str(actor or "").strip() or "local-admin"


def _normalize_workflow_node(raw_node: Any, *, module_ids: set[str]) -> dict[str, Any]:
    raw = raw_node if isinstance(raw_node, dict) else {}
    node_id = str(raw.get("id") or "").strip()
    if not node_id:
        raise ProjectValidationError("Workflow node id is required")
    default_node = _DEFAULT_WORKFLOW_NODE_BY_ID.get(node_id, {})
    label = str(raw.get("label") or default_node.get("label") or node_id).strip() or node_id
    node_type = str(raw.get("type") or default_node.get("type") or "custom").strip() or "custom"
    module_id = str(raw.get("module_id") or raw.get("moduleId") or default_node.get("module_id") or "").strip()
    required = bool(raw.get("required", default_node.get("required", False)))
    enabled = bool(raw.get("enabled", required or not module_id or module_id in module_ids))
    if required:
        enabled = True
    if module_id and module_id not in _PROJECT_MODULE_BY_ID:
        raise ProjectValidationError(f"Workflow node references unknown module: {module_id}")
    order = raw.get("order", default_node.get("order", 0))
    try:
        normalized_order = int(order)
    except (TypeError, ValueError):
        normalized_order = int(default_node.get("order", 0) or 0)
    config = raw.get("config")
    return {
        "id": node_id,
        "type": node_type,
        "label": label,
        "enabled": enabled,
        "required": required,
        "order": normalized_order,
        "module_id": module_id,
        "config": config if isinstance(config, dict) else {},
    }


def _default_project_workflow(*, module_ids: tuple[str, ...], actor: str | None = None) -> dict[str, Any]:
    enabled_module_ids = set(module_ids)
    nodes = [
        _normalize_workflow_node(node, module_ids=enabled_module_ids)
        for node in _DEFAULT_WORKFLOW_NODE_DEFINITIONS
    ]
    nodes.sort(key=lambda node: (int(node["order"]), str(node["id"])))
    enabled_nodes = [node for node in nodes if node["enabled"]]
    edges = [
        {
            "id": f"{source['id']}__{target['id']}",
            "source": source["id"],
            "target": target["id"],
            "label": "下一步",
        }
        for source, target in zip(enabled_nodes, enabled_nodes[1:])
    ]
    return {
        "version": 1,
        "nodes": nodes,
        "edges": edges,
        "module_sync_enabled": False,
        "updated_at": _now_iso(),
        "updated_by": _workflow_actor(actor),
    }


def _normalize_project_workflow(
    raw_workflow: Any,
    *,
    module_ids: tuple[str, ...],
    actor: str | None = None,
) -> dict[str, Any]:
    if not isinstance(raw_workflow, dict):
        return _default_project_workflow(module_ids=module_ids, actor=actor)
    enabled_module_ids = set(module_ids)
    raw_nodes = raw_workflow.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        return _default_project_workflow(module_ids=module_ids, actor=actor)

    normalized_nodes: list[dict[str, Any]] = []
    seen_node_ids: set[str] = set()
    for raw_node in raw_nodes:
        node = _normalize_workflow_node(raw_node, module_ids=enabled_module_ids)
        if node["id"] in seen_node_ids:
            raise ProjectValidationError(f"Workflow node is duplicated: {node['id']}")
        seen_node_ids.add(node["id"])
        normalized_nodes.append(node)

    for default_node in _DEFAULT_WORKFLOW_NODE_DEFINITIONS:
        default_node_id = str(default_node["id"])
        if default_node_id not in seen_node_ids:
            normalized_nodes.append(_normalize_workflow_node(default_node, module_ids=enabled_module_ids))

    normalized_nodes.sort(key=lambda node: (int(node["order"]), str(node["id"])))
    normalized_node_ids = {node["id"] for node in normalized_nodes}
    raw_edges = raw_workflow.get("edges")
    normalized_edges: list[dict[str, str]] = []
    if isinstance(raw_edges, list):
        for raw_edge in raw_edges:
            if not isinstance(raw_edge, dict):
                continue
            source = str(raw_edge.get("source") or "").strip()
            target = str(raw_edge.get("target") or "").strip()
            if not source or not target:
                continue
            if source not in normalized_node_ids or target not in normalized_node_ids:
                raise ProjectValidationError("Workflow edge references an unknown node")
            normalized_edges.append(
                {
                    "id": str(raw_edge.get("id") or f"{source}__{target}").strip() or f"{source}__{target}",
                    "source": source,
                    "target": target,
                    "label": str(raw_edge.get("label") or "下一步").strip() or "下一步",
                }
            )
    if not normalized_edges:
        enabled_nodes = [node for node in normalized_nodes if node["enabled"]]
        normalized_edges = [
            {
                "id": f"{source['id']}__{target['id']}",
                "source": source["id"],
                "target": target["id"],
                "label": "下一步",
            }
            for source, target in zip(enabled_nodes, enabled_nodes[1:])
        ]
    return {
        "version": int(raw_workflow.get("version") or 1),
        "nodes": normalized_nodes,
        "edges": normalized_edges,
        "module_sync_enabled": bool(raw_workflow.get("module_sync_enabled", False)),
        "updated_at": str(raw_workflow.get("updated_at") or _now_iso()),
        "updated_by": _workflow_actor(str(raw_workflow.get("updated_by") or actor or "")),
    }


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
        "workflow": _normalize_project_workflow(project.workflow, module_ids=project.module_ids),
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
        workflow=_normalize_project_workflow(raw_project.get("workflow"), module_ids=module_ids),
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


def _effective_module_ids_for_project(definition: ProjectDefinition) -> tuple[str, ...]:
    if not isinstance(definition.workflow, dict):
        return definition.module_ids
    workflow = _normalize_project_workflow(definition.workflow, module_ids=definition.module_ids)
    if not workflow.get("module_sync_enabled"):
        return definition.module_ids
    enabled_module_ids = {
        str(node.get("module_id") or "").strip()
        for node in workflow.get("nodes", [])
        if isinstance(node, dict) and bool(node.get("enabled"))
    }
    ordered_module_ids = tuple(
        module.id
        for module in _PROJECT_MODULES
        if module.id in enabled_module_ids
    )
    return ordered_module_ids or definition.module_ids


def _build_workflow_status(definition: ProjectDefinition) -> dict[str, Any]:
    workflow = _normalize_project_workflow(definition.workflow, module_ids=definition.module_ids)
    effective_module_ids = _effective_module_ids_for_project(definition)
    effective_module_id_set = set(effective_module_ids)
    enabled_nodes = [
        node
        for node in workflow.get("nodes", [])
        if isinstance(node, dict)
        and bool(node.get("enabled"))
        and (
            not str(node.get("module_id") or "").strip()
            or str(node.get("module_id") or "").strip() in effective_module_id_set
        )
    ]
    enabled_nodes.sort(key=lambda node: (int(node.get("order", 0)), str(node.get("id") or "")))
    current_node = enabled_nodes[0] if enabled_nodes else None
    return {
        "total_nodes": len(enabled_nodes),
        "enabled_node_ids": [str(node.get("id") or "") for node in enabled_nodes],
        "enabled_node_labels": [str(node.get("label") or node.get("id") or "") for node in enabled_nodes],
        "enabled_module_ids": list(effective_module_ids),
        "current_node_id": str(current_node.get("id") or "") if current_node else "",
        "current_node_label": str(current_node.get("label") or current_node.get("id") or "") if current_node else "",
        "pending_node_ids": [str(node.get("id") or "") for node in enabled_nodes],
        "pending_node_labels": [str(node.get("label") or node.get("id") or "") for node in enabled_nodes],
        "module_sync_enabled": bool(workflow.get("module_sync_enabled")),
    }


def _modules_for_project(definition: ProjectDefinition) -> list[ProjectModuleDefinition]:
    modules = []
    for module_id in _effective_module_ids_for_project(definition):
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
    overview["workflow"] = _normalize_project_workflow(definition.workflow, module_ids=definition.module_ids)
    overview["workflow_status"] = _build_workflow_status(definition)
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
            "initial_work_orders": 0,
            "external_completed": 0,
            "pending_review": 0,
            "returned_rework": 0,
            "approved_archive": 0,
            "not_ready": 0,
            "kpi_ready": 0,
            "photo_total": 0,
            "old_device_recovered": 0,
            "average_online_duration_minutes": 0,
            "installer_count": 0,
            "upload_rate": 0,
            "review_rate": 0,
        },
    }


def _build_draft_project_overview(definition: ProjectDefinition) -> dict[str, Any]:
    sections = _empty_sections()
    from app.services.platform.templates import summarize_platform_work_orders

    work_orders = summarize_platform_work_orders(definition.id)
    total = int(work_orders.get("total", 0))
    completed = int(work_orders.get("completed", 0))
    exceptions = int(work_orders.get("exceptions", 0))
    uploaded = int(work_orders.get("uploaded", 0))
    reviewing = int(work_orders.get("reviewing", 0))
    archived = int(work_orders.get("archived", 0))
    not_ready = int(work_orders.get("not_ready", max(total - uploaded, 0)))
    sections["delivery"]["total_items"] = total
    sections["delivery"]["completed_items"] = completed
    sections["field"]["unconstructed_groups"] = not_ready
    sections["field"]["exception_count"] = exceptions
    sections["review"]["reviewed_groups"] = archived
    sections["review"]["review_rate"] = round((archived / total) * 100, 2) if total else 0
    sections["review"]["pending_groups"] = reviewing
    sections["risks"]["total"] = exceptions + not_ready
    sections["risks"]["field_exceptions"] = exceptions
    sections["risks"]["unconstructed_groups"] = not_ready
    sections["tasks"]["total"] = total
    sections["tasks"]["uploaded"] = uploaded
    sections["tasks"]["reviewing"] = reviewing
    sections["tasks"]["archived"] = archived
    sections["tasks"]["initial_work_orders"] = int(work_orders.get("initial_work_orders", 0))
    sections["tasks"]["external_completed"] = int(work_orders.get("external_completed", 0))
    sections["tasks"]["pending_review"] = int(work_orders.get("pending_review", reviewing))
    sections["tasks"]["returned_rework"] = int(work_orders.get("returned_rework", 0))
    sections["tasks"]["approved_archive"] = int(work_orders.get("approved_archive", archived))
    sections["tasks"]["not_ready"] = not_ready
    sections["tasks"]["kpi_ready"] = int(work_orders.get("kpi_ready", 0))
    sections["tasks"]["photo_total"] = int(work_orders.get("photo_total", 0))
    sections["tasks"]["old_device_recovered"] = int(work_orders.get("old_device_recovered", 0))
    sections["tasks"]["average_online_duration_minutes"] = int(work_orders.get("average_online_duration_minutes", 0))
    sections["tasks"]["installer_count"] = int(work_orders.get("installer_count", 0))
    sections["tasks"]["upload_rate"] = round((uploaded / total) * 100, 2) if total else 0
    sections["tasks"]["review_rate"] = round((archived / uploaded) * 100, 2) if uploaded else 0
    overview: dict[str, Any] = {
        "id": definition.id,
        "name": definition.name,
        "description": definition.description,
        "status": definition.status,
        "total_groups": total,
        "completed_groups": completed,
        "exception_groups": exceptions,
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
            workflow=_default_project_workflow(module_ids=tuple(deduped_module_ids)),
        )
        _save_project_drafts_unlocked()
    return get_project_overview(project_id)


def update_project_work_item_schema(
    project_id: str,
    work_item_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    with _DRAFT_PROJECTS_LOCK:
        _load_project_drafts_unlocked()
        if project_id not in _DRAFT_PROJECTS:
            raise ProjectNotFound(project_id)
        definition = _DRAFT_PROJECTS[project_id]
        _DRAFT_PROJECTS[project_id] = replace(
            definition,
            updated_at=_now_iso(),
            work_item_schema=_normalize_work_item_schema(work_item_schema),
        )
        _save_project_drafts_unlocked()
    return get_project_overview(project_id)


def get_project_workflow(project_id: str) -> dict[str, Any]:
    definition = get_project_definition(project_id)
    return _normalize_project_workflow(definition.workflow, module_ids=definition.module_ids)


def update_project_workflow(
    project_id: str,
    workflow: dict[str, Any] | None,
    *,
    actor: str | None = None,
) -> dict[str, Any]:
    with _DRAFT_PROJECTS_LOCK:
        _load_project_drafts_unlocked()
        if project_id not in _DRAFT_PROJECTS:
            raise ProjectNotFound(project_id)
        definition = _DRAFT_PROJECTS[project_id]
        normalized_workflow = _normalize_project_workflow(
            workflow,
            module_ids=definition.module_ids,
            actor=actor,
        )
        normalized_workflow["updated_at"] = _now_iso()
        normalized_workflow["updated_by"] = _workflow_actor(actor)
        normalized_workflow["module_sync_enabled"] = True
        _DRAFT_PROJECTS[project_id] = replace(
            definition,
            updated_at=normalized_workflow["updated_at"],
            workflow=normalized_workflow,
        )
        _save_project_drafts_unlocked()
    return get_project_workflow(project_id)


def reset_project_workflow(project_id: str, *, actor: str | None = None) -> dict[str, Any]:
    with _DRAFT_PROJECTS_LOCK:
        _load_project_drafts_unlocked()
        if project_id not in _DRAFT_PROJECTS:
            raise ProjectNotFound(project_id)
        definition = _DRAFT_PROJECTS[project_id]
        workflow = _default_project_workflow(module_ids=definition.module_ids, actor=actor)
        workflow["module_sync_enabled"] = False
        _DRAFT_PROJECTS[project_id] = replace(
            definition,
            updated_at=workflow["updated_at"],
            workflow=workflow,
        )
        _save_project_drafts_unlocked()
    return get_project_workflow(project_id)


def reset_project_drafts(*, remove_store: bool = False) -> None:
    global _DRAFT_PROJECTS_LOADED
    with _DRAFT_PROJECTS_LOCK:
        _DRAFT_PROJECTS.clear()
        _DRAFT_PROJECTS_LOADED = False
        if remove_store and _DRAFT_PROJECT_STORE_PATH_OVERRIDE is not None:
            path = _project_draft_store_path()
            if path.exists():
                path.unlink()
