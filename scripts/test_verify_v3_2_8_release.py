from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil

import pytest


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "verify_v3_2_8_release.py"

ATTESTATION_FIELD_VALUES = {
    "Status": "attested",
    "Local Verification": "passed",
    "Package": "passed",
    "Production Deployment": "passed",
    "Production Reconciliation": "passed",
    "Rollback target": "V3.2.7",
    "Candidate branch": "`production/V3/3.2.8`",
    "Deployed production baseline": "`V3.2.7`",
    "Candidate version": "`V3.2.8`",
    "Database head": "`20260824_0016 (head)`",
    "Source commit": "`0123456789abcdef0123456789abcdef01234567`",
    "Archive file": "`build/server-release/module-manager-v2-server-3.2.8.zip`",
    "SHA256": "`AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA`",
    "Server SHA256": "`AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA`",
    "Backup directory": "`C:\\Users\\Administrator\\Documents\\module-manager-production-backups\\20260825T010203Z`",
    "Backup verification": "passed: SHA256, pg_restore -l, tar listings, schema nonempty, source metadata",
    "Release directory": "`/opt/module-manager-v2/releases/v3.2.8-20260825_010203`",
    "Rollback directory": "`/opt/module-manager-v2/releases/v3.2.7-20260824_173544`",
    "Uvicorn readiness": "`127.0.0.1:8000 ready`",
    "Local health": "`HTTP 200, version 3.2.8`",
    "Public health": "`HTTP 200, version 3.2.8`",
    "Smoke request count": "`1`",
    "Smoke barcode": "`V328-SMOKE-NOT-FOUND-20260825T010204Z`",
    "Smoke project ID": "`11111111-1111-4111-8111-111111111111`",
    "Smoke decision": "`pool_needs_photo`",
    "Smoke latency ms": "`123`",
    "Smoke physical count delta": "`0`",
    "Smoke photo count delta": "`0`",
    "Smoke scan-event count delta": "`0`",
    "Smoke barcode row count": "`0`",
    "Smoke Uvicorn RSS": "`before=125829120; after=126877696`",
    "Smoke host memory": "`before_available=734003200; after_available=725614592`",
    "Smoke restart delta": "`0`",
    "PostgreSQL sessions": "`idle after smoke`",
    "Browser viewport": "`390x844`",
    "Browser authentication": "`passed`",
    "Browser routes": "`/collector-inventory, /collector-batches, /collector-workbench, /project-board`",
    "Browser native BarcodeDetector": "`unavailable`",
    "Browser real-phone camera permission": "`passed`",
    "Browser live preview": "`passed`",
    "Browser recognition": "`Quagga detection passed`",
    "Browser manual input": "`passed`",
    "Browser camera teardown": "`passed`",
    "Client-platform requests": "`0`",
    "Maintenance worker": "`active`",
    "Maintenance timer": "`active`",
    "Maintenance restoration": "`passed`",
    "Soak health checks": "`passed`",
    "Soak PostgreSQL sessions": "`stable`",
    "Soak restart count delta": "`0`",
    "Attestation": "`passed`",
}


def complete_attestation_record() -> str:
    sections = {
        "Summary": (
            "Status", "Local Verification", "Package", "Production Deployment",
            "Production Reconciliation", "Rollback target", "Candidate branch",
            "Deployed production baseline", "Candidate version", "Database head",
        ),
        "Source and package": (
            "Source commit", "Archive file", "SHA256", "Server SHA256",
        ),
        "Backup": ("Backup directory", "Backup verification"),
        "Deployment readiness": (
            "Release directory", "Rollback directory", "Uvicorn readiness",
            "Local health", "Public health",
        ),
        "Exactly one guarded non-photo smoke": (
            "Smoke request count", "Smoke barcode", "Smoke project ID", "Smoke decision",
            "Smoke latency ms", "Smoke physical count delta", "Smoke photo count delta",
            "Smoke scan-event count delta", "Smoke barcode row count", "Smoke Uvicorn RSS",
            "Smoke host memory", "Smoke restart delta", "PostgreSQL sessions",
        ),
        "Authenticated browser acceptance": (
            "Browser viewport", "Browser authentication", "Browser routes",
            "Browser native BarcodeDetector", "Browser real-phone camera permission",
            "Browser live preview", "Browser recognition", "Browser manual input",
            "Browser camera teardown", "Client-platform requests",
        ),
        "Maintenance and soak": (
            "Maintenance worker", "Maintenance timer", "Maintenance restoration",
            "Soak health checks", "Soak PostgreSQL sessions", "Soak restart count delta",
            "Attestation",
        ),
    }
    lines = ["# V3.2.8 Production Release Record", ""]
    for heading, fields in sections.items():
        lines.extend((f"## {heading}", ""))
        lines.extend(f"- {field}: {ATTESTATION_FIELD_VALUES[field]}" for field in fields)
        lines.append("")
    return "\n".join(lines)


