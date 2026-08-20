from __future__ import annotations

import ast
import copy
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import verify_v3_2_4_release as legacy  # noqa: E402


VERSION = "3.2.5"
DISPLAY_VERSION = "V3.2.5"
DEPLOYED_BASELINE = "V3.2.2"
MAINTENANCE_BRANCH = "production/V3/3.2.5"
MIGRATION_REVISION = "20260724_0014"
RELEASE_PATH = "ops/releases/V3.2.5.md"
MIGRATION_PATH = "v2-api/scripts/migrate_external_photos_to_oss.py"
MIGRATION_TEST_PATH = "v2-api/tests/test_migrate_external_photos_to_oss.py"
V325_REQUIRED_FILES = (
    "scripts/verify_v3_2_5_release.py",
    "scripts/test_verify_v3_2_5_release.py",
    MIGRATION_PATH,
    MIGRATION_TEST_PATH,
    RELEASE_PATH,
)
REQUIRED_PACKAGE_MEMBERS = frozenset(V325_REQUIRED_FILES)
CONTRACT_PATHS = tuple(
    dict.fromkeys(
        (
            *legacy.CONTRACT_PATHS,
            "docs/sop/06-production-deploy-runbook.md",
            "scripts/test_verify_client_release.py",
            "scripts/test_verify_release_sop.py",
            "scripts/test_verify_v3_2_4_release.py",
            "scripts/test_verify_v3_2_5_release.py",
            "scripts/verify_v3_2_5_release.py",
            "v2-api/scripts/verify_v3_1_release.py",
            "v2-api/tests/test_api.py",
            "v2-api/tests/test_v3_1_release.py",
            MIGRATION_TEST_PATH,
            RELEASE_PATH,
        )
    )
)


