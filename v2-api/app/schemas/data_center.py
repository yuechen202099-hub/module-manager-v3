from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


SUPPORTED_PAGE_SIZES = {20, 50, 100}


class DataCenterQuery(BaseModel):
    data_type: Literal["all", "group", "unmatched"] = "all"
    construction_status: Literal["all", "unconstructed", "in_progress", "completed"] = "all"
    archive_status: Literal["all", "unarchived", "pending", "archived"] = "all"
    barcode_status: Literal["all", "passed", "manual", "mismatched", "unreadable", "ineligible"] = "all"
    classification_status: Literal["all", "complete", "incomplete"] = "all"
    exception_status: str = ""
    installer: str = ""
    date_from: date | None = None
    date_to: date | None = None
    terminal: str = ""
    query: str = ""
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20)
    sort: Literal["updated_desc", "updated_asc", "terminal_asc"] = "updated_desc"

    @field_validator("page_size")
    @classmethod
    def supported_page_size(cls, value: int) -> int:
        if value not in SUPPORTED_PAGE_SIZES:
            raise ValueError("page_size must be one of 20, 50, 100")
        return value


class DataCenterRow(BaseModel):
    kind: Literal["group", "unmatched"]
    id: str
    terminal: str = ""
    meter_no: str = ""
    meter_match_key: str = ""
    address: str = ""
    collector: str = ""
    module_asset_no: str = ""
    construction_collector: str = ""
    construction_module_asset_no: str = ""
    installer: str = ""
    photo_count: int = 0
    classification_status: str = "incomplete"
    classification_progress: dict[str, Any] = Field(default_factory=dict)
    barcode_status: str = "ineligible"
    barcode_progress: dict[str, Any] = Field(default_factory=dict)
    group_barcode_missing_fields: list[str] = Field(default_factory=list)
    construction_status: str = "unconstructed"
    archive_status: str = "unarchived"
    exception_status: str = ""
    updated_at: datetime | str | None = None


class DataCenterPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[DataCenterRow]


class DataCenterDetail(DataCenterRow):
    photos: list[dict[str, Any]] = Field(default_factory=list)
    audit: list[dict[str, Any]] = Field(default_factory=list)
