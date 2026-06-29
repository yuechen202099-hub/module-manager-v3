from __future__ import annotations

from typing import Any


def number(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def percent(value: float) -> int:
    return max(0, min(100, round(value * 100)))