def _function(
    tree: ast.Module | None,
    name: str,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    matches = legacy.legacy._functions(tree, name)
    return matches[0] if len(matches) == 1 else None


def _check_json_version(
    root: Path,
    relative_path: str,
    key: str,
    failures: list[str],
) -> None:
    source = legacy.legacy._read(root, relative_path, failures)
    try:
        payload = json.loads(source)
        value = payload.get(key) if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        value = None
    if value != VERSION:
        failures.append(f"{relative_path}: {key} must equal {VERSION}")


def _check_static_vue_version(root: Path, failures: list[str]) -> None:
    runtime_path = "v2-api/app/static/vue/version.json"
    _check_json_version(root, runtime_path, "version", failures)
    index_path = "v2-api/app/static/vue/index.html"
    index = legacy.legacy._read(root, index_path, failures)
    if f"<title>Module Manager {DISPLAY_VERSION}</title>" not in index:
        failures.append(f"{index_path}: production Vue title must equal {DISPLAY_VERSION}")
    entry_match = re.search(r'<script[^>]+src="/vue/(?P<path>assets/[^"]+\.js)"', index)
    if entry_match is None:
        failures.append(f"{index_path}: production Vue entry script is missing")
        return
    entry_path = f"v2-api/app/static/vue/{entry_match.group('path')}"
    entry = legacy.legacy._read(root, entry_path, failures)
    marker = f'__MODULE_MANAGER_VUE_ENTRY_ATTESTATION__={{"version":"{VERSION}"}}'
    if marker not in entry:
        failures.append(f"{entry_path}: entry bundle version marker must equal {VERSION}")


def _check_version_surfaces(root: Path, failures: list[str]) -> None:
    _check_json_version(root, "v2-web/package.json", "version", failures)
    _check_json_version(root, "v2-web/src/version.json", "version", failures)

    pyproject_path = "v2-api/pyproject.toml"
    pyproject_source = legacy.legacy._read(root, pyproject_path, failures)
    try:
        project = tomllib.loads(pyproject_source).get("project", {})
    except tomllib.TOMLDecodeError:
        project = {}
    if project.get("version") != VERSION:
        failures.append(f"{pyproject_path}: project.version must equal {VERSION}")
    if DISPLAY_VERSION not in str(project.get("description") or ""):
        failures.append(f"{pyproject_path}: description must identify {DISPLAY_VERSION}")

    ops_tree = legacy.legacy._parse_python(
        root,
        "v2-api/app/services/ops_status.py",
        failures,
    )
    app_version = _function(ops_tree, "app_version")
    if app_version is None or not legacy.legacy._first_is_return(app_version, VERSION):
        failures.append(f"v2-api/app/services/ops_status.py: app_version() must return {VERSION}")

    main_tree = legacy.legacy._parse_python(root, "v2-api/app/main.py", failures)
    fastapi_versions: list[str] = []
    if main_tree is not None:
        for node in ast.walk(main_tree):
            if isinstance(node, ast.Call) and legacy.legacy._call_leaf(node) == "FastAPI":
                for keyword in node.keywords:
                    if keyword.arg == "version" and isinstance(keyword.value, ast.Constant):
                        fastapi_versions.append(str(keyword.value.value))
    if fastapi_versions != [VERSION]:
        failures.append(f"v2-api/app/main.py: FastAPI version must equal {VERSION} exactly once")

    for relative_path in (
        "v2-api/scripts/verify_v3_1_release.py",
        "v2-api/tests/test_v3_1_release.py",
    ):
        tree = legacy.legacy._parse_python(root, relative_path, failures)
        if legacy._literal_assignment(tree, "EXPECTED_VERSION") != VERSION:
            failures.append(f"{relative_path}: EXPECTED_VERSION must equal {VERSION}")

    text_surfaces: dict[str, tuple[str, ...]] = {
        "v2-web/index.html": (f"<title>Module Manager {DISPLAY_VERSION}</title>",),
        "v2-web/src/components/AppLayout.vue": (f"<span>{DISPLAY_VERSION}</span>",),
        "scripts/build-client-release.ps1": (
            f'[string]$Version = "{VERSION}"',
            f"Performance report is required for {DISPLAY_VERSION} packaging.",
            f"Running {DISPLAY_VERSION} focused release gates...",
        ),
        "RELEASE_MANIFEST.md": (
            f"- Package: `build/server-release/module-manager-v2-server-{VERSION}.zip`",
            f"- Name: `module-manager-v2-server-{VERSION}.zip`",
            f"- Version: {VERSION}",
            f"verify_release_sop.py --version {DISPLAY_VERSION}",
        ),
        "README.md": (
            f"verify_release_sop.py --version {DISPLAY_VERSION}",
            f"build-client-release.ps1 -Version {VERSION}",
            f"v{VERSION}-task-review.json",
        ),
        "docs/CLIENT_SIGNOFF_CHECKLIST.md": (
            f"## {DISPLAY_VERSION} 候选生产包路径",
            f"module-manager-v2-server-{VERSION}.zip",
        ),
        "v2-api/tests/test_api.py": (f'assert data["version"] == "{VERSION}"',),
        "v2-api/tests/test_v3_1_release.py": (
            f"Performance report is required for {DISPLAY_VERSION} packaging",
        ),
    }
    for relative_path, markers in text_surfaces.items():
        source = legacy.legacy._read(root, relative_path, failures)
        for marker in markers:
            if marker not in source:
                failures.append(f"{relative_path}: current version surface must contain {marker}")

    agents = legacy.legacy._read(root, "AGENTS.md", failures)
    required_agent_markers = {
        f"Deployed production baseline: `{DEPLOYED_BASELINE}`": "deployed baseline",
        f"Release candidate: `{DISPLAY_VERSION}`": "release candidate",
        f"Release-candidate maintenance branch: `{MAINTENANCE_BRANCH}`": "candidate branch",
        f"当前已部署生产版本：`{DEPLOYED_BASELINE}`": "deployed baseline",
        f"当前发布候选版本：`{DISPLAY_VERSION}`": "release candidate",
        f"当前候选维护分支：`{MAINTENANCE_BRANCH}`": "candidate branch",
    }
    for marker, description in required_agent_markers.items():
        if agents.count(marker) != 1:
            failures.append(f"AGENTS.md: {description} must define {marker} exactly once")

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
    }
    for relative_path, markers in required_document_markers.items():
        source = legacy.legacy._read(root, relative_path, failures)
        for marker in markers:
            if marker not in source:
                failures.append(f"{relative_path}: current candidate marker missing: {marker}")

    _check_static_vue_version(root, failures)


