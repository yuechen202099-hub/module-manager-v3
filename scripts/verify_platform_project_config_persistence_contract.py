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
            create_response = client.post(
                "/projects",
                json={
                    "name": "更换终端",
                    "description": "终端施工采集契约验证项目",
                    "module_ids": ["progress", "field", "review", "tasks", "delivery"],
                    "work_item_schema": {
                        "primary_field": {
                            "key": "terminal",
                            "label": "终端（需更换）",
                            "source": "import",
                            "capture_method": "scan",
                            "required": True,
                        },
                        "aggregate_field": {
                            "key": "station_area",
                            "label": "台区",
                            "source": "import",
                            "capture_method": "manual",
                            "required": True,
                        },
                        "custom_fields": [
                            {
                                "key": "communication_module",
                                "label": "通讯模块（需更换）",
                                "source": "field_collection",
                                "capture_method": "scan",
                                "required": True,
                                "parent_key": "terminal",
                            },
                            {
                                "key": "new_sim_card",
                                "label": "新 SIM 卡",
                                "source": "field_collection",
                                "capture_method": "manual",
                                "required": True,
                                "parent_key": "terminal",
                            },
                            {
                                "key": "after_photo",
                                "label": "改造后照片",
                                "data_type": "image",
                                "source": "field_collection",
                                "capture_method": "photo",
                                "required": True,
                                "parent_key": "terminal",
                            },
                        ],
                    },
                },
            )
            require(create_response.status_code == 200, "project creation failed")
            project_id = create_response.json()["data"]["id"]

            workflow_response = client.put(
                f"/projects/{project_id}/workflow",
                json={
                    "actor": "ops-admin",
                    "version": 1,
                    "module_sync_enabled": True,
                    "nodes": [
                        {"id": "project_setup", "required": True, "module_id": "progress", "order": 10},
                        {"id": "field_schema", "required": True, "module_id": "field", "order": 20},
                        {"id": "construction_collection", "module_id": "field", "enabled": True, "order": 30},
                        {"id": "review", "module_id": "review", "enabled": True, "order": 40},
                        {"id": "delivery_archive", "module_id": "delivery", "enabled": True, "order": 50},
                    ],
                },
            )
            require(workflow_response.status_code == 200, "workflow update failed")

            contract_response = client.get(f"/projects/{project_id}/persistence/contract")
            require(contract_response.status_code == 200, "contract route failed")
            contract = contract_response.json()["data"]
            record = contract.get("config_record", {})
            roundtrip = contract.get("roundtrip", {})

            require(record.get("project_key") == project_id, "project_key not preserved")
            require(record.get("field_schema", {}).get("primary_field", {}).get("key") == "terminal", "primary field not preserved")
            require(record.get("field_schema", {}).get("aggregate_field", {}).get("key") == "station_area", "aggregate field not preserved")
            require(record.get("workflow_definition", {}).get("module_sync_enabled") is True, "workflow sync flag not preserved")
            require(roundtrip.get("can_restore") is True, "roundtrip preview failed")
            require(roundtrip.get("missing_preserved_keys") == [], "roundtrip missing preserved keys")
            require("no_database_connection" in contract.get("safety", []), "database safety missing")
            require("requires_user_approval_before_migration" in contract.get("migration_gate", []), "migration approval gate missing")
        finally:
            reset_project_drafts(remove_store=True)
            configure_project_draft_store_path(None)

    print("[OK] platform project config persistence contract is consistent")


if __name__ == "__main__":
    main()
