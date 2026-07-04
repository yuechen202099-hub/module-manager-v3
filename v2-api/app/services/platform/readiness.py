from __future__ import annotations

from typing import Any

from app.services.platform.catalog import (
    _normalize_project_workflow,
    _normalize_work_item_schema,
    get_project_definition,
    list_project_definitions,
)


READINESS_SAFETY = [
    "read_only_no_write",
    "no_database_connection",
    "no_postgres_schema_change",
    "no_production_data_edit",
]

READY_NEXT_ACTIONS = [
    "ready_for_template_import",
    "ready_for_construction_collection",
    "ready_for_review_archive",
]

ACTION_BY_CHECK_ID = {
    "primary_field": "set_primary_field",
    "aggregate_field": "set_aggregate_field",
    "single_aggregate_field": "fix_aggregate_field",
    "custom_site_fields": "complete_field_schema",
    "photo_evidence": "add_photo_evidence_fields",
    "required_kpi_fields": "confirm_required_kpi_fields",
    "core_modules": "enable_required_modules",
    "template_import_workflow": "enable_template_import_workflow",
    "construction_workflow": "enable_construction_workflow",
    "review_workflow": "enable_review_workflow",
    "delivery_workflow": "enable_delivery_workflow",
    "device_hierarchy": "complete_device_hierarchy",
}

DEVICE_RELATION_ROLES = {
    "replacement_device",
    "old_device",
    "accessory_replace_confirm",
    "accessory_new_device",
    "evidence_photo",
}

CONDITIONAL_ACCESSORY_ROLES = {"old_device", "accessory_new_device", "evidence_photo"}

ACCESSORY_HINTS = (
    "accessory",
    "communication",
    "module",
    "sim",
    "collector",
    "附属",
    "通讯",
    "模块",
    "sim卡",
    "采集器",
)


def _field_key(field: dict[str, Any] | None) -> str:
    return str((field or {}).get("key") or "").strip()


def _field_label(field: dict[str, Any] | None) -> str:
    return str((field or {}).get("label") or "").strip()


def _check(
    *,
    check_id: str,
    group: str,
    label: str,
    passed: bool,
    evidence: dict[str, Any],
    action: str,
    severity: str = "blocker",
) -> dict[str, Any]:
    return {
        "id": check_id,
        "group": group,
        "label": label,
        "status": "passed" if passed else "failed",
        "severity": severity,
        "evidence": evidence,
        "action": action,
    }


def _enabled_workflow_node_ids(workflow: dict[str, Any]) -> set[str]:
    return {
        str(node.get("id") or "")
        for node in workflow.get("nodes", [])
        if isinstance(node, dict) and bool(node.get("enabled")) and str(node.get("id") or "").strip()
    }


def _custom_site_fields(field_schema: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        field
        for field in field_schema.get("custom_fields", [])
        if isinstance(field, dict)
        and str(field.get("source") or "") == "field_collection"
        and str(field.get("capture_method") or "") != "photo"
    ]


def _photo_fields(field_schema: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        field
        for field in field_schema.get("custom_fields", [])
        if isinstance(field, dict)
        and (
            str(field.get("capture_method") or "") == "photo"
            or str(field.get("data_type") or "") == "image"
        )
    ]


def _required_kpi_keys(field_schema: dict[str, Any]) -> list[str]:
    return [
        str(field.get("key") or "")
        for field in field_schema.get("platform_required_fields", [])
        if isinstance(field, dict) and (field.get("required") or field.get("kpi_enabled"))
    ]


def _custom_fields(field_schema: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        field
        for field in field_schema.get("custom_fields", [])
        if isinstance(field, dict)
    ]


def _relation_role(field: dict[str, Any] | None) -> str:
    return str((field or {}).get("relation_role") or "").strip()


def _required_when_field_key(field: dict[str, Any] | None) -> str:
    required_when = (field or {}).get("required_when")
    if not isinstance(required_when, dict):
        return ""
    return str(required_when.get("field_key") or "").strip()


def _field_search_text(field: dict[str, Any]) -> str:
    return f"{_field_key(field)} {_field_label(field)}".lower()


def _looks_like_accessory_confirmation(field: dict[str, Any]) -> bool:
    text = _field_search_text(field)
    return (
        _relation_role(field) == "accessory_replace_confirm"
        or "replace_confirm" in text
        or "confirm" in text
        or "是否更换" in text
        or "确认是否更换" in text
    )


