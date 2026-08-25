from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
VALID_SHA256 = "a" * 64
BULLETS = ("", "- ", "* ", "+ ")
PUNCTUATION_FORMS = (".", "．", "。", "!", "！", "?", "？", ":", "：", ";", "；", "brackets")


def load_verifier():
    spec = importlib.util.spec_from_file_location(
        "verify_release_sop", ROOT / "scripts" / "verify_release_sop.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load verify_release_sop.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v328_sop_inputs_bind_scale_and_camera_release_gates() -> None:
    verifier = load_verifier()

    assert {
        "scripts/verify_v3_2_8_release.py",
        "scripts/test_verify_v3_2_8_release.py",
        "v2-api/tests/test_collector_transfer_scale.py",
        "v2-web/src/views/__tests__/CollectorInventoryView.spec.ts",
        "ops/releases/V3.2.8.md",
    } <= set(verifier.RELEASE_INPUTS)


def test_v327_recovered_unattested_baseline_is_valid_for_v328_candidate() -> None:
    verifier = load_verifier()
    record = (ROOT / "ops/releases/V3.2.7.md").read_text(encoding="utf-8")

    verifier.release_record_matches_lifecycle_state(
        record,
        "V3.2.7",
        "V3.2.7",
        "V3.2.8",
    )


@pytest.mark.parametrize(
    ("field", "unexpected"),
    (
        ("Local Verification", "not run"),
        ("Package", "pending"),
        ("Production Deployment", "passed"),
        ("Production Reconciliation", "passed"),
        ("Rollback target", "V3.2.7"),
    ),
)
def test_v327_recovered_baseline_requires_exact_lifecycle_fields(
    field: str,
    unexpected: str,
) -> None:
    verifier = load_verifier()
    record = (ROOT / "ops/releases/V3.2.7.md").read_text(encoding="utf-8")
    matching_lines = [line for line in record.splitlines() if line.startswith(f"- {field}:")]
    assert len(matching_lines) == 1
    record = record.replace(matching_lines[0], f"- {field}: {unexpected}")

    with pytest.raises(AssertionError, match=rf"{field}: .* exactly once"):
        verifier.release_record_matches_lifecycle_state(
            record,
            "V3.2.7",
            "V3.2.7",
            "V3.2.8",
        )


@pytest.mark.parametrize(
    "claim",
    (
        "Production acceptance succeeded and V3.2.7 is fully accepted in production.",
        "V3.2.7 attestation: passed.",
        "The V3.2.7 production attestation was issued.",
        "Production acceptance has been approved.",
        "Production acceptance approval was granted.",
        "V3.2.7 has received production acceptance.",
        "Production attestation was formally signed.",
        "V3.2.7 已通过生产验收。",
    ),
)
def test_v327_recovered_baseline_rejects_affirmative_acceptance_or_attestation(
    claim: str,
) -> None:
    verifier = load_verifier()
    record = (ROOT / "ops/releases/V3.2.7.md").read_text(encoding="utf-8")

    with pytest.raises(AssertionError, match="affirmative production acceptance or attestation"):
        verifier.release_record_matches_lifecycle_state(
            f"{record}\n{claim}\n",
            "V3.2.7",
            "V3.2.7",
            "V3.2.8",
        )


@pytest.mark.parametrize(
    "negated_claim",
    (
        "V3.2.7 production acceptance is incomplete.",
        "There is no V3.2.7 attestation.",
        "V3.2.7 was not accepted in production.",
        "Production acceptance has not been approved.",
        "Production acceptance approval was not granted.",
        "V3.2.7 has not received production acceptance.",
        "Production attestation was not formally signed.",
        "V3.2.7 尚未通过生产验收。",
    ),
)
def test_v327_recovered_baseline_allows_explicitly_negated_acceptance_claims(
    negated_claim: str,
) -> None:
    verifier = load_verifier()
    record = (ROOT / "ops/releases/V3.2.7.md").read_text(encoding="utf-8")

    verifier.release_record_matches_lifecycle_state(
        f"{record}\n{negated_claim}\n",
        "V3.2.7",
        "V3.2.7",
        "V3.2.8",
    )


def test_v327_acceptance_gate_does_not_let_unrelated_negation_hide_acceptance() -> None:
    verifier = load_verifier()
    record = (ROOT / "ops/releases/V3.2.7.md").read_text(encoding="utf-8")

    with pytest.raises(AssertionError, match="affirmative production acceptance or attestation"):
        verifier.release_record_matches_lifecycle_state(
            f"{record}\n系统未发现错误且 V3.2.7 已通过生产验收。\n",
            "V3.2.7",
            "V3.2.7",
            "V3.2.8",
        )


def test_v327_acceptance_gate_checks_each_topic_occurrence() -> None:
    verifier = load_verifier()

    assert verifier.release_record_has_affirmative_acceptance_or_attestation(
        "No acceptance evidence was recorded before production acceptance was approved."
    )


def test_v327_acceptance_gate_allows_each_locally_negated_topic_occurrence() -> None:
    verifier = load_verifier()

    assert not verifier.release_record_has_affirmative_acceptance_or_attestation(
        "No acceptance evidence was recorded because production acceptance was not approved."
    )


def test_parses_current_deployed_baseline_and_release_candidate_markers() -> None:
    verifier = load_verifier()
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert verifier.deployed_production_baseline(agents) == "V3.2.7"
    assert verifier.release_candidate(agents) == "V3.2.8"


def test_cli_parses_version_and_rejects_unknown_arguments() -> None:
    verifier = load_verifier()

    args = verifier.parse_args(["--version", "V3.2.8", "--phase", "attestation"])
    assert args.version == "V3.2.8"
    assert args.phase == "attestation"
    with pytest.raises(SystemExit):
        verifier.parse_args(["--version", "V3.2.8", "--phase", "attestation", "--unknown"])
    with pytest.raises(SystemExit):
        verifier.parse_args(["--version", "V3.2.8"])


def test_cli_version_must_match_the_release_candidate() -> None:
    verifier = load_verifier()
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert verifier.validate_requested_candidate_version("V3.2.8", agents) == "V3.2.8"
    with pytest.raises(AssertionError, match="release candidate"):
        verifier.validate_requested_candidate_version("V3.1.1", agents)


def test_cli_verifies_the_current_release_contract() -> None:
    verifier = load_verifier()

    assert verifier.main(["--version", "V3.2.8", "--phase", "source"]) == 0


def test_v323_nested_release_inputs_accept_parent_directory_copy_semantics() -> None:
    verifier = load_verifier()
    build_script = "\n".join(
        (
            'Copy-ReleaseItem "v2-api\\app" "v2-api\\app"',
            'Copy-ReleaseItem "v2-api\\alembic" "v2-api\\alembic"',
            'Copy-ReleaseItem "v2-api\\scripts" "v2-api\\scripts"',
        )
    )

    assert verifier.release_input_is_copied_by_build_script(
        "v2-api/app/services/export_retirement.py", build_script
    )
    assert verifier.release_input_is_copied_by_build_script(
        "v2-api/alembic/versions/0014_export_center_jobs.py", build_script
    )
    assert verifier.release_input_is_copied_by_build_script(
        "v2-api/scripts/build_oss_export_manifest.py", build_script
    )
    assert not verifier.release_input_is_copied_by_build_script(
        "v2-web/src/version.json", build_script
    )


def test_rejects_wrong_release_candidate_maintenance_branch() -> None:
    verifier = load_verifier()
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8").replace(
        "production/V3/3.2.8", "production/V3/3.0.81"
    )

    with pytest.raises(AssertionError, match="maintenance branch"):
        verifier.release_candidate(agents)


