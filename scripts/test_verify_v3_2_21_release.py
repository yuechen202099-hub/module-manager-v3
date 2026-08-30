from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "verify_v3_2_21_release.py"
V3220_RECORD_SHA256 = "9e9c5d2edd0a0463bdd8744a7d69b937539b1e74916f7ce522b86d31016bef96"


def load_script(path: Path, module_name: str):
    assert path.is_file(), f"missing script: {path.name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v3221_release_contract_identity_and_immutable_baseline() -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_21_release")

    assert verifier.VERSION == "3.2.21"
    assert verifier.DISPLAY_VERSION == "V3.2.21"
    assert verifier.DEPLOYED_BASELINE == "V3.2.20"
    assert verifier.MAINTENANCE_BRANCH == "production/V3/3.2.21"
    assert verifier.BASELINE_RELEASE_PATH == "ops/releases/V3.2.20.md"
    assert verifier.RELEASE_PATH == "ops/releases/V3.2.21.md"
    assert verifier.ARCHIVE_PATH == "build/server-release/module-manager-v2-server-3.2.21.zip"
    assert verifier.PRODUCTION_RECORD_SHA256 == V3220_RECORD_SHA256
    assert hashlib.sha256((ROOT / verifier.BASELINE_RELEASE_PATH).read_bytes()).hexdigest() == V3220_RECORD_SHA256


def test_v3221_contract_registers_bulk_anomaly_approval_and_generic_archive_gate() -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_21_release_inputs")
    required = set(verifier.REQUIRED_FILES)
    expected = {
        "docs/superpowers/specs/2026-08-30-bulk-anomaly-approval.md",
        "docs/superpowers/plans/2026-08-30-bulk-anomaly-approval.md",
        "ops/releases/V3.2.21.md",
        "scripts/verify_v3_2_21_release.py",
        "scripts/test_verify_v3_2_21_release.py",
        "v2-api/tests/test_data_center_review.py",
        "v2-api/tests/test_state_repository.py",
        "v2-web/src/components/__tests__/DataCenterGroupReviewPanel.spec.ts",
    }
    assert expected <= required

    generic = load_script(ROOT / "scripts" / "verify-client-release.py", "verify_client_release_v3221")
    assert generic.V3220_CONTRACT_INPUTS < generic.V3221_CONTRACT_INPUTS
    assert generic.required_files_for_version("3.2.20") < generic.required_files_for_version("3.2.21")
    assert generic.required_files_for_version("3.2.21") == frozenset(
        generic.REQUIRED_FILES | generic.V3221_CONTRACT_INPUTS
    )
    assert callable(generic.verify_v3221_archive_source_contract)


def test_v3221_sop_dispatches_source_contract_and_current_source_passes() -> None:
    sop = load_script(ROOT / "scripts" / "verify_release_sop.py", "verify_release_sop_v3221")
    assert "scripts/verify_v3_2_21_release.py" in sop.RELEASE_INPUTS
    assert "scripts/test_verify_v3_2_21_release.py" in sop.RELEASE_INPUTS
    assert "ops/releases/V3.2.21.md" in sop.RELEASE_INPUTS

    verifier = load_script(VERIFIER_PATH, "verify_v3_2_21_release_source")
    assert verifier.collect_failures(ROOT, "source") == []
    sop.verify_current_release_phase("source", "V3.2.21")


def test_v3221_build_script_is_locked_to_candidate_branch_and_contract() -> None:
    content = (ROOT / "scripts" / "build-client-release.ps1").read_text(encoding="utf-8")
    assert '[string]$Version = "3.2.21"' in content
    assert '$requiredVersion = "3.2.21"' in content
    assert 'production/V3/3.2.21' in content
    assert 'scripts\\verify_v3_2_21_release.py' in content
    assert 'scripts\\test_verify_v3_2_21_release.py' in content


def test_v3221_attestation_uses_candidate_release_and_health_evidence() -> None:
    source = VERIFIER_PATH.read_text(encoding="utf-8")

    assert '"Release directory": r"/opt/module-manager-v2/releases/v3\\.2\\.21-' in source
    assert '"Rollback directory": r"/opt/module-manager-v2/releases/v3\\.2\\.20-' in source
    assert 'r"HTTP\\s+200\\s+version\\s+3\\.2\\.21"' in source
