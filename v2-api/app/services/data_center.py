from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any, Callable, Iterable, Mapping

from app.schemas.data_center import DataCenterQuery
from app.services.barcode_verification_contract import has_current_eligible_photo_set


REQUIRED_CLASSIFICATION_SLOTS = {"before_box", "module_meter", "after_box", "collector_barcode"}


def coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return result if result.tzinfo is not None else result.replace(tzinfo=UTC)
    except ValueError:
        return None


def datetime_sort_value(value: Any) -> float:
    result = coerce_datetime(value)
    if result is None:
        return float("-inf")
    return result.timestamp()


def _desc_text_key(value: Any) -> tuple[int, ...]:
    return tuple(-ord(char) for char in str(value or ""))


def row_order_key(row: Mapping[str, Any], sort: str) -> tuple[Any, ...]:
    if sort == "updated_asc":
        updated = coerce_datetime(row.get("updated_at"))
        return (updated is None, updated.timestamp() if updated else 0, str(row.get("id") or ""))
    if sort == "terminal_asc":
        return (str(row.get("terminal") or ""), str(row.get("id") or ""))
    updated = coerce_datetime(row.get("updated_at"))
    return (updated is None, -(updated.timestamp() if updated else 0), _desc_text_key(row.get("id")))


def date_bounds(query: DataCenterQuery) -> tuple[datetime | None, datetime | None]:
    start = datetime.combine(query.date_from, time.min, tzinfo=UTC) if query.date_from else None
    end = datetime.combine(query.date_to, time.max, tzinfo=UTC) if query.date_to else None
    return start, end


def activity_date_bounds(query: DataCenterQuery) -> tuple[datetime | None, datetime | None]:
    start = datetime.combine(query.activity_date_from, time.min, tzinfo=UTC) if query.activity_date_from else None
    end = datetime.combine(query.activity_date_to, time.max, tzinfo=UTC) if query.activity_date_to else None
    return start, end


def active_photos(group: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(photo)
        for photo in group.get("photos", []) or []
        if isinstance(photo, Mapping) and photo.get("is_active", True) is not False
    ]


def classification_summary_from_photos(photos: list[Mapping[str, Any]], photo_count: int = 0) -> dict[str, Any]:
    categories = {
        str(photo.get("category") or photo.get("construction_slot") or "").strip()
        for photo in photos
        if str(photo.get("category") or photo.get("construction_slot") or "").strip()
        and str(photo.get("category") or photo.get("construction_slot") or "").strip() != "unclassified"
    }
    total = max(photo_count, len(photos))
    classified = len(categories)
    complete = REQUIRED_CLASSIFICATION_SLOTS.issubset(categories) if photos else False
    return {
        "status": "complete" if complete else "incomplete",
        "classified_count": classified,
        "required_count": len(REQUIRED_CLASSIFICATION_SLOTS),
        "total_count": total,
        "missing_categories": sorted(REQUIRED_CLASSIFICATION_SLOTS - categories),
    }


