from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import stat
import sys
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
V3079_RELEASE_RECORD = "ops/releases/V3.0.79.md"
V326_BASELINE_RELEASE_RECORD = "ops/releases/V3.2.6.md"
V323_RELEASE_RECORD = "ops/releases/V3.2.3.md"
V324_RELEASE_RECORD = "ops/releases/V3.2.4.md"
V326_RELEASE_RECORD = "ops/releases/V3.2.6.md"
V327_RELEASE_RECORD = "ops/releases/V3.2.7.md"
V328_RELEASE_RECORD = "ops/releases/V3.2.8.md"
RUNTIME_VERSION_ARTIFACT = "v2-api/app/static/vue/version.json"
SOURCE_VERSION_ARTIFACT = "v2-web/src/version.json"
VALID_SHA256 = "a" * 64
VALID_SOURCE_COMMIT = "b" * 40
KPI_SOURCE_PATHS = (
    "v2-web/src/components/InstallerKpiDialog.vue",
    "v2-web/src/utils/installerKpi.ts",
)
V328_ARCHIVE_SOURCE_FILES = frozenset(
    {
        "docs/superpowers/specs/2026-08-23-collector-transfer-workbench-design.md",
        "scripts/build-client-release.ps1",
        "scripts/verify-client-release.py",
        "scripts/verify_release_sop.py",
        "scripts/verify_v3_2_8_release.py",
        "scripts/test_verify_v3_2_8_release.py",
        "v2-api/alembic/versions/0015_collector_transfer_workbench.py",
        "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py",
        "v2-api/app/api/routes/collector_transfer.py",
        "v2-api/app/main.py",
        "v2-api/app/models.py",
        "v2-api/app/services/collector_transfer.py",
        "v2-api/app/services/ops_status.py",
        "v2-api/pyproject.toml",
        "v2-api/scripts/verify_v3_1_release.py",
        "v2-api/tests/test_collector_transfer_api.py",
        "v2-api/tests/test_collector_transfer_domain.py",
        "v2-api/tests/test_collector_transfer_postgres_integration.py",
        "v2-api/tests/test_collector_transfer_service.py",
        "v2-api/tests/test_collector_transfer_scale.py",
        "v2-api/tests/test_v3_1_release.py",
        "v2-web/index.html",
        "v2-web/package.json",
        "v2-web/src/api/services.ts",
        "v2-web/src/api/types.ts",
        "v2-web/src/components/AppLayout.vue",
        "v2-web/src/constants/releaseNotes.ts",
        "v2-web/src/version.json",
        "v2-web/src/views/CollectorInventoryView.vue",
        "v2-web/src/views/__tests__/CollectorInventoryView.spec.ts",
    }
)
SAFETY_NOTES = (
    "Production mode disables demo accounts by default",
    "Production mode disables /docs, /redoc, and /openapi.json by default",
    "Confirm /docs, /redoc, and /openapi.json return 404 in production",
    "Vue strict-native production pages are required",
    "PostgreSQL cutover audit must be reviewed before production deployment",
    "Production SOP files and release record templates are present",
)

VALID_AGENTS = """# Package fixture

- Deployed production baseline: `V3.2.7`.
- Release candidate: `V3.2.8`.
- Release-candidate maintenance branch: `production/V3/3.2.8`.
- 当前已部署生产版本：`V3.2.7`。
- 当前发布候选版本：`V3.2.8`。
- 当前候选维护分支：`production/V3/3.2.8`。
"""
PENDING_RELEASE_RECORD = """# V3.2.8 Production Release Record

## Summary

- Status: pending
- Local Verification: not run
- Package: pending
- Production Deployment: pending
- Production Reconciliation: pending
- Rollback target: V3.2.7
- Candidate branch: `production/V3/3.2.8`
- Deployed production baseline: `V3.2.7`
- Candidate version: `V3.2.8`
- Database head: `20260824_0016 (head)`
- V3.2.8 has not been deployed to production.
- bounded single-collector lookup
- compact selected-column streaming
- pinned QuaggaJS scanner
- project/team isolation
- photo-first precedence
- mobile no-batch behavior
- API contracts are unchanged
- production acceptance is pending

## Package

| Evidence | Value |
| --- | --- |
| SHA256 | |

## Production Deployment

| Evidence | Value |
| --- | --- |
| Backup directory | |
| Release directory | |
| Public health check | |
"""

V322_PENDING_RELEASE_RECORD = """# V3.2.2 Production Release Record

## Summary

- Status: pending
- Local Verification: not run
- Package: pending
- Production Deployment: pending
- Production Reconciliation: pending
- Rollback target: V3.2.1
"""


def deployed_release_record(version: str, status: str) -> str:
    return f"""# V{version} Production Release Record

## Summary

- {status}

## Package

| Evidence | Value |
| --- | --- |
| SHA256 | {VALID_SHA256} |

## Production Deployment

| Evidence | Value |
| --- | --- |
| Backup directory | /opt/module-manager-v2/backups/V{version}-pre-20260719_120000 |
| Release directory | /opt/module-manager-v2/releases/v{version}-20260719_120000 |
| Public health check | https://www.sgcc.online/health passed |
"""


