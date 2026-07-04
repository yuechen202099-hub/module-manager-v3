from __future__ import annotations

import argparse
from io import BytesIO
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "v2-api"
sys.path.insert(0, str(API_ROOT))

DEFAULT_LOCAL_STATE_PATH = ROOT / "data" / "platform-terminal-demo-state-local.json"
os.environ.setdefault("LOCAL_SIMULATION_STATE_PATH", str(DEFAULT_LOCAL_STATE_PATH))

from app.services.platform.catalog import (  # noqa: E402
    create_project_draft,
    get_project_overview,
    list_project_definitions,
    update_project_work_item_schema,
)
from app.services.platform.templates import (  # noqa: E402
    build_project_template_workbook,
    create_import_work_order_task,
    create_project_template_import_batch,
    execute_import_work_order_task,
    list_platform_review_work_orders,
)
from app.services.local_simulation import (  # noqa: E402
    assign_construction_task,
    create_empty_group_for_terminal,
    list_construction_task_groups,
    list_construction_tasks,
    reset_current_team,
    save_all_team_states,
    set_current_team,
)
from openpyxl import load_workbook  # noqa: E402


TERMINAL_PROJECT_NAME = "更换终端"
DEFAULT_TEAM_ID = "default-team"
DEFAULT_CONSTRUCTOR = "constructor"

TERMINAL_PROJECT_SCHEMA: dict[str, Any] = {
    "primary_field": {
        "key": "terminal_no",
        "label": "终端（需更换）",
        "data_type": "text",
        "source": "import",
        "capture_method": "manual",
        "required": True,
        "show_in_construction_panel": True,
        "relation_role": "task_object",
    },
    "aggregate_field": {
        "key": "area_no",
        "label": "台区",
        "data_type": "text",
        "source": "import",
        "capture_method": "manual",
        "required": True,
        "show_in_construction_panel": True,
        "relation_role": "aggregate",
    },
    "custom_fields": [
        {
            "key": "old_device_no",
            "label": "旧终端/旧设备（拆回）",
            "data_type": "text",
            "source": "field_collection",
            "capture_method": "scan",
            "required": True,
            "parent_key": "terminal_no",
            "show_in_construction_panel": True,
            "relation_role": "old_device",
        },
        {
            "key": "new_terminal_no",
            "label": "新终端号（安装后扫码）",
            "data_type": "text",
            "source": "field_collection",
            "capture_method": "scan",
            "required": True,
            "parent_key": "terminal_no",
            "show_in_construction_panel": True,
            "relation_role": "replacement_device",
        },
        {
            "key": "communication_module_replace_confirm",
            "label": "通讯模块是否更换",
            "data_type": "enum",
            "source": "field_collection",
            "capture_method": "select",
            "required": True,
            "parent_key": "terminal_no",
            "options": ["更换", "不更换", "待确认"],
            "show_in_construction_panel": True,
            "relation_role": "accessory_replace_confirm",
        },
        {
            "key": "old_communication_module_no",
            "label": "旧通讯模块号（更换时扫码）",
            "data_type": "text",
            "source": "field_collection",
            "capture_method": "scan",
            "required": False,
            "parent_key": "terminal_no",
            "show_in_construction_panel": True,
            "relation_role": "old_device",
            "required_when": {"field_key": "communication_module_replace_confirm", "equals": "更换"},
        },
        {
            "key": "communication_module_no",
            "label": "新通讯模块号（更换时扫码）",
            "data_type": "text",
            "source": "field_collection",
            "capture_method": "scan",
            "required": False,
            "parent_key": "terminal_no",
            "show_in_construction_panel": True,
            "relation_role": "accessory_new_device",
            "required_when": {"field_key": "communication_module_replace_confirm", "equals": "更换"},
        },
        {
            "key": "sim_card_replace_confirm",
            "label": "SIM卡是否更换",
            "data_type": "enum",
            "source": "field_collection",
            "capture_method": "select",
            "required": True,
            "parent_key": "terminal_no",
            "options": ["更换", "不更换", "待确认"],
            "show_in_construction_panel": True,
            "relation_role": "accessory_replace_confirm",
        },
        {
            "key": "old_sim_card_no",
            "label": "旧SIM卡号（更换时录入）",
            "data_type": "text",
            "source": "field_collection",
            "capture_method": "manual",
            "required": False,
            "parent_key": "terminal_no",
            "show_in_construction_panel": True,
            "relation_role": "old_device",
            "required_when": {"field_key": "sim_card_replace_confirm", "equals": "更换"},
        },
        {
            "key": "new_sim_card_no",
            "label": "新SIM卡号（更换时录入）",
            "data_type": "text",
            "source": "field_collection",
            "capture_method": "manual",
            "required": False,
            "parent_key": "terminal_no",
            "show_in_construction_panel": True,
            "relation_role": "accessory_new_device",
            "required_when": {"field_key": "sim_card_replace_confirm", "equals": "更换"},
        },
        {
            "key": "before_reform_photo",
            "label": "改造前照片",
            "data_type": "image",
            "source": "field_collection",
            "capture_method": "photo",
            "required": True,
            "parent_key": "terminal_no",
            "show_in_construction_panel": True,
            "relation_role": "evidence_photo",
        },
        {
            "key": "old_device_recovery_photo",
            "label": "旧设备回收照片",
            "data_type": "image",
            "source": "field_collection",
            "capture_method": "photo",
            "required": True,
            "parent_key": "terminal_no",
            "show_in_construction_panel": True,
            "relation_role": "evidence_photo",
        },
        {
            "key": "old_new_module_photo",
            "label": "新旧模块照片",
            "data_type": "image",
            "source": "field_collection",
            "capture_method": "photo",
            "required": True,
            "parent_key": "terminal_no",
            "show_in_construction_panel": True,
            "relation_role": "evidence_photo",
            "required_when": {"field_key": "communication_module_replace_confirm", "equals": "更换"},
        },
        {
            "key": "after_reform_photo",
            "label": "改造后照片",
            "data_type": "image",
            "source": "field_collection",
            "capture_method": "photo",
            "required": True,
            "parent_key": "terminal_no",
            "show_in_construction_panel": True,
            "relation_role": "evidence_photo",
        },
    ],
}

