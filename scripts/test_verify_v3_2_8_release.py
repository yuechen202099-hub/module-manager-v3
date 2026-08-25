from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil

import pytest


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "verify_v3_2_8_release.py"


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


def test_release_gate_keeps_schema_at_0016(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace('revision = "20260824_0016"', 'revision = "broken"'),
        encoding="utf-8",
    )

    assert_rejected(repo, "unchanged collector inventory contract")
