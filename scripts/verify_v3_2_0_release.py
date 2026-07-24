#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "3.2.0"
DISPLAY_VERSION = f"V{VERSION}"

RELEASE_ITEMS = (
    "数据中台统一审阅",
    "驾驶舱下钻",
    "统一导出中心",
    "审阅员角色下线",
    "明细分页支持 20/50/100",
)

FOCUSED_VERIFIERS = (
    "scripts/verify_v3_2_0_role_routes.py",
    "scripts/verify_v3_2_0_data_center_ui.py",
    "scripts/verify_v3_2_0_dashboard_drilldown.py",
    "scripts/verify_v3_2_0_export_center_ui.py",
    "scripts/verify_v3_2_0_single_export_entry.py",
    "scripts/verify_v3_2_0_release.py",
)

PACKAGE_FILES = (
    *FOCUSED_VERIFIERS,
    "v2-api/alembic/versions/0013_data_center_query_indexes.py",
    "v2-api/alembic/versions/0014_export_center_jobs.py",
    "v2-api/app/schemas/data_center.py",
    "v2-api/app/schemas/export_center.py",
    "v2-api/app/services/construction_task_rules.py",
    "v2-api/app/services/data_center.py",
    "v2-api/app/services/export_center.py",
    "v2-web/src/components/data-center/DataCenterFilters.vue",
    "v2-web/src/components/data-center/DataCenterReviewDialog.vue",
    "v2-web/src/components/export-center/ExportCatalogTab.vue",
    "v2-web/src/components/export-center/ExportJobsTable.vue",
    "v2-web/src/components/export-center/TerminalDeliveryTab.vue",
    "v2-web/src/views/GlobalSearchView.vue",
    "v2-web/src/views/ExportsView.vue",
    "ops/releases/V3.2.0.md",
)

FORBIDDEN_RELEASE_DIRECTORIES = (
    ".cache",
    ".mypy_cache",
    ".nyc_output",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vite",
    "__pycache__",
    "build",
    "coverage",
    "data",
    "dist",
    "htmlcov",
    "node_modules",
    "playwright-report",
    "test-results",
    "uploads",
)

FORBIDDEN_RELEASE_SUFFIXES = (
    ".db",
    ".dump",
    ".key",
    ".log",
    ".p12",
    ".pem",
    ".pfx",
    ".pyc",
    ".pyo",
    ".sql",
    ".sqlite",
    ".sqlite3",
)

FORBIDDEN_RELEASE_FILE_NAMES = (
    ".coverage",
    "coverage.xml",
    "junit.xml",
)

CLASSIFIER_FIXTURES = (
    {
        "path": "config/.env.production/settings.json",
        "is_directory": False,
        "forbidden": True,
    },
    {
        "path": "nested/.ENV.LOCAL/key.txt",
        "is_directory": False,
        "forbidden": True,
    },
    {
        "path": "artifacts/nested/.VeNv/pyvenv.cfg",
        "is_directory": False,
        "forbidden": True,
    },
    {
        "path": "artifacts/nested/BUILD/output.bin",
        "is_directory": False,
        "forbidden": True,
    },
    {
        "path": "certificates/client.PEM",
        "is_directory": False,
        "forbidden": True,
    },
    {
        "path": "database/production.DuMp",
        "is_directory": False,
        "forbidden": True,
    },
    {
        "path": "reports/coverage.xml",
        "is_directory": False,
        "forbidden": True,
    },
    {
        "path": "v2-web/src/main.ts",
        "is_directory": False,
        "forbidden": False,
    },
)


def read_text(relative_path: str, failures: list[str]) -> str:
    path = ROOT / relative_path
    if not path.is_file():
        failures.append(f"missing required file: {relative_path}")
        return ""
    return path.read_text(encoding="utf-8")


def require_contains(
    text: str,
    marker: str,
    relative_path: str,
    failures: list[str],
) -> None:
    if marker not in text:
        failures.append(f"{relative_path}: missing {marker!r}")


