from __future__ import annotations

import math
import re
import shutil
import subprocess
import tempfile
import urllib.request
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from threading import BoundedSemaphore
from typing import Any, Callable, Iterable, Mapping
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse

from app.services.matching import build_long_scan_match_key, build_total_catalog_match_key
from app.services.photo_storage import (
    parse_oss_image_url,
    sign_oss_server_url,
    static_upload_root,
    validate_image_content,
    validate_remote_image_url,
)

BarcodeScanner = Callable[[dict[str, Any]], Iterable[str] | Mapping[str, Iterable[str]]]
OcrReader = Callable[[dict[str, Any], list[str]], Iterable[str]]


class MachineCodeValues(list[str]):
    def __init__(self, barcode_values: Iterable[str], qr_values: Iterable[str]) -> None:
        self.barcode_values = _unique_values(barcode_values)
        self.qr_values = _unique_values(qr_values)
        super().__init__(_unique_values([*self.barcode_values, *self.qr_values]))

BARCODE_REQUIRED_CATEGORY_TYPES = {
    "meter_barcode": "meter",
    "collector_barcode": "collector",
    "module_meter": "module",
    "module_barcode": "module",
}

REQUIRED_STATUSES = {"matched", "mismatched", "unreadable"}
GROUP_BARCODE_TYPES = ("meter", "module", "collector")
GROUP_BARCODE_REQUIRED_PHOTO_COUNT = 4
BARCODE_RESCUE_ROTATION_ANGLES = (5, -5, 10, -10, 15, -15, 20, -20, 25, -25, 30, -30, 8, -8, 12, -12)
BARCODE_RESCUE_FOCUS_ROTATION_ANGLES = BARCODE_RESCUE_ROTATION_ANGLES[:12]
BARCODE_RESCUE_UPSCALE_ROTATION_ANGLES = (5, -5, 10, -10, 15, -15, 20, -20)
BARCODE_RESCUE_FOCUS_BOXES = ((0.0, 0.4, 1.0, 1.0), (0.05, 0.15, 0.95, 0.9))
BARCODE_RESCUE_TARGET_LONG_SIDE = 1800
BARCODE_RESCUE_MAX_WORK_LONG_SIDE = 2200
BARCODE_RESCUE_MAX_CANDIDATES = 40
BARCODE_SLOW_RESCAN_MAX_CANDIDATES = 12
REGION_BARCODE_TYPES = frozenset({"meter", "module", "collector"})
REGION_MIN_SIDE_PIXELS = 24
OCR_RESCUE_ROTATION_ANGLES = (0, 5, -5)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


_REMOTE_IMAGE_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirectHandler)
OCR_RESCUE_MAX_CANDIDATES = 3
OCR_RESCUE_TIMEOUT_SECONDS = 3
OCR_RESCUE_SEMAPHORE = BoundedSemaphore(1)
OCR_ASSISTED_FRAGMENT_MIN_LENGTH = 12
OCR_ASSISTED_NEAR_FULL_MAX_DISTANCE = 2
OCR_REVIEW_REQUIRED_METHODS = {"ocr", "barcode_ocr", "ocr_assisted"}

BARCODE_CHECK_FIELDS = (
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
    "machine_barcode_values",
    "machine_barcode_normalized_values",
    "machine_qr_values",
    "machine_qr_normalized_values",
    "ocr_candidate_values",
    "ocr_candidate_normalized_values",
)


