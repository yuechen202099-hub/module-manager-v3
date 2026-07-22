from __future__ import annotations

import hashlib
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.services.group_barcode_verification import (
    apply_group_scan_result,
    evaluate_group_eligibility,
    invalidate_group_verification,
    scan_group_evidence,
)
from app.api.routes.local_test import GroupBarcodeManualConfirmRequest


def _group() -> dict:
    photos = []
    for index, category in enumerate(("before_box", "collector_barcode", "module_meter", "after_box"), start=1):
        photos.append(
            {
                "id": f"photo-{index}",
                "category": category,
                "sha256": hashlib.sha256(str(index).encode()).hexdigest(),
                "archive_status": "archived",
                "is_active": True,
            }
        )
    return {
        "id": "group-1",
        "terminal": "TERM-001",
        "meter_no": "110000288056",
        "module_asset_no": "MOD-001",
        "collector": "COLLECTOR-001",
        "photos": photos,
    }


def test_scan_group_evidence_passes_distributed_machine_barcode_and_qr_values() -> None:
    group = _group()
    results = {
        "photo-1": {"barcode": ["noise-001"]},
        "photo-2": {"barcode": ["COLLECTOR-001"]},
        "photo-3": {"qr": ["MOD-001"]},
        "photo-4": {"barcode": ["110000288056"]},
    }

    result = scan_group_evidence(
        group,
        group["photos"],
        {"recognize": lambda photo: results[photo["id"]]},
    )

    assert result.status == "passed"
    assert result.passed_count == 3
    assert result.machine_barcode_values == ["NOISE001", "COLLECTOR001", "110000288056"]
    assert result.machine_qr_values == ["MOD001"]
    assert result.ocr_candidates == []
    assert result.unmatched_machine_values == ["NOISE001"]


def test_scan_group_evidence_never_passes_from_ocr_candidates_alone() -> None:
    group = _group()
    result = scan_group_evidence(
        group,
        group["photos"],
        {
            "recognize": lambda _photo: {
                "ocr": ["110000288056", "MOD-001", "COLLECTOR-001"]
            }
        },
    )

    assert result.status == "partial"
    assert result.passed_count == 0
    assert result.machine_barcode_values == []
    assert result.machine_qr_values == []
    assert result.ocr_candidates == ["110000288056", "MOD001", "COLLECTOR001"]


def test_scan_group_evidence_distinguishes_unreadable_mismatch_and_partial() -> None:
    group = _group()

    unreadable = scan_group_evidence(group, group["photos"], {"recognize": lambda _photo: {}})
    mismatch = scan_group_evidence(
        group, group["photos"], {"recognize": lambda _photo: {"barcode": ["WRONG-001"]}}
    )
    partial = scan_group_evidence(
        group,
        group["photos"],
        {"recognize": lambda photo: {"barcode": ["110000288056"]} if photo["id"] == "photo-1" else {}},
    )

    assert unreadable.status == "unreadable"
    assert mismatch.status == "mismatch"
    assert partial.status == "partial"


def test_apply_group_scan_result_rejects_stale_claim_and_requeues_current_evidence() -> None:
    group = _group()
    claimed_fingerprint = evaluate_group_eligibility(group).evidence_fingerprint
    assert claimed_fingerprint
    result = scan_group_evidence(group, group["photos"], {"recognize": lambda _photo: {}})
    group["photos"][0]["sha256"] = hashlib.sha256(b"changed").hexdigest()

    applied = apply_group_scan_result(
        {"status": "processing", "evidence_fingerprint": claimed_fingerprint, "evidence_version": 3},
        group,
        result,
        claimed_evidence_fingerprint=claimed_fingerprint,
        actor="barcode-worker",
    )

    assert applied["applied"] is False
    assert applied["verification"]["status"] == "pending"
    assert applied["verification"]["should_enqueue"] is True
    assert applied["verification"]["invalidation_reason"] == "evidence_fingerprint_changed"


def test_manual_confirmation_request_requires_formal_values_reason_and_photo_evidence() -> None:
    with pytest.raises(ValidationError):
        GroupBarcodeManualConfirmRequest.model_validate({"actor": "reviewer"})

    payload = GroupBarcodeManualConfirmRequest.model_validate(
        {
            "actor": "reviewer",
            "meter_no": "110000288056",
            "module_asset_no": "MOD-001",
            "collector": "COLLECTOR-001",
            "reason": "现场标签清晰，机器读取失败",
            "photo_ids": ["photo-1", "photo-2"],
        }
    )

    assert payload.reason == "现场标签清晰，机器读取失败"
    assert payload.photo_ids == ["photo-1", "photo-2"]


