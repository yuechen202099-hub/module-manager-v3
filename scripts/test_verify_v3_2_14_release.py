from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile

import pytest


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "verify_v3_2_14_release.py"
V3213_PRODUCTION_RECORD_SHA256 = (
    "2db0b2c7a895d57dfef268ff3f12063c6104a06cbe9031eabcb86b70ea98bfb8"
)
VALID_SOURCE_COMMIT = "1" * 40
VALID_PACKAGE_SHA256 = "a" * 64


def load_verifier():
    assert VERIFIER_PATH.is_file(), "V3.2.14 release verifier is missing"
    spec = importlib.util.spec_from_file_location("verify_v3_2_14_release", VERIFIER_PATH)
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
    command = [sys.executable, str(root / "scripts" / "verify_v3_2_14_release.py"), "--phase", phase]
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


def write_attested_record(repo: Path) -> Path:
    path = repo / "ops/releases/V3.2.14.md"
    text = path.read_text(encoding="utf-8")
    replacements = {
        "- Status: pending": "- Status: attested",
        "- Local Verification: pending": "- Local Verification: passed",
        "- Package: pending": "- Package: passed",
        "- Production Deployment: pending": "- Production Deployment: passed",
        "- Production Reconciliation: pending": "- Production Reconciliation: passed",
        "- Archive file: pending": (
            "- Archive file: `build/server-release/module-manager-v2-server-3.2.14.zip`"
        ),
        "- SHA256: pending": f"- SHA256: `{VALID_PACKAGE_SHA256}`",
        "- Server SHA256: pending": f"- Server SHA256: `{VALID_PACKAGE_SHA256}`",
        "- Source commit: pending": f"- Source commit: `{VALID_SOURCE_COMMIT}`",
        "- Backup verification: pending": "- Backup verification: passed",
        "- Uvicorn readiness: pending": "- Uvicorn readiness: `127.0.0.1:8000 ready`",
        "- Authorization acceptance: pending": "- Authorization acceptance: passed",
        "- Zero-write acceptance: pending": "- Zero-write acceptance: passed",
        "- Camera requests: pending": "- Camera requests: `0`",
        "- Client-platform requests: pending": "- Client-platform requests: `0`",
        "- Maintenance restoration: pending": "- Maintenance restoration: passed",
        "- Soak health checks: pending": "- Soak health checks: passed",
        "- Attestation: pending": "- Attestation: passed",
        "- Backup directory: pending": "- Backup directory: `/opt/module-manager-v2/backups/v3.2.14-20260828T010000Z`",
        "- Release directory: pending": "- Release directory: `/opt/module-manager-v2/releases/v3.2.14-20260828T010000Z`",
        "- Rollback directory: pending": "- Rollback directory: `/opt/module-manager-v2/releases/v3.2.13-20260827T160539Z`",
        "- Local health: pending": "- Local health: `HTTP 200`",
        "- Public health: pending": "- Public health: `HTTP 200`",
        "- Browser viewport: pending": "- Browser viewport: `390x844 passed`",
    }
    for pending, attested in replacements.items():
        assert pending in text
        text = text.replace(pending, attested, 1)
    path.write_text(text, encoding="utf-8")
    return path


def test_current_v3214_source_contract_executes_for_pending_candidate() -> None:
    result = run_verifier(ROOT, "source")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[OK] V3.2.14 source release contract" in result.stdout


def test_v3213_production_record_is_byte_locked(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "ops/releases/V3.2.13.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nmutated\n", encoding="utf-8")

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert V3213_PRODUCTION_RECORD_SHA256 in result.stderr


