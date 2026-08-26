from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import stat
import sys
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile


ROOT = Path(__file__).resolve().parents[1]
VERSION = "3.2.10"
DISPLAY_VERSION = "V3.2.10"
DEPLOYED_BASELINE = "V3.2.9"
MAINTENANCE_BRANCH = "production/V3/3.2.10"
MIGRATION_REVISION = "20260824_0016"
RELEASE_PATH = "ops/releases/V3.2.10.md"
BASELINE_RELEASE_PATH = "ops/releases/V3.2.9.md"
ARCHIVE_PATH = "build/server-release/module-manager-v2-server-3.2.10.zip"
PRODUCTION_RECORD_SHA256 = "ba333764f85ed83908b2d5a4ed2cf0b4118a623f37328b514474c5d04c253243"
VERIFICATION_PHASES = frozenset(("source", "package", "attestation"))

REQUIRED_FILES = (
    "AGENTS.md",
    "RELEASE_MANIFEST.md",
    "docs/AGENT_REQUIRED_READING.md",
    "docs/sop/README.md",
    "docs/superpowers/specs/2026-08-26-unified-terminal-review-rephoto-workbench-design.md",
    BASELINE_RELEASE_PATH,
    RELEASE_PATH,
    "scripts/build-client-release.ps1",
    "scripts/verify-client-release.py",
    "scripts/verify_release_sop.py",
    "scripts/verify_v3_2_10_release.py",
    "scripts/test_verify_v3_2_10_release.py",
    "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py",
    "v2-api/app/api/routes/collector_transfer.py",
    "v2-api/app/api/routes/groups.py",
    "v2-api/app/domain/terminal_review.py",
    "v2-api/app/main.py",
    "v2-api/app/services/collector_transfer.py",
    "v2-api/app/services/ops_status.py",
    "v2-api/pyproject.toml",
    "v2-api/scripts/verify_v3_1_release.py",
    "v2-api/tests/test_collector_transfer_api.py",
    "v2-api/tests/test_collector_transfer_postgres_integration.py",
    "v2-api/tests/test_collector_transfer_scale.py",
    "v2-api/tests/test_collector_transfer_service.py",
    "v2-api/tests/test_data_center_review.py",
    "v2-api/tests/test_terminal_review_domain.py",
    "v2-api/tests/test_v3_1_release.py",
    "v2-web/index.html",
    "v2-web/package.json",
    "v2-web/src/api/services.ts",
    "v2-web/src/api/types.ts",
    "v2-web/src/components/AppLayout.vue",
    "v2-web/src/components/data-center/DataCenterGroupReviewPanel.vue",
    "v2-web/src/constants/releaseNotes.ts",
    "v2-web/src/features/collectorTransfer/state.ts",
    "v2-web/src/router/index.ts",
    "v2-web/src/router/staticPages.ts",
    "v2-web/src/version.json",
    "v2-web/src/views/CollectorInventoryView.vue",
    "v2-web/src/views/ReviewRephotoWorkbenchView.vue",
    "v2-web/src/views/__tests__/CollectorInventoryRouting.spec.ts",
    "v2-web/src/views/__tests__/CollectorInventoryView.spec.ts",
    "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
)

VERSION_SURFACES = {
    "v2-api/app/main.py": 'version="3.2.10"',
    "v2-api/app/services/ops_status.py": 'return "3.2.10"',
    "v2-api/pyproject.toml": 'version = "3.2.10"',
    "v2-api/scripts/verify_v3_1_release.py": 'EXPECTED_VERSION = "3.2.10"',
    "v2-api/tests/test_v3_1_release.py": 'EXPECTED_VERSION = "3.2.10"',
    "v2-web/index.html": "Module Manager V3.2.10",
    "v2-web/package.json": '"version": "3.2.10"',
    "v2-web/src/components/AppLayout.vue": "V3.2.10",
    "v2-web/src/constants/releaseNotes.ts": "version: 'V3.2.10'",
    "v2-web/src/version.json": '"version":"3.2.10"',
    "RELEASE_MANIFEST.md": "- Version: 3.2.10",
}