def _compile_hash_contract(
    tree: ast.Module,
) -> tuple[object, object, object]:
    names = (
        "_legacy_declared_hash_class",
        "_declared_hash_class",
        "_hash_status",
    )
    functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for name in names:
        function = _function(tree, name)
        if function is None:
            raise ValueError(f"exactly one {name} function is required")
        functions.append(copy.deepcopy(function))
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            *functions,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    namespace: dict[str, object] = {"hashlib": hashlib, "re": re}
    exec(compile(module, MIGRATION_PATH, "exec"), namespace)
    return tuple(namespace[name] for name in names)  # type: ignore[return-value]


def _historical_candidate(formula: str, *, declared: str | None = None) -> SimpleNamespace:
    if formula == "a":
        values = {
            "photo_id": "photo-a-id",
            "team_id": "team-a",
            "group_id": "group-a-id",
            "group_legacy_id": "group-a-1",
            "photo_legacy_id": "photo-a-9",
            "source_fingerprint": "scan:batch-7:row-3",
            "source_url": "https://img.example/historical-a.jpg",
            "image_file_id": "file-a-123",
            "url": "https://img.example/historical-a.jpg",
            "declared_sha256": "7ab18e35bc20bcdca0578f4c5211d811503c1f7d13b0ec5e80ddd42b08d3c446",
            "filename": "historical-a.jpg",
        }
    elif formula == "b":
        values = {
            "photo_id": "photo-b-id",
            "team_id": "team-b",
            "group_id": "group-b-id",
            "group_legacy_id": "group-b-42",
            "photo_legacy_id": "photo-b-7",
            "source_fingerprint": "",
            "source_url": "https://img.example/historical-b.png",
            "image_file_id": "file-b-456",
            "url": "https://img.example/historical-b.png",
            "declared_sha256": "4d360bde40c524917f800120c2b5019fefd72d80d375a90766d24f1560e7760a",
            "filename": "historical-b.png",
        }
    else:
        raise ValueError(f"unknown historical formula fixture: {formula}")
    if declared is not None:
        values["declared_sha256"] = declared
    return SimpleNamespace(**values)


def _check_candidate_snapshot(tree: ast.Module, failures: list[str]) -> None:
    classes = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ExternalPhotoCandidate"
    ]
    expected_fields = (
        "photo_id",
        "team_id",
        "group_id",
        "group_legacy_id",
        "photo_legacy_id",
        "source_fingerprint",
        "source_url",
        "image_file_id",
        "url",
        "declared_sha256",
        "filename",
    )
    actual_fields = tuple(
        node.target.id
        for node in classes[0].body
        if len(classes) == 1
        and isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
    ) if len(classes) == 1 else ()
    if actual_fields != expected_fields:
        failures.append(f"{MIGRATION_PATH}: candidate identity snapshot fields must remain exact")

    statement = _function(tree, "candidate_statement")
    candidate_from_row = _function(tree, "_candidate_from_row")
    statement_source = ast.unparse(statement) if statement is not None else ""
    row_source = ast.unparse(candidate_from_row) if candidate_from_row is not None else ""
    query_markers = (
        "Photo.legacy_id.label('photo_legacy_id')",
        "Photo.source_fingerprint",
        "Photo.source_url",
        "Photo.image_file_id",
    )
    row_markers = tuple(f"{field}=" for field in expected_fields)
    if any(marker not in statement_source for marker in query_markers) or any(
        marker not in row_source for marker in row_markers
    ):
        failures.append(f"{MIGRATION_PATH}: candidate identity snapshot query/mapping is incomplete")


