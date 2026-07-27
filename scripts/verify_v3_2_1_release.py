#!/usr/bin/env python3
from __future__ import annotations

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
IMPORT_FROM_PATTERN = re.compile(
    r"(?ms)^\s*import\s+(?P<binding>.*?)\s+from\s+['\"](?P<source>[^'\"]+)['\"]\s*;?"
)
IMPORT_SIDE_EFFECT_PATTERN = re.compile(r"(?m)^\s*import\s+['\"](?P<source>[^'\"]+)['\"]\s*;?")
KPI_ALLOWED_IMPORT_SOURCES = {
    "v2-web/src/components/InstallerKpiDialog.vue": {
        "vue",
        "@/api/services",
        "@/api/types",
        "@/utils/installerKpi",
    },
    "v2-web/src/utils/installerKpi.ts": {"@/api/types"},
}
REGEX_PREFIX_KEYWORDS = frozenset(
    {
        "await",
        "case",
        "delete",
        "do",
        "else",
        "in",
        "instanceof",
        "of",
        "return",
        "throw",
        "typeof",
        "void",
        "yield",
    }
)
CONTROL_HEAD_KEYWORDS = frozenset({"catch", "for", "if", "switch", "while", "with"})


def lexical_import_positions(text: str) -> list[int]:
    """Return executable ``import`` positions from self-contained JS/TS lexing."""
    positions: list[int] = []
    length = len(text)

    def identifier_part(character: str) -> bool:
        return character.isalnum() or character in "_$"

    def skip_quoted(index: int, quote: str) -> int:
        index += 1
        while index < length:
            if text[index] == "\\":
                index += 2
            elif text[index] == quote:
                return index + 1
            else:
                index += 1
        return index

    def regex_literal_end(index: int) -> int | None:
        cursor = index + 1
        in_character_class = False
        while cursor < length:
            character = text[cursor]
            if character in "\r\n":
                return None
            if character == "\\":
                cursor += 2
            elif character == "[" and not in_character_class:
                in_character_class = True
                cursor += 1
            elif character == "]" and in_character_class:
                in_character_class = False
                cursor += 1
            elif character == "/" and not in_character_class:
                cursor += 1
                while cursor < length and text[cursor].isalpha():
                    cursor += 1
                return cursor
            else:
                cursor += 1
        return None

    def scan_template(index: int) -> int:
        index += 1
        while index < length:
            if text[index] == "\\":
                index += 2
            elif text[index] == "`":
                return index + 1
            elif text.startswith("${", index):
                index = scan_code(index + 2, stop_at_template_brace=True)
            else:
                index += 1
        return index

    def scan_code(index: int, *, stop_at_template_brace: bool = False) -> int:
        can_start_regex = True
        brace_depth = 0
        parenthesis_context: list[bool] = []
        last_word: str | None = None
        while index < length:
            character = text[index]
            if text.startswith("//", index):
                newline = text.find("\n", index + 2)
                index = length if newline < 0 else newline + 1
                continue
            if text.startswith("/*", index):
                comment_end = text.find("*/", index + 2)
                index = length if comment_end < 0 else comment_end + 2
                continue
            if character in "'\"":
                index = skip_quoted(index, character)
                can_start_regex = False
                last_word = None
                continue
            if character == "`":
                index = scan_template(index)
                can_start_regex = False
                last_word = None
                continue
            if character == "/":
                closing_tag = (
                    index > 0
                    and text[index - 1] == "<"
                    and index + 1 < length
                    and (text[index + 1].isalpha() or text[index + 1] in "_$")
                )
                regex_end = None if closing_tag or not can_start_regex else regex_literal_end(index)
                if regex_end is not None:
                    index = regex_end
                    can_start_regex = False
                else:
                    index += 2 if text.startswith("/=", index) else 1
                    can_start_regex = True
                last_word = None
                continue
            if character.isalpha() or character in "_$":
                word_start = index
                index += 1
                while index < length and identifier_part(text[index]):
                    index += 1
                word = text[word_start:index]
                if word == "import":
                    positions.append(word_start)
                can_start_regex = word in REGEX_PREFIX_KEYWORDS
                last_word = word
                continue
            if character.isdigit():
                index += 1
                while index < length and (identifier_part(text[index]) or text[index] == "."):
                    index += 1
                can_start_regex = False
                last_word = None
                continue
            if character == "{":
                if stop_at_template_brace:
                    brace_depth += 1
                can_start_regex = True
            elif character == "}":
                if stop_at_template_brace and brace_depth == 0:
                    return index + 1
                if brace_depth:
                    brace_depth -= 1
                can_start_regex = False
            elif character == "(":
                parenthesis_context.append(last_word in CONTROL_HEAD_KEYWORDS)
                can_start_regex = True
            elif character == ")":
                can_start_regex = parenthesis_context.pop() if parenthesis_context else False
            elif character == "]":
                can_start_regex = False
            elif text.startswith("...", index):
                index += 3
                can_start_regex = True
                last_word = None
                continue
            elif text.startswith("++", index) or text.startswith("--", index):
                index += 2
                can_start_regex = False
                last_word = None
                continue
            elif character == ".":
                can_start_regex = False
            elif not character.isspace():
                can_start_regex = True
            if not character.isspace():
                last_word = None
            index += 1
        return index

    scan_code(0)
    return positions


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


