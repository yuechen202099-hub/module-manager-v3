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
                    "name": "terminal display field guard",
                    "module_ids": ["progress", "field", "review"],
                    "work_item_schema": {
                        "primary_field": {
                            "key": "terminal_no",
                            "label": "Terminal",
                            "source": "import",
                            "capture_method": "manual",
                            "required": True,
                            "show_in_construction_panel": True,
                        },
                        "aggregate_field": {
                            "key": "area_no",
                            "label": "Area",
                            "source": "import",
                            "capture_method": "manual",
                            "required": True,
                            "show_in_construction_panel": True,
                        },
                        "custom_fields": [
                            {
                                "key": "terminal_address",
                                "label": "Terminal address",
                                "source": "import",
                                "capture_method": "manual",
                                "required": True,
                                "parent_key": "terminal_no",
                                "show_in_construction_panel": True,
                            },
                            {
                                "key": "manufacturer_name",
                                "label": "Manufacturer",
                                "source": "import",
                                "capture_method": "manual",
                                "required": False,
                                "parent_key": "terminal_no",
                                "show_in_construction_panel": False,
                            },
                            {
                                "key": "communication_module_no",
                                "label": "Communication module",
                                "source": "field_collection",
                                "capture_method": "scan",
                                "required": True,
                                "parent_key": "terminal_no",
                                "show_in_construction_panel": True,
                            },
                            {
                                "key": "new_sim_card_no",
                                "label": "New SIM card",
                                "source": "field_collection",
                                "capture_method": "manual",
                                "required": False,
                                "parent_key": "terminal_no",
                                "show_in_construction_panel": False,
                            },
                            {
                                "key": "after_photo",
                                "label": "After photo",
                                "data_type": "image",
                                "source": "field_collection",
                                "capture_method": "photo",
                                "required": True,
                                "parent_key": "terminal_no",
                                "show_in_construction_panel": True,
                            },
                        ],
                    },
                },
            )
            require(response.status_code == 200, "project creation failed")
            project = response.json()["data"]
            schema = project.get("work_item_schema", {})
            custom_by_key = {field.get("key"): field for field in schema.get("custom_fields", [])}
            require(custom_by_key.get("terminal_address", {}).get("show_in_construction_panel") is True, "display flag not persisted for core field")
            require(custom_by_key.get("manufacturer_name", {}).get("show_in_construction_panel") is False, "hidden core field flag not persisted")

            construction_response = client.get(f"/projects/{project['id']}/construction/work-orders")
            require(construction_response.status_code == 200, "construction route failed")
            field_schema = construction_response.json()["data"].get("field_schema", {})
            display_keys = {field.get("key") for field in field_schema.get("display_fields", [])}
            construction_keys = {field.get("key") for field in field_schema.get("construction_fields", [])}
            photo_keys = {field.get("key") for field in field_schema.get("photo_slots", [])}
            require({"terminal_no", "area_no", "terminal_address"}.issubset(display_keys), "display fields missing task core context")
            require("manufacturer_name" not in display_keys, "hidden core field leaked into display fields")
            require("communication_module_no" in construction_keys, "visible attached device field missing from construction fields")
            require("new_sim_card_no" not in construction_keys, "hidden attached device field leaked into construction fields")
            require("after_photo" in photo_keys, "visible photo slot missing from photo slots")
        finally:
            reset_project_drafts(remove_store=True)
            configure_project_draft_store_path(None)

    print("[OK] platform construction display fields are separated from collection fields")


if __name__ == "__main__":
    main()