def _check_historical_hash_contract(tree: ast.Module, failures: list[str]) -> None:
    try:
        legacy_class, declared_class, hash_status = _compile_hash_contract(tree)
    except (ValueError, SyntaxError, TypeError, NameError) as exc:
        failures.append(f"{MIGRATION_PATH}: historical Formula A/B contract is not executable: {exc}")
        return

    formula_fields = {
        "a": ("source_fingerprint", "source_url", "image_file_id", "photo_legacy_id"),
        "b": ("team_id", "group_legacy_id", "photo_legacy_id", "url", "image_file_id"),
    }
    for formula, expected_class in (("a", "legacy_formula_a"), ("b", "legacy_formula_b")):
        candidate = _historical_candidate(formula)
        try:
            if legacy_class(candidate) != expected_class or declared_class(candidate) != expected_class:
                raise AssertionError("classification mismatch")
            if hash_status(candidate, "a" * 64) != "accepted":
                raise AssertionError("historical digest was rejected")
            for field in formula_fields[formula]:
                mutated = SimpleNamespace(**vars(candidate))
                setattr(mutated, field, f"{getattr(mutated, field)}-changed")
                if hash_status(mutated, "a" * 64) != "declared_hash_mismatch":
                    raise AssertionError(f"{formula}.{field} drift was accepted")
        except (AttributeError, AssertionError, TypeError, ValueError) as exc:
            failures.append(f"{MIGRATION_PATH}: historical Formula A/B support is incomplete: {exc}")
            break

    fallback = _historical_candidate("a")
    fallback.source_url = ""
    fallback.declared_sha256 = hashlib.sha256(
        "|".join(
            (
                fallback.source_fingerprint,
                fallback.url,
                fallback.image_file_id,
                fallback.photo_legacy_id,
            )
        ).encode("utf-8")
    ).hexdigest()
    arbitrary = _historical_candidate("a", declared="e" * 64)
    try:
        if hash_status(fallback, "a" * 64) != "accepted":
            failures.append(f"{MIGRATION_PATH}: historical Formula A/B source-url fallback is missing")
        if hash_status(arbitrary, "a" * 64) != "declared_hash_mismatch":
            failures.append(f"{MIGRATION_PATH}: arbitrary declared-hash mismatch must remain rejected")
        controls = _historical_candidate("a", declared="")
        if hash_status(controls, "a" * 64) != "accepted":
            failures.append(f"{MIGRATION_PATH}: empty declared hash acceptance changed")
        controls.declared_sha256 = hashlib.sha256(controls.url.encode("utf-8")).hexdigest()
        if hash_status(controls, "a" * 64) != "accepted":
            failures.append(f"{MIGRATION_PATH}: source-URL hash acceptance changed")
        controls.declared_sha256 = "a" * 64
        if hash_status(controls, "a" * 64) != "accepted":
            failures.append(f"{MIGRATION_PATH}: downloaded-content hash acceptance changed")
    except (AttributeError, TypeError, ValueError) as exc:
        failures.append(f"{MIGRATION_PATH}: historical Formula A/B executable checks failed: {exc}")


def _compile_source_match(tree: ast.Module):
    function = _function(tree, "_source_still_matches")
    if function is None:
        raise ValueError("exactly one _source_still_matches function is required")
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            copy.deepcopy(function),
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    namespace: dict[str, object] = {}
    exec(compile(module, MIGRATION_PATH, "exec"), namespace)
    return namespace["_source_still_matches"]


