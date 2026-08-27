from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from app.domain.collector_transfer import (
    CollectorRequirementSnapshot,
    MeterSource,
    build_terminal_snapshots,
    normalize_identifier,
    terminal_source_revision,
)


ConstructionState = Literal["constructed", "unconstructed"]
TerminalWorkflowState = Literal[
    "no_construction",
    "needs_review",
    "blocked",
    "needs_replacement",
    "pool_shortage",
    "ready",
    "in_progress",
    "completed",
]

_REQUIRED_PHOTO_CATEGORIES = ("module_meter", "after_box")
_BARCODE_READY_STATUSES = frozenset({"passed", "manual_confirmed", "manual"})
_BLOCKER_ORDER = (
    "review_not_approved",
    "terminal_missing",
    "meter_missing",
    "module_missing",
    "collector_missing",
    "module_meter_photo_missing",
    "module_meter_photo_conflict",
    "after_box_photo_missing",
    "after_box_photo_conflict",
    "barcode_verification_required",
    "exception_open",
    "address_missing",
    "address_conflict",
    "source_conflict",
)
_BLOCKER_INDEX = {code: index for index, code in enumerate(_BLOCKER_ORDER)}
_SOFT_REVIEW_BLOCKERS = frozenset({"review_not_approved", "barcode_verification_required"})


@dataclass(frozen=True, slots=True)
class ReviewPhotoEvidence:
    id: str
    category: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ReviewMeterEvidence:
    group_id: str
    status: str
    terminal_code: str
    installation_address: str
    meter_no: str
    collector_no: str
    module_no: str
    persisted_photo_count: int
    active_photos: tuple[ReviewPhotoEvidence, ...]
    barcode_status: str
    identity_blockers: tuple[str, ...] = ()
    source_blockers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReviewMeterProjection:
    group_id: str
    construction_state: ConstructionState
    review_ready: bool
    blockers: tuple[str, ...]
    source: MeterSource | None


@dataclass(frozen=True, slots=True)
class TerminalReviewProjection:
    constructed_meters: tuple[ReviewMeterProjection, ...]
    unconstructed_meters: tuple[ReviewMeterProjection, ...]
    rephoto_sources: tuple[MeterSource, ...]
    collector_requirements: tuple[CollectorRequirementSnapshot, ...]
    review_ready_count: int
    review_required_count: int
    source_revision: str
    hard_blocked: bool


def _ordered_blockers(codes: Iterable[str]) -> tuple[str, ...]:
    normalized = {normalize_identifier(code) for code in codes if normalize_identifier(code)}
    unknown = normalized.difference(_BLOCKER_INDEX)
    if unknown:
        raise ValueError(f"unsupported terminal review blocker: {sorted(unknown)[0]}")
    return tuple(sorted(normalized, key=_BLOCKER_INDEX.__getitem__))


def _selected_photo(
    photos: tuple[ReviewPhotoEvidence, ...],
    category: str,
) -> ReviewPhotoEvidence | None:
    matching = tuple(
        item
        for item in photos
        if normalize_identifier(item.category).lower() == category
    )
    return matching[0] if len(matching) == 1 else None


def _project_constructed_meter(evidence: ReviewMeterEvidence) -> ReviewMeterProjection:
    status = normalize_identifier(evidence.status).lower()
    terminal_code = normalize_identifier(evidence.terminal_code)
    meter_no = normalize_identifier(evidence.meter_no)
    collector_no = normalize_identifier(evidence.collector_no)
    module_no = normalize_identifier(evidence.module_no)
    blockers: list[str] = []

    if status != "approved":
        blockers.append("review_not_approved")
    if not terminal_code:
        blockers.append("terminal_missing")
    if not meter_no:
        blockers.append("meter_missing")
    if not module_no:
        blockers.append("module_missing")
    if not collector_no:
        blockers.append("collector_missing")
    blockers.extend(evidence.identity_blockers)

    photos = tuple(evidence.active_photos)
    selected: dict[str, ReviewPhotoEvidence | None] = {}
    for category in _REQUIRED_PHOTO_CATEGORIES:
        matching_count = sum(
            1
            for item in photos
            if normalize_identifier(item.category).lower() == category
        )
        if matching_count == 0:
            blockers.append(f"{category}_photo_missing")
        elif matching_count > 1:
            blockers.append(f"{category}_photo_conflict")
        selected[category] = _selected_photo(photos, category)

    barcode_status = normalize_identifier(evidence.barcode_status).lower()
    if barcode_status not in _BARCODE_READY_STATUSES:
        blockers.append("barcode_verification_required")
    blockers.extend(evidence.source_blockers)
    ordered_blockers = _ordered_blockers(blockers)

    source = MeterSource(
        group_id=normalize_identifier(evidence.group_id),
        terminal_code=terminal_code,
        installation_address=normalize_identifier(evidence.installation_address),
        meter_no=meter_no,
        collector_no=collector_no,
        module_no=module_no,
        module_meter_photo_id=(
            normalize_identifier(selected["module_meter"].id)
            if selected["module_meter"] is not None
            else None
        ),
        after_box_photo_id=(
            normalize_identifier(selected["after_box"].id)
            if selected["after_box"] is not None
            else None
        ),
    )
    return ReviewMeterProjection(
        group_id=source.group_id,
        construction_state="constructed",
        review_ready=not ordered_blockers,
        blockers=ordered_blockers,
        source=source,
    )


