from __future__ import annotations

import argparse
import hashlib
import importlib.util
import re
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "3.2.27"
DISPLAY_VERSION = "V3.2.27"
DEPLOYED_BASELINE = "V3.2.26"
MAINTENANCE_BRANCH = "production/V3/3.2.27"
MIGRATION_REVISION = "20260901_0017"
RELEASE_PATH = "ops/releases/V3.2.27.md"
BASELINE_RELEASE_PATH = "ops/releases/V3.2.26.md"
ARCHIVE_PATH = "build/server-release/module-manager-v2-server-3.2.27.zip"
PRODUCTION_RECORD_SHA256 = "6536c67f6080737c7cecdd116c1034839e3fa4f77552891aba05389e286c1836"
VERIFICATION_PHASES = frozenset(("source", "package", "attestation"))
RETIRED_BACKGROUND_BARCODE_FILES = frozenset(
    {
        "infra/module-manager-v2-photo-barcode-maintenance.service",
        "infra/module-manager-v2-photo-barcode-maintenance-enqueue.service",
        "infra/module-manager-v2-photo-barcode-maintenance.timer",
        "scripts/run_photo_barcode_maintenance.sh",
        "scripts/run_photo_barcode_maintenance_slice.sh",
        "scripts/run_photo_barcode_not_matched_rescan.sh",
    }
)


def _load_v3226_verifier():
    path = ROOT / "scripts" / "verify_v3_2_26_release.py"
    spec = importlib.util.spec_from_file_location("v3227_v3226_release_base", path)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load the immutable V3.2.26 release verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BASE = _load_v3226_verifier()

MATERIAL_EXPORT_FILES = frozenset(
    {
        "v2-api/alembic/versions/0017_material_exports.py",
        "v2-api/app/domain/material_export.py",
        "v2-api/app/api/routes/material_exports.py",
        "v2-api/app/api/schemas/material_export.py",
        "v2-api/app/services/material_export.py",
        "v2-api/app/services/material_export_stream.py",
        "v2-api/tests/test_material_export_domain.py",
        "v2-api/tests/test_material_export_models.py",
        "v2-api/tests/test_material_export_service.py",
        "v2-api/tests/test_material_export_api.py",
        "v2-api/tests/test_material_export_stream.py",
        "v2-web/src/features/materialExport/state.ts",
        "v2-web/src/features/materialExport/checkpoint.ts",
        "v2-web/src/features/materialExport/fileSystem.ts",
        "v2-web/src/features/materialExport/workbooks.ts",
        "v2-web/src/features/materialExport/runner.ts",
        "v2-web/src/features/materialExport/useMaterialExport.ts",
        "v2-web/src/components/material-export/MaterialExportToolbar.vue",
        "v2-web/src/components/material-export/MaterialExportCardControls.vue",
        "v2-web/src/views/__tests__/ClaimTasksMaterialExport.spec.ts",
        "scripts/verify_material_export_gate.py",
    }
)

REQUIRED_FILES = tuple(
    path
    for path in dict.fromkeys(
        (
            *_BASE.REQUIRED_FILES,
            *sorted(MATERIAL_EXPORT_FILES),
            RELEASE_PATH,
            "scripts/verify_v3_2_27_release.py",
            "scripts/test_verify_v3_2_27_release.py",
        )
    )
    if path not in RETIRED_BACKGROUND_BARCODE_FILES
)

