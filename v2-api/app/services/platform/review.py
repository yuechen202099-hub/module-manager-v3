from __future__ import annotations

from typing import Any


def build_review_summary(*, groups: int, reviewed_groups: int, progress: int) -> dict[str, Any]:
    return {
        "reviewed_groups": reviewed_groups,
        "review_rate": progress,
        "pending_groups": max(groups - reviewed_groups, 0),
    }
