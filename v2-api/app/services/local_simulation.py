from __future__ import annotations

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
TASK_ID = 1


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
                "task_id": TASK_ID,
                "meter_match_key": stage["meter_match_key"],
                "meter_no": total["meter_no"] if total else stage["meter_no"],
                "terminal": total["terminal"] if total else stage["terminal"],
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

    task = {
        "id": 1,
        "project_id": 1,
        "name": "First batch local review",
        "status": "published",
        "claimed_by": None,
        "claimed_at": None,
        "released_at": None,
        "total_groups": len(groups),
        "completed_groups": summary["reviewed_groups"],
        "exception_groups": summary["exception_groups"],
        "incomplete_groups": summary["incomplete_groups"],
        "pending_groups": summary["unreviewed_groups"],
        "progress": summary["review_progress"],
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
                    "name": "V2.1 Local Simulation",
                    "status": "active",
                    "summary": summary,
                }
            ],
            "tasks": [task],
            "groups": groups,
            "scan_unmatched": scan_unmatched,
            "stage_unmatched": stage_unmatched,
            "review_events": [],
        }
    )
    return _state


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
    if state["tasks"]:
        task = state["tasks"][0]
        task["total_groups"] = summary["groups"]
        task["completed_groups"] = summary["reviewed_groups"]
        task["exception_groups"] = summary["exception_groups"]
        task["incomplete_groups"] = summary["incomplete_groups"]
        task["pending_groups"] = summary["unreviewed_groups"]
        task["progress"] = summary["review_progress"]


def calculate_progress(groups: list[dict[str, Any]]) -> float:
    if not groups:
        return 0.0
    reviewed = sum(1 for item in groups if item["status"] in DONE_STATUSES)
    return round(reviewed / len(groups), 4)


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
) -> dict[str, Any]:
    find_task(task_id)
    state = get_state()
    groups = [item for item in state["groups"] if item["task_id"] == task_id]
    if status:
        groups = [item for item in groups if item["status"] == status]
    return {"total": len(groups), "items": groups[offset : offset + limit]}


def get_group(group_id: str) -> dict[str, Any] | None:
    state = get_state()
    return next((item for item in state["groups"] if item["id"] == group_id), None)


def list_tasks() -> list[dict[str, Any]]:
    return get_state()["tasks"]


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
        "by_status": by_status,
        "progress": calculate_progress(groups),
    }


def claim_task(task_id: int, reviewer: str) -> dict[str, Any]:
    task = find_task(task_id)
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


def get_workbook_loader():
    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "openpyxl is required to read local simulation workbooks. "
            "Install v2-api requirements before bootstrapping from Excel files."
        ) from exc
    return load_workbook
