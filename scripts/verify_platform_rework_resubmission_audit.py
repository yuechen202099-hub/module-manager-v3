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
NEW_TERMINAL = "\u65b0\u7ec8\u7aef\u53f7"
REWORK_SUBMITTED_NOTE = "\u8fd4\u5de5\u8865\u91c7\u540e\u91cd\u65b0\u63d0\u4ea4\u5ba1\u9605"
REWORK_SUBMITTED_REASON = "returned_rework_resubmitted"


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


def create_project(client: TestClient) -> str:
    response = client.post(
        "/projects",
        json={
            "name": "rework resubmission audit",
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
                        "label": NEW_TERMINAL,
                        "data_type": "text",
                        "source": "field_collection",
                        "capture_method": "scan",
                        "required": True,
                        "parent_key": "terminal_no",
                        "show_in_construction_panel": True,
                        "relation_role": "replacement_device",
                    }
                ],
            },
        },
    )
    require(response.status_code == 200, f"project creation failed: {response.text}")
    return response.json()["data"]["id"]


def create_work_order(client: TestClient, project_id: str) -> str:
    batch_response = client.post(
        f"/projects/{project_id}/templates/initial_work_orders/import-batches",
        data={"actor": "admin"},
        files={
            "file": (
                "rework-resubmission-audit.xlsx",
                workbook_bytes([[TERMINAL, AREA], ["TERM-001", "\u53f0\u533a-01"]]),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    require(batch_response.status_code == 200, f"import batch failed: {batch_response.text}")
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
    construction_response = client.get(f"/projects/{project_id}/construction/work-orders")
    require(construction_response.status_code == 200, f"construction listing failed: {construction_response.text}")
    items = construction_response.json()["data"].get("items", [])
    require(len(items) == 1, "expected one construction work order")
    return items[0]["id"]


def submit_collection(client: TestClient, project_id: str, work_order_id: str, new_terminal_no: str) -> dict:
    response = client.post(
        f"/projects/{project_id}/construction/work-orders/{work_order_id}/collection-draft",
        json={
            "actor": "constructor",
            "status": "submitted",
            "field_values": {"new_terminal_no": new_terminal_no},
            "covered_photo_slots": [],
            "client_batch_id": f"batch-{new_terminal_no}",
        },
    )
    require(response.status_code == 200, f"collection submit failed: {response.text}")
    return response.json()["data"]


def main() -> None:
    with TemporaryDirectory() as temp_dir:
        configure_project_draft_store_path(Path(temp_dir) / "platform-project-drafts.json")
        reset_project_drafts(remove_store=True)
        reset_platform_runtime_files()
        try:
            client = TestClient(app)
            project_id = create_project(client)
            work_order_id = create_work_order(client, project_id)

            first_submit = submit_collection(client, project_id, work_order_id, "TERM-NEW-001")
            require(first_submit.get("review_status") == "pending_review", "first submit must enter pending review")

            return_response = client.post(
                f"/projects/{project_id}/review/work-orders/{work_order_id}/actions",
                json={
                    "actor": "reviewer",
                    "action": "returned",
                    "note": "\u65b0\u7ec8\u7aef\u53f7\u9700\u590d\u6838",
                    "reason": "\u65b0\u7ec8\u7aef\u53f7\u9700\u590d\u6838",
                },
            )
            require(return_response.status_code == 200, f"return action failed: {return_response.text}")
            returned = return_response.json()["data"]
            require(returned.get("review_status") == "returned", "review action must return the work order")

            second_submit = submit_collection(client, project_id, work_order_id, "TERM-NEW-002")
            require(second_submit.get("review_status") == "pending_review", "rework submit must re-enter pending review")
            history = second_submit.get("review_history") or []
            require(any(event.get("action") == "returned" for event in history), "returned history must be preserved")
            resubmissions = [event for event in history if event.get("action") == "rework_submitted"]
            require(resubmissions, "rework submit must append a rework_submitted history event")
            latest_resubmission = resubmissions[-1]
            require(latest_resubmission.get("actor") == "constructor", "resubmission actor must be the constructor")
            require(latest_resubmission.get("note") == REWORK_SUBMITTED_NOTE, "resubmission note must be operator-readable")
            require(latest_resubmission.get("reason") == REWORK_SUBMITTED_REASON, "resubmission reason must be machine-readable")
        finally:
            reset_project_drafts(remove_store=True)
            reset_platform_runtime_files()
            configure_project_draft_store_path(None)

    print("[OK] platform rework resubmission audit trail is available")


if __name__ == "__main__":
    main()
