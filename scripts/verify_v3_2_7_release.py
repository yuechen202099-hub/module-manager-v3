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

REQUIRED_FILES = (
    "scripts/verify_v3_2_7_release.py",
    "scripts/test_verify_v3_2_7_release.py",
    "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py",
    "v2-api/app/api/routes/collector_transfer.py",
    "v2-api/app/services/collector_transfer.py",
    "v2-api/tests/test_collector_transfer_api.py",
    "v2-api/tests/test_collector_transfer_service.py",
    "v2-web/src/api/services.ts",
    "v2-web/src/views/CollectorInventoryView.vue",
    RELEASE_PATH,
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


def _check_version_surfaces(root: Path, failures: list[str]) -> None:
    markers = {
        "v2-api/app/main.py": 'version="3.2.7"',
        "v2-api/app/services/ops_status.py": 'return "3.2.7"',
        "v2-api/pyproject.toml": 'version = "3.2.7"',
        "v2-api/scripts/verify_v3_1_release.py": 'EXPECTED_VERSION = "3.2.7"',
        "v2-api/tests/test_v3_1_release.py": 'EXPECTED_VERSION = "3.2.7"',
        "v2-web/index.html": "Module Manager V3.2.7",
        "v2-web/src/components/AppLayout.vue": "V3.2.7",
        "v2-web/src/constants/releaseNotes.ts": "version: 'V3.2.7'",
        "RELEASE_MANIFEST.md": "- Version: 3.2.7",
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


def _check_release_tools(root: Path, failures: list[str]) -> None:
    requirements = {
        "scripts/build-client-release.ps1": (
            '[string]$Version = "3.2.7"',
            "production/V3/3.2.7",
            "scripts\\verify_v3_2_7_release.py",
            "scripts\\test_verify_v3_2_7_release.py",
            "ops\\releases\\V3.2.7.md",
        ),
        "scripts/verify-client-release.py": (
            '"scripts/verify_v3_2_7_release.py"',
            '"scripts/test_verify_v3_2_7_release.py"',
            '"ops/releases/V3.2.7.md"',
            'with_name("verify_v3_2_7_release.py")',
        ),
        "scripts/verify_release_sop.py": (
            '"scripts/verify_v3_2_7_release.py"',
            '"scripts/test_verify_v3_2_7_release.py"',
            '"ops/releases/V3.2.7.md"',
            'with_name("verify_v3_2_7_release.py")',
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
        "current-project no-batch scanning",
        "atomic photo admission",
        "project isolation",
        "unchanged client-platform boundary",
        MIGRATION_REVISION,
    ):
        if marker not in record:
            failures.append(f"{RELEASE_PATH}: release boundary is missing: {marker}")


def collect_failures(root: Path, phase: str) -> list[str]:
    root = Path(root)
    failures: list[str] = []
    if phase not in VERIFICATION_PHASES:
        return [f"verification phase must be one of {sorted(VERIFICATION_PHASES)}"]
    for path in REQUIRED_FILES:
        if not (root / path).is_file():
            failures.append(f"{path}: required V3.2.7 file is missing")
    _check_version_surfaces(root, failures)
    _check_project_inventory_contract(root, failures)
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
