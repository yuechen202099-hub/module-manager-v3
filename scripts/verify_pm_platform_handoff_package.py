from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs/reports/pm-platform-pr-patch-handoff-2026-07-02.md"
PR_BODY = ROOT / "docs/reports/pm-platform-pr-body-2026-07-02.md"
READINESS_PANEL_REPORT = (
    ROOT / "docs/reports/pm-platform-readiness-panel-frontend-2026-07-02.md"
)
READINESS_SUMMARY_REPORT = (
    ROOT / "docs/reports/pm-platform-readiness-summary-list-2026-07-02.md"
)
READINESS_ACTION_FILTER_REPORT = (
    ROOT / "docs/reports/pm-platform-readiness-action-filter-2026-07-02.md"
)
PERSISTENCE_READINESS_FRONTEND_REPORT = (
    ROOT / "docs/reports/pm-platform-persistence-readiness-frontend-2026-07-02.md"
)
MIGRATION_READINESS_GATE_REPORT = (
    ROOT / "docs/reports/pm-platform-migration-readiness-gate-2026-07-02.md"
)
HANDOFF_READINESS_SUMMARY_REPORT = (
    ROOT / "docs/reports/pm-platform-handoff-readiness-summary-2026-07-02.md"
)
LAN_TABLET_ACCESS_REPORT = (
    ROOT / "docs/reports/pm-platform-lan-tablet-access-2026-07-02.md"
)
PRODUCTION_SYNC_READINESS_REPORT = (
    ROOT / "docs/reports/pm-platform-production-3.0.77-sync-readiness-2026-07-02.md"
)
TEAM_MEMORY = ROOT / "docs/PM_PLATFORM_TEAM_DEVELOPMENT.md"
PLAN = ROOT / "docs/superpowers/plans/2026-07-02-pm-platform-pr-patch-handoff.md"

REQUIRED_REPORT_SECTIONS = [
    "## Baseline",
    "## Changed File Groups",
    "## Feature Summary",
    "## Verification",
    "## Risks",
    "## Migration Notes",
    "## Rollback Plan",
    "## Production Safety",
]

REQUIRED_REPORT_STRINGS = [
    "production/V3/3.0.71",
    "pm-platform/project-drafts",
    "862659e0e6599367e7dbb164659b7ccd147c2574",
    "8035f3247b5f2aaf579747fe4d71ae25fe2211e5",
    "verify_platform_backend_contract_snapshot.py",
    "verify_platform_persistence_status.py",
    "verify_platform_postgres_design.py",
    "verify_platform_project_config_persistence_contract.py",
    "verify_platform_project_readiness.py",
    "verify_pm_platform_team_operating_model.py",
    "verify_vue_project_readiness_summary_list.js",
    "verify_vue_project_readiness_panel.js",
    "verify_vue_construction_checklist_consumption.js",
    "verify_production_baseline.py",
    "上线检查",
    "live OSS/PostgreSQL",
    ".env",
    "uploads",
    "PostgreSQL",
    "rollback",
    "Team Operating Model Lock",
    "/projects/readiness/summary",
    "上线状态",
    "action_counts",
    "接入待办",
    "Project Readiness Action Filter",
    "filteredProjects",
    "筛选中",
    "清除筛选",
    "Project Persistence Readiness Frontend",
    "verify_vue_project_persistence_readiness.js",
    "持久化准备",
    "当前存储",
    "迁移审批",
    "安全门槛",
    "Platform Migration Readiness Gate",
    "verify_platform_migration_readiness.py",
    "/projects/persistence/migration-readiness",
    "迁移门禁",
    "ready_for_migration",
    "Platform Handoff Readiness Summary",
    "verify_platform_handoff_readiness.py",
    "verify_vue_platform_handoff_readiness.js",
    "/projects/handoff/readiness",
    "handoff-readiness-band",
    "交付就绪",
    "可评审包",
    "生产迁移未放行",
    "ready_for_review_package",
    "ready_for_production_migration",
    "Platform LAN Tablet Access",
    "verify_platform_local_start_script.py",
    "start-platform-local.ps1",
    "HostAddress",
    "LAN URL",
    "0.0.0.0:52131",
    "平台版本号评估",
    "PM-V1.0.xx",
    "production/V3/3.0.77",
    "Production 3.0.77 Sync Readiness",
    "production_changed=145",
    "dirty=192",
    "overlap=43",
]