def test_rejects_inconsistent_release_candidate_maintenance_branch_markers() -> None:
    verifier = load_verifier()
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8").replace(
        "- Release-candidate maintenance branch: `production/V3/3.2.8`.",
        "- Release-candidate maintenance branch: `production/V3/3.0.81`.",
        1,
    )

    with pytest.raises(AssertionError, match="English and Chinese release-candidate maintenance branch"):
        verifier.release_candidate(agents)


def test_accepts_pending_v3081_candidate_release_record() -> None:
    verifier = load_verifier()
    record = """# V3.0.81 Production Release Record

- Status: pending
- Local Verification: not run
- Package: pending
- Production Deployment: pending
- Production Reconciliation: pending
- Rollback target: V3.0.80
"""

    verifier.candidate_release_record_is_pending(record, "V3.0.81")


def test_accepts_pending_candidate_after_local_verification() -> None:
    verifier = load_verifier()
    record = """# V3.1.0 Production Release Record

- Status: pending
- Local Verification: passed
- Package: pending
- Production Deployment: pending
- Production Reconciliation: pending
- Rollback target: V3.0.84
"""

    verifier.candidate_release_record_is_pending(record, "V3.1.0", "V3.0.84")


def test_current_v328_source_phase_is_checked() -> None:
    verifier = load_verifier()

    verifier.verify_current_release_phase("source")


@pytest.mark.parametrize(
    "baseline_with_candidate_claim",
    (
        "- Deployed production baseline: `V3.2.6`; V3.2.7 was deployed today.",
        "- 当前已部署生产版本：`V3.2.6`；V3.2.7 已部署到生产环境。",
    ),
)
def test_baseline_metadata_does_not_hide_an_appended_candidate_deployment_claim(
    baseline_with_candidate_claim: str,
) -> None:
    verifier = load_verifier()
    record = f"{release_record('Status: pending')}\n{baseline_with_candidate_claim}\n"

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.release_record_claims_deployed_without_live_evidence(record)


@pytest.mark.parametrize(
    ("field", "conflicting_line"),
    [
        ("Package", "* Package: module-manager-v2-server-3.0.81.zip"),
        ("Local Verification", "+ Local Verification: passed"),
        ("Production Reconciliation", "Production Reconciliation: completed"),
        ("Production Reconciliation", "- Production Reconciliation\uff1a completed"),
    ],
)
def test_rejects_candidate_record_with_normalized_duplicate_lifecycle_field(
    field: str,
    conflicting_line: str,
) -> None:
    verifier = load_verifier()
    record = f"""# V3.0.81 Production Release Record

- Status: pending
- Local Verification: not run
- Package: pending
- Production Deployment: pending
- Production Reconciliation: pending
- Rollback target: V3.0.80
{conflicting_line}
"""

    with pytest.raises(AssertionError, match=rf"{field}: .* exactly once"):
        verifier.candidate_release_record_is_pending(record, "V3.0.81")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Package", "module-manager-v2-server-3.0.81.zip"),
        ("Production Deployment", "deployed"),
        ("Production Reconciliation", "released"),
    ],
)
def test_rejects_candidate_record_with_non_pending_lifecycle_evidence(field: str, value: str) -> None:
    verifier = load_verifier()
    record = f"""# V3.0.81 Production Release Record

- Status: pending
- Local Verification: not run
- Package: pending
- Production Deployment: pending
- Production Reconciliation: pending
- Rollback target: V3.0.80
- {field}: {value}
"""

    with pytest.raises(AssertionError, match=rf"{field}: .* exactly once"):
        verifier.candidate_release_record_is_pending(record, "V3.0.81")


def test_rejects_candidate_record_with_hidden_deployment_claim_and_valid_evidence() -> None:
    verifier = load_verifier()
    record = f"""# V3.0.81 Production Release Record

- Status: pending
- Local Verification: not run
- Package: pending
- Production Deployment: pending
- Production Reconciliation: pending
- Rollback target: V3.0.80
- Production Deployment: deployed

| Evidence | Value |
| --- | --- |
| SHA256 | {VALID_SHA256} |
| Backup directory | /opt/module-manager-v2/backups/V3.0.81-pre-20260719_120000 |
| Release directory | /opt/module-manager-v2/releases/v3.0.81-20260719_120000 |
| Public health check | https://www.sgcc.online/health passed |
"""

    with pytest.raises(AssertionError, match="Production Deployment: pending exactly once"):
        verifier.candidate_release_record_is_pending(record, "V3.0.81")


