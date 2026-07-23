#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "3.2.0"
DISPLAY_VERSION = f"V{VERSION}"

RELEASE_ITEMS = (
    "数据中台统一审阅",
    "驾驶舱下钻",
    "统一导出中心",
    "审阅员角色下线",
    "明细分页支持 20/50/100",
)

FOCUSED_VERIFIERS = (
    "scripts/verify_v3_2_0_role_routes.py",
    "scripts/verify_v3_2_0_data_center_ui.py",
    "scripts/verify_v3_2_0_dashboard_drilldown.py",
    "scripts/verify_v3_2_0_export_center_ui.py",
    "scripts/verify_v3_2_0_single_export_entry.py",
    "scripts/verify_v3_2_0_release.py",
)

PACKAGE_FILES = (
    *FOCUSED_VERIFIERS,
    "v2-api/alembic/versions/0013_data_center_query_indexes.py",
    "v2-api/alembic/versions/0014_export_center_jobs.py",
    "v2-api/app/schemas/data_center.py",
    "v2-api/app/schemas/export_center.py",
    "v2-api/app/services/data_center.py",
    "v2-api/app/services/export_center.py",
    "v2-web/src/components/data-center/DataCenterFilters.vue",
    "v2-web/src/components/data-center/DataCenterReviewDialog.vue",
    "v2-web/src/components/export-center/ExportCatalogTab.vue",
    "v2-web/src/components/export-center/ExportJobsTable.vue",
    "v2-web/src/components/export-center/TerminalDeliveryTab.vue",
    "v2-web/src/views/GlobalSearchView.vue",
    "v2-web/src/views/ExportsView.vue",
    "ops/releases/V3.2.0.md",
)

FORBIDDEN_RELEASE_DIRECTORIES = (
    "coverage",
    "htmlcov",
    "test-results",
    "playwright-report",
    ".nyc_output",
    ".pytest_cache",
    "__pycache__",
)

FORBIDDEN_RELEASE_SUFFIXES = (
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".sql",
    ".dump",
    ".sqlite",
    ".sqlite3",
    ".db",
)


def read_text(relative_path: str, failures: list[str]) -> str:
    path = ROOT / relative_path
    if not path.is_file():
        failures.append(f"missing required file: {relative_path}")
        return ""
    return path.read_text(encoding="utf-8")


def require_contains(
    text: str,
    marker: str,
    relative_path: str,
    failures: list[str],
) -> None:
    if marker not in text:
        failures.append(f"{relative_path}: missing {marker!r}")


def verify_version_surfaces(failures: list[str]) -> None:
    package_path = ROOT / "v2-web/package.json"
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        failures.append(f"v2-web/package.json: cannot read package version: {exc}")
    else:
        if package.get("version") != VERSION:
            failures.append(
                f"v2-web/package.json: expected version {VERSION!r}, "
                f"got {package.get('version')!r}"
            )

    index_html = read_text("v2-web/index.html", failures)
    require_contains(
        index_html,
        f"<title>Module Manager {DISPLAY_VERSION}</title>",
        "v2-web/index.html",
        failures,
    )

    main_py = read_text("v2-api/app/main.py", failures)
    if not re.search(rf'\bversion\s*=\s*"{re.escape(VERSION)}"', main_py):
        failures.append(f"v2-api/app/main.py: FastAPI version must be exactly {VERSION}")

    ops_status = read_text("v2-api/app/services/ops_status.py", failures)
    require_contains(
        ops_status,
        f'return "{VERSION}"',
        "v2-api/app/services/ops_status.py",
        failures,
    )

    source_version = read_text("v2-web/src/version.json", failures)
    try:
        source_version_artifact = json.loads(source_version)
    except json.JSONDecodeError as exc:
        failures.append(f"v2-web/src/version.json: invalid JSON: {exc}")
    else:
        if source_version_artifact != {"version": VERSION}:
            failures.append(
                "v2-web/src/version.json: "
                f"expected {{'version': {VERSION!r}}}, got {source_version_artifact!r}"
            )

    release_notes = read_text("v2-web/src/constants/releaseNotes.ts", failures)
    require_contains(
        release_notes,
        f"version: '{DISPLAY_VERSION}'",
        "v2-web/src/constants/releaseNotes.ts",
        failures,
    )
    for item in RELEASE_ITEMS:
        require_contains(
            release_notes,
            item,
            "v2-web/src/constants/releaseNotes.ts",
            failures,
        )

    operational_markers = {
        "README.md": (
            r".\.venv\Scripts\python.exe .\scripts\verify_release_sop.py --version V3.2.0",
            r".\scripts\build-client-release.ps1 -Version 3.2.0",
        ),
        "v2-web/src/components/AppLayout.vue": ("V3.2.0",),
        "v2-web/src/api/services.ts": ("V3.2.0-final-delivery-",),
        "v2-api/app/api/routes/exports.py": ("V3.2.0-final-delivery-",),
        "v2-api/pyproject.toml": (
            'version = "3.2.0"',
            "Module Replacement Project Manager V3.2.0",
        ),
        "v2-api/scripts/verify_v3_1_release.py": (
            'EXPECTED_VERSION = "3.2.0"',
        ),
    }
    for relative_path, markers in operational_markers.items():
        content = read_text(relative_path, failures)
        for marker in markers:
            require_contains(content, marker, relative_path, failures)


