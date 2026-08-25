from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

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
    decide_collector_scan,
    decide_project_inventory_scan,
    normalize_identifier,
    plan_random_assignments,
    terminal_key,
    terminal_source_revision,
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
    MaterialGroup,
    Photo,
    PhysicalCollector,
    Project,
    ProjectStatus,
    TotalCatalogRow,
    User,
)
from app.services.photo_storage import resolve_photo_for_response


class CollectorAllocationConflictError(ValueError):
    """A database uniqueness backstop rejected an allocation after the service acquired its locks."""


class CollectorRunBlockedError(ValueError):
    """Allocation was rejected because the run contains blocked terminal evidence."""


class CollectorPhotoConflictError(ValueError):
    """Photo content is already bound to a different physical collector."""


class CollectorScanProvenanceError(ValueError):
    """Photo registration was not preceded by a scan in the same run."""


class CollectorDirectConflictError(ValueError):
    """A direct physical collector is already owned by another active terminal."""


class CollectorSnapshotChangedError(ValueError):
    """A hidden terminal snapshot cannot be refreshed while progress remains."""


class CollectorWorkbenchIncompleteError(ValueError):
    """Workbench completion was rejected because authoritative evidence is incomplete."""

    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__("；".join(self.reasons) or "翻拍工作项资料不完整")


