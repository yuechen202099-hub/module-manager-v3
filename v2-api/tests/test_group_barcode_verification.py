from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.group_barcode_verification import (
    evaluate_group_eligibility,
    invalidate_group_verification,
)


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
        lambda group: group["photos"].append(
            {"id": "p-extra", "sha256": "e" * 64, "category": "extra"}
        ),
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

    assert evaluate_group_eligibility(group).evidence_fingerprint == evaluate_group_eligibility(
        reversed_group
    ).evidence_fingerprint
    assert evaluate_group_eligibility(group).evidence_fingerprint != evaluate_group_eligibility(
        changed_group
    ).evidence_fingerprint


@pytest.mark.parametrize("sha256", ["g" * 64, "a" * 63, "a" * 65])
def test_photo_evidence_requires_a_64_character_hex_sha256(sha256: str) -> None:
    group = eligible_group()
    group["photos"][0]["sha256"] = sha256

    result = evaluate_group_eligibility(group)

    assert result.status == "not_eligible"
    assert result.reason == "invalid_photo_evidence"


def test_invalidation_with_new_evidence_resets_to_pending_and_records_actor() -> None:
    verification = {
        "status": "passed",
        "evidence_fingerprint": "old-fingerprint",
        "evidence_version": 3,
        "attempt_count": 2,
    }

    result = invalidate_group_verification(
        verification,
        reason="photo_reclassified",
        actor="reviewer-a",
        evidence_fingerprint="new-fingerprint",
    )

    assert result["status"] == "pending"
    assert result["evidence_fingerprint"] == "new-fingerprint"
    assert result["evidence_version"] == 4
    assert result["attempt_count"] == 0
    assert result["invalidation_reason"] == "photo_reclassified"
    assert result["invalidated_by"] == "reviewer-a"
    assert result["should_enqueue"] is True


def test_invalidation_with_unchanged_pending_fingerprint_does_not_requeue() -> None:
    verification = {
        "status": "pending",
        "evidence_fingerprint": "same-fingerprint",
        "evidence_version": 3,
        "attempt_count": 1,
    }

    result = invalidate_group_verification(
        verification,
        reason="duplicate_event",
        actor="reviewer-a",
        evidence_fingerprint="same-fingerprint",
    )

    assert result["status"] == "pending"
    assert result["evidence_version"] == 3
    assert result["attempt_count"] == 1
    assert result["should_enqueue"] is False


def test_invalidation_without_fingerprint_clears_passed_state_and_versions_evidence() -> None:
    verification = {
        "status": "passed",
        "evidence_fingerprint": "old-fingerprint",
        "evidence_version": 3,
        "attempt_count": 2,
    }

    result = invalidate_group_verification(
        verification,
        reason="photo_changed",
        actor="reviewer-a",
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
        reason=reason,
        actor="reviewer-a",
        evidence_fingerprint=evaluation.evidence_fingerprint,
        next_status=evaluation.status,
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
            reason="photo_changed",
            actor="reviewer-a",
            evidence_fingerprint="new",
            next_status=next_status,
        )


@pytest.mark.parametrize("next_status", ["passed", "manual_confirmed"])
def test_invalidation_rejects_completed_status_before_same_fingerprint_idempotency(
    next_status: str,
) -> None:
    with pytest.raises(ValueError, match="pending or not_eligible"):
        invalidate_group_verification(
            {"status": "passed", "evidence_fingerprint": "same", "evidence_version": 3},
            reason="duplicate_event",
            actor="reviewer-a",
            evidence_fingerprint="same",
            next_status=next_status,
        )


@pytest.mark.parametrize(
    ("next_status", "should_enqueue"),
    [("pending", True), ("not_eligible", False)],
)
def test_invalidation_accepts_only_pending_or_not_eligible(next_status: str, should_enqueue: bool) -> None:
    result = invalidate_group_verification(
        {"status": "passed", "evidence_fingerprint": "old", "evidence_version": 3},
        reason="photo_changed",
        actor="reviewer-a",
        evidence_fingerprint="new",
        next_status=next_status,
    )

    assert result["status"] == next_status
    assert result["should_enqueue"] is should_enqueue
