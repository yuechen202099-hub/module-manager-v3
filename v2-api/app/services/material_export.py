from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
import secrets
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.domain.collector_transfer import normalize_identifier
from app.domain.material_export import (
    MaterialExportIssue,
    MaterialExportMeter,
    collector_demand,
    preflight_fingerprint,
    project_module_issues,
    required_meter_issues,
)
from app.domain.terminal_review import (
    ReviewMeterEvidence,
    ReviewPhotoEvidence,
    is_constructed_evidence,
    project_terminal_review,
)
from app.models import (
    AuditLog,
    CollectorAssignment,
    CollectorPhoto,
    CollectorRequirement,
    CollectorTransferTerminal,
    MaterialExportCollectorAllocation,
    MaterialExportJob,
    MaterialExportTerminal,
    MaterialGroup,
    Photo,
    PhysicalCollector,
    Task,
    TerminalExportSetting,
    TotalCatalogRow,
)
from app.services.collector_transfer import meter_sources_from_groups
from app.services.data_center import group_anomalies


class MaterialExportError(RuntimeError):
    code = "material_export_error"


class MaterialExportProjectMismatch(MaterialExportError):
    code = "project_mismatch"


class MaterialExportSnapshotChanged(MaterialExportError):
    code = "snapshot_changed"


class MaterialExportPoolShortage(MaterialExportError):
    code = "pool_shortage"

    def __init__(
        self,
        message: str,
        *,
        total_shortage: int,
        terminal_shortages: Mapping[str, int],
    ) -> None:
        super().__init__(message)
        self.total_shortage = total_shortage
        self.terminal_shortages = dict(terminal_shortages)


class MaterialExportCompletedCannotRelease(MaterialExportError):
    code = "completed_cannot_release"


@dataclass(frozen=True, slots=True)
class MaterialExportTerminalPreflight:
    task_id: str
    terminal_code: str
    constructed_meter_count: int
    source_collector_count: int
    requested_collector_count: int
    final_collector_count: int
    source_revision: str
    can_export: bool
    issues: tuple[MaterialExportIssue, ...]
    pool_shortage: int


