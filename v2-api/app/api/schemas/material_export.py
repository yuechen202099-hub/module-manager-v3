from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskIdsRequest(StrictRequest):
    task_ids: list[str] = Field(min_length=1, max_length=500)


class TerminalSettingRequest(StrictRequest):
    requested_collector_count: int = Field(ge=0, le=999)


class ReserveJobRequest(TaskIdsRequest):
    preflight_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")


class LeaseRequest(StrictRequest):
    owner_token: str = Field(min_length=16, max_length=128)


class FileAcknowledgeRequest(StrictRequest):
    byte_size: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")


class ReleaseRequest(StrictRequest):
    terminal_ids: list[str] = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=500)