def _looks_like_conditional_accessory_child(field: dict[str, Any]) -> bool:
    text = _field_search_text(field)
    return any(hint.lower() in text for hint in ACCESSORY_HINTS)


def _device_replacement_hierarchy_mode(fields: list[dict[str, Any]]) -> str:
    has_device_replacement = any(
        _relation_role(field) in DEVICE_RELATION_ROLES
        or _looks_like_accessory_confirmation(field)
        for field in fields
    )
    if not has_device_replacement:
        return "no_device_replacement_fields"
    if any(_relation_role(field) == "replacement_device" for field in fields):
        return "main_device_with_accessory_confirmation"
    return "accessory_under_task_object"


def _device_hierarchy_contract(replacement_hierarchy_mode: str) -> dict[str, str]:
    return {
        "active_mode": replacement_hierarchy_mode,
        "module_replacement": "换模块：任务对象保持不变，在任务对象下更换附属设备。",
        "terminal_replacement": "换终端：先完成主设备更换，再确认附属设备是否更换，并按确认结果采集旧件、新件或照片。",
        "conditional_collection": "附属设备选择“更换”后，旧件、新件和照片通过 required_when 条件采集。",
    }


def _single_aggregate_field_check(field_schema: dict[str, Any]) -> dict[str, Any]:
    primary_field = field_schema.get("primary_field", {})
    aggregate_field = field_schema.get("aggregate_field", {})
    fields = _custom_fields(field_schema)
    extra_aggregate_keys = [
        _field_key(field)
        for field in fields
        if _relation_role(field) == "aggregate" and _field_key(field)
    ]
    primary_is_aggregate = _relation_role(primary_field) == "aggregate"
    aggregate_role = _relation_role(aggregate_field)
    aggregate_role_invalid = bool(aggregate_role and aggregate_role != "aggregate")
    passed = not (primary_is_aggregate or aggregate_role_invalid or extra_aggregate_keys)
    return _check(
        check_id="single_aggregate_field",
        group="field_schema",
        label="Single aggregate field configured",
        passed=passed,
        evidence={
            "aggregate_key": _field_key(aggregate_field),
            "aggregate_role": aggregate_role or "aggregate",
            "primary_is_aggregate": primary_is_aggregate,
            "extra_aggregate_keys": extra_aggregate_keys,
            "active_aggregate_count": 1 + len(extra_aggregate_keys) + (1 if primary_is_aggregate else 0),
        },
        action=ACTION_BY_CHECK_ID["single_aggregate_field"],
    )


