from __future__ import annotations

import logging
import re
import hashlib
import json
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import String, and_, case, cast, func, literal, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import SessionLocal
from app.models import (
    AuditLog,
    ExceptionItem,
    ExceptionStatus,
    GroupStatus,
    MaterialGroup,
    Photo,
    Project,
    ProjectStatus,
    StageCatalogRow,
    Task,
    TaskStatus,
    Team,
    TotalCatalogRow,
    UnmatchedRecord,
)
from app.services import account_store
from app.services import local_simulation, photo_barcode_check


logger = logging.getLogger(__name__)

REVIEWABLE_STATUSES = {"pending", "incomplete", "approved", "exception", "unmatched"}
OPEN_STATUSES = {"pending", "incomplete", "unmatched"}
MAX_ACTIVE_CONSTRUCTION_TASKS_PER_CONSTRUCTOR = 5
LOCAL_WORK_TZ = timezone(timedelta(hours=8))
MISSING_MODULE_ASSET_REASON = "\u7f3a\u5c11\u6a21\u5757\u8d44\u4ea7\u7f16\u53f7"
INSUFFICIENT_GROUP_PHOTO_REASON = "\u8d44\u6599\u7ec4\u7167\u7247\u4e0d\u8db3 4 \u5f20"
MISSING_COLLECTOR_INFO_REASON = "\u7f3a\u5c11\u91c7\u96c6\u5668\u4fe1\u606f"
MODULE_DUPLICATE_REASON_PREFIX = "\u6a21\u5757\u53f7\u91cd\u590d"


class StateBackendNotReady(RuntimeError):
    """Raised when the selected state backend cannot safely serve the operation."""


def _status_value(value: Any) -> str:
    return getattr(value, "value", str(value or ""))


def _legacy_task_status(task: Task) -> str:
    status = _status_value(task.status)
    if status == TaskStatus.CLAIMED.value:
        return "in_review"
    return status


def _legacy_group_status(group: MaterialGroup) -> str:
    raw_status = (group.raw_data or {}).get("status")
    if raw_status in {"pending", "incomplete", "approved", "exception", "unmatched", "unreviewed"}:
        return str(raw_status)
    status = _status_value(group.status)
    if status == GroupStatus.UNREVIEWED.value:
        return "pending"
    if status == GroupStatus.REJECTED.value:
        return "exception"
    return status


def _date_key_from_value(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) >= 10 and re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return ""


def _datetime_from_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        if re.fullmatch(r"\d+(?:\.\d+)?", text):
            number = float(text)
            if 25569 <= number <= 60000:
                result = datetime(1899, 12, 30) + timedelta(days=number)
            elif number > 10_000_000_000:
                result = datetime.fromtimestamp(number / 1000, tz=UTC)
            elif number > 1_000_000_000:
                result = datetime.fromtimestamp(number, tz=UTC)
            else:
                return None
        else:
            normalized = text.replace("Z", "+00:00").replace("/", "-")
            if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}", normalized):
                normalized = normalized.replace(" ", "T", 1)
            try:
                result = datetime.fromisoformat(normalized)
            except ValueError:
                return None
    if result.tzinfo is not None:
        return result.astimezone(LOCAL_WORK_TZ).replace(tzinfo=None)
    return result


def _photo_is_construction_upload(photo: Photo) -> bool:
    raw = photo.raw_data or {}
    source_text = " ".join(
        str(value or "")
        for value in (photo.source, raw.get("upload_source"), raw.get("storage_source"), raw.get("source_file"))
    ).lower()
    return "construction" in source_text


def _photo_work_date_key(photo: Photo) -> str:
    raw = photo.raw_data or {}
    if _photo_is_construction_upload(photo):
        return (
            _date_key_from_value(raw.get("client_completed_at"))
            or _date_key_from_value(raw.get("construction_completed_at"))
            or _date_key_from_value(photo.created_at)
        )
    for key in (
        "scan_created_at",
        "source_created_at",
        "created_at",
        "\u521b\u5efa\u65f6\u95f4",
        "scan_time",
        "scanned_at",
        "taken_at",
        "classified_at",
    ):
        date_key = _date_key_from_value(raw.get(key))
        if date_key:
            return date_key
    if photo.taken_at:
        return _date_key_from_value(photo.taken_at)
    return _date_key_from_value(photo.created_at)


def _photo_work_datetime(photo: Photo) -> datetime | None:
    raw = photo.raw_data or {}
    if _photo_is_construction_upload(photo):
        return (
            _datetime_from_value(raw.get("client_completed_at"))
            or _datetime_from_value(raw.get("construction_completed_at"))
            or _datetime_from_value(photo.created_at)
            or _datetime_from_value(raw.get("downloaded_at"))
        )
    for key in (
        "scan_created_at",
        "source_created_at",
        "created_at",
        "\u521b\u5efa\u65f6\u95f4",
        "scan_time",
        "scanned_at",
        "taken_at",
        "classified_at",
    ):
        value = _datetime_from_value(raw.get(key))
        if value:
            return value
    return _datetime_from_value(photo.taken_at) or _datetime_from_value(photo.created_at)


def _photo_confirmed_non_idle_datetime(photo: Photo) -> datetime | None:
    raw = photo.raw_data or {}
    if _photo_is_construction_upload(photo):
        return _datetime_from_value(raw.get("client_completed_at")) or _datetime_from_value(
            raw.get("construction_completed_at")
        )
    return _photo_work_datetime(photo)


def _photo_construction_slot(photo: Photo) -> str:
    raw = photo.raw_data or {}
    for value in (raw.get("construction_slot"), raw.get("slot"), photo.category):
        slot = local_simulation.normalize_construction_slot(value)
        if slot and slot != "other":
            return slot
    return ""


def _photo_dict_construction_slot(photo: dict[str, Any]) -> str:
    return local_simulation.normalize_construction_slot(
        photo.get("slot") or photo.get("construction_slot") or photo.get("category")
    )


def _group_active_photo_slots(session: Session, group: MaterialGroup, *, exclude_photo_id: Any | None = None) -> set[str]:
    statement = select(Photo).where(
        Photo.team_id == group.team_id,
        Photo.group_id == group.id,
        Photo.is_active.is_(True),
    )
    if exclude_photo_id is not None:
        statement = statement.where(Photo.id != exclude_photo_id)
    slots: set[str] = set()
    for photo in session.scalars(statement).all():
        slot = _photo_construction_slot(photo)
        if slot and slot != "other":
            slots.add(slot)
    return slots


def _validate_construction_upload_required_slots(
    session: Session,
    group: MaterialGroup,
    photos: list[dict[str, Any]],
) -> None:
    covered = _group_active_photo_slots(session, group)
    seen_sha = {
        str(value or "").strip()
        for value in session.scalars(
            select(Photo.sha256).where(
                Photo.team_id == group.team_id,
                Photo.group_id == group.id,
                Photo.is_active.is_(True),
                Photo.sha256.is_not(None),
            )
        ).all()
        if str(value or "").strip()
    }
    for item in photos:
        sha256 = str(item.get("sha256") or "").strip()
        if sha256 and sha256 in seen_sha:
            continue
        slot = _photo_dict_construction_slot(item)
        if slot and slot != "other":
            covered.add(slot)
        if sha256:
            seen_sha.add(sha256)
    missing = [slot for slot in ("before_box", "module_meter", "after_box") if slot not in covered]
    if missing:
        labels = [local_simulation.PHOTO_CATEGORIES[slot] for slot in missing]
        raise ValueError("\u7f3a\u5c11\u5fc5\u586b\u7167\u7247\uff1a" + chr(0x3001).join(labels))


def _apply_photo_quality_exception_status(
    session: Session,
    group: MaterialGroup,
    *,
    exclude_photo_id: Any | None = None,
) -> None:
    previous_reasons = {str(item).strip() for item in (group.exception_reasons or []) if str(item).strip()}
    had_missing_collector = local_simulation.MISSING_COLLECTOR_PHOTO_REASON in previous_reasons
    slots = _group_active_photo_slots(session, group, exclude_photo_id=exclude_photo_id)
    missing_collector = (
        group.photo_count > 0
        and local_simulation.CONSTRUCTION_UPLOAD_REQUIRED_SLOTS.issubset(slots)
        and "collector_barcode" not in slots
    )
    reasons = [item for item in previous_reasons if item != local_simulation.MISSING_COLLECTOR_PHOTO_REASON]
    if missing_collector:
        reasons.append(local_simulation.MISSING_COLLECTOR_PHOTO_REASON)
    group.exception_reasons = list(dict.fromkeys(reasons))
    group.has_archive_blocker = bool(group.exception_reasons)
    raw = dict(group.raw_data or {})
    if missing_collector:
        group.status = GroupStatus.REJECTED
        group.exception_status = "open"
        group.exception_note = local_simulation.MISSING_COLLECTOR_PHOTO_LABEL
        group.reviewer = None
        group.review_note = ""
        group.reviewed_at = None
        raw.update(
            {
                "status": "exception",
                "exception_note": group.exception_note,
                "exception_reasons": group.exception_reasons,
                "reviewer": "",
                "review_note": "",
                "reviewed_at": None,
            }
        )
    elif had_missing_collector and str(group.exception_note or "").strip() == local_simulation.MISSING_COLLECTOR_PHOTO_LABEL:
        group.exception_note = ""
        if not group.exception_reasons and _legacy_group_status(group) == "exception":
            group.status = GroupStatus.UNREVIEWED if group.photo_count > 0 else GroupStatus.UNREVIEWED
            group.exception_status = ""
        raw.update(
            {
                "status": _legacy_group_status(group),
                "exception_note": group.exception_note or "",
                "exception_reasons": group.exception_reasons,
            }
        )
    else:
        raw["exception_reasons"] = group.exception_reasons
    group.raw_data = raw


def _auto_archive_exception_note(note: str) -> bool:
    text = str(note or "").strip()
    if not text:
        return False
    if text in {
        MISSING_MODULE_ASSET_REASON,
        INSUFFICIENT_GROUP_PHOTO_REASON,
        MISSING_COLLECTOR_INFO_REASON,
        local_simulation.MISSING_COLLECTOR_PHOTO_REASON,
        local_simulation.MISSING_COLLECTOR_PHOTO_LABEL,
    }:
        return True
    return text.startswith(f"{MODULE_DUPLICATE_REASON_PREFIX}:")


def _has_manual_exception_marker(group: MaterialGroup) -> bool:
    raw = dict(group.raw_data or {})
    return bool(str(raw.get("exception_category") or "").strip())


def _validate_group_archive_with_module_map(
    group: dict[str, Any],
    module_groups: dict[str, set[str]],
) -> list[str]:
    photos = group.get("photos", [])
    reasons: list[str] = []
    if not photos:
        return reasons
    slots = local_simulation.group_photo_slots(group)
    missing_collector_only = (
        local_simulation.CONSTRUCTION_UPLOAD_REQUIRED_SLOTS.issubset(slots)
        and "collector_barcode" not in slots
    )
    if len(photos) < 4 and not missing_collector_only:
        reasons.append(INSUFFICIENT_GROUP_PHOTO_REASON)
    if missing_collector_only:
        reasons.append(local_simulation.MISSING_COLLECTOR_PHOTO_REASON)
    if photos and not any(str(photo.get("collector") or "").strip() for photo in photos):
        reasons.append(MISSING_COLLECTOR_INFO_REASON)
    module_asset_values = local_simulation.group_module_asset_values(group)
    if photos and not module_asset_values:
        reasons.append(MISSING_MODULE_ASSET_REASON)
    group_id = str(group.get("id") or "")
    duplicate_modules = sorted(
        {
            asset_no
            for asset_no in module_asset_values
            if len(module_groups.get(asset_no, set()) - {group_id}) > 0
        }
    )
    if duplicate_modules:
        reasons.append(f"{MODULE_DUPLICATE_REASON_PREFIX}: {', '.join(duplicate_modules[:3])}")
    return reasons


def _collect_material_group_module_map(session: Session, team_id: str) -> dict[str, set[str]]:
    module_groups: dict[str, set[str]] = defaultdict(set)
    group_ids: dict[Any, str] = {}
    groups = session.scalars(select(MaterialGroup).where(MaterialGroup.team_id == team_id)).all()
    for group in groups:
        group_id = group.legacy_id or str(group.id)
        group_ids[group.id] = group_id
        raw = group.raw_data or {}
        for value in (
            raw.get("module_asset_no"),
            raw.get("asset_no"),
            raw.get("construction_module_asset_no"),
        ):
            normalized = str(value or "").strip()
            if normalized:
                module_groups[normalized].add(group_id)
    photos = session.scalars(
        select(Photo).where(
            Photo.team_id == team_id,
            Photo.is_active.is_(True),
            Photo.asset_no.is_not(None),
        )
    ).all()
    for photo in photos:
        group_id = group_ids.get(photo.group_id)
        normalized = str(photo.asset_no or "").strip()
        if group_id and normalized:
            module_groups[normalized].add(group_id)
    return module_groups


def _refresh_group_archive_exceptions(
    session: Session,
    group: MaterialGroup,
    module_groups: dict[str, set[str]],
) -> bool:
    if _has_manual_exception_marker(group):
        return False
    payload = _group_payload(session, group, include_photos=True)
    reasons = _validate_group_archive_with_module_map(payload, module_groups)
    before_reasons = [str(item).strip() for item in (group.exception_reasons or []) if str(item).strip()]
    before_note = str(group.exception_note or "").strip()
    before = (
        tuple(before_reasons),
        before_note,
        bool(group.has_archive_blocker),
        str(group.exception_status or ""),
        _status_value(group.status),
    )
    raw = dict(group.raw_data or {})
    group.exception_reasons = reasons
    group.has_archive_blocker = bool(reasons)
    group.exception_status = "open" if reasons else None
    raw["exception_reasons"] = reasons
    if reasons:
        if not before_note or _auto_archive_exception_note(before_note):
            group.exception_note = "; ".join(local_simulation.display_exception_reasons(reasons))
            raw["exception_note"] = group.exception_note
    else:
        if _auto_archive_exception_note(before_note):
            group.exception_note = ""
            raw["exception_note"] = ""
        if group.status in {GroupStatus.INCOMPLETE, GroupStatus.REJECTED} and not group.exception_note and not group.review_note:
            group.status = GroupStatus.UNREVIEWED
            raw["status"] = "pending"
    group.raw_data = raw
    after_reasons = [str(item).strip() for item in (group.exception_reasons or []) if str(item).strip()]
    after = (
        tuple(after_reasons),
        str(group.exception_note or "").strip(),
        bool(group.has_archive_blocker),
        str(group.exception_status or ""),
        _status_value(group.status),
    )
    return before != after


def _empty_task_stats() -> dict[str, Any]:
    return {
        "total_groups": 0,
        "address": "",
        "address_search_text": "",
        "meter_search_text": "",
        "uploaded_count": 0,
        "reviewed_count": 0,
        "unreviewed_count": 0,
    }


