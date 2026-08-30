from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time
from io import BytesIO
from typing import Any, Callable, Iterable, Mapping

from app.schemas.data_center import DataCenterQuery
from app.services.barcode_verification_contract import has_current_eligible_photo_set, normalize_barcode_verification


REQUIRED_CLASSIFICATION_SLOTS = {"before_box", "module_meter", "after_box", "collector_barcode"}
MANUAL_CLASSIFICATION_BARCODE_READY = {"passed", "manual", "manual_confirmed", "manual_passed"}
DASHBOARD_IGNORED_EXCEPTION_REASON = "missing_collector_photo"
ANOMALY_RESOLUTIONS_KEY = "data_center_anomaly_resolutions"


class AnomalyResolutionConflict(ValueError):
    """Raised when an anomaly decision no longer matches the evidence shown to the user."""


ANOMALY_MESSAGES = {
    "unclassified_photos": "存在未分类照片",
    "module_meter_photo_missing": "缺少电表和模块照片",
    "module_meter_photo_conflict": "电表和模块照片重复",
    "after_box_photo_missing": "缺少改造完成照片",
    "after_box_photo_conflict": "改造完成照片重复",
    "barcode_verification_required": "条码识别未通过",
    "terminal_missing": "缺少终端号",
    "meter_missing": "缺少表号",
    "module_missing": "缺少模块号",
    "collector_missing": "缺少采集器号",
    "address_missing": "缺少安装地址",
    "exception_open": "资料存在未关闭异常",
    "meter_barcode_mismatch": "表号与照片识别结果不一致",
    "module_barcode_mismatch": "模块号与台账不一致",
    "collector_barcode_mismatch": "采集器号与照片识别结果不一致",
    "required_photos_missing": "缺少必要施工照片",
}

EXCEPTION_REASON_ANOMALIES = {
    "missing_module_asset_no": ("module_missing", ANOMALY_MESSAGES["module_missing"]),
    "缺少模块资产编号": ("module_missing", ANOMALY_MESSAGES["module_missing"]),
    "missing_collector_info": ("collector_missing", ANOMALY_MESSAGES["collector_missing"]),
    "缺少采集器信息": ("collector_missing", ANOMALY_MESSAGES["collector_missing"]),
    "insufficient_group_photos": ("required_photos_missing", ANOMALY_MESSAGES["required_photos_missing"]),
    "资料组照片不足 4 张": ("required_photos_missing", ANOMALY_MESSAGES["required_photos_missing"]),
    "barcode_error": ("exception_barcode_error", "资料被标记为条码异常"),
    "module_error": ("exception_module_error", "资料被标记为模块异常"),
    "collector_error": ("exception_collector_error", "资料被标记为采集器异常"),
    "photo_error": ("exception_photo_error", "资料被标记为照片异常"),
}


def is_only_missing_collector_photo_exception(group: Mapping[str, Any]) -> bool:
    raw_reasons = group.get("exception_reasons")
    if not isinstance(raw_reasons, list):
        return False
    reasons = {str(item).strip() for item in raw_reasons if str(item).strip()}
    return reasons == {DASHBOARD_IGNORED_EXCEPTION_REASON}


def effective_collector(group: Mapping[str, Any]) -> str:
    construction_value = str(group.get("construction_collector") or "").strip()
    if construction_value:
        return construction_value
    return str(group.get("collector") or "").strip()


def effective_module_asset_no(group: Mapping[str, Any]) -> str:
    construction_value = str(group.get("construction_module_asset_no") or "").strip()
    if construction_value:
        return construction_value
    return str(group.get("module_asset_no") or group.get("asset_no") or "").strip()


def manual_classification_snapshot(
    group: Mapping[str, Any],
    photos: list[Mapping[str, Any]],
) -> tuple[list[dict[str, str]], list[str]]:
    active = [photo for photo in photos if photo.get("is_active", True) is not False]
    snapshot = [
        {
            "photo_id": str(photo.get("id") or photo.get("legacy_id") or ""),
            "category": str(photo.get("category") or "unclassified"),
            "sha256": str(photo.get("sha256") or ""),
        }
        for photo in active
    ]
    anomalies: list[str] = []
    categories = [item["category"] for item in snapshot]
    if any(category not in REQUIRED_CLASSIFICATION_SLOTS for category in categories):
        anomalies.append("unclassified_photos")
    for category in ("module_meter", "after_box"):
        count = categories.count(category)
        if count == 0:
            anomalies.append(f"{category}_photo_missing")
        elif count > 1:
            anomalies.append(f"{category}_photo_conflict")
    verification = group.get("barcode_verification")
    barcode_status = ""
    if isinstance(verification, Mapping):
        barcode_status = str(verification.get("status") or "").strip().lower()
    if not barcode_status:
        barcode_status = str(group.get("barcode_status") or "").strip().lower()
    if barcode_status not in MANUAL_CLASSIFICATION_BARCODE_READY:
        anomalies.append("barcode_verification_required")
    for value, code in (
        (group.get("terminal"), "terminal_missing"),
        (group.get("meter_no"), "meter_missing"),
        (effective_module_asset_no(group), "module_missing"),
        (effective_collector(group), "collector_missing"),
        (group.get("address"), "address_missing"),
    ):
        if not str(value or "").strip():
            anomalies.append(code)
    if str(group.get("exception_status") or "").strip().lower() in {"open", "exception", "rejected"}:
        anomalies.append("exception_open")
    return snapshot, anomalies