def test_rejects_pending_candidate_with_unversioned_deployment_claim_and_complete_evidence() -> None:
    verifier = load_verifier()
    record = f"""# V3.0.81 Production Release Record

- Status: pending
- Local Verification: not run
- Package: pending
- Production Deployment: pending
- Production Reconciliation: pending
- Rollback target: V3.0.80

Production was deployed successfully.

| Evidence | Value |
| --- | --- |
| SHA256 | {VALID_SHA256} |
| Backup directory | /opt/module-manager-v2/backups/V3.0.81-pre-20260719_120000 |
| Release directory | /opt/module-manager-v2/releases/v3.0.81-20260719_120000 |
| Public health check | https://www.sgcc.online/health passed |
"""

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.candidate_release_record_is_pending(record, "V3.0.81")


def test_candidate_lifecycle_uses_the_deployed_baseline_after_task5() -> None:
    verifier = load_verifier()
    record = valid_deployed_record(
        "Status: reviewed, packaged, deployed, and verified in production"
    ).replace("V3.0.80", "V3.0.81")

    verifier.release_record_matches_lifecycle_state(record, "V3.0.81", "V3.0.81", "V3.0.82")


def test_v3084_candidate_uses_the_deployed_baseline_as_its_rollback_target() -> None:
    verifier = load_verifier()
    record = """# V3.0.84 Production Release Record

- Status: pending
- Local Verification: not run
- Package: pending
- Production Deployment: pending
- Production Reconciliation: pending
- Rollback target: V3.0.83
"""

    verifier.release_record_matches_lifecycle_state(record, "V3.0.84", "V3.0.83", "V3.0.84")


def test_v3083_release_record_contains_required_chinese_feature_titles() -> None:
    record = (ROOT / "ops" / "releases" / "V3.0.83.md").read_text(encoding="utf-8")

    assert "审阅图片框选识别" in record
    assert "终端优先施工" in record


def test_v323_manifest_records_the_release_candidate_package() -> None:
    manifest = (ROOT / "RELEASE_MANIFEST.md").read_text(encoding="utf-8")

    assert "- Package: `build/server-release/module-manager-v2-server-3.2.8.zip`" in manifest
    assert "- Name: `module-manager-v2-server-3.2.8.zip`" in manifest
    assert "- Version: 3.2.8" in manifest


def test_v320_deployed_release_record_contains_required_release_evidence_contract() -> None:
    verifier = load_verifier()
    record = (ROOT / "ops" / "releases" / "V3.2.0.md").read_text(encoding="utf-8")

    verifier.deployed_release_record_is_verified(record, "V3.2.0")
    evidence = verifier.release_record_evidence(record)
    assert verifier.release_record_status(record) == (
        "reviewed, packaged, deployed, and verified in production"
    )
    assert evidence["SHA256"] == [
        "9448EDDCA27A36F2DF606EC1BC04A3BED05930B3D4D718E2D10381EE7FAEE6DF"
    ]
    assert evidence["Backup directory"] == [
        "/opt/module-manager-v2/backups/V3.2.0-pre-20260724_105349"
    ]
    assert evidence["Release directory"] == [
        "/opt/module-manager-v2/releases/v3.2.0-20260724_105649"
    ]
    assert evidence["Public health check"] == [
        "https://www.sgcc.online/health passed"
    ]
    for marker in (
        "数据中台统一审阅",
        "驾驶舱下钻",
        "统一导出中心",
        "审阅员角色下线",
        "明细分页支持 20/50/100",
        "0013_data_center_query_indexes",
        "0014_export_center_jobs",
        "fe527eb84064096321e727abf9ccbdc981e10b7e",
    ):
        assert marker in record


def test_v322_release_record_passes_the_deployed_baseline_gate() -> None:
    verifier = load_verifier()
    record = (ROOT / "ops" / "releases" / "V3.2.2.md").read_text(encoding="utf-8")

    verifier.deployed_release_record_is_verified(record, "V3.2.2")


@pytest.mark.parametrize("duplicate_value", ("passed", "pending"))
def test_v322_deployed_release_record_rejects_duplicate_package_field(
    duplicate_value: str,
) -> None:
    verifier = load_verifier()
    record = (ROOT / "ops" / "releases" / "V3.2.2.md").read_text(encoding="utf-8")
    record = record.replace(
        "- Package: passed",
        f"- Package: passed\n- Package: {duplicate_value}",
        1,
    )

    with pytest.raises(AssertionError, match="Package: passed exactly once"):
        verifier.deployed_release_record_is_verified(record, "V3.2.2")


@pytest.mark.parametrize(
    "replacement",
    (
        "- Rollback target: V3.2.1\n- Rollback target: V3.2.1",
        "- Rollback target: V3.2.1\n- Rollback target: V3.2.0",
        "",
    ),
)
def test_v322_deployed_release_record_requires_one_rollback_target(
    replacement: str,
) -> None:
    verifier = load_verifier()
    record = (ROOT / "ops" / "releases" / "V3.2.2.md").read_text(encoding="utf-8")
    record = record.replace("- Rollback target: V3.2.1", replacement, 1)

    with pytest.raises(AssertionError, match="Rollback target.*exactly once"):
        verifier.deployed_release_record_is_verified(record, "V3.2.2")


@pytest.mark.parametrize(
    "replacement",
    (
        "- Rollback target: V3.2.2\n- Rollback target: V3.2.2",
        "- Rollback target: V3.2.2\n- Rollback target: V3.2.1",
        "",
    ),
)
def test_candidate_release_record_requires_one_rollback_target(replacement: str) -> None:
    verifier = load_verifier()
    record = """# V3.2.3 Production Release Record

- Status: pending
- Local Verification: passed
- Package: pending
- Production Deployment: pending
- Production Reconciliation: pending
- Rollback target: V3.2.2
""".replace("- Rollback target: V3.2.2", replacement, 1)

    with pytest.raises(AssertionError, match="Rollback target: V3.2.2 exactly once"):
        verifier.candidate_release_record_is_pending(record, "V3.2.3", "V3.2.2")


