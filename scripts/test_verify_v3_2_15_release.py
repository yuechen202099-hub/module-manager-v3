from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile

import pytest


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "verify_v3_2_15_release.py"
V3214_PRODUCTION_RECORD_SHA256 = (
    "5a6fe4a2daa700e1340fb218dc202e3c8e21d52c500b077f86adfe1ad431be7d"
)
VALID_SOURCE_COMMIT = "1" * 40
VALID_PACKAGE_SHA256 = "a" * 64


def load_verifier():
    assert VERIFIER_PATH.is_file(), "V3.2.15 release verifier is missing"
    spec = importlib.util.spec_from_file_location("verify_v3_2_15_release", VERIFIER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_verifier(
    root: Path,
    phase: str,
    *,
    package_path: Path | None = None,
    expected_source_commit: str | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(root / "scripts" / "verify_v3_2_15_release.py"), "--phase", phase]
    if package_path is not None:
        command.extend(("--package", str(package_path)))
    if expected_source_commit is not None:
        command.extend(("--expected-source-commit", expected_source_commit))
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
    migration_source = ROOT / "v2-api/alembic/versions"
    migration_target = repo / "v2-api/alembic/versions"
    migration_target.mkdir(parents=True, exist_ok=True)
    for source in migration_source.glob("*.py"):
        shutil.copy2(source, migration_target / source.name)
    return repo


def write_attested_record(
    repo: Path,
    *,
    source_commit: str = VALID_SOURCE_COMMIT,
    package_sha256: str = VALID_PACKAGE_SHA256,
) -> Path:
    path = repo / "ops/releases/V3.2.15.md"
    text = path.read_text(encoding="utf-8")
    replacements = {
        "- Status: pending": "- Status: attested",
        "- Local Verification: pending": "- Local Verification: passed",
        "- Package: pending": "- Package: passed",
        "- Production Deployment: pending": "- Production Deployment: passed",
        "- Production Reconciliation: pending": "- Production Reconciliation: passed",
        "- Archive file: pending": (
            "- Archive file: `build/server-release/module-manager-v2-server-3.2.15.zip`"
        ),
        "- Source verifier tests: pending": "- Source verifier tests: passed",
        "- Generic client-package verifier tests: pending": (
            "- Generic client-package verifier tests: passed"
        ),
        "- SOP verifier tests: pending": "- SOP verifier tests: passed",
        "- Source phase: pending": "- Source phase: passed",
        "- SOP source phase: pending": "- SOP source phase: passed",
        "- Git diff check: pending": "- Git diff check: passed",
        "- SHA256: pending": f"- SHA256: `{package_sha256}`",
        "- Server SHA256: pending": f"- Server SHA256: `{package_sha256}`",
        "- Source commit: pending": f"- Source commit: `{source_commit}`",
        "- Build command: pending": "- Build command: passed",
        "- Archive verification result: pending": "- Archive verification result: passed",
        "- Backup verification: pending": "- Backup verification: passed",
        "- Uvicorn readiness: pending": "- Uvicorn readiness: `127.0.0.1:8000 ready`",
        "- Authorization acceptance: pending": "- Authorization acceptance: passed",
        "- Zero-write acceptance: pending": "- Zero-write acceptance: passed",
        "- Camera requests: pending": "- Camera requests: `0`",
        "- Client-platform requests: pending": "- Client-platform requests: `0`",
        "- Maintenance restoration: pending": "- Maintenance restoration: passed",
        "- Soak health checks: pending": "- Soak health checks: passed",
        "- Attestation: pending": "- Attestation: passed",
        "- Backup directory: pending": "- Backup directory: `/opt/module-manager-v2/backups/v3.2.15-20260828T010000Z`",
        "- Release directory: pending": "- Release directory: `/opt/module-manager-v2/releases/v3.2.15-20260828T010000Z`",
        "- Rollback directory: pending": "- Rollback directory: `/opt/module-manager-v2/releases/v3.2.14-20260828T113306Z`",
        "- Local health: pending": "- Local health: `HTTP 200 version 3.2.15`",
        "- Public health: pending": "- Public health: `HTTP 200 version 3.2.15`",
        "- Browser viewport: pending": "- Browser viewport: `390x844 passed`",
    }
    for pending, attested in replacements.items():
        if pending in text:
            text = text.replace(pending, attested, 1)
        else:
            assert attested in text
    path.write_text(text, encoding="utf-8")
    return path


def load_generic_test_helpers():
    path = ROOT / "scripts" / "test_verify_client_release.py"
    spec = importlib.util.spec_from_file_location("v3215_generic_test_helpers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rewrite_archive_member(archive_path: Path, member_name: str, content: bytes) -> None:
    rewritten = archive_path.with_name(archive_path.stem + "-rewritten.zip")
    with ZipFile(archive_path) as source, ZipFile(rewritten, "w", ZIP_DEFLATED) as target:
        found = False
        for info in source.infolist():
            payload = source.read(info.filename)
            if info.filename == member_name:
                payload = content
                found = True
            target.writestr(info, payload)
        if not found:
            target.writestr(member_name, content)
    rewritten.replace(archive_path)


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


@pytest.fixture(scope="module")
def attestation_template(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, str, str]:
    template_root = tmp_path_factory.mktemp("v3215-attestation-template")
    helpers = load_generic_test_helpers()
    package_verifier = helpers.load_verifier()
    package_path = template_root / "module-manager-v2-server-3.2.15.zip"
    helpers.write_release_archive(
        package_verifier,
        package_path,
        source_commit="0" * 40,
        release_record=(ROOT / "ops/releases/V3.2.15.md").read_text(encoding="utf-8"),
        content_overrides={
            path.relative_to(ROOT).as_posix(): path.read_bytes()
            for path in (ROOT / "v2-api/alembic/versions").glob("*.py")
        },
    )

    repo = template_root / "repo"
    repo.mkdir()
    with ZipFile(package_path) as archive:
        archive.extractall(repo)
    (repo / "SOURCE_COMMIT").unlink()
    run_git(repo, "init")
    run_git(repo, "config", "user.email", "release-test@example.invalid")
    run_git(repo, "config", "user.name", "Release Test")
    run_git(repo, "config", "core.autocrlf", "false")
    run_git(repo, "add", "-f", "--", ".")
    run_git(repo, "commit", "-m", "test source")
    source_commit = run_git(repo, "rev-parse", "HEAD")
    rewrite_archive_member(package_path, "SOURCE_COMMIT", f"{source_commit}\n".encode("ascii"))
    package_sha256 = hashlib.sha256(package_path.read_bytes()).hexdigest()
    return repo, package_path, source_commit, package_sha256


@pytest.fixture
def valid_attestation_context(
    tmp_path: Path,
    attestation_template: tuple[Path, Path, str, str],
) -> tuple[Path, Path, str]:
    template_repo, template_package, source_commit, package_sha256 = attestation_template
    repo = tmp_path / "repo"
    shutil.copytree(template_repo, repo)
    package_path = tmp_path / template_package.name
    shutil.copy2(template_package, package_path)
    write_attested_record(
        repo,
        source_commit=source_commit,
        package_sha256=package_sha256,
    )
    return repo, package_path, source_commit


def test_current_v3215_source_contract_executes_for_pending_candidate() -> None:
    result = run_verifier(ROOT, "source")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[OK] V3.2.15 source release contract" in result.stdout


def test_v3214_production_record_is_byte_locked(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "ops/releases/V3.2.14.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nmutated\n", encoding="utf-8")

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert V3214_PRODUCTION_RECORD_SHA256 in result.stderr


def test_v3215_contract_rejects_review_lock_regression(tmp_path: Path) -> None:
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


def test_v3215_contract_rejects_missing_original_photo_preview(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-web/src/components/data-center/DataCenterGroupReviewPanel.vue"
    marker = "fetchGroupPhotoObjectUrl(groupId, photo.id, 'original'"
    text = path.read_text(encoding="utf-8")
    assert marker in text
    path.write_text(text.replace(marker, "removed_original_photo_preview(", 1), encoding="utf-8")

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert "protected original-photo preview" in result.stderr


def test_v3215_contract_rejects_lightbox_without_focus_restoration(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-web/src/components/PhotoLightbox.vue"
    marker = "if (previousFocus?.isConnected) previousFocus.focus()"
    text = path.read_text(encoding="utf-8")
    assert marker in text
    path.write_text(text.replace(marker, "// removed focus restoration", 1), encoding="utf-8")

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert "lightbox keyboard focus" in result.stderr


def test_v3215_contract_requires_lightbox_focus_regression_test(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-web/src/components/__tests__/PhotoLightbox.spec.ts"
    if path.exists():
        path.unlink()

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert "lightbox keyboard focus regression" in result.stderr


def test_v3215_contract_rejects_a_stale_deploy_runbook_database_head(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "docs/sop/06-production-deploy-runbook.md"
    marker = '$APP/venv/bin/python -m alembic current | grep -q "20260824_0016"'
    text = path.read_text(encoding="utf-8")
    assert marker in text
    path.write_text(text.replace(marker, marker.replace("20260824_0016", "20260724_0014"), 1), encoding="utf-8")

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert "production Alembic head gate" in result.stderr


def test_v3214_archive_cannot_satisfy_v3215_package_gate(tmp_path: Path) -> None:
    package = tmp_path / "module-manager-v2-server-3.2.14.zip"
    with ZipFile(package, "w", ZIP_DEFLATED) as archive:
        archive.writestr("SOURCE_COMMIT", "0" * 40 + "\n")
        archive.writestr("RELEASE_MANIFEST.md", "# Release\n\n- Version: 3.2.14\n")

    result = run_verifier(
        ROOT,
        "package",
        package_path=package,
        expected_source_commit="0" * 40,
    )

    assert result.returncode == 1
    assert "Version 3.2.15" in result.stderr


def test_pending_v3215_candidate_does_not_pass_attestation() -> None:
    result = run_verifier(ROOT, "attestation")

    assert result.returncode == 1
    assert "attestation requires Status: attested" in result.stderr


def test_complete_v3215_production_attestation_passes(
    valid_attestation_context: tuple[Path, Path, str],
) -> None:
    repo, package_path, source_commit = valid_attestation_context

    result = run_verifier(
        repo,
        "attestation",
        package_path=package_path,
        expected_source_commit=source_commit,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[OK] V3.2.15 attestation release contract" in result.stdout


@pytest.mark.parametrize(
    ("valid_line", "forged_line", "expected_error"),
    (
        (
            "- Archive file: `build/server-release/module-manager-v2-server-3.2.15.zip`",
            "- Archive file: `build/server-release/module-manager-v2-server-3.2.14.zip`",
            "Archive file",
        ),
        (
            "- Backup verification: passed",
            "- Backup verification: pending",
            "Backup verification",
        ),
        (
            "- Browser viewport: `390x844 passed`",
            "- Browser viewport: `not-a-viewport`",
            "Browser viewport",
        ),
        (
            "- Source verifier tests: passed",
            "- Source verifier tests: pending",
            "Source verifier tests",
        ),
        (
            "- Build command: passed",
            "- Build command: pending",
            "Build command",
        ),
        (
            "- Archive verification result: passed",
            "- Archive verification result: failed",
            "Archive verification result",
        ),
        (
            "- Backup directory: `/opt/module-manager-v2/backups/v3.2.15-20260828T010000Z`",
            "- Backup directory: `C:/arbitrary/non-pending`",
            "Backup directory",
        ),
        (
            "- Release directory: `/opt/module-manager-v2/releases/v3.2.15-20260828T010000Z`",
            "- Release directory: `/tmp/arbitrary-release`",
            "Release directory",
        ),
        (
            "- Rollback directory: `/opt/module-manager-v2/releases/v3.2.14-20260828T113306Z`",
            "- Rollback directory: `/opt/module-manager-v2/releases/v3.2.15-wrong`",
            "Rollback directory",
        ),
        (
            "- Local health: `HTTP 200 version 3.2.15`",
            "- Local health: `failed`",
            "Local health",
        ),
        (
            "- Public health: `HTTP 200 version 3.2.15`",
            "- Public health: `HTTP 500 version 3.2.15`",
            "Public health",
        ),
    ),
)
def test_v3215_attestation_rejects_forged_or_missing_production_evidence(
    valid_attestation_context: tuple[Path, Path, str],
    valid_line: str,
    forged_line: str,
    expected_error: str,
) -> None:
    repo, package_path, source_commit = valid_attestation_context
    path = repo / "ops/releases/V3.2.15.md"
    text = path.read_text(encoding="utf-8")
    assert valid_line in text
    path.write_text(text.replace(valid_line, forged_line, 1), encoding="utf-8")

    result = run_verifier(
        repo,
        "attestation",
        package_path=package_path,
        expected_source_commit=source_commit,
    )

    assert result.returncode == 1
    assert expected_error in result.stderr


@pytest.mark.parametrize(
    ("field", "replacement", "expected_error"),
    (
        ("Source commit", "1" * 39, "Source commit"),
        ("SHA256", "f" * 64, "package SHA256"),
        ("Server SHA256", "e" * 64, "Server SHA256"),
    ),
)
def test_v3215_attestation_binds_commit_and_hashes_to_the_verified_package(
    valid_attestation_context: tuple[Path, Path, str],
    field: str,
    replacement: str,
    expected_error: str,
) -> None:
    repo, package_path, source_commit = valid_attestation_context
    path = repo / "ops/releases/V3.2.15.md"
    text = path.read_text(encoding="utf-8")
    values = [line for line in text.splitlines() if line.startswith(f"- {field}:")]
    assert len(values) == 1
    path.write_text(
        text.replace(values[0], f"- {field}: `{replacement}`", 1),
        encoding="utf-8",
    )

    result = run_verifier(
        repo,
        "attestation",
        package_path=package_path,
        expected_source_commit=source_commit,
    )

    assert result.returncode == 1
    assert expected_error in result.stderr


def test_v3215_attestation_rejects_duplicate_sha256(
    valid_attestation_context: tuple[Path, Path, str],
) -> None:
    repo, package_path, source_commit = valid_attestation_context
    path = repo / "ops/releases/V3.2.15.md"
    with path.open("a", encoding="utf-8") as record:
        record.write(f"\n- SHA256: `{VALID_PACKAGE_SHA256}`\n")

    result = run_verifier(
        repo,
        "attestation",
        package_path=package_path,
        expected_source_commit=source_commit,
    )

    assert result.returncode == 1
    assert "SHA256" in result.stderr


def test_v3215_package_phase_requires_an_expected_source_commit(
    attestation_template: tuple[Path, Path, str, str],
) -> None:
    repo, package_path, _, _ = attestation_template

    result = run_verifier(repo, "package", package_path=package_path)

    assert result.returncode == 1
    assert "--expected-source-commit" in result.stderr


@pytest.mark.parametrize(
    ("member_name", "replacement", "expected_error"),
    (
        ("README.md", b"tampered tracked bytes\n", "bytes do not match SOURCE_COMMIT"),
        ("debug/untracked.txt", b"untracked member\n", "not tracked by SOURCE_COMMIT"),
    ),
)
def test_v3215_package_wrapper_rejects_source_unbound_members(
    tmp_path: Path,
    attestation_template: tuple[Path, Path, str, str],
    member_name: str,
    replacement: bytes,
    expected_error: str,
) -> None:
    template_repo, template_package, source_commit, _ = attestation_template
    repo = tmp_path / "repo"
    shutil.copytree(template_repo, repo)
    package_path = tmp_path / template_package.name
    shutil.copy2(template_package, package_path)
    rewrite_archive_member(package_path, member_name, replacement)

    result = run_verifier(
        repo,
        "package",
        package_path=package_path,
        expected_source_commit=source_commit,
    )

    assert result.returncode == 1
    assert expected_error in result.stderr


@pytest.mark.parametrize(
    "member_name",
    (
        "nested/payload.zip",
        "nested/secrets/token.txt",
        "nested/backups/database.bin",
        "nested/uv.lock",
    ),
)
def test_v3215_package_wrapper_rejects_nested_release_artifacts(
    tmp_path: Path,
    attestation_template: tuple[Path, Path, str, str],
    member_name: str,
) -> None:
    template_repo, template_package, source_commit, _ = attestation_template
    repo = tmp_path / "repo"
    shutil.copytree(template_repo, repo)
    package_path = tmp_path / template_package.name
    shutil.copy2(template_package, package_path)
    rewrite_archive_member(package_path, member_name, b"must not ship\n")

    result = run_verifier(
        repo,
        "package",
        package_path=package_path,
        expected_source_commit=source_commit,
    )

    assert result.returncode == 1
    assert f"forbidden archive member: {member_name}" in result.stderr


def test_v3215_source_rejects_duplicate_alembic_revision_ids(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    duplicate = repo / "v2-api/alembic/versions/0099_duplicate_revision.py"
    duplicate.write_text(
        'revision = "20260824_0016"\n'
        'down_revision = "20260823_0015"\n',
        encoding="utf-8",
    )

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert "duplicate Alembic revision" in result.stderr


def test_v3215_source_rejects_metadata_less_alembic_files(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    migration = repo / "v2-api/alembic/versions/0099_metadata_less.py"
    migration.write_text("def upgrade():\n    pass\n", encoding="utf-8")

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert "valid revision and down_revision metadata" in result.stderr


def test_v3215_source_rejects_an_approved_migration_under_the_wrong_filename(
    tmp_path: Path,
) -> None:
    repo = copy_contract_repo(tmp_path)
    original = repo / "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py"
    renamed = original.with_name("0016_renamed.py")
    original.rename(renamed)

    result = run_verifier(repo, "source")

    assert result.returncode == 1
    assert "approved Alembic file chain" in result.stderr



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
            "v2-api/tests/test_collector_transfer_api.py",
            "def test_manual_collector_demand_enforces_the_operational_quantity_limit(",
            "Task 2 manual demand API quantity-limit regression",
        ),
        (
            "v2-api/tests/test_collector_transfer_service.py",
            "def test_manual_demand_rejects_oversized_quantity_before_terminal_locking(",
            "Task 2 manual demand service quantity-limit regression",
        ),
        (
            "v2-api/tests/test_collector_transfer_service.py",
            "def test_global_terminal_detail_reuses_authorized_source_photo_for_present_collector(",
            "Task 3 present collector source-photo regression",
        ),
        (
            "v2-api/tests/test_collector_transfer_service.py",
            "row[\"source_group_id\"]",
            "Task 4 stable meter group identity regression",
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
        (
            "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
            "keeps every incomplete manual-demand collector visible by requirement identity",
            "Task 4 manual demand identity regression",
        ),
        (
            "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
            "hides only the completed group when sibling meters share a display number",
            "Task 4 stable meter group UI regression",
        ),
    ),
)


def test_v3215_contract_requires_task_1_through_4_regression_markers(
    tmp_path: Path,
    relative_path: str,
    marker: str,
    label: str,
) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / relative_path
    text = path.read_text(encoding="utf-8")
    assert marker in text
    path.write_text(text.replace(marker, "removed_required_v3215_regression", 1), encoding="utf-8")

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


def test_v3215_contract_preserves_v3213_scanner_and_rephoto_markers(
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
