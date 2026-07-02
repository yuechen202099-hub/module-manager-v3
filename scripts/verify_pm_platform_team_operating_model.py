from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEAM_MEMORY = ROOT / "docs/PM_PLATFORM_TEAM_DEVELOPMENT.md"
PLAN = ROOT / "docs/superpowers/plans/2026-07-02-team-operating-model-lock.md"


REQUIRED_TEAM_STRINGS = [
    "Context-Stable Team Contract",
    "Codex Integrator remains the single project manager",
    "Agent Dispatch Packet Template",
    "Two-Stage Review Gate",
    "Spec compliance review",
    "Code quality review",
    "Backend Team Split Contract",
    "Frontend Team Split Contract",
    "Next Execution Queue",
    "No production database migration may start without explicit user approval.",
    "no tag, no deploy, no official version bump",
    "codebase-memory-mcp",
]


REQUIRED_PLAN_STRINGS = [
    "Team Operating Model Lock Implementation Plan",
    "verify_pm_platform_team_operating_model.py",
    "Agent Dispatch Packet Template",
    "Two-Stage Review Gate",
    "Next Execution Queue",
]


def read_text(path: Path) -> str:
    if not path.exists():
        raise AssertionError(f"missing required file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def assert_contains(text: str, required: list[str], label: str) -> None:
    missing = [item for item in required if item not in text]
    if missing:
        raise AssertionError(f"{label} missing required content: {', '.join(missing)}")


def main() -> int:
    try:
        assert_contains(read_text(TEAM_MEMORY), REQUIRED_TEAM_STRINGS, "team memory")
        assert_contains(read_text(PLAN), REQUIRED_PLAN_STRINGS, "team operating plan")
    except AssertionError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    print("[OK] PM platform team operating model is locked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
