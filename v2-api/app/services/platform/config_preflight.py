from __future__ import annotations

import json
from typing import Any

from app.services.platform.catalog import (
    ProjectConfigurationError,
    ProjectValidationError,
    _PROJECT_MODULE_BY_ID,
    _normalize_project_workflow,
    _normalize_work_item_schema,
    _project_draft_store_path,
)


CONFIG_PREFLIGHT_SAFETY = [
    "read_only_no_write",
    "no_project_draft_load",
    "no_database_connection",
    "no_oss_mutation",
    "no_migration_execution",
    "no_production_data_edit",
]


def _issue(
    *,
    scope: str,
    message: str,
    action: str,
    code: str = "validation_error",
    severity: str = "blocker",
) -> dict[str, str]:
    return {
        "scope": scope,
        "code": code,
        "severity": severity,
        "message": message,
        "action": action,
    }


def _raw_project_identity(raw_project: Any, index: int) -> tuple[str, str]:
    if not isinstance(raw_project, dict):
        return f"raw-project-{index}", f"Raw project {index}"
    project_id = str(raw_project.get("id") or "").strip() or f"raw-project-{index}"
    name = str(raw_project.get("name") or "").strip() or project_id
    return project_id, name


def _project_module_ids(raw_project: dict[str, Any]) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    raw_module_ids = raw_project.get("module_ids")
    if not isinstance(raw_module_ids, list):
        return (), [
            _issue(
                scope="module_ids",
                code="missing_module_ids",
                message="Project draft must define module_ids before config load",
                action="fix_module_selection_before_import",
            )
        ]
    module_ids = tuple(
        module_id
        for module_id in (str(raw_module_id or "").strip() for raw_module_id in raw_module_ids)
        if module_id
    )
    if not module_ids:
        issues.append(
            _issue(
                scope="module_ids",
                code="empty_module_ids",
                message="Project draft must define at least one module before config load",
                action="fix_module_selection_before_import",
            )
        )
    unknown_modules = [module_id for module_id in module_ids if module_id not in _PROJECT_MODULE_BY_ID]
    if unknown_modules:
        issues.append(
            _issue(
                scope="module_ids",
                code="unknown_module",
                message=f"Project draft references unknown module: {unknown_modules[0]}",
                action="fix_module_selection_before_import",
            )
        )
    return module_ids, issues


def _preflight_raw_project(raw_project: Any, index: int) -> dict[str, Any]:
    project_id, name = _raw_project_identity(raw_project, index)
    issues: list[dict[str, str]] = []
    if not isinstance(raw_project, dict):
        issues.append(
            _issue(
                scope="project_record",
                code="invalid_project_record",
                message="Project draft record must be an object",
                action="fix_project_record_before_import",
            )
        )
        return {
            "project_id": project_id,
            "name": name,
            "status": "blocked",
            "issue_count": len(issues),
            "issues": issues,
        }

    if not str(raw_project.get("id") or "").strip():
        issues.append(
            _issue(
                scope="project_record",
                code="missing_project_id",
                message="Project draft must define id before config load",
                action="fix_project_record_before_import",
            )
        )
    if not str(raw_project.get("name") or "").strip():
        issues.append(
            _issue(
                scope="project_record",
                code="missing_project_name",
                message="Project draft must define name before config load",
                action="fix_project_record_before_import",
            )
        )

    module_ids, module_issues = _project_module_ids(raw_project)
    issues.extend(module_issues)

    try:
        _normalize_work_item_schema(raw_project.get("work_item_schema"))
    except (ProjectConfigurationError, ProjectValidationError) as exc:
        issues.append(
            _issue(
                scope="field_schema",
                code="field_schema_invalid",
                message=str(exc),
                action="fix_field_schema_before_import",
            )
        )

    if module_ids and not module_issues:
        try:
            _normalize_project_workflow(raw_project.get("workflow"), module_ids=module_ids)
        except (ProjectConfigurationError, ProjectValidationError) as exc:
            issues.append(
                _issue(
                    scope="workflow",
                    code="workflow_invalid",
                    message=str(exc),
                    action="fix_workflow_before_import",
                )
            )

    return {
        "project_id": project_id,
        "name": name,
        "source_status": str(raw_project.get("status") or "draft").strip() or "draft",
        "status": "blocked" if issues else "ready",
        "issue_count": len(issues),
        "issues": issues,
    }


def build_project_config_preflight() -> dict[str, Any]:
    path = _project_draft_store_path()
    store = {
        "id": "project_drafts",
        "backend": "local_json",
        "path": str(path),
        "exists": path.exists(),
        "readable": True,
    }
    store_issues: list[dict[str, str]] = []
    if not path.exists():
        return {
            "preflight_version": 1,
            "ready_for_config_load": True,
            "store": store,
            "summary": {
                "total_projects": 0,
                "ready_projects": 0,
                "blocked_projects": 0,
                "store_issues": 0,
            },
            "issues": [],
            "projects": [],
            "safety": list(CONFIG_PREFLIGHT_SAFETY),
        }

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        store["readable"] = False
        store_issues.append(
            _issue(
                scope="project_draft_store",
                code="store_unreadable",
                message=f"Project draft store is unreadable: {exc}",
                action="fix_project_draft_store_before_import",
            )
        )
        payload = {}

    raw_projects = payload.get("projects") if isinstance(payload, dict) else None
    if store["readable"] and not isinstance(raw_projects, list):
        store_issues.append(
            _issue(
                scope="project_draft_store",
                code="invalid_store_format",
                message="Project draft store must contain a projects list",
                action="fix_project_draft_store_before_import",
            )
        )
        raw_projects = []

    projects = [
        _preflight_raw_project(raw_project, index)
        for index, raw_project in enumerate(raw_projects or [], start=1)
    ]
    blocked_projects = sum(1 for project in projects if project["status"] == "blocked")
    ready_projects = len(projects) - blocked_projects
    ready_for_config_load = not store_issues and blocked_projects == 0
    return {
        "preflight_version": 1,
        "ready_for_config_load": ready_for_config_load,
        "store": store,
        "summary": {
            "total_projects": len(projects),
            "ready_projects": ready_projects,
            "blocked_projects": blocked_projects,
            "store_issues": len(store_issues),
        },
        "issues": store_issues,
        "projects": projects,
        "safety": list(CONFIG_PREFLIGHT_SAFETY),
    }
