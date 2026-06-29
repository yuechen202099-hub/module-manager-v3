from __future__ import annotations

from typing import Any

from app.services.platform.delivery import build_delivery_summary
from app.services.platform.field import build_field_summary
from app.services.platform.progress import build_progress_summary
from app.services.platform.projects import build_project_overview
from app.services.platform.review import build_review_summary
from app.services.platform.risks import build_risk_summary
from app.services.platform.tasks import build_task_summary
from app.services.platform.utils import number


def build_replacement_project_overview(
    *,
    summary: dict[str, Any],
    task_status: dict[str, Any],
) -> dict[str, Any]:
    groups = number(summary.get("groups"))
    reviewed_groups = number(summary.get("reviewed_groups"))
    exception_groups = number(summary.get("exception_groups"))
    unconstructed_groups = number(summary.get("unconstructed_groups"))
    photo_rows_linked = number(summary.get("photo_rows_linked"))

    tasks = build_task_summary(task_status)
    risk_seed_total = exception_groups + unconstructed_groups
    progress = build_progress_summary(
        groups=groups,
        reviewed_groups=reviewed_groups,
        risk_total=risk_seed_total,
        unconstructed_groups=unconstructed_groups,
        reviewing_tasks=tasks["reviewing"],
        fallback_review_rate=float(task_status.get("avg_review_rate") or 0),
    )
    delivery_ready = progress["system_progress"] >= 100 and risk_seed_total == 0
    risks = build_risk_summary(
        exception_groups=exception_groups,
        unconstructed_groups=unconstructed_groups,
        delivery_ready=delivery_ready,
    )
    delivery = build_delivery_summary(progress=progress["system_progress"], risk_total=risks["total"])

    return build_project_overview(
        project_id="replacement-project",
        name="更换模块项目",
        status="active",
        progress=progress,
        total_groups=groups,
        completed_groups=reviewed_groups,
        exception_groups=exception_groups,
        tasks=tasks,
        delivery=delivery,
        field=build_field_summary(
            photo_rows_linked=photo_rows_linked,
            unconstructed_groups=unconstructed_groups,
            exception_groups=exception_groups,
        ),
        review=build_review_summary(
            groups=groups,
            reviewed_groups=reviewed_groups,
            progress=progress["system_progress"],
        ),
        risks=risks,
    )
