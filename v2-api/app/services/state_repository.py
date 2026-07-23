from __future__ import annotations

import logging
import re
import hashlib
import json
from abc import ABC, abstractmethod
from collections import defaultdict
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, NoReturn
from uuid import UUID, uuid4

from sqlalchemy import String, Text, and_, case, cast, func, literal, or_, select, union_all
from sqlalchemy.dialects.postgresql import JSONB, array
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.core.config import settings
from app.database import SessionLocal
from app.models import (
    AuditLog,
    DeliveryCacheJob,
    ExceptionItem,
    ExceptionStatus,
    GroupBarcodeVerification,
    GroupStatus,
    MaterialGroup,
    Photo,
    PhotoUploadStatus,
    Project,
    ProjectStatus,
    StageCatalogRow,
    Task,
    TaskStatus,
    Team,
    TotalCatalogRow,
    UnmatchedRecord,
)
from app.schemas.data_center import DataCenterQuery
from app.services import data_center as data_center_service
from app.services import account_store
from app.services.barcode_verification_contract import (
    DURABLE_STATUSES,
    EXCEPTION_STATUSES,
    LEGACY_EVIDENCE_WHITESPACE,
    OCR_ONLY_METHODS,
    PASS_STATUSES,
    REQUIRED_CATEGORIES,
    TERMINAL_STATUSES,
    normalize_barcode_verification,
    resolve_persisted_barcode_verification,
    summarize_durable_accuracy,
    verification_compatibility_fields,
)
from app.services.final_delivery_export import LeasedDeliveryPackage
from app.services.matching import build_total_catalog_match_key


def construction_task_availability(stats: Mapping[str, Any]) -> tuple[bool, bool]:
    total = max(0, int(stats.get("total_groups") or 0))
    uploaded = max(0, int(stats.get("uploaded_count") or 0))
    unreviewed = max(0, int(stats.get("unreviewed_count") or 0))
    return total > 0 and uploaded < total, uploaded > 0 and unreviewed > 0


def _construction_priority_import_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    statuses = ("valid", "duplicate", "conflict", "unknown", "completed", "unchanged", "malformed")
    return {status: sum(1 for item in items if item["status"] == status) for status in statuses}


from app.services import local_simulation, photo_barcode_check, unmatched_review


logger = logging.getLogger(__name__)

REVIEWABLE_STATUSES = {"pending", "incomplete", "approved", "exception", "unmatched"}
OPEN_STATUSES = {"pending", "incomplete", "unmatched"}
MAX_ACTIVE_CONSTRUCTION_TASKS_PER_CONSTRUCTOR = 5
LOCAL_WORK_TZ = timezone(timedelta(hours=8))
MISSING_MODULE_ASSET_REASON = "\u7f3a\u5c11\u6a21\u5757\u8d44\u4ea7\u7f16\u53f7"
INSUFFICIENT_GROUP_PHOTO_REASON = "\u8d44\u6599\u7ec4\u7167\u7247\u4e0d\u8db3 4 \u5f20"
MISSING_COLLECTOR_INFO_REASON = "\u7f3a\u5c11\u91c7\u96c6\u5668\u4fe1\u606f"
MODULE_DUPLICATE_REASON_PREFIX = "\u6a21\u5757\u53f7\u91cd\u590d"
FINALIZATION_REPLAY_KEY = "finalization_replay"
DATA_CENTER_IDENTITY_FIELDS = {
    "meter_no",
    "terminal",
    "collector",
    "module_asset_no",
    "construction_collector",
    "construction_module_asset_no",
}


class StateBackendNotReady(RuntimeError):
    """Raised when the selected state backend cannot safely serve the operation."""


def _data_center_archive_status(group: Mapping[str, Any]) -> str:
    return str(data_center_service.group_row(group).get("archive_status") or "unarchived")


def _data_center_barcode_status(group: Mapping[str, Any]) -> str:
    row_status = str(data_center_service.group_row(group).get("barcode_status") or "ineligible")
    return "manual_passed" if row_status == "manual" else row_status


def _data_center_group_result(
    group: Mapping[str, Any],
    *,
    changed_fields: list[str] | None = None,
    delivery_package_job_status: str = "",
    archive_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    row = data_center_service.group_row(group)
    return {
        "group": deepcopy(dict(group)),
        "changed_fields": changed_fields or [],
        "archive_status": row.get("archive_status", "unarchived"),
        "barcode_status": _data_center_barcode_status(group),
        "construction_status": row.get("construction_status", "unconstructed"),
        "classification_status": row.get("classification_status", "incomplete"),
        "delivery_package_job_status": delivery_package_job_status,
        "archive_result": dict(archive_result or {}),
    }


def _reject_placeholder_or_ambiguous_data_center_target(*, terminal: str, meter_no: str, candidate_key: str) -> None:
    values = [terminal, meter_no, candidate_key]
    if any(str(value or "").strip() == "00000000" for value in values):
        raise ValueError("数据中台未匹配归并必须选择唯一真实资料组，禁止使用 00000000")


def _data_center_audit_payload(
    *,
    source_page: str,
    actor: str,
    reason: str = "",
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    source = source_page.strip() or "data_center"
    payload = {
        "source_page": source,
        "source": source,
        "actor": actor,
        "reason": reason.strip() or source,
        "before": dict(before or {}),
        "after": dict(after or {}),
    }
    payload.update(extra)
    return payload


def _json_enrich_latest_audit_payload(
    action: str,
    *,
    source_page: str,
    actor: str,
    reason: str = "",
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
) -> None:
    state = local_simulation.get_state()
    for event in reversed(state.get("audit_events", [])):
        if event.get("action") != action:
            continue
        payload = event.setdefault("payload", {})
        before_payload = before if before is not None else payload.get("before") or payload.get("previous") or {}
        after_payload = after if after is not None else payload.get("after") or payload.get("updates") or {}
        payload.update(
            _data_center_audit_payload(
                source_page=source_page,
                actor=actor,
                reason=reason or str(payload.get("reason") or ""),
                before=before_payload if isinstance(before_payload, Mapping) else {},
                after=after_payload if isinstance(after_payload, Mapping) else {},
            )
        )
        return


def _json_mark_data_center_archive_invalidated(group: dict[str, Any], *, actor: str, reason: str) -> None:
    previous_archive = _data_center_archive_status(group)
    if previous_archive != "archived":
        return
    before = {
        "archive_status": previous_archive,
        "status": str(group.get("status") or ""),
        "delivery_cache_status": str(group.get("delivery_cache_status") or ""),
    }
    for photo in group.get("photos", []) or []:
        if not isinstance(photo, dict) or photo.get("is_active", True) is False:
            continue
        photo["archive_status"] = "pending"
        photo["archived_at"] = ""
        photo["archive_filename"] = ""
    group["archive_status"] = "pending"
    group["status"] = "pending"
    group["reviewer"] = ""
    group["review_note"] = ""
    group["reviewed_at"] = None
    local_simulation.mark_delivery_cache_stale(group, reason)
    local_simulation.append_audit_event(
        "data_center_archive_invalidated",
        actor,
        _data_center_audit_payload(
            source_page="data_center",
            actor=actor,
            reason=reason,
            before=before,
            after={
                "archive_status": group.get("archive_status"),
                "status": group.get("status"),
                "delivery_cache_status": group.get("delivery_cache_status"),
            },
            group_id=group.get("id"),
            previous_archive_status=previous_archive,
        ),
    )


def _json_request_data_center_delivery_package(group: Mapping[str, Any], *, actor: str) -> str:
    from app.services.delivery_package_queue import DeliveryPackageNotReady, request_json_delivery_package
    from app.services.final_delivery_export import DeliveryPackageValidationError

    try:
        request_json_delivery_package(
            groups=[dict(group)],
            task_id=int(group.get("task_id") or 0) or None,
            terminal=str(group.get("terminal") or ""),
            review_scope="reviewed",
            requested_by=actor,
        )
        return "ready"
    except DeliveryPackageNotReady as exc:
        return exc.status
    except DeliveryPackageValidationError as exc:
        now = datetime.now(UTC).isoformat()
        state = local_simulation.get_state()
        group_id = str(group.get("id") or "")
        jobs = state.setdefault("delivery_package_jobs", [])
        job = next(
            (
                item
                for item in jobs
                if group_id in {str(value) for value in item.get("group_ids", [])}
                and str(item.get("status") or "") not in {"ready", "pending", "processing"}
            ),
            None,
        )
        if job is None:
            job = {
                "id": str(uuid4()),
                "team_id": str(state.get("team_id") or local_simulation.current_team_id()),
                "group_ids": [group_id],
                "created_at": now,
            }
            jobs.append(job)
        job.update(
            {
                "status": "pending",
                "requested_by": actor,
                "request_reason": "data_center_auto_archive",
                "last_error": str(exc),
                "lease_owner": None,
                "lease_token": None,
                "lease_expires_at": None,
                "completed_at": None,
                "updated_at": now,
            }
        )
        return "pending"


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


def _reset_group_after_photo_evidence_change(
    session: Session,
    group: MaterialGroup,
) -> None:
    group.status = GroupStatus.INCOMPLETE if group.photo_count < 4 else GroupStatus.UNREVIEWED
    group.reviewed_by_id = None
    group.reviewer = None
    group.review_note = ""
    group.reviewed_at = None
    group.exception_status = None
    group.exception_note = ""
    group.exception_reasons = []
    group.has_archive_blocker = False
    raw = dict(group.raw_data or {})
    raw.update(
        {
            "status": "incomplete" if group.photo_count < 4 else "pending",
            "photo_count": group.photo_count,
            "reviewer": "",
            "review_note": "",
            "reviewed_at": None,
            "exception_status": "",
            "exception_note": "",
            "exception_reasons": [],
            "has_archive_blocker": False,
        }
    )
    group.raw_data = raw
    session.flush()
    active_photos = list(
        session.scalars(
            select(Photo).where(
                Photo.team_id == group.team_id,
                Photo.group_id == group.id,
                Photo.is_active.is_(True),
            )
        ).all()
    )
    for photo in active_photos:
        photo.archive_status = ""
        photo.archive_filename = ""
        photo.archived_at = None
        photo.classified_by = ""
        photo.classified_at = None
        photo_raw = dict(photo.raw_data or {})
        for key in (
            "archive_status",
            "archive_filename",
            "archived_at",
            "archived_by",
            "classified_by",
            "classified_at",
        ):
            photo_raw.pop(key, None)
        photo.raw_data = photo_raw
    session.flush()
    _apply_photo_quality_exception_status(session, group)


def _formal_identity_advisory_lock_key(project_id: Any, meter_match_key: str) -> int:
    digest = hashlib.sha256(f"{project_id}\0{meter_match_key}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _terminal_task_advisory_lock_key(team_id: str, terminal: str) -> int:
    digest = hashlib.sha256(f"terminal-task\0{team_id}\0{terminal}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _stage_transactional_audit(
    session: Session,
    *,
    team_id: str,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: Any = None,
    before_data: Any = None,
    after_data: Any = None,
    payload: Any = None,
) -> AuditLog:
    event = AuditLog(
        team_id=team_id,
        legacy_id=f"{action}-{uuid4()}",
        actor_username=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_data=unmatched_review.redact_audit_photo_secrets(before_data or {}),
        after_data=unmatched_review.redact_audit_photo_secrets(after_data or {}),
        payload=unmatched_review.redact_audit_photo_secrets(payload or {}),
    )
    session.add(event)
    return event


def _verification_group_payload(
    session: Session | None,
    group: Any,
    *,
    prefetched_photos: list[Any] | None = None,
) -> dict[str, Any]:
    from app.services.group_barcode_verification import normalize_verification_group_identity

    if isinstance(group, Mapping):
        return normalize_verification_group_identity(group)
    raw = dict(getattr(group, "raw_data", None) or {})
    photos = list(prefetched_photos or [])
    if prefetched_photos is None and session is not None:
        photos = list(
            session.scalars(
                select(Photo).where(
                    Photo.team_id == group.team_id,
                    Photo.group_id == group.id,
                    Photo.is_active.is_(True),
                )
            ).all()
        )
    return normalize_verification_group_identity({
        "id": str(getattr(group, "legacy_id", None) or group.id),
        "terminal": str(getattr(group, "terminal", None) or raw.get("terminal") or "").strip(),
        "meter_no": str(getattr(group, "display_meter_no", None) or raw.get("meter_no") or "").strip(),
        "construction_collector": raw.get("construction_collector"),
        "collector": raw.get("collector"),
        "construction_module_asset_no": raw.get("construction_module_asset_no"),
        "module_asset_no": raw.get("module_asset_no"),
        "photos": [
            {
                "id": str(
                    getattr(photo, "legacy_id", None)
                    or getattr(photo, "id", None)
                    or ""
                ),
                "sha256": str(getattr(photo, "sha256", None) or ""),
                "category": str(getattr(photo, "category", None) or ""),
                "is_active": bool(getattr(photo, "is_active", True)),
                "upload_status": getattr(getattr(photo, "upload_status", "uploaded"), "value", getattr(photo, "upload_status", "uploaded")),
                "collector": str(getattr(photo, "collector", None) or ""),
                "asset_no": str(getattr(photo, "asset_no", None) or ""),
                "image_url": str(getattr(photo, "image_url", None) or ""),
                "source_url": str(getattr(photo, "source_url", None) or ""),
                "storage_type": str(getattr(photo, "storage_type", None) or ""),
                "storage_bucket": str(getattr(photo, "storage_bucket", None) or ""),
                "storage_key": str(getattr(photo, "storage_key", None) or ""),
            }
            for photo in photos
        ],
    })


def _force_completed_verification_transition(
    current: Mapping[str, Any],
    evidence_fingerprint: str | None,
) -> dict[str, Any]:
    transition_source = dict(current)
    if (
        str(transition_source.get("status") or "") in {"passed", "manual_confirmed"}
        and evidence_fingerprint == transition_source.get("evidence_fingerprint")
    ):
        transition_source["evidence_fingerprint"] = None
    return transition_source


def _clear_legacy_verification_flags(group: Any) -> None:
    values = {
        "group_barcode_manual_confirmed": False,
        "group_barcode_manual_confirmed_fields": [],
        "group_barcode_manual_confirmed_by": "",
        "group_barcode_manual_confirmed_at": "",
        "group_barcode_manual_confirmation_reason": "",
        "group_barcode_manual_confirmation_photo_ids": [],
    }
    if isinstance(group, dict):
        group.update(values)
        return
    raw = dict(getattr(group, "raw_data", None) or {})
    raw.update(values)
    group.raw_data = raw


def _mask_barcode_audit_value(value: str) -> str:
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}***{value[-2:]}"


def invalidate_verification_for_group(
    session: Session | None,
    group: Any,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    """Invalidate the current verification after an evidence write."""
    from app.services.group_barcode_verification import (
        evaluate_group_eligibility,
        invalidate_group_verification,
    )

    evaluation = evaluate_group_eligibility(_verification_group_payload(session, group))
    now = datetime.now(UTC)

    if isinstance(group, dict):
        current = dict(
            group.get("barcode_verification")
            or {"status": "not_eligible", "evidence_version": 0, "evidence_fingerprint": None}
        )
        transition_source = _force_completed_verification_transition(
            current,
            evaluation.evidence_fingerprint,
        )
        result = invalidate_group_verification(
            transition_source,
            reason=reason,
            actor=actor,
            evidence_fingerprint=evaluation.evidence_fingerprint,
            next_status=evaluation.status,
        )
        result.update(
            {
                "meter_matched": None,
                "module_matched": None,
                "collector_matched": None,
                "recognition_source": None,
                "invalidated_at": now.isoformat(),
            }
        )
        group["barcode_verification"] = result
        _clear_legacy_verification_flags(group)
        local_simulation.mark_delivery_cache_stale(group, reason)
        from app.services.delivery_cache import sync_json_delivery_cache_job_for_group

        sync_json_delivery_cache_job_for_group(
            group,
            team_id=local_simulation.current_team_id(),
            actor=actor,
            reason=reason,
        )
        local_simulation.append_audit_event(
            "group_barcode_verification_invalidated",
            actor,
            {
                "group_id": str(group.get("id") or ""),
                "reason": reason,
                "previous_status": current.get("status"),
                "status": result["status"],
                "evidence_version": result["evidence_version"],
            },
        )
        return result

    if session is None:
        raise ValueError("PostgreSQL verification invalidation requires a session")
    verification = session.scalar(
        select(GroupBarcodeVerification)
        .where(
            GroupBarcodeVerification.team_id == group.team_id,
            GroupBarcodeVerification.group_id == group.id,
        )
        .with_for_update()
    )
    if verification is None:
        verification = GroupBarcodeVerification(
            team_id=group.team_id,
            group_id=group.id,
            status="not_eligible",
            evidence_version=0,
        )
        session.add(verification)
    current = {
        "status": verification.status,
        "evidence_fingerprint": verification.evidence_fingerprint,
        "evidence_version": verification.evidence_version,
        "attempt_count": verification.attempt_count,
        "lease_owner": verification.lease_owner,
        "lease_token": verification.lease_token,
        "lease_expires_at": verification.lease_expires_at,
        "auto_archive_status": getattr(verification, "auto_archive_status", None),
        "auto_archive_attempt_count": getattr(verification, "auto_archive_attempt_count", 0),
        "auto_archive_lease_owner": getattr(verification, "auto_archive_lease_owner", None),
        "auto_archive_lease_token": getattr(verification, "auto_archive_lease_token", None),
        "auto_archive_lease_expires_at": getattr(verification, "auto_archive_lease_expires_at", None),
        "auto_archive_error": getattr(verification, "auto_archive_error", None),
    }
    result = invalidate_group_verification(
        _force_completed_verification_transition(current, evaluation.evidence_fingerprint),
        reason=reason,
        actor=actor,
        evidence_fingerprint=evaluation.evidence_fingerprint,
        next_status=evaluation.status,
    )
    for field in (
        "status",
        "evidence_fingerprint",
        "evidence_version",
        "attempt_count",
        "lease_owner",
        "lease_token",
        "lease_expires_at",
        "invalidation_reason",
        "invalidated_by",
        "auto_archive_status",
        "auto_archive_attempt_count",
        "auto_archive_lease_owner",
        "auto_archive_lease_token",
        "auto_archive_lease_expires_at",
        "auto_archive_error",
    ):
        setattr(verification, field, result.get(field))
    verification.meter_matched = None
    verification.module_matched = None
    verification.collector_matched = None
    verification.recognition_source = None
    verification.invalidated_at = now
    _clear_legacy_verification_flags(group)
    group_raw = dict(group.raw_data or {})
    if group_raw.get("delivery_cache_status") not in {None, "", "none"}:
        group_raw["delivery_cache_status"] = "stale"
        group_raw["delivery_cache_error"] = reason
        group.raw_data = group_raw
    cached_photos = session.scalars(
        select(Photo).where(
            Photo.team_id == group.team_id,
            Photo.group_id == group.id,
            Photo.is_active.is_(True),
        )
    ).all()
    for photo in cached_photos:
        photo_raw = dict(photo.raw_data or {})
        if photo_raw.get("delivery_cache_path"):
            photo_raw["delivery_cache_status"] = "stale"
            photo.raw_data = photo_raw
    from app.services.delivery_cache import (
        postgres_delivery_group_payload,
        sync_postgres_delivery_cache_job_for_group,
    )

    sync_postgres_delivery_cache_job_for_group(
        session,
        group,
        group_payload=postgres_delivery_group_payload(group, cached_photos),
        actor=actor,
        reason=reason,
        mark_retry_without_job=False,
    )
    _stage_transactional_audit(
        session,
        team_id=group.team_id,
        actor=actor,
        action="group_barcode_verification_invalidated",
        entity_type="material_group",
        entity_id=group.id,
        before_data={"status": current["status"], "evidence_version": current["evidence_version"]},
        after_data={"status": result["status"], "evidence_version": result["evidence_version"]},
        payload={
            "group_id": str(getattr(group, "legacy_id", None) or group.id),
            "reason": reason,
            "evidence_fingerprint": evaluation.evidence_fingerprint or "",
        },
    )
    session.flush()
    return {**result, "invalidated_at": now.isoformat()}


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
    construction_available, review_available = construction_task_availability(resolved_stats)
    construction_priority = bool(
        getattr(task, "construction_priority", False) and construction_available
    )
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
        "construction_priority": construction_priority,
        "construction_priority_updated_by": getattr(task, "construction_priority_updated_by", None) or "",
        "construction_priority_updated_at": (
            getattr(task, "construction_priority_updated_at", None).isoformat()
            if getattr(task, "construction_priority_updated_at", None)
            else ""
        ),
        "construction_available": construction_available,
        "review_available": review_available,
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
        "original_filename": getattr(photo, "original_filename", None) or "",
        "sort_order": photo.sort_order,
        "barcode": photo.barcode or "",
        "collector": photo.collector or "",
        "module_asset_no": photo.asset_no or "",
        "creator": photo.creator or "",
        "upload_status": str(
            getattr(getattr(photo, "upload_status", "uploaded"), "value", getattr(photo, "upload_status", "uploaded"))
            or ""
        ),
        "upload_source": raw.get("upload_source") or raw.get("storage_source") or "",
    }
    for key in (
        *unmatched_review.PHOTO_EVIDENCE_FIELDS,
        "sha256_source",
        "temporary_review_manual_confirmed",
        "temporary_review_reviewer",
        "temporary_review_reviewed_at",
        "delivery_cache_path",
        "delivery_cache_version",
        "delivery_cache_status",
        "delivery_cache_content_sha256",
        "delivery_cache_content_type",
        "delivery_cache_built_at",
        "delivery_cache_error",
        "client_completed_at",
    ):
        if key in raw:
            payload[key] = raw[key]
    if not payload.get("sha256_source"):
        if str(raw.get("sha256") or "").strip():
            payload["sha256_source"] = "declared"
        elif image_url and photo.sha256 == hashlib.sha256(image_url.encode("utf-8")).hexdigest():
            payload["sha256_source"] = "image_url"
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
        "sha256": _row_value(row, "sha256") or raw.get("sha256") or "",
        "is_active": bool(_row_value(row, "is_active", True)),
        "upload_status": _status_value(_row_value(row, "upload_status", "uploaded")),
    }
    for key in unmatched_review.PHOTO_EVIDENCE_FIELDS:
        if key in raw:
            payload[key] = raw[key]
    return payload


def _group_barcode_payload_from_row(row: Any) -> dict[str, Any]:
    raw = dict(_row_value(row, "raw_data", {}) or {})
    payload = {
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
        "_barcode_legacy_raw": raw,
    }
    verification_status = str(_row_value(row, "verification_status", "") or "")
    if verification_status:
        verification_source = {
            key: _row_value(row, f"verification_{key}")
            for key in (
                "status",
                "evidence_fingerprint",
                "evidence_version",
                "meter_matched",
                "module_matched",
                "collector_matched",
                "recognition_source",
                "attempt_count",
                "invalidation_reason",
                "invalidated_by",
                "invalidated_at",
                "auto_archive_status",
                "auto_archived_at",
                "auto_archive_error",
                "updated_at",
            )
        }
        durable_verification = normalize_barcode_verification(
            verification_source,
            raw.get("barcode_verification") or {},
        )
        if durable_verification:
            payload["barcode_verification"] = durable_verification
            payload.update(verification_compatibility_fields(durable_verification))
    else:
        durable_verification = normalize_barcode_verification(raw.get("barcode_verification"))
        if durable_verification:
            payload["barcode_verification"] = durable_verification
            payload.update(verification_compatibility_fields(durable_verification))
    return payload


def _group_barcode_payload(group: Any, photos: list[Any]) -> dict[str, Any]:
    if isinstance(group, dict):
        payload = dict(group)
        raw = payload.pop("_barcode_legacy_raw", payload)
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
    durable_verification = resolve_persisted_barcode_verification(
        payload.get("barcode_verification"),
        raw,
        photo_payloads,
    )
    if durable_verification:
        payload["barcode_verification"] = durable_verification
        payload.update(verification_compatibility_fields(durable_verification))
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
    payloads: list[dict[str, Any]] = []
    for group in groups:
        photos = photos_by_group_id.get(_group_lookup_id(group))
        if photos is None and isinstance(group, dict):
            photos = list(group.get("photos") or [])
        payloads.append(_group_barcode_payload(group, photos or []))
    summary = summarize_durable_accuracy(payloads)
    unmaterialized = max(0, int(total_groups or 0) - len(groups)) if total_groups is not None else 0
    summary["group_barcode_accuracy_not_required"] += unmaterialized
    summary["group_barcode_accuracy_not_eligible"] += unmaterialized
    return summary


def _eligible_group_photo_set_subquery(team_id: str):
    required_count = len(REQUIRED_CATEGORIES)
    return (
        select(
            Photo.group_id.label("group_id"),
            func.count(Photo.id).label("photo_count"),
            func.count(Photo.category.distinct()).label("category_count"),
        )
        .where(
            Photo.team_id == team_id,
            Photo.is_active.is_(True),
            Photo.upload_status != PhotoUploadStatus.INVALID,
            Photo.group_id.is_not(None),
        )
        .group_by(Photo.group_id)
        .having(
            func.count(Photo.id) == required_count,
            func.count(Photo.category.distinct()) == required_count,
            func.sum(case((Photo.category.in_(REQUIRED_CATEGORIES), 1), else_=0)) == required_count,
        )
        .subquery()
    )


def _postgres_review_verification_status_expression():
    legacy_photo = aliased(Photo)
    nested_status = MaterialGroup.raw_data["barcode_verification"]["status"].as_string()
    legacy_status = func.lower(
        func.coalesce(MaterialGroup.raw_data.op("->>")("group_barcode_check_status"), "")
    )
    photo_method = func.lower(
        func.coalesce(legacy_photo.raw_data.op("->>")("barcode_check_method"), "")
    )

    def has_array_values(key: str):
        value = legacy_photo.raw_data[key]
        elements = func.jsonb_array_elements(value).table_valued("value")
        element = cast(elements.c.value, JSONB)
        element_text = element.op("#>>")(array([], type_=Text))
        non_empty_element_count = (
            select(func.count())
            .select_from(elements)
            .where(
                func.jsonb_typeof(element) == "string",
                func.btrim(element_text, LEGACY_EVIDENCE_WHITESPACE) != "",
            )
            .scalar_subquery()
        )
        return case(
            (func.jsonb_typeof(value) == "array", non_empty_element_count),
            else_=0,
        ) > 0

    legacy_ocr_match = (
        select(legacy_photo.id)
        .where(
            legacy_photo.team_id == MaterialGroup.team_id,
            legacy_photo.group_id == MaterialGroup.id,
            legacy_photo.is_active.is_(True),
            legacy_photo.upload_status != PhotoUploadStatus.INVALID,
            or_(
                photo_method.in_(OCR_ONLY_METHODS),
                has_array_values("ocr_candidate_values"),
                has_array_values("barcode_check_ocr_values"),
            ),
        )
        .exists()
    )
    legacy_machine_match = (
        select(legacy_photo.id)
        .where(
            legacy_photo.team_id == MaterialGroup.team_id,
            legacy_photo.group_id == MaterialGroup.id,
            legacy_photo.is_active.is_(True),
            legacy_photo.upload_status != PhotoUploadStatus.INVALID,
            or_(
                has_array_values("machine_barcode_values"),
                has_array_values("machine_qr_values"),
                and_(
                    photo_method != "",
                    photo_method.notin_(OCR_ONLY_METHODS),
                    has_array_values("barcode_check_values"),
                ),
            ),
        )
        .exists()
    )
    manual_confirmed = (
        func.lower(
            func.coalesce(
                MaterialGroup.raw_data.op("->>")("group_barcode_manual_confirmed"),
                "",
            )
        )
        == "true"
    )
    nested_durable_status = case(
        (nested_status.in_(DURABLE_STATUSES), nested_status),
        else_=None,
    )
    legacy_durable_status = case(
        (
            legacy_status == "matched",
            case(
                (manual_confirmed, "manual_confirmed"),
                (and_(legacy_ocr_match, ~legacy_machine_match), "partial"),
                else_="passed",
            ),
        ),
        (legacy_status == "mismatched", "mismatch"),
        (legacy_status == "unreadable", "unreadable"),
        (legacy_status == "not_required", "not_eligible"),
        else_=None,
    )
    return func.coalesce(
        GroupBarcodeVerification.status,
        nested_durable_status,
        legacy_durable_status,
    )


def _group_lookup_id(group: Any) -> str:
    if isinstance(group, dict):
        return str(group.get("id") or group.get("group_id") or "")
    return str(getattr(group, "id", ""))


def _group_barcode_review_statuses(status: str) -> set[str]:
    normalized = str(status or "unreadable").strip().lower()
    if normalized == "all":
        return {"matched", "unreadable", "mismatched"}
    if normalized == "review":
        return {"unreadable", "mismatched"}
    if normalized in {"matched", "passed", "success"}:
        return {"matched"}
    if normalized in {"mismatched", "failed"}:
        return {"mismatched"}
    return {"unreadable"}


def _group_barcode_review_item_matches_query(item: dict[str, Any], query: str) -> bool:
    keyword = str(query or "").strip().lower()
    if not keyword:
        return True
    values: list[Any] = [
        item.get("group_id"),
        item.get("meter_no"),
        item.get("module_asset_no"),
        item.get("collector"),
        item.get("terminal"),
        item.get("address"),
        item.get("installer"),
        item.get("group_status"),
        item.get("status"),
        *(item.get("missing_fields") or []),
        *(item.get("missing_expected_fields") or []),
        *(item.get("unmatched_values") or []),
    ]
    for mapping_key in ("expected", "detected_values"):
        mapping = item.get(mapping_key) or {}
        if isinstance(mapping, dict):
            for key, nested_values in mapping.items():
                values.append(key)
                if isinstance(nested_values, list):
                    values.extend(nested_values)
                else:
                    values.append(nested_values)
    for photo in item.get("photos") or []:
        if not isinstance(photo, dict):
            continue
        values.extend(
            [
                photo.get("id"),
                photo.get("category"),
                photo.get("category_label"),
                photo.get("barcode_check_status"),
                photo.get("barcode_check_method"),
            ]
        )
        for list_key in (
            "barcode_check_values",
            "barcode_check_normalized_values",
            "barcode_check_ocr_values",
            "barcode_check_ocr_normalized_values",
        ):
            list_value = photo.get(list_key)
            if isinstance(list_value, list):
                values.extend(list_value)
    return keyword in " ".join(str(value or "") for value in values).lower()


def _filter_group_barcode_review_items(items: list[dict[str, Any]], query: str = "") -> list[dict[str, Any]]:
    keyword = str(query or "").strip()
    if not keyword:
        return items
    return [item for item in items if _group_barcode_review_item_matches_query(item, keyword)]


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


_VERIFICATION_NOT_LOADED = object()


def _group_payload(
    session: Session,
    group: MaterialGroup,
    include_photos: bool = True,
    *,
    verification: Any = _VERIFICATION_NOT_LOADED,
) -> dict[str, Any]:
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
    if verification is _VERIFICATION_NOT_LOADED:
        verification = session.scalar(
            select(GroupBarcodeVerification).where(
                GroupBarcodeVerification.team_id == group.team_id,
                GroupBarcodeVerification.group_id == group.id,
            )
        )
    durable_verification = resolve_persisted_barcode_verification(
        verification,
        raw,
        photos if include_photos else None,
    )
    if durable_verification:
        payload["barcode_verification"] = durable_verification
        payload.update(verification_compatibility_fields(durable_verification))
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
        "source_unmatched_id",
        "group_barcode_check_status",
        "group_barcode_missing_fields",
        "group_barcode_missing_expected_fields",
        "group_barcode_expected_values",
        "group_barcode_detected_values",
        "group_barcode_matched_fields",
        "group_barcode_unmatched_values",
        "delivery_cache_status",
        "delivery_cache_built_at",
        "delivery_cache_error",
        "delivery_cache_retryable",
        "delivery_package_invalidation_epoch",
        "delivery_package_invalidated_at",
        "delivery_package_invalidated_by",
    ):
        if key in raw and key not in payload:
            payload[key] = raw[key]
    if not str(payload.get("installer") or "").strip() and task_installer:
        payload["installer"] = task_installer
    return payload


