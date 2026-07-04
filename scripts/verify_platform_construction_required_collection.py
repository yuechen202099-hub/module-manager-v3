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
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


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


def create_project(client: TestClient) -> str:
    response = client.post(
        "/projects",
        json={
            "name": "construction required collection guard",
            "module_ids": ["progress", "field", "review", "tasks", "delivery"],
            "work_item_schema": {
                "primary_field": {
                    "key": "terminal",
                    "label": "终端",
                    "source": "import",
                    "capture_method": "scan",
                    "required": True,
                    "relation_role": "task_object",
                },
                "aggregate_field": {
                    "key": "station_area",
                    "label": "台区",
                    "source": "import",
                    "capture_method": "manual",
                    "required": True,
                    "relation_role": "aggregate",
                },
                "custom_fields": [
                    {
                        "key": "new_terminal",
                        "label": "新终端",
                        "source": "field_collection",
                        "capture_method": "scan",
                        "required": True,
                        "parent_key": "terminal",
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
                        "parent_key": "terminal",
                        "show_in_construction_panel": True,
                        "relation_role": "accessory_replace_confirm",
                        "options": ["更换", "不更换"],
                    },
                    {
                        "key": "communication_module_no",
                        "label": "新通讯模块号",
                        "source": "field_collection",
                        "capture_method": "scan",
                        "required": False,
                        "parent_key": "terminal",
                        "show_in_construction_panel": True,
                        "relation_role": "accessory_new_device",
                        "required_when": {"field_key": "communication_module_replace_confirm", "equals": "更换"},
                    },
                    {
                        "key": "old_new_module_photo",
                        "label": "新旧模块照片",
                        "data_type": "image",
                        "source": "field_collection",
                        "capture_method": "photo",
                        "required": True,
                        "parent_key": "terminal",
                        "show_in_construction_panel": True,
                        "relation_role": "evidence_photo",
                        "required_when": {"field_key": "communication_module_replace_confirm", "equals": "更换"},
                    },
                    {
                        "key": "after_photo",
                        "label": "改造后照片",
                        "data_type": "image",
                        "source": "field_collection",
                        "capture_method": "photo",
                        "required": True,
                        "parent_key": "terminal",
                        "show_in_construction_panel": True,
                        "relation_role": "evidence_photo",
                    },
                ],
            },
        },
    )
    require(response.status_code == 200, "project creation failed")
    return response.json()["data"]["id"]


def create_work_order(client: TestClient, project_id: str) -> str:
    batch_response = client.post(
        f"/projects/{project_id}/templates/initial_work_orders/import-batches",
        data={"actor": "admin"},
        files={
            "file": (
                "construction-required-collection.xlsx",
                workbook_bytes([["终端", "台区"], ["TERM-001", "台区-01"]]),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    require(batch_response.status_code == 200, "import batch failed")
    task_response = client.post(
        f"/projects/{project_id}/import-batches/{batch_response.json()['data']['job_id']}/work-order-tasks",
        json={"actor": "admin", "mode": "safe_record_only"},
    )
    require(task_response.status_code == 200, "work order task creation failed")
    executed_response = client.post(
        f"/projects/{project_id}/work-order-tasks/{task_response.json()['data']['job_id']}/execute",
        json={"actor": "admin", "mode": "local_platform_store"},
    )
    require(executed_response.status_code == 200, "work order task execution failed")
    construction_response = client.get(f"/projects/{project_id}/construction/work-orders")
    require(construction_response.status_code == 200, "construction work order listing failed")
    items = construction_response.json()["data"]["items"]
    require(len(items) == 1, "expected one construction work order")
    return items[0]["id"]


def main() -> None:
    with TemporaryDirectory() as temp_dir:
        store_path = Path(temp_dir) / "platform-project-drafts.json"
        configure_project_draft_store_path(store_path)
        reset_project_drafts(remove_store=True)
        reset_platform_runtime_files()
        try:
            client = TestClient(app)
            project_id = create_project(client)
            work_order_id = create_work_order(client, project_id)

            cached_response = client.post(
                f"/projects/{project_id}/construction/work-orders/{work_order_id}/collection-draft",
                json={
                    "actor": "installer",
                    "status": "cached",
                    "field_values": {"communication_module_replace_confirm": "更换"},
                    "covered_photo_slots": [],
                    "client_batch_id": "cached-incomplete",
                },
            )
            require(cached_response.status_code == 200, "cached incomplete draft should be allowed")

            incomplete_response = client.post(
                f"/projects/{project_id}/construction/work-orders/{work_order_id}/collection-draft",
                json={
                    "actor": "installer",
                    "status": "submitted",
                    "field_values": {
                        "new_terminal": "TERM-NEW-001",
                        "communication_module_replace_confirm": "更换",
                    },
                    "covered_photo_slots": ["after_photo"],
                    "client_batch_id": "submitted-incomplete",
                },
            )
            require(incomplete_response.status_code == 400, "submitted conditional missing data must be rejected")
            detail = str(incomplete_response.json().get("detail") or "")
            require("新通讯模块号" in detail, "missing conditional field label not reported")
            require("新旧模块照片" in detail, "missing conditional photo label not reported")

            complete_response = client.post(
                f"/projects/{project_id}/construction/work-orders/{work_order_id}/collection-draft",
                json={
                    "actor": "installer",
                    "status": "submitted",
                    "field_values": {
                        "new_terminal": "TERM-NEW-001",
                        "communication_module_replace_confirm": "更换",
                        "communication_module_no": "COMM-001",
                    },
                    "covered_photo_slots": ["old_new_module_photo", "after_photo"],
                    "client_batch_id": "submitted-complete",
                },
            )
            require(complete_response.status_code == 200, "complete conditional collection should submit")
            require(complete_response.json()["data"]["collection_status"] == "submitted", "complete collection did not submit")
        finally:
            reset_project_drafts(remove_store=True)
            reset_platform_runtime_files()
            configure_project_draft_store_path(None)

    print("[OK] platform construction required collection is enforced")


if __name__ == "__main__":
    main()
