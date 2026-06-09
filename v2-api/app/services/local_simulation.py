from __future__ import annotations

from io import BytesIO
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.matching import build_long_scan_match_key, build_total_catalog_match_key


DEFAULT_TOTAL_CATALOG = Path("C:/Users/Administrator/Desktop/\u603b\u4f53\u6570\u636e.xlsx")
DEFAULT_STAGE_CATALOG = Path("C:/Users/Administrator/Desktop/\u7b2c\u4e00\u6279\u6570\u636e.xlsx")
DEFAULT_SCAN_FILE = Path("C:/Users/Administrator/Desktop/\u6279\u91cf\u626b\u7801_20260608125555.xlsx")
REVIEWABLE_STATUSES = {"pending", "incomplete", "approved", "exception", "unmatched"}
OPEN_STATUSES = {"pending", "incomplete", "unmatched"}
DONE_STATUSES = {"approved", "exception"}
PHOTO_CATEGORIES = {
    "unclassified": "\u672a\u5206\u7c7b",
    "before_box": "\u8868\u7bb1\u6574\u4f53\u6539\u9020\u524d",
    "after_box": "\u8868\u7bb1\u6574\u4f53\u6539\u9020\u540e",
    "module_meter": "\u6a21\u5757\u4e0e\u7535\u80fd\u8868",
    "collector_barcode": "\u91c7\u96c6\u5668\u6761\u5f62\u7801",
    "other": "\u5176\u4ed6",
}


@dataclass(frozen=True)
class LocalTestPaths:
    total_catalog: Path = DEFAULT_TOTAL_CATALOG
    stage_catalog: Path = DEFAULT_STAGE_CATALOG
    scan_file: Path = DEFAULT_SCAN_FILE


_state: dict[str, Any] = {
    "loaded": False,
    "paths": {},
    "summary": {},
    "projects": [],
    "tasks": [],
    "groups": [],
    "scan_unmatched": [],
    "stage_unmatched": [],
    "review_events": [],
    "photo_events": [],
}


def get_state() -> dict[str, Any]:
    if not _state["loaded"]:
        bootstrap_local_simulation()
    return _state


def clear_scan_data() -> dict[str, Any]:
    state = get_state()
    for group in state["groups"]:
        group["photos"] = []
        group["photo_count"] = 0
        if group["status"] != "unmatched":
            group["status"] = "incomplete"
        group["reviewer"] = None
        group["review_note"] = ""
        group["exception_note"] = ""
        group["reviewed_at"] = None
    state["scan_unmatched"] = []
    state["photo_events"] = []
    state["summary"]["scan_rows"] = 0
    refresh_summary()
    return state


def apply_synced_scan_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    state = get_state()
    groups_by_key = {group["meter_match_key"]: group for group in state["groups"]}
    known_photo_keys = {
        make_photo_unique_key(photo)
        for group in state["groups"]
        for photo in group.get("photos", [])
    }
    applied = 0
    skipped_duplicates = 0
    unmatched = []
    for index, record in enumerate(records, start=1):
        match_key = str(record.get("meter_match_key") or "")
        group = groups_by_key.get(match_key)
        if group is None:
            unmatched.append(record)
            continue
        rows = scan_record_to_photo_rows(record, index)
        group_changed = False
        for row in rows:
            unique_key = make_scan_unique_key(row)
            if unique_key in known_photo_keys:
                skipped_duplicates += 1
                continue
            photo = build_photo_record(group["photo_count"] + 1, row)
            group["photos"].append(photo)
            group["photo_count"] = len(group["photos"])
            known_photo_keys.add(unique_key)
            applied += 1
            group_changed = True
        if group_changed and (group["status"] in DONE_STATUSES or group["status"] in OPEN_STATUSES):
            group["status"] = "incomplete" if group["photo_count"] < 4 else "pending"
            group["reviewer"] = None
            group["review_note"] = ""
            group["exception_note"] = ""
            group["reviewed_at"] = None
    state["scan_unmatched"] = unmatched
    state["summary"]["scan_rows"] = sum(group["photo_count"] for group in state["groups"]) + len(unmatched)
    refresh_summary()
    return {
        "received_records": len(records),
        "applied_records": applied,
        "skipped_duplicates": skipped_duplicates,
        "unmatched_records": len(unmatched),
        "summary": state["summary"],
    }


