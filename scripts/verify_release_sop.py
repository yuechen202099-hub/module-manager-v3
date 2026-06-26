from __future__ import annotations

import sys
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
    "ops/releases/V3.0.37.md",
    "ops/incidents/P0-template.md",
    "scripts/production_backup.sh",
    "scripts/production_health_check.py",
]


def fail(message: str) -> None:
    raise AssertionError(message)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


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
    for path in [
        "docs/sop/01-demand-intake-and-priority.md",
        "docs/sop/02-production-branch-versioning.md",
        "docs/sop/03-change-analysis-and-tdd.md",
        "docs/sop/04-subagent-review-template.md",
        "docs/sop/05-release-package-and-hash.md",
        "docs/sop/06-production-deploy-runbook.md",
        "docs/sop/07-rollback-and-incident-review.md",
        "docs/sop/08-business-acceptance-templates.md",
        "ops/releases/V3.0.37.md",
    ]:
        if path not in release_verifier:
            fail(f"verify-client-release.py must require {path}")

    agents = read("AGENTS.md")
    if "V3.0.37" not in agents:
        fail("AGENTS.md must state current production baseline V3.0.37")
    if "ops/releases" not in agents:
        fail("AGENTS.md must reference production release records")

    manifest = read("RELEASE_MANIFEST.md")
    if "3.0.37" not in manifest:
        fail("Root RELEASE_MANIFEST.md must be aligned to 3.0.37")

    print("[OK] release SOP files and references are consistent")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