def eligible_group() -> dict:
    return {
        "terminal": "T-001",
        "meter_no": "M-001",
        "module_asset_no": "MOD-001",
        "collector": "COL-001",
        "photos": [
            {"id": "p-before", "sha256": "a" * 64, "category": "before_box"},
            {"id": "p-collector", "sha256": "b" * 64, "category": "collector_barcode"},
            {"id": "p-module-meter", "sha256": "c" * 64, "category": "module_meter"},
            {"id": "p-after", "sha256": "d" * 64, "category": "after_box"},
        ],
    }


def test_eligible_group_with_exactly_four_unique_categories_is_pending() -> None:
    result = evaluate_group_eligibility(eligible_group())
    assert result.status == "pending"
    assert result.reason is None
    assert result.evidence_fingerprint


@pytest.mark.parametrize(
    "mutate",
    [
        lambda group: group["photos"].pop(),
        lambda group: group["photos"].append({"id": "p-extra", "sha256": "e" * 64, "category": "extra"}),
        lambda group: group["photos"].__setitem__(3, {"id": "p-duplicate", "sha256": "e" * 64, "category": "before_box"}),
        lambda group: group.__setitem__("terminal", ""),
        lambda group: group.__setitem__("meter_no", "未关联终端"),
    ],
    ids=["too_few", "too_many", "duplicate_category", "missing_identity", "placeholder_identity"],
)
def test_ineligible_photo_or_identity_sets_are_not_eligible(mutate) -> None:
    group = eligible_group()
    mutate(group)
    assert evaluate_group_eligibility(group).status == "not_eligible"


@pytest.mark.parametrize("placeholder", ["00000000", "0000", "test", "TEST-001"])
def test_formal_identity_placeholders_are_not_eligible(placeholder: str) -> None:
    group = eligible_group()
    group["terminal"] = placeholder
    assert evaluate_group_eligibility(group).status == "not_eligible"


def test_real_identity_with_zeroes_is_eligible() -> None:
    group = eligible_group()
    group["terminal"] = "350000000001"
    group["meter_no"] = "120000912473"
    assert evaluate_group_eligibility(group).status == "pending"


def test_missing_required_photo_category_is_not_eligible() -> None:
    group = eligible_group()
    group["photos"][3]["category"] = "overview"
    result = evaluate_group_eligibility(group)
    assert result.status == "not_eligible"
    assert result.reason == "missing_required_photo_category"


def test_evidence_fingerprint_is_category_sorted_and_detects_photo_changes() -> None:
    group = eligible_group()
    reversed_group = deepcopy(group)
    reversed_group["photos"].reverse()
    changed_group = deepcopy(group)
    changed_group["photos"][0]["sha256"] = "f" * 64
    assert evaluate_group_eligibility(group).evidence_fingerprint == evaluate_group_eligibility(reversed_group).evidence_fingerprint
    assert evaluate_group_eligibility(group).evidence_fingerprint != evaluate_group_eligibility(changed_group).evidence_fingerprint


@pytest.mark.parametrize("sha256", ["g" * 64, "a" * 63, "a" * 65])
def test_photo_evidence_requires_a_64_character_hex_sha256(sha256: str) -> None:
    group = eligible_group()
    group["photos"][0]["sha256"] = sha256
    result = evaluate_group_eligibility(group)
    assert result.status == "not_eligible"
    assert result.reason == "invalid_photo_evidence"


def test_invalidation_with_new_evidence_resets_to_pending_and_records_actor() -> None:
    result = invalidate_group_verification(
        {"status": "passed", "evidence_fingerprint": "old-fingerprint", "evidence_version": 3, "attempt_count": 2},
        reason="photo_reclassified", actor="reviewer-a", evidence_fingerprint="new-fingerprint",
    )
    assert result["status"] == "pending"
    assert result["evidence_fingerprint"] == "new-fingerprint"
    assert result["evidence_version"] == 4
    assert result["attempt_count"] == 0
    assert result["invalidation_reason"] == "photo_reclassified"
    assert result["invalidated_by"] == "reviewer-a"
    assert result["should_enqueue"] is True


def test_invalidation_with_unchanged_pending_fingerprint_does_not_requeue() -> None:
    result = invalidate_group_verification(
        {"status": "pending", "evidence_fingerprint": "same-fingerprint", "evidence_version": 3, "attempt_count": 1},
        reason="duplicate_event", actor="reviewer-a", evidence_fingerprint="same-fingerprint",
    )
    assert result["status"] == "pending"
    assert result["evidence_version"] == 3
    assert result["attempt_count"] == 1
    assert result["should_enqueue"] is False


