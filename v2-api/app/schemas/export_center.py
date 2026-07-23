from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ExportJobCreateRequest(BaseModel):
    job_type: str
    filters: dict[str, Any] = Field(default_factory=dict)
