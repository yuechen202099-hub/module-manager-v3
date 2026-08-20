from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import scripts.oss_local_export as oss_local_export


ROOT = Path(__file__).resolve().parents[1]
SEMANTIC_VERSION_RE = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\Z")


def current_source_version() -> str | None:
    try:
        payload = json.loads((ROOT / "v2-web" / "src" / "version.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    version = payload.get("version") if isinstance(payload, dict) else None
    normalized = version.strip() if isinstance(version, str) else ""
    return normalized if SEMANTIC_VERSION_RE.fullmatch(normalized) else None


CURRENT_SOURCE_VERSION = current_source_version()
V323_CURRENT_TREE_ONLY = pytest.mark.skipif(
    CURRENT_SOURCE_VERSION is not None and CURRENT_SOURCE_VERSION != "3.2.3",
    reason="historical V3.2.3 current-tree-only contract requires active version 3.2.3",
)


def load_verifier():
    path = ROOT / "scripts" / "verify_v3_2_3_release.py"
    assert path.exists(), "V3.2.3 release verifier is missing"
    spec = importlib.util.spec_from_file_location("verify_v3_2_3_release", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_production_health_check():
    path = ROOT / "scripts" / "production_health_check.py"
    spec = importlib.util.spec_from_file_location("production_health_check", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TemporaryRepository:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, relative_path: str) -> Path:
        return self.root / relative_path

    def read(self, relative_path: str) -> str:
        return self.path(relative_path).read_text(encoding="utf-8")

    def write(self, relative_path: str, value: str) -> None:
        target = self.path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding="utf-8")

    def append(self, relative_path: str, value: str) -> None:
        self.write(relative_path, self.read(relative_path) + value)

    def replace(self, relative_path: str, old: str, new: str) -> None:
        source = self.read(relative_path)
        assert old in source, f"fixture marker missing from {relative_path}: {old!r}"
        self.write(relative_path, source.replace(old, new, 1))


@pytest.fixture()
def tmp_repo(tmp_path: Path) -> TemporaryRepository:
    verifier = load_verifier()
    destination = tmp_path / "repo"
    destination.mkdir()
    for relative_path in verifier.CONTRACT_PATHS:
        source = ROOT / relative_path
        if not source.exists():
            continue
        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
    return TemporaryRepository(destination)


def failures_for(tmp_repo: TemporaryRepository) -> list[str]:
    return load_verifier().collect_failures(tmp_repo.root)


def assert_rejected(tmp_repo: TemporaryRepository, marker: str) -> None:
    failures = failures_for(tmp_repo)
    assert any(marker in failure for failure in failures), failures


@V323_CURRENT_TREE_ONLY
def test_current_tree_satisfies_v323_contract() -> None:
    assert load_verifier().main([]) == 0


@V323_CURRENT_TREE_ONLY
@pytest.mark.parametrize(
    ("relative_path", "old", "new"),
    (
        ("v2-api/app/services/ops_status.py", 'return "3.2.3"', 'return "0.0.0"'),
        ("v2-api/app/main.py", 'version="3.2.3"', 'version="0.0.0"'),
        ("v2-api/pyproject.toml", 'version = "3.2.3"', 'version = "0.0.0"'),
        ("v2-web/package.json", '"version": "3.2.3"', '"version": "0.0.0"'),
        ("v2-web/src/version.json", '"3.2.3"', '"0.0.0"'),
        ("v2-web/index.html", "Module Manager V3.2.3", "Module Manager V0.0.0"),
        ("v2-web/src/components/AppLayout.vue", "V3.2.3", "V0.0.0"),
    ),
)
def test_release_verifier_rejects_stale_version_surfaces(
    tmp_repo: TemporaryRepository,
    relative_path: str,
    old: str,
    new: str,
) -> None:
    tmp_repo.replace(relative_path, old, new)
    assert_rejected(tmp_repo, relative_path)


@V323_CURRENT_TREE_ONLY
def test_release_verifier_requires_candidate_branch_and_deployed_baseline(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.replace("AGENTS.md", "production/V3/3.2.3", "production/V3/9.9.9")
    assert_rejected(tmp_repo, "production/V3/3.2.3")


def test_release_verifier_requires_exact_retirement_copy(tmp_repo: TemporaryRepository) -> None:
    tmp_repo.replace("v2-api/app/services/export_retirement.py", "请联系管理员", "请联系管理员！")
    assert_rejected(tmp_repo, "retirement message")


@pytest.mark.parametrize(
    "path",
    (
        "/exports",
        "/exports/child",
        "/local-test/export-manifest/final-delivery",
        "/local-test/unmatched/export",
        "/local-test/photo-barcode/review-groups/export",
    ),
)
def test_release_verifier_requires_every_retired_path_class(
    tmp_repo: TemporaryRepository,
    path: str,
) -> None:
    retirement = tmp_repo.read("v2-api/app/services/export_retirement.py")
    if path == "/exports/child":
        retirement = retirement.replace('normalized.startswith("/exports/")', "False")
    else:
        retirement = retirement.replace(f'"{path}"', f'"{path}-missing"', 1)
    tmp_repo.write("v2-api/app/services/export_retirement.py", retirement)
    assert_rejected(tmp_repo, "retired path")


def test_release_verifier_rejects_retired_paths_hidden_in_dead_code(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.replace(
        "v2-api/app/services/export_retirement.py",
        '''    return (
        normalized == "/exports"
        or normalized.startswith("/exports/")
        or normalized in RETIRED_EXACT_PATHS
    )''',
        '''    if False:
        return (
            normalized == "/exports"
            or normalized.startswith("/exports/")
            or normalized in RETIRED_EXACT_PATHS
        )
    return False''',
    )

    assert_rejected(tmp_repo, "retired path predicate")


@pytest.mark.parametrize(
    "terminator",
    (
        '    raise RuntimeError("stop before retirement return")\n',
        "    return False\n",
        '    if True:\n        raise RuntimeError("stop before retirement return")\n',
        "    if True:\n        return False\n",
    ),
)
def test_release_verifier_rejects_termination_before_retired_path_return(
    tmp_repo: TemporaryRepository,
    terminator: str,
) -> None:
    marker = '''    return (
        normalized == "/exports"'''
    tmp_repo.replace(
        "v2-api/app/services/export_retirement.py",
        marker,
        terminator + marker,
    )

    assert_rejected(tmp_repo, "retired path predicate")


def test_release_verifier_requires_retirement_before_authentication(
    tmp_repo: TemporaryRepository,
) -> None:
    old = """        if is_retired_export_path(request.url.path):\n            return retired_export_response()\n        rejection = production_auth_rejection(request)"""
    new = """        rejection = production_auth_rejection(request)\n        if is_retired_export_path(request.url.path):\n            return retired_export_response()"""
    tmp_repo.replace("v2-api/app/main.py", old, new)
    assert_rejected(tmp_repo, "before authentication")


@pytest.mark.parametrize(
    ("relative_path", "marker"),
    (
        ("v2-web/src/router/staticPages.ts", "title: '导出中心'"),
        ("v2-web/src/api/services.ts", "createExportJob"),
        ("v2-api/app/services/barcode_maintenance_worker.py", '"delivery_package": lambda'),
        ("v2-api/scripts/migrate_external_photos_to_oss.py", "ThreadPoolExecutor(max_workers=2)"),
        ("v2-api/scripts/migrate_external_photos_to_oss.py", "urlopen('https://example.invalid')"),
        ("v2-api/scripts/migrate_external_photos_to_oss.py", "bucket.delete_object('key')"),
    ),
)
def test_release_verifier_rejects_retired_or_unsafe_markers(
    tmp_repo: TemporaryRepository,
    relative_path: str,
    marker: str,
) -> None:
    tmp_repo.append(relative_path, "\n" + marker + "\n")
    assert_rejected(tmp_repo, relative_path)


@pytest.mark.parametrize(
    "relative_path",
    (
        "v2-web/src/views/ExportsView.vue",
        "v2-web/src/composables/useExportCenterQuery.ts",
        "v2-web/src/components/export-center/ExportCatalogTab.vue",
        "v2-web/src/components/export-center/ExportJobsTable.vue",
        "v2-web/src/components/export-center/TerminalDeliveryTab.vue",
    ),
)
def test_release_verifier_rejects_deleted_export_ui_files(
    tmp_repo: TemporaryRepository,
    relative_path: str,
) -> None:
    tmp_repo.write(relative_path, "retired file resurrected\n")
    assert_rejected(tmp_repo, relative_path)


def test_release_verifier_requires_exactly_two_worker_claim_kinds(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.replace(
        "v2-api/app/services/barcode_maintenance_worker.py",
        'claim_order = ("verification", "auto_archive")',
        'claim_order = ("verification", "auto_archive", "delivery_package")',
    )
    assert_rejected(tmp_repo, "worker claim kinds")


@pytest.mark.parametrize(
    ("relative_path", "function_marker", "guard"),
    (
        ("v2-api/app/services/delivery_cache.py", "enqueue_json_delivery_cache_job", "return None"),
        ("v2-api/app/services/delivery_cache.py", "enqueue_postgres_delivery_cache_job", "return None"),
        ("v2-api/app/services/delivery_package_queue.py", "request_postgres_delivery_package", "_raise_delivery_retired()"),
        ("v2-api/app/services/state_repository.py", "_enqueue_delivery_cache_after_commit", "return None"),
        ("v2-api/app/services/state_repository.py", "_stage_data_center_auto_archive_delivery_jobs", 'return "retired"'),
    ),
)
def test_release_verifier_requires_low_level_producer_tombstones(
    tmp_repo: TemporaryRepository,
    relative_path: str,
    function_marker: str,
    guard: str,
) -> None:
    source = tmp_repo.read(relative_path)
    function_start = source.index(f"def {function_marker}") if f"def {function_marker}" in source else source.index(f"def {function_marker}")
    guard_start = source.index(guard, function_start)
    source = source[:guard_start] + "pass" + source[guard_start + len(guard) :]
    tmp_repo.write(relative_path, source)
    assert_rejected(tmp_repo, function_marker)


def test_release_verifier_requires_30_mib_and_forbid_overwrite(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.replace(
        "v2-api/app/services/external_photo_oss_migration.py",
        "MAX_EXTERNAL_PHOTO_BYTES = 30 * 1024 * 1024",
        "MAX_EXTERNAL_PHOTO_BYTES = 31 * 1024 * 1024",
    )
    tmp_repo.replace(
        "v2-api/app/services/external_photo_oss_migration.py",
        '"x-oss-forbid-overwrite": "true"',
        '"x-oss-forbid-overwrite": "false"',
    )
    failures = failures_for(tmp_repo)
    assert any("30 MiB" in item for item in failures)
    assert any("forbid overwrite" in item for item in failures)


def test_release_verifier_rejects_migration_concurrency_option(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.append(
        "v2-api/scripts/migrate_external_photos_to_oss.py",
        '\nparser.add_argument("--workers", type=int)\n',
    )
    assert_rejected(tmp_repo, "concurrency option")


def test_release_verifier_rejects_thread_pool_called_through_import_alias(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.append(
        "v2-api/scripts/migrate_external_photos_to_oss.py",
        "\nfrom concurrent.futures import ThreadPoolExecutor as MigrationPool\n"
        "MigrationPool(max_workers=2)\n",
    )

    assert_rejected(tmp_repo, "ThreadPoolExecutor")


def test_release_verifier_rejects_delete_object_called_through_module_and_call_aliases(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.append(
        "v2-api/scripts/migrate_external_photos_to_oss.py",
        "\nimport oss2 as storage_sdk\n"
        "remove_object = storage_sdk.Bucket.delete_object\n"
        "remove_object(None, 'key')\n",
    )

    assert_rejected(tmp_repo, "delete_object")


def test_release_verifier_requires_scalar_manifest_query_and_header_first_stream(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.append("v2-api/scripts/build_oss_export_manifest.py", "\nsession.query(Photo)\n")
    tmp_repo.replace(
        "v2-api/scripts/build_oss_export_manifest.py",
        '"kind": "manifest"',
        '"kind": "item"',
    )
    failures = failures_for(tmp_repo)
    assert any("scalar-only" in item for item in failures)
    assert any("header first" in item for item in failures)


def test_release_verifier_rejects_dead_manifest_yield_before_item_stream(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.replace(
        "v2-api/scripts/build_oss_export_manifest.py",
        '''    yield {
        "schema": SCHEMA,
        "kind": "manifest",
        "planned_count": len(members),
        "planned_bytes": sum(int(member["photo"].get("byte_size") or 0) for member in members),
    }''',
        '''    if False:
        yield {"kind": "manifest"}
    if True:
        yield {
            "schema": SCHEMA,
            "kind": "item",
            "planned_count": len(members),
            "planned_bytes": sum(int(member["photo"].get("byte_size") or 0) for member in members),
        }''',
    )

    assert_rejected(tmp_repo, "header first")


@pytest.mark.parametrize(
    "terminator",
    (
        '    raise RuntimeError("stop before manifest")\n',
        "    return\n",
        '    if True:\n        raise RuntimeError("stop before manifest")\n',
        "    if True:\n        return\n",
    ),
)
def test_release_verifier_rejects_termination_before_manifest_header(
    tmp_repo: TemporaryRepository,
    terminator: str,
) -> None:
    marker = '''    yield {
        "schema": SCHEMA,
        "kind": "manifest",'''
    tmp_repo.replace(
        "v2-api/scripts/build_oss_export_manifest.py",
        marker,
        terminator + marker,
    )

    assert_rejected(tmp_repo, "header first")


@pytest.mark.parametrize(
    "premature_effect",
    (
        '    yield {"kind": "item"}\n',
        '    signer("premature", 60)\n',
        '    if True:\n        signer("premature", 60)\n',
        '    early_signer = signer\n    early_signer("premature", 60)\n',
    ),
)
def test_release_verifier_rejects_item_or_signing_before_manifest_header(
    tmp_repo: TemporaryRepository,
    premature_effect: str,
) -> None:
    marker = '''    yield {
        "schema": SCHEMA,
        "kind": "manifest",'''
    tmp_repo.replace(
        "v2-api/scripts/build_oss_export_manifest.py",
        marker,
        premature_effect + marker,
    )

    assert_rejected(tmp_repo, "header first")


def test_release_verifier_allows_nonterminating_setup_before_live_targets(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.replace(
        "v2-api/app/services/export_retirement.py",
        "def is_retired_export_path(path: str) -> bool:\n",
        'def is_retired_export_path(path: str) -> bool:\n    """Classify live request paths."""\n    audit_marker = path\n',
    )
    tmp_repo.replace(
        "v2-api/scripts/build_oss_export_manifest.py",
        ") -> Iterator[dict[str, Any]]:\n    if not 60 <= expires_seconds <= 600:",
        ') -> Iterator[dict[str, Any]]:\n    """Emit the header before signed items."""\n    audit_scope = scope\n    if not 60 <= expires_seconds <= 600:',
    )

    failures = failures_for(tmp_repo)
    assert not any("retired path predicate" in failure for failure in failures), failures
    assert not any("header first" in failure for failure in failures), failures


@pytest.mark.parametrize(
    ("old", "new", "marker"),
    (
        ("MAX_DOWNLOAD_WORKERS = 4", "MAX_DOWNLOAD_WORKERS = 5", "four workers"),
        ("MAX_PENDING_DOWNLOADS = 8", "MAX_PENDING_DOWNLOADS = 9", "eight pending"),
        ("RETRY_DELAYS = (1.0, 2.0, 4.0)", "RETRY_DELAYS = (1.0, 3.0, 4.0)", "1/2/4"),
    ),
)
def test_release_verifier_requires_local_download_bounds(
    tmp_repo: TemporaryRepository,
    old: str,
    new: str,
    marker: str,
) -> None:
    tmp_repo.replace("scripts/oss_local_export.py", old, new)
    assert_rejected(tmp_repo, marker)


def test_release_verifier_requires_unchanged_migration_head(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.write("v2-api/alembic/versions/0015_export_retirement.py", "revision = '20260819_0015'\n")
    assert_rejected(tmp_repo, "migration head must remain 0014")


def test_release_verifier_requires_package_members_and_forbids_runtime_artifacts(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.replace(
        "scripts/verify-client-release.py",
        '"scripts/oss_local_export.py",',
        "",
    )
    tmp_repo.replace(
        "scripts/verify-client-release.py",
        '"migration-reports",',
        "",
    )
    failures = failures_for(tmp_repo)
    assert any("required package member" in item for item in failures)
    assert any("forbidden package classifier" in item for item in failures)


@V323_CURRENT_TREE_ONLY
def test_release_verifier_requires_pending_candidate_lifecycle(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.replace("ops/releases/V3.2.3.md", "- Package: pending", "- Package: passed")
    assert_rejected(tmp_repo, "Package")


def test_release_verifier_requires_retired_health_probes(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.replace(
        "scripts/production_health_check.py",
        '"/exports/terminal-readiness",',
        "",
    )
    assert_rejected(tmp_repo, "production health check")


class RetiredPathHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/gone":
            self.send_response(410)
        elif self.path == "/ok":
            self.send_response(200)
        elif self.path.startswith("/redirect-"):
            self.send_response(int(self.path.removeprefix("/redirect-")))
            self.send_header("Location", "/gone")
        else:
            self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def run_retired_path_server() -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), RetiredPathHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


class ProductionHealthContractHandler(BaseHTTPRequestHandler):
    public_200 = {
        "/health",
        "/login",
        "/project-board",
        "/global-search",
        "/claim-tasks",
        "/construction",
    }
    retired_410 = {
        "/exports",
        "/exports/terminal-readiness",
        "/local-test/export-manifest/final-delivery",
        "/local-test/photo-barcode/review-groups/export",
        "/local-test/unmatched/export",
    }
    hidden_404 = {"/docs", "/redoc", "/openapi.json"}

    def do_GET(self) -> None:  # noqa: N802
        self.server.seen_paths.append(self.path)  # type: ignore[attr-defined]
        if self.path in self.public_200:
            self.send_response(200)
        elif self.path == "/task-hall":
            self.send_response(307)
            self.send_header("Location", "/global-search")
        elif self.path in self.retired_410:
            self.send_response(410)
        elif self.path in self.hidden_404:
            self.send_response(404)
        else:
            self.send_response(500)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def run_production_health_contract_server() -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), ProductionHealthContractHandler)
    server.seen_paths = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_health_check_accepts_task_hall_307_and_probes_claim_tasks_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    health_check = load_production_health_check()
    server, thread = run_production_health_contract_server()
    base_url = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(
        health_check.sys,
        "argv",
        [
            "production_health_check.py",
            "--base-url",
            base_url,
            "--expected-version",
            "3.2.3",
            "--skip-admin",
        ],
    )
    try:
        assert health_check.main() == 0
        seen_paths = server.seen_paths  # type: ignore[attr-defined]
        assert seen_paths.count("/task-hall") == 1
        assert seen_paths.count("/claim-tasks") == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_retired_health_probe_accepts_direct_410_and_rejects_200() -> None:
    health_check = load_production_health_check()
    server, thread = run_retired_path_server()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        health_check.assert_http_status(f"{base_url}/gone", 410)
        with pytest.raises(AssertionError, match="returned HTTP 200, expected 410"):
            health_check.assert_http_status(f"{base_url}/ok", 410)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("status", (301, 302, 307, 308))
def test_retired_health_probe_rejects_redirect_to_410(status: int) -> None:
    health_check = load_production_health_check()
    server, thread = run_retired_path_server()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        with pytest.raises(AssertionError, match=rf"returned HTTP {status}, expected 410"):
            health_check.assert_http_status(f"{base_url}/redirect-{status}", 410)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def bash_blocks(markdown: str) -> list[tuple[int, int, str]]:
    return [
        (match.start(), match.end(), match.group("body"))
        for match in re.finditer(r"(?ms)^```bash\n(?P<body>.*?)^```$", markdown)
    ]


def powershell_blocks(markdown: str) -> list[str]:
    return [
        match.group("body")
        for match in re.finditer(
            r"(?ms)^(?P<fence>`{3}|~{3})powershell\r?\n(?P<body>.*?)^(?P=fence)\s*$",
            markdown,
        )
    ]


def test_task11_acceptance_scope_selector_executes_against_migration_report_fixture(
    tmp_path: Path,
) -> None:
    plan = (
        ROOT
        / "docs"
        / "superpowers"
        / "plans"
        / "2026-08-17-v3.2.3-export-center-retirement.md"
    ).read_text(encoding="utf-8")
    match = re.search(
        r"(?m)^\$scope = ssh .*? -c '(?P<code>import json;.*?)'\"\s*$",
        plan,
    )
    assert match is not None, "Task 11 acceptance-scope selector command is missing"

    report = {
        "items": {
            "not-ready": {
                "status": "committed",
                "final_delivery_ready": False,
                "team_id": "team-not-ready",
                "group_id": "group-not-ready",
            },
            "ready": {
                "status": "committed",
                "final_delivery_ready": True,
                "team_id": "team-ready",
                "group_id": "group-ready",
            },
        }
    }
    report_path = tmp_path / "full.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    code = match.group("code").replace(r'\"', '"')
    code = code.replace("$reportDir/full.json", report_path.as_posix())

    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "team-ready group-ready"


@pytest.mark.parametrize(
    "relative_path",
    (
        "docs/sop/09-export-retirement-and-oss-local-export.md",
        "docs/superpowers/plans/2026-08-17-v3.2.3-export-center-retirement.md",
    ),
)
def test_documented_acceptance_export_executes_the_safe_default_output_contract(
    relative_path: str,
) -> None:
    markdown = (ROOT / relative_path).read_text(encoding="utf-8")
    blocks = [
        block
        for block in powershell_blocks(markdown)
        if "build_oss_export_manifest.py" in block and "oss_local_export.py" in block
    ]
    assert len(blocks) == 1
    invocation = next(line for line in blocks[0].splitlines() if "oss_local_export.py" in line)
    argv = invocation.split("oss_local_export.py", 1)[1].strip().split()

    args = oss_local_export.build_parser().parse_args(argv)
    assert args.output is None
    assert args.formats == ["files", "zip", "csv", "xlsx"]
    assert args.max_workers == 4


def test_migration_execute_and_resume_are_separate_copyable_blocks_with_approval_stop() -> None:
    sop = (ROOT / "docs" / "sop" / "09-export-retirement-and-oss-local-export.md").read_text(
        encoding="utf-8"
    )
    blocks = bash_blocks(sop)
    execute_blocks = [block for block in blocks if "--execute" in block[2]]
    resume_blocks = [block for block in blocks if "--resume" in block[2]]

    assert len(execute_blocks) == 1
    assert len(resume_blocks) == 1
    execute_block = execute_blocks[0]
    resume_block = resume_blocks[0]
    assert execute_block[1] < resume_block[0]
    assert "--resume" not in execute_block[2]
    assert "--execute" not in resume_block[2]
    between_blocks = sop[execute_block[1] : resume_block[0]]
    assert re.search(r"(?m)^### 人工核验与审批停止点$", between_blocks)


def test_rollback_block_runs_copyable_resource_preflight_before_rollback() -> None:
    sop = (ROOT / "docs" / "sop" / "09-export-retirement-and-oss-local-export.md").read_text(
        encoding="utf-8"
    )
    rollback_blocks = [block[2] for block in bash_blocks(sop) if "--rollback-run" in block[2]]

    assert len(rollback_blocks) == 1
    block = rollback_blocks[0]
    required_in_order = (
        "START_MEMORY_KIB=$((400 * 1024))",
        "STOP_MEMORY_KIB=$((250 * 1024))",
        "START_TEMP_FREE_KIB=$((512 * 1024))",
        "MEM_AVAILABLE_KIB=$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)",
        'test "$MEM_AVAILABLE_KIB" -ge "$START_MEMORY_KIB"',
        'test "$MEM_AVAILABLE_KIB" -ge "$STOP_MEMORY_KIB"',
        'TEMP_FREE_KIB=$(df -Pk "${TMPDIR:-/tmp}" | awk \'NR==2 {print $4}\')',
        'test "$TEMP_FREE_KIB" -ge "$START_TEMP_FREE_KIB"',
        "--rollback-run",
    )
    positions = [block.index(marker) for marker in required_in_order]
    assert positions == sorted(positions)
    assert block.count("exit 1") >= 3