def powershell_string_array(
    text: str,
    variable_name: str,
    relative_path: str,
    failures: list[str],
) -> set[str]:
    assignment = powershell_array_text(
        text,
        variable_name,
        relative_path,
        failures,
    )
    if not assignment:
        return set()
    values = set(re.findall(r'"([^"]+)"', assignment))
    if not values:
        failures.append(f"{relative_path}: ${variable_name} has no string values")
    return values


def powershell_array_text(
    text: str,
    variable_name: str,
    relative_path: str,
    failures: list[str],
) -> str:
    match = re.search(
        rf"(?m)^\${re.escape(variable_name)}\s*=\s*@\(",
        text,
    )
    if match is None:
        failures.append(f"{relative_path}: missing ${variable_name} string array")
        return set()
    closing_index = text.find(")", match.end())
    if closing_index < 0:
        failures.append(f"{relative_path}: unterminated ${variable_name} string array")
        return ""
    return text[match.start():closing_index + 1]


def python_literal_set(
    text: str,
    variable_name: str,
    relative_path: str,
    failures: list[str],
) -> set[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        failures.append(f"{relative_path}: cannot parse Python source: {exc}")
        return set()
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == variable_name
            for target in statement.targets
        ):
            continue
        try:
            value = ast.literal_eval(statement.value)
        except (TypeError, ValueError) as exc:
            failures.append(
                f"{relative_path}: {variable_name} must be a literal set: {exc}"
            )
            return set()
        if not isinstance(value, set) or not all(
            isinstance(item, str) for item in value
        ):
            failures.append(
                f"{relative_path}: {variable_name} must be a string set"
            )
            return set()
        return value
    failures.append(f"{relative_path}: missing {variable_name}")
    return set()


