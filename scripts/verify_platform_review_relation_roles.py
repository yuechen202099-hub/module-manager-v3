from __future__ import annotations

import sys
import shutil
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "v2-api"
sys.path.insert(0, str(API_ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import Workbook  # noqa: E402

from app.main import app  # noqa: E402
from app.services.platform.catalog import configure_project_draft_store_path, reset_project_drafts  # noqa: E402
from app.services.platform import templates as platform_templates  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"[FAIL] {message}")


def workbook_bytes(rows: list[list[str]]) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


def reset_project_template_import_state(*, remove_store: bool = False) -> None:
    with platform_templates._IMPORT_BATCHES_LOCK:
        platform_templates._IMPORT_BATCHES.clear()
        platform_templates._IMPORT_BATCHES_LOADED = False
    with platform_templates._WORK_ORDER_TASKS_LOCK:
        platform_templates._WORK_ORDER_TASKS.clear()
        platform_templates._WORK_ORDER_TASKS_LOADED = False
    with platform_templates._PLATFORM_WORK_ORDERS_LOCK:
        platform_templates._PLATFORM_WORK_ORDERS.clear()
        platform_templates._PLATFORM_WORK_ORDERS_LOADED = False
    if not remove_store:
        return
    for path in (
        platform_templates._import_batches_store_path(),
        platform_templates._work_order_tasks_store_path(),
        platform_templates._platform_work_orders_store_path(),
    ):
        path.unlink(missing_ok=True)
    shutil.rmtree(platform_templates._platform_photo_storage_root(), ignore_errors=True)


def main() -> None:
    with TemporaryDirectory() as temp_dir:
        store_path = Path(temp_dir) / "platform-project-drafts.json"
        configure_project_draft_store_path(store_path)
        reset_project_drafts(remove_store=True)
        reset_project_template_import_state(remove_store=True)
        try:
            client = TestClient(app)
            project_response = client.post(
                "/projects",
                json={
                    "name": f"review relation roles {uuid4()}",
                    "module_ids": ["progress", "field", "review"],
                    "work_item_schema": {
                        "primary_field": {
                            "key": "terminal_no",
                            "label": "Terminal",
                            "source": "import",
                            "required": True,
                            "relation_role": "task_object",
                        },
                        "aggregate_field": {
                            "key": "area_no",
                            "label": "Area",
                            "source": "import",
                            "required": True,
                            "relation_role": "aggregate",
                        },
                        "custom_fields": [
                            {
                                "key": "terminal_address",
                                "label": "Terminal address",
                                "source": "import",
                                "required": True,
                                "parent_key": "terminal_no",
                                "relation_role": "task_detail",
                            },
                            {
                                "key": "communication_module_replace_confirm",
                                "label": "Communication module replacement",
                                "data_type": "enum",
                                "source": "field_collection",
                                "capture_method": "select",
                                "required": True,
                                "parent_key": "terminal_no",
                                "show_in_construction_panel": True,
                                "relation_role": "accessory_replace_confirm",
                                "options": ["更换", "不更换", "待确认"],
                            },
                            {
                                "key": "communication_module_no",
                                "label": "New communication module",
                                "source": "field_collection",
                                "capture_method": "scan",
                                "required": False,
                                "parent_key": "terminal_no",
                                "show_in_construction_panel": True,
                                "relation_role": "accessory_new_device",
                                "required_when": {
                                    "field_key": "communication_module_replace_confirm",
                                    "equals": "更换",
                                },
                            },
                            {
                                "key": "old_new_module_photo",
                                "label": "Old and new module photo",
                                "data_type": "image",
                                "source": "field_collection",
                                "capture_method": "photo",
                                "required": True,
                                "parent_key": "terminal_no",
                                "show_in_construction_panel": True,
                                "relation_role": "evidence_photo",
                            },
                        ],
                    },
                },
            )
            require(project_response.status_code == 200, "project creation failed")
            project_id = project_response.json()["data"]["id"]

            batch_response = client.post(
                f"/projects/{project_id}/templates/initial_work_orders/import-batches",
                data={"actor": "admin"},
                files={
                    "file": (
                        "review-relation-roles.xlsx",
                        workbook_bytes([["Terminal", "Area", "Terminal address"], ["TT-REVIEW-001", "Area-01", "Room 1"]]),
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
            work_orders = construction_response.json()["data"]["items"]
            require(len(work_orders) == 1, "expected one work order")
            work_order_id = work_orders[0]["id"]

            collection_response = client.post(
                f"/projects/{project_id}/construction/work-orders/{work_order_id}/collection-draft",
                json={
                    "actor": "installer",
                    "status": "submitted",
                    "field_values": {
                        "communication_module_replace_confirm": "更换",
                        "communication_module_no": "COMM-001",
                    },
                    "covered_photo_slots": ["old_new_module_photo"],
                    "client_batch_id": "review-relation-roles",
                },
            )
            require(collection_response.status_code == 200, "collection draft submission failed")

            review_response = client.get(f"/projects/{project_id}/review/work-orders")
            require(review_response.status_code == 200, "review work order listing failed")
            review_payload = review_response.json()["data"]
            review_items = review_payload.get("items", [])
            require(len(review_items) == 1, "expected one review work order")
            field_by_key = {field.get("key"): field for field in review_items[0].get("field_reviews", [])}
            photo_by_key = {slot.get("key"): slot for slot in review_items[0].get("photo_slot_reviews", [])}
            require(
                field_by_key.get("communication_module_replace_confirm", {}).get("relation_role")
                == "accessory_replace_confirm",
                "review field relation_role not exposed",
            )
            require(
                field_by_key.get("communication_module_no", {}).get("relation_role") == "accessory_new_device",
                "review new device relation_role not exposed",
            )
            require(
                photo_by_key.get("old_new_module_photo", {}).get("relation_role") == "evidence_photo",
                "review photo relation_role not exposed",
            )
        finally:
            reset_project_template_import_state(remove_store=True)
            reset_project_drafts(remove_store=True)
            configure_project_draft_store_path(None)

    print("[OK] platform review relation roles are preserved")


if __name__ == "__main__":
    main()
