from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "v2-api"
sys.path.insert(0, str(API_ROOT))

from app.services.platform.migration_readiness import build_platform_migration_readiness  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"[FAIL] {message}")


def main() -> None:
    readiness = build_platform_migration_readiness()
    require(readiness.get("readiness_version") == 1, "readiness_version must be 1")
    require(readiness.get("scope") == "project_config", "scope must be project_config")
    require(readiness.get("ready_for_migration") is False, "migration must remain blocked")
    require(readiness.get("requires_user_approval") is True, "user approval gate missing")
    require(readiness.get("creates_migration") is False, "this package must not create a migration")

    target_tables = set(readiness.get("target_tables", []))
    require("platform_project_configs" in target_tables, "platform_project_configs target missing")
    require("platform_project_config_events" in target_tables, "platform_project_config_events target missing")

    gate_items = {item.get("id"): item for item in readiness.get("gate_items", [])}
    for gate_id in ("backup", "dry_run", "verification", "rollback", "approval", "cutover_flag"):
        item = gate_items.get(gate_id)
        require(item is not None, f"missing gate item: {gate_id}")
        require(item.get("required") is True, f"{gate_id} must be required")
        require(item.get("status") == "blocked", f"{gate_id} must be blocked")

    safety = set(readiness.get("safety", []))
    for token in (
        "read_only_no_write",
        "no_database_connection",
        "no_postgres_schema_change",
        "no_production_data_edit",
        "requires_user_approval_before_migration",
        "json_fallback_required",
    ):
        require(token in safety, f"safety missing {token}")

    migration_text = " ".join(readiness.get("migration_plan", []))
    rollback_text = " ".join(readiness.get("rollback_plan", []))
    for token in ("backup", "dry-run", "backfill", "verify", "cutover"):
        require(token in migration_text, f"migration plan missing {token}")
    for token in ("disable_postgres_reads", "json_fallback", "backup_before_drop"):
        require(token in rollback_text, f"rollback plan missing {token}")

    print("[OK] platform migration readiness gate is consistent")


if __name__ == "__main__":
    main()
