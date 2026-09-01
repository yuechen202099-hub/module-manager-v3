from __future__ import annotations

import argparse
import hashlib
import importlib.util
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "3.2.26"
DISPLAY_VERSION = "V3.2.26"
DEPLOYED_BASELINE = "V3.2.25"
MAINTENANCE_BRANCH = "production/V3/3.2.26"
MIGRATION_REVISION = "20260824_0016"
RELEASE_PATH = "ops/releases/V3.2.26.md"
BASELINE_RELEASE_PATH = "ops/releases/V3.2.25.md"
ARCHIVE_PATH = "build/server-release/module-manager-v2-server-3.2.26.zip"
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
PRODUCTION_RECORD_SHA256 = "74e8bafeaf919e57cd012f6f0f01753979231bb446a99265c5ec2185ad83de10"
OPERATOR_PRODUCTION_MARKERS = (
    "当前生产 release：`/opt/module-manager-v2/releases/v3.2.25-20260831T224124Z`",
    "当前回滚 release：`/opt/module-manager-v2/releases/v3.2.24-20260831T133027Z`",
    "当前生产提交：`ddfd09301612c5c278a1b7652a9be483f729d0cf`",
)
VERIFICATION_PHASES = frozenset(("source", "package", "attestation"))
BASH_CODE_BLOCK_PATTERN = re.compile(
    r"(?ms)^```bash[^\n]*\n(?P<code>.*?)^```[ \t]*$"
)
REVIEWED_EXECUTABLE_BASH_BLOCKS = {
    "docs/sop/06-production-deploy-runbook.md": (
        "Deploy",
        "rollback_cutover()",
        "1ae0fdf47453a8069ff9e265da8bf61a19a6e3fda32087c7e7eda42f9610b70b",
        "9ab7af28ba7906254fee7670a89a65970c6238671ab48aba0dc9d6e94012926a",
    ),
    "docs/sop/07-rollback-and-incident-review.md": (
        "Rollback Steps",
        "UNIT_BEFORE=$(mktemp)",
        "340991652b06f3575a8c20d672c9d76248457a3a6b199c4c86fcd78dfe64146f",
        "dd25a9aca8b24df5165137df500d9f2e0087b2439e3f2f8736eabacfcc77d87b",
    ),
}


def _load_v3225_verifier():
    path = ROOT / "scripts" / "verify_v3_2_25_release.py"
    spec = importlib.util.spec_from_file_location("v3226_v3225_release_base", path)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load the immutable V3.2.25 release verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BASE = _load_v3225_verifier()

REQUIRED_FILES = tuple(
    path
    for path in dict.fromkeys(
        (
            *_BASE.REQUIRED_FILES,
            RELEASE_PATH,
            "scripts/verify_v3_2_26_release.py",
            "scripts/test_verify_v3_2_26_release.py",
            "v2-api/app/api/router.py",
            "v2-api/tests/test_v21_data_rules.py",
        )
    )
    if path not in RETIRED_BACKGROUND_BARCODE_FILES
)

VERSION_SURFACES = {
    "v2-api/app/main.py": 'version="3.2.26"',
    "v2-api/app/services/ops_status.py": 'return "3.2.26"',
    "v2-api/pyproject.toml": 'version = "3.2.26"',
    "v2-api/scripts/verify_v3_1_release.py": 'EXPECTED_VERSION = "3.2.26"',
    "v2-api/tests/test_v3_1_release.py": 'EXPECTED_VERSION = "3.2.26"',
    "v2-web/index.html": "Module Manager V3.2.26",
    "v2-web/package.json": '"version": "3.2.26"',
    "v2-web/src/components/AppLayout.vue": "V3.2.26",
    "v2-web/src/constants/releaseNotes.ts": "version: 'V3.2.26'",
    "v2-web/src/version.json": '"version":"3.2.26"',
    "RELEASE_MANIFEST.md": "- Version: 3.2.26",
}

V3226_EXCEPTION_MARKERS = {
    "v2-api/app/services/data_center.py": (
        "DASHBOARD_IGNORED_EXCEPTION_REASONS = frozenset(",
        '"missing_collector_info"',
        '"缺少采集器信息"',
        "reasons.issubset(DASHBOARD_IGNORED_EXCEPTION_REASONS)",
    ),
    "v2-api/app/services/state_repository.py": (
        'reasons.op("<@")(ignored_reasons)',
        "data_center_service.DASHBOARD_IGNORED_EXCEPTION_REASONS",
        "def _validate_group_archive_with_module_map(",
    ),
    "v2-api/tests/test_data_center_review.py": (
        "test_data_center_exception_drilldown_ignores_collector_missing_reasons",
        "test_collector_only_gap_creates_no_open_data_center_anomaly",
        "test_json_approval_is_not_blocked_by_collector_only_gap",
        "missing_module_asset_no",
    ),
    "v2-api/tests/test_state_repository.py": (
        "test_postgres_installer_workload_ignores_only_missing_collector_photo_exception",
        "test_postgres_archive_validation_does_not_generate_missing_collector_info",
        "test_postgres_exception_listing_ignores_only_collector_missing_reasons",
        "test_postgres_approval_is_not_blocked_by_collector_only_gap",
        "test_postgres_exception_listing_is_read_only_for_stale_missing_module_note",
    ),
    "v2-api/tests/test_collector_transfer_service.py": (
        "test_review_workbench_ignores_stale_collector_missing_exceptions",
    ),
    "v2-api/tests/test_v21_data_rules.py": (
        "test_project_progress_ignores_collector_missing_reasons_but_keeps_real_exceptions",
    ),
}

