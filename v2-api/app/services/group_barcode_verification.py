from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping

from app.services.local_simulation import is_valid_photo_evidence, validate_real_formal_identity_value
from app.services.matching import build_long_scan_match_key
from app.services.photo_barcode_check import GROUP_BARCODE_TYPES, expected_group_barcode_values, normalize_barcode_value

VerificationStatus = Literal[
    "not_eligible",
    "pending",
    "processing",
    "passed",
    "partial",
    "unreadable",
    "mismatch",
    "manual_confirmed",
    "failed",
]
InvalidationStatus = Literal["pending", "not_eligible"]
INVALIDATION_STATUSES = frozenset({"pending", "not_eligible"})

REQUIRED_CATEGORIES = frozenset(
    {"before_box", "collector_barcode", "module_meter", "after_box"}
)
IDENTITY_FIELDS = ("terminal", "meter_no", "module_asset_no", "collector")
PLACEHOLDER_VALUES = frozenset(
    {"-", "--", "n/a", "na", "none", "null", "unknown", "未关联", "未关联终端", "未匹配", "待补充"}
)


@dataclass(frozen=True)
class EligibilityResult:
    status: VerificationStatus
    reason: str | None = None
    evidence_fingerprint: str | None = None


@dataclass(frozen=True)
class GroupScanResult:
    """Pure group-level recognition result for the later barcode worker."""

    status: VerificationStatus
    passed_count: int
    machine_barcode_values: list[str]
    machine_qr_values: list[str]
    ocr_candidates: list[str]
    matched_fields: list[str]
    missing_fields: list[str]
    unmatched_machine_values: list[str]


PhotoRecognizer = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def scan_group_evidence(
    group: Mapping[str, Any],
    photos: list[Mapping[str, Any]],
    limits: Mapping[str, Any] | None = None,
) -> GroupScanResult:
    """Aggregate injected machine barcode, QR and OCR channels without side effects."""

    recognizer = (limits or {}).get("recognize")
    if recognizer is not None and not callable(recognizer):
        raise ValueError("recognize must be callable")

    machine_barcodes: list[str] = []
    machine_qrs: list[str] = []
    ocr_candidates: list[str] = []
    for photo in photos:
        evidence = recognizer(photo) if recognizer else _photo_scan_evidence(photo)
        if not isinstance(evidence, Mapping):
            raise ValueError("recognize must return a mapping")
        _extend_unique(machine_barcodes, _normalized_channel_values(evidence.get("barcode")))
        _extend_unique(machine_qrs, _normalized_channel_values(evidence.get("qr")))
        _extend_unique(ocr_candidates, _normalized_channel_values(evidence.get("ocr")))

    expected = expected_group_barcode_values(dict(group))
    machine_values = [*machine_barcodes, *machine_qrs]
    matched_fields: list[str] = []
    unmatched_machine_values: list[str] = []
    for value in machine_values:
        field = _matched_group_field(value, expected)
        if field:
            _extend_unique(matched_fields, [field])
        else:
            _extend_unique(unmatched_machine_values, [value])

    missing_fields = [field for field in GROUP_BARCODE_TYPES if field not in matched_fields]
    if not missing_fields:
        status: VerificationStatus = "passed"
    elif matched_fields:
        status = "partial"
    elif unmatched_machine_values:
        status = "mismatch"
    elif ocr_candidates:
        status = "partial"
    else:
        status = "unreadable"
    return GroupScanResult(
        status=status,
        passed_count=len(matched_fields),
        machine_barcode_values=machine_barcodes,
        machine_qr_values=machine_qrs,
        ocr_candidates=ocr_candidates,
        matched_fields=matched_fields,
        missing_fields=missing_fields,
        unmatched_machine_values=unmatched_machine_values,
    )


def apply_group_scan_result(
    verification: Mapping[str, Any],
    group: Any,
    result: GroupScanResult,
    *,
    claimed_evidence_fingerprint: str,
    actor: str,
) -> dict[str, Any]:
    """Apply a worker result only when the evidence claimed by that worker is current."""

    eligibility = evaluate_group_eligibility(group)
    current_fingerprint = eligibility.evidence_fingerprint
    if eligibility.status != "pending":
        invalidated = invalidate_group_verification(
            verification,
            reason=eligibility.reason or "not_eligible",
            actor=actor,
            evidence_fingerprint=current_fingerprint,
            next_status="not_eligible",
        )
        return {"applied": False, "verification": invalidated}
    if claimed_evidence_fingerprint != current_fingerprint:
        invalidated = invalidate_group_verification(
            verification,
            reason="evidence_fingerprint_changed",
            actor=actor,
            evidence_fingerprint=current_fingerprint,
            next_status="pending",
        )
        return {"applied": False, "verification": invalidated}

    applied = dict(verification)
    applied.update(
        {
            "status": result.status,
            "evidence_fingerprint": current_fingerprint,
            "lease_owner": None,
            "lease_expires_at": None,
            "should_enqueue": False,
            "result": {
                "passed_count": result.passed_count,
                "machine_barcode_values": result.machine_barcode_values,
                "machine_qr_values": result.machine_qr_values,
                "ocr_candidates": result.ocr_candidates,
                "matched_fields": result.matched_fields,
                "missing_fields": result.missing_fields,
                "unmatched_machine_values": result.unmatched_machine_values,
            },
        }
    )
    return {"applied": True, "verification": applied}


