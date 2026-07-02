from __future__ import annotations

from app.services.platform.templates import SUPPORTED_TEMPLATE_TYPES
from app.services.platform.contracts import build_platform_contract_snapshot


def test_platform_contract_snapshot_names_shared_backend_contracts() -> None:
    snapshot = build_platform_contract_snapshot()

    assert snapshot["contract_version"] == 1
    assert set(snapshot["template_types"]) == SUPPORTED_TEMPLATE_TYPES

    field_schema = snapshot["field_schema"]
    assert {"import", "field_collection", "review", "system"}.issubset(field_schema["sources"])
    assert {"manual", "scan", "photo", "datetime", "system"}.issubset(field_schema["capture_methods"])
    assert {"text", "number", "datetime", "image", "duration"}.issubset(field_schema["data_types"])

    construction = snapshot["construction"]
    assert construction["field_schema_keys"] == [
        "primary_field",
        "aggregate_field",
        "construction_fields",
        "photo_slots",
    ]
    assert {"installer", "completed_at", "uploaded_at", "photo_count", "old_device_recovered"}.issubset(
        construction["required_kpi_keys"]
    )
    assert {"field_values", "covered_photo_slots", "client_batch_id", "status", "actor"}.issubset(
        construction["collection_payload_keys"]
    )
    assert {"kpi_values", "collection_field_values", "review_status", "review_history"}.issubset(
        construction["work_order_payload_keys"]
    )

    review = snapshot["review"]
    assert review["status_count_keys"] == ["pending_review", "approved", "returned", "exception", "not_ready"]
    assert review["actions"] == ["approved", "returned", "exception"]
    assert review["handoff_from_template_types"] == {
        "initial_work_orders": "construction_collection",
        "external_completed": "pending_review",
    }

    project_config = snapshot["persistence"]["project_config"]
    assert project_config["route"] == "/projects/{project_id}/persistence/contract"
    assert project_config["source_backend"] == "local_json_project_draft_store"
    assert project_config["target_backend"] == "postgres_after_approved_migration"
    assert project_config["target_tables"] == ["platform_project_configs", "platform_project_config_events"]
    assert {"project_key", "field_schema", "workflow_definition"}.issubset(project_config["config_record_keys"])
    assert {"can_restore", "preserved_keys", "missing_preserved_keys"}.issubset(project_config["roundtrip_keys"])
    assert "requires_user_approval_before_migration" in project_config["migration_gate"]
    assert "no_database_connection" in project_config["safety"]
