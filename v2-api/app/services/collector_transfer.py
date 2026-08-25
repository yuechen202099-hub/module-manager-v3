from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import String, exists, func, or_, select
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

    def create_run(self, *, project_id: str, name: str) -> dict[str, object]:
        project = self._project(project_id)
        project_uuid = project.id
        projection, photos = self._project_meter_projection(project_uuid)
        source_photos_by_id = {str(photo.id): photo for photo in photos}
        snapshots = build_terminal_snapshots(projection.sources)
        run = CollectorTransferRun(
            team_id=self.team_id,
            project_id=project_uuid,
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

        requirement_count = 0
        blocked_terminal_count = 0
        for terminal_index, snapshot in enumerate(snapshots):
            terminal_diagnostics = [
                diagnostic
                for meter_source in snapshot.meters
                for diagnostic in diagnostics_by_group.get(meter_source.group_id, [])
            ]
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

        run.stats = {
            "terminal_count": len(snapshots),
            "meter_count": len(projection.sources),
            "collector_requirement_count": requirement_count,
            "blocked_terminal_count": blocked_terminal_count,
            "direct_match_count": 0,
            "pool_available_count": 0,
            "assignment_count": 0,
        }
        self._bind_direct_inventory(run)
        self._refresh_allocation_stats(run)
        self._audit(
            action="collector_transfer.run_created",
            entity_type="collector_transfer_run",
            entity_id=run.id,
            project_id=project_uuid,
            payload=dict(run.stats),
        )
        self.session.commit()
        self.session.refresh(run)
        return self._run_summary(run)

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
                    PhysicalCollector.pool_status.in_(("direct", "available")),
                )
                .order_by(PhysicalCollector.collector_no, PhysicalCollector.id)
                .with_for_update()
            ).all()
        )
        physical_by_number = {item.collector_no: item for item in physical_collectors}
        physical_by_id = {item.id: item for item in physical_collectors}
        photos_by_collector: dict[UUID, CollectorPhoto] = {}
        if physical_collectors:
            photos = self.session.scalars(
                select(CollectorPhoto)
                .where(
                    CollectorPhoto.team_id == self.team_id,
                    CollectorPhoto.physical_collector_id.in_(
                        [item.id for item in physical_collectors]
                    ),
                    CollectorPhoto.is_active.is_(True),
                )
                .order_by(
                    CollectorPhoto.physical_collector_id,
                    CollectorPhoto.created_at.desc(),
                    CollectorPhoto.id.desc(),
                )
                .with_for_update()
            ).all()
            for photo in photos:
                physical = physical_by_id[photo.physical_collector_id]
                self._validate_inventory_ownership(run=run, physical=physical, photo=photo)
                photos_by_collector.setdefault(photo.physical_collector_id, photo)

        bound_count = 0
        consumed_physical_ids: set[UUID] = set()
        for requirement in requirements:
            physical = physical_by_number.get(requirement.original_collector_no)
            if physical is None or physical.id in consumed_physical_ids:
                continue
            physical.pool_status = "direct"
            photo = photos_by_collector.get(physical.id)
            if photo is None:
                requirement.status = "direct_pending_photo"
                consumed_physical_ids.add(physical.id)
                continue
            assignment, _created = self._create_assignment(
                run=run,
                requirement=requirement,
                physical=physical,
                photo=photo,
                assignment_mode="direct",
            )
            requirement.status = "direct_ready"
            self._ensure_removal_workbench_item(
                run=run,
                requirement=requirement,
                assignment=assignment,
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

    def rollback_assignment(self, *, assignment_id: str) -> dict[str, object]:
        assignment_uuid = _uuid(assignment_id, "assignment_id")
        run_id = self.session.scalar(
            select(CollectorAssignment.run_id).where(
                CollectorAssignment.id == assignment_uuid,
                CollectorAssignment.team_id == self.team_id,
            )
        )
        if run_id is None:
            raise KeyError(assignment_id)

        # Collector-transfer mutation lock order: run -> assignment -> workbench
        # -> requirement -> physical -> terminal -> evidence. Completion/undo use
        # the same order so PostgreSQL never sees the former inverted cycle.
        run = self._run(str(run_id), lock=True)
        assignment = self.session.scalar(
            select(CollectorAssignment)
            .where(
                CollectorAssignment.id == assignment_uuid,
                CollectorAssignment.run_id == run.id,
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
                    CollectorWorkbenchItem.team_id == self.team_id,
                )
                .order_by(CollectorWorkbenchItem.id)
                .with_for_update()
            ).all()
        )
        requirement = self.session.scalar(
            select(CollectorRequirement)
            .where(
                CollectorRequirement.id == assignment.requirement_id,
                CollectorRequirement.team_id == self.team_id,
            )
            .with_for_update()
        )
        physical = self.session.scalar(
            select(PhysicalCollector)
            .where(
                PhysicalCollector.id == assignment.physical_collector_id,
                PhysicalCollector.team_id == self.team_id,
            )
            .with_for_update()
        )
        if requirement is None or physical is None:
            raise ValueError("assignment resources are missing")
        terminal = self.session.scalar(
            select(CollectorTransferTerminal)
            .where(
                CollectorTransferTerminal.id == requirement.terminal_id,
                CollectorTransferTerminal.team_id == self.team_id,
            )
            .with_for_update()
        )
        assignment_photo = self.session.scalar(
            select(CollectorPhoto)
            .where(
                CollectorPhoto.id == assignment.collector_photo_id,
                CollectorPhoto.team_id == self.team_id,
                CollectorPhoto.physical_collector_id == physical.id,
            )
            .with_for_update()
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
        active_photo = self._active_collector_photo(physical.id)
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

        if terminal is not None:
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
            terminal.status = "ready" if not total else ("completed" if completed_count >= total else "in_progress")

        stats = self._refresh_allocation_stats(run)
        run.status = "allocated" if stats["assignment_count"] else "inventory"
        self._audit(
            action="collector_transfer.assignment_rolled_back",
            entity_type="collector_assignment",
            entity_id=assignment.id,
            project_id=run.project_id,
            payload={
                "run_id": str(run.id),
                "requirement_id": str(requirement.id),
                "physical_collector_id": str(physical.id),
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
                CollectorWorkbenchItem.assignment_id,
            ).where(
                CollectorWorkbenchItem.id == item_uuid,
                CollectorWorkbenchItem.team_id == self.team_id,
            )
        ).one_or_none()
        if item_ref is None:
            raise KeyError(item_id)

        # Keep the same mutation lock order documented in rollback_assignment.
        run = self._run(str(item_ref.run_id), lock=True)
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
            if item_ref.assignment_id
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

        requirement = (
            self.session.scalar(
                select(CollectorRequirement)
                .where(
                    CollectorRequirement.id == assignment.requirement_id,
                    CollectorRequirement.run_id == run.id,
                    CollectorRequirement.team_id == self.team_id,
                )
                .with_for_update()
            )
            if assignment is not None
            else None
        )
        physical = (
            self.session.scalar(
                select(PhysicalCollector)
                .where(
                    PhysicalCollector.id == assignment.physical_collector_id,
                    PhysicalCollector.team_id == self.team_id,
                )
                .with_for_update()
            )
            if assignment is not None
            else None
        )
        terminal = self.session.scalar(
            select(CollectorTransferTerminal)
            .where(
                CollectorTransferTerminal.id == item.terminal_id,
                CollectorTransferTerminal.run_id == run.id,
                CollectorTransferTerminal.team_id == self.team_id,
            )
            .with_for_update()
        )
        if terminal is None:
            raise CollectorWorkbenchIncompleteError(("终端快照不存在",))

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
                if assignment is None or assignment.status not in {"reserved", "used"}:
                    reasons.append("拆除分配不存在或已失效")
                if physical is None or not normalize_identifier(physical.collector_no):
                    reasons.append("缺少最终采集器号")
                if requirement is None or requirement.status == "blocked":
                    reasons.append("拆除采集器需求存在阻断")
                if (
                    photo is None
                    or not photo.is_active
                    or not _snapshot_has_photo_evidence(
                        {
                            "id": str(photo.id),
                            "storage_key": normalize_identifier(photo.object_key or photo.image_url),
                        }
                    )
                ):
                    reasons.append("缺少有效采集器实物照片")
            if reasons:
                raise CollectorWorkbenchIncompleteError(reasons)

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
            payload={"completed": completed},
        )
        self.session.commit()
        return {"id": str(item.id), "status": item.status, "completed_at": item.completed_at.isoformat() if item.completed_at else None}
