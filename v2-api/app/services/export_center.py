from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping
from uuid import uuid4

from app.services import local_simulation
from app.services.final_delivery_export import LeasedDeliveryPackage, delivery_group_readiness


SUPPORTED_EXPORT_JOB_PAGE_SIZES = {20, 50, 100}
PLACEHOLDER_DEVICE_VALUES = {"", "00000000", "UNKNOWN", "N/A", "NULL", "-"}
DEVICE_EXPORT_KINDS = {"terminal", "meter", "module", "collector"}

EXPORT_CATALOG: tuple[dict[str, str], ...] = (
    {"key": "final_delivery", "label": "正式交付包", "delivery": "zip", "mode": "background"},
    {"key": "device_terminal", "label": "终端设备清单", "delivery": "xlsx", "mode": "inline"},
    {"key": "device_meter", "label": "表号设备清单", "delivery": "xlsx", "mode": "inline"},
    {"key": "device_module", "label": "模块设备清单", "delivery": "xlsx", "mode": "inline"},
    {"key": "device_collector", "label": "采集器设备清单", "delivery": "xlsx", "mode": "inline"},
    {"key": "task_detail", "label": "任务明细", "delivery": "xlsx", "mode": "inline"},
    {"key": "exception_meter", "label": "异常表计", "delivery": "xlsx", "mode": "inline"},
    {"key": "exception_missing_photo", "label": "缺图异常", "delivery": "xlsx", "mode": "inline"},
    {"key": "replacement", "label": "换表记录", "delivery": "xlsx", "mode": "inline"},
    {"key": "unmatched", "label": "未匹配记录", "delivery": "xlsx", "mode": "inline"},
    {"key": "barcode_review", "label": "条码复核", "delivery": "xlsx", "mode": "inline"},
    {"key": "project_outside", "label": "项目外记录", "delivery": "xlsx", "mode": "inline"},
    {"key": "installer_kpi", "label": "施工人员 KPI", "delivery": "xlsx", "mode": "inline"},
    {"key": "installer_daily_completion", "label": "施工人员每日完成", "delivery": "xlsx", "mode": "inline"},
)
CATALOG_BY_KEY = {item["key"]: item for item in EXPORT_CATALOG}


def normalize_export_page_size(value: int) -> int:
    page_size = int(value or 20)
    if page_size not in SUPPORTED_EXPORT_JOB_PAGE_SIZES:
        raise ValueError("Export job page_size must be one of 20, 50, or 100")
    return page_size


def normalize_device_value(value: object) -> str:
    text = str(value or "").strip()
    if text.upper() in PLACEHOLDER_DEVICE_VALUES:
        return ""
    if text[:1] in {"=", "+", "-", "@"}:
        return ""
    return text


def _text(value: object) -> str:
    return str(value or "").strip()


def terminal_delivery_preflight(group: Mapping[str, Any]) -> dict[str, Any]:
    return delivery_group_readiness(group)


def terminal_readiness_item(terminal: str, groups: list[Mapping[str, Any]]) -> dict[str, Any]:
    preflights = [delivery_group_readiness(group) for group in groups]
    group_count = len(groups)
    constructed_count = sum(1 for item in preflights if item["constructed"])
    archived_count = sum(1 for item in preflights if item["archived"])
    cache_ready_count = sum(1 for item in preflights if item["cache_ready"])
    cache_pending_count = sum(1 for item in preflights if item["cache_pending"])
    cache_path_uncontrolled_count = sum(1 for item in preflights if item["cache_path_uncontrolled"])
    identity_blocked_count = sum(1 for item in preflights if not item["identity_ready"])
    blockers: list[str] = []
    if constructed_count < group_count:
        blockers.append(f"{group_count - constructed_count} \u4e2a\u8d44\u6599\u7ec4\u672a\u65bd\u5de5")
    if archived_count < group_count:
        blockers.append(f"{group_count - archived_count} \u4e2a\u8d44\u6599\u7ec4\u672a\u5f52\u6863")
    if cache_pending_count:
        blockers.append(f"{cache_pending_count} \u4e2a\u8d44\u6599\u7ec4\u4ea4\u4ed8\u7f13\u5b58\u672a\u5c31\u7eea")
    if cache_path_uncontrolled_count:
        blockers.append(f"{cache_path_uncontrolled_count} \u4e2a\u8d44\u6599\u7ec4\u4ea4\u4ed8\u7f13\u5b58\u8def\u5f84\u4e0d\u53d7\u63a7")
    if identity_blocked_count:
        blockers.append(f"{identity_blocked_count} \u4e2a\u8d44\u6599\u7ec4\u6b63\u5f0f\u4ea4\u4ed8\u8eab\u4efd\u4e0d\u5b8c\u6574")
    return {
        "terminal": terminal,
        "group_count": group_count,
        "constructed_count": constructed_count,
        "archived_count": archived_count,
        "cache_ready_count": cache_ready_count,
        "status": "ready" if group_count > 0 and not blockers else "blocked",
        "blockers": blockers,
    }