def _device_hierarchy_check(field_schema: dict[str, Any]) -> dict[str, Any]:
    primary_key = _field_key(field_schema.get("primary_field", {}))
    fields = _custom_fields(field_schema)
    replacement_hierarchy_mode = _device_replacement_hierarchy_mode(fields)
    device_fields = [
        field
        for field in fields
        if _relation_role(field) in DEVICE_RELATION_ROLES or _looks_like_accessory_confirmation(field)
    ]
    if not device_fields:
        return _check(
            check_id="device_hierarchy",
            group="field_schema",
            label="Device replacement hierarchy configured",
            passed=True,
            evidence={
                "mode": "no_device_replacement_fields",
                "replacement_hierarchy_mode": replacement_hierarchy_mode,
                "requires_accessory_confirmation": False,
                "hierarchy_contract": _device_hierarchy_contract(replacement_hierarchy_mode),
            },
            action=ACTION_BY_CHECK_ID["device_hierarchy"],
        )

    confirmation_fields = [
        field
        for field in fields
        if _relation_role(field) == "accessory_replace_confirm"
    ]
    confirmation_keys = {_field_key(field) for field in confirmation_fields if _field_key(field)}
    has_main_replacement = any(_relation_role(field) == "replacement_device" for field in fields)

    missing_parent_keys = [
        _field_key(field)
        for field in device_fields
        if _field_key(field) and str(field.get("parent_key") or "").strip() != primary_key
    ]
    missing_confirmation_keys = [
        _field_key(field)
        for field in fields
        if _looks_like_accessory_confirmation(field)
        and _field_key(field)
        and _relation_role(field) != "accessory_replace_confirm"
    ]
    invalid_conditional_keys = [
        _field_key(field)
        for field in fields
        if _required_when_field_key(field) and _required_when_field_key(field) not in confirmation_keys
    ]

    unconditional_child_keys: list[str] = []
    if has_main_replacement:
        for field in fields:
            role = _relation_role(field)
            if role == "accessory_new_device" and not _required_when_field_key(field):
                unconditional_child_keys.append(_field_key(field))
            if (
                role == "evidence_photo"
                and not _required_when_field_key(field)
                and _looks_like_conditional_accessory_child(field)
            ):
                unconditional_child_keys.append(_field_key(field))

    confirmation_without_child_keys = [
        _field_key(field)
        for field in confirmation_fields
        if _field_key(field)
        and not any(_required_when_field_key(child) == _field_key(field) for child in fields)
    ]
    missing_main_accessory_confirmation = has_main_replacement and not confirmation_keys

    passed = not (
        missing_parent_keys
        or missing_confirmation_keys
        or invalid_conditional_keys
        or unconditional_child_keys
        or confirmation_without_child_keys
        or missing_main_accessory_confirmation
    )
    return _check(
        check_id="device_hierarchy",
        group="field_schema",
        label="Device replacement hierarchy configured",
        passed=passed,
        evidence={
            "primary_key": primary_key,
            "device_field_keys": [_field_key(field) for field in device_fields if _field_key(field)],
            "main_replacement_keys": [
                _field_key(field)
                for field in fields
                if _relation_role(field) == "replacement_device" and _field_key(field)
            ],
            "main_old_device_keys": [
                _field_key(field)
                for field in fields
                if _relation_role(field) == "old_device"
                and not _required_when_field_key(field)
                and _field_key(field)
            ],
            "direct_accessory_replacement_keys": [
                _field_key(field)
                for field in fields
                if _relation_role(field) == "accessory_new_device"
                and not _required_when_field_key(field)
                and _field_key(field)
            ],
            "conditional_accessory_keys": [
                _field_key(field)
                for field in fields
                if _required_when_field_key(field) and _field_key(field)
            ],
            "accessory_confirmation_keys": sorted(confirmation_keys),
            "replacement_hierarchy_mode": replacement_hierarchy_mode,
            "requires_accessory_confirmation": has_main_replacement,
            "hierarchy_contract": _device_hierarchy_contract(replacement_hierarchy_mode),
            "missing_parent_keys": missing_parent_keys,
            "missing_confirmation_keys": missing_confirmation_keys,
            "invalid_conditional_keys": invalid_conditional_keys,
            "unconditional_child_keys": unconditional_child_keys,
            "confirmation_without_child_keys": confirmation_without_child_keys,
            "missing_main_accessory_confirmation": missing_main_accessory_confirmation,
        },
        action=ACTION_BY_CHECK_ID["device_hierarchy"],
    )


def _summary(checks: list[dict[str, Any]]) -> dict[str, int]:
    passed = sum(1 for check in checks if check["status"] == "passed")
    failed = sum(1 for check in checks if check["status"] == "failed")
    blockers = sum(1 for check in checks if check["status"] == "failed" and check["severity"] == "blocker")
    return {
        "total": len(checks),
        "passed": passed,
        "failed": failed,
        "blockers": blockers,
    }


def _next_actions(checks: list[dict[str, Any]]) -> list[str]:
    failed_actions = [
        str(check.get("action") or "")
        for check in checks
        if check.get("status") == "failed" and str(check.get("action") or "")
    ]
    if failed_actions:
        return list(dict.fromkeys(failed_actions))
    return list(READY_NEXT_ACTIONS)


def _action_counts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in items:
        if bool(item.get("ready")):
            continue
        for action in item.get("next_actions", []):
            action_id = str(action or "").strip()
            if action_id:
                counts[action_id] = counts.get(action_id, 0) + 1
    return [
        {"action": action, "count": count}
        for action, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]


