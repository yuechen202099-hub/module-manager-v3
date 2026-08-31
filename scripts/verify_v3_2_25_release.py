from __future__ import annotations

import argparse
import hashlib
import importlib.util
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "3.2.25"
DISPLAY_VERSION = "V3.2.25"
DEPLOYED_BASELINE = "V3.2.24"
MAINTENANCE_BRANCH = "production/V3/3.2.25"
MIGRATION_REVISION = "20260824_0016"
RELEASE_PATH = "ops/releases/V3.2.25.md"
BASELINE_RELEASE_PATH = "ops/releases/V3.2.24.md"
ARCHIVE_PATH = "build/server-release/module-manager-v2-server-3.2.25.zip"
PRODUCTION_RECORD_SHA256 = "d25448d7e0a1355065b8617371bb35c4a05a1dec03aa11fc4e458cedab06cdb6"
OPERATOR_PRODUCTION_MARKERS = (
    "当前生产 release：`/opt/module-manager-v2/releases/v3.2.24-20260831T133027Z`",
    "当前回滚 release：`/opt/module-manager-v2/releases/v3.2.23-20260830T225639Z`",
    "当前生产提交：`f611d9b90fcee4fa82519a9cd83edaa17eb39664`",
)
VERIFICATION_PHASES = frozenset(("source", "package", "attestation"))


def _load_v3224_verifier():
    path = ROOT / "scripts" / "verify_v3_2_24_release.py"
    spec = importlib.util.spec_from_file_location("v3225_v3224_release_base", path)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load the immutable V3.2.24 release verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BASE = _load_v3224_verifier()

REQUIRED_FILES = tuple(
    dict.fromkeys(
        (
            *_BASE.REQUIRED_FILES,
            RELEASE_PATH,
            "scripts/verify_v3_2_25_release.py",
            "scripts/test_verify_v3_2_25_release.py",
            "v2-api/app/services/barcode_maintenance_worker.py",
            "v2-api/app/services/collector_transfer.py",
            "v2-api/app/services/data_center.py",
            "v2-api/app/services/local_simulation.py",
            "v2-api/app/services/state_repository.py",
            "v2-api/scripts/repair_missing_collector_photo_exceptions.py",
            "v2-api/tests/test_api.py",
            "v2-api/tests/test_barcode_maintenance_worker.py",
            "v2-api/tests/test_collector_transfer_service.py",
            "v2-api/tests/test_data_center_review.py",
            "v2-api/tests/test_local_simulation.py",
            "v2-api/tests/test_miniprogram_api.py",
            "v2-api/tests/test_repair_missing_collector_photo_exceptions.py",
            "v2-api/tests/test_state_repository.py",
        )
    )
)

VERSION_SURFACES = {
    "v2-api/app/main.py": 'version="3.2.25"',
    "v2-api/app/services/ops_status.py": 'return "3.2.25"',
    "v2-api/pyproject.toml": 'version = "3.2.25"',
    "v2-api/scripts/verify_v3_1_release.py": 'EXPECTED_VERSION = "3.2.25"',
    "v2-api/tests/test_v3_1_release.py": 'EXPECTED_VERSION = "3.2.25"',
    "v2-web/index.html": "Module Manager V3.2.25",
    "v2-web/package.json": '"version": "3.2.25"',
    "v2-web/src/components/AppLayout.vue": "V3.2.25",
    "v2-web/src/constants/releaseNotes.ts": "version: 'V3.2.25'",
    "v2-web/src/version.json": '"version":"3.2.25"',
    "RELEASE_MANIFEST.md": "- Version: 3.2.25",
}

V3225_EXCEPTION_MARKERS = {
    "v2-api/app/services/local_simulation.py": (
        "has_required_construction_slots = CONSTRUCTION_UPLOAD_REQUIRED_SLOTS.issubset(slots)",
        "if len(photos) < 4 and not has_required_construction_slots:",
        "data_center_service.is_only_missing_collector_photo_exception(group)",
    ),
    "v2-api/app/services/state_repository.py": (
        "reasons = [item for item in previous_reasons if item != local_simulation.MISSING_COLLECTOR_PHOTO_REASON]",
        "and local_simulation.CONSTRUCTION_UPLOAD_REQUIRED_SLOTS.issubset(slots)",
        "~_only_missing_collector_photo_exception_clause()",
    ),
    "v2-api/app/services/data_center.py": (
        "def status_from_group(group: Mapping[str, Any]) -> str:",
        "is_only_missing_collector_photo_exception(group)",
    ),
    "v2-api/app/services/collector_transfer.py": (
        "from app.services.data_center import is_only_missing_collector_photo_exception",
        "exception_reasons: list[object] | None",
    ),
    "v2-api/app/services/barcode_maintenance_worker.py": (
        "only_ignored_exception = data_center.is_only_missing_collector_photo_exception(group)",
        "and not only_ignored_exception",
    ),
    "v2-api/scripts/repair_missing_collector_photo_exceptions.py": (
        "def repair_missing_collector_photo_exceptions(",
        "apply_changes: bool = False",
        'action="missing_collector_photo_exception_repaired"',
        "session.rollback()",
    ),
    "v2-api/tests/test_repair_missing_collector_photo_exceptions.py": (
        "test_repair_preview_is_read_only_and_reports_only_safe_candidates",
        "test_repair_apply_clears_only_retired_exception_and_is_idempotent",
        "test_repair_keeps_approved_status_while_removing_retired_reason",
    ),
}