def load_verifier():
    spec = importlib.util.spec_from_file_location(
        "verify_client_release", ROOT / "scripts" / "verify-client-release.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load verify-client-release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_v320_release_verifier():
    spec = importlib.util.spec_from_file_location(
        "verify_v3_2_0_release", ROOT / "scripts" / "verify_v3_2_0_release.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load verify_v3_2_0_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_v321_release_verifier():
    spec = importlib.util.spec_from_file_location(
        "verify_v3_2_2_release", ROOT / "scripts" / "verify_v3_2_2_release.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load verify_v3_2_2_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v328_package_contract_requires_scale_and_camera_regressions() -> None:
    verifier = load_verifier()

    assert {
        "scripts/verify_v3_2_8_release.py",
        "scripts/test_verify_v3_2_8_release.py",
        "v2-api/tests/test_collector_transfer_scale.py",
        "v2-web/src/views/__tests__/CollectorInventoryView.spec.ts",
        "ops/releases/V3.2.8.md",
    } <= verifier.REQUIRED_FILES


def test_v328_package_verifier_rejects_a_v327_candidate_archive(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "module-manager-v2-server-3.2.7.zip"
    write_release_archive(
        verifier,
        archive_path,
        manifest_version="3.2.7",
        static_version="3.2.7",
    )

    with pytest.raises(AssertionError, match="V3.2.8"):
        verifier.verify_package(archive_path)


def test_release_builder_excludes_runtime_uploads_before_recursive_app_copy() -> None:
    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(encoding="utf-8")

    assert 'if ($Source -eq "v2-api\\app")' in build_script
    assert "robocopy" in build_script
    assert '"static\\uploads"' in build_script


def test_release_builder_generates_0016_irreversible_migration_warning() -> None:
    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(encoding="utf-8")

    assert "V3.1-V3.2 migrations ``0006`` through ``0016`` are production-irreversible" in build_script


def write_release_archive(
    verifier,
    archive_path: Path,
    *,
    manifest_version: str | None = "3.2.8",
    manifest_versions: list[str] | None = None,
    static_version: str = "3.2.8",
    title_version: str | None = None,
    runtime_version: str | None = None,
    source_version: str | None = None,
    entry_version: str | None = None,
    entry_source: str | None = None,
    duplicate_entry: bool = False,
    runtime_entry_sha256: str | None = None,
    unrelated_chunk_entry_version: str = "",
    unrelated_static_version: str = "",
    unrelated_index_text: str = "",
    agents: str = VALID_AGENTS,
    release_record: str = PENDING_RELEASE_RECORD,
    source_commit: str = VALID_SOURCE_COMMIT,
    omitted: set[str] | None = None,
    content_overrides: dict[str, str | bytes] | None = None,
) -> None:
    omitted_names = set(omitted or set())
    names = (set(verifier.REQUIRED_FILES) | {RUNTIME_VERSION_ARTIFACT, SOURCE_VERSION_ARTIFACT}) - omitted_names
    versions = manifest_versions
    if versions is None:
        versions = [] if manifest_version is None else [manifest_version]
    version_lines = [f"- Version: {version}" for version in versions]
    manifest = "\n".join(
        (
            "# Release manifest",
            *version_lines,
            *SAFETY_NOTES,
            "- V3.1-V3.2 migrations `0006` through `0016` are production-irreversible.",
        )
    )
    resolved_runtime_version = runtime_version or static_version
    resolved_source_version = source_version or resolved_runtime_version
    resolved_entry_version = entry_version or resolved_runtime_version
    resolved_title_version = title_version or static_version
    resolved_document_version = versions[0] if len(versions) == 1 else resolved_source_version
    resolved_entry_source = entry_source or (
        "globalThis.__MODULE_MANAGER_VUE_ENTRY_ATTESTATION__="
        f'{{"version":"{resolved_entry_version}"}};\n'
        f"const unrelatedReleaseNote = '{unrelated_static_version}';\n"
        "const collectorScanner = '/static/vendor/quagga.min.js?v=20260615-quagga2';\n"
    )
    contents = {
        "SOURCE_COMMIT": source_commit,
        "RELEASE_MANIFEST.md": manifest,
        "AGENTS.md": agents,
        "README.md": f".\\scripts\\build-client-release.ps1 -Version {resolved_document_version}",
        "docs/CLIENT_FINAL_AUDIT.md": (ROOT / "docs/CLIENT_FINAL_AUDIT.md").read_text(encoding="utf-8"),
        V326_BASELINE_RELEASE_RECORD: deployed_release_record(
            "3.2.6",
            "Status: reviewed, packaged, deployed, and verified in production",
        ),
        V324_RELEASE_RECORD: (ROOT / V324_RELEASE_RECORD).read_text(encoding="utf-8"),
        V327_RELEASE_RECORD: (ROOT / V327_RELEASE_RECORD).read_text(encoding="utf-8"),
        V328_RELEASE_RECORD: release_record,
        SOURCE_VERSION_ARTIFACT: json.dumps(
            {"version": resolved_source_version}, separators=(",", ":")
        ),
        "v2-api/app/static/vue/index.html": (
            f"<!doctype html><title>Module Manager V{resolved_title_version}</title>"
            f'<script type="module" src="/vue/assets/app.js"></script>{unrelated_index_text}'
        ),
        "v2-api/app/static/vue/assets/app.js": resolved_entry_source,
    }
    if unrelated_chunk_entry_version:
        contents["v2-api/app/static/vue/assets/unrelated.js"] = (
            "globalThis.__MODULE_MANAGER_VUE_ENTRY_ATTESTATION__="
            f'{{"version":"{unrelated_chunk_entry_version}"}};\n'
        )
    archive_contents = {
        name: (
            (ROOT / name).read_bytes()
            if name in KPI_SOURCE_PATHS or name in V328_ARCHIVE_SOURCE_FILES
            else contents.get(name, "fixture\n")
        )
        for name in names
        if name != RUNTIME_VERSION_ARTIFACT
    }
    archive_contents.update(content_overrides or {})
    if SOURCE_VERSION_ARTIFACT in names and SOURCE_VERSION_ARTIFACT not in (content_overrides or {}):
        archive_contents[SOURCE_VERSION_ARTIFACT] = contents[SOURCE_VERSION_ARTIFACT]
    archive_contents["v2-api/app/static/vue/assets/app.js"] = resolved_entry_source
    if unrelated_chunk_entry_version:
        archive_contents["v2-api/app/static/vue/assets/unrelated.js"] = contents[
            "v2-api/app/static/vue/assets/unrelated.js"
        ]
    vue_prefix = "v2-api/app/static/vue/"
    assets = []
    for name, content in sorted(archive_contents.items()):
        if not name.startswith(vue_prefix):
            continue
        encoded = content.encode("utf-8") if isinstance(content, str) else content
        assets.append(
            {
                "path": name.removeprefix(vue_prefix),
                "size": len(encoded),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            }
        )
    resolved_entry_sha256 = runtime_entry_sha256 or hashlib.sha256(
        resolved_entry_source.encode("utf-8")
    ).hexdigest()
    if RUNTIME_VERSION_ARTIFACT in names:
        archive_contents[RUNTIME_VERSION_ARTIFACT] = json.dumps(
            {
                "version": resolved_runtime_version,
                "entry": "assets/app.js",
                "entrySha256": resolved_entry_sha256,
                "assets": assets,
            }
        )
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, content in sorted(archive_contents.items()):
            archive.writestr(name, content)
        if duplicate_entry:
            archive.writestr("v2-api/app/static/vue/assets/app.js", resolved_entry_source)


def test_archive_missing_v3081_historical_release_record_fails_verification(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "module-manager-v2-server-v3.0.81.zip"
    write_release_archive(verifier, archive_path, omitted={"ops/releases/V3.0.81.md"})

    with pytest.raises(AssertionError, match=r"ops/releases/V3\.0\.81\.md"):
        verifier.verify_package(archive_path)


def test_archive_missing_v326_candidate_release_record_fails_verification(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "module-manager-v2-server-v3.2.6.zip"
    write_release_archive(verifier, archive_path, omitted={V326_RELEASE_RECORD})

    with pytest.raises(AssertionError, match=re.escape(V326_RELEASE_RECORD)):
        verifier.verify_package(archive_path)


def test_archive_missing_v324_historical_release_record_fails_verification(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "module-manager-v2-server-v3.2.6.zip"
    write_release_archive(verifier, archive_path, omitted={V324_RELEASE_RECORD})

    with pytest.raises(AssertionError, match=re.escape(V324_RELEASE_RECORD)):
        verifier.verify_package(archive_path)


def test_archive_missing_v323_historical_release_record_fails_verification(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "module-manager-v2-server-v3.2.6.zip"
    write_release_archive(verifier, archive_path, omitted={V323_RELEASE_RECORD})

    with pytest.raises(AssertionError, match=re.escape(V323_RELEASE_RECORD)):
        verifier.verify_package(archive_path)


def test_archive_missing_v3079_historical_release_record_fails_verification(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "module-manager-v2-server-v3.0.81.zip"
    write_release_archive(verifier, archive_path, omitted={V3079_RELEASE_RECORD})

    with pytest.raises(AssertionError, match=r"ops/releases/V3\.0\.79\.md"):
        verifier.verify_package(archive_path)


def test_release_builder_default_version_is_candidate_semantic_version() -> None:
    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(encoding="utf-8")

    assert '[string]$Version = "3.2.8"' in build_script


@pytest.mark.parametrize("version", ("3.2.7", "3.2.9"))
def test_release_builder_rejects_non_candidate_version_before_output_mutation(
    tmp_path: Path,
    version: str,
) -> None:
    script_root = tmp_path / "scripts"
    script_root.mkdir()
    copied_builder = script_root / "build-client-release.ps1"
    copied_builder.write_bytes((ROOT / "scripts" / "build-client-release.ps1").read_bytes())
    release_root = tmp_path / "build" / "server-release"
    staging = release_root / f"module-manager-v2-server-{version}"
    staging.mkdir(parents=True)
    staging_sentinel = staging / "sentinel.txt"
    staging_sentinel.write_text("preserve staging", encoding="utf-8")
    archive = release_root / f"module-manager-v2-server-{version}.zip"
    archive.write_bytes(b"preserve archive")

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(copied_builder),
            "-Version",
            version,
            "-SkipSmoke",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert "Expected exactly 3.2.8" in output
    assert staging_sentinel.read_text(encoding="utf-8") == "preserve staging"
    assert archive.read_bytes() == b"preserve archive"


def test_release_builder_manifest_reports_optional_performance_evidence_truthfully(
    tmp_path: Path,
) -> None:
    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(encoding="utf-8")
    failures: list[str] = []
    function_text = load_v320_release_verifier().powershell_function_text(
        build_script,
        "Get-PerformanceEvidenceManifestLine",
        "scripts/build-client-release.ps1",
        failures,
    )
    assert not failures
    harness = "\n".join(
        (
            function_text,
            "$results = @(",
            "    (Get-PerformanceEvidenceManifestLine -Verified $false),",
            "    (Get-PerformanceEvidenceManifestLine -Verified $true)",
            ")",
            "$results | ConvertTo-Json -Compress",
        )
    )
    harness_path = tmp_path / "performance-manifest-contract.ps1"
    harness_path.write_text(harness, encoding="utf-8")

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    without_report, with_report = json.loads(completed.stdout)
    assert "not supplied" in without_report
    assert "not run" in without_report
    assert "passes" not in without_report
    assert "passes the release verifier" in with_report


def test_release_builder_embeds_the_current_source_commit() -> None:
    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(encoding="utf-8")

    assert build_script.count("git rev-parse HEAD") >= 2
    assert "git status --porcelain --untracked-files=all" in build_script
    assert 'Join-Path $staging "SOURCE_COMMIT"' in build_script
    assert "source commit or worktree changed during packaging" in build_script
    assert "verify-client-release.py $zipPath --expected-source-commit $sourceCommit" in build_script


def test_release_builder_checks_cleanliness_before_building_into_isolated_staging() -> None:
    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(encoding="utf-8")
    vite_config = (ROOT / "v2-web" / "vite.config.ts").read_text(encoding="utf-8")

    clean_check = build_script.index("git status --porcelain --untracked-files=all")
    dependency_build = build_script.index("-m pip install")
    vue_build = build_script.index('Write-Host "Building Vue production bundle..."')
    create_staging = build_script.index("New-Item -ItemType Directory -Force -Path $staging")
    copy_api = build_script.index('Copy-ReleaseItem "v2-api\\app" "v2-api\\app"')

    assert clean_check < dependency_build < vue_build
    assert create_staging < copy_api < vue_build
    assert '$stagedVueDir = Join-Path $staging "v2-api\\app\\static\\vue"' in build_script
    assert "$env:MODULE_MANAGER_VUE_OUT_DIR = $stagedVueDir" in build_script
    assert "process.env.MODULE_MANAGER_VUE_OUT_DIR" in vite_config


def test_release_builder_guards_candidate_version_before_output_mutation() -> None:
    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(encoding="utf-8")

    candidate_guard = build_script.index("Expected exactly 3.2.8")
    release_root = build_script.index('$releaseRoot = Join-Path $root "build\\server-release"')
    remove_archive = build_script.index("Remove-Item -Force -LiteralPath $zipPath")
    first_validation = build_script.index('Write-Host "Verifying administrator release notes..."')

    assert candidate_guard < release_root < remove_archive < first_validation


def test_archive_members_must_be_tracked_by_the_expected_source_commit() -> None:
    verifier = load_verifier()
    verify_members = getattr(verifier, "verify_archive_members_are_tracked", None)
    assert callable(verify_members), "release verifier must validate every archive member against SOURCE_COMMIT"
    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()

    verify_members({"SOURCE_COMMIT", "README.md"}, source_commit)
    with pytest.raises(AssertionError, match="not tracked by SOURCE_COMMIT"):
        verify_members(
            {"SOURCE_COMMIT", "README.md", "v2-api/app/ignored-debug.log"},
            source_commit,
        )


def test_generated_vue_assets_are_bound_by_manifest_instead_of_git_membership() -> None:
    verifier = load_verifier()
    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()

    verifier.verify_archive_members_are_tracked(
        {
            "SOURCE_COMMIT",
            "README.md",
            "v2-api/app/static/vue/index.html",
            "v2-api/app/static/vue/assets/index-generated-hash.js",
        },
        source_commit,
    )



def test_archive_rejects_missing_source_commit(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "missing-source-commit.zip"
    write_release_archive(verifier, archive_path, omitted={"SOURCE_COMMIT"})

    with pytest.raises(AssertionError, match="SOURCE_COMMIT"):
        verifier.verify_package(archive_path)


def test_archive_rejects_a_different_expected_source_commit(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "mismatched-source-commit.zip"
    write_release_archive(verifier, archive_path)

    with pytest.raises(AssertionError, match="does not match expected commit"):
        verifier.verify_package(archive_path, expected_source_commit="c" * 40)


def test_v3083_feature_verifiers_are_packaged_and_required() -> None:
    verifier = load_verifier()
    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(encoding="utf-8")
    feature_verifiers = {
        "scripts/verify_claim_tasks_construction_priority.js",
        "scripts/verify_construction_priority_import_dialog.js",
        "scripts/verify_review_image_inspector.js",
    }

    assert feature_verifiers <= verifier.REQUIRED_FILES
    for verifier_path in feature_verifiers:
        windows_path = verifier_path.replace("/", "\\")
        assert f'Copy-ReleaseItem "{windows_path}" "{windows_path}"' in build_script


def test_v3084_backend_performance_verifier_is_packaged_and_required() -> None:
    verifier = load_verifier()
    acceptance_script = (ROOT / "scripts" / "run-client-acceptance-gate.ps1").read_text(encoding="utf-8")

    assert "v2-api/scripts/verify_task_review_performance.py" in verifier.REQUIRED_FILES
    assert "v2-api\\scripts\\verify_task_review_performance.py" in acceptance_script
    assert "$sourceCommit = (& git rev-parse HEAD).Trim().ToLowerInvariant()" in acceptance_script
    assert "verify-client-release.py $zipPath --expected-source-commit $sourceCommit" in acceptance_script


def test_v31_release_requires_barcode_enqueue_unit_and_all_queue_migrations() -> None:
    verifier = load_verifier()
    required = {
        "infra/module-manager-v2-photo-barcode-maintenance-enqueue.service",
        "v2-api/alembic/versions/0006_group_barcode_verification.py",
        "v2-api/alembic/versions/0007_group_barcode_verification_lease_token.py",
        "v2-api/alembic/versions/0008_delivery_cache_jobs.py",
        "v2-api/alembic/versions/0009_delivery_cache_fix3.py",
        "v2-api/alembic/versions/0010_auto_archive_queue_state.py",
        "v2-api/alembic/versions/0011_delivery_package_jobs.py",
        "v2-api/alembic/versions/0012_delivery_package_group_ids_gin.py",
    }

    assert required <= verifier.REQUIRED_FILES


def test_v320_release_inputs_are_packaged_and_required() -> None:
    verifier = load_verifier()
    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(encoding="utf-8")
    release_verifier = (ROOT / "scripts" / "verify_v3_2_0_release.py").read_text(
        encoding="utf-8"
    )
    required = {
        "scripts/verify_v3_2_0_role_routes.py",
        "scripts/verify_v3_2_0_data_center_ui.py",
        "scripts/verify_v3_2_0_dashboard_drilldown.py",
        "scripts/verify_v3_2_0_export_center_ui.py",
        "scripts/verify_v3_2_0_single_export_entry.py",
        "scripts/verify_v3_2_0_release.py",
        "v2-api/alembic/versions/0013_data_center_query_indexes.py",
        "v2-api/alembic/versions/0014_export_center_jobs.py",
        "v2-api/app/schemas/data_center.py",
        "v2-api/app/schemas/export_center.py",
        "v2-api/app/services/construction_task_rules.py",
        "v2-api/app/services/data_center.py",
        "v2-api/app/services/export_center.py",
        "v2-web/src/components/data-center/DataCenterFilters.vue",
        "v2-web/src/components/data-center/DataCenterReviewDialog.vue",
        "v2-web/src/views/GlobalSearchView.vue",
        "ops/releases/V3.2.0.md",
    }

    assert required <= verifier.REQUIRED_FILES
    for path in required:
        assert path.replace("/", "\\") in build_script
        assert f'"{path}"' in release_verifier


def test_v321_installer_kpi_release_inputs_are_packaged_and_required() -> None:
    verifier = load_verifier()
    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(encoding="utf-8")
    required = {
        "scripts/verify_v3_2_1_installer_kpi_restore.py",
        "scripts/verify_v3_2_2_release.py",
        "v2-web/src/components/InstallerKpiDialog.vue",
        "v2-web/src/utils/installerKpi.ts",
        "ops/releases/V3.2.2.md",
    }

    assert required <= verifier.REQUIRED_FILES
    for path in required:
        assert path.replace("/", "\\") in build_script


def test_v327_contract_inputs_are_packaged_and_required() -> None:
    verifier = load_verifier()
    required = {
        "AGENTS.md",
        "RELEASE_MANIFEST.md",
        "ops/releases/V3.2.7.md",
        "scripts/build-client-release.ps1",
        "scripts/verify-client-release.py",
        "scripts/verify_release_sop.py",
        "scripts/verify_v3_2_7_release.py",
        "scripts/test_verify_v3_2_7_release.py",
        "docs/superpowers/specs/2026-08-23-collector-transfer-workbench-design.md",
        "v2-api/alembic/versions/0015_collector_transfer_workbench.py",
        "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py",
        "v2-api/app/api/routes/collector_transfer.py",
        "v2-api/app/main.py",
        "v2-api/app/models.py",
        "v2-api/app/services/collector_transfer.py",
        "v2-api/app/services/ops_status.py",
        "v2-api/pyproject.toml",
        "v2-api/scripts/verify_v3_1_release.py",
        "v2-api/tests/test_collector_transfer_api.py",
        "v2-api/tests/test_collector_transfer_service.py",
        "v2-api/tests/test_v3_1_release.py",
        "v2-web/index.html",
        "v2-web/src/api/services.ts",
        "v2-web/src/api/types.ts",
        "v2-web/src/components/AppLayout.vue",
        "v2-web/src/constants/releaseNotes.ts",
        "v2-web/src/views/CollectorInventoryView.vue",
    }

    assert required <= verifier.REQUIRED_FILES
    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(encoding="utf-8")
    assert (
        'Copy-ReleaseItem "docs\\superpowers\\specs\\2026-08-23-collector-transfer-workbench-design.md" '
        '"docs\\superpowers\\specs\\2026-08-23-collector-transfer-workbench-design.md"'
        in build_script
    )


def test_archive_runs_v328_contract_against_archived_sources(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "broken-v328-contract.zip"
    write_release_archive(
        verifier,
        archive_path,
        content_overrides={
            "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py": "revision = 'broken'\n",
        },
    )

    with pytest.raises(AssertionError, match="V3.2.8 archive source contract"):
        verifier.verify_package(archive_path)


def test_v321_kpi_sources_are_pinned_to_lf() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "v2-web/src/components/InstallerKpiDialog.vue text eol=lf" in attributes
    assert "v2-web/src/utils/installerKpi.ts text eol=lf" in attributes


def test_valid_pending_candidate_archive_contains_reviewed_kpi_bytes(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "valid-reviewed-kpi.zip"
    write_release_archive(verifier, archive_path)

    with zipfile.ZipFile(archive_path) as archive:
        for relative_path in KPI_SOURCE_PATHS:
            assert archive.read(relative_path) == (ROOT / relative_path).read_bytes()

    verifier.verify_package(archive_path)


def test_v328_build_sequence_executes_current_and_compatible_release_gates_only() -> None:
    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(encoding="utf-8")
    match = re.search(r"\$releaseVerifiers\s*=\s*@\((?P<items>[\s\S]*?)\n\)", build_script)

    assert match is not None
    release_verifiers = match.group("items")
    expected = (
        "scripts\\verify_v3_2_0_role_routes.py",
        "scripts\\verify_v3_2_0_data_center_ui.py",
        "scripts\\verify_v3_2_0_dashboard_drilldown.py",
        "scripts\\verify_v3_2_0_export_center_ui.py",
        "scripts\\verify_v3_2_0_single_export_entry.py",
        "scripts\\verify_v3_2_1_installer_kpi_restore.py",
        "scripts\\verify_v3_2_8_release.py",
    )
    for verifier_path in expected:
        assert verifier_path in release_verifiers
    assert "scripts\\verify_v3_2_0_release.py" not in release_verifiers
    assert "scripts\\verify_v3_2_2_release.py" not in release_verifiers
    assert "scripts\\verify_v3_2_3_release.py" not in release_verifiers
    assert "scripts\\verify_v3_2_4_release.py" not in release_verifiers
    assert '"scripts\\verify_v3_2_3_release.py"' in build_script
    assert (
        'Copy-ReleaseItem "scripts\\verify_v3_2_3_release.py" "scripts\\verify_v3_2_3_release.py"'
        in build_script
    )
    assert (
        'Copy-ReleaseItem "scripts\\verify_v3_2_4_release.py" "scripts\\verify_v3_2_4_release.py"'
        in build_script
    )


def test_v321_manifest_keeps_candidate_artifact_evidence_pending() -> None:
    verifier = load_v321_release_verifier()
    manifest = (ROOT / "RELEASE_MANIFEST.md").read_text(encoding="utf-8")
    failures: list[str] = []

    verifier.verify_manifest_pending_truth(manifest, failures)

    assert failures == []
    stale = manifest.replace("- SHA256: pending", "- SHA256: `2A05A337D20982BF67B750D4EB7E48C137FCDAD902668636A7B513C1E456BA2B`")
    failures = []
    verifier.verify_manifest_pending_truth(stale, failures)
    assert failures == ["RELEASE_MANIFEST.md: must not retain V3.2.1 artifact evidence"]


@pytest.mark.parametrize("local_verification", ("not run", "passed"))
def test_v321_pending_record_accepts_prepackage_local_verification_states(
    local_verification: str,
) -> None:
    verifier = load_v321_release_verifier()
    record = V322_PENDING_RELEASE_RECORD
    candidate = re.sub(
        r"(?m)^- Local Verification: .*?$",
        f"- Local Verification: {local_verification}",
        record,
    )
    failures: list[str] = []

    verifier.verify_pending_record(candidate, failures)

    assert failures == []


@pytest.mark.parametrize(
    ("candidate", "expected_matches"),
    (
        ("- Local Verification: failed", ["failed"]),
        ("- Local Verification: passed\n- Local Verification: passed", ["passed", "passed"]),
    ),
)
def test_v321_pending_record_rejects_invalid_or_duplicate_local_verification(
    candidate: str,
    expected_matches: list[str],
) -> None:
    verifier = load_v321_release_verifier()
    record = V322_PENDING_RELEASE_RECORD
    candidate_record = re.sub(r"(?m)^- Local Verification: .*?$", candidate, record)
    failures: list[str] = []

    verifier.verify_pending_record(candidate_record, failures)

    assert failures == [
        "ops/releases/V3.2.2.md: Local Verification must equal one of "
        f"('not run', 'passed') exactly once; got {expected_matches!r}"
    ]


@pytest.mark.parametrize(
    "claim",
    (
        "Deployment completed.",
        "Deployment succeeded.",
        "Deployment was successful.",
        "Deployment has succeeded.",
        "Production verified.",
        "Production verification completed.",
        "Production verification was completed.",
        "The release is live.",
        "已部署。",
        "已上线。",
        "部署完成。",
        "部署已完成。",
        "已完成部署。",
        "部署成功。",
        "上线完成。",
        "生产验证通过。",
    ),
)
def test_v321_pending_record_rejects_english_and_chinese_affirmative_deployment_claims(claim: str) -> None:
    verifier = load_v321_release_verifier()
    record = V322_PENDING_RELEASE_RECORD
    failures: list[str] = []

    verifier.verify_pending_record(f"{record}\n- {claim}\n", failures)

    assert failures == ["ops/releases/V3.2.2.md: pending candidate must not claim deployment"]


@pytest.mark.parametrize(
    ("relative_path", "mutate", "expected_failure"),
    (
        (
            "v2-web/src/components/InstallerKpiDialog.vue",
            lambda text: text.replace(
                "import { fetchInstallerWorkload } from '@/api/services'",
                "import { fetchInstallerWorkload, createExportJob as queuedExport } from '@/api/services'",
            ),
            "source integrity mismatch",
        ),
        (
            "v2-web/src/components/InstallerKpiDialog.vue",
            lambda text: text.replace(
                "const requestGate = createInstallerKpiRequestGate()",
                "void fetch('/exports')\nconst requestGate = createInstallerKpiRequestGate()",
            ),
            "source integrity mismatch",
        ),
        (
            "v2-web/src/utils/installerKpi.ts",
            lambda text: "import axios from 'axios'\nvoid axios.post('/exports')\n" + text,
            "source integrity mismatch",
        ),
        (
            "v2-web/src/utils/installerKpi.ts",
            lambda text: "const forbiddenRoute = '/export-jobs'\n" + text,
            "source integrity mismatch",
        ),
        (
            "v2-web/src/utils/installerKpi.ts",
            lambda text: "import { queueExport as run } from '@/lib/exporter'\nrun()\n" + text,
            "source integrity mismatch",
        ),
        (
            "v2-web/src/utils/installerKpi.ts",
            lambda text: "import '@/lib/exporter'\n" + text,
            "source integrity mismatch",
        ),
        (
            "v2-web/src/utils/installerKpi.ts",
            lambda text: "const { queueExport: run } = await import('@/lib/exporter')\nrun()\n" + text,
            "source integrity mismatch",
        ),
        (
            "v2-web/src/utils/installerKpi.ts",
            lambda text: "const { queueExport: run } = await import('@/lib/' + 'exporter')\nrun()\n" + text,
            "source integrity mismatch",
        ),
        (
            "v2-web/src/utils/installerKpi.ts",
            lambda text: "import/*comment*/{ run }from '@/lib/sideEffects'; run()\n" + text,
            "source integrity mismatch",
        ),
        (
            "v2-web/src/utils/installerKpi.ts",
            lambda text: "const sideEffects = await import/*comment*/('@/lib/sideEffects')\n" + text,
            "source integrity mismatch",
        ),
    ),
)
def test_v321_kpi_source_integrity_rejects_prior_parser_and_write_export_mutations(
    relative_path,
    mutate,
    expected_failure,
) -> None:
    verifier = load_v321_release_verifier()
    source = (ROOT / relative_path).read_text(encoding="utf-8")
    failures: list[str] = []

    verifier.verify_kpi_source_contract(relative_path, mutate(source), failures)

    assert len(failures) == 1
    assert any(expected_failure in failure for failure in failures)


@pytest.mark.parametrize(
    ("relative_path", "mutate", "expected_failure"),
    (
        (
            "v2-web/src/components/InstallerKpiDialog.vue",
            lambda text: text.replace(
                "import { fetchInstallerWorkload } from '@/api/services'",
                "import { fetchInstallerWorkload, createExportJob } from '@/api/services'",
            ),
            "missing",
        ),
        (
            "v2-web/src/components/InstallerKpiDialog.vue",
            lambda text: "void fetch('/exports')\n" + text,
            "must not make direct network calls",
        ),
        (
            "v2-web/src/utils/installerKpi.ts",
            lambda text: "client.delete('/workload')\n" + text,
            "must not call write methods",
        ),
        (
            "v2-web/src/utils/installerKpi.ts",
            lambda text: "queueInstallerExport()\n" + text,
            "must not call export-job helpers",
        ),
        (
            "v2-web/src/utils/installerKpi.ts",
            lambda text: "const forbiddenRoute = '/export-jobs'\n" + text,
            "must not reference export routes",
        ),
    ),
)
def test_v321_kpi_source_semantics_keep_client_write_and_export_defense_in_depth(
    relative_path,
    mutate,
    expected_failure,
) -> None:
    verifier = load_v321_release_verifier()
    source = (ROOT / relative_path).read_text(encoding="utf-8")
    failures: list[str] = []

    verifier.verify_kpi_source_semantics(relative_path, mutate(source), failures)

    assert any(expected_failure in failure for failure in failures)


def test_v321_kpi_source_integrity_rejects_template_quasi_span_bypass() -> None:
    verifier = load_v321_release_verifier()
    relative_path = "v2-web/src/utils/installerKpi.ts"
    source = (ROOT / relative_path).read_text(encoding="utf-8")
    mutation = """async function probe() {
  return `
import type ${await import('@/lib/sideEffects')} from '@/api/types'
`;
}
"""
    failures: list[str] = []

    verifier.verify_kpi_source_contract(relative_path, mutation + source, failures)

    assert len(failures) == 1
    assert failures[0].startswith(f"{relative_path}: source integrity mismatch:")
    assert "import" not in failures[0]


def test_v321_kpi_source_integrity_does_not_misclassify_contextual_regex() -> None:
    verifier = load_v321_release_verifier()
    relative_path = "v2-web/src/utils/installerKpi.ts"
    source = (ROOT / relative_path).read_text(encoding="utf-8")
    mutation = r"if (enabled) {} /import\(/.test(label);" + "\n"
    failures: list[str] = []

    verifier.verify_kpi_source_contract(relative_path, mutation + source, failures)

    assert len(failures) == 1
    assert failures[0].startswith(f"{relative_path}: source integrity mismatch:")
    assert "import" not in failures[0]


@pytest.mark.parametrize(
    "relative_path",
    (
        "v2-web/src/components/InstallerKpiDialog.vue",
        "v2-web/src/utils/installerKpi.ts",
    ),
)
def test_v321_kpi_source_integrity_rejects_harmless_source_mutations(
    relative_path: str,
) -> None:
    verifier = load_v321_release_verifier()
    source = (ROOT / relative_path).read_text(encoding="utf-8")
    failures: list[str] = []

    verifier.verify_kpi_source_contract(
        relative_path,
        source + "\n// harmless release-gate integrity mutation\n",
        failures,
    )

    assert len(failures) == 1
    assert failures[0].startswith(f"{relative_path}: source integrity mismatch:")
    assert "import" not in failures[0]


def test_v321_kpi_source_integrity_supersedes_string_import_parser_control() -> None:
    verifier = load_v321_release_verifier()
    source = (ROOT / "v2-web/src/utils/installerKpi.ts").read_text(encoding="utf-8")
    failures: list[str] = []

    verifier.verify_kpi_source_contract(
        "v2-web/src/utils/installerKpi.ts",
        "const explanatoryText = \"import('@/lib/exporter') is forbidden\"\n" + source,
        failures,
    )

    assert len(failures) == 1
    assert "source integrity mismatch" in failures[0]
    assert "unrecognized import syntax" not in failures[0]


@pytest.mark.parametrize(
    "template_expression",
    (
        "async function probe() { return `${await import('@/lib/sideEffects')}` }\n",
        (
            "async function probe() { return "
            "`outer ${await import('@/lib/sideEffects') ? `inner ${value}` : ''}` }\n"
        ),
        "async function probe() { return `outer ${`inner ${await import('@/lib/sideEffects')}`}` }\n",
    ),
)
def test_v321_kpi_source_integrity_supersedes_template_import_parser_controls(
    template_expression: str,
) -> None:
    verifier = load_v321_release_verifier()
    source = (ROOT / "v2-web/src/utils/installerKpi.ts").read_text(encoding="utf-8")
    failures: list[str] = []

    verifier.verify_kpi_source_contract(
        "v2-web/src/utils/installerKpi.ts",
        template_expression + source,
        failures,
    )

    assert len(failures) == 1
    assert "source integrity mismatch" in failures[0]
    assert "unrecognized import syntax" not in failures[0]


def test_v321_kpi_source_integrity_supersedes_regex_import_parser_control() -> None:
    verifier = load_v321_release_verifier()
    source = (ROOT / "v2-web/src/utils/installerKpi.ts").read_text(encoding="utf-8")
    failures: list[str] = []

    verifier.verify_kpi_source_contract(
        "v2-web/src/utils/installerKpi.ts",
        r"const importPattern = /import\(/;" + "\n" + source,
        failures,
    )

    assert len(failures) == 1
    assert "source integrity mismatch" in failures[0]
    assert "unrecognized import syntax" not in failures[0]


def test_v320_release_verifies_the_real_admin_system_status_route() -> None:
    release_verifier = (ROOT / "scripts" / "verify_v3_2_0_release.py").read_text(
        encoding="utf-8"
    )

    assert '"/local-test/system/status"' in release_verifier
    assert '"/system/status/version"' not in release_verifier


def test_v320_deployed_evidence_gate_accepts_the_recorded_production_values() -> None:
    verifier = load_v320_release_verifier()
    record = (ROOT / "ops" / "releases" / "V3.2.0.md").read_text(encoding="utf-8")
    failures: list[str] = []

    verifier.verify_deployed_release_evidence(record, failures)

    assert failures == []


@pytest.mark.parametrize(
    ("field", "original", "replacement", "correct_value"),
    [
        (
            "Package",
            "- Package: verified",
            "- Package: pending",
            "verified",
        ),
        (
            "Production Deployment",
            "- Production Deployment: deployed",
            "- Production Deployment: pending",
            "deployed",
        ),
        (
            "SHA256",
            "| SHA256 | 9448EDDCA27A36F2DF606EC1BC04A3BED05930B3D4D718E2D10381EE7FAEE6DF |",
            f"| SHA256 | {'0' * 64} |",
            "9448EDDCA27A36F2DF606EC1BC04A3BED05930B3D4D718E2D10381EE7FAEE6DF",
        ),
        (
            "Source commit",
            "| Source commit | `fe527eb84064096321e727abf9ccbdc981e10b7e` |",
            f"| Source commit | `{'0' * 40}` |",
            "fe527eb84064096321e727abf9ccbdc981e10b7e",
        ),
        (
            "Backup directory",
            "| Backup directory | /opt/module-manager-v2/backups/V3.2.0-pre-20260724_105349 |",
            "| Backup directory | /opt/module-manager-v2/backups/wrong-backup |",
            "/opt/module-manager-v2/backups/V3.2.0-pre-20260724_105349",
        ),
        (
            "Release directory",
            "| Release directory | /opt/module-manager-v2/releases/v3.2.0-20260724_105649 |",
            "| Release directory | /opt/module-manager-v2/releases/missing-release |",
            "/opt/module-manager-v2/releases/v3.2.0-20260724_105649",
        ),
        (
            "Rollback target",
            "- Rollback target: `/opt/module-manager-v2/releases/v3.2.0-20260724_095503`",
            "- Rollback target: `/opt/module-manager-v2/releases/missing-rollback`",
            "/opt/module-manager-v2/releases/v3.2.0-20260724_095503",
        ),
        (
            "Full test result",
            "| Full test result | 1782 passed, 13 skipped |",
            "| Full test result | 1 passed |",
            "1782 passed, 13 skipped",
        ),
        (
            "Required files",
            "| Required files | 167 |",
            "| Required files | 166 |",
            "167",
        ),
        (
            "Independent review",
            "| Independent review | Critical 0 / Important 0 / Minor 1，结论可发布 |",
            "| Independent review | Critical 0 / Important 2 / Minor 0，结论不可发布 |",
            "Critical 0 / Important 0 / Minor 1，结论可发布",
        ),
    ],
)
def test_v320_deployed_evidence_gate_binds_values_to_their_fields(
    field: str,
    original: str,
    replacement: str,
    correct_value: str,
) -> None:
    verifier = load_v320_release_verifier()
    record = (ROOT / "ops" / "releases" / "V3.2.0.md").read_text(encoding="utf-8")
    assert original in record
    mutated = record.replace(original, replacement, 1)
    mutated += f"\nUnstructured note containing the old value: {correct_value}\n"
    failures: list[str] = []

    verifier.verify_deployed_release_evidence(mutated, failures)

    assert any(field in failure for failure in failures)


@pytest.mark.parametrize(
    "marker",
    [
        "PENDING_TASK_9",
        "Task 9 待完成",
        "* Package: pending",
        "- Package： pending",
        "Package: pending",
        "V3.2.0 候选生产验证",
    ],
)
def test_v320_deployed_evidence_gate_rejects_stale_or_contradictory_markers(
    marker: str,
) -> None:
    verifier = load_v320_release_verifier()
    record = (ROOT / "ops" / "releases" / "V3.2.0.md").read_text(encoding="utf-8")
    failures: list[str] = []

    verifier.verify_deployed_release_evidence(f"{record}\n{marker}\n", failures)

    assert failures


def test_v320_deployed_evidence_gate_requires_independent_review_exactly_once() -> None:
    verifier = load_v320_release_verifier()
    record = (ROOT / "ops" / "releases" / "V3.2.0.md").read_text(encoding="utf-8")
    duplicate = (
        f"{record}\n| Independent review | {verifier.INDEPENDENT_REVIEW} |\n"
    )
    failures: list[str] = []

    verifier.verify_deployed_release_evidence(duplicate, failures)

    assert any("Independent review" in failure for failure in failures)


def test_release_builder_stops_when_smoke_check_fails() -> None:
    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(encoding="utf-8")
    smoke_block = build_script.split("Running release smoke check before packaging...", maxsplit=1)[1]
    smoke_block = smoke_block.split("$releaseRoot", maxsplit=1)[0]

    assert "$LASTEXITCODE -ne 0" in smoke_block
    assert 'throw "Release smoke check failed."' in smoke_block


def test_admin_release_notes_gate_executes_against_machine_version_source() -> None:
    result = subprocess.run(
        ["node", "scripts/verify_admin_release_notes.js"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "admin release notes checks passed" in result.stdout


def test_package_and_acceptance_chains_execute_admin_release_notes_gate() -> None:
    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(encoding="utf-8")
    acceptance_script = (ROOT / "scripts" / "run-client-acceptance-gate.ps1").read_text(encoding="utf-8")

    command = "node .\\scripts\\verify_admin_release_notes.js"
    assert command in build_script
    assert command in acceptance_script


def test_acceptance_gate_derives_and_validates_machine_version_contract() -> None:
    acceptance_script = (ROOT / "scripts" / "run-client-acceptance-gate.ps1").read_text(encoding="utf-8")
    documents = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ["README.md", "RELEASE_MANIFEST.md", "docs/CLIENT_SIGNOFF_CHECKLIST.md"]
    )

    assert '[string]$Version = ""' in acceptance_script
    assert "v2-web\\src\\version.json" in acceptance_script
    assert "ConvertFrom-Json" in acceptance_script
    assert "must match the machine version source" in acceptance_script
    assert "final-delivery-ready" not in acceptance_script
    assert "final-delivery-ready" not in documents


def test_all_copied_operational_documents_reject_round8_stale_markers() -> None:
    verifier = load_verifier()
    document_paths = sorted(
        path
        for path in verifier.REQUIRED_FILES
        if path.endswith(".md")
    )

    assert document_paths
    for document_path in document_paths:
        content = (ROOT / document_path).read_text(encoding="utf-8")
        verifier.verify_release_markdown_text(document_path, content, "3.2.8")


@pytest.mark.parametrize(
    "document_path",
    ["README.md", "docs/CLIENT_ACCEPTANCE_REPORT.md", "docs/CLIENT_SIGNOFF_CHECKLIST.md"],
)
def test_current_operational_documents_validate_against_the_package_version(document_path: str) -> None:
    verifier = load_verifier()

    verifier.verify_release_markdown_text(
        document_path,
        (ROOT / document_path).read_text(encoding="utf-8"),
        "3.2.8",
    )


def test_readme_build_command_requires_current_candidate_version() -> None:
    verifier = load_verifier()
    incomplete_command = r".\scripts\build-client-release.ps1 -Version 3.2.6"

    with pytest.raises(AssertionError, match="non-current release version"):
        verifier.verify_release_markdown_text("README.md", incomplete_command, "3.2.8")


def test_client_final_audit_is_valid_only_as_version_locked_v320_history() -> None:
    verifier = load_verifier()

    verifier.verify_release_markdown_text(
        "docs/CLIENT_FINAL_AUDIT.md",
        (ROOT / "docs/CLIENT_FINAL_AUDIT.md").read_text(encoding="utf-8"),
        "3.2.6",
    )


@pytest.mark.parametrize(
    ("document_path", "content", "expected_version"),
    [
        ("README.md", ".\\scripts\\build-client-release.ps1 -Version 3.2.0", "3.2.6"),
        (
            "docs/CLIENT_FINAL_AUDIT.md",
            "\n".join(
                (
                    "# V3.2.0 生产发布审计",
                    "V3.2.0 是当前公网生产基线",
                    "build/server-release/module-manager-v2-server-3.2.2.zip",
                )
            ),
            "3.2.0",
        ),
    ],
)
def test_release_markdown_rejects_unexpected_current_or_locked_historical_versions(
    document_path: str,
    content: str,
    expected_version: str,
) -> None:
    verifier = load_verifier()

    with pytest.raises(AssertionError, match=rf"non-current release version .* expected {re.escape(expected_version)}"):
        verifier.verify_release_markdown_text(document_path, content, "3.2.6")


def test_archive_accepts_version_locked_client_final_audit_history(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "version-locked-history.zip"
    audit_history = (ROOT / "docs/CLIENT_FINAL_AUDIT.md").read_text(encoding="utf-8")

    write_release_archive(
        verifier,
        archive_path,
        content_overrides={"docs/CLIENT_FINAL_AUDIT.md": audit_history},
    )

    verifier.verify_package(archive_path)


def test_archive_rejects_relabelled_version_locked_client_final_audit_identity(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "relabelled-version-locked-history.zip"
    audit_history = (ROOT / "docs/CLIENT_FINAL_AUDIT.md").read_text(encoding="utf-8")
    relabelled_history = (
        audit_history.replace("# V3.2.0 生产发布审计", "# V3.2.1 生产发布审计")
        .replace("V3.2.0 是当前公网生产基线", "V3.2.1 是当前公网生产基线")
    )

    assert "module-manager-v2-server-3.2.0.zip" in relabelled_history
    write_release_archive(
        verifier,
        archive_path,
        content_overrides={"docs/CLIENT_FINAL_AUDIT.md": relabelled_history},
    )

    with pytest.raises(AssertionError, match="version-locked historical identity"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize(
    "document_path",
    sorted(path for path in load_verifier().REQUIRED_FILES if path.endswith(".md")),
)
def test_archive_rejects_stale_marker_in_every_required_markdown(
    tmp_path: Path,
    document_path: str,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / f"stale-markdown-{hashlib.sha256(document_path.encode()).hexdigest()[:8]}.zip"
    stale_content = "final-delivery-ready\n"
    if document_path == "RELEASE_MANIFEST.md":
            stale_content = "\n".join(("# Release manifest", "- Version: 3.2.6", *SAFETY_NOTES, stale_content))
    write_release_archive(
        verifier,
        archive_path,
        content_overrides={document_path: stale_content},
    )

    expected_message = (
        "Release manifest Version" if document_path == "RELEASE_MANIFEST.md" else re.escape(document_path)
    )
    with pytest.raises(AssertionError, match=expected_message):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize(
    "stale_text",
    [
        ".\\scripts\\build-client-release.ps1 -Version 3.0.39",
        "build/server-release/module-manager-v2-server-3.0.39.zip",
    ],
)
def test_archive_rejects_non_current_version_in_operational_document(
    tmp_path: Path,
    stale_text: str,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "stale-operational-version.zip"
    write_release_archive(
        verifier,
        archive_path,
        content_overrides={"README.md": stale_text},
    )

    with pytest.raises(AssertionError, match="non-current release version"):
        verifier.verify_package(archive_path)


def test_smoke_check_validates_current_server_release_signoff_package() -> None:
    smoke_check = (ROOT / "scripts" / "smoke-client-demo.py").read_text(encoding="utf-8")

    assert 'ROOT / "v2-web" / "src" / "version.json"' in smoke_check
    assert 'f"module-manager-v2-server-{release_version}.zip"' in smoke_check
    assert "module-manager-v2-client-demo-final-delivery-ready.zip" not in smoke_check
    assert 'check("retired demo reviewer rejected", reviewer.status_code == 401)' in smoke_check
    assert (
        '{"admin", "constructor"}'
        in smoke_check
    )
    assert 'check("demo reviewer login", reviewer.status_code == 200)' not in smoke_check
    assert 'reviewer.json()["data"]["user"]["home"]' not in smoke_check
    assert '"/unmatched": "/global-search?review=1"' in smoke_check
    assert '"/unmatched?embedded=1": "/global-search?review=1"' in smoke_check


def test_smoke_client_demo_executes_v323_retirement_and_retained_vue_contracts() -> None:
    """The release smoke must exercise live route responses, not a source marker."""
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["STATE_BACKEND"] = "json"
    environment["APP_ENV"] = "local"
    environment["DEMO_AUTH_ENABLED"] = "true"
    completed = subprocess.run(
        [sys.executable, "scripts/smoke-client-demo.py"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    output = completed.stdout + completed.stderr

    assert completed.returncode == 0, output
    for marker in (
        "[OK] /project-board returns 200",
        "[OK] /project-board serves Vue shell",
        "[OK] /claim-tasks returns 200",
        "[OK] /claim-tasks serves Vue shell",
        "[OK] /exports returns exact V3.2.3 retirement response",
    ):
        assert marker in completed.stdout


def test_smoke_client_demo_does_not_overwrite_the_callers_environment() -> None:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["STATE_BACKEND"] = "json"
    environment["APP_ENV"] = "local"
    environment["DEMO_AUTH_ENABLED"] = "false"
    probe = "\n".join(
        (
            "import os, runpy",
            "runpy.run_path('scripts/smoke-client-demo.py', run_name='smoke_contract_probe')",
            "print(os.environ['STATE_BACKEND'])",
            "print(os.environ['APP_ENV'])",
            "print(os.environ['DEMO_AUTH_ENABLED'])",
        )
    )

    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.splitlines()[-3:] == ["json", "local", "false"]


def test_archive_missing_manifest_version_fails_verification(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "missing-version.zip"
    write_release_archive(verifier, archive_path, manifest_version=None)

    with pytest.raises(AssertionError, match="exactly one semantic Version"):
        verifier.verify_package(archive_path)


def test_archive_manifest_version_must_match_static_version(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "static-version-mismatch.zip"
    write_release_archive(verifier, archive_path, static_version="3.0.80")

    with pytest.raises(AssertionError, match="static index title"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize(
    "manifest_versions",
    [
        ["3.0.81", "3.0.81"],
        ["3.0.81", "3.0.80"],
    ],
)
def test_archive_manifest_must_have_exactly_one_version(
    tmp_path: Path,
    manifest_versions: list[str],
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "duplicate-manifest-version.zip"
    write_release_archive(verifier, archive_path, manifest_versions=manifest_versions)

    with pytest.raises(AssertionError, match="exactly one semantic Version"):
        verifier.verify_package(archive_path)


def test_archive_manifest_version_must_be_semantic(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "non-semantic-manifest-version.zip"
    write_release_archive(verifier, archive_path, manifest_version="release-3.0.81")

    with pytest.raises(AssertionError, match="exactly one semantic Version"):
        verifier.verify_package(archive_path)


def test_archive_runtime_version_cannot_be_satisfied_by_unrelated_candidate_string(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "forged-runtime-version.zip"
    write_release_archive(
        verifier,
        archive_path,
        runtime_version="3.0.80",
        unrelated_static_version="3.0.81",
    )

    with pytest.raises(AssertionError, match="runtime version"):
        verifier.verify_package(archive_path)


def test_archive_requires_machine_readable_runtime_version_artifact(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "missing-runtime-version-artifact.zip"
    write_release_archive(verifier, archive_path, omitted={RUNTIME_VERSION_ARTIFACT})

    with pytest.raises(AssertionError, match="version.json"):
        verifier.verify_package(archive_path)


def test_archive_source_and_runtime_version_artifacts_must_match(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "source-runtime-version-mismatch.zip"
    write_release_archive(verifier, archive_path, source_version="3.0.80")

    with pytest.raises(AssertionError, match="V3.2.8 archive source contract|source and built runtime versions"):
        verifier.verify_package(archive_path)


def test_archive_rejects_stale_entry_bundle_despite_current_sidecars(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "stale-entry-bundle.zip"
    write_release_archive(
        verifier,
        archive_path,
        runtime_version="3.2.8",
        source_version="3.2.8",
        entry_version="3.2.4",
        unrelated_static_version="3.2.8",
        unrelated_chunk_entry_version="3.2.8",
    )

    with pytest.raises(AssertionError, match="entry bundle version"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize(
    "entry_source",
    [
        "/* globalThis.__MODULE_MANAGER_VUE_ENTRY_ATTESTATION__={\"version\":\"3.0.81\"}; */\n",
        "const unused = 'globalThis.__MODULE_MANAGER_VUE_ENTRY_ATTESTATION__={\"version\":\"3.0.81\"};';\n",
        "if (false) { globalThis.__MODULE_MANAGER_VUE_ENTRY_ATTESTATION__={\"version\":\"3.0.81\"}; }\n",
        "/* stale V3.0.80 entry */\nglobalThis.__MODULE_MANAGER_VUE_ENTRY_ATTESTATION__={\"version\":\"3.0.81\"};\n",
    ],
)
def test_archive_rejects_non_executable_or_stale_entry_markers(
    tmp_path: Path,
    entry_source: str,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "non-executable-entry-marker.zip"
    write_release_archive(verifier, archive_path, entry_source=entry_source)

    with pytest.raises(AssertionError, match="entry bundle"):
        verifier.verify_package(archive_path)


def test_archive_rejects_duplicate_entry_bundle_members(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "duplicate-entry-member.zip"
    write_release_archive(verifier, archive_path, duplicate_entry=True)

    with pytest.raises(AssertionError, match="duplicate"):
        verifier.verify_package(archive_path)


def test_archive_rejects_entry_marker_found_only_in_unrelated_chunk(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "unrelated-chunk-marker.zip"
    write_release_archive(
        verifier,
        archive_path,
        entry_source="console.log('entry without attestation');\n",
        unrelated_chunk_entry_version="3.0.81",
    )

    with pytest.raises(AssertionError, match="entry bundle"):
        verifier.verify_package(archive_path)


def test_archive_rejects_runtime_attestation_with_wrong_entry_digest(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "wrong-entry-digest.zip"
    write_release_archive(verifier, archive_path, runtime_entry_sha256="0" * 64)

    with pytest.raises(AssertionError, match="SHA-256"):
        verifier.verify_package(archive_path)


def test_archive_title_version_cannot_be_satisfied_by_unrelated_index_text(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "forged-title-version.zip"
    write_release_archive(
        verifier,
        archive_path,
        title_version="3.0.80",
        unrelated_index_text="<!-- Module Manager V3.0.81 -->",
    )

    with pytest.raises(AssertionError, match="static index title"):
        verifier.verify_package(archive_path)


def test_archive_rejects_contradictory_agents_deployed_markers(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "contradictory-agents.zip"
    agents = VALID_AGENTS.replace(
            "- Deployed production baseline: `V3.2.7`.",
        "- Deployed production baseline: `V3.2.3`.",
    )
    write_release_archive(verifier, archive_path, agents=agents)

    with pytest.raises(AssertionError, match="English and Chinese deployed production baseline"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize(
    ("case_name", "field", "conflicting_line"),
    [
        (
            "star-package",
            "Package",
            "* Package: module-manager-v2-server-3.2.8.zip",
        ),
        ("plus-local-verification", "Local Verification", "+ Local Verification: passed"),
        (
            "unbulleted-reconciliation",
            "Production Reconciliation",
            "Production Reconciliation: completed",
        ),
        (
            "fullwidth-colon-reconciliation",
            "Production Reconciliation",
            "- Production Reconciliation\uff1a completed",
        ),
    ],
)
def test_archive_rejects_normalized_duplicate_candidate_lifecycle_field(
    tmp_path: Path,
    case_name: str,
    field: str,
    conflicting_line: str,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / f"{case_name}.zip"
    write_release_archive(
        verifier,
        archive_path,
        release_record=f"{PENDING_RELEASE_RECORD}\n{conflicting_line}\n",
    )

    with pytest.raises(AssertionError, match=rf"{field}: .* exactly once"):
        verifier.verify_package(archive_path)


def test_archive_rejects_deployed_record_without_live_evidence(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "unsupported-deployed-record.zip"
    record = deployed_release_record(
        "3.2.8",
        "Status: reviewed, packaged, deployed, and verified in production",
    ).replace(f"| SHA256 | {VALID_SHA256} |", "| SHA256 | |")
    write_release_archive(
        verifier,
        archive_path,
        release_record=record,
    )

    with pytest.raises(AssertionError, match="release record must define Status: pending"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize(
    "affirmative_prose",
    [
        "V3.0.81 was not deployed yesterday and was deployed today.",
        "V3.0.81\n\nhas been deployed to production.",
        "V3.0.81 生产部署已完成。",
    ],
)
def test_archive_rejects_pending_record_with_affirmative_deployment_prose(
    tmp_path: Path,
    affirmative_prose: str,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "affirmative-prose.zip"
    write_release_archive(
        verifier,
        archive_path,
        release_record=f"{PENDING_RELEASE_RECORD}\n{affirmative_prose}\n",
    )

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.verify_package(archive_path)


def test_archive_rejects_pending_candidate_with_unversioned_claim_and_complete_evidence(
    tmp_path: Path,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "forged-complete-pending.zip"
    record = (
        PENDING_RELEASE_RECORD.replace("- V3.0.81 has not been deployed to production.\n", "")
        .replace(f"| SHA256 | |", f"| SHA256 | {VALID_SHA256} |")
        .replace(
            "| Backup directory | |",
            "| Backup directory | /opt/module-manager-v2/backups/forged-complete |",
        )
        .replace(
            "| Release directory | |",
            "| Release directory | /opt/module-manager-v2/releases/forged-complete |",
        )
        .replace(
            "| Public health check | |",
            "| Public health check | https://www.sgcc.online/health passed |",
        )
    )
    record += "\nProduction was deployed successfully.\n"
    write_release_archive(verifier, archive_path, release_record=record)

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.verify_package(archive_path)


def test_archive_rejects_bare_deployed_baseline_status(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "bare-deployed-baseline.zip"
    write_release_archive(
        verifier,
        archive_path,
        content_overrides={
            V327_RELEASE_RECORD: deployed_release_record("3.2.7", "Status: deployed")
        },
    )

    with pytest.raises(AssertionError, match="reviewed, packaged, deployed, and verified"):
        verifier.verify_package(archive_path)


def test_archive_accepts_complete_deployed_baseline_status(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "complete-deployed-baseline.zip"
    write_release_archive(verifier, archive_path)

    verifier.verify_package(archive_path)


def test_archive_rejects_deployed_candidate_record(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "post-deploy-equal-markers.zip"
    write_release_archive(
        verifier,
        archive_path,
        release_record=deployed_release_record(
            "3.2.8",
            "Status: reviewed, packaged, deployed, and verified in production",
        ),
    )

    with pytest.raises(AssertionError, match="release record must define Status: pending"):
        verifier.verify_package(archive_path)


def test_valid_pending_candidate_archive_passes_truthfulness_checks(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "valid-pending.zip"
    write_release_archive(verifier, archive_path)

    verifier.verify_package(archive_path)


ROUND4_CONDITIONAL_OR_NEGATED_CLAIMS = [
    "V3.0.81 can't be deployed to production.",
    "V3.0.81 cannot be deployed to production.",
    "V3.0.81 can be deployed to production.",
    "V3.0.81 could be deployed to production.",
    "V3.0.81 may be deployed to production.",
    "V3.0.81 might be deployed to production.",
    "V3.0.81 is deployed to production if approval is granted.",
    "V3.0.81 is deployed to production unless rollback is required.",
    "V3.0.81 可能已上线生产环境。",
    "V3.0.81 若通过验收则已上线生产环境。",
    "如果验证通过，V3.0.81 生产部署已完成。",
    "除非回归测试失败，否则 V3.0.81 已部署到生产环境。",
]


@pytest.mark.parametrize("prose", ROUND4_CONDITIONAL_OR_NEGATED_CLAIMS)
def test_archive_accepts_conditional_or_negated_deployment_prose(
    tmp_path: Path,
    prose: str,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "conditional-deployment-prose.zip"
    write_release_archive(
        verifier,
        archive_path,
        release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n",
    )

    verifier.verify_package(archive_path)


@pytest.mark.parametrize(
    "prose",
    [
        "V3.0.81 has gone live in production.",
        "V3.0.81 and its assets have gone live in production.",
        "V3.0.81 could be deployed after approval, but V3.0.81 was deployed today.",
        "V3.0.81 已在生产环境上线。",
        "V3.0.81 已完成生产上线。",
        "V3.0.81 现已在生产环境正式生效。",
        "V3.0.81 可能在审批后上线，但 V3.0.81 今日已上线生产环境。",
    ],
)
def test_archive_rejects_round4_live_and_completion_synonyms(
    tmp_path: Path,
    prose: str,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "live-synonym-prose.zip"
    write_release_archive(
        verifier,
        archive_path,
        release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n",
    )

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize(
    "prose",
    [
        "V3.0.81 has not gone live in production.",
        "V3.0.81 cannot go live in production.",
        "V3.0.81 may go live in production.",
        "V3.0.81 will go live in production after approval.",
        "V3.0.81 尚未在生产环境上线。",
        "V3.0.81 可能在生产环境上线。",
        "V3.0.81 将在生产环境上线。",
    ],
)
def test_archive_accepts_negative_pending_and_future_live_controls(
    tmp_path: Path,
    prose: str,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "live-control-prose.zip"
    write_release_archive(
        verifier,
        archive_path,
        release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n",
    )

    verifier.verify_package(archive_path)


ROUND5_AFFIRMATIVE_CLAIMS = [
    "Operators can log in, and V3.0.81 was deployed to production.",
    "Operators can log in if authorized, and V3.0.81 was deployed to production.",
    "V3.0.81 has already gone live in production.",
]


ROUND5_NORMATIVE_OR_FUTURE_CLAIMS = [
    "V3.0.81 should be deployed tomorrow.",
    "V3.0.81 must be deployed after approval.",
    "V3.0.81 ought to be deployed tomorrow.",
    "V3.0.81 应于明日部署至生产环境。",
    "V3.0.81 必须在验收后部署至生产环境。",
]


ROUND6_AFFIRMATIVE_CLAIMS = [
    "V3.0.81 was deployed to production because operators can verify it.",
    "V3.0.81 was deployed to production because operators can verify it if authorized.",
    "V3.0.81 was deployed to production after admins could approve it.",
    "V3.0.81 已部署到生产环境且响应正常。",
]


ROUND6_NEGATIVE_CONDITIONAL_OR_FUTURE_CLAIMS = [
    "V3.0.81 did not get deployed to production.",
    "V3.0.81 should be deployed tomorrow because operators can verify it.",
    "V3.0.81 应于明日部署至生产环境且响应需验证。",
    "V3.0.81 仅当验收通过才可部署到生产环境。",
]


ROUND7_AFFIRMATIVE_CLAIMS = [
    "V3.0.81 has gone live.",
    "V3.0.81 已经部署到生产环境。",
]


ROUND7_NONAFFIRMATIVE_CLAIMS = [
    "V3.0.81 could have been deployed to production.",
    "V3.0.81 will have been deployed to production by Friday.",
    "V3.0.81 was not even deployed to production.",
    "V3.0.81 may eventually be deployed to production.",
]


ROUND8_AFFIRMATIVE_LIVE_CLAIMS = [
    "V3.0.81 is currently live in production.",
    "V3.0.81 is presently live in production.",
]


ROUND9_AFFIRMATIVE_PERFECT_PRODUCTION_STATE_CLAIMS = [
    "V3.0.81 has been running in production since Monday.",
    "V3.0.81 has been in production since Monday.",
    "V3.0.81 and its assets have been running in production since Monday.",
    "V3.0.81 had been in production before the rollback.",
    "V3.0.81 has been continuously running in production since Monday.",
    "V3.0.81 has been running successfully in production since Monday.",
    "V3.0.81 has recently been running in production since Monday.",
    "V3.0.81 has long been running steadily in production.",
    "V3.0.81 has been running reliably in production.",
]


ROUND9_NONAFFIRMATIVE_PERFECT_PRODUCTION_STATE_CLAIMS = [
    "V3.0.81 has not been continuously running in production.",
    "V3.0.81 will have been continuously running in production by Friday.",
    "V3.0.81 may have been running successfully in production.",
    "V3.0.81 has possibly been running in production.",
    "V3.0.81 may recently have been running steadily in production.",
    "V3.0.81 may well have been running in production.",
    "V3.0.81 could recently have been running in production.",
]

ROUND10_NONCLAIM_CONTEXTS = [
    '> Example: "V3.0.81 was deployed to production."',
    '`V3.0.81 was deployed to production.`',
    '示例：“V3.0.81 已在生产环境上线。”',
    'There is no evidence that V3.0.81 was deployed to production.',
    'We cannot claim that V3.0.81 has been released to production.',
    '目前没有证据表明 V3.0.81 已在生产环境上线。',
    '我们不能声称 V3.0.81 已部署到生产环境。',
]


@pytest.mark.parametrize("prose", ROUND5_AFFIRMATIVE_CLAIMS)
def test_archive_rejects_round5_atomic_affirmative_claims(tmp_path: Path, prose: str) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "round5-affirmative-prose.zip"
    write_release_archive(
        verifier,
        archive_path,
        release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n",
    )

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize("prose", ROUND5_NORMATIVE_OR_FUTURE_CLAIMS)
def test_archive_accepts_round5_normative_or_future_claims(tmp_path: Path, prose: str) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "round5-normative-prose.zip"
    write_release_archive(
        verifier,
        archive_path,
        release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n",
    )

    verifier.verify_package(archive_path)


@pytest.mark.parametrize("prose", ROUND6_AFFIRMATIVE_CLAIMS)
def test_archive_rejects_round6_modal_tokens_outside_deployment_predicate(
    tmp_path: Path,
    prose: str,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "round6-affirmative-prose.zip"
    write_release_archive(
        verifier,
        archive_path,
        release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n",
    )

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize("prose", ROUND6_NEGATIVE_CONDITIONAL_OR_FUTURE_CLAIMS)
def test_archive_accepts_round6_nonaffirmative_deployment_predicate_controls(
    tmp_path: Path,
    prose: str,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "round6-nonaffirmative-prose.zip"
    write_release_archive(
        verifier,
        archive_path,
        release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n",
    )

    verifier.verify_package(archive_path)


@pytest.mark.parametrize("prose", ROUND7_AFFIRMATIVE_CLAIMS)
def test_archive_rejects_round7_common_affirmative_claims(tmp_path: Path, prose: str) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "round7-affirmative-prose.zip"
    write_release_archive(verifier, archive_path, release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n")

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize("prose", ROUND7_NONAFFIRMATIVE_CLAIMS)
def test_archive_accepts_round7_complete_auxiliary_controls(tmp_path: Path, prose: str) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "round7-nonaffirmative-prose.zip"
    write_release_archive(verifier, archive_path, release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n")

    verifier.verify_package(archive_path)


@pytest.mark.parametrize("prose", ROUND8_AFFIRMATIVE_LIVE_CLAIMS)
def test_archive_rejects_round8_current_live_adverbs(tmp_path: Path, prose: str) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "round8-current-live-prose.zip"
    write_release_archive(verifier, archive_path, release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n")

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize("prose", ROUND9_AFFIRMATIVE_PERFECT_PRODUCTION_STATE_CLAIMS)
def test_archive_rejects_round9_perfect_production_states(tmp_path: Path, prose: str) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "round9-perfect-production-state.zip"
    write_release_archive(verifier, archive_path, release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n")

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize("prose", ROUND9_NONAFFIRMATIVE_PERFECT_PRODUCTION_STATE_CLAIMS)
def test_archive_accepts_round9_nonaffirmative_perfect_states(tmp_path: Path, prose: str) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "round9-nonaffirmative-perfect-production-state.zip"
    write_release_archive(verifier, archive_path, release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n")

    verifier.verify_package(archive_path)


@pytest.mark.parametrize("prose", ROUND10_NONCLAIM_CONTEXTS)
def test_archive_accepts_round10_nonclaim_contexts(tmp_path: Path, prose: str) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "round10-nonclaim-context.zip"
    write_release_archive(
        verifier,
        archive_path,
        release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n",
    )

    verifier.verify_package(archive_path)


def test_archive_rejects_substituted_imported_chunk(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "stale-imported-chunk.zip"
    entry = (
        'globalThis.__MODULE_MANAGER_VUE_ENTRY_ATTESTATION__={"version":"3.0.81"};\n'
        'import "./stale.js";\n'
    )
    write_release_archive(verifier, archive_path, entry_source=entry)
    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr("v2-api/app/static/vue/assets/stale.js", "const staleVersion = '3.0.80';\n")

    with pytest.raises(AssertionError, match="Vue asset manifest"):
        verifier.verify_package(archive_path)


def test_archive_rejects_extra_executable_script(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "extra-script.zip"
    write_release_archive(
        verifier,
        archive_path,
        unrelated_index_text='<script src="/vue/assets/stale-classic.js"></script>',
    )
    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr("v2-api/app/static/vue/assets/stale-classic.js", "const stale = true;\n")

    with pytest.raises(AssertionError, match="exactly one executable module entry"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize(
    "member_name",
    [
        "../../outside-release.txt",
        "/absolute-release.txt",
        "C:/drive-release.txt",
        "v2-api/app/static/vue/./dot.js",
        "v2-api/app/static/vue//empty.js",
        "v2-api/app/static/vue/control\x01.js",
    ],
)
def test_archive_rejects_noncanonical_member_paths(tmp_path: Path, member_name: str) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "noncanonical-member.zip"
    write_release_archive(verifier, archive_path)
    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr(member_name, "unsafe\n")

    with pytest.raises(AssertionError, match="canonical relative POSIX path"):
        verifier.verify_package(archive_path)


def test_archive_rejects_symlink_member(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "symlink-member.zip"
    write_release_archive(verifier, archive_path)
    link = zipfile.ZipInfo("v2-api/app/static/vue/assets/link.js")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr(link, "target.js")

    with pytest.raises(AssertionError, match="symbolic links"):
        verifier.verify_package(archive_path)


def test_archive_rejects_case_colliding_member(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "case-collision.zip"
    write_release_archive(verifier, archive_path)
    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr("V2-API/app/static/vue/assets/app.js", "collision\n")

    with pytest.raises(AssertionError, match="case-insensitive file names"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize(
    "member_name",
    [
        ".ENV",
        "config/.Env.production",
        "certificates/client.PEM",
        "certificates/private.Key",
        "certificates/signing.P12",
        "certificates/signing.PfX",
        "database/production.SQL",
        "database/production.DuMp",
        "database/local.SQLite",
        "database/local.SQLITE3",
        "database/local.DB",
        "artifacts/Coverage/index.html",
        "artifacts/HTMLCOV/index.html",
        "artifacts/Test-Results/results.json",
        "artifacts/Playwright-Report/index.html",
        "artifacts/.NYC_OUTPUT/coverage.json",
        "artifacts/.PyTeSt_CaChE/state",
        "artifacts/__PyCaChE__/module.pyc",
    ],
)
def test_archive_rejects_sensitive_and_test_artifacts_case_insensitively(
    tmp_path: Path,
    member_name: str,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "forbidden-release-artifact.zip"
    write_release_archive(
        verifier,
        archive_path,
        content_overrides={member_name: "must not ship\n"},
    )

    with pytest.raises(AssertionError, match="Forbidden local/cache files"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize(
    "member_name",
    [
        "config/.env.production/settings.json",
        "nested/.ENV.LOCAL/key.txt",
        "artifacts/nested/.VeNv/pyvenv.cfg",
        "artifacts/nested/BUILD/output.bin",
    ],
)
def test_archive_rejects_forbidden_directory_components_at_any_depth(
    tmp_path: Path,
    member_name: str,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "forbidden-directory-component.zip"
    write_release_archive(
        verifier,
        archive_path,
        content_overrides={member_name: "must not ship\n"},
    )

    with pytest.raises(AssertionError, match="Forbidden local/cache files"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize(
    "member_name",
    (
        "nested/Migration-Report.JSON",
        r"nested\ALLOWED-HOSTS.TXT",
        "nested/deeper/Oss-Local-Export-20260819.ZIP",
    ),
)
def test_python_classifier_rejects_operational_artifact_basenames_at_any_depth(
    member_name: str,
) -> None:
    assert load_verifier().is_forbidden_release_path(member_name)


@pytest.mark.parametrize(
    "member_name",
    (
        "docs/sop/09-export-retirement-and-oss-local-export.md",
        "v2-api/scripts/migrate_external_photos_to_oss.py",
        "scripts/oss_local_export.py",
    ),
)
def test_python_classifier_keeps_authorized_export_migration_sources(
    member_name: str,
) -> None:
    assert not load_verifier().is_forbidden_release_path(member_name)


def test_release_builder_classifier_rejects_forbidden_components_on_windows(
    tmp_path: Path,
) -> None:
    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(
        encoding="utf-8"
    )

    def array_definition(variable_name: str) -> str:
        start = build_script.index(f"${variable_name} = @(")
        return build_script[start:build_script.index(")", start) + 1]

    function_start = build_script.index("function Test-ForbiddenReleasePath")
    opening_brace = build_script.index("{", function_start)
    depth = 0
    function_end = -1
    for index in range(opening_brace, len(build_script)):
        if build_script[index] == "{":
            depth += 1
        elif build_script[index] == "}":
            depth -= 1
            if depth == 0:
                function_end = index + 1
                break
    assert function_end > 0

    staging = str(tmp_path / "release-staging").replace("'", "''")
    harness = "\n".join(
        (
            '$ErrorActionPreference = "Stop"',
            array_definition("forbiddenReleaseDirectoryNames"),
            array_definition("forbiddenReleaseFileNames"),
            array_definition("forbiddenReleaseFileSuffixes"),
            build_script[function_start:function_end],
            f"$staging = '{staging}'",
            "$forbiddenCases = @(",
            "    (Join-Path $staging 'config\\.env.production\\settings.json'),",
            "    (Join-Path $staging 'nested\\.ENV.LOCAL\\key.txt'),",
            "    (Join-Path $staging 'artifacts\\.VeNv\\pyvenv.cfg'),",
            "    (Join-Path $staging 'artifacts\\BUILD\\output.bin'),",
            "    (Join-Path $staging 'nested\\Migration-Report.JSON'),",
            "    (Join-Path $staging 'nested\\ALLOWED-HOSTS.TXT'),",
            "    (Join-Path $staging 'nested\\Oss-Local-Export-20260819.ZIP')",
            ")",
            "foreach ($path in $forbiddenCases) {",
            "    if (-not (Test-ForbiddenReleasePath -Path $path -IsDirectory $false)) {",
            '        throw "Forbidden path was accepted: $path"',
            "    }",
            "}",
            "$allowedCases = @(",
            "    (Join-Path $staging 'docs\\sop\\09-export-retirement-and-oss-local-export.md'),",
            "    (Join-Path $staging 'v2-api\\scripts\\migrate_external_photos_to_oss.py'),",
            "    (Join-Path $staging 'scripts\\oss_local_export.py')",
            ")",
            "foreach ($path in $allowedCases) {",
            "    if (Test-ForbiddenReleasePath -Path $path -IsDirectory $false) {",
            '        throw "Allowed path was rejected: $path"',
            "    }",
            "}",
        )
    )
    harness_path = tmp_path / "verify-build-release-policy.ps1"
    harness_path.write_text(harness, encoding="utf-8")

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_v320_semantic_gate_rejects_leaf_only_python_classifier() -> None:
    release_verifier = load_v320_release_verifier()
    semantic_gate = getattr(
        release_verifier,
        "verify_classifier_semantics",
        None,
    )
    assert callable(semantic_gate), (
        "V3.2.0 release verifier must execute both package classifiers"
    )

    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(
        encoding="utf-8"
    )
    package_verifier = (ROOT / "scripts" / "verify-client-release.py").read_text(
        encoding="utf-8"
    )
    extraction_failures: list[str] = []
    classifier_text = release_verifier.python_function_text(
        package_verifier,
        "is_forbidden_release_path",
        "scripts/verify-client-release.py",
        extraction_failures,
    )
    assert not extraction_failures
    leaf_only_classifier = """def is_forbidden_release_path(name: str) -> bool:
    normalized_name = name.replace("\\\\", "/").casefold()
    leaf_name = PurePosixPath(normalized_name).name
    return (
        leaf_name in FORBIDDEN_PARTS
        or leaf_name == ".env"
        or leaf_name.startswith(".env.")
        or leaf_name in FORBIDDEN_NAMES
        or PurePosixPath(leaf_name).suffix in FORBIDDEN_SUFFIXES
    )
"""
    reduced_package_verifier = package_verifier.replace(
        classifier_text,
        leaf_only_classifier,
        1,
    )
    failures: list[str] = []

    semantic_gate(build_script, reduced_package_verifier, failures)

    assert any(
        "Python classifier" in failure
        and "config/.env.production/settings.json" in failure
        for failure in failures
    )


def test_v320_semantic_gate_rejects_leaf_only_powershell_classifier() -> None:
    release_verifier = load_v320_release_verifier()
    semantic_gate = getattr(
        release_verifier,
        "verify_classifier_semantics",
        None,
    )
    assert callable(semantic_gate), (
        "V3.2.0 release verifier must execute both package classifiers"
    )

    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(
        encoding="utf-8"
    )
    package_verifier = (ROOT / "scripts" / "verify-client-release.py").read_text(
        encoding="utf-8"
    )
    extraction_failures: list[str] = []
    classifier_text = release_verifier.powershell_function_text(
        build_script,
        "Test-ForbiddenReleasePath",
        "scripts/build-client-release.ps1",
        extraction_failures,
    )
    assert not extraction_failures
    leaf_only_classifier = r"""function Test-ForbiddenReleasePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [bool]$IsDirectory
    )
    $leafName = [System.IO.Path]::GetFileName($Path).ToLowerInvariant()
    $leafSuffix = [System.IO.Path]::GetExtension($leafName)
    return (
        $leafName -in $forbiddenReleaseDirectoryNames -or
        $leafName -eq ".env" -or
        $leafName.StartsWith(".env.") -or
        $leafName -in $forbiddenReleaseFileNames -or
        $leafSuffix -in $forbiddenReleaseFileSuffixes
    )
}"""
    reduced_build_script = build_script.replace(
        classifier_text,
        leaf_only_classifier,
        1,
    )
    failures: list[str] = []

    semantic_gate(reduced_build_script, package_verifier, failures)

    assert any(
        "PowerShell classifier" in failure
        and "nested/.ENV.LOCAL/key.txt" in failure
        for failure in failures
    )
