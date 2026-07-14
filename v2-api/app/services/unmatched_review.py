import copy
import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from app.services.matching import build_total_catalog_match_key


REVIEW_SCHEMA_VERSION = 1
REVIEW_METADATA_FIELDS = {"meter_no", "collector", "module_asset_no"}
PHOTO_UPDATE_FIELDS = {"category"}
REVIEW_STATES = {"pending", "reviewed"}
INVALID_TERMINALS = {"", "00000000"}
PHOTO_EVIDENCE_FIELDS = (
    "barcode_check_status",
    "barcode_check_expected_type",
    "barcode_check_values",
    "barcode_check_normalized_values",
    "barcode_check_ocr_values",
    "barcode_check_ocr_normalized_values",
    "barcode_check_expected_values",
    "barcode_check_matched_value",
    "barcode_checked_at",
    "barcode_check_method",
    "barcode_check_error",
    "barcode_rescanned_by",
    "barcode_rescanned_at",
    "qr_values",
    "qr_normalized_values",
    "ocr_values",
    "ocr_normalized_values",
)
CONFIRMATION_PHOTO_EVIDENCE_FIELDS = (
    "category",
    *(
        field
        for field in PHOTO_EVIDENCE_FIELDS
        if field not in {"barcode_checked_at", "barcode_rescanned_by", "barcode_rescanned_at"}
    ),
)


class ReviewVersionConflict(ValueError):
    pass


class FinalizationIdentityConflict(ValueError):
    pass


AUDIT_REDACTED_VALUE = "[REDACTED]"
AUDIT_PHOTO_SECRET_FIELDS = {
    "bucket",
    "image_url",
    "image_urls",
    "object_key",
    "original_url",
    "oss_key",
    "photo_url",
    "photo_urls",
    "raw_url",
    "signed_url",
    "source_url",
    "storage_bucket",
    "storage_key",
    "url",
    "urls",
}
AUDIT_PHOTO_SECRET_KEYS = {
    re.sub(r"[^0-9a-z]+", "", field.casefold()) for field in AUDIT_PHOTO_SECRET_FIELDS
}
AUDIT_SECRET_LOCATOR_TOKENS = {
    "bucket",
    "buckets",
    "href",
    "key",
    "keys",
    "link",
    "links",
    "name",
    "names",
    "path",
    "paths",
    "uri",
    "uris",
    "url",
    "urls",
}
AUDIT_SECRET_QUALIFIER_TOKENS = {
    "blob",
    "cos",
    "image",
    "minio",
    "object",
    "oss",
    "photo",
    "presigned",
    "raw",
    "s3",
    "signed",
    "source",
    "storage",
}


def audit_key_semantic_tokens(key: Any) -> set[str]:
    value = str(key).strip()
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return set(re.findall(r"[0-9a-z]+", value.casefold()))


def audit_key_contains_photo_secret(key: Any) -> bool:
    normalized_key = re.sub(r"[^0-9a-z]+", "", str(key).strip().casefold())
    if normalized_key in AUDIT_PHOTO_SECRET_KEYS:
        return True
    tokens = audit_key_semantic_tokens(key)
    if tokens & {"bucket", "buckets"}:
        return True
    return bool(tokens & AUDIT_SECRET_LOCATOR_TOKENS) and bool(
        tokens & AUDIT_SECRET_QUALIFIER_TOKENS
    )


