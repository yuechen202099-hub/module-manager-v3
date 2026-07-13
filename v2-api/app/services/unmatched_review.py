import copy
import hashlib
import re
from datetime import UTC, datetime
from typing import Any


REVIEW_SCHEMA_VERSION = 1
REVIEW_METADATA_FIELDS = {"meter_no", "collector", "module_asset_no"}
PHOTO_UPDATE_FIELDS = {"category"}


class ReviewVersionConflict(ValueError):
    pass


def normalized_photo_urls(record: dict[str, Any]) -> list[str]:
    values = record.get("photo_urls") or record.get("image_urls") or []
    if isinstance(values, str):
        values = re.split(r"[\r\n,]+", values)
    return [str(value).strip() for value in values if str(value).strip()]


def validate_category(category: str) -> None:
    if category not in {"unclassified", "before_box", "collector_barcode", "module_meter", "after_box"}:
        raise ValueError(f"Unsupported photo category: {category}")


def stable_photo_id(unmatched_id: str, index: int, source_url: str) -> str:
    digest = hashlib.sha256(f"{unmatched_id}|{index}|{source_url}".encode("utf-8")).hexdigest()[:16]
    return f"unmatched-photo-{digest}"


def build_review(record: dict[str, Any]) -> dict[str, Any]:
    existing = dict(record.get("temporary_review") or {})
    urls = normalized_photo_urls(record)
    photos_by_id = {str(item.get("id")): dict(item) for item in existing.get("photos") or []}
    photos = []
    for index, url in enumerate(urls):
        photo_id = stable_photo_id(str(record.get("unmatched_id") or ""), index, url)
        photos.append({
            "id": photo_id,
            "source_url": url,
            "category": "unclassified",
            "barcode_check_status": "not_checked",
            **photos_by_id.get(photo_id, {}),
        })
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "version": max(1, int(existing.get("version") or 1)),
        "state": str(existing.get("state") or "pending"),
        "meter_no": str(existing.get("meter_no") or record.get("meter_no") or record.get("barcode") or ""),
        "collector": str(existing.get("collector") or record.get("collector") or ""),
        "module_asset_no": str(existing.get("module_asset_no") or record.get("module_asset_no") or ""),
        "manual_confirmed": bool(existing.get("manual_confirmed")),
        "reviewer": str(existing.get("reviewer") or ""),
        "reviewed_at": str(existing.get("reviewed_at") or ""),
        "updated_at": str(existing.get("updated_at") or ""),
        "photos": photos,
    }


def find_review_photo(review: dict[str, Any], photo_id: str) -> dict[str, Any]:
    photo = next((item for item in review.get("photos") or [] if item.get("id") == photo_id), None)
    if photo is None:
        raise KeyError(photo_id)
    return photo


def apply_review_patch(
    review: dict[str, Any],
    *,
    actor: str,
    expected_version: int,
    metadata: dict[str, Any],
    photo_updates: list[dict[str, Any]],
    state: str,
) -> dict[str, Any]:
    if int(review.get("version") or 0) != expected_version:
        raise ReviewVersionConflict("Unmatched review was updated by another user")
    updated = copy.deepcopy(review)
    for key in REVIEW_METADATA_FIELDS:
        if key in metadata:
            updated[key] = str(metadata.get(key) or "").strip()
    for patch in photo_updates:
        photo = find_review_photo(updated, str(patch.get("id") or ""))
        if "category" in patch:
            validate_category(str(patch.get("category") or ""))
            photo["category"] = str(patch["category"])
    updated["state"] = state if state in {"pending", "reviewed"} else "pending"
    updated["reviewer"] = actor
    updated["updated_at"] = datetime.now(UTC).isoformat()
    updated["version"] = expected_version + 1
    return updated


def audit_diff(unmatched_id: str, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        "unmatched_id": unmatched_id,
        "before_version": before.get("version"),
        "after_version": after.get("version"),
        "before": before,
        "after": after,
    }
