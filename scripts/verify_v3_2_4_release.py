from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import verify_v3_2_3_release as legacy  # noqa: E402


VERSION = "3.2.4"
DISPLAY_VERSION = "V3.2.4"
DEPLOYED_BASELINE = "V3.2.2"
MAINTENANCE_BRANCH = "production/V3/3.2.4"
RELEASE_PATH = "ops/releases/V3.2.4.md"
V324_REQUIRED_FILES = (
    "scripts/verify_v3_2_4_release.py",
    "scripts/test_verify_v3_2_4_release.py",
    "v2-api/app/services/photo_storage.py",
    "v2-api/tests/test_photo_storage.py",
    RELEASE_PATH,
)
REQUIRED_PACKAGE_MEMBERS = frozenset(V324_REQUIRED_FILES)
CONTRACT_PATHS = tuple(
    dict.fromkeys(
        (
            *legacy.CONTRACT_PATHS,
            "v2-api/scripts/verify_v3_1_release.py",
            "v2-api/app/services/photo_storage.py",
            "v2-api/tests/test_photo_storage.py",
            RELEASE_PATH,
        )
    )
)


def _check_json_version(
    root: Path,
    relative_path: str,
    key: str,
    failures: list[str],
) -> None:
    source = legacy._read(root, relative_path, failures)
    try:
        value = json.loads(source).get(key)
    except (json.JSONDecodeError, AttributeError):
        value = None
    if value != VERSION:
        failures.append(f"{relative_path}: {key} must equal {VERSION}")


def _check_static_vue_version(root: Path, failures: list[str]) -> None:
    runtime_path = "v2-api/app/static/vue/version.json"
    _check_json_version(root, runtime_path, "version", failures)
    index_path = "v2-api/app/static/vue/index.html"
    index = legacy._read(root, index_path, failures)
    entry_match = re.search(r'<script[^>]+src="/vue/(?P<path>assets/[^"]+\.js)"', index)
    if entry_match is None:
        failures.append(f"{index_path}: production Vue entry script is missing")
        return
    entry_path = f"v2-api/app/static/vue/{entry_match.group('path')}"
    entry = legacy._read(root, entry_path, failures)
    marker = f'__MODULE_MANAGER_VUE_ENTRY_ATTESTATION__={{"version":"{VERSION}"}}'
    if marker not in entry:
        failures.append(f"{entry_path}: entry bundle version marker must equal {VERSION}")


