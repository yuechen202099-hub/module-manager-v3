from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import re
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "3.2.28"
DISPLAY_VERSION = "V3.2.28"
DEPLOYED_BASELINE = "V3.2.27"
MAINTENANCE_BRANCH = "production/V3/3.2.28"
MIGRATION_REVISION = "20260901_0017"
RELEASE_PATH = "ops/releases/V3.2.28.md"
BASELINE_RELEASE_PATH = "ops/releases/V3.2.27.md"
ARCHIVE_PATH = "build/server-release/module-manager-v2-server-3.2.28.zip"
PRODUCTION_RECORD_SHA256 = "b34b32b2979c2c11acc79b69c22fbd2e51bf024d223fcc5f96d7181a8df32a59"
CLAIM_TASKS_VIEW_PATH = "v2-web/src/views/ClaimTasksView.vue"
CLAIM_TASKS_VIEW_SHA256 = "d663dc8e0179cc96e54107b221760465bb282c31ce99d01cdf7573a9179da804"
VERIFICATION_PHASES = frozenset(("source", "package", "attestation"))


def _load_v3227_verifier():
    path = ROOT / "scripts" / "verify_v3_2_27_release.py"
    spec = importlib.util.spec_from_file_location("v3228_v3227_release_base", path)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load the immutable V3.2.27 release verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BASE = _load_v3227_verifier()
REQUIRED_FILES = tuple(
    dict.fromkeys(
        (
            *_BASE.REQUIRED_FILES,
            RELEASE_PATH,
            "scripts/verify_v3_2_28_release.py",
            "scripts/test_verify_v3_2_28_release.py",
            "v2-api/app/api/routes/material_exports.py",
            "v2-api/tests/test_material_export_api.py",
            "v2-web/src/views/ClaimTasksView.vue",
            "v2-web/src/views/__tests__/ClaimTasksMaterialExport.spec.ts",
        )
    )
)
RETIRED_BACKGROUND_BARCODE_FILES = _BASE.RETIRED_BACKGROUND_BARCODE_FILES
_V3226 = _BASE._BASE
EXPECTED_MIGRATION_FILES = frozenset(
    {
        "0001_initial_schema.py",
        "0002_local_state_postgres_bridge.py",
        "0003_photo_import_dedup_fields.py",
        "0004_allow_five_construction_tasks.py",
        "0005_add_construction_priority.py",
        "0006_group_barcode_verification.py",
        "0007_group_barcode_verification_lease_token.py",
        "0008_delivery_cache_jobs.py",
        "0009_delivery_cache_fix3.py",
        "0010_auto_archive_queue_state.py",
        "0011_delivery_package_jobs.py",
        "0012_delivery_package_group_ids_gin.py",
        "0013_data_center_query_indexes.py",
        "0014_export_center_jobs.py",
        "0015_collector_transfer_workbench.py",
        "0016_project_scoped_collector_inventory.py",
        "0017_material_exports.py",
    }
)

VERSION_SURFACES = {
    "v2-api/app/main.py": 'version="3.2.28"',
    "v2-api/app/services/ops_status.py": 'return "3.2.28"',
    "v2-api/pyproject.toml": 'version = "3.2.28"',
    "v2-api/scripts/verify_v3_1_release.py": 'EXPECTED_VERSION = "3.2.28"',
    "v2-api/tests/test_v3_1_release.py": 'EXPECTED_VERSION = "3.2.28"',
    "v2-web/index.html": "Module Manager V3.2.28",
    "v2-web/package.json": '"version": "3.2.28"',
    "v2-web/src/components/AppLayout.vue": "V3.2.28",
    "v2-web/src/constants/releaseNotes.ts": "version: 'V3.2.28'",
    "v2-web/src/version.json": '"version":"3.2.28"',
    "RELEASE_MANIFEST.md": "- Version: 3.2.28",
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


def _assignment_values(module: ast.Module, name: str) -> list[ast.expr]:
    values: list[ast.expr] = []
    for statement in module.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in statement.targets
        ):
            values.append(statement.value)
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) and statement.target.id == name:
            if statement.value is not None:
                values.append(statement.value)
    return values


def _is_disabled_guard(statement: ast.stmt) -> bool:
    if not isinstance(statement, ast.If):
        return False
    if not isinstance(statement.test, ast.Name) or statement.test.id != "MATERIAL_EXPORTS_TEMPORARILY_DISABLED":
        return False
    if len(statement.body) != 1 or not isinstance(statement.body[0], ast.Return):
        return False
    value = statement.body[0].value
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "_temporarily_disabled"
        and len(value.args) == 1
        and isinstance(value.args[0], ast.Name)
        and value.args[0].id == "request"
        and not value.keywords
    )


