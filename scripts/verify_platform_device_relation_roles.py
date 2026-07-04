from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "v2-api"
sys.path.insert(0, str(API_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.platform.catalog import (  # noqa: E402
    _normalize_work_item_schema,
    configure_project_draft_store_path,
    get_project_definition,
    reset_project_drafts,
)


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
                    "name": "device relation roles",
                    "module_ids": ["progress", "field", "review"],
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
                                "key": "old_device_no",
                                "label": "Old terminal",
                                "source": "field_collection",
                                "capture_method": "scan",
                                "required": True,
                                "parent_key": "terminal_no",
                                "show_in_construction_panel": True,
                                "relation_role": "old_device",
                            },
                            {
                                "key": "new_terminal_no",
                                "label": "New terminal",
                                "source": "field_collection",
                                "capture_method": "scan",
                                "required": True,
                                "parent_key": "terminal_no",
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
                        ],
                    },
                },
            )
            require(response.status_code == 200, "project creation failed")
            project = response.json()["data"]
            schema = project.get("work_item_schema", {})
            require(
                schema.get("primary_field", {}).get("relation_role") == "task_object",
                "primary field relation_role not persisted",
            )
            custom_by_key = {
                field.get("key"): field
                for field in schema.get("custom_fields", [])
            }
            require(
                custom_by_key.get("old_device_no", {}).get("relation_role") == "old_device",
                "old device relation_role not persisted",
            )
            require(
                custom_by_key.get("old_device_no", {}).get("parent_key") == "terminal_no",
                "old device hierarchy parent not persisted",
            )
            require(
                custom_by_key.get("new_terminal_no", {}).get("relation_role") == "replacement_device",
                "new terminal replacement_device relation_role not persisted",
            )
            require(
                custom_by_key.get("new_terminal_no", {}).get("parent_key") == "terminal_no",
                "new terminal hierarchy parent not persisted",
            )
            require(
                custom_by_key.get("new_terminal_no", {}).get("required") is True,
                "new terminal must stay required for terminal replacement",
            )
            require(
                custom_by_key.get("communication_module_replace_confirm", {}).get("relation_role")
                == "accessory_replace_confirm",
                "replacement confirmation relation_role not persisted",
            )
            require(
                custom_by_key.get("communication_module_replace_confirm", {}).get("parent_key") == "terminal_no",
                "replacement confirmation hierarchy parent not persisted",
            )
            require(
                custom_by_key.get("communication_module_no", {}).get("relation_role") == "accessory_new_device",
                "new accessory device relation_role not persisted",
            )
            require(
                custom_by_key.get("communication_module_no", {}).get("parent_key") == "terminal_no",
                "new accessory device hierarchy parent not persisted",
            )

            construction_response = client.get(f"/projects/{project['id']}/construction/work-orders")
            require(construction_response.status_code == 200, "construction route failed")
            field_schema = construction_response.json()["data"].get("field_schema", {})
            construction_by_key = {
                field.get("key"): field
                for field in field_schema.get("construction_fields", [])
            }
            require(
                construction_by_key.get("communication_module_no", {}).get("relation_role")
                == "accessory_new_device",
                "construction schema did not expose relation_role",
            )
            require(
                construction_by_key.get("new_terminal_no", {}).get("relation_role") == "replacement_device",
                "construction schema did not expose main replacement device relation_role",
            )
            require(
                construction_by_key.get("new_terminal_no", {}).get("parent_key") == "terminal_no",
                "construction schema did not expose main replacement device parent",
            )

            replacement_definition = get_project_definition("replacement-project")
            replacement_schema = _normalize_work_item_schema(replacement_definition.work_item_schema)
            replacement_custom_by_key = {
                field.get("key"): field
                for field in replacement_schema.get("custom_fields", [])
            }
            require(
                replacement_schema.get("primary_field", {}).get("key") == "meter_no",
                "default module replacement project primary field must be meter_no",
            )
            require(
                replacement_schema.get("primary_field", {}).get("relation_role") == "task_object",
                "default module replacement project primary field must be task_object",
            )
            require(
                replacement_schema.get("aggregate_field", {}).get("relation_role") == "aggregate",
                "default module replacement project aggregate field must be aggregate",
            )
            require(
                replacement_custom_by_key.get("module_asset_no", {}).get("parent_key") == "meter_no",
                "default module replacement module must be attached under meter_no",
            )
            require(
                replacement_custom_by_key.get("module_asset_no", {}).get("relation_role") == "accessory_new_device",
                "default module replacement module must be an accessory_new_device",
            )
            require(
                replacement_custom_by_key.get("collector_replace_confirm", {}).get("parent_key") == "meter_no",
                "default module replacement collector confirmation must be attached under meter_no",
            )
            require(
                replacement_custom_by_key.get("collector_replace_confirm", {}).get("relation_role")
                == "accessory_replace_confirm",
                "default module replacement collector confirmation must be accessory_replace_confirm",
            )
            require(
                replacement_custom_by_key.get("collector_no", {}).get("required_when", {}).get("field_key")
                == "collector_replace_confirm",
                "default module replacement new collector must depend on collector confirmation",
            )
        finally:
            reset_project_drafts(remove_store=True)
            configure_project_draft_store_path(None)

    print("[OK] platform device relation roles are preserved")


if __name__ == "__main__":
    main()
