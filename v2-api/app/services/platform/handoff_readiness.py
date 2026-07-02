from __future__ import annotations

from typing import Any

from app.services.platform.migration_readiness import build_platform_migration_readiness
from app.services.platform.persistence import build_platform_persistence_status
from app.services.platform.readiness import build_project_readiness_summary


PRODUCTION_BASELINE = {
    "branch": "production/V3/3.0.71",
    "version": "V3.0.71",
}
FEATURE_BRANCH = "pm-platform/project-drafts"


def build_platform_handoff_readiness() -> dict[str, Any]:
    project_readiness_summary = build_project_readiness_summary()
    persistence_status = build_platform_persistence_status()
    migration_readiness = build_platform_migration_readiness()
    return {
        "handoff_version": 1,
        "feature_branch": FEATURE_BRANCH,
        "production_baseline": PRODUCTION_BASELINE,
        "ready_for_review_package": True,
        "ready_for_production_migration": False,
        "ready_for_production_release": False,
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
        "next_actions": [
            "prepare_pr_or_patch_handoff",
            "review_against_production_baseline",
            "keep_migration_blocked_until_user_approval",
            "run_browser_smoke_before_handoff",
        ],
    }
