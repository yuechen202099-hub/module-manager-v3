from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile

import pytest


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "verify_v3_2_13_release.py"
V3212_PRODUCTION_RECORD_SHA256 = (
    "7354aa5be62423111f4e4136cc56d88da76dd426965b7c1c10705eca83d598aa"
)
VALID_SOURCE_COMMIT = "1" * 40
VALID_PACKAGE_SHA256 = "a" * 64


def load_verifier():
    assert VERIFIER_PATH.is_file(), "V3.2.13 release verifier is missing"
    spec = importlib.util.spec_from_file_location("verify_v3_2_13_release", VERIFIER_PATH)
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
    command = [sys.executable, str(root / "scripts" / "verify_v3_2_13_release.py"), "--phase", phase]
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
    path = repo / "ops/releases/V3.2.13.md"
    text = path.read_text(encoding="utf-8")
    replacements = {
        "- Status: pending": "- Status: attested",
        "- Package: pending": "- Package: passed",
        "- Production Deployment: pending": "- Production Deployment: passed",
        "- Production Reconciliation: pending": "- Production Reconciliation: passed",
        "- Archive file: pending": (
            "- Archive file: `build/server-release/module-manager-v2-server-3.2.13.zip`"
        ),
        "- SHA256: pending": f"- SHA256: `{VALID_PACKAGE_SHA256}`",
        "- Server SHA256: pending": f"- Server SHA256: `{VALID_PACKAGE_SHA256}`",
        "- Source commit: pending": f"- Source commit: `{VALID_SOURCE_COMMIT}`",
    }
    for pending, attested in replacements.items():
        assert pending in text
        text = text.replace(pending, attested, 1)
    text += """

## Production evidence

- Backup verification: passed
- Uvicorn readiness: `127.0.0.1:8000 ready`
- Authorization acceptance: passed
- Zero-write acceptance: passed
- Camera requests: `0`
- Client-platform requests: `0`
- Maintenance restoration: passed
- Soak health checks: passed
- Attestation: passed
- Backup directory: `/opt/module-manager-v2/backups/v3.2.13-20260828T010000Z`
- Release directory: `/opt/module-manager-v2/releases/v3.2.13-20260828T010000Z`
- Rollback directory: `/opt/module-manager-v2/releases/v3.2.12-20260827T160539Z`
- Local health: `HTTP 200`
- Public health: `HTTP 200`
- Browser viewport: `390x844 passed`
"""
    path.write_text(text, encoding="utf-8")
    return path


def test_current_v3213_source_contract_executes_for_pending_candidate() -> None:
    result = run_verifier(ROOT, "source")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[OK] V3.2.13 source release contract" in result.stdout


def test_v3212_production_record_is_byte_locked(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "ops/releases/V3.2.12.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nmutated\n", encoding="utf-8")

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert V3212_PRODUCTION_RECORD_SHA256 in result.stderr


def test_v3213_contract_rejects_review_lock_regression(tmp_path: Path) -> None:
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


def test_v3213_contract_rejects_missing_original_photo_preview(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-web/src/components/data-center/DataCenterGroupReviewPanel.vue"
    marker = "fetchGroupPhotoObjectUrl(groupId, photo.id, 'original'"
    text = path.read_text(encoding="utf-8")
    assert marker in text
    path.write_text(text.replace(marker, "removed_original_photo_preview(", 1), encoding="utf-8")

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert "protected original-photo preview" in result.stderr


def test_v3213_contract_rejects_lightbox_without_focus_restoration(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-web/src/components/PhotoLightbox.vue"
    marker = "if (previousFocus?.isConnected) previousFocus.focus()"
    text = path.read_text(encoding="utf-8")
    assert marker in text
    path.write_text(text.replace(marker, "// removed focus restoration", 1), encoding="utf-8")

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert "lightbox keyboard focus" in result.stderr


def test_v3213_contract_requires_lightbox_focus_regression_test(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-web/src/components/__tests__/PhotoLightbox.spec.ts"
    if path.exists():
        path.unlink()

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert "lightbox keyboard focus regression" in result.stderr


def test_v3213_contract_rejects_a_stale_deploy_runbook_database_head(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "docs/sop/06-production-deploy-runbook.md"
    marker = '$APP/venv/bin/python -m alembic current | grep -q "20260824_0016"'
    text = path.read_text(encoding="utf-8")
    assert marker in text
    path.write_text(text.replace(marker, marker.replace("20260824_0016", "20260724_0014"), 1), encoding="utf-8")

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert "production Alembic head gate" in result.stderr


def test_v3212_archive_cannot_satisfy_v3213_package_gate(tmp_path: Path) -> None:
    package = tmp_path / "module-manager-v2-server-3.2.12.zip"
    with ZipFile(package, "w", ZIP_DEFLATED) as archive:
        archive.writestr("SOURCE_COMMIT", "0" * 40 + "\n")
        archive.writestr("RELEASE_MANIFEST.md", "# Release\n\n- Version: 3.2.12\n")

    result = run_verifier(ROOT, "package", package_path=package)

    assert result.returncode == 1
    assert "Version 3.2.13" in result.stderr


def test_pending_v3213_candidate_does_not_pass_attestation() -> None:
    result = run_verifier(ROOT, "attestation")

    assert result.returncode == 1
    assert "attestation requires Status: attested" in result.stderr


def test_complete_v3213_production_attestation_passes(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    write_attested_record(repo)

    result = run_verifier(repo, "attestation")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[OK] V3.2.13 attestation release contract" in result.stdout


@pytest.mark.parametrize(
    ("valid_line", "forged_line", "expected_error"),
    (
        (
            "- Archive file: `build/server-release/module-manager-v2-server-3.2.13.zip`",
            "- Archive file: `build/server-release/module-manager-v2-server-3.2.12.zip`",
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
def test_v3213_attestation_rejects_forged_or_missing_production_evidence(
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


def test_v3213_attestation_rejects_duplicate_sha256(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = write_attested_record(repo)
    with path.open("a", encoding="utf-8") as record:
        record.write(f"\n- SHA256: `{VALID_PACKAGE_SHA256}`\n")

    result = run_verifier(repo, "attestation")

    assert result.returncode == 1
    assert "SHA256" in result.stderr
