from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "verify_v3_2_6_release.py"

CONTRACT_PATHS = (
    "AGENTS.md",
    "README.md",
    "RELEASE_MANIFEST.md",
    "docs/AGENT_REQUIRED_READING.md",
    "docs/sop/README.md",
    "docs/superpowers/specs/2026-08-23-collector-transfer-workbench-design.md",
    "ops/releases/V3.2.5.md",
    "ops/releases/V3.2.6.md",
    "scripts/build-client-release.ps1",
    "scripts/test_verify_v3_2_6_release.py",
    "scripts/verify-client-release.py",
    "scripts/verify_release_sop.py",
    "scripts/verify_v3_2_5_release.py",
    "scripts/verify_v3_2_6_release.py",
    "v2-api/alembic/versions/0015_collector_transfer_workbench.py",
    "v2-api/app/api/router.py",
    "v2-api/app/api/routes/collector_transfer.py",
    "v2-api/app/domain/collector_transfer.py",
    "v2-api/app/main.py",
    "v2-api/app/models.py",
    "v2-api/app/services/collector_transfer.py",
    "v2-api/app/services/ops_status.py",
    "v2-api/app/static/vue/index.html",
    "v2-api/app/static/vue/version.json",
    "v2-api/pyproject.toml",
    "v2-api/scripts/verify_v3_1_release.py",
    "v2-api/tests/test_api.py",
    "v2-api/tests/test_collector_transfer_api.py",
    "v2-api/tests/test_collector_transfer_domain.py",
    "v2-api/tests/test_collector_transfer_postgres_integration.py",
    "v2-api/tests/test_collector_transfer_service.py",
    "v2-api/tests/test_migrations.py",
    "v2-api/tests/test_models.py",
    "v2-api/tests/test_v3_1_release.py",
    "v2-web/index.html",
    "v2-web/package.json",
    "v2-web/src/api/services.ts",
    "v2-web/src/api/types.ts",
    "v2-web/src/components/Code128Barcode.vue",
    "v2-web/src/components/AppLayout.vue",
    "v2-web/src/constants/releaseNotes.ts",
    "v2-web/src/router/index.ts",
    "v2-web/src/router/staticPages.ts",
    "v2-web/src/version.json",
    "v2-web/src/views/CollectorBatchManagementView.vue",
    "v2-web/src/views/CollectorInventoryView.vue",
    "v2-web/src/views/CollectorWorkbenchView.vue",
    "v2-web/src/views/__tests__/CollectorInventoryView.spec.ts",
)


def load_verifier():
    assert VERIFIER_PATH.is_file(), "V3.2.6 release verifier is missing"
    spec = importlib.util.spec_from_file_location("verify_v3_2_6_release", VERIFIER_PATH)
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


def test_current_v326_source_contract_passes(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    assert load_verifier().collect_failures(repo, "source") == []


def test_source_contract_rejects_retired_inventory_import_route(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-api/app/api/routes/collector_transfer.py"
    path.write_text(
        path.read_text(encoding="utf-8")
        + '\n@router.post("/runs/{run_id}/inventory/import")\ndef import_inventory(): ...\n',
        encoding="utf-8",
    )
    assert_rejected(repo, "retired collector inventory import")


def test_source_contract_rejects_removed_import_model_or_table(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    model = repo / "v2-api/app/models.py"
    model.write_text(
        model.read_text(encoding="utf-8") + "\nclass CollectorImportRow: ...\n",
        encoding="utf-8",
    )
    migration = repo / "v2-api/alembic/versions/0015_collector_transfer_workbench.py"
    migration.write_text(
        migration.read_text(encoding="utf-8") + '\nop.create_table("collector_import_rows")\n',
        encoding="utf-8",
    )
    assert_rejected(repo, "CollectorImportRow")
    assert_rejected(repo, "collector_import_rows")


def test_source_contract_rejects_batch_import_ui_returning(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    view = repo / "v2-web/src/views/CollectorInventoryView.vue"
    view.write_text(
        view.read_text(encoding="utf-8") + "\n<button>批量导入</button>\n",
        encoding="utf-8",
    )
    assert_rejected(repo, "batch inventory UI")


def test_attestation_contract_rejects_deployment_claim_without_evidence(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    record = repo / "ops/releases/V3.2.6.md"
    record.write_text(
        "\n".join(
            (
                "# V3.2.6 Production Release Record",
                "",
                "- Status: deployed",
                "- Local Verification: passed",
                "- Package: passed",
                "- Production Deployment: passed",
                "- Production Reconciliation: passed",
                "- Rollback target: `/opt/module-manager-v2/releases/v3.2.5-example`",
            )
        ),
        encoding="utf-8",
    )
    failures = load_verifier().collect_failures(repo, "attestation")
    assert any("deployment evidence" in failure for failure in failures), failures
