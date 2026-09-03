from __future__ import annotations

import argparse
import hashlib
import importlib.util
import re
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "3.2.29"
DISPLAY_VERSION = "V3.2.29"
DEPLOYED_BASELINE = "V3.2.28"
MAINTENANCE_BRANCH = "production/V3/3.2.29"
MIGRATION_REVISION = "20260901_0017"
RELEASE_PATH = "ops/releases/V3.2.29.md"
BASELINE_RELEASE_PATH = "ops/releases/V3.2.28.md"
ARCHIVE_PATH = "build/server-release/module-manager-v2-server-3.2.29.zip"
PRODUCTION_RECORD_SHA256 = "59773cd6fe0bb75654e5a2a6a840c8097d82d6532a4be37f48e30c93f102a600"
VERIFICATION_PHASES = frozenset(("source", "package", "attestation"))


def _load_v3228_verifier():
    path = ROOT / "scripts" / "verify_v3_2_28_release.py"
    spec = importlib.util.spec_from_file_location("v3229_v3228_release_base", path)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load the immutable V3.2.28 release verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BASE = _load_v3228_verifier()
REQUIRED_FILES = tuple(
    dict.fromkeys(
        (
            *_BASE.REQUIRED_FILES,
            RELEASE_PATH,
            "scripts/verify_v3_2_29_release.py",
            "scripts/test_verify_v3_2_29_release.py",
            "v2-api/app/services/photo_storage.py",
            "v2-api/tests/test_photo_storage.py",
        )
    )
)
RETIRED_BACKGROUND_BARCODE_FILES = _BASE.RETIRED_BACKGROUND_BARCODE_FILES

VERSION_SURFACES = {
    "v2-api/app/main.py": 'version="3.2.29"',
    "v2-api/app/services/ops_status.py": 'return "3.2.29"',
    "v2-api/pyproject.toml": 'version = "3.2.29"',
    "v2-api/scripts/verify_v3_1_release.py": 'EXPECTED_VERSION = "3.2.29"',
    "v2-api/tests/test_v3_1_release.py": 'EXPECTED_VERSION = "3.2.29"',
    "v2-web/index.html": "Module Manager V3.2.29",
    "v2-web/package.json": '"version": "3.2.29"',
    "v2-web/src/components/AppLayout.vue": "V3.2.29",
    "v2-web/src/constants/releaseNotes.ts": "version: 'V3.2.29'",
    "v2-web/src/version.json": '"version":"3.2.29"',
    "RELEASE_MANIFEST.md": "- Version: 3.2.29",
}
EXPECTED_SOURCE_FIELDS = {
    "Rollback target": DEPLOYED_BASELINE,
    "Candidate branch": MAINTENANCE_BRANCH,
    "Deployed production baseline": DEPLOYED_BASELINE,
    "Candidate version": DISPLAY_VERSION,
    "Database head": f"{MIGRATION_REVISION} (head)",
}


def _read(root: Path, relative_path: str, failures: list[str]) -> str:
    path = root / relative_path
    if not path.is_file():
        failures.append(f"{relative_path}: required file is missing")
        return ""
    return path.read_text(encoding="utf-8")


def _field_values(document: str, field: str) -> list[str]:
    pattern = re.compile(rf"(?m)^- {re.escape(field)}:\s*(.*?)\s*$")
    return [match.group(1).strip().strip("`") for match in pattern.finditer(document)]


def _require_exact_field(document: str, field: str, expected: str, failures: list[str]) -> None:
    if _field_values(document, field) != [expected]:
        failures.append(f"{RELEASE_PATH}: requires {field}: {expected} exactly once")


