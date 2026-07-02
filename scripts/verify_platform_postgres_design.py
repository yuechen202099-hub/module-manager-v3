from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "v2-api"
sys.path.insert(0, str(API_ROOT))

from app.services.platform.postgres_design import build_platform_postgres_persistence_design  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"[FAIL] {message}")


def main() -> None:
    design = build_platform_postgres_persistence_design()
    tables = {table.get("name"): table for table in design.get("tables", [])}

    require(design.get("contract_version") == 1, "contract_version must be 1")
    require(design.get("scope") == "project_config", "scope must be project_config")
    require(design.get("creates_migration") is False, "design package must not create a migration")
    require("requires_user_approval_before_migration" in design.get("safety", []), "migration approval safety missing")

    for table_name in ("platform_project_configs", "platform_project_config_events"):
        require(table_name in tables, f"missing table design: {table_name}")
        table = tables[table_name]
        require(table.get("primary_key") == ["id"], f"{table_name} must use id primary key")
        require(table.get("indexes"), f"{table_name} indexes are required")

    config_columns = {column.get("name"): column for column in tables["platform_project_configs"].get("columns", [])}
    require(config_columns.get("field_schema", {}).get("type") == "jsonb", "field_schema must be jsonb")
    require(config_columns.get("workflow_definition", {}).get("type") == "jsonb", "workflow_definition must be jsonb")
    require(config_columns.get("updated_at", {}).get("type") == "timestamptz", "updated_at must be timestamptz")

    config_indexes = {index.get("name"): index for index in tables["platform_project_configs"].get("indexes", [])}
    require(config_indexes.get("uq_platform_project_configs_team_project_key", {}).get("unique") is True, "team/project unique index missing")
    require(config_indexes.get("ix_platform_project_configs_team_status", {}).get("columns") == ["team_id", "status"], "team/status index missing")

    event_indexes = {index.get("name"): index for index in tables["platform_project_config_events"].get("indexes", [])}
    require(event_indexes.get("ix_platform_project_config_events_config_created", {}).get("columns") == ["config_id", "created_at"], "config event index missing")
    require(event_indexes.get("ix_platform_project_config_events_team_created", {}).get("columns") == ["team_id", "created_at"], "team event index missing")

    migration_text = " ".join(design.get("migration_plan", []))
    rollback_text = " ".join(design.get("rollback_plan", []))
    for token in ("backup", "dry-run", "backfill", "verify", "cutover"):
        require(token in migration_text, f"migration plan missing {token}")
    for token in ("disable_postgres_reads", "json_fallback", "backup_before_drop"):
        require(token in rollback_text, f"rollback plan missing {token}")

    print("[OK] platform postgres persistence design is consistent")


if __name__ == "__main__":
    main()