FEATURE_MARKERS = {
    "v2-api/app/main.py": (
        '@app.get("/review-workbench")',
    ),
    "v2-api/app/domain/terminal_review.py": (
        "def project_terminal_review(",
        "def derive_terminal_workflow_state(",
        'TerminalWorkflowState = Literal[',
    ),
    "v2-api/app/services/collector_transfer.py": (
        "def open_review_workbench_terminal(",
        "def _require_terminal_review_ready(",
        "def _lock_global_terminal_identity(",
    ),
    "v2-api/app/api/routes/collector_transfer.py": (
        '@router.post("/review-workbench/terminals/open")',
        'code="terminal_review_required"',
        "require_admin(request)",
    ),
    "v2-api/tests/test_collector_transfer_postgres_integration.py": (
        "def test_real_postgres_terminal_review_change_after_terminal_lock_is_deadlock_free_and_atomic(",
        "def test_real_postgres_concurrent_allocation_is_stable_and_consumes_each_resource_once(",
    ),
    "v2-web/src/views/ReviewRephotoWorkbenchView.vue": (
        "DataCenterGroupReviewPanel",
        "未施工，不参与本次翻拍",
        "review_required_count === 0",
    ),
    "v2-web/src/router/index.ts": (
        "path: '/review-workbench'",
        "redirect: '/review-workbench'",
        "roles.has('constructor') && !roles.has('admin')",
    ),
    "v2-web/src/views/__tests__/CollectorInventoryRouting.spec.ts": (
        "converges retired review bookmarks through real navigation on the canonical workbench",
        "hydrates an authenticated session into a constructor before enforcing the global route gate",
        "keeps composite constructor-admin accounts on administrator routes and navigation",
    ),
}

SCANNER_MARKERS = {
    "v2-web/src/views/CollectorInventoryView.vue": (
        "if (await startQuaggaScanner(session))",
        "const stream = await requestCameraStream(session)",
        "offDetected",
    ),
    "v2-web/src/views/__tests__/CollectorInventoryView.spec.ts": (
        "reuses the construction Quagga scanner before opening a competing native camera stream",
        "stops a partially started construction scanner before native fallback opens the camera",
    ),
}

PENDING_FIELDS = {
    "Status": ("pending",),
    "Local Verification": ("not run", "passed"),
    "Package": ("pending", "passed"),
    "Production Deployment": ("pending",),
    "Production Reconciliation": ("pending",),
    "Rollback target": (DEPLOYED_BASELINE,),
    "Candidate branch": (f"`{MAINTENANCE_BRANCH}`",),
    "Deployed production baseline": (f"`{DEPLOYED_BASELINE}`",),
    "Candidate version": (f"`{DISPLAY_VERSION}`",),
    "Database head": (f"`{MIGRATION_REVISION} (head)`",),
}

ATTESTATION_EXACT_FIELDS = {
    "Status": "attested",
    "Local Verification": "passed",
    "Package": "passed",
    "Production Deployment": "passed",
    "Production Reconciliation": "passed",
    "Rollback target": DEPLOYED_BASELINE,
    "Candidate branch": f"`{MAINTENANCE_BRANCH}`",
    "Deployed production baseline": f"`{DEPLOYED_BASELINE}`",
    "Candidate version": f"`{DISPLAY_VERSION}`",
    "Database head": f"`{MIGRATION_REVISION} (head)`",
    "Archive file": f"`{ARCHIVE_PATH}`",
    "Backup verification": "passed",
    "Uvicorn readiness": "`127.0.0.1:8000 ready`",
    "Authorization acceptance": "passed",
    "Zero-write acceptance": "passed",
    "Camera requests": "`0`",
    "Client-platform requests": "`0`",
    "Maintenance restoration": "passed",
    "Soak health checks": "passed",
    "Attestation": "passed",
}

ATTESTATION_DYNAMIC_FIELDS = (
    "Source commit",
    "SHA256",
    "Server SHA256",
    "Backup directory",
    "Release directory",
    "Rollback directory",
    "Local health",
    "Public health",
    "Browser viewport",
)

FORBIDDEN_COMPONENTS = frozenset(
    {
        ".git",
        ".cache",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "backups",
        "cache",
        "node_modules",
        "uploads",
    }
)


def _read(root: Path, relative_path: str, failures: list[str]) -> str:
    path = root / relative_path
    if not path.is_file():
        failures.append(f"{relative_path}: required V3.2.10 file is missing")
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        failures.append(f"{relative_path}: cannot be read as UTF-8: {exc}")
        return ""


def _require_once(text: str, marker: str, path: str, failures: list[str]) -> None:
    if text.count(marker) != 1:
        failures.append(f"{path}: required marker must appear exactly once: {marker}")


def _require_markers(
    root: Path,
    path: str,
    markers: tuple[str, ...],
    label: str,
    failures: list[str],
) -> None:
    text = _read(root, path, failures)
    for marker in markers:
        if marker not in text:
            failures.append(f"{path}: {label} is missing: {marker}")


def _field_values(record: str, field: str) -> list[str]:
    return re.findall(rf"(?m)^\s*[-*+]\s*{re.escape(field)}\s*[:：]\s*(.*?)\s*$", record)