def _backend_containment_is_active(source: str) -> bool:
    try:
        module = ast.parse(source)
    except SyntaxError:
        return False
    flag_values = _assignment_values(module, "MATERIAL_EXPORTS_TEMPORARILY_DISABLED")
    if len(flag_values) != 1 or not isinstance(flag_values[0], ast.Constant) or flag_values[0].value is not True:
        return False
    functions = {
        statement.name: statement
        for statement in module.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and statement.name in {"reserve_job", "stream_file"}
    }
    return all(
        name in functions and bool(functions[name].body) and _is_disabled_guard(functions[name].body[0])
        for name in ("reserve_job", "stream_file")
    )


def _strip_javascript_non_code(source: str) -> str:
    output: list[str] = []
    index = 0
    state = "code"
    quote = ""
    while index < len(source):
        current = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if state == "code":
            if current in ("'", '"', "`"):
                state = "string"
                quote = current
                output.append(" ")
            elif current == "/" and following == "/":
                state = "line_comment"
                output.extend("  ")
                index += 1
            elif current == "/" and following == "*":
                state = "block_comment"
                output.extend("  ")
                index += 1
            else:
                output.append(current)
        elif state == "string":
            output.append("\n" if current == "\n" else " ")
            if current == "\\" and following:
                output.append("\n" if following == "\n" else " ")
                index += 1
            elif current == quote:
                state = "code"
        elif state == "line_comment":
            output.append("\n" if current == "\n" else " ")
            if current == "\n":
                state = "code"
        else:
            output.append("\n" if current == "\n" else " ")
            if current == "*" and following == "/":
                output.append(" ")
                index += 1
                state = "code"
        index += 1
    return "".join(output)


def _top_level_material_export_assignments(source: str) -> list[str]:
    declaration_pattern = re.compile(r"\b(?:const|let|var)\s+MATERIAL_EXPORT_ENABLED\s*=")
    brace_depth = 0
    depths: list[int] = []
    for character in source:
        depths.append(brace_depth)
        if character == "{":
            brace_depth += 1
        elif character == "}" and brace_depth > 0:
            brace_depth -= 1

    values: list[str] = []
    for declaration in declaration_pattern.finditer(source):
        if depths[declaration.start()] != 0:
            continue
        line_end = len(source)
        for terminator in ("\r", "\n"):
            position = source.find(terminator, declaration.end())
            if position >= 0:
                line_end = min(line_end, position)
        expression = source[declaration.end():line_end].strip()
        if expression.endswith(";"):
            expression = expression[:-1].rstrip()
        values.append(expression if expression in {"true", "false"} else "<non-literal>")
    return values


def _frontend_containment_is_active(source: str) -> bool:
    without_html_comments = re.sub(r"<!--.*?-->", "", source, flags=re.DOTALL)
    script_blocks = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", without_html_comments, flags=re.DOTALL | re.IGNORECASE)
    executable_script = "\n".join(_strip_javascript_non_code(block) for block in script_blocks)
    return _top_level_material_export_assignments(executable_script) == ["false"]


def _check_inherited_release_safety(root: Path, failures: list[str]) -> None:
    historical_baseline = root / _V3226.BASELINE_RELEASE_PATH
    if historical_baseline.is_file() and hashlib.sha256(historical_baseline.read_bytes()).hexdigest() != _V3226.PRODUCTION_RECORD_SHA256:
        failures.append(f"{_V3226.BASELINE_RELEASE_PATH}: immutable production baseline must remain byte-identical")

    migration_root = root / "v2-api/alembic/versions"
    actual_migrations = frozenset(path.name for path in migration_root.glob("*.py")) if migration_root.is_dir() else frozenset()
    if actual_migrations != EXPECTED_MIGRATION_FILES:
        missing = sorted(EXPECTED_MIGRATION_FILES - actual_migrations)
        unexpected = sorted(actual_migrations - EXPECTED_MIGRATION_FILES)
        failures.append(
            "v2-api/alembic/versions: no new Alembic migration is permitted; "
            f"approved Alembic file chain mismatch; missing={missing}, unexpected={unexpected}"
        )

    for relative_path in _V3226.REVIEWED_EXECUTABLE_BASH_BLOCKS:
        _V3226._check_reviewed_executable_bash_block(
            relative_path,
            _read(root, relative_path, failures),
            failures,
        )


