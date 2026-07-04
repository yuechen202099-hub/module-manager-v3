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
    configure_project_draft_store_path,
    reset_project_drafts,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"[FAIL] {message}")


def _client_with_temp_store():
    temp_dir = TemporaryDirectory()
    store_path = Path(temp_dir.name) / "platform-project-drafts.json"
    configure_project_draft_store_path(store_path)
    reset_project_drafts(remove_store=True)
    return temp_dir, TestClient(app)


def _base_schema() -> dict[str, object]:
    return {
        "primary_field": {
            "key": "terminal_no",
            "label": "Terminal",
            "source": "import",
            "relation_role": "task_object",
        },
        "aggregate_field": {
            "key": "area_no",
            "label": "Area",
            "source": "import",
            "relation_role": "aggregate",
        },
        "custom_fields": [],
    }


def main() -> None:
    temp_dir, client = _client_with_temp_store()
    try:
        multiple_aggregate_response = client.post(
            "/projects",
            json={
                "name": "multiple aggregate guard",
                "module_ids": ["progress", "field"],
                "work_item_schema": {
                    **_base_schema(),
                    "custom_fields": [
                        {
                            "key": "region_name",
                            "label": "Region",
                            "source": "import",
                            "relation_role": "aggregate",
                        }
                    ],
                },
            },
        )
        require(
            multiple_aggregate_response.status_code == 400,
            "backend must reject custom fields marked as an extra aggregate field",
        )
        require(
            "Only one aggregate field" in multiple_aggregate_response.json().get("detail", ""),
            "aggregate guard must explain that only one aggregate field is allowed",
        )

        create_response = client.post(
            "/projects",
            json={
                "name": "terminal hierarchy guard",
                "module_ids": ["progress", "field", "review"],
                "work_item_schema": _base_schema(),
            },
        )
        require(create_response.status_code == 200, "valid base project creation failed")
        project_id = create_response.json()["data"]["id"]

        invalid_terminal_hierarchy_response = client.patch(
            f"/projects/{project_id}/work-item-schema",
            json={
                **_base_schema(),
                "custom_fields": [
                    {
                        "key": "new_terminal_no",
                        "label": "New terminal",
                        "source": "field_collection",
                        "capture_method": "scan",
                        "required": True,
                        "parent_key": "terminal_no",
                        "relation_role": "replacement_device",
                    },
                    {
                        "key": "communication_module_no",
                        "label": "New communication module",
                        "source": "field_collection",
                        "capture_method": "scan",
                        "parent_key": "terminal_no",
                        "relation_role": "accessory_new_device",
                    },
                ],
            },
        )
        require(
            invalid_terminal_hierarchy_response.status_code == 400,
            "backend must reject main-device replacement without accessory confirmation",
        )
        require(
            "accessory confirmation" in invalid_terminal_hierarchy_response.json().get("detail", ""),
            "device hierarchy guard must explain that main-device replacement needs accessory confirmation",
        )
    finally:
        reset_project_drafts(remove_store=True)
        configure_project_draft_store_path(None)
        temp_dir.cleanup()

    print("[OK] platform single aggregate and device hierarchy guards are enforced")


if __name__ == "__main__":
    main()
