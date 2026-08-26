from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from app.domain.terminal_review import (
    ReviewMeterEvidence,
    ReviewPhotoEvidence,
    TerminalReviewProjection,
    derive_terminal_workflow_state,
    project_terminal_review,
)


def photo(photo_id: str, category: str, sha_byte: str) -> ReviewPhotoEvidence:
    return ReviewPhotoEvidence(
        id=photo_id,
        category=category,
        sha256=sha_byte * 64,
    )


def review_meter(
    group_id: str,
    *,
    status: str = "approved",
    terminal_code: str = "T-001",
    installation_address: str = "聚丰园路95弄21号",
    meter_no: str | None = None,
    collector_no: str = "C-001",
    module_no: str = "A-001",
    persisted_photo_count: int | None = None,
    active_photos: tuple[ReviewPhotoEvidence, ...] | None = None,
    barcode_status: str = "passed",
    identity_blockers: tuple[str, ...] = (),
    source_blockers: tuple[str, ...] = (),
) -> ReviewMeterEvidence:
    resolved_photos = active_photos
    if resolved_photos is None:
        resolved_photos = (
            photo(f"{group_id}-module-meter", "module_meter", "1"),
            photo(f"{group_id}-after-box", "after_box", "2"),
        )
    return ReviewMeterEvidence(
        group_id=group_id,
        status=status,
        terminal_code=terminal_code,
        installation_address=installation_address,
        meter_no=meter_no or f"M-{group_id}",
        collector_no=collector_no,
        module_no=module_no,
        persisted_photo_count=(len(resolved_photos) if persisted_photo_count is None else persisted_photo_count),
        active_photos=resolved_photos,
        barcode_status=barcode_status,
        identity_blockers=identity_blockers,
        source_blockers=source_blockers,
    )


def test_mixed_terminal_partitions_unconstructed_and_locks_on_constructed_review() -> None:
    """Catches zero-photo rows blocking or entering the terminal re-photo snapshot."""
    projection = project_terminal_review(
        (
            review_meter("g-1", status="approved", barcode_status="passed"),
            review_meter("g-2", status="unreviewed", barcode_status="passed"),
            review_meter(
                "g-3",
                status="unreviewed",
                persisted_photo_count=0,
                active_photos=(),
            ),
        )
    )

    assert [item.group_id for item in projection.constructed_meters] == ["g-1", "g-2"]
    assert [item.group_id for item in projection.unconstructed_meters] == ["g-3"]
    assert projection.review_ready_count == 1
    assert projection.review_required_count == 1
    assert [item.group_id for item in projection.rephoto_sources] == ["g-1"]
    assert projection.source_revision != project_terminal_review(
        (review_meter("g-1", status="approved", barcode_status="passed"),)
    ).source_revision


def test_persisted_construction_without_active_photos_requires_both_slots() -> None:
    """Catches treating a positive historical photo count as current re-photo evidence."""
    projection = project_terminal_review(
        (
            review_meter(
                "g-1",
                persisted_photo_count=4,
                active_photos=(),
            ),
        )
    )

    meter = projection.constructed_meters[0]
    assert meter.construction_state == "constructed"
    assert "module_meter_photo_missing" in meter.blockers
    assert "after_box_photo_missing" in meter.blockers
    assert meter.review_ready is False
    assert meter.source is not None
    assert meter.source.module_meter_photo_id is None
    assert meter.source.after_box_photo_id is None


def test_exactly_one_photo_per_required_slot_has_no_photo_blocker() -> None:
    """Catches rejecting the confirmed two-slot new-install evidence contract."""
    projection = project_terminal_review((review_meter("g-1"),))

    assert projection.constructed_meters[0].blockers == ()
    assert projection.constructed_meters[0].review_ready is True


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("module_meter", "module_meter_photo_conflict"),
        ("after_box", "after_box_photo_conflict"),
    ],
)
def test_duplicate_required_slot_is_a_hard_blocker(category: str, expected: str) -> None:
    """Catches silently selecting one of two conflicting active slot photos."""
    other_category = "after_box" if category == "module_meter" else "module_meter"
    projection = project_terminal_review(
        (
            review_meter(
                "g-1",
                active_photos=(
                    photo("duplicate-1", category, "1"),
                    photo("duplicate-2", category, "2"),
                    photo("other", other_category, "3"),
                ),
            ),
        )
    )

    assert expected in projection.constructed_meters[0].blockers
    assert projection.hard_blocked is True