def import_url_scan_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    records = [normalize_url_import_row(row, index) for index, row in enumerate(rows, start=1)]
    return apply_synced_scan_records(records)


def import_scan_template_xlsx(content: bytes) -> dict[str, Any]:
    rows = read_scan_template_xlsx_rows(content)
    result = import_url_scan_rows(rows)
    result["template_rows"] = len(rows)
    return result


def read_scan_template_xlsx_rows(content: bytes) -> list[dict[str, Any]]:
    load_workbook = get_workbook_loader()
    workbook = load_workbook(BytesIO(content), read_only=False, data_only=True)
    sheet = workbook.worksheets[0]
    header_cells = next(sheet.iter_rows(min_row=1, max_row=1, values_only=False))
    headers = [normalize_cell(cell.value) for cell in header_cells]
    rows: list[dict[str, Any]] = []
    blank_run = 0
    for row_number, cells in enumerate(sheet.iter_rows(min_row=2, values_only=False), start=2):
        values: dict[str, Any] = {"row_number": row_number}
        for index, cell in enumerate(cells):
            if index >= len(headers) or not headers[index]:
                continue
            header = headers[index]
            value = normalize_cell(cell.value)
            values[header] = value
            if cell.hyperlink and cell.hyperlink.target:
                values[f"{header}_url"] = cell.hyperlink.target
                if "图片" in header:
                    values["photo_urls"] = cell.hyperlink.target
        if not any(str(value).strip() for key, value in values.items() if key != "row_number"):
            blank_run += 1
            if blank_run >= 20:
                break
            continue
        blank_run = 0
        rows.append(values)
    return rows


def normalize_url_import_row(row: dict[str, Any], index: int) -> dict[str, Any]:
    barcode = pick_first(row, "barcode", "scan_code", "扫码内容", "条形码", "长条码")
    meter_no = pick_first(row, "meter_no", "表号", "短表号")
    if not meter_no and barcode:
        meter_no = barcode
    meter_match_key = pick_first(row, "meter_match_key", "匹配键")
    if not meter_match_key:
        if barcode:
            try:
                meter_match_key = build_long_scan_match_key(barcode)
            except ValueError:
                meter_match_key = ""
        elif meter_no:
            meter_match_key = build_total_catalog_match_key(meter_no)
    return {
        "file_id": f"import-row-{index}",
        "source_file": pick_first(row, "source_file", "来源文件", "来自文件", "批次") or "url-import",
        "installer": pick_first(row, "installer", "安装人员", "创建者"),
        "barcode": barcode or meter_no or f"row-{index}",
        "meter_match_key": meter_match_key,
        "terminal": pick_first(row, "terminal", "终端"),
        "collector": pick_first(row, "collector", "采集器"),
        "meter_no": meter_no,
        "module_asset_no": pick_first(row, "module_asset_no", "module", "模块", "模块资产编号"),
        "address": pick_first(row, "address", "地址"),
        "asset_type": pick_first(row, "asset_type", "资产类型"),
        "creator": pick_first(row, "creator", "创建者"),
        "created_at": pick_first(row, "created_at", "创建时间"),
        "image_count": len(split_urls(pick_first(row, "photo_urls", "image_urls", "照片URL", "图片URL", "图片 (电脑查看)_url", "图片(电脑查看)_url", "url", "URL"))),
        "image_urls": split_urls(pick_first(row, "photo_urls", "image_urls", "照片URL", "图片URL", "图片 (电脑查看)_url", "图片(电脑查看)_url", "url", "URL")),
        "image_file_ids": [],
    }


def pick_first(row: dict[str, Any], *keys: str) -> str:
    normalized = {str(key).strip().lower(): value for key, value in row.items()}
    for key in keys:
        value = row.get(key)
        if value is None:
            value = normalized.get(key.lower())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def split_urls(value: str) -> list[str]:
    if not value:
        return []
    normalized = value.replace("\r", "\n").replace("；", ";").replace("，", ",")
    parts = []
    for block in normalized.split("\n"):
        for segment in block.replace(";", ",").split(","):
            item = segment.strip()
            if item:
                parts.append(item)
    return parts


