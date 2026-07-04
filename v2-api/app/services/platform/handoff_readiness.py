from __future__ import annotations

from typing import Any

from app.services.platform.config_preflight import build_project_config_preflight
from app.services.platform.migration_readiness import build_platform_migration_readiness
from app.services.platform.persistence import build_platform_persistence_status
from app.services.platform.readiness import build_project_readiness_summary


PRODUCTION_BASELINE = {
    "branch": "production/V3/3.0.77",
    "version": "V3.0.77",
}
FEATURE_BRANCH = "pm-platform/production-3.0.77-sync"


def _blocked_project_readiness_summary(config_preflight: dict[str, Any]) -> dict[str, Any]:
    summary = config_preflight.get("summary") if isinstance(config_preflight.get("summary"), dict) else {}
    blocked_projects = int(summary.get("blocked_projects") or 0)
    store_issues = int(summary.get("store_issues") or 0)
    blocker_count = max(1, blocked_projects + store_issues)
    return {
        "readiness_version": 1,
        "total": int(summary.get("total_projects") or 0),
        "ready": int(summary.get("ready_projects") or 0),
        "not_ready": blocker_count,
        "action_counts": [
            {
                "action": "fix_config_preflight_blockers",
                "count": blocker_count,
            }
        ],
        "items": [],
        "safety": [
            "config_preflight_blocks_project_load",
            "read_only_no_write",
            "no_database_connection",
            "no_production_data_edit",
        ],
    }


def build_platform_handoff_readiness() -> dict[str, Any]:
    config_preflight = build_project_config_preflight()
    config_preflight_ready = bool(config_preflight.get("ready_for_config_load"))
    if config_preflight_ready:
        project_readiness_summary = build_project_readiness_summary()
    else:
        project_readiness_summary = _blocked_project_readiness_summary(config_preflight)
    persistence_status = build_platform_persistence_status()
    migration_readiness = build_platform_migration_readiness()
    next_actions = [
        "prepare_pr_or_patch_handoff",
        "review_against_production_baseline",
        "keep_migration_blocked_until_user_approval",
        "run_browser_smoke_before_handoff",
    ]
    if not config_preflight_ready:
        next_actions.insert(0, "fix_config_preflight_blockers")
    return {
        "handoff_version": 1,
        "feature_branch": FEATURE_BRANCH,
        "production_baseline": PRODUCTION_BASELINE,
        "ready_for_review_package": config_preflight_ready,
        "ready_for_production_migration": False,
        "ready_for_production_release": False,
        "config_preflight": config_preflight,
        "project_readiness_summary": project_readiness_summary,
        "persistence": persistence_status,
        "migration": migration_readiness,
        "production_safety": [
            "no_tag",
            "no_deploy",
            "no_official_version_bump",
            "no_production_data_edit",
            "no_oss_mutation",
            "no_postgres_write",
            "requires_pr_or_patch_review",
            "requires_backup_dry_run_rollback_before_migration",
        ],
        "next_actions": next_actions,
    }
