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


def create_terminal_project(client: TestClient) -> str:
    response = client.post(
        "/projects",
        json={
            "name": "external completed hierarchy validation",
            "module_ids": ["progress", "field", "review", "tasks", "delivery"],
            "work_item_schema": {
                "primary_field": {
                    "key": "terminal_no",
                    "label": "Terminal",
                    "source": "import",
                    "capture_method": "manual",
                    "data_type": "text",
                    "required": True,
                    "relation_role": "task_object",
                },
                "aggregate_field": {
                    "key": "area_no",
                    "label": "Area",
                    "source": "import",
                    "capture_method": "manual",
                    "data_type": "text",
                    "required": True,
                    "relation_role": "aggregate",
                },
                "custom_fields": [
                    {
                        "key": "comm_replace_confirm",
                        "label": "Communication module replace",
                        "data_type": "enum",
                        "source": "field_collection",
                        "capture_method": "select",
                        "required": True,
                        "parent_key": "terminal_no",
                        "show_in_construction_panel": True,
                        "relation_role": "accessory_replace_confirm",
                        "options": ["replace", "keep"],
                    },
                    {
                        "key": "old_comm_module",
                        "label": "Old communication module",
                        "data_type": "text",
                        "source": "field_collection",
                        "capture_method": "scan",
                        "required": False,
                        "parent_key": "terminal_no",
                        "show_in_construction_panel": True,
                        "relation_role": "old_device",
                        "required_when": {"field_key": "comm_replace_confirm", "equals": "replace"},
                    },
                    {
                        "key": "new_comm_module",
                        "label": "New communication module",
                        "data_type": "text",
                        "source": "field_collection",
                        "capture_method": "scan",
                        "required": False,
                        "parent_key": "terminal_no",
                        "show_in_construction_panel": True,
                        "relation_role": "accessory_new_device",
                        "required_when": {"field_key": "comm_replace_confirm", "equals": "replace"},
                    },
                    {
                        "key": "comm_photo",
                        "label": "Communication module photo",
                        "data_type": "image",
                        "source": "field_collection",
                        "capture_method": "photo",
                        "required": False,
                        "parent_key": "terminal_no",
                        "show_in_construction_panel": True,
                        "relation_role": "evidence_photo",
                        "required_when": {"field_key": "comm_replace_confirm", "equals": "replace"},
                    },
                ],
            },
        },
    )
    require(response.status_code == 200, f"project creation failed: {response.text}")
    return response.json()["data"]["id"]


def validate_rows(client: TestClient, project_id: str, rows: list[list[str]]) -> dict:
    response = client.post(
        f"/projects/{project_id}/templates/external_completed/validate",
        files={
            "file": (
                "external-completed.xlsx",
                workbook_bytes(rows),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    require(response.status_code == 200, f"template validation request failed: {response.text}")
    return response.json()["data"]


def main() -> None:
    headers = [
        "Terminal",
        "Area",
        "Communication module replace",
        "Old communication module",
        "New communication module",
        "Communication module photo",
    ]
    with TemporaryDirectory() as temp_dir:
        configure_project_draft_store_path(Path(temp_dir) / "platform-project-drafts.json")
        reset_project_drafts(remove_store=True)
        try:
            client = TestClient(app)
            project_id = create_terminal_project(client)

            missing_report = validate_rows(
                client,
                project_id,
                [headers, ["TERM-001", "Area-01", "replace", "", "", ""]],
            )
            require(missing_report["status"] == "warning", "missing conditional evidence should warn but not block")
            missing_items = [
                item
                for item in missing_report["items"]
                if item.get("code") == "missing_conditional_field"
            ]
            missing_labels = {item.get("field_label") for item in missing_items}
            require(len(missing_items) >= 3, "all triggered conditional child fields must be reported")
            require("Old communication module" in missing_labels, "missing old module warning not reported")
            require("New communication module" in missing_labels, "missing new module warning not reported")
            require("Communication module photo" in missing_labels, "missing module photo warning not reported")

            keep_report = validate_rows(
                client,
                project_id,
                [headers, ["TERM-002", "Area-01", "keep", "", "", ""]],
            )
            keep_codes = {item.get("code") for item in keep_report["items"]}
            require("missing_conditional_field" not in keep_codes, "untriggered conditional fields must not warn")
        finally:
            reset_project_drafts(remove_store=True)
            configure_project_draft_store_path(None)

    print("[OK] external completed template hierarchy validation is enforced")


if __name__ == "__main__":
    main()
