from __future__ import annotations

import logging
import re
import hashlib
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, case, func, or_, select
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
from app.services import local_simulation


logger = logging.getLogger(__name__)

REVIEWABLE_STATUSES = {"pending", "incomplete", "approved", "exception", "unmatched"}
OPEN_STATUSES = {"pending", "incomplete", "unmatched"}


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
        return _date_key_from_value(photo.created_at)
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
    return _date_key_from_value(photo.created_at)


def _empty_task_stats() -> dict[str, int]:
    return {
        "total_groups": 0,
        "uploaded_count": 0,
        "reviewed_count": 0,
        "unreviewed_count": 0,
    }


def _task_payload(task: Task, stats: dict[str, int] | None = None) -> dict[str, Any]:
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
    }


def _construction_task_payload(task: Task, stats: dict[str, int] | None = None) -> dict[str, Any]:
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
    return {
        "id": photo.legacy_id or str(photo.id),
        "url": image_url,
        "image_url": image_url,
        "source_url": photo.source_url or photo.image_url or "",
        "storage_type": photo.storage_type or "",
        "storage_bucket": photo.storage_bucket or "",
        "storage_key": photo.storage_key or "",
        "sha256": photo.sha256,
        "category": photo.category or "unclassified",
        "archive_filename": photo.archive_filename or "",
        "archive_status": photo.archive_status or "",
        "sort_order": photo.sort_order,
        "barcode": photo.barcode or "",
        "collector": photo.collector or "",
        "module_asset_no": photo.asset_no or "",
        "creator": photo.creator or "",
        "upload_source": raw.get("upload_source") or raw.get("storage_source") or "",
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
    raw = group.raw_data or {}
    for key in ("collector", "module_asset_no", "asset_no", "creator", "installer"):
        if key in raw and key not in payload:
            payload[key] = raw[key]
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


def _group_target_summary(group: dict[str, Any]) -> dict[str, Any]:
    photo_count = int(group.get("photo_count") or 0)
    return {
        "id": group["id"],
        "task_id": group.get("task_id"),
        "terminal": group.get("terminal", ""),
        "meter_no": group.get("meter_no", ""),
        "meter_match_key": group.get("meter_match_key", ""),
        "address": group.get("address", ""),
        "status": group.get("status", ""),
        "reviewer": group.get("reviewer", ""),
        "review_note": group.get("review_note", ""),
        "photo_count": photo_count,
        "construction_status": "unconstructed" if photo_count == 0 else "scanned",
        "has_archive_blocker": group.get("has_archive_blocker", False),
        "exception_reasons": group.get("exception_reasons", []),
    }


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
    photo_urls = payload.get("photo_urls") or payload.get("images") or []
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


class StateRepository(ABC):
    @abstractmethod
    def summary(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_tasks(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def installer_daily_workload(self, installer: str) -> dict[str, Any]:
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
    def update_group_metadata(self, group_id: str, *, actor: str, updates: dict[str, Any]) -> dict[str, Any]:
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

    def list_tasks(self) -> list[dict[str, Any]]:
        return local_simulation.list_tasks()

    def installer_daily_workload(self, installer: str) -> dict[str, Any]:
        return local_simulation.installer_daily_workload(installer)

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

    def update_group_metadata(self, group_id: str, *, actor: str, updates: dict[str, Any]) -> dict[str, Any]:
        return local_simulation.update_group_metadata(group_id, actor=actor, updates=updates)

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
    ) -> dict[str, Any]:
        return local_simulation.upload_construction_group_batch(
            group_id,
            actor=actor,
            client_batch_id=client_batch_id,
            collector=collector,
            module_asset_no=module_asset_no,
            photos=photos,
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

        groups = int(group_stats.groups or 0)
        reviewed_groups = int(group_stats.reviewed_groups or 0)
        installer_group_ids: dict[str, set[str]] = {}
        for row in installer_pairs:
            installer = str(row.creator or "").strip() or "未填写"
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

    def _task_stats_map(self, session: Session, team_id: str) -> dict[int, dict[str, int]]:
        rows = session.execute(
            select(
                MaterialGroup.legacy_task_id,
                func.count(MaterialGroup.id).label("total_groups"),
                func.coalesce(func.sum(case((MaterialGroup.photo_count > 0, 1), else_=0)), 0).label("uploaded_count"),
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
        return {
            int(row.legacy_task_id): {
                "total_groups": int(row.total_groups or 0),
                "uploaded_count": int(row.uploaded_count or 0),
                "reviewed_count": int(row.reviewed_count or 0),
                "unreviewed_count": int(row.unreviewed_count or 0),
            }
            for row in rows
            if row.legacy_task_id is not None
        }

    def _task_stats(self, session: Session, task: Task) -> dict[str, int]:
        if task.legacy_id is None:
            return _empty_task_stats()
        return self._task_stats_map(session, task.team_id or local_simulation.current_team_id()).get(
            int(task.legacy_id),
            _empty_task_stats(),
        )

    def list_tasks(self) -> list[dict[str, Any]]:
        with self._session() as session:
            team_id = local_simulation.current_team_id()
            tasks = session.scalars(
                select(Task)
                .where(Task.team_id == team_id)
                .order_by(Task.terminal, Task.legacy_id)
            ).all()
            stats_by_task = self._task_stats_map(session, team_id)
            return sorted(
                [_task_payload(task, stats_by_task.get(int(task.legacy_id or 0), _empty_task_stats())) for task in tasks],
                key=lambda item: (not item.get("can_claim", False), str(item.get("terminal", "")), item["id"]),
            )

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
                },
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
            statement = statement.where(
                or_(
                    MaterialGroup.legacy_id.ilike(pattern),
                    MaterialGroup.terminal.ilike(pattern),
                    MaterialGroup.display_meter_no.ilike(pattern),
                    MaterialGroup.meter_match_key.ilike(pattern),
                    MaterialGroup.installation_address.ilike(pattern),
                    MaterialGroup.reviewer.ilike(pattern),
                    photo_match,
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
                "items": [_group_target_summary(_group_payload(session, group, include_photos=False)) for group in groups],
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
                    existing = session.scalar(
                        select(Task)
                        .where(
                            Task.team_id == record.team_id,
                            Task.id != task.id,
                            Task.construction_enabled.is_(True),
                            Task.construction_claimed_by == constructor,
                        )
                        .with_for_update()
                    )
                    if existing is not None:
                        terminal_label = existing.terminal or existing.legacy_id or ""
                        raise ValueError(f"Current constructor already has active terminal {terminal_label}")
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

    def update_group_metadata(self, group_id: str, *, actor: str, updates: dict[str, Any]) -> dict[str, Any]:
        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id, lock=True)
            raw_data = dict(group.raw_data or {})
            if "meter_no" in updates:
                group.display_meter_no = str(updates.get("meter_no") or "").strip()
                raw_data["meter_no"] = group.display_meter_no
            if "meter_match_key" in updates:
                group.meter_match_key = str(updates.get("meter_match_key") or "").strip() or None
                raw_data["meter_match_key"] = group.meter_match_key or ""
            if "address" in updates:
                group.installation_address = str(updates.get("address") or "").strip()
                raw_data["address"] = group.installation_address
            if "exception_note" in updates:
                group.exception_note = str(updates.get("exception_note") or "").strip()
                raw_data["exception_note"] = group.exception_note

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
            group.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(group)
            return {"group": _group_payload(session, group)}

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
            existing = session.scalar(
                select(Task)
                .where(
                    Task.team_id == team_id,
                    Task.id != task.id,
                    Task.construction_enabled.is_(True),
                    Task.construction_claimed_by == constructor,
                )
                .with_for_update()
            )
            if existing is not None:
                terminal = existing.terminal or existing.legacy_id or ""
                raise ValueError(f"Current constructor already has active terminal {terminal}")
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
                existing = session.scalar(
                    select(Task)
                    .where(
                        Task.team_id == group.team_id,
                        Task.id != task.id,
                        Task.construction_enabled.is_(True),
                        Task.construction_claimed_by == constructor,
                    )
                    .with_for_update()
                )
                if existing is not None:
                    terminal = existing.terminal or existing.legacy_id or ""
                    raise ValueError(f"Current constructor already has active terminal {terminal}")
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
            photo.raw_data = raw_data
            session.commit()
            session.refresh(photo)
            return _photo_payload(photo)

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
    ) -> dict[str, Any]:
        actor = actor.strip() or "constructor"
        if not client_batch_id.strip():
            raise ValueError("Client batch id is required")
        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id, lock=True)
            task = session.scalar(select(Task).where(Task.id == group.task_id).with_for_update())
            if task is None or task.construction_claimed_by != actor:
                raise ValueError("Construction task must be claimed by the current constructor before upload")
            result = self._add_photo_records_to_group(
                session,
                group,
                actor=actor,
                photos=photos,
                collector=collector,
                module_asset_no=module_asset_no,
                creator=actor,
                source="construction",
                client_batch_id=client_batch_id,
            )
            raw = dict(group.raw_data or {})
            raw["construction_collector"] = collector
            raw["construction_module_asset_no"] = module_asset_no
            group.raw_data = raw
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
            group.exception_note = ""
            group.exception_reasons = []
            group.has_archive_blocker = False
            group.reviewed_at = None
            session.commit()
            session.refresh(group)
            return {"group": _group_payload(session, group), "soft_deleted_photos": len(photos)}

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

    def delete_photo(self, group_id: str, photo_id: str, reviewer: str) -> dict[str, Any]:
        result = super().delete_photo(group_id, photo_id, reviewer)
        self._mirror_write("delete_photo", group_id, photo_id, reviewer)
        return result

    def update_group_metadata(self, group_id: str, *, actor: str, updates: dict[str, Any]) -> dict[str, Any]:
        result = super().update_group_metadata(group_id, actor=actor, updates=updates)
        self._mirror_write("update_group_metadata", group_id, actor=actor, updates=updates)
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


def get_state_repository() -> StateRepository:
    backend = settings.state_backend.lower().strip()
    if backend == "json":
        return JsonStateRepository()
    if backend == "dual":
        return DualWriteStateRepository()
    if backend == "postgres":
        return PostgresStateRepository()
    raise StateBackendNotReady(f"Unsupported STATE_BACKEND value: {settings.state_backend}")
