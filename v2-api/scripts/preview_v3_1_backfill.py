from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal  # noqa: E402
from scripts.backfill_construction_photo_categories import (  # noqa: E402
    backfill_construction_photo_categories,
)


def summarize_preview(report: dict[str, Any]) -> dict[str, Any]:
    """Translate the category-backfill report into the V3.1 release preview contract."""

    skipped = sum(
        int(report.get(key) or 0)
        for key in (
            "skipped_manual_category",
            "skipped_archived_group",
            "skipped_inactive",
            "skipped_invalid_upload",
            "skipped_invalid_slot",
        )
    )
    conflicts = int(report.get("skipped_conflict") or 0)
    unscannable = conflicts + int(report.get("skipped_invalid_upload") or 0) + int(
        report.get("skipped_invalid_slot") or 0
    )
    return {
        "mode": str(report.get("mode") or "preview"),
        "classification_backfilled": int(report.get("updated") or report.get("candidates") or 0),
        "backfilled": int(report.get("updated") or report.get("candidates") or 0),
        "conflicts": conflicts,
        "skipped": skipped,
        "queueable": int(report.get("affected_groups") or 0),
        "unscannable": unscannable,
        "estimated_export_errors": conflicts
        + int(report.get("skipped_archived_group") or 0)
        + int(report.get("skipped_invalid_upload") or 0)
        + int(report.get("skipped_invalid_slot") or 0),
        "source": report,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview V3.1 category backfill and delivery readiness without writes.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--preview", dest="mode", action="store_const", const="preview", default="preview", help="Read-only preview (default)."
    )
    mode.add_argument("--apply", dest="mode", action="store_const", const="apply", help="Apply the category backfill.")
    parser.add_argument("--team-id", default="", help="Limit the preview or apply operation to one team.")
    parser.add_argument("--actor", default="v3-1-category-backfill", help="Audit actor used only with --apply.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    apply_changes = args.mode == "apply"
    with SessionLocal() as session:
        source_report = backfill_construction_photo_categories(
            session,
            apply_changes=apply_changes,
            actor=args.actor,
            team_id=args.team_id,
        )
    print(json.dumps(summarize_preview(source_report), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
