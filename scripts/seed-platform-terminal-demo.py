from __future__ import annotations

import argparse
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
from app.services.local_simulation import (  # noqa: E402
    assign_construction_task,
    create_empty_group_for_terminal,
    list_construction_task_groups,
    list_construction_tasks,
    reset_current_team,
    save_all_team_states,
    set_current_team,
)


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
    },
    "aggregate_field": {
        "key": "area_no",
        "label": "台区",
        "data_type": "text",
        "source": "import",
        "capture_method": "manual",
        "required": True,
    },
    "custom_fields": [
        {
            "key": "old_device_no",
            "label": "旧设备（拆回）",
            "data_type": "text",
            "source": "field_collection",
            "capture_method": "scan",
            "required": True,
            "parent_key": "terminal_no",
        },
        {
            "key": "communication_module_no",
            "label": "通讯模块（需更换）",
            "data_type": "text",
            "source": "field_collection",
            "capture_method": "scan",
            "required": True,
            "parent_key": "terminal_no",
        },
        {
            "key": "new_sim_card_no",
            "label": "新SIM卡",
            "data_type": "text",
            "source": "field_collection",
            "capture_method": "manual",
            "required": True,
            "parent_key": "terminal_no",
        },
        {
            "key": "before_reform_photo",
            "label": "改造前照片",
            "data_type": "image",
            "source": "field_collection",
            "capture_method": "photo",
            "required": True,
            "parent_key": "terminal_no",
        },
        {
            "key": "old_device_recovery_photo",
            "label": "旧设备回收照片",
            "data_type": "image",
            "source": "field_collection",
            "capture_method": "photo",
            "required": True,
            "parent_key": "terminal_no",
        },
        {
            "key": "old_new_module_photo",
            "label": "新旧模块照片",
            "data_type": "image",
            "source": "field_collection",
            "capture_method": "photo",
            "required": True,
            "parent_key": "terminal_no",
        },
        {
            "key": "after_reform_photo",
            "label": "改造后照片",
            "data_type": "image",
            "source": "field_collection",
            "capture_method": "photo",
            "required": True,
            "parent_key": "terminal_no",
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed local terminal replacement project demo data.")
    parser.add_argument("--team-id", default=DEFAULT_TEAM_ID)
    parser.add_argument("--actor", default="admin")
    parser.add_argument("--force-local", action="store_true")
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


if __name__ == "__main__":
    main()