def scan_record_to_photo_rows(record: dict[str, Any], index: int) -> list[dict[str, Any]]:
    image_urls = record.get("image_urls") or []
    image_file_ids = record.get("image_file_ids") or []
    photo_slots = max(len(image_urls), len(image_file_ids), 1)
    rows = []
    for photo_index in range(1, photo_slots + 1):
        image_url = str(image_urls[photo_index - 1]) if photo_index <= len(image_urls) else ""
        image_file_id = str(image_file_ids[photo_index - 1]) if photo_index <= len(image_file_ids) else ""
        rows.append(
            {
                "row_number": f"ez-{record.get('file_id') or index}-{index}-{photo_index}",
                "barcode": str(record.get("barcode") or ""),
                "meter_match_key": str(record.get("meter_match_key") or ""),
                "source_file": str(record.get("source_file") or ""),
                "collector": str(record.get("collector") or ""),
                "asset_no": str(record.get("module_asset_no") or ""),
                "asset_type": str(record.get("asset_type") or ""),
                "creator": str(record.get("creator") or record.get("installer") or ""),
                "created_at": str(record.get("created_at") or ""),
                "has_image": bool(image_url or image_file_id),
                "image_file_id": image_file_id,
                "image_url": str(image_url),
            }
        )
    return rows


def make_scan_unique_key(row: dict[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("barcode") or ""),
            str(row.get("source_file") or ""),
            str(row.get("image_file_id") or ""),
            str(row.get("image_url") or ""),
        ]
    )


def make_photo_unique_key(photo: dict[str, Any]) -> str:
    return "|".join(
        [
            str(photo.get("barcode") or ""),
            str(photo.get("source_file") or ""),
            str(photo.get("image_file_id") or ""),
            str(photo.get("image_url") or ""),
        ]
    )


def apply_group_photo_urls(group_id: str, urls: dict[str, str]) -> dict[str, Any]:
    group = get_group(group_id)
    if group is None:
        raise KeyError(group_id)
    applied = 0
    for photo in group.get("photos", []):
        file_id = str(photo.get("image_file_id") or "")
        if file_id and not photo.get("image_url") and file_id in urls:
            photo["image_url"] = urls[file_id]
            photo["download_status"] = "downloaded"
            photo["downloaded_at"] = now_iso()
            applied += 1
    refresh_summary()
    return {"group_id": group_id, "loaded_photo_urls": applied, "group": group}


def bootstrap_local_simulation(paths: LocalTestPaths | None = None) -> dict[str, Any]:
    paths = paths or LocalTestPaths()
    total_rows = read_catalog_rows(paths.total_catalog, source="total")
    stage_rows = read_catalog_rows(paths.stage_catalog, source="stage")
    scan_rows = read_scan_rows(paths.scan_file)

    total_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in total_rows:
        total_by_key[row["meter_match_key"]].append(row)

    scans_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    scan_unmatched = []
    for row in scan_rows:
        if row["meter_match_key"] in total_by_key:
            scans_by_key[row["meter_match_key"]].append(row)
        else:
            scan_unmatched.append(row)

    terminal_task_ids = build_terminal_task_ids(stage_rows)
    groups = []
    stage_unmatched = []
    for index, stage in enumerate(stage_rows, start=1):
        total_matches = total_by_key.get(stage["meter_match_key"], [])
        total = total_matches[0] if total_matches else None
        photos = [build_photo_record(photo_index, row) for photo_index, row in enumerate(scans_by_key.get(stage["meter_match_key"], []), start=1)]
        terminal = total["terminal"] if total else stage["terminal"]
        status = "pending"
        if not total:
            status = "unmatched"
            stage_unmatched.append(stage)
        elif len(photos) < 4:
            status = "incomplete"

        groups.append(
            {
                "id": f"g-{index:05d}",
                "task_id": terminal_task_ids.get(terminal, 0),
                "meter_match_key": stage["meter_match_key"],
                "meter_no": total["meter_no"] if total else stage["meter_no"],
                "terminal": terminal,
                "address": total["address"] if total else "",
                "stage_meter_no": stage["meter_no"],
                "stage_terminal": stage["terminal"],
                "status": status,
                "reviewer": None,
                "review_note": "",
                "exception_note": "",
                "reviewed_at": None,
                "photo_count": len(photos),
                "photos": photos[:8],
            }
        )

    summary = build_summary(total_rows, stage_rows, scan_rows, groups, stage_unmatched, scan_unmatched)
    tasks = build_terminal_tasks(groups)

    _state.update(
        {
            "loaded": True,
            "paths": {
                "total_catalog": str(paths.total_catalog),
                "stage_catalog": str(paths.stage_catalog),
                "scan_file": str(paths.scan_file),
            },
            "summary": summary,
            "projects": [
                {
                    "id": 1,
                    "name": "V2.1 Local Simulation",
                    "status": "active",
                    "summary": summary,
                }
            ],
            "tasks": tasks,
            "groups": groups,
            "scan_unmatched": scan_unmatched,
            "stage_unmatched": stage_unmatched,
            "review_events": [],
            "photo_events": [],
        }
    )
    return _state