def test_v3214_contract_rejects_review_lock_regression(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-api/app/services/collector_transfer.py"
    marker = 'if locked_state in {"no_construction", "blocked"}:'
    text = path.read_text(encoding="utf-8")
    assert marker in text
    path.write_text(
        text.replace(marker, 'if locked_state in {"no_construction", "needs_review", "blocked"}:', 1),
        encoding="utf-8",
    )

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert "classification-independent rephoto" in result.stderr


def test_v3214_contract_rejects_missing_original_photo_preview(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-web/src/components/data-center/DataCenterGroupReviewPanel.vue"
    marker = "fetchGroupPhotoObjectUrl(groupId, photo.id, 'original'"
    text = path.read_text(encoding="utf-8")
    assert marker in text
    path.write_text(text.replace(marker, "removed_original_photo_preview(", 1), encoding="utf-8")

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert "protected original-photo preview" in result.stderr


def test_v3214_contract_rejects_lightbox_without_focus_restoration(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-web/src/components/PhotoLightbox.vue"
    marker = "if (previousFocus?.isConnected) previousFocus.focus()"
    text = path.read_text(encoding="utf-8")
    assert marker in text
    path.write_text(text.replace(marker, "// removed focus restoration", 1), encoding="utf-8")

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert "lightbox keyboard focus" in result.stderr


def test_v3214_contract_requires_lightbox_focus_regression_test(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-web/src/components/__tests__/PhotoLightbox.spec.ts"
    if path.exists():
        path.unlink()

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert "lightbox keyboard focus regression" in result.stderr


def test_v3214_contract_rejects_a_stale_deploy_runbook_database_head(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "docs/sop/06-production-deploy-runbook.md"
    marker = '$APP/venv/bin/python -m alembic current | grep -q "20260824_0016"'
    text = path.read_text(encoding="utf-8")
    assert marker in text
    path.write_text(text.replace(marker, marker.replace("20260824_0016", "20260724_0014"), 1), encoding="utf-8")

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert "production Alembic head gate" in result.stderr


def test_v3213_archive_cannot_satisfy_v3214_package_gate(tmp_path: Path) -> None:
    package = tmp_path / "module-manager-v2-server-3.2.13.zip"
    with ZipFile(package, "w", ZIP_DEFLATED) as archive:
        archive.writestr("SOURCE_COMMIT", "0" * 40 + "\n")
        archive.writestr("RELEASE_MANIFEST.md", "# Release\n\n- Version: 3.2.13\n")

    result = run_verifier(ROOT, "package", package_path=package)

    assert result.returncode == 1
    assert "Version 3.2.14" in result.stderr


def test_pending_v3214_candidate_does_not_pass_attestation() -> None:
    result = run_verifier(ROOT, "attestation")

    assert result.returncode == 1
    assert "attestation requires Status: attested" in result.stderr


def test_complete_v3214_production_attestation_passes(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    write_attested_record(repo)

    result = run_verifier(repo, "attestation")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[OK] V3.2.14 attestation release contract" in result.stdout


@pytest.mark.parametrize(
    ("valid_line", "forged_line", "expected_error"),
    (
        (
            "- Archive file: `build/server-release/module-manager-v2-server-3.2.14.zip`",
            "- Archive file: `build/server-release/module-manager-v2-server-3.2.13.zip`",
            "Archive file",
        ),
        (
            f"- Source commit: `{VALID_SOURCE_COMMIT}`",
            f"- Source commit: `{'1' * 39}`",
            "Source commit",
        ),
        (
            f"- SHA256: `{VALID_PACKAGE_SHA256}`",
            f"- SHA256: `{'g' * 64}`",
            "valid SHA256",
        ),
        (
            "- Backup verification: passed",
            "- Backup verification: pending",
            "Backup verification",
        ),
        (
            "- Browser viewport: `390x844 passed`",
            "- Browser viewport: pending",
            "Browser viewport",
        ),
    ),
)
def test_v3214_attestation_rejects_forged_or_missing_production_evidence(
    tmp_path: Path,
    valid_line: str,
    forged_line: str,
    expected_error: str,
) -> None:
    repo = copy_contract_repo(tmp_path)
    path = write_attested_record(repo)
    text = path.read_text(encoding="utf-8")
    assert valid_line in text
    path.write_text(text.replace(valid_line, forged_line, 1), encoding="utf-8")

    result = run_verifier(repo, "attestation")

    assert result.returncode == 1
    assert expected_error in result.stderr


def test_v3214_attestation_rejects_duplicate_sha256(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = write_attested_record(repo)
    with path.open("a", encoding="utf-8") as record:
        record.write(f"\n- SHA256: `{VALID_PACKAGE_SHA256}`\n")

    result = run_verifier(repo, "attestation")

    assert result.returncode == 1
    assert "SHA256" in result.stderr



@pytest.mark.parametrize(
    ("relative_path", "marker", "label"),
    (
        (
            "v2-api/tests/test_terminal_review_domain.py",
            "def test_safe_constructed_sources_survive_unconstructed_and_incomplete_rows()",
            "Task 1 safe constructed source regression",
        ),
        (
            "v2-api/tests/test_collector_transfer_service.py",
            "def test_open_global_terminal_keeps_only_safe_constructed_sources(",
            "Task 1 terminal open regression",
        ),
        (
            "v2-api/tests/test_collector_transfer_service.py",
            "def test_manual_demand_matches_unique_current_project_collectors_and_audits(",
            "Task 2 manual demand allocation regression",
        ),
        (
            "v2-api/tests/test_collector_transfer_api.py",
            "def test_manual_collector_demand_requires_positive_quantity_and_administrator(",
            "Task 2 manual demand API regression",
        ),
        (
            "v2-api/tests/test_collector_transfer_service.py",
            "def test_global_terminal_detail_reuses_authorized_source_photo_for_present_collector(",
            "Task 3 present collector source-photo regression",
        ),
        (
            "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
            "posts a positive manual demand to the active terminal through the API boundary",
            "Task 4 manual demand API boundary regression",
        ),
        (
            "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
            "omits persisted completed meter and collector items after reopening",
            "Task 4 completed row visibility regression",
        ),
    ),
)


def test_v3214_contract_requires_task_1_through_4_regression_markers(
    tmp_path: Path,
    relative_path: str,
    marker: str,
    label: str,
) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / relative_path
    text = path.read_text(encoding="utf-8")
    assert marker in text
    path.write_text(text.replace(marker, "removed_required_v3214_regression", 1), encoding="utf-8")

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert label in result.stderr


@pytest.mark.parametrize(
    ("relative_path", "marker", "label"),
    (
        (
            "v2-web/src/views/CollectorInventoryView.vue",
            "if (await startQuaggaScanner(session))",
            "V3.2.13 inventory scanner regression",
        ),
        (
            "v2-web/src/views/CollectorInventoryView.vue",
            "const stream = await requestCameraStream(session)",
            "V3.2.13 inventory scanner regression",
        ),
        (
            "v2-web/src/views/CollectorInventoryView.vue",
            "function closeScanner()",
            "V3.2.13 inventory scanner regression",
        ),
        (
            "v2-web/src/views/__tests__/CollectorInventoryView.spec.ts",
            "reuses the construction Quagga scanner before opening a competing native camera stream",
            "V3.2.13 inventory scanner test regression",
        ),
        (
            "v2-web/src/views/__tests__/CollectorInventoryView.spec.ts",
            "stops a partially started construction scanner before native fallback opens the camera",
            "V3.2.13 inventory scanner test regression",
        ),
        (
            "v2-web/src/views/ConstructionView.vue",
            "scannerSessionIsCurrent(session)",
            "V3.2.13 Android scanner regression",
        ),
        (
            "v2-web/src/views/ConstructionView.vue",
            "decodeFromConstraints",
            "V3.2.13 Android scanner regression",
        ),
        (
            "v2-web/src/views/ConstructionView.vue",
            "controls.stop()",
            "V3.2.13 Android scanner regression",
        ),
        (
            "v2-web/src/views/__tests__/ConstructionScannerAndroid.spec.ts",
            "stops controls from a closed ZXing session instead of letting an old promise replace the reopened scanner",
            "V3.2.13 Android scanner test regression",
        ),
        (
            "scripts/production_health_check.py",
            '("/static/vendor/quagga.min.js", 200)',
            "V3.2.13 scanner health regression",
        ),
        (
            "v2-api/tests/test_terminal_review_domain.py",
            "def test_pending_manual_confirmation_remains_visible_but_keeps_rephoto_source()",
            "V3.2.13 classification-independent rephoto regression",
        ),
    ),
)


def test_v3214_contract_preserves_v3213_scanner_and_rephoto_markers(
    tmp_path: Path,
    relative_path: str,
    marker: str,
    label: str,
) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / relative_path
    text = path.read_text(encoding="utf-8")
    assert marker in text
    path.write_text(text.replace(marker, "removed_v3213_regression"), encoding="utf-8")

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert label in result.stderr
