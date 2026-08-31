from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "verify_v3_2_25_release.py"
V3224_RECORD_SHA256 = "d25448d7e0a1355065b8617371bb35c4a05a1dec03aa11fc4e458cedab06cdb6"


def load_script(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v3225_identity_uses_the_attested_v3224_record_as_baseline() -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_25_release")

    assert verifier.VERSION == "3.2.25"
    assert verifier.DEPLOYED_BASELINE == "V3.2.24"
    assert verifier.MAINTENANCE_BRANCH == "production/V3/3.2.25"
    assert verifier.BASELINE_RELEASE_PATH == "ops/releases/V3.2.24.md"
    assert verifier.PRODUCTION_RECORD_SHA256 == V3224_RECORD_SHA256
    assert hashlib.sha256((ROOT / verifier.BASELINE_RELEASE_PATH).read_bytes()).hexdigest() == V3224_RECORD_SHA256


def test_v3225_contract_registers_retired_collector_photo_exception_guards() -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_25_inputs")

    assert {
        "ops/releases/V3.2.25.md",
        "scripts/verify_v3_2_25_release.py",
        "scripts/test_verify_v3_2_25_release.py",
        "v2-api/scripts/repair_missing_collector_photo_exceptions.py",
        "v2-api/tests/test_miniprogram_api.py",
        "v2-api/tests/test_repair_missing_collector_photo_exceptions.py",
    } <= set(verifier.REQUIRED_FILES)
    assert "v2-api/app/services/local_simulation.py" in verifier.V3225_EXCEPTION_MARKERS
    assert "v2-api/app/services/state_repository.py" in verifier.V3225_EXCEPTION_MARKERS
    assert "v2-api/scripts/repair_missing_collector_photo_exceptions.py" in verifier.V3225_EXCEPTION_MARKERS


def test_v3225_source_and_sop_gates_accept_the_current_pending_candidate() -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_25_source")

    assert verifier.collect_failures(ROOT, "source") == []
    sop = load_script(ROOT / "scripts" / "verify_release_sop.py", "verify_release_sop_v3225")
    sop.verify_current_release_phase("source", "V3.2.25")
