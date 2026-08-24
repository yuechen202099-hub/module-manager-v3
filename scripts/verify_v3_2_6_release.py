from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "3.2.6"
DISPLAY_VERSION = "V3.2.6"
DEPLOYED_BASELINE = "V3.2.5"
MAINTENANCE_BRANCH = "production/V3/3.2.6"
MIGRATION_REVISION = "20260823_0015"
PREVIOUS_REVISION = "20260724_0014"
RELEASE_PATH = "ops/releases/V3.2.6.md"
VERIFICATION_PHASES = frozenset(("source", "attestation"))

REQUIRED_FILES = (
    "scripts/verify_v3_2_5_release.py",
    "scripts/verify_v3_2_6_release.py",
    "scripts/test_verify_v3_2_6_release.py",
    "v2-api/alembic/versions/0015_collector_transfer_workbench.py",
    "v2-api/app/api/routes/collector_transfer.py",
    "v2-api/app/domain/collector_transfer.py",
    "v2-api/app/services/collector_transfer.py",
    "v2-api/tests/test_collector_transfer_api.py",
    "v2-api/tests/test_collector_transfer_domain.py",
    "v2-api/tests/test_collector_transfer_postgres_integration.py",
    "v2-api/tests/test_collector_transfer_service.py",
    "v2-web/src/components/Code128Barcode.vue",
    "v2-web/src/views/CollectorBatchManagementView.vue",
    "v2-web/src/views/CollectorInventoryView.vue",
    "v2-web/src/views/CollectorWorkbenchView.vue",
    RELEASE_PATH,
)


def _read(root: Path, relative_path: str, failures: list[str]) -> str:
    path = root / relative_path
    if not path.is_file():
        failures.append(f"{relative_path}: required V3.2.6 file is missing")
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        failures.append(f"{relative_path}: must be UTF-8 text")
        return ""


def _require_once(text: str, marker: str, path: str, failures: list[str]) -> None:
    if text.count(marker) != 1:
        failures.append(f"{path}: required marker must appear exactly once: {marker}")


def _check_version_surfaces(root: Path, failures: list[str]) -> None:
    literal_markers = {
        "v2-api/app/main.py": 'version="3.2.6"',
        "v2-api/app/services/ops_status.py": 'return "3.2.6"',
        "v2-api/pyproject.toml": 'version = "3.2.6"',
        "v2-api/scripts/verify_v3_1_release.py": 'EXPECTED_VERSION = "3.2.6"',
        "v2-api/tests/test_v3_1_release.py": 'EXPECTED_VERSION = "3.2.6"',
        "v2-web/index.html": "Module Manager V3.2.6",
        "v2-web/src/components/AppLayout.vue": "V3.2.6",
        "v2-web/src/constants/releaseNotes.ts": "version: 'V3.2.6'",
        "RELEASE_MANIFEST.md": "- Version: 3.2.6",
    }
    for path, marker in literal_markers.items():
        _require_once(_read(root, path, failures), marker, path, failures)

    package_path = "v2-web/package.json"
    package_text = _read(root, package_path, failures)
    if package_text:
        try:
            package = json.loads(package_text)
        except json.JSONDecodeError:
            failures.append(f"{package_path}: invalid JSON")
        else:
            if package.get("version") != VERSION:
                failures.append(f"{package_path}: version must equal {VERSION}")

    for path in ("v2-web/src/version.json", "v2-api/app/static/vue/version.json"):
        text = _read(root, path, failures)
        if not text:
            continue
        try:
            artifact = json.loads(text)
        except json.JSONDecodeError:
            failures.append(f"{path}: invalid JSON")
            continue
        if not isinstance(artifact, dict) or artifact.get("version") != VERSION:
            failures.append(f"{path}: runtime version must equal {VERSION}")

    static_index_path = "v2-api/app/static/vue/index.html"
    static_index = _read(root, static_index_path, failures)
    if f"Module Manager V{VERSION}" not in static_index:
        failures.append(f"{static_index_path}: built title must equal V{VERSION}")

    agents_path = "AGENTS.md"
    agents = _read(root, agents_path, failures)
    for marker in (
        f"- Deployed production baseline: `{DEPLOYED_BASELINE}`.",
        f"- Release candidate: `{DISPLAY_VERSION}`.",
        f"- Release-candidate maintenance branch: `{MAINTENANCE_BRANCH}`.",
        f"- 当前已部署生产版本：`{DEPLOYED_BASELINE}`。",
        f"- 当前发布候选版本：`{DISPLAY_VERSION}`。",
        f"- 当前候选维护分支：`{MAINTENANCE_BRANCH}`。",
    ):
        _require_once(agents, marker, agents_path, failures)

    notes_path = "v2-web/src/constants/releaseNotes.ts"
    notes = _read(root, notes_path, failures)
    first_version = re.search(r"version:\s*'([^']+)'", notes)
    if first_version is None or first_version.group(1) != DISPLAY_VERSION:
        failures.append(f"{notes_path}: first release note must be {DISPLAY_VERSION}")