def test_candidate_and_deployed_records_accept_one_rollback_target() -> None:
    verifier = load_verifier()
    candidate = """# V3.2.3 Production Release Record

- Status: pending
- Local Verification: passed
- Package: pending
- Production Deployment: pending
- Production Reconciliation: pending
- Rollback target: V3.2.2
"""
    deployed = (ROOT / "ops" / "releases" / "V3.2.2.md").read_text(encoding="utf-8")

    verifier.candidate_release_record_is_pending(candidate, "V3.2.3", "V3.2.2")
    verifier.deployed_release_record_is_verified(deployed, "V3.2.2")


def test_v3082_release_record_passes_the_deployed_baseline_gate() -> None:
    verifier = load_verifier()
    record = (ROOT / "ops" / "releases" / "V3.0.82.md").read_text(encoding="utf-8")

    verifier.deployed_release_record_is_verified(record, "V3.0.82")


@pytest.mark.parametrize(
    ("english_marker", "replacement", "parser_name"),
    [
        (
            "- Deployed production baseline: `V3.2.7`.",
            "- Deployed production baseline: `V3.0.82`.",
            "deployed_production_baseline",
        ),
        (
            "- Release candidate: `V3.2.8`.",
            "- Release candidate: `V3.0.83`.",
            "release_candidate",
        ),
    ],
)
def test_rejects_disagreement_between_english_and_chinese_agents_markers(
    english_marker: str,
    replacement: str,
    parser_name: str,
) -> None:
    verifier = load_verifier()
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8").replace(english_marker, replacement)

    with pytest.raises(AssertionError, match="English and Chinese"):
        getattr(verifier, parser_name)(agents)


@pytest.mark.parametrize(
    ("marker", "expected_error"),
    [
        ("当前  已部署 生产版本 ： `V3.0.79`  。", "deployed production baseline"),
        ("当前 发布候选版本 ： `V3.0.80`  。", "release candidate"),
    ],
)
def test_rejects_duplicate_normalized_version_markers(marker: str, expected_error: str) -> None:
    verifier = load_verifier()
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8") + f"\n- {marker}\n"

    parser = verifier.deployed_production_baseline if "已部署" in marker else verifier.release_candidate
    with pytest.raises(AssertionError, match=expected_error):
        parser(agents)


@pytest.mark.parametrize(
    "marker_line",
    [
        "+ 当前已部署生产版本: `V3.0.79`",
        "【当前已部署生产版本】！： `V3.0.79`",
    ],
)
def test_rejects_plus_and_punctuation_duplicate_version_markers(marker_line: str) -> None:
    verifier = load_verifier()
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8") + f"\n{marker_line}\n"

    with pytest.raises(AssertionError, match="deployed production baseline"):
        verifier.deployed_production_baseline(agents)


def decorated_field(label: str, value: str, bullet: str, punctuation: str) -> str:
    if punctuation == "brackets":
        return f"{bullet}\t【{label}】\u3000{value}"
    return f"{bullet}\t{label}\u3000{punctuation}\u3000{value}"


@pytest.mark.parametrize("bullet", BULLETS)
@pytest.mark.parametrize("punctuation", PUNCTUATION_FORMS)
def test_rejects_all_punctuation_duplicate_markers(bullet: str, punctuation: str) -> None:
    verifier = load_verifier()
    marker = decorated_field("当前已部署生产版本", "`V3.0.79`", bullet, punctuation)
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8") + f"\n{marker}\n"

    with pytest.raises(AssertionError, match="deployed production baseline"):
        verifier.deployed_production_baseline(agents)


def release_record(*status_lines: str, sha256: str = "", backup: str = "", release: str = "", health: str = "") -> str:
    statuses = "\n".join(f"- {line}" for line in status_lines)
    return f"""# V3.0.80 Production Release Record

## Summary

{statuses}

## Package

| Evidence | Value |
| --- | --- |
| SHA256 | {sha256} |

## Production Deployment

| Evidence | Value |
| --- | --- |
| Backup directory | {backup} |
| Release directory | {release} |
| Public health check | {health} |
"""


def valid_deployed_record(
    *status_lines: str,
    sha256: str = VALID_SHA256,
    backup: str = "/opt/module-manager-v2/backups/V3.0.80-pre-20260713_120000",
    release: str = "/opt/module-manager-v2/releases/v3.0.80-20260713_120000",
    health: str = "https://www.sgcc.online/health passed",
) -> str:
    return release_record(
        *(status_lines or ("Status: deployed",)),
        sha256=sha256,
        backup=backup,
        release=release,
        health=health,
    )


def valid_unbulleted_deployed_record() -> str:
    return f"""Status: shipped
SHA256: {VALID_SHA256}
Backup directory: /opt/module-manager-v2/backups/V3.0.80-pre-20260713_120000
Release directory: /opt/module-manager-v2/releases/v3.0.80-20260713_120000
Public health check: https://www.sgcc.online/health passed
"""


def test_deployed_lifecycle_rejects_bare_deployed_status() -> None:
    verifier = load_verifier()

    with pytest.raises(AssertionError, match="reviewed, packaged, deployed, and verified"):
        verifier.deployed_release_record_is_verified(
            valid_deployed_record("Status: deployed"),
            "V3.0.80",
        )


def test_deployed_lifecycle_accepts_complete_status() -> None:
    verifier = load_verifier()

    verifier.deployed_release_record_is_verified(
        valid_deployed_record(
            "Status: reviewed, packaged, deployed, and verified in production"
        ),
        "V3.0.80",
    )


