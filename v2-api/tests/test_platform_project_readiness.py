from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.platform.catalog import configure_project_draft_store_path, reset_project_drafts
from app.services.platform.readiness import _device_hierarchy_check, _single_aggregate_field_check


def _complete_terminal_project_payload() -> dict:
    return {
        "name": "terminal readiness project",
        "description": "terminal replacement readiness sample",
        "module_ids": ["progress", "field", "review", "tasks", "delivery"],
        "work_item_schema": {
            "primary_field": {
                "key": "terminal",
                "label": "Terminal to replace",
                "source": "import",
                "capture_method": "scan",
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
                    "key": "old_terminal",
                    "label": "Old terminal",
                    "source": "field_collection",
                    "capture_method": "scan",
                    "required": True,
                    "parent_key": "terminal",
                    "relation_role": "old_device",
                },
                {
                    "key": "new_terminal",
                    "label": "New terminal",
                    "source": "field_collection",
                    "capture_method": "scan",
                    "required": True,
                    "parent_key": "terminal",
                    "relation_role": "replacement_device",
                },
                {
                    "key": "communication_module_replace_confirm",
                    "label": "Communication module replace confirm",
                    "source": "field_collection",
                    "capture_method": "select",
                    "data_type": "enum",
                    "required": True,
                    "parent_key": "terminal",
                    "relation_role": "accessory_replace_confirm",
                    "options": ["更换", "不更换"],
                },
                {
                    "key": "communication_module",
                    "label": "Communication module to replace",
                    "source": "field_collection",
                    "capture_method": "scan",
                    "required": False,
                    "parent_key": "terminal",
                    "relation_role": "accessory_new_device",
                    "required_when": {"field_key": "communication_module_replace_confirm", "equals": "更换"},
                },
                {
                    "key": "sim_card_replace_confirm",
                    "label": "SIM card replace confirm",
                    "source": "field_collection",
                    "capture_method": "select",
                    "data_type": "enum",
                    "required": True,
                    "parent_key": "terminal",
                    "relation_role": "accessory_replace_confirm",
                    "options": ["更换", "不更换"],
                },
                {
                    "key": "new_sim_card",
                    "label": "New SIM card",
                    "source": "field_collection",
                    "capture_method": "manual",
                    "required": False,
                    "parent_key": "terminal",
                    "relation_role": "accessory_new_device",
                    "required_when": {"field_key": "sim_card_replace_confirm", "equals": "更换"},
                },
                {
                    "key": "before_photo",
                    "label": "Before photo",
                    "data_type": "image",
                    "source": "field_collection",
                    "capture_method": "photo",
                    "required": True,
                    "parent_key": "terminal",
                    "relation_role": "evidence_photo",
                },
                {
                    "key": "module_photo",
                    "label": "Old and new module photo",
                    "data_type": "image",
                    "source": "field_collection",
                    "capture_method": "photo",
                    "required": True,
                    "parent_key": "terminal",
                    "relation_role": "evidence_photo",
                    "required_when": {"field_key": "communication_module_replace_confirm", "equals": "更换"},
                },
                {
                    "key": "after_photo",
                    "label": "After photo",
                    "data_type": "image",
                    "source": "field_collection",
                    "capture_method": "photo",
                    "required": True,
                    "parent_key": "terminal",
                    "relation_role": "evidence_photo",
                },
            ],
        },
    }


def _enable_complete_workflow(client: TestClient, project_id: str) -> None:
    response = client.put(
        f"/projects/{project_id}/workflow",
        json={
            "actor": "ops-admin",
            "version": 1,
            "module_sync_enabled": True,
            "nodes": [
                {"id": "project_setup", "required": True, "module_id": "progress", "enabled": True, "order": 10},
                {"id": "field_schema", "required": True, "module_id": "field", "enabled": True, "order": 20},
                {"id": "template_import", "module_id": "tasks", "enabled": True, "order": 30},
                {"id": "construction_collection", "module_id": "field", "enabled": True, "order": 40},
                {"id": "review", "module_id": "review", "enabled": True, "order": 50},
                {"id": "delivery_archive", "module_id": "delivery", "enabled": True, "order": 60},
            ],
        },
    )
    assert response.status_code == 200


