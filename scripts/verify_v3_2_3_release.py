from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
VERSION = "3.2.3"
DISPLAY_VERSION = "V3.2.3"
DEPLOYED_BASELINE = "V3.2.2"
MAINTENANCE_BRANCH = "production/V3/3.2.3"
MIGRATION_FILE = "0014_export_center_jobs.py"
MIGRATION_REVISION = "20260724_0014"
RETIREMENT_MESSAGE = "导出中心已下线，请联系管理员由 OSS 导出到本机。"

RETIRED_EXACT_PATHS = frozenset(
    {
        "/local-test/export-manifest/final-delivery",
        "/local-test/unmatched/export",
        "/local-test/photo-barcode/review-groups/export",
    }
)
RETIRED_HEALTH_PATHS = (
    "/exports",
    "/exports/terminal-readiness",
    *sorted(RETIRED_EXACT_PATHS),
)
RETIRED_FRONTEND_FILES = (
    "v2-web/src/views/ExportsView.vue",
    "v2-web/src/composables/useExportCenterQuery.ts",
    "v2-web/src/components/export-center/ExportCatalogTab.vue",
    "v2-web/src/components/export-center/ExportJobsTable.vue",
    "v2-web/src/components/export-center/TerminalDeliveryTab.vue",
)
RETIRED_FRONTEND_MARKERS = (
    "title: '导出中心'",
    "ExportsView",
    "fetchExportCatalog",
    "fetchTerminalDeliveryReadiness",
    "fetchTerminalReadinessPage",
    "createExportJob",
    "downloadExportJob",
    "exportTerminalDeliveryPackage",
    "buildInstallerKpiCsv",
    "导出 KPI CSV",
)
REQUIRED_NEW_FILES = (
    "scripts/patch_export_retirement_nginx.py",
    "scripts/test_patch_export_retirement_nginx.py",
    "v2-api/app/services/export_retirement.py",
    "v2-api/tests/test_export_retirement.py",
    "v2-api/app/services/external_photo_oss_migration.py",
    "v2-api/scripts/build_oss_export_manifest.py",
    "v2-api/scripts/migrate_external_photos_to_oss.py",
    "v2-api/scripts/migrate_photos_to_oss.py",
    "scripts/oss_local_export.py",
    "scripts/test_oss_local_export.py",
    "scripts/verify_v3_2_3_release.py",
    "scripts/test_verify_v3_2_3_release.py",
    "docs/sop/09-export-retirement-and-oss-local-export.md",
    "ops/releases/V3.2.3.md",
)
REQUIRED_PACKAGE_MEMBERS = frozenset(REQUIRED_NEW_FILES)
FORBIDDEN_PACKAGE_CLASSIFIERS = frozenset(
    {
        "delivery-cache",
        "delivery_cache",
        "migration-reports",
        "migration_reports",
        "allowlists",
        "module-manager-exports",
    }
)

# Tests copy these paths into controlled repositories and exercise collect_failures.
CONTRACT_PATHS = (
    "AGENTS.md",
    "README.md",
    "RELEASE_MANIFEST.md",
    "docs/AGENT_REQUIRED_READING.md",
    "docs/CLIENT_SIGNOFF_CHECKLIST.md",
    "docs/sop/README.md",
    "docs/sop/09-export-retirement-and-oss-local-export.md",
    "ops/releases/V3.2.2.md",
    "ops/releases/V3.2.3.md",
    "scripts/build-client-release.ps1",
    "scripts/verify-client-release.py",
    "scripts/verify_release_sop.py",
    "scripts/production_health_check.py",
    "scripts/patch_export_retirement_nginx.py",
    "scripts/oss_local_export.py",
    "v2-api/alembic/versions",
    "v2-api/app/api/router.py",
    "v2-api/app/main.py",
    "v2-api/app/services/barcode_maintenance_worker.py",
    "v2-api/app/services/delivery_cache.py",
    "v2-api/app/services/delivery_package_queue.py",
    "v2-api/app/services/export_retirement.py",
    "v2-api/app/services/external_photo_oss_migration.py",
    "v2-api/app/services/local_simulation.py",
    "v2-api/app/services/ops_status.py",
    "v2-api/app/services/state_repository.py",
    "v2-api/pyproject.toml",
    "v2-api/scripts/build_oss_export_manifest.py",
    "v2-api/scripts/migrate_external_photos_to_oss.py",
    "v2-api/scripts/migrate_photos_to_oss.py",
    "v2-web/index.html",
    "v2-web/package.json",
    "v2-web/src",
    "v2-api/app/static/vue",
)


