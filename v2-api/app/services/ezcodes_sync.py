from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.services.matching import build_long_scan_match_key


EZCODES_ENV_ID = "cloud1-8g4k4khc04701207"
EZCODES_CLOUD_API_ENDPOINT = "https://cloud1-8g4k4khc04701207.ap-shanghai.tcb-api.tencentcloudapi.com/web"
EZCODES_DATA_VERSION = "2020-01-10"
EZCODES_ROOT_FOLDER = "\u6a21\u5757\u6539\u9020"
EZCODES_ROOT_PARENT_NAME = "\u6279\u91cf\u626b\u7801"
EZCODES_INSTALLERS = (
    "\u7f57\u7231\u6c11",
    "\u9f99\u7fd4",
    "\u5f20\u6d77\u519b",
    "\u9093\u5353",
)


class EzcodesError(ValueError):
    pass


@dataclass(frozen=True)
class EzcodesCredentials:
    access_token: str
    team_id: str
    env_id: str = EZCODES_ENV_ID
    endpoint: str = EZCODES_CLOUD_API_ENDPOINT


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


class EzcodesCloudBaseBackend:
    def __init__(self, page_size: int = 1000, timeout_seconds: int = 30) -> None:
        self.page_size = page_size
        self.timeout_seconds = timeout_seconds

    def list_files(self, credentials: EzcodesCredentials, parent_id: str) -> list[EzcodesFile]:
        docs = self._query_all(
            credentials,
            collection_name="BGFiles",
            query={
                "teamId": {"$eq": credentials.team_id},
                "parentId": parent_id,
                "moduleType": {"$ne": 1},
                "delete": {"$ne": True},
            },
            order=[{"field": "createTime", "direction": "desc"}],
        )
        return [parse_file_document(item) for item in docs]

    def list_barcodes(self, credentials: EzcodesCredentials, file_id: str) -> list[dict[str, Any]]:
        return self._query_all(
            credentials,
            collection_name="BGBarcodes",
            query={
                "teamId": {"$eq": credentials.team_id},
                "fileId": {"$eq": file_id},
                "delete": {"$ne": True},
            },
            order=[{"field": "createTime", "direction": "asc"}],
        )

    def get_temp_file_urls(self, credentials: EzcodesCredentials, file_ids: list[str]) -> dict[str, str]:
        if not file_ids:
            return {}
        result: dict[str, str] = {}
        for batch in chunked(file_ids, 50):
            result.update(self._get_temp_file_url_batch(credentials, batch))
        return result

    def _get_temp_file_url_batch(self, credentials: EzcodesCredentials, file_ids: list[str]) -> dict[str, str]:
        payload = {
            "action": "storage.batchGetDownloadUrl",
            "dataVersion": EZCODES_DATA_VERSION,
            "env": credentials.env_id,
            "file_list": [{"fileid": file_id, "max_age": 7200} for file_id in file_ids],
            "access_token": credentials.access_token,
        }
        response = self._request(credentials, payload)
        download_list = response.get("data", {}).get("download_list") or response.get("fileList") or []
        result: dict[str, str] = {}
        for item in download_list:
            file_id = str(item.get("fileid") or item.get("fileID") or "")
            url = str(item.get("download_url") or item.get("tempFileURL") or item.get("url") or "")
            if file_id and url:
                result[file_id] = url
        return result

    def _query_all(
        self,
        credentials: EzcodesCredentials,
        collection_name: str,
        query: dict[str, Any],
        order: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        offset = 0
        while True:
            payload = {
                "action": "database.queryDocument",
                "dataVersion": EZCODES_DATA_VERSION,
                "env": credentials.env_id,
                "collectionName": collection_name,
                "queryType": "WHERE",
                "query": query,
                "order": order,
                "limit": self.page_size,
                "offset": offset,
                "access_token": credentials.access_token,
            }
            response = self._request(credentials, payload)
            docs = parse_document_list(response)
            result.extend(docs)
            if len(docs) < self.page_size:
                break
            offset += self.page_size
        return result

    def _request(self, credentials: EzcodesCredentials, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            credentials.endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise EzcodesError(f"CloudBase request failed with HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise EzcodesError(f"CloudBase request failed: {reason}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EzcodesError("CloudBase returned invalid JSON") from exc
        if data.get("code"):
            raise EzcodesError(str(data.get("message") or data.get("msg") or data.get("code")))
        return data


def build_target_sync_plan(
    backend: EzcodesBackend,
    credentials: EzcodesCredentials,
    max_total_files: int | None = None,
) -> dict[str, Any]:
    root = find_single_folder(backend.list_files(credentials, "0"), EZCODES_ROOT_FOLDER, parent_name=EZCODES_ROOT_PARENT_NAME)
    installer_folders = backend.list_files(credentials, root.id)

    files_by_installer: dict[str, list[EzcodesFile]] = {}
    missing_installers: list[str] = []
    remaining_files = max_total_files
    for installer in EZCODES_INSTALLERS:
        folder = find_folder(installer_folders, installer)
        if folder is None:
            missing_installers.append(installer)
            files_by_installer[installer] = []
            continue
        if remaining_files is not None and remaining_files <= 0:
            files_by_installer[installer] = []
            continue
        files = collect_scan_files(backend, credentials, folder.id, max_files=remaining_files)
        files_by_installer[installer] = files
        if remaining_files is not None:
            remaining_files -= len(files)

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


def download_scan_data_preview(
    backend: EzcodesBackend,
    credentials: EzcodesCredentials,
    max_files: int = 5,
    max_records_per_file: int = 20,
) -> dict[str, Any]:
    plan = build_target_sync_plan(backend, credentials, max_total_files=max_files)
    files_to_read = []
    for installer in plan["installers"]:
        for file_info in installer["files"]:
            files_to_read.append({"installer": installer["name"], **file_info})
            if len(files_to_read) >= max_files:
                break
        if len(files_to_read) >= max_files:
            break

    records: list[EzcodesScanRecord] = []
    invalid_records: list[dict[str, str]] = []
    image_file_ids: list[str] = []
    for file_info in files_to_read:
        file = EzcodesFile(
            id=file_info["id"],
            name=file_info["name"],
            type=1,
            parent_id="",
            created_at=file_info.get("created_at", ""),
        )
        raw_rows = backend.list_barcodes(credentials, file.id)[:max_records_per_file]
        for raw in raw_rows:
            try:
                record = normalize_barcode_record(raw, file=file, installer=file_info["installer"])
            except EzcodesError as exc:
                invalid_records.append({"file_id": file.id, "reason": str(exc)})
                continue
            records.append(record)
            image_file_ids.extend(record.image_file_ids)

    temp_urls = backend.get_temp_file_urls(credentials, unique_preserve_order(image_file_ids))
    return {
        "plan": plan,
        "tested_files": len(files_to_read),
        "downloaded_records": len(records),
        "invalid_records": invalid_records,
        "image_file_ids": len(unique_preserve_order(image_file_ids)),
        "resolved_image_urls": len(temp_urls),
        "records": [serialize_scan_record(record, temp_urls) for record in records],
        "sample_records": [serialize_scan_record(record, temp_urls) for record in records[:10]],
    }


def collect_scan_files(
    backend: EzcodesBackend,
    credentials: EzcodesCredentials,
    parent_id: str,
    max_files: int | None = None,
) -> list[EzcodesFile]:
    result: list[EzcodesFile] = []
    pending = [parent_id]
    while pending:
        current_parent = pending.pop()
        children = sorted(backend.list_files(credentials, current_parent), key=lambda item: (item.created_at, item.name, item.id))
        for item in children:
            if item.is_folder:
                pending.append(item.id)
            else:
                result.append(item)
                if max_files is not None and len(result) >= max_files:
                    return result
    return result


def normalize_barcode_record(raw: dict[str, Any], file: EzcodesFile, installer: str) -> EzcodesScanRecord:
    barcode = pick_text(raw, "txtValue", "barcode", "\u626b\u7801\u5185\u5bb9")
    if not barcode:
        raise EzcodesError("Barcode record is missing txtValue.")
    try:
        meter_match_key = build_long_scan_match_key(barcode)
    except ValueError as exc:
        raise EzcodesError(f"Barcode cannot produce match key: {barcode}") from exc

    return EzcodesScanRecord(
        file_id=file.id,
        source_file=file.name,
        installer=installer,
        barcode=barcode,
        meter_match_key=meter_match_key,
        terminal=pick_text(raw, "terminal", "\u7ec8\u7aef"),
        collector=pick_text(raw, "collector", "\u91c7\u96c6\u5668"),
        meter_no=pick_text(raw, "meterNo", "meter_no", "\u8868\u53f7"),
        module_asset_no=pick_text(raw, "asset_no", "assetNo", "moduleAssetNo", "\u6a21\u5757\u8d44\u4ea7\u7f16\u53f7"),
        address=pick_text(raw, "address", "\u5730\u5740"),
        asset_type=pick_text(raw, "assetType", "asset_type", "\u8d44\u4ea7\u7c7b\u578b"),
        creator=pick_text(raw, "creator", "\u521b\u5efa\u8005"),
        created_at=pick_text(raw, "createTime", "created_at", "\u521b\u5efa\u65f6\u95f4"),
        image_file_ids=tuple(normalize_images(raw.get("images") or raw.get("\u56fe\u7247") or [])),
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
        raise EzcodesError(f"Folder not found: {parent_name}/{name}")
    return folder


def find_folder(files: list[EzcodesFile], name: str) -> EzcodesFile | None:
    return next((item for item in files if item.is_folder and item.name == name), None)


def parse_document_list(response: dict[str, Any]) -> list[dict[str, Any]]:
    raw_list = response.get("data", {}).get("list", [])
    docs = []
    for item in raw_list:
        if isinstance(item, str):
            docs.append(json.loads(item))
        elif isinstance(item, dict):
            docs.append(item)
    return docs


def parse_file_document(item: dict[str, Any]) -> EzcodesFile:
    return EzcodesFile(
        id=str(item.get("_id") or item.get("id") or ""),
        name=str(item.get("name") or ""),
        type=int(item.get("type") or 0),
        parent_id=str(item.get("parentId") or ""),
        creator=str(item.get("creator") or item.get("userId") or ""),
        created_at=str(item.get("createTime") or ""),
        raw=item,
    )


def serialize_scan_record(record: EzcodesScanRecord, temp_urls: dict[str, str]) -> dict[str, Any]:
    return {
        "file_id": record.file_id,
        "source_file": record.source_file,
        "installer": record.installer,
        "barcode": record.barcode,
        "meter_match_key": record.meter_match_key,
        "terminal": record.terminal,
        "collector": record.collector,
        "meter_no": record.meter_no,
        "module_asset_no": record.module_asset_no,
        "address": record.address,
        "asset_type": record.asset_type,
        "creator": record.creator,
        "created_at": record.created_at,
        "image_count": len(record.image_file_ids),
        "image_urls": [temp_urls[file_id] for file_id in record.image_file_ids if file_id in temp_urls],
    }


def unique_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]