def _check_locked_identity_contract(tree: ast.Module, failures: list[str]) -> None:
    try:
        source_still_matches = _compile_source_match(tree)
        candidate = _historical_candidate("a")
        photo = SimpleNamespace(
            id=candidate.photo_id,
            team_id=candidate.team_id,
            group_id=candidate.group_id,
            legacy_id=candidate.photo_legacy_id,
            is_active=True,
            storage_type="external_url",
            image_url=candidate.url,
            source_url=candidate.source_url,
            source_fingerprint=candidate.source_fingerprint,
            image_file_id=candidate.image_file_id,
            sha256=candidate.declared_sha256,
        )
        if source_still_matches(photo, candidate) is not True:
            raise AssertionError("unchanged source does not match")
        fields = {
            "team_id": "changed-team",
            "group_id": "changed-group",
            "legacy_id": "changed-photo-legacy",
            "image_url": "https://img.example/changed.jpg",
            "source_url": "https://img.example/changed-source.jpg",
            "source_fingerprint": "changed-fingerprint",
            "image_file_id": "changed-file",
            "sha256": "f" * 64,
        }
        for field, value in fields.items():
            mutated = SimpleNamespace(**vars(photo))
            setattr(mutated, field, value)
            if source_still_matches(mutated, candidate):
                raise AssertionError(f"{field} drift was accepted")
    except (AssertionError, AttributeError, SyntaxError, TypeError, ValueError) as exc:
        failures.append(f"{MIGRATION_PATH}: locked identity revalidation is incomplete: {exc}")

    commit = _function(tree, "_commit_group")
    conflict_guards = [] if commit is None else [
        node
        for node in ast.walk(commit)
        if isinstance(node, ast.If)
        and "group_legacy_id != candidate.group_legacy_id" in ast.unparse(node.test)
        and "_source_still_matches(photo, candidate)" in ast.unparse(node.test)
        and "statuses[item_key] = 'conflict'" in ast.unparse(
            ast.Module(body=node.body, type_ignores=[])
        )
    ]
    if len(conflict_guards) != 1:
        failures.append(f"{MIGRATION_PATH}: locked identity revalidation must include group legacy ID")


def _check_canonical_sha_contract(tree: ast.Module, failures: list[str]) -> None:
    commit = _function(tree, "_commit_group")
    runner = _function(tree, "_run_transfer_mode")
    if commit is None or runner is None:
        failures.append(f"{MIGRATION_PATH}: canonical downloaded-content SHA functions are missing")
        return

    pre_oss_values: list[str] = []
    for node in ast.walk(commit):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if isinstance(key, ast.Constant) and key.value == "pre_oss_sha256":
                pre_oss_values.append(ast.unparse(value))
    if pre_oss_values != ["photo.sha256"]:
        failures.append(f"{MIGRATION_PATH}: pre_oss_sha256 must preserve the locked source digest")

    assignments = {
        ast.unparse(node.targets[0]): ast.unparse(node.value)
        for node in ast.walk(commit)
        if isinstance(node, ast.Assign) and len(node.targets) == 1
    }
    if assignments.get("photo.sha256") != "receipt.sha256":
        failures.append(f"{MIGRATION_PATH}: canonical downloaded-content SHA must replace Photo.sha256")

    calls: dict[str, list[ast.Call]] = {}
    for node in ast.walk(runner):
        if isinstance(node, ast.Call):
            calls.setdefault(legacy.legacy._call_leaf(node), []).append(node)
    hash_calls = calls.get("_hash_status", [])
    key_calls = calls.get("oss_object_key", [])
    store_calls = calls.get("store_downloaded_photo", [])
    valid_hash = len(hash_calls) == 1 and tuple(map(ast.unparse, hash_calls[0].args)) == (
        "candidate",
        "downloaded.sha256",
    )
    valid_key = len(key_calls) == 1 and len(key_calls[0].args) >= 3 and ast.unparse(
        key_calls[0].args[2]
    ) == "downloaded.sha256"
    valid_store = len(store_calls) == 1 and len(store_calls[0].args) == 4 and ast.unparse(
        store_calls[0].args[3]
    ) == "downloaded"
    if not (valid_hash and valid_key and valid_store):
        failures.append(f"{MIGRATION_PATH}: canonical downloaded-content SHA flow is incomplete")


