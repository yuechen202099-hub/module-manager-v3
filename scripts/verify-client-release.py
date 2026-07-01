from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path


REQUIRED_FILES = {
    "README.md",
    "AGENTS.md",
    ".gitattributes",
    ".env.example",
    "RELEASE_MANIFEST.md",
    "docs/CLIENT_ACCEPTANCE_REPORT.md",
    "docs/CLIENT_FINAL_AUDIT.md",
    "docs/CLIENT_DEMO_READINESS.md",
    "docs/CLIENT_DEMO_SCRIPT.md",
    "docs/CLIENT_SIGNOFF_CHECKLIST.md",
    "docs/CLIENT_VISUAL_QA.md",
    "docs/SERVER_DEPLOYMENT_PREP.md",
    "docs/PROJECT_DECISIONS.md",
    "docs/STATIC_TO_VUE_MIGRATION.md",
    "docs/sop/README.md",
    "docs/sop/01-demand-intake-and-priority.md",
    "docs/sop/02-production-branch-versioning.md",
    "docs/sop/03-change-analysis-and-tdd.md",
    "docs/sop/04-subagent-review-template.md",
    "docs/sop/05-release-package-and-hash.md",
    "docs/sop/06-production-deploy-runbook.md",
    "docs/sop/07-rollback-and-incident-review.md",
    "docs/sop/08-business-acceptance-templates.md",
    "docs/database/postgresql-schema.md",
    "infra/nginx/module-manager-v2.conf",
    "infra/module-manager-v2.service",
    "infra/module-manager-v2-photo-barcode-maintenance.service",
    "infra/module-manager-v2-photo-barcode-maintenance.timer",
    "scripts/build-client-release.ps1",
    "scripts/run_photo_barcode_maintenance.sh",
    "scripts/run_photo_barcode_maintenance_slice.sh",
    "scripts/run_photo_barcode_not_matched_rescan.sh",
    "scripts/run-client-acceptance-gate.ps1",
    "scripts/run-client-demo.ps1",
    "scripts/smoke-client-demo.py",
    "scripts/seed-client-demo-data.py",
    "scripts/verify_vue_migration_gate.py",
    "scripts/verify_postgres_cutover_gate.py",
    "scripts/verify-production-readiness.py",
    "scripts/verify-client-release.py",
    "scripts/verify_security_hardening.py",
    "scripts/verify_claim_tasks_completion_status.js",
    "scripts/verify_construction_one_click_upload.js",
    "scripts/verify_construction_draft_photo_cache.js",
    "scripts/verify_installer_workload_completion_visibility.js",
    "scripts/verify_release_sop.py",
    "scripts/verify_release_retention_policy.py",
    "scripts/verify_project_board_photo_dialog.js",
    "scripts/verify_project_board_data_center_photos.js",
    "scripts/production_backup.sh",
    "scripts/cleanup_old_releases.sh",
    "scripts/production_health_check.py",
    "ops/releases/README.md",
    "ops/releases/V3.0.73.md",
    "ops/releases/V3.0.72.md",
    "ops/releases/V3.0.71.md",
    "ops/releases/V3.0.70.md",
    "ops/releases/V3.0.69.md",
    "ops/releases/V3.0.68.md",
    "ops/releases/V3.0.67.md",
    "ops/releases/V3.0.66.md",
    "ops/releases/V3.0.65.md",
    "ops/releases/V3.0.64.md",
    "ops/releases/V3.0.63.md",
    "ops/releases/V3.0.62.md",
    "ops/releases/V3.0.61.md",
    "ops/releases/V3.0.60.md",
    "ops/releases/V3.0.59.md",
    "ops/releases/V3.0.58.md",
    "ops/releases/V3.0.56.md",
    "ops/releases/V3.0.55.md",
    "ops/releases/V3.0.54.md",
    "ops/releases/V3.0.53.md",
    "ops/releases/V3.0.52.md",
    "ops/releases/V3.0.51.md",
    "ops/releases/V3.0.50.md",
    "ops/releases/V3.0.49.md",
    "ops/releases/V3.0.48.md",
    "ops/releases/V3.0.47.md",
    "ops/releases/V3.0.46.md",
    "ops/releases/V3.0.45.md",
    "ops/releases/V3.0.44.md",
    "ops/releases/V3.0.43.md",
    "ops/releases/V3.0.42.md",
    "ops/releases/V3.0.41.md",
    "ops/releases/V3.0.40.md",
    "ops/releases/V3.0.39.md",
    "ops/releases/V3.0.38.md",
    "ops/releases/V3.0.37.md",
    "ops/incidents/P0-template.md",
    "v2-api/app/main.py",
    "v2-api/app/static/favicon.svg",
    "v2-api/app/static/vue/index.html",
    "v2-api/app/static/demo-assets/review-photo-1.svg",
    "v2-api/app/static/demo-assets/review-photo-2.svg",
    "v2-api/app/static/demo-assets/review-photo-3.svg",
    "v2-api/app/static/demo-assets/review-photo-4.svg",
    "v2-api/requirements.txt",
    "v2-api/requirements-dev.txt",
    "v2-api/tests/test_api.py",
    "v2-api/tests/test_recompute_photo_barcode_checks.py",
    "v2-api/scripts/recompute_photo_barcode_checks.py",
    "v2-api/scripts/migrate_json_to_postgres.py",
    "v2-api/scripts/migrate_photos_to_oss.py",
    "v2-web/Dockerfile",
    "v2-web/package.json",
    "v2-web/src/main.ts",
}