def normalize_barcode_value(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", str(value or "").strip()).upper()


def expected_type_for_category(category: str) -> str:
    return BARCODE_REQUIRED_CATEGORY_TYPES.get(str(category or "").strip(), "none")


def expected_values_for_group(group: dict[str, Any], expected_type: str) -> list[str]:
    raw_values: list[Any] = []
    if expected_type == "meter":
        raw_values.extend(
            [
                group.get("meter_no"),
                group.get("meter_match_key"),
                build_total_catalog_match_key(str(group.get("meter_no") or "")),
            ]
        )
    elif expected_type == "collector":
        raw_values.extend(
            [
                group.get("collector"),
                group.get("construction_collector"),
                group.get("construction_collector_no"),
            ]
        )
    elif expected_type == "module":
        raw_values.extend(
            [
                group.get("module_asset_no"),
                group.get("asset_no"),
                group.get("construction_module_asset_no"),
            ]
        )
    values = [normalize_barcode_value(item) for item in raw_values]
    return list(dict.fromkeys(item for item in values if item))


def check_photo_barcode(
    photo: dict[str, Any],
    group: dict[str, Any],
    *,
    scanner: BarcodeScanner | None = None,
    ocr_reader: OcrReader | None = None,
    use_ocr: bool = False,
    collect_group_evidence: bool = False,
) -> dict[str, Any]:
    expected_type = expected_type_for_category(str(photo.get("category") or ""))
    checked_at = datetime.now(UTC).isoformat()

    if expected_type == "none":
        scanned_values: list[str] = []
        normalized_scanned_values: list[str] = []
        machine_barcode_values: list[str] = []
        machine_qr_values: list[str] = []
        if collect_group_evidence:
            machine_barcode_values, machine_qr_values = _scan_machine_values(photo, scanner=scanner)
            machine_values = _unique_values([*machine_barcode_values, *machine_qr_values])
            ocr_values = _ocr_values(photo, [], ocr_reader=ocr_reader) if use_ocr and not machine_values else []
            scanned_values = _unique_values([*machine_values, *ocr_values])
            normalized_scanned_values = _normalized_values(scanned_values)
        else:
            ocr_values = []
        return {
            "barcode_check_status": "not_required",
            "barcode_check_expected_type": "none",
            "barcode_check_values": scanned_values,
            "barcode_check_normalized_values": normalized_scanned_values,
            "barcode_check_ocr_values": ocr_values,
            "barcode_check_ocr_normalized_values": _normalized_values(ocr_values),
            "barcode_check_expected_values": [],
            "barcode_check_matched_value": "",
            "barcode_checked_at": checked_at,
            "barcode_check_error": "",
            "barcode_check_method": "ocr" if ocr_values and not machine_barcode_values and not machine_qr_values else "barcode" if machine_barcode_values or machine_qr_values else "none",
            **_separated_recognition_fields(machine_barcode_values, machine_qr_values, ocr_values),
        }

    machine_barcode_values, machine_qr_values = _scan_machine_values(photo, scanner=scanner)
    machine_values = _unique_values([*machine_barcode_values, *machine_qr_values])
    normalized_machine_values = _normalized_values(machine_values)
    expected_context = dict(photo)
    expected_context.update({key: value for key, value in group.items() if value})
    expected_values = expected_values_for_group(expected_context, expected_type)
    machine_matched = _matched_expected_value(normalized_machine_values, expected_values, expected_type)
    ocr_values = _ocr_values(photo, expected_values, ocr_reader=ocr_reader) if use_ocr and not machine_matched else []
    normalized_ocr_values = _normalized_values(ocr_values)
    combined_values = _unique_values([*machine_values, *ocr_values])
    normalized_combined_values = _normalized_values(combined_values)

    if not normalized_combined_values:
        return {
            "barcode_check_status": "unreadable",
            "barcode_check_expected_type": expected_type,
            "barcode_check_values": [],
            "barcode_check_normalized_values": [],
            "barcode_check_ocr_values": [],
            "barcode_check_ocr_normalized_values": [],
            "barcode_check_expected_values": expected_values,
            "barcode_check_matched_value": "",
            "barcode_checked_at": checked_at,
            "barcode_check_error": "no_barcode_or_ocr_detected" if use_ocr else "no_barcode_detected",
            "barcode_check_method": "none",
            **_separated_recognition_fields([], [], []),
        }

    matched = _matched_expected_value(normalized_combined_values, expected_values, expected_type)
    return {
        "barcode_check_status": "matched" if matched else "mismatched",
        "barcode_check_expected_type": expected_type,
        "barcode_check_values": combined_values,
        "barcode_check_normalized_values": normalized_combined_values,
        "barcode_check_ocr_values": ocr_values,
        "barcode_check_ocr_normalized_values": normalized_ocr_values,
        "barcode_check_expected_values": expected_values,
        "barcode_check_matched_value": matched,
        "barcode_checked_at": checked_at,
        "barcode_check_error": "",
        "barcode_check_method": _barcode_check_method(machine_matched, ocr_values, matched),
        **_separated_recognition_fields(machine_barcode_values, machine_qr_values, ocr_values),
    }


def _separated_recognition_fields(
    machine_barcode_values: Iterable[Any],
    machine_qr_values: Iterable[Any],
    ocr_candidate_values: Iterable[Any],
) -> dict[str, list[str]]:
    barcodes = _unique_values(str(value or "").strip() for value in machine_barcode_values)
    qrs = _unique_values(str(value or "").strip() for value in machine_qr_values)
    ocr = _unique_values(str(value or "").strip() for value in ocr_candidate_values)
    return {
        "machine_barcode_values": barcodes,
        "machine_barcode_normalized_values": _normalized_values(barcodes),
        "machine_qr_values": qrs,
        "machine_qr_normalized_values": _normalized_values(qrs),
        "ocr_candidate_values": ocr,
        "ocr_candidate_normalized_values": _normalized_values(ocr),
    }


def ensure_photo_barcode_check(photo: dict[str, Any], group: dict[str, Any]) -> dict[str, Any]:
    status = str(photo.get("barcode_check_status") or "").strip()
    if status:
        return {key: photo[key] for key in BARCODE_CHECK_FIELDS if key in photo}
    return check_photo_barcode(photo, group)


def summarize_photo_accuracy(photos: Iterable[dict[str, Any]]) -> dict[str, Any]:
    passed = 0
    failed = 0
    unreadable = 0
    not_required = 0
    for photo in photos:
        status = str(photo.get("barcode_check_status") or "").strip()
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
        "photo_accuracy_checked": checked,
        "photo_accuracy_passed": passed,
        "photo_accuracy_failed": failed,
        "photo_accuracy_unreadable": unreadable,
        "photo_accuracy_not_required": not_required,
        "photo_accuracy_rate": round(passed / checked, 4) if checked else 0.0,
    }


def expected_group_barcode_values(group: dict[str, Any]) -> dict[str, list[str]]:
    context = _group_expected_context(group)
    return {
        barcode_type: expected_values_for_group(context, barcode_type)
        for barcode_type in GROUP_BARCODE_TYPES
    }


