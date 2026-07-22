from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal  # noqa: E402
from app.models import GroupStatus, MaterialGroup, Photo  # noqa: E402
from app.services.local_simulation import (  # noqa: E402
    CONSTRUCTION_SLOT_CATEGORIES,
    PHOTO_CATEGORIES,
    normalize_construction_slot,
)
from app.services.state_repository import (  # noqa: E402
    _stage_transactional_audit,
    invalidate_verification_for_group,
)


def _group_is_archived(group: MaterialGroup) -> bool:
    raw_status = str((group.raw_data or {}).get("status") or "").strip().lower()
    return group.status == GroupStatus.APPROVED or raw_status in {"approved", "archived"}


def _photo_slot(photo: Photo) -> str:
    raw = dict(photo.raw_data or {})
    return normalize_construction_slot(raw.get("construction_slot") or raw.get("slot"))


def backfill_construction_photo_categories(
    session: Session,
    *,
    apply_changes: bool = False,
    actor: str = "construction-category-backfill",
    team_id: str = "",
) -> dict[str, Any]:
    statement = select(Photo, MaterialGroup).join(MaterialGroup, MaterialGroup.id == Photo.group_id)
    if team_id:
        statement = statement.where(Photo.team_id == team_id)
    rows = list(session.execute(statement.order_by(Photo.group_id, Photo.sort_order, Photo.id)).all())
    slot_counts = Counter(
        (str(group.id), _photo_slot(photo))
        for photo, group in rows
        if bool(photo.is_active) and _photo_slot(photo) in CONSTRUCTION_SLOT_CATEGORIES
    )
    report = {
        "mode": "apply" if apply_changes else "preview",
        "candidates": 0,
        "updated": 0,
        "skipped_manual_category": 0,
        "skipped_conflict": 0,
        "skipped_archived_group": 0,
        "skipped_inactive": 0,
        "skipped_invalid_slot": 0,
        "affected_groups": 0,
    }
    candidates: list[tuple[Photo, MaterialGroup, str]] = []
    affected_groups: dict[str, MaterialGroup] = {}
    for photo, group in rows:
        if not bool(photo.is_active):
            report["skipped_inactive"] += 1
            continue
        if _group_is_archived(group):
            report["skipped_archived_group"] += 1
            continue
        if str(photo.category or "unclassified") != "unclassified" or str(photo.classified_by or "").strip():
            report["skipped_manual_category"] += 1
            continue
        slot = _photo_slot(photo)
        if slot not in CONSTRUCTION_SLOT_CATEGORIES or slot == "other":
            report["skipped_invalid_slot"] += 1
            continue
        if slot_counts[(str(group.id), slot)] > 1:
            report["skipped_conflict"] += 1
            continue
        candidates.append((photo, group, slot))
        affected_groups[str(group.id)] = group

    report["candidates"] = len(candidates)
    report["affected_groups"] = len(affected_groups)
    if not apply_changes:
        session.rollback()
        return report

    now = datetime.now(UTC)
    for photo, group, category in candidates:
        previous_category = str(photo.category or "unclassified")
        photo.category = category
        photo.classified_by = actor
        photo.classified_at = now
        raw = dict(photo.raw_data or {})
        raw.update(
            {
                "category": category,
                "category_label": PHOTO_CATEGORIES[category],
                "classified_by": actor,
                "classified_at": now.isoformat(),
            }
        )
        photo.raw_data = raw
        _stage_transactional_audit(
            session,
            team_id=group.team_id,
            actor=actor,
            action="photo_category_corrected",
            entity_type="photo",
            entity_id=photo.id,
            before_data={"category": previous_category},
            after_data={"category": category},
            payload={
                "group_id": str(group.legacy_id or group.id),
                "photo_id": str(photo.legacy_id or photo.id),
                "previous_category": previous_category,
                "next_category": category,
                "invalidation_reason": "construction_category_backfill",
            },
        )
        report["updated"] += 1
    session.flush()
    for group in affected_groups.values():
        invalidate_verification_for_group(
            session,
            group,
            actor=actor,
            reason="construction_category_backfill",
        )
    session.commit()
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill authoritative categories from construction slots.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preview", action="store_true", help="Preview changes without writing (default).")
    mode.add_argument("--apply", action="store_true", help="Apply changes in one transaction.")
    parser.add_argument("--team-id", default="", help="Limit the backfill to one team.")
    parser.add_argument("--actor", default="construction-category-backfill", help="Audit actor name.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with SessionLocal() as session:
        report = backfill_construction_photo_categories(
            session,
            apply_changes=bool(args.apply),
            actor=args.actor,
            team_id=args.team_id,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