def barcode_status_from_group(group: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    verification = group.get("barcode_verification") if isinstance(group.get("barcode_verification"), Mapping) else {}
    raw_status = str(
        verification.get("status")
        or group.get("group_barcode_check_status")
        or group.get("barcode_status")
        or ""
    ).strip()
    manual = bool(group.get("group_barcode_manual_confirmed")) or raw_status == "manual_confirmed"
    if manual:
        status = "manual_confirmed"
    elif raw_status in {"passed", "pass", "matched"}:
        status = "passed"
    elif raw_status in {"mismatch", "mismatched", "partial"}:
        status = "mismatched"
    elif raw_status == "failed":
        status = "failed"
    elif raw_status in {"unreadable", "no_barcode"}:
        status = "unreadable"
    else:
        status = "ineligible"
    result = verification.get("result") if isinstance(verification.get("result"), Mapping) else {}
    missing = group.get("group_barcode_missing_fields") or result.get("missing_fields") or []
    missing_fields = [str(item) for item in missing if str(item).strip()] if isinstance(missing, list) else []
    return status, missing_fields, {"status": raw_status or status, "manual_confirmed": manual}


def construction_status_from_group(group: Mapping[str, Any], photo_count: int) -> str:
    explicit = str(group.get("construction_status") or "").strip()
    if explicit in {"unconstructed", "in_progress", "completed"}:
        return explicit
    status = str(group.get("status") or "").strip()
    if status in {"approved", "exception", "rejected", "completed"}:
        return "completed"
    if photo_count > 0:
        return "in_progress"
    return "unconstructed"


def archive_status_from_group(group: Mapping[str, Any], photos: list[Mapping[str, Any]]) -> str:
    if photos and all(str(photo.get("archive_status") or "").strip() == "archived" for photo in photos):
        return "archived"
    if any(str(photo.get("archive_status") or "").strip() for photo in photos):
        return "pending"
    return "unarchived"


def exception_status_from_group(group: Mapping[str, Any]) -> str:
    explicit = str(group.get("exception_status") or "").strip()
    if explicit:
        return explicit
    if str(group.get("status") or "").strip() in {"exception", "rejected"} or bool(group.get("has_archive_blocker")):
        return "open"
    return ""


def group_row(group: Mapping[str, Any]) -> dict[str, Any]:
    photos = active_photos(group)
    photo_count = int(group.get("photo_count") or 0)
    classification = (
        dict(group.get("classification_progress") or {})
        if isinstance(group.get("classification_progress"), Mapping)
        else classification_summary_from_photos(photos, photo_count)
    )
    if "status" not in classification:
        classification["status"] = str(group.get("classification_status") or "incomplete")
    barcode_status, missing_fields, barcode_progress = barcode_status_from_group(group)
    return {
        "kind": "group",
        "id": str(group.get("id") or group.get("legacy_id") or "").strip(),
        "terminal": str(group.get("terminal") or "").strip(),
        "meter_no": str(group.get("meter_no") or group.get("display_meter_no") or "").strip(),
        "meter_match_key": str(group.get("meter_match_key") or "").strip(),
        "address": str(group.get("address") or group.get("installation_address") or "").strip(),
        "collector": str(group.get("collector") or "").strip(),
        "module_asset_no": str(group.get("module_asset_no") or group.get("asset_no") or "").strip(),
        "construction_collector": str(group.get("construction_collector") or "").strip(),
        "construction_module_asset_no": str(group.get("construction_module_asset_no") or "").strip(),
        "installer": str(group.get("installer") or group.get("constructor") or group.get("creator") or "").strip(),
        "photo_count": photo_count,
        "classification_status": classification["status"],
        "classification_progress": classification,
        "barcode_status": barcode_status,
        "barcode_progress": barcode_progress,
        "group_barcode_missing_fields": missing_fields,
        "construction_status": construction_status_from_group(group, photo_count),
        "archive_status": archive_status_from_group(group, photos),
        "exception_status": exception_status_from_group(group),
        "updated_at": group.get("updated_at") or group.get("last_photo_imported_at") or "",
    }


def unmatched_row(record: Mapping[str, Any]) -> dict[str, Any]:
    photos = record.get("photos") or record.get("photo_urls") or []
    photo_count = len(photos) if isinstance(photos, list) else int(record.get("photo_count") or 0)
    return {
        "kind": "unmatched",
        "id": str(record.get("unmatched_id") or record.get("id") or record.get("legacy_id") or "").strip(),
        "terminal": str(record.get("terminal") or "").strip(),
        "meter_no": str(record.get("meter_no") or record.get("barcode") or "").strip(),
        "meter_match_key": str(record.get("meter_match_key") or "").strip(),
        "address": str(record.get("address") or "").strip(),
        "collector": str(record.get("collector") or "").strip(),
        "module_asset_no": str(record.get("module_asset_no") or record.get("asset_no") or "").strip(),
        "construction_collector": "",
        "construction_module_asset_no": "",
        "installer": str(record.get("assigned_to") or record.get("creator") or "").strip(),
        "photo_count": photo_count,
        "classification_status": "incomplete",
        "classification_progress": {"status": "incomplete", "classified_count": 0, "required_count": 4},
        "barcode_status": "ineligible",
        "barcode_progress": {"status": "ineligible"},
        "group_barcode_missing_fields": [],
        "construction_status": "in_progress" if str(record.get("assigned_to") or "").strip() else "unconstructed",
        "archive_status": "unarchived",
        "exception_status": str(record.get("status") or "").strip(),
        "updated_at": record.get("updated_at") or record.get("assigned_at") or "",
    }


def row_matches_query(row: Mapping[str, Any], keyword: str) -> bool:
    needle = keyword.strip().lower()
    if not needle:
        return True
    haystack = " ".join(str(value or "") for value in row.values()).lower()
    return all(term in haystack for term in needle.split())


def _matches_barcode_filter(actual: str, requested: str) -> bool:
    if requested == "all":
        return True
    if requested == "verified":
        return actual in {"passed", "manual_confirmed"}
    if requested == "needs_review":
        return actual in {"mismatched", "failed", "unreadable"}
    return actual == requested


def row_passes_filters(row: Mapping[str, Any], query: DataCenterQuery) -> bool:
    if query.data_type != "all" and row.get("kind") != query.data_type:
        return False
    for attr, requested in (
        ("construction_status", query.construction_status),
        ("archive_status", query.archive_status),
        ("classification_status", query.classification_status),
    ):
        if requested != "all" and row.get(attr) != requested:
            return False
    if query.has_photos and int(row.get("photo_count") or 0) <= 0:
        return False
    if query.barcode_eligibility != "all":
        eligible = bool(row.get("_barcode_eligible"))
        if query.barcode_eligibility == "eligible" and not eligible:
            return False
        if query.barcode_eligibility == "ineligible" and eligible:
            return False
    actual_barcode_status = str(row.get("barcode_status") or "").strip()
    if not _matches_barcode_filter(actual_barcode_status, query.barcode_status):
        return False
    requested_terminal_status = query.terminal_status
    actual_terminal_status = str(row.get("_terminal_status") or row.get("terminal_status") or "").strip()
    if requested_terminal_status != "all":
        if requested_terminal_status == "completed":
            if actual_terminal_status not in {"completed", "pending_archive", "archived"}:
                return False
        elif actual_terminal_status != requested_terminal_status:
            return False
    requested_exception = query.exception_status.strip()
    if requested_exception == "none":
        if str(row.get("exception_status") or "").strip():
            return False
    elif requested_exception and row.get("exception_status") != requested_exception:
        return False
    if query.installer.strip():
        if query.installer_source == "photo":
            if not row.get("_installer_photo_source_match"):
                return False
        elif query.installer.strip().lower() not in str(row.get("installer") or "").lower():
            return False
    if query.terminal.strip() and query.terminal.strip().lower() not in str(row.get("terminal") or "").lower():
        return False
    if not row_matches_query(row, query.query):
        return False
    start, end = date_bounds(query)
    updated = coerce_datetime(row.get("updated_at"))
    if start and (not updated or updated < start):
        return False
    if end and (not updated or updated > end):
        return False
    activity_start, activity_end = activity_date_bounds(query)
    if activity_start or activity_end:
        activity_at = coerce_datetime(row.get("_activity_at") or row.get("activity_at"))
        if activity_start and (not activity_at or activity_at < activity_start):
            return False
        if activity_end and (not activity_at or activity_at > activity_end):
            return False
    return True


def sort_rows(rows: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: row_order_key(row, sort))


def select_bounded_page(
    raw_items: Iterable[Any],
    query: DataCenterQuery,
    mapper: Callable[[Any], dict[str, Any]],
    *,
    on_retained_size: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    start = (query.page - 1) * query.page_size
    retained_limit = start + query.page_size
    total = 0
    retained: list[dict[str, Any]] = []
    for raw_item in raw_items:
        row = mapper(raw_item)
        if not row_passes_filters(row, query):
            continue
        total += 1
        retained.append(row)
        retained.sort(key=lambda item: row_order_key(item, query.sort))
        if len(retained) > retained_limit:
            retained.pop()
        if on_retained_size is not None:
            on_retained_size(len(retained))
    return {
        "total": total,
        "page": query.page,
        "page_size": query.page_size,
        "items": retained[start : start + query.page_size],
    }


def page_rows(rows: list[dict[str, Any]], query: DataCenterQuery) -> dict[str, Any]:
    return select_bounded_page(rows, query, lambda row: row)