def build_terminal_readiness_page(
    groups: Iterable[Mapping[str, Any]],
    *,
    page: int = 1,
    page_size: int = 20,
    query: str = "",
) -> dict[str, Any]:
    page_size = normalize_export_page_size(page_size)
    page = max(1, int(page or 1))
    query_text = _text(query).lower()
    groups_by_terminal: dict[str, list[Mapping[str, Any]]] = {}
    for group in groups:
        terminal = _text(group.get("terminal"))
        if not terminal or (query_text and query_text not in terminal.lower()):
            continue
        groups_by_terminal.setdefault(terminal, []).append(group)
    items = [
        terminal_readiness_item(terminal, terminal_groups)
        for terminal, terminal_groups in sorted(groups_by_terminal.items(), key=lambda item: item[0])
    ]
    offset = (page - 1) * page_size
    return {"page": page, "page_size": page_size, "total": len(items), "items": items[offset : offset + page_size]}


def stable_export_snapshot(groups: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    snapshot: list[dict[str, Any]] = []
    for group in groups:
        photos = []
        for photo in group.get("photos") or []:
            if not isinstance(photo, Mapping):
                continue
            photos.append(
                {
                    "id": _text(photo.get("id")),
                    "is_active": photo.get("is_active") is not False,
                    "upload_status": _text(photo.get("upload_status") or photo.get("status")).lower(),
                    "archive_status": _text(photo.get("archive_status")).lower(),
                    "delivery_cache_status": _text(photo.get("delivery_cache_status")).lower(),
                    "delivery_cache_path": _text(photo.get("delivery_cache_path")),
                    "delivery_cache_content_sha256": _text(photo.get("delivery_cache_content_sha256")),
                    "delivery_cache_version": _text(photo.get("delivery_cache_version")),
                    "sha256": _text(photo.get("sha256")),
                    "category": _text(photo.get("category")),
                    "module_asset_no": _text(photo.get("module_asset_no") or photo.get("asset_no")),
                    "collector": _text(photo.get("collector")),
                    "client_completed_at": _text(photo.get("client_completed_at")),
                    "original_filename": _text(photo.get("original_filename")),
                }
            )
        photos.sort(key=lambda item: (item["id"], item["category"], item["delivery_cache_path"]))
        snapshot.append(
            {
                "id": _text(group.get("id")),
                "terminal": _text(group.get("terminal")),
                "meter_no": _text(group.get("meter_no")),
                "module_asset_no": _text(group.get("module_asset_no") or group.get("asset_no")),
                "collector": _text(group.get("collector")),
                "address": _text(group.get("address") or group.get("installation_address")),
                "status": _text(group.get("status")).lower(),
                "archive_status": _text(group.get("archive_status")).lower(),
                "archived_at": _text(group.get("archived_at")),
                "client_completed_at": _text(group.get("client_completed_at")),
                "barcode_verification": {
                    "auto_archive_status": _text((group.get("barcode_verification") or {}).get("auto_archive_status")).lower(),
                    "status": _text((group.get("barcode_verification") or {}).get("status")).lower(),
                    "evidence_fingerprint": _text((group.get("barcode_verification") or {}).get("evidence_fingerprint")),
                },
                "replacement_old_meter_no": _text(group.get("replacement_old_meter_no")),
                "replacement_new_meter_no": _text(group.get("replacement_new_meter_no")),
                "construction_collector": _text(group.get("construction_collector")),
                "construction_module_asset_no": _text(group.get("construction_module_asset_no")),
                "photos": photos,
            }
        )
    snapshot.sort(key=lambda item: (item["terminal"], item["id"], item["meter_no"]))
    return snapshot


def scope_export_groups(groups: Iterable[Mapping[str, Any]], filters: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    terminal = _text(filters.get("terminal"))
    task_id = _text(filters.get("task_id"))
    scoped: list[Mapping[str, Any]] = []
    for group in groups:
        if terminal and _text(group.get("terminal")) != terminal:
            continue
        if task_id and _text(group.get("task_id")) != task_id:
            continue
        scoped.append(group)
    return scoped


def export_request_key(*, job_type: str, filters: Mapping[str, Any], snapshot: Iterable[Mapping[str, Any]]) -> str:
    payload = {
        "job_type": _text(job_type),
        "filters": dict(sorted((str(key), value) for key, value in dict(filters or {}).items())),
        "snapshot": list(snapshot),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_device_workbook(
    *,
    kind: str,
    rows: Iterable[object],
    project: Mapping[str, Any] | None = None,
    filters: Mapping[str, Any] | None = None,
) -> bytes:
    if kind not in DEVICE_EXPORT_KINDS:
        raise ValueError(f"Unsupported device export kind: {kind}")
    try:
        from openpyxl import Workbook
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("openpyxl is required to export Excel files") from exc

    values = sorted({value for value in (normalize_device_value(row) for row in rows) if value})
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = f"{kind} devices"[:31]
    sheet.append([kind])
    for value in values:
        cell = sheet.cell(row=sheet.max_row + 1, column=1, value=value)
        cell.number_format = "@"
    sheet.column_dimensions["A"].width = max(12, min(32, max((len(value) for value in values), default=8) + 2))
    project = dict(project or {})
    filters = dict(filters or {})
    workbook.properties.title = f"{kind} device export"
    workbook.properties.subject = f"project={project.get('name') or project.get('id') or ''}"
    workbook.properties.description = (
        f"generated_at={datetime.now(UTC).isoformat()}; "
        f"count={len(values)}; filters={json.dumps(filters, ensure_ascii=False, sort_keys=True)}"
    )
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def extract_device_values(groups: Iterable[Mapping[str, Any]], kind: str) -> list[str]:
    field_by_kind = {
        "terminal": "terminal",
        "meter": "meter_no",
        "module": "module_asset_no",
        "collector": "collector",
    }
    field = field_by_kind[kind]
    values: list[str] = []
    for group in groups:
        values.append(str(group.get(field) or ""))
        if kind == "module":
            values.append(str(group.get("asset_no") or ""))
        if kind in {"module", "collector"}:
            for photo in group.get("photos") or []:
                if isinstance(photo, Mapping):
                    values.append(str(photo.get(field) or photo.get("asset_no") or ""))
    return values


def build_simple_table_workbook(*, title: str, rows: Iterable[Mapping[str, Any]]) -> bytes:
    try:
        from openpyxl import Workbook
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("openpyxl is required to export Excel files") from exc

    materialized = [dict(row) for row in rows]
    headers = sorted({key for row in materialized for key in row})
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title[:31]
    sheet.append(headers or ["message"])
    if not materialized:
        sheet.append([""])
    for row in materialized:
        sheet.append([row.get(header, "") for header in headers])
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            if isinstance(cell.value, str):
                cell.number_format = "@"
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def file_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def file_sha256_path(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_export_content(content: bytes, *, job_id: str, filename: str) -> tuple[str, str, int]:
    root = (local_simulation.delivery_cache_root() / "exports").resolve()
    root.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix or ".bin"
    target = (root / f"{job_id}{suffix}").resolve()
    target.relative_to(root)
    target.write_bytes(content)
    return str(target), file_sha256(content), len(content)


def validated_export_file(path_value: str) -> Path:
    root = local_simulation.delivery_cache_root().resolve()
    try:
        candidate = Path(path_value).resolve(strict=True)
        candidate.relative_to(root)
    except (OSError, ValueError) as exc:
        raise FileNotFoundError(path_value) from exc
    if candidate.is_dir():
        raise FileNotFoundError(path_value)
    return candidate


@dataclass
class OpenedExportStream:
    path: Path
    file_name: str
    media_type: str
    fd: int
    size_bytes: int
    handle: Any | None = None

    def iter_bytes(self, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        try:
            if self.handle is not None:
                handle = self.handle
                self.handle = None
                should_close = True
            else:
                handle = os.fdopen(self.fd, "rb", closefd=True)
                self.fd = -1
                should_close = True
            try:
                while True:
                    chunk = handle.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
            finally:
                if should_close:
                    handle.close()
        finally:
            self.close()

    def close(self) -> None:
        if self.handle is not None:
            self.handle.close()
            self.handle = None
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1


def open_validated_export_stream(path_value: str | Path, *, filename: str = "", media_type: str = "") -> OpenedExportStream:
    root = local_simulation.delivery_cache_root().resolve()
    original = Path(path_value)
    if original.is_symlink():
        raise FileNotFoundError(str(path_value))
    try:
        candidate = original.resolve(strict=True)
        candidate.relative_to(root)
    except (OSError, ValueError) as exc:
        raise FileNotFoundError(str(path_value)) from exc
    if candidate.is_dir() or candidate.is_symlink():
        raise FileNotFoundError(str(path_value))
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(candidate, flags)
    except OSError as exc:
        raise FileNotFoundError(str(path_value)) from exc
    try:
        info = os.fstat(fd)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
            raise FileNotFoundError(str(path_value))
        stable_handle = None
        if os.name == "nt":
            stable_handle = tempfile.TemporaryFile()
            with os.fdopen(os.dup(fd), "rb", closefd=True) as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    stable_handle.write(chunk)
            stable_handle.seek(0)
        return OpenedExportStream(
            path=candidate,
            file_name=filename or candidate.name,
            media_type=media_type or media_type_for_filename(filename or candidate.name),
            fd=fd,
            size_bytes=info.st_size,
            handle=stable_handle,
        )
    except BaseException:
        os.close(fd)
        raise


def media_type_for_filename(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".xlsx":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if suffix == ".zip":
        return "application/zip"
    return "application/octet-stream"


def export_filename(job_type: str, suffix: str = "xlsx") -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    safe_type = "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in job_type)
    return f"{safe_type}-{stamp}.{suffix}"


def build_inline_export_content(repository: Any, *, job_type: str, filters: Mapping[str, Any]) -> tuple[bytes, str, str]:
    filters = dict(filters or {})
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if job_type.startswith("device_"):
        kind = job_type.removeprefix("device_")
        groups_page = repository.list_groups(limit=100_000, offset=0)
        content = build_device_workbook(
            kind=kind,
            rows=extract_device_values(groups_page.get("items", []), kind),
            project=filters.get("project") or {},
            filters=filters,
        )
        return content, export_filename(job_type), media_type
    if job_type == "task_detail":
        return repository.build_task_detail_export(int(filters.get("task_id") or 0)), export_filename(job_type), media_type
    if job_type == "exception_meter":
        return repository.build_exception_meter_export(reviewer=str(filters.get("reviewer") or "")), export_filename(job_type), media_type
    if job_type == "project_outside":
        return repository.build_project_outside_export(), export_filename(job_type), media_type
    if job_type == "unmatched":
        page = repository.export_unmatched_records(query=str(filters.get("query") or ""), limit=100_000)
        return build_simple_table_workbook(title=job_type, rows=page.get("items", [])), export_filename(job_type), media_type
    if job_type in {"exception_missing_photo", "replacement", "barcode_review", "installer_kpi", "installer_daily_completion"}:
        return build_simple_table_workbook(title=job_type, rows=[]), export_filename(job_type), media_type
    raise ValueError(f"Unsupported export job type: {job_type}")


def request_background_export(repository: Any, *, job_type: str, filters: Mapping[str, Any], actor: str) -> dict[str, Any]:
    if job_type != "final_delivery":
        raise ValueError(f"Unsupported background export job type: {job_type}")
    from app.services.delivery_package_queue import DeliveryPackageNotReady

    try:
        package: LeasedDeliveryPackage = repository.request_final_delivery_export(
            task_id=filters.get("task_id"),
            terminal=str(filters.get("terminal") or ""),
            review_scope=str(filters.get("review_scope") or "reviewed"),
            requested_by=actor,
        )
    except DeliveryPackageNotReady as exc:
        return {
            "delivery_package_job_id": exc.job_id,
            "status": "pending",
            "content_path": "",
            "content_sha256": "",
            "size_bytes": None,
        }
    try:
        resolved = package.path.resolve(strict=True)
        return {
            "delivery_package_job_id": "",
            "status": "succeeded",
            "content_path": str(resolved),
            "content_sha256": file_sha256_path(resolved),
            "size_bytes": resolved.stat().st_size,
        }
    finally:
        package.release()


def new_export_job_id() -> str:
    return str(uuid4())