def build_terminal_task_ids(stage_rows: list[dict[str, Any]]) -> dict[str, int]:
    terminals = sorted({row["terminal"] for row in stage_rows if row["terminal"]})
    return {terminal: index for index, terminal in enumerate(terminals, start=1)}


def build_photo_record(photo_index: int, row: dict[str, Any]) -> dict[str, Any]:
    has_image = bool(row.get("has_image"))
    return {
        "id": f"p-{row['row_number']}-{photo_index}",
        "row_number": row["row_number"],
        "barcode": row["barcode"],
        "meter_match_key": row["meter_match_key"],
        "source_file": row.get("source_file", ""),
        "collector": row.get("collector", ""),
        "asset_no": row.get("asset_no", ""),
        "asset_type": row.get("asset_type", ""),
        "creator": row.get("creator", ""),
        "created_at": row.get("created_at", ""),
        "has_image": has_image,
        "download_status": "downloaded" if has_image else "missing",
        "downloaded_at": now_iso() if has_image else None,
        "image_file_id": row.get("image_file_id", ""),
        "image_url": row.get("image_url", ""),
        "category": "unclassified",
        "category_label": PHOTO_CATEGORIES["unclassified"],
        "archive_status": "pending",
        "archive_filename": "",
        "archived_at": None,
    }