@dataclass(frozen=True, slots=True)
class ProjectExportEvidence:
    meters: tuple[MaterialExportMeter, ...]
    group_payloads: Mapping[str, Mapping[str, object]]
    photo_storage_rows: Mapping[str, Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class MaterialExportPreflight:
    project_id: str
    fingerprint: str
    terminals: Mapping[str, MaterialExportTerminalPreflight]
    source_group_ids: tuple[str, ...]
    total_pool_shortage: int


@dataclass(frozen=True, slots=True)
class TerminalMaterialExportSummary:
    task_id: str
    project_id: str
    terminal_code: str
    requested_collector_count: int
    source_collector_count: int
    final_collector_count: int
    active_allocation_count: int = 0
    last_job_status: str = ""


@dataclass(frozen=True, slots=True)
class MaterialExportShortageSimulation:
    total_shortage: int
    terminal_shortages: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class MaterialExportAllocationResult:
    allocation_id: str
    physical_collector_id: str
    original_collector_no: str | None
    final_collector_no: str
    allocation_mode: str
    is_extra: bool


@dataclass(frozen=True, slots=True)
class MaterialExportTerminalResult:
    id: str
    task_id: str
    terminal_code: str
    allocations: tuple[MaterialExportAllocationResult, ...]


@dataclass(frozen=True, slots=True)
class MaterialExportJobResult:
    job_id: str
    total_allocations: int
    terminals: tuple[MaterialExportTerminalResult, ...]


def _setting_count(setting: object | None) -> int:
    if setting is None:
        return 0
    return max(0, int(getattr(setting, "requested_collector_count", 0) or 0))


def _terminal_issue(
    *, task_id: str, terminal_code: str, code: str, message: str
) -> MaterialExportIssue:
    return MaterialExportIssue(
        code=code,
        terminal_code=terminal_code,
        group_ids=(),
        meter_nos=(),
        module_nos=(),
        message=message,
    )


def terminal_preflight_from_evidence(
    task_id: str,
    terminal_code: str,
    evidence: ProjectExportEvidence,
    setting: object | None,
    project_issues: Sequence[MaterialExportIssue],
) -> MaterialExportTerminalPreflight:
    logical: dict[str, MaterialExportMeter] = {}
    for item in evidence.meters:
        if item.constructed and str(item.task_id) == task_id:
            logical.setdefault(str(item.group_id), item)
    meters = tuple(sorted(logical.values(), key=lambda item: str(item.group_id)))
    issues = [
        issue
        for issue in project_issues
        if normalize_identifier(issue.terminal_code) == normalize_identifier(terminal_code)
    ]
    for item in meters:
        issues.extend(required_meter_issues(item))
    if not meters:
        issues.append(
            _terminal_issue(
                task_id=task_id,
                terminal_code=terminal_code,
                code="no_constructed_data",
                message="该终端没有已施工资料，未施工资料不导出",
            )
        )
    issues = sorted(
        issues,
        key=lambda issue: (issue.code, issue.group_ids, issue.meter_nos, issue.module_nos),
    )
    demand = collector_demand(meters, _setting_count(setting))
    revision_rows = canonical_preflight_rows_for_terminal(
        task_id=task_id,
        meters=meters,
        requested_count=_setting_count(setting),
        evidence=evidence,
    )
    return MaterialExportTerminalPreflight(
        task_id=task_id,
        terminal_code=terminal_code,
        constructed_meter_count=len(meters),
        source_collector_count=len(demand.source_collector_nos),
        requested_collector_count=_setting_count(setting),
        final_collector_count=demand.final_count,
        source_revision=preflight_fingerprint(revision_rows),
        can_export=not issues,
        issues=tuple(issues),
        pool_shortage=0,
    )


def build_terminal_preflight_rows(
    selected_tasks: Mapping[str, object],
    evidence: ProjectExportEvidence,
    settings: Mapping[str, TerminalExportSetting],
    project_issues: Sequence[MaterialExportIssue],
) -> tuple[MaterialExportTerminalPreflight, ...]:
    return tuple(
        terminal_preflight_from_evidence(
            task_id,
            normalize_identifier(getattr(task, "terminal", "")),
            evidence,
            settings.get(task_id),
            project_issues,
        )
        for task_id, task in sorted(selected_tasks.items())
    )


def canonical_preflight_rows_for_terminal(
    *,
    task_id: str,
    meters: Sequence[MaterialExportMeter],
    requested_count: int,
    evidence: ProjectExportEvidence,
) -> tuple[Mapping[str, object], ...]:
    rows: list[Mapping[str, object]] = [{"task_id": task_id, "requested_count": requested_count}]
    for item in meters:
        payload: dict[str, object] = {
            "group_id": item.group_id,
            "task_id": item.task_id,
            "terminal_code": item.terminal_code,
            "meter_no": item.meter_no,
            "module_no": item.module_no,
            "collector_no": item.collector_no,
            "installation_address": item.installation_address,
            "module_meter_photo_id": item.module_meter_photo_id,
            "after_box_photo_id": item.after_box_photo_id,
            "open_module_anomalies": list(item.open_module_anomalies),
            "group": dict(evidence.group_payloads.get(item.group_id, {})),
        }
        for field in ("module_meter_photo_id", "after_box_photo_id"):
            photo_id = getattr(item, field)
            if photo_id:
                payload[field.removesuffix("_id") + "_storage"] = dict(
                    evidence.photo_storage_rows.get(photo_id, {})
                )
        rows.append(payload)
    return tuple(rows)


def canonical_preflight_rows(
    *,
    evidence: ProjectExportEvidence,
    terminals: Sequence[MaterialExportTerminalPreflight],
) -> tuple[Mapping[str, object], ...]:
    rows: list[Mapping[str, object]] = []
    for terminal in terminals:
        rows.append(
            {
                "task_id": terminal.task_id,
                "terminal_code": terminal.terminal_code,
                "requested_collector_count": terminal.requested_collector_count,
                "source_revision": terminal.source_revision,
                "can_export": terminal.can_export,
                "issues": [
                    {
                        "code": issue.code,
                        "message": issue.message,
                        "groups": list(issue.group_ids),
                        "meters": list(issue.meter_nos),
                        "modules": list(issue.module_nos),
                    }
                    for issue in terminal.issues
                ],
            }
        )
    return tuple(rows)


def build_preflight_fingerprint_rows(
    evidence: ProjectExportEvidence,
    terminals: Sequence[MaterialExportTerminalPreflight],
) -> tuple[Mapping[str, object], ...]:
    return canonical_preflight_rows(evidence=evidence, terminals=terminals)


def build_preflight(
    *,
    tasks: Sequence[Task],
    evidence: ProjectExportEvidence,
    settings: Mapping[str, TerminalExportSetting],
) -> MaterialExportPreflight:
    if not tasks:
        raise ValueError("至少选择一个终端")
    project_ids = {str(task.project_id) for task in tasks}
    if len(project_ids) != 1:
        raise MaterialExportProjectMismatch("一次导出只能选择同一项目的终端")
    selected_tasks = {str(task.id): task for task in tasks}
    terminal_rows = build_terminal_preflight_rows(
        selected_tasks,
        evidence,
        settings,
        project_module_issues(evidence.meters),
    )
    fingerprint = preflight_fingerprint(
        build_preflight_fingerprint_rows(evidence, terminal_rows)
    )
    return MaterialExportPreflight(
        project_id=next(iter(project_ids)),
        fingerprint=fingerprint,
        terminals={row.task_id: row for row in terminal_rows},
        source_group_ids=tuple(
            sorted({item.group_id for item in evidence.meters if item.constructed})
        ),
        total_pool_shortage=sum(row.pool_shortage for row in terminal_rows),
    )


def _status_text(value: object) -> str:
    return normalize_identifier(getattr(value, "value", value)).lower()


def _photo_payload(photo: Photo) -> dict[str, object]:
    raw = dict(photo.raw_data or {})
    raw.update(
        {
            "id": str(photo.id),
            "legacy_id": photo.legacy_id or str(photo.id),
            "category": normalize_identifier(photo.category).lower() or "unclassified",
            "construction_slot": normalize_identifier(photo.category).lower(),
            "sha256": photo.sha256,
            "collector": photo.collector or "",
            "module_asset_no": photo.asset_no or "",
            "is_active": bool(photo.is_active),
        }
    )
    return raw


def _group_anomaly_payload(group: MaterialGroup, photos: Sequence[Photo]) -> dict[str, Any]:
    raw = dict(group.raw_data or {})
    raw.update(
        {
            "id": str(group.id),
            "group_id": str(group.id),
            "status": _status_text(group.status),
            "meter_no": group.display_meter_no,
            "terminal": group.terminal or "",
            "address": group.installation_address,
            "photo_count": group.photo_count,
            "photos": [_photo_payload(photo) for photo in photos],
            "exception_status": group.exception_status or "",
            "exception_note": group.exception_note or "",
            "exception_reasons": list(group.exception_reasons or []),
        }
    )
    return raw


class PostgresMaterialExportService:
    def __init__(
        self,
        session: Session,
        *,
        team_id: str,
        actor_id: UUID | None,
        actor: str,
    ) -> None:
        self.session = session
        self.team_id = team_id
        self.actor_id = actor_id
        self.actor = actor

    def _owned_tasks(self, task_ids: Sequence[str], *, lock: bool) -> tuple[Task, ...]:
        normalized = tuple(dict.fromkeys(normalize_identifier(item) for item in task_ids if normalize_identifier(item)))
        if not normalized:
            raise ValueError("至少选择一个终端")
        if len(normalized) > 500:
            raise ValueError("一次最多选择 500 个终端")
        uuid_ids: list[UUID] = []
        legacy_ids: list[int] = []
        for value in normalized:
            try:
                uuid_ids.append(UUID(value))
            except ValueError:
                if value.isdigit():
                    legacy_ids.append(int(value))
        criteria = []
        if uuid_ids:
            criteria.append(Task.id.in_(uuid_ids))
        if legacy_ids:
            criteria.append(Task.legacy_id.in_(legacy_ids))
        if not criteria:
            raise ValueError("终端任务编号无效")
        statement = select(Task).where(
            Task.team_id == self.team_id,
            or_(*criteria),
        )
        if lock:
            statement = statement.with_for_update()
        tasks = tuple(self.session.scalars(statement.order_by(Task.id)).all())
        if len(tasks) != len(normalized):
            raise ValueError("终端不存在或不属于当前施工组")
        return tasks

    def _settings(self, tasks: Sequence[Task]) -> dict[str, TerminalExportSetting]:
        task_ids = [task.id for task in tasks]
        rows = self.session.scalars(
            select(TerminalExportSetting).where(
                TerminalExportSetting.team_id == self.team_id,
                TerminalExportSetting.task_id.in_(task_ids),
            )
        ).all()
        return {str(row.task_id): row for row in rows}

    def _load_project_evidence(self, project_id: UUID) -> ProjectExportEvidence:
        groups = tuple(
            self.session.scalars(
                select(MaterialGroup)
                .where(
                    MaterialGroup.team_id == self.team_id,
                    MaterialGroup.project_id == project_id,
                )
                .order_by(MaterialGroup.id)
            ).all()
        )
        group_ids = [group.id for group in groups]
        photos = tuple(
            self.session.scalars(
                select(Photo)
                .where(
                    Photo.team_id == self.team_id,
                    Photo.group_id.in_(group_ids),
                    Photo.is_active.is_(True),
                )
                .order_by(Photo.group_id, Photo.sort_order, Photo.id)
            ).all()
        ) if group_ids else ()
        catalog_ids = [group.total_catalog_row_id for group in groups if group.total_catalog_row_id]
        catalogs = {
            row.id: row
            for row in self.session.scalars(
                select(TotalCatalogRow).where(
                    TotalCatalogRow.team_id == self.team_id,
                    TotalCatalogRow.project_id == project_id,
                    TotalCatalogRow.id.in_(catalog_ids),
                )
            ).all()
        } if catalog_ids else {}
        photos_by_group: dict[UUID, list[Photo]] = defaultdict(list)
        for photo in photos:
            photos_by_group[photo.group_id].append(photo)
        group_proxies = []
        for group in groups:
            catalog = catalogs.get(group.total_catalog_row_id)
            group_proxies.append(
                SimpleNamespace(
                    id=group.id,
                    terminal=group.terminal,
                    installation_address=(
                        catalog.installation_address if catalog is not None else group.installation_address
                    ),
                    display_meter_no=(
                        catalog.original_meter_no if catalog is not None else group.display_meter_no
                    ),
                    raw_data=group.raw_data or {},
                )
            )
        sources = meter_sources_from_groups(group_proxies, photos)
        source_by_group = {source.group_id: source for source in sources.sources}

        meters: list[MaterialExportMeter] = []
        group_payloads: dict[str, Mapping[str, object]] = {}
        storage_rows: dict[str, Mapping[str, object]] = {}
        for photo in photos:
            storage_rows[str(photo.id)] = {
                "photo_id": str(photo.id),
                "storage_type": photo.storage_type or "",
                "storage_bucket": photo.storage_bucket or "",
                "storage_key": photo.storage_key or photo.object_key,
                "sha256": photo.sha256,
                "byte_size": photo.byte_size,
                "content_type": photo.content_type or "application/octet-stream",
                "original_filename": photo.original_filename or "",
            }
        for group in groups:
            group_id = str(group.id)
            source = source_by_group[group_id]
            group_photos = tuple(photos_by_group.get(group.id, ()))
            payload = _group_anomaly_payload(group, group_photos)
            group_payloads[group_id] = payload
            raw = group.raw_data if isinstance(group.raw_data, Mapping) else {}
            manual = raw.get("classification_manual_confirmation")
            review_evidence = ReviewMeterEvidence(
                group_id=group_id,
                status=_status_text(group.status),
                terminal_code=source.terminal_code,
                installation_address=source.installation_address,
                meter_no=source.meter_no,
                collector_no=source.collector_no,
                module_no=source.module_no,
                persisted_photo_count=max(0, int(group.photo_count or 0)),
                active_photos=tuple(
                    ReviewPhotoEvidence(
                        id=str(photo.id),
                        category=normalize_identifier(photo.category).lower(),
                        sha256=photo.sha256,
                        confirmation_id=photo.legacy_id or str(photo.id),
                    )
                    for photo in group_photos
                ),
                barcode_status=normalize_identifier(raw.get("barcode_status")).lower(),
                classification_manual_confirmation=(
                    dict(manual) if isinstance(manual, Mapping) else None
                ),
            )
            constructed = is_constructed_evidence(review_evidence)
            if constructed:
                projected = project_terminal_review((review_evidence,))
                if projected.constructed_meters and projected.constructed_meters[0].source:
                    source = projected.constructed_meters[0].source
            module_anomalies = tuple(
                str(item.get("message") or item.get("code") or "").strip()
                for item in group_anomalies(payload)
                if "module" in str(item.get("code") or "").lower()
                or "模块" in str(item.get("message") or "")
            )
            meters.append(
                MaterialExportMeter(
                    group_id=group_id,
                    task_id=str(group.task_id or ""),
                    terminal_code=source.terminal_code,
                    meter_no=source.meter_no,
                    module_no=source.module_no,
                    collector_no=source.collector_no,
                    installation_address=source.installation_address,
                    module_meter_photo_id=source.module_meter_photo_id,
                    after_box_photo_id=source.after_box_photo_id,
                    constructed=constructed,
                    open_module_anomalies=module_anomalies,
                )
            )
        return ProjectExportEvidence(
            meters=tuple(meters),
            group_payloads=group_payloads,
            photo_storage_rows=storage_rows,
        )

    def preflight(self, *, task_ids: Sequence[str]) -> MaterialExportPreflight:
        tasks = self._owned_tasks(task_ids, lock=False)
        project_ids = {task.project_id for task in tasks}
        if len(project_ids) != 1:
            raise MaterialExportProjectMismatch("一次导出只能选择同一项目的终端")
        project_id = next(iter(project_ids))
        result = build_preflight(
            tasks=tasks,
            evidence=self._load_project_evidence(project_id),
            settings=self._settings(tasks),
        )
        result = self._with_pool_shortages(result, project_id)
        inventory_rows = self._inventory_fingerprint_rows(project_id)
        return replace(
            result,
            fingerprint=preflight_fingerprint(
                ({"preflight": result.fingerprint}, *inventory_rows)
            ),
        )

    def _inventory_fingerprint_rows(
        self, project_id: UUID
    ) -> tuple[Mapping[str, object], ...]:
        physical_rows = self.session.execute(
            select(
                PhysicalCollector.id,
                PhysicalCollector.collector_no,
                PhysicalCollector.pool_status,
            )
            .where(
                PhysicalCollector.team_id == self.team_id,
                PhysicalCollector.project_id == project_id,
            )
            .order_by(PhysicalCollector.id)
        ).all()
        allocation_rows = self.session.execute(
            select(
                MaterialExportCollectorAllocation.id,
                MaterialExportCollectorAllocation.physical_collector_id,
                MaterialExportCollectorAllocation.requirement_key,
                MaterialExportCollectorAllocation.status,
            )
            .where(
                MaterialExportCollectorAllocation.team_id == self.team_id,
                MaterialExportCollectorAllocation.project_id == project_id,
                MaterialExportCollectorAllocation.status.in_(("reserved", "used")),
            )
            .order_by(MaterialExportCollectorAllocation.id)
        ).all()
        old_assignment_rows = self.session.execute(
            select(
                CollectorAssignment.id,
                CollectorAssignment.physical_collector_id,
                CollectorAssignment.requirement_id,
                CollectorAssignment.status,
            )
            .join(
                PhysicalCollector,
                PhysicalCollector.id == CollectorAssignment.physical_collector_id,
            )
            .where(
                CollectorAssignment.team_id == self.team_id,
                CollectorAssignment.status.in_(("reserved", "used")),
                PhysicalCollector.project_id == project_id,
            )
            .order_by(CollectorAssignment.id)
        ).all()
        rows: list[Mapping[str, object]] = [
            {
                "kind": "physical",
                "id": str(row.id),
                "collector_no": row.collector_no,
                "pool_status": row.pool_status,
            }
            for row in physical_rows
        ]
        rows.extend(
            {
                "kind": "active_allocation",
                "id": str(row.id),
                "physical_collector_id": str(row.physical_collector_id),
                "requirement_key": row.requirement_key,
                "status": row.status,
            }
            for row in allocation_rows
        )
        rows.extend(
            {
                "kind": "active_collector_assignment",
                "id": str(row.id),
                "physical_collector_id": str(row.physical_collector_id),
                "requirement_id": str(row.requirement_id),
                "status": row.status,
            }
            for row in old_assignment_rows
        )
        return tuple(rows)

    def _with_pool_shortages(
        self, preflight: MaterialExportPreflight, project_id: UUID
    ) -> MaterialExportPreflight:
        available_count = int(
            self.session.scalar(
                select(func.count(PhysicalCollector.id)).where(
                    PhysicalCollector.team_id == self.team_id,
                    PhysicalCollector.project_id == project_id,
                    PhysicalCollector.pool_status.in_(("awaiting_photo", "direct", "available")),
                    ~PhysicalCollector.id.in_(
                        select(MaterialExportCollectorAllocation.physical_collector_id).where(
                            MaterialExportCollectorAllocation.status.in_(("reserved", "used"))
                        )
                    ),
                )
            )
            or 0
        )
        rows: dict[str, MaterialExportTerminalPreflight] = {}
        reusable_rows = self.session.execute(
            select(
                MaterialExportTerminal.task_id,
                func.count(MaterialExportCollectorAllocation.id),
            )
            .join(
                MaterialExportCollectorAllocation,
                MaterialExportCollectorAllocation.terminal_export_id
                == MaterialExportTerminal.id,
            )
            .where(
                MaterialExportTerminal.task_id.in_(
                    [UUID(task_id) for task_id in preflight.terminals]
                ),
                MaterialExportCollectorAllocation.status.in_(("reserved", "used")),
            )
            .group_by(MaterialExportTerminal.task_id)
        ).all()
        reusable_by_task = {str(task_id): int(count) for task_id, count in reusable_rows}
        remaining = available_count
        for task_id, row in sorted(preflight.terminals.items()):
            needed = (
                max(0, row.final_collector_count - reusable_by_task.get(task_id, 0))
                if row.can_export
                else 0
            )
            satisfied = min(needed, remaining)
            shortage = needed - satisfied
            remaining -= satisfied
            rows[task_id] = replace(row, pool_shortage=shortage)
        total_shortage = sum(row.pool_shortage for row in rows.values())
        return replace(preflight, terminals=rows, total_pool_shortage=total_shortage)

    def list_terminal_summaries(
        self, *, task_ids: Sequence[str]
    ) -> tuple[TerminalMaterialExportSummary, ...]:
        tasks = self._owned_tasks(task_ids, lock=False)
        settings = self._settings(tasks)
        project_ids = {task.project_id for task in tasks}
        evidence_by_project = {
            project_id: self._load_project_evidence(project_id) for project_id in project_ids
        }
        results: list[TerminalMaterialExportSummary] = []
        for task in tasks:
            task_id = str(task.id)
            meters = tuple(
                item
                for item in evidence_by_project[task.project_id].meters
                if item.constructed and item.task_id == task_id
            )
            demand = collector_demand(meters, _setting_count(settings.get(task_id)))
            active_count = int(
                self.session.scalar(
                    select(func.count(MaterialExportCollectorAllocation.id))
                    .join(
                        MaterialExportTerminal,
                        MaterialExportTerminal.id
                        == MaterialExportCollectorAllocation.terminal_export_id,
                    )
                    .where(
                        MaterialExportTerminal.task_id == task.id,
                        MaterialExportCollectorAllocation.status.in_(("reserved", "used")),
                    )
                )
                or 0
            )
            last_status = self.session.scalar(
                select(MaterialExportJob.status)
                .join(
                    MaterialExportTerminal,
                    MaterialExportTerminal.job_id == MaterialExportJob.id,
                )
                .where(MaterialExportTerminal.task_id == task.id)
                .order_by(MaterialExportJob.created_at.desc())
                .limit(1)
            )
            results.append(
                TerminalMaterialExportSummary(
                    task_id=task_id,
                    project_id=str(task.project_id),
                    terminal_code=normalize_identifier(task.terminal),
                    requested_collector_count=_setting_count(settings.get(task_id)),
                    source_collector_count=len(demand.source_collector_nos),
                    final_collector_count=demand.final_count,
                    active_allocation_count=active_count,
                    last_job_status=normalize_identifier(last_status),
                )
            )
        return tuple(results)

    def set_requested_collector_count(
        self, *, task_id: str, count: int
    ) -> TerminalMaterialExportSummary:
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("应还采集器数量必须是非负整数")
        task = self._owned_tasks((task_id,), lock=True)[0]
        setting = self.session.scalar(
            select(TerminalExportSetting)
            .where(
                TerminalExportSetting.team_id == self.team_id,
                TerminalExportSetting.project_id == task.project_id,
                TerminalExportSetting.task_id == task.id,
            )
            .with_for_update()
        )
        before_count = int(setting.requested_collector_count) if setting else 0
        if setting is None:
            setting = TerminalExportSetting(
                team_id=self.team_id,
                project_id=task.project_id,
                task_id=task.id,
                terminal_code=task.terminal or "",
                requested_collector_count=count,
                updated_by_id=self.actor_id,
                updated_by_username=self.actor,
            )
            self.session.add(setting)
        else:
            setting.requested_collector_count = count
            setting.terminal_code = task.terminal or ""
            setting.updated_by_id = self.actor_id
            setting.updated_by_username = self.actor
        self.session.add(
            AuditLog(
                team_id=self.team_id,
                actor_id=self.actor_id,
                actor_username=self.actor,
                project_id=task.project_id,
                action="material_export.setting_updated",
                entity_type="task",
                entity_id=task.id,
                before_data={"requested_collector_count": before_count},
                after_data={"requested_collector_count": count},
                payload={"terminal_code": task.terminal or ""},
            )
        )
        self.session.flush()
        return self.list_terminal_summaries(task_ids=(str(task.id),))[0]

    def _active_export_allocations(
        self, project_id: UUID
    ) -> tuple[tuple[MaterialExportCollectorAllocation, MaterialExportTerminal], ...]:
        return tuple(
            self.session.execute(
                select(MaterialExportCollectorAllocation, MaterialExportTerminal)
                .join(
                    MaterialExportTerminal,
                    MaterialExportTerminal.id
                    == MaterialExportCollectorAllocation.terminal_export_id,
                )
                .where(
                    MaterialExportCollectorAllocation.team_id == self.team_id,
                    MaterialExportCollectorAllocation.project_id == project_id,
                    MaterialExportCollectorAllocation.status.in_(("reserved", "used")),
                )
                .order_by(MaterialExportCollectorAllocation.id)
                .with_for_update()
            ).all()
        )

    def _active_old_assignments(
        self, project_id: UUID
    ) -> dict[UUID, tuple[CollectorAssignment, CollectorRequirement, CollectorTransferTerminal]]:
        rows = self.session.execute(
            select(CollectorAssignment, CollectorRequirement, CollectorTransferTerminal)
            .join(
                CollectorRequirement,
                CollectorRequirement.id == CollectorAssignment.requirement_id,
            )
            .join(
                CollectorTransferTerminal,
                CollectorTransferTerminal.id == CollectorRequirement.terminal_id,
            )
            .join(
                PhysicalCollector,
                PhysicalCollector.id == CollectorAssignment.physical_collector_id,
            )
            .where(
                CollectorAssignment.team_id == self.team_id,
                CollectorAssignment.status.in_(("reserved", "used")),
                PhysicalCollector.project_id == project_id,
            )
            .order_by(CollectorAssignment.physical_collector_id)
            .with_for_update()
        ).all()
        return {
            assignment.physical_collector_id: (assignment, requirement, terminal)
            for assignment, requirement, terminal in rows
        }

    def _requirement_rows(
        self,
        tasks: Sequence[Task],
        evidence: ProjectExportEvidence,
        settings: Mapping[str, TerminalExportSetting],
    ) -> dict[str, tuple[tuple[str, str | None, bool], ...]]:
        rows: dict[str, tuple[tuple[str, str | None, bool], ...]] = {}
        for task in tasks:
            task_id = str(task.id)
            meters = tuple(
                item
                for item in evidence.meters
                if item.constructed and item.task_id == task_id
            )
            demand = collector_demand(meters, _setting_count(settings.get(task_id)))
            requirements: list[tuple[str, str | None, bool]] = [
                (f"collector:{collector_no}", collector_no, False)
                for collector_no in demand.source_collector_nos
            ]
            requirements.extend(
                (f"extra:{index + 1:04d}", None, True)
                for index in range(demand.extra_count)
            )
            rows[task_id] = tuple(requirements)
        return rows

    def _collector_photo_map(self, physical_ids: Sequence[UUID]) -> dict[UUID, CollectorPhoto]:
        if not physical_ids:
            return {}
        rows = self.session.scalars(
            select(CollectorPhoto)
            .where(
                CollectorPhoto.team_id == self.team_id,
                CollectorPhoto.physical_collector_id.in_(physical_ids),
                CollectorPhoto.is_active.is_(True),
            )
            .order_by(CollectorPhoto.created_at, CollectorPhoto.id)
        ).all()
        result: dict[UUID, CollectorPhoto] = {}
        for row in rows:
            result.setdefault(row.physical_collector_id, row)
        return result

    @staticmethod
    def _group_photo_for_requirement(
        evidence: ProjectExportEvidence, *, task_id: str, original_collector_no: str
    ) -> UUID | None:
        matching_groups = sorted(
            {
                meter.group_id
                for meter in evidence.meters
                if meter.constructed
                and meter.task_id == task_id
                and normalize_identifier(meter.collector_no)
                == normalize_identifier(original_collector_no)
            }
        )
        for group_id in matching_groups:
            payload = evidence.group_payloads.get(group_id, {})
            photos = payload.get("photos") if isinstance(payload, Mapping) else None
            if not isinstance(photos, Sequence):
                continue
            for photo in photos:
                if not isinstance(photo, Mapping):
                    continue
                category = normalize_identifier(
                    photo.get("category") or photo.get("construction_slot")
                )
                if category != "collector_barcode":
                    continue
                try:
                    return UUID(str(photo.get("id")))
                except (TypeError, ValueError):
                    continue
        return None

    def reserve_job(
        self,
        *,
        preflight_fingerprint: str,
        task_ids: Sequence[str],
    ) -> MaterialExportJobResult:
        tasks = self._owned_tasks(task_ids, lock=True)
        project_ids = {task.project_id for task in tasks}
        if len(project_ids) != 1:
            raise MaterialExportProjectMismatch("一次导出只能选择同一项目的终端")
        project_id = next(iter(project_ids))
        current = self.preflight(task_ids=[str(task.id) for task in tasks])
        if current.fingerprint != preflight_fingerprint:
            raise MaterialExportSnapshotChanged("资料已变化，请重新预检")
        exportable = tuple(
            task for task in tasks if current.terminals[str(task.id)].can_export
        )
        if not exportable:
            raise MaterialExportError("所选终端均存在资料异常，无法导出")

        evidence = self._load_project_evidence(project_id)
        settings = self._settings(tasks)
        requirement_rows = self._requirement_rows(exportable, evidence, settings)
        active_pairs = self._active_export_allocations(project_id)
        active_by_physical = {
            allocation.physical_collector_id: (allocation, terminal)
            for allocation, terminal in active_pairs
        }
        reusable: dict[tuple[str, str], MaterialExportCollectorAllocation] = {}
        selected_task_ids = {task.id for task in exportable}
        for allocation, terminal in active_pairs:
            if terminal.task_id in selected_task_ids:
                reusable[(str(terminal.task_id), allocation.requirement_key)] = allocation

        physical_rows = tuple(
            self.session.scalars(
                select(PhysicalCollector)
                .where(
                    PhysicalCollector.team_id == self.team_id,
                    PhysicalCollector.project_id == project_id,
                )
                .order_by(PhysicalCollector.id)
                .with_for_update()
            ).all()
        )
        old_assignments = self._active_old_assignments(project_id)
        physical_by_id = {row.id: row for row in physical_rows}
        chosen: set[UUID] = set()
        planned: dict[
            str,
            list[
                tuple[
                    str,
                    str | None,
                    bool,
                    PhysicalCollector,
                    str,
                    CollectorAssignment | None,
                ]
            ],
        ] = defaultdict(list)
        shortage_by_task: dict[str, int] = defaultdict(int)

        for task in sorted(exportable, key=lambda item: str(item.id)):
            task_id = str(task.id)
            terminal_code = normalize_identifier(task.terminal)
            for requirement_key, original_no, is_extra in requirement_rows[task_id]:
                prior = reusable.get((task_id, requirement_key))
                if prior is not None:
                    physical = physical_by_id.get(prior.physical_collector_id)
                    if physical is None:
                        raise MaterialExportSnapshotChanged("已预留采集器不存在，请重新预检")
                    chosen.add(physical.id)
                    planned[task_id].append(
                        (
                            requirement_key,
                            original_no,
                            is_extra,
                            physical,
                            prior.allocation_mode,
                            None,
                        )
                    )
                    continue

                candidate: PhysicalCollector | None = None
                source_assignment: CollectorAssignment | None = None
                mode = "extra_pool" if is_extra else "pool_replacement"
                if original_no:
                    for physical in physical_rows:
                        if physical.id in chosen or physical.id in active_by_physical:
                            continue
                        if normalize_identifier(physical.collector_no) != normalize_identifier(
                            original_no
                        ):
                            continue
                        old = old_assignments.get(physical.id)
                        if old is not None:
                            assignment, _requirement, old_terminal = old
                            if normalize_identifier(old_terminal.terminal_code) != terminal_code:
                                continue
                            source_assignment = assignment
                        elif physical.pool_status not in (
                            "awaiting_photo",
                            "direct",
                            "available",
                        ):
                            continue
                        candidate = physical
                        mode = "same_number"
                        break
                if candidate is None:
                    pool_candidates = [
                        physical
                        for physical in physical_rows
                        if physical.id not in chosen
                        and physical.id not in active_by_physical
                        and physical.id not in old_assignments
                        and physical.pool_status == "available"
                    ]
                    if pool_candidates:
                        candidate = secrets.choice(pool_candidates)
                if candidate is None:
                    shortage_by_task[task_id] += 1
                    continue
                chosen.add(candidate.id)
                planned[task_id].append(
                    (
                        requirement_key,
                        original_no,
                        is_extra,
                        candidate,
                        mode,
                        source_assignment,
                    )
                )

        total_shortage = sum(shortage_by_task.values())
        if total_shortage:
            raise MaterialExportPoolShortage(
                "采集器池库存不足，本批次未开始分配",
                total_shortage=total_shortage,
                terminal_shortages=shortage_by_task,
            )

        job = MaterialExportJob(
            team_id=self.team_id,
            project_id=project_id,
            status="reserved",
            preflight_fingerprint=current.fingerprint,
            manifest_sha256=current.fingerprint,
            created_by_id=self.actor_id,
            created_by_username=self.actor,
            stats={"terminal_count": len(exportable)},
            diagnostics=[],
        )
        self.session.add(job)
        self.session.flush()
        photo_map = self._collector_photo_map(tuple(chosen))
        results: list[MaterialExportTerminalResult] = []
        total_allocations = 0
        for task in sorted(exportable, key=lambda item: str(item.id)):
            task_id = str(task.id)
            row = current.terminals[task_id]
            terminal_export = MaterialExportTerminal(
                job_id=job.id,
                team_id=self.team_id,
                project_id=project_id,
                task_id=task.id,
                terminal_code=task.terminal or "",
                status="reserved",
                requested_collector_count=row.requested_collector_count,
                source_collector_count=row.source_collector_count,
                final_collector_count=row.final_collector_count,
                source_revision=row.source_revision,
                manifest_json={},
                diagnostics=[],
            )
            self.session.add(terminal_export)
            self.session.flush()
            allocation_results: list[MaterialExportAllocationResult] = []
            allocation_ids: list[str] = []
            for (
                requirement_key,
                original_no,
                is_extra,
                physical,
                mode,
                source_assignment,
            ) in planned[task_id]:
                existing = reusable.get((task_id, requirement_key))
                if existing is not None:
                    allocation = existing
                else:
                    collector_photo = photo_map.get(physical.id)
                    group_photo_id = None
                    photo_source_kind = "none"
                    if collector_photo is not None:
                        photo_source_kind = (
                            "inventory_same" if mode == "same_number" else "pool"
                        )
                    elif original_no and mode == "same_number":
                        group_photo_id = self._group_photo_for_requirement(
                            evidence,
                            task_id=task_id,
                            original_collector_no=original_no,
                        )
                        if group_photo_id is not None:
                            photo_source_kind = "terminal_group"
                    allocation = MaterialExportCollectorAllocation(
                        job_id=job.id,
                        terminal_export_id=terminal_export.id,
                        team_id=self.team_id,
                        project_id=project_id,
                        requirement_key=requirement_key,
                        original_collector_no=original_no,
                        physical_collector_id=physical.id,
                        source_assignment_id=(
                            source_assignment.id if source_assignment is not None else None
                        ),
                        collector_photo_id=(
                            collector_photo.id if collector_photo is not None else None
                        ),
                        group_photo_id=group_photo_id,
                        allocation_mode=mode,
                        photo_source_kind=photo_source_kind,
                        prior_pool_status=physical.pool_status,
                        status="reserved",
                        created_by_id=self.actor_id,
                        created_by_username=self.actor,
                    )
                    self.session.add(allocation)
                    physical.pool_status = "reserved"
                    self.session.flush()
                output_mode = allocation.allocation_mode
                allocation_results.append(
                    MaterialExportAllocationResult(
                        allocation_id=str(allocation.id),
                        physical_collector_id=str(physical.id),
                        original_collector_no=allocation.original_collector_no,
                        final_collector_no=physical.collector_no,
                        allocation_mode=output_mode,
                        is_extra=is_extra,
                    )
                )
                allocation_ids.append(str(allocation.id))
                total_allocations += 1
            terminal_export.manifest_json = {"allocation_ids": allocation_ids}
            results.append(
                MaterialExportTerminalResult(
                    id=str(terminal_export.id),
                    task_id=task_id,
                    terminal_code=task.terminal or "",
                    allocations=tuple(allocation_results),
                )
            )
        job.stats = {
            "terminal_count": len(results),
            "allocation_count": total_allocations,
        }
        self.session.add(
            AuditLog(
                team_id=self.team_id,
                actor_id=self.actor_id,
                actor_username=self.actor,
                project_id=project_id,
                action="material_export.reserved",
                entity_type="material_export_job",
                entity_id=job.id,
                payload={
                    "task_ids": [str(task.id) for task in exportable],
                    "allocation_count": total_allocations,
                },
            )
        )
        self.session.flush()
        return MaterialExportJobResult(
            job_id=str(job.id),
            total_allocations=total_allocations,
            terminals=tuple(results),
        )

    def mark_terminal_completed(self, *, job_id: str, terminal_id: str) -> None:
        terminal = self.session.scalar(
            select(MaterialExportTerminal)
            .join(MaterialExportJob, MaterialExportJob.id == MaterialExportTerminal.job_id)
            .where(
                MaterialExportTerminal.id == UUID(terminal_id),
                MaterialExportTerminal.job_id == UUID(job_id),
                MaterialExportTerminal.team_id == self.team_id,
            )
            .with_for_update()
        )
        if terminal is None:
            raise ValueError("导出终端不存在")
        allocation_ids = [
            UUID(value) for value in terminal.manifest_json.get("allocation_ids", [])
        ]
        allocations = self.session.scalars(
            select(MaterialExportCollectorAllocation)
            .where(MaterialExportCollectorAllocation.id.in_(allocation_ids))
            .with_for_update()
        ).all() if allocation_ids else []
        physical_ids = [row.physical_collector_id for row in allocations]
        physical_rows = self.session.scalars(
            select(PhysicalCollector)
            .where(PhysicalCollector.id.in_(physical_ids))
            .with_for_update()
        ).all() if physical_ids else []
        now = datetime.now(UTC)
        for allocation in allocations:
            allocation.status = "used"
            allocation.used_at = now
        for physical in physical_rows:
            physical.pool_status = "used"
        terminal.status = "completed"
        terminal.completed_at = now
        pending_count = int(
            self.session.scalar(
                select(func.count(MaterialExportTerminal.id)).where(
                    MaterialExportTerminal.job_id == terminal.job_id,
                    MaterialExportTerminal.id != terminal.id,
                    MaterialExportTerminal.status != "completed",
                )
            )
            or 0
        )
        if pending_count == 0:
            job = self.session.get(MaterialExportJob, terminal.job_id)
            if job is not None:
                job.status = "completed"
        self.session.flush()

    def cancel_and_release(
        self,
        *,
        job_id: str,
        terminal_ids: Sequence[str],
        reason: str,
    ) -> None:
        normalized_reason = normalize_identifier(reason)
        if not normalized_reason:
            raise ValueError("取消原因不能为空")
        ids = [UUID(value) for value in terminal_ids]
        terminals = self.session.scalars(
            select(MaterialExportTerminal)
            .where(
                MaterialExportTerminal.job_id == UUID(job_id),
                MaterialExportTerminal.team_id == self.team_id,
                MaterialExportTerminal.id.in_(ids),
            )
            .order_by(MaterialExportTerminal.id)
            .with_for_update()
        ).all()
        if len(terminals) != len(ids):
            raise ValueError("导出终端不存在")
        if any(terminal.status == "completed" for terminal in terminals):
            raise MaterialExportCompletedCannotRelease("已完成终端不能取消释放")
        now = datetime.now(UTC)
        allocations = self.session.scalars(
            select(MaterialExportCollectorAllocation)
            .where(
                MaterialExportCollectorAllocation.terminal_export_id.in_(ids),
                MaterialExportCollectorAllocation.status == "reserved",
            )
            .order_by(MaterialExportCollectorAllocation.id)
            .with_for_update()
        ).all()
        for allocation in allocations:
            allocation.status = "released"
            allocation.released_by_id = self.actor_id
            allocation.released_by_username = self.actor
            allocation.released_at = now
            has_old_owner = self.session.scalar(
                select(func.count(CollectorAssignment.id)).where(
                    CollectorAssignment.physical_collector_id
                    == allocation.physical_collector_id,
                    CollectorAssignment.status.in_(("reserved", "used")),
                )
            )
            has_new_owner = self.session.scalar(
                select(func.count(MaterialExportCollectorAllocation.id)).where(
                    MaterialExportCollectorAllocation.physical_collector_id
                    == allocation.physical_collector_id,
                    MaterialExportCollectorAllocation.status.in_(("reserved", "used")),
                )
            )
            if not has_old_owner and not has_new_owner:
                physical = self.session.get(
                    PhysicalCollector,
                    allocation.physical_collector_id,
                    with_for_update=True,
                )
                if physical is not None:
                    physical.pool_status = allocation.prior_pool_status
        for terminal in terminals:
            terminal.status = "cancelled_released"
            terminal.released_at = now
        job = self.session.get(MaterialExportJob, UUID(job_id))
        if job is not None:
            job.status = "cancelled"
        self.session.add(
            AuditLog(
                team_id=self.team_id,
                actor_id=self.actor_id,
                actor_username=self.actor,
                project_id=terminals[0].project_id if terminals else None,
                action="material_export.cancelled_released",
                entity_type="material_export_job",
                entity_id=UUID(job_id),
                payload={
                    "terminal_ids": [str(value) for value in ids],
                    "reason": normalized_reason,
                    "released_collectors": [
                        str(row.physical_collector_id) for row in allocations
                    ],
                },
            )
        )
        self.session.flush()
