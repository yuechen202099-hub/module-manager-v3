from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile
from zoneinfo import ZoneInfo


OLD_DEVICE_HEADERS = (
    "终端地址",
    "终端厂家",
    "终端安装地址",
    "表号",
    "采集器设备号",
    "供服中心",
    "改造工程队",
    "旧设备拆除时间",
    "旧设备状态",
)
NEW_DEVICE_HEADERS = ("改造日期", "模块对应的表号", "新模块编号", "备注")
STANDARD_PHOTO_CATEGORIES = {
    "before_box": "表箱整体改造前",
    "collector_barcode": "采集器条形码",
    "module_meter": "模块与电能表",
    "after_box": "表箱整体改造后",
}
STANDARD_PHOTO_ORDER = tuple(STANDARD_PHOTO_CATEGORIES)
FORMAL_IDENTITY_PLACEHOLDERS = {"", "00000000", "未关联终端"}
PACKAGE_TTL = timedelta(days=7)
LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")

_INVALID_WINDOWS_PART = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TRAILING_WINDOWS_PART = re.compile(r"[ .]+$")
_PACKAGE_LOCKS: dict[str, threading.Lock] = {}
_PACKAGE_LOCKS_GUARD = threading.Lock()
_ACTIVE_CACHE_PATHS: dict[str, int] = {}
_ACTIVE_CACHE_PATHS_GUARD = threading.Lock()


class DeliveryPackageValidationError(ValueError):
    def __init__(self, errors: Sequence[Mapping[str, Any]]):
        self.errors = [dict(error) for error in errors]
        super().__init__("Formal delivery package validation failed")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(*values: Any) -> str:
    return next((_text(value) for value in values if _text(value)), "")


def _active_photos(group: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(photo)
        for photo in group.get("photos", []) or []
        if isinstance(photo, Mapping) and photo.get("is_active") is not False
    ]


def _group_identity(group: Mapping[str, Any]) -> dict[str, str]:
    photos = _active_photos(group)
    return {
        "terminal": _text(group.get("terminal")),
        "meter_no": _first_text(group.get("meter_no"), group.get("display_meter_no")),
        "module_asset_no": _first_text(
            group.get("construction_module_asset_no"),
            group.get("module_asset_no"),
            group.get("asset_no"),
            *(photo.get("module_asset_no") or photo.get("asset_no") for photo in photos),
        ),
        "collector": _first_text(
            group.get("construction_collector"),
            group.get("collector"),
            *(photo.get("collector") for photo in photos),
        ),
        "address": _first_text(group.get("address"), group.get("installation_address")),
    }


def _completed_at(group: Mapping[str, Any]) -> str:
    photos = _active_photos(group)
    return _first_text(
        group.get("client_completed_at"),
        *(photo.get("client_completed_at") for photo in photos),
    )


def _local_date(value: Any) -> str:
    text = _text(value)
    if not text:
        raise ValueError("missing date")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid date") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(LOCAL_TIMEZONE)
    return parsed.date().isoformat()


def group_is_formally_archived(group: Mapping[str, Any]) -> bool:
    status = _text(group.get("status")).lower()
    archive_status = _text(group.get("archive_status")).lower()
    verification = group.get("barcode_verification") or {}
    photos = _active_photos(group)
    return (
        status == "archived"
        or archive_status == "archived"
        or bool(group.get("archived_at"))
        or _text(verification.get("auto_archive_status")).lower() == "archived"
        or (bool(photos) and all(_text(photo.get("archive_status")).lower() == "archived" for photo in photos))
    )


def _error(group_id: str, code: str, field: str, message: str) -> dict[str, str]:
    return {"group_id": group_id, "code": code, "field": field, "message": message}