SAMPLE_WORK_ORDERS: list[dict[str, str]] = [
    {
        "terminal_no": "TT-TERM-001",
        "area_no": "城东一号台区",
        "meter_no": "370100000001",
        "address": "城东路 1 号配电房",
        "constructor": DEFAULT_CONSTRUCTOR,
    },
    {
        "terminal_no": "TT-TERM-002",
        "area_no": "城东一号台区",
        "meter_no": "370100000002",
        "address": "城东路 3 号低压柜",
        "constructor": DEFAULT_CONSTRUCTOR,
    },
    {
        "terminal_no": "TT-TERM-003",
        "area_no": "城南二号台区",
        "meter_no": "370100000003",
        "address": "城南路 8 号箱变",
        "constructor": DEFAULT_CONSTRUCTOR,
    },
]

TERMINAL_REVIEW_SAMPLE_VALUES: dict[str, str] = {
    "terminal_no": "TT-TERM-REVIEW-001",
    "area_no": "城东一号台区",
    "old_device_no": "OLD-TERM-001",
    "new_terminal_no": "NEW-TERM-001",
    "communication_module_replace_confirm": "更换",
    "old_communication_module_no": "OLD-COMM-001",
    "communication_module_no": "NEW-COMM-001",
    "sim_card_replace_confirm": "更换",
    "old_sim_card_no": "OLD-SIM-001",
    "new_sim_card_no": "NEW-SIM-001",
    "before_reform_photo": "before-terminal-review.jpg",
    "old_device_recovery_photo": "old-terminal-recovery.jpg",
    "old_new_module_photo": "old-new-communication-module.jpg",
    "after_reform_photo": "after-terminal-review.jpg",
    "installer": DEFAULT_CONSTRUCTOR,
    "completed_at": "2026-07-03 09:30:00",
    "external_evidence": "本地终端更换审阅样例",
}