def _group_payloads(
    session: Session,
    groups: list[MaterialGroup],
    *,
    include_photos: bool,
) -> list[dict[str, Any]]:
    if not groups:
        return []
    group_ids = [group.id for group in groups]
    verification_rows = session.scalars(
        select(GroupBarcodeVerification).where(
            GroupBarcodeVerification.team_id == groups[0].team_id,
            GroupBarcodeVerification.group_id.in_(group_ids),
        )
    ).all()
    verification_by_group_id = {str(row.group_id): row for row in verification_rows}
    return [
        _group_payload(
            session,
            group,
            include_photos=include_photos,
            verification=verification_by_group_id.get(str(group.id)),
        )
        for group in groups
    ]


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
    barcode_group = _group_barcode_payload(group, photos)

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
        **_group_barcode_status_summary(barcode_group),
    }
    durable_verification = normalize_barcode_verification(barcode_group.get("barcode_verification"))
    if durable_verification:
        payload["barcode_verification"] = durable_verification
        payload.update(verification_compatibility_fields(durable_verification))
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


def _review_queue_status_expression():
    raw_status = func.nullif(func.trim(MaterialGroup.raw_data["status"].astext), "")
    legacy_status = case(
        (
            raw_status.in_(("pending", "incomplete", "approved", "exception", "unmatched", "unreviewed")),
            raw_status,
        ),
        (MaterialGroup.status == GroupStatus.UNREVIEWED, literal("pending")),
        (MaterialGroup.status == GroupStatus.REJECTED, literal("exception")),
        else_=cast(MaterialGroup.status, String),
    )
    return case(
        (legacy_status == "approved", literal("archived")),
        (
            or_(legacy_status == "exception", MaterialGroup.has_archive_blocker.is_(True)),
            literal("exception"),
        ),
        (
            and_(MaterialGroup.photo_count == 0, legacy_status != "unmatched"),
            literal("unconstructed"),
        ),
        else_=literal("reviewable"),
    )


def _review_queue_search_conditions(team_id: str, query: str) -> list[Any]:
    conditions: list[Any] = []
    for term in [item for item in re.split(r"\s+", query.strip()) if item]:
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
                    Photo.original_filename.ilike(pattern),
                    Photo.source_file_id.ilike(pattern),
                    Photo.source.ilike(pattern),
                    Photo.raw_data["module_asset_no"].astext.ilike(pattern),
                    Photo.raw_data["asset_no"].astext.ilike(pattern),
                    Photo.raw_data["collector"].astext.ilike(pattern),
                    Photo.raw_data["creator"].astext.ilike(pattern),
                    Photo.raw_data["source_file"].astext.ilike(pattern),
                ),
            )
            .exists()
        )
        task_installer_match = (
            select(Task.id)
            .where(
                Task.team_id == team_id,
                Task.id == MaterialGroup.task_id,
                Task.construction_claimed_by.ilike(pattern),
            )
            .exists()
        )
        conditions.append(
            or_(
                MaterialGroup.legacy_id.ilike(pattern),
                MaterialGroup.terminal.ilike(pattern),
                MaterialGroup.display_meter_no.ilike(pattern),
                MaterialGroup.meter_match_key.ilike(pattern),
                MaterialGroup.installation_address.ilike(pattern),
                MaterialGroup.reviewer.ilike(pattern),
                cast(MaterialGroup.status, String).ilike(pattern),
                MaterialGroup.raw_data["status"].astext.ilike(pattern),
                MaterialGroup.raw_data["installer"].astext.ilike(pattern),
                MaterialGroup.raw_data["constructor"].astext.ilike(pattern),
                MaterialGroup.raw_data["creator"].astext.ilike(pattern),
                MaterialGroup.raw_data["replacement_by"].astext.ilike(pattern),
                MaterialGroup.raw_data["module_asset_no"].astext.ilike(pattern),
                MaterialGroup.raw_data["asset_no"].astext.ilike(pattern),
                MaterialGroup.raw_data["collector"].astext.ilike(pattern),
                MaterialGroup.raw_data["construction_module_asset_no"].astext.ilike(pattern),
                MaterialGroup.raw_data["construction_collector"].astext.ilike(pattern),
                task_installer_match,
                photo_match,
            )
        )
    return conditions


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
        "delivery_cache_content_sha256": photo.get("delivery_cache_content_sha256", ""),
        "source_file": photo.get("source_file", ""),
        "delivery_cache_url": local_simulation.delivery_cache_url_for_photo(group, photo),
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
    result = {
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
        "temporary_review": payload.get("temporary_review") or {},
        "raw": payload,
    }
    result["review_version"] = int(unmatched_review.build_review(result)["version"])
    return result


def _checked_unmatched_review(record: UnmatchedRecord, expected_version: int) -> dict[str, Any]:
    review = unmatched_review.build_review(_unmatched_payload(record))
    unmatched_review.require_version(review, expected_version)
    return review


def _advance_unmatched_review_payload(
    raw: dict[str, Any],
    review: dict[str, Any],
    expected_version: int,
) -> dict[str, Any]:
    updated = deepcopy(review)
    updated["version"] = expected_version + 1
    updated["updated_at"] = datetime.now(UTC).isoformat()
    raw["temporary_review"] = updated
    return raw