def _deduplicated_groups(groups: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        payload = dict(group)
        group_id = _text(payload.get("id"))
        key = group_id or hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        result.append(payload)
    return result


def validate_delivery_groups(
    groups: Iterable[Mapping[str, Any]],
    *,
    require_cache: bool = True,
) -> list[dict[str, Any]]:
    deduplicated = _deduplicated_groups(groups)
    if not deduplicated:
        raise DeliveryPackageValidationError(
            [_error("", "no_groups", "scope", "No archived groups are eligible for formal delivery")]
        )
    errors: list[dict[str, str]] = []
    identities: dict[str, dict[str, list[str]]] = {
        field: {} for field in ("terminal", "meter_no", "module_asset_no", "collector")
    }
    for index, group in enumerate(deduplicated, start=1):
        group_id = _text(group.get("id")) or f"group-{index}"
        identity = _group_identity(group)
        for field, code in (
            ("terminal", "missing_terminal"),
            ("meter_no", "missing_meter_no"),
            ("module_asset_no", "missing_module_no"),
            ("collector", "missing_collector"),
            ("address", "missing_address"),
        ):
            if not identity[field]:
                errors.append(_error(group_id, code, field, f"Missing required {field}"))
        for field in ("terminal", "meter_no", "module_asset_no", "collector"):
            if identity[field] in FORMAL_IDENTITY_PLACEHOLDERS - {""}:
                errors.append(_error(group_id, "placeholder_identity", field, "Placeholder identity is forbidden"))
            if identity[field]:
                identities[field].setdefault(identity[field], []).append(group_id)
        if not group_is_formally_archived(group):
            errors.append(_error(group_id, "not_archived", "status", "Group is not archived"))
        try:
            _local_date(_completed_at(group))
        except ValueError:
            errors.append(_error(group_id, "invalid_completed_at", "client_completed_at", "Missing or invalid completion date"))
        photos = _active_photos(group)
        if len(photos) != 4:
            errors.append(_error(group_id, "invalid_photo_count", "photos", "Exactly four active photos are required"))
        categories = [_text(photo.get("category")) for photo in photos]
        if len(categories) != 4 or set(categories) != set(STANDARD_PHOTO_CATEGORIES):
            errors.append(
                _error(group_id, "invalid_photo_categories", "photos", "Four unique standard photo categories are required")
            )
        if require_cache:
            for photo in photos:
                if _text(photo.get("delivery_cache_status")) != "ready" or not _text(photo.get("delivery_cache_path")):
                    errors.append(
                        _error(group_id, "delivery_cache_pending", "photos", "Completed original photo cache is required")
                    )
                    break
    for field, values in identities.items():
        for value, group_ids in values.items():
            unique_group_ids = sorted(set(group_ids))
            if len(unique_group_ids) < 2:
                continue
            for group_id in unique_group_ids:
                errors.append(
                    _error(group_id, "device_conflict", field, f"Device identifier {value} is used by multiple groups")
                )
    if errors:
        raise DeliveryPackageValidationError(errors)
    return deduplicated


def _delivery_remark(group: Mapping[str, Any]) -> str:
    notes = [
        _text(item)
        for item in (
            *(group.get("exception_reasons") or []),
            group.get("exception_note"),
        )
        if _text(item)
    ]
    old_meter_no = _first_text(
        group.get("replacement_old_meter_no"),
        *(photo.get("replacement_old_meter_no") for photo in _active_photos(group)),
    )
    if old_meter_no:
        notes.insert(0, f"换表：旧表号 {old_meter_no}")
    manually_confirmed = bool(group.get("group_barcode_manual_confirmed")) or _text(
        group.get("auto_archive_source")
    ) == "manual_confirmed"
    if manually_confirmed and "人工确认" not in notes:
        notes.append("人工确认")
    return "；".join(dict.fromkeys(notes))


def _append_text_row(sheet: Any, values: Sequence[Any]) -> None:
    sheet.append([str(value or "") for value in values])
    for cell in sheet[sheet.max_row]:
        cell.number_format = "@"
        cell.data_type = "s"


def build_delivery_workbook(groups: Iterable[Mapping[str, Any]]) -> bytes:
    from openpyxl import Workbook

    validated = validate_delivery_groups(groups, require_cache=False)
    workbook = Workbook()
    old_sheet = workbook.active
    old_sheet.title = "老设备"
    new_sheet = workbook.create_sheet("新设备")
    old_sheet.append(list(OLD_DEVICE_HEADERS))
    new_sheet.append(list(NEW_DEVICE_HEADERS))
    old_sheet.freeze_panes = "A2"
    new_sheet.freeze_panes = "A2"
    for group in validated:
        identity = _group_identity(group)
        _append_text_row(
            old_sheet,
            (
                identity["terminal"],
                "",
                identity["address"],
                identity["meter_no"],
                identity["collector"],
                "南大供电服务中心",
                "奕福",
                "",
                "",
            ),
        )
        _append_text_row(
            new_sheet,
            (
                _local_date(_completed_at(group)),
                identity["meter_no"],
                identity["module_asset_no"],
                _delivery_remark(group),
            ),
        )
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def sanitize_delivery_path_part(value: Any) -> str:
    text = _INVALID_WINDOWS_PART.sub("_", str(value or ""))
    text = _TRAILING_WINDOWS_PART.sub(lambda match: "_" * len(match.group()), text)
    return text or "_"


def _photo_extension(photo: Mapping[str, Any]) -> str:
    for value in (
        photo.get("original_filename"),
        photo.get("source_file"),
        str(photo.get("image_url") or "").split("?", 1)[0],
        photo.get("delivery_cache_path"),
    ):
        suffix = Path(str(value or "")).suffix.lower()
        if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
            return suffix
    return ".jpg"


def _collision_name(path: str, group_id: str, used: set[str]) -> str:
    if path not in used:
        return path
    candidate = Path(path)
    suffix = candidate.suffix
    stable_id = sanitize_delivery_path_part(group_id)
    collided = str(candidate.with_name(f"{candidate.stem}-{stable_id}{suffix}")).replace("\\", "/")
    serial = 2
    while collided in used:
        collided = str(candidate.with_name(f"{candidate.stem}-{stable_id}-{serial}{suffix}")).replace("\\", "/")
        serial += 1
    return collided


def build_delivery_package(
    groups: Iterable[Mapping[str, Any]],
    photo_reader: Callable[[dict[str, Any]], bytes],
) -> bytes:
    validated = validate_delivery_groups(groups)
    output = BytesIO()
    used_names = {"设备清单.xlsx"}
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("设备清单.xlsx", build_delivery_workbook(validated))
        for group in validated:
            identity = _group_identity(group)
            group_id = _text(group.get("id")) or "group"
            directory = "/".join(
                (
                    sanitize_delivery_path_part(identity["terminal"]),
                    sanitize_delivery_path_part(
                        f'{identity["meter_no"]}-{identity["module_asset_no"]}-{identity["address"]}'
                    ),
                )
            )
            photos = {str(photo.get("category")): photo for photo in _active_photos(group)}
            for category in STANDARD_PHOTO_ORDER:
                photo = photos[category]
                filename = sanitize_delivery_path_part(
                    f'{identity["module_asset_no"]}-{STANDARD_PHOTO_CATEGORIES[category]}'
                ) + _photo_extension(photo)
                path = _collision_name(f"{directory}/{filename}", group_id, used_names)
                used_names.add(path)
                content = photo_reader(photo)
                if not isinstance(content, bytes) or not content:
                    raise ValueError(f"Empty completed photo cache for {group_id}/{photo.get('id')}")
                archive.writestr(path, content)
    return output.getvalue()


def delivery_evidence_fingerprint(groups: Iterable[Mapping[str, Any]]) -> str:
    payload = []
    for group in sorted(_deduplicated_groups(groups), key=lambda item: _text(item.get("id"))):
        identity = _group_identity(group)
        payload.append(
            {
                "id": _text(group.get("id")),
                **identity,
                "client_completed_at": _completed_at(group),
                "photos": sorted(
                    (
                        {
                            "id": _text(photo.get("id")),
                            "category": _text(photo.get("category")),
                            "sha256": _first_text(
                                photo.get("delivery_cache_content_sha256"), photo.get("sha256")
                            ).lower(),
                            "cache_version": _text(photo.get("delivery_cache_version")),
                        }
                        for photo in _active_photos(group)
                    ),
                    key=lambda item: (item["category"], item["id"]),
                ),
            }
        )
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _package_lock(key: str) -> threading.Lock:
    with _PACKAGE_LOCKS_GUARD:
        return _PACKAGE_LOCKS.setdefault(key, threading.Lock())


def _cache_path_key(path: Path | str) -> str:
    return str(Path(path).resolve()).casefold()


def reserve_delivery_cache_path(path: Path | str) -> str:
    key = _cache_path_key(path)
    with _ACTIVE_CACHE_PATHS_GUARD:
        _ACTIVE_CACHE_PATHS[key] = _ACTIVE_CACHE_PATHS.get(key, 0) + 1
    return key


def release_delivery_cache_path(lease: Path | str) -> None:
    key = str(lease).casefold()
    with _ACTIVE_CACHE_PATHS_GUARD:
        count = _ACTIVE_CACHE_PATHS.get(key, 0)
        if count <= 1:
            _ACTIVE_CACHE_PATHS.pop(key, None)
        else:
            _ACTIVE_CACHE_PATHS[key] = count - 1


def _active_cache_path_keys() -> set[str]:
    with _ACTIVE_CACHE_PATHS_GUARD:
        return {key for key, count in _ACTIVE_CACHE_PATHS.items() if count > 0}


def cleanup_delivery_cache(
    cache_root: Path,
    *,
    max_object_bytes: int,
    groups: Iterable[Mapping[str, Any]],
    now: datetime | None = None,
) -> dict[str, int]:
    root = Path(cache_root).resolve()
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    active = _active_cache_path_keys()
    referenced: set[str] = set()
    for group in groups:
        if _text(group.get("delivery_cache_status")) != "ready":
            continue
        for photo in _active_photos(group):
            if _text(photo.get("delivery_cache_status")) != "ready":
                continue
            relative = _text(photo.get("delivery_cache_path"))
            if not relative:
                continue
            candidate = (root / relative).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            referenced.add(_cache_path_key(candidate))

    object_root = root / "objects"
    object_files = [path for path in object_root.rglob("*") if path.is_file()] if object_root.exists() else []
    total_bytes = sum(path.stat().st_size for path in object_files)
    protected = active | referenced
    if _cache_path_key(object_root) in active:
        protected.update(_cache_path_key(path) for path in object_files)
    deleted_objects = 0
    protected_objects = 0
    for path in sorted(object_files, key=lambda item: (item.stat().st_mtime, str(item))):
        key = _cache_path_key(path)
        if key in protected:
            protected_objects += 1
            continue
        if total_bytes <= max(0, int(max_object_bytes)):
            continue
        size = path.stat().st_size
        path.unlink(missing_ok=True)
        total_bytes -= size
        deleted_objects += 1

    deleted_packages = 0
    package_root = root / "packages"
    if package_root.exists():
        expires_before = current.astimezone(UTC) - PACKAGE_TTL
        for path in package_root.rglob("*.zip"):
            if not path.is_file() or _cache_path_key(path) in active:
                continue
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            if modified < expires_before:
                path.unlink(missing_ok=True)
                deleted_packages += 1
    return {
        "deleted_objects": deleted_objects,
        "protected_objects": protected_objects,
        "remaining_object_bytes": total_bytes,
        "deleted_packages": deleted_packages,
    }


def get_or_build_delivery_package(
    scope: str,
    evidence_fingerprint: str,
    *,
    groups: Iterable[Mapping[str, Any]],
    photo_reader: Callable[[dict[str, Any]], bytes],
    cache_root: Path,
    now: datetime | None = None,
    package_builder: Callable[
        [Iterable[Mapping[str, Any]], Callable[[dict[str, Any]], bytes]], bytes
    ] = build_delivery_package,
) -> Path:
    validated_groups = validate_delivery_groups(groups)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    fingerprint = _text(evidence_fingerprint).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError("Invalid delivery evidence fingerprint")
    scope_hash = hashlib.sha256(_text(scope).encode("utf-8")).hexdigest()[:24]
    package_dir = Path(cache_root).resolve() / "packages" / scope_hash
    target = package_dir / f"{fingerprint}.zip"
    lock_key = str(target).lower()
    with _package_lock(lock_key):
        if target.is_file():
            modified = datetime.fromtimestamp(target.stat().st_mtime, tz=UTC)
            if current.astimezone(UTC) - modified <= PACKAGE_TTL:
                return target
        content = package_builder(validated_groups, photo_reader)
        package_dir.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f".zip.tmp-{uuid4().hex}")
        try:
            with temporary.open("xb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.utime(temporary, (current.timestamp(), current.timestamp()))
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target