def build_group_barcode_check(group: dict[str, Any]) -> dict[str, Any]:
    expected_values = expected_group_barcode_values(group)
    missing_expected_fields = [
        barcode_type for barcode_type in GROUP_BARCODE_TYPES if not expected_values.get(barcode_type)
    ]
    detected_values: dict[str, list[str]] = {barcode_type: [] for barcode_type in GROUP_BARCODE_TYPES}
    matched_fields: list[str] = []
    unmatched_values: list[str] = []

    for photo in group.get("photos") or []:
        legacy_matched_type = _legacy_matched_group_barcode_type(photo)
        if legacy_matched_type and legacy_matched_type not in missing_expected_fields:
            legacy_values = _legacy_matched_group_barcode_values(photo)
            matched_value = next(
                (
                    value
                    for value in legacy_values
                    if _match_group_barcode_type(value, expected_values) == legacy_matched_type
                ),
                "",
            )
            if matched_value:
                _append_unique(matched_fields, legacy_matched_type)
                _append_unique(detected_values[legacy_matched_type], matched_value)
                for value in _photo_barcode_values(photo):
                    matched_type = _match_group_barcode_type(value, expected_values)
                    if matched_type:
                        _append_unique(detected_values[matched_type], value)
                        _append_unique(matched_fields, matched_type)
            else:
                for value in legacy_values:
                    matched_type = _match_group_barcode_type(value, expected_values)
                    if matched_type:
                        _append_unique(detected_values[matched_type], value)
                        _append_unique(matched_fields, matched_type)
                    else:
                        _append_unique(unmatched_values, value)
            continue
        for value in _photo_barcode_values(photo):
            matched_type = _match_group_barcode_type(value, expected_values)
            if matched_type:
                _append_unique(detected_values[matched_type], value)
                _append_unique(matched_fields, matched_type)
            else:
                    _append_unique(unmatched_values, value)

    manual_confirmed = bool(group.get("group_barcode_manual_confirmed"))
    manual_fields = group.get("group_barcode_manual_confirmed_fields") or []
    if manual_confirmed and not manual_fields:
        manual_fields = list(GROUP_BARCODE_TYPES)
    if not isinstance(manual_fields, list):
        manual_fields = [manual_fields]
    for barcode_type in manual_fields:
        barcode_type = str(barcode_type or "").strip()
        if barcode_type in GROUP_BARCODE_TYPES and barcode_type not in missing_expected_fields:
            _append_unique(matched_fields, barcode_type)
            for value in expected_values.get(barcode_type, [])[:1]:
                _append_unique(detected_values[barcode_type], value)

    missing_fields = [
        barcode_type
        for barcode_type in GROUP_BARCODE_TYPES
        if barcode_type not in matched_fields and barcode_type not in missing_expected_fields
    ]
    if missing_expected_fields:
        status = "not_required"
    elif not missing_fields:
        status = "matched"
    elif unmatched_values:
        status = "mismatched"
    elif missing_fields:
        status = "unreadable"
    else:
        status = "matched"

    return {
        "group_barcode_check_status": status,
        "group_barcode_missing_fields": missing_fields,
        "group_barcode_missing_expected_fields": missing_expected_fields,
        "group_barcode_expected_values": expected_values,
        "group_barcode_detected_values": detected_values,
        "group_barcode_matched_fields": matched_fields,
        "group_barcode_unmatched_values": unmatched_values,
        "group_barcode_manual_confirmed": manual_confirmed,
        "group_barcode_manual_confirmed_fields": [
            field for field in manual_fields if field in GROUP_BARCODE_TYPES
        ],
        "group_barcode_manual_confirmed_by": group.get("group_barcode_manual_confirmed_by") or "",
        "group_barcode_manual_confirmed_at": group.get("group_barcode_manual_confirmed_at") or "",
    }


def has_complete_group_photo_set(group: dict[str, Any]) -> bool:
    return len(group.get("photos") or []) == GROUP_BARCODE_REQUIRED_PHOTO_COUNT


def summarize_group_barcode_accuracy(groups: Iterable[dict[str, Any]]) -> dict[str, Any]:
    from app.services.barcode_verification_contract import summarize_durable_accuracy

    return summarize_durable_accuracy(list(groups))


def list_group_barcode_review_items(
    groups: Iterable[dict[str, Any]],
    *,
    statuses: set[str] | None = None,
) -> list[dict[str, Any]]:
    target_statuses = statuses or {"unreadable", "mismatched"}
    items: list[dict[str, Any]] = []
    for group in groups:
        from app.services.barcode_verification_contract import (
            has_current_eligible_photo_set,
            legacy_review_status,
            normalize_barcode_verification,
            verification_compatibility_fields,
        )

        durable_verification = normalize_barcode_verification(group.get("barcode_verification"))
        if durable_verification:
            if not has_current_eligible_photo_set(group):
                continue
            status = legacy_review_status(str(durable_verification.get("status") or ""))
            if not status or status not in target_statuses:
                continue
            result = durable_verification.get("result") or {}
            expected = expected_group_barcode_values(group)
            matched_fields = [str(item) for item in result.get("matched_fields") or []]
            detected_values = {field: expected.get(field, []) if field in matched_fields else [] for field in GROUP_BARCODE_TYPES}
            item = {
                "group_id": str(group.get("id") or group.get("group_id") or ""),
                "meter_no": str(group.get("meter_no") or group.get("barcode") or ""),
                "module_asset_no": str(group.get("module_asset_no") or group.get("asset_no") or ""),
                "collector": str(group.get("collector") or group.get("construction_collector") or ""),
                "terminal": str(group.get("terminal") or ""),
                "address": str(group.get("address") or group.get("installation_address") or ""),
                "installer": str(group.get("installer") or group.get("creator") or ""),
                "group_status": str(group.get("status") or group.get("group_status") or ""),
                "archived": str(group.get("status") or group.get("group_status") or "") == "approved",
                "photo_count": int(group.get("photo_count") or len(group.get("photos") or []) or 0),
                "status": status,
                "missing_fields": list(result.get("missing_fields") or []),
                "missing_expected_fields": [field for field in GROUP_BARCODE_TYPES if not expected.get(field)],
                "expected": expected,
                "detected_values": detected_values,
                "unmatched_values": [
                    *list(result.get("unmatched_machine_values") or []),
                    *list(result.get("unmatched_ocr_candidates") or []),
                ],
                "barcode_verification": durable_verification,
                "photo_category_classified_count": len({str(photo.get("category") or "") for photo in group.get("photos") or []}),
                "photo_category_total_count": len(group.get("photos") or []),
                "photo_category_complete": True,
                "photo_category_status": "complete",
                "photos": [_group_review_photo_payload(group, photo) for photo in group.get("photos") or []],
            }
            item.update(verification_compatibility_fields(durable_verification))
            items.append(item)
            continue
        if not has_complete_group_photo_set(group):
            continue
        check = build_group_barcode_check(group)
        status = str(check.get("group_barcode_check_status") or "")
        if status not in target_statuses:
            continue
        items.append(
            {
                "group_id": str(group.get("id") or group.get("group_id") or ""),
                "meter_no": str(group.get("meter_no") or group.get("barcode") or ""),
                "module_asset_no": str(group.get("module_asset_no") or group.get("asset_no") or ""),
                "collector": str(group.get("collector") or group.get("construction_collector") or ""),
                "terminal": str(group.get("terminal") or ""),
                "address": str(group.get("address") or group.get("installation_address") or ""),
                "installer": str(group.get("installer") or group.get("creator") or ""),
                "group_status": str(group.get("status") or group.get("group_status") or ""),
                "archived": str(group.get("status") or group.get("group_status") or "") == "approved",
                "photo_count": int(group.get("photo_count") or len(group.get("photos") or []) or 0),
                "status": status,
                "missing_fields": check["group_barcode_missing_fields"],
                "missing_expected_fields": check["group_barcode_missing_expected_fields"],
                "expected": check["group_barcode_expected_values"],
                "detected_values": check["group_barcode_detected_values"],
                "unmatched_values": check["group_barcode_unmatched_values"],
                "photos": [_group_review_photo_payload(group, photo) for photo in group.get("photos") or []],
            }
        )
    return items


