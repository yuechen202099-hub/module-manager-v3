from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.platform.catalog import configure_project_draft_store_path, reset_project_drafts


def _terminal_project_payload() -> dict:
    return {
        "name": "更换终端",
        "description": "终端、通讯模块和 SIM 卡更换施工项目",
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
                    "key": "old_terminal",
                    "label": "旧终端",
                    "source": "field_collection",
                    "capture_method": "scan",
                    "required": True,
                    "parent_key": "terminal",
                },
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
                    "key": "before_photo",
                    "label": "改造前照片",
                    "data_type": "image",
                    "source": "field_collection",
                    "capture_method": "photo",
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
    }


def test_project_config_persistence_contract_preserves_schema_and_workflow(tmp_path) -> None:
    store_path = tmp_path / "platform-project-drafts.json"
    configure_project_draft_store_path(store_path)
    reset_project_drafts(remove_store=True)
    try:
        client = TestClient(app)

        create_response = client.post("/projects", json=_terminal_project_payload())
        assert create_response.status_code == 200
        project_id = create_response.json()["data"]["id"]

        workflow_response = client.put(
            f"/projects/{project_id}/workflow",
            json={
                "actor": "ops-admin",
                "version": 1,
                "module_sync_enabled": True,
                "nodes": [
                    {"id": "project_setup", "label": "项目建立", "required": True, "module_id": "progress", "order": 10},
                    {"id": "field_schema", "label": "字段配置", "required": True, "module_id": "field", "order": 20},
                    {"id": "construction_collection", "label": "现场施工采集", "module_id": "field", "enabled": True, "order": 30},
                    {"id": "review", "label": "审阅", "module_id": "review", "enabled": True, "order": 40},
                    {"id": "delivery_archive", "label": "交付归档", "module_id": "delivery", "enabled": True, "order": 50},
                ],
            },
        )
        assert workflow_response.status_code == 200

        contract_response = client.get(f"/projects/{project_id}/persistence/contract")

        assert contract_response.status_code == 200
        contract = contract_response.json()["data"]
        assert contract["contract_version"] == 1
        assert contract["project_id"] == project_id
        assert contract["target_tables"] == ["platform_project_configs", "platform_project_config_events"]
        assert contract["safety"] == [
            "read_only_no_write",
            "no_database_connection",
            "no_postgres_schema_change",
            "json_source_only",
            "requires_user_approval_before_migration",
        ]

        record = contract["config_record"]
        assert record["team_id"] == "local"
        assert record["project_key"] == project_id
        assert record["name"] == "更换终端"
        assert record["field_schema"]["primary_field"]["key"] == "terminal"
        assert record["field_schema"]["aggregate_field"]["key"] == "station_area"
        assert {field["key"] for field in record["field_schema"]["custom_fields"]} >= {
            "old_terminal",
            "communication_module",
            "new_sim_card",
            "before_photo",
            "after_photo",
        }
        assert record["workflow_definition"]["module_sync_enabled"] is True
        assert "construction_collection" in {
            node["id"] for node in record["workflow_definition"]["nodes"] if node["enabled"]
        }

        roundtrip = contract["roundtrip"]
        assert roundtrip["can_restore"] is True
        assert roundtrip["missing_preserved_keys"] == []
        assert set(roundtrip["preserved_keys"]) >= {
            "project_key",
            "primary_field",
            "aggregate_field",
            "workflow_node_ids",
        }
    finally:
        reset_project_drafts(remove_store=True)
        configure_project_draft_store_path(None)