def test_post_deploy_equal_markers_validate_one_deployed_record() -> None:
    verifier = load_verifier()
    reads: list[str] = []
    record = valid_deployed_record(
        "Status: reviewed, packaged, deployed, and verified in production"
    ).replace("V3.0.80", "V3.0.81")

    verifier.validate_release_lifecycle_records(
        lambda version: reads.append(version) or record,
        "V3.0.81",
        "V3.0.81",
    )

    assert reads == ["V3.0.81"]


def test_rejects_multiple_or_contradictory_status_claims() -> None:
    verifier = load_verifier()
    record = valid_deployed_record("Status: pending", "Deployment state: deployed")

    with pytest.raises(AssertionError, match="multiple status-like claims"):
        verifier.release_record_claims_deployed_without_live_evidence(record)


def test_detects_shipped_and_chinese_deployment_status_claims() -> None:
    verifier = load_verifier()

    assert verifier.release_record_claims_deployed_without_live_evidence(
        release_record("Deployment state: shipped")
    )
    assert verifier.release_record_claims_deployed_without_live_evidence(release_record("部署状态：已上线"))


@pytest.mark.parametrize("status_line", ["+ Status: shipped", "Status！ shipped"])
def test_parses_plus_and_unbulleted_punctuation_status_claims(status_line: str) -> None:
    verifier = load_verifier()
    record = valid_deployed_record().replace("- Status: deployed", status_line)

    assert not verifier.release_record_claims_deployed_without_live_evidence(record)


@pytest.mark.parametrize("bullet", BULLETS)
@pytest.mark.parametrize("punctuation", PUNCTUATION_FORMS)
def test_rejects_later_deployed_status_for_all_punctuation_forms(bullet: str, punctuation: str) -> None:
    verifier = load_verifier()
    later_status = decorated_field("Status", "shipped", bullet, punctuation)
    record = valid_deployed_record().replace("- Status: deployed", f"- Status: pending\n{later_status}")

    with pytest.raises(AssertionError, match="multiple status-like claims"):
        verifier.release_record_claims_deployed_without_live_evidence(record)


def test_parses_unbulleted_evidence_lines() -> None:
    verifier = load_verifier()

    assert not verifier.release_record_claims_deployed_without_live_evidence(valid_unbulleted_deployed_record())


def replace_evidence_row(record: str, label: str, value: str) -> str:
    return "\n".join(
        f"| {label} | {value} |" if line.startswith(f"| {label} |") else line
        for line in record.splitlines()
    )


def append_evidence_row(record: str, label: str, value: str) -> str:
    return f"{record}\n| {label} | {value} |\n"


@pytest.mark.parametrize(
    ("label", "invalid", "valid"),
    [
        ("SHA256", "TBD", VALID_SHA256),
        ("Backup directory", "TBD", "/opt/module-manager-v2/backups/V3.0.80-pre-20260713_120000"),
        ("Release directory", "TBD", "/opt/module-manager-v2/releases/v3.0.80-20260713_120000"),
        ("Public health check", "TBD", "https://www.sgcc.online/health passed"),
    ],
)
def test_rejects_duplicate_invalid_and_valid_evidence(label: str, invalid: str, valid: str) -> None:
    verifier = load_verifier()
    record = replace_evidence_row(valid_deployed_record(), label, invalid)
    record = append_evidence_row(record, label, valid)

    assert verifier.release_record_claims_deployed_without_live_evidence(record)


@pytest.mark.parametrize(
    ("label", "value"),
    [
        ("SHA256", VALID_SHA256),
        ("Backup directory", "/opt/module-manager-v2/backups/V3.0.80-pre-20260713_120000"),
        ("Release directory", "/opt/module-manager-v2/releases/v3.0.80-20260713_120000"),
        ("Public health check", "https://www.sgcc.online/health passed"),
    ],
)
def test_rejects_duplicate_valid_evidence(label: str, value: str) -> None:
    verifier = load_verifier()

    assert verifier.release_record_claims_deployed_without_live_evidence(
        append_evidence_row(valid_deployed_record(), label, value)
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sha256", "TBD"),
        ("sha256", "TODO"),
        ("sha256", "N/A"),
        ("sha256", "unknown"),
        ("sha256", "-"),
        ("sha256", "a" * 63),
        ("backup", "pending"),
        ("backup", "/tmp/backups/V3.0.80"),
        ("backup", "/opt/module-manager-v2/backups/.."),
        ("release", "待补充"),
        ("release", "待验证"),
        ("release", "/opt/module-manager-v2/current"),
        ("release", "/opt/module-manager-v2/releases/."),
        ("health", "https://www.sgcc.online/health pending"),
        ("health", "https://www.sgcc.online/health passed TBD"),
        ("health", "https://example.invalid/health passed"),
    ],
)
def test_rejects_placeholder_and_invalid_deployment_evidence(field: str, value: str) -> None:
    verifier = load_verifier()
    evidence = {
        "sha256": VALID_SHA256,
        "backup": "/opt/module-manager-v2/backups/V3.0.80-pre-20260713_120000",
        "release": "/opt/module-manager-v2/releases/v3.0.80-20260713_120000",
        "health": "https://www.sgcc.online/health passed",
    }
    evidence[field] = value

    assert verifier.release_record_claims_deployed_without_live_evidence(
        valid_deployed_record(**evidence)
    )


@pytest.mark.parametrize("status", ["Status: released", "Deployment state: shipped", "发布状态：已发布"])
def test_accepts_a_valid_deployed_release_record(status: str) -> None:
    verifier = load_verifier()

    assert not verifier.release_record_claims_deployed_without_live_evidence(valid_deployed_record(status))


@pytest.mark.parametrize(
    "affirmative_prose",
    [
        "V3.0.80 was deployed to production and verified successfully.",
        "V3.0.80 已部署至生产环境并完成验证。",
        "Production successfully shipped V3.0.80.",
    ],
)
def test_rejects_affirmative_candidate_deployment_prose_when_status_is_pending(
    affirmative_prose: str,
) -> None:
    verifier = load_verifier()
    record = f"{release_record('Status: pending')}\n{affirmative_prose}\n"

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.release_record_claims_deployed_without_live_evidence(record)


