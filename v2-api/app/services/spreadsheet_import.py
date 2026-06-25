from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from app.services.matching import build_long_scan_match_key, build_total_catalog_match_key


PHOTO_URL_SEPARATORS = re.compile(r"[\r\n,;\uff0c\uff1b]+")
URL_RE = re.compile(r"^https?://", re.IGNORECASE)

HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "terminal": ("terminal", "terminal_no", "\u7ec8\u7aef", "\u7ec8\u7aef\u53f7", "\u7ec8\u7aef\u7f16\u53f7"),
    "collector": ("collector", "collector_no", "\u91c7\u96c6\u5668", "\u91c7\u96c6\u5668\u53f7", "\u91c7\u96c6\u5668\u7f16\u53f7"),
    "meter_no": ("meter_no", "meter", "\u8868\u53f7", "\u7535\u8868\u53f7", "\u8868\u8ba1\u53f7", "\u77ed\u8868\u53f7"),
    "module_asset_no": (
        "module_asset_no",
        "module",
        "\u6a21\u5757",
        "\u6a21\u5757\u53f7",
        "\u6a21\u5757\u7f16\u53f7",
        "\u6a21\u5757\u8d44\u4ea7\u7f16\u53f7",
    ),
    "address": ("address", "installation_address", "\u5730\u5740", "\u5b89\u88c5\u5730\u5740", "\u7528\u7535\u5730\u5740"),
    "photo_urls": (
        "photo_urls",
        "photo_url",
        "image_urls",
        "image_url",
        "\u7167\u7247URL",
        "\u56fe\u7247URL",
        "\u7167\u7247\u94fe\u63a5",
        "\u56fe\u7247\u94fe\u63a5",
        "URL",
        "url",
    ),
    "category_name": (
        "category_name",
        "category",
        "classification",
        "\u5206\u7c7b\u547d\u540d",
        "\u5206\u7c7b",
        "\u7167\u7247\u5206\u7c7b",
        "\u5f52\u6863\u547d\u540d",
    ),
    "barcode": ("barcode", "scan_code", "\u626b\u7801\u5185\u5bb9", "\u6761\u5f62\u7801", "\u957f\u6761\u7801", "\u626b\u63cf\u6761\u7801"),
    "meter_match_key": ("meter_match_key", "match_key", "\u5339\u914d\u952e", "\u8868\u53f7\u5339\u914d\u952e"),
}

PHOTO_URL_PREFIXES = (
    "photo_url",
    "image_url",
    "\u7167\u7247url",
    "\u56fe\u7247url",
    "\u7167\u7247\u94fe\u63a5",
    "\u56fe\u7247\u94fe\u63a5",
    "url",
)


@dataclass(frozen=True)
class SpreadsheetImportError:
    row_number: int
    field: str
    message: str


@dataclass(frozen=True)
class SpreadsheetPhotoRef:
    url: str
    category_name: str = ""


