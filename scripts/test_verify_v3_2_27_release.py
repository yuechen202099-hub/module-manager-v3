from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "verify_v3_2_27_release.py"


def load_script(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v3227_release_contract_covers_material_export_and_migration() -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_27_release_contract")

    assert verifier.VERSION == "3.2.27"
    assert verifier.DEPLOYED_BASELINE == "V3.2.26"
    assert verifier.MAINTENANCE_BRANCH == "production/V3/3.2.27"
    assert verifier.MIGRATION_REVISION == "20260901_0017"
    assert {
        "v2-api/alembic/versions/0017_material_exports.py",
        "v2-api/app/services/material_export.py",
        "v2-web/src/features/materialExport/runner.ts",
        "scripts/verify_material_export_gate.py",
        "ops/releases/V3.2.27.md",
    } <= set(verifier.REQUIRED_FILES)


def test_v3227_current_source_candidate_passes_its_release_contract() -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_27_release_source")

    assert verifier.collect_failures(ROOT, "source") == []


def test_generic_package_verifier_supports_v3227_contract_inputs() -> None:
    generic = load_script(ROOT / "scripts" / "verify-client-release.py", "verify_client_release_v3227")

    required = generic.required_files_for_version("3.2.27")
    assert "scripts/verify_v3_2_27_release.py" in required
    assert "scripts/test_verify_v3_2_27_release.py" in required
    assert "scripts/verify_material_export_gate.py" in required
    assert generic.forbidden_files_for_version("3.2.27") == generic.V3226_RETIRED_BACKGROUND_BARCODE_FILES


def test_release_sop_dispatches_v3227_to_its_versioned_verifier() -> None:
    sop = load_script(ROOT / "scripts" / "verify_release_sop.py", "verify_release_sop_v3227")

    assert "ops/releases/V3.2.27.md" in sop.RELEASE_INPUTS
    sop.verify_current_release_phase("source", "V3.2.27")