def verify_release_record(failures: list[str]) -> None:
    release_path = "ops/releases/V3.2.0.md"
    release_record = read_text(release_path, failures)
    required_markers = (
        "V3.1.1",
        "0013_data_center_query_indexes",
        "0014_export_center_jobs",
        "admin",
        ".env",
        "data",
        "uploads",
        "PostgreSQL",
        "rollback",
        "/health",
        "/system/status/version",
        "verify_v3_2_0_role_routes.py",
        "verify_v3_2_0_data_center_ui.py",
        "verify_v3_2_0_dashboard_drilldown.py",
        "verify_v3_2_0_export_center_ui.py",
        "verify_v3_2_0_single_export_entry.py",
        "verify_v3_2_0_release.py",
        "pytest",
        "npm run type-check",
        "npm run build",
        "SHA256",
        "PENDING_TASK_9",
    )
    for marker in required_markers:
        require_contains(release_record, marker, release_path, failures)

    manifest = read_text("RELEASE_MANIFEST.md", failures)
    for marker in (
        "module-manager-v2-server-3.2.0.zip",
        "- Version: 3.2.0",
        "verify_release_sop.py --version V3.2.0",
    ):
        require_contains(manifest, marker, "RELEASE_MANIFEST.md", failures)

    agents = read_text("AGENTS.md", failures)
    for marker in (
        "- Deployed production baseline: `V3.1.1`.",
        "- Release candidate: `V3.2.0`.",
        "- Release-candidate maintenance branch: `production/V3/3.2.0`.",
        "codebase-memory-mcp",
        "工具/skill",
        "数据中台",
        "导出中心",
        "MP-V1.0.xx",
        "PM-V1.0.xx",
        "正式生产 `V3.x.y`",
    ):
        require_contains(agents, marker, "AGENTS.md", failures)
    if "正式生产 `V3.0.xx`" in agents:
        failures.append("AGENTS.md: obsolete formal production namespace V3.0.xx remains")

    signoff_path = "docs/CLIENT_SIGNOFF_CHECKLIST.md"
    signoff = read_text(signoff_path, failures)
    for marker in (
        "V3.2.0 候选生产验证",
        "ops/releases/V3.2.0.md",
    ):
        require_contains(signoff, marker, signoff_path, failures)
    for stale_marker in (
        "V3.1.1 生产验证",
        "ops/releases/V3.1.1.md",
    ):
        if stale_marker in signoff:
            failures.append(f"{signoff_path}: stale candidate signoff marker {stale_marker!r}")


def verify_feature_files_and_routes(failures: list[str]) -> None:
    for relative_path in PACKAGE_FILES:
        if not (ROOT / relative_path).is_file():
            failures.append(f"missing V3.2.0 release input: {relative_path}")

    groups = read_text("v2-api/app/api/routes/groups.py", failures)
    for marker in (
        '@router.get("/data-center")',
        '@router.get("/data-center/{kind}/{item_id}")',
        '@router.patch("/data-center/groups/{group_id}")',
    ):
        require_contains(groups, marker, "v2-api/app/api/routes/groups.py", failures)

    exports = read_text("v2-api/app/api/routes/exports.py", failures)
    for marker in (
        '@router.get("/catalog")',
        '@router.get("/terminal-readiness")',
        '@router.get("/jobs")',
        '@router.post("/jobs")',
        '@router.get("/jobs/{job_id}/download")',
    ):
        require_contains(exports, marker, "v2-api/app/api/routes/exports.py", failures)

    for retired_path in (
        "v2-web/src/views/TaskHallView.vue",
        "v2-api/app/static/task_hall.html",
    ):
        if (ROOT / retired_path).exists():
            failures.append(f"retired reviewer/task-hall page restored: {retired_path}")

    navigation = "\n".join(
        (
            read_text("v2-web/src/layouts/AppLayout.vue", failures),
            read_text("v2-web/src/router/staticPages.ts", failures),
        )
    )
    for retired_marker in ("审阅工作台", "TaskHallView"):
        if retired_marker in navigation:
            failures.append(
                f"reviewer navigation still contains {retired_marker!r}"
            )

    for relative_path in (
        "docs/CLIENT_ACCEPTANCE_REPORT.md",
        "docs/CLIENT_FINAL_AUDIT.md",
        "docs/CLIENT_SIGNOFF_CHECKLIST.md",
    ):
        acceptance_document = read_text(relative_path, failures)
        for retired_marker in (
            "http://127.0.0.1:8000/task-hall",
            "reviewer / review123",
            "审阅员 demo 账号",
        ):
            if retired_marker in acceptance_document:
                failures.append(
                    f"{relative_path}: retired acceptance entry remains {retired_marker!r}"
                )