TERMINAL_REVIEW_NO_COMM_SAMPLE_VALUES: dict[str, str] = {
    "terminal_no": "TT-TERM-REVIEW-002",
    "area_no": "城东二号台区",
    "old_device_no": "OLD-TERM-002",
    "new_terminal_no": "NEW-TERM-002",
    "communication_module_replace_confirm": "不更换",
    "sim_card_replace_confirm": "更换",
    "old_sim_card_no": "OLD-SIM-002",
    "new_sim_card_no": "NEW-SIM-002",
    "before_reform_photo": "before-terminal-no-comm.jpg",
    "old_device_recovery_photo": "old-terminal-no-comm-recovery.jpg",
    "after_reform_photo": "after-terminal-no-comm.jpg",
    "installer": DEFAULT_CONSTRUCTOR,
    "completed_at": "2026-07-03 10:15:00",
    "external_evidence": "本地终端更换审阅样例：通讯模块不更换",
}

TERMINAL_REVIEW_SAMPLE_VARIANTS: list[dict[str, str]] = [
    TERMINAL_REVIEW_SAMPLE_VALUES,
    TERMINAL_REVIEW_NO_COMM_SAMPLE_VALUES,
]


def ensure_local_environment(force: bool = False) -> None:
    app_env = os.getenv("APP_ENV", "local").strip().lower()
    if force or app_env in {"local", "dev", "development", "test"}:
        return
    raise SystemExit(
        f"Refusing to seed terminal demo data when APP_ENV={app_env!r}. "
        "Set APP_ENV=local/test or pass --force-local only on a disposable local environment."
    )


def ensure_terminal_project() -> dict[str, Any]:
    for project in list_project_definitions():
        if project.get("name") == TERMINAL_PROJECT_NAME:
            project_id = str(project["id"])
            if project.get("status") == "draft":
                return update_project_work_item_schema(project_id, TERMINAL_PROJECT_SCHEMA)
            return get_project_overview(project_id)
    return create_project_draft(
        name=TERMINAL_PROJECT_NAME,
        description="本地演示：终端、通讯模块、新SIM卡和三类改造照片采集。",
        module_ids=["progress", "delivery", "field", "review"],
        work_item_schema=TERMINAL_PROJECT_SCHEMA,
    )


def find_task_by_terminal(terminal: str) -> dict[str, Any] | None:
    for task in list_construction_tasks(include_closed=True):
        if str(task.get("terminal") or "") == terminal:
            return task
    return None


def group_exists_for_task(task_id: int, meter_no: str) -> bool:
    groups = list_construction_task_groups(task_id, limit=1000, summary_only=True).get("items", [])
    return any(str(group.get("meter_no") or "") == meter_no for group in groups)


def ensure_sample_work_order(order: dict[str, str], actor: str) -> dict[str, Any]:
    terminal = order["terminal_no"]
    meter_no = order["meter_no"]
    task = find_task_by_terminal(terminal)
    created_group = None
    if task is None or not group_exists_for_task(int(task["id"]), meter_no):
        created = create_empty_group_for_terminal(
            terminal=terminal,
            actor=actor,
            meter_no=meter_no,
            address=order["address"],
            meter_match_key=meter_no,
        )
        created_group = created.get("group")
        task = created.get("task") or find_task_by_terminal(terminal)
    if task is None:
        raise RuntimeError(f"Failed to create task for terminal {terminal}")
    if str(task.get("construction_claimed_by") or "") != order["constructor"]:
        task = assign_construction_task(
            int(task["id"]),
            actor=actor,
            constructor=order["constructor"],
            note=f"{TERMINAL_PROJECT_NAME} 本地演示样例",
        )
    return {"task": task, "group": created_group, "order": order}


def seed_terminal_demo(*, actor: str = "admin", team_id: str = DEFAULT_TEAM_ID, force_local: bool = False) -> dict[str, Any]:
    ensure_local_environment(force_local)
    token = set_current_team(team_id)
    try:
        project = ensure_terminal_project()
        seeded = [ensure_sample_work_order(order, actor) for order in SAMPLE_WORK_ORDERS]
        save_all_team_states()
    finally:
        reset_current_team(token)
    return {
        "project": project,
        "team_id": team_id,
        "draft_store_path": os.getenv("PLATFORM_PROJECT_DRAFTS_PATH", ""),
        "local_state_path": os.getenv("LOCAL_SIMULATION_STATE_PATH", ""),
        "sample_count": len(SAMPLE_WORK_ORDERS),
        "items": seeded,
    }


def find_terminal_review_work_order(project_id: str, terminal_no: str) -> dict[str, Any] | None:
    payload = list_platform_review_work_orders(project_id)
    for work_order in payload.get("items", []):
        if str(work_order.get("primary_value") or "") == terminal_no:
            return work_order
    return None


