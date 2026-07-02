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


def _create_complete_project(client: TestClient) -> str:
    response = client.post(
        "/projects",
        json={
            "name": "terminal readiness guard",
            "module_ids": ["progress", "field", "review", "tasks", "delivery"],
            "work_item_schema": {
                "primary_field": {"key": "terminal", "label": "Terminal", "source": "import", "capture_method": "scan", "required": True},
                "aggregate_field": {"key": "station_area", "label": "Station area", "source": "import", "capture_method": "manual", "required": True},
                "custom_fields": [
                    {"key": "old_terminal", "label": "Old terminal", "source": "field_collection", "capture_method": "scan", "required": True, "parent_key": "terminal"},
                    {"key": "communication_module", "label": "Communication module", "source": "field_collection", "capture_method": "scan", "required": True, "parent_key": "terminal"},
                    {"key": "new_sim_card", "label": "New SIM card", "source": "field_collection", "capture_method": "manual", "required": True, "parent_key": "terminal"},
                    {"key": "before_photo", "label": "Before photo", "data_type": "image", "source": "field_collection", "capture_method": "photo", "required": True, "parent_key": "terminal"},
                    {"key": "module_photo", "label": "Module photo", "data_type": "image", "source": "field_collection", "capture_method": "photo", "required": True, "parent_key": "terminal"},
                    {"key": "after_photo", "label": "After photo", "data_type": "image", "source": "field_collection", "capture_method": "photo", "required": True, "parent_key": "terminal"},
                ],
            },
        },
    )
    require(response.status_code == 200, "complete project creation failed")
    project_id = response.json()["data"]["id"]
    workflow_response = client.put(
        f"/projects/{project_id}/workflow",
        json={
            "actor": "ops-admin",
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
    require(workflow_response.status_code == 200, "complete workflow update failed")
    return project_id


def main() -> None:
    with TemporaryDirectory() as temp_dir:
        store_path = Path(temp_dir) / "platform-project-drafts.json"
        configure_project_draft_store_path(store_path)
        reset_project_drafts(remove_store=True)
        try:
            client = TestClient(app)
            ready_project_id = _create_complete_project(client)
            ready_response = client.get(f"/projects/{ready_project_id}/readiness")
            require(ready_response.status_code == 200, "ready project readiness route failed")
            ready_payload = ready_response.json()["data"]
            require(ready_payload.get("ready") is True, "complete project should be ready")
            require(ready_payload.get("summary", {}).get("failed") == 0, "complete project has failed checks")
            require("ready_for_construction_collection" in ready_payload.get("next_actions", []), "ready next action missing")

            incomplete_response = client.post(
                "/projects",
                json={"name": "incomplete readiness guard", "module_ids": ["progress"]},
            )
            require(incomplete_response.status_code == 200, "incomplete project creation failed")
            incomplete_project_id = incomplete_response.json()["data"]["id"]
            not_ready_response = client.get(f"/projects/{incomplete_project_id}/readiness")
            require(not_ready_response.status_code == 200, "incomplete project readiness route failed")
            not_ready_payload = not_ready_response.json()["data"]
            failed_ids = {
                check.get("id")
                for check in not_ready_payload.get("checks", [])
                if check.get("status") == "failed"
            }
            require(not_ready_payload.get("ready") is False, "incomplete project should not be ready")
            require({"custom_site_fields", "photo_evidence", "review_workflow"}.issubset(failed_ids), "expected failed readiness checks missing")
            require("enable_review_workflow" in not_ready_payload.get("next_actions", []), "review next action missing")

            summary_response = client.get("/projects/readiness/summary")
            require(summary_response.status_code == 200, "readiness summary route failed")
            summary_payload = summary_response.json()["data"]
            require(summary_payload.get("readiness_version") == 1, "readiness summary version drifted")
            require(summary_payload.get("ready", 0) >= 1, "readiness summary missing ready project")
            require(summary_payload.get("not_ready", 0) >= 1, "readiness summary missing not-ready project")
            items_by_id = {
                item.get("project_id"): item
                for item in summary_payload.get("items", [])
                if isinstance(item, dict)
            }
            require(items_by_id.get(ready_project_id, {}).get("ready") is True, "ready project missing from summary")
            require(items_by_id.get(incomplete_project_id, {}).get("ready") is False, "incomplete project missing from summary")
            require("checks" not in items_by_id.get(ready_project_id, {}), "readiness summary must stay lightweight")
            require("read_only_no_write" in summary_payload.get("safety", []), "readiness summary safety missing")
            action_counts = {
                item.get("action"): item.get("count")
                for item in summary_payload.get("action_counts", [])
                if isinstance(item, dict)
            }
            require(action_counts.get("complete_field_schema", 0) >= 1, "field schema action count missing")
            require(action_counts.get("enable_review_workflow", 0) >= 1, "review workflow action count missing")
            require("ready_for_template_import" not in action_counts, "ready next actions must not be counted as todos")
        finally:
            reset_project_drafts(remove_store=True)
            configure_project_draft_store_path(None)

    print("[OK] platform project readiness is consistent")


if __name__ == "__main__":
    main()
