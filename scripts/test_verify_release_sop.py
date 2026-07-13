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


def test_parses_deployed_baseline_and_release_candidate_independently() -> None:
    verifier = load_verifier()
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert verifier.deployed_production_baseline(agents) == "V3.0.79"
    assert verifier.release_candidate(agents) == "V3.0.80"


@pytest.mark.parametrize(
    ("english_marker", "replacement", "parser_name"),
    [
        (
            "- Deployed production baseline: `V3.0.79`.",
            "- Deployed production baseline: `V3.0.80`.",
            "deployed_production_baseline",
        ),
        (
            "- Release candidate: `V3.0.80`.",
            "- Release candidate: `V3.0.81`.",
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


def test_round5_vue_app_version_uses_one_machine_source_and_entry_marker() -> None:
    source_path = ROOT / "v2-web" / "src" / "version.json"
    legacy_source_path = ROOT / "v2-web" / "public" / "version.json"
    release_notes = (ROOT / "v2-web" / "src" / "constants" / "releaseNotes.ts").read_text(encoding="utf-8")
    main = (ROOT / "v2-web" / "src" / "main.ts").read_text(encoding="utf-8")
    vite_config = (ROOT / "v2-web" / "vite.config.ts").read_text(encoding="utf-8")

    assert source_path.is_file()
    assert json.loads(source_path.read_text(encoding="utf-8")) == {"version": "3.0.80"}
    assert not legacy_source_path.exists()
    assert "from '../version.json'" in release_notes
    assert "APP_VERSION = versionArtifact.version" in release_notes
    assert "APP_VERSION = '3.0.80'" not in release_notes
    assert "__MODULE_MANAGER_VUE_ENTRY_VERSION_MARKER__" in main
    assert "__MODULE_MANAGER_VUE_ENTRY_VERSION__" in vite_config


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
