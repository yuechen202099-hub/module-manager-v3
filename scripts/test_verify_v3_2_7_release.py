from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "verify_v3_2_7_release.py"

CONTRACT_PATHS = (
    "AGENTS.md",
    "RELEASE_MANIFEST.md",
    "ops/releases/V3.2.7.md",
    "scripts/build-client-release.ps1",
    "scripts/verify-client-release.py",
    "scripts/verify_release_sop.py",
    "scripts/verify_v3_2_7_release.py",
    "scripts/test_verify_v3_2_7_release.py",
    "docs/superpowers/specs/2026-08-23-collector-transfer-workbench-design.md",
    "v2-api/alembic/versions/0015_collector_transfer_workbench.py",
    "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py",
    "v2-api/app/api/routes/collector_transfer.py",
    "v2-api/app/main.py",
    "v2-api/app/models.py",
    "v2-api/app/services/collector_transfer.py",
    "v2-api/app/services/ops_status.py",
    "v2-api/pyproject.toml",
    "v2-api/scripts/verify_v3_1_release.py",
    "v2-api/tests/test_v3_1_release.py",
    "v2-api/tests/test_collector_transfer_api.py",
    "v2-api/tests/test_collector_transfer_service.py",
    "v2-web/index.html",
    "v2-web/src/api/services.ts",
    "v2-web/src/api/types.ts",
    "v2-web/src/components/AppLayout.vue",
    "v2-web/src/constants/releaseNotes.ts",
    "v2-web/src/views/CollectorInventoryView.vue",
)


def load_verifier():
    assert VERIFIER_PATH.is_file(), "V3.2.7 release verifier is missing"
    spec = importlib.util.spec_from_file_location("verify_v3_2_7_release", VERIFIER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_contract_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    for relative_path in CONTRACT_PATHS:
        source = ROOT / relative_path
        assert source.is_file(), f"contract fixture source is missing: {relative_path}"
        target = repo / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return repo


def assert_rejected(repo: Path, expected: str) -> None:
    failures = load_verifier().collect_failures(repo, "source")
    assert any(expected in failure for failure in failures), failures


def test_current_v327_source_contract_passes(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    assert load_verifier().collect_failures(repo, "source") == []


def test_source_contract_rejects_old_mutating_run_scan_routes_in_frontend(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-web/src/api/services.ts"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nconst retired = '/collector-transfer/runs/${runId}/inventory/scan'\n",
        encoding="utf-8",
    )
    assert_rejected(repo, "retired mutating run-scan route")


def test_source_contract_rejects_missing_project_inventory_no_run_contract(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-api/app/api/routes/collector_transfer.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace('@router.post("/inventory/scan")', "# removed"),
        encoding="utf-8",
    )
    assert_rejected(repo, "no-run inventory endpoint")


def test_source_contract_rejects_wrong_project_inventory_migration_head(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace('revision = "20260824_0016"', 'revision = "broken"'),
        encoding="utf-8",
    )
    assert_rejected(repo, "20260824_0016")


def test_source_contract_rejects_retired_batch_import_service(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-api/app/services/collector_transfer.py"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\ndef import_collector_inventory(): ...\n",
        encoding="utf-8",
    )

    assert_rejected(repo, "retired collector inventory import")


def test_source_contract_requires_0016_irreversible_migration_warning(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "RELEASE_MANIFEST.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("0016", "0015", 1),
        encoding="utf-8",
    )

    assert_rejected(repo, "irreversible")