def _source_revision_row(
    evidence: ReviewMeterEvidence,
    projection: ReviewMeterProjection,
) -> dict[str, object]:
    photos = tuple(evidence.active_photos)
    module_meter = _selected_photo(photos, "module_meter")
    after_box = _selected_photo(photos, "after_box")
    source = projection.source
    assert source is not None
    return {
        "group_id": source.group_id,
        "status": normalize_identifier(evidence.status).lower(),
        "terminal_code": source.terminal_code,
        "installation_address": source.installation_address,
        "meter_no": source.meter_no,
        "collector_no": source.collector_no,
        "module_no": source.module_no,
        "blockers": projection.blockers,
        "module_meter_photo_id": normalize_identifier(module_meter.id) if module_meter else None,
        "module_meter_photo_sha256": normalize_identifier(module_meter.sha256) if module_meter else None,
        "after_box_photo_id": normalize_identifier(after_box.id) if after_box else None,
        "after_box_photo_sha256": normalize_identifier(after_box.sha256) if after_box else None,
        "barcode_status": normalize_identifier(evidence.barcode_status).lower(),
    }


def project_terminal_review(
    meters: Iterable[ReviewMeterEvidence],
) -> TerminalReviewProjection:
    constructed_pairs: list[tuple[ReviewMeterEvidence, ReviewMeterProjection]] = []
    unconstructed: list[ReviewMeterProjection] = []

    for evidence in meters:
        group_id = normalize_identifier(evidence.group_id)
        if not group_id:
            raise ValueError("group_id is required")
        if evidence.active_photos or evidence.persisted_photo_count > 0:
            constructed_pairs.append((evidence, _project_constructed_meter(evidence)))
        else:
            unconstructed.append(
                ReviewMeterProjection(
                    group_id=group_id,
                    construction_state="unconstructed",
                    review_ready=False,
                    blockers=(),
                    source=None,
                )
            )

    constructed_pairs.sort(key=lambda pair: pair[1].group_id)
    unconstructed.sort(key=lambda item: item.group_id)
    constructed = tuple(pair[1] for pair in constructed_pairs)
    ready_sources = tuple(
        item.source
        for item in constructed
        if item.review_ready and item.source is not None
    )
    all_valid_sources = tuple(
        item.source
        for item in constructed
        if item.source is not None and item.source.terminal_code
    )
    collector_requirements = tuple(
        requirement
        for snapshot in build_terminal_snapshots(all_valid_sources)
        for requirement in snapshot.collector_requirements
    )
    revision_rows = (
        _source_revision_row(evidence, projection)
        for evidence, projection in constructed_pairs
    )
    review_ready_count = sum(item.review_ready for item in constructed)
    hard_blocked = any(
        code not in _SOFT_REVIEW_BLOCKERS
        for item in constructed
        for code in item.blockers
    )
    return TerminalReviewProjection(
        constructed_meters=constructed,
        unconstructed_meters=tuple(unconstructed),
        rephoto_sources=ready_sources,
        collector_requirements=collector_requirements,
        review_ready_count=review_ready_count,
        review_required_count=len(constructed) - review_ready_count,
        source_revision=terminal_source_revision(revision_rows),
        hard_blocked=hard_blocked,
    )


def derive_terminal_workflow_state(
    projection: TerminalReviewProjection,
    missing_collector_count: int,
    pool_available_count: int,
    snapshot_state: str | None,
) -> TerminalWorkflowState:
    if not projection.constructed_meters:
        return "no_construction"
    if projection.hard_blocked:
        return "blocked"
    if projection.review_required_count:
        return "needs_review"
    normalized_snapshot_state = normalize_identifier(snapshot_state).lower()
    if normalized_snapshot_state == "in_progress":
        return "in_progress"
    if normalized_snapshot_state == "completed":
        return "completed"
    if missing_collector_count > pool_available_count:
        return "pool_shortage"
    if missing_collector_count:
        return "needs_replacement"
    return "ready"
