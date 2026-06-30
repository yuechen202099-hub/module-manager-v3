from __future__ import annotations

from io import BytesIO
from typing import Any, Literal

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from app.services.platform.catalog import get_project_overview

TemplateType = Literal["initial_work_orders", "external_completed"]

SUPPORTED_TEMPLATE_TYPES = {"initial_work_orders", "external_completed"}

PLATFORM_FILL_RULES = {
    "uploaded_at": "平台上传时补齐",
    "completed_at": "缺失时按上传时间补齐",
    "installer": "缺失时按上传人补齐",
    "work_order_id": "缺失时由平台生成",
    "photo_count": "缺失时按0或附件数补齐",
    "online_duration_minutes": "外部无法提供时可留空",
}


def build_project_template_workbook(project_id: str, template_type: str) -> bytes:
    if template_type not in SUPPORTED_TEMPLATE_TYPES:
        raise KeyError(template_type)
    project = get_project_overview(project_id)
    schema = project.get("work_item_schema") or {}
    fields = _fields_for_template(schema, template_type)
    field_rows = _field_rows_for_template(schema, fields, template_type)

    workbook = Workbook()
    template_sheet = workbook.active
    template_sheet.title = "template"
    fields_sheet = workbook.create_sheet("fields")

    headers = [field["label"] for field in fields]
    keys = [field["key"] for field in fields]
    template_sheet.append(headers)
    template_sheet.append([_example_value(field, index) for index, field in enumerate(fields, start=1)])
    template_sheet.append([f"字段编码: {key}" for key in keys])

    fields_sheet.append(["字段编码", "字段名称", "来源", "采集方式", "数据格式", "是否必填", "平台补齐规则"])
    for field in field_rows:
        fields_sheet.append(
            [
                field["key"],
                field["label"],
                field.get("source", ""),
                field.get("capture_method", ""),
                field.get("data_type", ""),
                "是" if field.get("required") else "否",
                _platform_fill_rule(field, template_type),
            ]
        )

    for sheet in workbook.worksheets:
        _style_sheet(sheet)

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def project_template_filename(project_id: str, template_type: str) -> str:
    return f"{project_id}-{template_type}.xlsx"


def _fields_for_template(schema: dict[str, Any], template_type: str) -> list[dict[str, Any]]:
    primary = _clean_field(schema.get("primary_field"))
    aggregate = _clean_field(schema.get("aggregate_field"))
    custom_fields = [_clean_field(field) for field in schema.get("custom_fields", []) if isinstance(field, dict)]
    platform_fields = [_clean_field(field) for field in schema.get("platform_required_fields", []) if isinstance(field, dict)]

    import_fields = [field for field in custom_fields if field.get("source") == "import"]
    field_collection_fields = [field for field in custom_fields if field.get("source") == "field_collection"]
    platform_by_key = {field["key"]: field for field in platform_fields}

    if template_type == "initial_work_orders":
        return _dedupe_fields([primary, aggregate, *import_fields])
    return _dedupe_fields(
        [
            primary,
            aggregate,
            *import_fields,
            *field_collection_fields,
            platform_by_key.get("installer"),
            platform_by_key.get("completed_at"),
            {"key": "external_evidence", "label": "外部完成证明", "source": "import", "capture_method": "manual", "data_type": "text", "required": False},
        ]
    )


def _field_rows_for_template(schema: dict[str, Any], template_fields: list[dict[str, Any]], template_type: str) -> list[dict[str, Any]]:
    primary = _clean_field(schema.get("primary_field"))
    aggregate = _clean_field(schema.get("aggregate_field"))
    if template_type != "external_completed":
        return template_fields
    platform_fields = [_clean_field(field) for field in schema.get("platform_required_fields", []) if isinstance(field, dict)]
    platform_by_key = {field["key"]: field for field in platform_fields}
    return _dedupe_fields(
        [
            *template_fields,
            platform_by_key.get("work_order_id"),
            platform_by_key.get("uploaded_at"),
            platform_by_key.get("photo_count"),
            platform_by_key.get("online_duration_minutes"),
        ]
    )


def _clean_field(raw: Any) -> dict[str, Any]:
    field = raw if isinstance(raw, dict) else {}
    key = str(field.get("key") or "").strip()
    label = str(field.get("label") or key).strip() or key
    return {
        "key": key,
        "label": label,
        "source": str(field.get("source") or "").strip(),
        "capture_method": str(field.get("capture_method") or "").strip(),
        "data_type": str(field.get("data_type") or "").strip(),
        "required": bool(field.get("required", False)),
    }


def _dedupe_fields(fields: list[dict[str, Any] | None]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for field in fields:
        if not field:
            continue
        key = str(field.get("key") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(field)
    return result


def _platform_fill_rule(field: dict[str, Any], template_type: str) -> str:
    if template_type != "external_completed":
        return ""
    return PLATFORM_FILL_RULES.get(str(field.get("key") or ""), "")


def _example_value(field: dict[str, Any], index: int) -> str:
    key = str(field.get("key") or "")
    data_type = str(field.get("data_type") or "")
    if key in {"terminal_no", "terminal"}:
        return "TT-001"
    if key in {"station_area", "area", "area_no"}:
        return "台区-001"
    if key in {"meter_no", "work_item"}:
        return "370100000001"
    if data_type == "datetime":
        return "2026-06-30 09:30:00"
    if data_type in {"number", "duration"}:
        return "15"
    return f"示例值{index}"


def _style_sheet(sheet) -> None:
    header_fill = PatternFill("solid", fgColor="E8F1FF")
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
    for column_cells in sheet.columns:
        width = max(len(str(cell.value or "")) for cell in column_cells) + 2
        sheet.column_dimensions[get_column_letter(column_cells[0].column)].width = min(max(width, 12), 34)
