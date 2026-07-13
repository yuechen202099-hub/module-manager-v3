from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
VALID_SHA256 = "a" * 64


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
