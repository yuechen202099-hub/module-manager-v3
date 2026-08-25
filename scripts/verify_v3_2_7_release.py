from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "3.2.7"
DISPLAY_VERSION = "V3.2.7"
DEPLOYED_BASELINE = "V3.2.6"
MAINTENANCE_BRANCH = "production/V3/3.2.7"
MIGRATION_REVISION = "20260824_0016"
PREVIOUS_REVISION = "20260823_0015"
RELEASE_PATH = "ops/releases/V3.2.7.md"
VERIFICATION_PHASES = frozenset(("source", "attestation"))
ORIGINAL_SOURCE_COMMIT = "8db0c64e82e98cdffa8e95ca83f6230236368b6a"
ORIGINAL_ZIP_SHA256 = "32D2365D1F3470D2A2476E8547DAE3B12AA0B43E903C8E387548028545DB5CAC"

REQUIRED_FILES = (
    "AGENTS.md",
    "RELEASE_MANIFEST.md",
    "docs/superpowers/specs/2026-08-23-collector-transfer-workbench-design.md",
    RELEASE_PATH,
    "scripts/build-client-release.ps1",
    "scripts/verify-client-release.py",
    "scripts/verify_release_sop.py",
    "scripts/verify_v3_2_7_release.py",
    "scripts/test_verify_v3_2_7_release.py",
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
)


def _read(root: Path, relative_path: str, failures: list[str]) -> str:
    path = root / relative_path
    if not path.is_file():
        failures.append(f"{relative_path}: required V3.2.7 file is missing")
        return ""
    return path.read_text(encoding="utf-8")


def _require_once(text: str, marker: str, path: str, failures: list[str]) -> None:
    if text.count(marker) != 1:
        failures.append(f"{path}: required marker must appear exactly once: {marker}")


