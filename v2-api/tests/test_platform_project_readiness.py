from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.platform.catalog import configure_project_draft_store_path, reset_project_drafts


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
            },
            "aggregate_field": {
                "key": "station_area",
                "label": "Station area",
                "source": "import",
                "capture_method": "manual",
                "required": True,
            },
            "custom_fields": [
                {
                    "key": "old_terminal",
                    "label": "Old terminal",
                    "source": "field_collection",
                    "capture_method": "scan",
                    "required": True,
                    "parent_key": "terminal",
                },
                {
                    "key": "communication_module",
                    "label": "Communication module to replace",
                    "source": "field_collection",
                    "capture_method": "scan",
                    "required": True,
                    "parent_key": "terminal",
                },
                {
                    "key": "new_sim_card",
                    "label": "New SIM card",
                    "source": "field_collection",
                    "capture_method": "manual",
                    "required": True,
                    "parent_key": "terminal",
                },
                {
                    "key": "before_photo",
                    "label": "Before photo",
                    "data_type": "image",
                    "source": "field_collection",
                    "capture_method": "photo",
                    "required": True,
                    "parent_key": "terminal",
                },
                {
                    "key": "module_photo",
                    "label": "Old and new module photo",
                    "data_type": "image",
                    "source": "field_collection",
                    "capture_method": "photo",
                    "required": True,
                    "parent_key": "terminal",
                },
                {
                    "key": "after_photo",
                    "label": "After photo",
                    "data_type": "image",
                    "source": "field_collection",
                    "capture_method": "photo",
                    "required": True,
                    "parent_key": "terminal",
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
            "custom_site_fields",
            "photo_evidence",
            "required_kpi_fields",
            "template_import_workflow",
            "construction_workflow",
            "review_workflow",
            "delivery_workflow",
        }
        assert "read_only_no_write" in payload["safety"]
    finally:
        reset_project_drafts(remove_store=True)
        configure_project_draft_store_path(None)


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
