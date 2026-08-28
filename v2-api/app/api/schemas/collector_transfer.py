from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ManualCollectorDemandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: int = Field(gt=0, strict=True)


class ManualCollectorDemandAssignmentResponse(BaseModel):
    assignment_id: str
    requirement_id: str
    original_collector_no: Literal["人工需求"]
    physical_collector_id: str
    final_collector_no: str
    mode: Literal["random"]


class ManualCollectorDemandResultResponse(BaseModel):
    run_id: str
    terminal_id: str
    required: int
    assigned: int
    assignments: list[ManualCollectorDemandAssignmentResponse]


class ManualCollectorDemandResponse(BaseModel):
    data: ManualCollectorDemandResultResponse
    error: None = None
    request_id: str
