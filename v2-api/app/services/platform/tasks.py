from __future__ import annotations

from typing import Any

from app.services.platform.utils import number, percent


def build_task_summary(task_status: dict[str, Any]) -> dict[str, Any]:
    return {
        "total": number(task_status.get("total")),
        "uploaded": number(task_status.get("uploaded")),
        "reviewing": number(task_status.get("reviewing")),
        "archived": number(task_status.get("archived")),
        "upload_rate": percent(float(task_status.get("avg_upload_rate") or 0)),
        "review_rate": percent(float(task_status.get("avg_review_rate") or 0)),
    }
