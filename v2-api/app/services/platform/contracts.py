from __future__ import annotations

from typing import Any

from app.services.platform.catalog import (
    _PLATFORM_REQUIRED_FIELDS,
    _VALID_CAPTURE_METHODS,
    _VALID_DATA_TYPES,
    _VALID_FIELD_SOURCES,
)
from app.services.platform.config_persistence_contract import PERSISTENCE_CONTRACT_SAFETY
from app.services.platform.templates import SUPPORTED_TEMPLATE_TYPES


FIELD_SCHEMA_KEYS = ["primary_field", "aggregate_field", "construction_fields", "photo_slots"]

CONSTRUCTION_COLLECTION_PAYLOAD_KEYS = [
    "actor",
    "client_batch_id",
    "status",
    "field_values",
    "covered_photo_slots",
]

CONSTRUCTION_WORK_ORDER_PAYLOAD_KEYS = [
    "id",
    "project_id",
    "source_task_id",
    "source_batch_id",
    "primary_value",
    "aggregate_value",
    "field_values",
    "required_fields",
    "photo_slots",
    "collection_photos",
    "collection_status",
    "collection_field_values",
    "kpi_values",
    "covered_photo_slots",
    "client_batch_id",
    "collected_by",
    "collected_at",
    "review_status",
    "reviewed_by",
    "reviewed_at",
    "review_note",
    "review_reason",
    "review_history",
]

REVIEW_STATUS_COUNT_KEYS = ["pending_review", "approved", "returned", "exception", "not_ready"]
REVIEW_ACTIONS = ["approved", "returned", "exception"]

TEMPLATE_REVIEW_HANDOFF = {
    "initial_work_orders": "construction_collection",
    "external_completed": "pending_review",
}

PROJECT_CONFIG_PERSISTENCE_ROUTE = "/projects/{project_id}/persistence/contract"
PROJECT_CONFIG_SOURCE_BACKEND = "local_json_project_draft_store"
PROJECT_CONFIG_TARGET_BACKEND = "postgres_after_approved_migration"
PROJECT_CONFIG_TARGET_TABLES = ["platform_project_configs", "platform_project_config_events"]
PROJECT_CONFIG_RECORD_KEYS = [
    "team_id",
    "project_key",
    "name",
    "status",
    "adapter",
    "module_ids",
    "description",
    "field_schema",
    "workflow_definition",
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
]
PROJECT_CONFIG_ROUNDTRIP_KEYS = ["can_restore", "preserved_keys", "missing_preserved_keys"]
PROJECT_CONFIG_MIGRATION_GATE = [
    "requires_user_approval_before_migration",
    "no_alembic_file_created_in_this_package",
    "no_database_connection",
    "no_production_data_edit",
    "json_fallback_required",
]


def _platform_required_kpi_keys() -> list[str]:
    keys = [
        str(field["key"])
        for field in _PLATFORM_REQUIRED_FIELDS
        if field.get("kpi_enabled") or field.get("required")
    ]
    if "old_device_recovered" not in keys:
        keys.append("old_device_recovered")
    return keys


def build_platform_contract_snapshot() -> dict[str, Any]:
    return {
        "contract_version": 1,
        "template_types": sorted(SUPPORTED_TEMPLATE_TYPES),
        "field_schema": {
            "sources": sorted(_VALID_FIELD_SOURCES),
            "capture_methods": sorted(_VALID_CAPTURE_METHODS),
            "data_types": sorted(_VALID_DATA_TYPES),
            "required_platform_field_keys": [str(field["key"]) for field in _PLATFORM_REQUIRED_FIELDS],
        },
        "construction": {
            "field_schema_keys": list(FIELD_SCHEMA_KEYS),
            "collection_payload_keys": list(CONSTRUCTION_COLLECTION_PAYLOAD_KEYS),
            "work_order_payload_keys": list(CONSTRUCTION_WORK_ORDER_PAYLOAD_KEYS),
            "required_kpi_keys": _platform_required_kpi_keys(),
        },
        "review": {
            "status_count_keys": list(REVIEW_STATUS_COUNT_KEYS),
            "actions": list(REVIEW_ACTIONS),
            "handoff_from_template_types": dict(TEMPLATE_REVIEW_HANDOFF),
        },
        "persistence": {
            "project_config": {
                "route": PROJECT_CONFIG_PERSISTENCE_ROUTE,
                "source_backend": PROJECT_CONFIG_SOURCE_BACKEND,
                "target_backend": PROJECT_CONFIG_TARGET_BACKEND,
                "target_tables": list(PROJECT_CONFIG_TARGET_TABLES),
                "config_record_keys": list(PROJECT_CONFIG_RECORD_KEYS),
                "roundtrip_keys": list(PROJECT_CONFIG_ROUNDTRIP_KEYS),
                "migration_gate": list(PROJECT_CONFIG_MIGRATION_GATE),
                "safety": list(PERSISTENCE_CONTRACT_SAFETY),
            },
        },
        "handoff": {
            "migration": "No database migration. Snapshot only records the current platform contract names.",
            "rollback": "Remove the snapshot module, test, and verification script.",
        },
    }