def verify_package_gates(failures: list[str]) -> None:
    build_script = read_text("scripts/build-client-release.ps1", failures)
    package_verifier = read_text("scripts/verify-client-release.py", failures)
    sop_verifier = read_text("scripts/verify_release_sop.py", failures)

    require_contains(
        build_script,
        '[string]$Version = "3.2.0"',
        "scripts/build-client-release.ps1",
        failures,
    )
    for relative_path in PACKAGE_FILES:
        normalized = relative_path.replace("/", "\\")
        if relative_path not in build_script and normalized not in build_script:
            failures.append(
                f"scripts/build-client-release.ps1: package copy gate missing {relative_path}"
            )
        if relative_path not in package_verifier:
            failures.append(
                f"scripts/verify-client-release.py: required-file gate missing {relative_path}"
            )

    for marker in (
        "verify_v3_2_0_release.py",
        "ops/releases/V3.2.0.md",
    ):
        require_contains(
            sop_verifier,
            marker,
            "scripts/verify_release_sop.py",
            failures,
        )

    for directory_name in FORBIDDEN_RELEASE_DIRECTORIES:
        for relative_path, content in (
            ("scripts/build-client-release.ps1", build_script),
            ("scripts/verify-client-release.py", package_verifier),
        ):
            require_contains(content, directory_name, relative_path, failures)
    for suffix in FORBIDDEN_RELEASE_SUFFIXES:
        for relative_path, content in (
            ("scripts/build-client-release.ps1", build_script),
            ("scripts/verify-client-release.py", package_verifier),
        ):
            require_contains(content, suffix, relative_path, failures)
    for marker in (
        "$_.Name.ToLowerInvariant() -in $forbiddenReleaseDirectoryNames",
        "$normalizedExtension = $_.Extension.ToLowerInvariant()",
        '$normalizedName -eq ".env"',
        '$normalizedName.StartsWith(".env.")',
    ):
        require_contains(
            build_script,
            marker,
            "scripts/build-client-release.ps1",
            failures,
        )
    for marker in (
        "normalized_name = name.casefold()",
        'leaf_name == ".env"',
        'leaf_name.startswith(".env.")',
        "parts = set(normalized_path.parts)",
        "normalized_path.suffix in FORBIDDEN_SUFFIXES",
    ):
        require_contains(
            package_verifier,
            marker,
            "scripts/verify-client-release.py",
            failures,
        )
    if build_script.count("Remove-ForbiddenReleaseItems") < 3:
        failures.append(
            "scripts/build-client-release.ps1: forbidden cleanup must run "
            "after source copy and after Vue build"
        )
    if 'Copy-ReleaseItem ".env.example"' in build_script:
        failures.append(
            "scripts/build-client-release.ps1: .env.example must not be copied"
        )


def verify_static_build(failures: list[str]) -> None:
    version_path = ROOT / "v2-api/app/static/vue/version.json"
    try:
        version_artifact = json.loads(version_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        failures.append(f"static version.json is missing or invalid: {exc}")
    else:
        if version_artifact.get("version") != VERSION:
            failures.append(
                "v2-api/app/static/vue/version.json: "
                f"expected version {VERSION!r}, got {version_artifact.get('version')!r}"
            )

    static_index = read_text("v2-api/app/static/vue/index.html", failures)
    require_contains(
        static_index,
        f"<title>Module Manager {DISPLAY_VERSION}</title>",
        "v2-api/app/static/vue/index.html",
        failures,
    )

    asset_dir = ROOT / "v2-api/app/static/vue/assets"
    javascript = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(asset_dir.glob("*.js"))
        if path.is_file()
    )
    require_contains(
        javascript,
        DISPLAY_VERSION,
        "v2-api/app/static/vue/assets/*.js",
        failures,
    )
    for item in RELEASE_ITEMS:
        require_contains(
            javascript,
            item,
            "v2-api/app/static/vue/assets/*.js",
            failures,
        )


def main() -> int:
    failures: list[str] = []
    verify_version_surfaces(failures)
    verify_release_record(failures)
    verify_feature_files_and_routes(failures)
    verify_package_gates(failures)
    verify_static_build(failures)

    if failures:
        print("[FAIL] V3.2.0 release checks failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("[OK] V3.2.0 release checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
