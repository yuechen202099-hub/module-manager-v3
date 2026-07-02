from __future__ import annotations

from typing import Any

from app.services.platform.catalog import (
    ProjectDefinition,
    _normalize_project_workflow,
    _normalize_work_item_schema,
    get_project_definition,
)
from app.services.platform.postgres_design import build_platform_postgres_persistence_design


PERSISTENCE_CONTRACT_SAFETY = [
    "read_only_no_write",
    "no_database_connection",
    "no_postgres_schema_change",
    "json_source_only",
    "requires_user_approval_before_migration",
]


def _workflow_updated_by(workflow: dict[str, Any]) -> str:
    return str(workflow.get("updated_by") or "").strip()


def _workflow_node_ids(workflow: dict[str, Any]) -> list[str]:
    return [
        str(node.get("id") or "")
        for node in workflow.get("nodes", [])
        if isinstance(node, dict) and str(node.get("id") or "").strip()
    ]


def _custom_field_keys(field_schema: dict[str, Any]) -> list[str]:
    return [
        str(field.get("key") or "")
        for field in field_schema.get("custom_fields", [])
        if isinstance(field, dict) and str(field.get("key") or "").strip()
    ]


def build_project_config_record(
    definition: ProjectDefinition,
    *,
    team_id: str = "local",
) -> dict[str, Any]:
    field_schema = _normalize_work_item_schema(definition.work_item_schema)
    workflow = _normalize_project_workflow(definition.workflow, module_ids=definition.module_ids)
    return {
        "team_id": str(team_id or "local").strip() or "local",
        "project_key": definition.id,
        "name": definition.name,
        "status": definition.status,
        "adapter": definition.adapter,
        "module_ids": list(definition.module_ids),
        "description": definition.description,
        "field_schema": field_schema,
        "workflow_definition": workflow,
        "created_at": definition.created_at,
        "updated_at": definition.updated_at or workflow.get("updated_at", ""),
        "created_by": "",
        "updated_by": _workflow_updated_by(workflow),
    }


def restore_project_definition_from_config_record(record: dict[str, Any]) -> ProjectDefinition:
    raw_module_ids = record.get("module_ids")
    module_ids = tuple(
        module_id
        for module_id in (str(raw_module_id or "").strip() for raw_module_id in raw_module_ids or [])
        if module_id
    )
    field_schema = _normalize_work_item_schema(record.get("field_schema"))
    workflow = _normalize_project_workflow(record.get("workflow_definition"), module_ids=module_ids)
    return ProjectDefinition(
        id=str(record.get("project_key") or "").strip(),
        name=str(record.get("name") or "").strip(),
        status=str(record.get("status") or "draft").strip() or "draft",
        adapter=str(record.get("adapter") or "draft").strip() or "draft",
        module_ids=module_ids,
        description=str(record.get("description") or "").strip(),
        created_at=str(record.get("created_at") or "").strip(),
        updated_at=str(record.get("updated_at") or "").strip(),
        work_item_schema=field_schema,
        workflow=workflow,
    )


def _roundtrip_preservation(
    original: ProjectDefinition,
    record: dict[str, Any],
    restored: ProjectDefinition,
) -> dict[str, Any]:
    original_field_schema = _normalize_work_item_schema(original.work_item_schema)
    restored_field_schema = _normalize_work_item_schema(restored.work_item_schema)
    original_workflow = _normalize_project_workflow(original.workflow, module_ids=original.module_ids)
    restored_workflow = _normalize_project_workflow(restored.workflow, module_ids=restored.module_ids)
    checks = {
        "project_key": original.id == restored.id == record.get("project_key"),
        "name": original.name == restored.name == record.get("name"),
        "status": original.status == restored.status == record.get("status"),
        "adapter": original.adapter == restored.adapter == record.get("adapter"),
        "module_ids": list(original.module_ids) == list(restored.module_ids) == record.get("module_ids"),
        "primary_field": original_field_schema["primary_field"]["key"] == restored_field_schema["primary_field"]["key"],
        "aggregate_field": original_field_schema["aggregate_field"]["key"] == restored_field_schema["aggregate_field"]["key"],
        "custom_field_keys": _custom_field_keys(original_field_schema) == _custom_field_keys(restored_field_schema),
        "workflow_node_ids": _workflow_node_ids(original_workflow) == _workflow_node_ids(restored_workflow),
    }
    preserved_keys = [key for key, preserved in checks.items() if preserved]
    missing_preserved_keys = [key for key, preserved in checks.items() if not preserved]
    return {
        "can_restore": not missing_preserved_keys,
        "preserved_keys": preserved_keys,
        "missing_preserved_keys": missing_preserved_keys,
    }


def build_project_config_persistence_contract(
    project_id: str,
    *,
    team_id: str = "local",
) -> dict[str, Any]:
    definition = get_project_definition(project_id)
    record = build_project_config_record(definition, team_id=team_id)
    restored = restore_project_definition_from_config_record(record)
    design = build_platform_postgres_persistence_design()
    target_tables = [str(table.get("name") or "") for table in design.get("tables", [])]
    return {
        "contract_version": 1,
        "project_id": definition.id,
        "source_backend": "local_json_project_draft_store",
        "target_backend": "postgres_after_approved_migration",
        "target_tables": target_tables,
        "config_record": record,
        "roundtrip": _roundtrip_preservation(definition, record, restored),
        "migration_gate": list(design.get("safety", [])),
        "safety": list(PERSISTENCE_CONTRACT_SAFETY),
    }