def default_barcode_scanner(photo: dict[str, Any]) -> list[str]:
    channels = default_machine_code_scanner(photo)
    return MachineCodeValues(channels["barcode"], channels["qr"])


def default_machine_code_scanner(photo: dict[str, Any]) -> dict[str, list[str]]:
    try:
        import zxingcpp  # type: ignore # noqa: F401
    except Exception:
        return {"barcode": [], "qr": []}

    image = _photo_image(photo)
    if image is None:
        return {"barcode": [], "qr": []}
    try:
        return _scan_barcode_image_channels(image, candidate_limit=_scan_candidate_limit(photo))
    finally:
        try:
            image.close()
        except Exception:
            pass


def _scan_barcode_image(image, *, candidate_limit: int) -> list[str]:
    channels = _scan_barcode_image_channels(image, candidate_limit=candidate_limit)
    return _unique_values([*channels["barcode"], *channels["qr"]])


def _scan_barcode_image_channels(image, *, candidate_limit: int) -> dict[str, list[str]]:
    try:
        import zxingcpp  # type: ignore
    except Exception:
        return {"barcode": [], "qr": []}

    try:
        barcodes: list[str] = []
        qrs: list[str] = []
        remaining_candidates = max(0, candidate_limit)
        for candidate in _barcode_scan_candidates(image):
            if remaining_candidates == 0:
                break
            remaining_candidates -= 1
            try:
                scanned_items = _read_zxing_barcodes(zxingcpp, candidate)
                for item in scanned_items:
                    for value in _scan_text_candidates(getattr(item, "text", "")):
                        target = qrs if _is_qr_result(item) else barcodes
                        _append_unique(target, value)
            except Exception:
                continue
            if barcodes or qrs:
                return {"barcode": barcodes, "qr": qrs}
        return {"barcode": barcodes, "qr": qrs}
    except Exception:
        return {"barcode": [], "qr": []}


def _is_qr_result(item: Any) -> bool:
    return "qr" in str(getattr(item, "format", "")).replace("_", "").lower()


def scan_photo_region(
    photo: dict[str, Any],
    barcode_type: str,
    region: Mapping[str, float],
) -> dict[str, Any]:
    from PIL import ImageOps

    normalized_region = _validated_normalized_region(region)
    if barcode_type not in REGION_BARCODE_TYPES:
        raise ValueError("Unsupported barcode type")
    image = _photo_image(photo)
    if image is None:
        raise ValueError("Photo image is unavailable")
    oriented = image
    crop = None
    try:
        oriented = ImageOps.exif_transpose(image)
        left = round(normalized_region["x"] * oriented.width)
        top = round(normalized_region["y"] * oriented.height)
        right = round((normalized_region["x"] + normalized_region["width"]) * oriented.width)
        bottom = round((normalized_region["y"] + normalized_region["height"]) * oriented.height)
        if right - left < REGION_MIN_SIDE_PIXELS or bottom - top < REGION_MIN_SIDE_PIXELS:
            raise ValueError("Selected region is too small")
        crop = oriented.crop((left, top, right, bottom))
        values = _scan_barcode_image(crop, candidate_limit=_scan_candidate_limit(photo))
        method = "barcode" if values else ""
        if not values:
            if shutil.which("tesseract") and OCR_RESCUE_SEMAPHORE.acquire(blocking=False):
                try:
                    values = _scan_ocr_image(crop, expected_values=[])
                finally:
                    OCR_RESCUE_SEMAPHORE.release()
            method = "ocr" if values else "none"
        normalized_values = _normalized_values(values)
        return {
            "barcode_type": barcode_type,
            "values": _unique_values(values),
            "normalized_values": _unique_values(normalized_values),
            "method": method,
            "region": normalized_region,
        }
    finally:
        if crop is not None:
            try:
                crop.close()
            except Exception:
                pass
        if oriented is not image:
            try:
                oriented.close()
            except Exception:
                pass
        try:
            image.close()
        except Exception:
            pass


def _validated_normalized_region(region: Mapping[str, float]) -> dict[str, float]:
    try:
        normalized = {name: float(region[name]) for name in ("x", "y", "width", "height")}
    except (KeyError, TypeError, ValueError):
        raise ValueError("Invalid region") from None
    if (
        not all(math.isfinite(value) and 0 <= value <= 1 for value in normalized.values())
        or normalized["width"] <= 0
        or normalized["height"] <= 0
        or normalized["x"] + normalized["width"] > 1
        or normalized["y"] + normalized["height"] > 1
    ):
        raise ValueError("Invalid region")
    return normalized


