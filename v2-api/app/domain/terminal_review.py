from __future__ import annotations

from collections.abc import Iterable, Mapping
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
    confirmation_id: str = ""


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
    classification_manual_confirmation: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ReviewMeterProjection:
    group_id: str
    construction_state: ConstructionState
    review_ready: bool
    blockers: tuple[str, ...]
    source: MeterSource | None
    classification_manually_confirmed: bool = False
    classification_confirmation_anomalies: tuple[str, ...] = ()
    classification_manual_confirmation: Mapping[str, object] | None = None


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


def _valid_manual_confirmation(
    evidence: ReviewMeterEvidence,
) -> tuple[bool, tuple[str, ...], Mapping[str, object] | None]:
    marker = evidence.classification_manual_confirmation
    if not isinstance(marker, Mapping):
        return False, (), None
    snapshot = marker.get("photo_snapshot")
    if not isinstance(snapshot, list):
        return False, (), marker
    expected_rows = sorted(
        (
            normalize_identifier(item.confirmation_id) or normalize_identifier(item.id),
            normalize_identifier(item.category).lower(),
            normalize_identifier(item.sha256).lower(),
        )
        for item in evidence.active_photos
    )
    marker_rows: list[tuple[str, str, str]] = []
    for item in snapshot:
        if not isinstance(item, Mapping):
            return False, (), marker
        marker_rows.append(
            (
                normalize_identifier(item.get("photo_id")),
                normalize_identifier(item.get("category")).lower(),
                normalize_identifier(item.get("sha256")).lower(),
            )
        )
    if sorted(marker_rows) != expected_rows:
        return False, (), marker
    anomalies = marker.get("anomalies")
    normalized_anomalies = tuple(
        normalize_identifier(item)
        for item in anomalies
        if normalize_identifier(item)
    ) if isinstance(anomalies, list) else ()
    return True, normalized_anomalies, marker


def _project_constructed_meter(evidence: ReviewMeterEvidence) -> ReviewMeterProjection:
    manually_confirmed, confirmation_anomalies, confirmation = _valid_manual_confirmation(evidence)
    terminal_code = normalize_identifier(evidence.terminal_code)
    meter_no = normalize_identifier(evidence.meter_no)
    collector_no = normalize_identifier(evidence.collector_no)
    module_no = normalize_identifier(evidence.module_no)
    blockers: list[str] = []

    if not manually_confirmed:
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
        classification_manually_confirmed=manually_confirmed,
        classification_confirmation_anomalies=confirmation_anomalies,
        classification_manual_confirmation=confirmation,
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
        "terminal_code": source.terminal_code,
        "installation_address": source.installation_address,
        "meter_no": source.meter_no,
        "collector_no": source.collector_no,
        "module_no": source.module_no,
        "module_meter_photo_id": normalize_identifier(module_meter.id) if module_meter else None,
        "module_meter_photo_sha256": normalize_identifier(module_meter.sha256) if module_meter else None,
        "after_box_photo_id": normalize_identifier(after_box.id) if after_box else None,
        "after_box_photo_sha256": normalize_identifier(after_box.sha256) if after_box else None,
    }


def _has_construction_evidence(evidence: ReviewMeterEvidence) -> bool:
    return bool(evidence.active_photos or evidence.persisted_photo_count > 0)


def _meter_evidence_key(evidence: ReviewMeterEvidence) -> tuple[str, str]:
    meter_no = normalize_identifier(evidence.meter_no)
    if meter_no:
        return "meter", meter_no
    return "group", normalize_identifier(evidence.group_id)


def _preferred_identity_value(
    rows: tuple[ReviewMeterEvidence, ...],
    primary: ReviewMeterEvidence,
    field: str,
) -> tuple[str, bool]:
    constructed_rows = tuple(item for item in rows if _has_construction_evidence(item))
    authoritative_rows = tuple(
        item
        for item in constructed_rows
        if normalize_identifier(getattr(item, field))
    )
    candidate_rows = authoritative_rows or rows
    ordered = (primary,) + tuple(
        item
        for item in candidate_rows
        if item is not primary
    )
    values = tuple(
        dict.fromkeys(
            normalize_identifier(getattr(item, field))
            for item in ordered
            if normalize_identifier(getattr(item, field))
        )
    )
    return (values[0] if values else ""), len(values) > 1