def verify_kpi_source_contract(relative_path: str, text: str, failures: list[str]) -> None:
    lexical_positions = set(lexical_import_positions(text))
    static_imports = [
        (match, match.group("binding").strip(), match.group("source"))
        for match in IMPORT_FROM_PATTERN.finditer(text)
    ]
    static_imports.extend(
        (match, "<side-effect>", match.group("source")) for match in IMPORT_SIDE_EFFECT_PATTERN.finditer(text)
    )
    recognized_spans = [
        match.span()
        for match, _, _ in static_imports
        if next((position for position in lexical_positions if match.start() <= position < match.end()), None) is not None
    ]
    imports = [
        (binding, source)
        for match, binding, source in static_imports
        if match.span() in recognized_spans
    ]
    if any(not any(start <= position < end for start, end in recognized_spans) for position in lexical_positions):
        failures.append(f"{relative_path}: must not contain unrecognized import syntax")
    allowed_sources = KPI_ALLOWED_IMPORT_SOURCES[relative_path]
    for binding, source in imports:
        if source not in allowed_sources:
            failures.append(f"{relative_path}: must not import unsupported source {source}")
        elif source == "@/api/services" and binding != "{ fetchInstallerWorkload }":
            failures.append(f"{relative_path}: must import only fetchInstallerWorkload from @/api/services")
        elif source == "@/api/types" and not binding.startswith("type "):
            failures.append(f"{relative_path}: API declarations must be type-only")
    service_imports = [binding for binding, source in imports if source == "@/api/services"]
    if relative_path.endswith("InstallerKpiDialog.vue"):
        if service_imports != ["{ fetchInstallerWorkload }"]:
            failures.append(f"{relative_path}: must import only fetchInstallerWorkload from @/api/services")
        if len(re.findall(r"\bfetchInstallerWorkload\s*\(", text)) != 1:
            failures.append(f"{relative_path}: must call fetchInstallerWorkload exactly once")
    elif service_imports:
        failures.append(f"{relative_path}: must not import API services")
    if re.search(r"\b(?:fetch|XMLHttpRequest|axios)\b", text):
        failures.append(f"{relative_path}: must not make direct network calls")
    if re.search(r"\b(?:post|put|patch|delete)\s*\(", text):
        failures.append(f"{relative_path}: must not call write methods")
    if re.search(r"\b(?:create|download|queue|start)[A-Za-z0-9_]*(?:Export|export)[A-Za-z0-9_]*\s*\(", text):
        failures.append(f"{relative_path}: must not call export-job helpers")
    if re.search(r"['\"]/(?:[^'\"\n]*export)[^'\"\n]*['\"]", text, re.IGNORECASE):
        failures.append(f"{relative_path}: must not reference export routes")


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
        verify_kpi_source_contract(relative_path, read(relative_path, failures), failures)


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
