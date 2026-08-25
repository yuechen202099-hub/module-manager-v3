from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "3.2.8"
DISPLAY_VERSION = "V3.2.8"
DEPLOYED_BASELINE = "V3.2.7"
DEPLOYED_BASELINE_COMMIT = "8db0c64e82e98cdffa8e95ca83f6230236368b6a"
DEPLOYED_BASELINE_ZIP_SHA256 = "32D2365D1F3470D2A2476E8547DAE3B12AA0B43E903C8E387548028545DB5CAC"
MAINTENANCE_BRANCH = "production/V3/3.2.8"
MIGRATION_REVISION = "20260824_0016"
RELEASE_PATH = "ops/releases/V3.2.8.md"
BASELINE_RELEASE_PATH = "ops/releases/V3.2.7.md"
ARCHIVE_PATH = "build/server-release/module-manager-v2-server-3.2.8.zip"
VERIFICATION_PHASES = frozenset(("source", "attestation"))

SCALE_REGRESSION_PATH = "v2-api/tests/test_collector_transfer_scale.py"
CAMERA_REGRESSION_PATH = "v2-web/src/views/__tests__/CollectorInventoryView.spec.ts"

REQUIRED_FILES = (
    "AGENTS.md",
    "README.md",
    "RELEASE_MANIFEST.md",
    "docs/CLIENT_SIGNOFF_CHECKLIST.md",
    "docs/superpowers/specs/2026-08-23-collector-transfer-workbench-design.md",
    BASELINE_RELEASE_PATH,
    RELEASE_PATH,
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
    SCALE_REGRESSION_PATH,
    "v2-api/tests/test_v3_1_release.py",
    "v2-web/index.html",
    "v2-web/package.json",
    "v2-web/src/api/services.ts",
    "v2-web/src/api/types.ts",
    "v2-web/src/components/AppLayout.vue",
    "v2-web/src/constants/releaseNotes.ts",
    "v2-web/src/version.json",
    "v2-web/src/views/CollectorInventoryView.vue",
    CAMERA_REGRESSION_PATH,
)


def _read(root: Path, relative_path: str, failures: list[str]) -> str:
    path = root / relative_path
    if not path.is_file():
        failures.append(f"{relative_path}: required V3.2.8 file is missing")
        return ""
    return path.read_text(encoding="utf-8")


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


def _check_version_surfaces(root: Path, failures: list[str]) -> None:
    markers = {
        "v2-api/app/main.py": 'version="3.2.8"',
        "v2-api/app/services/ops_status.py": 'return "3.2.8"',
        "v2-api/pyproject.toml": 'version = "3.2.8"',
        "v2-api/scripts/verify_v3_1_release.py": 'EXPECTED_VERSION = "3.2.8"',
        "v2-api/tests/test_v3_1_release.py": 'EXPECTED_VERSION = "3.2.8"',
        "v2-web/index.html": "Module Manager V3.2.8",
        "v2-web/package.json": '"version": "3.2.8"',
        "v2-web/src/components/AppLayout.vue": "V3.2.8",
        "v2-web/src/constants/releaseNotes.ts": "version: 'V3.2.8'",
        "v2-web/src/version.json": '"version":"3.2.8"',
        "RELEASE_MANIFEST.md": "- Version: 3.2.8",
    }
    for path, marker in markers.items():
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


def _check_scale_contract(root: Path, failures: list[str]) -> None:
    _require_markers(
        root,
        SCALE_REGRESSION_PATH,
        (
            "PRODUCTION_GROUP_COUNT = 22_358",
            "PRODUCTION_PHOTO_COUNT = 17_453",
            "def test_project_collector_lookup_is_bounded_at_production_cardinality(",
            "def test_project_meter_projection_streams_selected_columns_at_production_cardinality(",
            "def test_cancelled_asgi_scan_quiesces_with_exact_bounded_outcome(",
        ),
        "collector scale regression gate",
        failures,
    )
    _require_markers(
        root,
        "v2-api/app/services/collector_transfer.py",
        (
            "def _project_has_collector_number(",
            "def _project_meter_projection(",
            ".execution_options(yield_per=1_000)",
        ),
        "bounded collector source implementation",
        failures,
    )


def _check_camera_contract(root: Path, failures: list[str]) -> None:
    _require_markers(
        root,
        CAMERA_REGRESSION_PATH,
        (
            "catches a BarcodeDetector gate before getUserMedia by opening the preview without native detection",
            "catches removal of the generic-video retry",
            "catches setting scanning before the native preview has played",
            "catches removal of the Quagga fallback and its shared one-in-flight submission guard",
            "catches a camera startup timeout",
            "catches a timed-out rear-camera request that later retains tracks instead of releasing them",
            "catches late camera startup retaining tracks or Quagga callbacks after unmount",
        ),
        "collector camera regression gate",
        failures,
    )
    _require_markers(
        root,
        "v2-web/src/views/CollectorInventoryView.vue",
        (
            "const stream = await requestCameraStream(session)",
            "await withCameraTimeout(preview.play()",
            "void startQuaggaScanner(session)",
            "navigator.mediaDevices.getUserMedia({ audio: false, video: true })",
            "stopMediaStream,",
            "script.src = '/static/vendor/quagga.min.js?v=20260615-quagga2'",
            "相机已打开，当前浏览器不支持实时识别，可手工输入或使用扫码枪。",
        ),
        "collector camera preview/fallback implementation",
        failures,
    )


