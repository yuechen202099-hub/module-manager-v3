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


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"[FAIL] {message}")


def main() -> None:
    with TemporaryDirectory() as temp_dir:
        store_path = Path(temp_dir) / "platform-project-drafts.json"
        configure_project_draft_store_path(store_path)
        reset_project_drafts(remove_store=True)
        try:
            client = TestClient(app)
            response = client.post(
                "/projects",
                json={
                    "name": "conditional required guard",
                    "module_ids": ["progress", "field", "review"],
                    "work_item_schema": {
                        "primary_field": {
                            "key": "terminal_no",
                            "label": "Terminal",
                            "source": "import",
                            "capture_method": "manual",
                            "required": True,
                        },
                        "aggregate_field": {
                            "key": "area_no",
                            "label": "Area",
                            "source": "import",
                            "capture_method": "manual",
                            "required": True,
                        },
                        "custom_fields": [
                            {
                                "key": "communication_module_replace_confirm",
                                "label": "Communication module replacement",
                                "data_type": "enum",
                                "source": "field_collection",
                                "capture_method": "select",
                                "required": True,
                                "parent_key": "terminal_no",
                                "show_in_construction_panel": True,
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
                                "required": False,
                                "parent_key": "terminal_no",
                                "show_in_construction_panel": True,
                                "required_when": {
                                    "field_key": "communication_module_replace_confirm",
                                    "equals": "更换",
                                },
                            },
                        ],
                    },
                },
            )
            require(response.status_code == 200, "project creation failed")
            project = response.json()["data"]
            custom_by_key = {
                field.get("key"): field
                for field in project.get("work_item_schema", {}).get("custom_fields", [])
            }
            require(
                custom_by_key.get("communication_module_no", {}).get("required_when", {}).get("field_key")
                == "communication_module_replace_confirm",
                "conditional field required_when not persisted",
            )
            require(
                custom_by_key.get("old_new_module_photo", {}).get("required_when", {}).get("equals")
                == "更换",
                "conditional photo required_when not persisted",
            )

            construction_response = client.get(f"/projects/{project['id']}/construction/work-orders")
            require(construction_response.status_code == 200, "construction route failed")
            field_schema = construction_response.json()["data"].get("field_schema", {})
            construction_by_key = {
                field.get("key"): field
                for field in field_schema.get("construction_fields", [])
            }
            photo_by_key = {
                field.get("key"): field
                for field in field_schema.get("photo_slots", [])
            }
            require(
                construction_by_key.get("communication_module_no", {}).get("required_when", {}).get("field_key")
                == "communication_module_replace_confirm",
                "construction field schema did not expose required_when",
            )
            require(
                photo_by_key.get("old_new_module_photo", {}).get("required_when", {}).get("equals")
                == "更换",
                "construction photo schema did not expose required_when",
            )
        finally:
            reset_project_drafts(remove_store=True)
            configure_project_draft_store_path(None)

    print("[OK] platform conditional required fields are preserved")


if __name__ == "__main__":
    main()
