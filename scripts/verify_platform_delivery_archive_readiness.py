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
            "name": "delivery archive readiness guard",
            "module_ids": ["progress", "field", "review", "tasks", "delivery"],
            "work_item_schema": {
                "primary_field": {
                    "key": "terminal",
                    "label": "Terminal",
                    "source": "import",
                    "capture_method": "manual",
                    "required": True,
                    "relation_role": "task_object",
                },
                "aggregate_field": {
                    "key": "station_area",
                    "label": "Station area",
                    "source": "import",
                    "capture_method": "manual",
                    "required": True,
                    "relation_role": "aggregate",
                },
                "custom_fields": [
                    {
                        "key": "new_terminal",
                        "label": "New terminal",
                        "source": "field_collection",
                        "capture_method": "scan",
                        "required": True,
                        "parent_key": "terminal",
                        "show_in_construction_panel": True,
                        "relation_role": "replacement_device",
                    },
                    {
                        "key": "communication_module_replace_confirm",
                        "label": "Communication module replacement",
                        "data_type": "enum",
                        "source": "field_collection",
                        "capture_method": "select",
                        "required": True,
                        "parent_key": "terminal",
                        "show_in_construction_panel": True,
                        "relation_role": "accessory_replace_confirm",
                        "options": ["replace", "keep"],
                    },
                    {
                        "key": "communication_module_no",
                        "label": "New communication module",
                        "source": "field_collection",
                        "capture_method": "scan",
                        "required": False,
                        "parent_key": "terminal",
                        "show_in_construction_panel": True,
                        "relation_role": "accessory_new_device",
                        "required_when": {"field_key": "communication_module_replace_confirm", "equals": "replace"},
                    },
                    {
                        "key": "old_new_module_photo",
                        "label": "Old and new module photo",
                        "data_type": "image",
                        "source": "field_collection",
                        "capture_method": "photo",
                        "required": True,
                        "parent_key": "terminal",
                        "show_in_construction_panel": True,
                        "relation_role": "evidence_photo",
                        "required_when": {"field_key": "communication_module_replace_confirm", "equals": "replace"},
                    },
                    {
                        "key": "after_photo",
                        "label": "After photo",
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


def create_work_orders(client: TestClient, project_id: str) -> dict[str, str]:
    rows = [
        ["Terminal", "Station area"],
        ["TERM-READY", "A"],
        ["TERM-PENDING", "A"],
        ["TERM-RETURNED", "B"],
        ["TERM-GAP", "B"],
        ["TERM-NOTREADY", "C"],
        ["TERM-EXCEPTION", "C"],
    ]
    batch_response = client.post(
        f"/projects/{project_id}/templates/initial_work_orders/import-batches",
        data={"actor": "admin"},
        files={
            "file": (
                "delivery-archive-readiness.xlsx",
                workbook_bytes(rows),
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
    require(len(items) == 6, "expected six construction work orders")
    return {item["primary_value"]: item["id"] for item in items}


def submit_complete_collection(client: TestClient, project_id: str, work_order_id: str, suffix: str) -> None:
    response = client.post(
        f"/projects/{project_id}/construction/work-orders/{work_order_id}/collection-draft",
        json={
            "actor": "installer",
            "status": "submitted",
            "field_values": {
                "new_terminal": f"NEW-{suffix}",
                "communication_module_replace_confirm": "replace",
                "communication_module_no": f"COMM-{suffix}",
            },
            "covered_photo_slots": ["old_new_module_photo", "after_photo"],
            "client_batch_id": f"complete-{suffix}",
        },
    )
    require(response.status_code == 200, f"complete collection failed for {suffix}")


def submit_incomplete_cached_collection(client: TestClient, project_id: str, work_order_id: str) -> None:
    response = client.post(
        f"/projects/{project_id}/construction/work-orders/{work_order_id}/collection-draft",
        json={
            "actor": "installer",
            "status": "cached",
            "field_values": {"communication_module_replace_confirm": "replace"},
            "covered_photo_slots": [],
            "client_batch_id": "evidence-gap",
        },
    )
    require(response.status_code == 200, "incomplete cached collection should be allowed")


def review_action(client: TestClient, project_id: str, work_order_id: str, action: str) -> None:
    response = client.post(
        f"/projects/{project_id}/review/work-orders/{work_order_id}/actions",
        json={"actor": "reviewer", "action": action, "note": action},
    )
    require(response.status_code == 200, f"{action} review action failed")


def main() -> None:
    with TemporaryDirectory() as temp_dir:
        configure_project_draft_store_path(Path(temp_dir) / "platform-project-drafts.json")
        reset_project_drafts(remove_store=True)
        reset_platform_runtime_files()
        try:
            client = TestClient(app)
            project_id = create_project(client)
            work_order_ids = create_work_orders(client, project_id)

            submit_complete_collection(client, project_id, work_order_ids["TERM-READY"], "READY")
            review_action(client, project_id, work_order_ids["TERM-READY"], "approved")

            submit_complete_collection(client, project_id, work_order_ids["TERM-PENDING"], "PENDING")

            submit_complete_collection(client, project_id, work_order_ids["TERM-RETURNED"], "RETURNED")
            review_action(client, project_id, work_order_ids["TERM-RETURNED"], "returned")

            submit_incomplete_cached_collection(client, project_id, work_order_ids["TERM-GAP"])

            submit_complete_collection(client, project_id, work_order_ids["TERM-EXCEPTION"], "EXCEPTION")
            review_action(client, project_id, work_order_ids["TERM-EXCEPTION"], "exception")

            response = client.get(f"/projects/{project_id}/delivery/archive-readiness")
            require(response.status_code == 200, "delivery archive readiness route failed")
            payload = response.json()["data"]

            expected_counts = {
                "total": 6,
                "ready_for_archive": 1,
                "approved_archive": 1,
                "pending_review": 1,
                "returned_rework": 1,
                "evidence_gap": 1,
                "not_ready": 1,
                "exception": 1,
                "blocked": 5,
            }
            for key, expected in expected_counts.items():
                require(payload.get(key) == expected, f"{key} expected {expected}, got {payload.get(key)}")

            require(payload.get("ready") is False, "mixed project must not be ready for archive")
            require(payload.get("status") == "blocked", "mixed project status must be blocked")
            for action in (
                "archive_approved_work_orders",
                "review_pending_work_orders",
                "resolve_returned_rework",
                "complete_evidence",
                "collect_not_ready_work_orders",
                "handle_exceptions",
            ):
                require(action in payload.get("next_actions", []), f"missing next action {action}")
            blocker_reasons = {item.get("reason") for item in payload.get("blockers", []) if isinstance(item, dict)}
            for reason in ("pending_review", "returned_rework", "evidence_gap", "not_ready", "exception"):
                require(reason in blocker_reasons, f"missing blocker reason {reason}")
        finally:
            reset_project_drafts(remove_store=True)
            reset_platform_runtime_files()
            configure_project_draft_store_path(None)

    print("[OK] platform delivery archive readiness is summarized")


if __name__ == "__main__":
    main()
