#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "3.2.1"
DISPLAY_VERSION = "V3.2.1"
REQUIRED_KPI_FILES = (
    "scripts/verify_v3_2_1_installer_kpi_restore.py",
    "v2-web/src/components/InstallerKpiDialog.vue",
    "v2-web/src/utils/installerKpi.ts",
    "ops/releases/V3.2.1.md",
)
RELEASE_NOTE_ITEMS = (
    "项目驾驶舱重新以独立弹窗展示安装人员每日工作量、效率、工时和异常明细。",
    "恢复 2 小时工时分段、分段地址清单、异常资料组下钻和页面内 KPI CSV。",
    "保留日、周、月范围与数据中台“查看原始资料”次级入口，KPI 公式、接口和生产数据不变。",
)
PENDING_LIFECYCLE_FIELDS = {
    "Status": "pending",
    "Local Verification": "not run",
    "Package": "pending",
    "Production Deployment": "pending",
    "Production Reconciliation": "pending",
    "Rollback target": "V3.2.0",
}
PENDING_MANIFEST_FIELDS = (
    "Generated at",
    "Size",
    "SHA256",
    "Source commit",
    "Production release",
)
V320_ARTIFACT_EVIDENCE = (
    "module-manager-v2-server-3.2.0.zip",
    "2026-07-24 10:33:21 +08:00",
    "1621627 bytes",
    "9448EDDCA27A36F2DF606EC1BC04A3BED05930B3D4D718E2D10381EE7FAEE6DF",
    "fe527eb84064096321e727abf9ccbdc981e10b7e",
    "/opt/module-manager-v2/releases/v3.2.0-20260724_105649",
)
AFFIRMATIVE_PENDING_RECORD_PATTERNS = (
    re.compile(r"\b(?:deployed|shipped|released)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:deployment|production(?:\s+verification)?)\s+"
        r"(?:(?:has|was|is)\s+)?(?:been\s+)?(?:completed|verified|successful|succeeded)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:the\s+)?release\s+(?:is|was|has\s+gone)\s+live\b", re.IGNORECASE),
    re.compile(r"已部署|已上线|部署(?:已)?(?:完成|成功)|已完成部署|上线完成|生产(?:已)?验证(?:通过)?|已发布"),
)
KPI_SOURCE_SHA256 = {
    "v2-web/src/components/InstallerKpiDialog.vue": (
        "488605be1de1bfcf022c9365253be5e352e94cc9e058aae879fce9b3b899f5dc"
    ),
    "v2-web/src/utils/installerKpi.ts": (
        "8d9e308fc073d4703ad22b116ee297571c4051df7e23ae8b9984c1f17ab46c78"
    ),
}


def read(relative_path: str, failures: list[str]) -> str:
    path = ROOT / relative_path
    if not path.is_file():
        failures.append(f"missing required file: {relative_path}")
        return ""
    return path.read_text(encoding="utf-8")


def require(text: str, marker: str, relative_path: str, failures: list[str]) -> None:
    if marker not in text:
        failures.append(f"{relative_path}: missing {marker!r}")


