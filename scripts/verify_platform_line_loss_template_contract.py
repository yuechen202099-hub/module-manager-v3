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


LINE_LOSS_SCHEMA = {
    "primary_field": {
        "key": "station_area_no",
        "label": "Station area",
        "data_type": "text",
        "source": "import",
        "capture_method": "manual",
        "required": True,
        "show_in_construction_panel": True,
        "relation_role": "task_object",
    },
    "aggregate_field": {
        "key": "power_supply_unit",
        "label": "Power supply unit",
        "data_type": "text",
        "source": "import",
        "capture_method": "manual",
        "required": True,
        "show_in_construction_panel": True,
        "relation_role": "aggregate",
    },
    "custom_fields": [
        {
            "key": "master_meter_no",
            "label": "Master meter",
            "data_type": "text",
            "source": "import",
            "capture_method": "manual",
            "required": True,
            "parent_key": "station_area_no",
            "show_in_construction_panel": True,
            "relation_role": "task_detail",
        },
        {
            "key": "user_no",
            "label": "User",
            "data_type": "text",
            "source": "import",
            "capture_method": "manual",
            "required": True,
            "parent_key": "station_area_no",
            "show_in_construction_panel": True,
            "relation_role": "task_detail",
        },
        {
            "key": "line_loss_issue_type",
            "label": "Line loss issue type",
            "data_type": "enum",
            "source": "field_collection",
            "capture_method": "select",
            "required": True,
            "parent_key": "station_area_no",
            "show_in_construction_panel": True,
            "options": ["meter mismatch", "wiring issue", "suspected theft", "other"],
            "relation_role": "supporting_field",
        },
        {
            "key": "master_meter_photo",
            "label": "Master meter photo",
            "data_type": "image",
            "source": "field_collection",
            "capture_method": "photo",
            "required": True,
            "parent_key": "station_area_no",
            "show_in_construction_panel": True,
            "relation_role": "evidence_photo",
        },
        {
            "key": "user_meter_sample_photo",
            "label": "User meter sample photo",
            "data_type": "image",
            "source": "field_collection",
            "capture_method": "photo",
            "required": True,
            "parent_key": "station_area_no",
            "show_in_construction_panel": True,
            "relation_role": "evidence_photo",
        },
        {
            "key": "site_check_note",
            "label": "Site check note",
            "data_type": "text",
            "source": "field_collection",
            "capture_method": "manual",
            "required": False,
            "parent_key": "station_area_no",
            "show_in_construction_panel": True,
            "relation_role": "supporting_field",
        },
    ],
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"[FAIL] {message}")


def template_headers(preview: dict, template_type: str) -> list[str]:
    for template in preview.get("templates", []):
        if template.get("template_type") == template_type:
            return [str(header) for header in template.get("headers", [])]
    return []


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
                    "name": "line loss investigation",
                    "module_ids": ["progress", "field", "review", "delivery"],
                    "work_item_schema": LINE_LOSS_SCHEMA,
                },
            )
            require(response.status_code == 200, f"project creation failed: {response.text}")
            project = response.json()["data"]
            schema = project.get("work_item_schema", {})
            custom_by_key = {field.get("key"): field for field in schema.get("custom_fields", [])}
            require(schema.get("primary_field", {}).get("key") == "station_area_no", "primary field drifted")
            require(schema.get("aggregate_field", {}).get("key") == "power_supply_unit", "aggregate field drifted")
            require(custom_by_key.get("master_meter_no", {}).get("parent_key") == "station_area_no", "master meter parent drifted")
            require(custom_by_key.get("user_no", {}).get("parent_key") == "station_area_no", "user parent drifted")
            require(custom_by_key.get("line_loss_issue_type", {}).get("capture_method") == "select", "issue type must be select")
            require(custom_by_key.get("master_meter_photo", {}).get("relation_role") == "evidence_photo", "master meter photo role drifted")

            preview_response = client.post(
                f"/projects/{project['id']}/templates/preview",
                json={"work_item_schema": schema},
            )
            require(preview_response.status_code == 200, f"template preview failed: {preview_response.text}")
            preview = preview_response.json()["data"]
            initial_headers = template_headers(preview, "initial_work_orders")
            external_headers = template_headers(preview, "external_completed")
            for header in ("Station area", "Power supply unit", "Master meter", "User"):
                require(header in initial_headers, f"initial template missing {header}")
                require(header in external_headers, f"external-completed template missing {header}")
            for header in ("Line loss issue type", "Master meter photo", "User meter sample photo"):
                require(header not in initial_headers, f"initial template should not require site field {header}")
                require(header in external_headers, f"external-completed template missing site field {header}")
            require(
                set(preview.get("site_required_fields", [])) >= {"Line loss issue type", "Master meter photo", "User meter sample photo"},
                "site required fields must include line-loss collection evidence",
            )
        finally:
            reset_project_drafts(remove_store=True)
            configure_project_draft_store_path(None)

    print("[OK] platform line-loss template contract is preserved")


if __name__ == "__main__":
    main()
