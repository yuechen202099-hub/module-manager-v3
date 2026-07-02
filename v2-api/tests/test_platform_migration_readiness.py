from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_platform_migration_readiness_gate_is_read_only_and_blocks_cutover() -> None:
    client = TestClient(app)

    response = client.get("/projects/persistence/migration-readiness")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["readiness_version"] == 1
    assert payload["scope"] == "project_config"
    assert payload["ready_for_migration"] is False
    assert payload["requires_user_approval"] is True
    assert payload["creates_migration"] is False
    assert payload["target_tables"] == [
        "platform_project_configs",
        "platform_project_config_events",
    ]

    gate_items = {item["id"]: item for item in payload["gate_items"]}
    assert set(gate_items) >= {
        "backup",
        "dry_run",
        "verification",
        "rollback",
        "approval",
        "cutover_flag",
    }
    assert gate_items["backup"]["required"] is True
    assert gate_items["backup"]["status"] == "blocked"
    assert gate_items["dry_run"]["status"] == "blocked"
    assert gate_items["approval"]["status"] == "blocked"

    safety = set(payload["safety"])
    assert "read_only_no_write" in safety
    assert "no_database_connection" in safety
    assert "no_postgres_schema_change" in safety
    assert "no_production_data_edit" in safety

    migration_plan = " ".join(payload["migration_plan"])
    rollback_plan = " ".join(payload["rollback_plan"])
    for token in ("backup", "dry-run", "backfill", "verify", "cutover"):
        assert token in migration_plan
    for token in ("disable_postgres_reads", "json_fallback", "backup_before_drop"):
        assert token in rollback_plan