def _check_version_surfaces(root: Path, failures: list[str]) -> None:
    _check_json_version(root, "v2-web/package.json", "version", failures)
    _check_json_version(root, "v2-web/src/version.json", "version", failures)

    pyproject_path = "v2-api/pyproject.toml"
    pyproject_source = legacy._read(root, pyproject_path, failures)
    try:
        project = tomllib.loads(pyproject_source).get("project", {})
    except tomllib.TOMLDecodeError:
        project = {}
    if project.get("version") != VERSION:
        failures.append(f"{pyproject_path}: project.version must equal {VERSION}")
    if DISPLAY_VERSION not in str(project.get("description") or ""):
        failures.append(f"{pyproject_path}: description must identify {DISPLAY_VERSION}")

    ops_tree = legacy._parse_python(root, "v2-api/app/services/ops_status.py", failures)
    app_version_functions = legacy._functions(ops_tree, "app_version")
    if len(app_version_functions) != 1 or not legacy._first_is_return(
        app_version_functions[0], VERSION
    ):
        failures.append(f"v2-api/app/services/ops_status.py: app_version() must return {VERSION}")

    main_tree = legacy._parse_python(root, "v2-api/app/main.py", failures)
    fastapi_versions: list[str] = []
    if main_tree is not None:
        for node in ast.walk(main_tree):
            if isinstance(node, ast.Call) and legacy._call_leaf(node) == "FastAPI":
                for keyword in node.keywords:
                    if keyword.arg == "version" and isinstance(keyword.value, ast.Constant):
                        fastapi_versions.append(str(keyword.value.value))
    if fastapi_versions != [VERSION]:
        failures.append(f"v2-api/app/main.py: FastAPI version must equal {VERSION} exactly once")

    active_verifier_path = "v2-api/scripts/verify_v3_1_release.py"
    active_verifier_tree = legacy._parse_python(root, active_verifier_path, failures)
    if legacy._literal_assignment(active_verifier_tree, "EXPECTED_VERSION") != VERSION:
        failures.append(f"{active_verifier_path}: EXPECTED_VERSION must equal {VERSION}")

    text_surfaces = {
        "v2-web/index.html": f"<title>Module Manager {DISPLAY_VERSION}</title>",
        "v2-web/src/components/AppLayout.vue": f"<span>{DISPLAY_VERSION}</span>",
        "scripts/build-client-release.ps1": f'[string]$Version = "{VERSION}"',
        "RELEASE_MANIFEST.md": f"- Version: {VERSION}",
        "README.md": f"build-client-release.ps1 -Version {VERSION}",
        "docs/CLIENT_SIGNOFF_CHECKLIST.md": f"module-manager-v2-server-{VERSION}.zip",
    }
    for relative_path, marker in text_surfaces.items():
        if marker not in legacy._read(root, relative_path, failures):
            failures.append(f"{relative_path}: current version surface must contain {marker}")

    agents = legacy._read(root, "AGENTS.md", failures)
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

    required_document_markers = {
        "docs/AGENT_REQUIRED_READING.md": (
            f"生产维护分支：`{MAINTENANCE_BRANCH}`",
            f"当前发布候选版本：`{DISPLAY_VERSION}`",
            f"verify_release_sop.py --version {DISPLAY_VERSION}",
        ),
        "docs/sop/README.md": (
            f"Current release candidate: `{DISPLAY_VERSION}`",
            f"Current candidate branch: `{MAINTENANCE_BRANCH}`",
        ),
        "docs/sop/09-export-retirement-and-oss-local-export.md": (
            f"# {DISPLAY_VERSION}",
            "v324-external-photo",
        ),
    }
    for relative_path, markers in required_document_markers.items():
        source = legacy._read(root, relative_path, failures)
        for marker in markers:
            if marker not in source:
                failures.append(f"{relative_path}: current candidate marker missing: {marker}")

    _check_static_vue_version(root, failures)


def _check_https_handler_compatibility(root: Path, failures: list[str]) -> None:
    relative_path = "v2-api/app/services/photo_storage.py"
    tree = legacy._parse_python(root, relative_path, failures)
    handlers = [
        node
        for node in ast.walk(tree) if tree is not None
        if isinstance(node, ast.ClassDef) and node.name == "_PinnedHTTPSHandler"
    ]
    if len(handlers) != 1:
        failures.append(f"{relative_path}: exactly one _PinnedHTTPSHandler is required")
        return
    methods = [
        node
        for node in handlers[0].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "https_open"
    ]
    if len(methods) != 1:
        failures.append(f"{relative_path}: _PinnedHTTPSHandler.https_open is required")
        return
    method = methods[0]
    if any(isinstance(node, ast.Attribute) and node.attr == "_check_hostname" for node in ast.walk(method)):
        failures.append(
            f"{relative_path}: _PinnedHTTPSHandler must not read legacy _check_hostname"
        )
    do_open_calls = [
        node
        for node in ast.walk(method)
        if isinstance(node, ast.Call) and legacy._call_leaf(node) == "do_open"
    ]
    if len(do_open_calls) != 1:
        failures.append(f"{relative_path}: HTTPS handler must delegate exactly once to do_open")
        return
    keywords = {keyword.arg: keyword.value for keyword in do_open_calls[0].keywords}
    context = keywords.get("context")
    if set(keywords) != {"context"} or not (
        isinstance(context, ast.Attribute)
        and isinstance(context.value, ast.Name)
        and context.value.id == "self"
        and context.attr == "_context"
    ):
        failures.append(
            f"{relative_path}: HTTPS handler must pass only the inherited SSL context to do_open"
        )


