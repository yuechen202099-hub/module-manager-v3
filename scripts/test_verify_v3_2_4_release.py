from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_verifier():
    path = ROOT / "scripts" / "verify_v3_2_4_release.py"
    assert path.exists(), "V3.2.4 release verifier is missing"
    spec = importlib.util.spec_from_file_location("verify_v3_2_4_release", path)
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


def test_current_tree_satisfies_v324_contract() -> None:
    assert load_verifier().main([]) == 0


@pytest.mark.parametrize(
    ("relative_path", "old", "new"),
    (
        ("v2-api/app/services/ops_status.py", 'return "3.2.4"', 'return "0.0.0"'),
        ("v2-api/app/main.py", 'version="3.2.4"', 'version="0.0.0"'),
        ("v2-api/pyproject.toml", 'version = "3.2.4"', 'version = "0.0.0"'),
        ("v2-web/package.json", '"version": "3.2.4"', '"version": "0.0.0"'),
        ("v2-web/src/version.json", '"3.2.4"', '"0.0.0"'),
        ("v2-web/index.html", "Module Manager V3.2.4", "Module Manager V0.0.0"),
        ("v2-web/src/components/AppLayout.vue", "V3.2.4", "V0.0.0"),
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


def test_release_verifier_rejects_legacy_https_handler_keyword(
    tmp_repo: TemporaryRepository,
) -> None:
    tmp_repo.replace(
        "v2-api/app/services/photo_storage.py",
        "            context=self._context,\n",
        "            context=self._context,\n            check_hostname=self._check_hostname,\n",
    )
    assert_rejected(tmp_repo, "_check_hostname")


@pytest.mark.parametrize(
    ("relative_path", "marker", "failure"),
    (
        (
            "scripts/verify-client-release.py",
            '    "scripts/verify_v3_2_4_release.py",\n',
            "required package member",
        ),
        (
            "scripts/build-client-release.ps1",
            'Copy-ReleaseItem "scripts\\verify_v3_2_4_release.py" "scripts\\verify_v3_2_4_release.py"\n',
            "package copy",
        ),
        (
            "scripts/build-client-release.ps1",
            '    "scripts\\verify_v3_2_4_release.py"\n',
            "release gate",
        ),
    ),
)
def test_release_verifier_requires_v324_package_and_gate_references(
    tmp_repo: TemporaryRepository,
    relative_path: str,
    marker: str,
    failure: str,
) -> None:
    tmp_repo.replace(relative_path, marker, "")
    assert_rejected(tmp_repo, failure)


@pytest.mark.parametrize(
    ("marker", "failure"),
    (
        ("'_PinnedHTTPSHandler' object has no attribute '_check_hostname'", "root cause"),
        ("zero-write", "zero-write"),
        ("Application rollback: V3.2.2 restored", "application rollback"),
    ),
)
def test_release_verifier_requires_failed_trial_and_rollback_evidence(
    tmp_repo: TemporaryRepository,
    marker: str,
    failure: str,
) -> None:
    tmp_repo.replace("ops/releases/V3.2.4.md", marker, "missing evidence")
    assert_rejected(tmp_repo, failure)