def _merge_constructed_meter_evidence(
    rows: tuple[ReviewMeterEvidence, ...],
) -> ReviewMeterEvidence:
    constructed_rows = tuple(item for item in rows if _has_construction_evidence(item))
    primary = sorted(
        constructed_rows,
        key=lambda item: (
            -len(item.active_photos),
            -max(0, item.persisted_photo_count),
            normalize_identifier(item.group_id),
        ),
    )[0]
    terminal_code, terminal_conflict = _preferred_identity_value(
        rows, primary, "terminal_code"
    )
    collector_no, collector_conflict = _preferred_identity_value(
        rows, primary, "collector_no"
    )
    module_no, module_conflict = _preferred_identity_value(rows, primary, "module_no")

    photos_by_id: dict[str, ReviewPhotoEvidence] = {}
    for item in constructed_rows:
        for photo in item.active_photos:
            photos_by_id.setdefault(normalize_identifier(photo.id), photo)
    active_photos = tuple(
        sorted(
            photos_by_id.values(),
            key=lambda item: (
                normalize_identifier(item.category).lower(),
                normalize_identifier(item.id),
            ),
        )
    )

    merged_identity_values = {
        "terminal_missing": terminal_code,
        "meter_missing": normalize_identifier(primary.meter_no),
        "collector_missing": collector_no,
        "module_missing": module_no,
    }
    primary_identity_values = {
        "terminal_missing": normalize_identifier(primary.terminal_code),
        "meter_missing": normalize_identifier(primary.meter_no),
        "collector_missing": normalize_identifier(primary.collector_no),
        "module_missing": normalize_identifier(primary.module_no),
    }
    identity_blockers = {
        code
        for item in constructed_rows
        for code in item.identity_blockers
        if not (
            code in merged_identity_values
            and not primary_identity_values[code]
            and merged_identity_values[code]
        )
    }
    source_blockers = {
        code
        for item in constructed_rows
        for code in item.source_blockers
    }
    if terminal_conflict or collector_conflict or module_conflict:
        source_blockers.add("source_conflict")

    return ReviewMeterEvidence(
        group_id=normalize_identifier(primary.group_id),
        status=primary.status,
        terminal_code=terminal_code,
        installation_address=normalize_identifier(primary.installation_address),
        meter_no=normalize_identifier(primary.meter_no),
        collector_no=collector_no,
        module_no=module_no,
        persisted_photo_count=max(
            len(active_photos),
            *(max(0, item.persisted_photo_count) for item in constructed_rows),
        ),
        active_photos=active_photos,
        barcode_status=primary.barcode_status,
        identity_blockers=tuple(sorted(identity_blockers)),
        source_blockers=tuple(sorted(source_blockers)),
        classification_manual_confirmation=primary.classification_manual_confirmation,
    )


def project_terminal_review(
    meters: Iterable[ReviewMeterEvidence],
) -> TerminalReviewProjection:
    constructed_pairs: list[tuple[ReviewMeterEvidence, ReviewMeterProjection]] = []
    unconstructed: list[ReviewMeterProjection] = []

    meters_by_identity: dict[tuple[str, str], list[ReviewMeterEvidence]] = {}
    for evidence in meters:
        group_id = normalize_identifier(evidence.group_id)
        if not group_id:
            raise ValueError("group_id is required")
        meters_by_identity.setdefault(_meter_evidence_key(evidence), []).append(evidence)

    for identity in sorted(meters_by_identity):
        evidence_rows = tuple(meters_by_identity[identity])
        if any(_has_construction_evidence(item) for item in evidence_rows):
            evidence = _merge_constructed_meter_evidence(evidence_rows)
            constructed_pairs.append((evidence, _project_constructed_meter(evidence)))
        else:
            evidence = min(
                evidence_rows,
                key=lambda item: normalize_identifier(item.group_id),
            )
            unconstructed.append(
                ReviewMeterProjection(
                    group_id=normalize_identifier(evidence.group_id),
                    construction_state="unconstructed",
                    review_ready=False,
                    blockers=(),
                    source=None,
                )
            )

    constructed_pairs.sort(key=lambda pair: pair[1].group_id)
    unconstructed.sort(key=lambda item: item.group_id)
    constructed = tuple(pair[1] for pair in constructed_pairs)
    rephoto_sources = tuple(
        item.source
        for item in constructed
        if item.source is not None
        and all(code in _SOFT_REVIEW_BLOCKERS for code in item.blockers)
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
    hard_blocked = bool(constructed) and not rephoto_sources
    return TerminalReviewProjection(
        constructed_meters=constructed,
        unconstructed_meters=tuple(unconstructed),
        rephoto_sources=rephoto_sources,
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
