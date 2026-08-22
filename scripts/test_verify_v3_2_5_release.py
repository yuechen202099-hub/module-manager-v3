from __future__ import annotations

import importlib.util
import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = "v2-api/scripts/migrate_external_photos_to_oss.py"
PACKAGING_BRANCH_GUARD = """$sourceBranch = (& git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $sourceBranch -ne "production/V3/3.2.5") {
    throw "Refusing to package branch '$sourceBranch'. Expected production/V3/3.2.5."
}"""


def load_verifier():
    path = ROOT / "scripts" / "verify_v3_2_5_release.py"
    assert path.exists(), "V3.2.5 release verifier is missing"
    spec = importlib.util.spec_from_file_location("verify_v3_2_5_release", path)
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

    def replace(self, relative_path: str, old: str, new: str) -> None:
        source = self.read(relative_path)
        assert old in source, f"fixture marker missing from {relative_path}: {old!r}"
        self.write(relative_path, source.replace(old, new, 1))

    def replace_all(self, relative_path: str, old: str, new: str) -> None:
        source = self.read(relative_path)
        assert old in source, f"fixture marker missing from {relative_path}: {old!r}"
        self.write(relative_path, source.replace(old, new))


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
    release_path = destination / "ops/releases/V3.2.5.md"
    release_path.write_text(
        release_path.read_text(encoding="utf-8")
        .replace("- Local Verification: passed", "- Local Verification: not run", 1)
        .replace("- Package: passed", "- Package: pending", 1),
        encoding="utf-8",
    )
    return TemporaryRepository(destination)


def failures_for(tmp_repo: TemporaryRepository, phase: str = "source") -> list[str]:
    return load_verifier().collect_failures(tmp_repo.root, phase)


def assert_rejected(tmp_repo: TemporaryRepository, marker: str) -> None:
    failures = failures_for(tmp_repo)
    assert any(marker in failure for failure in failures), failures


def test_current_tree_satisfies_v325_contract() -> None:
    assert load_verifier().main(["--phase", "attestation"]) == 0


def test_cli_rejects_unexpected_arguments() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_v3_2_5_release.py"), "--unexpected"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--phase" in result.stderr
    unknown = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_v3_2_5_release.py"), "--phase", "unknown"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert unknown.returncode == 2
    assert "invalid choice" in unknown.stderr