PENDING_FIELDS = {
    "Status": {"pending"},
    "Local Verification": {"passed"},
    "Package": {"pending"},
    "Production Deployment": {"pending"},
    "Production Reconciliation": {"pending"},
    "Rollback target": {DEPLOYED_BASELINE},
    "Candidate branch": {MAINTENANCE_BRANCH},
    "Deployed production baseline": {DEPLOYED_BASELINE},
    "Candidate version": {DISPLAY_VERSION},
    "Database head": {f"{MIGRATION_REVISION} (head)"},
}

ATTESTATION_EXACT_FIELDS = {
    **_BASE.ATTESTATION_EXACT_FIELDS,
    "Rollback target": DEPLOYED_BASELINE,
    "Candidate branch": MAINTENANCE_BRANCH,
    "Deployed production baseline": DEPLOYED_BASELINE,
    "Candidate version": DISPLAY_VERSION,
    "Archive file": ARCHIVE_PATH,
}
ATTESTATION_DYNAMIC_FIELDS = _BASE.ATTESTATION_DYNAMIC_FIELDS


def _configure_base() -> None:
    values = {
        "VERSION": VERSION,
        "DISPLAY_VERSION": DISPLAY_VERSION,
        "DEPLOYED_BASELINE": DEPLOYED_BASELINE,
        "MAINTENANCE_BRANCH": MAINTENANCE_BRANCH,
        "MIGRATION_REVISION": MIGRATION_REVISION,
        "RELEASE_PATH": RELEASE_PATH,
        "BASELINE_RELEASE_PATH": BASELINE_RELEASE_PATH,
        "ARCHIVE_PATH": ARCHIVE_PATH,
        "PRODUCTION_RECORD_SHA256": PRODUCTION_RECORD_SHA256,
        "OPERATOR_PRODUCTION_MARKERS": OPERATOR_PRODUCTION_MARKERS,
        "REQUIRED_FILES": REQUIRED_FILES,
        "VERSION_SURFACES": VERSION_SURFACES,
        "PENDING_FIELDS": PENDING_FIELDS,
        "ATTESTATION_EXACT_FIELDS": ATTESTATION_EXACT_FIELDS,
        "ATTESTATION_DYNAMIC_FIELDS": ATTESTATION_DYNAMIC_FIELDS,
    }
    for name, value in values.items():
        setattr(_BASE, name, value)


def _require_markers(root: Path, path: str, markers: tuple[str, ...], label: str, failures: list[str]) -> None:
    target = root / path
    if not target.is_file():
        failures.append(f"{path}: required {label} file is missing")
        return
    text = target.read_text(encoding="utf-8")
    for marker in markers:
        if text.count(marker) < 1:
            failures.append(f"{path}: {label} is missing: {marker}")


def _check_v3225_source(root: Path, failures: list[str]) -> None:
    for path, markers in V3225_EXCEPTION_MARKERS.items():
        _require_markers(root, path, markers, "V3.2.25 collector-photo exception contract", failures)
    release_tool_markers = {
        "scripts/build-client-release.ps1": (
            '[string]$Version = "3.2.25"',
            MAINTENANCE_BRANCH,
            "scripts\\verify_v3_2_25_release.py",
            "scripts\\test_verify_v3_2_25_release.py",
            "ops\\releases\\V3.2.25.md",
            "verify_v3_2_25_release.py --phase package --package $zipPath --expected-source-commit $sourceCommit",
        ),
        "scripts/verify-client-release.py": (
            "V3225_CONTRACT_INPUTS",
            '"scripts/verify_v3_2_25_release.py"',
            '"scripts/test_verify_v3_2_25_release.py"',
            '"ops/releases/V3.2.25.md"',
            "verify_v3225_archive_source_contract",
        ),
        "scripts/verify_release_sop.py": (
            'with_name("verify_v3_2_25_release.py")',
            'candidate == "V3.2.25"',
            '"scripts/verify_v3_2_25_release.py"',
            '"ops/releases/V3.2.25.md"',
        ),
    }
    for path, markers in release_tool_markers.items():
        _require_markers(root, path, markers, "V3.2.25 release gate", failures)


