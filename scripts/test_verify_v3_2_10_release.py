from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "verify_v3_2_10_release.py"
PRODUCTION_RECORD_SHA256 = "ba333764f85ed83908b2d5a4ed2cf0b4118a623f37328b514474c5d04c253243"


def load_verifier():
    assert VERIFIER_PATH.is_file(), "V3.2.10 release verifier is missing"
    spec = importlib.util.spec_from_file_location("verify_v3_2_10_release", VERIFIER_PATH)
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
        shutil.copy2(source, target)
    return repo


def assert_rejected(repo: Path, expected: str, *, phase: str = "source", package_path: Path | None = None) -> None:
    failures = load_verifier().collect_failures(repo, phase, package_path=package_path)
    assert any(expected in failure for failure in failures), failures


def write_minimal_package(path: Path, *, version: str = "3.2.10", extra: tuple[str, bytes] = ()) -> None:
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("SOURCE_COMMIT", "0" * 40 + "\n")
        archive.writestr("RELEASE_MANIFEST.md", f"# Release\n\n- Version: {version}\n")
        for name, content in extra:
            archive.writestr(name, content)


def test_current_v3210_source_contract_passes() -> None:
    assert load_verifier().collect_failures(ROOT, "source") == []


def test_production_v329_record_is_byte_locked(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "ops/releases/V3.2.9.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nmutated\n", encoding="utf-8")

    assert_rejected(repo, PRODUCTION_RECORD_SHA256)


def test_version_surface_cannot_fall_back_to_v329(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-api/app/main.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace('version="3.2.10"', 'version="3.2.9"'),
        encoding="utf-8",
    )

    assert_rejected(repo, "v2-api/app/main.py")


def test_unified_workbench_source_is_required(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    (repo / "v2-web/src/views/ReviewRephotoWorkbenchView.vue").unlink()

    assert_rejected(repo, "ReviewRephotoWorkbenchView.vue")


def test_unified_workbench_role_and_redirect_markers_are_required(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-web/src/router/index.ts"
    path.write_text(
        path.read_text(encoding="utf-8").replace("/review-workbench", "/removed-workbench"),
        encoding="utf-8",
    )

    assert_rejected(repo, "canonical review workbench routing")


def test_inventory_quagga_first_regressions_are_required(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-web/src/views/__tests__/CollectorInventoryView.spec.ts"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "reuses the construction Quagga scanner before opening a competing native camera stream",
            "removed Quagga-first regression",
        ),
        encoding="utf-8",
    )

    assert_rejected(repo, "V3.2.9 Quagga-first regression")


def test_release_gate_keeps_alembic_at_0016(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace('revision = "20260824_0016"', 'revision = "broken"'),
        encoding="utf-8",
    )

    assert_rejected(repo, "20260824_0016")


def test_pending_candidate_record_fails_attestation() -> None:
    assert_rejected(ROOT, "attestation requires", phase="attestation")


def test_v329_archive_cannot_satisfy_v3210_package_gate(tmp_path: Path) -> None:
    package = tmp_path / "v329.zip"
    write_minimal_package(package, version="3.2.9")

    assert_rejected(ROOT, "3.2.10", phase="package", package_path=package)


def test_package_gate_rejects_protected_uv_lock(tmp_path: Path) -> None:
    package = tmp_path / "uv-lock.zip"
    write_minimal_package(package, extra=(("v2-api/uv.lock", b"forbidden"),))

    assert_rejected(ROOT, "v2-api/uv.lock", phase="package", package_path=package)


def test_invalid_phase_is_rejected() -> None:
    failures = load_verifier().collect_failures(ROOT, "unknown")
    assert failures == ["verification phase must be one of ['attestation', 'package', 'source']"]
