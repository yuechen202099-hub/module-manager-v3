from __future__ import annotations

from typing import Any


def build_risk_summary(
    *,
    exception_groups: int,
    unconstructed_groups: int,
    delivery_ready: bool,
) -> dict[str, Any]:
    risk_total = exception_groups + unconstructed_groups
    return {
        "total": risk_total,
        "field_exceptions": exception_groups,
        "unconstructed_groups": unconstructed_groups,
        "delivery_blockers": 0 if delivery_ready else risk_total,
    }