def redact_audit_photo_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            redacted[key] = (
                AUDIT_REDACTED_VALUE
                if audit_key_contains_photo_secret(key)
                else redact_audit_photo_secrets(item)
            )
        return redacted
    if isinstance(value, list):
        return [redact_audit_photo_secrets(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_audit_photo_secrets(item) for item in value)
    return copy.deepcopy(value)


def review_meter_match_key(record: dict[str, Any], review: dict[str, Any]) -> str:
    meter_no = str(review.get("meter_no") or record.get("meter_no") or "").strip()
    if not meter_no:
        return ""
    try:
        return build_total_catalog_match_key(meter_no)
    except ValueError:
        return ""


def build_match_candidates(
    record: dict[str, Any],
    review: dict[str, Any],
    catalog_rows: list[dict[str, Any]],
    groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    meter_key = review_meter_match_key(record, review)
    if not meter_key:
        return []

    sorted_groups = sorted(groups, key=lambda item: str(item.get("id") or item.get("legacy_id") or ""))

    candidates: dict[str, dict[str, Any]] = {}
    for row in catalog_rows:
        row_meter = str(row.get("meter_no") or row.get("meter_match_key") or "").strip()
        try:
            row_key = build_total_catalog_match_key(row_meter)
        except ValueError:
            continue
        if row_key != meter_key:
            continue
        terminal = str(row.get("terminal") or "").strip()
        if terminal in INVALID_TERMINALS:
            continue
        catalog_id = str(row.get("id") or row.get("legacy_id") or meter_key)
        catalog_db_id = str(row.get("catalog_row_db_id") or catalog_id)
        target_group = next(
            (
                group
                for group in sorted_groups
                if str(group.get("terminal") or "").strip() == terminal
                and (
                    str(group.get("total_catalog_row_id") or group.get("catalog_row_id") or "").strip()
                    in {catalog_id, catalog_db_id}
                    or (
                        not str(group.get("total_catalog_row_id") or group.get("catalog_row_id") or "").strip()
                        and str(group.get("meter_match_key") or "").strip() == meter_key
                    )
                )
            ),
            {},
        )
        candidate_key = f"catalog:{catalog_id}:{terminal}"
        reasons = ["表号精确匹配"]
        review_collector = str(review.get("collector") or "").strip()
        if review_collector and review_collector == str(row.get("collector") or "").strip():
            reasons.append("采集器号一致")
        review_module = str(review.get("module_asset_no") or "").strip()
        row_modules = {
            str(row.get("module_asset_no") or "").strip(),
            str(row.get("asset_no") or "").strip(),
        }
        if review_module and review_module in row_modules:
            reasons.append("模块号一致")
        candidates[candidate_key] = {
            "candidate_key": candidate_key,
            "catalog_row_id": catalog_id,
            "catalog_row_db_id": catalog_db_id,
            "target_group_id": str(target_group.get("id") or target_group.get("legacy_id") or ""),
            "terminal": terminal,
            "meter_no": str(row.get("meter_no") or review.get("meter_no") or ""),
            "meter_match_key": meter_key,
            "address": str(row.get("address") or row.get("installation_address") or ""),
            "match_reasons": reasons,
        }
    return sorted(
        candidates.values(),
        key=lambda item: (-len(item["match_reasons"]), item["terminal"], item["candidate_key"]),
    )


def require_version(review: dict[str, Any], expected_version: int) -> None:
    if int(review.get("version") or 0) != expected_version:
        raise ReviewVersionConflict("Unmatched review was updated by another user")


def migrate_review_to_photo_rows(review: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for photo in review.get("photos") or []:
        source_url = str(photo.get("source_url") or "")
        row = {
            "id": migrated_formal_photo_id(
                str(review.get("unmatched_id") or ""),
                str(photo.get("id") or ""),
            ),
            "url": source_url,
            "image_url": source_url,
            "source_url": source_url,
            "source_fingerprint": str(photo.get("id") or ""),
            "category": photo.get("category") or "unclassified",
            "temporary_review_manual_confirmed": bool(review.get("manual_confirmed")),
            "temporary_review_reviewer": review.get("reviewer") or "",
            "temporary_review_reviewed_at": review.get("reviewed_at") or "",
        }
        for key in PHOTO_EVIDENCE_FIELDS:
            if key in photo:
                row[key] = copy.deepcopy(photo[key])
        rows.append(row)
    return rows


def merge_migrated_photo_evidence(target: dict[str, Any], migrated: dict[str, Any]) -> None:
    for key in (
        "category",
        "source_url",
        "source_fingerprint",
        *PHOTO_EVIDENCE_FIELDS,
        "temporary_review_manual_confirmed",
        "temporary_review_reviewer",
        "temporary_review_reviewed_at",
    ):
        if key in migrated:
            target[key] = copy.deepcopy(migrated[key])


def normalized_photo_urls(record: dict[str, Any]) -> list[str]:
    values = record.get("photo_urls") or record.get("image_urls") or []
    if isinstance(values, str):
        values = re.split(r"[\r\n,]+", values)
    return [str(value).strip() for value in values if str(value).strip()]


def validate_category(category: str) -> None:
    if category not in {"unclassified", "before_box", "collector_barcode", "module_meter", "after_box"}:
        raise ValueError(f"Unsupported photo category: {category}")


def validate_state(state: str) -> None:
    if state not in REVIEW_STATES:
        raise ValueError(f"Unsupported review state: {state}")


def stable_photo_id(unmatched_id: str, index: int, source_url: str) -> str:
    digest = hashlib.sha256(f"{unmatched_id}|{index}|{source_url}".encode("utf-8")).hexdigest()[:16]
    return f"unmatched-photo-{digest}"


def migrated_formal_photo_id(unmatched_id: str, review_photo_id: str) -> str:
    review_photo_hash = hashlib.sha256(review_photo_id.encode("utf-8")).hexdigest()[:16]
    return f"p-unmatched-{unmatched_id}-{review_photo_hash}"


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
        "unmatched_id": str(record.get("unmatched_id") or ""),
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


def advance_record_version(record: dict[str, Any], expected_version: int) -> int:
    review = build_review(record)
    require_version(review, expected_version)
    review["version"] = expected_version + 1
    review["updated_at"] = datetime.now(UTC).isoformat()
    record["temporary_review"] = review
    record["review_version"] = review["version"]
    return review["version"]


def find_review_photo(review: dict[str, Any], photo_id: str) -> dict[str, Any]:
    photo = next((item for item in review.get("photos") or [] if item.get("id") == photo_id), None)
    if photo is None:
        raise KeyError(photo_id)
    return photo


def barcode_context(review: dict[str, Any]) -> dict[str, Any]:
    meter_no = str(review.get("meter_no") or "")
    try:
        meter_match_key = build_total_catalog_match_key(meter_no)
    except ValueError:
        meter_match_key = ""
    return {
        "meter_no": meter_no,
        "meter_match_key": meter_match_key,
        "collector": str(review.get("collector") or ""),
        "module_asset_no": str(review.get("module_asset_no") or ""),
        "photos": review.get("photos") or [],
    }


def confirmation_evidence(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "metadata": {
            key: str(review.get(key) or "").strip()
            for key in REVIEW_METADATA_FIELDS
        },
        "photos": [
            {
                "id": str(photo.get("id") or ""),
                **{
                    key: copy.deepcopy(photo.get(key))
                    for key in CONFIRMATION_PHOTO_EVIDENCE_FIELDS
                    if key in photo
                },
            }
            for photo in review.get("photos") or []
        ],
    }


def invalidate_manual_confirmation_if_evidence_changed(
    before: dict[str, Any],
    after: dict[str, Any],
) -> bool:
    if confirmation_evidence(before) == confirmation_evidence(after):
        return False
    after["manual_confirmed"] = False
    after["reviewed_at"] = ""
    return True


def manual_confirmation_state(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "manual_confirmed": bool(review.get("manual_confirmed")),
        "reviewed_at": str(review.get("reviewed_at") or ""),
    }


def apply_review_patch(
    review: dict[str, Any],
    *,
    actor: str,
    expected_version: int,
    metadata: dict[str, Any],
    photo_updates: list[dict[str, Any]],
    state: str,
) -> dict[str, Any]:
    validate_state(state)
    if int(review.get("version") or 0) != expected_version:
        raise ReviewVersionConflict("Unmatched review was updated by another user")
    updated = copy.deepcopy(review)
    for key in REVIEW_METADATA_FIELDS:
        if key in metadata:
            updated[key] = str(metadata.get(key) or "").strip()
    for patch in photo_updates:
        photo = find_review_photo(updated, str(patch.get("id") or ""))
        for key in PHOTO_UPDATE_FIELDS:
            if key not in patch:
                continue
            if key == "category":
                validate_category(str(patch[key] or ""))
            photo[key] = str(patch[key])
    invalidate_manual_confirmation_if_evidence_changed(review, updated)
    updated["state"] = state
    updated["reviewer"] = actor
    updated["updated_at"] = datetime.now(UTC).isoformat()
    updated["version"] = expected_version + 1
    updated["audit_event"] = audit_diff(
        str(updated.get("unmatched_id") or ""),
        review,
        updated,
        actor=actor,
        timestamp=updated["updated_at"],
    )
    return updated


def audit_diff(
    unmatched_id: str,
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    actor: str = "",
    action: str = "update_unmatched_review",
    timestamp: str | None = None,
) -> dict[str, Any]:
    before_payload = copy.deepcopy(before)
    after_payload = copy.deepcopy(after)
    before_payload.pop("audit_event", None)
    after_payload.pop("audit_event", None)
    return {
        "actor": actor,
        "action": action,
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
        "unmatched_id": unmatched_id,
        "before_version": before.get("version"),
        "after_version": after.get("version"),
        "before": before_payload,
        "after": after_payload,
    }