def manual_classification_fingerprint(
    snapshot: list[dict[str, str]],
    anomalies: list[str],
) -> str:
    canonical = {
        "photo_snapshot": sorted(
            snapshot,
            key=lambda item: (item["photo_id"], item["category"], item["sha256"]),
        ),
        "anomalies": sorted(anomalies),
    }
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _anomaly_resolution_map(group: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    direct = group.get(ANOMALY_RESOLUTIONS_KEY)
    raw = group.get("raw_data")
    nested = raw.get(ANOMALY_RESOLUTIONS_KEY) if isinstance(raw, Mapping) else None
    source = direct if isinstance(direct, Mapping) else nested
    if not isinstance(source, Mapping):
        return {}
    return {str(code): value for code, value in source.items() if isinstance(value, Mapping)}


def group_anomaly_evidence_fingerprint(group: Mapping[str, Any]) -> str:
    photos = active_photos(group)
    snapshot, manual_codes = manual_classification_snapshot(group, photos)
    verification = group.get("barcode_verification")
    verification_payload = dict(verification) if isinstance(verification, Mapping) else {}
    canonical = {
        "fields": {
            "terminal": str(group.get("terminal") or "").strip(),
            "meter_no": str(group.get("meter_no") or "").strip(),
            "module_asset_no": effective_module_asset_no(group),
            "collector": effective_collector(group),
            "address": str(group.get("address") or "").strip(),
        },
        "photo_snapshot": sorted(
            snapshot,
            key=lambda item: (item["photo_id"], item["category"], item["sha256"]),
        ),
        "manual_codes": sorted(manual_codes),
        "barcode": {
            "status": str(verification_payload.get("status") or group.get("barcode_status") or ""),
            "evidence_fingerprint": str(verification_payload.get("evidence_fingerprint") or ""),
            "evidence_version": int(verification_payload.get("evidence_version") or 0),
            "meter_matched": verification_payload.get("meter_matched"),
            "module_matched": verification_payload.get("module_matched"),
            "collector_matched": verification_payload.get("collector_matched"),
            "missing_fields": sorted(
                str(item)
                for item in (
                    group.get("group_barcode_missing_fields")
                    or (verification_payload.get("result") or {}).get("missing_fields")
                    or []
                )
                if str(item)
            ),
        },
        "exception": {
            "status": str(group.get("exception_status") or ""),
            "note": str(group.get("exception_note") or ""),
            "reasons": sorted(str(item) for item in group.get("exception_reasons") or [] if str(item)),
        },
    }
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def rebind_anomaly_resolutions(
    group: Mapping[str, Any],
    anomaly_codes: Iterable[str],
) -> dict[str, dict[str, Any]]:
    fingerprint = group_anomaly_evidence_fingerprint(group)
    resolutions = {
        str(code): dict(resolution)
        for code, resolution in _anomaly_resolution_map(group).items()
    }
    for code in anomaly_codes:
        normalized = str(code or "").strip()
        if normalized in resolutions:
            resolutions[normalized]["evidence_fingerprint"] = fingerprint
    return resolutions


def group_anomalies(group: Mapping[str, Any]) -> list[dict[str, str]]:
    photos = active_photos(group)
    _snapshot, manual_codes = manual_classification_snapshot(group, photos)
    if is_only_missing_collector_photo_exception(group):
        manual_codes = [code for code in manual_codes if code != "exception_open"]

    messages: dict[str, str] = {}
    unclassified_count = sum(
        1
        for photo in photos
        if str(photo.get("category") or "unclassified") not in REQUIRED_CLASSIFICATION_SLOTS
    )
    for code in manual_codes:
        message = ANOMALY_MESSAGES.get(code)
        if code == "unclassified_photos" and unclassified_count:
            message = f"存在 {unclassified_count} 张未分类照片"
        if message:
            messages.setdefault(code, message)

    _barcode_status, missing_fields, _progress = barcode_status_from_group(group)
    for field, code in (
        ("meter", "meter_barcode_mismatch"),
        ("module", "module_barcode_mismatch"),
        ("collector", "collector_barcode_mismatch"),
    ):
        if field in missing_fields:
            messages.setdefault(code, ANOMALY_MESSAGES[code])

    for raw_reason in group.get("exception_reasons") or []:
        reason = str(raw_reason or "").strip()
        if not reason or reason == DASHBOARD_IGNORED_EXCEPTION_REASON:
            continue
        known = EXCEPTION_REASON_ANOMALIES.get(reason)
        if known:
            messages.setdefault(*known)
            continue
        if reason in ANOMALY_MESSAGES:
            messages.setdefault(reason, ANOMALY_MESSAGES[reason])
            continue
        code = f"exception_reason_{hashlib.sha256(reason.encode('utf-8')).hexdigest()[:12]}"
        readable = reason if any("\u4e00" <= char <= "\u9fff" for char in reason) else f"资料异常（系统记录：{reason}）"
        messages.setdefault(code, readable)

    fingerprint = group_anomaly_evidence_fingerprint(group)
    resolutions = _anomaly_resolution_map(group)
    anomalies: list[dict[str, str]] = []
    for code, message in messages.items():
        resolution = resolutions.get(code) or {}
        resolved = str(resolution.get("evidence_fingerprint") or "") == fingerprint
        anomalies.append(
            {
                "code": code,
                "message": message,
                "status": "resolved" if resolved else "open",
                "evidence_fingerprint": fingerprint,
                "resolved_by": str(resolution.get("resolved_by") or "") if resolved else "",
                "resolved_at": str(resolution.get("resolved_at") or "") if resolved else "",
            }
        )
    return anomalies


def build_meter_module_workbook(rows: Iterable[Mapping[str, Any]]) -> bytes:
    try:
        from openpyxl import Workbook
    except ImportError as exc:  # pragma: no cover - guarded by runtime dependency checks
        raise RuntimeError("openpyxl is required to export Excel files") from exc

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "表号模块号对应表"
    sheet.append(
        [
            "序号",
            "终端号",
            "安装地址",
            "表号",
            "候选模块号",
            "模块号来源",
            "出现次数",
            "是否重复",
            "重复类型",
            "模块关联表号数",
            "表号候选模块数",
            "施工状态",
        ]
    )
    construction_labels = {
        "completed": "已施工",
        "constructed": "已施工",
        "in_progress": "施工中",
        "unconstructed": "未施工",
    }
    for index, row in enumerate(rows, start=1):
        value = lambda key: str(row.get(key) or "").strip() or "未填写"
        status = construction_labels.get(str(row.get("construction_status") or "").strip(), "未填写")
        sheet.append(
            [
                index,
                value("terminal"),
                value("address"),
                value("meter_no"),
                value("module_asset_no"),
                value("module_source"),
                int(row.get("occurrence_count") or 0),
                value("is_duplicate"),
                value("duplicate_type"),
                int(row.get("module_meter_count") or 0),
                int(row.get("meter_candidate_count") or 0),
                status,
            ]
        )
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column, width in {
        "A": 10,
        "B": 22,
        "C": 42,
        "D": 24,
        "E": 24,
        "F": 28,
        "G": 12,
        "H": 12,
        "I": 28,
        "J": 18,
        "K": 18,
        "L": 14,
    }.items():
        sheet.column_dimensions[column].width = width
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def aggregate_meter_module_export_rows(
    evidence_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    source_labels = {
        "original": "原始资料",
        "construction": "施工回传",
        "photo": "照片记录",
    }
    source_order = tuple(source_labels)
    relations: dict[tuple[str, str, str], dict[str, Any]] = {}
    meter_modules: dict[tuple[str, str], set[str]] = {}
    module_meters: dict[str, set[tuple[str, str]]] = {}

    for evidence in evidence_rows:
        terminal = str(evidence.get("terminal") or "").strip()
        meter_no = str(evidence.get("meter_no") or "").strip()
        module_asset_no = str(evidence.get("module_asset_no") or "").strip()
        if not module_asset_no:
            continue

        meter_key = (terminal, meter_no)
        relation_key = (terminal, meter_no, module_asset_no)
        relation = relations.setdefault(
            relation_key,
            {
                "terminal": terminal,
                "address": str(evidence.get("address") or "").strip(),
                "meter_no": meter_no,
                "module_asset_no": module_asset_no,
                "construction_status": str(evidence.get("construction_status") or "").strip(),
                "_sources": set(),
                "occurrence_count": 0,
            },
        )
        if not relation["address"]:
            relation["address"] = str(evidence.get("address") or "").strip()
        if not relation["construction_status"]:
            relation["construction_status"] = str(evidence.get("construction_status") or "").strip()
        relation["occurrence_count"] += 1
        source = str(evidence.get("module_source") or "").strip()
        if source:
            relation["_sources"].add(source)
        meter_modules.setdefault(meter_key, set()).add(module_asset_no)
        module_meters.setdefault(module_asset_no, set()).add(meter_key)

    output: list[dict[str, Any]] = []
    for relation_key in sorted(relations):
        relation = relations[relation_key]
        meter_key = (relation["terminal"], relation["meter_no"])
        meter_candidate_count = len(meter_modules[meter_key])
        module_meter_count = len(module_meters[relation["module_asset_no"]])
        duplicate_reasons = []
        if meter_candidate_count > 1:
            duplicate_reasons.append("同表多模块")
        if module_meter_count > 1:
            duplicate_reasons.append("同模块多表")

        sources = relation.pop("_sources")
        ordered_sources = [source_labels[source] for source in source_order if source in sources]
        ordered_sources.extend(sorted(source for source in sources if source not in source_labels))
        relation.update(
            {
                "module_source": "、".join(ordered_sources) or "未填写",
                "is_duplicate": "是" if duplicate_reasons else "否",
                "duplicate_type": "、".join(duplicate_reasons) or "无",
                "module_meter_count": module_meter_count,
                "meter_candidate_count": meter_candidate_count,
            }
        )
        output.append(relation)
    return output


def meter_module_export_rows_from_groups(
    groups: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    evidence_rows: list[dict[str, Any]] = []
    for group in groups:
        mapped = group_row(group)
        base = {
            "terminal": mapped["terminal"],
            "address": mapped["address"],
            "meter_no": mapped["meter_no"],
            "construction_status": mapped["construction_status"],
        }
        evidence_rows.extend(
            {
                **base,
                "module_asset_no": module_asset_no,
                "module_source": module_source,
            }
            for module_asset_no, module_source in (
                (group.get("module_asset_no") or group.get("asset_no"), "original"),
                (group.get("construction_module_asset_no"), "construction"),
            )
        )
        for photo in list(group.get("photos") or []) + list(group.get("deleted_photos") or []):
            if not isinstance(photo, Mapping):
                continue
            raw = photo.get("raw_data") if isinstance(photo.get("raw_data"), Mapping) else {}
            evidence_rows.append(
                {
                    **base,
                    "module_asset_no": (
                        photo.get("module_asset_no")
                        or photo.get("asset_no")
                        or raw.get("module_asset_no")
                        or raw.get("asset_no")
                    ),
                    "module_source": "photo",
                }
            )
    return aggregate_meter_module_export_rows(evidence_rows)


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


def durable_barcode_status_from_group(group: Mapping[str, Any]) -> str:
    verification = normalize_barcode_verification(group.get("barcode_verification"))
    return str((verification or {}).get("status") or "").strip()


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
    if str(group.get("status") or "").strip() == "approved":
        return ""
    if is_only_missing_collector_photo_exception(group):
        return ""
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
    manual_confirmation = group.get("classification_manual_confirmation")
    confirmation_snapshot, confirmation_anomalies = manual_classification_snapshot(group, photos)
    return {
        "kind": "group",
        "id": str(group.get("id") or group.get("legacy_id") or "").strip(),
        "terminal": str(group.get("terminal") or "").strip(),
        "meter_no": str(group.get("meter_no") or group.get("display_meter_no") or "").strip(),
        "meter_match_key": str(group.get("meter_match_key") or "").strip(),
        "address": str(group.get("address") or group.get("installation_address") or "").strip(),
        "collector": effective_collector(group),
        "module_asset_no": effective_module_asset_no(group),
        "construction_collector": str(group.get("construction_collector") or "").strip(),
        "construction_module_asset_no": str(group.get("construction_module_asset_no") or "").strip(),
        "installer": str(group.get("installer") or group.get("constructor") or group.get("creator") or "").strip(),
        "photo_count": photo_count,
        "classification_status": classification["status"],
        "classification_progress": classification,
        "classification_manual_confirmation": (
            dict(manual_confirmation) if isinstance(manual_confirmation, Mapping) else None
        ),
        "classification_confirmation_fingerprint": manual_classification_fingerprint(
            confirmation_snapshot,
            confirmation_anomalies,
        ),
        "anomalies": group_anomalies(group),
        "barcode_status": barcode_status,
        "barcode_progress": barcode_progress,
        "group_barcode_missing_fields": missing_fields,
        "construction_status": construction_status_from_group(group, photo_count),
        "archive_status": archive_status_from_group(group, photos),
        "exception_status": exception_status_from_group(group),
        "status": str(group.get("status") or "pending").strip() or "pending",
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
        "classification_manual_confirmation": None,
        "anomalies": [],
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
        durable_status = str(row.get("_durable_barcode_status") or "").strip()
        if query.barcode_eligibility == "ineligible" and eligible and durable_status != "not_eligible":
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
