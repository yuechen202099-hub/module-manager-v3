from __future__ import annotations

import sys
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "docs/sop/README.md",
    "docs/sop/01-demand-intake-and-priority.md",
    "docs/sop/02-production-branch-versioning.md",
    "docs/sop/03-change-analysis-and-tdd.md",
    "docs/sop/04-subagent-review-template.md",
    "docs/sop/05-release-package-and-hash.md",
    "docs/sop/06-production-deploy-runbook.md",
    "docs/sop/07-rollback-and-incident-review.md",
    "docs/sop/08-business-acceptance-templates.md",
    "ops/releases/README.md",
    "ops/releases/V3.0.79.md",
    "ops/releases/V3.0.80.md",
    "ops/releases/V3.0.78.md",
    "ops/releases/V3.0.77.md",
    "ops/releases/V3.0.76.md",
    "ops/releases/V3.0.75.md",
    "ops/releases/V3.0.74.md",
    "ops/releases/V3.0.73.md",
    "ops/releases/V3.0.72.md",
    "ops/releases/V3.0.71.md",
    "ops/releases/V3.0.70.md",
    "ops/releases/V3.0.69.md",
    "ops/releases/V3.0.68.md",
    "ops/releases/V3.0.67.md",
    "ops/releases/V3.0.66.md",
    "ops/releases/V3.0.65.md",
    "ops/releases/V3.0.64.md",
    "ops/releases/V3.0.63.md",
    "ops/releases/V3.0.62.md",
    "ops/releases/V3.0.61.md",
    "ops/releases/V3.0.60.md",
    "ops/releases/V3.0.59.md",
    "ops/releases/V3.0.58.md",
    "ops/releases/V3.0.56.md",
    "ops/releases/V3.0.55.md",
    "ops/releases/V3.0.54.md",
    "ops/releases/V3.0.53.md",
    "ops/releases/V3.0.52.md",
    "ops/releases/V3.0.51.md",
    "ops/releases/V3.0.50.md",
    "ops/releases/V3.0.49.md",
    "ops/releases/V3.0.48.md",
    "ops/releases/V3.0.47.md",
    "ops/releases/V3.0.46.md",
    "ops/releases/V3.0.45.md",
    "ops/releases/V3.0.44.md",
    "ops/releases/V3.0.42.md",
    "ops/releases/V3.0.41.md",
    "ops/releases/V3.0.40.md",
    "ops/releases/V3.0.39.md",
    "ops/releases/V3.0.38.md",
    "ops/releases/V3.0.37.md",
    "ops/incidents/P0-template.md",
    "scripts/production_backup.sh",
    "scripts/cleanup_old_releases.sh",
    "scripts/production_health_check.py",
    "scripts/verify_release_retention_policy.py",
    "scripts/verify_project_board_data_center_photos.js",
    "scripts/verify_project_board_unmatched_review.js",
    "scripts/verify_dialog_information_integration.js",
]

DEPLOYED_BASELINE_PATTERN = re.compile(
    r"^- 当前已部署生产版本：`(?P<version>V\d+\.\d+\.\d+)`。$", re.MULTILINE
)
RELEASE_CANDIDATE_PATTERN = re.compile(
    r"^- 当前发布候选版本：`(?P<version>V\d+\.\d+\.\d+)`。$", re.MULTILINE
)
RELEASE_STATUS_PATTERN = re.compile(r"^- Status:\s*(?P<status>.+?)\s*$", re.MULTILINE)
RELEASE_TABLE_ROW_PATTERN = re.compile(
    r"^\|\s*(?P<evidence>[^|]+?)\s*\|\s*(?P<value>[^|]*)\s*\|\s*$", re.MULTILINE
)
DEPLOYMENT_EVIDENCE_FIELDS = (
    "SHA256",
    "Backup directory",
    "Release directory",
    "Public health check",
)


def fail(message: str) -> None:
    raise AssertionError(message)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def parse_agents_marker(agents: str, pattern: re.Pattern[str], marker_name: str) -> str:
    matches = list(pattern.finditer(agents))
    if len(matches) != 1:
        fail(f"AGENTS.md must define exactly one {marker_name} marker")
    return matches[0].group("version")


def deployed_production_baseline(agents: str) -> str:
    return parse_agents_marker(agents, DEPLOYED_BASELINE_PATTERN, "deployed production baseline")


def release_candidate(agents: str) -> str:
    return parse_agents_marker(agents, RELEASE_CANDIDATE_PATTERN, "release candidate")


def release_record_status(record: str) -> str:
    match = RELEASE_STATUS_PATTERN.search(record)
    if match is None:
        fail("release record must include a Status field")
    return match.group("status").strip()


def release_record_evidence(record: str) -> dict[str, str]:
    return {
        match.group("evidence").strip(): match.group("value").strip()
        for match in RELEASE_TABLE_ROW_PATTERN.finditer(record)
    }


def release_record_claims_deployed_without_live_evidence(record: str) -> bool:
    if "deployed" not in release_record_status(record).casefold():
        return False
    evidence = release_record_evidence(record)
    return any(not evidence.get(field, "").strip() for field in DEPLOYMENT_EVIDENCE_FIELDS)


