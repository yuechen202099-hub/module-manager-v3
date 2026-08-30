from __future__ import annotations

import pytest

from app.domain import collector_transfer as collector_transfer_domain
from app.domain.collector_transfer import (
    CollectorScanDecisionKind,
    MeterSource,
    PoolInsufficientError,
    ProjectInventoryDecisionKind,
    build_terminal_snapshots,
    decode_terminal_key,
    decide_collector_scan,
    decide_project_inventory_scan,
    plan_random_assignments,
    terminal_key,
)


def meter(
    *,
    group_id: str,
    terminal: str,
    meter_no: str,
    collector_no: str,
    module_no: str,
) -> MeterSource:
    return MeterSource(
        group_id=group_id,
        terminal_code=terminal,
        installation_address="聚丰园路95弄21号",
        meter_no=meter_no,
        collector_no=collector_no,
        module_no=module_no,
        module_meter_photo_id=f"{group_id}-module-meter",
        after_box_photo_id=f"{group_id}-after-box",
    )


def test_terminal_snapshot_deduplicates_collectors_and_duplicate_meter_rows() -> None:
    """Catches construction-stage duplicates creating a second meter or collector demand."""
    snapshots = build_terminal_snapshots(
        [
            meter(group_id="g-1", terminal="T-001", meter_no="M-001", collector_no="C-100", module_no="A-001"),
            meter(
                group_id="g-1-before",
                terminal="T-001",
                meter_no="M-001",
                collector_no="C-100",
                module_no="A-001",
            ),
            meter(group_id="g-2", terminal="T-001", meter_no="M-002", collector_no="C-100", module_no="A-002"),
            meter(group_id="g-3", terminal="T-001", meter_no="M-003", collector_no="C-200", module_no="A-003"),
        ]
    )

    assert len(snapshots) == 1
    assert [item.meter_no for item in snapshots[0].meters] == ["M-001", "M-002", "M-003"]
    assert [item.original_collector_no for item in snapshots[0].collector_requirements] == ["C-100", "C-200"]
    assert snapshots[0].collector_requirements[0].meter_group_ids == ("g-1", "g-2")


@pytest.mark.parametrize(
    ("has_photo", "expected_kind", "expected_requires_photo"),
    [
        (True, CollectorScanDecisionKind.DIRECT_REUSE, False),
        (False, CollectorScanDecisionKind.DIRECT_NEEDS_PHOTO, True),
    ],
)
def test_same_number_scan_never_enters_pool(
    has_photo: bool,
    expected_kind: CollectorScanDecisionKind,
    expected_requires_photo: bool,
) -> None:
    """Catches sending a same-number physical collector into the random pool."""
    decision = decide_collector_scan(
        collector_no=" 000123 ",
        unmatched_requirements={"requirement-1": "000123"},
        has_reusable_photo=has_photo,
    )

    assert decision.kind is expected_kind
    assert decision.requirement_id == "requirement-1"
    assert decision.requires_photo is expected_requires_photo
    assert decision.add_to_pool is False


def test_non_matching_scan_requires_photo_before_pool_admission() -> None:
    """Catches treating an unphotographed replacement collector as available."""
    decision = decide_collector_scan(
        collector_no="000999",
        unmatched_requirements={"requirement-1": "000123"},
        has_reusable_photo=False,
    )

    assert decision.kind is CollectorScanDecisionKind.POOL_NEEDS_PHOTO
    assert decision.requirement_id is None
    assert decision.requires_photo is True
    assert decision.add_to_pool is True


def test_project_scan_non_direct_requires_photo_without_persistence_intent() -> None:
    """Catches creating a server-side draft as soon as a non-matching barcode is scanned."""
    decision = decide_project_inventory_scan(
        collector_no=" 000999 ",
        is_project_requirement=False,
        existing_pool_status=None,
        has_active_photo=False,
    )

    assert decision.kind is ProjectInventoryDecisionKind.POOL_NEEDS_PHOTO
    assert decision.persist_confirmation is False
    assert decision.requires_photo is True
    assert decision.add_to_pool is True


def test_project_scan_direct_with_photo_confirms_without_pool_admission() -> None:
    """Catches forcing a photographed same-number collector through random-pool admission."""
    decision = decide_project_inventory_scan(
        collector_no="000123",
        is_project_requirement=True,
        existing_pool_status="direct",
        has_active_photo=True,
    )

    assert decision.kind is ProjectInventoryDecisionKind.DIRECT_REUSE
    assert decision.persist_confirmation is True
    assert decision.requires_photo is False
    assert decision.add_to_pool is False


