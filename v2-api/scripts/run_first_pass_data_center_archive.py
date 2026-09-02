"""Run the single controlled archive pass after deploying the two-state archive rule.

Usage (from v2-api):
    python scripts/run_first_pass_data_center_archive.py --team-id <team> --confirm
"""

from __future__ import annotations

import argparse
import json

from app.services import local_simulation
from app.services.state_repository import get_state_repository


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive all currently eligible data-center groups once.")
    parser.add_argument("--team-id", required=True, help="Target project/team identifier")
    parser.add_argument("--confirm", action="store_true", help="Required acknowledgement for the write operation")
    arguments = parser.parse_args()
    if not arguments.confirm:
        parser.error("This writes archive state. Re-run with --confirm after checking the target team.")

    token = local_simulation.set_current_team(arguments.team_id)
    try:
        result = get_state_repository().first_pass_archive_data_center_groups()
    finally:
        local_simulation.reset_current_team(token)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
