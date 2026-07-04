from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "v2-api"
sys.path.insert(0, str(API_ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import Workbook  # noqa: E402

from app.main import app  # noqa: E402
from app.services.platform import templates as platform_templates  # noqa: E402
from app.services.platform.catalog import configure_project_draft_store_path, reset_project_drafts  # noqa: E402


TERMINAL = "\u7ec8\u7aef"
AREA = "\u53f0\u533a"
NEW_TERMINAL_NO = "\u65b0\u7ec8\u7aef\u53f7"
COMM_REPLACE_CONFIRM = "\u901a\u8baf\u6a21\u5757\u662f\u5426\u66f4\u6362"
OLD_COMM_MODULE = "\u65e7\u901a\u8baf\u6a21\u5757\u53f7"
NEW_COMM_MODULE = "\u65b0\u901a\u8baf\u6a21\u5757\u53f7"
OLD_NEW_MODULE_PHOTO = "\u65b0\u65e7\u6a21\u5757\u7167\u7247"
REPLACE = "\u66f4\u6362"
KEEP = "\u4e0d\u66f4\u6362"
IMPORT_HIERARCHY_GAP = "\u5bfc\u5165\u5c42\u7ea7\u7f3a\u53e3"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"[FAIL] {message}")


def workbook_bytes(rows: list[list[str]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def reset_platform_runtime_files() -> None:
    with platform_templates._IMPORT_BATCHES_LOCK:
        platform_templates._IMPORT_BATCHES.clear()
        platform_templates._IMPORT_BATCHES_LOADED = False
    with platform_templates._WORK_ORDER_TASKS_LOCK:
        platform_templates._WORK_ORDER_TASKS.clear()
        platform_templates._WORK_ORDER_TASKS_LOADED = False
    with platform_templates._PLATFORM_WORK_ORDERS_LOCK:
        platform_templates._PLATFORM_WORK_ORDERS.clear()
        platform_templates._PLATFORM_WORK_ORDERS_LOADED = False
    for path in (
        platform_templates._import_batches_store_path(),
        platform_templates._work_order_tasks_store_path(),
        platform_templates._platform_work_orders_store_path(),
    ):
        if path.exists():
            path.unlink()


def create_terminal_project(client: TestClient) -> str:
    response = client.post(
        "/projects",
        json={
            "name": "construction rework gap panel",
            "module_ids": ["progress", "field", "review", "tasks", "delivery"],
            "work_item_schema": {
                "primary_field": {
                    "key": "terminal_no",
                    "label": TERMINAL,
                    "source": "import",
                    "capture_method": "scan",
                    "data_type": "text",
                    "required": True,
                    "relation_role": "task_object",
                },
                "aggregate_field": {
                    "key": "area_no",
                    "label": AREA,
                    "source": "import",
                    "capture_method": "manual",
                    "data_type": "text",
                    "required": True,
                    "relation_role": "aggregate",
                },
                "custom_fields": [
                    {
                        "key": "new_terminal_no",
                        "label": NEW_TERMINAL_NO,
                        "data_type": "text",
                        "source": "field_collection",
                        "capture_method": "scan",
                        "required": True,
                        "parent_key": "terminal_no",
                        "show_in_construction_panel": True,
                        "relation_role": "replacement_device",
                    },
                    {
                        "key": "comm_replace_confirm",
                        "label": COMM_REPLACE_CONFIRM,
                        "data_type": "enum",
                        "source": "field_collection",
                        "capture_method": "select",
                        "required": True,
                        "parent_key": "terminal_no",
                        "show_in_construction_panel": True,
                        "relation_role": "accessory_replace_confirm",
                        "options": [REPLACE, KEEP],
                    },
                    {
                        "key": "old_comm_module",
                        "label": OLD_COMM_MODULE,
                        "data_type": "text",
                        "source": "field_collection",
                        "capture_method": "scan",
                        "required": False,
                        "parent_key": "terminal_no",
                        "show_in_construction_panel": True,
                        "relation_role": "old_device",
                        "required_when": {"field_key": "comm_replace_confirm", "equals": REPLACE},
                    },
                    {
                        "key": "new_comm_module",
                        "label": NEW_COMM_MODULE,
                        "data_type": "text",
                        "source": "field_collection",
                        "capture_method": "scan",
                        "required": False,
                        "parent_key": "terminal_no",
                        "show_in_construction_panel": True,
                        "relation_role": "accessory_new_device",
                        "required_when": {"field_key": "comm_replace_confirm", "equals": REPLACE},
                    },
                    {
                        "key": "old_new_module_photo",
                        "label": OLD_NEW_MODULE_PHOTO,
                        "data_type": "image",
                        "source": "field_collection",
                        "capture_method": "photo",
                        "required": False,
                        "parent_key": "terminal_no",
                        "show_in_construction_panel": True,
                        "relation_role": "evidence_photo",
                        "required_when": {"field_key": "comm_replace_confirm", "equals": REPLACE},
                    },
                ],
            },
        },
    )
    require(response.status_code == 200, f"project creation failed: {response.text}")
    return response.json()["data"]["id"]


def create_returned_work_order(client: TestClient, project_id: str) -> str:
    rows = [
        [TERMINAL, AREA, NEW_TERMINAL_NO, COMM_REPLACE_CONFIRM, OLD_COMM_MODULE, NEW_COMM_MODULE, OLD_NEW_MODULE_PHOTO],
        ["TERM-001", "\u53f0\u533a-01", "TERM-NEW-001", REPLACE, "", "", ""],
    ]
    batch_response = client.post(
        f"/projects/{project_id}/templates/external_completed/import-batches",
        data={"actor": "admin"},
        files={
            "file": (
                "external-completed-rework-gap.xlsx",
                workbook_bytes(rows),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    require(batch_response.status_code == 200, f"external completed import batch failed: {batch_response.text}")
    task_response = client.post(
        f"/projects/{project_id}/import-batches/{batch_response.json()['data']['job_id']}/work-order-tasks",
        json={"actor": "admin", "mode": "safe_record_only"},
    )
    require(task_response.status_code == 200, f"work order task creation failed: {task_response.text}")
    execute_response = client.post(
        f"/projects/{project_id}/work-order-tasks/{task_response.json()['data']['job_id']}/execute",
        json={"actor": "admin", "mode": "local_platform_store"},
    )
    require(execute_response.status_code == 200, f"work order task execution failed: {execute_response.text}")
    review_response = client.get(f"/projects/{project_id}/review/work-orders")
    require(review_response.status_code == 200, f"review listing failed: {review_response.text}")
    work_order_id = review_response.json()["data"]["items"][0]["id"]
    return_response = client.post(
        f"/projects/{project_id}/review/work-orders/{work_order_id}/actions",
        json={"actor": "reviewer", "action": "returned", "note": "", "reason": ""},
    )
    require(return_response.status_code == 200, f"return action failed: {return_response.text}")
    return work_order_id


def main() -> None:
    with TemporaryDirectory() as temp_dir:
        configure_project_draft_store_path(Path(temp_dir) / "platform-project-drafts.json")
        reset_project_drafts(remove_store=True)
        reset_platform_runtime_files()
        try:
            client = TestClient(app)
            project_id = create_terminal_project(client)
            work_order_id = create_returned_work_order(client, project_id)
            construction_response = client.get(f"/projects/{project_id}/construction/work-orders")
            require(construction_response.status_code == 200, f"construction listing failed: {construction_response.text}")
            items = construction_response.json()["data"].get("items", [])
            work_order = next((item for item in items if item.get("id") == work_order_id), None)
            require(work_order is not None, "returned platform work order missing from construction listing")
            require(work_order.get("review_status") == "returned", "construction work order must expose returned review status")
            groups = work_order.get("rework_evidence_gap_groups")
            require(isinstance(groups, list) and groups, "construction payload must expose rework_evidence_gap_groups")
            gap_by_label = {group.get("label"): group.get("items", []) for group in groups if isinstance(group, dict)}
            imported_items = gap_by_label.get(IMPORT_HIERARCHY_GAP) or []
            require(OLD_COMM_MODULE in imported_items, "old accessory field missing from rework gap group")
            require(NEW_COMM_MODULE in imported_items, "new accessory field missing from rework gap group")
            require(OLD_NEW_MODULE_PHOTO in imported_items, "photo evidence field missing from rework gap group")
        finally:
            reset_project_drafts(remove_store=True)
            reset_platform_runtime_files()
            configure_project_draft_store_path(None)

    print("[OK] construction rework gap panel payload is available")


if __name__ == "__main__":
    main()