def build_terminal_tasks(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_terminal: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for group in groups:
        by_terminal[group["terminal"] or "UNKNOWN"].append(group)

    tasks = []
    for task_id, terminal in enumerate(sorted(by_terminal), start=1):
        terminal_groups = by_terminal[terminal]
        scan_rows = sum(group["photo_count"] for group in terminal_groups)
        has_scan_info = scan_rows > 0
        task = {
            "id": task_id,
            "project_id": 1,
            "terminal": terminal,
            "name": f"终端 {terminal}",
            "status": "published",
            "claimed_by": None,
            "claimed_at": None,
            "released_at": None,
            "total_groups": len(terminal_groups),
            "completed_groups": count_groups(terminal_groups, DONE_STATUSES),
            "exception_groups": count_groups(terminal_groups, {"exception"}),
            "incomplete_groups": count_groups(terminal_groups, {"incomplete"}),
            "pending_groups": count_groups(terminal_groups, OPEN_STATUSES),
            "scan_rows": scan_rows,
            "groups_with_scan": sum(1 for group in terminal_groups if group["photo_count"] > 0),
            "complete_groups": count_complete_groups(terminal_groups),
            "partial_groups": count_partial_groups(terminal_groups),
            "has_scan_info": has_scan_info,
            "can_claim": has_scan_info,
            "claim_block_reason": "" if has_scan_info else "该终端暂无扫码信息，不能领取",
            "progress": calculate_progress(terminal_groups),
            "completeness_rate": calculate_completeness_rate(terminal_groups, scan_only=True),
        }
        tasks.append(task)
    return tasks


def build_summary(
    total_rows: list[dict[str, Any]],
    stage_rows: list[dict[str, Any]],
    scan_rows: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    stage_unmatched: list[dict[str, Any]],
    scan_unmatched: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "total_catalog_rows": len(total_rows),
        "stage_catalog_rows": len(stage_rows),
        "scan_rows": len(scan_rows),
        "groups": len(groups),
        "matched_groups": sum(1 for item in groups if item["status"] != "unmatched"),
        "incomplete_groups": sum(1 for item in groups if item["status"] == "incomplete"),
        "approved_groups": sum(1 for item in groups if item["status"] == "approved"),
        "exception_groups": sum(1 for item in groups if item["status"] == "exception"),
        "reviewed_groups": sum(1 for item in groups if item["status"] in DONE_STATUSES),
        "unreviewed_groups": sum(1 for item in groups if item["status"] in OPEN_STATUSES),
        "stage_unmatched": len(stage_unmatched),
        "scan_unmatched": len(scan_unmatched),
        "photo_rows_linked": sum(item["photo_count"] for item in groups),
        "downloaded_photos": sum(
            1 for group in groups for photo in group.get("photos", []) if photo.get("download_status") == "downloaded"
        ),
        "unclassified_photos": sum(
            1 for group in groups for photo in group.get("photos", []) if photo.get("category") == "unclassified"
        ),
        "review_progress": calculate_progress(groups),
    }

def refresh_summary() -> None:
    state = get_state()
    summary = build_summary([], [], [], state["groups"], state["stage_unmatched"], state["scan_unmatched"])
    summary["total_catalog_rows"] = state["summary"].get("total_catalog_rows", 0)
    summary["stage_catalog_rows"] = state["summary"].get("stage_catalog_rows", 0)
    summary["scan_rows"] = state["summary"].get("scan_rows", 0)
    state["summary"] = summary
    if state["projects"]:
        state["projects"][0]["summary"] = summary
    for task in state["tasks"]:
        task_groups = [group for group in state["groups"] if group["task_id"] == task["id"]]
        task["total_groups"] = len(task_groups)
        task["completed_groups"] = count_groups(task_groups, DONE_STATUSES)
        task["exception_groups"] = count_groups(task_groups, {"exception"})
        task["incomplete_groups"] = count_groups(task_groups, {"incomplete"})
        task["pending_groups"] = count_groups(task_groups, OPEN_STATUSES)
        task["scan_rows"] = sum(group["photo_count"] for group in task_groups)
        task["groups_with_scan"] = sum(1 for group in task_groups if group["photo_count"] > 0)
        task["complete_groups"] = count_complete_groups(task_groups)
        task["partial_groups"] = count_partial_groups(task_groups)
        task["has_scan_info"] = task["scan_rows"] > 0
        task["can_claim"] = task["has_scan_info"]
        task["claim_block_reason"] = "" if task["can_claim"] else "该终端暂无扫码信息，不能领取"
        task["progress"] = calculate_progress(task_groups)
        task["completeness_rate"] = calculate_completeness_rate(task_groups, scan_only=True)


def calculate_progress(groups: list[dict[str, Any]]) -> float:
    if not groups:
        return 0.0
    reviewed = sum(1 for item in groups if item["status"] in DONE_STATUSES)
    return round(reviewed / len(groups), 4)


def count_groups(groups: list[dict[str, Any]], statuses: set[str]) -> int:
    return sum(1 for item in groups if item["status"] in statuses)


def count_complete_groups(groups: list[dict[str, Any]]) -> int:
    return sum(1 for item in groups if item["photo_count"] >= 4)


def count_partial_groups(groups: list[dict[str, Any]]) -> int:
    return sum(1 for item in groups if 0 < item["photo_count"] < 4)


def calculate_completeness_rate(groups: list[dict[str, Any]], scan_only: bool = False) -> float:
    scoped_groups = [item for item in groups if item["photo_count"] > 0] if scan_only else groups
    if not scoped_groups:
        return 0.0
    collected_slots = sum(min(item["photo_count"], 4) for item in scoped_groups)
    required_slots = len(scoped_groups) * 4
    return round(collected_slots / required_slots, 4)


def read_catalog_rows(path: Path, source: str) -> list[dict[str, Any]]:
    assert_file_exists(path)
    load_workbook = get_workbook_loader()
    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.worksheets[0]
    rows = []
    blank_run = 0
    for row_number, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        terminal, meter_no, address = normalize_cell(row[0]), normalize_cell(row[1]), normalize_cell(row[2])
        if not terminal and not meter_no and not address:
            blank_run += 1
            if blank_run >= 20:
                break
            continue
        blank_run = 0
        if not meter_no:
            continue
        rows.append(
            {
                "source": source,
                "row_number": row_number,
                "terminal": terminal,
                "meter_no": meter_no,
                "address": address,
                "meter_match_key": build_total_catalog_match_key(meter_no),
            }
        )
    return rows


def read_scan_rows(path: Path) -> list[dict[str, Any]]:
    assert_file_exists(path)
    load_workbook = get_workbook_loader()
    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.worksheets[0]
    headers = [normalize_cell(value) for value in next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))]
    rows = []
    blank_run = 0
    for row_number, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        values = {headers[index]: normalize_cell(value) for index, value in enumerate(row) if index < len(headers)}
        barcode = values.get("\u626b\u7801\u5185\u5bb9", "")
        if not barcode:
            blank_run += 1
            if blank_run >= 20:
                break
            continue
        blank_run = 0
        try:
            meter_match_key = build_long_scan_match_key(barcode)
        except ValueError:
            meter_match_key = ""
        rows.append(
            {
                "row_number": row_number,
                "barcode": barcode,
                "meter_match_key": meter_match_key,
                "source_file": values.get("\u6765\u81ea\u6587\u4ef6", ""),
                "collector": values.get("\u91c7\u96c6\u5668", ""),
                "asset_no": values.get("\u6a21\u5757\u8d44\u4ea7\u7f16\u53f7", ""),
                "asset_type": values.get("\u8d44\u4ea7\u7c7b\u578b", ""),
                "creator": values.get("\u521b\u5efa\u8005", ""),
                "created_at": values.get("\u521b\u5efa\u65f6\u95f4", ""),
                "has_image": bool(values.get("\u56fe\u7247 (\u7535\u8111\u67e5\u770b)", "")),
            }
        )
    return rows


