from __future__ import annotations

import re
import urllib.request
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

from app.services.matching import build_long_scan_match_key, build_total_catalog_match_key
from app.services.photo_storage import parse_oss_image_url, sign_oss_server_url, static_upload_root, validate_image_content

BarcodeScanner = Callable[[dict[str, Any]], Iterable[str]]

BARCODE_REQUIRED_CATEGORY_TYPES = {
    "meter_barcode": "meter",
    "collector_barcode": "collector",
    "module_meter": "module",
    "module_barcode": "module",
}

REQUIRED_STATUSES = {"matched", "mismatched", "unreadable"}
GROUP_BARCODE_TYPES = ("meter", "module", "collector")

BARCODE_CHECK_FIELDS = (
    "barcode_check_status",
    "barcode_check_expected_type",
    "barcode_check_values",
    "barcode_check_normalized_values",
    "barcode_check_expected_values",
    "barcode_check_matched_value",
    "barcode_checked_at",
    "barcode_check_error",
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
) -> dict[str, Any]:
    expected_type = expected_type_for_category(str(photo.get("category") or ""))
    checked_at = datetime.now(UTC).isoformat()

    if expected_type == "none":
        return {
            "barcode_check_status": "not_required",
            "barcode_check_expected_type": "none",
            "barcode_check_values": [],
            "barcode_check_normalized_values": [],
            "barcode_check_expected_values": [],
            "barcode_check_matched_value": "",
            "barcode_checked_at": checked_at,
            "barcode_check_error": "",
        }

    scanned_values = _scan_values(photo, scanner=scanner)
    normalized_scanned_values = [normalize_barcode_value(item) for item in scanned_values]
    expected_context = dict(photo)
    expected_context.update({key: value for key, value in group.items() if value})
    expected_values = expected_values_for_group(expected_context, expected_type)

    if not normalized_scanned_values:
        return {
            "barcode_check_status": "unreadable",
            "barcode_check_expected_type": expected_type,
            "barcode_check_values": [],
            "barcode_check_normalized_values": [],
            "barcode_check_expected_values": expected_values,
            "barcode_check_matched_value": "",
            "barcode_checked_at": checked_at,
            "barcode_check_error": "no_barcode_detected",
        }

    matched = next((value for value in normalized_scanned_values if value in expected_values), "")
    return {
        "barcode_check_status": "matched" if matched else "mismatched",
        "barcode_check_expected_type": expected_type,
        "barcode_check_values": scanned_values,
        "barcode_check_normalized_values": normalized_scanned_values,
        "barcode_check_expected_values": expected_values,
        "barcode_check_matched_value": matched,
        "barcode_checked_at": checked_at,
        "barcode_check_error": "",
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

    missing_fields = [
        barcode_type
        for barcode_type in GROUP_BARCODE_TYPES
        if barcode_type not in matched_fields and barcode_type not in missing_expected_fields
    ]
    if missing_expected_fields:
        status = "not_required"
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
    }


def summarize_group_barcode_accuracy(groups: Iterable[dict[str, Any]]) -> dict[str, Any]:
    passed = 0
    failed = 0
    unreadable = 0
    not_required = 0
    for group in groups:
        status = str(build_group_barcode_check(group).get("group_barcode_check_status") or "")
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


def list_group_barcode_review_items(
    groups: Iterable[dict[str, Any]],
    *,
    statuses: set[str] | None = None,
) -> list[dict[str, Any]]:
    target_statuses = statuses or {"unreadable", "mismatched"}
    items: list[dict[str, Any]] = []
    for group in groups:
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
    try:
        import zxingcpp  # type: ignore
    except Exception:
        return []

    image = _photo_image(photo)
    if image is None:
        return []
    try:
        return [normalize_barcode_value(item.text) for item in zxingcpp.read_barcodes(image) if item.text]
    except Exception:
        return []
    finally:
        try:
            image.close()
        except Exception:
            pass


def _scan_values(photo: dict[str, Any], *, scanner: BarcodeScanner | None) -> list[str]:
    scan = scanner or default_barcode_scanner
    try:
        values = scan(photo)
    except Exception:
        values = []
    cleaned = [str(item or "").strip() for item in values]
    return list(dict.fromkeys(item for item in cleaned if item))


def _photo_barcode_values(photo: dict[str, Any]) -> list[str]:
    raw_values = photo.get("barcode_check_normalized_values") or photo.get("barcode_check_values") or []
    if not isinstance(raw_values, list):
        raw_values = [raw_values]
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
        "barcode_check_values": list(photo.get("barcode_check_values") or []),
        "barcode_check_normalized_values": _photo_barcode_values(photo),
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
    try:
        with urllib.request.urlopen(image_url, timeout=8) as response:
            return response.read(8 * 1024 * 1024)
    except Exception:
        return None


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
            return value
    return ""