def _check_v324_package_contract(root: Path, failures: list[str]) -> None:
    verifier_path = "scripts/verify-client-release.py"
    verifier_tree = legacy._parse_python(root, verifier_path, failures)
    required_files = set(legacy._literal_assignment(verifier_tree, "REQUIRED_FILES") or ())
    for member in sorted(REQUIRED_PACKAGE_MEMBERS):
        if member not in required_files:
            failures.append(f"{verifier_path}: required package member missing: {member}")

    builder_path = "scripts/build-client-release.ps1"
    builder = legacy._read(root, builder_path, failures)
    for member in (
        "scripts\\verify_v3_2_4_release.py",
        "scripts\\test_verify_v3_2_4_release.py",
    ):
        copy_marker = f'Copy-ReleaseItem "{member}" "{member}"'
        if copy_marker not in builder:
            failures.append(f"{builder_path}: package copy missing: {member}")
    gate = "scripts\\verify_v3_2_4_release.py"
    release_verifier_match = re.search(
        r"\$releaseVerifiers\s*=\s*@\((?P<items>[\s\S]*?)\n\)", builder
    )
    if release_verifier_match is None or gate not in release_verifier_match.group("items"):
        failures.append(f"{builder_path}: release gate missing: {gate}")


def _check_release_record_and_sop(root: Path, failures: list[str]) -> None:
    release = legacy._read(root, RELEASE_PATH, failures)
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
            failures.append(f"{RELEASE_PATH}: {field} must define one candidate-state value")
    evidence_markers = {
        "'_PinnedHTTPSHandler' object has no attribute '_check_hostname'": "root cause",
        "zero-write": "zero-write",
        "Application rollback: V3.2.2 restored": "application rollback",
        "v323-external-20260819T142410Z": "failed migration ID",
        "20260724_0014": "unchanged migration head",
    }
    for marker, description in evidence_markers.items():
        if marker not in release:
            failures.append(f"{RELEASE_PATH}: {description} evidence is required")

    notes_path = "v2-web/src/constants/releaseNotes.ts"
    notes = legacy._read(root, notes_path, failures)
    first_version = re.search(r"version:\s*'([^']+)'", notes)
    if first_version is None or first_version.group(1) != DISPLAY_VERSION:
        failures.append(f"{notes_path}: first release note must be {DISPLAY_VERSION}")
    first_block = notes.split("  },", 1)[0]
    for term in ("外链照片", "HTTPS", "DNS", "SSL", "Python 3.12"):
        if term not in first_block:
            failures.append(f"{notes_path}: first release note must mention {term}")

    sop_path = "docs/sop/09-export-retirement-and-oss-local-export.md"
    sop = legacy._read(root, sop_path, failures)
    for marker in (
        "--dry-run",
        "--execute",
        "--limit 10",
        "--resume",
        "--rollback-run",
        "400 MiB",
        "250 MiB",
        "512 MiB",
        "单 worker",
        "30 MiB",
        "allowlist",
        "不删除 OSS",
    ):
        if marker not in sop:
            failures.append(f"{sop_path}: required operating marker missing: {marker}")

    health_path = "scripts/production_health_check.py"
    health_tree = legacy._parse_python(root, health_path, failures)
    paths = tuple(legacy._literal_assignment(health_tree, "RETIRED_PATHS") or ())
    if paths != legacy.RETIRED_HEALTH_PATHS:
        failures.append(f"{health_path}: production health check must probe every retired path and child")


def collect_failures(root: Path) -> list[str]:
    root = Path(root)
    failures: list[str] = []
    for relative_path in V324_REQUIRED_FILES:
        if not (root / relative_path).is_file():
            failures.append(f"{relative_path}: required V3.2.4 file is missing")
    _check_version_surfaces(root, failures)
    legacy._check_retirement_contract(root, failures)
    legacy._check_frontend_retirement(root, failures)
    legacy._check_worker_and_producers(root, failures)
    legacy._check_migration_and_manifest(root, failures)
    legacy._check_migration_head(root, failures)
    legacy._check_package_contract(root, failures)
    _check_https_handler_compatibility(root, failures)
    _check_v324_package_contract(root, failures)
    _check_release_record_and_sop(root, failures)
    return failures


def main(argv: list[str] | None = None) -> int:
    if argv:
        print("verify_v3_2_4_release.py does not accept positional arguments", file=sys.stderr)
        return 2
    failures = collect_failures(ROOT)
    if failures:
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("[OK] V3.2.4 release contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