def verify_version_surfaces(failures: list[str]) -> None:
    source_version = read("v2-web/src/version.json", failures)
    try:
        version_artifact = json.loads(source_version)
    except json.JSONDecodeError as exc:
        failures.append(f"v2-web/src/version.json: invalid JSON: {exc}")
    else:
        if version_artifact != {"version": VERSION}:
            failures.append(
                f"v2-web/src/version.json: expected {{'version': {VERSION!r}}}, got {version_artifact!r}"
            )

    package = read("v2-web/package.json", failures)
    try:
        package_version = json.loads(package).get("version")
    except json.JSONDecodeError as exc:
        failures.append(f"v2-web/package.json: invalid JSON: {exc}")
    else:
        if package_version != VERSION:
            failures.append(f"v2-web/package.json: expected version {VERSION!r}, got {package_version!r}")

    required_markers = {
        "v2-web/index.html": f"<title>Module Manager {DISPLAY_VERSION}</title>",
        "v2-web/src/components/AppLayout.vue": DISPLAY_VERSION,
        "v2-api/app/main.py": f'version="{VERSION}"',
        "v2-api/app/services/ops_status.py": f'return "{VERSION}"',
        "v2-api/pyproject.toml": f'version = "{VERSION}"',
        "v2-api/scripts/verify_v3_1_release.py": f'EXPECTED_VERSION = "{VERSION}"',
    }
    for relative_path, marker in required_markers.items():
        require(read(relative_path, failures), marker, relative_path, failures)
    require(
        read("v2-api/pyproject.toml", failures),
        "Module Replacement Project Manager V3.2.1",
        "v2-api/pyproject.toml",
        failures,
    )


def verify_release_note(failures: list[str]) -> None:
    notes = read("v2-web/src/constants/releaseNotes.ts", failures)
    first_note = re.search(r"releaseNotes: ReleaseNote\[\] = \[\s*\{(?P<note>[\s\S]*?)\n  \},", notes)
    if first_note is None:
        failures.append("v2-web/src/constants/releaseNotes.ts: missing first release note")
        return
    note = first_note.group("note")
    require(note, f"version: '{DISPLAY_VERSION}'", "v2-web/src/constants/releaseNotes.ts", failures)
    require(note, "title: '安装人员 KPI 原模式恢复'", "v2-web/src/constants/releaseNotes.ts", failures)
    for item in RELEASE_NOTE_ITEMS:
        require(note, item, "v2-web/src/constants/releaseNotes.ts", failures)


def verify_manifest_pending_truth(manifest: str, failures: list[str]) -> None:
    artifact_values = [
        match.group("value").strip()
        for field in PENDING_MANIFEST_FIELDS
        if (match := re.search(rf"(?m)^- {re.escape(field)}:\s*(?P<value>.*?)\s*$", manifest))
    ]
    if any(marker in manifest for marker in V320_ARTIFACT_EVIDENCE) or any(
        re.search(r"(?i)\bv?3\.2\.0\b", value) for value in artifact_values
    ):
        failures.append("RELEASE_MANIFEST.md: must not retain V3.2.0 artifact evidence")
        return
    for field in PENDING_MANIFEST_FIELDS:
        match = re.search(rf"(?m)^- {re.escape(field)}:\s*(?P<value>.*?)\s*$", manifest)
        if match is None or match.group("value").strip() != "pending":
            failures.append(f"RELEASE_MANIFEST.md: {field} must be pending")


def verify_pending_record(record: str, failures: list[str]) -> None:
    record_path = "ops/releases/V3.2.1.md"
    require(record, "# V3.2.1 Production Release Record", record_path, failures)
    for field, value in PENDING_LIFECYCLE_FIELDS.items():
        matches = re.findall(rf"(?m)^[-*+]\s*{re.escape(field)}:\s*`?([^`\n]+)`?\s*$", record)
        if matches != [value]:
            failures.append(f"{record_path}: {field} must equal {value!r} exactly once; got {matches!r}")
    normalized_record = " ".join(record.split())
    if any(pattern.search(normalized_record) for pattern in AFFIRMATIVE_PENDING_RECORD_PATTERNS):
        failures.append(f"{record_path}: pending candidate must not claim deployment")


def verify_lifecycle(failures: list[str]) -> None:
    agents = read("AGENTS.md", failures)
    for marker in (
        "- Deployed production baseline: `V3.2.0`.",
        "- Release candidate: `V3.2.1`.",
        "- Release-candidate maintenance branch: `production/V3/3.2.1`.",
        "- 当前已部署生产版本：`V3.2.0`。",
        "- 当前发布候选版本：`V3.2.1`。",
        "- 当前候选维护分支：`production/V3/3.2.1`。",
    ):
        require(agents, marker, "AGENTS.md", failures)

    verify_pending_record(read("ops/releases/V3.2.1.md", failures), failures)


