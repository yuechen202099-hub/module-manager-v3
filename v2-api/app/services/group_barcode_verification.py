from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal, Mapping


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

REQUIRED_CATEGORIES = frozenset(
    {"meter_barcode", "collector_barcode", "module_meter", "module_barcode"}
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


def evaluate_group_eligibility(group: Any) -> EligibilityResult:
    identity = {field: _group_value(group, field) for field in IDENTITY_FIELDS}
    if any(_is_missing_identity(value) for value in identity.values()):
        return EligibilityResult(status="not_eligible", reason="missing_identity")

    photos = _group_value(group, "photos") or []
    if not isinstance(photos, list) or len(photos) != len(REQUIRED_CATEGORIES):
        return EligibilityResult(status="not_eligible", reason="invalid_photo_count")

    evidence = [_photo_evidence(photo) for photo in photos]
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
) -> dict[str, Any]:
    result = dict(verification)
    current_fingerprint = str(result.get("evidence_fingerprint") or "")
    next_fingerprint = str(evidence_fingerprint or current_fingerprint)

    if next_fingerprint == current_fingerprint:
        result["should_enqueue"] = False
        return result

    result.update(
        {
            "status": "pending",
            "evidence_fingerprint": next_fingerprint,
            "evidence_version": int(result.get("evidence_version") or 0) + 1,
            "attempt_count": 0,
            "lease_owner": None,
            "lease_expires_at": None,
            "invalidation_reason": reason,
            "invalidated_by": actor,
            "should_enqueue": True,
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
    normalized = str(value or "").strip().lower()
    return not normalized or normalized in PLACEHOLDER_VALUES


def _photo_evidence(photo: Any) -> dict[str, str] | None:
    if not isinstance(photo, Mapping):
        return None
    photo_id = str(photo.get("id") or "").strip()
    sha256 = str(photo.get("sha256") or "").strip().lower()
    category = str(photo.get("category") or "").strip()
    if not photo_id or len(sha256) != 64 or not category:
        return None
    return {"id": photo_id, "sha256": sha256, "category": category}
