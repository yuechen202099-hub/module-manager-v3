from __future__ import annotations

from typing import Any


def build_delivery_summary(*, progress: int, risk_total: int) -> dict[str, Any]:
    delivery_ready = progress >= 100 and risk_total == 0
    return {
        "status": "ready" if delivery_ready else "preparing",
        "total_items": 4,
        "completed_items": 4 if delivery_ready else max(0, min(3, progress // 30)),
        "latest_record": "",
    }