REQUIRED_PR_BODY_SECTIONS = [
    "## Summary",
    "## Baseline",
    "## Test Plan",
    "## Migration / Rollback",
    "## Risks",
]

REQUIRED_PR_BODY_STRINGS = [
    "verify_pm_platform_team_operating_model.py",
    "verify_vue_project_readiness_summary_list.js",
    "Team Operating Model Lock",
    "/projects/readiness/summary",
    "接入待办",
    "Project Readiness Action Filter",
    "筛选中",
    "清除筛选",
    "Project Persistence Readiness Frontend",
    "verify_vue_project_persistence_readiness.js",
    "持久化准备",
    "Platform Migration Readiness Gate",
    "verify_platform_migration_readiness.py",
    "迁移门禁",
    "Platform Handoff Readiness Summary",
    "verify_platform_handoff_readiness.py",
    "verify_vue_platform_handoff_readiness.js",
    "/projects/handoff/readiness",
    "交付就绪",
    "生产迁移未放行",
    "Platform LAN Tablet Access",
    "verify_platform_local_start_script.py",
    "LAN URL",
    "平台版本号评估",
    "PM-V1.0.xx",
    "production/V3/3.0.77",
    "Production 3.0.77 Sync Readiness",
    "overlap",
]

REQUIRED_TEAM_STRINGS = [
    "Context-Stable Team Contract",
    "Codex Integrator remains the single project manager",
    "Current production baseline: `production/V3/3.0.77`",
    "Current feature branch: `pm-platform/production-3.0.77-sync`",
    "PR/patch handoff",
    "frontend project readiness panel",
    "Context compression rule",
    "live OSS/PostgreSQL change-path guard",
    "Alembic migration",
    "Project readiness action filter",
    "filteredProjects",
    "清除筛选",
    "Project Persistence Readiness Frontend",
    "持久化准备",
    "Platform Migration Readiness Gate",
    "/projects/persistence/migration-readiness",
    "Platform Handoff Readiness Summary",
    "/projects/handoff/readiness",
    "交付就绪",
    "生产迁移未放行",
    "Platform LAN Tablet Access",
    "HostAddress",
    "LAN URL",
    "GitHub Issue #1",
    "平台版本号评估",
    "PM-V1.0.xx",
    "production/V3/3.0.77",
    "Production 3.0.77 Sync Readiness",
    "overlap",
]

SENSITIVE_PATHS = [
    ".env",
    "data",
    "v2-api/data",
    "v2-api/app/static/uploads",
    "uploads",
]

ALLOWED_POSTGRES_DESIGN_PATHS = {
    "v2-api/app/services/platform/postgres_design.py",
    "v2-api/tests/test_platform_postgres_design.py",
    "scripts/verify_platform_postgres_design.py",
    "docs/superpowers/plans/2026-07-02-platform-postgres-persistence-design.md",
    "docs/reports/pm-platform-postgres-persistence-design-2026-07-02.md",
}

LIVE_POSTGRES_PATH_MARKERS = [
    "alembic/",
    "migrations/",
    "sql/",
    "infra/",
    "ops/releases/",
    "ops/incidents/",
]

LIVE_DATA_EXTENSIONS = {
    ".bak",
    ".backup",
    ".db",
    ".dump",
    ".key",
    ".pem",
    ".pfx",
    ".sql",
    ".sqlite",
    ".sqlite3",
}


