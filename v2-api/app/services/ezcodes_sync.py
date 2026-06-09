from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.services.matching import build_long_scan_match_key


EZCODES_ENV_ID = "cloud1-8g4k4khc04701207"
EZCODES_ROOT_FOLDER = "模块改造"
EZCODES_INSTALLERS = ("罗爱民", "龙翔", "张海军", "邓卓")


class EzcodesError(ValueError):
    pass


@dataclass(frozen=True)
class EzcodesCredentials:
    access_token: str
    team_id: str
    env_id: str = EZCODES_ENV_ID


@dataclass(frozen=True)
class EzcodesFile:
    id: str
    name: str
    type: int
    parent_id: str
    creator: str = ""
    created_at: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_folder(self) -> bool:
        return self.type == 0


@dataclass(frozen=True)
class EzcodesScanRecord:
    file_id: str
    source_file: str
    installer: str
    barcode: str
    meter_match_key: str
    terminal: str
    collector: str
    meter_no: str
    module_asset_no: str
    address: str
    asset_type: str
    creator: str
    created_at: str
    image_file_ids: tuple[str, ...]
    raw: dict[str, Any] = field(default_factory=dict)


class EzcodesBackend(Protocol):
    def list_files(self, credentials: EzcodesCredentials, parent_id: str) -> list[EzcodesFile]:
        ...

    def list_barcodes(self, credentials: EzcodesCredentials, file_id: str) -> list[dict[str, Any]]:
        ...

    def get_temp_file_urls(self, credentials: EzcodesCredentials, file_ids: list[str]) -> dict[str, str]:
        ...


def build_target_sync_plan(backend: EzcodesBackend, credentials: EzcodesCredentials) -> dict[str, Any]:
    root = find_single_folder(backend.list_files(credentials, "0"), EZCODES_ROOT_FOLDER, parent_name="批量扫码")
    installer_folders = backend.list_files(credentials, root.id)

    files_by_installer: dict[str, list[EzcodesFile]] = {}
    missing_installers: list[str] = []
    for installer in EZCODES_INSTALLERS:
        folder = find_folder(installer_folders, installer)
        if folder is None:
            missing_installers.append(installer)
            files_by_installer[installer] = []
            continue
        files_by_installer[installer] = collect_scan_files(backend, credentials, folder.id)

    total_files = sum(len(files) for files in files_by_installer.values())
    return {
        "env_id": credentials.env_id,
        "team_id": credentials.team_id,
        "root_folder": {"id": root.id, "name": root.name},
        "installers": [
            {
                "name": installer,
                "file_count": len(files_by_installer[installer]),
                "files": [{"id": item.id, "name": item.name, "created_at": item.created_at} for item in files_by_installer[installer]],
            }
            for installer in EZCODES_INSTALLERS
        ],
        "missing_installers": missing_installers,
        "total_files": total_files,
    }


def collect_scan_files(backend: EzcodesBackend, credentials: EzcodesCredentials, parent_id: str) -> list[EzcodesFile]:
    result: list[EzcodesFile] = []
    pending = [parent_id]
    while pending:
        current_parent = pending.pop()
        for item in backend.list_files(credentials, current_parent):
            if item.is_folder:
                pending.append(item.id)
            else:
                result.append(item)
    return sorted(result, key=lambda item: (item.created_at, item.name, item.id))


def normalize_barcode_record(raw: dict[str, Any], file: EzcodesFile, installer: str) -> EzcodesScanRecord:
    barcode = pick_text(raw, "txtValue", "barcode", "扫码内容")
    if not barcode:
        raise EzcodesError("扫码记录缺少扫码内容")
    try:
        meter_match_key = build_long_scan_match_key(barcode)
    except ValueError as exc:
        raise EzcodesError(f"扫码内容无法生成匹配键: {barcode}") from exc

    return EzcodesScanRecord(
        file_id=file.id,
        source_file=file.name,
        installer=installer,
        barcode=barcode,
        meter_match_key=meter_match_key,
        terminal=pick_text(raw, "terminal", "终端"),
        collector=pick_text(raw, "collector", "采集器"),
        meter_no=pick_text(raw, "meterNo", "meter_no", "表号"),
        module_asset_no=pick_text(raw, "asset_no", "assetNo", "moduleAssetNo", "模块资产编号"),
        address=pick_text(raw, "address", "地址"),
        asset_type=pick_text(raw, "assetType", "asset_type", "资产类型"),
        creator=pick_text(raw, "creator", "创建者"),
        created_at=pick_text(raw, "createTime", "created_at", "创建时间"),
        image_file_ids=tuple(normalize_images(raw.get("images") or raw.get("图片") or [])),
        raw=raw,
    )


def normalize_images(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple):
        return [str(item) for item in value if item]
    return [str(value)]


def pick_text(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    custom = data.get("customFieldValue")
    if isinstance(custom, dict):
        for key in keys:
            value = custom.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return ""


def find_single_folder(files: list[EzcodesFile], name: str, parent_name: str) -> EzcodesFile:
    folder = find_folder(files, name)
    if folder is None:
        raise EzcodesError(f"未找到目录: {parent_name}/{name}")
    return folder


def find_folder(files: list[EzcodesFile], name: str) -> EzcodesFile | None:
    return next((item for item in files if item.is_folder and item.name == name), None)
