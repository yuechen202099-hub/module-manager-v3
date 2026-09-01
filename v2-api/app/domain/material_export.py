from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MaterialExportMeter:
    group_id: str
    task_id: str
    terminal_code: str
    meter_no: str
    module_no: str
    collector_no: str
    installation_address: str
    module_meter_photo_id: str | None
    after_box_photo_id: str | None
    constructed: bool
    open_module_anomalies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MaterialExportIssue:
    code: str
    terminal_code: str
    group_ids: tuple[str, ...]
    meter_nos: tuple[str, ...]
    module_nos: tuple[str, ...]
    message: str


@dataclass(frozen=True, slots=True)
class CollectorDemand:
    source_collector_nos: tuple[str, ...]
    final_count: int
    extra_count: int


def normalize_business_no(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def _logical_constructed_meters(
    meters: Iterable[MaterialExportMeter],
) -> tuple[MaterialExportMeter, ...]:
    by_group: dict[str, MaterialExportMeter] = {}
    for meter in meters:
        if not meter.constructed:
            continue
        key = normalize_business_no(meter.group_id)
        existing = by_group.get(key)
        if existing is None or _meter_sort_key(meter) < _meter_sort_key(existing):
            by_group[key] = meter
    return tuple(sorted(by_group.values(), key=_meter_sort_key))


def _meter_sort_key(meter: MaterialExportMeter) -> tuple[str, ...]:
    return (
        normalize_business_no(meter.terminal_code),
        normalize_business_no(meter.group_id),
        normalize_business_no(meter.meter_no),
        normalize_business_no(meter.module_no),
    )


def _values(rows: Iterable[MaterialExportMeter], field: str) -> tuple[str, ...]:
    values = {
        str(getattr(row, field) or "").strip()
        for row in rows
        if str(getattr(row, field) or "").strip()
    }
    return tuple(sorted(values, key=normalize_business_no))


def project_module_issues(
    meters: Iterable[MaterialExportMeter],
) -> tuple[MaterialExportIssue, ...]:
    constructed = _logical_constructed_meters(meters)
    modules: dict[str, list[MaterialExportMeter]] = defaultdict(list)
    meter_numbers: dict[str, list[MaterialExportMeter]] = defaultdict(list)
    for meter in constructed:
        module_key = normalize_business_no(meter.module_no)
        meter_key = normalize_business_no(meter.meter_no)
        if module_key:
            modules[module_key].append(meter)
        if meter_key:
            meter_numbers[meter_key].append(meter)

    issues: list[MaterialExportIssue] = []
    for module_key in sorted(modules):
        rows = modules[module_key]
        group_ids = {normalize_business_no(row.group_id) for row in rows}
        if len(group_ids) <= 1:
            continue
        terminals = sorted(
            {str(row.terminal_code).strip() for row in rows}, key=normalize_business_no
        )
        module_nos = _values(rows, "module_no")
        meter_nos = _values(rows, "meter_no")
        all_group_ids = _values(rows, "group_id")
        display_module = module_nos[0] if module_nos else module_key
        for terminal in terminals:
            issues.append(
                MaterialExportIssue(
                    code="duplicate_module",
                    terminal_code=terminal,
                    group_ids=all_group_ids,
                    meter_nos=meter_nos,
                    module_nos=module_nos,
                    message=(
                        f"模块号 {display_module} 在多个已施工资料组中重复，"
                        f"涉及终端：{'、'.join(terminals)}；表号：{'、'.join(meter_nos)}"
                    ),
                )
            )

    for meter_key in sorted(meter_numbers):
        rows = meter_numbers[meter_key]
        module_keys = {
            normalize_business_no(row.module_no)
            for row in rows
            if normalize_business_no(row.module_no)
        }
        if len(module_keys) <= 1:
            continue
        terminals = sorted(
            {str(row.terminal_code).strip() for row in rows}, key=normalize_business_no
        )
        meter_nos = _values(rows, "meter_no")
        module_nos = _values(rows, "module_no")
        all_group_ids = _values(rows, "group_id")
        display_meter = meter_nos[0] if meter_nos else meter_key
        for terminal in terminals:
            issues.append(
                MaterialExportIssue(
                    code="meter_multiple_modules",
                    terminal_code=terminal,
                    group_ids=all_group_ids,
                    meter_nos=meter_nos,
                    module_nos=module_nos,
                    message=(
                        f"表号 {display_meter} 对应多个模块号：{'、'.join(module_nos)}；"
                        f"涉及终端：{'、'.join(terminals)}"
                    ),
                )
            )

    return tuple(
        sorted(
            issues,
            key=lambda issue: (
                normalize_business_no(issue.terminal_code),
                issue.code,
                issue.group_ids,
            ),
        )
    )


def required_meter_issues(meter: MaterialExportMeter) -> tuple[MaterialExportIssue, ...]:
    if not meter.constructed:
        return ()
    required = (
        ("missing_meter_no", meter.meter_no, "缺少表号"),
        ("missing_module_no", meter.module_no, "缺少模块号"),
        ("missing_installation_address", meter.installation_address, "缺少总清单地址"),
        ("missing_module_meter_photo", meter.module_meter_photo_id, "缺少模块与电能表照片"),
        ("missing_after_box_photo", meter.after_box_photo_id, "缺少改造后照片"),
    )
    issues: list[MaterialExportIssue] = []
    for code, value, message in required:
        if normalize_business_no(value):
            continue
        issues.append(
            MaterialExportIssue(
                code=code,
                terminal_code=str(meter.terminal_code or "").strip(),
                group_ids=(str(meter.group_id or "").strip(),),
                meter_nos=((str(meter.meter_no).strip(),) if str(meter.meter_no or "").strip() else ()),
                module_nos=((str(meter.module_no).strip(),) if str(meter.module_no or "").strip() else ()),
                message=message,
            )
        )
    for anomaly in meter.open_module_anomalies:
        if str(anomaly).strip():
            issues.append(
                MaterialExportIssue(
                    code="open_module_anomaly",
                    terminal_code=str(meter.terminal_code or "").strip(),
                    group_ids=(str(meter.group_id or "").strip(),),
                    meter_nos=_values((meter,), "meter_no"),
                    module_nos=_values((meter,), "module_no"),
                    message=f"模块资料存在未关闭异常：{str(anomaly).strip()}",
                )
            )
    return tuple(issues)


def collector_demand(
    meters: Iterable[MaterialExportMeter], requested_count: int
) -> CollectorDemand:
    source = tuple(
        sorted(
            {
                normalize_business_no(item.collector_no)
                for item in meters
                if item.constructed and normalize_business_no(item.collector_no)
            }
        )
    )
    final_count = max(len(source), max(0, int(requested_count)))
    return CollectorDemand(
        source_collector_nos=source,
        final_count=final_count,
        extra_count=final_count - len(source),
    )


_WINDOWS_REPLACEMENTS = str.maketrans(
    {"<": "＜", ">": "＞", ":": "：", '"': "＂", "/": "／", "\\": "＼", "|": "｜", "?": "？", "*": "＊"}
)
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def safe_windows_component(value: object) -> str:
    component = unicodedata.normalize("NFKC", str(value or "")).strip()
    component = component.translate(_WINDOWS_REPLACEMENTS).rstrip(". ")
    if not component:
        component = "_"
    reserved_stem = component.split(".", 1)[0].upper()
    if reserved_stem in _WINDOWS_RESERVED:
        component = f"{component}_"
    component = component[:120].rstrip(". ")
    return component or "_"


def preflight_fingerprint(rows: Iterable[Mapping[str, object]]) -> str:
    canonical = sorted(
        (dict(row) for row in rows),
        key=lambda row: json.dumps(
            row, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
    )
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