@pytest.mark.parametrize(
    ("relative_path", "old", "new"),
    (
        ("v2-api/app/services/ops_status.py", 'return "3.2.5"', 'return "0.0.0"'),
        ("v2-api/app/main.py", 'version="3.2.5"', 'version="0.0.0"'),
        ("v2-api/pyproject.toml", 'version = "3.2.5"', 'version = "0.0.0"'),
        ("v2-web/package.json", '"version": "3.2.5"', '"version": "0.0.0"'),
        ("v2-web/src/version.json", '"3.2.5"', '"0.0.0"'),
        ("v2-web/index.html", "Module Manager V3.2.5", "Module Manager V0.0.0"),
        ("v2-web/src/components/AppLayout.vue", "V3.2.5", "V0.0.0"),
        ("RELEASE_MANIFEST.md", "- Version: 3.2.5", "- Version: 0.0.0"),
        (
            "scripts/build-client-release.ps1",
            '[string]$Version = "3.2.5"',
            '[string]$Version = "0.0.0"',
        ),
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


def test_release_verifier_rejects_stale_or_rebound_active_v31_version(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.replace(
        "v2-api/scripts/verify_v3_1_release.py",
        'EXPECTED_VERSION = "3.2.5"',
        'EXPECTED_VERSION = "3.2.5"\nEXPECTED_VERSION = "3.2.4"',
    )
    assert_rejected(tmp_repo, "EXPECTED_VERSION must equal 3.2.5")


@pytest.mark.parametrize(
    ("relative_path", "old", "new", "failure"),
    (
        (
            "AGENTS.md",
            "production/V3/3.2.5",
            "production/V3/9.9.9",
            "candidate branch",
        ),
        (
            "AGENTS.md",
            "Deployed production baseline: `V3.2.2`",
            "Deployed production baseline: `V3.2.1`",
            "deployed baseline",
        ),
        (
            "ops/releases/V3.2.5.md",
            "- Package: pending",
            "- Package: passed",
            "Package",
        ),
        (
            "ops/releases/V3.2.5.md",
            "- Rollback target: V3.2.2",
            "- Rollback target: V3.2.4",
            "Rollback target",
        ),
    ),
)
def test_release_verifier_requires_branch_baseline_and_pending_lifecycle(
    tmp_repo: TemporaryRepository,
    relative_path: str,
    old: str,
    new: str,
    failure: str,
) -> None:
    tmp_repo.replace(relative_path, old, new)
    assert_rejected(tmp_repo, failure)


@pytest.mark.parametrize(
    ("field", "expected", "wrong"),
    (
        ("Candidate branch", "`production/V3/3.2.5`", "`production/V3/9.9.9`"),
        ("Deployed production baseline", "`V3.2.2`", "`V3.2.1`"),
        ("Candidate version", "`V3.2.5`", "`V9.9.9`"),
    ),
)
@pytest.mark.parametrize("mutation", ("wrong", "duplicate"))
def test_release_verifier_binds_exact_release_identity_labels_once(
    tmp_repo: TemporaryRepository,
    field: str,
    expected: str,
    wrong: str,
    mutation: str,
) -> None:
    release = tmp_repo.read("ops/releases/V3.2.5.md")
    label = f"- {field}: {expected}"
    assert label in release
    if mutation == "wrong":
        release = release.replace(
            label,
            f"- {field}: {wrong}\n\nExpected identity mentioned elsewhere: {expected}",
            1,
        )
    else:
        release = f"{release.rstrip()}\n{label}\n"
    tmp_repo.write("ops/releases/V3.2.5.md", release)

    assert_rejected(tmp_repo, f"{field} must equal {expected} exactly once")


def test_release_verifier_accepts_exact_packaging_branch_guard() -> None:
    checker = getattr(load_verifier(), "_check_packaging_branch_contract", None)
    assert callable(checker), "V3.2.5 verifier must validate the packaging branch guard"
    failures: list[str] = []

    checker(PACKAGING_BRANCH_GUARD, failures)

    assert failures == []


@pytest.mark.parametrize(
    "mutated_guard",
    (
        PACKAGING_BRANCH_GUARD.replace(
            "$sourceBranch = (& git branch --show-current).Trim()",
            '$sourceBranch = "production/V3/3.2.5"',
        ),
        PACKAGING_BRANCH_GUARD.replace("production/V3/3.2.5", "production/V3/9.9.9"),
    ),
)
def test_release_verifier_rejects_missing_or_wrong_packaging_branch_guard(
    mutated_guard: str,
) -> None:
    checker = getattr(load_verifier(), "_check_packaging_branch_contract", None)
    assert callable(checker), "V3.2.5 verifier must validate the packaging branch guard"
    failures: list[str] = []

    checker(mutated_guard, failures)

    assert any("packaging branch" in failure for failure in failures), failures


@pytest.mark.parametrize(
    "member",
    (
        "scripts/verify_v3_2_5_release.py",
        "scripts/test_verify_v3_2_5_release.py",
        "v2-api/scripts/migrate_external_photos_to_oss.py",
        "v2-api/tests/test_migrate_external_photos_to_oss.py",
        "ops/releases/V3.2.5.md",
    ),
)
def test_release_verifier_requires_v325_package_members(
    tmp_repo: TemporaryRepository,
    member: str,
) -> None:
    tmp_repo.replace("scripts/verify-client-release.py", f'    "{member}",\n', "")
    assert_rejected(tmp_repo, f"required package member missing: {member}")


@pytest.mark.parametrize(
    ("marker", "failure"),
    (
        (
            'Copy-ReleaseItem "scripts\\verify_v3_2_5_release.py" "scripts\\verify_v3_2_5_release.py"\n',
            "package copy",
        ),
        (
            'Copy-ReleaseItem "scripts\\test_verify_v3_2_5_release.py" "scripts\\test_verify_v3_2_5_release.py"\n',
            "package copy",
        ),
        ('    "scripts\\verify_v3_2_5_release.py"\n', "active release gate"),
    ),
)
def test_release_verifier_requires_v325_builder_copies_and_active_gate(
    tmp_repo: TemporaryRepository,
    marker: str,
    failure: str,
) -> None:
    tmp_repo.replace("scripts/build-client-release.ps1", marker, "")
    assert_rejected(tmp_repo, failure)


@pytest.mark.parametrize(
    "marker",
    (
        "v324-external-20260819T233526Z",
        "10 declared_hash_mismatch",
        "uploaded/reused/committed: 0 / 0 / 0",
        "Formula A: 1999",
        "Formula B: 3",
        "arbitrary 64-hex mismatch",
        "locked identity revalidation",
        "canonical downloaded-content SHA256",
        "pre_oss_sha256",
        "no Alembic migration",
        "production reconciled to V3.2.2",
        "zero persistent database/OSS effects",
    ),
)
def test_release_verifier_requires_bounded_repair_evidence_in_record_and_notes(
    tmp_repo: TemporaryRepository,
    marker: str,
) -> None:
    for relative_path in (
        "ops/releases/V3.2.5.md",
        "v2-web/src/constants/releaseNotes.ts",
    ):
        tmp_repo.replace_all(relative_path, marker, "removed bounded-repair evidence")
        assert_rejected(tmp_repo, relative_path)


@pytest.mark.parametrize(
    "marker",
    (
        "--dry-run",
        "--execute",
        "--limit 10",
        "--resume",
        "--rollback-run",
        "400 MiB",
        "250 MiB",
        "512 MiB",
        "单 worker",
        "30 MiB",
        "allowlist",
        "明确批准继续",
        "不删除 OSS",
        "只读 OSS",
    ),
)
def test_release_verifier_keeps_export_sop_stop_and_resource_boundaries(
    tmp_repo: TemporaryRepository,
    marker: str,
) -> None:
    tmp_repo.replace_all(
        "docs/sop/09-export-retirement-and-oss-local-export.md",
        marker,
        "removed operating boundary",
    )
    assert_rejected(tmp_repo, "required operating marker")


def test_release_verifier_requires_v325_operational_identities(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.replace(
        "docs/sop/09-export-retirement-and-oss-local-export.md",
        "v325-external-photo",
        "v324-external-photo",
    )
    assert_rejected(tmp_repo, "V3.2.5 operational identity")


@pytest.mark.parametrize(
    ("old", "new"),
    (
        (
            """            candidate.source_fingerprint,
            candidate.source_url or candidate.url,
            candidate.image_file_id,
            candidate.photo_legacy_id,
""",
            """            candidate.source_fingerprint,
            candidate.source_url or candidate.url,
            candidate.image_file_id,
""",
        ),
        (
            """            candidate.team_id,
            candidate.group_legacy_id,
            candidate.photo_legacy_id,
            candidate.url,
            candidate.image_file_id,
""",
            """            candidate.team_id,
            candidate.group_legacy_id,
            candidate.photo_legacy_id,
            candidate.url,
""",
        ),
    ),
)
def test_release_verifier_requires_exact_historical_formula_inputs(
    tmp_repo: TemporaryRepository,
    old: str,
    new: str,
) -> None:
    tmp_repo.replace(MIGRATION_PATH, old, new)
    assert_rejected(tmp_repo, "historical Formula A/B")


@pytest.mark.parametrize(
    "field_marker",
    (
        '            Photo.legacy_id.label("photo_legacy_id"),\n',
        "            Photo.source_fingerprint,\n",
        "            Photo.source_url,\n",
        "            Photo.image_file_id,\n",
    ),
)
def test_release_verifier_requires_formula_inputs_at_candidate_snapshot_boundary(
    tmp_repo: TemporaryRepository,
    field_marker: str,
) -> None:
    tmp_repo.replace(MIGRATION_PATH, field_marker, "")
    assert_rejected(tmp_repo, "candidate identity snapshot")


@pytest.mark.parametrize(
    ("old", "new"),
    (
        (
            'MaterialGroup.legacy_id.label("group_legacy_id")',
            'Photo.legacy_id.label("group_legacy_id")',
        ),
        (
            'group_legacy_id=str(row.group_legacy_id or "")',
            'group_legacy_id=str(row.photo_legacy_id or "")',
        ),
    ),
)
def test_release_verifier_binds_formula_b_group_legacy_provenance(
    tmp_repo: TemporaryRepository,
    old: str,
    new: str,
) -> None:
    tmp_repo.replace(MIGRATION_PATH, old, new)
    assert_rejected(tmp_repo, "candidate identity snapshot")


def test_release_verifier_keeps_arbitrary_mismatch_rejection(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.replace(
        MIGRATION_PATH,
        '    return "declared_hash_mismatch"\n\n\ndef _oss_error_details',
        '    return "accepted"\n\n\ndef _oss_error_details',
    )
    assert_rejected(tmp_repo, "arbitrary declared-hash mismatch")


@pytest.mark.parametrize(
    "comparison",
    (
        "        and photo.team_id == candidate.team_id\n",
        "        and photo.group_id == candidate.group_id\n",
        '        and str(photo.legacy_id or "") == candidate.photo_legacy_id\n',
        '        and str(photo.image_url or "") == candidate.url\n',
        '        and str(photo.source_url or "") == candidate.source_url\n',
        '        and str(photo.source_fingerprint or "") == candidate.source_fingerprint\n',
        '        and str(photo.image_file_id or "") == candidate.image_file_id\n',
        '        and str(photo.sha256 or "") == candidate.declared_sha256\n',
        "                    or group_legacy_id != candidate.group_legacy_id\n",
    ),
)
def test_release_verifier_requires_every_locked_identity_revalidation(
    tmp_repo: TemporaryRepository,
    comparison: str,
) -> None:
    tmp_repo.replace(MIGRATION_PATH, comparison, "")
    assert_rejected(tmp_repo, "locked identity revalidation")


def test_release_verifier_rejects_group_identity_guard_moved_to_dead_code(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.replace(
        MIGRATION_PATH,
        '''                if (
                    photo is None
                    or group_legacy_id != candidate.group_legacy_id
                    or not _source_still_matches(photo, candidate)
                ):
                    statuses[item_key] = "conflict"
                    continue
''',
        '''                if False and (
                    group_legacy_id != candidate.group_legacy_id
                    or not _source_still_matches(photo, candidate)
                ):
                    statuses[item_key] = "conflict"
                if (
                    photo is None
                    or not _source_still_matches(photo, candidate)
                ):
                    statuses[item_key] = "conflict"
                    continue
''',
    )

    assert_rejected(tmp_repo, "locked identity revalidation")


def test_release_verifier_rejects_group_guard_under_false_constant_comparison(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.replace(
        MIGRATION_PATH,
        '''                if (
                    photo is None
                    or group_legacy_id != candidate.group_legacy_id
                    or not _source_still_matches(photo, candidate)
                ):
                    statuses[item_key] = "conflict"
                    continue
''',
        '''                if 1 == 2:
                    if (
                        photo is None
                        or group_legacy_id != candidate.group_legacy_id
                        or not _source_still_matches(photo, candidate)
                    ):
                        statuses[item_key] = "conflict"
                        continue
                if (
                    photo is None
                    or not _source_still_matches(photo, candidate)
                ):
                    statuses[item_key] = "conflict"
                    continue
''',
    )

    assert_rejected(tmp_repo, "locked identity revalidation")


def test_release_verifier_requires_pre_oss_sha256_preservation(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.replace(
        MIGRATION_PATH,
        '                        "pre_oss_sha256": photo.sha256,',
        '                        "pre_oss_sha256": receipt.sha256,',
    )
    assert_rejected(tmp_repo, "pre_oss_sha256")


@pytest.mark.parametrize(
    ("old", "new"),
    (
        (
            "hash_status = _hash_status(candidate, downloaded.sha256)",
            "hash_status = _hash_status(candidate, candidate.declared_sha256)",
        ),
        (
            '                        f"content{downloaded.suffix}",\n                        downloaded.sha256,',
            '                        f"content{downloaded.suffix}",\n                        candidate.declared_sha256,',
        ),
        (
            "receipt = store_downloaded_photo(bucket, bucket_name, key, downloaded)",
            "receipt = store_downloaded_photo(bucket, bucket_name, key, candidate)",
        ),
        (
            "photo.sha256 = receipt.sha256",
            "photo.sha256 = candidate.declared_sha256",
        ),
    ),
)
def test_release_verifier_requires_canonical_downloaded_content_sha_flow(
    tmp_repo: TemporaryRepository,
    old: str,
    new: str,
) -> None:
    tmp_repo.replace(MIGRATION_PATH, old, new)
    assert_rejected(tmp_repo, "canonical downloaded-content SHA")


@pytest.mark.parametrize(
    ("old", "new"),
    (
        (
            "                    hash_status = _hash_status(candidate, downloaded.sha256)\n",
            '''                    if False:
                        _hash_status(candidate, downloaded.sha256)
                    hash_status = "accepted"
''',
        ),
        (
            "                photo.sha256 = receipt.sha256\n",
            '''                photo.sha256 = candidate.declared_sha256
                if False:
                    photo.sha256 = receipt.sha256
''',
        ),
    ),
)
def test_release_verifier_rejects_canonical_sha_contract_moved_to_dead_code(
    tmp_repo: TemporaryRepository,
    old: str,
    new: str,
) -> None:
    tmp_repo.replace(MIGRATION_PATH, old, new)
    assert_rejected(tmp_repo, "canonical downloaded-content SHA")


@pytest.mark.parametrize(
    ("old", "new"),
    (
        (
            "                    hash_status = _hash_status(candidate, downloaded.sha256)\n",
            '''                    _hash_status = lambda *_args: "accepted"
                    hash_status = _hash_status(candidate, downloaded.sha256)
''',
        ),
        (
            "                    hash_status = _hash_status(candidate, downloaded.sha256)\n",
            '''                    if False:
                        _hash_status = lambda *_args: "accepted"
                    hash_status = _hash_status(candidate, downloaded.sha256)
''',
        ),
        (
            "                    hash_status = _hash_status(candidate, downloaded.sha256)\n",
            '''                    downloaded.sha256 = candidate.declared_sha256
                    hash_status = _hash_status(candidate, downloaded.sha256)
''',
        ),
        (
            "                receipt = transfer.receipt\n",
            '''                receipt = transfer.receipt
                receipt = candidate
''',
        ),
    ),
)
def test_release_verifier_rejects_canonical_sha_name_or_value_rebinding(
    tmp_repo: TemporaryRepository,
    old: str,
    new: str,
) -> None:
    tmp_repo.replace(MIGRATION_PATH, old, new)
    assert_rejected(tmp_repo, "canonical downloaded-content SHA")


def test_release_verifier_rejects_hash_gate_shadowed_by_default_parameter(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.replace(
        MIGRATION_PATH,
        "    bucket: Any,\n    *,\n",
        '''    bucket: Any,
    _hash_status: Any = lambda *_args: "accepted",
    *,
''',
    )

    assert_rejected(tmp_repo, "canonical downloaded-content SHA")


def test_release_verifier_requires_unchanged_migration_head(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.write(
        "v2-api/alembic/versions/0015_v325_forbidden.py",
        'revision = "20260820_0015"\ndown_revision = "20260724_0014"\n',
    )
    assert_rejected(tmp_repo, "migration head must remain 0014")


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def make_attestation_history(
    tmp_path: Path,
    *,
    intermediate_commit: bool = False,
    extra_attestation_path: bool = False,
) -> tuple[Path, str]:
    root = tmp_path / "attestation-repository"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "release-test@example.invalid")
    git(root, "config", "user.name", "Release Test")
    record = root / "ops" / "releases" / "V3.2.5.md"
    record.parent.mkdir(parents=True)
    record.write_text("source record\n", encoding="utf-8")
    git(root, "add", "ops/releases/V3.2.5.md")
    git(root, "commit", "-m", "source")
    source_commit = git(root, "rev-parse", "HEAD")
    if intermediate_commit:
        (root / "README.md").write_text("intermediate\n", encoding="utf-8")
        git(root, "add", "README.md")
        git(root, "commit", "-m", "intermediate")
    record.write_text("attested record\n", encoding="utf-8")
    if extra_attestation_path:
        (root / "application.py").write_text("unexpected drift\n", encoding="utf-8")
        git(root, "add", "application.py")
    git(root, "add", "ops/releases/V3.2.5.md")
    git(root, "commit", "-m", "attestation")
    (root / "scripts").mkdir(exist_ok=True)
    (root / "scripts" / "verify.py").write_text("repair\n", encoding="utf-8")
    git(root, "add", "scripts/verify.py")
    git(root, "commit", "-m", "later verifier-only repair")
    return root, source_commit


def test_attestation_relationship_accepts_real_git_history_with_later_repair(tmp_path: Path) -> None:
    verifier = load_verifier()
    repository, source_commit = make_attestation_history(tmp_path)
    failures: list[str] = []

    attestation_commit = verifier.attestation_commit_for_source(
        repository, source_commit, "ops/releases/V3.2.5.md", failures
    )

    assert failures == []
    assert attestation_commit == git(repository, "rev-parse", "HEAD~1")


@pytest.mark.parametrize(
    ("intermediate_commit", "extra_attestation_path", "failure"),
    (
        (True, False, "immediate child"),
        (False, True, "only change"),
    ),
)
def test_attestation_relationship_rejects_non_immediate_or_drifting_commit(
    tmp_path: Path,
    intermediate_commit: bool,
    extra_attestation_path: bool,
    failure: str,
) -> None:
    verifier = load_verifier()
    repository, source_commit = make_attestation_history(
        tmp_path,
        intermediate_commit=intermediate_commit,
        extra_attestation_path=extra_attestation_path,
    )
    failures: list[str] = []

    verifier.attestation_commit_for_source(
        repository, source_commit, "ops/releases/V3.2.5.md", failures
    )

    assert any(failure in item for item in failures), failures


def test_package_attestation_binds_real_zip_source_size_and_hash(tmp_path: Path) -> None:
    verifier = load_verifier()
    package_path = tmp_path / "package.zip"
    source_commit = "a" * 40
    with zipfile.ZipFile(package_path, "w") as archive:
        archive.writestr("SOURCE_COMMIT", f"{source_commit}\n")
    expected_size = package_path.stat().st_size
    expected_hash = hashlib.sha256(package_path.read_bytes()).hexdigest()

    failures: list[str] = []
    verifier.check_package_attestation(
        package_path, source_commit, expected_size, expected_hash, failures
    )
    assert failures == []

    for expected_source, size, digest, failure in (
        ("b" * 40, expected_size, expected_hash, "embedded source commit"),
        (source_commit, expected_size + 1, expected_hash, "size"),
        (source_commit, expected_size, "0" * 64, "SHA256"),
    ):
        failures = []
        verifier.check_package_attestation(package_path, expected_source, size, digest, failures)
        assert any(failure in item for item in failures), failures


def test_v325_phase_lifecycle_accepts_source_and_attestation_only() -> None:
    verifier = load_verifier()
    attested = (ROOT / "ops" / "releases" / "V3.2.5.md").read_text(encoding="utf-8")
    source = attested.replace("- Local Verification: passed", "- Local Verification: not run", 1).replace(
        "- Package: passed", "- Package: pending", 1
    )

    assert verifier.v325_release_lifecycle_failures(source, "source") == []
    assert verifier.v325_release_lifecycle_failures(attested, "attestation") == []
    assert verifier.v325_release_lifecycle_failures(attested, "source")
    assert verifier.v325_release_lifecycle_failures(source, "attestation")
    for field in ("Production Deployment", "Production Reconciliation"):
        deployed = attested.replace(f"- {field}: pending", f"- {field}: passed", 1)
        assert verifier.v325_release_lifecycle_failures(deployed, "attestation")


def test_packaging_builder_explicitly_selects_source_phase() -> None:
    verifier = load_verifier()
    builder = (ROOT / "scripts" / "build-client-release.ps1").read_text(encoding="utf-8")
    failures: list[str] = []

    verifier.check_packaging_source_phase_contract(builder, failures)
    assert failures == []

    failures = []
    verifier.check_packaging_source_phase_contract(
        builder.replace("--phase source", "--phase attestation", 1),
        failures,
    )
    assert any("--phase source" in failure for failure in failures), failures
