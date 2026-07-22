from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from contextlib import contextmanager
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
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
@dataclass
class _PackageLockEntry:
    lock: threading.Lock
    references: int = 0


_PACKAGE_LOCKS: dict[str, _PackageLockEntry] = {}
_PACKAGE_LOCKS_GUARD = threading.Lock()
_ACTIVE_CACHE_PATHS: dict[str, int] = {}
_CACHE_PATH_CONDITION = threading.Condition(threading.Lock())


class DeliveryPackageValidationError(ValueError):
    def __init__(self, errors: Sequence[Mapping[str, Any]]):
        self.errors = [dict(error) for error in errors]
        super().__init__("Formal delivery package validation failed")


@dataclass(eq=False)
class LeasedDeliveryPackage:
    path: Path
    lease: str
    _released: bool = field(default=False, init=False, repr=False)
    _release_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __fspath__(self) -> str:
        return os.fspath(self.path)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.path, name)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, LeasedDeliveryPackage):
            return self.path == other.path
        return self.path == other

    def release(self) -> None:
        with self._release_lock:
            if self._released:
                return
            self._released = True
        release_delivery_cache_path(self.lease)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(*values: Any) -> str:
    return next((_text(value) for value in values if _text(value)), "")


def _active_photos(group: Mapping[str, Any]) -> list[dict[str, Any]]:
    from app.services.local_simulation import is_valid_photo_evidence

    return [
        dict(photo)
        for photo in group.get("photos", []) or []
        if isinstance(photo, Mapping) and is_valid_photo_evidence(photo)
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
                if _text(photo.get("delivery_cache_status")) == "invalid":
                    errors.append(
                        _error(group_id, "delivery_cache_invalid", "photos", "Completed photo cache is invalid")
                    )
                    break
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
    for field in ("replacement_remark", "export_remark", "delivery_export_remark"):
        value = _text(group.get(field))
        if value:
            notes.append(value)
    manually_confirmed = bool(group.get("group_barcode_manual_confirmed")) or _text(
        group.get("auto_archive_source")
    ) == "manual_confirmed"
    if manually_confirmed and "人工确认" not in notes:
        notes.append("人工确认")
    return "；".join(dict.fromkeys(notes))


def _workbook_rows(group: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    identity = _group_identity(group)
    return {
        "old": (
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
        "new": (
            _local_date(_completed_at(group)),
            identity["meter_no"],
            identity["module_asset_no"],
            _delivery_remark(group),
        ),
    }


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
        rows = _workbook_rows(group)
        _append_text_row(old_sheet, rows["old"])
        _append_text_row(new_sheet, rows["new"])
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


def _windows_member_key(path: str) -> str:
    return "/".join(part.rstrip(" .").casefold() for part in path.replace("\\", "/").split("/"))


def _collision_name(path: str, group_id: str, discriminator: str = "") -> str:
    candidate = Path(path)
    suffix = candidate.suffix
    stable_id = sanitize_delivery_path_part(group_id)
    if discriminator:
        stable_id = f"{stable_id}-{hashlib.sha256(discriminator.encode('utf-8')).hexdigest()[:8]}"
    return str(candidate.with_name(f"{candidate.stem}-{stable_id}{suffix}")).replace("\\", "/")


def _delivery_photo_members(groups: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for group in sorted(groups, key=lambda item: _text(item.get("id"))):
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
            path = f"{directory}/{filename}"
            candidates.append(
                {
                    "group_id": group_id,
                    "photo": photo,
                    "path": path,
                    "member_key": _windows_member_key(path),
                    "discriminator": f'{group_id}|{category}|{_text(photo.get("id"))}',
                    "category_order": STANDARD_PHOTO_ORDER.index(category),
                }
            )
    collision_counts: dict[str, int] = {}
    for candidate in candidates:
        key = candidate["member_key"]
        collision_counts[key] = collision_counts.get(key, 0) + 1
    assigned: set[str] = set()
    for candidate in sorted(
        candidates,
        key=lambda item: (item["member_key"], item["group_id"].casefold(), item["discriminator"]),
    ):
        path = candidate["path"]
        if collision_counts[candidate["member_key"]] > 1:
            path = _collision_name(path, candidate["group_id"])
        key = _windows_member_key(path)
        if key in assigned:
            path = _collision_name(candidate["path"], candidate["group_id"], candidate["discriminator"])
            key = _windows_member_key(path)
        assigned.add(key)
        candidate["path"] = path
    return sorted(
        candidates,
        key=lambda item: (item["group_id"].casefold(), item["group_id"], item["category_order"]),
    )


def build_delivery_package(
    groups: Iterable[Mapping[str, Any]],
    photo_reader: Callable[[dict[str, Any]], bytes],
) -> bytes:
    validated = sorted(validate_delivery_groups(groups), key=lambda item: _text(item.get("id")))
    members = _delivery_photo_members(validated)
    errors: list[dict[str, str]] = []
    for member in members:
        photo = member["photo"]
        group_id = member["group_id"]
        try:
            content = photo_reader(photo)
        except DeliveryPackageValidationError as exc:
            errors.extend(exc.errors)
            continue
        except Exception:
            errors.append(
                _error(group_id, "delivery_cache_invalid", "photos", "Completed photo cache could not be read")
            )
            continue
        expected_sha256 = _text(photo.get("delivery_cache_content_sha256")).lower()
        if (
            not isinstance(content, bytes)
            or not content
            or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
            or hashlib.sha256(content).hexdigest() != expected_sha256
        ):
            errors.append(
                _error(group_id, "delivery_cache_invalid", "photos", "Completed photo cache failed integrity verification")
            )
            continue
        member["content"] = content
    if errors:
        raise DeliveryPackageValidationError(errors)
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("设备清单.xlsx", build_delivery_workbook(validated))
        for member in members:
            archive.writestr(member["path"], member["content"])
    return output.getvalue()


def delivery_evidence_fingerprint(groups: Iterable[Mapping[str, Any]]) -> str:
    payload = []
    for group in sorted(_deduplicated_groups(groups), key=lambda item: _text(item.get("id"))):
        payload.append(
            {
                "id": _text(group.get("id")),
                "workbook_rows": _workbook_rows(group),
                "photos": sorted(
                    (
                        {
                            "id": _text(photo.get("id")),
                            "category": _text(photo.get("category")),
                            "sha256": _first_text(
                                photo.get("delivery_cache_content_sha256"), photo.get("sha256")
                            ).lower(),
                            "cache_version": _text(photo.get("delivery_cache_version")),
                            "extension": _photo_extension(photo),
                        }
                        for photo in _active_photos(group)
                    ),
                    key=lambda item: (item["category"], item["id"]),
                ),
            }
        )
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


@contextmanager
def _package_lock(key: str):
    with _PACKAGE_LOCKS_GUARD:
        entry = _PACKAGE_LOCKS.get(key)
        if entry is None:
            entry = _PackageLockEntry(threading.Lock())
            _PACKAGE_LOCKS[key] = entry
        entry.references += 1
    entry.lock.acquire()
    try:
        yield
    finally:
        entry.lock.release()
        with _PACKAGE_LOCKS_GUARD:
            entry.references -= 1
            if entry.references == 0 and _PACKAGE_LOCKS.get(key) is entry:
                _PACKAGE_LOCKS.pop(key, None)


def _cache_path_key(path: Path | str) -> str:
    return str(Path(path).resolve()).casefold()


def reserve_delivery_cache_path(path: Path | str) -> str:
    key = _cache_path_key(path)
    with _CACHE_PATH_CONDITION:
        _reserve_delivery_cache_key_locked(key)
    return key


def _reserve_delivery_cache_key_locked(key: str) -> None:
    _ACTIVE_CACHE_PATHS[key] = _ACTIVE_CACHE_PATHS.get(key, 0) + 1


def release_delivery_cache_path(lease: Path | str) -> None:
    key = str(lease).casefold()
    with _CACHE_PATH_CONDITION:
        count = _ACTIVE_CACHE_PATHS.get(key, 0)
        if count <= 1:
            _ACTIVE_CACHE_PATHS.pop(key, None)
        else:
            _ACTIVE_CACHE_PATHS[key] = count - 1
        _CACHE_PATH_CONDITION.notify_all()


def _cache_path_is_reserved(key: str) -> bool:
    separator = os.sep.casefold()
    return any(
        count > 0 and (key == reserved or key.startswith(f"{reserved.rstrip(separator)}{separator}"))
        for reserved, count in _ACTIVE_CACHE_PATHS.items()
    )


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
    deleted_objects = 0
    protected_objects = 0
    for path in sorted(object_files, key=lambda item: (item.stat().st_mtime, str(item))):
        key = _cache_path_key(path)
        if key in referenced:
            protected_objects += 1
            continue
        if total_bytes <= max(0, int(max_object_bytes)):
            continue
        with _CACHE_PATH_CONDITION:
            if _cache_path_is_reserved(key):
                protected_objects += 1
                continue
            try:
                size = path.stat().st_size
                path.unlink()
            except FileNotFoundError:
                continue
            total_bytes -= size
            deleted_objects += 1

    deleted_packages = 0
    package_root = root / "packages"
    if package_root.exists():
        expires_before = current.astimezone(UTC) - PACKAGE_TTL
        for path in package_root.rglob("*.zip"):
            if not path.is_file():
                continue
            key = _cache_path_key(path)
            with _CACHE_PATH_CONDITION:
                if _cache_path_is_reserved(key):
                    continue
                try:
                    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
                    if modified < expires_before:
                        path.unlink()
                        deleted_packages += 1
                except FileNotFoundError:
                    continue
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
) -> LeasedDeliveryPackage:
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
        target_key = _cache_path_key(target)
        with _CACHE_PATH_CONDITION:
            if target.is_file():
                modified = datetime.fromtimestamp(target.stat().st_mtime, tz=UTC)
                if current.astimezone(UTC) - modified <= PACKAGE_TTL:
                    _reserve_delivery_cache_key_locked(target_key)
                    return LeasedDeliveryPackage(target, target_key)
        content = package_builder(validated_groups, photo_reader)
        package_dir.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f".zip.tmp-{uuid4().hex}")
        try:
            with temporary.open("xb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.utime(temporary, (current.timestamp(), current.timestamp()))
            with _CACHE_PATH_CONDITION:
                while _cache_path_is_reserved(target_key):
                    _CACHE_PATH_CONDITION.wait()
                temporary.replace(target)
                _reserve_delivery_cache_key_locked(target_key)
                return LeasedDeliveryPackage(target, target_key)
        finally:
            temporary.unlink(missing_ok=True)