def list_groups(limit: int = 100, offset: int = 0, status: str | None = None) -> dict[str, Any]:
    state = get_state()
    groups = state["groups"]
    if status:
        groups = [item for item in groups if item["status"] == status]
    return {"total": len(groups), "items": groups[offset : offset + limit]}


def list_task_groups(
    task_id: int,
    limit: int = 100,
    offset: int = 0,
    status: str | None = None,
    scan_only: bool = False,
) -> dict[str, Any]:
    find_task(task_id)
    state = get_state()
    groups = [item for item in state["groups"] if item["task_id"] == task_id]
    if scan_only:
        groups = [item for item in groups if item["photo_count"] > 0]
    if status:
        groups = [item for item in groups if item["status"] == status]
    return {"total": len(groups), "items": groups[offset : offset + limit]}


def get_group(group_id: str) -> dict[str, Any] | None:
    state = get_state()
    return next((item for item in state["groups"] if item["id"] == group_id), None)


def list_tasks() -> list[dict[str, Any]]:
    return sorted(
        get_state()["tasks"],
        key=lambda task: (
            not task.get("can_claim", False),
            str(task.get("terminal", "")),
            task["id"],
        ),
    )


def get_task_progress(task_id: int) -> dict[str, Any]:
    task = find_task(task_id)
    groups = [item for item in get_state()["groups"] if item["task_id"] == task_id]
    by_status = {status: 0 for status in sorted(REVIEWABLE_STATUSES)}
    for group in groups:
        by_status[group["status"]] = by_status.get(group["status"], 0) + 1
    return {
        "task_id": task_id,
        "status": task["status"],
        "claimed_by": task.get("claimed_by"),
        "total_groups": len(groups),
        "reviewed_groups": sum(by_status.get(status, 0) for status in DONE_STATUSES),
        "pending_groups": sum(by_status.get(status, 0) for status in OPEN_STATUSES),
        "approved_groups": by_status.get("approved", 0),
        "exception_groups": by_status.get("exception", 0),
        "incomplete_groups": by_status.get("incomplete", 0),
        "complete_groups": count_complete_groups(groups),
        "partial_groups": count_partial_groups(groups),
        "by_status": by_status,
        "progress": calculate_progress(groups),
        "completeness_rate": calculate_completeness_rate(groups, scan_only=True),
    }