def _check_migration_contract(root: Path, failures: list[str]) -> None:
    tree = legacy.legacy._parse_python(root, MIGRATION_PATH, failures)
    if tree is None:
        return
    _check_candidate_snapshot(tree, failures)
    _check_historical_hash_contract(tree, failures)
    _check_locked_identity_contract(tree, failures)
    _check_canonical_sha_contract(tree, failures)
    dry_run = _function(tree, "run_dry_run")
    dry_run_calls = [] if dry_run is None else [
        node
        for node in ast.walk(dry_run)
        if isinstance(node, ast.Call)
        and legacy.legacy._call_leaf(node) == "_declared_hash_class"
        and tuple(map(ast.unparse, node.args)) == ("candidate",)
    ]
    if len(dry_run_calls) != 1:
        failures.append(f"{MIGRATION_PATH}: dry-run must classify historical Formula A/B candidates")


def _check_v325_package_contract(root: Path, failures: list[str]) -> None:
    verifier_path = "scripts/verify-client-release.py"
    verifier_tree = legacy.legacy._parse_python(root, verifier_path, failures)
    required_files = set(legacy._literal_assignment(verifier_tree, "REQUIRED_FILES") or ())
    for member in sorted(REQUIRED_PACKAGE_MEMBERS):
        if member not in required_files:
            failures.append(f"{verifier_path}: required package member missing: {member}")

    loader = _function(verifier_tree, "load_v325_release_verifier")
    package_verifier = _function(verifier_tree, "verify_package")
    loader_constants = set() if loader is None else {
        node.value
        for node in ast.walk(loader)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    active_calls = [] if package_verifier is None else [
        node
        for node in ast.walk(package_verifier)
        if isinstance(node, ast.Call)
        and legacy.legacy._call_leaf(node) == "load_v325_release_verifier"
    ]
    if "verify_v3_2_5_release.py" not in loader_constants or len(active_calls) != 1:
        failures.append(f"{verifier_path}: active package verifier must load V3.2.5 exactly once")

    builder_path = "scripts/build-client-release.ps1"
    builder = legacy.legacy._read(root, builder_path, failures)
    for member in (
        "scripts\\verify_v3_2_5_release.py",
        "scripts\\test_verify_v3_2_5_release.py",
    ):
        copy_marker = f'Copy-ReleaseItem "{member}" "{member}"'
        if copy_marker not in builder:
            failures.append(f"{builder_path}: package copy missing: {member}")
    release_input_members = (
        "scripts\\verify_v3_2_5_release.py",
        "scripts\\test_verify_v3_2_5_release.py",
        "v2-api\\scripts\\migrate_external_photos_to_oss.py",
        "v2-api\\tests\\test_migrate_external_photos_to_oss.py",
        "ops\\releases\\V3.2.5.md",
    )
    for member in release_input_members:
        if f'    "{member}"' not in builder:
            failures.append(f"{builder_path}: release input missing: {member}")
    release_verifier_match = re.search(
        r"\$releaseVerifiers\s*=\s*@\((?P<items>[\s\S]*?)\n\)",
        builder,
    )
    active_gate = "scripts\\verify_v3_2_5_release.py"
    active_items = "" if release_verifier_match is None else release_verifier_match.group("items")
    if active_gate not in active_items or "scripts\\verify_v3_2_4_release.py" in active_items:
        failures.append(f"{builder_path}: active release gate must be only the V3.2.5 gate")

    sop_verifier_path = "scripts/verify_release_sop.py"
    sop_tree = legacy.legacy._parse_python(root, sop_verifier_path, failures)
    release_inputs = set(legacy.legacy._literal_assignment(sop_tree, "RELEASE_INPUTS") or ())
    for member in REQUIRED_PACKAGE_MEMBERS:
        if member not in release_inputs:
            failures.append(f"{sop_verifier_path}: release input missing: {member}")


def _check_release_record_and_sop(root: Path, failures: list[str]) -> None:
    release = legacy.legacy._read(root, RELEASE_PATH, failures)
    fields = {
        "Status": "pending",
        "Local Verification": "not run",
        "Package": "pending",
        "Production Deployment": "pending",
        "Production Reconciliation": "pending",
        "Rollback target": DEPLOYED_BASELINE,
    }
    for field, expected in fields.items():
        values = re.findall(rf"(?m)^- {re.escape(field)}:\s*(.*?)\s*$", release)
        if values != [expected]:
            failures.append(f"{RELEASE_PATH}: {field} must equal {expected} exactly once")
    for marker in (MAINTENANCE_BRANCH, DEPLOYED_BASELINE, MIGRATION_REVISION):
        if marker not in release:
            failures.append(f"{RELEASE_PATH}: release identity missing: {marker}")

    notes_path = "v2-web/src/constants/releaseNotes.ts"
    notes = legacy.legacy._read(root, notes_path, failures)
    first_version = re.search(r"version:\s*'([^']+)'", notes)
    if first_version is None or first_version.group(1) != DISPLAY_VERSION:
        failures.append(f"{notes_path}: first release note must be {DISPLAY_VERSION}")
    first_block = notes.split("  },", 1)[0]
    evidence_markers = (
        "v324-external-20260819T233526Z",
        "10 declared_hash_mismatch",
        "uploaded/reused/committed: 0 / 0 / 0",
        "Formula A: 1999",
        "Formula B: 3",
        "arbitrary 64-hex mismatch",
        "locked identity revalidation",
        "canonical downloaded-content SHA256",
        "pre_oss_sha256",
        "no Alembic migration",
        "production reconciled to V3.2.2",
        "zero persistent database/OSS effects",
    )
    for relative_path, source in ((RELEASE_PATH, release), (notes_path, first_block)):
        for marker in evidence_markers:
            if marker not in source:
                failures.append(f"{relative_path}: bounded V3.2.5 repair evidence missing: {marker}")

    sop_path = "docs/sop/09-export-retirement-and-oss-local-export.md"
    sop = legacy.legacy._read(root, sop_path, failures)
    required_sop_markers = (
        f"# {DISPLAY_VERSION}",
        "v325-external-photo",
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
        "明确批准继续",
        "不删除 OSS",
        "只读 OSS",
    )
    for marker in required_sop_markers:
        if marker not in sop:
            failures.append(f"{sop_path}: required operating marker missing: {marker}")
    if "v324-external-photo" in sop:
        failures.append(f"{sop_path}: V3.2.5 operational identity must not retain v324 IDs")

    runbook_path = "docs/sop/06-production-deploy-runbook.md"
    runbook = legacy.legacy._read(root, runbook_path, failures)
    if MIGRATION_REVISION not in runbook:
        failures.append(f"{runbook_path}: Alembic head must remain {MIGRATION_REVISION}")

    health_path = "scripts/production_health_check.py"
    health_tree = legacy.legacy._parse_python(root, health_path, failures)
    paths = tuple(legacy.legacy._literal_assignment(health_tree, "RETIRED_PATHS") or ())
    if paths != legacy.legacy.RETIRED_HEALTH_PATHS:
        failures.append(f"{health_path}: production health check must probe every retired path and child")


def collect_failures(root: Path) -> list[str]:
    root = Path(root)
    failures: list[str] = []
    for relative_path in V325_REQUIRED_FILES:
        if not (root / relative_path).is_file():
            failures.append(f"{relative_path}: required V3.2.5 file is missing")
    _check_version_surfaces(root, failures)
    legacy.legacy._check_retirement_contract(root, failures)
    legacy.legacy._check_frontend_retirement(root, failures)
    legacy.legacy._check_worker_and_producers(root, failures)
    legacy.legacy._check_migration_and_manifest(root, failures)
    legacy.legacy._check_migration_head(root, failures)
    legacy.legacy._check_package_contract(root, failures)
    legacy._check_https_handler_compatibility(root, failures)
    _check_migration_contract(root, failures)
    _check_v325_package_contract(root, failures)
    _check_release_record_and_sop(root, failures)
    return failures


def main(argv: list[str] | None = None) -> int:
    if argv:
        print("verify_v3_2_5_release.py does not accept positional arguments", file=sys.stderr)
        return 2
    failures = collect_failures(ROOT)
    if failures:
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("[OK] V3.2.5 release contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
