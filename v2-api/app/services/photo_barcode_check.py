from __future__ import annotations

import re
import urllib.request
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

from app.services.matching import build_total_catalog_match_key
from app.services.photo_storage import parse_oss_image_url, sign_oss_server_url, static_upload_root, validate_image_content

BarcodeScanner = Callable[[dict[str, Any]], Iterable[str]]

BARCODE_REQUIRED_CATEGORY_TYPES = {
    "meter_barcode": "meter",
    "collector_barcode": "collector",
    "module_meter": "module",
    "module_barcode": "module",
}

REQUIRED_STATUSES = {"matched", "mismatched", "unreadable"}

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