def _check_source(root: Path, failures: list[str], *, require_pending: bool = True) -> None:
    for relative_path in REQUIRED_FILES:
        if not (root / relative_path).is_file():
            failures.append(f"{relative_path}: required V3.2.28 source file is missing")

    for relative_path, marker in VERSION_SURFACES.items():
        if marker not in _read(root, relative_path, failures):
            failures.append(f"{relative_path}: active version surface is not {VERSION}")

    _check_inherited_release_safety(root, failures)

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

    route = _read(root, "v2-api/app/api/routes/material_exports.py", failures)
    if not _backend_containment_is_active(route):
        failures.append("material export server containment is not enabled")

    task_view_path = root / CLAIM_TASKS_VIEW_PATH
    task_view = _read(root, CLAIM_TASKS_VIEW_PATH, failures)
    if (
        not task_view_path.is_file()
        or hashlib.sha256(task_view_path.read_bytes()).hexdigest() != CLAIM_TASKS_VIEW_SHA256
        or not _frontend_containment_is_active(task_view)
    ):
        failures.append("task-dispatch export actions are not disabled")
    if 'data-testid="material-export-disabled-notice"' not in task_view:
        failures.append("task-dispatch export containment notice is missing")

    release_tools = {
        "scripts/build-client-release.ps1": (
            '[string]$Version = "3.2.28"',
            MAINTENANCE_BRANCH,
            "scripts\\verify_v3_2_28_release.py",
            "scripts\\test_verify_v3_2_28_release.py",
        ),
        "scripts/verify-client-release.py": (
            "V3228_CONTRACT_INPUTS",
            "verify_v3228_archive_source_contract",
            '"3.2.28"',
        ),
        "scripts/verify_release_sop.py": (
            'candidate == "V3.2.28"',
            'with_name("verify_v3_2_28_release.py")',
            '"ops/releases/V3.2.28.md"',
        ),
    }
    for relative_path, markers in release_tools.items():
        text = _read(root, relative_path, failures)
        for marker in markers:
            if marker not in text:
                failures.append(f"{relative_path}: missing V3.2.28 release marker: {marker}")


def _check_package(
    package_path: Path | None,
    expected_source_commit: str | None,
    failures: list[str],
) -> None:
    if package_path is None or not package_path.is_file():
        failures.append("V3.2.28 package path is missing")
        return
    try:
        with zipfile.ZipFile(package_path) as archive:
            names = set(archive.namelist())
            missing = sorted(set(REQUIRED_FILES) - names)
            if missing:
                failures.append("package missing V3.2.28 contract files: " + ", ".join(missing))
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
                failures.append("package release manifest version is not 3.2.28")
    except (KeyError, OSError, zipfile.BadZipFile, UnicodeError) as exc:
        failures.append(f"unable to verify V3.2.28 package: {exc}")


def _check_attestation(
    root: Path,
    package_path: Path | None,
    expected_source_commit: str | None,
    failures: list[str],
) -> None:
    record = _read(root, RELEASE_PATH, failures)
    for field in ("Status", "Local Verification", "Package", "Production Deployment", "Production Reconciliation"):
        _require_exact_field(record, field, "attested" if field == "Status" else "passed", failures)
    expected_commit = (expected_source_commit or "").strip().lower()
    if _field_values(record, "Source commit") != [expected_commit] or re.fullmatch(r"[0-9a-f]{40}", expected_commit) is None:
        failures.append(f"{RELEASE_PATH}: Source commit must match the verified package source")
    for field in ("SHA256", "Server SHA256"):
        values = _field_values(record, field)
        if package_path is None or not package_path.is_file() or values != [hashlib.sha256(package_path.read_bytes()).hexdigest()]:
            failures.append(f"{RELEASE_PATH}: {field} must match package bytes")
    for field in ("Local health", "Public health"):
        _require_exact_field(record, field, "HTTP 200 version 3.2.28", failures)
    patterns = {
        "Backup directory": r"/opt/module-manager-v2/backups/V3\.2\.28-pre-\d{8}_\d{6}",
        "Release directory": r"/opt/module-manager-v2/releases/v3\.2\.28-\d{8}T\d{6}Z",
        "Rollback directory": r"/opt/module-manager-v2/releases/v3\.2\.27-\d{8}T\d{6}Z",
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
    parser = argparse.ArgumentParser(description="Verify the V3.2.28 source, package, or attestation contract.")
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
    print(f"[OK] V3.2.28 {args.phase} release contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