def test_identity_blockers_and_blank_module_prevent_review_ready() -> None:
    """Catches approving placeholder identity or a meter without its module barcode."""
    placeholder = project_terminal_review(
        (review_meter("g-placeholder", identity_blockers=("meter_missing",)),)
    )
    blank_module = project_terminal_review((review_meter("g-module", module_no=""),))

    assert "meter_missing" in placeholder.constructed_meters[0].blockers
    assert "module_missing" in blank_module.constructed_meters[0].blockers
    assert placeholder.hard_blocked is True
    assert blank_module.hard_blocked is True


@pytest.mark.parametrize("status", ["passed", "manual_confirmed", "manual"])
def test_current_persisted_barcode_statuses_unlock_review(status: str) -> None:
    """Catches rejecting one of the three persisted verification success states."""
    projection = project_terminal_review((review_meter("g-1", barcode_status=status),))

    assert "barcode_verification_required" not in projection.constructed_meters[0].blockers
    assert projection.constructed_meters[0].review_ready is True


@pytest.mark.parametrize("status", ["", "pending", "failed", "expired"])
def test_non_success_barcode_status_requires_verification(status: str) -> None:
    """Catches accepting stale or failed barcode evidence as current verification."""
    projection = project_terminal_review((review_meter("g-1", barcode_status=status),))

    assert "barcode_verification_required" in projection.constructed_meters[0].blockers
    assert projection.constructed_meters[0].review_ready is False


@pytest.mark.parametrize("blocker", ["exception_open", "address_conflict", "source_conflict"])
def test_active_exception_address_and_source_conflicts_are_hard_blockers(blocker: str) -> None:
    """Catches allowing a known source conflict through the terminal lock."""
    projection = project_terminal_review((review_meter("g-1", source_blockers=(blocker,)),))

    assert blocker in projection.constructed_meters[0].blockers
    assert projection.hard_blocked is True


def test_source_revision_ignores_every_unconstructed_field() -> None:
    """Catches superseding a valid terminal snapshot when an unconstructed row changes."""
    first = project_terminal_review(
        (
            review_meter("g-1"),
            review_meter(
                "g-unbuilt",
                status="unreviewed",
                meter_no="M-OLD",
                collector_no="C-OLD",
                module_no="A-OLD",
                persisted_photo_count=0,
                active_photos=(),
            ),
        )
    )
    changed = project_terminal_review(
        (
            review_meter("g-1"),
            review_meter(
                "g-unbuilt",
                status="exception",
                terminal_code="T-CHANGED",
                installation_address="另一个地址",
                meter_no="M-NEW",
                collector_no="C-NEW",
                module_no="A-NEW",
                persisted_photo_count=0,
                active_photos=(),
                barcode_status="failed",
                identity_blockers=("meter_missing",),
                source_blockers=("source_conflict",),
            ),
        )
    )

    assert first.source_revision == changed.source_revision


def test_shared_collector_is_one_requirement_with_all_constructed_meter_groups() -> None:
    """Catches producing duplicate removal requirements for one physical collector."""
    projection = project_terminal_review(
        (
            review_meter("g-1", collector_no="C-SHARED"),
            review_meter("g-2", collector_no="C-SHARED"),
            review_meter(
                "g-unbuilt",
                collector_no="C-SHARED",
                persisted_photo_count=0,
                active_photos=(),
            ),
        )
    )

    assert len(projection.collector_requirements) == 1
    assert projection.collector_requirements[0].original_collector_no == "C-SHARED"
    assert projection.collector_requirements[0].meter_group_ids == ("g-1", "g-2")


@pytest.mark.parametrize(
    ("constructed", "required", "hard_blocked", "missing", "available", "snapshot", "expected"),
    [
        (0, 0, False, 0, 0, None, "no_construction"),
        (2, 0, True, 0, 0, None, "blocked"),
        (2, 1, False, 0, 0, None, "needs_review"),
        (2, 0, False, 2, 1, None, "pool_shortage"),
        (2, 0, False, 1, 2, None, "needs_replacement"),
        (2, 0, False, 0, 2, None, "ready"),
        (2, 0, False, 0, 2, "in_progress", "in_progress"),
        (2, 0, False, 0, 2, "completed", "completed"),
    ],
)
def test_terminal_workflow_state_priority(
    constructed: int,
    required: int,
    hard_blocked: bool,
    missing: int,
    available: int,
    snapshot: str | None,
    expected: str,
) -> None:
    """Catches lower-priority pool state overriding construction, review, or progress."""
    projection = cast(
        TerminalReviewProjection,
        SimpleNamespace(
            constructed_meters=tuple(object() for _ in range(constructed)),
            review_required_count=required,
            hard_blocked=hard_blocked,
        ),
    )

    assert derive_terminal_workflow_state(
        projection,
        missing_collector_count=missing,
        pool_available_count=available,
        snapshot_state=snapshot,
    ) == expected
