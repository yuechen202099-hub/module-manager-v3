from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.platform.catalog import configure_project_draft_store_path, reset_project_drafts


def test_project_persistence_status_reports_safe_storage_contract(tmp_path) -> None:
    store_path = tmp_path / "platform-project-drafts.json"
    configure_project_draft_store_path(store_path)
    reset_project_drafts(remove_store=True)
    try:
        client = TestClient(app)

        response = client.get("/projects/persistence/status")

        assert response.status_code == 200
        payload = response.json()["data"]
        assert isinstance(payload["state_backend"], str)
        assert payload["state_backend"]
        assert payload["database"]["configured"] is True
        assert "module_manager_password" not in payload["database"]["url_redacted"]
        assert "****" in payload["database"]["url_redacted"]

        stores = {store["id"]: store for store in payload["stores"]}
        assert stores["project_drafts"]["path"] == str(store_path)
        assert stores["project_drafts"]["backend"] == "local_json"
        assert stores["project_drafts"]["exists"] is False
        assert stores["import_batches"]["path"].endswith("platform-import-batches.json")
        assert stores["work_order_tasks"]["path"].endswith("platform-import-work-order-tasks.json")
        assert stores["platform_work_orders"]["path"].endswith("platform-work-orders.json")
        assert stores["construction_photos"]["backend"] == "local_files"

        assert "field_schema" in stores["project_drafts"]["contains"]
        assert "workflow_definition" in stores["project_drafts"]["contains"]
        assert "status_only_no_write" in payload["safety"]
        assert not store_path.exists()
    finally:
        reset_project_drafts(remove_store=True)
        configure_project_draft_store_path(None)