def build_project_readiness(project_id: str) -> dict[str, Any]:
    definition = get_project_definition(project_id)
    field_schema = _normalize_work_item_schema(definition.work_item_schema)
    workflow = _normalize_project_workflow(definition.workflow, module_ids=definition.module_ids)
    module_ids = set(definition.module_ids)
    enabled_node_ids = _enabled_workflow_node_ids(workflow)

    primary_field = field_schema.get("primary_field", {})
    aggregate_field = field_schema.get("aggregate_field", {})
    site_fields = _custom_site_fields(field_schema)
    photo_fields = _photo_fields(field_schema)
    required_kpi_keys = _required_kpi_keys(field_schema)

    checks = [
        _check(
            check_id="primary_field",
            group="field_schema",
            label="Primary field configured",
            passed=_field_key(primary_field) not in {"", "work_item"} and bool(primary_field.get("required")),
            evidence={"key": _field_key(primary_field), "label": _field_label(primary_field)},
            action=ACTION_BY_CHECK_ID["primary_field"],
        ),
        _check(
            check_id="aggregate_field",
            group="field_schema",
            label="Aggregate field configured",
            passed=_field_key(aggregate_field) not in {"", "work_order_group"} and bool(aggregate_field.get("required")),
            evidence={"key": _field_key(aggregate_field), "label": _field_label(aggregate_field)},
            action=ACTION_BY_CHECK_ID["aggregate_field"],
        ),
        _single_aggregate_field_check(field_schema),
        _check(
            check_id="custom_site_fields",
            group="field_schema",
            label="Site collection fields configured",
            passed=len(site_fields) >= 2,
            evidence={"count": len(site_fields), "keys": [_field_key(field) for field in site_fields]},
            action=ACTION_BY_CHECK_ID["custom_site_fields"],
        ),
        _check(
            check_id="photo_evidence",
            group="construction_evidence",
            label="Photo evidence fields configured",
            passed=len(photo_fields) >= 2,
            evidence={"count": len(photo_fields), "keys": [_field_key(field) for field in photo_fields]},
            action=ACTION_BY_CHECK_ID["photo_evidence"],
        ),
        _check(
            check_id="required_kpi_fields",
            group="kpi",
            label="Required KPI fields are present",
            passed={"installer", "completed_at", "photo_count"}.issubset(required_kpi_keys),
            evidence={"keys": required_kpi_keys},
            action=ACTION_BY_CHECK_ID["required_kpi_fields"],
        ),
        _device_hierarchy_check(field_schema),
        _check(
            check_id="core_modules",
            group="workflow",
            label="Core platform modules enabled",
            passed={"field", "review", "tasks", "delivery"}.issubset(module_ids),
            evidence={"module_ids": list(definition.module_ids)},
            action=ACTION_BY_CHECK_ID["core_modules"],
        ),
        _check(
            check_id="template_import_workflow",
            group="workflow",
            label="Template import workflow enabled",
            passed="template_import" in enabled_node_ids,
            evidence={"enabled_node_ids": sorted(enabled_node_ids)},
            action=ACTION_BY_CHECK_ID["template_import_workflow"],
        ),
        _check(
            check_id="construction_workflow",
            group="workflow",
            label="Construction collection workflow enabled",
            passed="construction_collection" in enabled_node_ids,
            evidence={"enabled_node_ids": sorted(enabled_node_ids)},
            action=ACTION_BY_CHECK_ID["construction_workflow"],
        ),
        _check(
            check_id="review_workflow",
            group="workflow",
            label="Review workflow enabled",
            passed="review" in enabled_node_ids,
            evidence={"enabled_node_ids": sorted(enabled_node_ids)},
            action=ACTION_BY_CHECK_ID["review_workflow"],
        ),
        _check(
            check_id="delivery_workflow",
            group="workflow",
            label="Delivery archive workflow enabled",
            passed="delivery_archive" in enabled_node_ids,
            evidence={"enabled_node_ids": sorted(enabled_node_ids)},
            action=ACTION_BY_CHECK_ID["delivery_workflow"],
        ),
    ]

    summary = _summary(checks)
    ready = summary["blockers"] == 0
    return {
        "readiness_version": 1,
        "project_id": definition.id,
        "ready": ready,
        "summary": summary,
        "checks": checks,
        "next_actions": _next_actions(checks),
        "safety": list(READINESS_SAFETY),
    }


def build_project_readiness_summary() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for project in list_project_definitions():
        project_id = str(project.get("id") or "")
        readiness = build_project_readiness(project_id)
        items.append(
            {
                "project_id": project_id,
                "project_name": str(project.get("name") or project_id),
                "project_status": str(project.get("status") or ""),
                "ready": bool(readiness.get("ready")),
                "summary": dict(readiness.get("summary") or {}),
                "next_actions": list(readiness.get("next_actions") or []),
            }
        )
    ready_count = sum(1 for item in items if item["ready"])
    return {
        "readiness_version": 1,
        "total": len(items),
        "ready": ready_count,
        "not_ready": len(items) - ready_count,
        "action_counts": _action_counts(items),
        "items": items,
        "safety": list(READINESS_SAFETY),
    }
