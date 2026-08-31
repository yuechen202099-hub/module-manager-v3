from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "verify_v3_2_24_release.py"
V3223_RECORD_SHA256 = "7a0e8cddc9edcb80f38fc7c490e437242e2bf80029962b17eb3cbbb54840dd09"


def load_script(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v3224_identity_uses_the_attested_v3223_record_as_baseline() -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_24_release")
    assert verifier.VERSION == "3.2.24"
    assert verifier.DEPLOYED_BASELINE == "V3.2.23"
    assert verifier.MAINTENANCE_BRANCH == "production/V3/3.2.24"
    assert verifier.BASELINE_RELEASE_PATH == "ops/releases/V3.2.23.md"
    assert verifier.PRODUCTION_RECORD_SHA256 == V3223_RECORD_SHA256
    assert hashlib.sha256((ROOT / verifier.BASELINE_RELEASE_PATH).read_bytes()).hexdigest() == V3223_RECORD_SHA256


def test_v3224_contract_registers_effective_identity_sync_and_release_gate() -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_24_inputs")
    assert {"ops/releases/V3.2.24.md", "scripts/verify_v3_2_24_release.py", "scripts/test_verify_v3_2_24_release.py"} <= set(verifier.REQUIRED_FILES)
    repository_markers = verifier.V3224_IDENTITY_SYNC_MARKERS["v2-api/app/services/state_repository.py"]
    assert "def _synchronize_data_center_identity_patch(" in repository_markers
    assert '("module_asset_no", "construction_module_asset_no")' in repository_markers


def test_v3224_source_and_sop_gates_accept_the_current_pending_candidate() -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_24_source")
    assert verifier.collect_failures(ROOT, "source") == []
    sop = load_script(ROOT / "scripts" / "verify_release_sop.py", "verify_release_sop_v3224")
    sop.verify_current_release_phase("source", "V3.2.24")