def _read(root: Path, relative_path: str, failures: list[str]) -> str:
    path = root / relative_path
    if not path.is_file():
        failures.append(f"{relative_path}: required file is missing")
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        failures.append(f"{relative_path}: cannot read UTF-8 source: {exc}")
        return ""


def _parse_python(root: Path, relative_path: str, failures: list[str]) -> ast.Module | None:
    source = _read(root, relative_path, failures)
    if not source:
        return None
    try:
        return ast.parse(source, filename=relative_path)
    except SyntaxError as exc:
        failures.append(f"{relative_path}: invalid Python syntax: {exc}")
        return None


def _literal_value(node: ast.AST, names: dict[str, Any] | None = None) -> Any:
    known = names or {}
    try:
        return ast.literal_eval(node)
    except (TypeError, ValueError):
        pass
    if isinstance(node, ast.Name) and node.id in known:
        return known[node.id]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        left = _literal_value(node.left, known)
        right = _literal_value(node.right, known)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return left * right
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"frozenset", "set", "tuple", "list"}
        and len(node.args) == 1
        and not node.keywords
    ):
        value = _literal_value(node.args[0], known)
        if value is not None:
            return {"frozenset": frozenset, "set": set, "tuple": tuple, "list": list}[
                node.func.id
            ](value)
    return None


def _literal_assignment(tree: ast.AST | None, name: str) -> Any:
    if tree is None:
        return None
    known: dict[str, Any] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = _literal_value(node.value, known)
            for target in targets:
                if isinstance(target, ast.Name):
                    known[target.id] = value
                    if target.id == name:
                        return value
    return None


def _functions(tree: ast.AST | None, name: str) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    if tree is None:
        return []
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]