def _task_status_signature(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _build_task_status_summary(
    rows: list[dict[str, Any]], summary: dict[str, Any] | None = None
) -> dict[str, Any]:
    total = len(rows)
    scanned = sum(1 for row in rows if int(row.get("uploaded_count") or 0) > 0)
    reviewing = sum(1 for row in rows if int(row.get("unreviewed_count") or 0) > 0)
    archived = sum(
        1
        for row in rows
        if int(row.get("uploaded_count") or 0) > 0 and int(row.get("unreviewed_count") or 0) == 0
    )
    claimed = sum(1 for row in rows if str(row.get("claimed_by") or "").strip())
    construction_assigned = sum(
        1 for row in rows if str(row.get("construction_assigned_to") or "").strip()
    )
    renovation_count = sum(int(row.get("total_groups") or 0) for row in rows)
    uploaded_count = sum(int(row.get("uploaded_count") or 0) for row in rows)
    reviewed_count = sum(int(row.get("reviewed_count") or 0) for row in rows)
    unreviewed_count = sum(int(row.get("unreviewed_count") or 0) for row in rows)
    avg_upload_rate = (
        sum(
            (int(row.get("uploaded_count") or 0) / int(row.get("total_groups") or 0))
            for row in rows
            if int(row.get("total_groups") or 0)
        )
        / total
        if total
        else 0
    )
    avg_review_rate = (
        sum(
            (int(row.get("reviewed_count") or 0) / int(row.get("total_groups") or 0))
            for row in rows
            if int(row.get("total_groups") or 0)
        )
        / total
        if total
        else 0
    )
    summary = summary or {}
    signature_source = {
        "summary": {
            "total_catalog_rows": summary.get("total_catalog_rows", 0),
            "groups": summary.get("groups", 0),
            "photo_rows_linked": summary.get("photo_rows_linked", 0),
            "approved_groups": summary.get("approved_groups", 0),
            "reviewed_groups": summary.get("reviewed_groups", 0),
            "unreviewed_groups": summary.get("unreviewed_groups", 0),
            "exception_groups": summary.get("exception_groups", 0),
        },
        "rows": sorted(rows, key=lambda row: str(row.get("id") or "")),
    }
    return {
        "version": _task_status_signature(signature_source),
        "generated_at": datetime.now(UTC).isoformat(),
        "total": total,
        "scanned": scanned,
        "uploaded": scanned,
        "reviewing": reviewing,
        "archived": archived,
        "claimed": claimed,
        "construction_assigned": construction_assigned,
        "avg_upload_rate": round(avg_upload_rate, 4),
        "avg_review_rate": round(avg_review_rate, 4),
        "renovation_count": renovation_count,
        "uploaded_count": uploaded_count,
        "reviewed_count": reviewed_count,
        "unreviewed_count": unreviewed_count,
        "total_catalog_rows": int(summary.get("total_catalog_rows") or 0),
        "groups": int(summary.get("groups") or 0),
    }


def _installer_display_name(value: Any, cache: dict[str, str] | None = None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if cache is not None and text in cache:
        return cache[text]
    display = text
    try:
        user = account_store.get_user(text)
    except ValueError:
        user = None
    if user:
        display = str(user.get("name") or user.get("username") or text).strip() or text
    if cache is not None:
        cache[text] = display
    return display


def _installer_distribution_from_counts(
    counts: dict[str, int],
    *,
    completed_count: int = 0,
    name_cache: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    resolved_name_cache = name_cache if name_cache is not None else {}
    display_counts: dict[str, int] = defaultdict(int)
    for installer, count in counts.items():
        display_name = _installer_display_name(installer, resolved_name_cache)
        if display_name and int(count or 0) > 0:
            display_counts[display_name] += int(count)
    total = max(int(completed_count or 0), sum(int(value or 0) for value in counts.values()))
    if total <= 0:
        return []
    return [
        {
            "installer": installer,
            "group_count": int(count),
            "share": round(int(count) / total, 4),
        }
        for installer, count in sorted(display_counts.items(), key=lambda item: (-int(item[1]), item[0]))
        if installer and int(count or 0) > 0
    ]


def _task_payload(task: Task, stats: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved_stats = stats or _empty_task_stats()
    total_groups = int(resolved_stats.get("total_groups", 0))
    uploaded_count = int(resolved_stats.get("uploaded_count", 0))
    reviewed_count = int(resolved_stats.get("reviewed_count", 0))
    unreviewed_count = int(resolved_stats.get("unreviewed_count", 0))
    renovation_count = total_groups
    review_rate = reviewed_count / renovation_count if renovation_count else 0
    can_claim = uploaded_count > 0
    claimed_by = task.review_claimed_by or None
    return {
        "id": task.legacy_id if task.legacy_id is not None else str(task.id),
        "terminal": task.terminal or "",
        "address": str(resolved_stats.get("address") or ""),
        "address_search_text": str(resolved_stats.get("address_search_text") or ""),
        "meter_search_text": str(resolved_stats.get("meter_search_text") or ""),
        "name": task.title,
        "status": _legacy_task_status(task),
        "claimed_by": claimed_by,
        "claimed_at": task.claimed_at.isoformat() if task.claimed_at else None,
        "released_at": task.released_at.isoformat() if task.released_at else None,
        "construction_enabled": task.construction_enabled,
        "construction_claimed_by": task.construction_claimed_by,
        "construction_claimed_at": task.construction_claimed_at.isoformat() if task.construction_claimed_at else None,
        "can_claim": can_claim,
        "has_scan_info": can_claim,
        "claim_block_reason": "" if can_claim else "Task has no scan information",
        "total_groups": total_groups,
        "renovation_count": renovation_count,
        "uploaded_count": uploaded_count,
        "reviewed_count": reviewed_count,
        "unreviewed_count": unreviewed_count,
        "review_rate": review_rate,
        "installer_distribution": resolved_stats.get("installer_distribution") or [],
    }


def _task_board_payload(task: dict[str, Any]) -> dict[str, Any]:
    payload = dict(task)
    payload["address_search_text"] = ""
    payload["meter_search_text"] = ""
    return payload


def _construction_task_payload(task: Task, stats: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = _task_payload(task, stats)
    raw = task.raw_data or {}
    assigned_constructor = task.construction_claimed_by or None
    payload.update(
        {
            "construction_enabled": task.construction_enabled,
            "construction_claimed_by": assigned_constructor,
            "construction_claimed_at": task.construction_claimed_at.isoformat()
            if task.construction_claimed_at
            else None,
            "construction_released_at": task.construction_released_at.isoformat()
            if task.construction_released_at
            else None,
            "construction_opened_by": task.construction_opened_by,
            "construction_opened_at": task.construction_opened_at.isoformat() if task.construction_opened_at else None,
            "construction_closed_at": task.construction_closed_at.isoformat() if task.construction_closed_at else None,
            "assigned_constructor": assigned_constructor,
            "assigned_at": task.construction_claimed_at.isoformat() if task.construction_claimed_at else None,
            "construction_status": "assigned"
            if task.construction_enabled and assigned_constructor
            else ("open" if task.construction_enabled else "closed"),
            "construction_assignment_note": raw.get("construction_assignment_note") or "",
            "construction_due_date": raw.get("construction_due_date") or "",
            "unconstructed_groups": max(
                int(payload.get("renovation_count") or 0) - int(payload.get("uploaded_count") or 0),
                0,
            ),
            "exception_order_count": int(raw.get("exception_order_count") or 0),
        }
    )
    return payload


def _photo_payload(photo: Photo) -> dict[str, Any]:
    image_url = photo.image_url or photo.source_url or ""
    if not image_url and (photo.storage_type or "").strip() == "oss" and photo.storage_key:
        image_url = f"oss://{photo.storage_bucket or ''}/{photo.storage_key}"
    raw = photo.raw_data or {}
    payload = {
        "id": photo.legacy_id or str(photo.id),
        "url": image_url,
        "image_url": image_url,
        "source_url": photo.source_url or photo.image_url or "",
        "storage_type": photo.storage_type or "",
        "storage_bucket": photo.storage_bucket or "",
        "storage_key": photo.storage_key or "",
        "sha256": photo.sha256,
        "category": photo.category or "unclassified",
        "category_label": raw.get("category_label")
        or local_simulation.PHOTO_CATEGORIES.get(photo.category or "unclassified", local_simulation.PHOTO_CATEGORIES["unclassified"]),
        "construction_slot": raw.get("construction_slot") or _photo_construction_slot(photo),
        "construction_slot_label": raw.get("construction_slot_label")
        or local_simulation.PHOTO_CATEGORIES.get(_photo_construction_slot(photo), ""),
        "archive_filename": photo.archive_filename or "",
        "archive_status": photo.archive_status or "",
        "sort_order": photo.sort_order,
        "barcode": photo.barcode or "",
        "collector": photo.collector or "",
        "module_asset_no": photo.asset_no or "",
        "creator": photo.creator or "",
        "upload_source": raw.get("upload_source") or raw.get("storage_source") or "",
    }
    for key in (
        "barcode_check_status",
        "barcode_check_expected_type",
        "barcode_check_values",
        "barcode_check_normalized_values",
        "barcode_check_ocr_values",
        "barcode_check_ocr_normalized_values",
        "barcode_check_expected_values",
        "barcode_check_matched_value",
        "barcode_checked_at",
        "barcode_check_error",
        "barcode_check_method",
    ):
        if key in raw:
            payload[key] = raw[key]
    return payload


def _photo_accuracy_summary_from_counts(counts: dict[str, int]) -> dict[str, Any]:
    passed = int(counts.get("matched") or 0)
    failed = int(counts.get("mismatched") or 0)
    unreadable = int(counts.get("unreadable") or 0)
    not_required = int(counts.get("not_required") or 0)
    checked = passed + failed + unreadable
    return {
        "photo_accuracy_checked": checked,
        "photo_accuracy_passed": passed,
        "photo_accuracy_failed": failed,
        "photo_accuracy_unreadable": unreadable,
        "photo_accuracy_not_required": not_required,
        "photo_accuracy_rate": round(passed / checked, 4) if checked else 0.0,
    }


def _photo_accuracy_summary(photos: list[Any]) -> dict[str, Any]:
    payloads = []
    for photo in photos:
        if isinstance(photo, dict):
            raw = photo
        else:
            raw = getattr(photo, "raw_data", {}) or {}
        payloads.append(raw)
    return photo_barcode_check.summarize_photo_accuracy(payloads)


def _row_value(row: Any, key: str, default: Any = "") -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    mapping = getattr(row, "_mapping", None)
    if mapping is not None and key in mapping:
        return mapping[key]
    return getattr(row, key, default)


def _photo_barcode_payload_from_row(row: Any) -> dict[str, Any]:
    raw = dict(_row_value(row, "raw_data", {}) or {})
    payload = {
        "id": _row_value(row, "legacy_id") or str(_row_value(row, "photo_id", "")),
        "category": _row_value(row, "category") or raw.get("category") or raw.get("construction_slot") or "unclassified",
        "barcode": _row_value(row, "barcode") or raw.get("barcode") or "",
        "collector": _row_value(row, "collector") or raw.get("collector") or "",
        "module_asset_no": _row_value(row, "asset_no") or raw.get("module_asset_no") or raw.get("asset_no") or "",
    }
    for key in (
        "barcode_check_status",
        "barcode_check_expected_type",
        "barcode_check_values",
        "barcode_check_normalized_values",
        "barcode_check_ocr_values",
        "barcode_check_ocr_normalized_values",
        "barcode_check_expected_values",
        "barcode_check_matched_value",
        "barcode_checked_at",
        "barcode_check_error",
        "barcode_check_method",
    ):
        if key in raw:
            payload[key] = raw[key]
    return payload


def _group_barcode_payload_from_row(row: Any) -> dict[str, Any]:
    raw = dict(_row_value(row, "raw_data", {}) or {})
    return {
        "id": str(_row_value(row, "group_id") or _row_value(row, "id") or ""),
        "legacy_id": _row_value(row, "legacy_id") or "",
        "task_id": _row_value(row, "legacy_task_id") or "",
        "meter_no": _row_value(row, "display_meter_no") or raw.get("meter_no") or raw.get("barcode") or "",
        "meter_match_key": _row_value(row, "meter_match_key") or raw.get("meter_match_key") or "",
        "terminal": _row_value(row, "terminal") or raw.get("terminal") or "",
        "address": _row_value(row, "installation_address") or raw.get("address") or "",
        "collector": raw.get("collector") or "",
        "module_asset_no": raw.get("module_asset_no") or raw.get("asset_no") or "",
        "asset_no": raw.get("asset_no") or raw.get("module_asset_no") or "",
        "construction_collector": raw.get("construction_collector") or "",
        "construction_module_asset_no": raw.get("construction_module_asset_no") or "",
        "group_barcode_manual_confirmed": bool(raw.get("group_barcode_manual_confirmed")),
        "group_barcode_manual_confirmed_fields": raw.get("group_barcode_manual_confirmed_fields") or [],
        "group_barcode_manual_confirmed_by": raw.get("group_barcode_manual_confirmed_by") or "",
        "group_barcode_manual_confirmed_at": raw.get("group_barcode_manual_confirmed_at") or "",
        "installer": raw.get("installer") or "",
        "creator": raw.get("creator") or "",
        "status": _row_value(row, "status") or raw.get("status") or "",
        "photo_count": int(_row_value(row, "photo_count", 0) or 0),
    }


def _group_barcode_payload(group: Any, photos: list[Any]) -> dict[str, Any]:
    if isinstance(group, dict):
        payload = dict(group)
    else:
        payload = _group_barcode_context(group)
        raw = getattr(group, "raw_data", {}) or {}
        for key in ("installer", "creator"):
            if raw.get(key):
                payload[key] = raw[key]
    photo_payloads = []
    for photo in photos:
        if isinstance(photo, dict):
            photo_payloads.append(photo)
        else:
            photo_payloads.append(_photo_payload(photo))
    payload["photos"] = photo_payloads
    return payload


def _group_photo_category_summary(photos: list[Any]) -> dict[str, Any]:
    photo_payloads = [_photo_barcode_payload_from_row(photo) if not isinstance(photo, dict) else photo for photo in photos]
    classified_count = sum(
        1
        for photo in photo_payloads
        if str(photo.get("category") or "").strip()
        and str(photo.get("category") or "").strip() != "unclassified"
    )
    total = len(photo_payloads)
    return {
        "photo_category_classified_count": classified_count,
        "photo_category_total_count": total,
        "photo_category_complete": bool(total) and classified_count == total,
    }


def _group_barcode_status_summary(group: dict[str, Any]) -> dict[str, Any]:
    check = photo_barcode_check.build_group_barcode_check(group)
    matched_fields = [str(item) for item in check.get("group_barcode_matched_fields", []) if str(item).strip()]
    return {
        "group_barcode_check_status": check.get("group_barcode_check_status", ""),
        "group_barcode_missing_fields": check.get("group_barcode_missing_fields", []),
        "group_barcode_missing_expected_fields": check.get("group_barcode_missing_expected_fields", []),
        "group_barcode_matched_fields": matched_fields,
        "group_barcode_detected_values": check.get("group_barcode_detected_values", {}),
        "group_barcode_passed_count": len(set(matched_fields)),
        "group_barcode_total_count": len(photo_barcode_check.GROUP_BARCODE_TYPES),
        "group_barcode_manual_confirmed": bool(check.get("group_barcode_manual_confirmed")),
        "group_barcode_manual_confirmed_by": check.get("group_barcode_manual_confirmed_by", ""),
        "group_barcode_manual_confirmed_at": check.get("group_barcode_manual_confirmed_at", ""),
    }


def _group_barcode_accuracy_summary(
    groups: list[Any],
    photos_by_group_id: dict[str, list[Any]],
    *,
    total_groups: int | None = None,
) -> dict[str, Any]:
    passed = 0
    failed = 0
    unreadable = 0
    not_required = max(0, int(total_groups or 0) - len(groups)) if total_groups is not None else 0
    for group in groups:
        photos = photos_by_group_id.get(_group_lookup_id(group))
        if photos is None and isinstance(group, dict):
            photos = list(group.get("photos") or [])
        photos = photos or []
        if len(photos) != photo_barcode_check.GROUP_BARCODE_REQUIRED_PHOTO_COUNT:
            not_required += 1
            continue
        payload = _group_barcode_payload(group, photos)
        status = str(photo_barcode_check.build_group_barcode_check(payload).get("group_barcode_check_status") or "")
        if status == "matched":
            passed += 1
        elif status == "mismatched":
            failed += 1
        elif status == "unreadable":
            unreadable += 1
        elif status == "not_required":
            not_required += 1
    checked = passed + failed + unreadable
    return {
        "group_barcode_accuracy_checked": checked,
        "group_barcode_accuracy_passed": passed,
        "group_barcode_accuracy_failed": failed,
        "group_barcode_accuracy_unreadable": unreadable,
        "group_barcode_accuracy_not_required": not_required,
        "group_barcode_accuracy_rate": round(passed / checked, 4) if checked else 0.0,
    }


def _group_lookup_id(group: Any) -> str:
    if isinstance(group, dict):
        return str(group.get("id") or group.get("group_id") or "")
    return str(getattr(group, "id", ""))


def _group_barcode_review_statuses(status: str) -> set[str]:
    normalized = str(status or "unreadable").strip().lower()
    if normalized in {"all", "review"}:
        return {"unreadable", "mismatched"}
    if normalized in {"mismatched", "failed"}:
        return {"mismatched"}
    return {"unreadable"}


def _group_barcode_context(group: Any) -> dict[str, Any]:
    raw = getattr(group, "raw_data", {}) or {}
    return {
        "id": getattr(group, "legacy_id", None) or str(getattr(group, "id", "")),
        "task_id": getattr(group, "legacy_task_id", None) or "",
        "meter_no": getattr(group, "display_meter_no", None) or raw.get("meter_no") or raw.get("barcode") or "",
        "meter_match_key": getattr(group, "meter_match_key", None) or raw.get("meter_match_key") or "",
        "terminal": getattr(group, "terminal", None) or raw.get("terminal") or "",
        "address": getattr(group, "installation_address", None) or raw.get("address") or "",
        "collector": raw.get("collector") or "",
        "module_asset_no": raw.get("module_asset_no") or raw.get("asset_no") or "",
        "asset_no": raw.get("asset_no") or raw.get("module_asset_no") or "",
        "construction_collector": raw.get("construction_collector") or "",
        "construction_module_asset_no": raw.get("construction_module_asset_no") or "",
        "group_barcode_manual_confirmed": bool(raw.get("group_barcode_manual_confirmed")),
        "group_barcode_manual_confirmed_fields": raw.get("group_barcode_manual_confirmed_fields") or [],
        "group_barcode_manual_confirmed_by": raw.get("group_barcode_manual_confirmed_by") or "",
        "group_barcode_manual_confirmed_at": raw.get("group_barcode_manual_confirmed_at") or "",
        "status": _legacy_group_status(group),
        "photo_count": int(getattr(group, "photo_count", 0) or 0),
    }


def _group_payload(session: Session, group: MaterialGroup, include_photos: bool = True) -> dict[str, Any]:
    photos = []
    if include_photos:
        photos = [
            _photo_payload(photo)
            for photo in session.scalars(
                select(Photo)
                .where(Photo.group_id == group.id, Photo.team_id == group.team_id, Photo.is_active.is_(True))
                .order_by(Photo.sort_order, Photo.created_at, Photo.legacy_id)
            ).all()
        ]
    task = None
    if group.task_id:
        task = session.get(Task, group.task_id)
    payload = {
        "id": group.legacy_id or str(group.id),
        "task_id": group.legacy_task_id,
        "meter_no": group.display_meter_no,
        "meter_match_key": group.meter_match_key or "",
        "terminal": group.terminal or "",
        "address": group.installation_address,
        "status": _legacy_group_status(group),
        "photo_count": len(photos) if include_photos else group.photo_count,
        "reviewer": group.reviewer or "",
        "reviewed_at": group.reviewed_at.isoformat() if group.reviewed_at else None,
        "review_note": group.review_note or "",
        "exception_note": group.exception_note or "",
        "exception_reasons": group.exception_reasons or [],
        "has_archive_blocker": group.has_archive_blocker,
        "photos": photos,
    }
    task_installer = task.construction_claimed_by if task is not None else ""
    raw = group.raw_data or {}
    for key in (
        "collector",
        "module_asset_no",
        "asset_no",
        "creator",
        "installer",
        "construction_collector",
        "construction_module_asset_no",
        "group_barcode_manual_confirmed",
        "group_barcode_manual_confirmed_fields",
        "group_barcode_manual_confirmed_by",
        "group_barcode_manual_confirmed_at",
        "replacement_old_meter_no",
        "replacement_new_meter_no",
        "replacement_by",
        "replacement_at",
    ):
        if key in raw and key not in payload:
            payload[key] = raw[key]
    if not str(payload.get("installer") or "").strip() and task_installer:
        payload["installer"] = task_installer
    return payload


def _installer_exception_group_payload(group: MaterialGroup, photo_count: int) -> dict[str, Any]:
    reasons = [str(item).strip() for item in (group.exception_reasons or []) if str(item).strip()]
    note = str(group.exception_note or group.review_note or "").strip()
    if note and note not in reasons:
        reasons.append(note)
    return {
        "group_id": group.legacy_id or str(group.id),
        "meter_no": group.display_meter_no,
        "terminal": group.terminal or "",
        "address": group.installation_address,
        "status": _legacy_group_status(group),
        "exception_note": note,
        "exception_reasons": reasons,
        "photo_count": int(photo_count or group.photo_count or 0),
    }


def _group_target_summary(group: dict[str, Any], *, include_photos: bool = False) -> dict[str, Any]:
    photo_count = int(group.get("photo_count") or 0)
    photos = group.get("photos", [])

    def first_photo_field(field: str) -> str:
        return next((str(photo.get(field) or "") for photo in photos if isinstance(photo, dict) and photo.get(field)), "")

    payload = {
        "id": group["id"],
        "task_id": group.get("task_id"),
        "terminal": group.get("terminal", ""),
        "meter_no": group.get("meter_no", ""),
        "meter_match_key": group.get("meter_match_key", ""),
        "address": group.get("address", ""),
        "status": group.get("status", ""),
        "reviewer": group.get("reviewer", ""),
        "review_note": group.get("review_note", ""),
        "exception_note": group.get("exception_note", ""),
        "installer": group.get("installer", "") or group.get("constructor", ""),
        "collector": group.get("collector", "") or first_photo_field("collector"),
        "module_asset_no": group.get("module_asset_no", "") or first_photo_field("module_asset_no") or first_photo_field("asset_no"),
        "creator": group.get("creator", "") or first_photo_field("creator"),
        "construction_collector": group.get("construction_collector", ""),
        "construction_module_asset_no": group.get("construction_module_asset_no", ""),
        "photo_count": photo_count,
        "construction_status": "unconstructed" if photo_count == 0 else "scanned",
        "has_archive_blocker": group.get("has_archive_blocker", False),
        "exception_reasons": group.get("exception_reasons", []),
        **_group_photo_category_summary(photos),
        **_group_barcode_status_summary(_group_barcode_payload(group, photos)),
    }
    if include_photos:
        payload["photos"] = photos
    return payload


def _apply_construction_status(group: dict[str, Any]) -> dict[str, Any]:
    group["construction_status"] = "unconstructed" if int(group.get("photo_count") or 0) == 0 else "scanned"
    return group


def _is_problem_group(group: dict[str, Any]) -> bool:
    photo_count = int(group.get("photo_count") or 0)
    return group.get("status") == "exception" or (
        photo_count > 0 and (group.get("status") == "incomplete" or bool(group.get("has_archive_blocker")))
    )


def _is_reviewed_group(group: dict[str, Any]) -> bool:
    return group.get("status") == "approved"


def _is_unreviewed_group(group: dict[str, Any]) -> bool:
    return group.get("status") in OPEN_STATUSES and not _is_problem_group(group)


def _count_incomplete_scanned_groups(groups: list[dict[str, Any]]) -> int:
    return sum(
        1
        for group in groups
        if group.get("status") == "incomplete"
        and int(group.get("photo_count") or 0) > 0
        and not _is_problem_group(group)
    )


def _count_unconstructed_groups(groups: list[dict[str, Any]]) -> int:
    return sum(
        1
        for group in groups
        if int(group.get("photo_count") or 0) == 0 and group.get("status") != "unmatched"
    )


def _count_complete_groups(groups: list[dict[str, Any]]) -> int:
    return sum(1 for group in groups if int(group.get("photo_count") or 0) >= 4)


def _count_partial_groups(groups: list[dict[str, Any]]) -> int:
    return sum(1 for group in groups if 0 < int(group.get("photo_count") or 0) < 4)


def _calculate_progress(groups: list[dict[str, Any]]) -> float:
    if not groups:
        return 0.0
    reviewed = sum(1 for group in groups if _is_reviewed_group(group))
    return round(reviewed / len(groups), 4)


def _calculate_completeness_rate(groups: list[dict[str, Any]], *, scan_only: bool = False) -> float:
    scoped_groups = [group for group in groups if int(group.get("photo_count") or 0) > 0] if scan_only else groups
    if not scoped_groups:
        return 0.0
    collected_slots = sum(min(int(group.get("photo_count") or 0), 4) for group in scoped_groups)
    required_slots = len(scoped_groups) * 4
    return round(collected_slots / required_slots, 4)


def _review_queue_rank(group: dict[str, Any]) -> int:
    if _is_reviewed_group(group):
        return 3
    if group.get("status") == "exception" or group.get("has_archive_blocker"):
        return 1
    if int(group.get("photo_count") or 0) == 0 and group.get("status") != "unmatched":
        return 2
    return 0


def _group_target_text(group: dict[str, Any]) -> str:
    values = [
        group.get("id"),
        group.get("terminal"),
        group.get("meter_no"),
        group.get("meter_match_key"),
        group.get("address"),
        group.get("status"),
        group.get("installer"),
        group.get("creator"),
        group.get("collector"),
        group.get("module_asset_no"),
        group.get("construction_collector"),
        group.get("construction_module_asset_no"),
    ]
    for photo in group.get("photos", []):
        values.extend(
            [
                photo.get("barcode"),
                photo.get("collector"),
                photo.get("asset_no"),
                photo.get("module_asset_no"),
                photo.get("creator"),
                photo.get("source_file"),
            ]
        )
    return " ".join(str(value or "") for value in values).lower()


def _catalog_row_payload(row: TotalCatalogRow) -> dict[str, Any]:
    raw = dict(row.raw_data or {})
    payload = {
        "id": raw.get("id") or str(row.id),
        "terminal": row.terminal or raw.get("terminal") or "",
        "meter_no": row.original_meter_no,
        "meter_match_key": row.meter_match_key,
        "address": row.installation_address,
        "installer": row.installer or raw.get("installer") or "",
        "source": row.source_file or raw.get("source") or "",
        "source_row_number": row.source_row_number,
        "raw": raw,
    }
    payload.update({key: value for key, value in raw.items() if key not in payload})
    return payload


def _stage_catalog_row_payload(row: StageCatalogRow) -> dict[str, Any]:
    raw = dict(row.raw_data or {})
    payload = {
        "id": raw.get("id") or str(row.id),
        "terminal": row.terminal_no or raw.get("terminal") or "",
        "meter_no": raw.get("meter_no") or row.original_barcode,
        "meter_match_key": row.meter_match_key,
        "address": raw.get("address") or "",
        "source": raw.get("source") or "",
        "source_row_number": row.source_row_number,
        "raw": raw,
    }
    payload.update({key: value for key, value in raw.items() if key not in payload})
    return payload


def _delivery_photo_manifest(group: dict[str, Any], photo: dict[str, Any], index: int) -> dict[str, Any]:
    category = photo.get("category") or "unclassified"
    category_label = local_simulation.PHOTO_CATEGORIES.get(category, local_simulation.PHOTO_CATEGORIES["unclassified"])
    image_url = photo.get("image_url") or photo.get("url") or ""
    return {
        "id": photo.get("id", ""),
        "index": index,
        "barcode": photo.get("barcode", ""),
        "collector": photo.get("collector", ""),
        "asset_no": photo.get("asset_no") or photo.get("module_asset_no") or "",
        "creator": photo.get("creator", ""),
        "category": category,
        "category_label": category_label,
        "archive_filename": photo.get("archive_filename")
        or local_simulation.build_archive_filename(category_label, image_url),
        "image_url": image_url,
        "storage_type": photo.get("storage_type", ""),
        "storage_key": photo.get("storage_key", ""),
        "storage_bucket": photo.get("storage_bucket", ""),
        "sha256": photo.get("sha256", ""),
        "source_file": photo.get("source_file", ""),
        "delivery_cache_url": photo.get("delivery_cache_url", ""),
        "delivery_cache_status": photo.get("delivery_cache_status", "none"),
    }


def _delivery_group_manifest(group: dict[str, Any]) -> dict[str, Any]:
    photos = group.get("photos") or []
    return {
        "id": group.get("id", ""),
        "task_id": group.get("task_id"),
        "terminal": group.get("terminal", ""),
        "meter_no": group.get("meter_no", ""),
        "meter_match_key": group.get("meter_match_key", ""),
        "address": group.get("address", ""),
        "status": group.get("status", ""),
        "reviewer": group.get("reviewer") or "",
        "review_note": group.get("review_note") or "",
        "exception_note": group.get("exception_note") or "",
        "has_archive_blocker": group.get("has_archive_blocker", False),
        "exception_reasons": group.get("exception_reasons", []),
        "photo_count": len(photos),
        "delivery_cache_status": group.get("delivery_cache_status", "none"),
        "delivery_cache_built_at": group.get("delivery_cache_built_at", ""),
        "photos": [_delivery_photo_manifest(group, photo, index) for index, photo in enumerate(photos, start=1)],
    }


def _unmatched_payload(record: UnmatchedRecord) -> dict[str, Any]:
    payload = record.payload or {}
    photo_urls = payload.get("photo_urls") or payload.get("image_urls") or payload.get("images") or []
    if isinstance(photo_urls, str):
        photo_urls = [item.strip() for item in re.split(r"[\r\n,]+", photo_urls) if item.strip()]
    if not isinstance(photo_urls, list):
        photo_urls = []
    return {
        "unmatched_id": record.legacy_id,
        "record_type": record.record_type,
        "status": record.status,
        "terminal": record.terminal or "",
        "meter_no": record.meter_no or "",
        "meter_match_key": record.meter_match_key or "",
        "barcode": record.barcode or "",
        "collector": record.collector or "",
        "module_asset_no": record.module_asset_no or "",
        "asset_no": record.module_asset_no or "",
        "address": record.address or "",
        "creator": payload.get("creator") or "",
        "photo_urls": photo_urls,
        "photo_count": len(photo_urls),
        "assigned_to": payload.get("assigned_to") or "",
        "assigned_by": payload.get("assigned_by") or "",
        "assigned_at": payload.get("assigned_at") or "",
        "assignment_note": payload.get("assignment_note") or "",
        "due_date": payload.get("due_date") or "",
        "project_outside": bool(payload.get("project_outside")),
        "project_outside_by": payload.get("project_outside_by") or "",
        "project_outside_at": payload.get("project_outside_at") or "",
        "project_outside_note": payload.get("project_outside_note") or "",
        "replacement_old_meter_no": payload.get("replacement_old_meter_no") or "",
        "replacement_target_group_id": payload.get("replacement_target_group_id") or "",
        "field_task_type": payload.get("field_task_type") or "",
        "source_file": payload.get("source_file") or "",
        "raw": payload,
    }


def _unmatched_duplicate_keys(records: list[UnmatchedRecord]) -> set[str]:
    keys: set[str] = set()
    for record in records:
        key = local_simulation.make_unmatched_duplicate_key(_unmatched_payload(record))
        if not key.startswith("id:"):
            keys.add(key)
    return keys


class StateRepository(ABC):
    @abstractmethod
    def summary(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_tasks(self, *, summary_only: bool = False) -> list[dict[str, Any]]:
        raise NotImplementedError

    def task_status(self) -> dict[str, Any]:
        task_rows = [
            {
                "id": task.get("id"),
                "terminal": task.get("terminal"),
                "claimed_by": task.get("claimed_by"),
                "construction_assigned_to": task.get("assigned_constructor")
                or task.get("construction_claimed_by"),
                "total_groups": task.get("renovation_count") or task.get("total_groups"),
                "uploaded_count": task.get("uploaded_count"),
                "reviewed_count": task.get("reviewed_count"),
                "unreviewed_count": task.get("unreviewed_count"),
            }
            for task in self.list_tasks(summary_only=True)
        ]
        return _build_task_status_summary(task_rows, self.summary().get("summary", {}))

    @abstractmethod
    def installer_daily_workload(self, installer: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def record_construction_activity_event(
        self,
        *,
        event_type: str,
        actor: str,
        task_id: str | int | None = None,
        group_id: str = "",
        client_batch_id: str = "",
        occurred_at: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_team_states(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def bootstrap(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def clear_scan_data(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def sync_photos_to_oss(self, *, team_id: str = "", progress_callback=None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def persist_state(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_groups(self, *, limit: int = 100, offset: int = 0, status: str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_photo_barcode_review_groups(
        self,
        *,
        status: str = "unreadable",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def search_group_targets(
        self,
        *,
        query: str = "",
        terminal: str = "",
        limit: int = 30,
        offset: int = 0,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_catalog_rows(
        self,
        catalog_type: str,
        *,
        query: str = "",
        terminal: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_task_groups(
        self,
        task_id: int,
        *,
        limit: int = 100,
        offset: int = 0,
        status: str | None = None,
        scan_only: bool = False,
        summary_only: bool = False,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_group(self, group_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    def list_unmatched_records(self, *, query: str = "", limit: int = 100, offset: int = 0) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_replacement_records(self, *, query: str = "", limit: int = 100, offset: int = 0) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def dedupe_unmatched_records(self, *, actor: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def create_blank_unmatched_record(self, *, actor: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def update_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def assign_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        constructor: str,
        note: str = "",
        due_date: str = "",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def unassign_unmatched_record(self, unmatched_id: str, *, actor: str, reason: str = "") -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def mark_unmatched_outside_project(self, unmatched_id: str, *, actor: str, note: str = "") -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def rematch_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        meter_no: str = "",
        old_meter_no: str = "",
        terminal: str = "",
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_exception_groups(self, *, reviewer: str = "", limit: int = 100, offset: int = 0) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def update_group_metadata(
        self,
        group_id: str,
        *,
        actor: str,
        updates: dict[str, Any],
        audit_action: str = "update_group_metadata",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def claim_task(self, task_id: int, reviewer: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def release_task(self, task_id: int, reviewer: str, *, force: bool = False) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_task_progress(self, task_id: int) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def release_all_claimed_tasks(self, actor: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_audit_events(self, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_construction_tasks(self, *, actor: str = "", include_closed: bool = False) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def open_construction_task(self, task_id: int, actor: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def close_construction_task(self, task_id: int, actor: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def assign_construction_task(
        self,
        task_id: int,
        *,
        actor: str,
        constructor: str,
        note: str = "",
        due_date: str = "",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def unassign_construction_task(self, task_id: int, *, actor: str, reason: str = "") -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def claim_construction_task(self, task_id: int, actor: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def release_construction_task(self, task_id: int, actor: str, *, force: bool = False) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_construction_task_groups(
        self,
        task_id: int,
        *,
        limit: int = 100,
        offset: int = 0,
        status: str | None = None,
        summary_only: bool = False,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_construction_exception_orders(
        self,
        *,
        actor: str = "",
        task_id: int | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def submit_construction_exception_order(
        self,
        order_id: str,
        *,
        actor: str,
        updates: dict[str, Any] | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def assign_construction_exception_order(
        self,
        order_id: str,
        *,
        actor: str,
        constructor: str,
        note: str = "",
        due_date: str = "",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def unassign_construction_exception_order(self, order_id: str, *, actor: str, reason: str = "") -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def review_group(
        self,
        group_id: str,
        status: str,
        reviewer: str,
        note: str = "",
        exception_note: str = "",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def classify_photo(self, group_id: str, photo_id: str, category: str, reviewer: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def rescan_photo_barcode(
        self,
        group_id: str,
        photo_id: str,
        reviewer: str,
        category: str = "",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def confirm_group_barcode_manually(self, group_id: str, *, actor: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def delete_photo(self, group_id: str, photo_id: str, reviewer: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def delete_unmatched_record(self, unmatched_id: str, *, actor: str, reason: str = "") -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def associate_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        target_group_id: str = "",
        target_meter_no: str = "",
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def create_group_from_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        terminal: str = "",
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def create_empty_group_for_terminal(
        self,
        *,
        terminal: str,
        actor: str,
        meter_no: str = "",
        address: str = "",
        meter_match_key: str = "",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def update_group_terminal(self, group_id: str, *, terminal: str, actor: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def save_exception_note(self, group_id: str, *, reviewer: str, note: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def add_photo_urls_to_group(
        self,
        group_id: str,
        *,
        actor: str,
        photo_urls: list[str],
        collector: str = "",
        module_asset_no: str = "",
        creator: str = "",
        photo_metadata: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def upload_construction_group_batch(
        self,
        group_id: str,
        *,
        actor: str,
        client_batch_id: str,
        collector: str,
        module_asset_no: str,
        photos: list[dict[str, Any]],
        creator: str = "",
        client_completed_at: str = "",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def build_task_detail_export(self, task_id: int) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def build_final_delivery_export(
        self,
        *,
        task_id: int | None = None,
        terminal: str = "",
        review_scope: str = "reviewed",
    ) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def build_final_delivery_manifest(
        self,
        *,
        task_id: int | None = None,
        terminal: str = "",
        review_scope: str = "reviewed",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def build_exception_meter_export(self, *, reviewer: str = "") -> bytes:
        raise NotImplementedError

    @abstractmethod
    def build_project_outside_export(self) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def get_delivery_cached_photo_path(self, group_id: str, photo_id: str) -> Path:
        raise NotImplementedError

    @abstractmethod
    def reset_group_to_unconstructed(
        self,
        group_id: str,
        *,
        actor: str,
        reason: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def reset_group_to_unreviewed(
        self,
        group_id: str,
        *,
        actor: str,
        reason: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def bulk_archive_groups(self, group_ids: list[str], *, actor: str, reason: str = "") -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def return_group_to_exception_order(
        self,
        group_id: str,
        *,
        actor: str,
        category: str,
        note: str,
        force: bool = False,
    ) -> dict[str, Any]:
        raise NotImplementedError


class JsonStateRepository(StateRepository):
    def summary(self) -> dict[str, Any]:
        state = local_simulation.get_state()
        return {"summary": state["summary"], "paths": state["paths"]}

    def list_tasks(self, *, summary_only: bool = False) -> list[dict[str, Any]]:
        tasks = local_simulation.list_tasks()
        if not summary_only:
            return tasks
        return [_task_board_payload(task) for task in tasks]

    def task_status(self) -> dict[str, Any]:
        return local_simulation.task_status_summary()

    def installer_daily_workload(self, installer: str) -> dict[str, Any]:
        return local_simulation.installer_daily_workload(installer)

    def record_construction_activity_event(
        self,
        *,
        event_type: str,
        actor: str,
        task_id: str | int | None = None,
        group_id: str = "",
        client_batch_id: str = "",
        occurred_at: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return local_simulation.record_construction_activity_event(
            event_type=event_type,
            actor=actor,
            task_id=task_id,
            group_id=group_id,
            client_batch_id=client_batch_id,
            occurred_at=occurred_at,
            payload=payload,
        )

    def list_team_states(self) -> list[dict[str, Any]]:
        return local_simulation.list_team_states()

    def bootstrap(self) -> dict[str, Any]:
        state = local_simulation.bootstrap_local_simulation()
        return {"summary": state["summary"], "paths": state["paths"]}

    def clear_scan_data(self) -> dict[str, Any]:
        state = local_simulation.clear_scan_data()
        return {"summary": state["summary"], "paths": state["paths"]}

    def sync_photos_to_oss(self, *, team_id: str = "", progress_callback=None) -> dict[str, Any]:
        return local_simulation.sync_state_photos_to_oss(team_id=team_id, progress_callback=progress_callback)

    def persist_state(self) -> None:
        local_simulation.save_all_team_states()

    def list_groups(self, *, limit: int = 100, offset: int = 0, status: str | None = None) -> dict[str, Any]:
        return local_simulation.list_groups(limit=limit, offset=offset, status=status)

    def list_photo_barcode_review_groups(
        self,
        *,
        status: str = "unreadable",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        groups = local_simulation.list_groups(limit=100000, offset=0).get("items", [])
        statuses = _group_barcode_review_statuses(status)
        items = photo_barcode_check.list_group_barcode_review_items(groups, statuses=statuses)
        capped_limit = max(1, min(int(limit or 100), 100000))
        safe_offset = max(0, int(offset or 0))
        return {
            "total": len(items),
            "limit": capped_limit,
            "offset": safe_offset,
            "page": (safe_offset // capped_limit) + 1,
            "page_size": capped_limit,
            "items": items[safe_offset : safe_offset + capped_limit],
        }

    def search_group_targets(
        self,
        *,
        query: str = "",
        terminal: str = "",
        limit: int = 30,
        offset: int = 0,
    ) -> dict[str, Any]:
        return local_simulation.search_group_targets(query=query, terminal=terminal, limit=limit, offset=offset)

    def list_catalog_rows(
        self,
        catalog_type: str,
        *,
        query: str = "",
        terminal: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        return local_simulation.list_catalog_rows(
            catalog_type,
            query=query,
            terminal=terminal,
            limit=limit,
            offset=offset,
        )

    def list_task_groups(
        self,
        task_id: int,
        *,
        limit: int = 100,
        offset: int = 0,
        status: str | None = None,
        scan_only: bool = False,
        summary_only: bool = False,
    ) -> dict[str, Any]:
        return local_simulation.list_task_groups(
            task_id,
            limit=limit,
            offset=offset,
            status=status,
            scan_only=scan_only,
            summary_only=summary_only,
        )

    def get_group(self, group_id: str) -> dict[str, Any] | None:
        return local_simulation.get_group(group_id)

    def list_unmatched_records(self, *, query: str = "", limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return local_simulation.list_unmatched_records(query=query, limit=limit, offset=offset)

    def list_replacement_records(self, *, query: str = "", limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return local_simulation.list_replacement_records(query=query, limit=limit, offset=offset)

    def dedupe_unmatched_records(self, *, actor: str) -> dict[str, Any]:
        return local_simulation.dedupe_unmatched_records(actor=actor)

    def create_blank_unmatched_record(self, *, actor: str) -> dict[str, Any]:
        return {"record": local_simulation.create_blank_unmatched_record(actor=actor)}

    def update_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {"record": local_simulation.update_unmatched_record(unmatched_id, actor=actor, updates=updates)}

    def assign_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        constructor: str,
        note: str = "",
        due_date: str = "",
    ) -> dict[str, Any]:
        return {
            "record": local_simulation.assign_unmatched_record(
                unmatched_id,
                actor=actor,
                constructor=constructor,
                note=note,
                due_date=due_date,
            )
        }

    def unassign_unmatched_record(self, unmatched_id: str, *, actor: str, reason: str = "") -> dict[str, Any]:
        return {
            "record": local_simulation.unassign_unmatched_record(
                unmatched_id,
                actor=actor,
                reason=reason,
            )
        }

    def mark_unmatched_outside_project(self, unmatched_id: str, *, actor: str, note: str = "") -> dict[str, Any]:
        return {
            "record": local_simulation.mark_unmatched_outside_project(
                unmatched_id,
                actor=actor,
                note=note,
            )
        }

    def rematch_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        meter_no: str = "",
        old_meter_no: str = "",
        terminal: str = "",
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return local_simulation.rematch_unmatched_record(
            unmatched_id,
            actor=actor,
            meter_no=meter_no,
            old_meter_no=old_meter_no,
            terminal=terminal,
            updates=updates,
        )

    def list_exception_groups(self, *, reviewer: str = "", limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return local_simulation.list_exception_groups(reviewer=reviewer, limit=limit, offset=offset)

    def update_group_metadata(
        self,
        group_id: str,
        *,
        actor: str,
        updates: dict[str, Any],
        audit_action: str = "update_group_metadata",
    ) -> dict[str, Any]:
        return local_simulation.update_group_metadata(group_id, actor=actor, updates=updates, audit_action=audit_action)

    def claim_task(self, task_id: int, reviewer: str) -> dict[str, Any]:
        return local_simulation.claim_task(task_id, reviewer)

    def release_task(self, task_id: int, reviewer: str, *, force: bool = False) -> dict[str, Any]:
        return local_simulation.release_task(task_id, reviewer, force=force)

    def get_task_progress(self, task_id: int) -> dict[str, Any]:
        return local_simulation.get_task_progress(task_id)

    def release_all_claimed_tasks(self, actor: str) -> dict[str, Any]:
        return local_simulation.release_all_claimed_tasks(actor)

    def list_audit_events(self, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return local_simulation.list_audit_events(limit=limit, offset=offset)

    def list_construction_tasks(self, *, actor: str = "", include_closed: bool = False) -> list[dict[str, Any]]:
        return local_simulation.list_construction_tasks(actor=actor, include_closed=include_closed)

    def open_construction_task(self, task_id: int, actor: str) -> dict[str, Any]:
        return local_simulation.open_construction_task(task_id, actor)

    def close_construction_task(self, task_id: int, actor: str) -> dict[str, Any]:
        return local_simulation.close_construction_task(task_id, actor)

    def assign_construction_task(
        self,
        task_id: int,
        *,
        actor: str,
        constructor: str,
        note: str = "",
        due_date: str = "",
    ) -> dict[str, Any]:
        return local_simulation.assign_construction_task(
            task_id,
            actor=actor,
            constructor=constructor,
            note=note,
            due_date=due_date,
        )

    def unassign_construction_task(self, task_id: int, *, actor: str, reason: str = "") -> dict[str, Any]:
        return local_simulation.unassign_construction_task(task_id, actor=actor, reason=reason)

    def claim_construction_task(self, task_id: int, actor: str) -> dict[str, Any]:
        return local_simulation.claim_construction_task(task_id, actor)

    def release_construction_task(self, task_id: int, actor: str, *, force: bool = False) -> dict[str, Any]:
        return local_simulation.release_construction_task(task_id, actor, force=force)

    def list_construction_task_groups(
        self,
        task_id: int,
        *,
        limit: int = 100,
        offset: int = 0,
        status: str | None = None,
        summary_only: bool = False,
    ) -> dict[str, Any]:
        return local_simulation.list_construction_task_groups(
            task_id,
            limit=limit,
            offset=offset,
            status=status,
            summary_only=summary_only,
        )

    def list_construction_exception_orders(
        self,
        *,
        actor: str = "",
        task_id: int | None = None,
    ) -> list[dict[str, Any]]:
        return local_simulation.list_construction_exception_orders(actor=actor, task_id=task_id)

    def submit_construction_exception_order(
        self,
        order_id: str,
        *,
        actor: str,
        updates: dict[str, Any] | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        return local_simulation.submit_construction_exception_order(
            order_id,
            actor=actor,
            updates=updates,
            note=note,
        )

    def assign_construction_exception_order(
        self,
        order_id: str,
        *,
        actor: str,
        constructor: str,
        note: str = "",
        due_date: str = "",
    ) -> dict[str, Any]:
        return {
            "order": local_simulation.assign_construction_exception_order(
                order_id,
                actor=actor,
                constructor=constructor,
                note=note,
                due_date=due_date,
            )
        }

    def unassign_construction_exception_order(self, order_id: str, *, actor: str, reason: str = "") -> dict[str, Any]:
        return {
            "order": local_simulation.unassign_construction_exception_order(
                order_id,
                actor=actor,
                reason=reason,
            )
        }

    def review_group(
        self,
        group_id: str,
        status: str,
        reviewer: str,
        note: str = "",
        exception_note: str = "",
    ) -> dict[str, Any]:
        return local_simulation.review_group(group_id, status, reviewer, note, exception_note)

    def classify_photo(self, group_id: str, photo_id: str, category: str, reviewer: str) -> dict[str, Any]:
        return local_simulation.classify_photo(group_id, photo_id, category, reviewer)

    def rescan_photo_barcode(
        self,
        group_id: str,
        photo_id: str,
        reviewer: str,
        category: str = "",
    ) -> dict[str, Any]:
        return local_simulation.rescan_photo_barcode(group_id, photo_id, reviewer, category)

    def confirm_group_barcode_manually(self, group_id: str, *, actor: str) -> dict[str, Any]:
        return local_simulation.confirm_group_barcode_manually(group_id, actor=actor)

    def delete_photo(self, group_id: str, photo_id: str, reviewer: str) -> dict[str, Any]:
        return local_simulation.delete_group_photo(group_id, photo_id, reviewer)

    def delete_unmatched_record(self, unmatched_id: str, *, actor: str, reason: str = "") -> dict[str, Any]:
        return local_simulation.delete_unmatched_record(unmatched_id, actor=actor, reason=reason)

    def associate_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        target_group_id: str = "",
        target_meter_no: str = "",
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return local_simulation.associate_unmatched_record(
            unmatched_id,
            actor=actor,
            target_group_id=target_group_id,
            target_meter_no=target_meter_no,
            updates=updates,
        )

    def create_group_from_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        terminal: str = "",
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return local_simulation.create_group_from_unmatched_record(
            unmatched_id,
            actor=actor,
            terminal=terminal,
            updates=updates,
        )

    def create_empty_group_for_terminal(
        self,
        *,
        terminal: str,
        actor: str,
        meter_no: str = "",
        address: str = "",
        meter_match_key: str = "",
    ) -> dict[str, Any]:
        return local_simulation.create_empty_group_for_terminal(
            terminal=terminal,
            actor=actor,
            meter_no=meter_no,
            address=address,
            meter_match_key=meter_match_key,
        )

    def update_group_terminal(self, group_id: str, *, terminal: str, actor: str) -> dict[str, Any]:
        return local_simulation.update_group_terminal(group_id, terminal=terminal, actor=actor)

    def save_exception_note(self, group_id: str, *, reviewer: str, note: str) -> dict[str, Any]:
        return local_simulation.save_exception_note(group_id, reviewer=reviewer, note=note)

    def add_photo_urls_to_group(
        self,
        group_id: str,
        *,
        actor: str,
        photo_urls: list[str],
        collector: str = "",
        module_asset_no: str = "",
        creator: str = "",
        photo_metadata: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return local_simulation.add_photo_urls_to_group(
            group_id,
            actor=actor,
            photo_urls=photo_urls,
            collector=collector,
            module_asset_no=module_asset_no,
            creator=creator,
            photo_metadata=photo_metadata,
        )

    def upload_construction_group_batch(
        self,
        group_id: str,
        *,
        actor: str,
        client_batch_id: str,
        collector: str,
        module_asset_no: str,
        photos: list[dict[str, Any]],
        creator: str = "",
        client_completed_at: str = "",
    ) -> dict[str, Any]:
        return local_simulation.upload_construction_group_batch(
            group_id,
            actor=actor,
            client_batch_id=client_batch_id,
            collector=collector,
            module_asset_no=module_asset_no,
            photos=photos,
            creator=creator,
            client_completed_at=client_completed_at,
        )

    def build_task_detail_export(self, task_id: int) -> bytes:
        return local_simulation.build_task_detail_export(task_id)

    def build_final_delivery_export(
        self,
        *,
        task_id: int | None = None,
        terminal: str = "",
        review_scope: str = "reviewed",
    ) -> bytes:
        return local_simulation.build_final_delivery_export(
            task_id=task_id,
            terminal=terminal,
            review_scope=review_scope,
        )

    def build_final_delivery_manifest(
        self,
        *,
        task_id: int | None = None,
        terminal: str = "",
        review_scope: str = "reviewed",
    ) -> dict[str, Any]:
        return local_simulation.build_final_delivery_manifest(
            task_id=task_id,
            terminal=terminal,
            review_scope=review_scope,
        )

    def build_exception_meter_export(self, *, reviewer: str = "") -> bytes:
        return local_simulation.build_exception_meter_export(reviewer=reviewer)

    def build_project_outside_export(self) -> bytes:
        return local_simulation.build_project_outside_export()

    def get_delivery_cached_photo_path(self, group_id: str, photo_id: str) -> Path:
        return local_simulation.get_delivery_cached_photo_path(group_id, photo_id)

    def reset_group_to_unconstructed(
        self,
        group_id: str,
        *,
        actor: str,
        reason: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        return local_simulation.reset_group_to_unconstructed(group_id, actor=actor, reason=reason, force=force)

    def reset_group_to_unreviewed(
        self,
        group_id: str,
        *,
        actor: str,
        reason: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        return local_simulation.reset_group_to_unreviewed(group_id, actor=actor, reason=reason, force=force)

    def bulk_archive_groups(self, group_ids: list[str], *, actor: str, reason: str = "") -> dict[str, Any]:
        return local_simulation.bulk_archive_groups(group_ids, actor=actor, reason=reason)

    def return_group_to_exception_order(
        self,
        group_id: str,
        *,
        actor: str,
        category: str,
        note: str,
        force: bool = False,
    ) -> dict[str, Any]:
        return local_simulation.return_group_to_exception_order(
            group_id,
            actor=actor,
            category=category,
            note=note,
            force=force,
        )


class PostgresStateRepository(StateRepository):
    def _session(self) -> Session:
        return SessionLocal()

    def _active_construction_tasks_for(
        self,
        session: Session,
        *,
        team_id: str,
        constructor: str,
        excluding_task_id: UUID | None = None,
    ) -> list[Task]:
        statement = select(Task).where(
            Task.team_id == team_id,
            Task.construction_enabled.is_(True),
            Task.construction_claimed_by == constructor,
        )
        if excluding_task_id is not None:
            statement = statement.where(Task.id != excluding_task_id)
        return list(session.scalars(statement.order_by(Task.terminal, Task.legacy_id).with_for_update()).all())

    def _ensure_construction_assignment_capacity(
        self,
        session: Session,
        *,
        team_id: str,
        constructor: str,
        excluding_task_id: UUID | None = None,
    ) -> None:
        active_tasks = self._active_construction_tasks_for(
            session,
            team_id=team_id,
            constructor=constructor,
            excluding_task_id=excluding_task_id,
        )
        if len(active_tasks) < MAX_ACTIVE_CONSTRUCTION_TASKS_PER_CONSTRUCTOR:
            return
        terminals = ", ".join(str(task.terminal or task.legacy_id or "") for task in active_tasks[:3])
        raise ValueError(
            f"Current constructor already has {MAX_ACTIVE_CONSTRUCTION_TASKS_PER_CONSTRUCTOR} active terminals"
            f"{': ' + terminals if terminals else ''}"
        )

    def summary(self) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        with self._session() as session:
            total_catalog_rows = session.scalar(
                select(func.count()).select_from(TotalCatalogRow).where(TotalCatalogRow.team_id == team_id)
            ) or 0
            group_stats = session.execute(
                select(
                    func.count(MaterialGroup.id).label("groups"),
                    func.coalesce(func.sum(MaterialGroup.photo_count), 0).label("photo_rows_linked"),
                    func.coalesce(
                        func.sum(case((MaterialGroup.photo_count > 0, 1), else_=0)),
                        0,
                    ).label("scanned_groups"),
                    func.coalesce(
                        func.sum(case((MaterialGroup.status == GroupStatus.APPROVED, 1), else_=0)),
                        0,
                    ).label("approved_groups"),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    MaterialGroup.status.in_(
                                        [GroupStatus.APPROVED, GroupStatus.INCOMPLETE, GroupStatus.REJECTED]
                                    ),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("reviewed_groups"),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    (MaterialGroup.status == GroupStatus.UNREVIEWED)
                                    & (MaterialGroup.photo_count > 0),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("unreviewed_groups"),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    (MaterialGroup.status == GroupStatus.REJECTED)
                                    | (MaterialGroup.exception_status == "open")
                                    | (MaterialGroup.has_archive_blocker.is_(True)),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("exception_groups"),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    (MaterialGroup.photo_count > 0)
                                    & (MaterialGroup.photo_count < 4)
                                    & (MaterialGroup.status != GroupStatus.REJECTED),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("incomplete_groups"),
                    func.coalesce(
                        func.sum(case((MaterialGroup.photo_count == 0, 1), else_=0)),
                        0,
                    ).label("unconstructed_groups"),
                ).where(MaterialGroup.team_id == team_id)
            ).one()
            scan_unmatched = session.scalar(
                select(func.count()).select_from(UnmatchedRecord).where(
                    UnmatchedRecord.team_id == team_id,
                    UnmatchedRecord.status == "open",
                )
            ) or 0
            installer_pairs = session.execute(
                select(Photo.creator, Photo.group_id).where(
                    Photo.team_id == team_id,
                    Photo.is_active.is_(True),
                    Photo.group_id.is_not(None),
                )
            ).all()
            photo_status_expr = Photo.raw_data.op("->>")("barcode_check_status")
            photo_accuracy_rows = session.execute(
                select(
                    photo_status_expr.label("status"),
                    func.count(Photo.id).label("count"),
                )
                .where(
                    Photo.team_id == team_id,
                    Photo.is_active.is_(True),
                    Photo.group_id.is_not(None),
                )
                .group_by(photo_status_expr)
            ).all()
            active_photo_counts = (
                select(Photo.group_id.label("group_id"), func.count(Photo.id).label("active_photo_count"))
                .where(Photo.team_id == team_id, Photo.is_active.is_(True), Photo.group_id.is_not(None))
                .group_by(Photo.group_id)
                .subquery()
            )
            group_barcode_rows = session.execute(
                select(
                    MaterialGroup.id.label("group_id"),
                    MaterialGroup.legacy_id,
                    MaterialGroup.legacy_task_id,
                    MaterialGroup.display_meter_no,
                    MaterialGroup.meter_match_key,
                    MaterialGroup.terminal,
                    MaterialGroup.installation_address,
                    MaterialGroup.status,
                    MaterialGroup.photo_count,
                    MaterialGroup.raw_data,
                )
                .join(active_photo_counts, active_photo_counts.c.group_id == MaterialGroup.id)
                .where(MaterialGroup.team_id == team_id, active_photo_counts.c.active_photo_count == 4)
            ).all()
            complete_group_ids = [row.group_id for row in group_barcode_rows]
            group_barcode_photo_rows = []
            if complete_group_ids:
                group_barcode_photo_rows = session.execute(
                    select(
                        Photo.id.label("photo_id"),
                        Photo.legacy_id,
                        Photo.group_id,
                        Photo.category,
                        Photo.barcode,
                        Photo.collector,
                        Photo.asset_no,
                        Photo.raw_data,
                    )
                    .where(
                        Photo.team_id == team_id,
                        Photo.is_active.is_(True),
                        Photo.group_id.in_(complete_group_ids),
                    )
                    .order_by(Photo.group_id, Photo.sort_order, Photo.created_at, Photo.legacy_id)
                ).all()

        groups = int(group_stats.groups or 0)
        reviewed_groups = int(group_stats.reviewed_groups or 0)
        installer_group_ids: dict[str, set[str]] = {}
        installer_name_cache: dict[str, str] = {}
        for row in installer_pairs:
            installer = _installer_display_name(row.creator, installer_name_cache) or "未填写"
            installer_group_ids.setdefault(installer, set()).add(str(row.group_id))
        installer_items = sorted(installer_group_ids.items(), key=lambda item: (-len(item[1]), item[0]))[:8]
        installer_total = sum(len(group_ids) for _, group_ids in installer_items)
        installer_distribution = [
            {
                "installer": installer,
                "group_count": len(group_ids),
                "share": round(len(group_ids) / installer_total, 4) if installer_total else 0.0,
            }
            for installer, group_ids in installer_items
        ]
        photo_accuracy = _photo_accuracy_summary_from_counts(
            {str(row.status or ""): int(row.count or 0) for row in photo_accuracy_rows}
        )
        photos_by_group_id: dict[str, list[Any]] = defaultdict(list)
        for photo in group_barcode_photo_rows:
            photos_by_group_id[str(photo.group_id)].append(_photo_barcode_payload_from_row(photo))
        group_barcode_accuracy = _group_barcode_accuracy_summary(
            [_group_barcode_payload_from_row(row) for row in group_barcode_rows],
            photos_by_group_id,
            total_groups=groups,
        )
        return {
            "summary": {
                "team_id": team_id,
                "total_catalog_rows": int(total_catalog_rows),
                "stage_catalog_rows": 0,
                "scan_rows": 0,
                "groups": groups,
                "matched_groups": groups,
                "incomplete_groups": int(group_stats.incomplete_groups or 0),
                "unconstructed_groups": int(group_stats.unconstructed_groups or 0),
                "approved_groups": int(group_stats.approved_groups or 0),
                "exception_groups": int(group_stats.exception_groups or 0),
                "reviewed_groups": reviewed_groups,
                "unreviewed_groups": int(group_stats.unreviewed_groups or 0),
                "stage_unmatched": 0,
                "scan_unmatched": int(scan_unmatched),
                "photo_rows_linked": int(group_stats.photo_rows_linked or 0),
                "scanned_groups": int(group_stats.scanned_groups or 0),
                "installer_distribution": installer_distribution,
                "downloaded_photos": 0,
                "unclassified_photos": 0,
                "review_progress": round(reviewed_groups / groups, 4) if groups else 0.0,
                **photo_accuracy,
                **group_barcode_accuracy,
            },
            "paths": {},
        }

    def _task_by_legacy_id(self, session: Session, task_id: int, *, lock: bool = False) -> Task:
        statement = select(Task).where(Task.team_id == local_simulation.current_team_id(), Task.legacy_id == task_id)
        if lock:
            statement = statement.with_for_update()
        task = session.scalar(statement)
        if task is None:
            raise KeyError(task_id)
        return task

    def _group_by_legacy_id(self, session: Session, group_id: str, *, lock: bool = False) -> MaterialGroup:
        statement = select(MaterialGroup).where(
            MaterialGroup.team_id == local_simulation.current_team_id(),
            MaterialGroup.legacy_id == group_id,
        )
        if lock:
            statement = statement.with_for_update()
        group = session.scalar(statement)
        if group is None:
            raise KeyError(group_id)
        return group

    def _ensure_task_claimed_by(self, session: Session, group: MaterialGroup, actor: str, *, force: bool = False) -> None:
        if force:
            return
        task = None
        if group.task_id is not None:
            task = session.scalar(select(Task).where(Task.id == group.task_id))
        if task is None and group.legacy_task_id is not None:
            task = session.scalar(
                select(Task).where(Task.team_id == group.team_id, Task.legacy_id == group.legacy_task_id)
            )
        if task is None or task.review_claimed_by != actor:
            raise ValueError("Task must be claimed by the current reviewer before review or classification")

    def _task_stats_map(self, session: Session, team_id: str, *, include_search_text: bool = True) -> dict[int, dict[str, Any]]:
        installer_expr = func.coalesce(
            func.nullif(func.trim(MaterialGroup.raw_data.op("->>")("installer")), ""),
            func.nullif(func.trim(MaterialGroup.raw_data.op("->>")("constructor")), ""),
            func.nullif(func.trim(MaterialGroup.raw_data.op("->>")("creator")), ""),
        )
        photo_installer_expr = func.nullif(func.trim(Photo.creator), "")
        active_photo_exists = (
            select(Photo.id)
            .where(
                Photo.group_id == MaterialGroup.id,
                Photo.team_id == MaterialGroup.team_id,
                Photo.is_active.is_(True),
            )
            .exists()
        )
        uploaded_group_condition = or_(MaterialGroup.photo_count > 0, active_photo_exists)
        address_search_expr = (
            func.string_agg(MaterialGroup.installation_address.distinct(), " ")
            if include_search_text
            else literal("")
        )
        meter_search_expr = (
            func.string_agg(
                func.concat(
                    func.coalesce(MaterialGroup.display_meter_no, ""),
                    " ",
                    func.coalesce(MaterialGroup.meter_match_key, ""),
                    " ",
                    func.coalesce(MaterialGroup.legacy_id, ""),
                ).distinct(),
                " ",
            )
            if include_search_text
            else literal("")
        )
        rows = session.execute(
            select(
                MaterialGroup.legacy_task_id,
                func.min(MaterialGroup.installation_address).label("address"),
                address_search_expr.label("address_search_text"),
                meter_search_expr.label("meter_search_text"),
                func.count(MaterialGroup.id).label("total_groups"),
                func.coalesce(func.sum(case((uploaded_group_condition, 1), else_=0)), 0).label("uploaded_count"),
                func.coalesce(
                    func.sum(case((MaterialGroup.status == GroupStatus.APPROVED, 1), else_=0)),
                    0,
                ).label("reviewed_count"),
                func.coalesce(
                    func.sum(case((MaterialGroup.status == GroupStatus.UNREVIEWED, 1), else_=0)),
                    0,
                ).label("unreviewed_count"),
            )
            .where(MaterialGroup.team_id == team_id)
            .group_by(MaterialGroup.legacy_task_id)
        ).all()
        stats_by_task = {
            int(row.legacy_task_id): {
                "total_groups": int(row.total_groups or 0),
                "address": str(row.address or ""),
                "address_search_text": str(row.address_search_text or ""),
                "meter_search_text": str(row.meter_search_text or ""),
                "uploaded_count": int(row.uploaded_count or 0),
                "reviewed_count": int(row.reviewed_count or 0),
                "unreviewed_count": int(row.unreviewed_count or 0),
            }
            for row in rows
            if row.legacy_task_id is not None
        }
        installer_rows = session.execute(
            select(
                MaterialGroup.legacy_task_id,
                photo_installer_expr.label("installer"),
                func.count(MaterialGroup.id.distinct()).label("group_count"),
            )
            .join(
                Photo,
                and_(
                    Photo.group_id == MaterialGroup.id,
                    Photo.team_id == MaterialGroup.team_id,
                    Photo.is_active.is_(True),
                ),
            )
            .where(
                MaterialGroup.team_id == team_id,
                MaterialGroup.legacy_task_id.is_not(None),
                photo_installer_expr.is_not(None),
            )
            .group_by(MaterialGroup.legacy_task_id, photo_installer_expr)
        ).all()
        groups_with_photo_installer = (
            select(Photo.group_id)
            .where(
                Photo.team_id == team_id,
                Photo.is_active.is_(True),
                Photo.group_id.is_not(None),
                photo_installer_expr.is_not(None),
            )
            .distinct()
            .subquery()
        )
        fallback_installer_rows = session.execute(
            select(
                MaterialGroup.legacy_task_id,
                installer_expr.label("installer"),
                func.count(MaterialGroup.id).label("group_count"),
            )
            .where(
                MaterialGroup.team_id == team_id,
                MaterialGroup.legacy_task_id.is_not(None),
                uploaded_group_condition,
                installer_expr.is_not(None),
                ~MaterialGroup.id.in_(select(groups_with_photo_installer.c.group_id)),
            )
            .group_by(MaterialGroup.legacy_task_id, installer_expr)
        ).all()
        installer_counts_by_task: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for row in [*installer_rows, *fallback_installer_rows]:
            if row.legacy_task_id is None:
                continue
            installer = str(row.installer or "").strip()
            if not installer:
                continue
            installer_counts_by_task[int(row.legacy_task_id)][installer] += int(row.group_count or 0)
        installer_name_cache: dict[str, str] = {}
        for task_id, installer_counts in installer_counts_by_task.items():
            stats = stats_by_task.setdefault(task_id, _empty_task_stats())
            stats["installer_distribution"] = _installer_distribution_from_counts(
                installer_counts,
                completed_count=int(stats.get("uploaded_count") or 0),
                name_cache=installer_name_cache,
            )
        return stats_by_task

    def _task_stats(self, session: Session, task: Task) -> dict[str, Any]:
        if task.legacy_id is None:
            return _empty_task_stats()
        return self._task_stats_map(session, task.team_id or local_simulation.current_team_id()).get(
            int(task.legacy_id),
            _empty_task_stats(),
        )

    def list_tasks(self, *, summary_only: bool = False) -> list[dict[str, Any]]:
        with self._session() as session:
            team_id = local_simulation.current_team_id()
            tasks = session.scalars(
                select(Task)
                .where(Task.team_id == team_id)
                .order_by(Task.terminal, Task.legacy_id)
            ).all()
            stats_by_task = self._task_stats_map(session, team_id, include_search_text=not summary_only)
            payloads = [
                _task_payload(task, stats_by_task.get(int(task.legacy_id or 0), _empty_task_stats()))
                for task in tasks
            ]
            if summary_only:
                payloads = [_task_board_payload(task) for task in payloads]
            return sorted(
                payloads,
                key=lambda item: (not item.get("can_claim", False), str(item.get("terminal", "")), item["id"]),
            )

    def task_status(self) -> dict[str, Any]:
        with self._session() as session:
            team_id = local_simulation.current_team_id()
            task_rows_raw = session.execute(
                select(
                    Task.id,
                    Task.legacy_id,
                    Task.terminal,
                    Task.review_claimed_by,
                    Task.construction_claimed_by,
                )
                .where(Task.team_id == team_id)
                .order_by(Task.terminal, Task.legacy_id)
            ).all()
            group_rows = session.execute(
                select(
                    MaterialGroup.legacy_task_id,
                    func.count(MaterialGroup.id).label("total_groups"),
                    func.coalesce(
                        func.sum(case((MaterialGroup.photo_count > 0, 1), else_=0)),
                        0,
                    ).label("uploaded_count"),
                    func.coalesce(
                        func.sum(case((MaterialGroup.status == GroupStatus.APPROVED, 1), else_=0)),
                        0,
                    ).label("reviewed_count"),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    (MaterialGroup.status == GroupStatus.UNREVIEWED)
                                    & (MaterialGroup.photo_count > 0),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("unreviewed_count"),
                )
                .where(MaterialGroup.team_id == team_id, MaterialGroup.legacy_task_id.is_not(None))
                .group_by(MaterialGroup.legacy_task_id)
            ).all()
            stats_by_task = {
                int(row.legacy_task_id): {
                    "total_groups": int(row.total_groups or 0),
                    "uploaded_count": int(row.uploaded_count or 0),
                    "reviewed_count": int(row.reviewed_count or 0),
                    "unreviewed_count": int(row.unreviewed_count or 0),
                }
                for row in group_rows
                if row.legacy_task_id is not None
            }
            task_rows = []
            for row in task_rows_raw:
                stats = stats_by_task.get(int(row.legacy_id or 0), _empty_task_stats())
                task_rows.append(
                    {
                        "id": row.legacy_id if row.legacy_id is not None else str(row.id),
                        "terminal": row.terminal or "",
                        "claimed_by": row.review_claimed_by or "",
                        "construction_assigned_to": row.construction_claimed_by or "",
                        "total_groups": stats.get("total_groups", 0),
                        "uploaded_count": stats.get("uploaded_count", 0),
                        "reviewed_count": stats.get("reviewed_count", 0),
                        "unreviewed_count": stats.get("unreviewed_count", 0),
                    }
                )
            total_catalog_rows = session.scalar(
                select(func.count()).select_from(TotalCatalogRow).where(TotalCatalogRow.team_id == team_id)
            )
            summary = {
                "total_catalog_rows": int(total_catalog_rows or 0),
                "groups": sum(int(row.get("total_groups") or 0) for row in task_rows),
                "photo_rows_linked": sum(int(row.get("uploaded_count") or 0) for row in task_rows),
                "approved_groups": sum(int(row.get("reviewed_count") or 0) for row in task_rows),
                "reviewed_groups": sum(int(row.get("reviewed_count") or 0) for row in task_rows),
                "unreviewed_groups": sum(int(row.get("unreviewed_count") or 0) for row in task_rows),
            }
            return _build_task_status_summary(task_rows, summary)

    def _construction_activity_times_for_installer(
        self,
        session: Session,
        installer: str,
        date_key: str,
    ) -> dict[str, list[datetime]]:
        target = str(installer or "").strip()
        aliases = local_simulation.installer_actor_aliases(target)
        result = {
            "heartbeats": [],
            "pending_non_idle_events": [],
            "deleted_pending_non_idle_events": [],
            "upload_action_times": [],
        }
        if not target or not date_key:
            return result
        action_map = {
            "construction_heartbeat": "heartbeats",
            "group_draft_completed": "pending_non_idle_events",
            "group_draft_deleted": "deleted_pending_non_idle_events",
            "group_uploaded": "upload_action_times",
            "construction_upload_batch": "upload_action_times",
        }
        if not hasattr(session, "scalars"):
            return result
        events = session.scalars(
            select(AuditLog).where(
                AuditLog.team_id == local_simulation.current_team_id(),
                AuditLog.actor_username.in_(tuple(aliases)),
                AuditLog.action.in_(tuple(action_map.keys())),
            )
        ).all()
        for event in events:
            bucket = action_map.get(event.action)
            if not bucket:
                continue
            payload = event.payload or {}
            occurred_at = _datetime_from_value(
                payload.get("occurred_at") or payload.get("client_completed_at") or event.created_at
            )
            if occurred_at and occurred_at.date().isoformat() == date_key:
                result[bucket].append(
                    {
                        "occurred_at": occurred_at,
                        "client_batch_id": str(payload.get("client_batch_id") or ""),
                    }
                )
        return result

    def installer_daily_workload(self, installer: str) -> dict[str, Any]:
        target = str(installer or "").strip()
        if not target:
            return {"installer": target, "items": []}
        with self._session() as session:
            team_id = local_simulation.current_team_id()
            rows = session.execute(
                select(Photo, MaterialGroup)
                .join(MaterialGroup, Photo.group_id == MaterialGroup.id)
                .where(
                    Photo.team_id == team_id,
                    Photo.is_active.is_(True),
                    Photo.creator == target,
                )
                .order_by(Photo.created_at, Photo.sort_order, Photo.legacy_id)
            ).all()
        groups_by_id: dict[str, dict[str, Any]] = {}
        for photo, group in rows:
            bundle = groups_by_id.setdefault(str(group.id), {"group": group, "photos": []})
            bundle["photos"].append(photo)
        rows_by_date: dict[str, dict[str, Any]] = {}
        for bundle in groups_by_id.values():
            group = bundle["group"]
            matched_photos = bundle["photos"]
            construction_dates = [
                _photo_work_date_key(photo)
                for photo in matched_photos
                if _photo_is_construction_upload(photo)
            ]
            date_key = max([date for date in construction_dates if date], default="")
            if not date_key:
                for photo in matched_photos:
                    date_key = _photo_work_date_key(photo)
                    if date_key:
                        break
            date_key = date_key or _date_key_from_value(group.last_photo_imported_at) or "未记录日期"
            row = rows_by_date.setdefault(
                date_key,
                {
                    "date": date_key,
                    "group_count": 0,
                    "photo_count": 0,
                    "archived_count": 0,
                    "exception_count": 0,
                    "unreviewed_count": 0,
                    "exception_groups": [],
                    "_work_timestamps": [],
                    "_completion_records": [],
                },
            )
            photo_times = [value for value in (_photo_work_datetime(photo) for photo in matched_photos) if value]
            confirmed_non_idle_times = [
                value for value in (_photo_confirmed_non_idle_datetime(photo) for photo in matched_photos) if value
            ]
            same_day_times = [value for value in photo_times if value.date().isoformat() == date_key]
            same_day_confirmed_non_idle_times = [
                value for value in confirmed_non_idle_times if value.date().isoformat() == date_key
            ]
            row["_work_timestamps"].extend(same_day_times or photo_times)
            completed_at = max(same_day_times or photo_times, default=None)
            confirmed_non_idle_at = max(same_day_confirmed_non_idle_times or confirmed_non_idle_times, default=None)
            if completed_at:
                row["_completion_records"].append(
                    {
                        "group_id": str(group.id),
                        "meter_no": str(group.display_meter_no or ""),
                        "terminal": str(group.terminal or ""),
                        "address": str(group.installation_address or ""),
                        "status": _status_value(group.status),
                        "photo_count": len(matched_photos),
                        "completed_at": completed_at,
                        "confirmed_non_idle_at": confirmed_non_idle_at,
                    }
                )
            row["group_count"] += 1
            row["photo_count"] += len(matched_photos)
            if _status_value(group.status) == GroupStatus.APPROVED.value:
                row["archived_count"] += 1
            elif (
                _status_value(group.status) == GroupStatus.REJECTED.value
                or group.exception_status == "open"
                or group.has_archive_blocker
            ):
                row["exception_count"] += 1
                row["exception_groups"].append(_installer_exception_group_payload(group, len(matched_photos)))
            else:
                row["unreviewed_count"] += 1
        for row in rows_by_date.values():
            timestamps = row.pop("_work_timestamps", [])
            completion_records = row.pop("_completion_records", [])
            row.update(local_simulation.build_work_time_summary(timestamps, completion_records))
            with self._session() as session:
                activity = self._construction_activity_times_for_installer(session, target, str(row["date"]))
            row.update(
                local_simulation.build_fused_online_work_summary(
                    date_key=str(row["date"]),
                    work_duration_minutes=row.get("work_duration_minutes", 0),
                    weighted_completion=row.get("weighted_completion", 0),
                    heartbeats=activity["heartbeats"],
                    confirmed_completion_times=[record.get("confirmed_non_idle_at") for record in completion_records],
                    efficiency_duration_minutes=row.get("efficiency_duration_minutes", 0),
                    pending_non_idle_events=activity["pending_non_idle_events"],
                    deleted_pending_non_idle_events=activity["deleted_pending_non_idle_events"],
                    upload_action_times=activity["upload_action_times"],
                )
            )
        items = sorted(rows_by_date.values(), key=lambda item: str(item["date"]), reverse=True)
        return {"installer": target, "items": items}
        with self._session() as session:
            team_id = local_simulation.current_team_id()
            day = func.date(Photo.created_at).label("work_date")
            rows = session.execute(
                select(
                    day,
                    func.count(func.distinct(Photo.group_id)).label("group_count"),
                    func.count(Photo.id).label("photo_count"),
                    func.coalesce(
                        func.sum(case((MaterialGroup.status == GroupStatus.APPROVED, 1), else_=0)),
                        0,
                    ).label("archived_photo_rows"),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    (MaterialGroup.status == GroupStatus.REJECTED)
                                    | (MaterialGroup.exception_status == "open")
                                    | (MaterialGroup.has_archive_blocker.is_(True)),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("exception_photo_rows"),
                )
                .join(MaterialGroup, Photo.group_id == MaterialGroup.id)
                .where(
                    Photo.team_id == team_id,
                    Photo.is_active.is_(True),
                    Photo.creator == target,
                )
                .group_by(day)
                .order_by(day.desc())
            ).all()
        items = []
        for row in rows:
            group_count = int(row.group_count or 0)
            archived_photo_rows = int(row.archived_photo_rows or 0)
            exception_photo_rows = int(row.exception_photo_rows or 0)
            archived_count = min(group_count, archived_photo_rows)
            exception_count = min(group_count, exception_photo_rows)
            items.append(
                {
                    "date": str(row.work_date or "未记录日期"),
                    "group_count": group_count,
                    "photo_count": int(row.photo_count or 0),
                    "archived_count": archived_count,
                    "exception_count": exception_count,
                    "unreviewed_count": max(group_count - archived_count - exception_count, 0),
                }
            )
        return {"installer": target, "items": items}

    def list_team_states(self) -> list[dict[str, Any]]:
        with self._session() as session:
            teams = session.scalars(select(Team).order_by(Team.id)).all()
            items: list[dict[str, Any]] = []
            for team in teams:
                group_count = session.scalar(
                    select(func.count()).select_from(MaterialGroup).where(MaterialGroup.team_id == team.id)
                ) or 0
                task_count = session.scalar(
                    select(func.count()).select_from(Task).where(Task.team_id == team.id)
                ) or 0
                summary = {
                    "team_id": team.id,
                    "total_groups": int(group_count),
                    "total_tasks": int(task_count),
                }
                items.append(
                    {
                        "id": team.id,
                        "name": team.name,
                        "status": team.status,
                        "team_id": team.id,
                        "loaded": True,
                        "groups": int(group_count),
                        "tasks": int(task_count),
                        "summary": summary,
                    }
                )
            return items

    def bootstrap(self) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        with self._session() as session:
            team = session.get(Team, team_id)
            if team is None:
                team = Team(id=team_id, name=team_id, status="active")
                session.add(team)
                session.flush()
            project = session.scalar(select(Project).where(Project.team_id == team_id).order_by(Project.created_at))
            if project is None:
                project = Project(
                    code=team_id,
                    name=f"Project {team_id}",
                    status=ProjectStatus.ACTIVE,
                    team_id=team_id,
                    settings={},
                )
                session.add(project)
            session.commit()
        return self.summary()

    def clear_scan_data(self) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        now = datetime.now(UTC)
        with self._session() as session:
            active_photos = session.scalars(
                select(Photo).where(Photo.team_id == team_id, Photo.is_active.is_(True))
            ).all()
            for photo in active_photos:
                photo.is_active = False
                photo.deleted_at = now
                photo.deleted_by = "system"
                photo.delete_reason = "clear_scan_data"
            groups = session.scalars(select(MaterialGroup).where(MaterialGroup.team_id == team_id)).all()
            for group in groups:
                group.photo_count = 0
                group.status = GroupStatus.UNREVIEWED
                group.reviewer = None
                group.review_note = ""
                group.exception_note = ""
                group.exception_reasons = []
                group.has_archive_blocker = False
                group.reviewed_at = None
                raw_data = dict(group.raw_data or {})
                raw_data.update(
                    {"photo_count": 0, "status": "pending", "reviewer": "", "review_note": "", "exception_note": ""}
                )
                group.raw_data = raw_data
            for record in session.scalars(select(UnmatchedRecord).where(UnmatchedRecord.team_id == team_id)).all():
                record.status = "cleared"
            session.commit()
        return self.summary()

    def sync_photos_to_oss(self, *, team_id: str = "", progress_callback=None) -> dict[str, Any]:
        return {"uploaded": 0, "failed": 0, "reused_existing_oss": 0}

    def persist_state(self) -> None:
        return None

    def list_groups(self, *, limit: int = 100, offset: int = 0, status: str | None = None) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        with self._session() as session:
            groups = list(
                session.scalars(
                    select(MaterialGroup)
                    .where(MaterialGroup.team_id == team_id)
                    .order_by(MaterialGroup.terminal, MaterialGroup.display_meter_no, MaterialGroup.legacy_id)
                ).all()
            )
            if status:
                groups = [group for group in groups if _legacy_group_status(group) == status]
            page = groups[offset : offset + limit]
            return {
                "total": len(groups),
                "items": [_group_payload(session, group, include_photos=True) for group in page],
            }

    def list_photo_barcode_review_groups(
        self,
        *,
        status: str = "unreadable",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        with self._session() as session:
            groups = list(
                session.scalars(
                    select(MaterialGroup)
                    .where(MaterialGroup.team_id == team_id)
                    .order_by(MaterialGroup.terminal, MaterialGroup.display_meter_no, MaterialGroup.legacy_id)
                ).all()
            )
            photos = list(
                session.scalars(
                    select(Photo)
                    .where(
                        Photo.team_id == team_id,
                        Photo.is_active.is_(True),
                        Photo.group_id.is_not(None),
                    )
                    .order_by(Photo.group_id, Photo.sort_order, Photo.created_at, Photo.legacy_id)
                ).all()
            )
        photos_by_group_id: dict[str, list[Any]] = defaultdict(list)
        for photo in photos:
            photos_by_group_id[str(photo.group_id)].append(photo)
        payloads = [_group_barcode_payload(group, photos_by_group_id.get(str(group.id), [])) for group in groups]
        statuses = _group_barcode_review_statuses(status)
        items = photo_barcode_check.list_group_barcode_review_items(payloads, statuses=statuses)
        capped_limit = max(1, min(int(limit or 100), 100000))
        safe_offset = max(0, int(offset or 0))
        return {
            "total": len(items),
            "limit": capped_limit,
            "offset": safe_offset,
            "page": (safe_offset // capped_limit) + 1,
            "page_size": capped_limit,
            "items": items[safe_offset : safe_offset + capped_limit],
        }

    def search_group_targets(
        self,
        *,
        query: str = "",
        terminal: str = "",
        limit: int = 30,
        offset: int = 0,
    ) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        statement = select(MaterialGroup).where(MaterialGroup.team_id == team_id)
        if terminal:
            statement = statement.where(MaterialGroup.terminal == terminal)
        for term in [item for item in re.split(r"\s+", query.strip().lower()) if item]:
            pattern = f"%{term}%"
            photo_match = (
                select(Photo.id)
                .where(
                    Photo.team_id == team_id,
                    Photo.group_id == MaterialGroup.id,
                    Photo.is_active.is_(True),
                    or_(
                        Photo.barcode.ilike(pattern),
                        Photo.collector.ilike(pattern),
                        Photo.asset_no.ilike(pattern),
                        Photo.creator.ilike(pattern),
                        Photo.source.ilike(pattern),
                    ),
                )
                .exists()
            )
            task_match = (
                select(Task.id)
                .where(
                    Task.team_id == team_id,
                    Task.id == MaterialGroup.task_id,
                    or_(
                        Task.construction_claimed_by.ilike(pattern),
                        cast(Task.raw_data, String).ilike(pattern),
                    ),
                )
                .exists()
            )
            statement = statement.where(
                or_(
                    MaterialGroup.legacy_id.ilike(pattern),
                    MaterialGroup.terminal.ilike(pattern),
                    MaterialGroup.display_meter_no.ilike(pattern),
                    MaterialGroup.meter_match_key.ilike(pattern),
                    MaterialGroup.installation_address.ilike(pattern),
                    MaterialGroup.reviewer.ilike(pattern),
                    cast(MaterialGroup.raw_data, String).ilike(pattern),
                    photo_match,
                    task_match,
                )
            )
        with self._session() as session:
            total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
            groups = session.scalars(
                statement.order_by(MaterialGroup.terminal, MaterialGroup.display_meter_no, MaterialGroup.legacy_id)
                .offset(offset)
                .limit(limit)
            ).all()
            terminal_rows = session.scalars(
                select(MaterialGroup.terminal)
                .where(MaterialGroup.team_id == team_id, MaterialGroup.terminal.is_not(None), MaterialGroup.terminal != "")
                .distinct()
                .order_by(MaterialGroup.terminal)
            ).all()
            return {
                "total": int(total),
                "terminals": [str(item) for item in terminal_rows],
                "items": [
                    _group_target_summary(_group_payload(session, group, include_photos=True), include_photos=True)
                    for group in groups
                ],
            }

    def list_catalog_rows(
        self,
        catalog_type: str,
        *,
        query: str = "",
        terminal: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        if catalog_type not in {"total", "stage"}:
            raise ValueError("Unsupported catalog type")
        team_id = local_simulation.current_team_id()
        terms = [item for item in re.split(r"\s+", query.strip().lower()) if item]
        with self._session() as session:
            if catalog_type == "total":
                statement = select(TotalCatalogRow).where(TotalCatalogRow.team_id == team_id)
                if terminal:
                    statement = statement.where(TotalCatalogRow.terminal == terminal)
                for term in terms:
                    pattern = f"%{term}%"
                    statement = statement.where(
                        or_(
                            TotalCatalogRow.terminal.ilike(pattern),
                            TotalCatalogRow.original_meter_no.ilike(pattern),
                            TotalCatalogRow.meter_match_key.ilike(pattern),
                            TotalCatalogRow.installation_address.ilike(pattern),
                            TotalCatalogRow.source_file.ilike(pattern),
                        )
                    )
                total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
                rows = session.scalars(
                    statement.order_by(TotalCatalogRow.terminal, TotalCatalogRow.original_meter_no)
                    .offset(offset)
                    .limit(limit)
                ).all()
                terminal_rows = session.scalars(
                    select(TotalCatalogRow.terminal)
                    .where(TotalCatalogRow.team_id == team_id, TotalCatalogRow.terminal.is_not(None), TotalCatalogRow.terminal != "")
                    .distinct()
                    .order_by(TotalCatalogRow.terminal)
                ).all()
                return {
                    "total": int(total),
                    "terminals": [str(item) for item in terminal_rows],
                    "items": [_catalog_row_payload(row) for row in rows],
                }

            stage_statement = select(StageCatalogRow).where(StageCatalogRow.team_id == team_id)
            if terminal:
                stage_statement = stage_statement.where(StageCatalogRow.terminal_no == terminal)
            for term in terms:
                pattern = f"%{term}%"
                stage_statement = stage_statement.where(
                    or_(
                        StageCatalogRow.terminal_no.ilike(pattern),
                        StageCatalogRow.original_barcode.ilike(pattern),
                        StageCatalogRow.meter_match_key.ilike(pattern),
                    )
                )
            total = session.scalar(select(func.count()).select_from(stage_statement.subquery())) or 0
            rows = session.scalars(
                stage_statement.order_by(StageCatalogRow.terminal_no, StageCatalogRow.original_barcode)
                .offset(offset)
                .limit(limit)
            ).all()
            terminal_rows = session.scalars(
                select(StageCatalogRow.terminal_no)
                .where(StageCatalogRow.team_id == team_id, StageCatalogRow.terminal_no.is_not(None), StageCatalogRow.terminal_no != "")
                .distinct()
                .order_by(StageCatalogRow.terminal_no)
            ).all()
            return {
                "total": int(total),
                "terminals": [str(item) for item in terminal_rows],
                "items": [_stage_catalog_row_payload(row) for row in rows],
            }

    def list_task_groups(
        self,
        task_id: int,
        *,
        limit: int = 100,
        offset: int = 0,
        status: str | None = None,
        scan_only: bool = False,
        summary_only: bool = False,
    ) -> dict[str, Any]:
        with self._session() as session:
            self._task_by_legacy_id(session, task_id)
            statement = select(MaterialGroup).where(
                MaterialGroup.team_id == local_simulation.current_team_id(),
                MaterialGroup.legacy_task_id == task_id,
            )
            groups = list(session.scalars(statement).all())
            if scan_only:
                groups = [group for group in groups if group.photo_count >= 4 and _legacy_group_status(group) not in {"incomplete", "exception", "unmatched"}]
            if status:
                groups = [group for group in groups if _legacy_group_status(group) == status]
            group_payloads = [_group_payload(session, group, include_photos=not summary_only) for group in groups]
            group_payloads.sort(
                key=lambda group: (
                    _review_queue_rank(group),
                    str(group.get("meter_no") or ""),
                    str(group.get("id") or ""),
                )
            )
            page = group_payloads[offset : offset + limit]
            if summary_only:
                page_group_model_ids = [
                    group.id
                    for group in groups
                    if any(str(item.get("id") or "") == str(group.legacy_id or group.id) for item in page)
                ]
                photos_by_group_model_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
                if page_group_model_ids:
                    photo_rows = session.execute(
                        select(
                            Photo.group_id,
                            Photo.id.label("photo_id"),
                            Photo.legacy_id,
                            Photo.category,
                            Photo.barcode,
                            Photo.collector,
                            Photo.asset_no,
                            Photo.raw_data,
                        )
                        .where(
                            Photo.team_id == local_simulation.current_team_id(),
                            Photo.group_id.in_(page_group_model_ids),
                            Photo.is_active.is_(True),
                        )
                        .order_by(Photo.group_id, Photo.sort_order, Photo.created_at, Photo.legacy_id)
                    ).all()
                    for row in photo_rows:
                        photos_by_group_model_id[str(row.group_id)].append(_photo_barcode_payload_from_row(row))
                legacy_to_model_id = {str(group.legacy_id or group.id): str(group.id) for group in groups}
                for item in page:
                    item["photos"] = photos_by_group_model_id.get(legacy_to_model_id.get(str(item.get("id") or ""), ""), [])
                return {"total": len(group_payloads), "items": [_group_target_summary(group) for group in page]}
            return {
                "total": len(group_payloads),
                "items": [_apply_construction_status(group) for group in page],
            }

    def get_group(self, group_id: str) -> dict[str, Any] | None:
        with self._session() as session:
            group = session.scalar(
                select(MaterialGroup).where(
                    MaterialGroup.team_id == local_simulation.current_team_id(),
                    MaterialGroup.legacy_id == group_id,
                )
            )
            return _group_payload(session, group) if group is not None else None

    def list_unmatched_records(self, *, query: str = "", limit: int = 100, offset: int = 0) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        statement = select(UnmatchedRecord).where(
            UnmatchedRecord.team_id == team_id,
            UnmatchedRecord.status == "open",
        )
        for term in [item.strip() for item in query.split() if item.strip()]:
            pattern = f"%{term}%"
            statement = statement.where(
                or_(
                    UnmatchedRecord.barcode.ilike(pattern),
                    UnmatchedRecord.meter_no.ilike(pattern),
                    UnmatchedRecord.meter_match_key.ilike(pattern),
                    UnmatchedRecord.terminal.ilike(pattern),
                    UnmatchedRecord.address.ilike(pattern),
                    UnmatchedRecord.collector.ilike(pattern),
                    UnmatchedRecord.module_asset_no.ilike(pattern),
                )
            )
        with self._session() as session:
            total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
            records = session.scalars(
                statement.order_by(UnmatchedRecord.terminal, UnmatchedRecord.barcode, UnmatchedRecord.legacy_id)
                .offset(offset)
                .limit(limit)
            ).all()
            return {"total": int(total), "items": [_unmatched_payload(record) for record in records]}

    def list_replacement_records(self, *, query: str = "", limit: int = 100, offset: int = 0) -> dict[str, Any]:
        with self._session() as session:
            groups = session.scalars(
                select(MaterialGroup).where(MaterialGroup.team_id == local_simulation.current_team_id())
            ).all()
            group_payloads = [_group_payload(session, group, include_photos=False) for group in groups]
        return local_simulation.list_replacement_records_from_groups(
            group_payloads,
            query=query,
            limit=limit,
            offset=offset,
        )

    def dedupe_unmatched_records(self, *, actor: str) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        with self._session() as session:
            records = list(
                session.scalars(
                    select(UnmatchedRecord)
                    .where(UnmatchedRecord.team_id == team_id, UnmatchedRecord.status == "open")
                    .with_for_update()
                ).all()
            )
            winners: dict[str, UnmatchedRecord] = {}
            duplicates: list[UnmatchedRecord] = []
            for record in records:
                payload = _unmatched_payload(record)
                key = local_simulation.make_unmatched_duplicate_key(payload)
                if key.startswith("id:"):
                    winners[key] = record
                    continue
                current = winners.get(key)
                if current is None:
                    winners[key] = record
                    continue
                if local_simulation.unmatched_keep_score(payload) > local_simulation.unmatched_keep_score(
                    _unmatched_payload(current)
                ):
                    duplicates.append(current)
                    winners[key] = record
                else:
                    duplicates.append(record)
            now = datetime.now(UTC).isoformat()
            duplicate_ids = [str(record.legacy_id) for record in duplicates]
            for record in duplicates:
                raw = dict(record.payload or {})
                raw.update(
                    {
                        "dedupe_deleted_by": actor,
                        "dedupe_deleted_at": now,
                        "dedupe_delete_reason": "duplicate unmatched record",
                    }
                )
                record.payload = raw
                record.status = "deduped"
            if duplicates:
                event = AuditLog(
                    team_id=team_id,
                    legacy_id=f"dedupe-unmatched-{uuid4()}",
                    actor_username=actor,
                    action="dedupe_unmatched",
                    entity_type="unmatched_records",
                    payload={"removed": len(duplicates), "duplicate_ids": duplicate_ids},
                )
                session.add(event)
                session.commit()
            return {
                "total": len(records),
                "kept": len(records) - len(duplicates),
                "removed": len(duplicates),
                "duplicate_ids": duplicate_ids,
            }

    def create_blank_unmatched_record(self, *, actor: str) -> dict[str, Any]:
        created_at = datetime.now(UTC).isoformat()
        record = UnmatchedRecord(
            team_id=local_simulation.current_team_id(),
            legacy_id=f"manual-blank-{created_at}",
            record_type="blank_group",
            status="open",
            terminal="",
            meter_no="",
            meter_match_key="",
            barcode="",
            collector="",
            module_asset_no="",
            address="",
            payload={"created_by": actor, "created_at": created_at, "photo_urls": []},
        )
        with self._session() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return {"record": _unmatched_payload(record)}

    def update_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        updates = updates or {}
        with self._session() as session:
            record = session.scalar(
                select(UnmatchedRecord)
                .where(
                    UnmatchedRecord.team_id == local_simulation.current_team_id(),
                    UnmatchedRecord.legacy_id == unmatched_id,
                    UnmatchedRecord.status == "open",
                )
                .with_for_update()
            )
            if record is None:
                raise KeyError(unmatched_id)
            raw = dict(record.payload or {})
            for key in (
                "barcode",
                "meter_no",
                "meter_match_key",
                "terminal",
                "address",
                "collector",
                "module_asset_no",
                "asset_no",
                "creator",
                "note",
                "assignment_note",
                "replacement_old_meter_no",
            ):
                if key in updates:
                    value = str(updates.get(key) or "").strip()
                    if key == "asset_no":
                        record.module_asset_no = value
                    elif hasattr(record, key):
                        setattr(record, key, value)
                    else:
                        raw[key] = value
            record.payload = {**raw, "updated_by": actor, "updated_at": datetime.now(UTC).isoformat()}
            session.commit()
            session.refresh(record)
            return {"record": _unmatched_payload(record)}

    def assign_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        constructor: str,
        note: str = "",
        due_date: str = "",
    ) -> dict[str, Any]:
        constructor = constructor.strip()
        if not constructor:
            raise ValueError("Constructor is required")
        with self._session() as session:
            record = session.scalar(
                select(UnmatchedRecord)
                .where(
                    UnmatchedRecord.team_id == local_simulation.current_team_id(),
                    UnmatchedRecord.legacy_id == unmatched_id,
                    UnmatchedRecord.status == "open",
                )
                .with_for_update()
            )
            if record is None:
                raise KeyError(unmatched_id)
            terminal = str(record.terminal or "").strip()
            if terminal:
                task = session.scalar(
                    select(Task)
                    .where(Task.team_id == record.team_id, Task.terminal == terminal)
                    .with_for_update()
                )
                if task is not None:
                    self._ensure_construction_assignment_capacity(
                        session,
                        team_id=record.team_id,
                        constructor=constructor,
                        excluding_task_id=task.id,
                    )
                    now = datetime.now(UTC)
                    task_raw = dict(task.raw_data or {})
                    task_raw["construction_assignment_note"] = note.strip()
                    task_raw["construction_due_date"] = due_date.strip()
                    task.raw_data = task_raw
                    task.construction_enabled = True
                    task.construction_claimed_by = constructor
                    task.construction_claimed_at = now
                    task.construction_released_at = None
                    task.construction_opened_by = actor.strip() or "admin"
                    task.construction_opened_at = task.construction_opened_at or now
            raw = dict(record.payload or {})
            raw.update(
                {
                    "assigned_to": constructor,
                    "assigned_by": actor,
                    "assigned_at": datetime.now(UTC).isoformat(),
                    "assignment_note": note.strip(),
                    "due_date": due_date.strip(),
                    "field_task_type": "unmatched",
                }
            )
            record.payload = raw
            session.commit()
            session.refresh(record)
            return {"record": _unmatched_payload(record)}

    def unassign_unmatched_record(self, unmatched_id: str, *, actor: str, reason: str = "") -> dict[str, Any]:
        with self._session() as session:
            record = session.scalar(
                select(UnmatchedRecord)
                .where(
                    UnmatchedRecord.team_id == local_simulation.current_team_id(),
                    UnmatchedRecord.legacy_id == unmatched_id,
                    UnmatchedRecord.status == "open",
                )
                .with_for_update()
            )
            if record is None:
                raise KeyError(unmatched_id)
            raw = dict(record.payload or {})
            raw.update(
                {
                    "assigned_to": "",
                    "unassigned_by": actor,
                    "unassigned_at": datetime.now(UTC).isoformat(),
                    "unassign_reason": reason.strip(),
                }
            )
            record.payload = raw
            session.commit()
            session.refresh(record)
            return {"record": _unmatched_payload(record)}

    def mark_unmatched_outside_project(self, unmatched_id: str, *, actor: str, note: str = "") -> dict[str, Any]:
        with self._session() as session:
            record = session.scalar(
                select(UnmatchedRecord)
                .where(
                    UnmatchedRecord.team_id == local_simulation.current_team_id(),
                    UnmatchedRecord.legacy_id == unmatched_id,
                    UnmatchedRecord.status == "open",
                )
                .with_for_update()
            )
            if record is None:
                raise KeyError(unmatched_id)
            raw = dict(record.payload or {})
            raw.update(
                {
                    "project_outside": True,
                    "project_outside_by": actor,
                    "project_outside_at": datetime.now(UTC).isoformat(),
                    "project_outside_note": note.strip(),
                    "field_task_type": "outside_project",
                }
            )
            record.payload = raw
            session.commit()
            session.refresh(record)
            return {"record": _unmatched_payload(record)}

    def rematch_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        meter_no: str = "",
        old_meter_no: str = "",
        terminal: str = "",
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        updates = dict(updates or {})
        meter_no = meter_no.strip()
        old_meter_no = old_meter_no.strip()
        terminal = terminal.strip()
        if meter_no:
            updates.update(
                {
                    "meter_no": meter_no,
                    "barcode": meter_no,
                    "meter_match_key": local_simulation.build_total_catalog_match_key(meter_no) or meter_no,
                }
            )
        if terminal:
            updates["terminal"] = terminal
        if old_meter_no:
            updates["replacement_old_meter_no"] = old_meter_no
        updated = self.update_unmatched_record(unmatched_id, actor=actor, updates=updates)["record"]
        reference = old_meter_no or meter_no or str(updated.get("meter_no") or updated.get("barcode") or "")
        match_key = local_simulation.build_total_catalog_match_key(reference) or reference
        with self._session() as session:
            statement = select(MaterialGroup).where(MaterialGroup.team_id == local_simulation.current_team_id())
            if terminal or updated.get("terminal"):
                statement = statement.where(MaterialGroup.terminal == (terminal or updated.get("terminal")))
            target = session.scalar(
                statement.where(
                    or_(
                        MaterialGroup.legacy_id == reference,
                        MaterialGroup.display_meter_no == reference,
                        MaterialGroup.meter_match_key == match_key,
                    )
                ).limit(1)
            )
        if target is None:
            return {"record": updated, "matched": False}
        associate_updates = dict(updated)
        if old_meter_no:
            associate_updates["replacement_old_meter_no"] = old_meter_no
            associate_updates["replacement_target_group_id"] = target.legacy_id
            associate_updates["replacement_new_meter_no"] = meter_no or str(updated.get("meter_no") or updated.get("barcode") or "")
            associate_updates["meter_no"] = target.display_meter_no
        associated = self.associate_unmatched_record(
            unmatched_id,
            actor=actor,
            target_group_id=str(target.legacy_id),
            updates=associate_updates,
        )
        associated["matched"] = True
        associated["replacement_old_meter_no"] = old_meter_no
        return associated

    def list_exception_groups(self, *, reviewer: str = "", limit: int = 100, offset: int = 0) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        statement = select(MaterialGroup).where(
            MaterialGroup.team_id == team_id,
            MaterialGroup.photo_count > 0,
            or_(
                MaterialGroup.status.in_([GroupStatus.INCOMPLETE, GroupStatus.REJECTED]),
                MaterialGroup.has_archive_blocker.is_(True),
                MaterialGroup.exception_status == "open",
            ),
        )
        if reviewer:
            claimed_task_ids = select(Task.legacy_id).where(Task.team_id == team_id, Task.review_claimed_by == reviewer)
            statement = statement.where(
                or_(
                    MaterialGroup.legacy_task_id.in_(claimed_task_ids),
                    MaterialGroup.terminal.is_(None),
                    MaterialGroup.terminal == "",
                )
            )
        with self._session() as session:
            candidates = session.scalars(statement).all()
            if candidates:
                module_groups = _collect_material_group_module_map(session, team_id)
                changed = False
                for group in candidates:
                    changed = _refresh_group_archive_exceptions(session, group, module_groups) or changed
                if changed:
                    session.commit()
            total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
            groups = session.scalars(
                statement.order_by(MaterialGroup.terminal, MaterialGroup.display_meter_no, MaterialGroup.legacy_id)
                .offset(offset)
                .limit(limit)
            ).all()
            return {
                "total": int(total),
                "items": [_group_payload(session, group, include_photos=False) for group in groups],
            }

    def update_group_metadata(
        self,
        group_id: str,
        *,
        actor: str,
        updates: dict[str, Any],
        audit_action: str = "update_group_metadata",
    ) -> dict[str, Any]:
        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id, lock=True)
            before = _group_payload(session, group, include_photos=False)
            raw_data = dict(group.raw_data or {})
            if "meter_no" in updates:
                group.display_meter_no = str(updates.get("meter_no") or "").strip()
                raw_data["meter_no"] = group.display_meter_no
            if "meter_match_key" in updates:
                group.meter_match_key = str(updates.get("meter_match_key") or "").strip() or None
                raw_data["meter_match_key"] = group.meter_match_key or ""
            if "terminal" in updates:
                group.terminal = str(updates.get("terminal") or "").strip()
                raw_data["terminal"] = group.terminal or ""
            if "address" in updates:
                group.installation_address = str(updates.get("address") or "").strip()
                raw_data["address"] = group.installation_address
            if "status" in updates:
                status_value = str(updates.get("status") or "").strip()
                status_map = {
                    "pending": GroupStatus.UNREVIEWED,
                    "unreviewed": GroupStatus.UNREVIEWED,
                    "incomplete": GroupStatus.INCOMPLETE,
                    "approved": GroupStatus.APPROVED,
                    "exception": GroupStatus.REJECTED,
                    "rejected": GroupStatus.REJECTED,
                }
                mapped_status = status_map.get(status_value)
                if mapped_status is None:
                    raise ValueError(f"Unsupported group status: {status_value}")
                group.status = mapped_status
                raw_data["status"] = status_value
            if "reviewer" in updates:
                group.reviewer = str(updates.get("reviewer") or "").strip() or None
                raw_data["reviewer"] = group.reviewer or ""
            if "review_note" in updates:
                group.review_note = str(updates.get("review_note") or "").strip()
                raw_data["review_note"] = group.review_note
            if "exception_note" in updates:
                group.exception_note = str(updates.get("exception_note") or "").strip()
                raw_data["exception_note"] = group.exception_note
            if "construction_collector" in updates:
                raw_data["construction_collector"] = str(updates.get("construction_collector") or "").strip()
            if "construction_module_asset_no" in updates:
                raw_data["construction_module_asset_no"] = str(updates.get("construction_module_asset_no") or "").strip()

            photo_updates = {
                "collector": "collector",
                "module_asset_no": "asset_no",
                "creator": "creator",
            }
            active_photos = []
            if any(key in updates for key in photo_updates):
                active_photos = session.scalars(
                    select(Photo).where(
                        Photo.team_id == group.team_id,
                        Photo.group_id == group.id,
                        Photo.is_active.is_(True),
                    )
                ).all()
            for incoming, attribute in photo_updates.items():
                if incoming not in updates:
                    continue
                value = str(updates.get(incoming) or "").strip()
                raw_data[incoming] = value
                for photo in active_photos:
                    setattr(photo, attribute, value)
                    photo_raw = dict(photo.raw_data or {})
                    photo_raw[incoming] = value
                    photo.raw_data = photo_raw

            group.raw_data = raw_data
            validation_group = _group_payload(session, group, include_photos=True)
            reasons = local_simulation.validate_group_archive(validation_group)
            group.exception_reasons = reasons
            group.has_archive_blocker = bool(reasons)
            group.exception_status = "open" if reasons else None
            raw_data["exception_reasons"] = reasons
            if reasons and "status" not in updates and group.status == GroupStatus.APPROVED:
                group.status = GroupStatus.INCOMPLETE
                raw_data["status"] = "incomplete"
            if (
                "status" not in updates
                and group.status in {GroupStatus.INCOMPLETE, GroupStatus.REJECTED}
                and not reasons
                and not group.exception_note
            ):
                group.status = GroupStatus.UNREVIEWED
                raw_data["status"] = "pending"
            group.raw_data = raw_data
            group.updated_at = datetime.now(UTC)
            after = _group_payload(session, group, include_photos=False)
            comparable_fields = {
                "meter_no",
                "meter_match_key",
                "terminal",
                "address",
                "status",
                "reviewer",
                "review_note",
                "exception_note",
                "collector",
                "module_asset_no",
                "creator",
                "construction_collector",
                "construction_module_asset_no",
            }
            changed_fields = sorted(
                field for field in comparable_fields if field in updates and str(before.get(field) or "") != str(after.get(field) or "")
            )
            if changed_fields:
                session.add(
                    AuditLog(
                        team_id=local_simulation.current_team_id(),
                        legacy_id=f"{audit_action}-{uuid4()}",
                        actor_username=actor,
                        action=audit_action,
                        entity_type="material_group",
                        entity_id=group.id,
                        before_data={field: before.get(field) for field in changed_fields},
                        after_data={field: after.get(field) for field in changed_fields},
                        payload={"group_id": group.legacy_id or str(group.id), "changed_fields": changed_fields},
                    )
                )
            session.commit()
            session.refresh(group)
            return {"group": _group_payload(session, group), "changed_fields": changed_fields}

    def claim_task(self, task_id: int, reviewer: str) -> dict[str, Any]:
        with self._session() as session:
            task = self._task_by_legacy_id(session, task_id, lock=True)
            payload = _task_payload(task, self._task_stats(session, task))
            if not payload.get("can_claim"):
                raise ValueError(payload.get("claim_block_reason") or "Task has no scan information")
            if task.status not in {TaskStatus.PUBLISHED, TaskStatus.RELEASED, TaskStatus.CLAIMED}:
                raise ValueError(f"Task cannot be claimed from status {_status_value(task.status)}")
            if task.review_claimed_by and task.review_claimed_by != reviewer:
                raise ValueError("Task is already claimed by another reviewer")
            task.status = TaskStatus.CLAIMED
            task.review_claimed_by = reviewer
            task.claimed_at = datetime.now(UTC)
            task.released_at = None
            session.commit()
            session.refresh(task)
            return _task_payload(task, self._task_stats(session, task))

    def release_task(self, task_id: int, reviewer: str, *, force: bool = False) -> dict[str, Any]:
        with self._session() as session:
            task = self._task_by_legacy_id(session, task_id, lock=True)
            if not force and task.review_claimed_by not in {None, reviewer}:
                raise ValueError("Only the current reviewer can release this task")
            task.status = TaskStatus.RELEASED
            task.review_claimed_by = None
            task.released_at = datetime.now(UTC)
            session.commit()
            session.refresh(task)
            return _task_payload(task, self._task_stats(session, task))

    def get_task_progress(self, task_id: int) -> dict[str, Any]:
        with self._session() as session:
            task = self._task_by_legacy_id(session, task_id)
            groups = [
                _group_payload(session, group, include_photos=False)
                for group in session.scalars(
                    select(MaterialGroup).where(
                        MaterialGroup.team_id == local_simulation.current_team_id(),
                        MaterialGroup.legacy_task_id == task_id,
                    )
                ).all()
            ]
            by_status = {status: 0 for status in sorted(REVIEWABLE_STATUSES)}
            for group in groups:
                status = str(group.get("status") or "")
                by_status[status] = by_status.get(status, 0) + 1
            return {
                "task_id": task_id,
                "status": _legacy_task_status(task),
                "claimed_by": task.review_claimed_by,
                "total_groups": len(groups),
                "reviewed_groups": sum(1 for group in groups if _is_reviewed_group(group)),
                "pending_groups": sum(1 for group in groups if _is_unreviewed_group(group)),
                "approved_groups": by_status.get("approved", 0),
                "exception_groups": sum(1 for group in groups if _is_problem_group(group)),
                "incomplete_groups": _count_incomplete_scanned_groups(groups),
                "unconstructed_groups": _count_unconstructed_groups(groups),
                "complete_groups": _count_complete_groups(groups),
                "partial_groups": _count_partial_groups(groups),
                "by_status": by_status,
                "progress": _calculate_progress(groups),
                "completeness_rate": _calculate_completeness_rate(groups, scan_only=True),
            }

    def release_all_claimed_tasks(self, actor: str) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        released_ids: list[int] = []
        with self._session() as session:
            tasks = session.scalars(
                select(Task)
                .where(Task.team_id == team_id, Task.review_claimed_by.is_not(None))
                .with_for_update()
                .order_by(Task.legacy_id)
            ).all()
            now = datetime.now(UTC)
            for task in tasks:
                task.status = TaskStatus.RELEASED
                task.review_claimed_by = None
                task.released_at = now
                if task.legacy_id is not None:
                    released_ids.append(int(task.legacy_id))
            session.commit()
        return {"released": len(released_ids), "task_ids": released_ids, "actor": actor}

    def list_audit_events(self, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        statement = select(AuditLog).where(AuditLog.team_id == team_id)
        with self._session() as session:
            total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
            rows = session.scalars(
                statement.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset(offset).limit(limit)
            ).all()
            return {
                "total": int(total),
                "items": [
                    {
                        "id": row.legacy_id or str(row.id),
                        "action": row.action,
                        "actor": row.actor_username or "",
                        "payload": row.payload or row.after_data or {},
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                    }
                    for row in rows
                ],
            }

    def record_construction_activity_event(
        self,
        *,
        event_type: str,
        actor: str,
        task_id: str | int | None = None,
        group_id: str = "",
        client_batch_id: str = "",
        occurred_at: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if event_type not in local_simulation.CONSTRUCTION_ACTIVITY_ACTIONS:
            raise ValueError(f"Unsupported construction activity event: {event_type}")
        actor = str(actor or "").strip() or "constructor"
        event_payload = {
            "task_id": task_id,
            "group_id": str(group_id or ""),
            "client_batch_id": str(client_batch_id or ""),
            "occurred_at": occurred_at or datetime.now(UTC).isoformat(),
            **(payload or {}),
        }
        with self._session() as session:
            self._add_construction_activity_audit(session, event_type, actor, event_payload)
            session.commit()
        return {"event_type": event_type, "actor": actor, **event_payload}

    def _add_construction_activity_audit(
        self,
        session: Session,
        event_type: str,
        actor: str,
        event_payload: dict[str, Any],
    ) -> None:
        session.add(
            AuditLog(
                team_id=local_simulation.current_team_id(),
                legacy_id=f"construction-activity-{uuid4()}",
                actor_username=actor,
                action=event_type,
                entity_type="construction_activity",
                entity_id=None,
                payload=event_payload,
                before_data=None,
                after_data=None,
            )
        )

    def list_construction_tasks(self, *, actor: str = "", include_closed: bool = False) -> list[dict[str, Any]]:
        team_id = local_simulation.current_team_id()
        actor = actor.strip()
        with self._session() as session:
            statement = select(Task).where(Task.team_id == team_id)
            if actor and not include_closed:
                statement = statement.where(
                    Task.construction_enabled.is_(True),
                    Task.construction_claimed_by == actor,
                )
            tasks = session.scalars(statement.order_by(Task.terminal, Task.legacy_id)).all()
            stats_by_task = self._task_stats_map(session, team_id)
            payloads = [
                _construction_task_payload(task, stats_by_task.get(int(task.legacy_id or 0), _empty_task_stats()))
                for task in tasks
            ]
        if actor and not include_closed:
            return sorted(payloads, key=lambda task: (str(task.get("terminal", "")), task["id"]))
        if not include_closed:
            payloads = [
                task
                for task in payloads
                if task.get("construction_enabled") and task.get("construction_claimed_by")
            ]
        return sorted(
            payloads,
            key=lambda task: (
                -int(task.get("uploaded_count") or 0) if include_closed else 0,
                -int(task.get("unconstructed_groups") or 0) if include_closed else 0,
                -int(task.get("exception_order_count") or 0) if include_closed else 0,
                not bool(actor and task.get("construction_claimed_by") == actor),
                str(task.get("terminal", "")),
                task["id"],
            ),
        )

    def open_construction_task(self, task_id: int, actor: str) -> dict[str, Any]:
        with self._session() as session:
            task = self._task_by_legacy_id(session, task_id, lock=True)
            task.construction_enabled = True
            task.construction_opened_by = actor.strip() or "admin"
            task.construction_opened_at = datetime.now(UTC)
            task.construction_closed_at = None
            session.commit()
            session.refresh(task)
            return _construction_task_payload(task, self._task_stats(session, task))

    def close_construction_task(self, task_id: int, actor: str) -> dict[str, Any]:
        with self._session() as session:
            task = self._task_by_legacy_id(session, task_id, lock=True)
            task.construction_enabled = False
            task.construction_closed_at = datetime.now(UTC)
            session.commit()
            session.refresh(task)
            return _construction_task_payload(task, self._task_stats(session, task))

    def assign_construction_task(
        self,
        task_id: int,
        *,
        actor: str,
        constructor: str,
        note: str = "",
        due_date: str = "",
    ) -> dict[str, Any]:
        constructor = constructor.strip()
        if not constructor:
            raise ValueError("Constructor is required")
        team_id = local_simulation.current_team_id()
        with self._session() as session:
            task = self._task_by_legacy_id(session, task_id, lock=True)
            self._ensure_construction_assignment_capacity(
                session,
                team_id=team_id,
                constructor=constructor,
                excluding_task_id=task.id,
            )
            now = datetime.now(UTC)
            raw = dict(task.raw_data or {})
            raw["construction_assignment_note"] = note.strip()
            raw["construction_due_date"] = due_date.strip()
            task.raw_data = raw
            task.construction_enabled = True
            task.construction_claimed_by = constructor
            task.construction_claimed_at = now
            task.construction_released_at = None
            task.construction_opened_by = actor.strip() or "admin"
            task.construction_opened_at = task.construction_opened_at or now
            session.commit()
            session.refresh(task)
            return _construction_task_payload(task, self._task_stats(session, task))

    def unassign_construction_task(self, task_id: int, *, actor: str, reason: str = "") -> dict[str, Any]:
        with self._session() as session:
            task = self._task_by_legacy_id(session, task_id, lock=True)
            raw = dict(task.raw_data or {})
            raw["construction_assignment_note"] = ""
            raw["construction_unassign_reason"] = reason.strip()
            raw["construction_unassigned_by"] = actor.strip() or "admin"
            task.raw_data = raw
            task.construction_claimed_by = None
            task.construction_released_at = datetime.now(UTC)
            session.commit()
            session.refresh(task)
            return _construction_task_payload(task, self._task_stats(session, task))

    def claim_construction_task(self, task_id: int, actor: str) -> dict[str, Any]:
        actor = actor.strip() or "constructor"
        with self._session() as session:
            task = self._task_by_legacy_id(session, task_id)
            if not task.construction_enabled:
                raise ValueError("该终端尚未开放施工")
            if task.construction_claimed_by != actor:
                raise ValueError("Construction task must be assigned by an administrator before entry")
            return _construction_task_payload(task, self._task_stats(session, task))

    def release_construction_task(self, task_id: int, actor: str, *, force: bool = False) -> dict[str, Any]:
        actor = actor.strip() or "constructor"
        with self._session() as session:
            task = self._task_by_legacy_id(session, task_id, lock=True)
            if not force and task.construction_claimed_by not in {None, actor}:
                raise ValueError("只有当前施工员可以释放该终端")
            task.construction_claimed_by = None
            task.construction_released_at = datetime.now(UTC)
            session.commit()
            session.refresh(task)
            return _construction_task_payload(task, self._task_stats(session, task))

    def list_construction_task_groups(
        self,
        task_id: int,
        *,
        limit: int = 100,
        offset: int = 0,
        status: str | None = None,
        summary_only: bool = False,
    ) -> dict[str, Any]:
        with self._session() as session:
            self._task_by_legacy_id(session, task_id)
            groups = list(
                session.scalars(
                    select(MaterialGroup)
                    .where(
                        MaterialGroup.team_id == local_simulation.current_team_id(),
                        MaterialGroup.legacy_task_id == task_id,
                        MaterialGroup.photo_count == 0,
                    )
                    .order_by(MaterialGroup.display_meter_no, MaterialGroup.legacy_id)
                ).all()
            )
            groups = [
                group
                for group in groups
                if _legacy_group_status(group) not in {"unmatched", "exception"}
                and (not status or _legacy_group_status(group) == status)
            ]
            payloads = [_group_payload(session, group, include_photos=not summary_only) for group in groups]
            page = payloads[offset : offset + limit]
            if summary_only:
                return {"total": len(payloads), "items": [_group_target_summary(group) for group in page]}
            return {
                "total": len(payloads),
                "items": [_apply_construction_status(group) for group in page],
            }

    def _exception_order_payload(
        self,
        session: Session,
        order: ExceptionItem,
        group: MaterialGroup | None = None,
    ) -> dict[str, Any]:
        if group is None and order.group_id is not None:
            group = session.scalar(select(MaterialGroup).where(MaterialGroup.id == order.group_id))
        task = None
        if group is not None and group.task_id is not None:
            task = session.scalar(select(Task).where(Task.id == group.task_id))
        active_photos = []
        if group is not None:
            active_photos = session.scalars(
                select(Photo)
                .where(Photo.team_id == group.team_id, Photo.group_id == group.id, Photo.is_active.is_(True))
                .order_by(Photo.sort_order, Photo.created_at, Photo.legacy_id)
            ).all()
        collector = next((photo.collector for photo in active_photos if photo.collector), "")
        module_asset_no = next((photo.asset_no for photo in active_photos if photo.asset_no), "")
        raw = group.raw_data if group is not None and group.raw_data else {}
        order_payload = getattr(order, "payload", None) or {}
        assignments = raw.get("exception_order_assignments") if isinstance(raw, dict) else {}
        assignment = assignments.get(str(order.id), {}) if isinstance(assignments, dict) else {}
        return {
            "id": str(order.id),
            "team_id": order.team_id,
            "task_id": group.legacy_task_id if group is not None else None,
            "group_id": group.legacy_id if group is not None else "",
            "terminal": group.terminal if group is not None else "",
            "status": order.status.value if hasattr(order.status, "value") else str(order.status),
            "category": order.category,
            "note": order.description,
            "assigned_to": assignment.get("assigned_to") or (task.construction_claimed_by if task is not None else ""),
            "assigned_by": assignment.get("assigned_by") or "",
            "assigned_at": assignment.get("assigned_at") or "",
            "assignment_note": assignment.get("assignment_note") or "",
            "due_date": assignment.get("due_date") or "",
            "created_by": order_payload.get("created_by", ""),
            "submitted_by": order_payload.get("submitted_by", ""),
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "updated_at": order.updated_at.isoformat() if getattr(order, "updated_at", None) else None,
            "submitted_at": order.resolved_at.isoformat() if order.resolved_at else None,
            "resolved_at": order.resolved_at.isoformat() if order.resolved_at else None,
            "payload": {
                "meter_no": group.display_meter_no if group is not None else "",
                "collector": raw.get("construction_collector") or collector,
                "module_asset_no": raw.get("construction_module_asset_no") or module_asset_no,
                "address": group.installation_address if group is not None else "",
            },
        }

    def list_construction_exception_orders(
        self,
        *,
        actor: str = "",
        task_id: int | None = None,
    ) -> list[dict[str, Any]]:
        actor = actor.strip()
        team_id = local_simulation.current_team_id()
        with self._session() as session:
            statement = select(ExceptionItem).where(ExceptionItem.team_id == team_id)
            if task_id is not None:
                task = self._task_by_legacy_id(session, task_id)
                statement = statement.where(ExceptionItem.task_id == task.id)
            orders = session.scalars(statement.order_by(ExceptionItem.created_at, ExceptionItem.id)).all()
            payloads = [self._exception_order_payload(session, order) for order in orders]
        if actor:
            payloads = [item for item in payloads if item.get("assigned_to") == actor]
        return sorted(
            payloads,
            key=lambda item: (
                str(item.get("terminal") or ""),
                str(item.get("created_at") or ""),
                str(item.get("id") or ""),
            ),
        )

    def submit_construction_exception_order(
        self,
        order_id: str,
        *,
        actor: str,
        updates: dict[str, Any] | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        actor = actor.strip() or "constructor"
        updates = updates or {}
        try:
            parsed_order_id = UUID(order_id)
        except ValueError as exc:
            raise KeyError(order_id) from exc
        with self._session() as session:
            order = session.scalar(
                select(ExceptionItem)
                .where(ExceptionItem.team_id == local_simulation.current_team_id(), ExceptionItem.id == parsed_order_id)
                .with_for_update()
            )
            if order is None:
                raise KeyError(order_id)
            group = session.scalar(
                select(MaterialGroup).where(MaterialGroup.id == order.group_id).with_for_update()
            )
            if group is None:
                raise KeyError(str(order.group_id or ""))
            task = session.scalar(select(Task).where(Task.id == group.task_id).with_for_update())
            if task is None or task.construction_claimed_by != actor:
                raise ValueError("Construction task must be assigned to the current constructor")

            meter_no = str(updates.get("meter_no") or updates.get("barcode") or "").strip()
            collector = str(updates.get("collector") or "").strip()
            module_asset_no = str(updates.get("module_asset_no") or updates.get("asset_no") or "").strip()
            raw = dict(group.raw_data or {})
            if meter_no:
                group.display_meter_no = meter_no
                raw["meter_no"] = meter_no
            if collector:
                raw["construction_collector"] = collector
            if module_asset_no:
                raw["construction_module_asset_no"] = module_asset_no
            active_photos = session.scalars(
                select(Photo).where(Photo.team_id == group.team_id, Photo.group_id == group.id, Photo.is_active.is_(True))
            ).all()
            for photo in active_photos:
                if collector:
                    photo.collector = collector
                if module_asset_no:
                    photo.asset_no = module_asset_no
            now = datetime.now(UTC)
            group.status = GroupStatus.UNREVIEWED
            group.reviewer = None
            group.review_note = ""
            group.exception_note = note.strip()
            group.has_archive_blocker = False
            group.reviewed_at = None
            raw["status"] = "pending"
            raw["exception_submit_note"] = note.strip()
            group.raw_data = raw
            order.status = ExceptionStatus.RESOLVED
            order.resolved_at = now
            session.commit()
            session.refresh(order)
            session.refresh(group)
            return {"order": self._exception_order_payload(session, order, group), "group": _group_payload(session, group)}

    def assign_construction_exception_order(
        self,
        order_id: str,
        *,
        actor: str,
        constructor: str,
        note: str = "",
        due_date: str = "",
    ) -> dict[str, Any]:
        constructor = constructor.strip()
        if not constructor:
            raise ValueError("Constructor is required")
        try:
            parsed_order_id = UUID(str(order_id))
        except ValueError as exc:
            raise KeyError(order_id) from exc
        with self._session() as session:
            order = session.scalar(
                select(ExceptionItem)
                .where(ExceptionItem.team_id == local_simulation.current_team_id(), ExceptionItem.id == parsed_order_id)
                .with_for_update()
            )
            if order is None:
                raise KeyError(order_id)
            group = session.scalar(select(MaterialGroup).where(MaterialGroup.id == order.group_id).with_for_update())
            if group is None:
                raise KeyError(str(order.group_id))
            if group.legacy_task_id is not None:
                task = self._task_by_legacy_id(session, int(group.legacy_task_id), lock=True)
                self._ensure_construction_assignment_capacity(
                    session,
                    team_id=group.team_id,
                    constructor=constructor,
                    excluding_task_id=task.id,
                )
                now = datetime.now(UTC)
                task_raw = dict(task.raw_data or {})
                task_raw["construction_assignment_note"] = note.strip()
                task_raw["construction_due_date"] = due_date.strip()
                task.raw_data = task_raw
                task.construction_enabled = True
                task.construction_claimed_by = constructor
                task.construction_claimed_at = now
                task.construction_released_at = None
                task.construction_opened_by = actor.strip() or "admin"
                task.construction_opened_at = task.construction_opened_at or now
            raw = dict(group.raw_data or {})
            assignments = dict(raw.get("exception_order_assignments") or {})
            assignments[str(order.id)] = {
                "assigned_to": constructor,
                "assigned_by": actor,
                "assigned_at": datetime.now(UTC).isoformat(),
                "assignment_note": note.strip(),
                "due_date": due_date.strip(),
            }
            raw["exception_order_assignments"] = assignments
            group.raw_data = raw
            session.commit()
            session.refresh(order)
            session.refresh(group)
            return {"order": self._exception_order_payload(session, order, group)}

    def unassign_construction_exception_order(self, order_id: str, *, actor: str, reason: str = "") -> dict[str, Any]:
        try:
            parsed_order_id = UUID(str(order_id))
        except ValueError as exc:
            raise KeyError(order_id) from exc
        with self._session() as session:
            order = session.scalar(
                select(ExceptionItem)
                .where(ExceptionItem.team_id == local_simulation.current_team_id(), ExceptionItem.id == parsed_order_id)
                .with_for_update()
            )
            if order is None:
                raise KeyError(order_id)
            group = session.scalar(select(MaterialGroup).where(MaterialGroup.id == order.group_id).with_for_update())
            if group is None:
                raise KeyError(str(order.group_id))
            raw = dict(group.raw_data or {})
            assignments = dict(raw.get("exception_order_assignments") or {})
            assignment = dict(assignments.get(str(order.id)) or {})
            assignment.update(
                {
                    "assigned_to": "",
                    "unassigned_by": actor,
                    "unassigned_at": datetime.now(UTC).isoformat(),
                    "unassign_reason": reason.strip(),
                }
            )
            assignments[str(order.id)] = assignment
            raw["exception_order_assignments"] = assignments
            group.raw_data = raw
            session.commit()
            session.refresh(order)
            session.refresh(group)
            return {"order": self._exception_order_payload(session, order, group)}

    def review_group(
        self,
        group_id: str,
        status: str,
        reviewer: str,
        note: str = "",
        exception_note: str = "",
    ) -> dict[str, Any]:
        status_map = {
            "pending": GroupStatus.UNREVIEWED,
            "unreviewed": GroupStatus.UNREVIEWED,
            "incomplete": GroupStatus.INCOMPLETE,
            "approved": GroupStatus.APPROVED,
            "exception": GroupStatus.REJECTED,
            "rejected": GroupStatus.REJECTED,
        }
        mapped_status = status_map.get(status)
        if mapped_status is None:
            raise ValueError(f"Unsupported review status: {status}")
        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id, lock=True)
            self._ensure_task_claimed_by(session, group, reviewer)
            group.status = mapped_status
            group.reviewer = reviewer
            group.review_note = note
            group.exception_note = exception_note
            group.reviewed_at = datetime.now(UTC) if status in {"approved", "exception", "rejected"} else None
            raw_data = dict(group.raw_data or {})
            raw_data.update({"status": status, "reviewer": reviewer, "review_note": note, "exception_note": exception_note})
            group.raw_data = raw_data
            session.commit()
            session.refresh(group)
            return _group_payload(session, group)

    def classify_photo(self, group_id: str, photo_id: str, category: str, reviewer: str) -> dict[str, Any]:
        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id)
            self._ensure_task_claimed_by(session, group, reviewer)
            photo = session.scalar(
                select(Photo).where(
                    Photo.team_id == local_simulation.current_team_id(),
                    Photo.group_id == group.id,
                    Photo.legacy_id == photo_id,
                    Photo.is_active.is_(True),
                )
            )
            if photo is None:
                raise KeyError(photo_id)
            category_label = local_simulation.PHOTO_CATEGORIES.get(
                category,
                local_simulation.PHOTO_CATEGORIES["unclassified"],
            )
            image_url = photo.image_url or photo.source_url or ""
            photo.category = category
            photo.classified_by = reviewer
            photo.classified_at = datetime.now(UTC)
            photo.archive_status = "archived"
            photo.archive_filename = local_simulation.build_archive_filename(category_label, image_url)
            photo.archived_at = datetime.now(UTC)
            raw_data = dict(photo.raw_data or {})
            group_context = _group_barcode_context(group)
            raw_data.update(
                {
                    "category": category,
                    "category_label": category_label,
                    "classified_by": reviewer,
                    "archive_status": "archived",
                    "archive_filename": photo.archive_filename,
                    "archived_at": photo.archived_at.isoformat() if photo.archived_at else "",
                }
            )
            raw_data.update(
                photo_barcode_check.check_photo_barcode(
                    {
                        **_photo_payload(photo),
                        "category": category,
                        "category_label": category_label,
                        "image_url": image_url,
                    },
                    group_context,
                )
            )
            photo.raw_data = raw_data
            session.commit()
            session.refresh(photo)
            return _photo_payload(photo)

    def rescan_photo_barcode(
        self,
        group_id: str,
        photo_id: str,
        reviewer: str,
        category: str = "",
    ) -> dict[str, Any]:
        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id)
            self._ensure_task_claimed_by(session, group, reviewer)
            photo = session.scalar(
                select(Photo).where(
                    Photo.team_id == local_simulation.current_team_id(),
                    Photo.group_id == group.id,
                    Photo.legacy_id == photo_id,
                    Photo.is_active.is_(True),
                )
            )
            if photo is None:
                raise KeyError(photo_id)
            next_category = str(category or photo.category or "unclassified").strip() or "unclassified"
            if next_category not in local_simulation.PHOTO_CATEGORIES:
                raise ValueError(f"Unsupported photo category: {next_category}")
            now = datetime.now(UTC)
            category_label = local_simulation.PHOTO_CATEGORIES.get(
                next_category,
                local_simulation.PHOTO_CATEGORIES["unclassified"],
            )
            if next_category != photo.category:
                photo.category = next_category
                photo.classified_by = reviewer
                photo.classified_at = now
            raw_data = dict(photo.raw_data or {})
            raw_data.update(
                {
                    "category": next_category,
                    "category_label": category_label,
                    "classified_by": photo.classified_by or reviewer,
                    "barcode_rescanned_by": reviewer,
                    "barcode_rescanned_at": now.isoformat(),
                }
            )
            image_url = photo.image_url or photo.source_url or ""
            group_context = _group_barcode_context(group)
            raw_data.update(
                photo_barcode_check.check_photo_barcode(
                    {
                        **_photo_payload(photo),
                        **raw_data,
                        "category": next_category,
                        "category_label": category_label,
                        "image_url": image_url,
                    },
                    group_context,
                    use_ocr=True,
                )
            )
            photo.raw_data = raw_data
            session.add(
                AuditLog(
                    team_id=local_simulation.current_team_id(),
                    legacy_id=f"photo_barcode_rescan-{uuid4()}",
                    actor_username=reviewer,
                    action="photo_barcode_rescan",
                    entity_type="photo",
                    entity_id=photo.id,
                    before_data={},
                    after_data={
                        key: raw_data.get(key)
                        for key in photo_barcode_check.BARCODE_CHECK_FIELDS
                        if key in raw_data
                    },
                    payload={
                        "group_id": group.legacy_id or str(group.id),
                        "photo_id": photo.legacy_id or str(photo.id),
                        "category": next_category,
                        "status": raw_data.get("barcode_check_status", ""),
                        "matched_value": raw_data.get("barcode_check_matched_value", ""),
                        "method": raw_data.get("barcode_check_method", ""),
                    },
                )
            )
            session.commit()
            session.refresh(photo)
            return _photo_payload(photo)

    def confirm_group_barcode_manually(self, group_id: str, *, actor: str) -> dict[str, Any]:
        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id, lock=True)
            self._ensure_task_claimed_by(session, group, actor)
            now = datetime.now(UTC)
            raw_data = dict(group.raw_data or {})
            before_data = {
                key: raw_data.get(key)
                for key in (
                    "group_barcode_manual_confirmed",
                    "group_barcode_manual_confirmed_fields",
                    "group_barcode_manual_confirmed_by",
                    "group_barcode_manual_confirmed_at",
                )
            }
            raw_data.update(
                {
                    "group_barcode_manual_confirmed": True,
                    "group_barcode_manual_confirmed_fields": list(photo_barcode_check.GROUP_BARCODE_TYPES),
                    "group_barcode_manual_confirmed_by": actor,
                    "group_barcode_manual_confirmed_at": now.isoformat(),
                }
            )
            group.raw_data = raw_data
            session.add(
                AuditLog(
                    team_id=local_simulation.current_team_id(),
                    legacy_id=f"group_barcode_manual_confirmed-{uuid4()}",
                    actor_username=actor,
                    action="group_barcode_manual_confirmed",
                    entity_type="material_group",
                    entity_id=group.id,
                    before_data=before_data,
                    after_data={
                        key: raw_data.get(key)
                        for key in (
                            "group_barcode_manual_confirmed",
                            "group_barcode_manual_confirmed_fields",
                            "group_barcode_manual_confirmed_by",
                            "group_barcode_manual_confirmed_at",
                        )
                    },
                    payload={
                        "group_id": group.legacy_id or str(group.id),
                        "fields": raw_data["group_barcode_manual_confirmed_fields"],
                        "confirmed_at": raw_data["group_barcode_manual_confirmed_at"],
                    },
                )
            )
            session.commit()
            session.refresh(group)
            return {"group": _group_target_summary(_group_payload(session, group, include_photos=True), include_photos=True)}

    def delete_photo(self, group_id: str, photo_id: str, reviewer: str) -> dict[str, Any]:
        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id, lock=True)
            self._ensure_task_claimed_by(session, group, reviewer)
            photo = session.scalar(
                select(Photo).where(
                    Photo.team_id == local_simulation.current_team_id(),
                    Photo.group_id == group.id,
                    Photo.legacy_id == photo_id,
                    Photo.is_active.is_(True),
                )
            )
            if photo is None:
                raise KeyError(photo_id)
            deleted_payload = _photo_payload(photo)
            photo.is_active = False
            photo.deleted_at = datetime.now(UTC)
            photo.deleted_by = reviewer
            photo.delete_reason = "manual_delete"
            active_count = session.scalar(
                select(func.count(Photo.id)).where(
                    Photo.group_id == group.id,
                    Photo.team_id == group.team_id,
                    Photo.is_active.is_(True),
                    Photo.id != photo.id,
                )
            )
            group.photo_count = int(active_count or 0)
            group.status = GroupStatus.INCOMPLETE if group.photo_count < 4 else GroupStatus.UNREVIEWED
            group.reviewer = None
            group.review_note = ""
            group.exception_note = ""
            group.reviewed_at = None
            raw_data = dict(group.raw_data or {})
            raw_data.update({"status": "incomplete" if group.photo_count < 4 else "pending"})
            group.raw_data = raw_data
            _apply_photo_quality_exception_status(session, group, exclude_photo_id=photo.id)
            session.commit()
            session.refresh(group)
            return {"group": _group_payload(session, group), "deleted_photo": deleted_payload}

    def _project_id_for_team(self, session: Session, team_id: str):
        project_id = session.scalar(
            select(Project.id).where(Project.team_id == team_id).order_by(Project.created_at, Project.id).limit(1)
        )
        if project_id is None:
            raise StateBackendNotReady(f"No project exists for team {team_id}")
        return project_id

    def _ensure_task_for_terminal(self, session: Session, team_id: str, terminal: str) -> Task:
        task = session.scalar(select(Task).where(Task.team_id == team_id, Task.terminal == terminal).limit(1))
        if task is not None:
            return task
        project_id = self._project_id_for_team(session, team_id)
        max_legacy_id = session.scalar(select(func.max(Task.legacy_id)).where(Task.team_id == team_id)) or 0
        task = Task(
            team_id=team_id,
            project_id=project_id,
            legacy_id=int(max_legacy_id) + 1,
            terminal=terminal,
            title=f"终端 {terminal}",
            status=TaskStatus.PUBLISHED,
            raw_data={"manual_created": True},
        )
        session.add(task)
        session.flush()
        return task

    def delete_unmatched_record(self, unmatched_id: str, *, actor: str, reason: str = "") -> dict[str, Any]:
        with self._session() as session:
            record = session.scalar(
                select(UnmatchedRecord).where(
                    UnmatchedRecord.team_id == local_simulation.current_team_id(),
                    UnmatchedRecord.legacy_id == unmatched_id,
                    UnmatchedRecord.status == "open",
                )
            )
            if record is None:
                raise KeyError(unmatched_id)
            payload = _unmatched_payload(record)
            raw = dict(record.payload or {})
            raw["deleted_by"] = actor
            raw["delete_reason"] = reason
            raw["deleted_at"] = datetime.now(UTC).isoformat()
            record.payload = raw
            record.status = "deleted"
            session.commit()
            return payload

    def _unmatched_photo_urls(self, payload: dict[str, Any]) -> list[str]:
        values = payload.get("photo_urls") or payload.get("image_urls") or []
        if isinstance(values, str):
            return [item.strip() for item in re.split(r"[\r\n,]+", values) if item.strip()]
        if isinstance(values, list):
            return [str(item).strip() for item in values if str(item).strip()]
        return []

    def associate_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        target_group_id: str = "",
        target_meter_no: str = "",
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._session() as session:
            record = session.scalar(
                select(UnmatchedRecord)
                .where(
                    UnmatchedRecord.team_id == local_simulation.current_team_id(),
                    UnmatchedRecord.legacy_id == unmatched_id,
                    UnmatchedRecord.status == "open",
                )
                .with_for_update()
            )
            if record is None:
                raise KeyError(unmatched_id)
            group_statement = select(MaterialGroup).where(MaterialGroup.team_id == record.team_id)
            if target_group_id:
                group_statement = group_statement.where(MaterialGroup.legacy_id == target_group_id)
            elif target_meter_no:
                group_statement = group_statement.where(MaterialGroup.display_meter_no == target_meter_no)
            else:
                raise ValueError("Target data group was not found")
            group = session.scalar(group_statement.with_for_update())
            if group is None:
                raise ValueError("Target data group was not found")
            payload = {**_unmatched_payload(record), **(updates or {})}
            raw = dict(group.raw_data or {})
            replacement_old_meter_no = str(payload.get("replacement_old_meter_no") or "").strip()
            if replacement_old_meter_no:
                raw["replacement_old_meter_no"] = replacement_old_meter_no
                raw["replacement_new_meter_no"] = str(payload.get("replacement_new_meter_no") or payload.get("barcode") or "").strip()
                raw["replacement_by"] = actor
                raw["replacement_at"] = datetime.now(UTC).isoformat()
            meter_no = str(payload.get("meter_no") or payload.get("barcode") or "").strip()
            collector = str(payload.get("collector") or "").strip()
            module_asset_no = str(payload.get("module_asset_no") or payload.get("asset_no") or "").strip()
            if meter_no:
                group.display_meter_no = meter_no
                raw["meter_no"] = meter_no
            if collector:
                raw["construction_collector"] = collector
            if module_asset_no:
                raw["construction_module_asset_no"] = module_asset_no
            group.raw_data = raw
            photo_urls = self._unmatched_photo_urls(payload)
            photo_items = [{"url": url} for url in photo_urls]
            add_result = self._add_photo_records_to_group(
                session,
                group,
                actor=actor,
                photos=photo_items,
                collector=collector,
                module_asset_no=module_asset_no,
                creator=str(payload.get("creator") or actor),
                source="unmatched-associate",
            )
            record.status = "associated"
            record.payload = {**(record.payload or {}), "associated_by": actor, "associated_group_id": group.legacy_id}
            session.commit()
            session.refresh(group)
            return {
                "group": _group_payload(session, group),
                "import_result": {
                    "applied_records": 1,
                    "photos_new": add_result["added"],
                    "photos_duplicate": add_result["skipped_duplicates"],
                },
            }

    def create_group_from_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        terminal: str = "",
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._session() as session:
            record = session.scalar(
                select(UnmatchedRecord).where(
                    UnmatchedRecord.team_id == local_simulation.current_team_id(),
                    UnmatchedRecord.legacy_id == unmatched_id,
                    UnmatchedRecord.status == "open",
                )
            )
            if record is None:
                raise KeyError(unmatched_id)
            payload = {**_unmatched_payload(record), **(updates or {})}
        created = self.create_empty_group_for_terminal(
            terminal=terminal or str(payload.get("terminal") or ""),
            actor=actor,
            meter_no=str(payload.get("meter_no") or payload.get("barcode") or ""),
            address=str(payload.get("address") or ""),
            meter_match_key=str(payload.get("meter_match_key") or ""),
        )
        associated = self.associate_unmatched_record(
            unmatched_id,
            actor=actor,
            target_group_id=str(created.get("group", {}).get("id") or ""),
            updates=updates,
        )
        return {
            "group": associated.get("group"),
            "task": created.get("task"),
            "attached": False,
            "added_photos": associated.get("import_result", {}).get("photos_new", 0),
        }

    def create_empty_group_for_terminal(
        self,
        *,
        terminal: str,
        actor: str,
        meter_no: str = "",
        address: str = "",
        meter_match_key: str = "",
    ) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        terminal_value = terminal.strip()
        task_terminal = terminal_value or "未关联终端"
        with self._session() as session:
            project_id = self._project_id_for_team(session, team_id)
            task = self._ensure_task_for_terminal(session, team_id, task_terminal)
            created_at = datetime.now(UTC)
            meter_no_value = meter_no.strip() or f"manual-{created_at.strftime('%Y%m%d%H%M%S%f')}"
            meter_key_value = meter_match_key.strip() or meter_no_value
            group = MaterialGroup(
                team_id=team_id,
                project_id=project_id,
                legacy_id=f"manual-{created_at.strftime('%Y%m%d%H%M%S%f')}",
                legacy_task_id=task.legacy_id,
                task_id=task.id,
                terminal=terminal_value,
                meter_match_key=meter_key_value,
                display_meter_no=meter_no_value,
                installation_address=address.strip(),
                status=GroupStatus.INCOMPLETE,
                photo_count=0,
                raw_data={
                    "manual_created": True,
                    "created_by": actor,
                    "status": "incomplete",
                    "stage_terminal": terminal_value,
                },
            )
            session.add(group)
            session.commit()
            session.refresh(group)
            session.refresh(task)
            return {"group": _group_payload(session, group), "task": _construction_task_payload(task, self._task_stats(session, task))}

    def update_group_terminal(self, group_id: str, *, terminal: str, actor: str) -> dict[str, Any]:
        terminal_value = terminal.strip()
        if not terminal_value:
            raise ValueError("Target terminal is required")
        team_id = local_simulation.current_team_id()
        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id, lock=True)
            task = self._ensure_task_for_terminal(session, team_id, terminal_value)
            raw = dict(group.raw_data or {})
            raw["previous_terminal"] = group.terminal or ""
            raw["stage_terminal"] = terminal_value
            raw["terminal_updated_by"] = actor
            group.raw_data = raw
            group.terminal = terminal_value
            group.legacy_task_id = task.legacy_id
            group.task_id = task.id
            session.commit()
            session.refresh(group)
            session.refresh(task)
            return {"group": _group_payload(session, group), "task": _construction_task_payload(task, self._task_stats(session, task))}

    def save_exception_note(self, group_id: str, *, reviewer: str, note: str) -> dict[str, Any]:
        return self.review_group(group_id, status="exception", reviewer=reviewer, exception_note=note)

    def _add_photo_records_to_group(
        self,
        session: Session,
        group: MaterialGroup,
        *,
        actor: str,
        photos: list[dict[str, Any]],
        collector: str = "",
        module_asset_no: str = "",
        creator: str = "",
        source: str = "manual-photo-import",
        client_batch_id: str = "",
    ) -> dict[str, Any]:
        if source == "construction":
            _validate_construction_upload_required_slots(session, group, photos)
        existing_keys: set[tuple[str, str]] = set()
        existing_sha: set[str] = set()
        existing_storage: set[tuple[str, str]] = set()
        for photo in session.scalars(select(Photo).where(Photo.team_id == group.team_id, Photo.group_id == group.id)).all():
            if photo.source_fingerprint:
                existing_keys.add(("fingerprint", photo.source_fingerprint))
            if photo.sha256:
                existing_sha.add(photo.sha256)
            if photo.storage_type and photo.storage_key:
                existing_storage.add((photo.storage_type, photo.storage_key))
        added = 0
        skipped_duplicates = 0
        active_count = session.scalar(
            select(func.count(Photo.id)).where(
                Photo.team_id == group.team_id,
                Photo.group_id == group.id,
                Photo.is_active.is_(True),
            )
        ) or 0
        for index, item in enumerate(photos, start=1):
            image_url = str(item.get("url") or item.get("image_url") or "").strip()
            if not image_url:
                continue
            storage_type = str(item.get("storage_type") or "").strip()
            storage_key = str(item.get("storage_key") or "").strip()
            sha256 = str(item.get("sha256") or "").strip() or hashlib.sha256(image_url.encode("utf-8")).hexdigest()
            source_url = str(item.get("source_url") or image_url)
            fingerprint_seed = "|".join(
                [
                    str(group.legacy_id or group.id),
                    str(item.get("client_photo_id") or ""),
                    str(item.get("source_fingerprint") or ""),
                    source_url.split("?", 1)[0],
                ]
            )
            source_fingerprint = str(item.get("source_fingerprint") or hashlib.sha256(fingerprint_seed.encode("utf-8")).hexdigest()[:32])
            if (
                ("fingerprint", source_fingerprint) in existing_keys
                or sha256 in existing_sha
                or (storage_type and storage_key and (storage_type, storage_key) in existing_storage)
            ):
                skipped_duplicates += 1
                continue
            active_count += 1
            legacy_id = str(item.get("id") or f"p-{group.legacy_id or group.id}-{uuid4().hex[:12]}")
            category = str(item.get("slot") or item.get("category") or "unclassified")
            raw_payload = dict(item)
            if source == "construction":
                raw_payload.setdefault("upload_source", "construction-mobile")
                slot = local_simulation.normalize_construction_slot(item.get("slot") or item.get("category"))
                if slot:
                    raw_payload.setdefault("construction_slot", slot)
                    raw_payload.setdefault(
                        "construction_slot_label",
                        local_simulation.PHOTO_CATEGORIES.get(slot, local_simulation.PHOTO_CATEGORIES["other"]),
                    )
            photo = Photo(
                team_id=group.team_id,
                group_id=group.id,
                legacy_id=legacy_id,
                source=source,
                barcode=group.display_meter_no,
                collector=collector or str(item.get("collector") or ""),
                asset_no=module_asset_no or str(item.get("module_asset_no") or item.get("asset_no") or ""),
                creator=creator or actor,
                image_url=image_url,
                source_url=source_url,
                source_url_hash=hashlib.sha256(source_url.split("?", 1)[0].encode("utf-8")).hexdigest(),
                source_file_id=str(item.get("source_file_id") or ""),
                source_fingerprint=source_fingerprint,
                storage_type=storage_type,
                storage_bucket=str(item.get("storage_bucket") or ""),
                storage_key=storage_key,
                sha256=sha256,
                original_filename=str(item.get("filename") or ""),
                object_key=storage_key or image_url or legacy_id,
                content_type=str(item.get("content_type") or ""),
                category=category if category else "unclassified",
                archive_status="",
                archive_filename="",
                sort_order=active_count,
                client_batch_id=client_batch_id or str(item.get("client_batch_id") or ""),
                client_photo_id=str(item.get("client_photo_id") or ""),
                metadata_json={},
                raw_data=raw_payload,
            )
            session.add(photo)
            existing_keys.add(("fingerprint", source_fingerprint))
            existing_sha.add(sha256)
            if storage_type and storage_key:
                existing_storage.add((storage_type, storage_key))
            added += 1
        if added:
            group.photo_count = int(active_count)
            group.status = GroupStatus.INCOMPLETE if group.photo_count < 4 else GroupStatus.UNREVIEWED
            group.reviewer = None
            group.review_note = ""
            group.exception_note = ""
            group.reviewed_at = None
            raw = dict(group.raw_data or {})
            raw.update({"status": "incomplete" if group.photo_count < 4 else "pending", "photo_count": group.photo_count})
            group.raw_data = raw
            session.flush()
            _apply_photo_quality_exception_status(session, group)
        return {"added": added, "skipped_duplicates": skipped_duplicates}

    def add_photo_urls_to_group(
        self,
        group_id: str,
        *,
        actor: str,
        photo_urls: list[str],
        collector: str = "",
        module_asset_no: str = "",
        creator: str = "",
        photo_metadata: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id, lock=True)
            photo_items = []
            for url in photo_urls:
                metadata = (photo_metadata or {}).get(url, {})
                photo_items.append({"url": url, **metadata})
            result = self._add_photo_records_to_group(
                session,
                group,
                actor=actor,
                photos=photo_items,
                collector=collector,
                module_asset_no=module_asset_no,
                creator=creator,
                source="manual-photo-import",
            )
            session.commit()
            session.refresh(group)
            return {"group": _group_payload(session, group), **result}

    def upload_construction_group_batch(
        self,
        group_id: str,
        *,
        actor: str,
        client_batch_id: str,
        collector: str,
        module_asset_no: str,
        photos: list[dict[str, Any]],
        creator: str = "",
        client_completed_at: str = "",
    ) -> dict[str, Any]:
        actor = actor.strip() or "constructor"
        creator = creator.strip() or actor
        if not client_batch_id.strip():
            raise ValueError("Client batch id is required")
        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id, lock=True)
            local_simulation.assert_not_placeholder_construction_group(
                group_id=group.legacy_id or str(group.id),
                meter_no=group.display_meter_no,
                meter_match_key=group.meter_match_key or "",
                address=group.installation_address,
            )
            task = session.scalar(select(Task).where(Task.id == group.task_id).with_for_update())
            if task is None or task.construction_claimed_by != actor:
                raise ValueError("Construction task must be claimed by the current constructor before upload")
            if client_completed_at:
                for photo in photos:
                    photo.setdefault("client_completed_at", client_completed_at)
            result = self._add_photo_records_to_group(
                session,
                group,
                actor=actor,
                photos=photos,
                collector=collector,
                module_asset_no=module_asset_no,
                creator=creator,
                source="construction",
                client_batch_id=client_batch_id,
            )
            raw = dict(group.raw_data or {})
            raw["construction_collector"] = collector
            raw["construction_module_asset_no"] = module_asset_no
            group.raw_data = raw
            self._add_construction_activity_audit(
                session,
                "group_uploaded",
                actor,
                {
                    "task_id": group.legacy_task_id,
                    "group_id": group.legacy_id or str(group.id),
                    "client_batch_id": client_batch_id,
                    "occurred_at": client_completed_at or datetime.now(UTC).isoformat(),
                    "added": result.get("added", 0),
                    "confirmed_non_idle": bool(_datetime_from_value(client_completed_at) and result.get("added", 0) > 0),
                },
            )
            session.commit()
            session.refresh(group)
            return {"group": _group_payload(session, group), **result}

    def build_task_detail_export(self, task_id: int) -> bytes:
        with self._session() as session:
            self._task_by_legacy_id(session, task_id)
            groups = [
                _group_payload(session, group, include_photos=True)
                for group in session.scalars(
                    select(MaterialGroup)
                    .where(
                        MaterialGroup.team_id == local_simulation.current_team_id(),
                        MaterialGroup.legacy_task_id == task_id,
                    )
                    .order_by(MaterialGroup.display_meter_no, MaterialGroup.legacy_id)
                ).all()
            ]
        return local_simulation.build_groups_export_workbook(groups, f"task-{task_id}")

    def build_final_delivery_export(
        self,
        *,
        task_id: int | None = None,
        terminal: str = "",
        review_scope: str = "reviewed",
    ) -> bytes:
        terminal = terminal.strip()
        if task_id is None and not terminal:
            raise ValueError("Final delivery export must be scoped to one terminal")
        if review_scope not in {"reviewed", "all"}:
            raise ValueError("Unsupported delivery export scope")
        team_id = local_simulation.current_team_id()
        with self._session() as session:
            statement = select(MaterialGroup).where(MaterialGroup.team_id == team_id)
            if task_id is not None:
                self._task_by_legacy_id(session, task_id)
                statement = statement.where(MaterialGroup.legacy_task_id == task_id)
            if terminal:
                statement = statement.where(MaterialGroup.terminal == terminal)
            groups = [
                _group_payload(session, group, include_photos=True)
                for group in session.scalars(
                    statement.order_by(MaterialGroup.terminal, MaterialGroup.display_meter_no, MaterialGroup.legacy_id)
                ).all()
            ]
        if review_scope == "reviewed":
            groups = [group for group in groups if _is_reviewed_group(group)]
        return local_simulation.build_groups_export_workbook(groups, "final-delivery")

    def build_final_delivery_manifest(
        self,
        *,
        task_id: int | None = None,
        terminal: str = "",
        review_scope: str = "reviewed",
    ) -> dict[str, Any]:
        terminal = terminal.strip()
        if task_id is None and not terminal:
            raise ValueError("Final delivery export must be scoped to one terminal")
        if review_scope not in {"reviewed", "all"}:
            raise ValueError("Unsupported delivery export scope")
        team_id = local_simulation.current_team_id()
        with self._session() as session:
            statement = select(MaterialGroup).where(MaterialGroup.team_id == team_id)
            if task_id is not None:
                self._task_by_legacy_id(session, task_id)
                statement = statement.where(MaterialGroup.legacy_task_id == task_id)
            if terminal:
                statement = statement.where(MaterialGroup.terminal == terminal)
            groups = [
                _group_payload(session, group, include_photos=True)
                for group in session.scalars(
                    statement.order_by(MaterialGroup.terminal, MaterialGroup.display_meter_no, MaterialGroup.legacy_id)
                ).all()
            ]
        if review_scope == "reviewed":
            groups = [group for group in groups if _is_reviewed_group(group)]
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "photo_limit_per_group": 4,
            "scope": {"task_id": task_id, "terminal": terminal, "review_scope": review_scope},
            "groups": [_delivery_group_manifest(group) for group in groups],
        }

    def build_exception_meter_export(self, *, reviewer: str = "") -> bytes:
        result = self.list_exception_groups(reviewer=reviewer, limit=100_000, offset=0)
        return local_simulation.build_exception_meter_workbook(result.get("items", []))

    def build_project_outside_export(self) -> bytes:
        team_id = local_simulation.current_team_id()
        with self._session() as session:
            records = session.scalars(
                select(UnmatchedRecord)
                .where(UnmatchedRecord.team_id == team_id, UnmatchedRecord.status == "open")
                .order_by(UnmatchedRecord.terminal, UnmatchedRecord.barcode, UnmatchedRecord.legacy_id)
            ).all()
            payloads = [
                _unmatched_payload(record)
                for record in records
                if bool((record.payload or {}).get("project_outside"))
            ]
        return local_simulation.build_project_outside_workbook(payloads)

    def get_delivery_cached_photo_path(self, group_id: str, photo_id: str) -> Path:
        raise FileNotFoundError(photo_id)

    def reset_group_to_unconstructed(
        self,
        group_id: str,
        *,
        actor: str,
        reason: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id, lock=True)
            self._ensure_task_claimed_by(session, group, actor, force=force)
            before = _group_payload(session, group, include_photos=False)
            photos = session.scalars(
                select(Photo).where(
                    Photo.group_id == group.id,
                    Photo.team_id == group.team_id,
                    Photo.is_active.is_(True),
                )
            ).all()
            now = datetime.now(UTC)
            for photo in photos:
                photo.is_active = False
                photo.deleted_at = now
                photo.deleted_by = actor
                photo.delete_reason = reason or "reset_to_unconstructed"
            raw_data = dict(group.raw_data or {})
            for key in ("construction_collector", "construction_module_asset_no", "constructor", "collector", "module_asset_no"):
                raw_data.pop(key, None)
            raw_data.update({"status": "pending", "reset_to_unconstructed_reason": reason})
            group.raw_data = raw_data
            group.photo_count = 0
            group.status = GroupStatus.UNREVIEWED
            group.reviewer = None
            group.review_note = ""
            group.exception_status = None
            group.exception_note = ""
            group.exception_reasons = []
            group.has_archive_blocker = False
            group.reviewed_at = None
            session.add(
                AuditLog(
                    team_id=local_simulation.current_team_id(),
                    legacy_id=f"group-reset-to-unconstructed-{uuid4()}",
                    actor_username=actor,
                    action="group_reset_to_unconstructed",
                    entity_type="material_group",
                    entity_id=group.id,
                    before_data=before,
                    after_data={
                        "status": "pending",
                        "photo_count": 0,
                        "reviewer": "",
                        "review_note": "",
                        "exception_note": "",
                    },
                    payload={
                        "group_id": group.legacy_id or str(group.id),
                        "soft_deleted_photos": len(photos),
                        "reason": reason,
                    },
                )
            )
            session.commit()
            session.refresh(group)
            return {"group": _group_payload(session, group), "soft_deleted_photos": len(photos)}

    def reset_group_to_unreviewed(
        self,
        group_id: str,
        *,
        actor: str,
        reason: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id, lock=True)
            self._ensure_task_claimed_by(session, group, actor, force=force)
            before = _group_payload(session, group, include_photos=False)
            raw_data = dict(group.raw_data or {})
            raw_data.update(
                {
                    "status": "pending",
                    "reviewer": "",
                    "review_note": "",
                    "exception_note": "",
                    "exception_reasons": [],
                    "reset_to_unreviewed_reason": reason,
                }
            )
            group.raw_data = raw_data
            group.status = GroupStatus.UNREVIEWED
            group.reviewer = None
            group.review_note = ""
            group.exception_status = None
            group.exception_note = ""
            group.exception_reasons = []
            group.has_archive_blocker = False
            group.reviewed_at = None
            session.add(
                AuditLog(
                    team_id=local_simulation.current_team_id(),
                    legacy_id=f"admin-group-reset-unreviewed-{uuid4()}",
                    actor_username=actor,
                    action="admin_group_reset_unreviewed",
                    entity_type="material_group",
                    entity_id=group.id,
                    before_data=before,
                    after_data={
                        "status": "pending",
                        "reviewer": "",
                        "review_note": "",
                        "exception_note": "",
                    },
                    payload={"group_id": group.legacy_id or str(group.id), "reason": reason},
                )
            )
            session.commit()
            session.refresh(group)
            return {"group": _group_payload(session, group)}

    def bulk_archive_groups(self, group_ids: list[str], *, actor: str, reason: str = "") -> dict[str, Any]:
        unique_ids = list(dict.fromkeys(str(item).strip() for item in group_ids if str(item).strip()))
        if not unique_ids:
            raise ValueError("At least one group is required")
        archived_groups: list[MaterialGroup] = []
        skipped: list[dict[str, str]] = []
        now = datetime.now(UTC)
        with self._session() as session:
            for group_id in unique_ids:
                try:
                    group = self._group_by_legacy_id(session, group_id, lock=True)
                except KeyError:
                    skipped.append({"group_id": group_id, "reason": "not_found"})
                    continue
                photos = session.scalars(
                    select(Photo)
                    .where(
                        Photo.team_id == group.team_id,
                        Photo.group_id == group.id,
                        Photo.is_active.is_(True),
                    )
                    .order_by(Photo.sort_order, Photo.created_at, Photo.legacy_id)
                ).all()
                if not photos:
                    skipped.append({"group_id": group_id, "reason": "no_active_photos"})
                    continue
                before = _group_payload(session, group, include_photos=True)
                group_context = _group_barcode_context(group)
                for photo in photos:
                    raw = dict(photo.raw_data or {})
                    category = photo.category or raw.get("category") or "unclassified"
                    label = raw.get("category_label") or local_simulation.PHOTO_CATEGORIES.get(
                        category,
                        local_simulation.PHOTO_CATEGORIES["unclassified"],
                    )
                    image_url = photo.image_url or photo.source_url or ""
                    photo.category = category
                    photo.archive_status = "archived"
                    photo.archive_filename = photo.archive_filename or local_simulation.build_archive_filename(label, image_url)
                    photo.archived_at = now
                    photo.classified_by = photo.classified_by or actor
                    raw.update(
                        {
                            "category": category,
                            "category_label": label,
                            "archive_status": "archived",
                            "archive_filename": photo.archive_filename,
                            "archived_at": now.isoformat(),
                            "bulk_archived_by": actor,
                        }
                    )
                    raw.update(
                        photo_barcode_check.ensure_photo_barcode_check(
                            {
                                **_photo_payload(photo),
                                "category": category,
                                "category_label": label,
                                "image_url": image_url,
                                **raw,
                            },
                            group_context,
                        )
                    )
                    photo.raw_data = raw

                validation_group = _group_payload(session, group, include_photos=True)
                reasons = local_simulation.validate_group_archive(validation_group)
                raw_data = dict(group.raw_data or {})
                group.exception_reasons = reasons
                group.has_archive_blocker = bool(reasons)
                group.exception_status = "open" if reasons else None
                raw_data["exception_reasons"] = reasons
                raw_data["bulk_archive_reason"] = reason.strip()
                if reasons:
                    group.status = GroupStatus.REJECTED
                    group.exception_note = "; ".join(local_simulation.display_exception_reasons(reasons))
                    raw_data["status"] = "exception"
                    raw_data["exception_note"] = group.exception_note
                else:
                    group.status = GroupStatus.APPROVED
                    group.reviewer = actor
                    group.review_note = "批量归档"
                    group.exception_note = ""
                    group.reviewed_at = now
                    raw_data["status"] = "approved"
                    raw_data["reviewer"] = actor
                    raw_data["review_note"] = group.review_note
                    raw_data["exception_note"] = ""
                group.raw_data = raw_data
                archived_groups.append(group)
                session.add(
                    AuditLog(
                        team_id=local_simulation.current_team_id(),
                        legacy_id=f"admin-groups-bulk-archive-{uuid4()}",
                        actor_username=actor,
                        action="admin_groups_bulk_archive",
                        entity_type="material_group",
                        entity_id=group.id,
                        before_data=before,
                        after_data=_group_payload(session, group, include_photos=True),
                        payload={"group_id": group.legacy_id or str(group.id), "reason": reason.strip()},
                    )
                )
            session.add(
                AuditLog(
                    team_id=local_simulation.current_team_id(),
                    legacy_id=f"admin-groups-bulk-archive-summary-{uuid4()}",
                    actor_username=actor,
                    action="admin_groups_bulk_archive",
                    entity_type="material_group",
                    entity_id=None,
                    before_data={},
                    after_data={},
                    payload={
                        "group_ids": unique_ids,
                        "archived_count": len(archived_groups),
                        "skipped": skipped,
                        "reason": reason.strip(),
                    },
                )
            )
            session.commit()
            for group in archived_groups:
                session.refresh(group)
            return {
                "archived_count": len(archived_groups),
                "skipped": skipped,
                "groups": [_group_target_summary(_group_payload(session, group, include_photos=True), include_photos=True) for group in archived_groups],
            }

    def return_group_to_exception_order(
        self,
        group_id: str,
        *,
        actor: str,
        category: str,
        note: str,
        force: bool = False,
    ) -> dict[str, Any]:
        note = note.strip()
        if not note:
            raise ValueError("Exception reason is required")
        category = category.strip() or "other"
        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id, lock=True)
            self._ensure_task_claimed_by(session, group, actor, force=force)
            group.status = GroupStatus.REJECTED
            group.reviewer = actor
            group.review_note = ""
            group.exception_note = note
            group.exception_reasons = [category, note] if category != note else [category]
            group.has_archive_blocker = True
            group.reviewed_at = None
            raw_data = dict(group.raw_data or {})
            raw_data.update({"status": "exception", "exception_note": note, "exception_category": category})
            group.raw_data = raw_data
            order = ExceptionItem(
                team_id=group.team_id,
                project_id=group.project_id,
                group_id=group.id,
                task_id=group.task_id,
                category=category,
                description=note,
                status=ExceptionStatus.OPEN,
            )
            session.add(order)
            session.commit()
            session.refresh(group)
            session.refresh(order)
            return {
                "group": _group_payload(session, group),
                "order": {**self._exception_order_payload(session, order, group), "created_by": actor},
            }


class DualWriteStateRepository(JsonStateRepository):
    """Dual mode keeps JSON authoritative while mirroring core writes to PostgreSQL."""

    postgres_repository_factory = PostgresStateRepository

    def _mirror_write(self, operation: str, *args: Any, **kwargs: Any) -> None:
        try:
            mirror = self.postgres_repository_factory()
            getattr(mirror, operation)(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - production safety path
            logger.warning("Dual write mirror failed for %s: %s", operation, exc, exc_info=True)

    def claim_task(self, task_id: int, reviewer: str) -> dict[str, Any]:
        result = super().claim_task(task_id, reviewer)
        self._mirror_write("claim_task", task_id, reviewer)
        return result

    def release_task(self, task_id: int, reviewer: str, *, force: bool = False) -> dict[str, Any]:
        result = super().release_task(task_id, reviewer, force=force)
        self._mirror_write("release_task", task_id, reviewer, force=force)
        return result

    def dedupe_unmatched_records(self, *, actor: str) -> dict[str, Any]:
        result = super().dedupe_unmatched_records(actor=actor)
        self._mirror_write("dedupe_unmatched_records", actor=actor)
        return result

    def review_group(
        self,
        group_id: str,
        status: str,
        reviewer: str,
        note: str = "",
        exception_note: str = "",
    ) -> dict[str, Any]:
        result = super().review_group(group_id, status, reviewer, note, exception_note)
        self._mirror_write("review_group", group_id, status, reviewer, note, exception_note)
        return result

    def classify_photo(self, group_id: str, photo_id: str, category: str, reviewer: str) -> dict[str, Any]:
        result = super().classify_photo(group_id, photo_id, category, reviewer)
        self._mirror_write("classify_photo", group_id, photo_id, category, reviewer)
        return result

    def rescan_photo_barcode(
        self,
        group_id: str,
        photo_id: str,
        reviewer: str,
        category: str = "",
    ) -> dict[str, Any]:
        result = super().rescan_photo_barcode(group_id, photo_id, reviewer, category)
        self._mirror_write("rescan_photo_barcode", group_id, photo_id, reviewer, category)
        return result

    def confirm_group_barcode_manually(self, group_id: str, *, actor: str) -> dict[str, Any]:
        result = super().confirm_group_barcode_manually(group_id, actor=actor)
        self._mirror_write("confirm_group_barcode_manually", group_id, actor=actor)
        return result

    def delete_photo(self, group_id: str, photo_id: str, reviewer: str) -> dict[str, Any]:
        result = super().delete_photo(group_id, photo_id, reviewer)
        self._mirror_write("delete_photo", group_id, photo_id, reviewer)
        return result

    def update_group_metadata(
        self,
        group_id: str,
        *,
        actor: str,
        updates: dict[str, Any],
        audit_action: str = "update_group_metadata",
    ) -> dict[str, Any]:
        result = super().update_group_metadata(group_id, actor=actor, updates=updates, audit_action=audit_action)
        self._mirror_write("update_group_metadata", group_id, actor=actor, updates=updates, audit_action=audit_action)
        return result

    def reset_group_to_unconstructed(
        self,
        group_id: str,
        *,
        actor: str,
        reason: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        result = super().reset_group_to_unconstructed(group_id, actor=actor, reason=reason, force=force)
        self._mirror_write("reset_group_to_unconstructed", group_id, actor=actor, reason=reason, force=force)
        return result

    def reset_group_to_unreviewed(
        self,
        group_id: str,
        *,
        actor: str,
        reason: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        result = super().reset_group_to_unreviewed(group_id, actor=actor, reason=reason, force=force)
        self._mirror_write("reset_group_to_unreviewed", group_id, actor=actor, reason=reason, force=force)
        return result

    def bulk_archive_groups(self, group_ids: list[str], *, actor: str, reason: str = "") -> dict[str, Any]:
        result = super().bulk_archive_groups(group_ids, actor=actor, reason=reason)
        self._mirror_write("bulk_archive_groups", group_ids, actor=actor, reason=reason)
        return result

    def return_group_to_exception_order(
        self,
        group_id: str,
        *,
        actor: str,
        category: str,
        note: str,
        force: bool = False,
    ) -> dict[str, Any]:
        result = super().return_group_to_exception_order(
            group_id,
            actor=actor,
            category=category,
            note=note,
            force=force,
        )
        self._mirror_write(
            "return_group_to_exception_order",
            group_id,
            actor=actor,
            category=category,
            note=note,
            force=force,
        )
        return result

    def record_construction_activity_event(
        self,
        *,
        event_type: str,
        actor: str,
        task_id: str | int | None = None,
        group_id: str = "",
        client_batch_id: str = "",
        occurred_at: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = super().record_construction_activity_event(
            event_type=event_type,
            actor=actor,
            task_id=task_id,
            group_id=group_id,
            client_batch_id=client_batch_id,
            occurred_at=occurred_at,
            payload=payload,
        )
        self._mirror_write(
            "record_construction_activity_event",
            event_type=event_type,
            actor=actor,
            task_id=task_id,
            group_id=group_id,
            client_batch_id=client_batch_id,
            occurred_at=occurred_at,
            payload=payload,
        )
        return result

    def upload_construction_group_batch(
        self,
        group_id: str,
        *,
        actor: str,
        client_batch_id: str,
        collector: str,
        module_asset_no: str,
        photos: list[dict[str, Any]],
        creator: str = "",
        client_completed_at: str = "",
    ) -> dict[str, Any]:
        result = super().upload_construction_group_batch(
            group_id,
            actor=actor,
            client_batch_id=client_batch_id,
            collector=collector,
            module_asset_no=module_asset_no,
            photos=photos,
            creator=creator,
            client_completed_at=client_completed_at,
        )
        self._mirror_write(
            "upload_construction_group_batch",
            group_id,
            actor=actor,
            client_batch_id=client_batch_id,
            collector=collector,
            module_asset_no=module_asset_no,
            photos=photos,
            creator=creator,
            client_completed_at=client_completed_at,
        )
        return result


def get_state_repository() -> StateRepository:
    backend = settings.state_backend.lower().strip()
    if backend == "json":
        return JsonStateRepository()
    if backend == "dual":
        return DualWriteStateRepository()
    if backend == "postgres":
        return PostgresStateRepository()
    raise StateBackendNotReady(f"Unsupported STATE_BACKEND value: {settings.state_backend}")
