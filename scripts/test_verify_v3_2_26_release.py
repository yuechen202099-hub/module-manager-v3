from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "verify_v3_2_26_release.py"
V3225_RECORD_SHA256 = "74e8bafeaf919e57cd012f6f0f01753979231bb446a99265c5ec2185ad83de10"


def load_script(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v3226_identity_uses_the_attested_v3225_record_as_baseline() -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_26_release")

    assert verifier.VERSION == "3.2.26"
    assert verifier.DEPLOYED_BASELINE == "V3.2.25"
    assert verifier.MAINTENANCE_BRANCH == "production/V3/3.2.26"
    assert verifier.BASELINE_RELEASE_PATH == "ops/releases/V3.2.25.md"
    assert verifier.PRODUCTION_RECORD_SHA256 == V3225_RECORD_SHA256
    assert hashlib.sha256((ROOT / verifier.BASELINE_RELEASE_PATH).read_bytes()).hexdigest() == V3225_RECORD_SHA256


def test_v3226_contract_registers_collector_missing_exception_guards() -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_26_inputs")

    assert {
        "ops/releases/V3.2.26.md",
        "scripts/verify_v3_2_26_release.py",
        "scripts/test_verify_v3_2_26_release.py",
        "v2-api/tests/test_v21_data_rules.py",
    } <= set(verifier.REQUIRED_FILES)
    assert "v2-api/app/services/data_center.py" in verifier.V3226_EXCEPTION_MARKERS
    assert "v2-api/app/services/state_repository.py" in verifier.V3226_EXCEPTION_MARKERS
    assert "v2-api/tests/test_collector_transfer_service.py" in verifier.V3226_EXCEPTION_MARKERS


def test_v3226_contract_registers_background_barcode_retirement_guards() -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_26_retirement_inputs")

    assert {
        "v2-api/app/api/router.py",
        "v2-api/app/main.py",
        "v2-api/tests/test_api.py",
        "docs/sop/06-production-deploy-runbook.md",
        "docs/sop/07-rollback-and-incident-review.md",
        "scripts/build-client-release.ps1",
        "scripts/verify-client-release.py",
    } <= set(verifier.V3226_BACKGROUND_BARCODE_RETIREMENT_MARKERS)


def test_v3226_source_gate_rejects_a_registered_background_barcode_route(tmp_path) -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_26_retirement_route")
    root = tmp_path / "source"
    router = root / "v2-api" / "app" / "api" / "router.py"
    router.parent.mkdir(parents=True)
    router.write_text(
        "from app.api.routes import barcode_maintenance\n"
        "api_router.include_router(barcode_maintenance.router)\n",
        encoding="utf-8",
    )

    failures: list[str] = []
    verifier._check_background_barcode_retirement(root, failures)

    assert any("background barcode maintenance route is still registered" in failure for failure in failures)


def test_v3226_source_gate_rejects_fail_open_or_late_retirement_sop(tmp_path) -> None:
    """Catches deployment guidance swallowing stop failures or checking units after migration."""
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_26_retirement_sop")
    root = tmp_path / "source"
    for relative_path in verifier.V3226_BACKGROUND_BARCODE_RETIREMENT_MARKERS:
        source = ROOT / relative_path
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for relative_path in (
        "v2-api/app/api/router.py",
        "v2-api/app/main.py",
        "docs/sop/07-rollback-and-incident-review.md",
    ):
        source = ROOT / relative_path
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    runbook = root / "docs/sop/06-production-deploy-runbook.md"
    unsafe_runbook = runbook.read_text(encoding="utf-8").replace(
            'systemctl disable --now "$unit"',
            'systemctl disable --now "$unit" 2>/dev/null || true',
            1,
    )
    unsafe_runbook = unsafe_runbook.replace(
        'systemctl daemon-reload\nfor UNIT in "${RETIRED_UNITS[@]}"; do\n  assert_retired_unit "$UNIT"\ndone\n\n# The current candidate',
        "systemctl daemon-reload\n\n# The current candidate",
        1,
    )
    unsafe_runbook = unsafe_runbook.replace(
        "systemctl show module-manager-v2.service -p User -p Group -p WorkingDirectory -p ExecStart\nwait_for_uvicorn\n",
        "systemctl show module-manager-v2.service -p User -p Group -p WorkingDirectory -p ExecStart\n",
        1,
    )
    runbook.write_text(unsafe_runbook, encoding="utf-8")

    failures: list[str] = []
    verifier._check_background_barcode_retirement(root, failures)

    assert any("fail-open" in failure for failure in failures)
    assert any("before migration or release switch" in failure for failure in failures)
    assert any("Uvicorn readiness" in failure for failure in failures)


def test_v3226_current_sop_fails_closed_on_unit_queries_and_verifies_rollback() -> None:
    deploy = (ROOT / "docs/sop/06-production-deploy-runbook.md").read_text(encoding="utf-8")
    rollback = (ROOT / "docs/sop/07-rollback-and-incident-review.md").read_text(encoding="utf-8")

    for text in (deploy, rollback):
        assert 'if ! LOAD_STATE=$(systemctl show "$unit" --property=LoadState --value); then' in text
        assert 'if ! ACTIVE_STATE=$(systemctl show "$unit" --property=ActiveState --value); then' in text
        assert 'if ! UNIT_FILE_STATE=$(systemctl show "$unit" --property=UnitFileState --value); then' in text
        assert 'systemctl show "$UNIT" --property=LoadState --value 2>/dev/null || true' not in text
        assert 'validate_release_directory "$PREVIOUS"' in text
        assert 'RESTORED=$(readlink -f -- "$APP/current")' in text

    assert '[ -L "$APP/current" ]' in deploy
    assert 'ROLLBACK_FAILED=0' in deploy
    assert '[ "$restored" != "$PREVIOUS" ]' in deploy
    assert 'Automatic rollback failed; current release state requires manual recovery.' in deploy
    assert '--expected-version "$PREVIOUS_VERSION"' in deploy
    assert '[ "$RESTORED" = "$PREVIOUS" ]' in rollback


def test_v3226_source_gate_rejects_query_error_swallowing_and_unverified_rollback(tmp_path) -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_26_fail_closed_queries")
    root = tmp_path / "source"
    for relative_path in verifier.V3226_BACKGROUND_BARCODE_RETIREMENT_MARKERS:
        source = ROOT / relative_path
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for relative_path in (
        "v2-api/app/api/router.py",
        "v2-api/app/main.py",
        "docs/sop/07-rollback-and-incident-review.md",
    ):
        source = ROOT / relative_path
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    deploy = root / "docs/sop/06-production-deploy-runbook.md"
    unsafe_deploy = deploy.read_text(encoding="utf-8").replace(
        'if ! LOAD_STATE=$(systemctl show "$unit" --property=LoadState --value); then',
        'LOAD_STATE=$(systemctl show "$unit" --property=LoadState --value 2>/dev/null || true)',
        1,
    )
    unsafe_deploy = unsafe_deploy.replace(
        'if [ -L "$APP/current" ]; then',
        "if true; then",
        1,
    )
    unsafe_deploy = unsafe_deploy.replace(
        'elif ! RESTORED=$(readlink -f -- "$APP/current"); then',
        'elif RESTORED=$(readlink -f -- "$APP/current"); then',
        1,
    )
    deploy.write_text(unsafe_deploy, encoding="utf-8")

    rollback = root / "docs/sop/07-rollback-and-incident-review.md"
    unsafe_rollback = rollback.read_text(encoding="utf-8").replace(
        'validate_release_directory "$PREVIOUS"',
        ': # rollback target was not validated',
        1,
    )
    rollback.write_text(unsafe_rollback, encoding="utf-8")

    failures: list[str] = []
    verifier._check_background_barcode_retirement(root, failures)

    assert any("unit state query is fail-open" in failure for failure in failures)
    assert any("previous release target is not validated" in failure for failure in failures)
    assert any("automatic rollback result is not verified" in failure for failure in failures)
    assert any("manual rollback target is not validated" in failure for failure in failures)


def test_v3226_source_gate_rejects_executable_bypass_with_markers_left_in_comments(tmp_path) -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_26_executable_block_lock")
    root = tmp_path / "source"
    for relative_path in verifier.V3226_BACKGROUND_BARCODE_RETIREMENT_MARKERS:
        source = ROOT / relative_path
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for relative_path in (
        "v2-api/app/api/router.py",
        "v2-api/app/main.py",
        "docs/sop/07-rollback-and-incident-review.md",
    ):
        source = ROOT / relative_path
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    deploy = root / "docs/sop/06-production-deploy-runbook.md"
    query_marker = 'if ! LOAD_STATE=$(systemctl show "$unit" --property=LoadState --value); then'
    unsafe_deploy = deploy.read_text(encoding="utf-8").replace(
        query_marker,
        f"# {query_marker}\n  LOAD_STATE=not-found\n  if false; then",
    )
    deploy.write_text(unsafe_deploy, encoding="utf-8")

    rollback = root / "docs/sop/07-rollback-and-incident-review.md"
    link_marker = 'if [ "$RESTORED" = "$PREVIOUS" ]; then'
    unsafe_rollback = rollback.read_text(encoding="utf-8").replace(
        link_marker,
        f"# {link_marker}\nif true; then",
        1,
    )
    rollback.write_text(unsafe_rollback, encoding="utf-8")

    failures: list[str] = []
    verifier._check_background_barcode_retirement(root, failures)

    locked_failures = [failure for failure in failures if "executable Bash block differs from reviewed" in failure]
    assert len(locked_failures) == 2


def test_v3226_source_gate_rejects_hidden_reviewed_block_and_visible_shadow_block(tmp_path) -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_26_visible_section_lock")
    root = tmp_path / "source"
    for relative_path in verifier.V3226_BACKGROUND_BARCODE_RETIREMENT_MARKERS:
        source = ROOT / relative_path
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for relative_path in (
        "v2-api/app/api/router.py",
        "v2-api/app/main.py",
        "docs/sop/07-rollback-and-incident-review.md",
    ):
        source = ROOT / relative_path
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    cases = (
        (
            root / "docs/sop/06-production-deploy-runbook.md",
            "## Deploy\n\n```bash",
            "\n```\n\nThe `0006`",
            "set -euo pipefail\nln -sfn /tmp/unreviewed /opt/module-manager-v2/current",
        ),
        (
            root / "docs/sop/07-rollback-and-incident-review.md",
            "## Rollback Steps\n\n```bash",
            "\n```\n\nKeep the retired",
            "set -euo pipefail\nln -sfn /tmp/unreviewed /opt/module-manager-v2/current",
        ),
    )
    for path, opening, closing, shadow in cases:
        text = path.read_text(encoding="utf-8")
        text = text.replace(opening, opening.replace("```bash", "<!--\n```bash"), 1)
        shadowed_closing = closing.replace(
            "\n```\n",
            f"\n```\n-->\n\n```bash\n{shadow}\n```\n",
            1,
        )
        text = text.replace(closing, shadowed_closing, 1)
        path.write_text(text, encoding="utf-8")

    failures: list[str] = []
    verifier._check_background_barcode_retirement(root, failures)

    section_failures = [failure for failure in failures if "reviewed SOP section differs from approved bytes" in failure]
    assert len(section_failures) == 2


def test_v3226_source_gate_rejects_html_comment_boundaries_outside_locked_sections(tmp_path) -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_26_html_comment_boundary")
    root = tmp_path / "source"
    for relative_path in verifier.V3226_BACKGROUND_BARCODE_RETIREMENT_MARKERS:
        source = ROOT / relative_path
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for relative_path in (
        "v2-api/app/api/router.py",
        "v2-api/app/main.py",
        "docs/sop/07-rollback-and-incident-review.md",
    ):
        source = ROOT / relative_path
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    cases = (
        (
            root / "docs/sop/06-production-deploy-runbook.md",
            "## Deploy",
            "## Post-Deploy Health Check",
            "## Deployment",
        ),
        (
            root / "docs/sop/07-rollback-and-incident-review.md",
            "## Rollback Steps",
            "## P0 Incident Flow",
            "## Rollback Procedure",
        ),
    )
    for path, locked_heading, next_heading, shadow_heading in cases:
        text = path.read_text(encoding="utf-8")
        text = text.replace(locked_heading, f"<!--\n{locked_heading}", 1)
        text = text.replace(
            next_heading,
            f"{next_heading}\n-->\n\n{shadow_heading}\n\n```bash\n"
            "set -euo pipefail\nln -sfn /tmp/unreviewed /opt/module-manager-v2/current\n```",
            1,
        )
        path.write_text(text, encoding="utf-8")

    failures: list[str] = []
    verifier._check_background_barcode_retirement(root, failures)

    html_comment_failures = [failure for failure in failures if "HTML comments are forbidden" in failure]
    assert len(html_comment_failures) == 2


def test_v3226_source_and_sop_gates_accept_the_current_pending_candidate() -> None:
    verifier = load_script(VERIFIER_PATH, "verify_v3_2_26_source")

    assert verifier.collect_failures(ROOT, "source") == []
    sop = load_script(ROOT / "scripts" / "verify_release_sop.py", "verify_release_sop_v3226")
    sop.verify_current_release_phase("source", "V3.2.26")
