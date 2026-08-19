from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_verifier():
    path = ROOT / "scripts" / "verify_v3_2_3_release.py"
    assert path.exists(), "V3.2.3 release verifier is missing"
    spec = importlib.util.spec_from_file_location("verify_v3_2_3_release", path)
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


def test_current_tree_satisfies_v323_contract() -> None:
    assert load_verifier().main([]) == 0


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