def claim_task(task_id: int, reviewer: str) -> dict[str, Any]:
    task = find_task(task_id)
    if not task.get("can_claim", False):
        raise ValueError(task.get("claim_block_reason") or "Task has no scan information")
    if task["status"] not in {"published", "released", "in_review"}:
        raise ValueError(f"Task cannot be claimed from status {task['status']}")
    if task.get("claimed_by") and task["claimed_by"] != reviewer:
        raise ValueError("Task is already claimed by another reviewer")
    task["status"] = "in_review"
    task["claimed_by"] = reviewer
    task["claimed_at"] = now_iso()
    task["released_at"] = None
    return task


def release_task(task_id: int, reviewer: str) -> dict[str, Any]:
    task = find_task(task_id)
    if task.get("claimed_by") not in {None, reviewer}:
        raise ValueError("Only the current reviewer can release this task")
    task["status"] = "released"
    task["claimed_by"] = None
    task["released_at"] = now_iso()
    return task


def review_group(
    group_id: str,
    status: str,
    reviewer: str,
    note: str = "",
    exception_note: str = "",
) -> dict[str, Any]:
    if status not in REVIEWABLE_STATUSES:
        raise ValueError(f"Unsupported group status: {status}")
    group = get_group(group_id)
    if group is None:
        raise KeyError(group_id)
    task = find_task(group["task_id"])
    claimed_by = task.get("claimed_by")
    if claimed_by and claimed_by != reviewer:
        raise ValueError("Only the current reviewer can review this task")
    if status == "exception" and not (note or exception_note):
        raise ValueError("Exception review requires a note")
    previous = group["status"]
    group["status"] = status
    group["reviewer"] = reviewer
    group["review_note"] = note
    group["exception_note"] = exception_note if status == "exception" else ""
    group["reviewed_at"] = now_iso() if status in DONE_STATUSES else None
    _state["review_events"].append(
        {
            "group_id": group_id,
            "task_id": group["task_id"],
            "previous_status": previous,
            "next_status": status,
            "reviewer": reviewer,
            "note": note,
            "exception_note": group["exception_note"],
            "created_at": now_iso(),
        }
    )
    refresh_summary()
    return group


def save_exception_note(group_id: str, reviewer: str, note: str) -> dict[str, Any]:
    return review_group(group_id, status="exception", reviewer=reviewer, exception_note=note)


def classify_photo(group_id: str, photo_id: str, category: str, reviewer: str) -> dict[str, Any]:
    if category not in PHOTO_CATEGORIES:
        raise ValueError(f"Unsupported photo category: {category}")
    group = get_group(group_id)
    if group is None:
        raise KeyError(group_id)
    photo = next((item for item in group["photos"] if item["id"] == photo_id), None)
    if photo is None:
        raise KeyError(photo_id)
    if photo.get("download_status") != "downloaded":
        raise ValueError("Photo must be downloaded before classification")

    previous = photo["category"]
    photo["category"] = category
    photo["category_label"] = PHOTO_CATEGORIES[category]
    photo["classified_by"] = reviewer
    photo["classified_at"] = now_iso()
    photo["archive_status"] = "archived"
    photo["archive_filename"] = build_archive_filename(photo["category_label"], photo.get("image_url", ""))
    photo["archived_at"] = now_iso()
    _state["photo_events"].append(
        {
            "group_id": group_id,
            "photo_id": photo_id,
            "previous_category": previous,
            "next_category": category,
            "reviewer": reviewer,
            "created_at": now_iso(),
        }
    )
    refresh_summary()
    return photo


def find_task(task_id: int) -> dict[str, Any]:
    state = get_state()
    task = next((item for item in state["tasks"] if item["id"] == task_id), None)
    if task is None:
        raise KeyError(task_id)
    return task


def normalize_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def assert_file_exists(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Test workbook not found: {path}")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def build_archive_filename(category_label: str, image_url: str) -> str:
    suffix = Path(image_url.split("?", 1)[0]).suffix.lower() if image_url else ".jpg"
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        suffix = ".jpg"
    return f"{sanitize_filename(category_label)}{suffix}"


def sanitize_filename(value: str) -> str:
    return "".join("_" if char in '<>:"/\\|?*' else char for char in value).strip() or "photo"


def get_workbook_loader():
    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "openpyxl is required to read local simulation workbooks. "
            "Install v2-api requirements before bootstrapping from Excel files."
        ) from exc
    return load_workbook
