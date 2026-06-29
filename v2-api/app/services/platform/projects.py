from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_project_overview(
    *,
    project_id: str,
    name: str,
    status: str,
    progress: dict[str, Any],
    total_groups: int,
    completed_groups: int,
    exception_groups: int,
    tasks: dict[str, Any],
    delivery: dict[str, Any],
    field: dict[str, Any],
    review: dict[str, Any],
    risks: dict[str, Any],
    updated_at: str | None = None,
) -> dict[str, Any]:
    return {
        "id": project_id,
        "name": name,
        "status": status,
        "stage": progress["stage"],
        "system_progress": progress["system_progress"],
        "management_progress": progress["management_progress"],
        "management_locked": progress["management_locked"],
        "total_groups": total_groups,
        "completed_groups": completed_groups,
        "exception_groups": exception_groups,
        "updated_at": updated_at or datetime.now(timezone.utc).isoformat(),
        "tasks": tasks,
        "delivery": delivery,
        "field": field,
        "review": review,
        "risks": risks,
    }
