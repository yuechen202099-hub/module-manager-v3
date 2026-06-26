from __future__ import annotations

import re
import tempfile
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

from app.services.matching import build_total_catalog_match_key

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

    path = _photo_local_path(photo)
    cleanup = False
    if path is None:
        path = _download_photo_to_temp(photo)
        cleanup = path is not None
    if path is None:
        return []
    try:
        return [normalize_barcode_value(item.text) for item in zxingcpp.read_barcodes(str(path)) if item.text]
    except Exception:
        return []
    finally:
        if cleanup:
            try:
                path.unlink(missing_ok=True)
            except OSError:
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
    for key in ("local_path", "path", "file_path", "object_key"):
        value = str(photo.get(key) or "").strip()
        if not value:
            continue
        path = Path(value)
        if path.exists():
            return path
    image_url = str(photo.get("image_url") or photo.get("url") or "").strip()
    parsed = urlparse(image_url)
    if parsed.scheme in {"", "file"}:
        path = Path(parsed.path or image_url)
        if path.exists():
            return path
    return None


def _download_photo_to_temp(photo: dict[str, Any]) -> Path | None:
    image_url = str(photo.get("preview_url") or photo.get("image_url") or photo.get("url") or "").strip()
    if not image_url.lower().startswith(("http://", "https://")):
        return None
    try:
        with urllib.request.urlopen(image_url, timeout=8) as response:
            content = response.read(8 * 1024 * 1024)
    except Exception:
        return None
    suffix = Path(urlparse(image_url).path).suffix or ".jpg"
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    with handle:
        handle.write(content)
    return Path(handle.name)
