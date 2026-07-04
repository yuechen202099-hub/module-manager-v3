from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "v2-api"
SCRIPTS_ROOT = ROOT / "scripts"
sys.path.insert(0, str(API_ROOT))
sys.path.insert(0, str(SCRIPTS_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.platform import templates as platform_templates  # noqa: E402
from app.services.platform.catalog import configure_project_draft_store_path, reset_project_drafts  # noqa: E402
from verify_platform_delivery_archive_readiness import (  # noqa: E402
    create_project,
    create_work_orders,
    require,
    reset_platform_runtime_files,
    review_action,
    submit_complete_collection,
    submit_incomplete_cached_collection,
)


def main() -> None:
    with TemporaryDirectory() as temp_dir:
        configure_project_draft_store_path(Path(temp_dir) / "platform-project-drafts.json")
        reset_project_drafts(remove_store=True)
        reset_platform_runtime_files()
        try:
            client = TestClient(app)
            project_id = create_project(client)
            work_order_ids = create_work_orders(client, project_id)

            submit_complete_collection(client, project_id, work_order_ids["TERM-READY"], "READY")
            review_action(client, project_id, work_order_ids["TERM-READY"], "approved")

            submit_complete_collection(client, project_id, work_order_ids["TERM-PENDING"], "PENDING")
            submit_incomplete_cached_collection(client, project_id, work_order_ids["TERM-GAP"])

            response = client.get(f"/projects/{project_id}/delivery/archive-manifest")
            require(response.status_code == 200, "delivery archive manifest route failed")
            payload = response.json()["data"]

            require(payload.get("project_id") == project_id, "manifest project_id mismatch")
            require(payload.get("manifest_id") == f"{project_id}:delivery-archive-preview", "manifest id mismatch")
            require(payload.get("status") == "blocked", "manifest must inherit blocked readiness status")
            require(payload.get("can_export") is False, "blocked manifest must not be exportable")
            require(payload.get("ready_count") == 1, "manifest ready count mismatch")
            require(payload.get("blocked_count") == 5, "manifest blocked count mismatch")
            require("review_pending_work_orders" in payload.get("next_actions", []), "manifest missing review action")

            section_by_id = {
                section.get("id"): section
                for section in payload.get("sections", [])
                if isinstance(section, dict)
            }
            require(section_by_id.get("approved_archive", {}).get("count") == 1, "approved archive section mismatch")
            require(section_by_id.get("pending_review", {}).get("count") == 1, "pending review section mismatch")
            require(section_by_id.get("evidence_gap", {}).get("count") == 1, "evidence gap section mismatch")
            require(section_by_id.get("not_ready", {}).get("count") == 3, "not ready section mismatch")
            ready_items = section_by_id.get("approved_archive", {}).get("items", [])
            require(
                any(item.get("primary_value") == "TERM-READY" for item in ready_items if isinstance(item, dict)),
                "approved archive section must include TERM-READY",
            )

            evidence = payload.get("required_evidence", {})
            field_keys = {item.get("key") for item in evidence.get("fields", []) if isinstance(item, dict)}
            photo_keys = {item.get("key") for item in evidence.get("photos", []) if isinstance(item, dict)}
            require(
                {"installer", "completed_at", "uploaded_at", "photo_count", "old_device_recovered"}.issubset(field_keys),
                "required evidence must include platform KPI archive fields",
            )
            require("new_terminal" in field_keys, "required evidence must include new terminal")
            require("communication_module_no" in field_keys, "required evidence must include conditional module number")
            require("after_photo" in photo_keys, "required evidence must include after photo")
            require("old_new_module_photo" in photo_keys, "required evidence must include conditional module photo")
        finally:
            reset_project_drafts(remove_store=True)
            reset_platform_runtime_files()
            configure_project_draft_store_path(None)

    print("[OK] platform delivery archive manifest is summarized")


if __name__ == "__main__":
    main()
