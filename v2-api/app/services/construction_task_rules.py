from __future__ import annotations

from typing import Any, Mapping


def construction_task_availability(stats: Mapping[str, Any]) -> tuple[bool, bool]:
    total = max(0, int(stats.get("total_groups") or 0))
    uploaded = max(0, int(stats.get("uploaded_count") or 0))
    unreviewed = max(0, int(stats.get("unreviewed_count") or 0))
    return total > 0 and uploaded < total, uploaded > 0 and unreviewed > 0
