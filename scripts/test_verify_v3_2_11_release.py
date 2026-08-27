from __future__ import annotations

import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import threading
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "verify_v3_2_11_release.py"
PRODUCTION_RECORD_SHA256 = "46c65deb2edf1500ac1315ab7e3e4bfdba4bcf70a5f3385c3c97b1ce9cc5e2f3"


def load_verifier():
    assert VERIFIER_PATH.is_file(), "V3.2.11 release verifier is missing"
    spec = importlib.util.spec_from_file_location("verify_v3_2_11_release", VERIFIER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_production_health_check():
    path = ROOT / "scripts" / "production_health_check.py"
    spec = importlib.util.spec_from_file_location("production_health_check_v3211", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProductionHealthContractHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.server.seen_paths.append(self.path)  # type: ignore[attr-defined]
        status = 200
        if self.path == "/task-hall":
            status = 307
        elif self.path in {
            "/exports",
            "/exports/terminal-readiness",
            "/local-test/export-manifest/final-delivery",
            "/local-test/photo-barcode/review-groups/export",
            "/local-test/unmatched/export",
        }:
            status = 410
        elif self.path in {"/docs", "/redoc", "/openapi.json"}:
            status = 404
        self.send_response(status)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def copy_contract_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    verifier = load_verifier()
    for relative_path in verifier.REQUIRED_FILES:
        source = ROOT / relative_path
        target = repo / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return repo


def mark_candidate_pending(repo: Path) -> None:
    path = repo / "ops/releases/V3.2.11.md"
    text = path.read_text(encoding="utf-8")
    if "- Status: pending" in text:
        return
    replacements = {
        "- Status: attested": "- Status: pending",
        "- Production Deployment: passed": "- Production Deployment: pending",
        "- Production Reconciliation: passed": "- Production Reconciliation: pending",
    }
    for current, pending in replacements.items():
        assert current in text
        text = text.replace(current, pending, 1)
    path.write_text(text, encoding="utf-8")


def assert_rejected(repo: Path, expected: str, *, phase: str = "source", package_path: Path | None = None) -> None:
    failures = load_verifier().collect_failures(repo, phase, package_path=package_path)
    assert any(expected in failure for failure in failures), failures


def write_minimal_package(path: Path, *, version: str = "3.2.11", extra: tuple[str, bytes] = ()) -> None:
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("SOURCE_COMMIT", "0" * 40 + "\n")
        archive.writestr("RELEASE_MANIFEST.md", f"# Release\n\n- Version: {version}\n")
        for name, content in extra:
            archive.writestr(name, content)


def test_current_v3211_source_contract_passes_for_pending_candidate(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    mark_candidate_pending(repo)

    assert load_verifier().collect_failures(repo, "source") == []


def test_production_v3210_record_is_byte_locked(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "ops/releases/V3.2.10.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nmutated\n", encoding="utf-8")

    assert_rejected(repo, PRODUCTION_RECORD_SHA256)


def test_version_surface_cannot_fall_back_to_v3210(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-api/app/main.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace('version="3.2.11"', 'version="3.2.10"'),
        encoding="utf-8",
    )

    assert_rejected(repo, "v2-api/app/main.py")


def test_unified_workbench_source_is_required(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    (repo / "v2-web/src/views/ReviewRephotoWorkbenchView.vue").unlink()

    assert_rejected(repo, "ReviewRephotoWorkbenchView.vue")


def test_direct_review_workbench_shell_route_is_required(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-api/app/main.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '@app.get("/review-workbench")',
            '# removed direct review workbench shell route',
        ),
        encoding="utf-8",
    )

    assert_rejected(repo, "V3.2.11 unified workbench gate")


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


def test_construction_android_scanner_source_and_regression_test_are_required(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    for relative_path in (
        "v2-web/src/views/ConstructionView.vue",
        "v2-web/src/views/__tests__/ConstructionScannerAndroid.spec.ts",
    ):
        target = repo / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative_path, target)
    (repo / "v2-web/src/views/ConstructionView.vue").unlink()
    (repo / "v2-web/src/views/__tests__/ConstructionScannerAndroid.spec.ts").unlink()

    failures = load_verifier().collect_failures(repo, "source")

    assert any("ConstructionView.vue" in failure for failure in failures)
    assert any("ConstructionScannerAndroid.spec.ts" in failure for failure in failures)


def test_construction_android_scanner_contract_rejects_tampered_fallback_markers(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-web/src/views/ConstructionView.vue"
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "v2-web/src/views/ConstructionView.vue", path)
    path.write_text(
        path.read_text(encoding="utf-8").replace("decodeFromConstraints", "removedAndroidFallback"),
        encoding="utf-8",
    )

    assert_rejected(repo, "V3.2.11 Android scanner fallback gate")


def test_production_health_check_probes_construction_scanner_runtime(monkeypatch) -> None:
    health_check = load_production_health_check()
    server = ThreadingHTTPServer(("127.0.0.1", 0), ProductionHealthContractHandler)
    server.seen_paths = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(
        health_check.sys,
        "argv",
        [
            "production_health_check.py",
            "--base-url",
            f"http://127.0.0.1:{server.server_port}",
            "--expected-version",
            "3.2.11",
            "--skip-admin",
        ],
    )
    try:
        assert health_check.main() == 0
        assert server.seen_paths.count("/static/vendor/quagga.min.js") == 1  # type: ignore[attr-defined]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_release_gate_requires_nginx_traversable_release_root(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    source = ROOT / "docs/sop/06-production-deploy-runbook.md"
    target = repo / "docs/sop/06-production-deploy-runbook.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        source.read_text(encoding="utf-8").replace('chmod 0751 "$REL"', 'chmod 0750 "$REL"'),
        encoding="utf-8",
    )

    assert_rejected(repo, "Nginx static runtime traversal gate")


def test_release_gate_keeps_alembic_at_0016(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    path = repo / "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace('revision = "20260824_0016"', 'revision = "broken"'),
        encoding="utf-8",
    )

    assert_rejected(repo, "20260824_0016")


def test_pending_candidate_record_fails_attestation(tmp_path: Path) -> None:
    repo = copy_contract_repo(tmp_path)
    mark_candidate_pending(repo)

    assert_rejected(repo, "attestation requires", phase="attestation")


def test_pending_candidate_record_does_not_pass_attestation() -> None:
    failures = load_verifier().collect_failures(ROOT, "attestation")
    assert any("attestation requires Status: attested" in failure for failure in failures)


def test_v3210_archive_cannot_satisfy_v3211_package_gate(tmp_path: Path) -> None:
    package = tmp_path / "v3210.zip"
    write_minimal_package(package, version="3.2.10")

    assert_rejected(ROOT, "3.2.11", phase="package", package_path=package)


def test_package_gate_rejects_protected_uv_lock(tmp_path: Path) -> None:
    package = tmp_path / "uv-lock.zip"
    write_minimal_package(package, extra=(("v2-api/uv.lock", b"forbidden"),))

    assert_rejected(ROOT, "v2-api/uv.lock", phase="package", package_path=package)


def test_invalid_phase_is_rejected() -> None:
    failures = load_verifier().collect_failures(ROOT, "unknown")
    assert failures == ["verification phase must be one of ['attestation', 'package', 'source']"]
