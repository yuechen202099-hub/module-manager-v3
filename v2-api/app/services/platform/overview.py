from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _number(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _percent(value: float) -> int:
    return max(0, min(100, round(value * 100)))


def _stage(progress: int, risk_total: int, unconstructed: int, reviewing: int) -> str:
    if progress >= 100 and risk_total == 0:
        return "待验收"
    if reviewing > 0:
        return "审阅中"
    if unconstructed > 0:
        return "施工中"
    if progress > 0:
        return "交付准备"
    return "准备中"


def build_replacement_project_overview(
    *,
    summary: dict[str, Any],
    task_status: dict[str, Any],
) -> dict[str, Any]:
    groups = _number(summary.get("groups"))
    reviewed_groups = _number(summary.get("reviewed_groups"))
    exception_groups = _number(summary.get("exception_groups"))
    unconstructed_groups = _number(summary.get("unconstructed_groups"))
    photo_rows_linked = _number(summary.get("photo_rows_linked"))
    task_total = _number(task_status.get("total"))
    uploaded_tasks = _number(task_status.get("uploaded"))
    reviewing_tasks = _number(task_status.get("reviewing"))
    archived_tasks = _number(task_status.get("archived"))
    upload_rate = float(task_status.get("avg_upload_rate") or 0)
    review_rate = float(task_status.get("avg_review_rate") or 0)
    progress = _percent(reviewed_groups / groups) if groups else _percent(review_rate)
    risk_total = exception_groups + unconstructed_groups
    stage = _stage(progress, risk_total, unconstructed_groups, reviewing_tasks)
    delivery_ready = progress >= 100 and risk_total == 0

    return {
        "id": "replacement-project",
        "name": "更换模块项目",
        "status": "active",
        "stage": stage,
        "system_progress": progress,
        "management_progress": progress,
        "management_locked": False,
        "total_groups": groups,
        "completed_groups": reviewed_groups,
        "exception_groups": exception_groups,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "tasks": {
            "total": task_total,
            "uploaded": uploaded_tasks,
            "reviewing": reviewing_tasks,
            "archived": archived_tasks,
            "upload_rate": _percent(upload_rate),
            "review_rate": _percent(review_rate),
        },
        "delivery": {
            "status": "ready" if delivery_ready else "preparing",
            "total_items": 4,
            "completed_items": 4 if delivery_ready else max(0, min(3, progress // 30)),
            "latest_record": "",
        },
        "field": {
            "photo_rows_linked": photo_rows_linked,
            "unconstructed_groups": unconstructed_groups,
            "exception_count": exception_groups,
        },
        "review": {
            "reviewed_groups": reviewed_groups,
            "review_rate": progress,
            "pending_groups": max(groups - reviewed_groups, 0),
        },
        "risks": {
            "total": risk_total,
            "field_exceptions": exception_groups,
            "unconstructed_groups": unconstructed_groups,
            "delivery_blockers": 0 if delivery_ready else risk_total,
        },
    }