def _check_unchanged_business_contract(root: Path, failures: list[str]) -> None:
    required = {
        "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py": (
            f'revision = "{MIGRATION_REVISION}"',
            'down_revision = "20260823_0015"',
        ),
        "v2-api/app/api/routes/collector_transfer.py": (
            '@router.post("/inventory/scan")',
            '@router.get("/inventory")',
            '@router.post("/inventory")',
            "project_id: str",
        ),
        "v2-api/app/services/collector_transfer.py": (
            "def scan_inventory(self, *, project_id: str, collector_no: str)",
            "def register_inventory(",
            "project_id=project.id",
        ),
        "v2-web/src/api/services.ts": ("'/collector-transfer/inventory/scan'",),
        "v2-web/src/views/CollectorInventoryView.vue": (
            "scanProjectCollector",
            "activeProjectId",
        ),
    }
    for path, markers in required.items():
        _require_markers(root, path, markers, "unchanged collector inventory contract", failures)

    forbidden = {
        "v2-api/app/api/routes/collector_transfer.py": ("inventory/import", "import_inventory"),
        "v2-api/app/services/collector_transfer.py": ("import_collector_inventory",),
        "v2-web/src/views/CollectorInventoryView.vue": ("批量导入", "开始批量盘点", "import-view"),
    }
    for path, markers in forbidden.items():
        text = _read(root, path, failures)
        for marker in markers:
            if marker in text:
                failures.append(f"{path}: no-batch collector contract was reintroduced: {marker}")


def _check_release_tools(root: Path, failures: list[str]) -> None:
    requirements = {
        "scripts/build-client-release.ps1": (
            '[string]$Version = "3.2.8"',
            MAINTENANCE_BRANCH,
            "scripts\\verify_v3_2_8_release.py",
            "scripts\\test_verify_v3_2_8_release.py",
            "v2-api\\tests\\test_collector_transfer_scale.py",
            "CollectorInventoryView.spec.ts",
            "ops\\releases\\V3.2.8.md",
        ),
        "scripts/verify-client-release.py": (
            '"scripts/verify_v3_2_8_release.py"',
            '"scripts/test_verify_v3_2_8_release.py"',
            f'"{SCALE_REGRESSION_PATH}"',
            f'"{CAMERA_REGRESSION_PATH}"',
            '"ops/releases/V3.2.8.md"',
            "verify_v328_archive_source_contract",
        ),
        "scripts/verify_release_sop.py": (
            '"scripts/verify_v3_2_8_release.py"',
            '"scripts/test_verify_v3_2_8_release.py"',
            f'"{SCALE_REGRESSION_PATH}"',
            f'"{CAMERA_REGRESSION_PATH}"',
            '"ops/releases/V3.2.8.md"',
            'with_name("verify_v3_2_8_release.py")',
        ),
    }
    for path, markers in requirements.items():
        _require_markers(root, path, markers, "V3.2.8 release gate", failures)


def _check_source_release_records(root: Path, failures: list[str]) -> None:
    record = _read(root, RELEASE_PATH, failures)
    fields = {
        "Status": "pending",
        "Local Verification": ("not run", "passed"),
        "Package": ("pending", "passed"),
        "Production Deployment": "pending",
        "Production Reconciliation": "pending",
        "Rollback target": DEPLOYED_BASELINE,
        "Candidate branch": f"`{MAINTENANCE_BRANCH}`",
        "Deployed production baseline": f"`{DEPLOYED_BASELINE}`",
        "Candidate version": f"`{DISPLAY_VERSION}`",
        "Database head": f"`{MIGRATION_REVISION} (head)`",
    }
    for field, expected in fields.items():
        values = re.findall(rf"(?m)^- {re.escape(field)}:\s*(.*?)\s*$", record)
        allowed = (expected,) if isinstance(expected, str) else expected
        if len(values) != 1 or values[0] not in allowed:
            failures.append(f"{RELEASE_PATH}: {field} must equal one of {allowed} exactly once")
    for marker in (
        "bounded single-collector lookup",
        "compact selected-column streaming",
        "pinned QuaggaJS scanner",
        "project/team isolation",
        "photo-first precedence",
        "mobile no-batch behavior",
        "API contracts are unchanged",
        "production acceptance is pending",
        MIGRATION_REVISION,
    ):
        if marker not in record:
            failures.append(f"{RELEASE_PATH}: release boundary is missing: {marker}")

    baseline = _read(root, BASELINE_RELEASE_PATH, failures)
    for marker in (
        "/opt/module-manager-v2/releases/v3.2.7-20260824_173544",
        DEPLOYED_BASELINE_ZIP_SHA256,
        r"C:\Users\Administrator\Documents\module-manager-production-backups\20260824T161047Z",
        "499",
        "OOM",
        "zero business-row additions",
        "no V3.2.7 attestation",
    ):
        if marker not in baseline:
            failures.append(f"{BASELINE_RELEASE_PATH}: immutable incident evidence is missing: {marker}")
    if "V3.2.7 acceptance passed" in baseline:
        failures.append(f"{BASELINE_RELEASE_PATH}: must not claim V3.2.7 acceptance passed")


def collect_failures(root: Path, phase: str) -> list[str]:
    root = Path(root)
    failures: list[str] = []
    if phase not in VERIFICATION_PHASES:
        return [f"verification phase must be one of {sorted(VERIFICATION_PHASES)}"]
    for path in REQUIRED_FILES:
        if not (root / path).is_file():
            failures.append(f"{path}: required V3.2.8 file is missing")
    _check_version_surfaces(root, failures)
    _check_scale_contract(root, failures)
    _check_camera_contract(root, failures)
    _check_unchanged_business_contract(root, failures)
    _check_release_tools(root, failures)
    if phase == "source":
        _check_source_release_records(root, failures)
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the V3.2.8 source or attestation release contract.")
    parser.add_argument("--phase", required=True, choices=sorted(VERIFICATION_PHASES))
    args = parser.parse_args(argv)
    failures = collect_failures(ROOT, args.phase)
    if failures:
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"[OK] V3.2.8 {args.phase} release contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