def main() -> int:
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).exists()]
    if missing:
        fail("Missing SOP files: " + ", ".join(missing))

    readme = read("README.md")
    if "build/server-release/" not in readme:
        fail("README must document build/server-release as the production package path")
    if "docs/sop/README.md" not in readme:
        fail("README must link the SOP index")

    gate = read("scripts/run-client-acceptance-gate.ps1")
    if "build\\client-release" in gate or "module-manager-v2-client-demo" in gate:
        fail("run-client-acceptance-gate.ps1 still references the legacy client-release package path")
    if "build\\server-release" not in gate:
        fail("run-client-acceptance-gate.ps1 must verify the server-release package")

    release_verifier = read("scripts/verify-client-release.py")
    if "build/client-release" in release_verifier or "module-manager-v2-client-demo" in release_verifier:
        fail("verify-client-release.py must not default to legacy client-release packages")
    build_script = read("scripts/build-client-release.ps1")
    if "scripts\\verify_admin_release_notes.js" not in build_script:
        fail("build-client-release.ps1 must copy scripts\\verify_admin_release_notes.js")
    if "scripts/verify_admin_release_notes.js" not in release_verifier:
        fail("verify-client-release.py must require scripts/verify_admin_release_notes.js")
    if "scripts\\verify_project_board_unmatched_review.js" not in build_script:
        fail("build-client-release.ps1 must copy scripts\\verify_project_board_unmatched_review.js")
    if "scripts/verify_project_board_unmatched_review.js" not in release_verifier:
        fail("verify-client-release.py must require scripts/verify_project_board_unmatched_review.js")
    if "scripts\\verify_dialog_information_integration.js" not in build_script:
        fail("build-client-release.ps1 must copy scripts\\verify_dialog_information_integration.js")
    if "scripts/verify_dialog_information_integration.js" not in release_verifier:
        fail("verify-client-release.py must require scripts/verify_dialog_information_integration.js")
    for path in [
        "docs/sop/01-demand-intake-and-priority.md",
        "docs/sop/02-production-branch-versioning.md",
        "docs/sop/03-change-analysis-and-tdd.md",
        "docs/sop/04-subagent-review-template.md",
        "docs/sop/05-release-package-and-hash.md",
        "docs/sop/06-production-deploy-runbook.md",
        "docs/sop/07-rollback-and-incident-review.md",
        "docs/sop/08-business-acceptance-templates.md",
        "ops/releases/V3.0.79.md",
        "ops/releases/V3.0.78.md",
        "ops/releases/V3.0.77.md",
        "ops/releases/V3.0.76.md",
        "ops/releases/V3.0.75.md",
        "ops/releases/V3.0.74.md",
        "ops/releases/V3.0.73.md",
        "ops/releases/V3.0.72.md",
        "ops/releases/V3.0.71.md",
        "ops/releases/V3.0.70.md",
        "ops/releases/V3.0.69.md",
        "ops/releases/V3.0.68.md",
        "ops/releases/V3.0.67.md",
        "ops/releases/V3.0.66.md",
        "ops/releases/V3.0.65.md",
        "ops/releases/V3.0.64.md",
        "ops/releases/V3.0.63.md",
        "ops/releases/V3.0.62.md",
        "ops/releases/V3.0.61.md",
        "ops/releases/V3.0.60.md",
        "ops/releases/V3.0.59.md",
        "ops/releases/V3.0.58.md",
        "ops/releases/V3.0.56.md",
        "ops/releases/V3.0.55.md",
        "ops/releases/V3.0.54.md",
        "ops/releases/V3.0.53.md",
        "ops/releases/V3.0.52.md",
        "ops/releases/V3.0.51.md",
        "ops/releases/V3.0.50.md",
        "ops/releases/V3.0.49.md",
        "ops/releases/V3.0.48.md",
        "ops/releases/V3.0.47.md",
        "ops/releases/V3.0.45.md",
        "ops/releases/V3.0.46.md",
        "ops/releases/V3.0.44.md",
        "ops/releases/V3.0.42.md",
        "ops/releases/V3.0.41.md",
        "ops/releases/V3.0.40.md",
        "ops/releases/V3.0.39.md",
        "ops/releases/V3.0.38.md",
        "ops/releases/V3.0.37.md",
    ]:
        if path not in release_verifier:
            fail(f"verify-client-release.py must require {path}")

    stale_sop_hits = [
        path
        for path in [
            "docs/sop/README.md",
            "docs/sop/02-production-branch-versioning.md",
            "docs/sop/05-release-package-and-hash.md",
            "docs/sop/06-production-deploy-runbook.md",
        ]
        if "3.0.38" in read(path) or "V3.0.38" in read(path)
    ]
    if stale_sop_hits:
        fail("SOP files must not keep stale V3.0.38 deployment examples: " + ", ".join(stale_sop_hits))

    agents = read("AGENTS.md")
    if deployed_production_baseline(agents) != "V3.0.79":
        fail("AGENTS.md deployed production baseline must be V3.0.79 before deployment")
    if release_candidate(agents) != "V3.0.80":
        fail("AGENTS.md release candidate must be V3.0.80")
    if "ops/releases" not in agents:
        fail("AGENTS.md must reference production release records")

    v3080_record = read("ops/releases/V3.0.80.md")
    if release_record_status(v3080_record).casefold() != "pending":
        fail("V3.0.80 release record status must remain explicitly pending before deployment")
    if release_record_claims_deployed_without_live_evidence(v3080_record):
        fail("V3.0.80 release record claims deployed without complete live evidence")

    manifest = read("RELEASE_MANIFEST.md")
    if "3.0.80" not in manifest:
        fail("Root RELEASE_MANIFEST.md must be aligned to 3.0.80")

    retention_runbook = read("docs/sop/06-production-deploy-runbook.md")
    for text in ["Production Release Retention", "cleanup_old_releases.sh", "keep 5", "--dry-run"]:
        if text not in retention_runbook:
            fail(f"deploy runbook must document release retention: {text}")

    print("[OK] release SOP files and references are consistent")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
