from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

from app.core.config import settings
from app.services.platform.catalog import _project_draft_store_path
from app.services.platform.templates import (
    _import_batches_store_path,
    _platform_photo_storage_root,
    _platform_work_orders_store_path,
    _work_order_tasks_store_path,
)


def _redact_database_url(database_url: str) -> str:
    if not database_url:
        return ""
    try:
        parsed = urlsplit(database_url)
    except ValueError:
        return "configured://****"
    if not parsed.netloc:
        return database_url
    username = parsed.username or ""
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    auth = f"{username}:****@" if username else ""
    redacted = SplitResult(parsed.scheme, f"{auth}{hostname}{port}", parsed.path, parsed.query, parsed.fragment)
    return urlunsplit(redacted)


def _store_status(
    *,
    store_id: str,
    label: str,
    backend: str,
    path: Path,
    contains: list[str],
) -> dict[str, Any]:
    parent = path.parent
    return {
        "id": store_id,
        "label": label,
        "backend": backend,
        "path": str(path),
        "exists": path.exists(),
        "parent": str(parent),
        "parent_exists": parent.exists(),
        "contains": contains,
    }


def build_platform_persistence_status() -> dict[str, Any]:
    database_url = settings.database_url.strip()
    return {
        "status_version": 1,
        "state_backend": settings.state_backend.strip() or "unknown",
        "database": {
            "configured": bool(database_url),
            "url_redacted": _redact_database_url(database_url),
            "used_for_platform_project_config": False,
            "migration_required_for_postgres_platform_config": True,
        },
        "stores": [
            _store_status(
                store_id="project_drafts",
                label="Project drafts, field schemas, and workflow definitions",
                backend="local_json",
                path=_project_draft_store_path(),
                contains=["project_definition", "field_schema", "workflow_definition", "module_selection"],
            ),
            _store_status(
                store_id="import_batches",
                label="Template import batches",
                backend="local_json",
                path=_import_batches_store_path(),
                contains=["template_type", "validation_summary", "batch_rows", "actor"],
            ),
            _store_status(
                store_id="work_order_tasks",
                label="Import work-order task plans",
                backend="local_json",
                path=_work_order_tasks_store_path(),
                contains=["planned_work_orders", "created_work_orders", "rollback_status"],
            ),
            _store_status(
                store_id="platform_work_orders",
                label="Platform construction and review work orders",
                backend="local_json",
                path=_platform_work_orders_store_path(),
                contains=["collection_field_values", "kpi_values", "review_status", "review_history"],
            ),
            _store_status(
                store_id="construction_photos",
                label="Local construction photo files for platform work orders",
                backend="local_files",
                path=_platform_photo_storage_root(),
                contains=["uploaded_collection_photos"],
            ),
        ],
        "guarantees": [
            "field_schema_persisted_for_draft_projects",
            "workflow_definition_persisted_for_draft_projects",
            "template_import_batches_are_rollback_traceable",
            "platform_work_orders_keep_collection_and_review_state",
        ],
        "safety": [
            "status_only_no_write",
            "database_url_redacted",
            "no_oss_mutation",
            "no_postgres_schema_change",
            "no_production_data_edit",
        ],
    }

