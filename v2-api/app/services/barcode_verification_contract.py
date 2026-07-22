from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


VERIFICATION_TOTAL = 3
REQUIRED_CATEGORIES = frozenset({"before_box", "collector_barcode", "module_meter", "after_box"})
DURABLE_STATUSES = frozenset(
    {
        "not_eligible",
        "pending",
        "processing",
        "passed",
        "partial",
        "unreadable",
        "mismatch",
        "manual_confirmed",
        "failed",
    }
)
TERMINAL_STATUSES = frozenset({"passed", "partial", "unreadable", "mismatch", "manual_confirmed", "failed"})
PASS_STATUSES = frozenset({"passed", "manual_confirmed"})
EXCEPTION_STATUSES = frozenset({"partial", "mismatch", "failed"})
MATCH_FIELDS = (("meter", "meter_matched"), ("module", "module_matched"), ("collector", "collector_matched"))
EVIDENCE_ARRAY_KEYS = (
    "machine_barcode_values",
    "machine_qr_values",
    "ocr_candidates",
    "unmatched_machine_values",
    "matched_ocr_candidates",
    "unmatched_ocr_candidates",
)
OCR_ONLY_METHODS = frozenset({"ocr", "barcode_ocr", "ocr_assisted"})
LEGACY_EVIDENCE_WHITESPACE = (
    "\u0009\u000a\u000b\u000c\u000d"
    "\u001c\u001d\u001e\u001f"
    "\u0020\u0085\u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000"
)