def _check_inherited_release_safety(root: Path, failures: list[str]) -> None:
    _BASE._check_inherited_release_safety(root, failures)

    route = _read(root, "v2-api/app/api/routes/material_exports.py", failures)
    if not _BASE._backend_containment_is_active(route):
        failures.append("material export server containment is not enabled")

    task_view_path = root / _BASE.CLAIM_TASKS_VIEW_PATH
    task_view = _read(root, _BASE.CLAIM_TASKS_VIEW_PATH, failures)
    if (
        not task_view_path.is_file()
        or hashlib.sha256(task_view_path.read_bytes()).hexdigest() != _BASE.CLAIM_TASKS_VIEW_SHA256
        or not _BASE._frontend_containment_is_active(task_view)
    ):
        failures.append("task-dispatch export actions are not disabled")


def _check_source(root: Path, failures: list[str], *, require_pending: bool = True) -> None:
    for relative_path in REQUIRED_FILES:
        if not (root / relative_path).is_file():
            failures.append(f"{relative_path}: required V3.2.29 source file is missing")

    for relative_path, marker in VERSION_SURFACES.items():
        if marker not in _read(root, relative_path, failures):
            failures.append(f"{relative_path}: active version surface is not {VERSION}")

    _check_inherited_release_safety(root, failures)

    agents = _read(root, "AGENTS.md", failures)
    for marker in (
        f"Deployed production baseline: `{DEPLOYED_BASELINE}`",
        f"Release candidate: `{DISPLAY_VERSION}`",
        f"Release-candidate maintenance branch: `{MAINTENANCE_BRANCH}`",
    ):
        if marker not in agents:
            failures.append(f"AGENTS.md: missing release lifecycle marker: {marker}")

    baseline = root / BASELINE_RELEASE_PATH
    if baseline.is_file() and hashlib.sha256(baseline.read_bytes()).hexdigest() != PRODUCTION_RECORD_SHA256:
        failures.append(f"{BASELINE_RELEASE_PATH}: immutable production baseline hash changed")

    record = _read(root, RELEASE_PATH, failures)
    for field, expected in EXPECTED_SOURCE_FIELDS.items():
        _require_exact_field(record, field, expected, failures)
    allowed_lifecycle = {
        "Status": {"pending", "attested"},
        "Local Verification": {"pending", "passed"},
        "Package": {"pending", "passed"},
        "Production Deployment": {"pending", "passed"},
        "Production Reconciliation": {"pending", "passed"},
    }
    for field, allowed in allowed_lifecycle.items():
        values = _field_values(record, field)
        if len(values) != 1 or values[0] not in allowed:
            failures.append(f"{RELEASE_PATH}: invalid {field} lifecycle value")
    if require_pending and _field_values(record, "Status") not in (["pending"], ["attested"]):
        failures.append(f"{RELEASE_PATH}: source lifecycle is not valid")

    release_tools = {
        "scripts/build-client-release.ps1": (
            '[string]$Version = "3.2.29"',
            MAINTENANCE_BRANCH,
            "scripts\\verify_v3_2_29_release.py",
            "scripts\\test_verify_v3_2_29_release.py",
        ),
        "scripts/verify-client-release.py": (
            "V3229_CONTRACT_INPUTS",
            "verify_v3229_archive_source_contract",
            '"3.2.29"',
        ),
        "scripts/verify_release_sop.py": (
            'candidate == "V3.2.29"',
            'with_name("verify_v3_2_29_release.py")',
            '"ops/releases/V3.2.29.md"',
        ),
    }
    for relative_path, markers in release_tools.items():
        text = _read(root, relative_path, failures)
        for marker in markers:
            if marker not in text:
                failures.append(f"{relative_path}: missing V3.2.29 release marker: {marker}")


