from __future__ import annotations

from typing import Any

from app.services.platform.utils import percent


def _stage(progress: int, risk_total: int, unconstructed_groups: int, reviewing_tasks: int) -> str:
    if progress >= 100 and risk_total == 0:
        return "待验收"
    if reviewing_tasks > 0:
        return "审阅中"
    if unconstructed_groups > 0:
        return "施工中"
    if progress > 0:
        return "交付准备"
    return "准备中"


def build_progress_summary(
    *,
    groups: int,
    reviewed_groups: int,
    risk_total: int,
    unconstructed_groups: int,
    reviewing_tasks: int,
    fallback_review_rate: float = 0,
) -> dict[str, Any]:
    progress = percent(reviewed_groups / groups) if groups else percent(fallback_review_rate)
    return {
        "stage": _stage(progress, risk_total, unconstructed_groups, reviewing_tasks),
        "system_progress": progress,
        "management_progress": progress,
        "management_locked": False,
    }