def load_verifier():
    assert VERIFIER_PATH.is_file(), "V3.2.8 release verifier is missing"
    spec = importlib.util.spec_from_file_location("verify_v3_2_8_release", VERIFIER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_contract_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    verifier = load_verifier()
    for relative_path in verifier.REQUIRED_FILES:
        source = ROOT / relative_path
        target = repo / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            shutil.copy2(source, target)
        else:
            assert relative_path == verifier.RELEASE_PATH
            target.write_text("# Pending V3.2.8 fixture\n", encoding="utf-8")
    return repo


def assert_rejected(repo: Path, expected: str, phase: str = "source") -> None:
    failures = load_verifier().collect_failures(repo, phase)
    assert any(expected in failure for failure in failures), failures


def test_current_v328_source_contract_passes(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    assert load_verifier().collect_failures(repo, "source") == []


def test_current_pending_v328_record_fails_attestation(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)

    assert_rejected(repo, "attestation requires", "attestation")


def test_complete_task5_record_passes_attestation(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    (repo / "ops/releases/V3.2.8.md").write_text(
        complete_attestation_record(),
        encoding="utf-8",
    )

    assert load_verifier().collect_failures(repo, "attestation") == []


@pytest.mark.parametrize("field", tuple(ATTESTATION_FIELD_VALUES))
def test_attestation_rejects_each_mutated_task5_field(tmp_path: Path, field: str) -> None:
    repo = copy_contract_repo(tmp_path)
    record = complete_attestation_record()
    expected_line = f"- {field}: {ATTESTATION_FIELD_VALUES[field]}"
    assert record.count(expected_line) == 1
    (repo / "ops/releases/V3.2.8.md").write_text(
        record.replace(expected_line, f"- {field}: pending"),
        encoding="utf-8",
    )

    assert_rejected(repo, field, "attestation")


def test_v327_baseline_rejects_inexact_lifecycle_field(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "ops/releases/V3.2.7.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "- Package: passed",
            "- Package: pending",
        ),
        encoding="utf-8",
    )

    assert_rejected(repo, "Package must equal 'passed' exactly once")


@pytest.mark.parametrize(
    "claim",
    (
        "Production acceptance has been approved.",
        "Production acceptance approval was granted.",
        "V3.2.7 has received production acceptance.",
        "Production attestation was formally signed.",
    ),
)
def test_v327_baseline_rejects_affirmative_acceptance_claim_variant(
    tmp_path: Path,
    claim: str,
) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "ops/releases/V3.2.7.md"
    path.write_text(
        path.read_text(encoding="utf-8") + f"\n{claim}\n",
        encoding="utf-8",
    )

    assert_rejected(repo, "must not claim affirmative production acceptance or attestation")


def test_v327_baseline_unrelated_negation_does_not_hide_chinese_acceptance(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "ops/releases/V3.2.7.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n系统未发现错误且 V3.2.7 已通过生产验收。\n",
        encoding="utf-8",
    )

    assert_rejected(repo, "must not claim affirmative production acceptance or attestation")


def test_v327_baseline_checks_each_acceptance_topic_occurrence(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "ops/releases/V3.2.7.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nNo acceptance evidence was recorded before production acceptance was approved.\n",
        encoding="utf-8",
    )

    assert_rejected(repo, "must not claim affirmative production acceptance or attestation")


def test_v327_baseline_allows_each_locally_negated_topic_occurrence(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "ops/releases/V3.2.7.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nNo acceptance evidence was recorded because production acceptance was not approved.\n",
        encoding="utf-8",
    )

    assert load_verifier().collect_failures(repo, "source") == []


def test_v327_baseline_allows_explicitly_negated_attestation_variant(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "ops/releases/V3.2.7.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\nThere is no V3.2.7 attestation issued.\n",
        encoding="utf-8",
    )

    assert load_verifier().collect_failures(repo, "source") == []


@pytest.mark.parametrize(
    "claim",
    (
        "Production acceptance has not been approved.",
        "Production acceptance approval was not granted.",
        "V3.2.7 has not received production acceptance.",
        "Production attestation was not formally signed.",
    ),
)
def test_v327_baseline_allows_structurally_negated_review_variants(
    tmp_path: Path,
    claim: str,
) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "ops/releases/V3.2.7.md"
    path.write_text(
        path.read_text(encoding="utf-8") + f"\n{claim}\n",
        encoding="utf-8",
    )

    assert load_verifier().collect_failures(repo, "source") == []


def test_attestation_rejects_a_v327_archive_tree_as_v328(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    replacements = {
        "v2-api/app/main.py": ('version="3.2.8"', 'version="3.2.7"'),
        "v2-api/app/services/ops_status.py": ('return "3.2.8"', 'return "3.2.7"'),
        "v2-api/pyproject.toml": ('version = "3.2.8"', 'version = "3.2.7"'),
        "v2-web/index.html": ("Module Manager V3.2.8", "Module Manager V3.2.7"),
        "v2-web/src/version.json": ('"version":"3.2.8"', '"version":"3.2.7"'),
        "RELEASE_MANIFEST.md": ("- Version: 3.2.8", "- Version: 3.2.7"),
    }
    for relative_path, (current, stale) in replacements.items():
        path = repo / relative_path
        path.write_text(path.read_text(encoding="utf-8").replace(current, stale), encoding="utf-8")

    assert_rejected(repo, "required marker must appear exactly once", "attestation")


def test_scale_gate_rejects_missing_regression_file(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    (repo / "v2-api/tests/test_collector_transfer_scale.py").unlink()

    assert_rejected(repo, "test_collector_transfer_scale.py: required V3.2.8 file is missing")


def test_scale_gate_rejects_removed_bounded_lookup_regression(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-api/tests/test_collector_transfer_scale.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "def test_project_collector_lookup_is_bounded_at_production_cardinality(",
            "def removed_bounded_lookup_regression(",
        ),
        encoding="utf-8",
    )

    assert_rejected(repo, "collector scale regression gate")


def test_camera_gate_rejects_missing_regression_file(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    (repo / "v2-web/src/views/__tests__/CollectorInventoryView.spec.ts").unlink()

    assert_rejected(repo, "CollectorInventoryView.spec.ts: required V3.2.8 file is missing")


def test_camera_gate_rejects_preview_before_media_or_removed_quagga_fallback(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-web/src/views/CollectorInventoryView.vue"
    text = path.read_text(encoding="utf-8")
    text = text.replace("const stream = await requestCameraStream(session)", "const stream = null")
    text = text.replace("void startQuaggaScanner(session)", "return")
    path.write_text(text, encoding="utf-8")

    failures = load_verifier().collect_failures(repo, "source")
    camera_failures = [failure for failure in failures if "collector camera preview/fallback" in failure]
    assert len(camera_failures) == 2


def test_camera_gate_requires_quagga_late_init_regressions(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / load_verifier().CAMERA_REGRESSION_PATH
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "catches a Quagga init timeout whose late success leaks its LiveStream",
        "removed Quagga init timeout regression",
    )
    text = text.replace(
        "catches Quagga late init success after %s",
        "removed Quagga teardown boundary regression %s",
    )
    path.write_text(text, encoding="utf-8")

    failures = load_verifier().collect_failures(repo, "source")
    camera_failures = [failure for failure in failures if "collector camera regression gate" in failure]
    assert len(camera_failures) == 2


def test_release_gate_keeps_schema_at_0016(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace('revision = "20260824_0016"', 'revision = "broken"'),
        encoding="utf-8",
    )

    assert_rejected(repo, "unchanged collector inventory contract")