def build_terminal_review_sample_workbook(project_id: str, values: dict[str, str] | None = None) -> bytes:
    sample_values = values or TERMINAL_REVIEW_SAMPLE_VALUES
    workbook_content = build_project_template_workbook(project_id, "external_completed")
    workbook = load_workbook(BytesIO(workbook_content))
    sheet = workbook.active
    field_keys_by_column: dict[int, str] = {}
    for column in range(1, sheet.max_column + 1):
        raw_code = str(sheet.cell(row=3, column=column).value or "")
        if ":" not in raw_code:
            continue
        field_key = raw_code.split(":", 1)[1].strip()
        if field_key:
            field_keys_by_column[column] = field_key
    for column, field_key in field_keys_by_column.items():
        sheet.cell(row=2, column=column).value = sample_values.get(field_key, "")
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def seed_terminal_review_sample(
    *,
    actor: str = "admin",
    team_id: str = DEFAULT_TEAM_ID,
    force_local: bool = False,
) -> dict[str, Any]:
    ensure_local_environment(force_local)
    token = set_current_team(team_id)
    try:
        project = ensure_terminal_project()
        project_id = str(project["id"])
        review_work_orders: list[dict[str, Any]] = []
        created_any = False
        for index, values in enumerate(TERMINAL_REVIEW_SAMPLE_VARIANTS, start=1):
            terminal_no = values["terminal_no"]
            existing = find_terminal_review_work_order(project_id, terminal_no)
            if existing is not None:
                review_work_orders.append(existing)
                continue

            workbook_content = build_terminal_review_sample_workbook(project_id, values)
            batch = create_project_template_import_batch(
                project_id,
                "external_completed",
                workbook_content,
                f"terminal-review-hierarchy-demo-{index}.xlsx",
                actor=actor,
            )
            task = create_import_work_order_task(project_id, batch["job_id"], actor=actor)
            execute_import_work_order_task(project_id, task["job_id"], actor=actor)
            review_work_order = find_terminal_review_work_order(project_id, terminal_no)
            if review_work_order is None:
                raise RuntimeError(f"Failed to create terminal review sample work order: {terminal_no}")
            review_work_orders.append(review_work_order)
            created_any = True

        primary_review_work_order = next(
            (item for item in review_work_orders if str(item.get("primary_value") or "") == TERMINAL_REVIEW_SAMPLE_VALUES["terminal_no"]),
            review_work_orders[0] if review_work_orders else None,
        )
        if primary_review_work_order is None:
            raise RuntimeError("Failed to create terminal review sample work order")
        if not created_any:
            return {
                "created": False,
                "project": project,
                "team_id": team_id,
                "review_work_order": primary_review_work_order,
                "review_work_orders": review_work_orders,
            }
        return {
            "created": True,
            "project": project,
            "team_id": team_id,
            "review_work_order": primary_review_work_order,
            "review_work_orders": review_work_orders,
        }
    finally:
        reset_current_team(token)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed local terminal replacement project demo data.")
    parser.add_argument("--team-id", default=DEFAULT_TEAM_ID)
    parser.add_argument("--actor", default="admin")
    parser.add_argument("--force-local", action="store_true")
    parser.add_argument("--with-review-sample", action="store_true")
    args = parser.parse_args()

    result = seed_terminal_demo(actor=args.actor, team_id=args.team_id, force_local=args.force_local)
    project = result["project"]
    print(f"project\t{project['id']}\t{project['name']}\t{project['status']}")
    print(f"team\t{result['team_id']}")
    print(f"state\t{result['local_state_path']}")
    print(f"sample_work_orders\t{result['sample_count']}")
    for item in result["items"]:
        task = item["task"]
        order = item["order"]
        print(f"task\t{task['id']}\t{order['terminal_no']}\t{order['meter_no']}\t{task.get('construction_claimed_by') or ''}")
    if args.with_review_sample:
        review_result = seed_terminal_review_sample(actor=args.actor, team_id=args.team_id, force_local=args.force_local)
        review_work_order = review_result["review_work_order"]
        print(f"review_sample\t{review_work_order['id']}\t{review_work_order['primary_value']}\t{review_work_order['review_status']}")


if __name__ == "__main__":
    main()