def evaluate_group_eligibility(group: Any) -> EligibilityResult:
    identity = {field: _group_value(group, field) for field in IDENTITY_FIELDS}
    if any(_is_missing_identity(value) for value in identity.values()):
        return EligibilityResult(status="not_eligible", reason="missing_identity")

    photos = _group_value(group, "photos") or []
    if not isinstance(photos, list):
        return EligibilityResult(status="not_eligible", reason="invalid_photo_count")

    valid_photos = [photo for photo in photos if is_valid_photo_evidence(photo)]
    if len(valid_photos) != len(REQUIRED_CATEGORIES):
        has_active_invalid_photo = any(
            bool(photo.get("is_active", True))
            and str(photo.get("upload_status") or "").strip().lower() == "invalid"
            for photo in photos
            if isinstance(photo, Mapping)
        )
        return EligibilityResult(
            status="not_eligible",
            reason="invalid_photo_evidence" if has_active_invalid_photo else "invalid_photo_count",
        )

    evidence = [_photo_evidence(photo) for photo in valid_photos]
    if any(item is None for item in evidence):
        return EligibilityResult(status="not_eligible", reason="invalid_photo_evidence")

    valid_evidence = [item for item in evidence if item is not None]
    categories = {item["category"] for item in valid_evidence}
    if not REQUIRED_CATEGORIES <= categories:
        return EligibilityResult(status="not_eligible", reason="missing_required_photo_category")
    if categories != REQUIRED_CATEGORIES:
        return EligibilityResult(status="not_eligible", reason="invalid_photo_categories")

    fingerprint_payload = {
        **identity,
        "photos": sorted(valid_evidence, key=lambda item: (item["category"], item["id"], item["sha256"])),
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return EligibilityResult(status="pending", evidence_fingerprint=fingerprint)


def invalidate_group_verification(
    verification: Mapping[str, Any],
    *,
    reason: str,
    actor: str,
    evidence_fingerprint: str | None = None,
    next_status: InvalidationStatus | None = None,
) -> dict[str, Any]:
    result = dict(verification)
    current_fingerprint = str(result.get("evidence_fingerprint") or "")
    resolved_status = next_status or "pending"
    if resolved_status not in INVALIDATION_STATUSES:
        raise ValueError("next_status must be pending or not_eligible")
    same_explicit_fingerprint = (
        evidence_fingerprint is not None and evidence_fingerprint == current_fingerprint
    )

    if same_explicit_fingerprint and str(result.get("status") or "") == resolved_status:
        result["should_enqueue"] = False
        return result

    result.update(
        {
            "status": resolved_status,
            "evidence_fingerprint": evidence_fingerprint,
            "evidence_version": int(result.get("evidence_version") or 0) + 1,
            "attempt_count": 0,
            "lease_owner": None,
            "lease_expires_at": None,
            "invalidation_reason": reason,
            "invalidated_by": actor,
            "should_enqueue": resolved_status == "pending",
        }
    )
    return result


def _group_value(group: Any, field: str) -> Any:
    if isinstance(group, Mapping):
        value = group.get(field)
        raw_data = group.get("raw_data")
    else:
        value = getattr(group, field, None)
        raw_data = getattr(group, "raw_data", None)
    if value is not None:
        return value
    return raw_data.get(field) if isinstance(raw_data, Mapping) else None


def _is_missing_identity(value: Any) -> bool:
    clean_value = str(value or "").strip()
    normalized = clean_value.lower()
    if not normalized or normalized in PLACEHOLDER_VALUES:
        return True
    try:
        validate_real_formal_identity_value(clean_value, "barcode verification identity")
    except ValueError:
        return True
    return bool(re.fullmatch(r"0+", clean_value) or normalized.startswith("test"))


def _photo_evidence(photo: Any) -> dict[str, str] | None:
    if not isinstance(photo, Mapping):
        return None
    if not is_valid_photo_evidence(photo):
        return None
    photo_id = str(photo.get("id") or "").strip()
    sha256 = str(photo.get("sha256") or "").strip().lower()
    category = str(photo.get("category") or "").strip()
    if not photo_id or not re.fullmatch(r"[0-9a-f]{64}", sha256) or not category:
        return None
    return {"id": photo_id, "sha256": sha256, "category": category}


def _photo_scan_evidence(photo: Mapping[str, Any]) -> dict[str, Any]:
    """Use persisted evidence when a worker has not injected a recognizer."""

    method = str(photo.get("barcode_check_method") or "").strip().lower()
    values = photo.get("barcode_check_normalized_values") or photo.get("barcode_check_values") or []
    ocr_values = photo.get("barcode_check_ocr_normalized_values") or photo.get("barcode_check_ocr_values") or []
    if method == "ocr":
        return {"ocr": values or ocr_values}
    if method in {"qr", "barcode_qr"}:
        return {"qr": values, "ocr": ocr_values}
    return {"barcode": values, "ocr": ocr_values}


def _normalized_channel_values(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    return [value for value in (normalize_barcode_value(item) for item in values) if value]


def _extend_unique(items: list[str], values: list[str]) -> None:
    for value in values:
        if value not in items:
            items.append(value)


def _matched_group_field(value: str, expected: Mapping[str, list[str]]) -> str:
    for field in GROUP_BARCODE_TYPES:
        if value in expected.get(field, []):
            return field
        if field == "meter":
            try:
                if build_long_scan_match_key(value) in expected.get(field, []):
                    return field
            except ValueError:
                pass
    return ""
