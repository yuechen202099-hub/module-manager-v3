from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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


def test_rejects_deployed_release_record_without_live_evidence() -> None:
    verifier = load_verifier()
    record = """# V3.0.80 Production Release Record

## Summary

- Status: deployed

## Package

| Evidence | Value |
| --- | --- |
| SHA256 | |

## Production Deployment

| Evidence | Value |
| --- | --- |
| Backup directory | |
| Release directory | |
| Public health check | |
"""

    assert verifier.release_record_claims_deployed_without_live_evidence(record)
