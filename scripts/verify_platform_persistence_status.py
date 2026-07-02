from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "v2-api"
sys.path.insert(0, str(API_ROOT))

from app.services.platform.persistence import build_platform_persistence_status  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"[FAIL] {message}")


def main() -> None:
    status = build_platform_persistence_status()
    stores = {store.get("id"): store for store in status.get("stores", [])}

    require(status.get("status_version") == 1, "status_version must be 1")
    require(bool(status.get("state_backend")), "state_backend is required")
    require("module_manager_password" not in status.get("database", {}).get("url_redacted", ""), "database password leaked")
    require("status_only_no_write" in status.get("safety", []), "status must be read-only")

    for store_id in (
        "project_drafts",
        "import_batches",
        "work_order_tasks",
        "platform_work_orders",
        "construction_photos",
    ):
        require(store_id in stores, f"missing store status: {store_id}")
        require(bool(stores[store_id].get("path")), f"missing path for store: {store_id}")

    project_store = stores["project_drafts"]
    require("field_schema" in project_store.get("contains", []), "project drafts must contain field_schema")
    require("workflow_definition" in project_store.get("contains", []), "project drafts must contain workflow_definition")
    require(
        "workflow_definition_persisted_for_draft_projects" in status.get("guarantees", []),
        "workflow persistence guarantee missing",
    )

    print("[OK] platform persistence status is consistent")


if __name__ == "__main__":
    main()