def test_project_requirement_without_photo_is_direct_reuse() -> None:
    """Catches forcing an in-hand same-number collector through website photo capture."""
    decision = decide_project_inventory_scan(
        collector_no="00001234",
        is_project_requirement=True,
        existing_pool_status=None,
        has_active_photo=False,
    )

    assert decision.kind is ProjectInventoryDecisionKind.DIRECT_REUSE
    assert decision.persist_confirmation is True
    assert decision.requires_photo is False
    assert decision.add_to_pool is False


def test_terminal_key_preserves_leading_zeroes_and_project_identity() -> None:
    """Catches merging same-code terminals across projects or normalizing away leading zeroes."""
    project_a = "11111111-1111-1111-1111-111111111111"
    project_b = "22222222-2222-2222-2222-222222222222"

    assert collector_transfer_domain.terminal_key(project_a, " 000123 ") == collector_transfer_domain.terminal_key(project_a, "000123")
    assert collector_transfer_domain.terminal_key(project_a, "000123") != collector_transfer_domain.terminal_key(project_b, "000123")
    assert collector_transfer_domain.terminal_key(project_a, "000123") != collector_transfer_domain.terminal_key(project_a, "123")


def test_terminal_key_round_trip_preserves_arbitrary_identifier_text() -> None:
    """Catches decoding a key with lossy identifier normalization."""
    encoded = terminal_key("7d0ea83b-7621-4b56-95bf-f32cf444ee93", "00001234-A")

    assert decode_terminal_key(encoded) == (
        "7d0ea83b-7621-4b56-95bf-f32cf444ee93",
        "00001234-A",
    )


@pytest.mark.parametrize(
    "value",
    ["", "%%%%", "W10=", "WyIiLCIxMjMiXQ", "WyJwIiwidCJd%%%%"],
)
def test_decode_terminal_key_rejects_malformed_or_blank_parts(value: str) -> None:
    """Catches accepting malformed keys as project or terminal authority."""
    with pytest.raises(ValueError, match="terminal_key"):
        decode_terminal_key(value)


def test_source_revision_is_order_stable_and_photo_sensitive() -> None:
    """Catches reusing a hidden snapshot after its selected photo evidence changed."""
    rows = [
        {
            "group_id": "g-2",
            "meter_no": "M-002",
            "collector_no": "C-001",
            "module_meter_photo_id": "photo-2",
            "module_meter_photo_sha256": "22" * 32,
        },
        {
            "group_id": "g-1",
            "meter_no": "M-001",
            "collector_no": "C-001",
            "module_meter_photo_id": "photo-1",
            "module_meter_photo_sha256": "11" * 32,
        },
    ]
    changed = [dict(row) for row in rows]
    changed[0]["module_meter_photo_sha256"] = "33" * 32

    assert collector_transfer_domain.terminal_source_revision(reversed(rows)) == collector_transfer_domain.terminal_source_revision(rows)
    assert collector_transfer_domain.terminal_source_revision(rows) != collector_transfer_domain.terminal_source_revision(changed)


@pytest.mark.parametrize(
    ("status", "expected_kind"),
    [
        ("reserved", ProjectInventoryDecisionKind.EXISTING_RESERVED),
        ("used", ProjectInventoryDecisionKind.EXISTING_USED),
    ],
)
def test_project_scan_never_demotes_consumed_inventory(
    status: str,
    expected_kind: ProjectInventoryDecisionKind,
) -> None:
    """Catches a repeated scan making an assigned or consumed collector reusable again."""
    decision = decide_project_inventory_scan(
        collector_no="C-1",
        is_project_requirement=True,
        existing_pool_status=status,
        has_active_photo=True,
    )

    assert decision.kind is expected_kind
    assert decision.persist_confirmation is False
    assert decision.requires_photo is False
    assert decision.add_to_pool is False


def test_random_allocation_fails_as_a_whole_when_pool_is_insufficient() -> None:
    """Catches silently returning a partial allocation when one pool item is missing."""
    chooser_called = False

    def chooser(_population: list[str], _count: int) -> list[str]:
        nonlocal chooser_called
        chooser_called = True
        return []

    with pytest.raises(PoolInsufficientError) as caught:
        plan_random_assignments(
            requirement_ids=["requirement-1", "requirement-2"],
            available_collector_ids=["collector-1"],
            sample=chooser,
        )

    assert caught.value.required == 2
    assert caught.value.available == 1
    assert chooser_called is False


def test_random_allocation_consumes_each_requirement_and_collector_once() -> None:
    """Catches assigning one physical collector to two removal requirements."""
    assignments = plan_random_assignments(
        requirement_ids=["requirement-2", "requirement-1"],
        available_collector_ids=["collector-1", "collector-2", "collector-3"],
        sample=lambda population, count: [population[2], population[0]][:count],
    )

    assert assignments == (
        ("requirement-1", "collector-3"),
        ("requirement-2", "collector-1"),
    )
    assert len({collector_id for _, collector_id in assignments}) == 2