def _scan_candidate_limit(photo: dict[str, Any]) -> int:
    raw_limit = photo.get("barcode_scan_max_candidates")
    if raw_limit is None:
        raw_limit = BARCODE_RESCUE_MAX_CANDIDATES
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        limit = BARCODE_RESCUE_MAX_CANDIDATES
    if limit <= 0:
        return BARCODE_RESCUE_MAX_CANDIDATES
    return min(limit, BARCODE_RESCUE_MAX_CANDIDATES)


def _read_zxing_barcodes(zxingcpp: Any, candidate: Any) -> Iterable[Any]:
    formats = _zxing_formats_with_qr(zxingcpp)
    if formats is None:
        return zxingcpp.read_barcodes(candidate)
    try:
        return zxingcpp.read_barcodes(candidate, formats=formats)
    except TypeError:
        return zxingcpp.read_barcodes(candidate)


def _zxing_formats_with_qr(zxingcpp: Any) -> Any:
    barcode_format = getattr(zxingcpp, "BarcodeFormat", None)
    if barcode_format is None:
        return None
    any_format = getattr(barcode_format, "Any", None)
    if any_format is not None:
        return any_format
    linear = getattr(barcode_format, "LinearCodes", None)
    qr = getattr(barcode_format, "QRCode", None)
    micro_qr = getattr(barcode_format, "MicroQRCode", None)
    if linear is None or qr is None:
        return None
    try:
        combined = linear | qr
        if micro_qr is not None:
            combined = combined | micro_qr
        return combined
    except Exception:
        return None


def _scan_text_candidates(text: Any) -> list[str]:
    raw = str(text or "").strip()
    values: list[str] = []
    _append_unique(values, normalize_barcode_value(raw))
    for token in re.findall(r"[0-9A-Za-z]{6,}", raw):
        value = normalize_barcode_value(token)
        if len(value) >= 6 and any(char.isdigit() for char in value):
            _append_unique(values, value)
    return values


def default_ocr_reader(photo: dict[str, Any], expected_values: list[str]) -> list[str]:
    if not shutil.which("tesseract"):
        return []
    if not OCR_RESCUE_SEMAPHORE.acquire(blocking=False):
        return []
    image = _photo_image(photo)
    if image is None:
        OCR_RESCUE_SEMAPHORE.release()
        return []
    try:
        return _scan_ocr_image(image, expected_values=expected_values)
    finally:
        try:
            image.close()
        except Exception:
            pass
        OCR_RESCUE_SEMAPHORE.release()


def _scan_ocr_image(image, *, expected_values: list[str]) -> list[str]:
    try:
        values: list[str] = []
        for candidate in _ocr_scan_candidates(image):
            text = _run_tesseract(candidate)
            for value in _extract_ocr_candidates(text, expected_values):
                _append_unique(values, value)
            if _matched_expected_value(_normalized_values(values), expected_values, ""):
                return values
        return values
    except Exception:
        return []


def _ocr_scan_candidates(image):
    created = []
    yielded = 0
    try:
        work_image = _resize_barcode_work_image(image)
        if work_image is not image:
            created.append(work_image)
        enhanced = _enhance_ocr_image(work_image)
        created.append(enhanced)

        base_images = []
        for box in _ocr_digit_line_focus_boxes():
            cropped = _crop_ratio(work_image, box)
            created.append(cropped)
            digit_line = _enhance_ocr_digit_line_image(cropped)
            created.append(digit_line)
            base_images.append(digit_line)
        base_images.append(enhanced)

        for box in BARCODE_RESCUE_FOCUS_BOXES:
            cropped = _crop_ratio(work_image, box)
            created.append(cropped)
            focus = _enhance_ocr_image(cropped)
            created.append(focus)
            base_images.append(focus)

        for base in base_images:
            for angle in OCR_RESCUE_ROTATION_ANGLES:
                if yielded >= OCR_RESCUE_MAX_CANDIDATES:
                    return
                if angle:
                    candidate = base.rotate(angle, expand=True, fillcolor=255)
                    created.append(candidate)
                else:
                    candidate = base
                yield candidate
                yielded += 1
    finally:
        for candidate in created:
            try:
                candidate.close()
            except Exception:
                pass


def _barcode_scan_candidates(image):
    created = []
    yielded = 0
    try:
        if yielded >= BARCODE_RESCUE_MAX_CANDIDATES:
            return
        yield image
        yielded += 1
        work_image = _resize_barcode_work_image(image)
        if work_image is not image:
            created.append(work_image)
        enhanced = _enhance_barcode_image(work_image)
        created.append(enhanced)
        if yielded >= BARCODE_RESCUE_MAX_CANDIDATES:
            return
        yield enhanced
        yielded = 2

        focus_images = []
        for box in BARCODE_RESCUE_FOCUS_BOXES:
            if yielded >= BARCODE_RESCUE_MAX_CANDIDATES:
                return
            cropped = _crop_ratio(work_image, box)
            created.append(cropped)
            focus = _enhance_barcode_image(cropped)
            created.append(focus)
            focus_images.append(focus)
            yield focus
            yielded += 1
            for angle in BARCODE_RESCUE_FOCUS_ROTATION_ANGLES:
                if yielded >= BARCODE_RESCUE_MAX_CANDIDATES:
                    return
                rotated = focus.rotate(angle, expand=True, fillcolor=255)
                created.append(rotated)
                yield rotated
                yielded += 1

        upscaled = _upscale_barcode_image(enhanced)
        if upscaled is not enhanced:
            created.append(upscaled)
            if yielded >= BARCODE_RESCUE_MAX_CANDIDATES:
                return
            yield upscaled
            yielded += 1
            for angle in BARCODE_RESCUE_UPSCALE_ROTATION_ANGLES:
                if yielded >= BARCODE_RESCUE_MAX_CANDIDATES:
                    return
                rotated = upscaled.rotate(angle, expand=True, fillcolor=255)
                created.append(rotated)
                yield rotated
                yielded += 1

        for angle in BARCODE_RESCUE_ROTATION_ANGLES:
            if yielded >= BARCODE_RESCUE_MAX_CANDIDATES:
                return
            rotated = enhanced.rotate(angle, expand=True, fillcolor=255)
            created.append(rotated)
            yield rotated
            yielded += 1
    finally:
        for candidate in created:
            try:
                candidate.close()
            except Exception:
                pass


