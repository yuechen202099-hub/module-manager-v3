from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "verify_v3_2_28_release.py"
DATA_CENTER_UI_VERIFIER_PATH = ROOT / "scripts" / "verify_v3_2_0_data_center_ui.py"
DASHBOARD_DRILLDOWN_VERIFIER_PATH = ROOT / "scripts" / "verify_v3_2_0_dashboard_drilldown.py"


def load_script(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_source_contract(verifier, destination: Path) -> None:
    required_paths = set(verifier.REQUIRED_FILES) | {
        "AGENTS.md",
        verifier.BASELINE_RELEASE_PATH,
        *verifier.VERSION_SURFACES,
    }
    for relative_path in required_paths:
        source = ROOT / relative_path
        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def test_v3228_release_contract_covers_export_containment() -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_28_release_contract")

    assert verifier.VERSION == "3.2.28"
    assert verifier.DEPLOYED_BASELINE == "V3.2.27"
    assert verifier.MAINTENANCE_BRANCH == "production/V3/3.2.28"
    assert verifier.MIGRATION_REVISION == "20260901_0017"
    assert {
        "v2-api/app/api/routes/material_exports.py",
        "v2-api/tests/test_material_export_api.py",
        "v2-web/src/views/ClaimTasksView.vue",
        "v2-web/src/views/__tests__/ClaimTasksMaterialExport.spec.ts",
        "ops/releases/V3.2.28.md",
    } <= set(verifier.REQUIRED_FILES)


def test_v3228_current_source_candidate_passes_its_release_contract() -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_28_release_source")

    assert verifier.collect_failures(ROOT, "source") == []


def test_data_center_ui_gate_matches_retired_barcode_contract() -> None:
    result = subprocess.run(
        [sys.executable, str(DATA_CENTER_UI_VERIFIER_PATH)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_dashboard_drilldown_gate_matches_retired_barcode_contract() -> None:
    result = subprocess.run(
        [sys.executable, str(DASHBOARD_DRILLDOWN_VERIFIER_PATH)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_v3228_source_contract_rejects_backend_containment_hidden_in_comments(tmp_path: Path) -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_28_backend_mutation")
    candidate = tmp_path / "candidate"
    copy_source_contract(verifier, candidate)
    route_path = candidate / "v2-api/app/api/routes/material_exports.py"
    route = route_path.read_text(encoding="utf-8")
    route = route.replace("MATERIAL_EXPORTS_TEMPORARILY_DISABLED = True", "MATERIAL_EXPORTS_TEMPORARILY_DISABLED = False", 1)
    route = route.replace("if MATERIAL_EXPORTS_TEMPORARILY_DISABLED:", "if False:")
    route += "\n# MATERIAL_EXPORTS_TEMPORARILY_DISABLED = True\n# if MATERIAL_EXPORTS_TEMPORARILY_DISABLED:\n# if MATERIAL_EXPORTS_TEMPORARILY_DISABLED:\n"
    route_path.write_text(route, encoding="utf-8")

    failures = verifier.collect_failures(candidate, "source")

    assert any("server containment" in failure for failure in failures)


def test_v3228_source_contract_rejects_frontend_disable_flag_hidden_in_comment(tmp_path: Path) -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_28_frontend_mutation")
    candidate = tmp_path / "candidate"
    copy_source_contract(verifier, candidate)
    view_path = candidate / "v2-web/src/views/ClaimTasksView.vue"
    view = view_path.read_text(encoding="utf-8")
    view = view.replace(
        "const MATERIAL_EXPORT_ENABLED = false",
        "// const MATERIAL_EXPORT_ENABLED = false\nconst MATERIAL_EXPORT_ENABLED = true",
        1,
    )
    view_path.write_text(view, encoding="utf-8")

    failures = verifier.collect_failures(candidate, "source")

    assert any("task-dispatch export actions" in failure for failure in failures)


def test_v3228_source_contract_rejects_frontend_disable_flag_hidden_in_string(tmp_path: Path) -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_28_frontend_string_mutation")
    candidate = tmp_path / "candidate"
    copy_source_contract(verifier, candidate)
    view_path = candidate / "v2-web/src/views/ClaimTasksView.vue"
    view = view_path.read_text(encoding="utf-8")
    view = view.replace(
        "const MATERIAL_EXPORT_ENABLED = false",
        'const MATERIAL_EXPORT_ENABLED = Boolean(true)\n'
        'const containmentEvidence = "const MATERIAL_EXPORT_ENABLED = false"\n'
        "const templateEvidence = `const MATERIAL_EXPORT_ENABLED = false`",
        1,
    )
    view_path.write_text(view, encoding="utf-8")

    failures = verifier.collect_failures(candidate, "source")

    assert any("task-dispatch export actions" in failure for failure in failures)


def test_v3228_source_contract_rejects_destructuring_and_loop_scope_decoy(tmp_path: Path) -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_28_frontend_scope_mutation")
    candidate = tmp_path / "candidate"
    copy_source_contract(verifier, candidate)
    view_path = candidate / "v2-web/src/views/ClaimTasksView.vue"
    view = view_path.read_text(encoding="utf-8")
    view = view.replace(
        "const MATERIAL_EXPORT_ENABLED = false",
        "const { MATERIAL_EXPORT_ENABLED } = { MATERIAL_EXPORT_ENABLED: true }\n"
        "for (const MATERIAL_EXPORT_ENABLED = false;\nfalse; ) {}",
        1,
    )
    view_path.write_text(view, encoding="utf-8")

    failures = verifier.collect_failures(candidate, "source")

    assert any("task-dispatch export actions" in failure for failure in failures)


def test_generic_package_verifier_supports_v3228_contract_inputs() -> None:
    generic = load_script(ROOT / "scripts" / "verify-client-release.py", "verify_client_release_v3228")

    required = generic.required_files_for_version("3.2.28")
    assert "scripts/verify_v3_2_28_release.py" in required
    assert "scripts/test_verify_v3_2_28_release.py" in required
    assert "ops/releases/V3.2.28.md" in required
    assert generic.forbidden_files_for_version("3.2.28") == generic.V3226_RETIRED_BACKGROUND_BARCODE_FILES


def test_release_sop_dispatches_v3228_to_its_versioned_verifier() -> None:
    sop = load_script(ROOT / "scripts" / "verify_release_sop.py", "verify_release_sop_v3228")

    assert "ops/releases/V3.2.28.md" in sop.RELEASE_INPUTS
    sop.verify_current_release_phase("source", "V3.2.28")
