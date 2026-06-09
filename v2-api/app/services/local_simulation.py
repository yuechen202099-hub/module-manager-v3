from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from app.services.matching import build_long_scan_match_key, build_total_catalog_match_key


DEFAULT_TOTAL_CATALOG = Path("C:/Users/Administrator/Desktop/\u603b\u4f53\u6570\u636e.xlsx")
DEFAULT_STAGE_CATALOG = Path("C:/Users/Administrator/Desktop/\u7b2c\u4e00\u6279\u6570\u636e.xlsx")
DEFAULT_SCAN_FILE = Path("C:/Users/Administrator/Desktop/\u6279\u91cf\u626b\u7801_20260608125555.xlsx")


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
}


def get_state() -> dict[str, Any]:
    if not _state["loaded"]:
        bootstrap_local_simulation()
    return _state


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

    groups = []
    stage_unmatched = []
    for index, stage in enumerate(stage_rows, start=1):
        total_matches = total_by_key.get(stage["meter_match_key"], [])
        total = total_matches[0] if total_matches else None
        photos = scans_by_key.get(stage["meter_match_key"], [])
        status = "pending"
        if not total:
            status = "unmatched"
            stage_unmatched.append(stage)
        elif len(photos) < 4:
            status = "incomplete"

        groups.append(
            {
                "id": f"g-{index:05d}",
                "task_id": "t-001",
                "meter_match_key": stage["meter_match_key"],
                "meter_no": total["meter_no"] if total else stage["meter_no"],
                "terminal": total["terminal"] if total else stage["terminal"],
                "address": total["address"] if total else "",
                "stage_meter_no": stage["meter_no"],
                "stage_terminal": stage["terminal"],
                "status": status,
                "photo_count": len(photos),
                "photos": photos[:8],
            }
        )

    summary = {
        "total_catalog_rows": len(total_rows),
        "stage_catalog_rows": len(stage_rows),
        "scan_rows": len(scan_rows),
        "groups": len(groups),
        "matched_groups": sum(1 for item in groups if item["status"] != "unmatched"),
        "incomplete_groups": sum(1 for item in groups if item["status"] == "incomplete"),
        "stage_unmatched": len(stage_unmatched),
        "scan_unmatched": len(scan_unmatched),
        "photo_rows_linked": sum(item["photo_count"] for item in groups),
    }

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
                    "name": "V2.01 Local Simulation",
                    "status": "active",
                    "summary": summary,
                }
            ],
            "tasks": [
                {
                    "id": 1,
                    "project_id": 1,
                    "name": "First batch local review",
                    "status": "published",
                    "total_groups": len(groups),
                    "completed_groups": 0,
                    "incomplete_groups": summary["incomplete_groups"],
                }
            ],
            "groups": groups,
            "scan_unmatched": scan_unmatched,
            "stage_unmatched": stage_unmatched,
        }
    )
    return _state


def read_catalog_rows(path: Path, source: str) -> list[dict[str, Any]]:
    assert_file_exists(path)
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


def get_group(group_id: str) -> dict[str, Any] | None:
    state = get_state()
    return next((item for item in state["groups"] if item["id"] == group_id), None)


def normalize_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def assert_file_exists(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Test workbook not found: {path}")