@pytest.mark.parametrize("status", ["processing", "partial", "mismatch", "unreadable", "failed", "passed", "manual_confirmed"])
def test_evidence_write_invalidates_every_non_target_status_with_an_unchanged_fingerprint(status: str) -> None:
    result = invalidate_group_verification(
        {"status": status, "evidence_fingerprint": "same-fingerprint", "evidence_version": 3, "attempt_count": 2, "lease_owner": "worker-a", "lease_expires_at": "2026-07-22T12:00:00+00:00"},
        reason="photo_replaced", actor="reviewer-a", evidence_fingerprint="same-fingerprint", next_status="pending",
    )
    assert result["status"] == "pending"
    assert result["evidence_version"] == 4
    assert result["attempt_count"] == 0
    assert result["lease_owner"] is None
    assert result["lease_expires_at"] is None
    assert result["should_enqueue"] is True


def test_active_invalid_upload_photos_are_not_eligible_evidence() -> None:
    group = eligible_group()
    for photo in group["photos"]:
        photo["upload_status"] = "invalid"
    result = evaluate_group_eligibility(group)
    assert result.status == "not_eligible"
    assert result.reason == "invalid_photo_evidence"


@pytest.mark.parametrize(
    "historical_photo",
    [
        {"id": "p-inactive", "sha256": "e" * 64, "category": "other", "is_active": False},
        {"id": "p-invalid", "sha256": "e" * 64, "category": "other", "upload_status": "invalid"},
    ],
    ids=["inactive", "invalid"],
)
def test_inactive_or_invalid_historical_photos_do_not_count_against_four_valid_evidence(historical_photo: dict) -> None:
    group = eligible_group()
    group["photos"].append(historical_photo)
    result = evaluate_group_eligibility(group)
    assert result.status == "pending"
    assert result.evidence_fingerprint


def test_invalidation_without_fingerprint_clears_passed_state_and_versions_evidence() -> None:
    result = invalidate_group_verification(
        {"status": "passed", "evidence_fingerprint": "old-fingerprint", "evidence_version": 3, "attempt_count": 2},
        reason="photo_changed", actor="reviewer-a",
    )
    assert result["status"] == "pending"
    assert result["evidence_fingerprint"] is None
    assert result["evidence_version"] == 4
    assert result["should_enqueue"] is True


@pytest.mark.parametrize(
    "reason,mutate",
    [
        ("photo_deleted", lambda group: group["photos"].pop()),
        ("photo_reclassified", lambda group: group["photos"].__setitem__(3, {"id": "p-overview", "sha256": "d" * 64, "category": "overview"})),
        ("identity_deleted", lambda group: group.__setitem__("collector", "")),
    ],
    ids=["photo_deleted", "photo_reclassified", "identity_deleted"],
)
def test_invalidation_can_mark_evidence_as_ineligible(reason, mutate) -> None:
    group = eligible_group()
    mutate(group)
    evaluation = evaluate_group_eligibility(group)
    result = invalidate_group_verification(
        {"status": "passed", "evidence_fingerprint": "old", "evidence_version": 3},
        reason=reason, actor="reviewer-a", evidence_fingerprint=evaluation.evidence_fingerprint, next_status=evaluation.status,
    )
    assert evaluation.status == "not_eligible"
    assert result["status"] == "not_eligible"
    assert result["evidence_fingerprint"] is None
    assert result["evidence_version"] == 4
    assert result["should_enqueue"] is False


@pytest.mark.parametrize("next_status", ["passed", "manual_confirmed"])
def test_invalidation_rejects_completed_status_for_changed_evidence(next_status: str) -> None:
    with pytest.raises(ValueError, match="pending or not_eligible"):
        invalidate_group_verification(
            {"status": "passed", "evidence_fingerprint": "old", "evidence_version": 3},
            reason="photo_changed", actor="reviewer-a", evidence_fingerprint="new", next_status=next_status,
        )


@pytest.mark.parametrize("next_status", ["passed", "manual_confirmed"])
def test_invalidation_rejects_completed_status_before_same_fingerprint_idempotency(next_status: str) -> None:
    with pytest.raises(ValueError, match="pending or not_eligible"):
        invalidate_group_verification(
            {"status": "passed", "evidence_fingerprint": "same", "evidence_version": 3},
            reason="duplicate_event", actor="reviewer-a", evidence_fingerprint="same", next_status=next_status,
        )


@pytest.mark.parametrize(("next_status", "should_enqueue"), [("pending", True), ("not_eligible", False)])
def test_invalidation_accepts_only_pending_or_not_eligible(next_status: str, should_enqueue: bool) -> None:
    result = invalidate_group_verification(
        {"status": "passed", "evidence_fingerprint": "old", "evidence_version": 3},
        reason="photo_changed", actor="reviewer-a", evidence_fingerprint="new", next_status=next_status,
    )
    assert result["status"] == next_status
    assert result["should_enqueue"] is should_enqueue