def _value(source: Any, key: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def _timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def normalize_legacy_evidence_value(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip(LEGACY_EVIDENCE_WHITESPACE)


def _same_evidence(source: Any, raw: Mapping[str, Any]) -> bool:
    if not raw:
        return False
    return (
        int(raw.get("evidence_version") or 0) == int(_value(source, "evidence_version", 0) or 0)
        and str(raw.get("evidence_fingerprint") or "") == str(_value(source, "evidence_fingerprint", "") or "")
    )


def normalize_barcode_verification(source: Any, raw: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    if source is None:
        return None
    status = str(_value(source, "status", "") or "").strip()
    if status not in DURABLE_STATUSES:
        return None

    source_is_mapping = isinstance(source, Mapping)
    raw_payload = dict(raw or {})
    source_result = source.get("result") if source_is_mapping else None
    if isinstance(source_result, Mapping):
        raw_result = source_result
    elif _same_evidence(source, raw_payload):
        raw_result = raw_payload.get("result")
    else:
        raw_result = {}
    if not isinstance(raw_result, Mapping):
        raw_result = {}

    match_values = {field: _value(source, attribute) for field, attribute in MATCH_FIELDS}
    if source_is_mapping:
        for field, attribute in MATCH_FIELDS:
            if match_values[field] is None:
                match_values[field] = source.get(attribute)
    matched_fields = [field for field, value in match_values.items() if value is True]
    missing_fields = [field for field, value in match_values.items() if value is not True]
    passed_count = len(matched_fields)
    if source_is_mapping and not any(value is not None for value in match_values.values()):
        passed_count = max(0, min(VERIFICATION_TOTAL, int(raw_result.get("passed_count") or 0)))
        matched_fields = [str(item) for item in raw_result.get("matched_fields") or [] if str(item)][:passed_count]
        missing_fields = [str(item) for item in raw_result.get("missing_fields") or [] if str(item)]

    result = {
        "passed_count": passed_count,
        "matched_fields": matched_fields,
        "missing_fields": missing_fields,
    }
    for key in EVIDENCE_ARRAY_KEYS:
        values = raw_result.get(key)
        result[key] = [str(item) for item in values or [] if str(item)] if isinstance(values, (list, tuple, set)) else []

    payload = {
        "status": status,
        "eligible": status != "not_eligible",
        "terminal": status in TERMINAL_STATUSES,
        "evidence_fingerprint": _value(source, "evidence_fingerprint"),
        "evidence_version": int(_value(source, "evidence_version", 0) or 0),
        "meter_matched": match_values["meter"],
        "module_matched": match_values["module"],
        "collector_matched": match_values["collector"],
        "recognition_source": str(_value(source, "recognition_source", "") or ""),
        "attempt_count": int(_value(source, "attempt_count", 0) or 0),
        "invalidation_reason": str(_value(source, "invalidation_reason", "") or ""),
        "invalidated_by": str(_value(source, "invalidated_by", "") or ""),
        "invalidated_at": _timestamp(_value(source, "invalidated_at")),
        "auto_archive_status": str(_value(source, "auto_archive_status", "") or ""),
        "auto_archived_at": _timestamp(_value(source, "auto_archived_at")),
        "auto_archive_error": str(_value(source, "auto_archive_error", "") or ""),
        "updated_at": _timestamp(_value(source, "updated_at")),
        "result": result,
    }
    return payload


def _unique_strings(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    unique: list[str] = []
    for value in values:
        text = normalize_legacy_evidence_value(value)
        if text and text not in unique:
            unique.append(text)
    return unique


def _legacy_evidence(photos: list[Mapping[str, Any]]) -> tuple[list[str], list[str], list[str], bool]:
    machine_barcodes: list[str] = []
    machine_qrs: list[str] = []
    ocr_candidates: list[str] = []
    has_machine_evidence = False
    has_ocr_evidence = False
    for photo in photos:
        if photo.get("is_active", True) is False:
            continue
        upload_status = getattr(
            photo.get("upload_status", "uploaded"),
            "value",
            photo.get("upload_status", "uploaded"),
        )
        if str(upload_status or "").strip().lower() == "invalid":
            continue
        method = str(photo.get("barcode_check_method") or "").strip().lower()
        barcode_values = _unique_strings(photo.get("machine_barcode_values"))
        qr_values = _unique_strings(photo.get("machine_qr_values"))
        ocr_values = _unique_strings(photo.get("ocr_candidate_values"))
        ocr_values.extend(
            value
            for value in _unique_strings(photo.get("barcode_check_ocr_values"))
            if value not in ocr_values
        )
        if not barcode_values and not qr_values and method and method not in OCR_ONLY_METHODS:
            barcode_values = _unique_strings(photo.get("barcode_check_values"))
        for target, values in (
            (machine_barcodes, barcode_values),
            (machine_qrs, qr_values),
            (ocr_candidates, ocr_values),
        ):
            target.extend(value for value in values if value not in target)
        has_machine_evidence = has_machine_evidence or bool(barcode_values or qr_values)
        has_ocr_evidence = has_ocr_evidence or bool(ocr_values) or method in OCR_ONLY_METHODS
    return machine_barcodes, machine_qrs, ocr_candidates, has_ocr_evidence and not has_machine_evidence


def _legacy_verification(raw: Mapping[str, Any], photos: list[Mapping[str, Any]]) -> dict[str, Any] | None:
    legacy_status = str(raw.get("group_barcode_check_status") or "").strip().lower()
    status_map = {
        "mismatched": "mismatch",
        "unreadable": "unreadable",
        "not_required": "not_eligible",
    }
    machine_barcodes, machine_qrs, ocr_candidates, ocr_only = _legacy_evidence(photos)
    manual_confirmed = bool(raw.get("group_barcode_manual_confirmed"))
    if legacy_status == "matched":
        if manual_confirmed:
            status = "manual_confirmed"
        elif ocr_only:
            status = "partial"
        else:
            status = "passed"
    else:
        status = status_map.get(legacy_status, "")
    if not status:
        return None

    matched_fields = [
        str(field)
        for field in raw.get("group_barcode_matched_fields") or []
        if str(field) in {name for name, _attribute in MATCH_FIELDS}
    ]
    if status in PASS_STATUSES:
        matched_fields = [name for name, _attribute in MATCH_FIELDS]
    if ocr_only:
        matched_fields = []
    matched_set = set(matched_fields)
    return {
        "status": status,
        "evidence_fingerprint": "",
        "evidence_version": 0,
        "meter_matched": "meter" in matched_set,
        "module_matched": "module" in matched_set,
        "collector_matched": "collector" in matched_set,
        "recognition_source": (
            "manual_confirmed"
            if status == "manual_confirmed"
            else "ocr_candidate"
            if ocr_only
            else "legacy_machine"
        ),
        "attempt_count": 0,
        "result": {
            "passed_count": len(matched_fields),
            "matched_fields": matched_fields,
            "missing_fields": [name for name, _attribute in MATCH_FIELDS if name not in matched_set],
            "machine_barcode_values": machine_barcodes,
            "machine_qr_values": machine_qrs,
            "ocr_candidates": ocr_candidates,
            "unmatched_machine_values": _unique_strings(raw.get("group_barcode_unmatched_values")),
            "matched_ocr_candidates": [],
            "unmatched_ocr_candidates": [],
        },
    }


def resolve_persisted_barcode_verification(
    source: Any,
    raw: Mapping[str, Any] | None,
    photos: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any] | None:
    raw_payload = raw if isinstance(raw, Mapping) else {}
    nested = raw_payload.get("barcode_verification")
    nested_payload = nested if isinstance(nested, Mapping) else {}
    if source is not None:
        return normalize_barcode_verification(source, nested_payload)
    durable = normalize_barcode_verification(nested_payload)
    if durable:
        return durable
    if photos is None:
        return None
    return normalize_barcode_verification(_legacy_verification(raw_payload, list(photos)))


def verification_compatibility_fields(verification: Mapping[str, Any] | None) -> dict[str, Any]:
    if not verification:
        return {}
    result = verification.get("result") if isinstance(verification.get("result"), Mapping) else {}
    return {
        "barcode_verification_status": verification.get("status", ""),
        "barcode_verification_source": verification.get("recognition_source", ""),
        "barcode_verification_passed_count": max(
            0,
            min(VERIFICATION_TOTAL, int(result.get("passed_count") or 0)),
        ),
        "barcode_verification_total_count": VERIFICATION_TOTAL,
        "barcode_verification_reason": verification.get("invalidation_reason", ""),
    }


def has_current_eligible_photo_set(group: Mapping[str, Any]) -> bool:
    photos = group.get("photos")
    if not isinstance(photos, list):
        return False
    valid = []
    for photo in photos:
        if not isinstance(photo, Mapping) or photo.get("is_active", True) is False:
            continue
        upload_status = getattr(photo.get("upload_status", "uploaded"), "value", photo.get("upload_status", "uploaded"))
        if str(upload_status or "").strip().lower() == "invalid":
            continue
        valid.append(photo)
    categories = [str(photo.get("category") or "").strip() for photo in valid]
    return len(valid) == len(REQUIRED_CATEGORIES) and set(categories) == REQUIRED_CATEGORIES


def legacy_review_status(status: str) -> str:
    if status in PASS_STATUSES:
        return "matched"
    if status == "unreadable":
        return "unreadable"
    if status in EXCEPTION_STATUSES:
        return "mismatched"
    return ""


def summarize_durable_accuracy(groups: list[Mapping[str, Any]]) -> dict[str, Any]:
    counts = {status: 0 for status in DURABLE_STATUSES}
    photo_ineligible = 0
    for group in groups:
        verification = normalize_barcode_verification(group.get("barcode_verification"))
        if not has_current_eligible_photo_set(group):
            photo_ineligible += 1
            continue
        status = str((verification or {}).get("status") or "not_eligible")
        counts[status] += 1

    checked = sum(counts[status] for status in TERMINAL_STATUSES)
    passed = counts["passed"] + counts["manual_confirmed"]
    failed = sum(counts[status] for status in EXCEPTION_STATUSES)
    not_eligible = counts["not_eligible"] + photo_ineligible
    return {
        "group_barcode_accuracy_checked": checked,
        "group_barcode_accuracy_passed": passed,
        "group_barcode_accuracy_failed": failed,
        "group_barcode_accuracy_unreadable": counts["unreadable"],
        "group_barcode_accuracy_not_required": not_eligible,
        "group_barcode_accuracy_rate": round(passed / checked, 4) if checked else 0.0,
        "group_barcode_accuracy_machine_passed": counts["passed"],
        "group_barcode_accuracy_manual_confirmed": counts["manual_confirmed"],
        "group_barcode_accuracy_partial": counts["partial"],
        "group_barcode_accuracy_mismatch": counts["mismatch"],
        "group_barcode_accuracy_terminal_failed": counts["failed"],
        "group_barcode_accuracy_not_eligible": not_eligible,
        "group_barcode_accuracy_pending": counts["pending"],
        "group_barcode_accuracy_processing": counts["processing"],
    }