def _check_source(root: Path, failures: list[str]) -> None:
    for relative_path in REQUIRED_FILES:
        if not (root / relative_path).is_file():
            failures.append(f"{relative_path}: required V3.2.10 file is missing")

    for path, marker in VERSION_SURFACES.items():
        _require_once(_read(root, path, failures), marker, path, failures)

    agents = _read(root, "AGENTS.md", failures)
    for marker in (
        f"- Deployed production baseline: `{DEPLOYED_BASELINE}`.",
        f"- Release candidate: `{DISPLAY_VERSION}`.",
        f"- Release-candidate maintenance branch: `{MAINTENANCE_BRANCH}`.",
        f"- 当前已部署生产版本：`{DEPLOYED_BASELINE}`。",
        f"- 当前发布候选版本：`{DISPLAY_VERSION}`。",
        f"- 当前候选维护分支：`{MAINTENANCE_BRANCH}`。",
    ):
        _require_once(agents, marker, "AGENTS.md", failures)

    _require_markers(
        root,
        "docs/AGENT_REQUIRED_READING.md",
        (
            f"生产维护分支：`{MAINTENANCE_BRANCH}`",
            f"当前生产应用基线：`{DEPLOYED_BASELINE}`",
            f"当前发布候选版本：`{DISPLAY_VERSION}`",
        ),
        "operator release identity",
        failures,
    )
    _require_markers(
        root,
        "docs/sop/README.md",
        (
            f"Current production baseline: `{DEPLOYED_BASELINE}`.",
            f"Current release candidate: `{DISPLAY_VERSION}`.",
            f"Current candidate branch: `{MAINTENANCE_BRANCH}`.",
        ),
        "SOP release identity",
        failures,
    )

    baseline_path = root / BASELINE_RELEASE_PATH
    if baseline_path.is_file():
        digest = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
        if digest != PRODUCTION_RECORD_SHA256:
            failures.append(
                f"{BASELINE_RELEASE_PATH}: SHA256 must remain {PRODUCTION_RECORD_SHA256}; got {digest}"
            )

    candidate = _read(root, RELEASE_PATH, failures)
    for field, allowed in PENDING_FIELDS.items():
        values = _field_values(candidate, field)
        if len(values) != 1 or values[0] not in allowed:
            failures.append(f"{RELEASE_PATH}: {field} must equal one of {allowed} exactly once")

    migration = _read(root, "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py", failures)
    _require_once(migration, f'revision = "{MIGRATION_REVISION}"', "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py", failures)
    for path, markers in FEATURE_MARKERS.items():
        _require_markers(root, path, markers, "canonical review workbench routing" if path.endswith("router/index.ts") else "V3.2.10 unified workbench gate", failures)
    for path, markers in SCANNER_MARKERS.items():
        _require_markers(root, path, markers, "V3.2.9 Quagga-first regression", failures)

    release_tool_markers = {
        "scripts/build-client-release.ps1": (
            '[string]$Version = "3.2.10"',
            MAINTENANCE_BRANCH,
            "scripts\\verify_v3_2_10_release.py",
            "scripts\\test_verify_v3_2_10_release.py",
            "ops\\releases\\V3.2.9.md",
            "ops\\releases\\V3.2.10.md",
        ),
        "scripts/verify-client-release.py": (
            '"scripts/verify_v3_2_10_release.py"',
            '"scripts/test_verify_v3_2_10_release.py"',
            '"ops/releases/V3.2.9.md"',
            '"ops/releases/V3.2.10.md"',
            "verify_v3210_archive_source_contract",
        ),
        "scripts/verify_release_sop.py": (
            'with_name("verify_v3_2_10_release.py")',
            "V3.2.10",
        ),
    }
    for path, markers in release_tool_markers.items():
        _require_markers(root, path, markers, "V3.2.10 release gate", failures)


def _canonical_member_name(name: str) -> str | None:
    if not name or "\\" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return None
    path = PurePosixPath(name)
    if any(part in ("", ".", "..") for part in path.parts):
        return None
    canonical = path.as_posix()
    return canonical if canonical == name else None


def _forbidden_package_path(name: str) -> bool:
    parts = tuple(part.casefold() for part in PurePosixPath(name).parts)
    if any(part in FORBIDDEN_COMPONENTS or part == ".env" or part.startswith(".env.") for part in parts):
        return True
    leaf = parts[-1] if parts else ""
    return leaf == "uv.lock" or leaf.endswith((".pem", ".key", ".p12", ".pfx", ".dump", ".sqlite", ".sqlite3"))


