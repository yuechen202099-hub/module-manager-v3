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
            "name": "review return reason suggestion",
            "module_ids": ["progress", "field", "review", "tasks", "delivery"],
            "work_item_schema": {
                "primary_field": {
                    "key": "terminal_no",
                    "label": "终端",
                    "source": "import",
                    "capture_method": "scan",
                    "data_type": "text",
                    "required": True,
                    "relation_role": "task_object",
                },
                "aggregate_field": {
                    "key": "area_no",
                    "label": "台区",
                    "source": "import",
                    "capture_method": "manual",
                    "data_type": "text",
                    "required": True,
                    "relation_role": "aggregate",
                },
                "custom_fields": [
                    {
                        "key": "new_terminal_no",
                        "label": "新终端号",
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
                        "label": "通讯模块是否更换",
                        "data_type": "enum",
                        "source": "field_collection",
                        "capture_method": "select",
                        "required": True,
                        "parent_key": "terminal_no",
                        "show_in_construction_panel": True,
                        "relation_role": "accessory_replace_confirm",
                        "options": ["更换", "不更换"],
                    },
                    {
                        "key": "old_comm_module",
                        "label": "旧通讯模块号",
                        "data_type": "text",
                        "source": "field_collection",
                        "capture_method": "scan",
                        "required": False,
                        "parent_key": "terminal_no",
                        "show_in_construction_panel": True,
                        "relation_role": "old_device",
                        "required_when": {"field_key": "comm_replace_confirm", "equals": "更换"},
                    },
                    {
                        "key": "new_comm_module",
                        "label": "新通讯模块号",
                        "data_type": "text",
                        "source": "field_collection",
                        "capture_method": "scan",
                        "required": False,
                        "parent_key": "terminal_no",
                        "show_in_construction_panel": True,
                        "relation_role": "accessory_new_device",
                        "required_when": {"field_key": "comm_replace_confirm", "equals": "更换"},
                    },
                    {
                        "key": "old_new_module_photo",
                        "label": "新旧模块照片",
                        "data_type": "image",
                        "source": "field_collection",
                        "capture_method": "photo",
                        "required": False,
                        "parent_key": "terminal_no",
                        "show_in_construction_panel": True,
                        "relation_role": "evidence_photo",
                        "required_when": {"field_key": "comm_replace_confirm", "equals": "更换"},
                    },
                ],
            },
        },
    )
    require(response.status_code == 200, f"project creation failed: {response.text}")
    return response.json()["data"]["id"]


def create_external_completed_work_order(client: TestClient, project_id: str) -> str:
    rows = [
        ["终端", "台区", "新终端号", "通讯模块是否更换", "旧通讯模块号", "新通讯模块号", "新旧模块照片"],
        ["TERM-001", "台区-01", "TERM-NEW-001", "更换", "", "", ""],
    ]
    batch_response = client.post(
        f"/projects/{project_id}/templates/external_completed/import-batches",
        data={"actor": "admin"},
        files={
            "file": (
                "external-completed-return-suggestion.xlsx",
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
    items = review_response.json()["data"].get("items", [])
    require(len(items) == 1, "expected one review work order")
    return items[0]["id"]


def main() -> None:
    with TemporaryDirectory() as temp_dir:
        configure_project_draft_store_path(Path(temp_dir) / "platform-project-drafts.json")
        reset_project_drafts(remove_store=True)
        reset_platform_runtime_files()
        try:
            client = TestClient(app)
            project_id = create_terminal_project(client)
            work_order_id = create_external_completed_work_order(client, project_id)

            review_response = client.get(f"/projects/{project_id}/review/work-orders")
            work_order = review_response.json()["data"]["items"][0]
            suggestion = str(work_order.get("suggested_review_return_reason") or "")
            require("导入层级缺口" in suggestion, "suggested return reason must name imported hierarchy gaps")
            require("旧通讯模块号" in suggestion, "suggestion must include old accessory field")
            require("新通讯模块号" in suggestion, "suggestion must include new accessory field")
            require("新旧模块照片" in suggestion, "suggestion must include photo evidence field")

            return_response = client.post(
                f"/projects/{project_id}/review/work-orders/{work_order_id}/actions",
                json={"actor": "reviewer", "action": "returned", "note": "", "reason": ""},
            )
            require(return_response.status_code == 200, f"return action failed: {return_response.text}")
            returned = return_response.json()["data"]
            require(returned.get("review_status") == "returned", "work order must be returned")
            require(returned.get("review_reason") == suggestion, "blank return reason must fall back to suggestion")
            history = returned.get("review_history") or []
            require(history and history[-1].get("reason") == suggestion, "review history must store fallback suggestion")
        finally:
            reset_project_drafts(remove_store=True)
            reset_platform_runtime_files()
            configure_project_draft_store_path(None)

    print("[OK] review return reason suggestions are available")


if __name__ == "__main__":
    main()
