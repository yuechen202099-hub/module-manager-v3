from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "verify_v3_2_20_release.py"
V3219_RECORD_SHA256 = "fc5663e7c5706d218902939064195cd0eaf95289af779d5f87949e0e08916d86"


def load_verifier():
    assert VERIFIER_PATH.is_file(), "V3.2.20 release verifier is missing"
    spec = importlib.util.spec_from_file_location("verify_v3_2_20_release", VERIFIER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_script(name: str, module_name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v3220_release_contract_identity_and_immutable_baseline() -> None:
    verifier = load_verifier()

    assert verifier.VERSION == "3.2.20"
    assert verifier.DISPLAY_VERSION == "V3.2.20"
    assert verifier.DEPLOYED_BASELINE == "V3.2.19"
    assert verifier.MAINTENANCE_BRANCH == "production/V3/3.2.20"
    assert verifier.BASELINE_RELEASE_PATH == "ops/releases/V3.2.19.md"
    assert verifier.RELEASE_PATH == "ops/releases/V3.2.20.md"
    assert verifier.ARCHIVE_PATH == "build/server-release/module-manager-v2-server-3.2.20.zip"
    assert verifier.PRODUCTION_RECORD_SHA256 == V3219_RECORD_SHA256
    assert hashlib.sha256((ROOT / verifier.BASELINE_RELEASE_PATH).read_bytes()).hexdigest() == V3219_RECORD_SHA256


def test_v3220_release_contract_carries_historical_and_current_inputs() -> None:
    verifier = load_verifier()
    required = set(verifier.REQUIRED_FILES)

    assert "ops/releases/V3.2.19.md" in required
    assert "ops/releases/V3.2.20.md" in required
    assert "scripts/verify_v3_2_19_release.py" in required
    assert "scripts/test_verify_v3_2_19_release.py" in required
    assert "scripts/verify_v3_2_20_release.py" in required
    assert "scripts/test_verify_v3_2_20_release.py" in required
    assert "docs/superpowers/plans/2026-08-30-v3-2-20-device-display-hotfix.md" in required


def test_v3220_contract_requires_effective_device_identifier_regressions() -> None:
    verifier = load_verifier()
    markers = {
        path: tuple(values)
        for path, values in verifier.V3220_DEVICE_DISPLAY_MARKERS.items()
    }

    assert "def effective_collector(" in markers["v2-api/app/services/data_center.py"]
    assert "def effective_module_asset_no(" in markers["v2-api/app/services/data_center.py"]
    assert "def test_data_center_anomalies_accept_construction_identifiers_when_source_is_empty()" in markers[
        "v2-api/tests/test_data_center.py"
    ]
    assert "shows only one collector column and one module column" in markers[
        "v2-web/src/views/__tests__/GlobalSearchView.spec.ts"
    ]


def test_v3220_generic_package_contract_extends_v3219_without_rewriting_history() -> None:
    generic = load_script("verify-client-release.py", "verify_client_release_v3220_test")

    assert generic.V3219_CONTRACT_INPUTS < generic.V3220_CONTRACT_INPUTS
    assert generic.required_files_for_version("3.2.19") < generic.required_files_for_version(
        "3.2.20"
    )
    assert generic.required_files_for_version("3.2.20") == frozenset(
        generic.REQUIRED_FILES
    )
    assert callable(generic.verify_v3220_archive_source_contract)


def test_v3220_sop_dispatches_the_new_three_phase_contract() -> None:
    sop = load_script("verify_release_sop.py", "verify_release_sop_v3220_test")

    assert "scripts/verify_v3_2_20_release.py" in sop.RELEASE_INPUTS
    assert "scripts/test_verify_v3_2_20_release.py" in sop.RELEASE_INPUTS
    assert "ops/releases/V3.2.20.md" in sop.RELEASE_INPUTS
    sop.verify_current_release_phase("source", "V3.2.20")


def test_v3220_source_contract_accepts_the_pending_candidate() -> None:
    verifier = load_verifier()

    assert verifier.collect_failures(ROOT, "source") == []


def test_v3220_attestation_requires_current_release_and_v3219_rollback_paths(
    tmp_path: Path,
) -> None:
    verifier = load_verifier()
    package = tmp_path / "module-manager-v2-server-3.2.20.zip"
    package.write_bytes(b"v3.2.20-package")
    package_sha256 = hashlib.sha256(package.read_bytes()).hexdigest()
    source_commit = "a" * 40
    release_path = tmp_path / verifier.RELEASE_PATH
    release_path.parent.mkdir(parents=True)
    exact_fields = {
        **verifier.ATTESTATION_EXACT_FIELDS,
        "Source commit": source_commit,
        "SHA256": package_sha256,
        "Server SHA256": package_sha256,
        "Backup directory": "/opt/module-manager-v2/backups/v3.2.20-20260830T120000Z",
        "Release directory": "/opt/module-manager-v2/releases/v3.2.20-20260830T120100Z",
        "Rollback directory": "/opt/module-manager-v2/releases/v3.2.19-20260830T035812Z",
        "Local health": "HTTP 200 version 3.2.20",
        "Public health": "HTTP 200 version 3.2.20",
        "Browser viewport": "1280x720 passed",
    }
    release_path.write_text(
        "# V3.2.20 Production Release Record\n\n"
        + "\n".join(f"- {field}: `{value}`" for field, value in exact_fields.items())
        + "\n",
        encoding="utf-8",
    )

    failures: list[str] = []
    verifier._check_attestation(tmp_path, package, source_commit, failures)

    assert failures == []