def _new_formal_group_legacy_id() -> str:
    return f"g-{uuid4().hex}"


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
    def list_tasks(
        self,
        *,
        summary_only: bool = False,
        include_installer_distribution: bool = True,
    ) -> list[dict[str, Any]]:
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
    def list_data_center_rows(self, query: DataCenterQuery) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_data_center_detail(self, *, kind: str, item_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    def list_photo_barcode_review_groups(
        self,
        *,
        status: str = "unreadable",
        query: str = "",
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
    def list_unmatched_records(
        self,
        *,
        query: str = "",
        limit: int = 100,
        offset: int = 0,
        assigned_to: str = "",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_review_task_groups(
        self,
        task_id: int,
        *,
        limit: int = 20,
        offset: int = 0,
        review_status: str = "all",
        query: str = "",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def export_unmatched_records(self, *, query: str = "", limit: int = 100_000) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_unmatched_review(self, unmatched_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_unmatched_match_candidates(self, unmatched_id: str, *, actor: str = "") -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def finalize_unmatched_match(
        self,
        unmatched_id: str,
        *,
        actor: str,
        candidate_key: str,
        expected_version: int,
        source_page: str = "",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def save_unmatched_review(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int,
        metadata: dict[str, Any] | None = None,
        photo_updates: list[dict[str, Any]] | None = None,
        state: str = "pending",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def rescan_unmatched_review_photo(
        self,
        unmatched_id: str,
        photo_id: str,
        *,
        actor: str,
        expected_version: int,
        category: str = "",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def confirm_unmatched_review(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int,
        confirmed: bool = True,
    ) -> dict[str, Any]:
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
        expected_version: int = 1,
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
        expected_version: int = 1,
        note: str = "",
        due_date: str = "",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def unassign_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int = 1,
        reason: str = "",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def mark_unmatched_outside_project(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int = 1,
        note: str = "",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def rematch_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int = 1,
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
    def update_data_center_group(
        self,
        group_id: str,
        *,
        patch: dict[str, Any],
        actor: str,
        reason: str = "",
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def classify_data_center_group_photo(
        self,
        group_id: str,
        photo_id: str,
        category: str,
        *,
        actor: str,
        reason: str = "",
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def rescan_data_center_group_photo_barcode(
        self,
        group_id: str,
        photo_id: str,
        *,
        actor: str,
        category: str = "",
        reason: str = "",
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def scan_data_center_group_photo_region(
        self,
        group_id: str,
        photo_id: str,
        *,
        barcode_type: str,
        region: Mapping[str, Any],
        actor: str,
        reason: str = "",
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def manual_confirm_group_barcode(
        self,
        group_id: str,
        *,
        actor: str,
        reason: str,
        source_page: str = "data_center",
        meter_no: str,
        module_asset_no: str,
        collector: str,
        photo_ids: list[str],
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def return_data_center_group_to_exception_order(
        self,
        group_id: str,
        *,
        actor: str,
        category: str,
        note: str,
        reason: str = "",
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def finalize_unmatched_to_group(
        self,
        unmatched_id: str,
        *,
        actor: str,
        terminal: str,
        meter_no: str,
        candidate_key: str,
        expected_version: int,
        source_page: str = "data_center",
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
    def set_construction_task_priority(
        self,
        task_id: int,
        *,
        actor: str,
        priority: bool,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def import_construction_priorities(self, rows: list[Any], *, actor: str, confirm: bool) -> dict[str, Any]:
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
        expected_version: int = 1,
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
    def apply_group_scan_result(
        self,
        group_id: str,
        result: Any,
        *,
        claimed_evidence_fingerprint: str,
        claimed_evidence_version: int,
        lease_owner: str,
        lease_token: str,
        actor: str,
    ) -> dict[str, Any]:
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
    def confirm_group_barcode_manually(
        self,
        group_id: str,
        *,
        actor: str,
        meter_no: str,
        module_asset_no: str,
        collector: str,
        reason: str,
        photo_ids: list[str],
        source_page: str = "",
        require_claim: bool = True,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def delete_photo(self, group_id: str, photo_id: str, reviewer: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def delete_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int = 1,
        reason: str = "",
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def associate_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int = 1,
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
        expected_version: int = 1,
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
    def request_final_delivery_export(
        self,
        *,
        task_id: int | None = None,
        terminal: str = "",
        review_scope: str = "reviewed",
        requested_by: str = "",
    ) -> LeasedDeliveryPackage:
        raise NotImplementedError

    @abstractmethod
    def build_final_delivery_export(
        self,
        *,
        task_id: int | None = None,
        terminal: str = "",
        review_scope: str = "reviewed",
    ) -> LeasedDeliveryPackage:
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
        source_page: str = "",
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
        source_page: str = "",
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
    def _authoritative_mutation(self, operation: Callable[[], Any]) -> Any:
        team_id = local_simulation.current_team_id()
        transaction = local_simulation.active_authoritative_json_write(team_id)
        owns_transaction = transaction is None
        token = None
        if owns_transaction:
            transaction = local_simulation.begin_authoritative_json_write(team_id)
            token = local_simulation.activate_authoritative_json_write(transaction)
        try:
            result = operation()
            if owns_transaction:
                local_simulation.finish_authoritative_json_write(transaction, token)
        except BaseException:
            if owns_transaction and transaction is not None and not transaction.closed:
                local_simulation.abort_authoritative_json_write(transaction, token)
            raise
        return result

    def summary(self) -> dict[str, Any]:
        state = local_simulation.get_state()
        return {"summary": state["summary"], "paths": state["paths"]}

    def list_tasks(
        self,
        *,
        summary_only: bool = False,
        include_installer_distribution: bool = True,
    ) -> list[dict[str, Any]]:
        tasks = local_simulation.list_tasks(
            include_installer_distribution=include_installer_distribution,
        )
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
        state = self._authoritative_mutation(local_simulation.clear_scan_data)
        return {"summary": state["summary"], "paths": state["paths"]}

    def sync_photos_to_oss(self, *, team_id: str = "", progress_callback=None) -> dict[str, Any]:
        return local_simulation.sync_state_photos_to_oss(team_id=team_id, progress_callback=progress_callback)

    def persist_state(self) -> None:
        local_simulation.save_all_team_states()

    def list_groups(self, *, limit: int = 100, offset: int = 0, status: str | None = None) -> dict[str, Any]:
        return local_simulation.list_groups(limit=limit, offset=offset, status=status)

    def list_data_center_rows(self, query: DataCenterQuery) -> dict[str, Any]:
        return local_simulation.list_data_center_rows(query)

    def get_data_center_detail(self, *, kind: str, item_id: str) -> dict[str, Any] | None:
        return local_simulation.get_data_center_detail(kind=kind, item_id=item_id)

    def list_photo_barcode_review_groups(
        self,
        *,
        status: str = "unreadable",
        query: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        groups = local_simulation.list_groups(limit=100000, offset=0).get("items", [])
        statuses = _group_barcode_review_statuses(status)
        items = photo_barcode_check.list_group_barcode_review_items(groups, statuses=statuses)
        items = _filter_group_barcode_review_items(items, query)
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

    def list_review_task_groups(
        self,
        task_id: int,
        *,
        limit: int = 20,
        offset: int = 0,
        review_status: str = "all",
        query: str = "",
    ) -> dict[str, Any]:
        return local_simulation.list_review_task_groups(
            task_id,
            limit=limit,
            offset=offset,
            review_status=review_status,
            query=query,
        )

    def get_group(self, group_id: str) -> dict[str, Any] | None:
        return local_simulation.get_group(group_id)

    def list_unmatched_records(
        self,
        *,
        query: str = "",
        limit: int = 100,
        offset: int = 0,
        assigned_to: str = "",
    ) -> dict[str, Any]:
        return local_simulation.list_unmatched_records(
            query=query,
            limit=limit,
            offset=offset,
            assigned_to=assigned_to,
        )

    def export_unmatched_records(self, *, query: str = "", limit: int = 100_000) -> dict[str, Any]:
        return deepcopy(
            local_simulation.list_unmatched_records(
                query=query,
                limit=limit,
                offset=0,
            )
        )

    def get_unmatched_review(self, unmatched_id: str) -> dict[str, Any]:
        return local_simulation.get_unmatched_review(unmatched_id)

    def list_unmatched_match_candidates(self, unmatched_id: str, *, actor: str = "") -> dict[str, Any]:
        return local_simulation.list_unmatched_match_candidates(unmatched_id, actor=actor)

    def finalize_unmatched_match(
        self,
        unmatched_id: str,
        *,
        actor: str,
        candidate_key: str,
        expected_version: int,
        source_page: str = "",
    ) -> dict[str, Any]:
        return local_simulation.finalize_unmatched_match(
            unmatched_id,
            actor=actor,
            candidate_key=candidate_key,
            expected_version=expected_version,
        )

    def save_unmatched_review(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int,
        metadata: dict[str, Any] | None = None,
        photo_updates: list[dict[str, Any]] | None = None,
        state: str = "pending",
    ) -> dict[str, Any]:
        return local_simulation.save_unmatched_review(
            unmatched_id,
            actor=actor,
            expected_version=expected_version,
            metadata=metadata,
            photo_updates=photo_updates,
            state=state,
        )

    def rescan_unmatched_review_photo(
        self,
        unmatched_id: str,
        photo_id: str,
        *,
        actor: str,
        expected_version: int,
        category: str = "",
    ) -> dict[str, Any]:
        return local_simulation.rescan_unmatched_review_photo(
            unmatched_id,
            photo_id,
            actor=actor,
            expected_version=expected_version,
            category=category,
        )

    def confirm_unmatched_review(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int,
        confirmed: bool = True,
    ) -> dict[str, Any]:
        return local_simulation.confirm_unmatched_review(
            unmatched_id,
            actor=actor,
            expected_version=expected_version,
            confirmed=confirmed,
        )

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
        expected_version: int = 1,
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "record": local_simulation.update_unmatched_record(
                unmatched_id,
                actor=actor,
                updates=updates,
                expected_version=expected_version,
            )
        }

    def assign_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        constructor: str,
        expected_version: int = 1,
        note: str = "",
        due_date: str = "",
    ) -> dict[str, Any]:
        return {
            "record": local_simulation.assign_unmatched_record(
                unmatched_id,
                actor=actor,
                constructor=constructor,
                expected_version=expected_version,
                note=note,
                due_date=due_date,
            )
        }

    def unassign_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int = 1,
        reason: str = "",
    ) -> dict[str, Any]:
        return {
            "record": local_simulation.unassign_unmatched_record(
                unmatched_id,
                actor=actor,
                expected_version=expected_version,
                reason=reason,
            )
        }

    def mark_unmatched_outside_project(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int = 1,
        note: str = "",
    ) -> dict[str, Any]:
        return {
            "record": local_simulation.mark_unmatched_outside_project(
                unmatched_id,
                actor=actor,
                expected_version=expected_version,
                note=note,
            )
        }

    def rematch_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int = 1,
        meter_no: str = "",
        old_meter_no: str = "",
        terminal: str = "",
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return local_simulation.rematch_unmatched_record(
            unmatched_id,
            actor=actor,
            expected_version=expected_version,
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
        team_id = local_simulation.current_team_id()
        transaction = local_simulation.active_authoritative_json_write(team_id)
        owns_transaction = transaction is None
        token = None
        if owns_transaction:
            transaction = local_simulation.begin_authoritative_json_write(team_id)
            token = local_simulation.activate_authoritative_json_write(transaction)
        try:
            result = local_simulation.update_group_metadata(
                group_id,
                actor=actor,
                updates=updates,
                audit_action=audit_action,
            )
            if owns_transaction:
                local_simulation.finish_authoritative_json_write(transaction, token)
        except BaseException:
            if owns_transaction and transaction is not None and not transaction.closed:
                local_simulation.abort_authoritative_json_write(transaction, token)
            raise
        return result

    def update_data_center_group(
        self,
        group_id: str,
        *,
        patch: dict[str, Any],
        actor: str,
        reason: str = "",
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        before_group = deepcopy(local_simulation.get_group(group_id) or {})
        result = self.update_group_metadata(
            group_id,
            actor=actor,
            updates=patch,
            audit_action="data_center_group_updated",
        )
        _json_enrich_latest_audit_payload(
            "data_center_group_updated",
            source_page=source_page,
            actor=actor,
            reason=reason or "data_center_group_updated",
        )
        group = local_simulation.get_group(group_id)
        if group is None:
            raise KeyError(group_id)
        changed_fields = list(result.get("changed_fields") or [])
        if changed_fields and set(changed_fields).intersection(DATA_CENTER_IDENTITY_FIELDS):
            had_archived_before_update = _data_center_archive_status(before_group) == "archived"
            _json_mark_data_center_archive_invalidated(
                group,
                actor=actor,
                reason=reason or "data_center_identity_changed",
            )
            if had_archived_before_update and not any(
                event.get("action") == "data_center_archive_invalidated"
                for event in local_simulation.get_state().get("audit_events", [])
            ):
                local_simulation.append_audit_event(
                    "data_center_archive_invalidated",
                    actor,
                    _data_center_audit_payload(
                        source_page=source_page,
                        actor=actor,
                        reason=reason or "data_center_identity_changed",
                        before={
                            "archive_status": _data_center_archive_status(before_group),
                            "status": before_group.get("status", ""),
                            "delivery_cache_status": before_group.get("delivery_cache_status", ""),
                        },
                        after={
                            "archive_status": _data_center_archive_status(group),
                            "status": group.get("status", ""),
                            "delivery_cache_status": group.get("delivery_cache_status", ""),
                        },
                        group_id=group_id,
                        previous_archive_status="archived",
                    ),
                )
            local_simulation.refresh_summary()
        return _data_center_group_result(group, changed_fields=changed_fields)

    def classify_data_center_group_photo(
        self,
        group_id: str,
        photo_id: str,
        category: str,
        *,
        actor: str,
        reason: str = "",
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        from app.services.barcode_maintenance_worker import _auto_archive_json_in_state
        from app.services.group_barcode_verification import evaluate_group_eligibility

        if category not in local_simulation.PHOTO_CATEGORIES:
            raise ValueError(f"Unsupported photo category: {category}")
        team_id = local_simulation.current_team_id()
        transaction = local_simulation.active_authoritative_json_write(team_id)
        owns_transaction = transaction is None
        token = None
        if owns_transaction:
            transaction = local_simulation.begin_authoritative_json_write(team_id)
            token = local_simulation.activate_authoritative_json_write(transaction)
        try:
            state = local_simulation.get_state()
            group = local_simulation.get_group(group_id)
            if group is None:
                raise KeyError(group_id)
            photo = next(
                (
                    item
                    for item in group.get("photos", [])
                    if str(item.get("id") or "") == photo_id and item.get("is_active", True) is not False
                ),
                None,
            )
            if photo is None:
                raise KeyError(photo_id)
            before = {
                "category": str(photo.get("category") or "unclassified"),
                "archive_status": str(photo.get("archive_status") or ""),
                "archive_filename": str(photo.get("archive_filename") or ""),
            }
            if photo.get("download_status") != "downloaded":
                has_previewable_source = bool(
                    str(photo.get("image_url") or "").strip()
                    or str(photo.get("storage_key") or "").strip()
                    or str(photo.get("storage_type") or "").strip() in {"oss", "local_upload", "external_url"}
                )
                if not has_previewable_source:
                    raise ValueError("Photo must have an image URL before classification")
                photo["download_status"] = "downloaded"
            category_label = local_simulation.PHOTO_CATEGORIES[category]
            now = local_simulation.now_iso()
            photo["category"] = category
            photo["category_label"] = category_label
            photo["classified_by"] = actor
            photo["classified_at"] = now
            photo["archive_status"] = "archived"
            photo["archive_filename"] = local_simulation.build_archive_filename(
                category_label,
                str(photo.get("image_url") or ""),
            )
            photo["archived_at"] = now
            photo.update(photo_barcode_check.check_photo_barcode(photo, group))
            after = {
                "category": str(photo.get("category") or ""),
                "archive_status": str(photo.get("archive_status") or ""),
                "archive_filename": str(photo.get("archive_filename") or ""),
            }
            state.setdefault("photo_events", []).append(
                {
                    "group_id": group_id,
                    "photo_id": photo_id,
                    "previous_category": before["category"],
                    "next_category": category,
                    "reviewer": actor,
                    "event": "data_center_photo_classified",
                    "created_at": now,
                }
            )
            local_simulation.append_audit_event(
                "data_center_photo_classified",
                actor,
                _data_center_audit_payload(
                    source_page=source_page,
                    actor=actor,
                    reason=reason or "data_center_photo_classified",
                    before=before,
                    after=after,
                    group_id=group_id,
                    photo_id=photo_id,
                    previous_category=before["category"],
                    next_category=category,
                ),
            )
            package_status = ""
            eligibility = evaluate_group_eligibility(group)
            verification = dict(group.get("barcode_verification") or {})
            fingerprint = str(verification.get("evidence_fingerprint") or "")
            current_fingerprint = str(eligibility.evidence_fingerprint or "")
            authoritative = (
                eligibility.status == "pending"
                and str(verification.get("status") or "") in {"passed", "manual_confirmed"}
                and (not fingerprint or fingerprint == current_fingerprint)
            )
            if authoritative:
                archive_result = _auto_archive_json_in_state(state, group_id, actor=actor)
                if archive_result.get("archived") or _data_center_archive_status(group) == "archived":
                    package_status = _json_request_data_center_delivery_package(group, actor=actor)
            else:
                archive_result = {"archived": False, "group_id": group_id, "reason": "not_authoritative_ready"}
                local_simulation.schedule_delivery_cache_build(group_id, reason="data_center_photo_classified")
            local_simulation.refresh_summary()
            if owns_transaction:
                local_simulation.finish_authoritative_json_write(transaction, token)
        except BaseException:
            if owns_transaction and transaction is not None and not transaction.closed:
                local_simulation.abort_authoritative_json_write(transaction, token)
            raise
        group = local_simulation.get_group(group_id)
        if group is None:
            raise KeyError(group_id)
        return _data_center_group_result(
            group,
            changed_fields=["photo.category"],
            delivery_package_job_status=package_status,
            archive_result=archive_result,
        )

    def rescan_data_center_group_photo_barcode(
        self,
        group_id: str,
        photo_id: str,
        *,
        actor: str,
        category: str = "",
        reason: str = "",
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        group = local_simulation.get_group(group_id)
        if group is None:
            raise KeyError(group_id)
        photo = next(
            (
                item
                for item in group.get("photos", [])
                if str(item.get("id") or "") == photo_id and item.get("is_active", True) is not False
            ),
            None,
        )
        if photo is None:
            raise KeyError(photo_id)
        now = local_simulation.now_iso()
        before = {
            "barcode_rescan_requested_at": str(photo.get("barcode_rescan_requested_at") or ""),
            "barcode_verification_status": str((group.get("barcode_verification") or {}).get("status") or ""),
        }
        local_simulation.invalidate_json_delivery_artifacts(
            group,
            actor=actor,
            reason="group_barcode_rescan_requested",
            verification_changed=True,
        )
        verification = dict(group.get("barcode_verification") or {})
        photo["barcode_rescan_requested_by"] = actor
        photo["barcode_rescan_requested_at"] = now
        if category:
            photo["category"] = category
        local_simulation.get_state().setdefault("photo_events", []).append(
            {
                "group_id": group_id,
                "photo_id": photo_id,
                "category": str(photo.get("category") or "unclassified"),
                "reviewer": actor,
                "event": "group_barcode_rescan_requested",
                "status": verification.get("status", "pending"),
                "created_at": now,
            }
        )
        after = {
            "barcode_rescan_requested_at": now,
            "barcode_verification_status": str((group.get("barcode_verification") or {}).get("status") or ""),
        }
        local_simulation.append_audit_event(
            "group_barcode_rescan_requested",
            actor,
            _data_center_audit_payload(
                source_page=source_page,
                actor=actor,
                reason=reason or "group_barcode_rescan_requested",
                before=before,
                after=after,
                group_id=group_id,
                photo_id=photo_id,
                status=after["barcode_verification_status"],
                should_enqueue=bool((group.get("barcode_verification") or {}).get("should_enqueue")),
            ),
        )
        local_simulation.refresh_summary()
        return photo

    def scan_data_center_group_photo_region(
        self,
        group_id: str,
        photo_id: str,
        *,
        barcode_type: str,
        region: Mapping[str, Any],
        actor: str,
        reason: str = "",
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        group = local_simulation.get_group(group_id)
        if group is None:
            raise KeyError(group_id)
        photo = next(
            (
                item
                for item in group.get("photos", [])
                if str(item.get("id") or "") == photo_id and item.get("is_active", True) is not False
            ),
            None,
        )
        if photo is None:
            raise KeyError(photo_id)
        return photo_barcode_check.scan_photo_region(photo, barcode_type, dict(region))

    def manual_confirm_group_barcode(
        self,
        group_id: str,
        *,
        actor: str,
        reason: str,
        source_page: str = "data_center",
        meter_no: str,
        module_asset_no: str,
        collector: str,
        photo_ids: list[str],
    ) -> dict[str, Any]:
        self.confirm_group_barcode_manually(
            group_id,
            actor=actor,
            meter_no=meter_no,
            module_asset_no=module_asset_no,
            collector=collector,
            reason=reason,
            photo_ids=photo_ids,
            require_claim=False,
        )
        _json_enrich_latest_audit_payload(
            "group_barcode_manual_confirmed",
            source_page=source_page,
            actor=actor,
            reason=reason,
        )
        from app.services.barcode_maintenance_worker import _auto_archive_json_in_state

        state = local_simulation.get_state()
        archive_result = _auto_archive_json_in_state(
            state,
            group_id,
            actor=actor,
        )
        group = local_simulation.get_group(group_id)
        if group is None:
            raise KeyError(group_id)
        package_status = ""
        if archive_result.get("archived") or _data_center_archive_status(group) == "archived":
            package_status = _json_request_data_center_delivery_package(group, actor=actor)
        return _data_center_group_result(
            group,
            delivery_package_job_status=package_status,
            archive_result=archive_result,
        )

    def return_data_center_group_to_exception_order(
        self,
        group_id: str,
        *,
        actor: str,
        category: str,
        note: str,
        reason: str = "",
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        before = deepcopy(local_simulation.get_group(group_id) or {})
        result = self.return_group_to_exception_order(
            group_id,
            actor=actor,
            category=category,
            note=note,
            force=True,
        )
        group = local_simulation.get_group(group_id)
        if group is None:
            raise KeyError(group_id)
        group["exception_status"] = "open"
        _json_enrich_latest_audit_payload(
            "group_returned_to_exception_order",
            source_page=source_page,
            actor=actor,
            reason=reason or note or "data_center_return_exception",
            before={
                "status": before.get("status", ""),
                "exception_status": before.get("exception_status", ""),
                "exception_note": before.get("exception_note", ""),
                "exception_reasons": before.get("exception_reasons", []),
                "has_archive_blocker": bool(before.get("has_archive_blocker")),
            },
            after={
                "status": group.get("status", ""),
                "exception_status": group.get("exception_status", ""),
                "exception_note": group.get("exception_note", ""),
                "exception_reasons": group.get("exception_reasons", []),
                "has_archive_blocker": bool(group.get("has_archive_blocker")),
            },
        )
        return result

    def finalize_unmatched_to_group(
        self,
        unmatched_id: str,
        *,
        actor: str,
        terminal: str,
        meter_no: str,
        candidate_key: str,
        expected_version: int,
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        _reject_placeholder_or_ambiguous_data_center_target(
            terminal=terminal,
            meter_no=meter_no,
            candidate_key=candidate_key,
        )
        result = self.finalize_unmatched_match(
            unmatched_id,
            actor=actor,
            candidate_key=candidate_key,
            expected_version=expected_version,
            source_page=source_page,
        )
        _json_enrich_latest_audit_payload(
            "unmatched_review_finalized",
            source_page=source_page,
            actor=actor,
            reason="data_center_unmatched_finalize",
        )
        return result

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

    def set_construction_task_priority(
        self,
        task_id: int,
        *,
        actor: str,
        priority: bool,
    ) -> dict[str, Any]:
        return local_simulation.set_construction_task_priority(task_id, actor=actor, priority=priority)

    def import_construction_priorities(self, rows: list[Any], *, actor: str, confirm: bool) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        transaction = local_simulation.active_authoritative_json_write(team_id)
        owns_transaction = transaction is None
        token = None
        if owns_transaction and confirm:
            transaction = local_simulation.begin_authoritative_json_write(team_id)
            token = local_simulation.activate_authoritative_json_write(transaction)
        try:
            state = local_simulation.get_state()
            groups_by_task: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for group in deepcopy(state.get("groups") or []):
                groups_by_task[int(group.get("task_id") or 0)].append(group)
            tasks: dict[str, dict[str, Any]] = {}
            for task in deepcopy(state.get("tasks") or []):
                metrics = local_simulation.calculate_task_metrics(groups_by_task.get(int(task.get("id") or 0), []))
                task["total_groups"] = metrics["renovation_count"]
                task.update(metrics)
                tasks[str(task.get("terminal") or "")] = task
            items = []
            for row in rows:
                item = {
                    "row_number": row.row_number,
                    "terminal": row.terminal,
                    "priority": row.priority,
                    "status": row.status,
                    "reason": row.message,
                }
                task = tasks.get(row.terminal)
                if item["status"] in {"conflict", "malformed", "duplicate"}:
                    items.append(item)
                    continue
                if task is None:
                    item["status"] = "unknown"
                else:
                    total = int(task.get("total_groups") or 0)
                    uploaded = int(task.get("uploaded_count") or 0)
                    if total <= 0 or uploaded >= total:
                        item["status"] = "completed"
                    elif bool(task.get("construction_priority")) == bool(row.priority):
                        item["status"] = "unchanged"
                    else:
                        item["task_id"] = task["id"]
                items.append(item)
            counts = {status: sum(1 for item in items if item["status"] == status) for status in ("valid", "duplicate", "conflict", "unknown", "completed", "unchanged", "malformed")}
            if not confirm:
                return {"counts": counts, "items": items, "confirmed": False}
            if counts["conflict"] or counts["malformed"]:
                raise ValueError("Priority import contains conflict or malformed rows")
            for item in items:
                if item["status"] == "valid":
                    local_simulation.set_construction_task_priority(item["task_id"], actor=actor, priority=bool(item["priority"]))
            local_simulation.append_audit_event("construction_priority_imported", actor, {"counts": counts})
        except BaseException:
            if owns_transaction:
                local_simulation.abort_authoritative_json_write(transaction, token)
            raise
        if owns_transaction:
            local_simulation.finish_authoritative_json_write(transaction, token)
        return {"counts": counts, "items": items, "confirmed": True}

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
        return self._authoritative_mutation(
            lambda: local_simulation.submit_construction_exception_order(
                order_id,
                actor=actor,
                updates=updates,
                note=note,
            )
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
        team_id = local_simulation.current_team_id()
        transaction = local_simulation.active_authoritative_json_write(team_id)
        owns_transaction = transaction is None
        token = None
        if owns_transaction:
            transaction = local_simulation.begin_authoritative_json_write(team_id)
            token = local_simulation.activate_authoritative_json_write(transaction)
        try:
            result = local_simulation.review_group(group_id, status, reviewer, note, exception_note)
            if owns_transaction:
                local_simulation.finish_authoritative_json_write(transaction, token)
        except BaseException:
            if owns_transaction:
                local_simulation.abort_authoritative_json_write(transaction, token)
            raise
        return result

    def classify_photo(self, group_id: str, photo_id: str, category: str, reviewer: str) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        transaction = local_simulation.active_authoritative_json_write(team_id)
        owns_transaction = transaction is None
        token = None
        if owns_transaction:
            transaction = local_simulation.begin_authoritative_json_write(team_id)
            token = local_simulation.activate_authoritative_json_write(transaction)
        try:
            result = local_simulation.classify_photo(group_id, photo_id, category, reviewer)
            if owns_transaction:
                local_simulation.finish_authoritative_json_write(transaction, token)
        except BaseException:
            if owns_transaction and transaction is not None and not transaction.closed:
                local_simulation.abort_authoritative_json_write(transaction, token)
            raise
        return result

    def rescan_photo_barcode(
        self,
        group_id: str,
        photo_id: str,
        reviewer: str,
        category: str = "",
    ) -> dict[str, Any]:
        return local_simulation.rescan_photo_barcode(group_id, photo_id, reviewer, category)

    def apply_group_scan_result(
        self,
        group_id: str,
        result: Any,
        *,
        claimed_evidence_fingerprint: str,
        claimed_evidence_version: int,
        lease_owner: str,
        lease_token: str,
        actor: str,
    ) -> dict[str, Any]:
        from app.services.group_barcode_verification import apply_group_scan_result, mark_auto_archive_pending

        team_id = local_simulation.current_team_id()
        transaction = local_simulation.active_authoritative_json_write(team_id)
        owns_transaction = transaction is None
        token = None
        if owns_transaction:
            transaction = local_simulation.begin_authoritative_json_write(team_id)
            token = local_simulation.activate_authoritative_json_write(transaction)
        try:
            group = local_simulation.get_group(group_id)
            if group is None:
                raise KeyError(group_id)
            current = dict(group.get("barcode_verification") or {})
            applied = apply_group_scan_result(
                current,
                group,
                result,
                claimed_evidence_fingerprint=claimed_evidence_fingerprint,
                claimed_evidence_version=claimed_evidence_version,
                lease_owner=lease_owner,
                lease_token=lease_token,
                actor=actor,
            )
            next_verification = dict(applied["verification"])
            if applied["applied"]:
                scan_result = next_verification.get("result") or {}
                matched_fields = set(scan_result.get("matched_fields") or [])
                next_verification.update(
                    {
                        "meter_matched": "meter" in matched_fields,
                        "module_matched": "module" in matched_fields,
                        "collector_matched": "collector" in matched_fields,
                        "recognition_source": (
                            "machine_qr"
                            if scan_result.get("machine_qr_values") and not scan_result.get("machine_barcode_values")
                            else "machine_barcode"
                            if scan_result.get("machine_barcode_values") or scan_result.get("machine_qr_values")
                            else "ocr_candidate"
                            if scan_result.get("ocr_candidates")
                            else "none"
                        ),
                    }
                )
                next_verification = mark_auto_archive_pending(next_verification)
                applied["verification"] = next_verification
            if next_verification != current:
                group["barcode_verification"] = next_verification
                local_simulation.append_audit_event(
                    "group_barcode_scan_result_applied" if applied["applied"] else "group_barcode_scan_result_rejected",
                    actor,
                    {
                        "group_id": group_id,
                        "before": local_simulation._manual_confirmation_audit_snapshot(group, current),
                        "after": local_simulation._manual_confirmation_audit_snapshot(group, next_verification),
                    },
                )
                local_simulation.refresh_summary()
        except BaseException:
            if owns_transaction:
                local_simulation.abort_authoritative_json_write(transaction, token)
            raise
        if owns_transaction:
            local_simulation.finish_authoritative_json_write(transaction, token)
        return applied

    def confirm_group_barcode_manually(
        self,
        group_id: str,
        *,
        actor: str,
        meter_no: str,
        module_asset_no: str,
        collector: str,
        reason: str,
        photo_ids: list[str],
        source_page: str = "",
        require_claim: bool = True,
    ) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        transaction = local_simulation.active_authoritative_json_write(team_id)
        owns_transaction = transaction is None
        token = None
        if owns_transaction:
            transaction = local_simulation.begin_authoritative_json_write(team_id)
            token = local_simulation.activate_authoritative_json_write(transaction)
        try:
            result = local_simulation.confirm_group_barcode_manually(
                group_id,
                actor=actor,
                meter_no=meter_no,
                module_asset_no=module_asset_no,
                collector=collector,
                reason=reason,
                photo_ids=photo_ids,
                require_claim=require_claim,
            )
        except BaseException:
            if owns_transaction:
                local_simulation.abort_authoritative_json_write(transaction, token)
            raise
        if owns_transaction:
            local_simulation.finish_authoritative_json_write(transaction, token)
        return result

    def delete_photo(self, group_id: str, photo_id: str, reviewer: str) -> dict[str, Any]:
        return local_simulation.delete_group_photo(group_id, photo_id, reviewer)

    def delete_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int = 1,
        reason: str = "",
    ) -> dict[str, Any]:
        return local_simulation.delete_unmatched_record(
            unmatched_id,
            actor=actor,
            expected_version=expected_version,
            reason=reason,
        )

    def associate_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int = 1,
        target_group_id: str = "",
        target_meter_no: str = "",
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return local_simulation.associate_unmatched_record(
            unmatched_id,
            actor=actor,
            expected_version=expected_version,
            target_group_id=target_group_id,
            target_meter_no=target_meter_no,
            updates=updates,
        )

    def create_group_from_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int = 1,
        terminal: str = "",
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return local_simulation.create_group_from_unmatched_record(
            unmatched_id,
            actor=actor,
            expected_version=expected_version,
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
        team_id = local_simulation.current_team_id()
        transaction = local_simulation.active_authoritative_json_write(team_id)
        owns_transaction = transaction is None
        token = None
        if owns_transaction:
            transaction = local_simulation.begin_authoritative_json_write(team_id)
            token = local_simulation.activate_authoritative_json_write(transaction)
        try:
            result = local_simulation.upload_construction_group_batch(
                group_id,
                actor=actor,
                client_batch_id=client_batch_id,
                collector=collector,
                module_asset_no=module_asset_no,
                photos=photos,
                creator=creator,
                client_completed_at=client_completed_at,
            )
        except BaseException:
            if owns_transaction:
                local_simulation.abort_authoritative_json_write(transaction, token)
            raise
        if owns_transaction:
            local_simulation.finish_authoritative_json_write(transaction, token)
        return result

    def build_task_detail_export(self, task_id: int) -> bytes:
        return local_simulation.build_task_detail_export(task_id)

    def request_final_delivery_export(
        self,
        *,
        task_id: int | None = None,
        terminal: str = "",
        review_scope: str = "reviewed",
        requested_by: str = "",
    ) -> LeasedDeliveryPackage:
        from app.services.delivery_package_queue import request_json_delivery_package

        groups = local_simulation.filter_delivery_groups(
            task_id=task_id,
            terminal=terminal,
            review_scope="all",
        )
        return request_json_delivery_package(
            groups=groups,
            task_id=task_id,
            terminal=terminal,
            review_scope=review_scope,
            requested_by=requested_by,
        )

    def build_final_delivery_export(
        self,
        *,
        task_id: int | None = None,
        terminal: str = "",
        review_scope: str = "reviewed",
    ) -> LeasedDeliveryPackage:
        return local_simulation.build_final_delivery_export(
            task_id=task_id,
            terminal=terminal,
            review_scope=review_scope,
            repair_delivery_cache=self._repair_delivery_cache_groups,
        )

    def _repair_delivery_cache_groups(self, group_ids: list[str], *, reason: str) -> None:
        for group_id in group_ids:
            local_simulation.schedule_delivery_cache_build(group_id, reason=reason)

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
        source_page: str = "",
    ) -> dict[str, Any]:
        result = self._authoritative_mutation(
            lambda: local_simulation.reset_group_to_unconstructed(
                group_id,
                actor=actor,
                reason=reason,
                force=force,
            )
        )
        if source_page:
            _json_enrich_latest_audit_payload(
                "group_reset_to_unconstructed",
                source_page=source_page,
                actor=actor,
                reason=reason or "reset_to_unconstructed",
            )
        return result

    def reset_group_to_unreviewed(
        self,
        group_id: str,
        *,
        actor: str,
        reason: str = "",
        force: bool = False,
        source_page: str = "",
    ) -> dict[str, Any]:
        result = self._authoritative_mutation(
            lambda: local_simulation.reset_group_to_unreviewed(
                group_id,
                actor=actor,
                reason=reason,
                force=force,
            )
        )
        if source_page:
            _json_enrich_latest_audit_payload(
                "admin_group_reset_unreviewed",
                source_page=source_page,
                actor=actor,
                reason=reason or "reset_to_unreviewed",
            )
        return result

    def bulk_archive_groups(self, group_ids: list[str], *, actor: str, reason: str = "") -> dict[str, Any]:
        return self._authoritative_mutation(
            lambda: local_simulation.bulk_archive_groups(group_ids, actor=actor, reason=reason)
        )

    def return_group_to_exception_order(
        self,
        group_id: str,
        *,
        actor: str,
        category: str,
        note: str,
        force: bool = False,
    ) -> dict[str, Any]:
        return self._authoritative_mutation(
            lambda: local_simulation.return_group_to_exception_order(
                group_id,
                actor=actor,
                category=category,
                note=note,
                force=force,
            )
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
                .where(
                    Photo.team_id == team_id,
                    Photo.is_active.is_(True),
                    Photo.upload_status != PhotoUploadStatus.INVALID,
                    Photo.group_id.is_not(None),
                )
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
                    GroupBarcodeVerification.status.label("verification_status"),
                    GroupBarcodeVerification.evidence_fingerprint.label("verification_evidence_fingerprint"),
                    GroupBarcodeVerification.evidence_version.label("verification_evidence_version"),
                    GroupBarcodeVerification.meter_matched.label("verification_meter_matched"),
                    GroupBarcodeVerification.module_matched.label("verification_module_matched"),
                    GroupBarcodeVerification.collector_matched.label("verification_collector_matched"),
                    GroupBarcodeVerification.recognition_source.label("verification_recognition_source"),
                    GroupBarcodeVerification.attempt_count.label("verification_attempt_count"),
                    GroupBarcodeVerification.invalidation_reason.label("verification_invalidation_reason"),
                    GroupBarcodeVerification.invalidated_by.label("verification_invalidated_by"),
                    GroupBarcodeVerification.invalidated_at.label("verification_invalidated_at"),
                    GroupBarcodeVerification.auto_archive_status.label("verification_auto_archive_status"),
                    GroupBarcodeVerification.auto_archived_at.label("verification_auto_archived_at"),
                    GroupBarcodeVerification.auto_archive_error.label("verification_auto_archive_error"),
                    GroupBarcodeVerification.updated_at.label("verification_updated_at"),
                )
                .join(active_photo_counts, active_photo_counts.c.group_id == MaterialGroup.id)
                .outerjoin(
                    GroupBarcodeVerification,
                    and_(
                        GroupBarcodeVerification.team_id == MaterialGroup.team_id,
                        GroupBarcodeVerification.group_id == MaterialGroup.id,
                    ),
                )
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
                        Photo.sha256,
                        Photo.is_active,
                        Photo.upload_status,
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
        installer_items = sorted(installer_group_ids.items(), key=lambda item: (-len(item[1]), item[0]))
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

    def _data_center_source(self, team_id: str, query: DataCenterQuery):
        required_categories = sorted(data_center_service.REQUIRED_CLASSIFICATION_SLOTS)
        active_photo_stats = (
            select(
                Photo.group_id.label("group_id"),
                func.count(Photo.id).label("active_photo_count"),
                func.coalesce(func.sum(case((Photo.archive_status == "archived", 1), else_=0)), 0).label(
                    "archived_photo_count"
                ),
                func.coalesce(
                    func.sum(case((func.nullif(func.trim(Photo.archive_status), "").is_not(None), 1), else_=0)),
                    0,
                ).label("archive_state_count"),
                func.count(
                    func.distinct(case((Photo.category.in_(required_categories), Photo.category), else_=None))
                ).label("required_category_count"),
            )
            .where(
                Photo.team_id == team_id,
                Photo.is_active.is_(True),
                Photo.upload_status != PhotoUploadStatus.INVALID,
                Photo.group_id.is_not(None),
            )
            .group_by(Photo.group_id)
            .subquery()
        )
        group_photo_count = func.coalesce(active_photo_stats.c.active_photo_count, 0)
        group_raw = MaterialGroup.raw_data
        group_installer = func.coalesce(
            func.nullif(func.trim(group_raw.op("->>")("installer")), ""),
            func.nullif(func.trim(group_raw.op("->>")("constructor")), ""),
            func.nullif(func.trim(group_raw.op("->>")("creator")), ""),
            func.nullif(func.trim(Task.construction_claimed_by), ""),
            literal(""),
        )
        group_barcode_status = case(
            (GroupBarcodeVerification.status == "passed", literal("passed")),
            (GroupBarcodeVerification.status == "manual_confirmed", literal("manual")),
            (GroupBarcodeVerification.status.in_(["mismatch", "partial", "failed"]), literal("mismatched")),
            (GroupBarcodeVerification.status == "unreadable", literal("unreadable")),
            else_=literal("ineligible"),
        )
        group_construction_status = case(
            (group_photo_count <= 0, literal("unconstructed")),
            (MaterialGroup.status.in_([GroupStatus.APPROVED, GroupStatus.REJECTED]), literal("completed")),
            else_=literal("in_progress"),
        )
        group_classification_status = case(
            (
                func.coalesce(active_photo_stats.c.required_category_count, 0) == len(required_categories),
                literal("complete"),
            ),
            else_=literal("incomplete"),
        )
        group_archive_status = case(
            (
                and_(
                    group_photo_count > 0,
                    func.coalesce(active_photo_stats.c.archived_photo_count, 0) == group_photo_count,
                ),
                literal("archived"),
            ),
            (func.coalesce(active_photo_stats.c.archive_state_count, 0) > 0, literal("pending")),
            else_=literal("unarchived"),
        )
        group_select = (
            select(
                literal("group").label("kind"),
                MaterialGroup.legacy_id.label("legacy_id"),
                MaterialGroup.terminal.label("terminal"),
                MaterialGroup.display_meter_no.label("meter_no"),
                MaterialGroup.meter_match_key.label("meter_match_key"),
                MaterialGroup.installation_address.label("address"),
                group_raw.op("->>")("collector").label("collector"),
                func.coalesce(group_raw.op("->>")("module_asset_no"), group_raw.op("->>")("asset_no")).label(
                    "module_asset_no"
                ),
                group_raw.op("->>")("construction_collector").label("construction_collector"),
                group_raw.op("->>")("construction_module_asset_no").label("construction_module_asset_no"),
                group_installer.label("installer"),
                group_photo_count.label("photo_count"),
                group_classification_status.label("classification_status"),
                group_construction_status.label("construction_status"),
                group_archive_status.label("archive_status"),
                group_barcode_status.label("barcode_status"),
                func.coalesce(
                    func.nullif(func.trim(MaterialGroup.exception_status), ""),
                    case((MaterialGroup.status == GroupStatus.REJECTED, literal("open")), else_=literal("")),
                ).label("exception_status"),
                MaterialGroup.updated_at.label("updated_at"),
                MaterialGroup.raw_data.label("raw_data"),
            )
            .select_from(MaterialGroup)
            .outerjoin(active_photo_stats, active_photo_stats.c.group_id == MaterialGroup.id)
            .outerjoin(Task, and_(Task.team_id == MaterialGroup.team_id, Task.id == MaterialGroup.task_id))
            .outerjoin(
                GroupBarcodeVerification,
                and_(
                    GroupBarcodeVerification.team_id == MaterialGroup.team_id,
                    GroupBarcodeVerification.group_id == MaterialGroup.id,
                ),
            )
            .where(MaterialGroup.team_id == team_id)
        )

        unmatched_payload = UnmatchedRecord.payload
        unmatched_select = select(
            literal("unmatched").label("kind"),
            UnmatchedRecord.legacy_id.label("legacy_id"),
            UnmatchedRecord.terminal.label("terminal"),
            UnmatchedRecord.meter_no.label("meter_no"),
            UnmatchedRecord.meter_match_key.label("meter_match_key"),
            UnmatchedRecord.address.label("address"),
            UnmatchedRecord.collector.label("collector"),
            UnmatchedRecord.module_asset_no.label("module_asset_no"),
            literal("").label("construction_collector"),
            literal("").label("construction_module_asset_no"),
            func.coalesce(
                unmatched_payload.op("->>")("assigned_to"),
                unmatched_payload.op("->>")("creator"),
                literal(""),
            ).label("installer"),
            literal(0).label("photo_count"),
            literal("incomplete").label("classification_status"),
            case(
                (
                    func.nullif(func.trim(unmatched_payload.op("->>")("assigned_to")), "").is_not(None),
                    literal("in_progress"),
                ),
                else_=literal("unconstructed"),
            ).label("construction_status"),
            literal("unarchived").label("archive_status"),
            literal("ineligible").label("barcode_status"),
            UnmatchedRecord.status.label("exception_status"),
            UnmatchedRecord.updated_at.label("updated_at"),
            UnmatchedRecord.payload.label("raw_data"),
        ).where(UnmatchedRecord.team_id == team_id)

        if query.data_type == "group":
            return group_select.subquery("data_center_rows")
        if query.data_type == "unmatched":
            return unmatched_select.subquery("data_center_rows")
        return union_all(group_select, unmatched_select).subquery("data_center_rows")

    def _data_center_filtered_source(self, team_id: str, query: DataCenterQuery):
        source = self._data_center_source(team_id, query)
        filters = []
        if query.construction_status != "all":
            filters.append(source.c.construction_status == query.construction_status)
        if query.archive_status != "all":
            filters.append(source.c.archive_status == query.archive_status)
        if query.barcode_status != "all":
            filters.append(source.c.barcode_status == query.barcode_status)
        if query.classification_status != "all":
            filters.append(source.c.classification_status == query.classification_status)
        requested_exception = query.exception_status.strip()
        if requested_exception == "none":
            filters.append(source.c.exception_status == "")
        elif requested_exception:
            filters.append(source.c.exception_status == requested_exception)
        if query.installer.strip():
            filters.append(func.lower(source.c.installer).like(f"%{query.installer.strip().lower()}%"))
        if query.terminal.strip():
            filters.append(func.lower(source.c.terminal).like(f"%{query.terminal.strip().lower()}%"))
        if query.query.strip():
            keyword = f"%{query.query.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(source.c.legacy_id).like(keyword),
                    func.lower(source.c.terminal).like(keyword),
                    func.lower(source.c.meter_no).like(keyword),
                    func.lower(source.c.meter_match_key).like(keyword),
                    func.lower(source.c.address).like(keyword),
                    func.lower(source.c.collector).like(keyword),
                    func.lower(source.c.module_asset_no).like(keyword),
                    func.lower(source.c.installer).like(keyword),
                )
            )
        start, end = data_center_service.date_bounds(query)
        if start is not None:
            filters.append(source.c.updated_at >= start)
        if end is not None:
            filters.append(source.c.updated_at <= end)
        return source, filters

    @staticmethod
    def _data_center_order(source, sort: str):
        if sort == "updated_asc":
            return (source.c.updated_at.asc().nulls_last(), source.c.legacy_id.asc())
        if sort == "terminal_asc":
            return (source.c.terminal.asc(), source.c.legacy_id.asc())
        return (source.c.updated_at.desc().nulls_last(), source.c.legacy_id.desc())

    @staticmethod
    def _data_center_row_from_mapping(row: Mapping[str, Any]) -> dict[str, Any]:
        raw = dict(row.get("raw_data") or {})
        base = {
            "id": row.get("legacy_id") or "",
            "terminal": row.get("terminal") or "",
            "meter_no": row.get("meter_no") or "",
            "meter_match_key": row.get("meter_match_key") or "",
            "address": row.get("address") or "",
            "collector": row.get("collector") or "",
            "module_asset_no": row.get("module_asset_no") or "",
            "construction_collector": row.get("construction_collector") or "",
            "construction_module_asset_no": row.get("construction_module_asset_no") or "",
            "installer": row.get("installer") or "",
            "photo_count": int(row.get("photo_count") or 0),
            "classification_status": row.get("classification_status") or "incomplete",
            "classification_progress": {"status": row.get("classification_status") or "incomplete"},
            "construction_status": row.get("construction_status") or "unconstructed",
            "archive_status": row.get("archive_status") or "unarchived",
            "barcode_status": row.get("barcode_status") or "ineligible",
            "exception_status": row.get("exception_status") or "",
            "updated_at": row.get("updated_at"),
        }
        if row.get("kind") == "unmatched":
            return data_center_service.unmatched_row({**raw, **base, "unmatched_id": base["id"]})
        mapped = data_center_service.group_row({**raw, **base})
        mapped["classification_status"] = base["classification_status"]
        mapped["classification_progress"] = {"status": base["classification_status"]}
        mapped["archive_status"] = base["archive_status"]
        mapped["barcode_status"] = base["barcode_status"]
        mapped["barcode_progress"] = {"status": base["barcode_status"]}
        return mapped

    def list_data_center_rows(self, query: DataCenterQuery) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        offset = (query.page - 1) * query.page_size
        with self._session() as session:
            source, filters = self._data_center_filtered_source(team_id, query)
            count_statement = select(func.count()).select_from(source).where(*filters)
            total = int(session.scalar(count_statement) or 0)
            row_statement = (
                select(source)
                .where(*filters)
                .order_by(*self._data_center_order(source, query.sort))
                .limit(query.page_size)
                .offset(offset)
            )
            rows = session.execute(row_statement).all()
        return {
            "total": total,
            "page": query.page,
            "page_size": query.page_size,
            "items": [self._data_center_row_from_mapping(dict(getattr(row, "_mapping", row))) for row in rows],
        }

    def get_data_center_detail(self, *, kind: str, item_id: str) -> dict[str, Any] | None:
        team_id = local_simulation.current_team_id()
        with self._session() as session:
            if kind == "group":
                group = session.scalar(
                    select(MaterialGroup).where(MaterialGroup.team_id == team_id, MaterialGroup.legacy_id == item_id)
                )
                if group is None:
                    return None
                base_payload = _group_payload(session, group, include_photos=False)
                photo_rows = [
                    photo
                    for photo in session.scalars(
                        select(Photo)
                        .where(
                            Photo.team_id == team_id,
                            Photo.group_id == group.id,
                            Photo.is_active.is_(True),
                            Photo.upload_status != PhotoUploadStatus.INVALID,
                        )
                        .order_by(Photo.sort_order, Photo.created_at, Photo.legacy_id)
                    ).all()
                    if _status_value(getattr(photo, "upload_status", "")) != PhotoUploadStatus.INVALID.value
                ]
                photos = [_photo_payload(photo) for photo in photo_rows]
                detail = data_center_service.group_row({**base_payload, "photos": photos, "photo_count": len(photos)})
                detail["photos"] = photos
                detail["audit"] = [
                    {
                        "actor": audit.actor_username or "",
                        "action": audit.action,
                        "entity_type": audit.entity_type,
                        "created_at": audit.created_at.isoformat() if audit.created_at else "",
                        "payload": audit.payload or {},
                    }
                    for audit in session.scalars(
                        select(AuditLog)
                        .where(
                            AuditLog.team_id == team_id,
                            or_(
                                AuditLog.entity_id == group.id,
                                AuditLog.legacy_id == item_id,
                            ),
                        )
                        .order_by(AuditLog.created_at.desc())
                    ).all()
                ]
                return detail
            if kind == "unmatched":
                record = session.scalar(
                    select(UnmatchedRecord).where(
                        UnmatchedRecord.team_id == team_id,
                        UnmatchedRecord.legacy_id == item_id,
                    )
                )
                if record is None:
                    return None
                payload = _unmatched_payload(record)
                detail = data_center_service.unmatched_row(payload)
                detail["photos"] = payload.get("photo_urls") or []
                detail["audit"] = [
                    {
                        "actor": audit.actor_username or "",
                        "action": audit.action,
                        "entity_type": audit.entity_type,
                        "created_at": audit.created_at.isoformat() if audit.created_at else "",
                        "payload": audit.payload or {},
                    }
                    for audit in session.scalars(
                        select(AuditLog)
                        .where(AuditLog.team_id == team_id, AuditLog.legacy_id == item_id)
                        .order_by(AuditLog.created_at.desc())
                    ).all()
                ]
                return detail
        return None

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

    def _task_stats_map(
        self,
        session: Session,
        team_id: str,
        *,
        include_search_text: bool = True,
        include_installer_distribution: bool = True,
        legacy_task_id: int | None = None,
    ) -> dict[int, dict[str, Any]]:
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
        group_filters = [MaterialGroup.team_id == team_id]
        if legacy_task_id is not None:
            group_filters.append(MaterialGroup.legacy_task_id == legacy_task_id)
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
                    func.sum(
                        case(
                            (
                                and_(
                                    MaterialGroup.status == GroupStatus.UNREVIEWED,
                                    uploaded_group_condition,
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("unreviewed_count"),
            )
            .where(*group_filters)
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
        if not include_installer_distribution:
            return stats_by_task
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
                *group_filters,
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
                Photo.group_id.in_(select(MaterialGroup.id).where(*group_filters)),
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
                *group_filters,
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

    def _task_payload_stats(self, session: Session, task: Task) -> dict[str, Any]:
        if task.legacy_id is None:
            return _empty_task_stats()
        task_id = int(task.legacy_id)
        return self._task_stats_map(
            session,
            task.team_id or local_simulation.current_team_id(),
            legacy_task_id=task_id,
        ).get(task_id, _empty_task_stats())

    def _construction_priority_stats_map(
        self,
        session: Session,
        team_id: str,
        legacy_task_ids: list[int],
    ) -> dict[int, dict[str, int]]:
        task_ids = sorted({int(task_id) for task_id in legacy_task_ids})
        stats_by_task = {task_id: _empty_task_stats() for task_id in task_ids}
        if not task_ids:
            return stats_by_task
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
        rows = session.execute(
            select(
                MaterialGroup.legacy_task_id,
                func.count(MaterialGroup.id).label("total_groups"),
                func.coalesce(func.sum(case((uploaded_group_condition, 1), else_=0)), 0).label("uploaded_count"),
                func.coalesce(
                    func.sum(case((MaterialGroup.status == GroupStatus.APPROVED, 1), else_=0)),
                    0,
                ).label("reviewed_count"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    MaterialGroup.status == GroupStatus.UNREVIEWED,
                                    uploaded_group_condition,
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("unreviewed_count"),
            )
            .where(
                MaterialGroup.team_id == team_id,
                MaterialGroup.legacy_task_id.in_(task_ids),
            )
            .group_by(MaterialGroup.legacy_task_id)
        ).all()
        for row in rows:
            if row.legacy_task_id is None:
                continue
            stats_by_task[int(row.legacy_task_id)] = {
                "total_groups": int(row.total_groups or 0),
                "uploaded_count": int(row.uploaded_count or 0),
                "reviewed_count": int(row.reviewed_count or 0),
                "unreviewed_count": int(row.unreviewed_count or 0),
            }
        return stats_by_task

    def _task_stats(self, session: Session, task: Task) -> dict[str, Any]:
        if task.legacy_id is None:
            return _empty_task_stats()
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
        row = session.execute(
            select(
                func.count(MaterialGroup.id).label("total_groups"),
                func.coalesce(func.sum(case((uploaded_group_condition, 1), else_=0)), 0).label("uploaded_count"),
                func.coalesce(
                    func.sum(case((MaterialGroup.status == GroupStatus.APPROVED, 1), else_=0)),
                    0,
                ).label("reviewed_count"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    MaterialGroup.status == GroupStatus.UNREVIEWED,
                                    uploaded_group_condition,
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("unreviewed_count"),
            ).where(
                MaterialGroup.team_id == (task.team_id or local_simulation.current_team_id()),
                MaterialGroup.legacy_task_id == int(task.legacy_id),
            )
        ).one()
        return {
            "total_groups": int(row.total_groups or 0),
            "uploaded_count": int(row.uploaded_count or 0),
            "reviewed_count": int(row.reviewed_count or 0),
            "unreviewed_count": int(row.unreviewed_count or 0),
        }

    def list_tasks(
        self,
        *,
        summary_only: bool = False,
        include_installer_distribution: bool = True,
    ) -> list[dict[str, Any]]:
        with self._session() as session:
            team_id = local_simulation.current_team_id()
            tasks = session.scalars(
                select(Task)
                .where(Task.team_id == team_id)
                .order_by(Task.terminal, Task.legacy_id)
            ).all()
            stats_by_task = self._task_stats_map(
                session,
                team_id,
                include_search_text=not summary_only,
                include_installer_distribution=include_installer_distribution,
            )
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
                    Task.construction_priority,
                )
                .where(Task.team_id == team_id)
                .order_by(Task.terminal, Task.legacy_id)
            ).all()
            stats_by_task = self._task_stats_map(
                session,
                team_id,
                include_search_text=False,
                include_installer_distribution=False,
            )
            task_rows = []
            for row in task_rows_raw:
                stats = stats_by_task.get(int(row.legacy_id or 0), _empty_task_stats())
                construction_available, _ = construction_task_availability(stats)
                task_rows.append(
                    {
                        "id": row.legacy_id if row.legacy_id is not None else str(row.id),
                        "terminal": row.terminal or "",
                        "claimed_by": row.review_claimed_by or "",
                        "construction_assigned_to": row.construction_claimed_by or "",
                        "construction_priority": bool(
                            row.construction_priority and construction_available
                        ),
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
        aliases = local_simulation.installer_actor_aliases(target)
        with self._session() as session:
            team_id = local_simulation.current_team_id()
            rows = session.execute(
                select(Photo, MaterialGroup)
                .join(MaterialGroup, Photo.group_id == MaterialGroup.id)
                .where(
                    Photo.team_id == team_id,
                    Photo.is_active.is_(True),
                    Photo.creator.in_(tuple(aliases)),
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
        from app.services.delivery_cache import invalidate_postgres_delivery_cache_for_group_change

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
                invalidate_verification_for_group(
                    session,
                    group,
                    actor="system",
                    reason="clear_scan_data",
                )
                invalidate_postgres_delivery_cache_for_group_change(
                    session,
                    group,
                    actor="system",
                    reason="clear_scan_data",
                )
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
            return {"total": len(groups), "items": _group_payloads(session, page, include_photos=True)}

    def list_photo_barcode_review_groups(
        self,
        *,
        status: str = "unreadable",
        query: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        capped_limit = max(1, min(int(limit or 100), 100000))
        safe_offset = max(0, int(offset or 0))
        normalized_status = str(status or "unreadable").strip().lower()
        if normalized_status in {"matched", "passed", "success"}:
            durable_statuses = PASS_STATUSES
        elif normalized_status == "all":
            durable_statuses = TERMINAL_STATUSES
        elif normalized_status in {"mismatched", "failed", "review"}:
            durable_statuses = EXCEPTION_STATUSES
        else:
            durable_statuses = frozenset({"unreadable"})

        valid_photo_counts = _eligible_group_photo_set_subquery(team_id)
        resolved_verification_status = _postgres_review_verification_status_expression()
        statement = (
            select(MaterialGroup)
            .join(valid_photo_counts, valid_photo_counts.c.group_id == MaterialGroup.id)
            .outerjoin(
                GroupBarcodeVerification,
                and_(
                    GroupBarcodeVerification.team_id == MaterialGroup.team_id,
                    GroupBarcodeVerification.group_id == MaterialGroup.id,
                ),
            )
            .where(
                MaterialGroup.team_id == team_id,
                resolved_verification_status.in_(durable_statuses),
            )
        )
        for term in [item for item in re.split(r"\s+", query.strip()) if item]:
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
                        cast(Photo.raw_data, String).ilike(pattern),
                    ),
                )
                .exists()
            )
            statement = statement.where(
                or_(
                    MaterialGroup.legacy_id.ilike(pattern),
                    MaterialGroup.terminal.ilike(pattern),
                    MaterialGroup.display_meter_no.ilike(pattern),
                    MaterialGroup.installation_address.ilike(pattern),
                    cast(MaterialGroup.raw_data, String).ilike(pattern),
                    resolved_verification_status.ilike(pattern),
                    GroupBarcodeVerification.recognition_source.ilike(pattern),
                    photo_match,
                )
            )

        with self._session() as session:
            total = int(session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
            groups = list(
                session.scalars(
                    statement.order_by(
                        MaterialGroup.terminal,
                        MaterialGroup.display_meter_no,
                        MaterialGroup.legacy_id,
                        MaterialGroup.id,
                    )
                    .offset(safe_offset)
                    .limit(capped_limit)
                ).all()
            )
            group_ids = [group.id for group in groups]
            verification_rows = []
            photos = []
            if group_ids:
                verification_rows = list(
                    session.scalars(
                        select(GroupBarcodeVerification).where(
                            GroupBarcodeVerification.team_id == team_id,
                            GroupBarcodeVerification.group_id.in_(group_ids),
                        )
                    ).all()
                )
                photos = list(session.scalars(
                    select(Photo)
                    .where(
                        Photo.team_id == team_id,
                        Photo.is_active.is_(True),
                        Photo.group_id.in_(group_ids),
                    )
                    .order_by(Photo.group_id, Photo.sort_order, Photo.created_at, Photo.legacy_id)
                ).all()
                )
        photos_by_group_id: dict[str, list[Any]] = defaultdict(list)
        for photo in photos:
            photos_by_group_id[str(photo.group_id)].append(photo)
        verification_by_group_id = {str(row.group_id): row for row in verification_rows}
        payloads = []
        for group in groups:
            payload = _group_barcode_payload(group, photos_by_group_id.get(str(group.id), []))
            durable_verification = resolve_persisted_barcode_verification(
                verification_by_group_id.get(str(group.id)),
                group.raw_data or {},
                payload.get("photos") or [],
            )
            if durable_verification:
                payload["barcode_verification"] = durable_verification
                payload.update(verification_compatibility_fields(durable_verification))
            payloads.append(payload)
        items = photo_barcode_check.list_group_barcode_review_items(
            payloads,
            statuses=_group_barcode_review_statuses("all"),
        )
        return {
            "total": total,
            "limit": capped_limit,
            "offset": safe_offset,
            "page": (safe_offset // capped_limit) + 1,
            "page_size": capped_limit,
            "items": items,
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
            payloads = _group_payloads(session, list(groups), include_photos=True)
            return {
                "total": int(total),
                "terminals": [str(item) for item in terminal_rows],
                "items": [
                    _group_target_summary(payload, include_photos=True)
                    for payload in payloads
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
            group_payloads = _group_payloads(session, groups, include_photos=not summary_only)
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
                            Photo.upload_status,
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

    def list_review_task_groups(
        self,
        task_id: int,
        *,
        limit: int = 20,
        offset: int = 0,
        review_status: str = "all",
        query: str = "",
    ) -> dict[str, Any]:
        if review_status not in local_simulation.REVIEW_QUEUE_STATUSES:
            raise ValueError("Unsupported review status")
        if not 1 <= int(limit) <= 20:
            raise ValueError("Review queue limit must be between 1 and 20")
        if int(offset) < 0:
            raise ValueError("Review queue offset must be non-negative")
        with self._session() as session:
            self._task_by_legacy_id(session, task_id)
            team_id = local_simulation.current_team_id()
            queue_status = _review_queue_status_expression()
            filters = [
                MaterialGroup.team_id == team_id,
                MaterialGroup.legacy_task_id == task_id,
                *_review_queue_search_conditions(team_id, query),
            ]
            status_rows = select(queue_status.label("queue_status")).where(*filters).subquery()
            counts = session.execute(
                select(
                    func.count().label("all_count"),
                    func.coalesce(
                        func.sum(case((status_rows.c.queue_status == "reviewable", 1), else_=0)),
                        0,
                    ).label("reviewable_count"),
                    func.coalesce(
                        func.sum(case((status_rows.c.queue_status == "exception", 1), else_=0)),
                        0,
                    ).label("exception_count"),
                    func.coalesce(
                        func.sum(case((status_rows.c.queue_status == "archived", 1), else_=0)),
                        0,
                    ).label("archived_count"),
                    func.coalesce(
                        func.sum(case((status_rows.c.queue_status == "unconstructed", 1), else_=0)),
                        0,
                    ).label("unconstructed_count"),
                ).select_from(status_rows)
            ).one()
            status_counts = {
                "all": int(_row_value(counts, "all_count", 0) or 0),
                "reviewable": int(_row_value(counts, "reviewable_count", 0) or 0),
                "exception": int(_row_value(counts, "exception_count", 0) or 0),
                "archived": int(_row_value(counts, "archived_count", 0) or 0),
                "unconstructed": int(_row_value(counts, "unconstructed_count", 0) or 0),
            }
            page_statement = select(MaterialGroup).where(*filters)
            if review_status != "all":
                page_statement = page_statement.where(queue_status == review_status)
            queue_rank = case(
                (queue_status == "reviewable", 0),
                (queue_status == "exception", 1),
                (queue_status == "unconstructed", 2),
                else_=3,
            )
            groups = list(
                session.scalars(
                    page_statement.order_by(
                        queue_rank,
                        func.coalesce(MaterialGroup.display_meter_no, ""),
                        func.coalesce(MaterialGroup.legacy_id, cast(MaterialGroup.id, String)),
                    )
                    .offset(offset)
                    .limit(limit)
                ).all()
            )
            payloads = _group_payloads(session, groups, include_photos=False)
            photos_by_group_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
            group_ids = [group.id for group in groups]
            if group_ids:
                photo_rows = session.execute(
                    select(
                        Photo.group_id,
                        Photo.id.label("photo_id"),
                        Photo.legacy_id,
                        Photo.category,
                        Photo.barcode,
                        Photo.collector,
                        Photo.asset_no,
                        Photo.upload_status,
                        Photo.raw_data,
                    )
                    .where(
                        Photo.team_id == team_id,
                        Photo.group_id.in_(group_ids),
                        Photo.is_active.is_(True),
                    )
                    .order_by(Photo.group_id, Photo.sort_order, Photo.created_at, Photo.legacy_id)
                ).all()
                for row in photo_rows:
                    photos_by_group_id[str(row.group_id)].append(_photo_barcode_payload_from_row(row))
            for group, payload in zip(groups, payloads, strict=True):
                payload["photos"] = photos_by_group_id.get(str(group.id), [])
            total = status_counts["all"] if review_status == "all" else status_counts[review_status]
            return {
                "total": total,
                "items": [_group_target_summary(payload) for payload in payloads],
                "status_counts": status_counts,
                "limit": limit,
                "offset": offset,
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

    def _unmatched_records_statement(self, *, query: str = "", assigned_to: str = ""):
        team_id = local_simulation.current_team_id()
        statement = select(UnmatchedRecord).where(
            UnmatchedRecord.team_id == team_id,
            UnmatchedRecord.status == "open",
        )
        assigned_scope = str(assigned_to or "").strip()
        if assigned_scope:
            statement = statement.where(
                func.trim(
                    func.coalesce(UnmatchedRecord.payload["assigned_to"].astext, "")
                )
                == assigned_scope
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
                    UnmatchedRecord.payload["temporary_review"]["meter_no"].astext.ilike(pattern),
                    UnmatchedRecord.payload["temporary_review"]["collector"].astext.ilike(pattern),
                    UnmatchedRecord.payload["temporary_review"]["module_asset_no"].astext.ilike(pattern),
                )
            )
        return statement

    def list_unmatched_records(
        self,
        *,
        query: str = "",
        limit: int = 100,
        offset: int = 0,
        assigned_to: str = "",
    ) -> dict[str, Any]:
        statement = self._unmatched_records_statement(query=query, assigned_to=assigned_to)
        with self._session() as session:
            filtered = statement.subquery()
            outside_condition = func.lower(
                func.coalesce(filtered.c.payload["project_outside"].astext, "false")
            ).in_(("true", "1"))
            assigned_condition = func.length(
                func.trim(func.coalesce(filtered.c.payload["assigned_to"].astext, ""))
            ) > 0
            total = session.scalar(select(func.count()).select_from(filtered)) or 0
            outside = session.scalar(
                select(func.count()).select_from(filtered).where(outside_condition)
            ) or 0
            assigned = session.scalar(
                select(func.count()).select_from(filtered).where(assigned_condition)
            ) or 0
            pending = session.scalar(
                select(func.count()).select_from(filtered).where(~outside_condition, ~assigned_condition)
            ) or 0
            records = session.scalars(
                statement.order_by(UnmatchedRecord.terminal, UnmatchedRecord.barcode, UnmatchedRecord.legacy_id)
                .offset(offset)
                .limit(limit)
            ).all()
            return {
                "total": int(total),
                "items": [_unmatched_payload(record) for record in records],
                "stats": {"pending": int(pending), "assigned": int(assigned), "outside": int(outside)},
            }

    def export_unmatched_records(self, *, query: str = "", limit: int = 100_000) -> dict[str, Any]:
        statement = (
            self._unmatched_records_statement(query=query)
            .add_columns(func.count().over().label("export_total"))
            .order_by(UnmatchedRecord.terminal, UnmatchedRecord.barcode, UnmatchedRecord.legacy_id)
            .limit(max(1, int(limit or 1)))
        )
        with self._session() as session:
            rows = session.execute(statement).all()
        total = int(rows[0][1]) if rows else 0
        return {
            "total": total,
            "items": [_unmatched_payload(row[0]) for row in rows],
        }

    def get_unmatched_review(self, unmatched_id: str) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        with self._session() as session:
            record = session.scalar(
                select(UnmatchedRecord).where(
                    UnmatchedRecord.team_id == team_id,
                    UnmatchedRecord.legacy_id == unmatched_id,
                    UnmatchedRecord.status == "open",
                )
            )
            if record is None:
                raise KeyError(unmatched_id)
            record_payload = _unmatched_payload(record)
            return {
                "record": record_payload,
                "review": unmatched_review.build_review(record_payload),
            }

    def _unmatched_match_candidates_for_session(
        self,
        session: Session,
        record: UnmatchedRecord,
        review: dict[str, Any],
    ) -> list[dict[str, Any]]:
        record_payload = _unmatched_payload(record)
        meter_key = unmatched_review.review_meter_match_key(record_payload, review)
        if not meter_key:
            return []
        catalog_rows = list(
            session.scalars(
                select(TotalCatalogRow).where(
                    TotalCatalogRow.team_id == record.team_id,
                    TotalCatalogRow.meter_match_key == meter_key,
                )
            ).all()
        )
        catalog_payloads = []
        for row in catalog_rows:
            payload = _catalog_row_payload(row)
            payload["catalog_row_db_id"] = str(row.id)
            catalog_payloads.append(payload)
        terminals = sorted(
            {
                str(row.get("terminal") or "").strip()
                for row in catalog_payloads
                if str(row.get("terminal") or "").strip() not in unmatched_review.INVALID_TERMINALS
            }
        )
        groups = []
        if terminals:
            groups = list(
                session.scalars(
                    select(MaterialGroup).where(
                        MaterialGroup.team_id == record.team_id,
                        MaterialGroup.terminal.in_(terminals),
                        or_(
                            MaterialGroup.total_catalog_row_id.in_([row.id for row in catalog_rows]),
                            MaterialGroup.meter_match_key == meter_key,
                        ),
                    )
                ).all()
            )
        group_payloads = [
            {
                "id": str(group.legacy_id or group.id),
                "terminal": str(group.terminal or ""),
                "total_catalog_row_id": str(group.total_catalog_row_id or ""),
                "meter_match_key": str(group.meter_match_key or ""),
            }
            for group in groups
        ]
        return unmatched_review.build_match_candidates(
            record_payload,
            review,
            catalog_payloads,
            group_payloads,
        )

    def list_unmatched_match_candidates(self, unmatched_id: str, *, actor: str = "") -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        with self._session() as session:
            record = session.scalar(
                select(UnmatchedRecord).where(
                    UnmatchedRecord.team_id == team_id,
                    UnmatchedRecord.legacy_id == unmatched_id,
                    UnmatchedRecord.status == "open",
                )
            )
            if record is None:
                raise KeyError(unmatched_id)
            review = unmatched_review.build_review(_unmatched_payload(record))
            unmatched_review.require_manual_confirmation(review)
            candidates = self._unmatched_match_candidates_for_session(session, record, review)
            if actor.strip():
                _stage_transactional_audit(
                    session,
                    team_id=team_id,
                    actor=actor.strip(),
                    action="unmatched_review_candidates_viewed",
                    entity_type="unmatched_record",
                    entity_id=record.id,
                    before_data={},
                    after_data={},
                    payload={
                        "unmatched_id": unmatched_id,
                        "review_version": int(review.get("version") or 0),
                        "candidate_count": len(candidates),
                        "candidate_digest": unmatched_review.candidate_snapshot_digest(candidates),
                    },
                )
                session.commit()
            return {"total": len(candidates), "items": candidates}

    def _resolve_unmatched_candidate(
        self,
        session: Session,
        record: UnmatchedRecord,
        review: dict[str, Any],
        candidate_key: str,
    ) -> dict[str, Any]:
        candidates = self._unmatched_match_candidates_for_session(session, record, review)
        candidate = next((item for item in candidates if item["candidate_key"] == candidate_key), None)
        if candidate is None:
            raise ValueError("Selected candidate is invalid or unavailable")
        if str(candidate.get("terminal") or "").strip() in unmatched_review.INVALID_TERMINALS:
            raise ValueError("Selected candidate has an invalid terminal")
        return candidate

    def _materialize_unmatched_candidate(
        self,
        session: Session,
        record: UnmatchedRecord,
        review: dict[str, Any],
        candidate: dict[str, Any],
        actor: str,
    ) -> tuple[MaterialGroup, bool]:
        terminal = str(candidate.get("terminal") or "").strip()
        meter_no = str(candidate.get("meter_no") or "").strip()
        meter_key = str(candidate.get("meter_match_key") or "").strip()
        if terminal in unmatched_review.INVALID_TERMINALS:
            raise ValueError("Selected candidate has an invalid terminal")
        if not meter_no or not meter_key:
            raise ValueError("Selected candidate has an invalid meter")

        catalog_row_id = None
        try:
            catalog_row_id = UUID(
                str(candidate.get("catalog_row_db_id") or candidate.get("catalog_row_id") or "")
            )
        except ValueError:
            pass
        project_id = self._project_id_for_team(session, record.team_id)
        target_group_id = str(candidate.get("target_group_id") or "").strip()
        group = session.scalar(
            select(MaterialGroup)
            .where(
                MaterialGroup.project_id == project_id,
                MaterialGroup.meter_match_key == meter_key,
            )
            .limit(1)
            .with_for_update()
        )
        if group is not None:
            group_id = str(group.legacy_id or group.id)
            if str(group.terminal or "").strip() != terminal or (
                target_group_id and target_group_id != group_id
            ):
                raise unmatched_review.FinalizationIdentityConflict(
                    "Candidate conflicts with existing formal group identity"
                )
        elif target_group_id:
            group = session.scalar(
                select(MaterialGroup)
                .where(
                    MaterialGroup.team_id == record.team_id,
                    MaterialGroup.legacy_id == target_group_id,
                )
                .with_for_update()
            )
            if group is None:
                raise ValueError("Selected candidate target group is unavailable")
            if (
                (group.project_id is not None and group.project_id != project_id)
                or (str(group.meter_match_key or "").strip() not in {"", meter_key})
                or str(group.terminal or "").strip() != terminal
            ):
                raise unmatched_review.FinalizationIdentityConflict(
                    "Candidate conflicts with existing formal group identity"
                )

        attached = group is not None
        task = self._ensure_task_for_terminal(session, record.team_id, terminal)
        if group is None:
            group = MaterialGroup(
                team_id=record.team_id,
                project_id=project_id,
                total_catalog_row_id=catalog_row_id,
                legacy_id=_new_formal_group_legacy_id(),
                legacy_task_id=task.legacy_id,
                task_id=task.id,
                terminal=terminal,
                meter_match_key=meter_key,
                display_meter_no=meter_no,
                installation_address=str(candidate.get("address") or ""),
                status=GroupStatus.INCOMPLETE,
                photo_count=0,
                raw_data={
                    "manual_created": False,
                    "created_by": actor,
                    "source_unmatched_id": record.legacy_id,
                    "status": "incomplete",
                    "stage_terminal": terminal,
                },
            )
            session.add(group)
            session.flush()
        else:
            group.project_id = group.project_id or project_id
            group.total_catalog_row_id = group.total_catalog_row_id or catalog_row_id
            group.legacy_task_id = task.legacy_id
            group.task_id = task.id
            group.terminal = terminal
            group.meter_match_key = meter_key
            group.display_meter_no = meter_no
            group.installation_address = str(candidate.get("address") or "")

        raw = dict(group.raw_data or {})
        raw.update(
            {
                "source_unmatched_id": record.legacy_id,
                "meter_no": meter_no,
                "meter_match_key": meter_key,
                "collector": str(review.get("collector") or ""),
                "module_asset_no": str(review.get("module_asset_no") or ""),
                "asset_no": str(review.get("module_asset_no") or ""),
                "stage_terminal": terminal,
            }
        )
        for key in (
            "group_barcode_manual_confirmed",
            "group_barcode_manual_confirmed_fields",
            "group_barcode_manual_confirmed_by",
            "group_barcode_manual_confirmed_at",
        ):
            raw.pop(key, None)
        group.raw_data = raw
        self._add_photo_records_to_group(
            session,
            group,
            actor=actor,
            photos=unmatched_review.migrate_review_to_photo_rows(review),
            collector=str(review.get("collector") or ""),
            module_asset_no=str(review.get("module_asset_no") or ""),
            creator=str(review.get("reviewer") or actor),
            source="unmatched-review-finalize",
        )
        photos = list(
            session.scalars(
                select(Photo).where(
                    Photo.team_id == group.team_id,
                    Photo.group_id == group.id,
                    Photo.is_active.is_(True),
                )
            ).all()
        )
        formal_check = photo_barcode_check.build_group_barcode_check(_group_barcode_payload(group, photos))
        raw = dict(group.raw_data or {})
        raw.update(formal_check)
        group.raw_data = raw
        session.flush()
        return group, attached

    def finalize_unmatched_match(
        self,
        unmatched_id: str,
        *,
        actor: str,
        candidate_key: str,
        expected_version: int,
        source_page: str = "",
    ) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        with self._session() as session:
            try:
                record = session.scalar(
                    select(UnmatchedRecord)
                    .where(
                        UnmatchedRecord.team_id == team_id,
                        UnmatchedRecord.legacy_id == unmatched_id,
                    )
                    .with_for_update()
                )
                if record is None:
                    raise KeyError(unmatched_id)
                replay = (record.payload or {}).get(FINALIZATION_REPLAY_KEY)
                if record.status == "associated":
                    if (
                        isinstance(replay, dict)
                        and replay.get("candidate_key") == candidate_key
                        and replay.get("expected_version") == expected_version
                        and isinstance(replay.get("result"), dict)
                    ):
                        return deepcopy(replay["result"])
                    raise KeyError(unmatched_id)
                if record.status != "open":
                    raise KeyError(unmatched_id)
                review = unmatched_review.build_review(_unmatched_payload(record))
                unmatched_review.require_version(review, expected_version)
                unmatched_review.require_manual_confirmation(review)
                candidate = self._resolve_unmatched_candidate(session, record, review, candidate_key)
                terminal, meter_no = local_simulation.validate_real_formal_identity(
                    str(candidate.get("terminal") or ""),
                    str(candidate.get("meter_no") or ""),
                )
                candidate = {**candidate, "terminal": terminal, "meter_no": meter_no}
                meter_key = str(
                    candidate.get("meter_match_key")
                    or local_simulation.build_total_catalog_match_key(meter_no)
                    or ""
                ).strip()
                meter_key = local_simulation.validate_real_formal_identity_value(
                    meter_key,
                    "meter match key",
                )
                project_id = self._project_id_for_team(session, team_id)
                lock_key = _formal_identity_advisory_lock_key(project_id, meter_key)
                session.scalar(select(func.pg_advisory_xact_lock(lock_key)))
                group, attached = self._materialize_unmatched_candidate(
                    session,
                    record,
                    review,
                    candidate,
                    actor,
                )
                record.status = "associated"
                record.payload = {
                    **(record.payload or {}),
                    "temporary_review": review,
                    "associated_by": actor,
                    "associated_group_id": group.legacy_id,
                }
                before = {"unmatched_id": unmatched_id, "review_version": expected_version}
                after = {"group_id": group.legacy_id, "terminal": candidate["terminal"]}
                _stage_transactional_audit(
                    session,
                    team_id=team_id,
                    actor=actor,
                    action="unmatched_review_finalized",
                    entity_type="unmatched_record",
                    entity_id=record.id,
                    before_data=before,
                    after_data=after,
                    payload=_data_center_audit_payload(
                        source_page=source_page or "admin",
                        actor=actor,
                        reason="unmatched_review_finalized",
                        before=before,
                        after=after,
                        candidate_key=candidate_key,
                        attached=attached,
                    ),
                )
                result = {
                    "group": _group_payload(session, group),
                    "attached": attached,
                }
                record.payload = {
                    **record.payload,
                    FINALIZATION_REPLAY_KEY: {
                        "candidate_key": candidate_key,
                        "expected_version": expected_version,
                        "result": deepcopy(result),
                    },
                }
                session.commit()
                return result
            except IntegrityError as exc:
                session.rollback()
                raise unmatched_review.FinalizationIdentityConflict(
                    "Candidate conflicts with existing formal group identity"
                ) from exc
            except Exception:
                session.rollback()
                raise

    def save_unmatched_review(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int,
        metadata: dict[str, Any] | None = None,
        photo_updates: list[dict[str, Any]] | None = None,
        state: str = "pending",
    ) -> dict[str, Any]:
        unmatched_review.validate_state(state)
        team_id = local_simulation.current_team_id()
        with self._session() as session:
            try:
                record = session.scalar(
                    select(UnmatchedRecord)
                    .where(
                        UnmatchedRecord.team_id == team_id,
                        UnmatchedRecord.legacy_id == unmatched_id,
                        UnmatchedRecord.status == "open",
                    )
                    .with_for_update()
                )
                if record is None:
                    raise KeyError(unmatched_id)
                previous = unmatched_review.build_review(_unmatched_payload(record))
                updated = unmatched_review.apply_review_patch(
                    previous,
                    actor=actor,
                    expected_version=expected_version,
                    metadata=metadata or {},
                    photo_updates=photo_updates or [],
                    state=state,
                )
                audit_event = updated.pop("audit_event")
                record.payload = {**(record.payload or {}), "temporary_review": updated}
                _stage_transactional_audit(
                    session,
                    team_id=team_id,
                    actor=actor,
                    action="unmatched_review_saved",
                    entity_type="unmatched_record",
                    entity_id=record.id,
                    before_data=audit_event["before"],
                    after_data=audit_event["after"],
                    payload={
                        "unmatched_id": unmatched_id,
                        "before_version": audit_event["before_version"],
                        "after_version": audit_event["after_version"],
                    },
                )
                session.commit()
                return {"record": _unmatched_payload(record), "review": deepcopy(updated)}
            except Exception:
                session.rollback()
                raise

    def rescan_unmatched_review_photo(
        self,
        unmatched_id: str,
        photo_id: str,
        *,
        actor: str,
        expected_version: int,
        category: str = "",
    ) -> dict[str, Any]:
        if category:
            unmatched_review.validate_category(category)
        team_id = local_simulation.current_team_id()
        with self._session() as snapshot_session:
            snapshot_record = snapshot_session.scalar(
                select(UnmatchedRecord).where(
                    UnmatchedRecord.team_id == team_id,
                    UnmatchedRecord.legacy_id == unmatched_id,
                    UnmatchedRecord.status == "open",
                )
            )
            if snapshot_record is None:
                raise KeyError(unmatched_id)
            snapshot_review = unmatched_review.build_review(_unmatched_payload(snapshot_record))
            unmatched_review.require_version(snapshot_review, expected_version)
            snapshot_photo = unmatched_review.find_review_photo(snapshot_review, photo_id)
            if category:
                snapshot_photo["category"] = category
            scan_photo = deepcopy(snapshot_photo)
            scan_context = deepcopy(unmatched_review.barcode_context(snapshot_review))

        scan_result = photo_barcode_check.check_photo_barcode(
            {**scan_photo, "image_url": scan_photo["source_url"]},
            scan_context,
            use_ocr=True,
        )

        with self._session() as session:
            try:
                record = session.scalar(
                    select(UnmatchedRecord)
                    .where(
                        UnmatchedRecord.team_id == team_id,
                        UnmatchedRecord.legacy_id == unmatched_id,
                        UnmatchedRecord.status == "open",
                    )
                    .with_for_update()
                )
                if record is None:
                    raise KeyError(unmatched_id)
                review = unmatched_review.build_review(_unmatched_payload(record))
                unmatched_review.require_version(review, expected_version)
                before_review = deepcopy(review)
                photo = unmatched_review.find_review_photo(review, photo_id)
                before_photo = deepcopy(photo)
                if category:
                    photo["category"] = category
                photo.update(deepcopy(scan_result))
                now = datetime.now(UTC).isoformat()
                photo["barcode_rescanned_by"] = actor
                photo["barcode_rescanned_at"] = now
                unmatched_review.invalidate_manual_confirmation_if_evidence_changed(before_review, review)
                before_confirmation = unmatched_review.manual_confirmation_state(before_review)
                after_confirmation = unmatched_review.manual_confirmation_state(review)
                review["version"] = expected_version + 1
                review["updated_at"] = now
                record.payload = {**(record.payload or {}), "temporary_review": review}
                _stage_transactional_audit(
                    session,
                    team_id=team_id,
                    actor=actor,
                    action="unmatched_review_barcode_rescan",
                    entity_type="unmatched_record",
                    entity_id=record.id,
                    before_data={
                        "photo": before_photo,
                        "review_version": expected_version,
                        "confirmation": before_confirmation,
                    },
                    after_data={
                        "photo": deepcopy(photo),
                        "review_version": review["version"],
                        "confirmation": after_confirmation,
                    },
                    payload={
                        "unmatched_id": unmatched_id,
                        "photo_id": photo_id,
                        "category": photo.get("category") or "",
                    },
                )
                session.commit()
                return {
                    "record": _unmatched_payload(record),
                    "review": deepcopy(review),
                    "photo": deepcopy(photo),
                }
            except Exception:
                session.rollback()
                raise

    def confirm_unmatched_review(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int,
        confirmed: bool = True,
    ) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        with self._session() as session:
            try:
                record = session.scalar(
                    select(UnmatchedRecord)
                    .where(
                        UnmatchedRecord.team_id == team_id,
                        UnmatchedRecord.legacy_id == unmatched_id,
                        UnmatchedRecord.status == "open",
                    )
                    .with_for_update()
                )
                if record is None:
                    raise KeyError(unmatched_id)
                review = unmatched_review.build_review(_unmatched_payload(record))
                unmatched_review.require_version(review, expected_version)
                before = deepcopy(review)
                reviewed_at = datetime.now(UTC).isoformat()
                review["manual_confirmed"] = bool(confirmed)
                review["reviewer"] = actor
                review["reviewed_at"] = reviewed_at
                review["version"] = expected_version + 1
                record.payload = {**(record.payload or {}), "temporary_review": review}
                _stage_transactional_audit(
                    session,
                    team_id=team_id,
                    actor=actor,
                    action="unmatched_review_confirmed",
                    entity_type="unmatched_record",
                    entity_id=record.id,
                    before_data=before,
                    after_data=deepcopy(review),
                    payload={
                        "unmatched_id": unmatched_id,
                        "confirmed": bool(confirmed),
                        "before_version": expected_version,
                        "after_version": review["version"],
                    },
                )
                session.commit()
                return {"record": _unmatched_payload(record), "review": deepcopy(review)}
            except Exception:
                session.rollback()
                raise

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
                _stage_transactional_audit(
                    session,
                    team_id=team_id,
                    actor=actor,
                    action="dedupe_unmatched",
                    entity_type="unmatched_records",
                    payload={"removed": len(duplicates), "duplicate_ids": duplicate_ids},
                )
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
        expected_version: int = 1,
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        updates = unmatched_review.normalize_legacy_identity_updates(updates)
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
            review = _checked_unmatched_review(record, expected_version)
            before = _unmatched_payload(record)
            raw = dict(record.payload or {})
            changed_fields: set[str] = set()
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
                        if str(record.module_asset_no or "").strip() != value:
                            changed_fields.add(key)
                        record.module_asset_no = value
                    elif hasattr(record, key):
                        if str(getattr(record, key) or "").strip() != value:
                            changed_fields.add(key)
                        setattr(record, key, value)
                    else:
                        if str(raw.get(key) or "").strip() != value:
                            changed_fields.add(key)
                        raw[key] = value
            raw.update({"updated_by": actor, "updated_at": datetime.now(UTC).isoformat()})
            synchronized_review = unmatched_review.synchronize_review_identity_after_legacy_patch(
                review,
                _unmatched_payload(record),
                changed_fields,
            )
            record.payload = _advance_unmatched_review_payload(raw, synchronized_review, expected_version)
            _stage_transactional_audit(
                session,
                team_id=record.team_id,
                actor=actor,
                action="unmatched_record_updated",
                entity_type="unmatched_record",
                entity_id=record.id,
                before_data=before,
                after_data=_unmatched_payload(record),
                payload={"expected_version": expected_version},
            )
            session.commit()
            session.refresh(record)
            return {"record": _unmatched_payload(record)}

    def assign_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        constructor: str,
        expected_version: int = 1,
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
            terminal = local_simulation.validate_real_formal_identity_value(record.terminal, "terminal")
            review = _checked_unmatched_review(record, expected_version)
            before = _unmatched_payload(record)
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
            record.payload = _advance_unmatched_review_payload(raw, review, expected_version)
            _stage_transactional_audit(
                session,
                team_id=record.team_id,
                actor=actor,
                action="unmatched_record_assigned",
                entity_type="unmatched_record",
                entity_id=record.id,
                before_data=before,
                after_data=_unmatched_payload(record),
                payload={"expected_version": expected_version},
            )
            session.commit()
            session.refresh(record)
            return {"record": _unmatched_payload(record)}

    def unassign_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int = 1,
        reason: str = "",
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
            review = _checked_unmatched_review(record, expected_version)
            before = _unmatched_payload(record)
            raw = dict(record.payload or {})
            raw.update(
                {
                    "assigned_to": "",
                    "unassigned_by": actor,
                    "unassigned_at": datetime.now(UTC).isoformat(),
                    "unassign_reason": reason.strip(),
                }
            )
            record.payload = _advance_unmatched_review_payload(raw, review, expected_version)
            _stage_transactional_audit(
                session,
                team_id=record.team_id,
                actor=actor,
                action="unmatched_record_unassigned",
                entity_type="unmatched_record",
                entity_id=record.id,
                before_data=before,
                after_data=_unmatched_payload(record),
                payload={"expected_version": expected_version},
            )
            session.commit()
            session.refresh(record)
            return {"record": _unmatched_payload(record)}

    def mark_unmatched_outside_project(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int = 1,
        note: str = "",
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
            review = _checked_unmatched_review(record, expected_version)
            before = _unmatched_payload(record)
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
            record.payload = _advance_unmatched_review_payload(raw, review, expected_version)
            _stage_transactional_audit(
                session,
                team_id=record.team_id,
                actor=actor,
                action="unmatched_record_marked_outside_project",
                entity_type="unmatched_record",
                entity_id=record.id,
                before_data=before,
                after_data=_unmatched_payload(record),
                payload={"expected_version": expected_version},
            )
            session.commit()
            session.refresh(record)
            return {"record": _unmatched_payload(record)}

    def rematch_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int = 1,
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
        updated = self.update_unmatched_record(
            unmatched_id,
            actor=actor,
            expected_version=expected_version,
            updates=updates,
        )["record"]
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
            expected_version=int(updated["review_version"]),
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
        updates = local_simulation.validate_formal_identity_updates(updates)
        requeue_delivery_cache_reason = ""
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
                identity_changed = bool(set(changed_fields).intersection(
                    {
                        "meter_no",
                        "terminal",
                        "collector",
                        "module_asset_no",
                        "construction_collector",
                        "construction_module_asset_no",
                    }
                ))
                if identity_changed:
                    invalidate_verification_for_group(
                        session,
                        group,
                        actor=actor,
                        reason="group_identity_changed",
                    )
                requeue_delivery_cache_reason = (
                    "group_identity_changed" if identity_changed else "group_metadata_changed"
                )
                from app.services.delivery_cache import (
                    invalidate_postgres_delivery_cache_for_group_change,
                )

                invalidate_postgres_delivery_cache_for_group_change(
                    session,
                    group,
                    actor=actor,
                    reason=requeue_delivery_cache_reason,
                )
                _stage_transactional_audit(
                    session,
                    team_id=local_simulation.current_team_id(),
                    actor=actor,
                    action=audit_action,
                    entity_type="material_group",
                    entity_id=group.id,
                    before_data={field: before.get(field) for field in changed_fields},
                    after_data={field: after.get(field) for field in changed_fields},
                    payload={"group_id": group.legacy_id or str(group.id), "changed_fields": changed_fields},
                )
            session.commit()
            session.refresh(group)
            result = {"group": _group_payload(session, group), "changed_fields": changed_fields}
        if requeue_delivery_cache_reason:
            self._enqueue_delivery_cache_after_commit(
                group_id,
                actor=actor,
                reason=requeue_delivery_cache_reason,
                require_eligible=True,
            )
        return result

    def update_data_center_group(
        self,
        group_id: str,
        *,
        patch: dict[str, Any],
        actor: str,
        reason: str = "",
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        result = self.update_group_metadata(
            group_id,
            actor=actor,
            updates=patch,
            audit_action="data_center_group_updated",
        )
        changed_fields = list(result.get("changed_fields") or [])
        if changed_fields and set(changed_fields).intersection(DATA_CENTER_IDENTITY_FIELDS):
            with self._session() as session:
                group = self._group_by_legacy_id(session, group_id, lock=True)
                photos = session.scalars(
                    select(Photo).where(
                        Photo.team_id == group.team_id,
                        Photo.group_id == group.id,
                        Photo.is_active.is_(True),
                    )
                ).all()
                if photos and all(str(photo.archive_status or "") == "archived" for photo in photos):
                    now = datetime.now(UTC)
                    for photo in photos:
                        raw = dict(photo.raw_data or {})
                        photo.archive_status = "pending"
                        photo.archived_at = None
                        raw.update({"archive_status": "pending", "archived_at": ""})
                        photo.raw_data = raw
                    raw_data = dict(group.raw_data or {})
                    raw_data.update(
                        {
                            "archive_status": "pending",
                            "status": "pending",
                            "reviewer": "",
                            "review_note": "",
                            "reviewed_at": "",
                        }
                    )
                    group.status = GroupStatus.UNREVIEWED
                    group.reviewer = None
                    group.review_note = ""
                    group.reviewed_at = None
                    group.raw_data = raw_data
                    group.updated_at = now
                    _stage_transactional_audit(
                        session,
                        team_id=local_simulation.current_team_id(),
                        actor=actor,
                        action="data_center_archive_invalidated",
                        entity_type="material_group",
                        entity_id=group.id,
                        payload={
                            "group_id": group.legacy_id or str(group.id),
                            "previous_archive_status": "archived",
                            "reason": reason or "data_center_identity_changed",
                        },
                    )
                    session.commit()
        group_payload = self.get_group(group_id) or result.get("group") or {}
        return _data_center_group_result(group_payload, changed_fields=changed_fields)

    def _stage_data_center_auto_archive_delivery_jobs(
        self,
        session: Session,
        group: MaterialGroup,
        *,
        group_payload: dict[str, Any],
        actor: str,
        reason: str,
    ) -> str:
        from app.services.delivery_cache import sync_postgres_delivery_cache_job_for_group
        from app.services.delivery_package_queue import DeliveryPackageNotReady, request_postgres_delivery_package

        if hasattr(session, "flush"):
            sync_postgres_delivery_cache_job_for_group(
                session,
                group,
                group_payload=group_payload,
                actor=actor,
                reason=reason,
            )
        try:
            request_postgres_delivery_package(
                session,
                groups=[group_payload],
                team_id=group.team_id,
                task_id=int(group.legacy_task_id or 0) or None,
                terminal=str(group.terminal or ""),
                review_scope="reviewed",
                requested_by=actor,
                auto_commit=False,
            )
            return "ready"
        except DeliveryPackageNotReady as exc:
            return exc.status

    def classify_data_center_group_photo(
        self,
        group_id: str,
        photo_id: str,
        category: str,
        *,
        actor: str,
        reason: str = "",
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        from app.services.group_barcode_verification import evaluate_group_eligibility

        if category not in local_simulation.PHOTO_CATEGORIES:
            raise ValueError(f"Unsupported photo category: {category}")
        should_enqueue = False
        package_status = ""
        group_payload: dict[str, Any] = {}
        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id, lock=True)
            photo = session.scalar(
                select(Photo).where(
                    Photo.team_id == local_simulation.current_team_id(),
                    Photo.group_id == group.id,
                    Photo.legacy_id == photo_id,
                    Photo.is_active.is_(True),
                ).with_for_update()
            )
            if photo is None:
                raise KeyError(photo_id)
            before = {
                "category": str(photo.category or "unclassified"),
                "archive_status": str(photo.archive_status or ""),
                "archive_filename": str(photo.archive_filename or ""),
            }
            category_label = local_simulation.PHOTO_CATEGORIES.get(
                category,
                local_simulation.PHOTO_CATEGORIES["unclassified"],
            )
            now = datetime.now(UTC)
            image_url = photo.image_url or photo.source_url or ""
            photo.category = category
            photo.classified_by = actor
            photo.classified_at = now
            photo.archive_status = "archived"
            photo.archive_filename = local_simulation.build_archive_filename(category_label, image_url)
            photo.archived_at = now
            raw_data = dict(photo.raw_data or {})
            raw_data.update(
                {
                    "category": category,
                    "category_label": category_label,
                    "classified_by": actor,
                    "archive_status": "archived",
                    "archive_filename": photo.archive_filename,
                    "archived_at": photo.archived_at.isoformat(),
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
                    _group_barcode_context(group),
                )
            )
            photo.raw_data = raw_data
            photos = list(
                session.scalars(
                    select(Photo)
                    .where(Photo.team_id == group.team_id, Photo.group_id == group.id, Photo.is_active.is_(True))
                    .with_for_update()
                ).all()
            )
            eligibility = evaluate_group_eligibility(
                _verification_group_payload(session, group, prefetched_photos=photos)
            )
            verification = session.scalar(
                select(GroupBarcodeVerification)
                .where(
                    GroupBarcodeVerification.team_id == group.team_id,
                    GroupBarcodeVerification.group_id == group.id,
                )
                .with_for_update()
            )
            persisted = dict((group.raw_data or {}).get("barcode_verification") or {})
            verification_result = dict(persisted.get("result") or getattr(verification, "result", None) or {})
            verification_payload = {
                **persisted,
                "status": getattr(verification, "status", persisted.get("status", "")),
                "evidence_fingerprint": getattr(
                    verification,
                    "evidence_fingerprint",
                    persisted.get("evidence_fingerprint"),
                ),
                "evidence_version": getattr(verification, "evidence_version", persisted.get("evidence_version", 0)),
                "meter_matched": getattr(verification, "meter_matched", persisted.get("meter_matched")),
                "module_matched": getattr(verification, "module_matched", persisted.get("module_matched")),
                "collector_matched": getattr(verification, "collector_matched", persisted.get("collector_matched")),
                "recognition_source": getattr(
                    verification,
                    "recognition_source",
                    persisted.get("recognition_source", ""),
                ),
                "result": verification_result,
            }
            authoritative = (
                verification is not None
                and eligibility.status == "pending"
                and str(verification_payload.get("status") or "") in {"passed", "manual_confirmed"}
                and str(verification_payload.get("evidence_fingerprint") or "")
                == str(eligibility.evidence_fingerprint or "")
                and verification_payload.get("meter_matched") is True
                and verification_payload.get("module_matched") is True
                and verification_payload.get("collector_matched") is True
                and int(verification_result.get("passed_count") or 0) == 3
                and str(verification_payload.get("recognition_source") or "")
                in {"machine_barcode", "machine_qr", "manual_confirmed", "manual"}
                and _legacy_group_status(group) in {"", "pending", "unreviewed", "in_review", "incomplete"}
                and not bool(getattr(group, "has_archive_blocker", False))
            )
            from app.services.delivery_cache import invalidate_postgres_delivery_cache_for_group_change

            invalidate_postgres_delivery_cache_for_group_change(
                session,
                group,
                actor=actor,
                reason="data_center_photo_classified",
            )
            if authoritative:
                archive_now = datetime.now(UTC)
                for item in photos:
                    item.archive_status = "archived"
                    item.archived_at = archive_now
                    item.classified_by = item.classified_by or actor
                    item_raw = dict(item.raw_data or {})
                    item_raw.update(
                        {
                            "archive_status": "archived",
                            "archived_at": archive_now.isoformat(),
                            "classified_by": item.classified_by,
                        }
                    )
                    item.raw_data = item_raw
                group.status = GroupStatus.APPROVED
                group.reviewer = actor
                group.review_note = "barcode verification auto archive"
                group.reviewed_at = archive_now
                group_raw = dict(group.raw_data or {})
                next_verification = {
                    **verification_payload,
                    "auto_archive_status": "archived",
                    "auto_archived_at": archive_now.isoformat(),
                    "auto_archive_lease_owner": None,
                    "auto_archive_lease_token": None,
                    "auto_archive_lease_expires_at": None,
                    "auto_archive_error": "",
                }
                group_raw.update(
                    {
                        "status": "approved",
                        "archive_status": "archived",
                        "reviewer": actor,
                        "review_note": "barcode verification auto archive",
                        "reviewed_at": archive_now.isoformat(),
                        "barcode_verification": next_verification,
                    }
                )
                group.raw_data = group_raw
                verification.auto_archive_status = "archived"
                verification.auto_archived_at = archive_now
                verification.auto_archive_lease_owner = None
                verification.auto_archive_lease_token = None
                verification.auto_archive_lease_expires_at = None
                verification.auto_archive_error = None
                should_enqueue = True
                group_payload = _group_payload(session, group, include_photos=True, verification=verification)
                package_status = self._stage_data_center_auto_archive_delivery_jobs(
                    session,
                    group,
                    group_payload=group_payload,
                    actor=actor,
                    reason="data_center_auto_archive",
                )
                _stage_transactional_audit(
                    session,
                    team_id=group.team_id,
                    actor=actor,
                    action="data_center_delivery_package_requested",
                    entity_type="material_group",
                    entity_id=group.id,
                    payload=_data_center_audit_payload(
                        source_page=source_page,
                        actor=actor,
                        reason="data_center_auto_archive",
                        before={"archive_status": "pending"},
                        after={
                            "archive_status": "archived",
                            "delivery_package_job_status": package_status,
                        },
                        group_id=str(group.legacy_id or group.id),
                    ),
                )
            after = {
                "category": str(photo.category or ""),
                "archive_status": str(photo.archive_status or ""),
                "archive_filename": str(photo.archive_filename or ""),
            }
            _stage_transactional_audit(
                session,
                team_id=group.team_id,
                actor=actor,
                action="data_center_photo_classified",
                entity_type="photo",
                entity_id=photo.id,
                before_data=before,
                after_data=after,
                payload=_data_center_audit_payload(
                    source_page=source_page,
                    actor=actor,
                    reason=reason or "data_center_photo_classified",
                    before=before,
                    after=after,
                    group_id=str(group.legacy_id or group.id),
                    photo_id=str(photo.legacy_id or photo.id),
                    auto_archived=should_enqueue,
                ),
            )
            session.commit()
            session.refresh(photo)
            if not group_payload:
                group_payload = _group_payload(session, group, verification=verification)
        return _data_center_group_result(
            group_payload,
            changed_fields=["photo.category"],
            delivery_package_job_status=package_status,
            archive_result={"archived": should_enqueue, "group_id": group_id},
        )

    def rescan_data_center_group_photo_barcode(
        self,
        group_id: str,
        photo_id: str,
        *,
        actor: str,
        category: str = "",
        reason: str = "",
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id, lock=True)
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
            now = datetime.now(UTC)
            before = {
                "barcode_rescan_requested_at": str((photo.raw_data or {}).get("barcode_rescan_requested_at") or ""),
            }
            raw_data = dict(photo.raw_data or {})
            raw_data.update(
                {
                    "barcode_rescan_requested_by": actor,
                    "barcode_rescan_requested_at": now.isoformat(),
                }
            )
            if category:
                photo.category = category
                raw_data["category"] = category
            photo.raw_data = raw_data
            verification = invalidate_verification_for_group(
                session,
                group,
                actor=actor,
                reason="group_barcode_rescan_requested",
            )
            from app.services.delivery_cache import invalidate_postgres_delivery_cache_for_group_change

            invalidate_postgres_delivery_cache_for_group_change(
                session,
                group,
                actor=actor,
                reason="group_barcode_rescan_requested",
            )
            after = {
                "barcode_rescan_requested_at": now.isoformat(),
                "barcode_verification_status": verification.get("status"),
            }
            _stage_transactional_audit(
                session,
                team_id=group.team_id,
                actor=actor,
                action="group_barcode_rescan_requested",
                entity_type="photo",
                entity_id=photo.id,
                before_data=before,
                after_data=after,
                payload=_data_center_audit_payload(
                    source_page=source_page,
                    actor=actor,
                    reason=reason or "group_barcode_rescan_requested",
                    before=before,
                    after=after,
                    group_id=str(group.legacy_id or group.id),
                    photo_id=str(photo.legacy_id or photo.id),
                    status=verification.get("status", "pending"),
                    should_enqueue=bool(verification.get("should_enqueue")),
                ),
            )
            session.commit()
            session.refresh(photo)
            return _photo_payload(photo)

    def scan_data_center_group_photo_region(
        self,
        group_id: str,
        photo_id: str,
        *,
        barcode_type: str,
        region: Mapping[str, Any],
        actor: str,
        reason: str = "",
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id, lock=False)
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
            return photo_barcode_check.scan_photo_region(_photo_payload(photo), barcode_type, dict(region))

    def manual_confirm_group_barcode(
        self,
        group_id: str,
        *,
        actor: str,
        reason: str,
        source_page: str = "data_center",
        meter_no: str,
        module_asset_no: str,
        collector: str,
        photo_ids: list[str],
    ) -> dict[str, Any]:
        self.confirm_group_barcode_manually(
            group_id,
            actor=actor,
            meter_no=meter_no,
            module_asset_no=module_asset_no,
            collector=collector,
            reason=reason,
            photo_ids=photo_ids,
            source_page=source_page,
            require_claim=False,
        )
        from app.services.barcode_maintenance_worker import auto_archive_verified_group
        from app.services.delivery_package_queue import DeliveryPackageNotReady

        archive_result = auto_archive_verified_group(group_id, actor=actor)
        group_payload = self.get_group(group_id) or {}
        package_status = ""
        if archive_result.get("archived") or _data_center_archive_status(group_payload) == "archived":
            try:
                self.request_final_delivery_export(
                    task_id=int(group_payload.get("task_id") or 0) or None,
                    terminal=str(group_payload.get("terminal") or ""),
                    review_scope="reviewed",
                    requested_by=actor,
                )
                package_status = "ready"
            except DeliveryPackageNotReady as exc:
                package_status = exc.status
        return _data_center_group_result(
            group_payload,
            delivery_package_job_status=package_status,
            archive_result=archive_result,
        )

    def finalize_unmatched_to_group(
        self,
        unmatched_id: str,
        *,
        actor: str,
        terminal: str,
        meter_no: str,
        candidate_key: str,
        expected_version: int,
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        _reject_placeholder_or_ambiguous_data_center_target(
            terminal=terminal,
            meter_no=meter_no,
            candidate_key=candidate_key,
        )
        return self.finalize_unmatched_match(
            unmatched_id,
            actor=actor,
            candidate_key=candidate_key,
            expected_version=expected_version,
            source_page=source_page,
        )

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
            return _task_payload(task, self._task_payload_stats(session, task))

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
            return _task_payload(task, self._task_payload_stats(session, task))

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
                        "payload": unmatched_review.redact_audit_photo_secrets(
                            row.payload or row.after_data or {}
                        ),
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
        _stage_transactional_audit(
            session,
            team_id=local_simulation.current_team_id(),
            actor=actor,
            action=event_type,
            entity_type="construction_activity",
            payload=event_payload,
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
            return _construction_task_payload(task, self._task_payload_stats(session, task))

    def import_construction_priorities(self, rows: list[Any], *, actor: str, confirm: bool) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        terminals = sorted({str(row.terminal or "") for row in rows if str(row.terminal or "")})
        with self._session() as session:
            if not confirm:
                task_by_terminal = {
                    str(task.terminal or ""): task
                    for task in session.scalars(select(Task).where(Task.team_id == team_id, Task.terminal.in_(terminals))).all()
                }
                task_ids = [int(task.legacy_id) for task in task_by_terminal.values() if task.legacy_id is not None]
                stats_by_task = self._construction_priority_stats_map(session, team_id, task_ids)
                items = self._classify_construction_priority_import_rows(rows, task_by_terminal, stats_by_task)
                counts = _construction_priority_import_counts(items)
                return {"counts": counts, "items": items, "confirmed": False}
            if any(row.status in {"conflict", "malformed"} for row in rows):
                raise ValueError("Priority import contains conflict or malformed rows")
            locked_tasks = session.scalars(
                select(Task)
                .where(Task.team_id == team_id, Task.terminal.in_(terminals))
                .order_by(Task.terminal, Task.legacy_id)
                .with_for_update()
            ).all()
            locked_by_terminal = {str(task.terminal or ""): task for task in locked_tasks}
            locked_task_ids = [int(task.legacy_id) for task in locked_tasks if task.legacy_id is not None]
            locked_stats_by_task = self._construction_priority_stats_map(session, team_id, locked_task_ids)
            items = self._classify_construction_priority_import_rows(rows, locked_by_terminal, locked_stats_by_task)
            for item in items:
                if item["status"] != "valid" or not bool(item["priority"]):
                    continue
                task = locked_by_terminal[item["terminal"]]
                construction_available, _review_available = construction_task_availability(
                    locked_stats_by_task.get(int(task.legacy_id or 0), _empty_task_stats())
                )
                if not construction_available:
                    raise ValueError("Construction priority is only available while construction remains available")
            for item in items:
                if item["status"] != "valid":
                    continue
                task = locked_by_terminal[item["terminal"]]
                before = bool(task.construction_priority)
                task.construction_priority = bool(item["priority"])
                task.construction_priority_updated_by = actor
                task.construction_priority_updated_at = datetime.now(UTC)
                _stage_transactional_audit(session, team_id=team_id, actor=actor, action="construction_priority_updated", entity_type="task", entity_id=task.id, before_data={"construction_priority": before}, after_data={"construction_priority": bool(item["priority"]), "source": "import"}, payload={"task_id": task.legacy_id, "terminal": task.terminal or "", "before": before, "after": bool(item["priority"])})
            counts = _construction_priority_import_counts(items)
            _stage_transactional_audit(session, team_id=team_id, actor=actor, action="construction_priority_imported", entity_type="construction_priority_import", payload={"counts": counts})
            session.commit()
            return {"counts": counts, "items": items, "confirmed": True}

    @staticmethod
    def _classify_construction_priority_import_rows(
        rows: list[Any],
        task_by_terminal: dict[str, Task],
        stats_by_task: Mapping[int, Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        items = []
        for row in rows:
            item = {
                "row_number": row.row_number,
                "terminal": row.terminal,
                "priority": row.priority,
                "status": row.status,
                "reason": row.message,
            }
            task = task_by_terminal.get(row.terminal)
            if item["status"] in {"conflict", "malformed", "duplicate"}:
                items.append(item)
                continue
            if task is None:
                item["status"] = "unknown"
            else:
                stats = stats_by_task.get(int(task.legacy_id or 0), _empty_task_stats())
                total = int(stats.get("total_groups") or 0)
                uploaded = int(stats.get("uploaded_count") or 0)
                if total <= 0 or uploaded >= total:
                    item["status"] = "completed"
                elif bool(task.construction_priority) == bool(row.priority):
                    item["status"] = "unchanged"
                else:
                    item["task_id"] = task.legacy_id
            items.append(item)
        return items

    def close_construction_task(self, task_id: int, actor: str) -> dict[str, Any]:
        with self._session() as session:
            task = self._task_by_legacy_id(session, task_id, lock=True)
            task.construction_enabled = False
            task.construction_closed_at = datetime.now(UTC)
            session.commit()
            session.refresh(task)
            return _construction_task_payload(task, self._task_payload_stats(session, task))

    def set_construction_task_priority(
        self,
        task_id: int,
        *,
        actor: str,
        priority: bool,
    ) -> dict[str, Any]:
        actor = actor.strip() or "admin"
        priority = bool(priority)
        with self._session() as session:
            task = self._task_by_legacy_id(session, task_id, lock=True)
            stats = self._task_stats(session, task)
            construction_available, _review_available = construction_task_availability(stats)
            if priority and not construction_available:
                raise ValueError("Construction priority is only available while construction remains available")
            before = bool(task.construction_priority)
            if before != priority:
                now = datetime.now(UTC)
                task.construction_priority = priority
                task.construction_priority_updated_by = actor
                task.construction_priority_updated_at = now
                _stage_transactional_audit(
                    session,
                    team_id=task.team_id or local_simulation.current_team_id(),
                    actor=actor,
                    action="construction_priority_updated",
                    entity_type="task",
                    entity_id=task.id,
                    before_data={"construction_priority": before},
                    after_data={"construction_priority": priority},
                    payload={
                        "task_id": task.legacy_id if task.legacy_id is not None else str(task.id),
                        "terminal": task.terminal or "",
                        "before": before,
                        "after": priority,
                    },
                )
            session.commit()
            session.refresh(task)
            return _construction_task_payload(task, self._task_payload_stats(session, task))

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
            return _construction_task_payload(task, self._task_payload_stats(session, task))

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
            return _construction_task_payload(task, self._task_payload_stats(session, task))

    def claim_construction_task(self, task_id: int, actor: str) -> dict[str, Any]:
        actor = actor.strip() or "constructor"
        with self._session() as session:
            task = self._task_by_legacy_id(session, task_id)
            if not task.construction_enabled:
                raise ValueError("该终端尚未开放施工")
            if task.construction_claimed_by != actor:
                raise ValueError("Construction task must be assigned by an administrator before entry")
            return _construction_task_payload(task, self._task_payload_stats(session, task))

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
            return _construction_task_payload(task, self._task_payload_stats(session, task))

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
            invalidate_verification_for_group(
                session,
                group,
                actor=actor,
                reason="construction_exception_submitted",
            )
            from app.services.delivery_cache import invalidate_postgres_delivery_cache_for_group_change

            invalidate_postgres_delivery_cache_for_group_change(
                session,
                group,
                actor=actor,
                reason="construction_exception_submitted",
            )
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

    def _enqueue_delivery_cache_after_commit(
        self,
        group_id: str,
        *,
        actor: str,
        reason: str,
        require_eligible: bool = False,
    ) -> None:
        from app.services.delivery_cache import (
            enqueue_postgres_delivery_cache_job,
            sync_postgres_delivery_cache_job_for_group,
        )

        try:
            with self._session() as session:
                group = self._group_by_legacy_id(session, group_id, lock=True)
                group_payload = _group_payload(session, group)
                if require_eligible:
                    sync_postgres_delivery_cache_job_for_group(
                        session,
                        group,
                        group_payload=group_payload,
                        actor=actor,
                        reason=reason,
                    )
                    session.commit()
                    return
                enqueue_postgres_delivery_cache_job(
                    session,
                    group,
                    actor=actor,
                    reason=reason,
                )
                session.commit()
        except Exception as exc:
            logger.exception("Failed to enqueue delivery cache for reviewed group %s", group_id)
            try:
                with self._session() as session:
                    group = self._group_by_legacy_id(session, group_id, lock=True)
                    raw_data = dict(group.raw_data or {})
                    raw_data.update(
                        {
                            "delivery_cache_status": "retry_pending",
                            "delivery_cache_error": "delivery cache enqueue failed",
                            "delivery_cache_retryable": True,
                            "delivery_cache_retry_requested_at": datetime.now(UTC).isoformat(),
                            "delivery_cache_error_type": type(exc).__name__,
                        }
                    )
                    group.raw_data = raw_data
                    _stage_transactional_audit(
                        session,
                        team_id=group.team_id,
                        actor="system",
                        action="delivery_cache_submission_failed",
                        entity_type="material_group",
                        entity_id=group.id,
                        payload={
                            "group_id": group.legacy_id,
                            "retryable": True,
                            "error_type": type(exc).__name__,
                        },
                    )
                    session.commit()
            except Exception:
                logger.exception("Failed to persist delivery-cache retry state for group %s", group_id)

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
            if status != "approved":
                from app.services.delivery_cache import (
                    invalidate_postgres_delivery_cache_for_group_change,
                )

                invalidate_postgres_delivery_cache_for_group_change(
                    session,
                    group,
                    actor=reviewer,
                    reason=f"review_{status}",
                )
            session.commit()
            session.refresh(group)
            result = _group_payload(session, group)
        if status == "approved":
            self._enqueue_delivery_cache_after_commit(
                group_id,
                actor=reviewer,
                reason="review_completed",
            )
        return result

    def classify_photo(self, group_id: str, photo_id: str, category: str, reviewer: str) -> dict[str, Any]:
        if category not in local_simulation.PHOTO_CATEGORIES:
            raise ValueError(f"Unsupported photo category: {category}")
        artifact_change_reason = ""
        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id, lock=True)
            self._ensure_task_claimed_by(session, group, reviewer)
            photo = session.scalar(
                select(Photo).where(
                    Photo.team_id == local_simulation.current_team_id(),
                    Photo.group_id == group.id,
                    Photo.legacy_id == photo_id,
                    Photo.is_active.is_(True),
                ).with_for_update()
            )
            if photo is None:
                raise KeyError(photo_id)
            previous_category = str(photo.category or "unclassified")
            previous_archive = (
                str(photo.archive_status or ""),
                str(photo.archive_filename or ""),
                photo.archived_at.isoformat() if photo.archived_at else "",
            )
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
            archive_changed = previous_archive != (
                str(photo.archive_status or ""),
                str(photo.archive_filename or ""),
                photo.archived_at.isoformat() if photo.archived_at else "",
            )
            if previous_category != category:
                _stage_transactional_audit(
                    session,
                    team_id=group.team_id,
                    actor=reviewer,
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
                        "invalidation_reason": "photo_category_changed",
                    },
                )
                invalidate_verification_for_group(
                    session,
                    group,
                    actor=reviewer,
                    reason="photo_category_changed",
                )
            if archive_changed:
                artifact_change_reason = (
                    "photo_category_changed" if previous_category != category else "photo_archive_changed"
                )
                from app.services.delivery_cache import invalidate_postgres_delivery_cache_for_group_change

                invalidate_postgres_delivery_cache_for_group_change(
                    session,
                    group,
                    actor=reviewer,
                    reason=artifact_change_reason,
                )
            session.commit()
            session.refresh(photo)
            result = _photo_payload(photo)
        if artifact_change_reason:
            self._enqueue_delivery_cache_after_commit(
                group_id,
                actor=reviewer,
                reason=artifact_change_reason,
                require_eligible=True,
            )
        return result

    def rescan_photo_barcode(
        self,
        group_id: str,
        photo_id: str,
        reviewer: str,
        category: str = "",
    ) -> dict[str, Any]:
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
            now = datetime.now(UTC)
            raw_data = dict(photo.raw_data or {})
            raw_data.update(
                {
                    "barcode_rescan_requested_by": reviewer,
                    "barcode_rescan_requested_at": now.isoformat(),
                }
            )
            photo.raw_data = raw_data
            verification = invalidate_verification_for_group(
                session,
                group,
                actor=reviewer,
                reason="group_barcode_rescan_requested",
            )
            from app.services.delivery_cache import invalidate_postgres_delivery_cache_for_group_change

            invalidate_postgres_delivery_cache_for_group_change(
                session,
                group,
                actor=reviewer,
                reason="group_barcode_rescan_requested",
            )
            _stage_transactional_audit(
                session,
                team_id=local_simulation.current_team_id(),
                actor=reviewer,
                action="group_barcode_rescan_requested",
                entity_type="photo",
                entity_id=photo.id,
                before_data={},
                after_data={"barcode_verification_status": verification.get("status")},
                payload={
                    "group_id": group.legacy_id or str(group.id),
                    "photo_id": photo.legacy_id or str(photo.id),
                    "status": verification.get("status", "pending"),
                    "should_enqueue": bool(verification.get("should_enqueue")),
                },
            )
            session.commit()
            session.refresh(photo)
            return _photo_payload(photo)

    def apply_group_scan_result(
        self,
        group_id: str,
        result: Any,
        *,
        claimed_evidence_fingerprint: str,
        claimed_evidence_version: int,
        lease_owner: str,
        lease_token: str,
        actor: str,
    ) -> dict[str, Any]:
        from app.services.group_barcode_verification import apply_group_scan_result, mark_auto_archive_pending

        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id, lock=True)
            verification = session.scalar(
                select(GroupBarcodeVerification)
                .where(
                    GroupBarcodeVerification.team_id == group.team_id,
                    GroupBarcodeVerification.group_id == group.id,
                )
                .with_for_update()
            )
            if verification is None:
                return {"applied": False, "verification": {}}

            raw_data = dict(group.raw_data or {})
            persisted = raw_data.get("barcode_verification")
            persisted = dict(persisted) if isinstance(persisted, Mapping) else {}
            current = {
                **persisted,
                "status": verification.status,
                "evidence_fingerprint": verification.evidence_fingerprint,
                "evidence_version": verification.evidence_version,
                "meter_matched": verification.meter_matched,
                "module_matched": verification.module_matched,
                "collector_matched": verification.collector_matched,
                "recognition_source": verification.recognition_source,
                "attempt_count": verification.attempt_count,
                "lease_owner": verification.lease_owner,
                "lease_token": verification.lease_token,
                "lease_expires_at": verification.lease_expires_at,
            }
            verification_group_payload = _verification_group_payload(session, group)
            applied = apply_group_scan_result(
                current,
                verification_group_payload,
                result,
                claimed_evidence_fingerprint=claimed_evidence_fingerprint,
                claimed_evidence_version=claimed_evidence_version,
                lease_owner=lease_owner,
                lease_token=lease_token,
                actor=actor,
            )
            next_verification = dict(applied["verification"])
            if next_verification == current:
                return applied

            before_data = dict(current)
            verification.status = str(next_verification.get("status") or verification.status)
            verification.evidence_fingerprint = next_verification.get("evidence_fingerprint")
            verification.evidence_version = int(next_verification.get("evidence_version") or 0)
            verification.attempt_count = int(next_verification.get("attempt_count") or 0)
            verification.lease_owner = next_verification.get("lease_owner")
            verification.lease_token = next_verification.get("lease_token")
            verification.lease_expires_at = next_verification.get("lease_expires_at")
            if applied["applied"]:
                scan_result = next_verification.get("result") or {}
                matched_fields = set(scan_result.get("matched_fields") or [])
                verification.meter_matched = "meter" in matched_fields
                verification.module_matched = "module" in matched_fields
                verification.collector_matched = "collector" in matched_fields
                if scan_result.get("machine_qr_values") and not scan_result.get("machine_barcode_values"):
                    verification.recognition_source = "machine_qr"
                elif scan_result.get("machine_barcode_values") or scan_result.get("machine_qr_values"):
                    verification.recognition_source = "machine_barcode"
                elif scan_result.get("ocr_candidates"):
                    verification.recognition_source = "ocr_candidate"
                else:
                    verification.recognition_source = "none"
                next_verification["meter_matched"] = verification.meter_matched
                next_verification["module_matched"] = verification.module_matched
                next_verification["collector_matched"] = verification.collector_matched
                next_verification["recognition_source"] = verification.recognition_source
                next_verification = mark_auto_archive_pending(next_verification)
                verification.auto_archive_status = next_verification.get("auto_archive_status")
                verification.auto_archive_attempt_count = int(
                    next_verification.get("auto_archive_attempt_count") or 0
                )
                verification.auto_archive_lease_owner = next_verification.get("auto_archive_lease_owner")
                verification.auto_archive_lease_token = next_verification.get("auto_archive_lease_token")
                verification.auto_archive_lease_expires_at = next_verification.get("auto_archive_lease_expires_at")
                verification.auto_archive_error = next_verification.get("auto_archive_error") or None
                applied["verification"] = next_verification
            else:
                verification.meter_matched = None
                verification.module_matched = None
                verification.collector_matched = None
                verification.recognition_source = None
                verification.invalidation_reason = next_verification.get("invalidation_reason")
                verification.invalidated_by = next_verification.get("invalidated_by")
                verification.invalidated_at = datetime.now(UTC)
                next_verification.update(
                    {
                        "meter_matched": None,
                        "module_matched": None,
                        "collector_matched": None,
                        "recognition_source": None,
                        "invalidated_at": verification.invalidated_at.isoformat(),
                    }
                )
            raw_data["barcode_verification"] = next_verification
            group.raw_data = raw_data
            audit_group = {**raw_data, **verification_group_payload}
            _stage_transactional_audit(
                session,
                team_id=group.team_id,
                actor=actor,
                action="group_barcode_scan_result_applied" if applied["applied"] else "group_barcode_scan_result_rejected",
                entity_type="material_group",
                entity_id=group.id,
                before_data=local_simulation._manual_confirmation_audit_snapshot(audit_group, before_data),
                after_data=local_simulation._manual_confirmation_audit_snapshot(audit_group, next_verification),
                payload={"group_id": group.legacy_id or str(group.id)},
            )
            session.commit()
            session.refresh(group)
            applied["verification"] = next_verification
            return applied

    def confirm_group_barcode_manually(
        self,
        group_id: str,
        *,
        actor: str,
        meter_no: str,
        module_asset_no: str,
        collector: str,
        reason: str,
        photo_ids: list[str],
        source_page: str = "",
        require_claim: bool = True,
    ) -> dict[str, Any]:
        from app.services.group_barcode_verification import evaluate_group_eligibility

        identity_changed = False
        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id, lock=True)
            if require_claim:
                self._ensure_task_claimed_by(session, group, actor)
            formal_values = {
                "meter_no": meter_no.strip(),
                "module_asset_no": module_asset_no.strip(),
                "collector": collector.strip(),
            }
            for field, value in formal_values.items():
                local_simulation.validate_real_formal_identity_value(value, field)
            reason = reason.strip()
            if not reason:
                raise ValueError("人工确认原因不能为空")
            selected_ids = [str(photo_id).strip() for photo_id in photo_ids if str(photo_id).strip()]
            active_photos = session.scalars(
                select(Photo).where(
                    Photo.team_id == group.team_id,
                    Photo.group_id == group.id,
                    Photo.is_active.is_(True),
                )
            ).all()
            evidence_by_id = local_simulation._manual_confirmation_evidence(
                [_photo_payload(photo) for photo in active_photos]
            )
            if (
                not selected_ids
                or len(selected_ids) != len(set(selected_ids))
                or any(photo_id not in evidence_by_id for photo_id in selected_ids)
            ):
                raise ValueError("人工确认照片证据无效")
            now = datetime.now(UTC)
            raw_data = dict(group.raw_data or {})
            previous_identity = (
                str(group.display_meter_no or ""),
                str(raw_data.get("module_asset_no") or raw_data.get("construction_module_asset_no") or ""),
                str(raw_data.get("collector") or raw_data.get("construction_collector") or ""),
                str(group.meter_match_key or raw_data.get("meter_match_key") or ""),
            )
            verification = session.scalar(
                select(GroupBarcodeVerification)
                .where(
                    GroupBarcodeVerification.team_id == group.team_id,
                    GroupBarcodeVerification.group_id == group.id,
                )
                .with_for_update()
            )
            persisted_verification = raw_data.get("barcode_verification")
            persisted_verification = (
                dict(persisted_verification) if isinstance(persisted_verification, Mapping) else {}
            )
            before_verification = {
                **persisted_verification,
                "status": verification.status if verification else str(persisted_verification.get("status") or ""),
                "evidence_fingerprint": verification.evidence_fingerprint if verification else persisted_verification.get("evidence_fingerprint"),
                "evidence_version": verification.evidence_version if verification else int(persisted_verification.get("evidence_version") or 0),
                "meter_matched": verification.meter_matched if verification else None,
                "module_matched": verification.module_matched if verification else None,
                "collector_matched": verification.collector_matched if verification else None,
                "recognition_source": verification.recognition_source if verification else str(persisted_verification.get("recognition_source") or ""),
                "lease_owner": verification.lease_owner if verification else None,
                "lease_token": verification.lease_token if verification else None,
                "lease_expires_at": verification.lease_expires_at if verification else None,
            }
            before_data = local_simulation._manual_confirmation_audit_snapshot(
                {
                    **raw_data,
                    "meter_no": group.display_meter_no,
                    "module_asset_no": raw_data.get("module_asset_no") or "",
                    "collector": raw_data.get("collector") or "",
                },
                before_verification,
            )
            raw_data.update(
                {
                    **formal_values,
                    "meter_match_key": build_total_catalog_match_key(formal_values["meter_no"]),
                    "construction_collector": formal_values["collector"],
                    "construction_module_asset_no": formal_values["module_asset_no"],
                    "group_barcode_manual_confirmed": True,
                    "group_barcode_manual_confirmed_fields": list(photo_barcode_check.GROUP_BARCODE_TYPES),
                    "group_barcode_manual_confirmed_by": actor,
                    "group_barcode_manual_confirmed_at": now.isoformat(),
                    "group_barcode_manual_confirmation_reason": reason,
                    "group_barcode_manual_confirmation_photo_ids": selected_ids,
                }
            )
            group.display_meter_no = formal_values["meter_no"]
            group.meter_match_key = build_total_catalog_match_key(formal_values["meter_no"])
            group.exception_reasons = local_simulation._without_barcode_exception_reasons(group.exception_reasons or [])
            group.has_archive_blocker = bool(group.exception_reasons)
            raw_data["exception_reasons"] = list(group.exception_reasons)
            raw_data["manual_preserved_exception_reasons"] = list(group.exception_reasons)
            raw_data["has_archive_blocker"] = group.has_archive_blocker
            for photo in active_photos:
                photo.barcode = formal_values["meter_no"]
                photo.collector = formal_values["collector"]
                photo.asset_no = formal_values["module_asset_no"]
                photo_raw = dict(photo.raw_data or {})
                photo_raw.update(
                    {
                        "barcode": formal_values["meter_no"],
                        "collector": formal_values["collector"],
                        "asset_no": formal_values["module_asset_no"],
                        "module_asset_no": formal_values["module_asset_no"],
                    }
                )
                photo.raw_data = photo_raw
            group.raw_data = raw_data
            final_eligibility = evaluate_group_eligibility(_verification_group_payload(session, group))
            if final_eligibility.status != "pending" or not final_eligibility.evidence_fingerprint:
                raise ValueError("资料组最终证据不满足人工确认条件")
            if verification is None:
                verification = GroupBarcodeVerification(
                    team_id=group.team_id,
                    group_id=group.id,
                    evidence_version=0,
                )
                session.add(verification)
            verification.status = "manual_confirmed"
            verification.evidence_fingerprint = final_eligibility.evidence_fingerprint
            verification.evidence_version = int(verification.evidence_version or 0) + 1
            verification.meter_matched = True
            verification.module_matched = True
            verification.collector_matched = True
            verification.recognition_source = "manual_confirmed"
            verification.lease_owner = None
            verification.lease_token = None
            verification.lease_expires_at = None
            verification.auto_archive_status = "pending"
            verification.auto_archive_attempt_count = 0
            verification.auto_archive_lease_owner = None
            verification.auto_archive_lease_token = None
            verification.auto_archive_lease_expires_at = None
            verification.auto_archive_error = None
            next_result = dict(before_verification.get("result") or {})
            next_result.update(
                {
                    "passed_count": 3,
                    "matched_fields": list(photo_barcode_check.GROUP_BARCODE_TYPES),
                    "missing_fields": [],
                }
            )
            next_verification = {
                **before_verification,
                "status": "manual_confirmed",
                "evidence_fingerprint": final_eligibility.evidence_fingerprint,
                "evidence_version": verification.evidence_version,
                "meter_matched": True,
                "module_matched": True,
                "collector_matched": True,
                "recognition_source": "manual_confirmed",
                "lease_owner": None,
                "lease_token": None,
                "lease_expires_at": None,
                "should_enqueue": False,
                "auto_archive_status": "pending",
                "auto_archive_attempt_count": 0,
                "auto_archive_lease_owner": None,
                "auto_archive_lease_token": None,
                "auto_archive_lease_expires_at": None,
                "auto_archive_error": "",
                "result": next_result,
            }
            raw_data["barcode_verification"] = next_verification
            group.raw_data = raw_data
            identity_changed = previous_identity != (
                formal_values["meter_no"],
                formal_values["module_asset_no"],
                formal_values["collector"],
                build_total_catalog_match_key(formal_values["meter_no"]),
            )
            if identity_changed:
                from app.services.delivery_cache import invalidate_postgres_delivery_cache_for_group_change

                invalidate_postgres_delivery_cache_for_group_change(
                    session,
                    group,
                    actor=actor,
                    reason="manual_barcode_identity_changed",
                )
            after_data = local_simulation._manual_confirmation_audit_snapshot(
                {**raw_data, "meter_no": formal_values["meter_no"]},
                next_verification,
            )
            _stage_transactional_audit(
                session,
                team_id=local_simulation.current_team_id(),
                actor=actor,
                action="group_barcode_manual_confirmed",
                entity_type="material_group",
                entity_id=group.id,
                before_data=before_data,
                after_data=after_data,
                payload=_data_center_audit_payload(
                    source_page=source_page or "admin",
                    actor=actor,
                    reason=reason,
                    before=before_data,
                    after=after_data,
                    group_id=group.legacy_id or str(group.id),
                    fields=raw_data["group_barcode_manual_confirmed_fields"],
                    confirmed_at=raw_data["group_barcode_manual_confirmed_at"],
                    photo_ids=selected_ids,
                    formal_values={
                        field: _mask_barcode_audit_value(value) for field, value in formal_values.items()
                    },
                ),
            )
            session.commit()
            session.refresh(group)
            result = {"group": _group_target_summary(_group_payload(session, group, include_photos=True), include_photos=True)}
        if identity_changed:
            self._enqueue_delivery_cache_after_commit(
                group_id,
                actor=actor,
                reason="manual_barcode_identity_changed",
                require_eligible=True,
            )
        return result

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
            invalidate_verification_for_group(session, group, actor=reviewer, reason="photo_deleted")
            from app.services.delivery_cache import (
                invalidate_postgres_delivery_cache_for_group_change,
            )

            invalidate_postgres_delivery_cache_for_group_change(
                session,
                group,
                actor=reviewer,
                reason="photo_deleted",
            )
            session.commit()
            session.refresh(group)
            result = {"group": _group_payload(session, group), "deleted_photo": deleted_payload}
        self._enqueue_delivery_cache_after_commit(
            group_id,
            actor=reviewer,
            reason="photo_deleted",
            require_eligible=True,
        )
        return result

    def _project_id_for_team(self, session: Session, team_id: str):
        project_id = session.scalar(
            select(Project.id).where(Project.team_id == team_id).order_by(Project.created_at, Project.id).limit(1)
        )
        if project_id is None:
            raise StateBackendNotReady(f"No project exists for team {team_id}")
        return project_id

    def _ensure_task_for_terminal(self, session: Session, team_id: str, terminal: str) -> Task:
        # Finalization always acquires meter identity before this terminal lock; other callers acquire only this lock.
        lock_key = _terminal_task_advisory_lock_key(team_id, terminal)
        session.scalar(select(func.pg_advisory_xact_lock(lock_key)))
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

    def delete_unmatched_record(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int = 1,
        reason: str = "",
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
            review = _checked_unmatched_review(record, expected_version)
            before = _unmatched_payload(record)
            raw = dict(record.payload or {})
            raw["deleted_by"] = actor
            raw["delete_reason"] = reason
            raw["deleted_at"] = datetime.now(UTC).isoformat()
            record.payload = _advance_unmatched_review_payload(raw, review, expected_version)
            payload = _unmatched_payload(record)
            record.status = "deleted"
            _stage_transactional_audit(
                session,
                team_id=record.team_id,
                actor=actor,
                action="unmatched_record_deleted",
                entity_type="unmatched_record",
                entity_id=record.id,
                before_data=before,
                after_data=_unmatched_payload(record),
                payload={"expected_version": expected_version},
            )
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
        expected_version: int = 1,
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
            review = _checked_unmatched_review(record, expected_version)
            before = _unmatched_payload(record)
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
            record_raw = {
                **(record.payload or {}),
                "associated_by": actor,
                "associated_group_id": group.legacy_id,
            }
            record.payload = _advance_unmatched_review_payload(record_raw, review, expected_version)
            _stage_transactional_audit(
                session,
                team_id=record.team_id,
                actor=actor,
                action="unmatched_record_associated",
                entity_type="unmatched_record",
                entity_id=record.id,
                before_data=before,
                after_data=_unmatched_payload(record),
                payload={"expected_version": expected_version, "group_id": group.legacy_id},
            )
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
        expected_version: int = 1,
        terminal: str = "",
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        with self._session() as session:
            try:
                record = session.scalar(
                    select(UnmatchedRecord)
                    .where(
                        UnmatchedRecord.team_id == team_id,
                        UnmatchedRecord.legacy_id == unmatched_id,
                        UnmatchedRecord.status == "open",
                    )
                    .with_for_update()
                )
                if record is None:
                    raise KeyError(unmatched_id)
                review = _checked_unmatched_review(record, expected_version)
                updates = updates or {}
                payload = {**_unmatched_payload(record), **updates}
                terminal_value, meter_no_value = local_simulation.validate_real_formal_identity(
                    terminal or str(payload.get("terminal") or ""),
                    str(payload.get("meter_no") or payload.get("barcode") or ""),
                )
                meter_key = str(payload.get("meter_match_key") or "").strip()
                if not meter_key or (
                    meter_key in local_simulation.FORMAL_IDENTITY_PLACEHOLDERS
                    or meter_key.lower().startswith(local_simulation.FORMAL_IDENTITY_PREFIXES)
                ):
                    if "meter_match_key" in updates:
                        local_simulation.validate_real_formal_identity_value(meter_key, "meter match key")
                    meter_key = local_simulation.build_total_catalog_match_key(meter_no_value) or meter_no_value
                meter_key = local_simulation.validate_real_formal_identity_value(
                    meter_key,
                    "meter match key",
                )
                review = {
                    **review,
                    "meter_no": meter_no_value,
                    "collector": str(payload.get("collector") or review.get("collector") or ""),
                    "module_asset_no": str(
                        payload.get("module_asset_no")
                        or payload.get("asset_no")
                        or review.get("module_asset_no")
                        or ""
                    ),
                }
                candidate = {
                    "candidate_key": f"legacy-create:{unmatched_id}",
                    "target_group_id": "",
                    "terminal": terminal_value,
                    "meter_no": meter_no_value,
                    "meter_match_key": meter_key,
                    "address": str(payload.get("address") or ""),
                }
                group, attached = self._materialize_unmatched_candidate(
                    session,
                    record,
                    review,
                    candidate,
                    actor,
                )
                record.status = "associated"
                record_raw = {
                    **(record.payload or {}),
                    "associated_by": actor,
                    "associated_group_id": group.legacy_id,
                }
                record.payload = _advance_unmatched_review_payload(record_raw, review, expected_version)
                _stage_transactional_audit(
                    session,
                    team_id=team_id,
                    actor=actor,
                    action="create_group_from_unmatched",
                    entity_type="unmatched_record",
                    entity_id=record.id,
                    before_data={"unmatched_id": unmatched_id, "review_version": expected_version},
                    after_data={"group_id": group.legacy_id, "terminal": terminal_value},
                    payload={"attached": attached, "meter_no": meter_no_value},
                )
                task = session.get(Task, group.task_id) if group.task_id else None
                result = {
                    "group": _group_payload(session, group),
                    "task": (
                        _construction_task_payload(task, self._task_stats(session, task))
                        if task is not None
                        else None
                    ),
                    "attached": attached,
                    "added_photos": len(review.get("photos") or []),
                }
                session.commit()
                return result
            except Exception:
                session.rollback()
                raise

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
        terminal_value, meter_no_value = local_simulation.validate_real_formal_identity(terminal, meter_no)
        meter_key_value = local_simulation.validate_real_formal_identity_value(
            meter_match_key or local_simulation.build_total_catalog_match_key(meter_no_value) or meter_no_value,
            "meter match key",
        )
        with self._session() as session:
            project_id = self._project_id_for_team(session, team_id)
            task = self._ensure_task_for_terminal(session, team_id, terminal_value)
            group = MaterialGroup(
                team_id=team_id,
                project_id=project_id,
                legacy_id=_new_formal_group_legacy_id(),
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
            return {
                "group": _group_payload(session, group),
                "task": _construction_task_payload(task, self._task_payload_stats(session, task)),
            }

    def update_group_terminal(self, group_id: str, *, terminal: str, actor: str) -> dict[str, Any]:
        terminal_value = local_simulation.validate_real_formal_identity_value(terminal, "terminal")
        team_id = local_simulation.current_team_id()
        terminal_changed = False
        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id, lock=True)
            previous_terminal = str(group.terminal or "")
            task = self._ensure_task_for_terminal(session, team_id, terminal_value)
            raw = dict(group.raw_data or {})
            raw["previous_terminal"] = previous_terminal
            raw["stage_terminal"] = terminal_value
            raw["terminal_updated_by"] = actor
            group.raw_data = raw
            group.terminal = terminal_value
            group.legacy_task_id = task.legacy_id
            group.task_id = task.id
            terminal_changed = previous_terminal != terminal_value
            if terminal_changed:
                invalidate_verification_for_group(session, group, actor=actor, reason="group_terminal_changed")
                from app.services.delivery_cache import (
                    invalidate_postgres_delivery_cache_for_group_change,
                )

                invalidate_postgres_delivery_cache_for_group_change(
                    session,
                    group,
                    actor=actor,
                    reason="group_terminal_changed",
                )
            session.commit()
            session.refresh(group)
            session.refresh(task)
            result = {
                "group": _group_payload(session, group),
                "task": _construction_task_payload(task, self._task_payload_stats(session, task)),
            }
        if terminal_changed:
            self._enqueue_delivery_cache_after_commit(
                group_id,
                actor=actor,
                reason="group_terminal_changed",
                require_eligible=True,
            )
        return result

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
        existing_by_fingerprint: dict[str, Photo] = {}
        existing_by_sha: dict[str, Photo] = {}
        existing_by_storage: dict[tuple[str, str], Photo] = {}
        existing_by_url_hash: dict[str, Photo] = {}

        def register_duplicate(mapping: dict[Any, Photo], key: Any, photo: Photo) -> None:
            if not key:
                return
            current = mapping.get(key)
            if current is None or (
                getattr(current, "is_active", True) is False
                and getattr(photo, "is_active", True) is not False
            ):
                mapping[key] = photo

        existing_statement = select(Photo).where(Photo.team_id == group.team_id, Photo.group_id == group.id)
        if source == "unmatched-review-finalize":
            existing_statement = existing_statement.with_for_update()
        for photo in session.scalars(existing_statement).all():
            register_duplicate(existing_by_fingerprint, photo.source_fingerprint, photo)
            register_duplicate(existing_by_sha, photo.sha256, photo)
            if photo.storage_type and photo.storage_key:
                register_duplicate(existing_by_storage, (photo.storage_type, photo.storage_key), photo)
            register_duplicate(existing_by_url_hash, getattr(photo, "source_url_hash", None), photo)
            existing_source_url = str(photo.source_url or photo.image_url or "").strip()
            normalized_existing_source_url = local_simulation.normalized_photo_source_url(existing_source_url)
            if normalized_existing_source_url:
                register_duplicate(
                    existing_by_url_hash,
                    hashlib.sha256(normalized_existing_source_url.encode("utf-8")).hexdigest(),
                    photo,
                )
        added = 0
        merged_duplicates = 0
        reactivated_duplicates = 0
        skipped_duplicates = 0
        retained_photo_urls: list[str] = []
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
            declared_sha256 = str(item.get("sha256") or "").strip()
            sha256 = declared_sha256 or hashlib.sha256(image_url.encode("utf-8")).hexdigest()
            source_url = str(item.get("source_url") or image_url)
            normalized_source_url = local_simulation.normalized_photo_source_url(source_url)
            source_url_hash = hashlib.sha256(normalized_source_url.encode("utf-8")).hexdigest()
            fingerprint_seed = "|".join(
                [
                    str(group.legacy_id or group.id),
                    str(item.get("client_photo_id") or ""),
                    str(item.get("source_fingerprint") or ""),
                    normalized_source_url,
                ]
            )
            source_fingerprint = str(item.get("source_fingerprint") or hashlib.sha256(fingerprint_seed.encode("utf-8")).hexdigest()[:32])
            duplicate = (
                existing_by_fingerprint.get(source_fingerprint)
                or existing_by_sha.get(sha256)
                or existing_by_url_hash.get(source_url_hash)
                or (existing_by_storage.get((storage_type, storage_key)) if storage_type and storage_key else None)
            )
            if duplicate is not None:
                skipped_duplicates += 1
                if source == "unmatched-review-finalize":
                    raw_payload = dict(duplicate.raw_data or {})
                    unmatched_review.merge_migrated_photo_evidence(raw_payload, item)
                    if not getattr(duplicate, "is_active", True):
                        active_count += 1
                        duplicate.is_active = True
                        duplicate.deleted_at = None
                        duplicate.deleted_by = ""
                        duplicate.delete_reason = ""
                        duplicate.sort_order = active_count
                        raw_payload.pop("deleted_at", None)
                        raw_payload.pop("deleted_by", None)
                        raw_payload.pop("delete_reason", None)
                        raw_payload["is_active"] = True
                        reactivated_duplicates += 1
                    duplicate.raw_data = raw_payload
                    duplicate.category = str(item.get("category") or duplicate.category or "unclassified")
                    duplicate.source_url = source_url
                    duplicate.source_url_hash = source_url_hash
                    duplicate.source_fingerprint = duplicate.source_fingerprint or source_fingerprint
                    duplicate.image_url = duplicate.image_url or image_url
                    merged_duplicates += 1
                continue
            active_count += 1
            legacy_id = str(item.get("id") or f"p-{group.legacy_id or group.id}-{uuid4().hex[:12]}")
            category = str(item.get("category") or "unclassified")
            raw_payload = dict(item)
            raw_payload.setdefault("sha256_source", "declared" if declared_sha256 else "image_url")
            if source == "construction":
                raw_payload.setdefault("upload_source", "construction-mobile")
                slot = local_simulation.normalize_construction_slot(item.get("slot") or item.get("category"))
                if slot:
                    category = local_simulation.CONSTRUCTION_SLOT_CATEGORIES.get(slot, "other")
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
                source_url_hash=source_url_hash,
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
            register_duplicate(existing_by_fingerprint, source_fingerprint, photo)
            register_duplicate(existing_by_sha, sha256, photo)
            register_duplicate(existing_by_url_hash, source_url_hash, photo)
            if storage_type and storage_key:
                register_duplicate(existing_by_storage, (storage_type, storage_key), photo)
            added += 1
            retained_photo_urls.append(image_url)
        if source == "unmatched-review-finalize" and (added or merged_duplicates):
            group.photo_count = int(active_count)
            _reset_group_after_photo_evidence_change(session, group)
        elif added or reactivated_duplicates:
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
        elif merged_duplicates:
            session.flush()
        if added or merged_duplicates or reactivated_duplicates:
            reason = {
                "construction": "construction_photos_changed",
                "unmatched-review-finalize": "photo_restored_or_replaced",
            }.get(source, "photo_added")
            invalidate_verification_for_group(session, group, actor=actor, reason=reason)
            from app.services.delivery_cache import (
                invalidate_postgres_delivery_cache_for_group_change,
            )

            invalidate_postgres_delivery_cache_for_group_change(
                session,
                group,
                actor=actor,
                reason=reason,
            )
        result = {
            "added": added,
            "skipped_duplicates": skipped_duplicates,
            "merged_duplicates": merged_duplicates,
        }
        if reactivated_duplicates:
            result["reactivated_duplicates"] = reactivated_duplicates
        if source == "manual-photo-import":
            result["retained_photo_urls"] = retained_photo_urls
        return result

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
            local_simulation.assert_not_placeholder_construction_group(
                group_id=group.legacy_id or str(group.id),
                terminal=group.terminal,
                meter_no=group.display_meter_no,
                meter_match_key=group.meter_match_key or "",
                address=group.installation_address,
            )
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
            session.flush()
            response = {"group": _group_payload(session, group), **result}
            session.commit()
            return response

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
            task = session.scalar(select(Task).where(Task.id == group.task_id).with_for_update())
            if task is None:
                raise ValueError("Construction task must be claimed by the current constructor before upload")
            local_simulation.assert_not_placeholder_construction_group(
                group_id=group.legacy_id or str(group.id),
                terminal=task.terminal,
                meter_no=group.display_meter_no,
                meter_match_key=group.meter_match_key or "",
                address=group.installation_address,
            )
            if task.construction_claimed_by != actor:
                raise ValueError("Construction task must be claimed by the current constructor before upload")
            if client_completed_at:
                for photo in photos:
                    photo.setdefault("client_completed_at", client_completed_at)
            raw = dict(group.raw_data or {})
            normalized_collector = str(collector or "").strip()
            normalized_module_asset_no = str(module_asset_no or "").strip()
            previous_identity = (
                str(raw.get("construction_collector") or "").strip(),
                str(raw.get("construction_module_asset_no") or "").strip(),
            )
            next_identity = (
                normalized_collector or previous_identity[0],
                normalized_module_asset_no or previous_identity[1],
            )
            identity_changed = next_identity != previous_identity
            if normalized_collector:
                raw["construction_collector"] = normalized_collector
            if normalized_module_asset_no:
                raw["construction_module_asset_no"] = normalized_module_asset_no
            group.raw_data = raw
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
            evidence_changed = any(
                int(result.get(key) or 0) > 0
                for key in ("added", "merged_duplicates", "reactivated_duplicates")
            )
            if identity_changed and not evidence_changed:
                invalidate_verification_for_group(
                    session,
                    group,
                    actor=actor,
                    reason="construction_identity_changed",
                )
                from app.services.delivery_cache import (
                    invalidate_postgres_delivery_cache_for_group_change,
                )

                invalidate_postgres_delivery_cache_for_group_change(
                    session,
                    group,
                    actor=actor,
                    reason="construction_identity_changed",
                )
            session.flush()
            task_stats = self._task_stats(session, task)
            construction_available, _review_available = construction_task_availability(task_stats)
            if task.construction_priority and not construction_available:
                task.construction_priority = False
                task.construction_priority_updated_by = actor
                task.construction_priority_updated_at = datetime.now(UTC)
                _stage_transactional_audit(
                    session,
                    team_id=task.team_id or local_simulation.current_team_id(),
                    actor=actor,
                    action="construction_priority_auto_cleared",
                    entity_type="task",
                    entity_id=task.id,
                    before_data={"construction_priority": True},
                    after_data={"construction_priority": False},
                    payload={
                        "task_id": task.legacy_id if task.legacy_id is not None else str(task.id),
                        "terminal": task.terminal or "",
                        "uploaded_count": int(task_stats.get("uploaded_count") or 0),
                        "total_groups": int(task_stats.get("total_groups") or 0),
                    },
                )
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
            session.refresh(task)
            return {
                "group": _group_payload(session, group),
                "task": _construction_task_payload(task, self._task_payload_stats(session, task)),
                **result,
            }

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

    def _repair_delivery_cache_groups(self, group_ids: list[str], *, reason: str) -> None:
        from app.services.delivery_cache import (
            _delivery_job_has_live_lease,
            enqueue_postgres_delivery_cache_job,
        )

        unique_group_ids = sorted({str(group_id).strip() for group_id in group_ids if str(group_id).strip()})
        if not unique_group_ids:
            return
        with self._session() as session:
            try:
                groups = session.scalars(
                    select(MaterialGroup)
                    .where(
                        MaterialGroup.team_id == local_simulation.current_team_id(),
                        MaterialGroup.legacy_id.in_(unique_group_ids),
                    )
                    .order_by(MaterialGroup.id)
                    .with_for_update(of=MaterialGroup)
                ).all()
                groups_by_id = {group.id: group for group in groups}
                jobs = []
                if groups_by_id:
                    jobs = session.scalars(
                        select(DeliveryCacheJob)
                        .where(
                            DeliveryCacheJob.team_id == local_simulation.current_team_id(),
                            DeliveryCacheJob.group_id.in_(list(groups_by_id)),
                        )
                        .order_by(DeliveryCacheJob.group_id, DeliveryCacheJob.id)
                        .with_for_update(of=DeliveryCacheJob)
                    ).all()
                jobs_by_group = {job.group_id: job for job in jobs}
                now = datetime.now(UTC)
                for group in groups:
                    existing_job = jobs_by_group.get(group.id)
                    if existing_job is not None and _delivery_job_has_live_lease(existing_job, now=now):
                        continue
                    enqueue_postgres_delivery_cache_job(
                        session,
                        group,
                        actor=str(group.reviewer or "system"),
                        reason=reason,
                        existing_job=existing_job,
                    )
                session.commit()
            except Exception:
                session.rollback()
                raise

    def request_final_delivery_export(
        self,
        *,
        task_id: int | None = None,
        terminal: str = "",
        review_scope: str = "reviewed",
        requested_by: str = "",
    ) -> LeasedDeliveryPackage:
        from app.services.delivery_package_queue import request_postgres_delivery_package

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
            return request_postgres_delivery_package(
                session,
                groups=groups,
                team_id=team_id,
                task_id=task_id,
                terminal=terminal,
                review_scope=review_scope,
                requested_by=requested_by,
            )

    def build_final_delivery_export(
        self,
        *,
        task_id: int | None = None,
        terminal: str = "",
        review_scope: str = "reviewed",
    ) -> LeasedDeliveryPackage:
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
        scope = f"{team_id}|task={task_id or ''}|terminal={terminal}|review_scope={review_scope}"
        return local_simulation.build_final_delivery_package_from_groups(
            groups,
            scope=scope,
            archived_only=review_scope == "reviewed",
            repair_delivery_cache=self._repair_delivery_cache_groups,
        )

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
        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id)
            payload = _group_payload(session, group, include_photos=True)
        photo = next(
            (item for item in payload.get("photos", []) if str(item.get("id") or "") == photo_id),
            None,
        )
        if photo is None:
            raise KeyError(photo_id)
        return local_simulation.get_delivery_cached_photo_path_from_payload(payload, photo)

    def reset_group_to_unconstructed(
        self,
        group_id: str,
        *,
        actor: str,
        reason: str = "",
        force: bool = False,
        source_page: str = "",
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
            for key in ("constructor",):
                raw_data.pop(key, None)
            raw_data.update(
                {
                    "status": "pending",
                    "reset_to_unconstructed_reason": reason,
                    "construction_collector": "",
                    "construction_module_asset_no": "",
                    "collector": "",
                    "module_asset_no": "",
                    "asset_no": "",
                    "group_barcode_manual_confirmed": False,
                    "group_barcode_manual_confirmed_fields": [],
                    "group_barcode_manual_confirmed_by": "",
                    "group_barcode_manual_confirmed_at": "",
                }
            )
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
            invalidate_verification_for_group(session, group, actor=actor, reason="reset_to_unconstructed")
            from app.services.delivery_cache import (
                invalidate_postgres_delivery_cache_for_group_change,
            )

            invalidate_postgres_delivery_cache_for_group_change(
                session,
                group,
                actor=actor,
                reason="reset_to_unconstructed",
            )
            after = {
                "status": "pending",
                "photo_count": 0,
                "reviewer": "",
                "review_note": "",
                "exception_note": "",
                "collector": "",
                "module_asset_no": "",
                "construction_collector": "",
                "construction_module_asset_no": "",
                "group_barcode_manual_confirmed": False,
            }
            _stage_transactional_audit(
                session,
                team_id=local_simulation.current_team_id(),
                actor=actor,
                action="group_reset_to_unconstructed",
                entity_type="material_group",
                entity_id=group.id,
                before_data=before,
                after_data=after,
                payload=_data_center_audit_payload(
                    source_page=source_page or "admin",
                    actor=actor,
                    reason=reason or "reset_to_unconstructed",
                    before=before,
                    after=after,
                    group_id=group.legacy_id or str(group.id),
                    soft_deleted_photos=len(photos),
                ),
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
        source_page: str = "",
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
            invalidate_verification_for_group(session, group, actor=actor, reason="reset_to_unreviewed")
            from app.services.delivery_cache import (
                invalidate_postgres_delivery_cache_for_group_change,
            )

            invalidate_postgres_delivery_cache_for_group_change(
                session,
                group,
                actor=actor,
                reason="reset_to_unreviewed",
            )
            after = {
                "status": "pending",
                "reviewer": "",
                "review_note": "",
                "exception_note": "",
            }
            _stage_transactional_audit(
                session,
                team_id=local_simulation.current_team_id(),
                actor=actor,
                action="admin_group_reset_unreviewed",
                entity_type="material_group",
                entity_id=group.id,
                before_data=before,
                after_data=after,
                payload=_data_center_audit_payload(
                    source_page=source_page or "admin",
                    actor=actor,
                    reason=reason or "reset_to_unreviewed",
                    before=before,
                    after=after,
                    group_id=group.legacy_id or str(group.id),
                ),
            )
            session.commit()
            session.refresh(group)
            return {"group": _group_payload(session, group)}

    def bulk_archive_groups(self, group_ids: list[str], *, actor: str, reason: str = "") -> dict[str, Any]:
        from app.services.delivery_cache import invalidate_postgres_delivery_cache_for_group_change

        unique_ids = list(dict.fromkeys(str(item).strip() for item in group_ids if str(item).strip()))
        if not unique_ids:
            raise ValueError("At least one group is required")
        archived_groups: list[MaterialGroup] = []
        approved_group_ids: list[str] = []
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
                invalidate_verification_for_group(
                    session,
                    group,
                    actor=actor,
                    reason="bulk_archive_completed",
                )
                invalidate_postgres_delivery_cache_for_group_change(
                    session,
                    group,
                    actor=actor,
                    reason="bulk_archive_completed",
                )
                if not reasons:
                    approved_group_ids.append(str(group.legacy_id or group.id))
                archived_groups.append(group)
                _stage_transactional_audit(
                    session,
                    team_id=local_simulation.current_team_id(),
                    actor=actor,
                    action="admin_groups_bulk_archive",
                    entity_type="material_group",
                    entity_id=group.id,
                    before_data=before,
                    after_data=_group_payload(session, group, include_photos=True),
                    payload={"group_id": group.legacy_id or str(group.id), "reason": reason.strip()},
                )
            _stage_transactional_audit(
                session,
                team_id=local_simulation.current_team_id(),
                actor=actor,
                action="admin_groups_bulk_archive",
                entity_type="material_group",
                payload={
                    "group_ids": unique_ids,
                    "archived_count": len(archived_groups),
                    "skipped": skipped,
                    "reason": reason.strip(),
                },
            )
            session.commit()
            for group in archived_groups:
                session.refresh(group)
            result = {
                "archived_count": len(archived_groups),
                "skipped": skipped,
                "groups": [_group_target_summary(_group_payload(session, group, include_photos=True), include_photos=True) for group in archived_groups],
            }
        for group_id in approved_group_ids:
            self._enqueue_delivery_cache_after_commit(
                group_id,
                actor=actor,
                reason="bulk_archive_completed",
            )
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
            invalidate_verification_for_group(
                session,
                group,
                actor=actor,
                reason="returned_to_exception_order",
            )
            from app.services.delivery_cache import invalidate_postgres_delivery_cache_for_group_change

            invalidate_postgres_delivery_cache_for_group_change(
                session,
                group,
                actor=actor,
                reason="returned_to_exception_order",
            )
            session.commit()
            session.refresh(group)
            session.refresh(order)
            return {
                "group": _group_payload(session, group),
                "order": {**self._exception_order_payload(session, order, group), "created_by": actor},
            }

    def return_data_center_group_to_exception_order(
        self,
        group_id: str,
        *,
        actor: str,
        category: str,
        note: str,
        reason: str = "",
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        note = note.strip()
        if not note:
            raise ValueError("Exception reason is required")
        category = category.strip() or "other"
        with self._session() as session:
            group = self._group_by_legacy_id(session, group_id, lock=True)
            before = {
                "status": _legacy_group_status(group),
                "exception_status": str(group.exception_status or ""),
                "exception_note": str(group.exception_note or ""),
                "exception_reasons": list(group.exception_reasons or []),
                "has_archive_blocker": bool(group.has_archive_blocker),
            }
            group.status = GroupStatus.REJECTED
            group.reviewer = actor
            group.review_note = ""
            group.exception_status = "open"
            group.exception_note = note
            group.exception_reasons = [category, note] if category != note else [category]
            group.has_archive_blocker = True
            group.reviewed_at = None
            raw_data = dict(group.raw_data or {})
            raw_data.update(
                {
                    "status": "exception",
                    "exception_status": "open",
                    "exception_note": note,
                    "exception_category": category,
                    "exception_reasons": group.exception_reasons,
                    "has_archive_blocker": True,
                }
            )
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
            invalidate_verification_for_group(
                session,
                group,
                actor=actor,
                reason="returned_to_exception_order",
            )
            from app.services.delivery_cache import invalidate_postgres_delivery_cache_for_group_change

            invalidate_postgres_delivery_cache_for_group_change(
                session,
                group,
                actor=actor,
                reason="returned_to_exception_order",
            )
            after = {
                "status": _legacy_group_status(group),
                "exception_status": str(group.exception_status or ""),
                "exception_note": str(group.exception_note or ""),
                "exception_reasons": list(group.exception_reasons or []),
                "has_archive_blocker": bool(group.has_archive_blocker),
            }
            _stage_transactional_audit(
                session,
                team_id=group.team_id,
                actor=actor,
                action="group_returned_to_exception_order",
                entity_type="material_group",
                entity_id=group.id,
                before_data=before,
                after_data=after,
                payload=_data_center_audit_payload(
                    source_page=source_page,
                    actor=actor,
                    reason=reason or note or "data_center_return_exception",
                    before=before,
                    after=after,
                    group_id=group.legacy_id or str(group.id),
                    category=category,
                    note=note,
                ),
            )
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

    def request_final_delivery_export(
        self,
        *,
        task_id: int | None = None,
        terminal: str = "",
        review_scope: str = "reviewed",
        requested_by: str = "",
    ) -> LeasedDeliveryPackage:
        raise StateBackendNotReady(
            "Dual formal delivery export requires one authoritative delivery-package queue backend"
        )

    def build_final_delivery_export(
        self,
        *,
        task_id: int | None = None,
        terminal: str = "",
        review_scope: str = "reviewed",
    ) -> LeasedDeliveryPackage:
        raise StateBackendNotReady(
            "Dual formal delivery export requires one authoritative delivery-cache repair backend"
        )

    def _mirror_write(self, operation: str, *args: Any, **kwargs: Any) -> None:
        try:
            mirror = self.postgres_repository_factory()
            getattr(mirror, operation)(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - production safety path
            logger.warning("Dual write mirror failed for %s: %s", operation, exc, exc_info=True)

    def _strict_unmatched_review_write(self, operation: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        team_id = local_simulation.current_team_id()
        transaction = local_simulation.active_authoritative_json_write(team_id)
        owns_transaction = transaction is None
        token = None
        if owns_transaction:
            transaction = local_simulation.begin_authoritative_json_write(team_id)
            token = local_simulation.activate_authoritative_json_write(transaction)
        try:
            raise StateBackendNotReady(
                "Dual unmatched-review writes require a coordinated JSON/PostgreSQL transaction; "
                f"{operation} was rejected before either backend mutated"
            )
        finally:
            if owns_transaction:
                local_simulation.abort_authoritative_json_write(transaction, token)

    @staticmethod
    def _reject_uncoordinated_dual_write(operation: str) -> NoReturn:
        raise StateBackendNotReady(
            "Dual review/verification writes require durable cross-backend recovery; "
            f"{operation} was rejected before either backend mutated"
        )

    def claim_task(self, task_id: int, reviewer: str) -> dict[str, Any]:
        result = super().claim_task(task_id, reviewer)
        self._mirror_write("claim_task", task_id, reviewer)
        return result

    def release_task(self, task_id: int, reviewer: str, *, force: bool = False) -> dict[str, Any]:
        result = super().release_task(task_id, reviewer, force=force)
        self._mirror_write("release_task", task_id, reviewer, force=force)
        return result

    def set_construction_task_priority(
        self,
        task_id: int,
        *,
        actor: str,
        priority: bool,
    ) -> dict[str, Any]:
        result = super().set_construction_task_priority(task_id, actor=actor, priority=priority)
        self._mirror_write("set_construction_task_priority", task_id, actor=actor, priority=priority)
        return result

    def import_construction_priorities(self, rows: list[Any], *, actor: str, confirm: bool) -> dict[str, Any]:
        if confirm:
            raise ValueError("Construction priority import confirmation is unavailable in dual backend mode")
        result = super().import_construction_priorities(rows, actor=actor, confirm=confirm)
        return result

    def dedupe_unmatched_records(self, *, actor: str) -> dict[str, Any]:
        result = super().dedupe_unmatched_records(actor=actor)
        self._mirror_write("dedupe_unmatched_records", actor=actor)
        return result

    def list_unmatched_match_candidates(self, unmatched_id: str, *, actor: str = "") -> dict[str, Any]:
        if actor.strip():
            return self._strict_unmatched_review_write(
                "list_unmatched_match_candidates",
                unmatched_id,
                actor=actor,
            )
        return super().list_unmatched_match_candidates(unmatched_id, actor=actor)

    def save_unmatched_review(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int,
        metadata: dict[str, Any] | None = None,
        photo_updates: list[dict[str, Any]] | None = None,
        state: str = "pending",
    ) -> dict[str, Any]:
        return self._strict_unmatched_review_write(
            "save_unmatched_review",
            unmatched_id,
            actor=actor,
            expected_version=expected_version,
            metadata=metadata,
            photo_updates=photo_updates,
            state=state,
        )

    def rescan_unmatched_review_photo(
        self,
        unmatched_id: str,
        photo_id: str,
        *,
        actor: str,
        expected_version: int,
        category: str = "",
    ) -> dict[str, Any]:
        return self._strict_unmatched_review_write(
            "rescan_unmatched_review_photo",
            unmatched_id,
            photo_id,
            actor=actor,
            expected_version=expected_version,
            category=category,
        )

    def confirm_unmatched_review(
        self,
        unmatched_id: str,
        *,
        actor: str,
        expected_version: int,
        confirmed: bool = True,
    ) -> dict[str, Any]:
        return self._strict_unmatched_review_write(
            "confirm_unmatched_review",
            unmatched_id,
            actor=actor,
            expected_version=expected_version,
            confirmed=confirmed,
        )

    def finalize_unmatched_match(
        self,
        unmatched_id: str,
        *,
        actor: str,
        candidate_key: str,
        expected_version: int,
        source_page: str = "",
    ) -> dict[str, Any]:
        return self._strict_unmatched_review_write(
            "finalize_unmatched_match",
            unmatched_id,
            actor=actor,
            candidate_key=candidate_key,
            expected_version=expected_version,
            source_page=source_page,
        )

    def review_group(
        self,
        group_id: str,
        status: str,
        reviewer: str,
        note: str = "",
        exception_note: str = "",
    ) -> dict[str, Any]:
        self._reject_uncoordinated_dual_write("review_group")

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

    def apply_group_scan_result(
        self,
        group_id: str,
        result: Any,
        *,
        claimed_evidence_fingerprint: str,
        claimed_evidence_version: int,
        lease_owner: str,
        lease_token: str,
        actor: str,
    ) -> dict[str, Any]:
        self._reject_uncoordinated_dual_write("apply_group_scan_result")

    def confirm_group_barcode_manually(
        self,
        group_id: str,
        *,
        actor: str,
        meter_no: str,
        module_asset_no: str,
        collector: str,
        reason: str,
        photo_ids: list[str],
        source_page: str = "",
        require_claim: bool = True,
    ) -> dict[str, Any]:
        self._reject_uncoordinated_dual_write("confirm_group_barcode_manually")

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

    def update_data_center_group(
        self,
        group_id: str,
        *,
        patch: dict[str, Any],
        actor: str,
        reason: str = "",
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        result = super().update_data_center_group(
            group_id,
            patch=patch,
            actor=actor,
            reason=reason,
            source_page=source_page,
        )
        self._mirror_write(
            "update_data_center_group",
            group_id,
            patch=patch,
            actor=actor,
            reason=reason,
            source_page=source_page,
        )
        return result

    def classify_data_center_group_photo(
        self,
        group_id: str,
        photo_id: str,
        category: str,
        *,
        actor: str,
        reason: str = "",
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        result = super().classify_data_center_group_photo(
            group_id,
            photo_id,
            category,
            actor=actor,
            reason=reason,
            source_page=source_page,
        )
        self._mirror_write(
            "classify_data_center_group_photo",
            group_id,
            photo_id,
            category,
            actor=actor,
            reason=reason,
            source_page=source_page,
        )
        return result

    def rescan_data_center_group_photo_barcode(
        self,
        group_id: str,
        photo_id: str,
        *,
        actor: str,
        category: str = "",
        reason: str = "",
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        result = super().rescan_data_center_group_photo_barcode(
            group_id,
            photo_id,
            actor=actor,
            category=category,
            reason=reason,
            source_page=source_page,
        )
        self._mirror_write(
            "rescan_data_center_group_photo_barcode",
            group_id,
            photo_id,
            actor=actor,
            category=category,
            reason=reason,
            source_page=source_page,
        )
        return result

    def scan_data_center_group_photo_region(
        self,
        group_id: str,
        photo_id: str,
        *,
        barcode_type: str,
        region: Mapping[str, Any],
        actor: str,
        reason: str = "",
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        return super().scan_data_center_group_photo_region(
            group_id,
            photo_id,
            barcode_type=barcode_type,
            region=region,
            actor=actor,
            reason=reason,
            source_page=source_page,
        )

    def manual_confirm_group_barcode(
        self,
        group_id: str,
        *,
        actor: str,
        reason: str,
        source_page: str = "data_center",
        meter_no: str,
        module_asset_no: str,
        collector: str,
        photo_ids: list[str],
    ) -> dict[str, Any]:
        self._reject_uncoordinated_dual_write("manual_confirm_group_barcode")

    def finalize_unmatched_to_group(
        self,
        unmatched_id: str,
        *,
        actor: str,
        terminal: str,
        meter_no: str,
        candidate_key: str,
        expected_version: int,
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        _reject_placeholder_or_ambiguous_data_center_target(
            terminal=terminal,
            meter_no=meter_no,
            candidate_key=candidate_key,
        )
        return super().finalize_unmatched_match(
            unmatched_id,
            actor=actor,
            candidate_key=candidate_key,
            expected_version=expected_version,
            source_page=source_page,
        )

    def reset_group_to_unconstructed(
        self,
        group_id: str,
        *,
        actor: str,
        reason: str = "",
        force: bool = False,
        source_page: str = "",
    ) -> dict[str, Any]:
        result = super().reset_group_to_unconstructed(
            group_id,
            actor=actor,
            reason=reason,
            force=force,
            source_page=source_page,
        )
        self._mirror_write(
            "reset_group_to_unconstructed",
            group_id,
            actor=actor,
            reason=reason,
            force=force,
            source_page=source_page,
        )
        return result

    def reset_group_to_unreviewed(
        self,
        group_id: str,
        *,
        actor: str,
        reason: str = "",
        force: bool = False,
        source_page: str = "",
    ) -> dict[str, Any]:
        result = super().reset_group_to_unreviewed(
            group_id,
            actor=actor,
            reason=reason,
            force=force,
            source_page=source_page,
        )
        self._mirror_write(
            "reset_group_to_unreviewed",
            group_id,
            actor=actor,
            reason=reason,
            force=force,
            source_page=source_page,
        )
        return result

    def bulk_archive_groups(self, group_ids: list[str], *, actor: str, reason: str = "") -> dict[str, Any]:
        result = super().bulk_archive_groups(group_ids, actor=actor, reason=reason)
        self._mirror_write("bulk_archive_groups", group_ids, actor=actor, reason=reason)
        return result

    def return_data_center_group_to_exception_order(
        self,
        group_id: str,
        *,
        actor: str,
        category: str,
        note: str,
        reason: str = "",
        source_page: str = "data_center",
    ) -> dict[str, Any]:
        result = super().return_data_center_group_to_exception_order(
            group_id,
            actor=actor,
            category=category,
            note=note,
            reason=reason,
            source_page=source_page,
        )
        self._mirror_write(
            "return_data_center_group_to_exception_order",
            group_id,
            actor=actor,
            category=category,
            note=note,
            reason=reason,
            source_page=source_page,
        )
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
