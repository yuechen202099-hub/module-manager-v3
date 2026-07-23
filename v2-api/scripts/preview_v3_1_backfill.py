from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import select


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal  # noqa: E402
from app.models import GroupStatus, MaterialGroup, Photo  # noqa: E402
from app.services.final_delivery_export import collect_delivery_validation_errors  # noqa: E402
from app.services.group_barcode_verification import (  # noqa: E402
    evaluate_group_eligibility,
    normalize_verification_group_identity,
)
from app.services.local_simulation import (  # noqa: E402
    CONSTRUCTION_SLOT_CATEGORIES,
    is_valid_photo_evidence,
    normalize_construction_slot,
)
from scripts.backfill_construction_photo_categories import (  # noqa: E402
    backfill_construction_photo_categories,
)


def _value(item: Any, name: str, default: Any = "") -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _status_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _photo_slot(photo: Any) -> str:
    raw = dict(_value(photo, "raw_data", {}) or {})
    return normalize_construction_slot(raw.get("construction_slot") or raw.get("slot"))


def _group_is_archived(group: Any) -> bool:
    raw = dict(_value(group, "raw_data", {}) or {})
    return _value(group, "status") == GroupStatus.APPROVED or str(raw.get("status") or "").strip().lower() in {
        "approved",
        "archived",
    }


def _projected_photo(photo: Any, category: str) -> dict[str, Any]:
    raw = dict(_value(photo, "raw_data", {}) or {})
    raw.update(
        {
            "id": str(_value(photo, "legacy_id") or _value(photo, "id")),
            "sha256": str(_value(photo, "sha256") or raw.get("sha256") or "").strip().lower(),
            "category": category,
            "construction_slot": _photo_slot(photo),
            "is_active": bool(_value(photo, "is_active", True)),
            "upload_status": _status_value(_value(photo, "upload_status", "uploaded")),
            "archive_status": _status_value(_value(photo, "archive_status", raw.get("archive_status", ""))),
            "original_filename": str(_value(photo, "original_filename", raw.get("original_filename", "")) or ""),
            "collector": str(_value(photo, "collector", raw.get("collector", "")) or ""),
            "module_asset_no": str(_value(photo, "asset_no", raw.get("module_asset_no", "")) or ""),
        }
    )
    return raw


def project_backfill_groups(groups: Iterable[Any], photos: Iterable[Any]) -> list[dict[str, Any]]:
    """Project candidate category changes in memory without mutating ORM rows."""

    materialized_groups = list(groups)
    materialized_photos = list(photos)
    slot_counts = Counter(
        (str(_value(photo, "group_id")), _photo_slot(photo))
        for photo in materialized_photos
        if is_valid_photo_evidence(photo) and _photo_slot(photo) in CONSTRUCTION_SLOT_CATEGORIES
    )
    group_order: list[str] = []
    projected_groups: dict[str, dict[str, Any]] = {}
    source_groups: dict[str, Any] = {}
    for group in materialized_groups:
        group_key = str(_value(group, "id"))
        raw = dict(_value(group, "raw_data", {}) or {})
        raw.update(
            {
                "id": str(_value(group, "legacy_id") or group_key),
                "terminal": str(_value(group, "terminal", raw.get("terminal", "")) or ""),
                "meter_no": str(_value(group, "display_meter_no", raw.get("meter_no", "")) or ""),
                "address": str(_value(group, "installation_address", raw.get("address", "")) or ""),
                "status": "archived" if _group_is_archived(group) else _status_value(_value(group, "status")),
                "photos": [],
            }
        )
        projected_groups[group_key] = raw
        source_groups[group_key] = group
        group_order.append(group_key)

    for photo in materialized_photos:
        group_key = str(_value(photo, "group_id"))
        group = source_groups.get(group_key)
        if group is None:
            continue
        category = str(_value(photo, "category", "unclassified") or "unclassified")
        slot = _photo_slot(photo)
        is_candidate = (
            bool(_value(photo, "is_active", True))
            and is_valid_photo_evidence(photo)
            and not _group_is_archived(group)
            and category == "unclassified"
            and not str(_value(photo, "classified_by", "") or "").strip()
            and slot in CONSTRUCTION_SLOT_CATEGORIES
            and slot != "other"
            and slot_counts[(group_key, slot)] == 1
        )
        projected_groups[group_key]["photos"].append(_projected_photo(photo, slot if is_candidate else category))
    return [normalize_verification_group_identity(projected_groups[key]) for key in group_order]


def load_projected_groups(session: Any, *, team_id: str = "") -> list[dict[str, Any]]:
    """Load every selected group and all of their photos in two bulk queries."""

    group_statement = select(MaterialGroup)
    if team_id:
        group_statement = group_statement.where(MaterialGroup.team_id == team_id)
    groups = list(session.scalars(group_statement.order_by(MaterialGroup.id)).all())
    if not groups:
        return []

    group_ids = [_value(group, "id") for group in groups]
    photo_statement = (
        select(Photo)
        .where(Photo.group_id.in_(group_ids))
        .order_by(Photo.group_id, Photo.sort_order, Photo.id)
    )
    photos = list(session.scalars(photo_statement).all())
    return project_backfill_groups(groups, photos)


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
    projected_groups = [group for group in report.get("projected_groups", []) if isinstance(group, Mapping)]
    eligibility_reasons: Counter[str] = Counter()
    queueable = 0
    for group in projected_groups:
        eligibility = evaluate_group_eligibility(group)
        if eligibility.status == "pending":
            queueable += 1
        else:
            eligibility_reasons[str(eligibility.reason or "not_eligible")] += 1
    export_errors = collect_delivery_validation_errors(projected_groups, require_cache=True)
    export_error_reasons = Counter(str(error.get("code") or "unknown") for error in export_errors)
    source = {key: value for key, value in report.items() if key != "projected_groups"}
    return {
        "mode": str(report.get("mode") or "preview"),
        "classification_backfilled": int(report.get("updated") or report.get("candidates") or 0),
        "backfilled": int(report.get("updated") or report.get("candidates") or 0),
        "conflicts": conflicts,
        "skipped": skipped,
        "queueable": queueable,
        "queueable_reasons": {"eligible": queueable} if queueable else {},
        "unscannable": sum(eligibility_reasons.values()),
        "unscannable_reasons": dict(sorted(eligibility_reasons.items())),
        "estimated_export_errors": len(export_errors),
        "estimated_export_error_reasons": dict(sorted(export_error_reasons.items())),
        "source": source,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview V3.1 category backfill and delivery readiness without writes.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--preview", dest="mode", action="store_const", const="preview", default="preview", help="Read-only preview (default)."
    )
    mode.add_argument("--apply", dest="mode", action="store_const", const="apply", help="Apply the category backfill.")
    parser.add_argument("--team-id", default="", help="Limit the preview or apply operation to one team.")
    parser.add_argument("--actor", default="v3-1-category-backfill", help="Audit actor used only with --apply.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    apply_changes = args.mode == "apply"
    with SessionLocal() as session:
        projected_groups = load_projected_groups(session, team_id=args.team_id)
        source_report = backfill_construction_photo_categories(
            session,
            apply_changes=apply_changes,
            actor=args.actor,
            team_id=args.team_id,
        )
        source_report["projected_groups"] = projected_groups
    print(json.dumps(summarize_preview(source_report), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