def _first_statement(function: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.stmt | None:
    body = list(function.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return body[0] if body else None


def _call_leaf(call: ast.Call) -> str:
    target = call.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return ""


def _qualified_reference(node: ast.AST, bindings: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return bindings.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        owner = _qualified_reference(node.value, bindings)
        return f"{owner}.{node.attr}" if owner else node.attr
    return ""


def _import_and_alias_bindings(tree: ast.AST | None) -> dict[str, str]:
    bindings: dict[str, str] = {}
    if tree is None:
        return bindings
    nodes = list(ast.walk(tree))
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                bindings[alias.asname or alias.name.split(".", 1)[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                if alias.name != "*":
                    bindings[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    changed = True
    while changed:
        changed = False
        for node in nodes:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            qualified = _qualified_reference(node.value, bindings)
            if not qualified:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in bindings:
                    bindings[target.id] = qualified
                    changed = True
    return bindings


def _retired_path_predicate_is_reachable(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    returns = [statement for statement in function.body if isinstance(statement, ast.Return)]
    if len(returns) != 1 or not isinstance(returns[0].value, ast.BoolOp):
        return False
    expression = returns[0].value
    if not isinstance(expression.op, ast.Or) or len(expression.values) != 3:
        return False

    exact_path = False
    child_paths = False
    exact_set = False
    for value in expression.values:
        if (
            isinstance(value, ast.Compare)
            and isinstance(value.left, ast.Name)
            and value.left.id == "normalized"
            and len(value.ops) == 1
            and len(value.comparators) == 1
        ):
            comparator = value.comparators[0]
            exact_path = exact_path or (
                isinstance(value.ops[0], ast.Eq)
                and isinstance(comparator, ast.Constant)
                and comparator.value == "/exports"
            )
            exact_set = exact_set or (
                isinstance(value.ops[0], ast.In)
                and isinstance(comparator, ast.Name)
                and comparator.id == "RETIRED_EXACT_PATHS"
            )
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and value.func.attr == "startswith"
            and isinstance(value.func.value, ast.Name)
            and value.func.value.id == "normalized"
            and len(value.args) == 1
            and isinstance(value.args[0], ast.Constant)
            and value.args[0].value == "/exports/"
        ):
            child_paths = True
    return exact_path and child_paths and exact_set


def _first_is_call(function: ast.FunctionDef | ast.AsyncFunctionDef, call_name: str) -> bool:
    statement = _first_statement(function)
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and _call_leaf(statement.value) == call_name
    )


def _first_is_return(function: ast.FunctionDef | ast.AsyncFunctionDef, value: Any) -> bool:
    statement = _first_statement(function)
    return (
        isinstance(statement, ast.Return)
        and isinstance(statement.value, ast.Constant)
        and statement.value.value == value
    )


def _first_is_retired_raise(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    statement = _first_statement(function)
    if not isinstance(statement, ast.Raise) or not isinstance(statement.exc, ast.Call):
        return False
    return _call_leaf(statement.exc) == "ExportCenterRetiredError"


def _check_version_surfaces(root: Path, failures: list[str]) -> None:
    json_surfaces = {
        "v2-web/package.json": ("version", VERSION),
        "v2-web/src/version.json": ("version", VERSION),
    }
    for relative_path, (key, expected) in json_surfaces.items():
        source = _read(root, relative_path, failures)
        try:
            value = json.loads(source).get(key)
        except (json.JSONDecodeError, AttributeError):
            value = None
        if value != expected:
            failures.append(f"{relative_path}: {key} must equal {expected}")

    pyproject_source = _read(root, "v2-api/pyproject.toml", failures)
    try:
        project = tomllib.loads(pyproject_source).get("project", {})
    except tomllib.TOMLDecodeError:
        project = {}
    if project.get("version") != VERSION:
        failures.append(f"v2-api/pyproject.toml: project.version must equal {VERSION}")
    if DISPLAY_VERSION not in str(project.get("description") or ""):
        failures.append(f"v2-api/pyproject.toml: description must identify {DISPLAY_VERSION}")

    ops_tree = _parse_python(root, "v2-api/app/services/ops_status.py", failures)
    app_version_functions = _functions(ops_tree, "app_version")
    if len(app_version_functions) != 1 or not _first_is_return(app_version_functions[0], VERSION):
        failures.append(f"v2-api/app/services/ops_status.py: app_version() must return {VERSION}")

    main_tree = _parse_python(root, "v2-api/app/main.py", failures)
    fastapi_versions: list[str] = []
    if main_tree is not None:
        for node in ast.walk(main_tree):
            if isinstance(node, ast.Call) and _call_leaf(node) == "FastAPI":
                for keyword in node.keywords:
                    if keyword.arg == "version" and isinstance(keyword.value, ast.Constant):
                        fastapi_versions.append(str(keyword.value.value))
    if fastapi_versions != [VERSION]:
        failures.append(f"v2-api/app/main.py: FastAPI version must equal {VERSION} exactly once")

    text_surfaces = {
        "v2-web/index.html": f"<title>Module Manager {DISPLAY_VERSION}</title>",
        "v2-web/src/components/AppLayout.vue": f"<span>{DISPLAY_VERSION}</span>",
        "scripts/build-client-release.ps1": f'[string]$Version = "{VERSION}"',
        "RELEASE_MANIFEST.md": f"- Version: {VERSION}",
    }
    for relative_path, marker in text_surfaces.items():
        if marker not in _read(root, relative_path, failures):
            failures.append(f"{relative_path}: current version surface must contain {marker}")

    agents = _read(root, "AGENTS.md", failures)
    required_agent_markers = (
        f"Deployed production baseline: `{DEPLOYED_BASELINE}`",
        f"Release candidate: `{DISPLAY_VERSION}`",
        f"Release-candidate maintenance branch: `{MAINTENANCE_BRANCH}`",
        f"当前已部署生产版本：`{DEPLOYED_BASELINE}`",
        f"当前发布候选版本：`{DISPLAY_VERSION}`",
        f"当前候选维护分支：`{MAINTENANCE_BRANCH}`",
    )
    for marker in required_agent_markers:
        if agents.count(marker) != 1:
            failures.append(f"AGENTS.md: must define {marker} exactly once")


def _check_retirement_contract(root: Path, failures: list[str]) -> None:
    relative_path = "v2-api/app/services/export_retirement.py"
    tree = _parse_python(root, relative_path, failures)
    if _literal_assignment(tree, "RETIREMENT_MESSAGE") != RETIREMENT_MESSAGE:
        failures.append(f"{relative_path}: retirement message must match the fixed copy")
    if set(_literal_assignment(tree, "RETIRED_EXACT_PATHS") or ()) != set(RETIRED_EXACT_PATHS):
        failures.append(f"{relative_path}: retired path exact set is incomplete")
    predicates = _functions(tree, "is_retired_export_path")
    if len(predicates) != 1:
        failures.append(f"{relative_path}: one retired path predicate is required")
    elif not _retired_path_predicate_is_reachable(predicates[0]):
        failures.append(
            f"{relative_path}: retired path predicate must reach /exports, its children, and exact paths"
        )

    main_tree = _parse_python(root, "v2-api/app/main.py", failures)
    middleware = _functions(main_tree, "persist_local_test_state")
    if len(middleware) != 1:
        failures.append("v2-api/app/main.py: retirement middleware is missing")
    else:
        calls = [
            _call_leaf(node)
            for node in ast.walk(middleware[0])
            if isinstance(node, ast.Call)
        ]
        try:
            retired_index = calls.index("is_retired_export_path")
            auth_index = calls.index("production_auth_rejection")
        except ValueError:
            failures.append("v2-api/app/main.py: retirement and authentication calls are required")
        else:
            if retired_index >= auth_index:
                failures.append("v2-api/app/main.py: retirement gate must run before authentication")

    router_tree = _parse_python(root, "v2-api/app/api/router.py", failures)
    if router_tree is not None:
        for node in ast.walk(router_tree):
            if isinstance(node, ast.ImportFrom) and any(alias.name == "exports" for alias in node.names):
                failures.append("v2-api/app/api/router.py: exports router must remain disconnected")
            if isinstance(node, ast.Call) and _call_leaf(node) == "include_router":
                if node.args and isinstance(node.args[0], ast.Attribute):
                    if isinstance(node.args[0].value, ast.Name) and node.args[0].value.id == "exports":
                        failures.append("v2-api/app/api/router.py: exports router must remain disconnected")

    nginx = _read(root, "scripts/patch_export_retirement_nginx.py", failures)
    for path in ("/exports", "/exports/", *RETIRED_EXACT_PATHS):
        if path not in nginx:
            failures.append(f"scripts/patch_export_retirement_nginx.py: retired path missing: {path}")
    if RETIREMENT_MESSAGE not in nginx:
        failures.append("scripts/patch_export_retirement_nginx.py: retirement message must match the fixed copy")


def _check_frontend_retirement(root: Path, failures: list[str]) -> None:
    for relative_path in RETIRED_FRONTEND_FILES:
        if (root / relative_path).exists():
            failures.append(f"{relative_path}: retired Vue file must stay deleted")
    search_roots = (root / "v2-web" / "src", root / "v2-api" / "app" / "static" / "vue")
    for search_root in search_roots:
        if not search_root.exists():
            failures.append(f"{search_root.relative_to(root).as_posix()}: frontend source tree is missing")
            continue
        for path in search_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".ts", ".vue", ".js", ".html"}:
                continue
            source = path.read_text(encoding="utf-8", errors="ignore")
            for marker in RETIRED_FRONTEND_MARKERS:
                if marker in source:
                    relative = path.relative_to(root).as_posix()
                    failures.append(f"{relative}: retired frontend marker remains: {marker}")


def _check_worker_and_producers(root: Path, failures: list[str]) -> None:
    worker_path = "v2-api/app/services/barcode_maintenance_worker.py"
    worker_tree = _parse_python(root, worker_path, failures)
    claimers = _functions(worker_tree, "_claim_next_work")
    claim_order = None
    claimer_keys: set[str] = set()
    if len(claimers) == 1:
        claim_order = _literal_assignment(claimers[0], "claim_order")
        for node in ast.walk(claimers[0]):
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "claimers" for target in node.targets
            ) and isinstance(node.value, ast.Dict):
                claimer_keys = {
                    str(key.value)
                    for key in node.value.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                }
    if claim_order != ("verification", "auto_archive") or claimer_keys != {
        "verification",
        "auto_archive",
    }:
        failures.append(f"{worker_path}: worker claim kinds must be exactly verification and auto_archive")

    guard_contracts: dict[str, dict[str, tuple[str, Any]]] = {
        "v2-api/app/services/delivery_cache.py": {
            "enqueue_json_delivery_cache_job": ("return", None),
            "enqueue_postgres_delivery_cache_job": ("return", None),
            "sync_json_delivery_cache_job_for_group": ("return", None),
            "sync_postgres_delivery_cache_job_for_group": ("return", None),
        },
        "v2-api/app/services/delivery_package_queue.py": {
            "request_json_delivery_package": ("call", "_raise_delivery_retired"),
            "stage_json_delivery_package": ("call", "_raise_delivery_retired"),
            "request_postgres_delivery_package": ("call", "_raise_delivery_retired"),
        },
        "v2-api/app/services/local_simulation.py": {
            "build_final_delivery_export": ("raise", None),
            "build_final_delivery_package_from_groups": ("raise", None),
            "build_final_delivery_manifest": ("raise", None),
        },
        "v2-api/app/services/state_repository.py": {
            "_json_request_data_center_delivery_package": ("return", "retired"),
            "_stage_data_center_auto_archive_delivery_jobs": ("return", "retired"),
            "_enqueue_delivery_cache_after_commit": ("return", None),
            "create_export_job": ("raise", None),
            "request_final_delivery_export": ("raise", None),
            "build_final_delivery_export": ("raise", None),
            "build_final_delivery_manifest": ("raise", None),
        },
    }
    for relative_path, contracts in guard_contracts.items():
        tree = _parse_python(root, relative_path, failures)
        for function_name, (kind, expected) in contracts.items():
            matches = _functions(tree, function_name)
            if not matches:
                failures.append(f"{relative_path}: producer {function_name} is missing")
                continue
            for function in matches:
                valid = (
                    _first_is_return(function, expected)
                    if kind == "return"
                    else _first_is_call(function, str(expected))
                    if kind == "call"
                    else _first_is_retired_raise(function)
                )
                if not valid:
                    failures.append(f"{relative_path}: producer {function_name} must be retired at entry")


def _check_migration_and_manifest(root: Path, failures: list[str]) -> None:
    service_path = "v2-api/app/services/external_photo_oss_migration.py"
    service_tree = _parse_python(root, service_path, failures)
    if _literal_assignment(service_tree, "MAX_EXTERNAL_PHOTO_BYTES") != 30 * 1024 * 1024:
        failures.append(f"{service_path}: external photo limit must be exactly 30 MiB")
    forbid_overwrite = False
    if service_tree is not None:
        for node in ast.walk(service_tree):
            if isinstance(node, ast.Dict):
                pairs = {
                    str(key.value): str(value.value)
                    for key, value in zip(node.keys, node.values)
                    if isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                }
                forbid_overwrite = forbid_overwrite or pairs.get("x-oss-forbid-overwrite") == "true"
    if not forbid_overwrite:
        failures.append(f"{service_path}: OSS uploads must send the forbid overwrite header")

    migration_path = "v2-api/scripts/migrate_external_photos_to_oss.py"
    migration_tree = _parse_python(root, migration_path, failures)
    forbidden_calls = {"ThreadPoolExecutor", "urlopen", "delete_object", "batch_delete_objects"}
    if migration_tree is not None:
        bindings = _import_and_alias_bindings(migration_tree)
        for node in ast.walk(migration_tree):
            if not isinstance(node, ast.Call):
                continue
            qualified_call = _qualified_reference(node.func, bindings)
            call_name = qualified_call.rsplit(".", 1)[-1]
            if call_name in forbidden_calls:
                failures.append(f"{migration_path}: forbidden migration call {call_name}")
            if call_name == "add_argument" and node.args:
                option = node.args[0]
                if isinstance(option, ast.Constant) and str(option.value) in {
                    "--workers",
                    "--max-workers",
                    "--concurrency",
                    "--threads",
                }:
                    failures.append(f"{migration_path}: migration concurrency option is forbidden")
    migration_constants = {
        "START_MEMORY_BYTES": 400 * 1024 * 1024,
        "START_TEMP_FREE_BYTES": 512 * 1024 * 1024,
        "STOP_MEMORY_BYTES": 250 * 1024 * 1024,
        "OSS_ERROR_LIMIT": 5,
    }
    for name, expected in migration_constants.items():
        if _literal_assignment(migration_tree, name) != expected:
            failures.append(f"{migration_path}: migration resource/stop constant {name} is invalid")

    signer_path = "v2-api/scripts/build_oss_export_manifest.py"
    signer_tree = _parse_python(root, signer_path, failures)
    if signer_tree is not None:
        for node in ast.walk(signer_tree):
            if isinstance(node, ast.Call) and _call_leaf(node) == "query":
                failures.append(f"{signer_path}: manifest query must remain scalar-only")
            if isinstance(node, ast.Call) and _call_leaf(node) == "select":
                if any(isinstance(argument, ast.Name) for argument in node.args):
                    failures.append(f"{signer_path}: manifest query must remain scalar-only")
    iterators = _functions(signer_tree, "iter_manifest_rows")
    yield_dicts = []
    if len(iterators) == 1:
        yield_dicts = [
            statement.value.value
            for statement in iterators[0].body
            if isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Yield)
            and isinstance(statement.value.value, ast.Dict)
        ]
    first_kind = None
    if yield_dicts:
        first_kind = {
            key.value: value.value
            for key, value in zip(yield_dicts[0].keys, yield_dicts[0].values)
            if isinstance(key, ast.Constant) and isinstance(value, ast.Constant)
        }.get("kind")
    if first_kind != "manifest":
        failures.append(f"{signer_path}: manifest stream must emit its header first")
    signer_source = _read(root, signer_path, failures)
    for marker in ('"planned_count"', '"planned_bytes"', '"download_url"'):
        if marker not in signer_source:
            failures.append(f"{signer_path}: manifest field missing: {marker}")

    local_path = "scripts/oss_local_export.py"
    local_tree = _parse_python(root, local_path, failures)
    local_constants = {
        "MAX_DOWNLOAD_WORKERS": (4, "four workers"),
        "MAX_PENDING_DOWNLOADS": (8, "eight pending"),
        "RETRY_DELAYS": ((1.0, 2.0, 4.0), "1/2/4 retry delays"),
    }
    for name, (expected, description) in local_constants.items():
        if _literal_assignment(local_tree, name) != expected:
            failures.append(f"{local_path}: local exporter must enforce {description}")


def _check_migration_head(root: Path, failures: list[str]) -> None:
    versions = root / "v2-api" / "alembic" / "versions"
    numbered = sorted(path.name for path in versions.glob("[0-9][0-9][0-9][0-9]_*.py")) if versions.exists() else []
    if not numbered or numbered[-1] != MIGRATION_FILE or any(name.startswith("0015_") for name in numbered):
        failures.append("v2-api/alembic/versions: migration head must remain 0014")
    migration_tree = _parse_python(root, f"v2-api/alembic/versions/{MIGRATION_FILE}", failures)
    if _literal_assignment(migration_tree, "revision") != MIGRATION_REVISION:
        failures.append(
            f"v2-api/alembic/versions/{MIGRATION_FILE}: revision must remain {MIGRATION_REVISION}"
        )


def _check_package_contract(root: Path, failures: list[str]) -> None:
    verifier_path = "scripts/verify-client-release.py"
    verifier_tree = _parse_python(root, verifier_path, failures)
    required_files = set(_literal_assignment(verifier_tree, "REQUIRED_FILES") or ())
    for member in sorted(REQUIRED_PACKAGE_MEMBERS):
        if member not in required_files:
            failures.append(f"{verifier_path}: required package member missing: {member}")
    forbidden_parts = set(_literal_assignment(verifier_tree, "FORBIDDEN_PARTS") or ())
    for classifier in sorted(FORBIDDEN_PACKAGE_CLASSIFIERS):
        if classifier not in forbidden_parts:
            failures.append(f"{verifier_path}: forbidden package classifier missing: {classifier}")

    builder = _read(root, "scripts/build-client-release.ps1", failures)
    required_root_copies = (
        "scripts\\patch_export_retirement_nginx.py",
        "scripts\\test_patch_export_retirement_nginx.py",
        "scripts\\oss_local_export.py",
        "scripts\\test_oss_local_export.py",
        "scripts\\verify_v3_2_3_release.py",
        "scripts\\test_verify_v3_2_3_release.py",
        "docs\\sop\\09-export-retirement-and-oss-local-export.md",
    )
    for member in required_root_copies:
        if member not in builder:
            failures.append(f"scripts/build-client-release.ps1: package copy missing: {member}")
    required_gates = (
        "scripts\\verify_v3_2_0_export_center_ui.py",
        "scripts\\verify_v3_2_0_single_export_entry.py",
        "scripts\\verify_v3_2_1_installer_kpi_restore.py",
        "scripts\\verify_v3_2_3_release.py",
    )
    for gate in required_gates:
        if gate not in builder:
            failures.append(f"scripts/build-client-release.ps1: release gate missing: {gate}")


def _check_release_record_and_sop(root: Path, failures: list[str]) -> None:
    release_path = "ops/releases/V3.2.3.md"
    release = _read(root, release_path, failures)
    fields: dict[str, set[str]] = {
        "Status": {"pending"},
        "Local Verification": {"not run", "passed"},
        "Package": {"pending"},
        "Production Deployment": {"pending"},
        "Production Reconciliation": {"pending"},
        "Rollback target": {DEPLOYED_BASELINE},
    }
    for field, allowed in fields.items():
        values = re.findall(rf"(?m)^- {re.escape(field)}:\s*(.*?)\s*$", release)
        if len(values) != 1 or values[0] not in allowed:
            failures.append(f"{release_path}: {field} must define one candidate-state value")
    if "20260724_0014" not in release or "no Alembic migration" not in release:
        failures.append(f"{release_path}: unchanged migration head must be recorded")

    notes = _read(root, "v2-web/src/constants/releaseNotes.ts", failures)
    first_version = re.search(r"version:\s*'([^']+)'", notes)
    if first_version is None or first_version.group(1) != DISPLAY_VERSION:
        failures.append("v2-web/src/constants/releaseNotes.ts: first release note must be V3.2.3")
    required_note_terms = (
        "导出中心",
        "浏览器 CSV",
        "交付包",
        "外链照片",
        "OSS",
        "本机",
    )
    first_block = notes.split("  },", 1)[0]
    for term in required_note_terms:
        if term not in first_block:
            failures.append(f"v2-web/src/constants/releaseNotes.ts: first release note must mention {term}")

    sop_path = "docs/sop/09-export-retirement-and-oss-local-export.md"
    sop = _read(root, sop_path, failures)
    required_sop_markers = (
        "--dry-run",
        "--execute",
        "--limit 10",
        "--resume",
        "--rollback-run",
        "build_oss_export_manifest.py",
        "oss_local_export.py",
        "400 MiB",
        "250 MiB",
        "512 MiB",
        "单 worker",
        "30 MiB",
        "5 次",
        "allowlist",
        "1/2/4",
        "4",
        "C:\\Users\\Administrator\\Downloads\\module-manager-exports",
        "签名 URL",
        "不完整",
        "不删除 OSS",
    )
    for marker in required_sop_markers:
        if marker not in sop:
            failures.append(f"{sop_path}: required operating marker missing: {marker}")

    health_path = "scripts/production_health_check.py"
    health_tree = _parse_python(root, health_path, failures)
    paths = tuple(_literal_assignment(health_tree, "RETIRED_PATHS") or ())
    if paths != RETIRED_HEALTH_PATHS:
        failures.append(f"{health_path}: production health check must probe every retired path and child")
    health_source = _read(root, health_path, failures)
    for retained in (
        "/health",
        "/login",
        "/project-board",
        "/global-search",
        "/construction",
        "/local-test/system/status",
        "/local-test/summary",
        "/docs",
        "/redoc",
        "/openapi.json",
    ):
        if retained not in health_source:
            failures.append(f"{health_path}: retained production probe missing: {retained}")


def collect_failures(root: Path) -> list[str]:
    root = Path(root)
    failures: list[str] = []
    for relative_path in REQUIRED_NEW_FILES:
        if not (root / relative_path).is_file():
            failures.append(f"{relative_path}: required V3.2.3 file is missing")
    _check_version_surfaces(root, failures)
    _check_retirement_contract(root, failures)
    _check_frontend_retirement(root, failures)
    _check_worker_and_producers(root, failures)
    _check_migration_and_manifest(root, failures)
    _check_migration_head(root, failures)
    _check_package_contract(root, failures)
    _check_release_record_and_sop(root, failures)
    return failures


def main(argv: list[str] | None = None) -> int:
    if argv:
        print("verify_v3_2_3_release.py does not accept positional arguments", file=sys.stderr)
        return 2
    failures = collect_failures(ROOT)
    if failures:
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("[OK] V3.2.3 release contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
