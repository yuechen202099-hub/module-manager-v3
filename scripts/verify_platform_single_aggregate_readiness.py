from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "v2-api"
sys.path.insert(0, str(API_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.platform.catalog import configure_project_draft_store_path, reset_project_drafts  # noqa: E402
from app.services.platform.readiness import _single_aggregate_field_check  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"[FAIL] {message}")


def main() -> None:
    invalid_check = _single_aggregate_field_check(
        {
            "primary_field": {"key": "terminal_no", "label": "Terminal", "relation_role": "task_object"},
            "aggregate_field": {"key": "area_no", "label": "Area", "relation_role": "aggregate"},
            "custom_fields": [
                {"key": "region_name", "label": "Region", "relation_role": "aggregate"},
                {"key": "manufacturer_name", "label": "Manufacturer", "relation_role": "task_detail"},
            ],
        }
    )
    require(invalid_check.get("id") == "single_aggregate_field", "single aggregate readiness check id missing")
    require(invalid_check.get("status") == "failed", "extra custom aggregate field must fail readiness")
    require(
        invalid_check.get("evidence", {}).get("extra_aggregate_keys") == ["region_name"],
        "single aggregate readiness must list extra aggregate keys",
    )
    require(invalid_check.get("action") == "fix_aggregate_field", "single aggregate readiness action drifted")

    with TemporaryDirectory() as temp_dir:
        store_path = Path(temp_dir) / "platform-project-drafts.json"
        configure_project_draft_store_path(store_path)
        reset_project_drafts(remove_store=True)
        try:
            client = TestClient(app)
            response = client.post(
                "/projects",
                json={
                    "name": "single aggregate readiness route",
                    "module_ids": ["progress", "field", "review", "tasks", "delivery"],
                    "work_item_schema": {
                        "primary_field": {
                            "key": "terminal_no",
                            "label": "Terminal",
                            "source": "import",
                            "capture_method": "manual",
                            "required": True,
                            "relation_role": "task_object",
                        },
                        "aggregate_field": {
                            "key": "area_no",
                            "label": "Area",
                            "source": "import",
                            "capture_method": "manual",
                            "required": True,
                            "relation_role": "aggregate",
                        },
                        "custom_fields": [
                            {
                                "key": "old_terminal",
                                "label": "Old terminal",
                                "source": "field_collection",
                                "capture_method": "scan",
                                "required": True,
                                "parent_key": "terminal_no",
                                "relation_role": "old_device",
                            },
                            {
                                "key": "new_terminal",
                                "label": "New terminal",
                                "source": "field_collection",
                                "capture_method": "scan",
                                "required": True,
                                "parent_key": "terminal_no",
                                "relation_role": "replacement_device",
                            },
                            {
                                "key": "communication_module_replace_confirm",
                                "label": "Communication module replace confirm",
                                "data_type": "enum",
                                "source": "field_collection",
                                "capture_method": "select",
                                "required": True,
                                "parent_key": "terminal_no",
                                "relation_role": "accessory_replace_confirm",
                                "options": ["更换", "不更换"],
                            },
                            {
                                "key": "communication_module_no",
                                "label": "Communication module",
                                "source": "field_collection",
                                "capture_method": "scan",
                                "required": False,
                                "parent_key": "terminal_no",
                                "relation_role": "accessory_new_device",
                                "required_when": {
                                    "field_key": "communication_module_replace_confirm",
                                    "equals": "更换",
                                },
                            },
                            {
                                "key": "before_photo",
                                "label": "Before photo",
                                "data_type": "image",
                                "source": "field_collection",
                                "capture_method": "photo",
                                "required": True,
                                "parent_key": "terminal_no",
                                "relation_role": "evidence_photo",
                            },
                            {
                                "key": "after_photo",
                                "label": "After photo",
                                "data_type": "image",
                                "source": "field_collection",
                                "capture_method": "photo",
                                "required": True,
                                "parent_key": "terminal_no",
                                "relation_role": "evidence_photo",
                            },
                        ],
                    },
                },
            )
            require(response.status_code == 200, "project creation failed")
            project_id = response.json()["data"]["id"]
            readiness_response = client.get(f"/projects/{project_id}/readiness")
            require(readiness_response.status_code == 200, "readiness route failed")
            checks = readiness_response.json()["data"].get("checks", [])
            check_by_id = {check.get("id"): check for check in checks}
            route_check = check_by_id.get("single_aggregate_field")
            require(route_check is not None, "readiness route must include single aggregate check")
            require(route_check.get("status") == "passed", "valid single aggregate project must pass readiness")
        finally:
            reset_project_drafts(remove_store=True)
            configure_project_draft_store_path(None)

    print("[OK] platform single aggregate readiness is exposed")


if __name__ == "__main__":
    main()