@pytest.mark.parametrize(
    "pending_or_negated_prose",
    [
        "V3.0.80 has not been deployed to production.",
        "V3.0.80 deployment is pending production approval.",
        "V3.0.80 尚未部署至生产环境。",
        "V3.0.80 待部署和验证。",
    ],
)
def test_preserves_negated_or_pending_candidate_deployment_prose(
    pending_or_negated_prose: str,
) -> None:
    verifier = load_verifier()
    record = f"{release_record('Status: pending')}\n{pending_or_negated_prose}\n"

    assert not verifier.release_record_claims_deployed_without_live_evidence(record)


@pytest.mark.parametrize(
    "contradictory_prose",
    [
        "V3.0.80 was not deployed yesterday; V3.0.80 was deployed today.",
        "V3.0.80 was not deployed yesterday, V3.0.80 was deployed today.",
        "V3.0.80 was not deployed yesterday and was deployed today.",
        "V3.0.80 昨日未部署并于今日已部署。",
        "V3.0.80\nhas been deployed to production.",
        "V3.0.80\n\nhas been deployed to production.",
        "V3.0.80 is now live in production.",
        "V3.0.80 生产部署已完成。",
        "V3.0.80 尚未部署的记录已过时；V3.0.80 已部署。",
    ],
)
def test_rejects_clause_scoped_and_cross_line_affirmative_deployment_prose(
    contradictory_prose: str,
) -> None:
    verifier = load_verifier()
    record = f"{release_record('Status: pending')}\n{contradictory_prose}\n"

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.release_record_claims_deployed_without_live_evidence(record)


@pytest.mark.parametrize(
    "negated_or_future_prose",
    [
        "V3.0.80 hasn't been deployed to production.",
        "V3.0.80 was not currently deployed.",
        "V3.0.80 is not live in production.",
        "V3.0.80 will be deployed tomorrow.",
        "V3.0.80 将于明日部署。",
        "V3.0.80 production deployment remains pending.",
        "V3.0.80\n\n| Deployed source commit | |",
        "V3.0.80 rollback is allowed only after the release has been deployed.",
    ],
)
def test_semantic_clause_parser_does_not_treat_negative_pending_or_future_as_deployed(
    negated_or_future_prose: str,
) -> None:
    verifier = load_verifier()
    record = f"{release_record('Status: pending')}\n{negated_or_future_prose}\n"

    assert not verifier.release_record_claims_deployed_without_live_evidence(record)


ROUND4_CONDITIONAL_OR_NEGATED_CLAIMS = [
    "V3.0.80 can't be deployed to production.",
    "V3.0.80 cannot be deployed to production.",
    "V3.0.80 can be deployed to production.",
    "V3.0.80 could be deployed to production.",
    "V3.0.80 may be deployed to production.",
    "V3.0.80 might be deployed to production.",
    "V3.0.80 is deployed to production if approval is granted.",
    "V3.0.80 is deployed to production unless rollback is required.",
    "V3.0.80 可能已上线生产环境。",
    "V3.0.80 若通过验收则已上线生产环境。",
    "如果验证通过，V3.0.80 生产部署已完成。",
    "除非回归测试失败，否则 V3.0.80 已部署到生产环境。",
]


@pytest.mark.parametrize("prose", ROUND4_CONDITIONAL_OR_NEGATED_CLAIMS)
def test_round4_conditional_or_negated_claims_are_not_affirmative(prose: str) -> None:
    verifier = load_verifier()
    record = f"{release_record('Status: pending')}\n{prose}\n"

    assert not verifier.release_record_claims_deployed_without_live_evidence(record)


@pytest.mark.parametrize(
    "prose",
    [
        "V3.0.80 has gone live in production.",
        "V3.0.80 and its assets have gone live in production.",
        "V3.0.80 could be deployed after approval, but V3.0.80 was deployed today.",
        "V3.0.80 已在生产环境上线。",
        "V3.0.80 已完成生产上线。",
        "V3.0.80 现已在生产环境正式生效。",
        "V3.0.80 可能在审批后上线，但 V3.0.80 今日已上线生产环境。",
    ],
)
def test_round4_live_and_completion_synonyms_are_affirmative(prose: str) -> None:
    verifier = load_verifier()
    record = f"{release_record('Status: pending')}\n{prose}\n"

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.release_record_claims_deployed_without_live_evidence(record)


@pytest.mark.parametrize(
    "prose",
    [
        "V3.0.80 has not gone live in production.",
        "V3.0.80 cannot go live in production.",
        "V3.0.80 may go live in production.",
        "V3.0.80 will go live in production after approval.",
        "V3.0.80 尚未在生产环境上线。",
        "V3.0.80 可能在生产环境上线。",
        "V3.0.80 将在生产环境上线。",
    ],
)
def test_round4_negative_pending_and_future_live_controls_remain_nonaffirmative(prose: str) -> None:
    verifier = load_verifier()
    record = f"{release_record('Status: pending')}\n{prose}\n"

    assert not verifier.release_record_claims_deployed_without_live_evidence(record)


ROUND5_AFFIRMATIVE_CLAIMS = [
    "Operators can log in, and V3.0.80 was deployed to production.",
    "Operators can log in if authorized, and V3.0.80 was deployed to production.",
    "V3.0.80 has already gone live in production.",
]


ROUND5_NORMATIVE_OR_FUTURE_CLAIMS = [
    "V3.0.80 should be deployed tomorrow.",
    "V3.0.80 must be deployed after approval.",
    "V3.0.80 ought to be deployed tomorrow.",
    "V3.0.80 应于明日部署至生产环境。",
    "V3.0.80 必须在验收后部署至生产环境。",
]


