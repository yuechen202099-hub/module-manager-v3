from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "v2-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.platform.catalog import configure_project_draft_store_path, reset_project_drafts  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def write_store(path: Path, projects: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "projects": projects}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def bad_legacy_project() -> dict:
    return {
        "id": "legacy-project-list-blocker",
        "name": "历史列表坏草稿",
        "status": "draft",
        "adapter": "draft",
        "module_ids": ["progress", "field", "review", "tasks"],
        "work_item_schema": {
            "primary_field": {
                "key": "terminal_no",
                "label": "终端",
                "required": True,
                "source": "import",
                "capture_method": "manual",
                "relation_role": "task_object",
            },
            "aggregate_field": {
                "key": "station_area",
                "label": "台区",
                "required": True,
                "source": "import",
                "capture_method": "manual",
                "relation_role": "aggregate",
            },
            "custom_fields": [
                {
                    "key": "manufacturer_name",
                    "label": "厂家",
                    "required": False,
                    "source": "import",
                    "capture_method": "manual",
                    "relation_role": "aggregate",
                }
            ],
        },
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store_path = Path(temp_dir) / "platform-project-drafts.json"
        configure_project_draft_store_path(store_path)
        reset_project_drafts(remove_store=True)
        client = TestClient(app)
        try:
            write_store(store_path, [bad_legacy_project()])
            response = client.get("/projects")
            require(response.status_code == 200, f"project list must degrade to 200, got {response.status_code}")
            payload = response.json()["data"]
            require(payload["total"] >= 1, "project list fallback must keep built-in projects visible")
            require(payload["config_preflight"]["ready_for_config_load"] is False, "project list must include blocked preflight")
            require(
                payload["config_preflight"]["summary"]["blocked_projects"] == 1,
                "project list preflight must count blocked draft projects",
            )
            require(
                "fix_config_preflight_blockers" in payload["next_actions"],
                "project list must surface config-preflight repair action",
            )
            require(
                "config_preflight_blocks_project_list" in payload["safety"],
                "project list fallback must expose safety evidence",
            )
        finally:
            reset_project_drafts(remove_store=True)
            configure_project_draft_store_path(None)

    print("[OK] project list degrades with config preflight blockers")


if __name__ == "__main__":
    main()