def _check_package(
    package_path: Path | None,
    expected_source_commit: str | None,
    failures: list[str],
) -> None:
    if package_path is None or not package_path.is_file():
        failures.append("V3.2.29 package path is missing")
        return
    try:
        with zipfile.ZipFile(package_path) as archive:
            names = set(archive.namelist())
            missing = sorted(set(REQUIRED_FILES) - names)
            if missing:
                failures.append("package missing V3.2.29 contract files: " + ", ".join(missing))
            forbidden = sorted(RETIRED_BACKGROUND_BARCODE_FILES & names)
            if forbidden:
                failures.append("package contains retired barcode workers: " + ", ".join(forbidden))
            source_commit = archive.read("SOURCE_COMMIT").decode("ascii").strip().lower()
            expected = (expected_source_commit or "").strip().lower()
            if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
                failures.append("package SOURCE_COMMIT is invalid")
            elif expected and source_commit != expected:
                failures.append("package SOURCE_COMMIT does not match expected source commit")
            manifest = archive.read("RELEASE_MANIFEST.md").decode("utf-8")
            if _field_values(manifest, "Version") != [VERSION]:
                failures.append("package release manifest version is not 3.2.29")
    except (KeyError, OSError, zipfile.BadZipFile, UnicodeError) as exc:
        failures.append(f"unable to verify V3.2.29 package: {exc}")


def _check_attestation(
    root: Path,
    package_path: Path | None,
    expected_source_commit: str | None,
    failures: list[str],
) -> None:
    record = _read(root, RELEASE_PATH, failures)
    for field in ("Status", "Local Verification", "Package", "Production Deployment", "Production Reconciliation"):
        _require_exact_field(record, field, "attested" if field == "Status" else "passed", failures)
    expected_commit = (expected_source_commit or "").strip().lower()
    if _field_values(record, "Source commit") != [expected_commit] or re.fullmatch(r"[0-9a-f]{40}", expected_commit) is None:
        failures.append(f"{RELEASE_PATH}: Source commit must match the verified package source")
    for field in ("SHA256", "Server SHA256"):
        values = _field_values(record, field)
        if package_path is None or not package_path.is_file() or values != [hashlib.sha256(package_path.read_bytes()).hexdigest()]:
            failures.append(f"{RELEASE_PATH}: {field} must match package bytes")
    for field in ("Local health", "Public health"):
        _require_exact_field(record, field, "HTTP 200 version 3.2.29", failures)
    patterns = {
        "Backup directory": r"/opt/module-manager-v2/backups/V3\.2\.29-pre-\d{8}_\d{6}",
        "Release directory": r"/opt/module-manager-v2/releases/v3\.2\.29-\d{8}T\d{6}Z",
        "Rollback directory": r"/opt/module-manager-v2/releases/v3\.2\.28-\d{8}T\d{6}Z",
    }
    for field, pattern in patterns.items():
        values = _field_values(record, field)
        if len(values) != 1 or re.fullmatch(pattern, values[0]) is None:
            failures.append(f"{RELEASE_PATH}: {field} is not one canonical production path")


def collect_failures(
    root: Path,
    phase: str,
    *,
    package_path: Path | None = None,
    expected_source_commit: str | None = None,
) -> list[str]:
    if phase not in VERIFICATION_PHASES:
        return [f"verification phase must be one of {sorted(VERIFICATION_PHASES)}"]
    failures: list[str] = []
    if phase == "source":
        _check_source(Path(root), failures)
    elif phase == "package":
        _check_package(package_path, expected_source_commit, failures)
    else:
        _check_source(Path(root), failures, require_pending=False)
        _check_package(package_path, expected_source_commit, failures)
        _check_attestation(Path(root), package_path, expected_source_commit, failures)
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the V3.2.29 source, package, or attestation contract.")
    parser.add_argument("--phase", required=True, choices=sorted(VERIFICATION_PHASES))
    parser.add_argument("--package", type=Path)
    parser.add_argument("--expected-source-commit")
    args = parser.parse_args(argv)
    failures = collect_failures(
        ROOT,
        args.phase,
        package_path=args.package,
        expected_source_commit=args.expected_source_commit,
    )
    if failures:
        print(*[f"- {failure}" for failure in failures], sep="\n", file=sys.stderr)
        return 1
    print(f"[OK] V3.2.29 {args.phase} release contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