FORBIDDEN_PARTS = {
    ".env",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "build",
}

FORBIDDEN_SUFFIXES = {
    ".pyc",
    ".pyo",
}

FORBIDDEN_PREFIXES = {
    "v2-api/app/static/uploads/",
}


def fail(message: str) -> None:
    raise AssertionError(message)


def normalize_zip_name(name: str) -> str:
    return name.replace("\\", "/").lstrip("/")


def verify_package(zip_path: Path) -> None:
    if not zip_path.exists():
        fail(f"Release zip not found: {zip_path}")
    if zip_path.stat().st_size <= 0:
        fail(f"Release zip is empty: {zip_path}")

    with zipfile.ZipFile(zip_path) as archive:
        raw_names = {info.filename for info in archive.infolist() if not info.is_dir()}
        backslash_names = sorted(name for name in raw_names if "\\" in name)
        if backslash_names:
            fail(
                "Release zip contains Windows path separators: "
                + ", ".join(backslash_names[:20])
            )
        names = {normalize_zip_name(name) for name in raw_names}
        manifest = archive.read("RELEASE_MANIFEST.md").decode("utf-8") if "RELEASE_MANIFEST.md" in names else ""
        package_version = ""
        version_match = re.search(r"^- Version:\s*(?P<version>\S+)", manifest, re.MULTILINE)
        if version_match:
            package_version = version_match.group("version")
        static_index = (
            archive.read("v2-api/app/static/vue/index.html").decode("utf-8")
            if "v2-api/app/static/vue/index.html" in names
            else ""
        )
        static_js = ""
        if package_version:
            for name in sorted(names):
                if name.startswith("v2-api/app/static/vue/assets/") and name.endswith(".js"):
                    chunk = archive.read(name).decode("utf-8", errors="ignore")
                    if package_version in chunk:
                        static_js = chunk
                        break
        crlf_shell_scripts = sorted(
            name
            for name in names
            if name.endswith(".sh") and b"\r\n" in archive.read(name)
        )
        if crlf_shell_scripts:
            fail("Shell scripts must use LF line endings: " + ", ".join(crlf_shell_scripts[:20]))

    missing = sorted(REQUIRED_FILES - names)
    if missing:
        fail("Missing required release files: " + ", ".join(missing))

    forbidden_hits: list[str] = []
    for name in names:
        if any(name.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
            forbidden_hits.append(name)
            continue
        parts = set(Path(name).parts)
        if parts & FORBIDDEN_PARTS:
            forbidden_hits.append(name)
            continue
        if Path(name).suffix in FORBIDDEN_SUFFIXES:
            forbidden_hits.append(name)
    if forbidden_hits:
        fail("Forbidden local/cache files found in release: " + ", ".join(sorted(forbidden_hits)[:20]))
    legacy_static_pages = sorted(
        name
        for name in names
        if name.startswith("v2-api/app/static/")
        and name.endswith(".html")
        and not name.startswith("v2-api/app/static/vue/")
    )
    if legacy_static_pages:
        fail("Legacy static HTML pages found in release: " + ", ".join(legacy_static_pages[:20]))
    for text in [
        "Production mode disables demo accounts by default",
        "Production mode disables /docs, /redoc, and /openapi.json by default",
        "Confirm /docs, /redoc, and /openapi.json return 404 in production",
        "Vue strict-native production pages are required",
        "PostgreSQL cutover audit must be reviewed before production deployment",
        "Production SOP files and release record templates are present",
    ]:
        if text not in manifest:
            fail(f"Release manifest missing production safety note: {text}")
    if package_version:
        if f"Module Manager V{package_version}" not in static_index:
            fail(f"Vue static index title must be V{package_version}")
        if package_version not in static_js:
            fail(f"Vue static assets must include APP_VERSION {package_version}; rebuild v2-web before packaging")

    print(f"[OK] release zip exists: {zip_path}")
    print(f"[OK] release zip size: {zip_path.stat().st_size} bytes")
    print(f"[OK] required files: {len(REQUIRED_FILES)}")
    print("[OK] release manifest contains production safety notes")
    print("[OK] no forbidden local/cache files")


def default_latest_zip() -> Path:
    root = Path(__file__).resolve().parents[1]
    candidates = sorted(
        [
            *root.glob("build/server-release/module-manager-v2-server-*.zip"),
        ],
        key=lambda item: item.stat().st_mtime,
    )
    if not candidates:
        fail(f"No release zip found under {root / 'build'}")
    return candidates[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a Module Manager V2 client release zip.")
    parser.add_argument("zip", nargs="?", type=Path, help="Release zip path. Defaults to the newest client release zip.")
    args = parser.parse_args()
    verify_package(args.zip or default_latest_zip())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