def test_complete_project_is_ready_for_platform_onboarding(tmp_path) -> None:
    store_path = tmp_path / "platform-project-drafts.json"
    configure_project_draft_store_path(store_path)
    reset_project_drafts(remove_store=True)
    try:
        client = TestClient(app)
        create_response = client.post("/projects", json=_complete_terminal_project_payload())
        assert create_response.status_code == 200
        project_id = create_response.json()["data"]["id"]
        _enable_complete_workflow(client, project_id)

        response = client.get(f"/projects/{project_id}/readiness")

        assert response.status_code == 200
        payload = response.json()["data"]
        assert payload["readiness_version"] == 1
        assert payload["project_id"] == project_id
        assert payload["ready"] is True
        assert payload["summary"]["failed"] == 0
        assert payload["summary"]["passed"] >= 8
        assert payload["next_actions"] == ["ready_for_template_import", "ready_for_construction_collection", "ready_for_review_archive"]
        assert {check["id"] for check in payload["checks"] if check["status"] == "passed"} >= {
            "primary_field",
            "aggregate_field",
            "single_aggregate_field",
            "custom_site_fields",
            "photo_evidence",
            "required_kpi_fields",
            "template_import_workflow",
            "construction_workflow",
            "review_workflow",
            "delivery_workflow",
            "device_hierarchy",
        }
        assert "read_only_no_write" in payload["safety"]
    finally:
        reset_project_drafts(remove_store=True)
        configure_project_draft_store_path(None)


def test_single_aggregate_readiness_reports_extra_aggregate_fields() -> None:
    check = _single_aggregate_field_check(
        {
            "primary_field": {"key": "terminal", "relation_role": "task_object"},
            "aggregate_field": {"key": "station_area", "relation_role": "aggregate"},
            "custom_fields": [
                {"key": "region_name", "relation_role": "aggregate"},
                {"key": "manufacturer_name", "relation_role": "task_detail"},
            ],
        }
    )

    assert check["id"] == "single_aggregate_field"
    assert check["status"] == "failed"
    assert check["action"] == "fix_aggregate_field"
    assert check["evidence"]["extra_aggregate_keys"] == ["region_name"]


def test_device_replacement_hierarchy_blocks_flat_accessory_fields(tmp_path) -> None:
    device_check = _device_hierarchy_check(
        {
            "primary_field": {"key": "terminal", "label": "Terminal", "relation_role": "task_object"},
            "custom_fields": [
                {"key": "old_terminal", "label": "Old terminal", "parent_key": "terminal", "relation_role": "old_device"},
                {"key": "new_terminal", "label": "New terminal", "parent_key": "terminal", "relation_role": "replacement_device"},
                {"key": "communication_module_replace_confirm", "label": "Communication module replace confirm", "parent_key": "terminal"},
                {"key": "communication_module", "label": "Communication module", "parent_key": "terminal", "relation_role": "accessory_new_device"},
                {"key": "sim_card_replace_confirm", "label": "SIM card replace confirm", "parent_key": "terminal"},
                {"key": "new_sim_card", "label": "New SIM card", "parent_key": "terminal", "relation_role": "accessory_new_device"},
                {"key": "module_photo", "label": "Module photo", "parent_key": "terminal", "relation_role": "evidence_photo"},
            ],
        }
    )

    assert device_check["status"] == "failed"
    assert device_check["group"] == "field_schema"
    assert device_check["action"] == "complete_device_hierarchy"
    assert set(device_check["evidence"]["missing_confirmation_keys"]) >= {
        "communication_module_replace_confirm",
        "sim_card_replace_confirm",
    }
    assert set(device_check["evidence"]["unconditional_child_keys"]) >= {
        "communication_module",
        "new_sim_card",
        "module_photo",
    }