def _enhance_barcode_image(image):
    from PIL import ImageEnhance, ImageFilter, ImageOps

    enhanced = ImageOps.grayscale(image)
    enhanced = ImageOps.autocontrast(enhanced, cutoff=1)
    enhanced = ImageEnhance.Contrast(enhanced).enhance(1.8)
    return enhanced.filter(ImageFilter.SHARPEN)


def _enhance_ocr_image(image):
    from PIL import ImageEnhance, ImageFilter, ImageOps

    enhanced = ImageOps.grayscale(image)
    enhanced = ImageOps.autocontrast(enhanced, cutoff=1)
    enhanced = ImageEnhance.Contrast(enhanced).enhance(2.1)
    return enhanced.filter(ImageFilter.SHARPEN)


def _ocr_digit_line_focus_boxes() -> tuple[tuple[float, float, float, float], ...]:
    return (
        (0.15, 0.612, 0.677, 0.646),
        (0.14, 0.60, 0.70, 0.66),
        (0.12, 0.58, 0.72, 0.68),
    )


def _enhance_ocr_digit_line_image(image):
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    line = ImageOps.grayscale(image)
    split_x = max(1, min(line.width - 1, int(line.width * 0.58)))
    left = ImageOps.autocontrast(line.crop((0, 0, split_x, line.height)), cutoff=0)
    left = ImageEnhance.Brightness(left).enhance(1.45)
    left = ImageEnhance.Contrast(left).enhance(1.8)
    right = ImageOps.autocontrast(line.crop((split_x, 0, line.width, line.height)), cutoff=0)
    right = ImageEnhance.Contrast(right).enhance(1.5)
    joined = Image.new("L", line.size, 255)
    joined.paste(left, (0, 0))
    joined.paste(right, (split_x, 0))
    upscaled = joined.resize((joined.width * 6, joined.height * 6), _lanczos_resampling())
    upscaled = upscaled.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=2))
    canvas = Image.new("L", (upscaled.width + 80, upscaled.height + 60), 255)
    canvas.paste(upscaled, (40, 30))
    return canvas


def _upscale_barcode_image(image):
    long_side = max(image.size)
    if long_side >= BARCODE_RESCUE_TARGET_LONG_SIDE:
        return image
    scale = BARCODE_RESCUE_TARGET_LONG_SIDE / long_side
    if scale <= 1.05:
        return image
    return image.resize((int(image.width * scale), int(image.height * scale)), _lanczos_resampling())


def _resize_barcode_work_image(image):
    long_side = max(image.size)
    if long_side <= BARCODE_RESCUE_MAX_WORK_LONG_SIDE:
        return image
    scale = BARCODE_RESCUE_MAX_WORK_LONG_SIDE / long_side
    return image.resize((int(image.width * scale), int(image.height * scale)), _lanczos_resampling())


def _crop_ratio(image, box: tuple[float, float, float, float]):
    left, top, right, bottom = box
    width, height = image.size
    return image.crop(
        (
            int(width * left),
            int(height * top),
            int(width * right),
            int(height * bottom),
        )
    )


def _lanczos_resampling():
    from PIL import Image

    return getattr(getattr(Image, "Resampling", Image), "LANCZOS")


def _scan_machine_values(
    photo: dict[str, Any],
    *,
    scanner: BarcodeScanner | None,
) -> tuple[list[str], list[str]]:
    scan = scanner or default_barcode_scanner
    try:
        values = scan(photo)
    except Exception:
        values = {"barcode": [], "qr": []}
    if isinstance(values, Mapping):
        barcode_values = values.get("barcode") or []
        qr_values = values.get("qr") or []
    elif isinstance(values, MachineCodeValues):
        barcode_values = values.barcode_values
        qr_values = values.qr_values
    else:
        barcode_values = values
        qr_values = []
    return _unique_values(barcode_values), _unique_values(qr_values)


def _ocr_values(
    photo: dict[str, Any],
    expected_values: list[str],
    *,
    ocr_reader: OcrReader | None,
) -> list[str]:
    reader = ocr_reader or default_ocr_reader
    try:
        values = reader(photo, expected_values)
    except Exception:
        values = []
    cleaned = [str(item or "").strip() for item in values]
    return _unique_values(cleaned)


def _run_tesseract(image) -> str:
    executable = shutil.which("tesseract")
    if not executable:
        return ""
    handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    path = Path(handle.name)
    handle.close()
    try:
        image.save(path)
        base_command = [
            executable,
            str(path),
            "stdout",
            "-l",
            "eng",
        ]
        config_command = [
            "-c",
            "tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
        ]
        completed = subprocess.run(
            [*base_command, "--psm", "7", *config_command],
            capture_output=True,
            text=True,
            timeout=OCR_RESCUE_TIMEOUT_SECONDS,
            check=False,
        )
        if not completed.stdout and "read_params_file" in (completed.stderr or ""):
            completed = subprocess.run(
                [*base_command, "-psm", "7", *config_command],
                capture_output=True,
                text=True,
                timeout=OCR_RESCUE_TIMEOUT_SECONDS,
                check=False,
            )
        return completed.stdout or ""
    except Exception:
        return ""
    finally:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass


