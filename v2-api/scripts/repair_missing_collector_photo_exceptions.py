from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal  # noqa: E402
from app.models import GroupStatus, MaterialGroup  # noqa: E402
from app.services.local_simulation import (  # noqa: E402
    MISSING_COLLECTOR_PHOTO_LABEL,
    MISSING_COLLECTOR_PHOTO_REASON,
)
from app.services.state_repository import _stage_transactional_audit  # noqa: E402


def _status_text(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _reason_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item).strip() for item in value if str(item).strip()}


def _candidate_skip_reason(group: MaterialGroup) -> str:
    if _reason_set(group.exception_reasons) != {MISSING_COLLECTOR_PHOTO_REASON}:
        return "not_single_reason"

    raw = dict(group.raw_data or {})
    notes = {
        str(group.exception_note or "").strip(),
        str(raw.get("exception_note") or "").strip(),
    }
    if any(note not in {"", MISSING_COLLECTOR_PHOTO_LABEL} for note in notes):
        return "nonstandard_note"

    raw_reasons = raw.get("exception_reasons")
    if raw_reasons not in (None, []) and _reason_set(raw_reasons) != {MISSING_COLLECTOR_PHOTO_REASON}:
        return "raw_mixed_reasons"
    return ""


def _repair_group(group: MaterialGroup) -> tuple[dict[str, Any], dict[str, Any], bool]:
    before = {
        "status": _status_text(group.status),
        "exception_status": str(group.exception_status or ""),
        "exception_note": str(group.exception_note or ""),
        "exception_reasons": list(group.exception_reasons or []),
        "has_archive_blocker": bool(group.has_archive_blocker),
    }
    raw = dict(group.raw_data or {})
    restored_status = group.status == GroupStatus.REJECTED

    group.exception_reasons = []
    group.has_archive_blocker = False
    if str(group.exception_note or "").strip() == MISSING_COLLECTOR_PHOTO_LABEL:
        group.exception_note = ""
    if str(group.exception_status or "").strip().lower() == "open":
        group.exception_status = ""
    if restored_status:
        group.status = GroupStatus.UNREVIEWED

    raw["exception_reasons"] = []
    if str(raw.get("exception_note") or "").strip() == MISSING_COLLECTOR_PHOTO_LABEL:
        raw["exception_note"] = ""
    if str(raw.get("exception_status") or "").strip().lower() == "open":
        raw["exception_status"] = ""
    if restored_status and str(raw.get("status") or "").strip().lower() in {"", "exception", "rejected"}:
        raw["status"] = "pending"
    group.raw_data = raw

    after = {
        "status": _status_text(group.status),
        "exception_status": str(group.exception_status or ""),
        "exception_note": str(group.exception_note or ""),
        "exception_reasons": list(group.exception_reasons or []),
        "has_archive_blocker": bool(group.has_archive_blocker),
    }
    return before, after, restored_status


def repair_missing_collector_photo_exceptions(
    session: Session,
    *,
    apply_changes: bool = False,
    actor: str = "missing-collector-photo-exception-repair",
    team_id: str = "",
    limit: int = 0,
) -> dict[str, Any]:
    statement = select(MaterialGroup).where(
        MaterialGroup.exception_reasons == [MISSING_COLLECTOR_PHOTO_REASON]
    )
    if team_id:
        statement = statement.where(MaterialGroup.team_id == team_id)
    statement = statement.order_by(MaterialGroup.updated_at.asc(), MaterialGroup.id.asc())
    if limit > 0:
        statement = statement.limit(limit)
    if apply_changes:
        statement = statement.with_for_update()

    groups = list(session.scalars(statement).all())
    report = {
        "mode": "apply" if apply_changes else "preview",
        "team_id": team_id,
        "scanned": len(groups),
        "candidates": 0,
        "updated": 0,
        "status_restored": 0,
        "skipped_not_single_reason": 0,
        "skipped_nonstandard_note": 0,
        "skipped_raw_mixed_reasons": 0,
    }
    candidates: list[MaterialGroup] = []
    for group in groups:
        skip_reason = _candidate_skip_reason(group)
        if skip_reason:
            report[f"skipped_{skip_reason}"] += 1
            continue
        candidates.append(group)
    report["candidates"] = len(candidates)

    if not apply_changes:
        session.rollback()
        return report

    for group in candidates:
        before, after, restored_status = _repair_group(group)
        _stage_transactional_audit(
            session,
            team_id=str(group.team_id or ""),
            actor=actor,
            action="missing_collector_photo_exception_repaired",
            entity_type="material_group",
            entity_id=group.id,
            before_data=before,
            after_data=after,
            payload={
                "legacy_group_id": str(group.legacy_id or ""),
                "retired_exception_reason": MISSING_COLLECTOR_PHOTO_REASON,
            },
        )
        report["updated"] += 1
        report["status_restored"] += int(restored_status)
    session.flush()
    session.commit()
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repair the retired missing-collector-photo-only exception. Preview is the default."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preview", action="store_true", help="Preview candidates without writing (default).")
    mode.add_argument("--apply", action="store_true", help="Apply repairs in one transaction.")
    parser.add_argument("--team-id", default="", help="Limit the repair to one team id.")
    parser.add_argument("--limit", type=int, default=0, help="Limit candidates for controlled rollout.")
    parser.add_argument("--actor", default="missing-collector-photo-exception-repair", help="Audit actor name.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    with SessionLocal() as session:
        report = repair_missing_collector_photo_exceptions(
            session,
            apply_changes=bool(args.apply),
            actor=args.actor,
            team_id=args.team_id.strip(),
            limit=max(args.limit, 0),
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