def read_text(path: Path) -> str:
    if not path.exists():
        raise AssertionError(f"missing required file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def assert_contains(text: str, required: list[str], label: str) -> None:
    missing = [item for item in required if item not in text]
    if missing:
        joined = ", ".join(missing)
        raise AssertionError(f"{label} missing required content: {joined}")


def git_executable() -> str:
    found = shutil.which("git")
    if found:
        return found
    bundled = (
        Path.home()
        / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe"
    )
    if bundled.exists():
        return str(bundled)
    raise AssertionError("git executable is required for sensitive path verification")


def assert_sensitive_paths_clean() -> None:
    cmd = [git_executable(), "status", "--short", "--", *SENSITIVE_PATHS]
    completed = subprocess.run(
        cmd,
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "git sensitive path check failed: " + completed.stderr.strip()
        )
    if completed.stdout.strip():
        raise AssertionError(
            "sensitive paths have pending changes:\n" + completed.stdout.strip()
        )


def changed_paths() -> list[str]:
    completed = subprocess.run(
        [git_executable(), "status", "--short"],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "git changed path scan failed: " + completed.stderr.strip()
        )
    paths: list[str] = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        raw_path = line[3:] if len(line) > 3 else line.strip()
        if " -> " in raw_path:
            raw_path = raw_path.split(" -> ", 1)[1]
        paths.append(raw_path.replace("\\", "/").strip())
    return paths


def assert_no_live_oss_or_postgres_changes(paths: list[str]) -> None:
    blocked: list[str] = []
    for path in paths:
        lower_path = path.lower()
        suffix = Path(lower_path).suffix
        if suffix in LIVE_DATA_EXTENSIONS:
            blocked.append(path)
            continue
        path_parts = set(lower_path.replace("-", "_").split("/"))
        has_oss_marker = "oss" in path_parts or lower_path.startswith("oss/")
        has_postgres_marker = "postgres" in lower_path or "postgresql" in lower_path
        is_allowed_postgres_design = path in ALLOWED_POSTGRES_DESIGN_PATHS
        is_live_postgres_area = (
            any(marker in lower_path for marker in LIVE_POSTGRES_PATH_MARKERS)
            or lower_path.startswith(("postgres/", "postgresql/"))
        )
        if has_oss_marker:
            blocked.append(path)
            continue
        if has_postgres_marker and not is_allowed_postgres_design and is_live_postgres_area:
            blocked.append(path)
    if blocked:
        raise AssertionError(
            "live OSS/PostgreSQL or dump-like paths have pending changes:\n"
            + "\n".join(blocked)
        )


def main() -> int:
    try:
        report = read_text(REPORT)
        pr_body = read_text(PR_BODY)
        readiness_panel_report = read_text(READINESS_PANEL_REPORT)
        readiness_summary_report = read_text(READINESS_SUMMARY_REPORT)
        readiness_action_filter_report = read_text(READINESS_ACTION_FILTER_REPORT)
        persistence_readiness_frontend_report = read_text(PERSISTENCE_READINESS_FRONTEND_REPORT)
        migration_readiness_gate_report = read_text(MIGRATION_READINESS_GATE_REPORT)
        handoff_readiness_summary_report = read_text(HANDOFF_READINESS_SUMMARY_REPORT)
        lan_tablet_access_report = read_text(LAN_TABLET_ACCESS_REPORT)
        production_sync_readiness_report = read_text(PRODUCTION_SYNC_READINESS_REPORT)
        team_memory = read_text(TEAM_MEMORY)
        plan = read_text(PLAN)

        assert_contains(report, REQUIRED_REPORT_SECTIONS, "handoff report")
        assert_contains(report, REQUIRED_REPORT_STRINGS, "handoff report")
        assert_contains(pr_body, REQUIRED_PR_BODY_SECTIONS, "PR body draft")
        assert_contains(pr_body, REQUIRED_PR_BODY_STRINGS, "PR body draft")
        assert_contains(
            readiness_panel_report,
            [
                "PM Platform Readiness Panel Frontend Report",
                "verify_vue_project_readiness_panel.js",
                "Browser smoke",
                "上线检查",
                "live OSS/PostgreSQL",
                "Migration And Rollback",
            ],
            "readiness panel report",
        )
        assert_contains(
            readiness_summary_report,
            [
                "PM Platform Readiness Summary List Report",
                "/projects/readiness/summary",
                "action_counts",
                "verify_vue_project_readiness_summary_list.js",
                "Browser smoke",
                "上线状态",
                "接入待办",
                "Migration And Rollback",
            ],
            "readiness summary report",
        )
        assert_contains(
            readiness_action_filter_report,
            [
                "PM Platform Readiness Action Filter Report",
                "Project Readiness Action Filter",
                "filteredProjects",
                "applyReadinessActionFilter",
                "clearReadinessActionFilter",
                "verify_vue_project_readiness_summary_list.js",
                "Browser smoke",
                "筛选中",
                "清除筛选",
                "Migration And Rollback",
            ],
            "readiness action filter report",
        )
        assert_contains(
            persistence_readiness_frontend_report,
            [
                "PM Platform Persistence Readiness Frontend Report",
                "Project Persistence Readiness Frontend",
                "fetchPlatformPersistenceStatus",
                "fetchProjectConfigPersistenceContract",
                "verify_vue_project_persistence_readiness.js",
                "Browser smoke",
                "持久化准备",
                "当前存储",
                "PostgreSQL",
                "迁移审批",
                "目标表",
                "安全门槛",
                "Migration And Rollback",
            ],
            "persistence readiness frontend report",
        )
        assert_contains(
            migration_readiness_gate_report,
            [
                "PM Platform Migration Readiness Gate Report",
                "Platform Migration Readiness Gate",
                "/projects/persistence/migration-readiness",
                "verify_platform_migration_readiness.py",
                "verify_vue_project_persistence_readiness.js",
                "ready_for_migration",
                "requires_user_approval",
                "dry-run",
                "rollback",
                "approval",
                "cutover-flag",
                "Browser smoke",
                "Migration And Rollback",
            ],
            "migration readiness gate report",
        )
        assert_contains(
            handoff_readiness_summary_report,
            [
                "PM Platform Handoff Readiness Summary Report",
                "Platform Handoff Readiness Summary",
                "/projects/handoff/readiness",
                "verify_platform_handoff_readiness.py",
                "verify_vue_platform_handoff_readiness.js",
                "ready_for_review_package",
                "ready_for_production_migration",
                "ready_for_production_release",
                "handoff-readiness-band",
                "交付就绪",
                "可评审包",
                "生产迁移未放行",
                "Browser smoke",
                "Migration And Rollback",
            ],
            "handoff readiness summary report",
        )
        assert_contains(
            lan_tablet_access_report,
            [
                "PM Platform LAN Tablet Access Report",
                "Platform LAN Tablet Access",
                "start-platform-local.ps1",
                "HostAddress",
                "0.0.0.0",
                "127.0.0.1",
                "LAN URL",
                "192.168.50.162",
                "verify_platform_local_start_script.py",
                "HTTP 200",
                "Safety And Rollback",
            ],
            "LAN tablet access report",
        )
        assert_contains(
            production_sync_readiness_report,
            [
                "PM Platform Production 3.0.77 Sync Readiness Report",
                "GitHub Issue #1",
                "平台版本号评估",
                "PM-V1.0.xx",
                "origin/production/V3/3.0.77",
                "4c05cc92a71e08a7eb5da6a25cef654271b4cfc5",
                "production_changed=145",
                "dirty=192",
                "overlap=43",
                "Do not merge or rebase directly in the current dirty worktree.",
                "Next Execution Sequence",
                "Rollback",
            ],
            "production sync readiness report",
        )
        assert_contains(team_memory, REQUIRED_TEAM_STRINGS, "team memory")
        assert_contains(
            plan,
            [
                "PM Platform PR Patch Handoff Implementation Plan",
                "verify_pm_platform_handoff_package.py",
                "Production Safety",
            ],
            "handoff plan",
        )
        assert_sensitive_paths_clean()
        assert_no_live_oss_or_postgres_changes(changed_paths())
    except AssertionError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    print("[OK] PM platform PR/patch handoff package is consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
