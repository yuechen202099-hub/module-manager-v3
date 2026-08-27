from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile

import pytest


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "verify_v3_2_12_release.py"
V3211_PRODUCTION_RECORD_SHA256 = (
    "75276c03c18ba4b66cfca62b25b85afa2022ab4aa7a975a46d46b7ad975bda15"
)


def load_verifier():
    assert VERIFIER_PATH.is_file(), "V3.2.12 release verifier is missing"
    spec = importlib.util.spec_from_file_location("verify_v3_2_12_release", VERIFIER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_verifier(
    root: Path,
    phase: str,
    *,
    package_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(root / "scripts" / "verify_v3_2_12_release.py"), "--phase", phase]
    if package_path is not None:
        command.extend(("--package", str(package_path)))
    return subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def copy_contract_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    verifier = load_verifier()
    for relative_path in verifier.REQUIRED_FILES:
        source = ROOT / relative_path
        target = repo / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return repo


def test_current_v3212_source_contract_executes_for_pending_candidate() -> None:
    result = run_verifier(ROOT, "source")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[OK] V3.2.12 source release contract" in result.stdout


def test_v3212_source_contract_binds_attested_v3211_operator_coordinates(tmp_path: Path) -> None:
    verifier = load_verifier()
    expected_markers = (
        "当前生产 release：`/opt/module-manager-v2/releases/v3.2.11-20260827T030718Z`",
        "当前回滚 release：`/opt/module-manager-v2/releases/v3.2.10-20260826T195524Z`",
        "当前生产提交：`2fd8c2cbe377d1316e3f97f6d7f83a53b4e08a3d`",
    )

    assert verifier.OPERATOR_PRODUCTION_MARKERS == expected_markers
    repo = copy_contract_repo(tmp_path)
    path = repo / "docs/AGENT_REQUIRED_READING.md"
    text = path.read_text(encoding="utf-8")
    for marker in expected_markers:
        assert marker in text
        mutated = text.replace(marker, "stale production coordinate", 1)
        path.write_text(mutated, encoding="utf-8")
        failures = verifier.collect_failures(repo, "source")
        assert any("operator release identity" in failure for failure in failures)
        path.write_text(text, encoding="utf-8")


def test_v3212_source_contract_rejects_a_historical_runtime_version(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-api/app/main.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace('version="3.2.12"', 'version="3.2.11"'),
        encoding="utf-8",
    )

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert "v2-api/app/main.py" in result.stderr


def test_v3211_production_record_is_byte_locked(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "ops/releases/V3.2.11.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nmutated\n", encoding="utf-8")

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert V3211_PRODUCTION_RECORD_SHA256 in result.stderr


def test_v3212_source_contract_rejects_a_new_alembic_revision(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    migration_path = repo / "v2-api/alembic/versions/0017_unapproved_candidate_change.py"
    migration_path.write_text(
        '"""Unapproved candidate migration."""\n\n'
        'revision = "20260827_0017"\n'
        'down_revision = "20260824_0016"\n'
        "branch_labels = None\n"
        "depends_on = None\n",
        encoding="utf-8",
    )

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert "no new Alembic migration" in result.stderr
    assert "20260827_0017" in result.stderr


@pytest.mark.parametrize(
    ("relative_path", "marker", "expected_error"),
    (
        (
            "v2-api/app/api/routes/groups.py",
            '@router.post("/data-center/groups/{group_id}/classification-manual-confirm")',
            "409 conflict regression",
        ),
        (
            "v2-api/app/services/data_center.py",
            "def manual_classification_fingerprint(",
            "evidence fingerprint",
        ),
        (
            "v2-api/tests/test_data_center_review.py",
            "def test_json_confirmation_rejects_concurrent_photo_evidence_change_without_audit(",
            "409 conflict regression",
        ),
        (
            "v2-api/tests/test_data_center_review.py",
            "def test_legacy_barcode_rescan_category_context_preserves_classification_and_confirmation(",
            "legacy rescan preservation regression",
        ),
        (
            "v2-api/tests/test_data_center_review.py",
            "def test_data_center_category_carrying_rescan_revokes_marker_only_for_real_evidence_change(",
            "JSON data-center revocation regression",
        ),
        (
            "v2-api/tests/test_state_repository.py",
            "def test_postgres_legacy_rescan_preserves_classification_while_data_center_rescan_revokes_on_change(",
            "PostgreSQL rescan boundary regression",
        ),
        (
            "v2-api/tests/test_state_repository.py",
            "def test_postgres_data_center_rescan_rejects_unsupported_category_before_transaction(",
            "PostgreSQL rescan category validation regression",
        ),
        (
            "v2-api/tests/test_data_center_review.py",
            "def test_dual_classification_evidence_writes_fail_before_json_or_postgres_mutates(",
            "dual-write fail-closed regression",
        ),
    ),
)
def test_v3212_source_contract_executes_and_rejects_missing_behavior_markers(
    tmp_path: Path,
    relative_path: str,
    marker: str,
    expected_error: str,
) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / relative_path
    text = path.read_text(encoding="utf-8")
    assert marker in text
    path.write_text(text.replace(marker, "removed_release_contract_marker", 1), encoding="utf-8")

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert expected_error in result.stderr


def test_v3211_archive_cannot_satisfy_v3212_package_gate(tmp_path: Path) -> None:
    package = tmp_path / "module-manager-v2-server-3.2.11.zip"
    with ZipFile(package, "w", ZIP_DEFLATED) as archive:
        archive.writestr("SOURCE_COMMIT", "0" * 40 + "\n")
        archive.writestr("RELEASE_MANIFEST.md", "# Release\n\n- Version: 3.2.11\n")

    result = run_verifier(ROOT, "package", package_path=package)

    assert result.returncode == 1
    assert "Version 3.2.12" in result.stderr


def test_pending_v3212_candidate_does_not_pass_attestation() -> None:
    result = run_verifier(ROOT, "attestation")

    assert result.returncode == 1
    assert "attestation requires Status: attested" in result.stderr
