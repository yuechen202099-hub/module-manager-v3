from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum


def normalize_identifier(value: object) -> str:
    """Normalize surrounding whitespace while preserving the identifier text."""
    return str(value or "").strip()


@dataclass(frozen=True, slots=True)
class MeterSource:
    group_id: str
    terminal_code: str
    installation_address: str
    meter_no: str
    collector_no: str
    module_no: str
    module_meter_photo_id: str | None
    after_box_photo_id: str | None


@dataclass(frozen=True, slots=True)
class CollectorRequirementSnapshot:
    original_collector_no: str
    meter_group_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TerminalSnapshot:
    terminal_code: str
    installation_address: str
    meters: tuple[MeterSource, ...]
    collector_requirements: tuple[CollectorRequirementSnapshot, ...]


class CollectorScanDecisionKind(str, Enum):
    DIRECT_REUSE = "direct_reuse"
    DIRECT_NEEDS_PHOTO = "direct_needs_photo"
    POOL_NEEDS_PHOTO = "pool_needs_photo"
    ASSIGNMENT_REUSE = "assignment_reuse"


@dataclass(frozen=True, slots=True)
class CollectorScanDecision:
    kind: CollectorScanDecisionKind
    requirement_id: str | None
    requires_photo: bool
    add_to_pool: bool


class ProjectInventoryDecisionKind(str, Enum):
    DIRECT_REUSE = "direct_reuse"
    DIRECT_NEEDS_PHOTO = "direct_needs_photo"
    POOL_NEEDS_PHOTO = "pool_needs_photo"
    EXISTING_AVAILABLE = "existing_available"
    EXISTING_RESERVED = "existing_reserved"
    EXISTING_USED = "existing_used"


@dataclass(frozen=True, slots=True)
class ProjectInventoryDecision:
    kind: ProjectInventoryDecisionKind
    persist_confirmation: bool
    requires_photo: bool
    add_to_pool: bool


class PoolInsufficientError(ValueError):
    def __init__(self, *, required: int, available: int) -> None:
        self.required = required
        self.available = available
        super().__init__(f"collector pool is insufficient: required={required}, available={available}")


def build_terminal_snapshots(records: Iterable[MeterSource]) -> tuple[TerminalSnapshot, ...]:
    terminals: dict[str, list[MeterSource]] = defaultdict(list)
    for record in records:
        terminal_code = normalize_identifier(record.terminal_code)
        if not terminal_code:
            raise ValueError("terminal_code is required")
        terminals[terminal_code].append(record)

    snapshots: list[TerminalSnapshot] = []
    for terminal_code in sorted(terminals):
        meters = tuple(
            sorted(
                terminals[terminal_code],
                key=lambda item: (normalize_identifier(item.meter_no), normalize_identifier(item.group_id)),
            )
        )
        requirement_groups: dict[str, list[str]] = defaultdict(list)
        for item in meters:
            collector_no = normalize_identifier(item.collector_no)
            if collector_no:
                requirement_groups[collector_no].append(normalize_identifier(item.group_id))
        requirements = tuple(
            CollectorRequirementSnapshot(
                original_collector_no=collector_no,
                meter_group_ids=tuple(group_ids),
            )
            for collector_no, group_ids in sorted(requirement_groups.items())
        )
        snapshots.append(
            TerminalSnapshot(
                terminal_code=terminal_code,
                installation_address=normalize_identifier(meters[0].installation_address) if meters else "",
                meters=meters,
                collector_requirements=requirements,
            )
        )
    return tuple(snapshots)


def decide_collector_scan(
    *,
    collector_no: str,
    unmatched_requirements: Mapping[str, str],
    has_reusable_photo: bool,
) -> CollectorScanDecision:
    normalized = normalize_identifier(collector_no)
    if not normalized:
        raise ValueError("collector_no is required")

    direct_requirement_id = next(
        (
            requirement_id
            for requirement_id, original_collector_no in sorted(unmatched_requirements.items())
            if normalize_identifier(original_collector_no) == normalized
        ),
        None,
    )
    if direct_requirement_id is not None:
        if has_reusable_photo:
            return CollectorScanDecision(
                kind=CollectorScanDecisionKind.DIRECT_REUSE,
                requirement_id=direct_requirement_id,
                requires_photo=False,
                add_to_pool=False,
            )
        return CollectorScanDecision(
            kind=CollectorScanDecisionKind.DIRECT_NEEDS_PHOTO,
            requirement_id=direct_requirement_id,
            requires_photo=True,
            add_to_pool=False,
        )
    return CollectorScanDecision(
        kind=CollectorScanDecisionKind.POOL_NEEDS_PHOTO,
        requirement_id=None,
        requires_photo=True,
        add_to_pool=True,
    )


def decide_project_inventory_scan(
    *,
    collector_no: str,
    is_project_requirement: bool,
    existing_pool_status: str | None,
    has_active_photo: bool,
) -> ProjectInventoryDecision:
    if not normalize_identifier(collector_no):
        raise ValueError("collector_no is required")

    status = normalize_identifier(existing_pool_status)
    terminal_states = {
        "available": ProjectInventoryDecisionKind.EXISTING_AVAILABLE,
        "reserved": ProjectInventoryDecisionKind.EXISTING_RESERVED,
        "used": ProjectInventoryDecisionKind.EXISTING_USED,
    }
    if status in terminal_states:
        return ProjectInventoryDecision(
            kind=terminal_states[status],
            persist_confirmation=False,
            requires_photo=False,
            add_to_pool=False,
        )

    if is_project_requirement or status == "direct":
        return ProjectInventoryDecision(
            kind=(
                ProjectInventoryDecisionKind.DIRECT_REUSE
                if has_active_photo
                else ProjectInventoryDecisionKind.DIRECT_NEEDS_PHOTO
            ),
            persist_confirmation=True,
            requires_photo=not has_active_photo,
            add_to_pool=False,
        )

    return ProjectInventoryDecision(
        kind=ProjectInventoryDecisionKind.POOL_NEEDS_PHOTO,
        persist_confirmation=False,
        requires_photo=True,
        add_to_pool=True,
    )


def plan_random_assignments(
    *,
    requirement_ids: Sequence[str],
    available_collector_ids: Sequence[str],
    sample: Callable[[list[str], int], list[str]] | None = None,
) -> tuple[tuple[str, str], ...]:
    requirements = sorted({normalize_identifier(value) for value in requirement_ids if normalize_identifier(value)})
    collectors = sorted(
        {normalize_identifier(value) for value in available_collector_ids if normalize_identifier(value)}
    )
    if len(collectors) < len(requirements):
        raise PoolInsufficientError(required=len(requirements), available=len(collectors))
    chooser = sample or random.SystemRandom().sample
    selected = chooser(collectors, len(requirements))
    if len(selected) != len(requirements) or len(set(selected)) != len(selected):
        raise ValueError("sample must return the requested number of distinct collectors")
    return tuple(zip(requirements, selected, strict=True))
