from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import String, and_, case, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.sql.functions import FunctionElement

from app.domain.collector_transfer import (
    CollectorScanDecision,
    CollectorScanDecisionKind,
    MeterSource,
    PoolInsufficientError,
    build_terminal_snapshots,
    decode_terminal_key,
    decide_collector_scan,
    decide_project_inventory_scan,
    normalize_identifier,
    plan_random_assignments,
    terminal_key,
    terminal_source_revision,
)
from app.domain.terminal_review import (
    ReviewMeterEvidence,
    ReviewMeterProjection,
    ReviewPhotoEvidence,
    TerminalReviewProjection,
    derive_terminal_workflow_state,
    project_terminal_review,
)
from app.models import (
    AuditLog,
    CollectorAssignment,
    CollectorMeterItem,
    CollectorPhoto,
    CollectorRequirement,
    CollectorRequirementMeter,
    CollectorScanEvent,
    CollectorTransferRun,
    CollectorTransferTerminal,
    CollectorWorkbenchItem,
    GroupBarcodeVerification,
    MaterialGroup,
    Photo,
    PhysicalCollector,
    Project,
    ProjectStatus,
    TotalCatalogRow,
    User,
)
from app.services.barcode_verification_contract import resolve_persisted_barcode_verification
from app.services.local_simulation import is_placeholder_formal_identity_value
from app.services import photo_barcode_check
from app.services.photo_storage import resolve_photo_for_response


class CollectorAllocationConflictError(ValueError):
    """A database uniqueness backstop rejected an allocation after the service acquired its locks."""


class CollectorRunBlockedError(ValueError):
    """Allocation was rejected because the run contains blocked terminal evidence."""


class CollectorTerminalSourceBlockedError(CollectorRunBlockedError):
    """A global terminal source cannot produce a valid re-photography snapshot."""


class CollectorPhotoConflictError(ValueError):
    """Photo content is already bound to a different physical collector."""


class CollectorScanProvenanceError(ValueError):
    """Photo registration was not preceded by a scan in the same run."""


class CollectorDirectConflictError(ValueError):
    """A direct physical collector is already owned by another active terminal."""


class CollectorSnapshotChangedError(ValueError):
    """A hidden terminal snapshot cannot be refreshed while progress remains."""


class CollectorInventorySnapshotChangedError(ValueError):
    """The inventory record changed after the operator opened it."""


class CollectorInventoryAssignmentLockedError(ValueError):
    """A reserved or used inventory record must be rolled back before renumbering."""


class CollectorInventoryNumberConflictError(ValueError):
    """The corrected collector number already belongs to another physical device."""


class TerminalReviewRequiredError(ValueError):
    """At least one constructed meter has not passed the current review gate."""

    def __init__(self, meters: Sequence[ReviewMeterProjection]) -> None:
        self.meters = tuple(meters)
        super().__init__("terminal review is required")


class TerminalNoConstructedMeterError(CollectorRunBlockedError):
    """A terminal with no constructed meter cannot have re-photo mutations."""


class TerminalSourceChangedError(CollectorSnapshotChangedError):
    """The constructed review evidence no longer matches the hidden snapshot."""


class TerminalNotFoundError(KeyError):
    """The opaque terminal identity is absent from the authenticated team."""


class CollectorWorkbenchIncompleteError(ValueError):
    """Workbench completion was rejected because authoritative evidence is incomplete."""

    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__("；".join(self.reasons) or "翻拍工作项资料不完整")


_MISSING_TERMINAL_PREFIX = "__missing_terminal__:"
_MANUAL_DEMAND_INTERNAL_PREFIX = "manual-demand:"
_MANUAL_DEMAND_DIAGNOSTIC_CODE = "manual_collector_demand"
_MANUAL_DEMAND_LABEL = "人工需求"
_IDENTIFIER_BOUNDARY_WHITESPACE = (
    "\t\n\v\f\r\x1c\x1d\x1e\x1f \x85\xa0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000"
)


def _is_reserved_collector_number(value: object) -> bool:
    return normalize_identifier(value).casefold().startswith(
        _MANUAL_DEMAND_INTERNAL_PREFIX
    )


def validate_collector_number(value: object, field_name: str = "collector_no") -> str:
    normalized = normalize_identifier(value)
    if not normalized:
        raise ValueError(f"{field_name} is required")
    if _is_reserved_collector_number(normalized):
        raise ValueError(f"{field_name} uses a reserved namespace")
    return normalized


def _public_collector_number_clause():
    return ~func.lower(PhysicalCollector.collector_no).like(
        f"{_MANUAL_DEMAND_INTERNAL_PREFIX}%"
    )


class _IdentifierBoundaryStrip(FunctionElement):
    type = String()
    inherit_cache = True


def _compile_boundary_strip(function_name: str, element, compiler, **kwargs) -> str:
    arguments = ", ".join(
        compiler.process(argument, **kwargs)
        for argument in element.clauses
    )
    return f"{function_name}({arguments})"


@compiles(_IdentifierBoundaryStrip, "sqlite")
def _compile_sqlite_boundary_strip(element, compiler, **kwargs) -> str:
    return _compile_boundary_strip("trim", element, compiler, **kwargs)


@compiles(_IdentifierBoundaryStrip, "postgresql")
def _compile_postgresql_boundary_strip(element, compiler, **kwargs) -> str:
    return _compile_boundary_strip("btrim", element, compiler, **kwargs)


def _sql_identifier_strip(value):
    return _IdentifierBoundaryStrip(value, _IDENTIFIER_BOUNDARY_WHITESPACE)


@dataclass(frozen=True, slots=True)
class MeterSourceProjection:
    sources: tuple[MeterSource, ...]
    diagnostics: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class _ProjectGroupRow:
    id: UUID
    legacy_id: str | None
    status: object
    terminal: str | None
    display_meter_no: str
    installation_address: str
    photo_count: int
    exception_note: str | None
    raw_data: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _GlobalTerminalGroupRow:
    project_id: UUID
    id: UUID
    legacy_id: str | None
    status: object
    terminal: str | None
    display_meter_no: str
    installation_address: str
    photo_count: int
    exception_note: str | None
    raw_data: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _ProjectPhotoRow:
    id: UUID
    legacy_id: str | None
    group_id: UUID
    collector: str | None
    asset_no: str | None
    category: str | None
    sort_order: int
    is_active: bool
    image_url: str | None
    object_key: str
    storage_type: str | None
    storage_key: str | None
    storage_bucket: str | None
    sha256: str
    content_type: str | None


@dataclass(frozen=True, slots=True)
class _TerminalReviewBundle:
    project_id: UUID
    terminal_code: str
    projection: TerminalReviewProjection
    photos: tuple[_ProjectPhotoRow, ...]
    review_rows: tuple[dict[str, object], ...]


def _raw_value(raw_data: object, *keys: str) -> str:
    if not isinstance(raw_data, Mapping):
        return ""
    for key in keys:
        value = normalize_identifier(raw_data.get(key))
        if value:
            return value
    return ""


def meter_sources_from_groups(groups: Iterable[object], photos: Iterable[object]) -> MeterSourceProjection:
    photos_by_group: dict[str, list[object]] = defaultdict(list)
    for photo in photos:
        if getattr(photo, "is_active", True) is False:
            continue
        photos_by_group[normalize_identifier(getattr(photo, "group_id", ""))].append(photo)

    sources: list[MeterSource] = []
    diagnostics: list[dict[str, str]] = []
    for group in groups:
        group_id = normalize_identifier(getattr(group, "id", ""))
        terminal_code = normalize_identifier(getattr(group, "terminal", ""))
        if not terminal_code:
            diagnostics.append(
                {"group_id": group_id, "code": "terminal_missing", "message": "终端地址码为空"}
            )
            terminal_code = f"{_MISSING_TERMINAL_PREFIX}{group_id}"
        group_photos = photos_by_group.get(group_id, [])
        module_meter = next(
            (photo for photo in group_photos if normalize_identifier(getattr(photo, "category", "")) == "module_meter"),
            None,
        )
        after_box = next(
            (photo for photo in group_photos if normalize_identifier(getattr(photo, "category", "")) == "after_box"),
            None,
        )
        raw_data = getattr(group, "raw_data", {})
        collector_no = next(
            (
                normalize_identifier(getattr(photo, "collector", ""))
                for photo in group_photos
                if normalize_identifier(getattr(photo, "collector", ""))
            ),
            "",
        ) or _raw_value(raw_data, "collector", "采集器", "采集器号", "construction_collector")
        module_no = (
            normalize_identifier(getattr(module_meter, "asset_no", ""))
            if module_meter is not None
            else ""
        ) or _raw_value(raw_data, "module_asset_no", "模块资产编号", "模块号", "construction_module_asset_no")
        meter_no = normalize_identifier(getattr(group, "display_meter_no", ""))
        source_diagnostics: list[str] = []
        if not meter_no:
            source_diagnostics.append("meter_missing")
        if not collector_no:
            source_diagnostics.append("collector_missing")
        if not module_no:
            source_diagnostics.append("module_missing")
        if module_meter is None:
            source_diagnostics.append("module_meter_photo_missing")
        if after_box is None:
            source_diagnostics.append("after_box_photo_missing")
        for code in source_diagnostics:
            diagnostics.append({"group_id": group_id, "code": code, "message": code})
        sources.append(
            MeterSource(
                group_id=group_id,
                terminal_code=terminal_code,
                installation_address=normalize_identifier(getattr(group, "installation_address", "")),
                meter_no=meter_no,
                collector_no=collector_no,
                module_no=module_no,
                module_meter_photo_id=(
                    normalize_identifier(getattr(module_meter, "id", "")) if module_meter is not None else None
                ),
                after_box_photo_id=(
                    normalize_identifier(getattr(after_box, "id", "")) if after_box is not None else None
                ),
            )
        )
    return MeterSourceProjection(sources=tuple(sources), diagnostics=tuple(diagnostics))


def _with_terminal_address_diagnostics(
    projection: MeterSourceProjection,
) -> MeterSourceProjection:
    missing_address_groups = sorted(
        source.group_id
        for source in projection.sources
        if not normalize_identifier(source.installation_address)
    )
    diagnostics = list(projection.diagnostics)
    for group_id in missing_address_groups:
        diagnostics.append(
            {
                "group_id": group_id,
                "code": "installation_address_missing",
                "message": "安装地址为空",
            }
        )
    return MeterSourceProjection(
        sources=projection.sources,
        diagnostics=tuple(diagnostics),
    )


def _status_text(value: object) -> str:
    return normalize_identifier(getattr(value, "value", value)).lower()


def _review_projection_from_rows(
    groups: Sequence[_ProjectGroupRow | _GlobalTerminalGroupRow],
    photos: Sequence[_ProjectPhotoRow],
    verification_by_group: Mapping[UUID, Mapping[str, object]],
) -> tuple[TerminalReviewProjection, tuple[dict[str, object], ...]]:
    source_projection = _with_terminal_address_diagnostics(
        meter_sources_from_groups(groups, photos)
    )
    source_by_group = {source.group_id: source for source in source_projection.sources}
    photos_by_group: dict[str, list[_ProjectPhotoRow]] = defaultdict(list)
    for item in photos:
        photos_by_group[str(item.group_id)].append(item)

    evidence_rows: list[ReviewMeterEvidence] = []
    for group in groups:
        internal_group_id = str(group.id)
        source = source_by_group[internal_group_id]
        identity_blockers: list[str] = []
        for value, code in (
            (source.terminal_code, "terminal_missing"),
            (source.meter_no, "meter_missing"),
            (source.module_no, "module_missing"),
            (source.collector_no, "collector_missing"),
        ):
            if is_placeholder_formal_identity_value(value):
                identity_blockers.append(code)

        source_blockers: list[str] = []
        if normalize_identifier(group.exception_note):
            source_blockers.append("exception_open")
        if not normalize_identifier(source.installation_address):
            source_blockers.append("address_missing")

        raw_data = group.raw_data if isinstance(group.raw_data, Mapping) else {}
        manual_confirmation = raw_data.get("classification_manual_confirmation")
        persisted_verification = resolve_persisted_barcode_verification(
            verification_by_group.get(group.id),
            raw_data,
            [],
        )
        barcode_status = normalize_identifier(
            (persisted_verification or {}).get("status")
        ).lower()
        if not barcode_status:
            nested_verification = raw_data.get("barcode_verification")
            if isinstance(nested_verification, Mapping):
                compatibility_status = normalize_identifier(
                    nested_verification.get("status")
                ).lower()
                if compatibility_status == "manual":
                    barcode_status = compatibility_status

        group_photos = tuple(photos_by_group.get(internal_group_id, ()))
        evidence_rows.append(
            ReviewMeterEvidence(
                group_id=internal_group_id,
                status=_status_text(group.status),
                terminal_code=source.terminal_code,
                installation_address=source.installation_address,
                meter_no=source.meter_no,
                collector_no=source.collector_no,
                module_no=source.module_no,
                persisted_photo_count=max(0, int(group.photo_count or 0)),
                active_photos=tuple(
                    ReviewPhotoEvidence(
                        id=str(item.id),
                        category=normalize_identifier(item.category).lower(),
                        sha256=normalize_identifier(item.sha256),
                        confirmation_id=normalize_identifier(item.legacy_id) or str(item.id),
                    )
                    for item in group_photos
                ),
                barcode_status=barcode_status,
                identity_blockers=tuple(identity_blockers),
                source_blockers=tuple(source_blockers),
                classification_manual_confirmation=(
                    dict(manual_confirmation) if isinstance(manual_confirmation, Mapping) else None
                ),
            )
        )

    projection = project_terminal_review(evidence_rows)
    meter_by_group = {
        item.group_id: item
        for item in (*projection.constructed_meters, *projection.unconstructed_meters)
    }
    review_rows: list[dict[str, object]] = []
    for group in sorted(
        groups,
        key=lambda item: (
            normalize_identifier(item.display_meter_no),
            normalize_identifier(item.legacy_id),
            str(item.id),
        ),
    ):
        internal_group_id = str(group.id)
        meter_projection = meter_by_group[internal_group_id]
        source = source_by_group[internal_group_id]
        review_rows.append(
            {
                "group_id": normalize_identifier(group.legacy_id) or internal_group_id,
                "meter_no": source.meter_no,
                "module_no": source.module_no,
                "collector_no": source.collector_no,
                "construction_state": meter_projection.construction_state,
                "review_ready": meter_projection.review_ready,
                "blockers": list(meter_projection.blockers),
                "review_status": _status_text(group.status),
                "classification_manually_confirmed": meter_projection.classification_manually_confirmed,
                "classification_confirmation_anomalies": list(
                    meter_projection.classification_confirmation_anomalies
                ),
                "classification_manual_confirmation": (
                    dict(meter_projection.classification_manual_confirmation)
                    if meter_projection.classification_manual_confirmation is not None
                    else None
                ),
            }
        )
    return projection, tuple(review_rows)


