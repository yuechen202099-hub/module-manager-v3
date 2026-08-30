from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "verify_v3_2_23_release.py"
V3222_RECORD_SHA256 = "4dd469d7124ee41e11a21076fb4a75369a032bbbb1e5629e546c3753bdc71069"


def load_script(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v3223_identity_uses_the_attested_v3222_record_as_baseline() -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_23_release")
    assert verifier.VERSION == "3.2.23"
    assert verifier.DEPLOYED_BASELINE == "V3.2.22"
    assert verifier.MAINTENANCE_BRANCH == "production/V3/3.2.23"
    assert verifier.BASELINE_RELEASE_PATH == "ops/releases/V3.2.22.md"
    assert verifier.PRODUCTION_RECORD_SHA256 == V3222_RECORD_SHA256
    assert hashlib.sha256((ROOT / verifier.BASELINE_RELEASE_PATH).read_bytes()).hexdigest() == V3222_RECORD_SHA256


def test_v3223_contract_registers_data_center_photo_workflow_and_release_gate() -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_23_inputs")
    assert {"ops/releases/V3.2.23.md", "scripts/verify_v3_2_23_release.py", "scripts/test_verify_v3_2_23_release.py"} <= set(verifier.REQUIRED_FILES)
    panel_markers = verifier.V3223_DATA_CENTER_MARKERS["v2-web/src/components/data-center/DataCenterGroupReviewPanel.vue"]
    assert "async function saveReview()" in panel_markers
    assert "上传替换" in panel_markers
    assert "删除照片" in panel_markers


def test_v3223_source_and_sop_gates_accept_the_current_pending_candidate() -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_23_source")
    assert verifier.collect_failures(ROOT, "source") == []
    sop = load_script(ROOT / "scripts" / "verify_release_sop.py", "verify_release_sop_v3223")
    sop.verify_current_release_phase("source", "V3.2.23")