def test_device_replacement_hierarchy_exposes_operator_contract_notes() -> None:
    module_check = _device_hierarchy_check(
        {
            "primary_field": {"key": "meter_no", "label": "Meter", "relation_role": "task_object"},
            "custom_fields": [
                {
                    "key": "module_asset_no",
                    "label": "Module to replace",
                    "parent_key": "meter_no",
                    "relation_role": "accessory_new_device",
                },
            ],
        }
    )
    terminal_check = _device_hierarchy_check(
        {
            "primary_field": {"key": "terminal_no", "label": "Terminal", "relation_role": "task_object"},
            "custom_fields": [
                {
                    "key": "old_terminal_no",
                    "label": "Old terminal",
                    "parent_key": "terminal_no",
                    "relation_role": "old_device",
                },
                {
                    "key": "new_terminal_no",
                    "label": "New terminal",
                    "parent_key": "terminal_no",
                    "relation_role": "replacement_device",
                },
                {
                    "key": "communication_module_replace_confirm",
                    "label": "Communication module replace confirm",
                    "parent_key": "terminal_no",
                    "relation_role": "accessory_replace_confirm",
                },
                {
                    "key": "communication_module_no",
                    "label": "Communication module",
                    "parent_key": "terminal_no",
                    "relation_role": "accessory_new_device",
                    "required_when": {"field_key": "communication_module_replace_confirm", "equals": "更换"},
                },
            ],
        }
    )

    assert module_check["evidence"]["hierarchy_contract"]["active_mode"] == "accessory_under_task_object"
    assert "任务对象下更换附属设备" in module_check["evidence"]["hierarchy_contract"]["module_replacement"]
    assert terminal_check["evidence"]["hierarchy_contract"]["active_mode"] == "main_device_with_accessory_confirmation"
    assert "确认附属设备是否更换" in terminal_check["evidence"]["hierarchy_contract"]["terminal_replacement"]


def test_incomplete_project_reports_blocking_readiness_failures(tmp_path) -> None:
    store_path = tmp_path / "platform-project-drafts.json"
    configure_project_draft_store_path(store_path)
    reset_project_drafts(remove_store=True)
    try:
        client = TestClient(app)
        create_response = client.post(
            "/projects",
            json={
                "name": "incomplete onboarding project",
                "module_ids": ["progress"],
            },
        )
        assert create_response.status_code == 200
        project_id = create_response.json()["data"]["id"]

        response = client.get(f"/projects/{project_id}/readiness")

        assert response.status_code == 200
        payload = response.json()["data"]
        assert payload["ready"] is False
        assert payload["summary"]["failed"] >= 4
        failed_check_ids = {check["id"] for check in payload["checks"] if check["status"] == "failed"}
        assert {"primary_field", "aggregate_field", "custom_site_fields", "photo_evidence", "review_workflow"}.issubset(failed_check_ids)
        assert "complete_field_schema" in payload["next_actions"]
        assert "enable_review_workflow" in payload["next_actions"]
    finally:
        reset_project_drafts(remove_store=True)
        configure_project_draft_store_path(None)


def test_project_readiness_summary_lists_ready_and_blocked_projects(tmp_path) -> None:
    store_path = tmp_path / "platform-project-drafts.json"
    configure_project_draft_store_path(store_path)
    reset_project_drafts(remove_store=True)
    try:
        client = TestClient(app)
        ready_response = client.post("/projects", json=_complete_terminal_project_payload())
        assert ready_response.status_code == 200
        ready_project_id = ready_response.json()["data"]["id"]
        _enable_complete_workflow(client, ready_project_id)

        blocked_response = client.post(
            "/projects",
            json={
                "name": "blocked readiness summary project",
                "module_ids": ["progress"],
            },
        )
        assert blocked_response.status_code == 200
        blocked_project_id = blocked_response.json()["data"]["id"]

        response = client.get("/projects/readiness/summary")

        assert response.status_code == 200
        payload = response.json()["data"]
        assert payload["readiness_version"] == 1
        assert payload["total"] >= 2
        assert payload["ready"] >= 1
        assert payload["not_ready"] >= 1
        assert "read_only_no_write" in payload["safety"]

        items_by_id = {item["project_id"]: item for item in payload["items"]}
        assert items_by_id[ready_project_id]["project_name"] == "terminal readiness project"
        assert items_by_id[ready_project_id]["ready"] is True
        assert items_by_id[ready_project_id]["summary"]["failed"] == 0
        assert "checks" not in items_by_id[ready_project_id]
        assert items_by_id[blocked_project_id]["ready"] is False
        assert items_by_id[blocked_project_id]["summary"]["failed"] >= 4
        assert "complete_field_schema" in items_by_id[blocked_project_id]["next_actions"]
        action_counts = {item["action"]: item["count"] for item in payload["action_counts"]}
        assert action_counts["complete_field_schema"] >= 1
        assert action_counts["enable_review_workflow"] >= 1
        assert "ready_for_template_import" not in action_counts
    finally:
        reset_project_drafts(remove_store=True)
        configure_project_draft_store_path(None)
