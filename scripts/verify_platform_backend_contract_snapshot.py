from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "v2-api"
sys.path.insert(0, str(API_ROOT))

from app.services.platform.contracts import build_platform_contract_snapshot  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"[FAIL] {message}")


def main() -> None:
    snapshot = build_platform_contract_snapshot()

    require(snapshot.get("contract_version") == 1, "contract_version must be 1")
    require(
        set(snapshot.get("template_types", [])) == {"initial_work_orders", "external_completed"},
        "template_types must include initial_work_orders and external_completed",
    )

    field_schema = snapshot.get("field_schema", {})
    require({"import", "field_collection", "review", "system"}.issubset(field_schema.get("sources", [])), "field sources incomplete")
    require({"manual", "scan", "photo", "datetime", "system"}.issubset(field_schema.get("capture_methods", [])), "capture methods incomplete")

    construction = snapshot.get("construction", {})
    require(construction.get("field_schema_keys") == ["primary_field", "aggregate_field", "construction_fields", "photo_slots"], "construction field schema keys drifted")
    require(
        {"installer", "completed_at", "uploaded_at", "photo_count", "old_device_recovered"}.issubset(construction.get("required_kpi_keys", [])),
        "required KPI keys incomplete",
    )
    require(
        {"field_values", "covered_photo_slots", "client_batch_id", "status", "actor"}.issubset(construction.get("collection_payload_keys", [])),
        "construction collection payload keys incomplete",
    )

    review = snapshot.get("review", {})
    require(review.get("status_count_keys") == ["pending_review", "approved", "returned", "exception", "not_ready"], "review status count keys drifted")
    require(review.get("actions") == ["approved", "returned", "exception"], "review actions drifted")
    require(
        review.get("handoff_from_template_types", {}).get("initial_work_orders") == "construction_collection",
        "initial_work_orders handoff must remain construction_collection",
    )
    require(
        review.get("handoff_from_template_types", {}).get("external_completed") == "pending_review",
        "external_completed handoff must remain pending_review",
    )

    project_config = snapshot.get("persistence", {}).get("project_config", {})
    require(
        project_config.get("route") == "/projects/{project_id}/persistence/contract",
        "project config persistence route drifted",
    )
    require(
        project_config.get("source_backend") == "local_json_project_draft_store",
        "project config source backend drifted",
    )
    require(
        project_config.get("target_backend") == "postgres_after_approved_migration",
        "project config target backend drifted",
    )
    require(
        project_config.get("target_tables") == ["platform_project_configs", "platform_project_config_events"],
        "project config target tables drifted",
    )
    require(
        {"project_key", "field_schema", "workflow_definition"}.issubset(project_config.get("config_record_keys", [])),
        "project config record keys incomplete",
    )
    require(
        {"can_restore", "preserved_keys", "missing_preserved_keys"}.issubset(project_config.get("roundtrip_keys", [])),
        "project config roundtrip keys incomplete",
    )
    require(
        "requires_user_approval_before_migration" in project_config.get("migration_gate", []),
        "project config migration approval gate missing",
    )
    require(
        "no_database_connection" in project_config.get("safety", []),
        "project config database safety missing",
    )

    print("[OK] platform backend contract snapshot is consistent")


if __name__ == "__main__":
    main()