def _uuid(value: object, field_name: str) -> UUID:
    try:
        return UUID(normalize_identifier(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"{field_name} is invalid") from exc


def _photo_value(photo: object, field: str) -> object:
    if isinstance(photo, Mapping):
        return photo.get(field)
    return getattr(photo, field, "")


def _photo_snapshot(photo: Photo | _ProjectPhotoRow | None) -> dict[str, object]:
    if photo is None:
        return {}
    return {
        "id": str(photo.id),
        "image_url": normalize_identifier(photo.image_url),
        "object_key": normalize_identifier(photo.object_key),
        "storage_type": normalize_identifier(photo.storage_type),
        "storage_key": normalize_identifier(photo.storage_key),
        "storage_bucket": normalize_identifier(photo.storage_bucket),
        "sha256": normalize_identifier(photo.sha256),
        "content_type": normalize_identifier(photo.content_type),
    }


def _photo_response(photo: Photo | CollectorPhoto | Mapping[str, object] | None) -> dict[str, object] | None:
    if photo is None:
        return None
    payload = {
        "id": str(_photo_value(photo, "id") or ""),
        "image_url": normalize_identifier(_photo_value(photo, "image_url")),
        "object_key": normalize_identifier(_photo_value(photo, "object_key")),
        "storage_type": normalize_identifier(_photo_value(photo, "storage_type")),
        "storage_key": normalize_identifier(_photo_value(photo, "storage_key")),
        "storage_bucket": normalize_identifier(_photo_value(photo, "storage_bucket")),
        "sha256": normalize_identifier(_photo_value(photo, "sha256")),
        "content_type": normalize_identifier(_photo_value(photo, "content_type")),
    }
    return resolve_photo_for_response(payload)


def _is_manual_requirement(requirement: CollectorRequirement) -> bool:
    for diagnostic in requirement.diagnostics or []:
        if (
            isinstance(diagnostic, Mapping)
            and normalize_identifier(diagnostic.get("code"))
            == _MANUAL_DEMAND_DIAGNOSTIC_CODE
        ):
            return True
    return False


def _collector_requirement_label(requirement: CollectorRequirement) -> str:
    return (
        _MANUAL_DEMAND_LABEL
        if _is_manual_requirement(requirement)
        else requirement.original_collector_no
    )


def _snapshot_has_photo_evidence(snapshot: object) -> bool:
    if not isinstance(snapshot, Mapping):
        return False
    return bool(
        normalize_identifier(snapshot.get("id"))
        and normalize_identifier(
            snapshot.get("storage_key")
            or snapshot.get("object_key")
            or snapshot.get("image_url")
        )
    )


def _projection_source_revision(
    *,
    project_id: UUID,
    terminal_code: str,
    projection: MeterSourceProjection,
    photos: Iterable[_ProjectPhotoRow],
) -> str:
    photos_by_id = {str(photo.id): photo for photo in photos}
    revision_rows: list[dict[str, object]] = []
    for source in projection.sources:
        revision_rows.append(
            {
                "project_id": str(project_id),
                "terminal_code": normalize_identifier(terminal_code),
                "installation_address": normalize_identifier(
                    source.installation_address
                ),
                "group_id": source.group_id,
                "meter_no": source.meter_no,
                "module_no": source.module_no,
                "collector_no": source.collector_no,
                "module_meter_photo": _photo_snapshot(
                    photos_by_id.get(
                        normalize_identifier(source.module_meter_photo_id)
                    )
                ),
                "after_box_photo": _photo_snapshot(
                    photos_by_id.get(normalize_identifier(source.after_box_photo_id))
                ),
            }
        )
    return terminal_source_revision(revision_rows)


class PostgresCollectorTransferService:
    """Transactional collector-transfer use cases scoped to one authenticated team."""

    def __init__(self, *, session: Session, team_id: str, actor: str) -> None:
        self.session = session
        self.team_id = normalize_identifier(team_id)
        self.actor = normalize_identifier(actor) or "admin"
        if not self.team_id:
            raise ValueError("team_id is required")

    def _run(self, run_id: str, *, lock: bool = False) -> CollectorTransferRun:
        query = select(CollectorTransferRun).where(
            CollectorTransferRun.id == _uuid(run_id, "run_id"),
            CollectorTransferRun.team_id == self.team_id,
        )
        if lock:
            query = query.with_for_update()
        record = self.session.scalar(query)
        if record is None:
            raise KeyError(run_id)
        return record

    def _actor_user_id(self) -> UUID | None:
        return self.session.scalar(
            select(User.id).where(
                User.team_id == self.team_id,
                User.username == self.actor,
            )
        )

    def _project(self, project_id: str) -> Project:
        project = self.session.scalar(
            select(Project).where(
                Project.id == _uuid(project_id, "project_id"),
                Project.team_id == self.team_id,
                Project.status != ProjectStatus.ARCHIVED,
                Project.archived_at.is_(None),
            )
        )
        if project is None:
            raise KeyError(project_id)
        return project

    def _project_meter_projection(
        self,
        project_id: UUID,
    ) -> tuple[MeterSourceProjection, list[_ProjectPhotoRow]]:
        group_statement = (
            select(
                MaterialGroup.id,
                MaterialGroup.legacy_id,
                MaterialGroup.status,
                MaterialGroup.terminal,
                MaterialGroup.display_meter_no,
                MaterialGroup.installation_address,
                MaterialGroup.photo_count,
                MaterialGroup.exception_note,
                MaterialGroup.raw_data,
            )
            .where(
                MaterialGroup.project_id == project_id,
                MaterialGroup.team_id == self.team_id,
            )
            .order_by(MaterialGroup.terminal, MaterialGroup.display_meter_no, MaterialGroup.id)
            .execution_options(yield_per=1_000)
        )
        groups = [
            _ProjectGroupRow(*row)
            for row in self.session.execute(group_statement).tuples()
        ]
        photo_statement = (
            select(
                Photo.id,
                Photo.legacy_id,
                Photo.group_id,
                Photo.collector,
                Photo.asset_no,
                Photo.category,
                Photo.sort_order,
                Photo.is_active,
                Photo.image_url,
                Photo.object_key,
                Photo.storage_type,
                Photo.storage_key,
                Photo.storage_bucket,
                Photo.sha256,
                Photo.content_type,
            )
            .join(MaterialGroup, Photo.group_id == MaterialGroup.id)
            .where(
                MaterialGroup.team_id == self.team_id,
                MaterialGroup.project_id == project_id,
                Photo.team_id == self.team_id,
                Photo.is_active.is_(True),
            )
            .order_by(Photo.group_id, Photo.sort_order, Photo.id)
            .execution_options(yield_per=1_000)
        )
        photos = [
            _ProjectPhotoRow(*row)
            for row in self.session.execute(photo_statement).tuples()
        ]
        return meter_sources_from_groups(groups, photos), photos

    def _global_terminal_projection(
        self,
        *,
        project_id: UUID,
        terminal_code: str,
    ) -> tuple[MeterSourceProjection, list[_ProjectPhotoRow]]:
        normalized_code = normalize_identifier(terminal_code)
        if not normalized_code:
            raise ValueError("terminal_code is required")
        normalized_terminal = _sql_identifier_strip(
            func.coalesce(MaterialGroup.terminal, "")
        )
        authoritative_address = func.coalesce(
            func.nullif(
                _sql_identifier_strip(
                    func.coalesce(TotalCatalogRow.installation_address, "")
                ),
                "",
            ),
            _sql_identifier_strip(
                func.coalesce(MaterialGroup.installation_address, "")
            ),
        )
        source_predicates = (
            MaterialGroup.team_id == self.team_id,
            MaterialGroup.project_id == project_id,
            normalized_terminal == normalized_code,
        )
        groups = [
            _ProjectGroupRow(*row)
            for row in self.session.execute(
                select(
                    MaterialGroup.id,
                    MaterialGroup.legacy_id,
                    MaterialGroup.status,
                    normalized_terminal,
                    MaterialGroup.display_meter_no,
                    authoritative_address,
                    MaterialGroup.photo_count,
                    MaterialGroup.exception_note,
                    MaterialGroup.raw_data,
                )
                .outerjoin(
                    TotalCatalogRow,
                    and_(
                        TotalCatalogRow.id == MaterialGroup.total_catalog_row_id,
                        TotalCatalogRow.project_id == MaterialGroup.project_id,
                        or_(
                            TotalCatalogRow.team_id == self.team_id,
                            TotalCatalogRow.team_id.is_(None),
                        ),
                    ),
                )
                .where(*source_predicates)
                .order_by(
                    MaterialGroup.display_meter_no,
                    MaterialGroup.id,
                )
            ).tuples()
        ]
        if not groups:
            raise KeyError(normalized_code)
        photos = [
            _ProjectPhotoRow(*row)
            for row in self.session.execute(
                select(
                    Photo.id,
                    Photo.legacy_id,
                    Photo.group_id,
                    Photo.collector,
                    Photo.asset_no,
                    Photo.category,
                    Photo.sort_order,
                    Photo.is_active,
                    Photo.image_url,
                    Photo.object_key,
                    Photo.storage_type,
                    Photo.storage_key,
                    Photo.storage_bucket,
                    Photo.sha256,
                    Photo.content_type,
                )
                .join(MaterialGroup, Photo.group_id == MaterialGroup.id)
                .where(
                    *source_predicates,
                    Photo.team_id == self.team_id,
                    Photo.is_active.is_(True),
                )
                .order_by(Photo.group_id, Photo.sort_order, Photo.id)
            ).tuples()
        ]
        return (
            _with_terminal_address_diagnostics(
                meter_sources_from_groups(groups, photos)
            ),
            photos,
        )

    def _barcode_verifications_for_groups(
        self,
        group_ids: Sequence[UUID],
        *,
        lock_rows: bool = False,
    ) -> dict[UUID, Mapping[str, object]]:
        if not group_ids:
            return {}
        statement = select(
                GroupBarcodeVerification.group_id,
                GroupBarcodeVerification.status,
                GroupBarcodeVerification.evidence_fingerprint,
                GroupBarcodeVerification.evidence_version,
                GroupBarcodeVerification.meter_matched,
                GroupBarcodeVerification.module_matched,
                GroupBarcodeVerification.collector_matched,
                GroupBarcodeVerification.recognition_source,
                GroupBarcodeVerification.attempt_count,
                GroupBarcodeVerification.invalidation_reason,
                GroupBarcodeVerification.invalidated_by,
                GroupBarcodeVerification.invalidated_at,
                GroupBarcodeVerification.auto_archive_status,
                GroupBarcodeVerification.auto_archived_at,
                GroupBarcodeVerification.auto_archive_error,
                GroupBarcodeVerification.updated_at,
            ).where(
                GroupBarcodeVerification.team_id == self.team_id,
                GroupBarcodeVerification.group_id.in_(tuple(group_ids)),
            )
        if lock_rows:
            statement = statement.with_for_update()
        rows = self.session.execute(statement).mappings()
        return {
            row["group_id"]: dict(row)
            for row in rows
        }

    def _terminal_review_bundle(
        self,
        *,
        project_id: UUID,
        terminal_code: str,
        lock_groups: bool = False,
    ) -> _TerminalReviewBundle:
        normalized_code = normalize_identifier(terminal_code)
        if not normalized_code:
            raise ValueError("terminal_code is required")
        normalized_terminal = _sql_identifier_strip(
            func.coalesce(MaterialGroup.terminal, "")
        )
        authoritative_address = func.coalesce(
            func.nullif(
                _sql_identifier_strip(
                    func.coalesce(TotalCatalogRow.installation_address, "")
                ),
                "",
            ),
            _sql_identifier_strip(
                func.coalesce(MaterialGroup.installation_address, "")
            ),
        )
        predicates = (
            MaterialGroup.team_id == self.team_id,
            MaterialGroup.project_id == project_id,
            normalized_terminal == normalized_code,
        )
        if lock_groups:
            locked_group_rows = list(
                self.session.execute(
                    select(
                        MaterialGroup.id,
                        MaterialGroup.total_catalog_row_id,
                    )
                    .where(*predicates)
                    .order_by(MaterialGroup.display_meter_no, MaterialGroup.id)
                    .with_for_update(of=MaterialGroup)
                ).tuples()
            )
            if not locked_group_rows:
                raise TerminalNotFoundError(normalized_code)
            catalog_row_ids = sorted(
                {
                    row.total_catalog_row_id
                    for row in locked_group_rows
                    if row.total_catalog_row_id is not None
                }
            )
            if catalog_row_ids:
                self.session.execute(
                    select(TotalCatalogRow.id)
                    .where(
                        TotalCatalogRow.id.in_(catalog_row_ids),
                        TotalCatalogRow.project_id == project_id,
                        or_(
                            TotalCatalogRow.team_id == self.team_id,
                            TotalCatalogRow.team_id.is_(None),
                        ),
                    )
                    .order_by(TotalCatalogRow.id)
                    .with_for_update(of=TotalCatalogRow)
                ).all()
        group_statement = (
            select(
                MaterialGroup.id,
                MaterialGroup.legacy_id,
                MaterialGroup.status,
                normalized_terminal,
                MaterialGroup.display_meter_no,
                authoritative_address,
                MaterialGroup.photo_count,
                MaterialGroup.exception_note,
                MaterialGroup.raw_data,
            )
            .outerjoin(
                TotalCatalogRow,
                and_(
                    TotalCatalogRow.id == MaterialGroup.total_catalog_row_id,
                    TotalCatalogRow.project_id == MaterialGroup.project_id,
                    or_(
                        TotalCatalogRow.team_id == self.team_id,
                        TotalCatalogRow.team_id.is_(None),
                    ),
                ),
            )
            .where(*predicates)
            .order_by(MaterialGroup.display_meter_no, MaterialGroup.id)
        )
        groups = [
            _ProjectGroupRow(*row)
            for row in self.session.execute(group_statement).tuples()
        ]
        if not groups:
            raise TerminalNotFoundError(normalized_code)
        photo_statement = (
            select(
                Photo.id,
                Photo.legacy_id,
                Photo.group_id,
                Photo.collector,
                Photo.asset_no,
                Photo.category,
                Photo.sort_order,
                Photo.is_active,
                Photo.image_url,
                Photo.object_key,
                Photo.storage_type,
                Photo.storage_key,
                Photo.storage_bucket,
                Photo.sha256,
                Photo.content_type,
            )
            .join(MaterialGroup, Photo.group_id == MaterialGroup.id)
            .where(
                *predicates,
                Photo.team_id == self.team_id,
                Photo.is_active.is_(True),
            )
            .order_by(Photo.group_id, Photo.sort_order, Photo.id)
        )
        if lock_groups:
            photo_statement = photo_statement.with_for_update(of=Photo)
        photos = tuple(
            _ProjectPhotoRow(*row)
            for row in self.session.execute(photo_statement).tuples()
        )
        verification_by_group = self._barcode_verifications_for_groups(
            [group.id for group in groups],
            lock_rows=lock_groups,
        )
        projection, review_rows = _review_projection_from_rows(
            groups,
            photos,
            verification_by_group,
        )
        return _TerminalReviewBundle(
            project_id=project_id,
            terminal_code=normalized_code,
            projection=projection,
            photos=photos,
            review_rows=review_rows,
        )

    def _require_terminal_rephoto_ready(
        self,
        *,
        run: CollectorTransferRun,
        terminal: CollectorTransferTerminal,
        client_source_revision: str = "",
    ) -> TerminalReviewProjection:
        bundle = self._terminal_review_bundle(
            project_id=run.project_id,
            terminal_code=terminal.terminal_code,
            lock_groups=True,
        )
        projection = bundle.projection
        if not projection.constructed_meters:
            raise TerminalNoConstructedMeterError(
                "terminal has no constructed meter"
            )
        if projection.hard_blocked:
            raise CollectorTerminalSourceBlockedError(
                "terminal source is blocked by current review evidence"
            )
        stored_revision = normalize_identifier(
            (run.stats or {}).get("source_revision")
        )
        requested_revision = normalize_identifier(client_source_revision)
        if (
            stored_revision != projection.source_revision
            or requested_revision
            and requested_revision != projection.source_revision
        ):
            raise TerminalSourceChangedError(
                "terminal source changed; refresh the snapshot first"
            )
        return projection

    def list_global_terminals(
        self,
        *,
        query: str = "",
        state: str | None = None,
        page: int = 1,
        page_size: int = 50,
        include_blocked: bool = False,
    ) -> dict[str, object]:
        normalized_state = normalize_identifier(state).lower() or None
        allowed_states = {
            "no_construction",
            "needs_review",
            "blocked",
            "needs_replacement",
            "pool_shortage",
            "ready",
            "in_progress",
            "completed",
        }
        if normalized_state is not None and normalized_state not in allowed_states:
            raise ValueError("state is invalid")
        bounded_page = max(1, int(page))
        bounded_page_size = min(100, max(1, int(page_size)))
        search_text = normalize_identifier(query)

        normalized_terminal = _sql_identifier_strip(func.coalesce(MaterialGroup.terminal, ""))
        authoritative_address = func.coalesce(
            func.nullif(
                _sql_identifier_strip(func.coalesce(TotalCatalogRow.installation_address, "")),
                "",
            ),
            _sql_identifier_strip(func.coalesce(MaterialGroup.installation_address, "")),
        )
        selected_photo_collector = (
            select(_sql_identifier_strip(Photo.collector))
            .where(
                Photo.group_id == MaterialGroup.id,
                Photo.team_id == self.team_id,
                Photo.is_active.is_(True),
                _sql_identifier_strip(func.coalesce(Photo.collector, "")) != "",
            )
            .order_by(Photo.sort_order, Photo.id)
            .limit(1)
            .correlate(MaterialGroup)
            .scalar_subquery()
        )
        raw_collector = func.coalesce(
            *(
                func.nullif(
                    _sql_identifier_strip(
                        MaterialGroup.raw_data[key].as_string()
                    ),
                    "",
                )
                for key in (
                    "collector",
                    "采集器",
                    "采集器号",
                    "construction_collector",
                )
            ),
            "",
        )
        effective_collector = func.coalesce(
            selected_photo_collector,
            raw_collector,
        )
        selected_module_asset = (
            select(_sql_identifier_strip(func.coalesce(Photo.asset_no, "")))
            .where(
                Photo.group_id == MaterialGroup.id,
                Photo.team_id == self.team_id,
                Photo.is_active.is_(True),
                Photo.category == "module_meter",
            )
            .order_by(Photo.sort_order, Photo.id)
            .limit(1)
            .correlate(MaterialGroup)
            .scalar_subquery()
        )
        raw_module = func.coalesce(
            *(
                func.nullif(
                    _sql_identifier_strip(
                        MaterialGroup.raw_data[key].as_string()
                    ),
                    "",
                )
                for key in (
                    "module_asset_no",
                    "模块资产编号",
                    "模块号",
                    "construction_module_asset_no",
                )
            ),
            "",
        )
        effective_module = func.coalesce(
            func.nullif(selected_module_asset, ""),
            raw_module,
        )
        has_module_meter_photo = exists().where(
            Photo.group_id == MaterialGroup.id,
            Photo.team_id == self.team_id,
            Photo.is_active.is_(True),
            Photo.category == "module_meter",
        )
        has_after_box_photo = exists().where(
            Photo.group_id == MaterialGroup.id,
            Photo.team_id == self.team_id,
            Photo.is_active.is_(True),
            Photo.category == "after_box",
        )
        complete_source = and_(
            _sql_identifier_strip(
                func.coalesce(MaterialGroup.display_meter_no, "")
            )
            != "",
            effective_collector != "",
            effective_module != "",
            has_module_meter_photo,
            has_after_box_photo,
            authoritative_address != "",
        )
        active_project_predicates = (
            Project.team_id == self.team_id,
            Project.status == ProjectStatus.ACTIVE,
            Project.archived_at.is_(None),
        )
        identity_statement = (
            select(
                Project.id.label("project_id"),
                Project.code.label("project_code"),
                Project.name.label("project_name"),
                normalized_terminal.label("terminal_code"),
            )
            .join(MaterialGroup, MaterialGroup.project_id == Project.id)
            .outerjoin(
                TotalCatalogRow,
                and_(
                    TotalCatalogRow.id == MaterialGroup.total_catalog_row_id,
                    TotalCatalogRow.project_id == MaterialGroup.project_id,
                    or_(
                        TotalCatalogRow.team_id == self.team_id,
                        TotalCatalogRow.team_id.is_(None),
                    ),
                ),
            )
            .where(
                *active_project_predicates,
                MaterialGroup.team_id == self.team_id,
                normalized_terminal != "",
            )
        )
        grouped_identity = identity_statement.group_by(
            Project.id,
            Project.code,
            Project.name,
            normalized_terminal,
        )
        has_any_active_photo = exists().where(
            Photo.group_id == MaterialGroup.id,
            Photo.team_id == self.team_id,
            Photo.is_active.is_(True),
        )
        constructed_missing_address_count = func.sum(
            case(
                (
                    and_(
                        or_(
                            func.coalesce(MaterialGroup.photo_count, 0) > 0,
                            has_any_active_photo,
                        ),
                        authoritative_address == "",
                    ),
                    1,
                ),
                else_=0,
            )
        )
        if search_text:
            pattern = f"%{search_text}%"
            grouped_identity = grouped_identity.having(
                func.sum(
                    case(
                        (
                            or_(
                                normalized_terminal.ilike(pattern),
                                authoritative_address.ilike(pattern),
                                MaterialGroup.legacy_id.ilike(pattern),
                            ),
                            1,
                        ),
                        else_=0,
                    )
                )
                > 0
            )
        if not include_blocked and normalized_state != "blocked":
            grouped_identity = grouped_identity.having(
                constructed_missing_address_count == 0,
            )
        identity_subquery = grouped_identity.subquery()

        duplicate_counts = (
            select(
                normalized_terminal.label("terminal_code"),
                func.count(func.distinct(Project.id)).label("project_count"),
            )
            .join(MaterialGroup, MaterialGroup.project_id == Project.id)
            .where(
                *active_project_predicates,
                MaterialGroup.team_id == self.team_id,
                normalized_terminal != "",
            )
            .group_by(normalized_terminal)
            .subquery()
        )
        total = int(
            self.session.scalar(select(func.count()).select_from(identity_subquery))
            or 0
        )
        identity_rows = self.session.execute(
            select(
                identity_subquery.c.project_id,
                identity_subquery.c.project_code,
                identity_subquery.c.project_name,
                identity_subquery.c.terminal_code,
                duplicate_counts.c.project_count,
            )
            .join(
                duplicate_counts,
                duplicate_counts.c.terminal_code == identity_subquery.c.terminal_code,
            )
            .order_by(
                identity_subquery.c.terminal_code,
                identity_subquery.c.project_name,
                identity_subquery.c.project_code,
                identity_subquery.c.project_id,
            )
            .offset((bounded_page - 1) * bounded_page_size)
            .limit(bounded_page_size)
        ).mappings().all()
        if not identity_rows:
            return {
                "items": [],
                "page": bounded_page,
                "page_size": bounded_page_size,
                "total": total,
            }

        candidate_keys = [
            (row["project_id"], normalize_identifier(row["terminal_code"]))
            for row in identity_rows
        ]
        source_key_predicate = or_(
            *(
                and_(
                    MaterialGroup.project_id == project_id,
                    normalized_terminal == terminal_code,
                )
                for project_id, terminal_code in candidate_keys
            )
        )
        group_rows = [
            _GlobalTerminalGroupRow(*row)
            for row in self.session.execute(
                select(
                    MaterialGroup.project_id,
                    MaterialGroup.id,
                    MaterialGroup.legacy_id,
                    MaterialGroup.status,
                    normalized_terminal,
                    MaterialGroup.display_meter_no,
                    authoritative_address,
                    MaterialGroup.photo_count,
                    MaterialGroup.exception_note,
                    MaterialGroup.raw_data,
                )
                .outerjoin(
                    TotalCatalogRow,
                    and_(
                        TotalCatalogRow.id == MaterialGroup.total_catalog_row_id,
                        TotalCatalogRow.project_id == MaterialGroup.project_id,
                        or_(
                            TotalCatalogRow.team_id == self.team_id,
                            TotalCatalogRow.team_id.is_(None),
                        ),
                    ),
                )
                .where(
                    MaterialGroup.team_id == self.team_id,
                    source_key_predicate,
                )
                .order_by(
                    MaterialGroup.project_id,
                    normalized_terminal,
                    MaterialGroup.display_meter_no,
                    MaterialGroup.id,
                )
            ).tuples()
        ]
        photo_rows = [
            _ProjectPhotoRow(*row)
            for row in self.session.execute(
                select(
                    Photo.id,
                    Photo.legacy_id,
                    Photo.group_id,
                    Photo.collector,
                    Photo.asset_no,
                    Photo.category,
                    Photo.sort_order,
                    Photo.is_active,
                    Photo.image_url,
                    Photo.object_key,
                    Photo.storage_type,
                    Photo.storage_key,
                    Photo.storage_bucket,
                    Photo.sha256,
                    Photo.content_type,
                )
                .join(MaterialGroup, Photo.group_id == MaterialGroup.id)
                .where(
                    MaterialGroup.team_id == self.team_id,
                    Photo.team_id == self.team_id,
                    Photo.is_active.is_(True),
                    source_key_predicate,
                )
                .order_by(
                    MaterialGroup.project_id,
                    normalized_terminal,
                    Photo.group_id,
                    Photo.sort_order,
                    Photo.id,
                )
            ).tuples()
        ]

        groups_by_key: dict[tuple[UUID, str], list[_GlobalTerminalGroupRow]] = defaultdict(list)
        group_key_by_id: dict[UUID, tuple[UUID, str]] = {}
        for group in group_rows:
            key = (group.project_id, normalize_identifier(group.terminal))
            groups_by_key[key].append(group)
            group_key_by_id[group.id] = key
        photos_by_key: dict[tuple[UUID, str], list[_ProjectPhotoRow]] = defaultdict(list)
        for photo in photo_rows:
            key = group_key_by_id.get(photo.group_id)
            if key is not None:
                photos_by_key[key].append(photo)

        verification_by_group = self._barcode_verifications_for_groups(
            [group.id for group in group_rows]
        )

        source_payloads: dict[tuple[UUID, str], dict[str, object]] = {}
        collector_pairs: list[tuple[UUID, str]] = []
        for key in candidate_keys:
            legacy_projection = _with_terminal_address_diagnostics(
                meter_sources_from_groups(
                    groups_by_key.get(key, ()),
                    photos_by_key.get(key, ()),
                )
            )
            projection, review_rows = _review_projection_from_rows(
                groups_by_key.get(key, ()),
                photos_by_key.get(key, ()),
                verification_by_group,
            )
            requirements = tuple(
                normalize_identifier(item.original_collector_no)
                for item in projection.collector_requirements
            )
            collector_pairs.extend((key[0], collector_no) for collector_no in requirements)
            source_payloads[key] = {
                "projection": projection,
                "review_rows": review_rows,
                "requirements": requirements,
                "diagnostics": legacy_projection.diagnostics,
            }

        direct_claims: dict[tuple[UUID, str], set[str]] = defaultdict(set)
        for chunk_start in range(0, len(collector_pairs), 400):
            chunk = collector_pairs[chunk_start : chunk_start + 400]
            if not chunk:
                continue
            for project_id, collector_no in self.session.execute(
                select(
                    PhysicalCollector.project_id,
                    PhysicalCollector.collector_no,
                ).where(
                    PhysicalCollector.team_id == self.team_id,
                    PhysicalCollector.pool_status == "direct",
                    _public_collector_number_clause(),
                    or_(
                        *(
                            and_(
                                PhysicalCollector.project_id == project_id,
                                PhysicalCollector.collector_no == collector_no,
                            )
                            for project_id, collector_no in chunk
                        )
                    ),
                )
            ).tuples():
                direct_claims[(project_id, collector_no)].add(collector_no)

        project_ids = sorted({project_id for project_id, _terminal_code in candidate_keys}, key=str)
        pool_counts = {
            project_id: int(available_count)
            for project_id, available_count in self.session.execute(
                select(
                    PhysicalCollector.project_id,
                    func.count(func.distinct(PhysicalCollector.id)),
                )
                .join(
                    CollectorPhoto,
                    and_(
                        CollectorPhoto.physical_collector_id == PhysicalCollector.id,
                        CollectorPhoto.team_id == self.team_id,
                        CollectorPhoto.is_active.is_(True),
                    ),
                )
                .where(
                    PhysicalCollector.team_id == self.team_id,
                    PhysicalCollector.project_id.in_(project_ids),
                    PhysicalCollector.pool_status == "available",
                    _public_collector_number_clause(),
                )
                .group_by(PhysicalCollector.project_id)
            ).tuples()
        }

        hidden_key_predicate = or_(
            *(
                and_(
                    CollectorTransferRun.project_id == project_id,
                    _sql_identifier_strip(CollectorTransferTerminal.terminal_code)
                    == terminal_code,
                )
                for project_id, terminal_code in candidate_keys
            )
        )
        progressed_claims: dict[tuple[UUID, str], set[str]] = defaultdict(set)
        assignment_rows = self.session.execute(
            select(
                CollectorTransferRun.project_id,
                CollectorTransferTerminal.terminal_code,
                CollectorRequirement.original_collector_no,
                CollectorTransferRun.stats,
            )
            .join(
                CollectorRequirement,
                CollectorRequirement.run_id == CollectorTransferRun.id,
            )
            .join(
                CollectorTransferTerminal,
                CollectorTransferTerminal.id == CollectorRequirement.terminal_id,
            )
            .join(
                CollectorAssignment,
                CollectorAssignment.requirement_id == CollectorRequirement.id,
            )
            .where(
                CollectorTransferRun.team_id == self.team_id,
                CollectorAssignment.status.in_(("reserved", "used")),
                hidden_key_predicate,
            )
        ).tuples()
        direct_item_rows = self.session.execute(
            select(
                CollectorTransferRun.project_id,
                CollectorTransferTerminal.terminal_code,
                CollectorRequirement.original_collector_no,
                CollectorTransferRun.stats,
            )
            .join(
                CollectorRequirement,
                CollectorRequirement.run_id == CollectorTransferRun.id,
            )
            .join(
                CollectorTransferTerminal,
                CollectorTransferTerminal.id == CollectorRequirement.terminal_id,
            )
            .join(
                CollectorWorkbenchItem,
                CollectorWorkbenchItem.requirement_id == CollectorRequirement.id,
            )
            .where(
                CollectorTransferRun.team_id == self.team_id,
                CollectorWorkbenchItem.assignment_id.is_(None),
                CollectorRequirement.status.in_(("direct_ready", "used")),
                hidden_key_predicate,
            )
        ).tuples()
        for project_id, terminal_code, collector_no, stats in (
            *assignment_rows,
            *direct_item_rows,
        ):
            metadata = stats if isinstance(stats, Mapping) else {}
            if metadata.get("workflow_kind") != "global_terminal_workbench":
                continue
            if bool(metadata.get("superseded")):
                continue
            progressed_claims[
                (project_id, normalize_identifier(terminal_code))
            ].add(normalize_identifier(collector_no))

        items: list[dict[str, object]] = []
        for identity in identity_rows:
            project_id = identity["project_id"]
            terminal_code = normalize_identifier(identity["terminal_code"])
            key = (project_id, terminal_code)
            payload = source_payloads[key]
            projection = payload["projection"]
            review_rows = tuple(payload["review_rows"])
            requirements = tuple(payload["requirements"])
            addresses = sorted(
                {
                    normalize_identifier(source.installation_address)
                    for source in (
                        item.source
                        for item in projection.constructed_meters
                        if item.source is not None
                    )
                    if normalize_identifier(source.installation_address)
                }
            )
            diagnostics = list(payload["diagnostics"])

            claimed_numbers = set(progressed_claims.get(key, set()))
            for original_collector_no in requirements:
                if direct_claims.get((project_id, original_collector_no)):
                    claimed_numbers.add(original_collector_no)
            physical_count = len(set(requirements) & claimed_numbers)
            missing_count = max(0, len(requirements) - physical_count)
            pool_available_count = pool_counts.get(project_id, 0)
            workflow_state = derive_terminal_workflow_state(
                projection,
                missing_collector_count=missing_count,
                pool_available_count=pool_available_count,
                snapshot_state=(
                    "in_progress"
                    if progressed_claims.get(key)
                    else None
                ),
            )

            candidate = {
                "terminal_key": terminal_key(str(project_id), terminal_code),
                "project_id": str(project_id),
                "project_name": normalize_identifier(identity["project_name"]),
                "project_code": normalize_identifier(identity["project_code"]),
                "terminal_code": terminal_code,
                "installation_address": "、".join(addresses),
                "needs_disambiguation": int(identity["project_count"] or 0) > 1,
                "meter_count": len(projection.constructed_meters),
                "collector_count": len(requirements),
                "physical_count": physical_count,
                "missing_count": missing_count,
                "pool_available_count": pool_available_count,
                "workflow_state": workflow_state,
                "selectable": workflow_state != "blocked",
                "source_revision": projection.source_revision,
                "constructed_meter_count": len(projection.constructed_meters),
                "unconstructed_meter_count": len(projection.unconstructed_meters),
                "review_ready_count": projection.review_ready_count,
                "review_required_count": projection.review_required_count,
                "diagnostics": diagnostics,
            }
            if normalized_state is not None and workflow_state != normalized_state:
                continue
            if workflow_state == "blocked" and not include_blocked:
                continue
            items.append(candidate)

        return {
            "items": items,
            "page": bounded_page,
            "page_size": bounded_page_size,
            "total": total,
        }

    def _project_has_collector_number(self, project_id: UUID, collector_no: str) -> bool:
        stripped_photo_collector = _sql_identifier_strip(Photo.collector)
        photo_collector = (
            select(stripped_photo_collector)
            .where(
                Photo.group_id == MaterialGroup.id,
                Photo.team_id == self.team_id,
                Photo.is_active.is_(True),
                _sql_identifier_strip(func.coalesce(Photo.collector, "")) != "",
            )
            .order_by(Photo.sort_order, Photo.id)
            .limit(1)
            .correlate(MaterialGroup)
            .scalar_subquery()
        )
        raw_collector = func.coalesce(
            *(
                func.nullif(
                    _sql_identifier_strip(MaterialGroup.raw_data[key].as_string()),
                    "",
                )
                for key in ("collector", "采集器", "采集器号", "construction_collector")
            ),
            "",
        )
        effective_collector = func.coalesce(photo_collector, raw_collector)
        return bool(
            self.session.scalar(
                select(
                    exists().where(
                        MaterialGroup.team_id == self.team_id,
                        MaterialGroup.project_id == project_id,
                        effective_collector == collector_no,
                    )
                )
            )
        )

    def _audit(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: UUID | None,
        project_id: UUID | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        self.session.add(
            AuditLog(
                team_id=self.team_id,
                actor_username=self.actor,
                project_id=project_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                payload=payload or {},
            )
        )

    def _run_summary(self, run: CollectorTransferRun) -> dict[str, object]:
        return {
            "id": str(run.id),
            "project_id": str(run.project_id),
            "name": run.name,
            "status": run.status,
            **dict(run.stats or {}),
            "diagnostics": list(run.diagnostics or []),
            "created_at": run.created_at.isoformat() if run.created_at else None,
        }

    def _refresh_allocation_stats(self, run: CollectorTransferRun) -> dict[str, int]:
        self.session.flush()
        active_assignment_count = int(
            self.session.scalar(
                select(func.count(CollectorAssignment.id)).where(
                    CollectorAssignment.run_id == run.id,
                    CollectorAssignment.status.in_(("reserved", "used")),
                )
            )
            or 0
        )
        direct_match_count = int(
            self.session.scalar(
                select(func.count(CollectorAssignment.id)).where(
                    CollectorAssignment.run_id == run.id,
                    CollectorAssignment.assignment_mode == "direct",
                    CollectorAssignment.status.in_(("reserved", "used")),
                )
            )
            or 0
        )
        direct_workbench_count = int(
            self.session.scalar(
                select(func.count(CollectorWorkbenchItem.id))
                .join(
                    CollectorRequirement,
                    CollectorRequirement.id == CollectorWorkbenchItem.requirement_id,
                )
                .where(
                    CollectorWorkbenchItem.run_id == run.id,
                    CollectorWorkbenchItem.item_kind == "collector_removal",
                    CollectorWorkbenchItem.assignment_id.is_(None),
                    CollectorRequirement.status.in_(("direct_ready", "used")),
                )
            )
            or 0
        )
        direct_match_count += direct_workbench_count
        random_match_count = int(
            self.session.scalar(
                select(func.count(CollectorAssignment.id)).where(
                    CollectorAssignment.run_id == run.id,
                    CollectorAssignment.assignment_mode == "random",
                    CollectorAssignment.status.in_(("reserved", "used")),
                )
            )
            or 0
        )
        available_pool_count = int(
            self.session.scalar(
                select(func.count(PhysicalCollector.id)).where(
                    PhysicalCollector.team_id == self.team_id,
                    PhysicalCollector.project_id == run.project_id,
                    PhysicalCollector.pool_status == "available",
                    _public_collector_number_clause(),
                )
            )
            or 0
        )
        stats = dict(run.stats or {})
        stats["assignment_count"] = active_assignment_count
        stats["active_assignment_count"] = active_assignment_count
        stats["direct_match_count"] = direct_match_count
        stats["random_match_count"] = random_match_count
        stats["pool_available_count"] = available_pool_count
        run.stats = stats
        return {
            "assignment_count": active_assignment_count,
            "active_assignment_count": active_assignment_count,
            "direct_match_count": direct_match_count,
            "random_match_count": random_match_count,
            "pool_available_count": available_pool_count,
        }

    def _refresh_terminal_item_progress(
        self,
        terminal: CollectorTransferTerminal,
        *,
        preserve_blocked: bool,
    ) -> tuple[int, int]:
        self.session.flush()
        total = int(
            self.session.scalar(
                select(func.count(CollectorWorkbenchItem.id)).where(
                    CollectorWorkbenchItem.run_id == terminal.run_id,
                    CollectorWorkbenchItem.terminal_id == terminal.id,
                    CollectorWorkbenchItem.team_id == self.team_id,
                )
            )
            or 0
        )
        completed_count = int(
            self.session.scalar(
                select(func.count(CollectorWorkbenchItem.id)).where(
                    CollectorWorkbenchItem.run_id == terminal.run_id,
                    CollectorWorkbenchItem.terminal_id == terminal.id,
                    CollectorWorkbenchItem.team_id == self.team_id,
                    CollectorWorkbenchItem.status == "completed",
                )
            )
            or 0
        )
        terminal.completed_item_count = completed_count
        if not preserve_blocked or terminal.status != "blocked":
            terminal.status = (
                "ready"
                if completed_count == 0
                else (
                    "completed"
                    if total and completed_count >= total
                    else "in_progress"
                )
            )
        return completed_count, total

    def _create_run_from_projection(
        self,
        *,
        project: Project,
        name: str,
        projection: MeterSourceProjection,
        source_photos_by_id: Mapping[str, _ProjectPhotoRow],
        stats_extra: Mapping[str, object] | None = None,
        bind_direct_inventory: bool = True,
    ) -> CollectorTransferRun:
        snapshots = build_terminal_snapshots(projection.sources)
        run = CollectorTransferRun(
            team_id=self.team_id,
            project_id=project.id,
            name=normalize_identifier(name) or "采集器盘点",
            status="inventory",
            diagnostics=list(projection.diagnostics),
            stats={},
            created_by_id=self._actor_user_id(),
        )
        self.session.add(run)
        self.session.flush()

        source_by_group = {source.group_id: source for source in projection.sources}
        diagnostics_by_group: dict[str, list[dict[str, str]]] = defaultdict(list)
        for diagnostic in projection.diagnostics:
            diagnostics_by_group[diagnostic["group_id"]].append(diagnostic)
        global_diagnostics = diagnostics_by_group.get("", [])

        requirement_count = 0
        blocked_terminal_count = 0
        for terminal_index, snapshot in enumerate(snapshots):
            terminal_diagnostics = [*global_diagnostics, *(
                diagnostic
                for meter_source in snapshot.meters
                for diagnostic in diagnostics_by_group.get(meter_source.group_id, [])
            )]
            terminal_status = "blocked" if terminal_diagnostics else "ready"
            if terminal_status == "blocked":
                blocked_terminal_count += 1
            terminal = CollectorTransferTerminal(
                run_id=run.id,
                team_id=self.team_id,
                terminal_code=snapshot.terminal_code,
                installation_address=snapshot.installation_address,
                status=terminal_status,
                meter_count=len(snapshot.meters),
                collector_requirement_count=len(snapshot.collector_requirements),
                diagnostics=terminal_diagnostics,
            )
            self.session.add(terminal)
            self.session.flush()

            meters_by_group: dict[str, CollectorMeterItem] = {}
            for meter_index, source in enumerate(snapshot.meters):
                source = source_by_group[source.group_id]
                meter_item = CollectorMeterItem(
                    run_id=run.id,
                    terminal_id=terminal.id,
                    team_id=self.team_id,
                    source_group_id=_uuid(source.group_id, "source_group_id"),
                    meter_no=source.meter_no,
                    meter_barcode=source.meter_no,
                    module_no=source.module_no,
                    module_barcode=source.module_no,
                    original_collector_no=source.collector_no,
                    module_meter_photo_id=(
                        _uuid(source.module_meter_photo_id, "module_meter_photo_id")
                        if source.module_meter_photo_id
                        else None
                    ),
                    after_box_photo_id=(
                        _uuid(source.after_box_photo_id, "after_box_photo_id")
                        if source.after_box_photo_id
                        else None
                    ),
                    module_meter_photo_snapshot=_photo_snapshot(
                        source_photos_by_id.get(source.module_meter_photo_id or "")
                    ),
                    after_box_photo_snapshot=_photo_snapshot(
                        source_photos_by_id.get(source.after_box_photo_id or "")
                    ),
                    sort_order=meter_index,
                    diagnostics=diagnostics_by_group.get(source.group_id, []),
                )
                self.session.add(meter_item)
                self.session.flush()
                meters_by_group[source.group_id] = meter_item
                self.session.add(
                    CollectorWorkbenchItem(
                        run_id=run.id,
                        terminal_id=terminal.id,
                        team_id=self.team_id,
                        item_kind="meter_install",
                        source_key=str(meter_item.id),
                        meter_item_id=meter_item.id,
                        status="pending",
                        sort_order=meter_index,
                    )
                )

            for requirement_index, snapshot_requirement in enumerate(snapshot.collector_requirements):
                requirement = CollectorRequirement(
                    run_id=run.id,
                    terminal_id=terminal.id,
                    team_id=self.team_id,
                    original_collector_no=snapshot_requirement.original_collector_no,
                    status="unmatched" if terminal_status != "blocked" else "blocked",
                    sort_order=requirement_index,
                    diagnostics=terminal_diagnostics,
                )
                self.session.add(requirement)
                self.session.flush()
                requirement_count += 1
                for group_id in snapshot_requirement.meter_group_ids:
                    self.session.add(
                        CollectorRequirementMeter(
                            requirement_id=requirement.id,
                            meter_item_id=meters_by_group[group_id].id,
                        )
                    )

        stats: dict[str, object] = {
            "terminal_count": len(snapshots),
            "meter_count": len(projection.sources),
            "collector_requirement_count": requirement_count,
            "blocked_terminal_count": blocked_terminal_count,
            "direct_match_count": 0,
            "pool_available_count": 0,
            "assignment_count": 0,
        }
        stats.update(dict(stats_extra or {}))
        run.stats = stats
        if bind_direct_inventory:
            self._bind_direct_inventory(run)
        self._refresh_allocation_stats(run)
        return run

    def create_run(self, *, project_id: str, name: str) -> dict[str, object]:
        project = self._project(project_id)
        projection, photos = self._project_meter_projection(project.id)
        run = self._create_run_from_projection(
            project=project,
            name=name,
            projection=projection,
            source_photos_by_id={str(photo.id): photo for photo in photos},
        )
        self._audit(
            action="collector_transfer.run_created",
            entity_type="collector_transfer_run",
            entity_id=run.id,
            project_id=project.id,
            payload=dict(run.stats),
        )
        self.session.commit()
        self.session.refresh(run)
        return self._run_summary(run)

    def _lock_global_terminal_identity(
        self,
        *,
        project_id: UUID,
        terminal_code: str,
    ) -> None:
        bind = self.session.get_bind()
        if bind.dialect.name != "postgresql":
            return
        lock_material = (
            f"{self.team_id}\x1f{project_id}\x1f{normalize_identifier(terminal_code)}"
        ).encode("utf-8")
        lock_id = int.from_bytes(
            hashlib.sha256(lock_material).digest()[:8],
            byteorder="big",
            signed=True,
        )
        self.session.execute(select(func.pg_advisory_xact_lock(lock_id)))

    def _active_global_terminal_run(
        self,
        *,
        project_id: UUID,
        terminal_code: str,
    ) -> CollectorTransferRun | None:
        workflow_kind = CollectorTransferRun.stats["workflow_kind"].as_string()
        source_terminal_code = CollectorTransferRun.stats[
            "source_terminal_code"
        ].as_string()
        superseded = CollectorTransferRun.stats["superseded"].as_boolean()
        return self.session.scalar(
            select(CollectorTransferRun)
            .where(
                CollectorTransferRun.team_id == self.team_id,
                CollectorTransferRun.project_id == project_id,
                workflow_kind == "global_terminal_workbench",
                source_terminal_code == normalize_identifier(terminal_code),
                or_(superseded.is_(None), superseded.is_(False)),
            )
            .order_by(
                CollectorTransferRun.created_at.desc(),
                CollectorTransferRun.id.desc(),
            )
            .limit(1)
        )

    def _global_run_has_progress(self, run: CollectorTransferRun) -> bool:
        completed_count = int(
            self.session.scalar(
                select(func.count(CollectorWorkbenchItem.id)).where(
                    CollectorWorkbenchItem.run_id == run.id,
                    CollectorWorkbenchItem.status == "completed",
                )
            )
            or 0
        )
        active_assignment_count = int(
            self.session.scalar(
                select(func.count(CollectorAssignment.id)).where(
                    CollectorAssignment.run_id == run.id,
                    CollectorAssignment.status.in_(("reserved", "used")),
                )
            )
            or 0
        )
        return completed_count > 0 or active_assignment_count > 0

    def _global_terminal_open_result(
        self,
        *,
        run: CollectorTransferRun,
        snapshot_reused: bool,
        source_changed: bool,
        current_source_revision: str,
    ) -> dict[str, object]:
        terminal = self.session.scalar(
            select(CollectorTransferTerminal).where(
                CollectorTransferTerminal.run_id == run.id,
                CollectorTransferTerminal.team_id == self.team_id,
            )
        )
        if terminal is None:
            raise KeyError(str(run.id))
        stats = dict(run.stats or {})
        return {
            "run_id": str(run.id),
            "terminal_id": str(terminal.id),
            "workbench_terminal_id": str(terminal.id),
            "project_id": str(run.project_id),
            "terminal_code": terminal.terminal_code,
            "source_revision": normalize_identifier(stats.get("source_revision")),
            "current_source_revision": current_source_revision,
            "snapshot_reused": snapshot_reused,
            "source_changed": source_changed,
        }

    def open_global_terminal(
        self,
        *,
        project_id: str,
        terminal_code: str,
        source_revision: str = "",
        terminal_key_value: str = "",
        force_refresh: bool = False,
    ) -> dict[str, object]:
        project = self._project(project_id)
        normalized_code = normalize_identifier(terminal_code)
        if not normalized_code:
            raise ValueError("terminal_code is required")
        expected_key = terminal_key(str(project.id), normalized_code)
        supplied_key = normalize_identifier(terminal_key_value)
        if supplied_key and supplied_key != expected_key:
            raise ValueError("terminal_key is invalid")

        self._lock_global_terminal_identity(
            project_id=project.id,
            terminal_code=normalized_code,
        )
        bundle = self._terminal_review_bundle(
            project_id=project.id,
            terminal_code=normalized_code,
        )
        if not bundle.projection.rephoto_sources:
            raise CollectorTerminalSourceBlockedError("terminal source is blocked")
        projection = MeterSourceProjection(
            sources=bundle.projection.rephoto_sources,
            diagnostics=(),
        )
        photos = bundle.photos
        current_revision = bundle.projection.source_revision
        requested_revision = normalize_identifier(source_revision)
        active_run = self._active_global_terminal_run(
            project_id=project.id,
            terminal_code=normalized_code,
        )
        if active_run is not None:
            stored_revision = normalize_identifier(
                (active_run.stats or {}).get("source_revision")
            )
            if stored_revision == current_revision and not force_refresh:
                return self._global_terminal_open_result(
                    run=active_run,
                    snapshot_reused=True,
                    source_changed=bool(
                        requested_revision and requested_revision != current_revision
                    ),
                    current_source_revision=current_revision,
                )
            if self._global_run_has_progress(active_run):
                return self._global_terminal_open_result(
                    run=active_run,
                    snapshot_reused=True,
                    source_changed=True,
                    current_source_revision=current_revision,
                )
            active_stats = dict(active_run.stats or {})
            active_stats["superseded"] = True
            active_run.stats = active_stats

        run = self._create_run_from_projection(
            project=project,
            name=f"全局翻拍/{normalized_code}/{current_revision[:8]}",
            projection=projection,
            source_photos_by_id={str(photo.id): photo for photo in photos},
            stats_extra={
                "workflow_kind": "global_terminal_workbench",
                "source_revision": current_revision,
                "source_terminal_code": normalized_code,
                "source_terminal_key": expected_key,
                "superseded": False,
            },
            bind_direct_inventory=False,
        )
        hidden_terminal = self.session.scalar(
            select(CollectorTransferTerminal).where(
                CollectorTransferTerminal.run_id == run.id,
                CollectorTransferTerminal.team_id == self.team_id,
            )
        )
        if hidden_terminal is None:
            raise KeyError(str(run.id))
        self._reconcile_direct_requirements(
            run=run,
            terminal=hidden_terminal,
        )
        self._refresh_allocation_stats(run)
        if active_run is not None:
            active_stats = dict(active_run.stats or {})
            active_stats["superseded_by_run_id"] = str(run.id)
            active_run.stats = active_stats
            self._audit(
                action="collector_workbench.snapshot_superseded",
                entity_type="collector_transfer_run",
                entity_id=active_run.id,
                project_id=project.id,
                payload={"superseded_by_run_id": str(run.id)},
            )
        self._audit(
            action="collector_workbench.snapshot_created",
            entity_type="collector_transfer_run",
            entity_id=run.id,
            project_id=project.id,
            payload=dict(run.stats or {}),
        )
        self.session.commit()
        self.session.refresh(run)
        return self._global_terminal_open_result(
            run=run,
            snapshot_reused=False,
            source_changed=bool(
                requested_revision and requested_revision != current_revision
            ),
            current_source_revision=current_revision,
        )

    def _review_workbench_result(
        self,
        *,
        project: Project,
        bundle: _TerminalReviewBundle,
        workflow_state: str,
        rephoto: dict[str, object] | None,
    ) -> dict[str, object]:
        addresses = sorted(
            {
                normalize_identifier(item.source.installation_address)
                for item in bundle.projection.constructed_meters
                if item.source is not None
                and normalize_identifier(item.source.installation_address)
            }
        )
        review_blockers = [
            {
                "group_id": row["group_id"],
                "codes": list(row["blockers"]),
            }
            for row in bundle.review_rows
            if row["construction_state"] == "constructed" and row["blockers"]
        ]
        return {
            "terminal": {
                "terminal_key": terminal_key(
                    str(project.id),
                    bundle.terminal_code,
                ),
                "project_id": str(project.id),
                "terminal_code": bundle.terminal_code,
                "installation_address": "、".join(addresses),
            },
            "workflow_state": workflow_state,
            "source_revision": bundle.projection.source_revision,
            "constructed_meter_count": len(bundle.projection.constructed_meters),
            "unconstructed_meter_count": len(bundle.projection.unconstructed_meters),
            "review_ready_count": bundle.projection.review_ready_count,
            "review_required_count": bundle.projection.review_required_count,
            "review_blockers": review_blockers,
            "meters": list(bundle.review_rows),
            "rephoto": rephoto,
        }

    def open_review_workbench_terminal(
        self,
        *,
        terminal_key_value: str,
        source_revision: str = "",
    ) -> dict[str, object]:
        decoded_project_id, decoded_terminal_code = decode_terminal_key(
            terminal_key_value
        )
        try:
            project = self._project(decoded_project_id)
        except (KeyError, ValueError) as exc:
            raise TerminalNotFoundError(decoded_terminal_code) from exc
        normalized_code = normalize_identifier(decoded_terminal_code)
        self._lock_global_terminal_identity(
            project_id=project.id,
            terminal_code=normalized_code,
        )
        try:
            bundle = self._terminal_review_bundle(
                project_id=project.id,
                terminal_code=normalized_code,
                lock_groups=True,
            )
        except TerminalNotFoundError:
            raise

        locked_state = derive_terminal_workflow_state(
            bundle.projection,
            missing_collector_count=0,
            pool_available_count=0,
            snapshot_state=None,
        )
        if locked_state in {"no_construction", "blocked"}:
            return self._review_workbench_result(
                project=project,
                bundle=bundle,
                workflow_state=locked_state,
                rephoto=None,
            )

        current_revision = bundle.projection.source_revision
        requested_revision = normalize_identifier(source_revision)
        expected_key = terminal_key(str(project.id), normalized_code)
        active_run = self._active_global_terminal_run(
            project_id=project.id,
            terminal_code=normalized_code,
        )
        run: CollectorTransferRun
        snapshot_reused = False
        source_changed = bool(
            requested_revision and requested_revision != current_revision
        )
        superseded_run: CollectorTransferRun | None = None
        if active_run is not None:
            stored_revision = normalize_identifier(
                (active_run.stats or {}).get("source_revision")
            )
            if stored_revision == current_revision:
                run = active_run
                snapshot_reused = True
            elif self._global_run_has_progress(active_run):
                run = active_run
                snapshot_reused = True
                source_changed = True
            else:
                active_stats = dict(active_run.stats or {})
                active_stats["superseded"] = True
                active_run.stats = active_stats
                superseded_run = active_run
                active_run = None

        if active_run is None:
            snapshot_projection = MeterSourceProjection(
                sources=bundle.projection.rephoto_sources,
                diagnostics=(),
            )
            run = self._create_run_from_projection(
                project=project,
                name=f"全局翻拍/{normalized_code}/{current_revision[:8]}",
                projection=snapshot_projection,
                source_photos_by_id={str(photo.id): photo for photo in bundle.photos},
                stats_extra={
                    "workflow_kind": "global_terminal_workbench",
                    "source_revision": current_revision,
                    "source_terminal_code": normalized_code,
                    "source_terminal_key": expected_key,
                    "superseded": False,
                },
                bind_direct_inventory=False,
            )
            hidden_terminal = self.session.scalar(
                select(CollectorTransferTerminal).where(
                    CollectorTransferTerminal.run_id == run.id,
                    CollectorTransferTerminal.team_id == self.team_id,
                )
            )
            if hidden_terminal is None:
                raise KeyError(str(run.id))
            self._reconcile_direct_requirements(
                run=run,
                terminal=hidden_terminal,
            )
            self._refresh_allocation_stats(run)
            if superseded_run is not None:
                superseded_stats = dict(superseded_run.stats or {})
                superseded_stats["superseded_by_run_id"] = str(run.id)
                superseded_run.stats = superseded_stats
                self._audit(
                    action="collector_workbench.snapshot_superseded",
                    entity_type="collector_transfer_run",
                    entity_id=superseded_run.id,
                    project_id=project.id,
                    payload={"superseded_by_run_id": str(run.id)},
                )
            self._audit(
                action="collector_workbench.snapshot_created",
                entity_type="collector_transfer_run",
                entity_id=run.id,
                project_id=project.id,
                payload=dict(run.stats or {}),
            )
            self.session.commit()
            self.session.refresh(run)

        hidden_terminal = self.session.scalar(
            select(CollectorTransferTerminal).where(
                CollectorTransferTerminal.run_id == run.id,
                CollectorTransferTerminal.team_id == self.team_id,
            )
        )
        if hidden_terminal is None:
            raise KeyError(str(run.id))
        rephoto = self.global_terminal_detail(terminal_id=str(hidden_terminal.id))
        stored_revision = normalize_identifier((run.stats or {}).get("source_revision"))
        source_changed = source_changed or stored_revision != current_revision
        rephoto["source_revision"] = stored_revision
        rephoto["current_source_revision"] = current_revision
        rephoto["source_changed"] = source_changed
        rephoto["snapshot_reused"] = snapshot_reused

        completed_count = int(rephoto.get("completed_count") or 0)
        total_count = int(rephoto.get("total_count") or 0)
        collector_items = rephoto.get("collector_items")
        has_random_progress = bool(
            isinstance(collector_items, list)
            and any(
                isinstance(item, Mapping)
                and item.get("physical_state") == "replaced"
                for item in collector_items
            )
        )
        snapshot_state: str | None = None
        if total_count and completed_count >= total_count:
            snapshot_state = "completed"
        elif completed_count or has_random_progress:
            snapshot_state = "in_progress"
        pool_summary = rephoto.get("pool_summary")
        pool_payload = pool_summary if isinstance(pool_summary, Mapping) else {}
        workflow_state = derive_terminal_workflow_state(
            bundle.projection,
            missing_collector_count=int(pool_payload.get("required") or 0),
            pool_available_count=int(pool_payload.get("available") or 0),
            snapshot_state=snapshot_state,
        )
        return self._review_workbench_result(
            project=project,
            bundle=bundle,
            workflow_state=workflow_state,
            rephoto=rephoto,
        )

    def scan_inventory(self, *, project_id: str, collector_no: str) -> dict[str, object]:
        project = self._project(project_id)
        normalized_no = validate_collector_number(collector_no)

        physical = self.session.scalar(
            select(PhysicalCollector)
            .where(
                PhysicalCollector.team_id == self.team_id,
                PhysicalCollector.project_id == project.id,
                PhysicalCollector.collector_no == normalized_no,
            )
            .with_for_update()
        )
        photo = self._active_collector_photo(physical.id) if physical is not None else None
        decision = decide_project_inventory_scan(
            collector_no=normalized_no,
            is_project_requirement=self._project_has_collector_number(project.id, normalized_no),
            existing_pool_status=physical.pool_status if physical is not None else None,
            has_active_photo=photo is not None,
        )

        if not decision.persist_confirmation:
            return {
                "collector_id": str(physical.id) if physical is not None else None,
                "collector_no": normalized_no,
                "decision": decision.kind.value,
                "requires_photo": decision.requires_photo,
                "add_to_pool": decision.add_to_pool,
                "pool_status": physical.pool_status if physical is not None else None,
                "photo": _photo_response(photo),
            }

        if physical is None:
            physical = self._locked_project_physical_collector(
                project_id=project.id,
                collector_no=normalized_no,
                initial_status="direct",
            )
            photo = self._active_collector_photo(physical.id)
            decision = decide_project_inventory_scan(
                collector_no=normalized_no,
                is_project_requirement=True,
                existing_pool_status=physical.pool_status,
                has_active_photo=photo is not None,
            )
            if not decision.persist_confirmation:
                return {
                    "collector_id": str(physical.id),
                    "collector_no": normalized_no,
                    "decision": decision.kind.value,
                    "requires_photo": decision.requires_photo,
                    "add_to_pool": decision.add_to_pool,
                    "pool_status": physical.pool_status,
                    "photo": _photo_response(photo),
                }
        elif physical.pool_status not in {"reserved", "used"}:
            physical.pool_status = "direct"
        physical.last_scanned_at = datetime.now(UTC)

        event = CollectorScanEvent(
            run_id=None,
            team_id=self.team_id,
            project_id=project.id,
            physical_collector_id=physical.id,
            requirement_id=None,
            scanned_value=normalized_no,
            decision=decision.kind.value,
            requires_photo=decision.requires_photo,
            add_to_pool=decision.add_to_pool,
            actor_id=self._actor_user_id(),
        )
        self.session.add(event)
        self._audit(
            action="collector_transfer.inventory_scanned",
            entity_type="physical_collector",
            entity_id=physical.id,
            project_id=project.id,
            payload={"collector_no": normalized_no, "decision": decision.kind.value},
        )
        self.session.commit()
        return {
            "collector_id": str(physical.id),
            "collector_no": normalized_no,
            "decision": decision.kind.value,
            "requires_photo": decision.requires_photo,
            "add_to_pool": decision.add_to_pool,
            "pool_status": physical.pool_status,
            "photo": _photo_response(photo),
        }

    def scan_inventory_photo_region(
        self,
        *,
        project_id: str,
        collector_id: str,
        expected_collector_no: str,
        expected_photo_sha256: str,
        region: Mapping[str, float],
    ) -> dict[str, object]:
        project = self._project(project_id)
        normalized_expected_no = validate_collector_number(
            expected_collector_no,
            "expected_collector_no",
        )
        physical = self.session.scalar(
            select(PhysicalCollector).where(
                PhysicalCollector.id == _uuid(collector_id, "collector_id"),
                PhysicalCollector.team_id == self.team_id,
                PhysicalCollector.project_id == project.id,
            )
        )
        if physical is None:
            raise KeyError("collector not found")
        if physical.collector_no != normalized_expected_no:
            raise CollectorInventorySnapshotChangedError(
                "collector number changed; refresh and retry"
            )

        photo = self._active_collector_photo(physical.id)
        if photo is None:
            raise CollectorInventorySnapshotChangedError(
                "collector photo changed; refresh and retry"
            )
        if photo.sha256 != normalize_identifier(expected_photo_sha256):
            raise CollectorInventorySnapshotChangedError(
                "collector photo changed; refresh and retry"
            )

        return photo_barcode_check.scan_photo_region(
            {
                "id": str(photo.id),
                "image_url": normalize_identifier(photo.image_url),
                "object_key": normalize_identifier(photo.object_key),
                "storage_type": normalize_identifier(photo.storage_type),
                "sha256": normalize_identifier(photo.sha256),
                "content_type": normalize_identifier(photo.content_type),
            },
            "collector",
            region,
        )

    def correct_inventory_number(
        self,
        *,
        project_id: str,
        collector_id: str,
        expected_collector_no: str,
        expected_photo_sha256: str,
        collector_no: str,
        recognition_method: str,
        region: Mapping[str, float] | None,
    ) -> dict[str, object]:
        project = self._project(project_id)
        normalized_expected_no = validate_collector_number(
            expected_collector_no,
            "expected_collector_no",
        )
        corrected_no = validate_collector_number(collector_no)
        physical = self.session.scalar(
            select(PhysicalCollector)
            .where(
                PhysicalCollector.id == _uuid(collector_id, "collector_id"),
                PhysicalCollector.team_id == self.team_id,
                PhysicalCollector.project_id == project.id,
            )
            .with_for_update()
        )
        if physical is None:
            raise KeyError("collector not found")

        before_collector_no = physical.collector_no
        before_pool_status = physical.pool_status
        if before_collector_no != normalized_expected_no:
            raise CollectorInventorySnapshotChangedError(
                "collector number changed; refresh and retry"
            )
        if physical.id in self._inventory_number_correction_locked_ids(
            project_id=project.id,
            physicals=(physical,),
        ):
            raise CollectorInventoryAssignmentLockedError(
                "rollback collector assignment before renumbering"
            )

        photo = self._active_collector_photo(physical.id)
        current_photo_sha256 = photo.sha256 if photo is not None else ""
        if current_photo_sha256 != normalize_identifier(expected_photo_sha256):
            raise CollectorInventorySnapshotChangedError(
                "collector photo changed; refresh and retry"
            )

        normalized_method = normalize_identifier(recognition_method).lower()
        if normalized_method not in {"manual", "barcode", "ocr"}:
            raise ValueError("recognition_method is invalid")

        duplicate = self.session.scalar(
            select(PhysicalCollector)
            .where(
                PhysicalCollector.team_id == self.team_id,
                PhysicalCollector.project_id == project.id,
                PhysicalCollector.collector_no == corrected_no,
                PhysicalCollector.id != physical.id,
            )
        )
        if duplicate is not None:
            raise CollectorInventoryNumberConflictError(
                "collector number already exists"
            )

        is_direct = self._project_has_collector_number(project.id, corrected_no)
        if is_direct:
            after_pool_status = "direct"
        elif photo is not None:
            after_pool_status = "available"
        else:
            after_pool_status = "awaiting_photo"

        physical.collector_no = corrected_no
        physical.pool_status = after_pool_status
        physical.last_scanned_at = datetime.now(UTC)
        decision = decide_project_inventory_scan(
            collector_no=corrected_no,
            is_project_requirement=is_direct,
            existing_pool_status=after_pool_status,
            has_active_photo=photo is not None,
        )
        self.session.add(
            CollectorScanEvent(
                run_id=None,
                team_id=self.team_id,
                project_id=project.id,
                physical_collector_id=physical.id,
                requirement_id=None,
                scanned_value=corrected_no,
                decision=decision.kind.value,
                requires_photo=decision.requires_photo,
                add_to_pool=decision.add_to_pool,
                actor_id=self._actor_user_id(),
            )
        )
        self._audit(
            action="collector_transfer.inventory_number_corrected",
            entity_type="physical_collector",
            entity_id=physical.id,
            project_id=project.id,
            payload={
                "before_collector_no": before_collector_no,
                "after_collector_no": corrected_no,
                "before_pool_status": before_pool_status,
                "after_pool_status": after_pool_status,
                "recognition_method": normalized_method,
                "region": dict(region) if region is not None else None,
                "photo_id": str(photo.id) if photo is not None else None,
                "photo_sha256": current_photo_sha256,
            },
        )
        try:
            self.session.commit()
        except IntegrityError as exc:
            raise CollectorInventoryNumberConflictError(
                "collector number already exists"
            ) from exc
        return {
            "collector_id": str(physical.id),
            "collector_no": corrected_no,
            "decision": decision.kind.value,
            "requires_photo": decision.requires_photo,
            "add_to_pool": decision.add_to_pool,
            "pool_status": after_pool_status,
            "photo": _photo_response(photo),
        }

    def register_inventory(
        self,
        *,
        project_id: str,
        collector_no: str,
        original_filename: str,
        stored: Mapping[str, object],
        byte_size: int,
    ) -> dict[str, object]:
        project = self._project(project_id)
        normalized_no = validate_collector_number(collector_no)
        sha256 = normalize_identifier(stored.get("sha256"))
        if not sha256:
            raise ValueError("sha256 is required")

        is_direct = self._project_has_collector_number(project.id, normalized_no)
        photo = self.session.scalar(
            select(CollectorPhoto).where(
                CollectorPhoto.team_id == self.team_id,
                CollectorPhoto.project_id == project.id,
                CollectorPhoto.sha256 == sha256,
            )
        )
        if photo is not None:
            physical = self.session.scalar(
                select(PhysicalCollector)
                .where(
                    PhysicalCollector.id == photo.physical_collector_id,
                    PhysicalCollector.team_id == self.team_id,
                    PhysicalCollector.project_id == project.id,
                    PhysicalCollector.collector_no == normalized_no,
                )
                .with_for_update()
            )
            if physical is None:
                raise CollectorPhotoConflictError(
                    "photo content is already bound to another physical collector"
                )
        else:
            physical = self._locked_project_physical_collector(
                project_id=project.id,
                collector_no=normalized_no,
                initial_status="direct" if is_direct else "available",
            )
        if physical.pool_status not in {"reserved", "used"}:
            physical.pool_status = (
                "direct"
                if is_direct or physical.pool_status == "direct"
                else "available"
            )
        physical.last_scanned_at = datetime.now(UTC)

        active_photo = self._active_collector_photo(physical.id)
        if active_photo is not None and active_photo.sha256 != sha256:
            raise CollectorPhotoConflictError(
                "physical collector already has another active photo"
            )

        if photo is None:
            candidate_photo = CollectorPhoto(
                team_id=self.team_id,
                project_id=project.id,
                physical_collector_id=physical.id,
                sha256=sha256,
                original_filename=normalize_identifier(original_filename) or f"{normalized_no}.jpg",
                object_key=normalize_identifier(stored.get("storage_key") or stored.get("url")),
                image_url=normalize_identifier(stored.get("url")) or None,
                storage_type=normalize_identifier(stored.get("storage_type")) or "local_upload",
                content_type=normalize_identifier(stored.get("content_type")) or None,
                byte_size=byte_size,
                captured_at=datetime.now(UTC),
                captured_by_id=self._actor_user_id(),
                captured_by_username=self.actor,
                is_active=True,
            )
            try:
                with self.session.begin_nested():
                    self.session.add(candidate_photo)
                    self.session.flush()
            except IntegrityError as exc:
                photo = self.session.scalar(
                    select(CollectorPhoto).where(
                        CollectorPhoto.team_id == self.team_id,
                        CollectorPhoto.project_id == project.id,
                        CollectorPhoto.sha256 == sha256,
                    )
                )
                if photo is None or photo.physical_collector_id != physical.id:
                    raise CollectorPhotoConflictError(
                        "photo content is already bound to another physical collector"
                    ) from exc
            else:
                photo = candidate_photo

        final_decision = decide_project_inventory_scan(
            collector_no=normalized_no,
            is_project_requirement=is_direct,
            existing_pool_status=physical.pool_status,
            has_active_photo=True,
        )
        self.session.add(
            CollectorScanEvent(
                run_id=None,
                team_id=self.team_id,
                project_id=project.id,
                physical_collector_id=physical.id,
                requirement_id=None,
                scanned_value=normalized_no,
                decision=final_decision.kind.value,
                requires_photo=final_decision.requires_photo,
                add_to_pool=final_decision.add_to_pool,
                actor_id=self._actor_user_id(),
            )
        )

        self._audit(
            action="collector_transfer.inventory_photo_registered",
            entity_type="collector_photo",
            entity_id=photo.id,
            project_id=project.id,
            payload={"collector_id": str(physical.id), "sha256": photo.sha256},
        )
        self.session.commit()
        return {
            "collector_id": str(physical.id),
            "collector_no": physical.collector_no,
            "pool_status": physical.pool_status,
            "photo": _photo_response(photo),
        }

    def list_inventory(
        self,
        *,
        project_id: str,
        status: str | None = None,
    ) -> dict[str, object]:
        project = self._project(project_id)
        normalized_status = normalize_identifier(status)
        known_statuses = ("direct", "available", "reserved", "used", "awaiting_photo")
        if normalized_status and normalized_status not in known_statuses:
            raise ValueError("status is invalid")

        filters = (
            PhysicalCollector.team_id == self.team_id,
            PhysicalCollector.project_id == project.id,
            _public_collector_number_clause(),
        )
        query = select(PhysicalCollector).where(*filters)
        if normalized_status:
            query = query.where(PhysicalCollector.pool_status == normalized_status)
        rows = list(
            self.session.scalars(
                query.order_by(
                    PhysicalCollector.created_at.desc(),
                    PhysicalCollector.id.desc(),
                )
            ).all()
        )
        grouped_counts = {
            pool_status: int(count)
            for pool_status, count in self.session.execute(
                select(PhysicalCollector.pool_status, func.count(PhysicalCollector.id))
                .where(*filters)
                .group_by(PhysicalCollector.pool_status)
            ).all()
        }
        stats = {pool_status: grouped_counts.get(pool_status, 0) for pool_status in known_statuses}
        number_correction_locked_ids = self._inventory_number_correction_locked_ids(
            project_id=project.id,
            physicals=rows,
        )
        items = []
        for row in rows:
            photo = self._active_collector_photo(row.id)
            items.append(
                {
                    "collector_id": str(row.id),
                    "collector_no": row.collector_no,
                    "pool_status": row.pool_status,
                    "number_correction_locked": row.id in number_correction_locked_ids,
                    "photo": _photo_response(photo),
                    "last_scanned_at": row.last_scanned_at.isoformat() if row.last_scanned_at else None,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
            )
        return {"items": items, "total": len(rows), "stats": stats}

    def _inventory_number_correction_locked_ids(
        self,
        *,
        project_id: UUID,
        physicals: Sequence[PhysicalCollector],
    ) -> set[UUID]:
        if not physicals:
            return set()
        physical_ids = [physical.id for physical in physicals]
        locked_ids = {
            physical.id
            for physical in physicals
            if physical.pool_status in {"reserved", "used"}
        }
        locked_ids.update(
            self.session.scalars(
                select(CollectorAssignment.physical_collector_id).where(
                    CollectorAssignment.team_id == self.team_id,
                    CollectorAssignment.physical_collector_id.in_(physical_ids),
                    CollectorAssignment.status.in_(("reserved", "used")),
                )
            ).all()
        )

        collector_numbers = [physical.collector_no for physical in physicals]
        superseded = CollectorTransferRun.stats["superseded"].as_boolean()
        claimed_numbers = set(
            self.session.scalars(
                select(CollectorRequirement.original_collector_no)
                .join(
                    CollectorWorkbenchItem,
                    CollectorWorkbenchItem.requirement_id == CollectorRequirement.id,
                )
                .join(
                    CollectorTransferRun,
                    CollectorTransferRun.id == CollectorWorkbenchItem.run_id,
                )
                .where(
                    CollectorWorkbenchItem.team_id == self.team_id,
                    CollectorWorkbenchItem.item_kind == "collector_removal",
                    CollectorWorkbenchItem.assignment_id.is_(None),
                    CollectorRequirement.team_id == self.team_id,
                    CollectorRequirement.original_collector_no.in_(collector_numbers),
                    CollectorRequirement.status.in_(("direct_ready", "used")),
                    CollectorTransferRun.team_id == self.team_id,
                    CollectorTransferRun.project_id == project_id,
                    CollectorTransferRun.status != "cancelled",
                    or_(superseded.is_(None), superseded.is_(False)),
                )
                .distinct()
            ).all()
        )
        locked_ids.update(
            physical.id
            for physical in physicals
            if physical.collector_no in claimed_numbers
        )
        return locked_ids

    def list_runs(self, *, project_id: str | None = None) -> list[dict[str, object]]:
        query = select(CollectorTransferRun).where(CollectorTransferRun.team_id == self.team_id)
        if project_id:
            query = query.where(CollectorTransferRun.project_id == _uuid(project_id, "project_id"))
        rows = self.session.scalars(query.order_by(CollectorTransferRun.created_at.desc())).all()
        return [self._run_summary(row) for row in rows]

    def _active_collector_photo(self, physical_collector_id: UUID) -> CollectorPhoto | None:
        return self.session.scalar(
            select(CollectorPhoto)
            .where(
                CollectorPhoto.team_id == self.team_id,
                CollectorPhoto.physical_collector_id == physical_collector_id,
                CollectorPhoto.is_active.is_(True),
            )
            .order_by(CollectorPhoto.created_at.desc(), CollectorPhoto.id.desc())
        )

    def _locked_project_physical_collector(
        self,
        *,
        project_id: UUID,
        collector_no: str,
        initial_status: str,
    ) -> PhysicalCollector:
        query = (
            select(PhysicalCollector)
            .where(
                PhysicalCollector.team_id == self.team_id,
                PhysicalCollector.project_id == project_id,
                PhysicalCollector.collector_no == collector_no,
            )
            .with_for_update()
        )
        physical = self.session.scalar(query)
        if physical is not None:
            return physical

        candidate = PhysicalCollector(
            team_id=self.team_id,
            project_id=project_id,
            collector_no=collector_no,
            pool_status=initial_status,
        )
        try:
            with self.session.begin_nested():
                self.session.add(candidate)
                self.session.flush()
        except IntegrityError:
            physical = self.session.scalar(query)
            if physical is None:
                raise
            return physical
        return candidate

    def _locked_physical_collector_for_scan(
        self,
        *,
        run: CollectorTransferRun,
        collector_no: str,
    ) -> PhysicalCollector:
        query = (
            select(PhysicalCollector)
            .where(
                PhysicalCollector.team_id == self.team_id,
                PhysicalCollector.project_id == run.project_id,
                PhysicalCollector.collector_no == collector_no,
            )
            .with_for_update()
        )
        physical = self.session.scalar(query)
        if physical is not None:
            return physical

        candidate = PhysicalCollector(
            team_id=self.team_id,
            project_id=run.project_id,
            collector_no=collector_no,
            pool_status="awaiting_photo",
            first_seen_run_id=run.id,
        )
        try:
            with self.session.begin_nested():
                self.session.add(candidate)
                self.session.flush()
        except IntegrityError:
            physical = self.session.scalar(query)
            if physical is None:
                raise
            return physical
        return candidate

    def _validate_inventory_ownership(
        self,
        *,
        run: CollectorTransferRun,
        physical: PhysicalCollector,
        photo: CollectorPhoto,
    ) -> None:
        if physical.team_id != self.team_id or physical.project_id != run.project_id:
            raise CollectorAllocationConflictError(
                "physical collector project ownership conflicts with the run"
            )
        if (
            photo.team_id != self.team_id
            or photo.project_id != run.project_id
            or photo.physical_collector_id != physical.id
        ):
            raise CollectorAllocationConflictError(
                "collector photo project ownership conflicts with the run"
            )

    def _create_assignment(
        self,
        *,
        run: CollectorTransferRun,
        requirement: CollectorRequirement,
        physical: PhysicalCollector,
        photo: CollectorPhoto,
        assignment_mode: str,
    ) -> tuple[CollectorAssignment, bool]:
        self._validate_inventory_ownership(run=run, physical=physical, photo=photo)
        candidate = CollectorAssignment(
            run_id=run.id,
            team_id=self.team_id,
            requirement_id=requirement.id,
            physical_collector_id=physical.id,
            collector_photo_id=photo.id,
            assignment_mode=assignment_mode,
            status="reserved",
            assigned_by_id=self._actor_user_id(),
            assigned_by_username=self.actor,
        )
        try:
            with self.session.begin_nested():
                self.session.add(candidate)
                self.session.flush()
        except IntegrityError as exc:
            winner = self.session.scalar(
                select(CollectorAssignment)
                .where(
                    or_(
                        CollectorAssignment.requirement_id == requirement.id,
                        CollectorAssignment.physical_collector_id == physical.id,
                    ),
                    CollectorAssignment.status.in_(("reserved", "used")),
                )
                .with_for_update()
            )
            if (
                winner is not None
                and winner.run_id == run.id
                and winner.requirement_id == requirement.id
                and winner.physical_collector_id == physical.id
                and winner.collector_photo_id == photo.id
                and winner.assignment_mode == assignment_mode
                and winner.status in {"reserved", "used"}
            ):
                return winner, False
            self.session.rollback()
            raise CollectorAllocationConflictError("collector assignment conflicts with an existing allocation") from exc
        return candidate, True

    def _ensure_removal_workbench_item(
        self,
        *,
        run: CollectorTransferRun,
        requirement: CollectorRequirement,
        assignment: CollectorAssignment,
    ) -> None:
        existing = self.session.scalar(
            select(CollectorWorkbenchItem).where(
                CollectorWorkbenchItem.run_id == run.id,
                CollectorWorkbenchItem.item_kind == "collector_removal",
                CollectorWorkbenchItem.source_key == str(requirement.id),
            )
        )
        if existing is None:
            meter_count = int(
                self.session.scalar(
                    select(func.count(CollectorMeterItem.id)).where(
                        CollectorMeterItem.terminal_id == requirement.terminal_id
                    )
                )
                or 0
            )
            self.session.add(
                CollectorWorkbenchItem(
                    run_id=run.id,
                    terminal_id=requirement.terminal_id,
                    team_id=self.team_id,
                    item_kind="collector_removal",
                    source_key=str(requirement.id),
                    requirement_id=requirement.id,
                    assignment_id=assignment.id,
                    status="pending",
                    sort_order=meter_count + requirement.sort_order,
                )
            )
        else:
            existing.assignment_id = assignment.id

    def _ensure_direct_removal_workbench_item(
        self,
        *,
        run: CollectorTransferRun,
        requirement: CollectorRequirement,
    ) -> CollectorWorkbenchItem:
        item = self.session.scalar(
            select(CollectorWorkbenchItem).where(
                CollectorWorkbenchItem.run_id == run.id,
                CollectorWorkbenchItem.requirement_id == requirement.id,
            )
        )
        if item is None:
            meter_count = int(
                self.session.scalar(
                    select(func.count(CollectorMeterItem.id)).where(
                        CollectorMeterItem.terminal_id == requirement.terminal_id
                    )
                )
                or 0
            )
            item = CollectorWorkbenchItem(
                run_id=run.id,
                terminal_id=requirement.terminal_id,
                team_id=self.team_id,
                item_kind="collector_removal",
                source_key=str(requirement.id),
                requirement_id=requirement.id,
                assignment_id=None,
                status="pending",
                sort_order=meter_count + requirement.sort_order,
            )
            self.session.add(item)
            self.session.flush()
        return item

    def _reconcile_direct_requirements(
        self,
        *,
        run: CollectorTransferRun,
        terminal: CollectorTransferTerminal,
    ) -> int:
        locked_run = self._run(str(run.id), lock=True)
        locked_terminal = self.session.scalar(
            select(CollectorTransferTerminal)
            .where(
                CollectorTransferTerminal.id == terminal.id,
                CollectorTransferTerminal.run_id == locked_run.id,
                CollectorTransferTerminal.team_id == self.team_id,
            )
            .with_for_update()
        )
        if locked_terminal is None:
            raise KeyError(str(terminal.id))
        requirements = list(
            self.session.scalars(
                select(CollectorRequirement)
                .where(
                    CollectorRequirement.run_id == locked_run.id,
                    CollectorRequirement.terminal_id == locked_terminal.id,
                    CollectorRequirement.team_id == self.team_id,
                    CollectorRequirement.status == "unmatched",
                )
                .order_by(CollectorRequirement.id)
                .with_for_update()
            ).all()
        )
        collector_numbers = sorted(
            {
                normalize_identifier(requirement.original_collector_no)
                for requirement in requirements
                if not _is_manual_requirement(requirement)
                and normalize_identifier(requirement.original_collector_no)
            }
        )
        if not collector_numbers:
            return 0
        physicals = list(
            self.session.scalars(
                select(PhysicalCollector)
                .where(
                    PhysicalCollector.team_id == self.team_id,
                    PhysicalCollector.project_id == locked_run.project_id,
                    PhysicalCollector.collector_no.in_(collector_numbers),
                    PhysicalCollector.pool_status.in_(("direct", "used")),
                    _public_collector_number_clause(),
                )
                .order_by(PhysicalCollector.id)
                .with_for_update()
            ).all()
        )
        physical_by_number = {physical.collector_no: physical for physical in physicals}
        workflow_kind = CollectorTransferRun.stats["workflow_kind"].as_string()
        superseded = CollectorTransferRun.stats["superseded"].as_boolean()
        eligible: list[tuple[CollectorRequirement, PhysicalCollector]] = []
        for requirement in requirements:
            physical = physical_by_number.get(requirement.original_collector_no)
            if physical is None:
                continue
            owner_terminal_id = self.session.scalar(
                select(CollectorTransferTerminal.id)
                .join(
                    CollectorTransferRun,
                    CollectorTransferRun.id == CollectorTransferTerminal.run_id,
                )
                .join(
                    CollectorRequirement,
                    CollectorRequirement.terminal_id == CollectorTransferTerminal.id,
                )
                .join(
                    CollectorWorkbenchItem,
                    CollectorWorkbenchItem.requirement_id == CollectorRequirement.id,
                )
                .where(
                    CollectorTransferRun.team_id == self.team_id,
                    CollectorTransferRun.project_id == locked_run.project_id,
                    workflow_kind == "global_terminal_workbench",
                    or_(superseded.is_(None), superseded.is_(False)),
                    CollectorTransferTerminal.id != locked_terminal.id,
                    CollectorRequirement.original_collector_no
                    == requirement.original_collector_no,
                    CollectorRequirement.status.in_(("direct_ready", "used")),
                    CollectorWorkbenchItem.assignment_id.is_(None),
                )
                .order_by(CollectorTransferTerminal.id)
                .limit(1)
            )
            if owner_terminal_id is not None:
                raise CollectorDirectConflictError(
                    "collector is already claimed by another terminal"
                )
            if physical.pool_status != "direct":
                continue
            eligible.append((requirement, physical))

        bound_count = 0
        for requirement, physical in eligible:
            requirement.status = "direct_ready"
            item = self._ensure_direct_removal_workbench_item(
                run=locked_run,
                requirement=requirement,
            )
            self._audit(
                action="collector_workbench.direct_bound",
                entity_type="collector_workbench_item",
                entity_id=item.id,
                project_id=locked_run.project_id,
                payload={
                    "run_id": str(locked_run.id),
                    "terminal_id": str(locked_terminal.id),
                    "requirement_id": str(requirement.id),
                    "physical_collector_id": str(physical.id),
                    "collector_no": physical.collector_no,
                    "mode": "direct",
                },
            )
            bound_count += 1
        return bound_count

    def _bind_direct_inventory(self, run: CollectorTransferRun) -> int:
        requirements = list(
            self.session.scalars(
                select(CollectorRequirement)
                .where(
                    CollectorRequirement.run_id == run.id,
                    CollectorRequirement.team_id == self.team_id,
                    CollectorRequirement.status == "unmatched",
                )
                .order_by(
                    CollectorRequirement.terminal_id,
                    CollectorRequirement.sort_order,
                    CollectorRequirement.id,
                )
                .with_for_update()
            ).all()
        )
        collector_numbers = {
            requirement.original_collector_no
            for requirement in requirements
            if not _is_manual_requirement(requirement)
            and requirement.original_collector_no
        }
        if not collector_numbers:
            return 0

        physical_collectors = list(
            self.session.scalars(
                select(PhysicalCollector)
                .where(
                    PhysicalCollector.team_id == self.team_id,
                    PhysicalCollector.project_id == run.project_id,
                    PhysicalCollector.collector_no.in_(collector_numbers),
                    PhysicalCollector.pool_status == "direct",
                    _public_collector_number_clause(),
                )
                .order_by(PhysicalCollector.collector_no, PhysicalCollector.id)
                .with_for_update()
            ).all()
        )
        physical_by_number = {item.collector_no: item for item in physical_collectors}

        bound_count = 0
        consumed_physical_ids: set[UUID] = set()
        for requirement in requirements:
            physical = physical_by_number.get(requirement.original_collector_no)
            if physical is None or physical.id in consumed_physical_ids:
                continue
            physical.pool_status = "direct"
            requirement.status = "direct_ready"
            self._ensure_direct_removal_workbench_item(
                run=run,
                requirement=requirement,
            )
            consumed_physical_ids.add(physical.id)
            bound_count += 1
        return bound_count

    def scan_collector(self, *, run_id: str, collector_no: str) -> dict[str, object]:
        run = self._run(run_id, lock=True)
        normalized_no = validate_collector_number(collector_no)
        physical = self._locked_physical_collector_for_scan(run=run, collector_no=normalized_no)
        physical.last_scanned_at = datetime.now(UTC)

        existing_assignment = self.session.scalar(
            select(CollectorAssignment).where(
                CollectorAssignment.physical_collector_id == physical.id,
                CollectorAssignment.status.in_(("reserved", "used")),
            )
        )
        if existing_assignment is not None and existing_assignment.run_id != run.id:
            raise ValueError("该采集器已经在其他批次使用，禁止重复使用")
        photo = self._active_collector_photo(physical.id)

        requirement: CollectorRequirement | None = None
        if existing_assignment is not None:
            requirement = self.session.scalar(
                select(CollectorRequirement).where(CollectorRequirement.id == existing_assignment.requirement_id)
            )
        if requirement is None:
            prior_direct = self.session.scalar(
                select(CollectorScanEvent)
                .where(
                    CollectorScanEvent.run_id == run.id,
                    CollectorScanEvent.physical_collector_id == physical.id,
                    CollectorScanEvent.requirement_id.is_not(None),
                )
                .order_by(CollectorScanEvent.created_at.desc(), CollectorScanEvent.id.desc())
            )
            if prior_direct is not None:
                requirement = self.session.scalar(
                    select(CollectorRequirement).where(CollectorRequirement.id == prior_direct.requirement_id)
                )
        if requirement is None:
            requirement = self.session.scalar(
                select(CollectorRequirement)
                .where(
                    CollectorRequirement.run_id == run.id,
                    CollectorRequirement.team_id == self.team_id,
                    CollectorRequirement.original_collector_no == normalized_no,
                    CollectorRequirement.status == "unmatched",
                )
                .order_by(CollectorRequirement.terminal_id, CollectorRequirement.sort_order, CollectorRequirement.id)
                .with_for_update()
            )

        if existing_assignment is not None:
            decision = CollectorScanDecision(
                kind=CollectorScanDecisionKind.ASSIGNMENT_REUSE,
                requirement_id=str(existing_assignment.requirement_id),
                requires_photo=False,
                add_to_pool=False,
            )
        else:
            decision = decide_collector_scan(
                collector_no=normalized_no,
                unmatched_requirements=({str(requirement.id): requirement.original_collector_no} if requirement else {}),
                has_reusable_photo=photo is not None,
            )
        if requirement is not None and existing_assignment is None:
            physical.pool_status = "direct"
            if photo is None:
                requirement.status = "direct_pending_photo"
            else:
                requirement.status = "direct_ready"
                existing_assignment, _created = self._create_assignment(
                    run=run,
                    requirement=requirement,
                    physical=physical,
                    photo=photo,
                    assignment_mode="direct",
                )
                self._ensure_removal_workbench_item(
                    run=run,
                    requirement=requirement,
                    assignment=existing_assignment,
                )
        if requirement is None:
            physical.pool_status = "available" if photo is not None else "awaiting_photo"
            if photo is not None:
                decision = CollectorScanDecision(
                    kind=CollectorScanDecisionKind.POOL_NEEDS_PHOTO,
                    requirement_id=None,
                    requires_photo=False,
                    add_to_pool=True,
                )

        event = CollectorScanEvent(
            run_id=run.id,
            team_id=self.team_id,
            project_id=run.project_id,
            physical_collector_id=physical.id,
            requirement_id=requirement.id if requirement is not None else None,
            scanned_value=normalized_no,
            decision=decision.kind.value,
            requires_photo=decision.requires_photo,
            add_to_pool=decision.add_to_pool,
            actor_id=self._actor_user_id(),
        )
        self.session.add(event)
        self._audit(
            action="collector_transfer.collector_scanned",
            entity_type="physical_collector",
            entity_id=physical.id,
            project_id=run.project_id,
            payload={
                "run_id": str(run.id),
                "collector_no": normalized_no,
                "decision": decision.kind.value,
                "requirement_id": str(requirement.id) if requirement else None,
            },
        )
        stats = self._refresh_allocation_stats(run)
        self.session.commit()
        return {
            "collector_id": str(physical.id),
            "collector_no": normalized_no,
            "decision": decision.kind.value,
            "requires_photo": decision.requires_photo,
            "add_to_pool": decision.add_to_pool,
            "pool_status": physical.pool_status,
            "requirement_id": str(requirement.id) if requirement else None,
            "photo": _photo_response(photo),
            "stats": stats,
        }

    def register_photo(
        self,
        *,
        run_id: str,
        collector_id: str,
        original_filename: str,
        stored: Mapping[str, object],
        byte_size: int,
    ) -> dict[str, object]:
        run = self._run(run_id, lock=True)
        physical = self.session.scalar(
            select(PhysicalCollector)
            .where(
                PhysicalCollector.id == _uuid(collector_id, "collector_id"),
                PhysicalCollector.team_id == self.team_id,
            )
            .with_for_update()
        )
        if physical is None:
            raise KeyError(collector_id)
        current_run_scan = self.session.scalar(
            select(CollectorScanEvent)
            .where(
                CollectorScanEvent.run_id == run.id,
                CollectorScanEvent.team_id == self.team_id,
                CollectorScanEvent.physical_collector_id == physical.id,
            )
            .order_by(CollectorScanEvent.created_at.desc(), CollectorScanEvent.id.desc())
            .with_for_update()
        )
        if current_run_scan is None:
            raise CollectorScanProvenanceError("当前批次没有该实物采集器的扫码记录")
        sha256 = normalize_identifier(stored.get("sha256"))
        photo = self.session.scalar(
            select(CollectorPhoto).where(
                CollectorPhoto.team_id == self.team_id,
                CollectorPhoto.project_id == run.project_id,
                CollectorPhoto.sha256 == sha256,
            )
        )
        if photo is not None and photo.physical_collector_id != physical.id:
            raise CollectorPhotoConflictError(
                "photo content is already bound to another physical collector"
            )
        if photo is None:
            photo = CollectorPhoto(
                team_id=self.team_id,
                project_id=run.project_id,
                physical_collector_id=physical.id,
                sha256=sha256,
                original_filename=normalize_identifier(original_filename) or f"{physical.collector_no}.jpg",
                object_key=normalize_identifier(stored.get("storage_key") or stored.get("url")),
                image_url=normalize_identifier(stored.get("url")) or None,
                storage_type=normalize_identifier(stored.get("storage_type")) or "local_upload",
                content_type=normalize_identifier(stored.get("content_type")) or None,
                byte_size=byte_size,
                captured_at=datetime.now(UTC),
                captured_by_id=self._actor_user_id(),
                captured_by_username=self.actor,
                is_active=True,
            )
            self.session.add(photo)
            try:
                self.session.flush()
            except IntegrityError as exc:
                self.session.rollback()
                raise CollectorPhotoConflictError(
                    "photo content is already bound to another physical collector"
                ) from exc

        direct_event = current_run_scan if current_run_scan.requirement_id is not None else None
        assignment: CollectorAssignment | None = None
        if direct_event is not None:
            requirement = self.session.scalar(
                select(CollectorRequirement)
                .where(
                    CollectorRequirement.id == direct_event.requirement_id,
                    CollectorRequirement.run_id == run.id,
                )
                .with_for_update()
            )
            if requirement is not None:
                assignment = self.session.scalar(
                    select(CollectorAssignment).where(CollectorAssignment.requirement_id == requirement.id)
                )
                if assignment is None:
                    assignment, _created = self._create_assignment(
                        run=run,
                        requirement=requirement,
                        physical=physical,
                        photo=photo,
                        assignment_mode="direct",
                    )
                    requirement.status = "direct_ready"
                    physical.pool_status = "direct"
                    self._ensure_removal_workbench_item(
                        run=run,
                        requirement=requirement,
                        assignment=assignment,
                    )
        if direct_event is None and physical.pool_status == "awaiting_photo":
            physical.pool_status = "available"
        self._audit(
            action="collector_transfer.photo_registered",
            entity_type="collector_photo",
            entity_id=photo.id,
            project_id=run.project_id,
            payload={"run_id": str(run.id), "collector_id": str(physical.id), "sha256": photo.sha256},
        )
        stats = self._refresh_allocation_stats(run)
        self.session.commit()
        return {
            "collector_id": str(physical.id),
            "collector_no": physical.collector_no,
            "pool_status": physical.pool_status,
            "photo": _photo_response(photo),
            "assignment_id": str(assignment.id) if assignment is not None else None,
            "stats": stats,
        }

    def allocate(self, *, run_id: str) -> dict[str, object]:
        run = self._run(run_id)
        if (run.stats or {}).get("workflow_kind") == "global_terminal_workbench":
            run_uuid = _uuid(run_id, "run_id")
            global_terminal_ref = self.session.execute(
                select(
                    CollectorTransferRun.project_id,
                    CollectorTransferTerminal.id,
                    CollectorTransferTerminal.terminal_code,
                )
                .outerjoin(
                    CollectorTransferTerminal,
                    and_(
                        CollectorTransferTerminal.run_id == CollectorTransferRun.id,
                        CollectorTransferTerminal.team_id == self.team_id,
                    ),
                )
                .where(
                    CollectorTransferRun.id == run_uuid,
                    CollectorTransferRun.team_id == self.team_id,
                )
                .order_by(CollectorTransferTerminal.id)
                .limit(1)
            ).one_or_none()
            if global_terminal_ref is None:
                raise KeyError(run_id)
            if global_terminal_ref.id is None:
                raise KeyError(run_id)
            self._lock_global_terminal_identity(
                project_id=global_terminal_ref.project_id,
                terminal_code=global_terminal_ref.terminal_code,
            )
            run = self._run(run_id, lock=True)
            terminal = self.session.scalar(
                select(CollectorTransferTerminal)
                .where(
                    CollectorTransferTerminal.id == global_terminal_ref.id,
                    CollectorTransferTerminal.run_id == run.id,
                    CollectorTransferTerminal.team_id == self.team_id,
                )
                .with_for_update()
            )
            if terminal is None:
                raise KeyError(run_id)
            self._require_terminal_rephoto_ready(run=run, terminal=terminal)
            raise CollectorRunBlockedError(
                "global terminal workbench requires terminal-scoped replacement"
            )
        run = self._run(run_id, lock=True)
        blocked_terminal_count = int(
            self.session.scalar(
                select(func.count(CollectorTransferTerminal.id)).where(
                    CollectorTransferTerminal.run_id == run.id,
                    CollectorTransferTerminal.status == "blocked",
                )
            )
            or 0
        )
        if blocked_terminal_count:
            raise CollectorRunBlockedError("批次存在资料阻断，不能执行随机分配")
        requirements = list(
            self.session.scalars(
                select(CollectorRequirement)
                .where(
                    CollectorRequirement.run_id == run.id,
                    CollectorRequirement.team_id == self.team_id,
                    CollectorRequirement.status == "unmatched",
                )
                .order_by(CollectorRequirement.terminal_id, CollectorRequirement.sort_order, CollectorRequirement.id)
                .with_for_update()
            ).all()
        )
        if not requirements and run.status == "allocated":
            return {
                "run_id": str(run.id),
                "assignment_count": int(dict(run.stats or {}).get("assignment_count") or 0),
                "assignments": [],
            }
        physical_collectors = list(
            self.session.scalars(
                select(PhysicalCollector)
                .where(
                    PhysicalCollector.team_id == self.team_id,
                    PhysicalCollector.project_id == run.project_id,
                    PhysicalCollector.pool_status == "available",
                    _public_collector_number_clause(),
                )
                .order_by(PhysicalCollector.id)
                .with_for_update()
            ).all()
        )
        physical_by_id = {item.id: item for item in physical_collectors}
        photos_by_collector: dict[str, CollectorPhoto] = {}
        if physical_collectors:
            photos = self.session.scalars(
                select(CollectorPhoto)
                .where(
                    CollectorPhoto.team_id == self.team_id,
                    CollectorPhoto.physical_collector_id.in_([item.id for item in physical_collectors]),
                    CollectorPhoto.is_active.is_(True),
                )
                .order_by(CollectorPhoto.physical_collector_id, CollectorPhoto.created_at.desc(), CollectorPhoto.id.desc())
                .with_for_update()
            ).all()
            for photo in photos:
                physical = physical_by_id[photo.physical_collector_id]
                self._validate_inventory_ownership(run=run, physical=physical, photo=photo)
                photos_by_collector.setdefault(str(photo.physical_collector_id), photo)

        plan = plan_random_assignments(
            requirement_ids=[str(item.id) for item in requirements],
            available_collector_ids=[
                str(item.id) for item in physical_collectors if str(item.id) in photos_by_collector
            ],
        )
        requirements_by_id = {str(item.id): item for item in requirements}
        collectors_by_id = {str(item.id): item for item in physical_collectors}
        result: list[dict[str, str]] = []
        for requirement_id, collector_id in plan:
            requirement = requirements_by_id[requirement_id]
            physical = collectors_by_id[collector_id]
            photo = photos_by_collector[collector_id]
            assignment, created = self._create_assignment(
                run=run,
                requirement=requirement,
                physical=physical,
                photo=photo,
                assignment_mode="random",
            )
            if created or requirement.status == "unmatched":
                requirement.status = "assigned"
            if created or physical.pool_status == "available":
                physical.pool_status = "reserved"
            self._ensure_removal_workbench_item(
                run=run,
                requirement=requirement,
                assignment=assignment,
            )
            result.append(
                {
                    "assignment_id": str(assignment.id),
                    "requirement_id": requirement_id,
                    "original_collector_no": _collector_requirement_label(requirement),
                    "physical_collector_id": collector_id,
                    "final_collector_no": physical.collector_no,
                    "mode": "random",
                }
            )
        if not requirements:
            result = []
        run.status = "allocated"
        stats = self._refresh_allocation_stats(run)
        self._audit(
            action="collector_transfer.random_allocated",
            entity_type="collector_transfer_run",
            entity_id=run.id,
            project_id=run.project_id,
            payload={
                "assignment_count": len(result),
                "assigned_by": self.actor,
                "assignments": result,
            },
        )
        self.session.commit()
        return {
            "run_id": str(run.id),
            "assignment_count": len(result),
            "assignments": result,
            "stats": stats,
        }

    def _locked_global_workbench_terminal(
        self,
        *,
        terminal_id: str,
    ) -> tuple[CollectorTransferRun, CollectorTransferTerminal]:
        terminal_uuid = _uuid(terminal_id, "terminal_id")
        terminal_ref = self.session.execute(
            select(
                CollectorTransferTerminal.run_id,
                CollectorTransferTerminal.id,
                CollectorTransferTerminal.terminal_code,
                CollectorTransferRun.project_id,
            )
            .join(
                CollectorTransferRun,
                CollectorTransferRun.id == CollectorTransferTerminal.run_id,
            ).where(
                CollectorTransferTerminal.id == terminal_uuid,
                CollectorTransferTerminal.team_id == self.team_id,
                CollectorTransferRun.team_id == self.team_id,
            )
        ).one_or_none()
        if terminal_ref is None:
            raise KeyError(terminal_id)

        # Canonical mutation lock order:
        # advisory terminal identity -> run -> terminal -> source evidence ->
        # requirement -> physical -> assignment -> workbench item.
        self._lock_global_terminal_identity(
            project_id=terminal_ref.project_id,
            terminal_code=terminal_ref.terminal_code,
        )
        run = self._run(str(terminal_ref.run_id), lock=True)
        stats = dict(run.stats or {})
        if (
            stats.get("workflow_kind") != "global_terminal_workbench"
            or bool(stats.get("superseded"))
        ):
            raise KeyError(terminal_id)
        terminal = self.session.scalar(
            select(CollectorTransferTerminal)
            .where(
                CollectorTransferTerminal.id == terminal_uuid,
                CollectorTransferTerminal.run_id == run.id,
                CollectorTransferTerminal.team_id == self.team_id,
            )
            .with_for_update()
        )
        if terminal is None:
            raise KeyError(terminal_id)
        self._require_terminal_rephoto_ready(run=run, terminal=terminal)
        if terminal.status == "blocked":
            raise CollectorTerminalSourceBlockedError(
                "终端存在资料阻断，不能执行随机替换"
            )
        return run, terminal

    def _allocate_locked_requirements(
        self,
        *,
        run: CollectorTransferRun,
        requirements: Sequence[CollectorRequirement],
    ) -> list[dict[str, str]]:
        physical_collectors = list(
            self.session.scalars(
                select(PhysicalCollector)
                .where(
                    PhysicalCollector.team_id == self.team_id,
                    PhysicalCollector.project_id == run.project_id,
                    PhysicalCollector.pool_status == "available",
                    _public_collector_number_clause(),
                    ~exists().where(
                        CollectorAssignment.physical_collector_id
                        == PhysicalCollector.id,
                        CollectorAssignment.status.in_(("reserved", "used")),
                    ),
                )
                .order_by(PhysicalCollector.id)
                .with_for_update()
            ).all()
        )
        physical_by_id = {physical.id: physical for physical in physical_collectors}
        photos_by_physical: dict[UUID, list[CollectorPhoto]] = defaultdict(list)
        if physical_collectors:
            photos = list(
                self.session.scalars(
                    select(CollectorPhoto)
                    .where(
                        CollectorPhoto.team_id == self.team_id,
                        CollectorPhoto.project_id == run.project_id,
                        CollectorPhoto.physical_collector_id.in_(physical_by_id),
                        CollectorPhoto.is_active.is_(True),
                    )
                    .order_by(
                        CollectorPhoto.physical_collector_id,
                        CollectorPhoto.id,
                    )
                    .with_for_update()
                ).all()
            )
            for photo in photos:
                photos_by_physical[photo.physical_collector_id].append(photo)

        valid_photos = {
            physical_id: rows[0]
            for physical_id, rows in photos_by_physical.items()
            if len(rows) == 1
        }
        plan = plan_random_assignments(
            requirement_ids=[str(requirement.id) for requirement in requirements],
            available_collector_ids=[
                str(physical.id)
                for physical in physical_collectors
                if physical.id in valid_photos
            ],
        )
        requirement_by_id = {
            str(requirement.id): requirement for requirement in requirements
        }
        result: list[dict[str, str]] = []
        for requirement_id, physical_id in plan:
            requirement = requirement_by_id[requirement_id]
            physical = physical_by_id[UUID(physical_id)]
            photo = valid_photos[physical.id]
            assignment, created = self._create_assignment(
                run=run,
                requirement=requirement,
                physical=physical,
                photo=photo,
                assignment_mode="random",
            )
            if created or requirement.status == "unmatched":
                requirement.status = "assigned"
            if created or physical.pool_status == "available":
                physical.pool_status = "reserved"
            self._ensure_removal_workbench_item(
                run=run,
                requirement=requirement,
                assignment=assignment,
            )
            result.append(
                {
                    "assignment_id": str(assignment.id),
                    "requirement_id": requirement_id,
                    "original_collector_no": _collector_requirement_label(requirement),
                    "physical_collector_id": physical_id,
                    "final_collector_no": physical.collector_no,
                    "mode": "random",
                }
            )
        return result

    def replace_terminal_missing(self, *, terminal_id: str) -> dict[str, object]:
        run, terminal = self._locked_global_workbench_terminal(
            terminal_id=terminal_id
        )

        requirements = list(
            self.session.scalars(
                select(CollectorRequirement)
                .where(
                    CollectorRequirement.run_id == run.id,
                    CollectorRequirement.terminal_id == terminal.id,
                    CollectorRequirement.team_id == self.team_id,
                    CollectorRequirement.status == "unmatched",
                )
                .order_by(CollectorRequirement.id)
                .with_for_update()
            ).all()
        )
        required = len(requirements)
        if not requirements:
            return {
                "run_id": str(run.id),
                "terminal_id": str(terminal.id),
                "required": 0,
                "assigned": 0,
                "assignments": [],
            }

        result = self._allocate_locked_requirements(
            run=run,
            requirements=requirements,
        )

        run.status = "allocated"
        self._refresh_allocation_stats(run)
        self._audit(
            action="collector_workbench.terminal_replaced",
            entity_type="collector_transfer_terminal",
            entity_id=terminal.id,
            project_id=run.project_id,
            payload={
                "run_id": str(run.id),
                "terminal_id": str(terminal.id),
                "required": required,
                "assigned": len(result),
                "assigned_by": self.actor,
                "assignments": result,
            },
        )
        self.session.commit()
        return {
            "run_id": str(run.id),
            "terminal_id": str(terminal.id),
            "required": required,
            "assigned": len(result),
            "assignments": result,
        }

    def create_manual_demand(
        self,
        *,
        terminal_id: str,
        quantity: int,
    ) -> dict[str, object]:
        if isinstance(quantity, bool) or quantity <= 0:
            raise ValueError("quantity must be a positive integer")

        run, terminal = self._locked_global_workbench_terminal(
            terminal_id=terminal_id
        )
        current_max_sort = int(
            self.session.scalar(
                select(func.max(CollectorRequirement.sort_order)).where(
                    CollectorRequirement.run_id == run.id,
                    CollectorRequirement.terminal_id == terminal.id,
                    CollectorRequirement.team_id == self.team_id,
                )
            )
            or 0
        )
        requirement_ids: list[UUID] = []
        new_requirements: list[CollectorRequirement] = []
        for offset in range(quantity):
            requirement_id = uuid4()
            requirement_ids.append(requirement_id)
            new_requirements.append(
                CollectorRequirement(
                    id=requirement_id,
                    run_id=run.id,
                    terminal_id=terminal.id,
                    team_id=self.team_id,
                    original_collector_no=(
                        f"{_MANUAL_DEMAND_INTERNAL_PREFIX}{uuid4().hex}"
                    ),
                    status="unmatched",
                    sort_order=current_max_sort + offset + 1,
                    diagnostics=[
                        {
                            "code": _MANUAL_DEMAND_DIAGNOSTIC_CODE,
                            "label": _MANUAL_DEMAND_LABEL,
                        }
                    ],
                )
            )
        self.session.add_all(new_requirements)

        try:
            self.session.flush()
            locked_requirements = list(
                self.session.scalars(
                    select(CollectorRequirement)
                    .where(
                        CollectorRequirement.id.in_(requirement_ids),
                        CollectorRequirement.run_id == run.id,
                        CollectorRequirement.terminal_id == terminal.id,
                        CollectorRequirement.team_id == self.team_id,
                    )
                    .order_by(
                        CollectorRequirement.sort_order,
                        CollectorRequirement.id,
                    )
                    .with_for_update()
                ).all()
            )
            result = self._allocate_locked_requirements(
                run=run,
                requirements=locked_requirements,
            )
        except Exception:
            self.session.rollback()
            raise

        terminal.collector_requirement_count += quantity
        run_stats = dict(run.stats or {})
        run_stats["collector_requirement_count"] = int(
            run_stats.get("collector_requirement_count") or 0
        ) + quantity
        run.stats = run_stats
        run.status = "allocated"
        self._refresh_allocation_stats(run)
        self._refresh_terminal_item_progress(
            terminal,
            preserve_blocked=True,
        )
        self._audit(
            action="collector_workbench.manual_demand_added",
            entity_type="collector_transfer_terminal",
            entity_id=terminal.id,
            project_id=run.project_id,
            payload={
                "run_id": str(run.id),
                "terminal_id": str(terminal.id),
                "quantity": quantity,
                "assigned": len(result),
                "assigned_by": self.actor,
                "assignments": result,
            },
        )
        self.session.commit()
        return {
            "run_id": str(run.id),
            "terminal_id": str(terminal.id),
            "required": quantity,
            "assigned": len(result),
            "assignments": result,
        }

    def refresh_global_terminal(self, *, terminal_id: str) -> dict[str, object]:
        terminal_uuid = _uuid(terminal_id, "terminal_id")
        terminal_ref = self.session.execute(
            select(
                CollectorTransferTerminal.run_id,
                CollectorTransferTerminal.terminal_code,
                CollectorTransferRun.project_id,
            )
            .join(
                CollectorTransferRun,
                CollectorTransferRun.id == CollectorTransferTerminal.run_id,
            )
            .where(
                CollectorTransferTerminal.id == terminal_uuid,
                CollectorTransferTerminal.team_id == self.team_id,
                CollectorTransferRun.team_id == self.team_id,
            )
        ).one_or_none()
        if terminal_ref is None:
            raise KeyError(terminal_id)

        self._lock_global_terminal_identity(
            project_id=terminal_ref.project_id,
            terminal_code=terminal_ref.terminal_code,
        )
        run = self._run(str(terminal_ref.run_id), lock=True)
        stats = dict(run.stats or {})
        if (
            stats.get("workflow_kind") != "global_terminal_workbench"
            or bool(stats.get("superseded"))
        ):
            raise KeyError(terminal_id)
        terminal = self.session.scalar(
            select(CollectorTransferTerminal)
            .where(
                CollectorTransferTerminal.id == terminal_uuid,
                CollectorTransferTerminal.run_id == run.id,
                CollectorTransferTerminal.team_id == self.team_id,
            )
            .with_for_update()
        )
        if terminal is None:
            raise KeyError(terminal_id)

        completed_count = int(
            self.session.scalar(
                select(func.count(CollectorWorkbenchItem.id)).where(
                    CollectorWorkbenchItem.run_id == run.id,
                    CollectorWorkbenchItem.terminal_id == terminal.id,
                    CollectorWorkbenchItem.status == "completed",
                )
            )
            or 0
        )
        active_assignment_count = int(
            self.session.scalar(
                select(func.count(CollectorAssignment.id))
                .join(
                    CollectorRequirement,
                    CollectorRequirement.id == CollectorAssignment.requirement_id,
                )
                .where(
                    CollectorAssignment.run_id == run.id,
                    CollectorAssignment.team_id == self.team_id,
                    CollectorAssignment.status.in_(("reserved", "used")),
                    CollectorRequirement.terminal_id == terminal.id,
                )
            )
            or 0
        )
        if completed_count or active_assignment_count:
            raise CollectorSnapshotChangedError(
                "snapshot has progress; undo completions and roll back assignments first"
            )
        self._require_terminal_rephoto_ready(run=run, terminal=terminal)

        return self.open_global_terminal(
            project_id=str(run.project_id),
            terminal_code=terminal.terminal_code,
            source_revision=normalize_identifier(stats.get("source_revision")),
            terminal_key_value=terminal_key(
                str(run.project_id),
                terminal.terminal_code,
            ),
            force_refresh=True,
        )

    def rollback_assignment(self, *, assignment_id: str) -> dict[str, object]:
        assignment_uuid = _uuid(assignment_id, "assignment_id")
        assignment_ref = self.session.execute(
            select(
                CollectorAssignment.run_id,
                CollectorAssignment.requirement_id,
                CollectorAssignment.physical_collector_id,
                CollectorAssignment.collector_photo_id,
                CollectorAssignment.status,
            ).where(
                CollectorAssignment.id == assignment_uuid,
                CollectorAssignment.team_id == self.team_id,
            )
        ).one_or_none()
        if assignment_ref is None:
            raise KeyError(assignment_id)
        requirement_ref = self.session.execute(
            select(
                CollectorRequirement.run_id,
                CollectorRequirement.terminal_id,
            ).where(
                CollectorRequirement.id == assignment_ref.requirement_id,
                CollectorRequirement.team_id == self.team_id,
            )
        ).one_or_none()
        if requirement_ref is None or requirement_ref.run_id != assignment_ref.run_id:
            raise ValueError("assignment resources are missing")
        terminal_identity = self.session.execute(
            select(
                CollectorTransferRun.project_id,
                CollectorTransferRun.stats,
                CollectorTransferTerminal.terminal_code,
            )
            .join(
                CollectorTransferRun,
                CollectorTransferRun.id == CollectorTransferTerminal.run_id,
            )
            .where(
                CollectorTransferTerminal.id == requirement_ref.terminal_id,
                CollectorTransferTerminal.run_id == assignment_ref.run_id,
                CollectorTransferTerminal.team_id == self.team_id,
                CollectorTransferRun.team_id == self.team_id,
            )
        ).one_or_none()
        if terminal_identity is None:
            raise ValueError("assignment resources are missing")

        # Canonical mutation lock order:
        # advisory terminal identity -> run -> terminal -> source evidence ->
        # requirement -> physical -> assignment -> workbench item.
        is_global_terminal_workbench = (
            (terminal_identity.stats or {}).get("workflow_kind")
            == "global_terminal_workbench"
        )
        if is_global_terminal_workbench:
            self._lock_global_terminal_identity(
                project_id=terminal_identity.project_id,
                terminal_code=terminal_identity.terminal_code,
            )
        run = self._run(str(assignment_ref.run_id), lock=True)
        terminal = self.session.scalar(
            select(CollectorTransferTerminal)
            .where(
                CollectorTransferTerminal.id == requirement_ref.terminal_id,
                CollectorTransferTerminal.run_id == run.id,
                CollectorTransferTerminal.team_id == self.team_id,
            )
            .with_for_update()
        )
        if terminal is None:
            raise ValueError("assignment resources are missing")
        if is_global_terminal_workbench:
            self._require_terminal_rephoto_ready(run=run, terminal=terminal)
        if assignment_ref.status == "rolled_back":
            return {
                "assignment_id": str(assignment_uuid),
                "run_id": str(assignment_ref.run_id),
                "status": "rolled_back",
            }
        requirement = self.session.scalar(
            select(CollectorRequirement)
            .where(
                CollectorRequirement.id == assignment_ref.requirement_id,
                CollectorRequirement.run_id == run.id,
                CollectorRequirement.terminal_id == requirement_ref.terminal_id,
                CollectorRequirement.team_id == self.team_id,
            )
            .with_for_update()
        )
        physical = self.session.scalar(
            select(PhysicalCollector)
            .where(
                PhysicalCollector.id == assignment_ref.physical_collector_id,
                PhysicalCollector.team_id == self.team_id,
            )
            .with_for_update()
        )
        if requirement is None or physical is None:
            raise ValueError("assignment resources are missing")
        assignment = self.session.scalar(
            select(CollectorAssignment)
            .where(
                CollectorAssignment.id == assignment_uuid,
                CollectorAssignment.run_id == run.id,
                CollectorAssignment.requirement_id == requirement.id,
                CollectorAssignment.physical_collector_id == physical.id,
                CollectorAssignment.team_id == self.team_id,
            )
            .with_for_update()
        )
        if assignment is None:
            raise KeyError(assignment_id)
        if assignment.status == "rolled_back":
            return {
                "assignment_id": str(assignment.id),
                "run_id": str(assignment.run_id),
                "status": "rolled_back",
            }
        workbench_items = list(
            self.session.scalars(
                select(CollectorWorkbenchItem)
                .where(
                    CollectorWorkbenchItem.assignment_id == assignment.id,
                    CollectorWorkbenchItem.run_id == run.id,
                    CollectorWorkbenchItem.terminal_id == terminal.id,
                    CollectorWorkbenchItem.team_id == self.team_id,
                )
                .order_by(CollectorWorkbenchItem.id)
                .with_for_update()
            ).all()
        )
        photos = list(
            self.session.scalars(
                select(CollectorPhoto)
                .where(
                    CollectorPhoto.team_id == self.team_id,
                    CollectorPhoto.physical_collector_id == physical.id,
                )
                .order_by(CollectorPhoto.id)
                .with_for_update()
            ).all()
        )
        assignment_photo = next(
            (photo for photo in photos if photo.id == assignment.collector_photo_id),
            None,
        )
        if assignment_photo is None:
            raise ValueError("assignment photo is missing")
        self._validate_inventory_ownership(
            run=run,
            physical=physical,
            photo=assignment_photo,
        )

        assignment.status = "rolled_back"
        assignment.used_at = None
        active_photo = next((photo for photo in photos if photo.is_active), None)
        if active_photo is not None:
            self._validate_inventory_ownership(
                run=run,
                physical=physical,
                photo=active_photo,
            )
        has_photo = active_photo is not None
        if assignment.assignment_mode == "direct":
            requirement.status = "direct_ready" if has_photo else "direct_pending_photo"
            physical.pool_status = "direct"
        else:
            requirement.status = "unmatched"
            physical.pool_status = "available" if has_photo else "awaiting_photo"
        for item in workbench_items:
            self.session.delete(item)
        self.session.flush()

        self._refresh_terminal_item_progress(
            terminal,
            preserve_blocked=False,
        )

        stats = self._refresh_allocation_stats(run)
        run.status = "allocated" if stats["assignment_count"] else "inventory"
        self._audit(
            action="collector_transfer.assignment_rolled_back",
            entity_type="collector_assignment",
            entity_id=assignment.id,
            project_id=run.project_id,
            payload={
                "run_id": str(run.id),
                "terminal_id": str(terminal.id),
                "requirement_id": str(requirement.id),
                "physical_collector_id": str(physical.id),
                "mode": assignment.assignment_mode,
                "removed_workbench_items": len(workbench_items),
            },
        )
        self.session.commit()
        return {
            "assignment_id": str(assignment.id),
            "run_id": str(run.id),
            "status": "rolled_back",
            "stats": stats,
        }

    def list_workbench(self, *, run_id: str) -> dict[str, object]:
        run = self._run(run_id)
        terminals = self.session.scalars(
            select(CollectorTransferTerminal)
            .where(CollectorTransferTerminal.run_id == run.id, CollectorTransferTerminal.team_id == self.team_id)
            .order_by(CollectorTransferTerminal.terminal_code, CollectorTransferTerminal.id)
        ).all()
        items = self.session.scalars(
            select(CollectorWorkbenchItem).where(
                CollectorWorkbenchItem.run_id == run.id,
                CollectorWorkbenchItem.team_id == self.team_id,
            )
        ).all()
        counts: dict[str, tuple[int, int]] = {}
        for terminal in terminals:
            terminal_items = [item for item in items if item.terminal_id == terminal.id]
            counts[str(terminal.id)] = (
                sum(item.status == "completed" for item in terminal_items),
                len(terminal_items),
            )
        return {
            "run": self._run_summary(run),
            "terminals": [
                {
                    "id": str(terminal.id),
                    "terminal_code": terminal.terminal_code,
                    "installation_address": terminal.installation_address,
                    "status": terminal.status,
                    "meter_count": terminal.meter_count,
                    "collector_requirement_count": terminal.collector_requirement_count,
                    "completed_count": counts[str(terminal.id)][0],
                    "total_count": counts[str(terminal.id)][1],
                    "progress": (
                        round(counts[str(terminal.id)][0] * 100 / counts[str(terminal.id)][1])
                        if counts[str(terminal.id)][1]
                        else 0
                    ),
                    "diagnostics": list(terminal.diagnostics or []),
                }
                for terminal in terminals
            ],
        }

    def global_terminal_detail(self, *, terminal_id: str) -> dict[str, object]:
        terminal_uuid = _uuid(terminal_id, "terminal_id")
        terminal_ref = self.session.execute(
            select(
                CollectorTransferTerminal.run_id,
                CollectorTransferTerminal.team_id,
            ).where(
                CollectorTransferTerminal.id == terminal_uuid,
                CollectorTransferTerminal.team_id == self.team_id,
            )
        ).one_or_none()
        if terminal_ref is None:
            raise KeyError(terminal_id)
        run = self._run(str(terminal_ref.run_id))
        stats = dict(run.stats or {})
        if (
            stats.get("workflow_kind") != "global_terminal_workbench"
            or bool(stats.get("superseded"))
        ):
            raise KeyError(terminal_id)
        terminal = self.session.scalar(
            select(CollectorTransferTerminal).where(
                CollectorTransferTerminal.id == terminal_uuid,
                CollectorTransferTerminal.run_id == run.id,
                CollectorTransferTerminal.team_id == self.team_id,
            )
        )
        if terminal is None:
            raise KeyError(terminal_id)
        bound_count = self._reconcile_direct_requirements(
            run=run,
            terminal=terminal,
        )
        if bound_count:
            self._refresh_allocation_stats(run)
            self.session.commit()
            self.session.refresh(run)
            self.session.refresh(terminal)

        meter_rows = list(
            self.session.scalars(
                select(CollectorMeterItem)
                .where(
                    CollectorMeterItem.run_id == run.id,
                    CollectorMeterItem.terminal_id == terminal.id,
                    CollectorMeterItem.team_id == self.team_id,
                )
                .order_by(CollectorMeterItem.sort_order, CollectorMeterItem.id)
            ).all()
        )
        requirement_rows = list(
            self.session.scalars(
                select(CollectorRequirement)
                .where(
                    CollectorRequirement.run_id == run.id,
                    CollectorRequirement.terminal_id == terminal.id,
                    CollectorRequirement.team_id == self.team_id,
                )
                .order_by(CollectorRequirement.sort_order, CollectorRequirement.id)
            ).all()
        )
        workbench_rows = list(
            self.session.scalars(
                select(CollectorWorkbenchItem)
                .where(
                    CollectorWorkbenchItem.run_id == run.id,
                    CollectorWorkbenchItem.terminal_id == terminal.id,
                    CollectorWorkbenchItem.team_id == self.team_id,
                )
                .order_by(
                    CollectorWorkbenchItem.sort_order,
                    CollectorWorkbenchItem.id,
                )
            ).all()
        )
        meter_items_by_id = {
            item.meter_item_id: item
            for item in workbench_rows
            if item.meter_item_id is not None
        }
        requirement_items_by_id = {
            item.requirement_id: item
            for item in workbench_rows
            if item.requirement_id is not None
        }
        requirement_ids = [row.id for row in requirement_rows]
        assignments = (
            list(
                self.session.scalars(
                    select(CollectorAssignment)
                    .where(
                        CollectorAssignment.team_id == self.team_id,
                        CollectorAssignment.run_id == run.id,
                        CollectorAssignment.requirement_id.in_(requirement_ids),
                        CollectorAssignment.status.in_(("reserved", "used")),
                    )
                    .order_by(CollectorAssignment.id)
                ).all()
            )
            if requirement_ids
            else []
        )
        assignment_by_requirement = {
            assignment.requirement_id: assignment
            for assignment in assignments
        }
        physical_ids = [assignment.physical_collector_id for assignment in assignments]
        photo_ids = [assignment.collector_photo_id for assignment in assignments]
        physicals = (
            list(
                self.session.scalars(
                    select(PhysicalCollector).where(
                        PhysicalCollector.team_id == self.team_id,
                        PhysicalCollector.id.in_(physical_ids),
                        _public_collector_number_clause(),
                    )
                ).all()
            )
            if physical_ids
            else []
        )
        collector_photos = (
            list(
                self.session.scalars(
                    select(CollectorPhoto).where(
                        CollectorPhoto.team_id == self.team_id,
                        CollectorPhoto.id.in_(photo_ids),
                    )
                ).all()
            )
            if photo_ids
            else []
        )
        physical_by_id = {row.id: row for row in physicals}
        collector_photo_by_id = {row.id: row for row in collector_photos}

        meter_install_items: list[dict[str, object]] = []
        for meter in meter_rows:
            item = meter_items_by_id.get(meter.id)
            meter_install_items.append(
                {
                    "meter_item_id": str(meter.id),
                    "workbench_item_id": str(item.id) if item is not None else None,
                    "status": item.status if item is not None else None,
                    "meter_no": meter.meter_no,
                    "meter_barcode": meter.meter_barcode,
                    "module_no": meter.module_no,
                    "module_barcode": meter.module_barcode,
                    "photos": [
                        {
                            "slot": "module_meter",
                            "label": "电表和模块",
                            "photo": _photo_response(
                                meter.module_meter_photo_snapshot
                            ),
                        },
                        {
                            "slot": "after_box",
                            "label": "改造完成",
                            "photo": _photo_response(
                                meter.after_box_photo_snapshot
                            ),
                        },
                    ],
                    "diagnostics": list(meter.diagnostics or []),
                }
            )

        collector_items: list[dict[str, object]] = []
        for requirement in requirement_rows:
            item = requirement_items_by_id.get(requirement.id)
            assignment = assignment_by_requirement.get(requirement.id)
            physical = (
                physical_by_id.get(assignment.physical_collector_id)
                if assignment is not None
                else None
            )
            photo = (
                collector_photo_by_id.get(assignment.collector_photo_id)
                if assignment is not None
                else None
            )
            is_random_replacement = (
                assignment is not None
                and assignment.assignment_mode == "random"
                and physical is not None
            )
            is_direct = (
                item is not None
                and item.assignment_id is None
                and requirement.status in {"direct_ready", "used"}
            ) or (
                assignment is not None
                and assignment.assignment_mode == "direct"
                and physical is not None
            )
            if is_random_replacement:
                physical_state = "replaced"
                final_collector_no = physical.collector_no
                collector_barcode = physical.collector_no
                capture_strategy = "screen_photo"
                response_photo = _photo_response(
                    photo if photo is not None and photo.is_active else None
                )
            elif is_direct:
                physical_state = "present"
                final_collector_no = requirement.original_collector_no
                collector_barcode = requirement.original_collector_no
                capture_strategy = "live_physical"
                response_photo = None
            else:
                physical_state = "missing"
                final_collector_no = None
                collector_barcode = None
                capture_strategy = "unavailable"
                response_photo = None
            collector_items.append(
                {
                    "requirement_id": str(requirement.id),
                    "workbench_item_id": str(item.id) if item is not None else None,
                    "status": item.status if item is not None else None,
                    "original_collector_no": _collector_requirement_label(requirement),
                    "physical_state": physical_state,
                    "final_collector_no": final_collector_no,
                    "collector_barcode": collector_barcode,
                    "capture_strategy": capture_strategy,
                    "assignment_id": (
                        str(assignment.id) if assignment is not None else None
                    ),
                    "photo": response_photo,
                    "diagnostics": list(requirement.diagnostics or []),
                }
            )

        available_pool_count = int(
            self.session.scalar(
                select(func.count(func.distinct(PhysicalCollector.id)))
                .join(
                    CollectorPhoto,
                    and_(
                        CollectorPhoto.physical_collector_id
                        == PhysicalCollector.id,
                        CollectorPhoto.team_id == self.team_id,
                        CollectorPhoto.is_active.is_(True),
                    ),
                )
                .where(
                    PhysicalCollector.team_id == self.team_id,
                    PhysicalCollector.project_id == run.project_id,
                    PhysicalCollector.pool_status == "available",
                    _public_collector_number_clause(),
                )
            )
            or 0
        )
        missing_count = sum(
            row["physical_state"] == "missing" for row in collector_items
        )
        completed_count = sum(
            item.status == "completed" for item in workbench_rows
        )
        total_count = len(meter_install_items) + len(collector_items)
        stored_revision = normalize_identifier(stats.get("source_revision"))
        try:
            current_bundle = self._terminal_review_bundle(
                project_id=run.project_id,
                terminal_code=terminal.terminal_code,
            )
            current_revision = current_bundle.projection.source_revision
        except (KeyError, TerminalNotFoundError):
            current_revision = ""
        return {
            "run_id": str(run.id),
            "project_id": str(run.project_id),
            "terminal": {
                "id": str(terminal.id),
                "terminal_code": terminal.terminal_code,
                "installation_address": terminal.installation_address,
                "status": terminal.status,
                "diagnostics": list(terminal.diagnostics or []),
            },
            "meter_install_items": meter_install_items,
            "collector_items": collector_items,
            "pool_summary": {
                "required": missing_count,
                "available": available_pool_count,
                "shortage": max(0, missing_count - available_pool_count),
            },
            "completed_count": completed_count,
            "total_count": total_count,
            "progress": (
                round(completed_count * 100 / total_count)
                if total_count
                else 0
            ),
            "source_revision": stored_revision,
            "current_source_revision": current_revision,
            "source_changed": current_revision != stored_revision,
        }

    def terminal_workbench(self, *, run_id: str, terminal_id: str) -> dict[str, object]:
        run = self._run(run_id)
        terminal = self.session.scalar(
            select(CollectorTransferTerminal).where(
                CollectorTransferTerminal.id == _uuid(terminal_id, "terminal_id"),
                CollectorTransferTerminal.run_id == run.id,
                CollectorTransferTerminal.team_id == self.team_id,
            )
        )
        if terminal is None:
            raise KeyError(terminal_id)
        items = self.session.scalars(
            select(CollectorWorkbenchItem)
            .where(
                CollectorWorkbenchItem.terminal_id == terminal.id,
                CollectorWorkbenchItem.team_id == self.team_id,
            )
            .order_by(CollectorWorkbenchItem.sort_order, CollectorWorkbenchItem.id)
        ).all()
        meter_ids = [item.meter_item_id for item in items if item.meter_item_id]
        meters = (
            self.session.scalars(select(CollectorMeterItem).where(CollectorMeterItem.id.in_(meter_ids))).all()
            if meter_ids
            else []
        )
        meters_by_id = {item.id: item for item in meters}
        assignment_ids = [item.assignment_id for item in items if item.assignment_id]
        assignments = (
            self.session.scalars(select(CollectorAssignment).where(CollectorAssignment.id.in_(assignment_ids))).all()
            if assignment_ids
            else []
        )
        assignments_by_id = {item.id: item for item in assignments}
        collector_ids = [item.physical_collector_id for item in assignments]
        collector_photo_ids = [item.collector_photo_id for item in assignments]
        physicals = (
            self.session.scalars(
                select(PhysicalCollector).where(
                    PhysicalCollector.id.in_(collector_ids),
                    PhysicalCollector.team_id == self.team_id,
                    PhysicalCollector.project_id == run.project_id,
                    _public_collector_number_clause(),
                )
            ).all()
            if collector_ids
            else []
        )
        collector_photos = (
            self.session.scalars(select(CollectorPhoto).where(CollectorPhoto.id.in_(collector_photo_ids))).all()
            if collector_photo_ids
            else []
        )
        physical_by_id = {item.id: item for item in physicals}
        collector_photo_by_id = {item.id: item for item in collector_photos}

        payload_items: list[dict[str, object]] = []
        for item in items:
            if item.item_kind == "meter_install" and item.meter_item_id in meters_by_id:
                meter_item = meters_by_id[item.meter_item_id]
                payload_items.append(
                    {
                        "id": str(item.id),
                        "kind": item.item_kind,
                        "status": item.status,
                        "meter_no": meter_item.meter_no,
                        "meter_barcode": meter_item.meter_barcode,
                        "module_no": meter_item.module_no,
                        "module_barcode": meter_item.module_barcode,
                        "photos": [
                            {
                                "slot": "module_meter",
                                "label": "电表和模块",
                                "photo": _photo_response(meter_item.module_meter_photo_snapshot),
                            },
                            {
                                "slot": "after_box",
                                "label": "改造完成",
                                "photo": _photo_response(meter_item.after_box_photo_snapshot),
                            },
                        ],
                    }
                )
            elif item.item_kind == "collector_removal" and item.assignment_id in assignments_by_id:
                assignment = assignments_by_id[item.assignment_id]
                physical = physical_by_id.get(assignment.physical_collector_id)
                payload_items.append(
                    {
                        "id": str(item.id),
                        "kind": item.item_kind,
                        "status": item.status,
                        "collector_no": physical.collector_no if physical else "",
                        "collector_barcode": physical.collector_no if physical else "",
                        "assignment_mode": assignment.assignment_mode,
                        "photos": [
                            {
                                "slot": "collector",
                                "label": "拆旧采集器",
                                "photo": _photo_response(collector_photo_by_id.get(assignment.collector_photo_id)),
                            }
                        ],
                    }
                )
        return {
            "run_id": str(run.id),
            "terminal": {
                "id": str(terminal.id),
                "terminal_code": terminal.terminal_code,
                "installation_address": terminal.installation_address,
                "status": terminal.status,
            },
            "items": payload_items,
        }

    def set_workbench_item_status(self, *, item_id: str, completed: bool) -> dict[str, object]:
        item_uuid = _uuid(item_id, "item_id")
        item_ref = self.session.execute(
            select(
                CollectorWorkbenchItem.run_id,
                CollectorWorkbenchItem.terminal_id,
                CollectorWorkbenchItem.requirement_id,
                CollectorWorkbenchItem.assignment_id,
                CollectorWorkbenchItem.meter_item_id,
                CollectorWorkbenchItem.item_kind,
            ).where(
                CollectorWorkbenchItem.id == item_uuid,
                CollectorWorkbenchItem.team_id == self.team_id,
            )
        ).one_or_none()
        if item_ref is None:
            raise KeyError(item_id)

        assignment_ref = (
            self.session.execute(
                select(
                    CollectorAssignment.requirement_id,
                    CollectorAssignment.physical_collector_id,
                    CollectorAssignment.collector_photo_id,
                    CollectorAssignment.assignment_mode,
                ).where(
                    CollectorAssignment.id == item_ref.assignment_id,
                    CollectorAssignment.team_id == self.team_id,
                )
            ).one_or_none()
            if item_ref.assignment_id is not None
            else None
        )
        if item_ref.assignment_id is not None and assignment_ref is None:
            raise CollectorWorkbenchIncompleteError(("拆除分配不存在或已失效",))
        terminal_identity = self.session.execute(
            select(
                CollectorTransferRun.project_id,
                CollectorTransferRun.stats,
                CollectorTransferTerminal.terminal_code,
            )
            .join(
                CollectorTransferRun,
                CollectorTransferRun.id == CollectorTransferTerminal.run_id,
            )
            .where(
                CollectorTransferTerminal.id == item_ref.terminal_id,
                CollectorTransferTerminal.run_id == item_ref.run_id,
                CollectorTransferTerminal.team_id == self.team_id,
                CollectorTransferRun.team_id == self.team_id,
            )
        ).one_or_none()
        if terminal_identity is None:
            raise CollectorWorkbenchIncompleteError(("终端快照不存在",))

        # Canonical mutation lock order:
        # advisory terminal identity -> run -> terminal -> source evidence ->
        # requirement -> physical -> assignment -> workbench item.
        is_global_terminal_workbench = (
            (terminal_identity.stats or {}).get("workflow_kind")
            == "global_terminal_workbench"
        )
        if is_global_terminal_workbench:
            self._lock_global_terminal_identity(
                project_id=terminal_identity.project_id,
                terminal_code=terminal_identity.terminal_code,
            )
        run = self._run(str(item_ref.run_id), lock=True)
        terminal = self.session.scalar(
            select(CollectorTransferTerminal)
            .where(
                CollectorTransferTerminal.id == item_ref.terminal_id,
                CollectorTransferTerminal.run_id == run.id,
                CollectorTransferTerminal.team_id == self.team_id,
            )
            .with_for_update()
        )
        if terminal is None:
            raise CollectorWorkbenchIncompleteError(("终端快照不存在",))
        if is_global_terminal_workbench:
            self._require_terminal_rephoto_ready(run=run, terminal=terminal)

        requirement_id = item_ref.requirement_id or (
            assignment_ref.requirement_id if assignment_ref is not None else None
        )
        requirement = (
            self.session.scalar(
                select(CollectorRequirement)
                .where(
                    CollectorRequirement.id == requirement_id,
                    CollectorRequirement.run_id == run.id,
                    CollectorRequirement.team_id == self.team_id,
                )
                .with_for_update()
            )
            if requirement_id is not None
            else None
        )
        physical = None
        if assignment_ref is not None:
            physical = self.session.scalar(
                select(PhysicalCollector)
                .where(
                    PhysicalCollector.id == assignment_ref.physical_collector_id,
                    PhysicalCollector.team_id == self.team_id,
                )
                .with_for_update()
            )
        elif (
            item_ref.item_kind == "collector_removal"
            and requirement is not None
        ):
            physical = self.session.scalar(
                select(PhysicalCollector)
                .where(
                    PhysicalCollector.team_id == self.team_id,
                    PhysicalCollector.project_id == run.project_id,
                    PhysicalCollector.collector_no
                    == requirement.original_collector_no,
                )
                .with_for_update()
            )

        assignment = (
            self.session.scalar(
                select(CollectorAssignment)
                .where(
                    CollectorAssignment.id == item_ref.assignment_id,
                    CollectorAssignment.run_id == run.id,
                    CollectorAssignment.team_id == self.team_id,
                )
                .with_for_update()
            )
            if item_ref.assignment_id is not None
            else None
        )
        item = self.session.scalar(
            select(CollectorWorkbenchItem)
            .where(
                CollectorWorkbenchItem.id == item_uuid,
                CollectorWorkbenchItem.run_id == run.id,
                CollectorWorkbenchItem.team_id == self.team_id,
            )
            .with_for_update()
        )
        if item is None:
            raise KeyError(item_id)

        meter: CollectorMeterItem | None = None
        photo: CollectorPhoto | None = None
        if item.item_kind == "meter_install" and item.meter_item_id:
            meter = self.session.scalar(
                select(CollectorMeterItem)
                .where(
                    CollectorMeterItem.id == item.meter_item_id,
                    CollectorMeterItem.run_id == run.id,
                    CollectorMeterItem.team_id == self.team_id,
                )
                .with_for_update()
            )
        elif assignment is not None:
            photo = self.session.scalar(
                select(CollectorPhoto)
                .where(
                    CollectorPhoto.id == assignment.collector_photo_id,
                    CollectorPhoto.team_id == self.team_id,
                    CollectorPhoto.physical_collector_id == assignment.physical_collector_id,
                )
                .with_for_update()
            )
        if assignment is not None and physical is not None and photo is not None:
            self._validate_inventory_ownership(run=run, physical=physical, photo=photo)

        if (
            not completed
            and item.item_kind == "collector_removal"
            and assignment is None
            and (
                requirement is None
                or requirement.status not in {"direct_ready", "used"}
                or physical is None
                or physical.project_id != run.project_id
                or physical.pool_status not in {"direct", "used"}
                or physical.collector_no != requirement.original_collector_no
            )
        ):
            raise CollectorWorkbenchIncompleteError(("缺少已确认同号实物",))

        if completed:
            reasons: list[str] = []
            if terminal.status == "blocked":
                reasons.append("终端存在资料阻断")
            reasons.extend(
                normalize_identifier(diagnostic.get("message") or diagnostic.get("code"))
                for diagnostic in terminal.diagnostics or []
                if isinstance(diagnostic, Mapping)
                and normalize_identifier(diagnostic.get("message") or diagnostic.get("code"))
            )
            if item.item_kind == "meter_install":
                if meter is None:
                    reasons.append("新装表计快照不存在")
                else:
                    if not normalize_identifier(meter.meter_barcode):
                        reasons.append("缺少表号条形码")
                    if not normalize_identifier(meter.module_barcode):
                        reasons.append("缺少模块号条形码")
                    if not _snapshot_has_photo_evidence(meter.module_meter_photo_snapshot):
                        reasons.append("缺少电表和模块照片")
                    if not _snapshot_has_photo_evidence(meter.after_box_photo_snapshot):
                        reasons.append("缺少改造完成照片")
            elif item.item_kind == "collector_removal":
                if assignment is None:
                    if (
                        requirement is None
                        or requirement.status not in {"direct_ready", "used"}
                    ):
                        reasons.append("拆除采集器需求存在阻断")
                    if (
                        physical is None
                        or physical.project_id != run.project_id
                        or physical.pool_status not in {"direct", "used"}
                        or requirement is None
                        or physical.collector_no
                        != requirement.original_collector_no
                    ):
                        reasons.append("缺少已确认同号实物")
                else:
                    if assignment.status not in {"reserved", "used"}:
                        reasons.append("拆除分配不存在或已失效")
                    if physical is None or not normalize_identifier(
                        physical.collector_no
                    ):
                        reasons.append("缺少最终采集器号")
                    if requirement is None or requirement.status == "blocked":
                        reasons.append("拆除采集器需求存在阻断")
                    if (
                        photo is None
                        or not photo.is_active
                        or not _snapshot_has_photo_evidence(
                            {
                                "id": str(photo.id),
                                "storage_key": normalize_identifier(
                                    photo.object_key or photo.image_url
                                ),
                            }
                        )
                    ):
                        reasons.append("缺少有效采集器实物照片")
            if reasons:
                raise CollectorWorkbenchIncompleteError(reasons)

        old_item_status = item.status
        old_requirement_status = requirement.status if requirement is not None else None
        old_physical_status = physical.pool_status if physical is not None else None
        item.status = "completed" if completed else "pending"
        item.completed_at = datetime.now(UTC) if completed else None
        item.completed_by_id = self._actor_user_id() if completed else None
        item.completed_by_username = self.actor if completed else None
        if assignment is not None:
            assignment.status = "used" if completed else "reserved"
            assignment.used_at = datetime.now(UTC) if completed else None
            if physical is not None:
                physical.pool_status = "used" if completed else (
                    "direct" if assignment.assignment_mode == "direct" else "reserved"
                )
            if requirement is not None:
                requirement.status = "used" if completed else (
                    "direct_ready" if assignment.assignment_mode == "direct" else "assigned"
                )
        elif item.item_kind == "collector_removal":
            if requirement is None or physical is None:
                raise CollectorWorkbenchIncompleteError(("缺少已确认同号实物",))
            requirement.status = "used" if completed else "direct_ready"
            physical.pool_status = "used" if completed else "direct"
        self.session.flush()
        if terminal is not None:
            self._refresh_terminal_item_progress(
                terminal,
                preserve_blocked=True,
            )
        self._audit(
            action="collector_transfer.workbench_item_completed" if completed else "collector_transfer.workbench_item_reopened",
            entity_type="collector_workbench_item",
            entity_id=item.id,
            project_id=run.project_id,
            payload={
                "completed": completed,
                "run_id": str(run.id),
                "terminal_id": str(terminal.id),
                "requirement_id": (
                    str(requirement.id) if requirement is not None else None
                ),
                "physical_collector_id": (
                    str(physical.id) if physical is not None else None
                ),
                "mode": (
                    assignment.assignment_mode
                    if assignment is not None
                    else (
                        "direct"
                        if item.item_kind == "collector_removal"
                        else "meter_install"
                    )
                ),
                "old_item_status": old_item_status,
                "new_item_status": item.status,
                "old_requirement_status": old_requirement_status,
                "new_requirement_status": (
                    requirement.status if requirement is not None else None
                ),
                "old_physical_status": old_physical_status,
                "new_physical_status": (
                    physical.pool_status if physical is not None else None
                ),
            },
        )
        self.session.commit()
        return {"id": str(item.id), "status": item.status, "completed_at": item.completed_at.isoformat() if item.completed_at else None}