def _extract_ocr_candidates(text: str, expected_values: list[str]) -> list[str]:
    normalized_text = normalize_barcode_value(text)
    values: list[str] = []
    for expected in expected_values:
        normalized_expected = normalize_barcode_value(expected)
        if normalized_expected and normalized_expected in normalized_text:
            _append_unique(values, normalized_expected)
    tokens: list[str] = []
    for token in re.findall(r"[0-9A-Za-z]{6,}", text or ""):
        value = normalize_barcode_value(token)
        _append_unique(tokens, value)
    for token in re.findall(r"\d{6,}", text or ""):
        value = normalize_barcode_value(token)
        _append_unique(tokens, value)
    for token in tokens:
        assisted = _unique_ocr_assisted_expected_value(token, expected_values)
        if assisted:
            _append_unique(values, assisted)
    if values:
        return values[:12]
    for value in tokens:
        if len(value) >= 8 and any(char.isdigit() for char in value):
            _append_unique(values, value)
        if len(values) >= 12:
            break
    return values


def _unique_ocr_assisted_expected_value(value: str, expected_values: list[str]) -> str:
    token = normalize_barcode_value(value)
    if len(token) < OCR_ASSISTED_FRAGMENT_MIN_LENGTH or not any(char.isdigit() for char in token):
        return ""
    matches: list[str] = []
    for expected in expected_values:
        normalized_expected = normalize_barcode_value(expected)
        if not normalized_expected:
            continue
        if _ocr_token_matches_expected(token, normalized_expected):
            _append_unique(matches, normalized_expected)
    return matches[0] if len(matches) == 1 else ""


def _ocr_token_matches_expected(token: str, expected: str) -> bool:
    if token == expected:
        return True
    if len(token) < max(OCR_ASSISTED_FRAGMENT_MIN_LENGTH, len(expected) - OCR_ASSISTED_NEAR_FULL_MAX_DISTANCE):
        return len(token) >= OCR_ASSISTED_FRAGMENT_MIN_LENGTH and (
            expected.startswith(token) or expected.endswith(token)
        )
    if abs(len(token) - len(expected)) <= OCR_ASSISTED_NEAR_FULL_MAX_DISTANCE:
        return _bounded_edit_distance(token, expected, OCR_ASSISTED_NEAR_FULL_MAX_DISTANCE) <= OCR_ASSISTED_NEAR_FULL_MAX_DISTANCE
    return False


def _bounded_edit_distance(left: str, right: str, limit: int) -> int:
    if abs(len(left) - len(right)) > limit:
        return limit + 1
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        row_min = current[0]
        for right_index, right_char in enumerate(right, start=1):
            insert_cost = current[right_index - 1] + 1
            delete_cost = previous[right_index] + 1
            replace_cost = previous[right_index - 1] + (left_char != right_char)
            value = min(insert_cost, delete_cost, replace_cost)
            current.append(value)
            row_min = min(row_min, value)
        if row_min > limit:
            return limit + 1
        previous = current
    return previous[-1]


def _normalized_values(values: Iterable[Any]) -> list[str]:
    return _unique_values(normalize_barcode_value(value) for value in values)


def _unique_values(values: Iterable[Any]) -> list[str]:
    return list(dict.fromkeys(str(item or "").strip() for item in values if str(item or "").strip()))


def _review_evidence_array(value: Any) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if str(item or "").strip()]


def _matched_expected_value(normalized_values: Iterable[str], expected_values: list[str], expected_type: str) -> str:
    expected = set(expected_values)
    for value in normalized_values:
        if value in expected:
            return value
        if expected_type == "meter":
            try:
                if build_long_scan_match_key(value) in expected:
                    return value
            except ValueError:
                pass
    return ""


def _barcode_check_method(barcode_matched: str, ocr_values: list[str], matched: str) -> str:
    if matched and barcode_matched:
        return "barcode"
    if matched and ocr_values:
        return "ocr"
    if ocr_values:
        return "barcode_ocr"
    return "barcode"


def _photo_barcode_values(photo: dict[str, Any]) -> list[str]:
    raw_values = _review_evidence_array(photo.get("barcode_check_normalized_values"))
    if not raw_values:
        raw_values = _review_evidence_array(photo.get("barcode_check_values"))
    values = [normalize_barcode_value(value) for value in raw_values]
    return list(dict.fromkeys(value for value in values if value))


def _match_group_barcode_type(value: str, expected_values: dict[str, list[str]]) -> str:
    for barcode_type in GROUP_BARCODE_TYPES:
        if value in expected_values.get(barcode_type, []):
            return barcode_type
        if barcode_type == "meter":
            try:
                if build_long_scan_match_key(value) in expected_values.get("meter", []):
                    return "meter"
            except ValueError:
                pass
    return ""


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _legacy_matched_group_barcode_type(photo: dict[str, Any]) -> str:
    status = str(photo.get("barcode_check_status") or "").strip()
    expected_type = str(photo.get("barcode_check_expected_type") or "").strip()
    if status == "matched" and expected_type in GROUP_BARCODE_TYPES:
        return expected_type
    return ""


def _legacy_matched_group_barcode_values(photo: dict[str, Any]) -> list[str]:
    values: list[str] = []
    _append_unique(values, normalize_barcode_value(photo.get("barcode_check_matched_value")))
    for value in _photo_barcode_values(photo):
        _append_unique(values, value)
    return values


def _group_expected_context(group: dict[str, Any]) -> dict[str, Any]:
    context = dict(group)
    photo_fallbacks = {
        "meter_no": ("meter_no", "barcode"),
        "meter_match_key": ("meter_match_key",),
        "collector": ("collector", "construction_collector", "construction_collector_no"),
        "module_asset_no": ("module_asset_no", "asset_no", "construction_module_asset_no"),
        "asset_no": ("asset_no", "module_asset_no", "construction_module_asset_no"),
    }
    for target_key, source_keys in photo_fallbacks.items():
        if str(context.get(target_key) or "").strip():
            continue
        for photo in group.get("photos") or []:
            value = next((photo.get(source_key) for source_key in source_keys if photo.get(source_key)), "")
            if value:
                context[target_key] = value
                break
    return context