ROUND6_AFFIRMATIVE_CLAIMS = [
    "V3.0.80 was deployed to production because operators can verify it.",
    "V3.0.80 was deployed to production because operators can verify it if authorized.",
    "V3.0.80 was deployed to production after admins could approve it.",
    "V3.0.80 已部署到生产环境且响应正常。",
]


ROUND6_NEGATIVE_CONDITIONAL_OR_FUTURE_CLAIMS = [
    "V3.0.80 did not get deployed to production.",
    "V3.0.80 should be deployed tomorrow because operators can verify it.",
    "V3.0.80 应于明日部署至生产环境且响应需验证。",
    "V3.0.80 仅当验收通过才可部署到生产环境。",
]


ROUND7_AFFIRMATIVE_CLAIMS = [
    "V3.0.80 has gone live.",
    "V3.0.80 已经部署到生产环境。",
]


ROUND7_NONAFFIRMATIVE_CLAIMS = [
    "V3.0.80 could have been deployed to production.",
    "V3.0.80 will have been deployed to production by Friday.",
    "V3.0.80 was not even deployed to production.",
    "V3.0.80 may eventually be deployed to production.",
]


ROUND8_AFFIRMATIVE_LIVE_CLAIMS = [
    "V3.0.80 is currently live in production.",
    "V3.0.80 is presently live in production.",
    "V3.0.80 is running in production.",
    "V3.0.80 is in production.",
]


ROUND8_NONAFFIRMATIVE_PRODUCTION_STATE_CLAIMS = [
    "V3.0.80 is not running in production.",
    "V3.0.80 is currently not in production.",
    "V3.0.80 will be running in production after approval.",
    "V3.0.80 may be in production after approval.",
]


ROUND9_AFFIRMATIVE_PERFECT_PRODUCTION_STATE_CLAIMS = [
    "V3.0.80 has been running in production since Monday.",
    "V3.0.80 has been in production since Monday.",
    "V3.0.80 and its assets have been running in production since Monday.",
    "V3.0.80 had been in production before the rollback.",
    "V3.0.80 has been continuously running in production since Monday.",
    "V3.0.80 has been running successfully in production since Monday.",
    "V3.0.80 has recently been running in production since Monday.",
    "V3.0.80 has long been running steadily in production.",
    "V3.0.80 has been running reliably in production.",
]


ROUND9_NONAFFIRMATIVE_PERFECT_PRODUCTION_STATE_CLAIMS = [
    "V3.0.80 has not been continuously running in production.",
    "V3.0.80 will have been continuously running in production by Friday.",
    "V3.0.80 may have been running successfully in production.",
    "V3.0.80 has possibly been running in production.",
    "V3.0.80 may recently have been running steadily in production.",
    "V3.0.80 may well have been running in production.",
    "V3.0.80 could recently have been running in production.",
]

ROUND10_NONCLAIM_CONTEXTS = [
    '> Example: "V3.0.80 was deployed to production."',
    'Example: "V3.0.80 was deployed to production."',
    '- "V3.0.80 was deployed to production."',
    '`V3.0.80 was deployed to production.`',
    '    V3.0.80 was deployed to production.',
    '```text\nV3.0.80 was deployed to production.\n```',
    '~~~\nV3.0.80 was deployed to production.\n~~~',
    '"V3.0.80 was deployed to production."',
    '示例：“V3.0.80 已在生产环境上线。”',
    '“V3.0.80 已在生产环境上线。”',
    'There is no evidence that V3.0.80 was deployed to production.',
    'We cannot claim that V3.0.80 has been released to production.',
    '目前没有证据表明 V3.0.80 已在生产环境上线。',
    '我们不能声称 V3.0.80 已部署到生产环境。',
]


@pytest.mark.parametrize("prose", ROUND5_AFFIRMATIVE_CLAIMS)
def test_round5_atomic_clauses_preserve_affirmative_deployment_claims(prose: str) -> None:
    verifier = load_verifier()
    record = f"{release_record('Status: pending')}\n{prose}\n"

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.release_record_claims_deployed_without_live_evidence(record)


@pytest.mark.parametrize("prose", ROUND5_NORMATIVE_OR_FUTURE_CLAIMS)
def test_round5_normative_or_future_claims_remain_nonaffirmative(prose: str) -> None:
    verifier = load_verifier()
    record = f"{release_record('Status: pending')}\n{prose}\n"

    assert not verifier.release_record_claims_deployed_without_live_evidence(record)


@pytest.mark.parametrize("prose", ROUND6_AFFIRMATIVE_CLAIMS)
def test_round6_modal_tokens_outside_deployment_predicate_do_not_hide_claim(prose: str) -> None:
    verifier = load_verifier()
    record = f"{release_record('Status: pending')}\n{prose}\n"

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.release_record_claims_deployed_without_live_evidence(record)


@pytest.mark.parametrize("prose", ROUND6_NEGATIVE_CONDITIONAL_OR_FUTURE_CLAIMS)
def test_round6_deployment_predicate_scope_preserves_nonaffirmative_controls(prose: str) -> None:
    verifier = load_verifier()
    record = f"{release_record('Status: pending')}\n{prose}\n"

    assert not verifier.release_record_claims_deployed_without_live_evidence(record)


@pytest.mark.parametrize("prose", ROUND7_AFFIRMATIVE_CLAIMS)
def test_round7_common_live_and_chinese_completion_are_affirmative(prose: str) -> None:
    verifier = load_verifier()
    record = f"{release_record('Status: pending')}\n{prose}\n"

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.release_record_claims_deployed_without_live_evidence(record)


@pytest.mark.parametrize("prose", ROUND7_NONAFFIRMATIVE_CLAIMS)
def test_round7_complete_auxiliary_chains_remain_nonaffirmative(prose: str) -> None:
    verifier = load_verifier()
    record = f"{release_record('Status: pending')}\n{prose}\n"

    assert not verifier.release_record_claims_deployed_without_live_evidence(record)