VERSION_SURFACES = {
    "v2-api/app/main.py": 'version="3.2.27"',
    "v2-api/app/services/ops_status.py": 'return "3.2.27"',
    "v2-api/pyproject.toml": 'version = "3.2.27"',
    "v2-api/scripts/verify_v3_1_release.py": 'EXPECTED_VERSION = "3.2.27"',
    "v2-api/tests/test_v3_1_release.py": 'EXPECTED_VERSION = "3.2.27"',
    "v2-web/index.html": "Module Manager V3.2.27",
    "v2-web/package.json": '"version": "3.2.27"',
    "v2-web/src/components/AppLayout.vue": "V3.2.27",
    "v2-web/src/constants/releaseNotes.ts": "version: 'V3.2.27'",
    "v2-web/src/version.json": '"version":"3.2.27"',
    "RELEASE_MANIFEST.md": "- Version: 3.2.27",
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


def _load_material_gate(root: Path):
    path = root / "scripts" / "verify_material_export_gate.py"
    spec = importlib.util.spec_from_file_location("v3227_material_export_gate", path)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load material export gate")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check_source(root: Path, failures: list[str], *, require_pending: bool = True) -> None:
    for relative_path in REQUIRED_FILES:
        if not (root / relative_path).is_file():
            failures.append(f"{relative_path}: required V3.2.27 source file is missing")

    for relative_path, marker in VERSION_SURFACES.items():
        text = _read(root, relative_path, failures)
        if marker not in text:
            failures.append(f"{relative_path}: active version surface is not {VERSION}")

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

    migration = _read(root, "v2-api/alembic/versions/0017_material_exports.py", failures)
    for marker in (
        'revision = "20260901_0017"',
        'down_revision = "20260824_0016"',
        'raise RuntimeError("material export persistence is forward-only")',
    ):
        if marker not in migration:
            failures.append(f"v2-api/alembic/versions/0017_material_exports.py: missing {marker}")

    release_tool_markers = {
        "scripts/build-client-release.ps1": (
            '[string]$Version = "3.2.27"',
            MAINTENANCE_BRANCH,
            "scripts\\verify_v3_2_27_release.py",
            "scripts\\test_verify_v3_2_27_release.py",
        ),
        "scripts/verify-client-release.py": (
            "V3227_CONTRACT_INPUTS",
            "verify_v3227_archive_source_contract",
            '"3.2.27"',
        ),
        "scripts/verify_release_sop.py": (
            'candidate == "V3.2.27"',
            'with_name("verify_v3_2_27_release.py")',
            '"ops/releases/V3.2.27.md"',
        ),
    }
    for relative_path, markers in release_tool_markers.items():
        text = _read(root, relative_path, failures)
        for marker in markers:
            if marker not in text:
                failures.append(f"{relative_path}: missing V3.2.27 release marker: {marker}")

    try:
        if _load_material_gate(root).main() != 0:
            failures.append("scripts/verify_material_export_gate.py: gate failed")
    except Exception as exc:  # pragma: no cover - converted into verifier evidence
        failures.append(f"scripts/verify_material_export_gate.py: unable to run: {exc}")


def _check_package(
    package_path: Path | None,
    expected_source_commit: str | None,
    failures: list[str],
) -> None:
    if package_path is None or not package_path.is_file():
        failures.append("V3.2.27 package path is missing")
        return
    try:
        with zipfile.ZipFile(package_path) as archive:
            names = set(archive.namelist())
            missing = sorted(set(REQUIRED_FILES) - names)
            if missing:
                failures.append("package missing V3.2.27 contract files: " + ", ".join(missing))
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
                failures.append("package release manifest version is not 3.2.27")
    except (KeyError, OSError, zipfile.BadZipFile, UnicodeError) as exc:
        failures.append(f"unable to verify V3.2.27 package: {exc}")


def _check_attestation(
    root: Path,
    package_path: Path | None,
    expected_source_commit: str | None,
    failures: list[str],
) -> None:
    record = _read(root, RELEASE_PATH, failures)
    for field in ("Status", "Local Verification", "Package", "Production Deployment", "Production Reconciliation"):
        expected = "attested" if field == "Status" else "passed"
        _require_exact_field(record, field, expected, failures)
    source_commits = _field_values(record, "Source commit")
    expected_commit = (expected_source_commit or "").strip().lower()
    if source_commits != [expected_commit] or re.fullmatch(r"[0-9a-f]{40}", expected_commit) is None:
        failures.append(f"{RELEASE_PATH}: Source commit must match the verified package source")
    for field in ("SHA256", "Server SHA256"):
        values = _field_values(record, field)
        if package_path is None or not package_path.is_file() or values != [hashlib.sha256(package_path.read_bytes()).hexdigest()]:
            failures.append(f"{RELEASE_PATH}: {field} must match package bytes")
    for field in ("Local health", "Public health"):
        _require_exact_field(record, field, "HTTP 200 version 3.2.27", failures)
    patterns = {
        "Backup directory": r"/opt/module-manager-v2/backups/V3\.2\.27-pre-\d{8}_\d{6}",
        "Release directory": r"/opt/module-manager-v2/releases/v3\.2\.27-\d{8}T\d{6}Z",
        "Rollback directory": r"/opt/module-manager-v2/releases/v3\.2\.26-\d{8}T\d{6}Z",
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
    parser = argparse.ArgumentParser(description="Verify the V3.2.27 source, package, or attestation contract.")
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
    print(f"[OK] V3.2.27 {args.phase} release contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