def _check_collector_contract(root: Path, failures: list[str]) -> None:
    required_markers = {
        "v2-api/app/api/router.py": (
            "collector_transfer",
            'api_router.include_router(collector_transfer.router, tags=["collector-transfer"])',
        ),
        "v2-api/app/main.py": (
            '"/collector-transfer"',
            '@app.get("/collector-inventory")',
            '@app.get("/collector-batches")',
            '@app.get("/collector-workbench")',
        ),
        "v2-web/src/router/index.ts": (
            "CollectorInventoryView.vue",
            "CollectorBatchManagementView.vue",
            "CollectorWorkbenchView.vue",
        ),
        "v2-web/src/router/staticPages.ts": (
            "'/collector-inventory'",
            "'/collector-batches'",
            "'/collector-workbench'",
        ),
        "v2-api/alembic/versions/0015_collector_transfer_workbench.py": (
            f'revision = "{MIGRATION_REVISION}"',
            f'down_revision = "{PREVIOUS_REVISION}"',
        ),
        "v2-api/tests/test_collector_transfer_api.py": (
            '"/collector-transfer/runs/run-1/inventory/import"',
            "assert response.status_code == 404",
        ),
        "v2-web/src/views/__tests__/CollectorInventoryView.spec.ts": (
            "aria-label=\"批量导入\"",
            ".exists()).toBe(false)",
        ),
    }
    for path, markers in required_markers.items():
        text = _read(root, path, failures)
        for marker in markers:
            if marker not in text:
                failures.append(f"{path}: collector-transfer contract marker is missing: {marker}")

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
    }
    for field, expected in fields.items():
        values = re.findall(rf"(?m)^- {re.escape(field)}:\s*(.*?)\s*$", record)
        allowed = (expected,) if isinstance(expected, str) else expected
        if len(values) != 1 or values[0] not in allowed:
            failures.append(f"{RELEASE_PATH}: {field} must equal one of {allowed} exactly once")
    for marker in (
        MIGRATION_REVISION,
        "/opt/module-manager-v2/releases/v3.2.5-20260823_030829",
        "本次不执行旧 release 清理",
        "已退役的 `POST /collector-transfer/runs/{run_id}/inventory/import` 必须返回 `404`",
    ):
        if marker not in record:
            failures.append(f"{RELEASE_PATH}: release boundary is missing: {marker}")


def _check_attestation_release_record(root: Path, failures: list[str]) -> None:
    record = _read(root, RELEASE_PATH, failures)
    summary = (
        "- Status: deployed",
        "- Local Verification: passed",
        "- Package: passed",
        "- Production Deployment: passed",
        "- Production Reconciliation: passed",
    )
    evidence_patterns = (
        r"(?m)^- 源码提交：`[0-9a-f]{40}`$",
        r"(?m)^- 本地 SHA256：`([0-9A-Fa-f]{64})`$",
        r"(?m)^- 服务器 SHA256：`([0-9A-Fa-f]{64})`$",
        r"(?m)^- 上线前备份：`/opt/module-manager-v2/backups/V3\.2\.6-[^`]+`$",
        r"(?m)^- 当前 release：`/opt/module-manager-v2/releases/v3\.2\.6-[^`]+`$",
        r"(?m)^- 本机 `/health`：`200`$",
        r"(?m)^- 公网 `/health`：`200`$",
        r"(?m)^- 数据库版本：`20260823_0015 \(head\)`$",
    )
    if any(marker not in record for marker in summary) or any(
        re.search(pattern, record) is None for pattern in evidence_patterns
    ):
        failures.append(f"{RELEASE_PATH}: complete deployment evidence is required for attestation")
        return
    local_hash = re.search(evidence_patterns[1], record)
    server_hash = re.search(evidence_patterns[2], record)
    if local_hash is None or server_hash is None or local_hash.group(1).lower() != server_hash.group(1).lower():
        failures.append(f"{RELEASE_PATH}: local and server SHA256 deployment evidence must match")


def _check_release_tools(root: Path, failures: list[str]) -> None:
    builder_path = "scripts/build-client-release.ps1"
    builder = _read(root, builder_path, failures)
    for marker in (
        '[string]$Version = "3.2.6"',
        'production/V3/3.2.6',
        'scripts\\verify_v3_2_6_release.py',
        'scripts\\test_verify_v3_2_6_release.py',
        'ops\\releases\\V3.2.6.md',
        '(Join-Path $root $releaseVerifier) --phase source',
    ):
        if marker not in builder:
            failures.append(f"{builder_path}: V3.2.6 release gate marker is missing: {marker}")

    package_verifier_path = "scripts/verify-client-release.py"
    package_verifier = _read(root, package_verifier_path, failures)
    for marker in (
        '"scripts/verify_v3_2_6_release.py"',
        '"scripts/test_verify_v3_2_6_release.py"',
        '"ops/releases/V3.2.6.md"',
        'with_name("verify_v3_2_6_release.py")',
    ):
        if marker not in package_verifier:
            failures.append(f"{package_verifier_path}: V3.2.6 package marker is missing: {marker}")

    sop_verifier_path = "scripts/verify_release_sop.py"
    sop_verifier = _read(root, sop_verifier_path, failures)
    for marker in (
        '"scripts/verify_v3_2_6_release.py"',
        '"scripts/test_verify_v3_2_6_release.py"',
        '"ops/releases/V3.2.6.md"',
        'with_name("verify_v3_2_6_release.py")',
    ):
        if marker not in sop_verifier:
            failures.append(f"{sop_verifier_path}: V3.2.6 SOP marker is missing: {marker}")


def collect_failures(root: Path, phase: str) -> list[str]:
    root = Path(root)
    failures: list[str] = []
    if phase not in VERIFICATION_PHASES:
        return [f"verification phase must be one of {sorted(VERIFICATION_PHASES)}"]
    for path in REQUIRED_FILES:
        if not (root / path).is_file():
            failures.append(f"{path}: required V3.2.6 file is missing")
    _check_version_surfaces(root, failures)
    _check_collector_contract(root, failures)
    _check_release_tools(root, failures)
    if phase == "source":
        _check_source_release_record(root, failures)
    else:
        _check_attestation_release_record(root, failures)
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the V3.2.6 source or attestation release contract.")
    parser.add_argument("--phase", required=True, choices=sorted(VERIFICATION_PHASES))
    args = parser.parse_args(argv)
    failures = collect_failures(ROOT, args.phase)
    if failures:
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"[OK] V3.2.6 {args.phase} release contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
