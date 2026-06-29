from __future__ import annotations

from typing import Any


def build_field_summary(
    *,
    photo_rows_linked: int,
    unconstructed_groups: int,
    exception_groups: int,
) -> dict[str, Any]:
    return {
        "photo_rows_linked": photo_rows_linked,
        "unconstructed_groups": unconstructed_groups,
        "exception_count": exception_groups,
    }