V3226_BACKGROUND_BARCODE_RETIREMENT_MARKERS = {
    "v2-api/app/api/router.py": (
        "api_router.include_router(collector_transfer.router",
    ),
    "v2-api/app/main.py": (
        '"/collector-transfer"',
    ),
    "v2-api/tests/test_api.py": (
        "test_barcode_maintenance_routes_are_retired_for_every_role",
        "test_group_region_scan_resolves_trusted_photo_without_mutating_state",
    ),
    "docs/sop/06-production-deploy-runbook.md": (
        'systemctl disable --now "$unit"',
        'assert_retired_unit "$UNIT"',
        "wait_for_uvicorn",
        "rollback_cutover",
    ),
    "docs/sop/07-rollback-and-incident-review.md": (
        'systemctl disable --now "$unit"',
        'assert_retired_unit "$UNIT"',
        "wait_for_uvicorn",
    ),
    "scripts/build-client-release.ps1": (
        "$retiredBackgroundBarcodeReleasePaths",
    ),
    "scripts/verify-client-release.py": (
        "V3226_RETIRED_BACKGROUND_BARCODE_FILES",
        "def forbidden_files_for_version",
        "Release contains retired background barcode entrypoints",
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


def _check_v3226_source(root: Path, failures: list[str]) -> None:
    for path, markers in V3226_EXCEPTION_MARKERS.items():
        _require_markers(root, path, markers, "V3.2.26 collector-missing exception contract", failures)
    release_tool_markers = {
        "scripts/build-client-release.ps1": (
            '[string]$Version = "3.2.26"',
            MAINTENANCE_BRANCH,
            "scripts\\verify_v3_2_26_release.py",
            "scripts\\test_verify_v3_2_26_release.py",
            "ops\\releases\\V3.2.26.md",
            "verify_v3_2_26_release.py --phase package --package $zipPath --expected-source-commit $sourceCommit",
        ),
        "scripts/verify-client-release.py": (
            "V3226_CONTRACT_INPUTS",
            '"scripts/verify_v3_2_26_release.py"',
            '"scripts/test_verify_v3_2_26_release.py"',
            '"ops/releases/V3.2.26.md"',
            "verify_v3226_archive_source_contract",
        ),
        "scripts/verify_release_sop.py": (
            'with_name("verify_v3_2_26_release.py")',
            'candidate == "V3.2.26"',
            '"scripts/verify_v3_2_26_release.py"',
            '"ops/releases/V3.2.26.md"',
        ),
    }
    for path, markers in release_tool_markers.items():
        _require_markers(root, path, markers, "V3.2.26 release gate", failures)
    _check_background_barcode_retirement(root, failures)


def _check_background_barcode_retirement(root: Path, failures: list[str]) -> None:
    for path, markers in V3226_BACKGROUND_BARCODE_RETIREMENT_MARKERS.items():
        _require_markers(root, path, markers, "V3.2.26 background barcode retirement contract", failures)

    router_path = root / "v2-api/app/api/router.py"
    if router_path.is_file():
        router_text = router_path.read_text(encoding="utf-8")
        if "barcode_maintenance" in router_text:
            failures.append("v2-api/app/api/router.py: background barcode maintenance route is still registered")

    main_path = root / "v2-api/app/main.py"
    if main_path.is_file():
        main_text = main_path.read_text(encoding="utf-8")
        if '"/barcode-maintenance"' in main_text:
            failures.append("v2-api/app/main.py: retired background barcode route is still protected")

    runbook_path = root / "docs/sop/06-production-deploy-runbook.md"
    if runbook_path.is_file():
        runbook_text = runbook_path.read_text(encoding="utf-8")
        _check_reviewed_executable_bash_block(
            "docs/sop/06-production-deploy-runbook.md",
            runbook_text,
            failures,
        )
        for unit in (
            "module-manager-v2-photo-barcode-maintenance.service",
            "module-manager-v2-photo-barcode-maintenance-enqueue.service",
            "module-manager-v2-photo-barcode-maintenance.timer",
        ):
            if f"systemctl enable {unit}" in runbook_text or f"systemctl start {unit}" in runbook_text:
                failures.append(f"docs/sop/06-production-deploy-runbook.md: retired service is restarted: {unit}")
        _check_retired_unit_sop(
            "docs/sop/06-production-deploy-runbook.md",
            runbook_text,
            failures,
            deploy=True,
        )

    rollback_path = root / "docs/sop/07-rollback-and-incident-review.md"
    if rollback_path.is_file():
        rollback_text = rollback_path.read_text(encoding="utf-8")
        _check_reviewed_executable_bash_block(
            "docs/sop/07-rollback-and-incident-review.md",
            rollback_text,
            failures,
        )
        _check_retired_unit_sop(
            "docs/sop/07-rollback-and-incident-review.md",
            rollback_text,
            failures,
            deploy=False,
        )


def _check_reviewed_executable_bash_block(path: str, text: str, failures: list[str]) -> None:
    if "<!--" in text or "-->" in text:
        failures.append(f"{path}: HTML comments are forbidden in production SOP files")

    section_title, marker, expected_sha256, expected_section_sha256 = (
        REVIEWED_EXECUTABLE_BASH_BLOCKS[path]
    )
    section_pattern = re.compile(
        rf"(?ms)^## {re.escape(section_title)}[ \t]*\n.*?(?=^## |\Z)"
    )
    sections = section_pattern.findall(text)
    if len(sections) != 1:
        failures.append(f"{path}: reviewed SOP section must appear exactly once")
        return
    section = sections[0]
    actual_section_sha256 = hashlib.sha256(section.encode("utf-8")).hexdigest()
    if actual_section_sha256 != expected_section_sha256:
        failures.append(f"{path}: reviewed SOP section differs from approved bytes")

    blocks = [
        match.group("code")
        for match in BASH_CODE_BLOCK_PATTERN.finditer(section)
        if marker in match.group("code")
    ]
    if len(blocks) != 1:
        failures.append(f"{path}: reviewed executable Bash block must appear exactly once")
        return
    actual_sha256 = hashlib.sha256(blocks[0].encode("utf-8")).hexdigest()
    if actual_sha256 != expected_sha256:
        failures.append(f"{path}: executable Bash block differs from reviewed bytes")


def _check_retired_unit_sop(path: str, text: str, failures: list[str], *, deploy: bool) -> None:
    if re.search(r"systemctl disable --now[^\n]*\|\|\s*true", text):
        failures.append(f"{path}: retired unit disable is fail-open")

    fail_closed_query_markers = (
        'if ! LOAD_STATE=$(systemctl show "$unit" --property=LoadState --value); then',
        'if ! ACTIVE_STATE=$(systemctl show "$unit" --property=ActiveState --value); then',
        'if ! UNIT_FILE_STATE=$(systemctl show "$unit" --property=UnitFileState --value); then',
    )
    if (
        text.count(fail_closed_query_markers[0]) < 2
        or any(marker not in text for marker in fail_closed_query_markers[1:])
        or re.search(r"systemctl show[^\n]*\|\|\s*true", text)
    ):
        failures.append(f"{path}: retired unit state query is fail-open")

    disable_index = text.find('systemctl disable --now "$unit"')
    switch_marker = 'ln -sfn "$REL" "$APP/current"' if deploy else 'ln -sfn "$PREVIOUS" "$APP/current"'
    switch_index = text.find(switch_marker)
    if disable_index < 0 or switch_index < 0 or disable_index >= switch_index:
        failures.append(f"{path}: retired units are not disabled before release switch")

    unit_file_removal = text.find("rm -f \\")
    daemon_reload = text.find("systemctl daemon-reload", unit_file_removal + 1) if unit_file_removal >= 0 else -1
    migration_index = text.find("alembic upgrade head") if deploy else switch_index
    post_reload_check = text.find('assert_retired_unit "$UNIT"', daemon_reload + 1) if daemon_reload >= 0 else -1
    if (
        daemon_reload < 0
        or post_reload_check < 0
        or migration_index < 0
        or not (daemon_reload < post_reload_check < migration_index)
    ):
        failures.append(f"{path}: retired units are not rechecked before migration or release switch")

    readiness_index = text.rfind("wait_for_uvicorn")
    health_marker = "production_health_check.py"
    health_index = text.find(health_marker, readiness_index + 1) if readiness_index >= 0 else -1
    if (
        switch_index < 0
        or readiness_index < 0
        or health_index < 0
        or not (switch_index < readiness_index < health_index)
    ):
        failures.append(f"{path}: Uvicorn readiness is not checked before health acceptance")

    if deploy:
        required_rollback_markers = (
            'if [ -L "$APP/current" ]; then',
            'if ! PREVIOUS=$(readlink -f -- "$APP/current"); then',
            'validate_release_directory "$PREVIOUS"',
            'PREVIOUS_VERSION=${BASH_REMATCH[1]}',
            "rollback_cutover()",
            "trap rollback_cutover ERR",
        )
        if any(marker not in text for marker in required_rollback_markers):
            failures.append(f"{path}: previous release target is not validated")
        rollback_result_markers = (
            'elif ! RESTORED=$(readlink -f -- "$APP/current"); then',
            '[ "$restored" != "$PREVIOUS" ]',
            'Automatic rollback failed; current release state requires manual recovery.',
            '--expected-version "$PREVIOUS_VERSION"',
        )
        if any(marker not in text for marker in rollback_result_markers):
            failures.append(f"{path}: automatic rollback result is not verified")
    else:
        target_markers = (
            'if ! PREVIOUS=$(readlink -f -- "$PREVIOUS"); then',
            'validate_release_directory "$PREVIOUS"',
            'PREVIOUS_VERSION=${BASH_REMATCH[1]}',
        )
        if any(marker not in text for marker in target_markers):
            failures.append(f"{path}: manual rollback target is not validated")
        rollback_result_markers = (
            'if ! RESTORED=$(readlink -f -- "$APP/current"); then',
            '[ "$RESTORED" = "$PREVIOUS" ]',
            '--expected-version "$PREVIOUS_VERSION"',
        )
        if any(marker not in text for marker in rollback_result_markers):
            failures.append(f"{path}: manual rollback result is not verified")


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
    original_check = _BASE._check_v3225_source
    legacy_module = _BASE
    while hasattr(legacy_module, "_BASE"):
        legacy_module = legacy_module._BASE
    original_feature_markers = legacy_module.V3216_FEATURE_MARKERS
    original_test_markers = legacy_module.V3216_TEST_MARKERS
    feature_markers = dict(original_feature_markers)
    feature_markers["v2-api/app/services/data_center.py"] = tuple(
        marker
        for marker in feature_markers["v2-api/app/services/data_center.py"]
        if marker != "reasons == {DASHBOARD_IGNORED_EXCEPTION_REASON}"
    )
    superseded_test_paths = {
        "v2-api/tests/test_data_center_review.py",
        "v2-api/tests/test_state_repository.py",
        "v2-api/tests/test_v21_data_rules.py",
    }
    legacy_module.V3216_FEATURE_MARKERS = feature_markers
    legacy_module.V3216_TEST_MARKERS = tuple(
        marker for marker in original_test_markers if marker[0] not in superseded_test_paths
    )
    _BASE._check_v3225_source = lambda _root, _failures: None
    try:
        _with_configured_base(
            lambda: _BASE._check_source(root, failures, require_pending_lifecycle=require_pending_lifecycle)
        )
    finally:
        _BASE._check_v3225_source = original_check
        legacy_module.V3216_FEATURE_MARKERS = original_feature_markers
        legacy_module.V3216_TEST_MARKERS = original_test_markers
    _check_v3226_source(root, failures)


def _check_package(
    root: Path,
    package_path: Path | None,
    expected_source_commit: str | None,
    failures: list[str],
) -> None:
    _with_configured_base(
        lambda: _BASE._check_package(root, package_path, expected_source_commit, failures)
    )


def _record_base():
    module = _BASE
    while hasattr(module, "_BASE"):
        module = module._BASE
    return module


def _check_attestation(
    root: Path,
    package_path: Path | None,
    expected_source_commit: str | None,
    failures: list[str],
) -> None:
    record_base = _record_base()
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
        "Backup directory": r"/opt/module-manager-v2/backups/v3\.2\.25-\d{8}T\d{6}Z",
        "Release directory": r"/opt/module-manager-v2/releases/v3\.2\.26-\d{8}T\d{6}Z",
        "Rollback directory": r"/opt/module-manager-v2/releases/v3\.2\.25-\d{8}T\d{6}Z",
    }.items():
        values = record_base._field_values(record, field)
        if len(values) != 1 or re.fullmatch(pattern, values[0]) is None:
            failures.append(f"{RELEASE_PATH}: {field} must be one canonical immutable release path")
    for field in ("Local health", "Public health"):
        values = record_base._field_values(record, field)
        if len(values) != 1 or re.fullmatch(r"HTTP\s+200\s+version\s+3\.2\.26", values[0], re.IGNORECASE) is None:
            failures.append(f"{RELEASE_PATH}: {field} must prove HTTP 200 for version 3.2.26")
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
    parser = argparse.ArgumentParser(description="Verify the V3.2.26 source, package, or attestation contract.")
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
    print(f"[OK] V3.2.26 {args.phase} release contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