_MISSING_TERMINAL_PREFIX = "__missing_terminal__:"
_IDENTIFIER_BOUNDARY_WHITESPACE = (
    "\t\n\v\f\r\x1c\x1d\x1e\x1f \x85\xa0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000"
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
    terminal: str | None
    display_meter_no: str
    installation_address: str
    raw_data: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _GlobalTerminalGroupRow:
    project_id: UUID
    id: UUID
    terminal: str | None
    display_meter_no: str
    installation_address: str
    raw_data: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _ProjectPhotoRow:
    id: UUID
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
    addresses = sorted(
        {
            normalize_identifier(source.installation_address)
            for source in projection.sources
            if normalize_identifier(source.installation_address)
        }
    )
    diagnostics = list(projection.diagnostics)
    if not addresses:
        diagnostics.append(
            {
                "group_id": "",
                "code": "installation_address_missing",
                "message": "安装地址为空",
            }
        )
    elif len(addresses) > 1:
        diagnostics.append(
            {
                "group_id": "",
                "code": "installation_address_conflict",
                "message": "安装地址冲突：" + "、".join(addresses),
            }
        )
    return MeterSourceProjection(
        sources=projection.sources,
        diagnostics=tuple(diagnostics),
    )


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
                MaterialGroup.terminal,
                MaterialGroup.display_meter_no,
                MaterialGroup.installation_address,
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
                    normalized_terminal,
                    MaterialGroup.display_meter_no,
                    authoritative_address,
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
        allowed_states = {"ready", "needs_replacement", "pool_shortage", "blocked"}
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
        address_count = func.count(
            func.distinct(func.nullif(authoritative_address, ""))
        )
        incomplete_count = func.sum(
            case((complete_source, 0), else_=1)
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
                            ),
                            1,
                        ),
                        else_=0,
                    )
                )
                > 0
            )
        if normalized_state == "blocked":
            grouped_identity = grouped_identity.having(
                or_(incomplete_count > 0, address_count != 1)
            )
        elif not include_blocked or normalized_state is not None:
            grouped_identity = grouped_identity.having(
                incomplete_count == 0,
                address_count == 1,
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
                    normalized_terminal,
                    MaterialGroup.display_meter_no,
                    authoritative_address,
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

        source_payloads: dict[tuple[UUID, str], dict[str, object]] = {}
        collector_pairs: list[tuple[UUID, str]] = []
        for key in candidate_keys:
            projection = _with_terminal_address_diagnostics(
                meter_sources_from_groups(
                    groups_by_key.get(key, ()),
                    photos_by_key.get(key, ()),
                )
            )
            snapshots = build_terminal_snapshots(projection.sources)
            snapshot = snapshots[0] if snapshots else None
            requirements = (
                tuple(
                    normalize_identifier(item.original_collector_no)
                    for item in snapshot.collector_requirements
                )
                if snapshot is not None
                else ()
            )
            collector_pairs.extend((key[0], collector_no) for collector_no in requirements)
            source_payloads[key] = {
                "projection": projection,
                "snapshot": snapshot,
                "requirements": requirements,
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
            snapshot = payload["snapshot"]
            requirements = tuple(payload["requirements"])
            addresses = sorted(
                {
                    normalize_identifier(source.installation_address)
                    for source in projection.sources
                    if normalize_identifier(source.installation_address)
                }
            )
            diagnostics = list(projection.diagnostics)

            claimed_numbers = set(progressed_claims.get(key, set()))
            for original_collector_no in requirements:
                if direct_claims.get((project_id, original_collector_no)):
                    claimed_numbers.add(original_collector_no)
            physical_count = len(set(requirements) & claimed_numbers)
            missing_count = max(0, len(requirements) - physical_count)
            pool_available_count = pool_counts.get(project_id, 0)
            if diagnostics:
                workflow_state = "blocked"
            elif missing_count == 0:
                workflow_state = "ready"
            elif pool_available_count >= missing_count:
                workflow_state = "needs_replacement"
            else:
                workflow_state = "pool_shortage"

            candidate = {
                "terminal_key": terminal_key(str(project_id), terminal_code),
                "project_id": str(project_id),
                "project_name": normalize_identifier(identity["project_name"]),
                "project_code": normalize_identifier(identity["project_code"]),
                "terminal_code": terminal_code,
                "installation_address": "、".join(addresses),
                "needs_disambiguation": int(identity["project_count"] or 0) > 1,
                "meter_count": len(snapshot.meters) if snapshot is not None else 0,
                "collector_count": len(requirements),
                "physical_count": physical_count,
                "missing_count": missing_count,
                "pool_available_count": pool_available_count,
                "workflow_state": workflow_state,
                "selectable": workflow_state != "blocked",
                "source_revision": _projection_source_revision(
                    project_id=project_id,
                    terminal_code=terminal_code,
                    projection=projection,
                    photos=photos_by_key.get(key, ()),
                ),
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
        projection, photos = self._global_terminal_projection(
            project_id=project.id,
            terminal_code=normalized_code,
        )
        if projection.diagnostics:
            raise CollectorRunBlockedError("terminal source is blocked")
        current_revision = _projection_source_revision(
            project_id=project.id,
            terminal_code=normalized_code,
            projection=projection,
            photos=photos,
        )
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

    def scan_inventory(self, *, project_id: str, collector_no: str) -> dict[str, object]:
        project = self._project(project_id)
        normalized_no = normalize_identifier(collector_no)
        if not normalized_no:
            raise ValueError("collector_no is required")

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
        normalized_no = normalize_identifier(collector_no)
        if not normalized_no:
            raise ValueError("collector_no is required")
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
        items = []
        for row in rows:
            photo = self._active_collector_photo(row.id)
            items.append(
                {
                    "collector_id": str(row.id),
                    "collector_no": row.collector_no,
                    "pool_status": row.pool_status,
                    "photo": _photo_response(photo),
                    "last_scanned_at": row.last_scanned_at.isoformat() if row.last_scanned_at else None,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
            )
        return {"items": items, "total": len(rows), "stats": stats}

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
                if normalize_identifier(requirement.original_collector_no)
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
            if requirement.original_collector_no
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
        normalized_no = normalize_identifier(collector_no)
        if not normalized_no:
            raise ValueError("collector_no is required")
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
        run = self._run(run_id, lock=True)
        if (run.stats or {}).get("workflow_kind") == "global_terminal_workbench":
            raise CollectorRunBlockedError(
                "global terminal workbench requires terminal-scoped replacement"
            )
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
                    "original_collector_no": requirement.original_collector_no,
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

    def replace_terminal_missing(self, *, terminal_id: str) -> dict[str, object]:
        terminal_uuid = _uuid(terminal_id, "terminal_id")
        terminal_ref = self.session.execute(
            select(
                CollectorTransferTerminal.run_id,
                CollectorTransferTerminal.id,
            ).where(
                CollectorTransferTerminal.id == terminal_uuid,
                CollectorTransferTerminal.team_id == self.team_id,
            )
        ).one_or_none()
        if terminal_ref is None:
            raise KeyError(terminal_id)

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
        if terminal.status == "blocked":
            raise CollectorRunBlockedError("终端存在资料阻断，不能执行随机替换")
        current_projection, current_photos = self._global_terminal_projection(
            project_id=run.project_id,
            terminal_code=terminal.terminal_code,
        )
        if current_projection.diagnostics:
            raise CollectorRunBlockedError("终端当前来源存在资料阻断")
        current_revision = _projection_source_revision(
            project_id=run.project_id,
            terminal_code=terminal.terminal_code,
            projection=current_projection,
            photos=current_photos,
        )
        if current_revision != normalize_identifier(stats.get("source_revision")):
            raise CollectorSnapshotChangedError(
                "terminal source changed; refresh the snapshot before replacement"
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

        physical_collectors = list(
            self.session.scalars(
                select(PhysicalCollector)
                .where(
                    PhysicalCollector.team_id == self.team_id,
                    PhysicalCollector.project_id == run.project_id,
                    PhysicalCollector.pool_status == "available",
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
                    .order_by(CollectorPhoto.physical_collector_id, CollectorPhoto.id)
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
            assignment, _created = self._create_assignment(
                run=run,
                requirement=requirement,
                physical=physical,
                photo=photo,
                assignment_mode="random",
            )
            requirement.status = "assigned"
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
                    "original_collector_no": requirement.original_collector_no,
                    "physical_collector_id": physical_id,
                    "final_collector_no": physical.collector_no,
                    "mode": "random",
                }
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

        projection, photos = self._global_terminal_projection(
            project_id=run.project_id,
            terminal_code=terminal.terminal_code,
        )
        current_revision = _projection_source_revision(
            project_id=run.project_id,
            terminal_code=terminal.terminal_code,
            projection=projection,
            photos=photos,
        )
        return self.open_global_terminal(
            project_id=str(run.project_id),
            terminal_code=terminal.terminal_code,
            source_revision=current_revision,
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
        if assignment_ref.status == "rolled_back":
            return {
                "assignment_id": str(assignment_uuid),
                "run_id": str(assignment_ref.run_id),
                "status": "rolled_back",
            }
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

        # Canonical mutation lock order:
        # run -> terminal -> requirement -> physical -> assignment -> item -> evidence.
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
        if terminal is None or requirement is None or physical is None:
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

        total = int(
            self.session.scalar(
                select(func.count(CollectorWorkbenchItem.id)).where(
                    CollectorWorkbenchItem.terminal_id == terminal.id
                )
            )
            or 0
        )
        completed_count = int(
            self.session.scalar(
                select(func.count(CollectorWorkbenchItem.id)).where(
                    CollectorWorkbenchItem.terminal_id == terminal.id,
                    CollectorWorkbenchItem.status == "completed",
                )
            )
            or 0
        )
        terminal.completed_item_count = completed_count
        terminal.status = "ready" if completed_count == 0 else (
            "completed" if total and completed_count >= total else "in_progress"
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
                    "original_collector_no": requirement.original_collector_no,
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
            current_projection, current_photos = self._global_terminal_projection(
                project_id=run.project_id,
                terminal_code=terminal.terminal_code,
            )
            current_revision = _projection_source_revision(
                project_id=run.project_id,
                terminal_code=terminal.terminal_code,
                projection=current_projection,
                photos=current_photos,
            )
        except KeyError:
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
            self.session.scalars(select(PhysicalCollector).where(PhysicalCollector.id.in_(collector_ids))).all()
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

        # Canonical mutation lock order:
        # run -> terminal -> requirement -> physical -> assignment -> item -> evidence.
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
        total = int(
            self.session.scalar(
                select(func.count(CollectorWorkbenchItem.id)).where(
                    CollectorWorkbenchItem.terminal_id == item.terminal_id
                )
            )
            or 0
        )
        completed_count = int(
            self.session.scalar(
                select(func.count(CollectorWorkbenchItem.id)).where(
                    CollectorWorkbenchItem.terminal_id == item.terminal_id,
                    CollectorWorkbenchItem.status == "completed",
                )
            )
            or 0
        )
        if terminal is not None:
            terminal.completed_item_count = completed_count
            if terminal.status != "blocked":
                terminal.status = (
                    "ready"
                    if completed_count == 0
                    else ("completed" if total and completed_count >= total else "in_progress")
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