def _with_configured_base(callback):
    _configure_base()
    _BASE._configure_base()
    original_configure = _BASE._configure_base
    _BASE._configure_base = lambda: None
    try:
        return callback()
    finally:
        _BASE._configure_base = original_configure


def _check_source(root: Path, failures: list[str], *, require_pending_lifecycle: bool = True) -> None:
    original_check = _BASE._check_v3224_source
    _BASE._check_v3224_source = lambda _root, _failures: None
    try:
        _with_configured_base(
            lambda: _BASE._check_source(root, failures, require_pending_lifecycle=require_pending_lifecycle)
        )
    finally:
        _BASE._check_v3224_source = original_check
    _check_v3225_source(root, failures)


def _check_package(
    root: Path,
    package_path: Path | None,
    expected_source_commit: str | None,
    failures: list[str],
) -> None:
    _with_configured_base(
        lambda: _BASE._check_package(root, package_path, expected_source_commit, failures)
    )


def _check_attestation(
    root: Path,
    package_path: Path | None,
    expected_source_commit: str | None,
    failures: list[str],
) -> None:
    record_base = _BASE._BASE._BASE._BASE._BASE._BASE
    record = record_base._read(root, RELEASE_PATH, failures)
    for field, expected in ATTESTATION_EXACT_FIELDS.items():
        values = record_base._field_values(record, field)
        if values != [expected]:
            failures.append(f"{RELEASE_PATH}: attestation requires {field}: {expected} exactly once")
    for field in ATTESTATION_DYNAMIC_FIELDS:
        values = record_base._field_values(record, field)
        if len(values) != 1 or values[0].strip().casefold() in {"", "pending", "not run"}:
            failures.append(f"{RELEASE_PATH}: attestation requires one non-pending {field} value")
    source_commits = record_base._field_values(record, "Source commit")
    expected = (expected_source_commit or "").strip().lower()
    if len(source_commits) != 1 or re.fullmatch(r"[0-9a-f]{40}", source_commits[0]) is None or source_commits[0] != expected:
        failures.append(f"{RELEASE_PATH}: Source commit must equal the verified expected source commit exactly once")
    for field, pattern in {
        "Backup directory": r"/opt/module-manager-v2/backups/v3\.2\.24-\d{8}T\d{6}Z",
        "Release directory": r"/opt/module-manager-v2/releases/v3\.2\.25-\d{8}T\d{6}Z",
        "Rollback directory": r"/opt/module-manager-v2/releases/v3\.2\.24-\d{8}T\d{6}Z",
    }.items():
        values = record_base._field_values(record, field)
        if len(values) != 1 or re.fullmatch(pattern, values[0]) is None:
            failures.append(f"{RELEASE_PATH}: {field} must be one canonical immutable release path")
    for field in ("Local health", "Public health"):
        values = record_base._field_values(record, field)
        if len(values) != 1 or re.fullmatch(r"HTTP\s+200\s+version\s+3\.2\.25", values[0], re.IGNORECASE) is None:
            failures.append(f"{RELEASE_PATH}: {field} must prove HTTP 200 for version 3.2.25")
    hashes = {field: record_base._field_values(record, field) for field in ("SHA256", "Server SHA256")}
    if all(len(values) == 1 for values in hashes.values()) and package_path is not None and Path(package_path).is_file():
        actual = hashlib.sha256(Path(package_path).read_bytes()).hexdigest()
        if hashes["SHA256"][0] != actual or hashes["Server SHA256"][0] != actual:
            failures.append(f"{RELEASE_PATH}: package SHA256 values must equal the verified package bytes")


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
        _check_package(Path(root), package_path, expected_source_commit, failures)
    else:
        _check_source(Path(root), failures, require_pending_lifecycle=False)
        _check_package(Path(root), package_path, expected_source_commit, failures)
        _check_attestation(Path(root), package_path, expected_source_commit, failures)
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the V3.2.25 source, package, or attestation contract.")
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
    print(f"[OK] V3.2.25 {args.phase} release contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
