from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
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
        return self._with_pool_shortages(result, project_id)

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
        remaining = available_count
        for task_id, row in sorted(preflight.terminals.items()):
            needed = row.final_collector_count if row.can_export else 0
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