def _group_review_photo_payload(group: dict[str, Any], photo: dict[str, Any]) -> dict[str, Any]:
    group_id = str(group.get("id") or group.get("group_id") or "")
    photo_id = str(photo.get("id") or photo.get("photo_id") or "")
    image_url = str(photo.get("image_url") or photo.get("url") or photo.get("preview_url") or "")
    content_url = f"/local-test/groups/{group_id}/photos/{photo_id}/content" if group_id and photo_id else ""
    if content_url and (not image_url or image_url.lower().startswith("oss://")):
        image_url = content_url
    thumbnail_url = str(photo.get("thumbnail_url") or "")
    if not thumbnail_url:
        if content_url:
            thumbnail_url = f"{content_url}?kind=thumbnail"
        elif "/content" in image_url:
            thumbnail_url = image_url if "kind=" in image_url else f"{image_url}?kind=thumbnail"
        elif image_url:
            thumbnail_url = image_url
    return {
        "id": photo_id,
        "category": str(photo.get("category") or ""),
        "category_label": str(photo.get("category_label") or ""),
        "image_url": image_url,
        "thumbnail_url": thumbnail_url,
        "barcode_check_status": str(photo.get("barcode_check_status") or ""),
        "barcode_check_values": _review_evidence_array(photo.get("barcode_check_values")),
        "barcode_check_normalized_values": _photo_barcode_values(photo),
        "barcode_check_ocr_values": _review_evidence_array(photo.get("barcode_check_ocr_values")),
        "barcode_check_ocr_normalized_values": _normalized_values(
            _review_evidence_array(photo.get("barcode_check_ocr_values"))
        ),
        "barcode_check_method": str(photo.get("barcode_check_method") or ""),
        "machine_barcode_values": _review_evidence_array(photo.get("machine_barcode_values")),
        "machine_barcode_normalized_values": _review_evidence_array(
            photo.get("machine_barcode_normalized_values")
        ),
        "machine_qr_values": _review_evidence_array(photo.get("machine_qr_values")),
        "machine_qr_normalized_values": _review_evidence_array(photo.get("machine_qr_normalized_values")),
        "ocr_candidate_values": _review_evidence_array(photo.get("ocr_candidate_values")),
        "ocr_candidate_normalized_values": _review_evidence_array(photo.get("ocr_candidate_normalized_values")),
    }


def _photo_local_path(photo: dict[str, Any]) -> Path | None:
    for key in ("local_path", "path", "file_path", "object_key", "storage_key"):
        value = str(photo.get(key) or "").strip()
        if not value:
            continue
        path = Path(value)
        if path.exists():
            return path
    storage_type = str(photo.get("storage_type") or "").strip()
    storage_key = str(photo.get("storage_key") or "").strip()
    if storage_type == "local_upload" and storage_key:
        path = static_upload_root() / storage_key.lstrip("/")
        if path.exists():
            return path
    for key in ("image_url", "url", "source_url", "delivery_cache_url", "preview_url", "thumbnail_url"):
        image_url = str(photo.get(key) or "").strip()
        if not image_url:
            continue
        if image_url.startswith("/static/uploads/"):
            path = static_upload_root() / image_url.removeprefix("/static/uploads/").lstrip("/")
            if path.exists():
                return path
        parsed = urlparse(image_url)
        if parsed.scheme in {"", "file"}:
            path = Path(parsed.path or image_url)
            if path.exists():
                return path
    return None


def _photo_image(photo: dict[str, Any]):
    try:
        from PIL import Image
    except Exception:
        return None

    path = _photo_local_path(photo)
    try:
        if path is not None:
            image = Image.open(path)
            image.load()
            return image
        content = _download_photo_content(photo)
        if not content:
            return None
        validate_image_content(content, source="barcode photo")
        image = Image.open(BytesIO(content))
        image.load()
        return image
    except Exception:
        return None


def _download_photo_content(photo: dict[str, Any]) -> bytes | None:
    image_url = _download_photo_url(photo)
    if not image_url:
        return None
    is_trusted_oss = _is_trusted_oss_photo(photo)
    opener = urllib.request.urlopen if is_trusted_oss else _REMOTE_IMAGE_NO_REDIRECT_OPENER.open
    try:
        with opener(image_url, timeout=8) as response:
            return response.read(8 * 1024 * 1024)
    except HTTPError as exc:
        if not is_trusted_oss and 300 <= exc.code < 400:
            location = exc.headers.get("Location") or ""
            if location:
                try:
                    validate_remote_image_url(urljoin(image_url, location))
                except ValueError:
                    return None
            return None
        return None
    except Exception:
        return None


def _is_trusted_oss_photo(photo: dict[str, Any]) -> bool:
    storage_type = str(photo.get("storage_type") or "").strip()
    image_url = str(photo.get("image_url") or photo.get("url") or photo.get("source_url") or "").strip()
    return storage_type == "oss" or image_url.startswith("oss://")


def _download_photo_url(photo: dict[str, Any]) -> str:
    storage_type = str(photo.get("storage_type") or "").strip()
    storage_key = str(photo.get("storage_key") or "").strip()
    image_url = str(photo.get("image_url") or photo.get("url") or photo.get("source_url") or "").strip()
    if storage_type == "oss" or image_url.startswith("oss://"):
        key = storage_key or parse_oss_image_url(image_url)[1]
        if key:
            try:
                return sign_oss_server_url(key)
            except RuntimeError:
                return ""
    for key in ("image_url", "source_url", "url", "preview_url", "delivery_cache_url", "thumbnail_url"):
        value = str(photo.get(key) or "").strip()
        if value.lower().startswith(("http://", "https://")):
            try:
                validate_remote_image_url(value)
            except ValueError:
                continue
            return value
    return ""