@dataclass(frozen=True)
class SpreadsheetImportRecord:
    row_number: int
    terminal: str = ""
    collector: str = ""
    meter_no: str = ""
    module_asset_no: str = ""
    address: str = ""
    category_name: str = ""
    barcode: str = ""
    meter_match_key: str = ""
    photos: tuple[SpreadsheetPhotoRef, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SpreadsheetImportResult:
    records: tuple[SpreadsheetImportRecord, ...]
    errors: tuple[SpreadsheetImportError, ...]

    @property
    def accepted_rows(self) -> int:
        return len(self.records)

    @property
    def rejected_rows(self) -> int:
        return len({error.row_number for error in self.errors})

    @property
    def photo_count(self) -> int:
        return sum(len(record.photos) for record in self.records)


def parse_csv_text(text: str) -> list[dict[str, str]]:
    return [dict(row) for row in csv.DictReader(io.StringIO(text))]


def parse_spreadsheet_rows(rows: Iterable[dict[str, Any]]) -> SpreadsheetImportResult:
    records: list[SpreadsheetImportRecord] = []
    errors: list[SpreadsheetImportError] = []
    for row_number, row in enumerate(rows, start=2):
        record, row_errors = normalize_spreadsheet_row(row, row_number)
        if row_errors:
            errors.extend(row_errors)
            continue
        records.append(record)
    return SpreadsheetImportResult(records=tuple(records), errors=tuple(errors))


def normalize_spreadsheet_row(
    row: dict[str, Any],
    row_number: int = 2,
) -> tuple[SpreadsheetImportRecord, tuple[SpreadsheetImportError, ...]]:
    normalized = normalize_headers(row)
    terminal = pick_field(normalized, "terminal")
    collector = pick_field(normalized, "collector")
    meter_no = pick_field(normalized, "meter_no")
    module_asset_no = pick_field(normalized, "module_asset_no")
    address = pick_field(normalized, "address")
    category_name = pick_field(normalized, "category_name")
    barcode = pick_field(normalized, "barcode")
    meter_match_key = pick_field(normalized, "meter_match_key")

    row_errors: list[SpreadsheetImportError] = []
    warnings: list[str] = []
    if not meter_match_key:
        try:
            meter_match_key = infer_meter_match_key(meter_no=meter_no, barcode=barcode)
        except ValueError as exc:
            row_errors.append(SpreadsheetImportError(row_number, "meter_match_key", str(exc)))

    photo_urls, rejected_photo_values = collect_photo_urls(normalized)
    if rejected_photo_values:
        warnings.append(f"Skipped non-URL photo values: {', '.join(rejected_photo_values)}")

    return (
        SpreadsheetImportRecord(
            row_number=row_number,
            terminal=terminal,
            collector=collector,
            meter_no=meter_no,
            module_asset_no=module_asset_no,
            address=address,
            category_name=category_name,
            barcode=barcode,
            meter_match_key=meter_match_key,
            photos=tuple(SpreadsheetPhotoRef(url=url, category_name=category_name) for url in photo_urls),
            raw=dict(row),
            warnings=tuple(warnings),
        ),
        tuple(row_errors),
    )


def infer_meter_match_key(*, meter_no: str = "", barcode: str = "") -> str:
    if barcode:
        return build_long_scan_match_key(barcode)
    if meter_no:
        return build_total_catalog_match_key(meter_no)
    raise ValueError("Row must include meter_match_key, barcode, or meter_no.")


def normalize_headers(row: dict[str, Any]) -> dict[str, Any]:
    return {normalize_header(key): value for key, value in row.items()}


def normalize_header(value: Any) -> str:
    return "".join(str(value or "").strip().lower().split())


def pick_field(row: dict[str, Any], canonical_name: str) -> str:
    for alias in HEADER_ALIASES[canonical_name]:
        value = row.get(normalize_header(alias))
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def collect_photo_urls(row: dict[str, Any]) -> tuple[list[str], list[str]]:
    values: list[Any] = []
    for alias in HEADER_ALIASES["photo_urls"]:
        key = normalize_header(alias)
        if key in row:
            values.append(row[key])
    for key, value in row.items():
        if is_numbered_photo_header(key) and value is not None:
            values.append(value)

    urls: list[str] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for value in values:
        for part in split_photo_url_cell(value):
            if not URL_RE.match(part):
                rejected.append(part)
                continue
            if part not in seen:
                urls.append(part)
                seen.add(part)
    return urls, rejected


def is_numbered_photo_header(normalized_key: str) -> bool:
    return any(normalized_key.startswith(prefix) for prefix in PHOTO_URL_PREFIXES) and any(char.isdigit() for char in normalized_key)


def split_photo_url_cell(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        parts: list[str] = []
        for item in value:
            parts.extend(split_photo_url_cell(item))
        return parts
    return [part.strip() for part in PHOTO_URL_SEPARATORS.split(str(value)) if part.strip()]
