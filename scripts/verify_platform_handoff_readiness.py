from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "v2-api"
sys.path.insert(0, str(API_ROOT))

from app.services.platform.handoff_readiness import build_platform_handoff_readiness  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"[FAIL] {message}")


def main() -> None:
    readiness = build_platform_handoff_readiness()
    require(readiness.get("handoff_version") == 1, "handoff version must be 1")
    require(readiness.get("feature_branch") == "pm-platform/project-drafts", "feature branch drifted")
    baseline = readiness.get("production_baseline", {})
    require(baseline.get("branch") == "production/V3/3.0.71", "production branch drifted")
    require(baseline.get("version") == "V3.0.71", "production version drifted")
    require(readiness.get("ready_for_review_package") is True, "review package should be ready")
    require(readiness.get("ready_for_production_migration") is False, "migration must stay blocked")
    require(readiness.get("ready_for_production_release") is False, "release must stay blocked")

    summary = readiness.get("project_readiness_summary", {})
    require(summary.get("readiness_version") == 1, "project readiness summary missing")
    require("items" in summary, "project readiness items missing")

    persistence = readiness.get("persistence", {})
    require(persistence.get("status_version") == 1, "persistence status missing")
    require(
        persistence.get("database", {}).get("used_for_platform_project_config") is False,
        "platform config must not use postgres yet",
    )

    migration = readiness.get("migration", {})
    require(migration.get("readiness_version") == 1, "migration readiness missing")
    require(migration.get("ready_for_migration") is False, "migration readiness must be blocked")
    gate_ids = {item.get("id") for item in migration.get("gate_items", []) if isinstance(item, dict)}
    require("backup" in gate_ids and "approval" in gate_ids, "migration gates missing")

    safety = set(readiness.get("production_safety", []))
    for token in (
        "no_tag",
        "no_deploy",
        "no_official_version_bump",
        "no_production_data_edit",
        "no_oss_mutation",
        "no_postgres_write",
        "requires_pr_or_patch_review",
        "requires_backup_dry_run_rollback_before_migration",
    ):
        require(token in safety, f"safety missing {token}")

    next_actions = set(readiness.get("next_actions", []))
    for token in (
        "prepare_pr_or_patch_handoff",
        "review_against_production_baseline",
        "keep_migration_blocked_until_user_approval",
    ):
        require(token in next_actions, f"next action missing {token}")

    print("[OK] platform handoff readiness summary is consistent")


if __name__ == "__main__":
    main()