def _check_project_inventory_contract(root: Path, failures: list[str]) -> None:
    required = {
        "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py": (
            f'revision = "{MIGRATION_REVISION}"',
            f'down_revision = "{PREVIOUS_REVISION}"',
            "project-scoped collector inventory is forward-only",
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
        "v2-web/src/views/CollectorInventoryView.vue": ("scanProjectCollector", "activeProjectId"),
    }
    for path, markers in required.items():
        text = _read(root, path, failures)
        for marker in markers:
            if marker not in text:
                failures.append(f"{path}: no-run inventory endpoint marker is missing: {marker}")

    frontend = _read(root, "v2-web/src/api/services.ts", failures)
    for marker in (
        "/collector-transfer/runs/${runId}/inventory/scan",
        "/collector-transfer/runs/${runId}/inventory",
    ):
        if marker in frontend:
            failures.append(f"v2-web/src/api/services.ts: retired mutating run-scan route must remain absent: {marker}")

    forbidden_markers = {
        "v2-api/app/api/routes/collector_transfer.py": (
            "inventory/import",
            "import_inventory",
            "CollectorImportRow",
        ),
        "v2-api/app/models.py": ("CollectorImportRow", "collector_import_rows"),
        "v2-api/app/services/collector_transfer.py": (
            "CollectorImportRow",
            "import_collector_inventory",
            "collector_import_rows",
        ),
        "v2-api/alembic/versions/0015_collector_transfer_workbench.py": (
            "collector_import_rows",
        ),
        "v2-web/src/api/services.ts": ("importCollectorInventory",),
        "v2-web/src/api/types.ts": ("CollectorInventoryImportResult",),
        "v2-web/src/views/CollectorInventoryView.vue": (
            "批量导入",
            "开始批量盘点",
            "import-view",
        ),
    }
    friendly = {
        "inventory/import": "retired collector inventory import",
        "import_inventory": "retired collector inventory import",
        "CollectorImportRow": "CollectorImportRow",
        "collector_import_rows": "collector_import_rows",
        "import_collector_inventory": "retired collector inventory import",
        "importCollectorInventory": "retired collector inventory import",
        "CollectorInventoryImportResult": "retired collector inventory import",
        "批量导入": "batch inventory UI",
        "开始批量盘点": "batch inventory UI",
        "import-view": "batch inventory UI",
    }
    for path, markers in forbidden_markers.items():
        text = _read(root, path, failures)
        for marker in markers:
            if marker in text:
                failures.append(f"{path}: {friendly[marker]} must remain retired")

    design_path = "docs/superpowers/specs/2026-08-23-collector-transfer-workbench-design.md"
    design = _read(root, design_path, failures)
    for marker in (
        "新采集器台账只通过手机网站逐个扫码建立",
        "不提供 Excel 或照片批量导入",
        "系统原有总清单、施工资料等导入能力不受此业务边界影响",
    ):
        if marker not in design:
            failures.append(f"{design_path}: retired-batch-import boundary is missing: {marker}")


def _check_release_tools(root: Path, failures: list[str]) -> None:
    requirements = {
        "scripts/build-client-release.ps1": (
            "scripts\\verify_v3_2_7_release.py",
            "scripts\\test_verify_v3_2_7_release.py",
            "ops\\releases\\V3.2.7.md",
        ),
        "scripts/verify-client-release.py": (
            '"scripts/verify_v3_2_7_release.py"',
            '"scripts/test_verify_v3_2_7_release.py"',
            '"ops/releases/V3.2.7.md"',
        ),
        "scripts/verify_release_sop.py": (
            '"scripts/verify_v3_2_7_release.py"',
            '"scripts/test_verify_v3_2_7_release.py"',
            '"ops/releases/V3.2.7.md"',
        ),
    }
    for path, markers in requirements.items():
        text = _read(root, path, failures)
        for marker in markers:
            if marker not in text:
                failures.append(f"{path}: V3.2.7 release gate marker is missing: {marker}")


def _check_source_release_record(root: Path, failures: list[str]) -> None:
    record = _read(root, RELEASE_PATH, failures)
    fields = {
        "Status": "deployed, recovered, production acceptance incomplete",
        "Local Verification": "passed before deployment",
        "Package": "passed",
        "Production Deployment": "incomplete after guarded smoke incident",
        "Production Reconciliation": "recovered with zero business-row additions",
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
        ORIGINAL_SOURCE_COMMIT,
        ORIGINAL_ZIP_SHA256,
        "/opt/module-manager-v2/releases/v3.2.7-20260824_173544",
        r"C:\Users\Administrator\Documents\module-manager-production-backups\20260824T161047Z",
        "HTTP `499`",
        "global OOM kill",
        "zero business-row additions",
        "worker and timer remain stopped",
        "no V3.2.7 attestation",
        MIGRATION_REVISION,
    ):
        if marker not in record:
            failures.append(f"{RELEASE_PATH}: immutable V3.2.7 evidence is missing: {marker}")
    if "V3.2.7 acceptance passed" in record:
        failures.append(f"{RELEASE_PATH}: must not claim V3.2.7 acceptance passed")


def _check_irreversible_migration_warning(root: Path, failures: list[str]) -> None:
    manifest_path = "RELEASE_MANIFEST.md"
    manifest = _read(root, manifest_path, failures)
    warning = "V3.1-V3.2 migrations `0006` through `0016` are production-irreversible"
    if warning not in manifest:
        failures.append(f"{manifest_path}: irreversible migration warning must include 0016")


def collect_failures(root: Path, phase: str) -> list[str]:
    root = Path(root)
    failures: list[str] = []
    if phase not in VERIFICATION_PHASES:
        return [f"verification phase must be one of {sorted(VERIFICATION_PHASES)}"]
    for path in REQUIRED_FILES:
        if not (root / path).is_file():
            failures.append(f"{path}: required V3.2.7 file is missing")
    _check_project_inventory_contract(root, failures)
    _check_irreversible_migration_warning(root, failures)
    _check_release_tools(root, failures)
    if phase == "source":
        _check_source_release_record(root, failures)
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the V3.2.7 source or attestation release contract.")
    parser.add_argument("--phase", required=True, choices=sorted(VERIFICATION_PHASES))
    args = parser.parse_args(argv)
    failures = collect_failures(ROOT, args.phase)
    if failures:
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"[OK] V3.2.7 {args.phase} release contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