def verify_kpi_source_semantics(relative_path: str, text: str, failures: list[str]) -> None:
    if relative_path.endswith("InstallerKpiDialog.vue"):
        require(
            text,
            "import { fetchInstallerWorkload } from '@/api/services'",
            relative_path,
            failures,
        )
        if len(re.findall(r"\bfetchInstallerWorkload\s*\(", text)) != 1:
            failures.append(f"{relative_path}: must call fetchInstallerWorkload exactly once")
    else:
        require(
            text,
            "import type { InstallerWorkloadRow } from '@/api/types'",
            relative_path,
            failures,
        )
    if re.search(r"\b(?:fetch|XMLHttpRequest|axios)\b", text):
        failures.append(f"{relative_path}: must not make direct network calls")
    if re.search(r"\b(?:post|put|patch|delete)\s*\(", text):
        failures.append(f"{relative_path}: must not call write methods")
    if re.search(r"\b(?:create|download|queue|start)[A-Za-z0-9_]*(?:Export|export)[A-Za-z0-9_]*\s*\(", text):
        failures.append(f"{relative_path}: must not call export-job helpers")
    if re.search(r"['\"]/(?:[^'\"\n]*export)[^'\"\n]*['\"]", text, re.IGNORECASE):
        failures.append(f"{relative_path}: must not reference export routes")


def verify_kpi_source_contract(
    relative_path: str,
    source: str | bytes,
    failures: list[str],
) -> None:
    if isinstance(source, str):
        source_bytes = source.encode("utf-8")
        text = source
    else:
        source_bytes = source
        try:
            text = source.decode("utf-8")
        except UnicodeDecodeError as exc:
            failures.append(f"{relative_path}: source must be valid UTF-8: {exc}")
            return

    expected_digest = KPI_SOURCE_SHA256.get(relative_path)
    if expected_digest is None:
        failures.append(f"{relative_path}: missing reviewed source integrity digest")
        return
    actual_digest = hashlib.sha256(source_bytes).hexdigest()
    if actual_digest != expected_digest:
        failures.append(
            f"{relative_path}: source integrity mismatch: "
            f"expected SHA-256 {expected_digest}, got {actual_digest}"
        )
        return

    verify_kpi_source_semantics(relative_path, text, failures)


def verify_kpi_contract(failures: list[str]) -> None:
    for relative_path in REQUIRED_KPI_FILES:
        if not (ROOT / relative_path).is_file():
            failures.append(f"missing V3.2.1 KPI release input: {relative_path}")
    migrations = sorted((ROOT / "v2-api/alembic/versions").glob("*.py"))
    migration_names = [path.name for path in migrations]
    if "0014_export_center_jobs.py" not in migration_names or any(name > "0014_export_center_jobs.py" for name in migration_names):
        failures.append("database migration head must remain 0014_export_center_jobs.py")
    route = read("v2-api/app/api/routes/local_test.py", failures)
    require(route, '/installers/{installer}/daily-workload', "v2-api/app/api/routes/local_test.py", failures)
    services = read("v2-web/src/api/services.ts", failures)
    require(services, "fetchInstallerWorkload", "v2-web/src/api/services.ts", failures)
    for relative_path in REQUIRED_KPI_FILES[1:3]:
        path = ROOT / relative_path
        if path.is_file():
            verify_kpi_source_contract(relative_path, path.read_bytes(), failures)


def main() -> int:
    failures: list[str] = []
    verify_version_surfaces(failures)
    verify_release_note(failures)
    verify_manifest_pending_truth(read("RELEASE_MANIFEST.md", failures), failures)
    verify_lifecycle(failures)
    verify_kpi_contract(failures)
    if failures:
        print("[FAIL] V3.2.1 release checks failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("[OK] V3.2.1 release checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