@pytest.mark.parametrize("prose", ROUND8_AFFIRMATIVE_LIVE_CLAIMS)
def test_round8_current_live_adverbs_are_affirmative(prose: str) -> None:
    verifier = load_verifier()
    record = f"{release_record('Status: pending')}\n{prose}\n"

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.release_record_claims_deployed_without_live_evidence(record)


@pytest.mark.parametrize("prose", ROUND8_NONAFFIRMATIVE_PRODUCTION_STATE_CLAIMS)
def test_round8_negative_future_or_modal_production_states_are_not_affirmative(prose: str) -> None:
    verifier = load_verifier()
    record = f"{release_record('Status: pending')}\n{prose}\n"

    assert not verifier.release_record_claims_deployed_without_live_evidence(record)


@pytest.mark.parametrize("prose", ROUND9_AFFIRMATIVE_PERFECT_PRODUCTION_STATE_CLAIMS)
def test_round9_perfect_production_states_are_affirmative(prose: str) -> None:
    verifier = load_verifier()
    record = f"{release_record('Status: pending')}\n{prose}\n"

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.release_record_claims_deployed_without_live_evidence(record)


@pytest.mark.parametrize("prose", ROUND9_NONAFFIRMATIVE_PERFECT_PRODUCTION_STATE_CLAIMS)
def test_round9_negative_future_or_modal_perfect_states_are_not_affirmative(prose: str) -> None:
    verifier = load_verifier()
    record = f"{release_record('Status: pending')}\n{prose}\n"

    assert not verifier.release_record_claims_deployed_without_live_evidence(record)


@pytest.mark.parametrize("prose", ROUND10_NONCLAIM_CONTEXTS)
def test_round10_quotes_examples_and_scoped_negations_are_not_affirmative(prose: str) -> None:
    verifier = load_verifier()
    record = f"{release_record('Status: pending')}\n{prose}\n"

    assert not verifier.release_record_claims_deployed_without_live_evidence(record)


def test_round10_ignored_code_does_not_hide_a_later_real_deployment_claim() -> None:
    verifier = load_verifier()
    prose = "```text\nV3.0.80 will be deployed to production.\n```\nV3.0.80 was deployed to production."
    record = f"{release_record('Status: pending')}\n{prose}\n"

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.release_record_claims_deployed_without_live_evidence(record)


def test_round10_table_prose_with_a_real_deployment_claim_is_affirmative() -> None:
    verifier = load_verifier()
    record = f"{release_record('Status: pending')}\n| Note | V3.0.80 was deployed to production. |\n"

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.release_record_claims_deployed_without_live_evidence(record)


def test_round11_indented_fence_marker_does_not_hide_later_real_deployment_claim() -> None:
    verifier = load_verifier()
    prose = "    ```text\nV3.0.80 was deployed to production."
    record = f"{release_record('Status: pending')}\n{prose}\n"

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.release_record_claims_deployed_without_live_evidence(record)


def test_round11_nested_bullet_blockquote_is_not_affirmative() -> None:
    verifier = load_verifier()
    record = f'{release_record("Status: pending")}\n- > "V3.0.80 was deployed to production."\n'

    assert not verifier.release_record_claims_deployed_without_live_evidence(record)


def test_round11_ordered_list_full_quote_is_not_affirmative() -> None:
    verifier = load_verifier()
    record = f'{release_record("Status: pending")}\n1. "V3.0.80 was deployed to production."\n'

    assert not verifier.release_record_claims_deployed_without_live_evidence(record)


def test_round11_not_true_scopes_negation_over_deployment_claim() -> None:
    verifier = load_verifier()
    prose = "It is not true that V3.0.80 was deployed to production."
    record = f"{release_record('Status: pending')}\n{prose}\n"

    assert not verifier.release_record_claims_deployed_without_live_evidence(record)


def test_round5_vue_app_version_uses_one_machine_source_and_entry_marker() -> None:
    source_path = ROOT / "v2-web" / "src" / "version.json"
    legacy_source_path = ROOT / "v2-web" / "public" / "version.json"
    release_notes = (ROOT / "v2-web" / "src" / "constants" / "releaseNotes.ts").read_text(encoding="utf-8")
    main = (ROOT / "v2-web" / "src" / "main.ts").read_text(encoding="utf-8")
    vite_config = (ROOT / "v2-web" / "vite.config.ts").read_text(encoding="utf-8")

    assert source_path.is_file()
    assert json.loads(source_path.read_text(encoding="utf-8")) == {"version": "3.2.8"}
    assert not legacy_source_path.exists()
    assert "from '../version.json'" in release_notes
    assert "APP_VERSION = versionArtifact.version" in release_notes
    assert "APP_VERSION = '3.0.80'" not in release_notes
    assert "import versionArtifact from './version.json'" in main
    assert "moduleManagerBuildVersion" in main
    assert "__MODULE_MANAGER_VUE_ENTRY_ATTESTATION__" in vite_config
    assert "entrySha256" in vite_config
    assert "assets," in vite_config
    assert "localeCompare" not in vite_config
    assert "left.path < right.path" in vite_config


@pytest.mark.parametrize(
    "payload",
    [
        '{"version": "3.0.80", "version": "3.0.79"}',
        '{"version": "V3.0.80"}',
        '{"version": "3.0.80-beta"}',
        '{"version": "3.0.80", "note": "ambiguous"}',
        'not-json',
    ],
)
def test_round4_runtime_version_artifact_rejects_ambiguous_or_nonsemantic_payload(payload: str) -> None:
    verifier = load_verifier()

    with pytest.raises(AssertionError, match="machine-readable runtime version"):
        verifier.runtime_version_from_artifact(payload)


def test_round4_runtime_version_artifact_reads_exact_semantic_version() -> None:
    verifier = load_verifier()

    assert verifier.runtime_version_from_artifact(json.dumps({"version": "3.0.80"})) == "3.0.80"


if __name__ == "__main__":
    raise SystemExit(pytest.main([str(Path(__file__).resolve()), "-q"]))