def _load_generic_package_verifier(root: Path):
    path = root / "scripts/verify-client-release.py"
    spec = importlib.util.spec_from_file_location("v3210_generic_package_verifier", path)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load generic package verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check_package(root: Path, package_path: Path | None, failures: list[str]) -> None:
    if package_path is None:
        failures.append("package phase requires --package for V3.2.10")
        return
    package = Path(package_path)
    if not package.is_file() or package.stat().st_size <= 0:
        failures.append(f"V3.2.10 package is missing or empty: {package}")
        return
    try:
        with ZipFile(package) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            canonical = [_canonical_member_name(name) for name in names]
            for name, normalized in zip(names, canonical, strict=True):
                if normalized is None:
                    failures.append(f"non-canonical archive member: {name}")
            if len(names) != len(set(names)):
                failures.append("duplicate archive member names are forbidden")
            folded = [name.casefold() for name in names]
            if len(folded) != len(set(folded)):
                failures.append("case-colliding archive member names are forbidden")
            for info in infos:
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    failures.append(f"symlink archive member is forbidden: {info.filename}")
                if _forbidden_package_path(info.filename):
                    failures.append(f"forbidden archive member: {info.filename}")
            bad_member = archive.testzip()
            if bad_member is not None:
                failures.append(f"archive CRC failed: {bad_member}")
            name_set = set(names)
            if "SOURCE_COMMIT" not in name_set:
                failures.append("V3.2.10 package requires SOURCE_COMMIT")
            else:
                source_commit = archive.read("SOURCE_COMMIT").decode("ascii", errors="replace").strip()
                if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
                    failures.append("V3.2.10 SOURCE_COMMIT must be one lowercase 40-character Git commit")
            if "RELEASE_MANIFEST.md" not in name_set:
                failures.append("V3.2.10 package requires RELEASE_MANIFEST.md")
            else:
                manifest_bytes = archive.read("RELEASE_MANIFEST.md")
                if b"\r" in manifest_bytes:
                    failures.append("V3.2.10 RELEASE_MANIFEST.md must use LF line endings")
                manifest = manifest_bytes.decode("utf-8", errors="replace")
                versions = re.findall(r"(?m)^- Version:\s*(\S+)\s*$", manifest)
                if versions != [VERSION]:
                    failures.append(f"V3.2.10 package manifest must contain exactly Version {VERSION}")
    except (BadZipFile, OSError) as exc:
        failures.append(f"V3.2.10 package cannot be opened: {exc}")
        return

    try:
        _load_generic_package_verifier(root).verify_package(package)
    except (AssertionError, KeyError, OSError, BadZipFile, UnicodeError, json.JSONDecodeError) as exc:
        failures.append(f"V3.2.10 package verification failed: {exc}")


def _check_attestation(root: Path, failures: list[str]) -> None:
    record = _read(root, RELEASE_PATH, failures)
    for field, expected in ATTESTATION_EXACT_FIELDS.items():
        values = _field_values(record, field)
        if values != [expected]:
            failures.append(f"{RELEASE_PATH}: attestation requires {field}: {expected} exactly once")
    for field in ATTESTATION_DYNAMIC_FIELDS:
        values = _field_values(record, field)
        if len(values) != 1 or values[0].strip().casefold() in {"", "pending", "not run"}:
            failures.append(f"{RELEASE_PATH}: attestation requires one non-pending {field} value")
    hashes = {field: _field_values(record, field) for field in ("SHA256", "Server SHA256")}
    if all(len(values) == 1 for values in hashes.values()):
        local_hash = hashes["SHA256"][0].strip("`").casefold()
        server_hash = hashes["Server SHA256"][0].strip("`").casefold()
        if re.fullmatch(r"[0-9a-f]{64}", local_hash) is None or local_hash != server_hash:
            failures.append(f"{RELEASE_PATH}: Server SHA256 must equal one valid SHA256")


def collect_failures(
    root: Path,
    phase: str,
    *,
    package_path: Path | None = None,
) -> list[str]:
    root = Path(root)
    if phase not in VERIFICATION_PHASES:
        return [f"verification phase must be one of {sorted(VERIFICATION_PHASES)}"]
    failures: list[str] = []
    if phase == "source":
        _check_source(root, failures)
    elif phase == "package":
        _check_package(root, package_path, failures)
    else:
        _check_source(root, failures)
        _check_attestation(root, failures)
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the V3.2.10 source, package, or attestation contract.")
    parser.add_argument("--phase", required=True, choices=sorted(VERIFICATION_PHASES))
    parser.add_argument("--package", type=Path)
    args = parser.parse_args(argv)
    failures = collect_failures(ROOT, args.phase, package_path=args.package)
    if failures:
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"[OK] V3.2.10 {args.phase} release contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