def powershell_function_text(
    text: str,
    function_name: str,
    relative_path: str,
    failures: list[str],
) -> str:
    match = re.search(
        rf"(?m)^function\s+{re.escape(function_name)}\s*\{{",
        text,
    )
    if match is None:
        failures.append(f"{relative_path}: missing function {function_name}")
        return ""
    opening_index = text.find("{", match.start())
    depth = 0
    for index in range(opening_index, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[match.start():index + 1]
    failures.append(f"{relative_path}: unterminated function {function_name}")
    return ""


def python_function_text(
    text: str,
    function_name: str,
    relative_path: str,
    failures: list[str],
) -> str:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        failures.append(f"{relative_path}: cannot parse Python source: {exc}")
        return ""
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if statement.name == function_name:
                return ast.get_source_segment(text, statement) or ""
    failures.append(f"{relative_path}: missing function {function_name}")
    return ""


def execute_python_classifier(
    package_verifier: str,
    failures: list[str],
) -> dict[str, bool] | None:
    namespace = {
        "__name__": "v320_package_classifier",
        "__file__": str(ROOT / "scripts" / "verify-client-release.py"),
    }
    try:
        exec(
            compile(
                package_verifier,
                "scripts/verify-client-release.py",
                "exec",
            ),
            namespace,
        )
    except Exception as exc:
        failures.append(f"Python classifier source execution failed: {exc}")
        return None
    classifier = namespace.get("is_forbidden_release_path")
    if not callable(classifier):
        failures.append(
            "scripts/verify-client-release.py: "
            "is_forbidden_release_path is not callable"
        )
        return None

    results: dict[str, bool] = {}
    for fixture in CLASSIFIER_FIXTURES:
        path = str(fixture["path"])
        try:
            results[path] = bool(classifier(path))
        except Exception as exc:
            failures.append(
                f"Python classifier execution failed for {path}: {exc}"
            )
            return None
    return results


def powershell_single_quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def execute_powershell_classifier(
    build_script: str,
    failures: list[str],
) -> dict[str, bool] | None:
    array_names = (
        "forbiddenReleaseDirectoryNames",
        "forbiddenReleaseFileNames",
        "forbiddenReleaseFileSuffixes",
    )
    definitions = [
        powershell_array_text(
            build_script,
            name,
            "scripts/build-client-release.ps1",
            failures,
        )
        for name in array_names
    ]
    classifier = powershell_function_text(
        build_script,
        "Test-ForbiddenReleasePath",
        "scripts/build-client-release.ps1",
        failures,
    )
    if not all(definitions) or not classifier:
        return None

    with tempfile.TemporaryDirectory(prefix="v320-release-policy-") as temp_dir:
        temp_root = Path(temp_dir)
        staging = temp_root / "release-staging"
        staging.mkdir()
        fixtures_path = temp_root / "fixtures.json"
        fixtures_path.write_text(
            json.dumps(CLASSIFIER_FIXTURES),
            encoding="utf-8",
        )
        harness_path = temp_root / "verify-release-policy.ps1"
        harness = "\n".join(
            (
                '$ErrorActionPreference = "Stop"',
                *definitions,
                classifier,
                f"$staging = {powershell_single_quoted(str(staging))}",
                (
                    "$fixtures = Get-Content -Raw -LiteralPath "
                    f"{powershell_single_quoted(str(fixtures_path))} "
                    "| ConvertFrom-Json"
                ),
                "$results = @()",
                "foreach ($fixture in $fixtures) {",
                '    $relativePath = [string]$fixture.path',
                '    $windowsPath = $relativePath.Replace("/", "\\")',
                "    $fullPath = Join-Path $staging $windowsPath",
                "    $forbidden = Test-ForbiddenReleasePath `",
                "        -Path $fullPath `",
                "        -IsDirectory ([bool]$fixture.is_directory)",
                "    $results += [pscustomobject]@{",
                "        path = $relativePath",
                "        forbidden = [bool]$forbidden",
                "    }",
                "}",
                "Write-Output (ConvertTo-Json -InputObject $results -Compress)",
            )
        )
        harness_path.write_text(harness, encoding="utf-8")
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(harness_path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
    if result.returncode != 0:
        failures.append(
            "PowerShell classifier source execution failed: "
            + (result.stdout + result.stderr).strip()
        )
        return None
    try:
        raw_results = json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        failures.append(f"PowerShell classifier returned invalid JSON: {exc}")
        return None
    if not isinstance(raw_results, list):
        failures.append("PowerShell classifier result must be a JSON list")
        return None
    try:
        return {
            str(item["path"]): bool(item["forbidden"])
            for item in raw_results
        }
    except (KeyError, TypeError) as exc:
        failures.append(f"PowerShell classifier result is malformed: {exc}")
        return None


def verify_classifier_semantics(
    build_script: str,
    package_verifier: str,
    failures: list[str],
) -> None:
    python_results = execute_python_classifier(package_verifier, failures)
    powershell_results = execute_powershell_classifier(build_script, failures)
    if python_results is None or powershell_results is None:
        return

    fixture_paths = {str(fixture["path"]) for fixture in CLASSIFIER_FIXTURES}
    if set(python_results) != fixture_paths:
        failures.append("Python classifier did not return every semantic fixture")
    if set(powershell_results) != fixture_paths:
        failures.append("PowerShell classifier did not return every semantic fixture")
    for fixture in CLASSIFIER_FIXTURES:
        path = str(fixture["path"])
        expected = bool(fixture["forbidden"])
        python_actual = python_results.get(path)
        powershell_actual = powershell_results.get(path)
        expected_label = "forbidden" if expected else "allowed"
        if python_actual is not expected:
            actual_label = "forbidden" if python_actual else "allowed"
            failures.append(
                f"Python classifier mismatch for {path}: "
                f"expected {expected_label}, got {actual_label}"
            )
        if powershell_actual is not expected:
            actual_label = "forbidden" if powershell_actual else "allowed"
            failures.append(
                f"PowerShell classifier mismatch for {path}: "
                f"expected {expected_label}, got {actual_label}"
            )
        if python_actual != powershell_actual:
            failures.append(
                f"release classifiers disagree for {path}: "
                f"Python={python_actual!r}, PowerShell={powershell_actual!r}"
            )


def verify_version_surfaces(failures: list[str]) -> None:
    package_path = ROOT / "v2-web/package.json"
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        failures.append(f"v2-web/package.json: cannot read package version: {exc}")
    else:
        if package.get("version") != VERSION:
            failures.append(
                f"v2-web/package.json: expected version {VERSION!r}, "
                f"got {package.get('version')!r}"
            )

    index_html = read_text("v2-web/index.html", failures)
    require_contains(
        index_html,
        f"<title>Module Manager {DISPLAY_VERSION}</title>",
        "v2-web/index.html",
        failures,
    )

    main_py = read_text("v2-api/app/main.py", failures)
    if not re.search(rf'\bversion\s*=\s*"{re.escape(VERSION)}"', main_py):
        failures.append(f"v2-api/app/main.py: FastAPI version must be exactly {VERSION}")

    ops_status = read_text("v2-api/app/services/ops_status.py", failures)
    require_contains(
        ops_status,
        f'return "{VERSION}"',
        "v2-api/app/services/ops_status.py",
        failures,
    )

    source_version = read_text("v2-web/src/version.json", failures)
    try:
        source_version_artifact = json.loads(source_version)
    except json.JSONDecodeError as exc:
        failures.append(f"v2-web/src/version.json: invalid JSON: {exc}")
    else:
        if source_version_artifact != {"version": VERSION}:
            failures.append(
                "v2-web/src/version.json: "
                f"expected {{'version': {VERSION!r}}}, got {source_version_artifact!r}"
            )

    release_notes = read_text("v2-web/src/constants/releaseNotes.ts", failures)
    require_contains(
        release_notes,
        f"version: '{DISPLAY_VERSION}'",
        "v2-web/src/constants/releaseNotes.ts",
        failures,
    )
    for item in RELEASE_ITEMS:
        require_contains(
            release_notes,
            item,
            "v2-web/src/constants/releaseNotes.ts",
            failures,
        )

    operational_markers = {
        "README.md": (
            r".\.venv\Scripts\python.exe .\scripts\verify_release_sop.py --version V3.2.0",
            r".\scripts\build-client-release.ps1 -Version 3.2.0",
        ),
        "v2-web/src/components/AppLayout.vue": ("V3.2.0",),
        "v2-web/src/api/services.ts": ("V3.2.0-final-delivery-",),
        "v2-api/app/api/routes/exports.py": ("V3.2.0-final-delivery-",),
        "v2-api/pyproject.toml": (
            'version = "3.2.0"',
            "Module Replacement Project Manager V3.2.0",
        ),
        "v2-api/scripts/verify_v3_1_release.py": (
            'EXPECTED_VERSION = "3.2.0"',
        ),
    }
    for relative_path, markers in operational_markers.items():
        content = read_text(relative_path, failures)
        for marker in markers:
            require_contains(content, marker, relative_path, failures)


def verify_release_record(failures: list[str]) -> None:
    release_path = "ops/releases/V3.2.0.md"
    release_record = read_text(release_path, failures)
    required_markers = (
        "V3.1.1",
        "0013_data_center_query_indexes",
        "0014_export_center_jobs",
        "admin",
        ".env",
        "data",
        "uploads",
        "PostgreSQL",
        "rollback",
        "/health",
        "/system/status/version",
        "verify_v3_2_0_role_routes.py",
        "verify_v3_2_0_data_center_ui.py",
        "verify_v3_2_0_dashboard_drilldown.py",
        "verify_v3_2_0_export_center_ui.py",
        "verify_v3_2_0_single_export_entry.py",
        "verify_v3_2_0_release.py",
        "pytest",
        "npm run type-check",
        "npm run build",
        "SHA256",
        "PENDING_TASK_9",
    )
    for marker in required_markers:
        require_contains(release_record, marker, release_path, failures)

    manifest = read_text("RELEASE_MANIFEST.md", failures)
    for marker in (
        "module-manager-v2-server-3.2.0.zip",
        "- Version: 3.2.0",
        "verify_release_sop.py --version V3.2.0",
    ):
        require_contains(manifest, marker, "RELEASE_MANIFEST.md", failures)

    agents = read_text("AGENTS.md", failures)
    for marker in (
        "- Deployed production baseline: `V3.1.1`.",
        "- Release candidate: `V3.2.0`.",
        "- Release-candidate maintenance branch: `production/V3/3.2.0`.",
        "codebase-memory-mcp",
        "工具/skill",
        "数据中台",
        "导出中心",
        "MP-V1.0.xx",
        "PM-V1.0.xx",
        "正式生产 `V3.x.y`",
    ):
        require_contains(agents, marker, "AGENTS.md", failures)
    if "正式生产 `V3.0.xx`" in agents:
        failures.append("AGENTS.md: obsolete formal production namespace V3.0.xx remains")

    signoff_path = "docs/CLIENT_SIGNOFF_CHECKLIST.md"
    signoff = read_text(signoff_path, failures)
    for marker in (
        "V3.2.0 候选生产验证",
        "ops/releases/V3.2.0.md",
    ):
        require_contains(signoff, marker, signoff_path, failures)
    for stale_marker in (
        "V3.1.1 生产验证",
        "ops/releases/V3.1.1.md",
    ):
        if stale_marker in signoff:
            failures.append(f"{signoff_path}: stale candidate signoff marker {stale_marker!r}")


def verify_feature_files_and_routes(failures: list[str]) -> None:
    for relative_path in PACKAGE_FILES:
        if not (ROOT / relative_path).is_file():
            failures.append(f"missing V3.2.0 release input: {relative_path}")

    groups = read_text("v2-api/app/api/routes/groups.py", failures)
    for marker in (
        '@router.get("/data-center")',
        '@router.get("/data-center/{kind}/{item_id}")',
        '@router.patch("/data-center/groups/{group_id}")',
    ):
        require_contains(groups, marker, "v2-api/app/api/routes/groups.py", failures)

    exports = read_text("v2-api/app/api/routes/exports.py", failures)
    for marker in (
        '@router.get("/catalog")',
        '@router.get("/terminal-readiness")',
        '@router.get("/jobs")',
        '@router.post("/jobs")',
        '@router.get("/jobs/{job_id}/download")',
    ):
        require_contains(exports, marker, "v2-api/app/api/routes/exports.py", failures)

    for retired_path in (
        "v2-web/src/views/TaskHallView.vue",
        "v2-api/app/static/task_hall.html",
    ):
        if (ROOT / retired_path).exists():
            failures.append(f"retired reviewer/task-hall page restored: {retired_path}")

    navigation = "\n".join(
        (
            read_text("v2-web/src/layouts/AppLayout.vue", failures),
            read_text("v2-web/src/router/staticPages.ts", failures),
        )
    )
    for retired_marker in ("审阅工作台", "TaskHallView"):
        if retired_marker in navigation:
            failures.append(
                f"reviewer navigation still contains {retired_marker!r}"
            )

    for relative_path in (
        "docs/CLIENT_ACCEPTANCE_REPORT.md",
        "docs/CLIENT_FINAL_AUDIT.md",
        "docs/CLIENT_SIGNOFF_CHECKLIST.md",
    ):
        acceptance_document = read_text(relative_path, failures)
        for retired_marker in (
            "http://127.0.0.1:8000/task-hall",
            "reviewer / review123",
            "审阅员 demo 账号",
        ):
            if retired_marker in acceptance_document:
                failures.append(
                    f"{relative_path}: retired acceptance entry remains {retired_marker!r}"
                )


def verify_package_gates(failures: list[str]) -> None:
    build_script = read_text("scripts/build-client-release.ps1", failures)
    package_verifier = read_text("scripts/verify-client-release.py", failures)
    sop_verifier = read_text("scripts/verify_release_sop.py", failures)

    require_contains(
        build_script,
        '[string]$Version = "3.2.0"',
        "scripts/build-client-release.ps1",
        failures,
    )
    for relative_path in PACKAGE_FILES:
        normalized = relative_path.replace("/", "\\")
        if relative_path not in build_script and normalized not in build_script:
            failures.append(
                f"scripts/build-client-release.ps1: package copy gate missing {relative_path}"
            )
        if relative_path not in package_verifier:
            failures.append(
                f"scripts/verify-client-release.py: required-file gate missing {relative_path}"
            )

    for marker in (
        "verify_v3_2_0_release.py",
        "ops/releases/V3.2.0.md",
    ):
        require_contains(
            sop_verifier,
            marker,
            "scripts/verify_release_sop.py",
            failures,
        )

    symmetric_sets = (
        (
            "forbiddenReleaseDirectoryNames",
            "FORBIDDEN_PARTS",
            set(FORBIDDEN_RELEASE_DIRECTORIES),
        ),
        (
            "forbiddenReleaseFileSuffixes",
            "FORBIDDEN_SUFFIXES",
            set(FORBIDDEN_RELEASE_SUFFIXES),
        ),
        (
            "forbiddenReleaseFileNames",
            "FORBIDDEN_NAMES",
            set(FORBIDDEN_RELEASE_FILE_NAMES),
        ),
    )
    for build_name, verifier_name, expected in symmetric_sets:
        build_values = powershell_string_array(
            build_script,
            build_name,
            "scripts/build-client-release.ps1",
            failures,
        )
        verifier_values = python_literal_set(
            package_verifier,
            verifier_name,
            "scripts/verify-client-release.py",
            failures,
        )
        if build_values != verifier_values:
            failures.append(
                "release forbidden sets differ: "
                f"${build_name}={sorted(build_values)!r}, "
                f"{verifier_name}={sorted(verifier_values)!r}"
            )
        if build_values != expected:
            failures.append(
                f"${build_name}: expected {sorted(expected)!r}, "
                f"got {sorted(build_values)!r}"
            )
    verify_classifier_semantics(build_script, package_verifier, failures)
    if build_script.count(
        "Test-ForbiddenReleasePath -Path $_.FullName -IsDirectory"
    ) != 2:
        failures.append(
            "scripts/build-client-release.ps1: cleanup must classify both "
            "directories and files through Test-ForbiddenReleasePath"
        )
    if package_verifier.count("if is_forbidden_release_path(name):") != 1:
        failures.append(
            "scripts/verify-client-release.py: verify_package must classify "
            "every archive member through is_forbidden_release_path"
        )
    if "FORBIDDEN_PREFIXES" in package_verifier:
        failures.append(
            "scripts/verify-client-release.py: legacy prefix-only policy remains"
        )
    if build_script.count("Remove-ForbiddenReleaseItems") < 3:
        failures.append(
            "scripts/build-client-release.ps1: forbidden cleanup must run "
            "after source copy and after Vue build"
        )
    if 'Copy-ReleaseItem ".env.example"' in build_script:
        failures.append(
            "scripts/build-client-release.ps1: .env.example must not be copied"
        )


def verify_static_build(failures: list[str]) -> None:
    version_path = ROOT / "v2-api/app/static/vue/version.json"
    try:
        version_artifact = json.loads(version_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        failures.append(f"static version.json is missing or invalid: {exc}")
    else:
        if version_artifact.get("version") != VERSION:
            failures.append(
                "v2-api/app/static/vue/version.json: "
                f"expected version {VERSION!r}, got {version_artifact.get('version')!r}"
            )

    static_index = read_text("v2-api/app/static/vue/index.html", failures)
    require_contains(
        static_index,
        f"<title>Module Manager {DISPLAY_VERSION}</title>",
        "v2-api/app/static/vue/index.html",
        failures,
    )

    asset_dir = ROOT / "v2-api/app/static/vue/assets"
    javascript = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(asset_dir.glob("*.js"))
        if path.is_file()
    )
    require_contains(
        javascript,
        DISPLAY_VERSION,
        "v2-api/app/static/vue/assets/*.js",
        failures,
    )
    for item in RELEASE_ITEMS:
        require_contains(
            javascript,
            item,
            "v2-api/app/static/vue/assets/*.js",
            failures,
        )


def main() -> int:
    failures: list[str] = []
    verify_version_surfaces(failures)
    verify_release_record(failures)
    verify_feature_files_and_routes(failures)
    verify_package_gates(failures)
    verify_static_build(failures)

    if failures:
        print("[FAIL] V3.2.0 release checks failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("[OK] V3.2.0 release checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
