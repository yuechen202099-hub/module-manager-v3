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


def bad_extra_aggregate_project() -> dict:
    return {
        "id": "legacy-bad-aggregate",
        "name": "历史多聚合项目",
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
            missing_response = client.get("/projects/persistence/config-preflight")
            require(missing_response.status_code == 200, "missing draft store preflight must return 200")
            missing_payload = missing_response.json()["data"]
            require(missing_payload["ready_for_config_load"] is True, "missing draft store should be load-ready")
            require(missing_payload["summary"]["total_projects"] == 0, "missing draft store should report zero projects")

            write_store(store_path, [bad_extra_aggregate_project()])
            response = client.get("/projects/persistence/config-preflight")
            require(response.status_code == 200, f"config preflight returned {response.status_code}")
            payload = response.json()["data"]
            require(payload["ready_for_config_load"] is False, "bad aggregate project must block config load")
            require(payload["summary"]["blocked_projects"] == 1, "preflight must count the blocked project")
            require(payload["summary"]["total_projects"] == 1, "preflight must count raw store projects")
            project = payload["projects"][0]
            require(project["project_id"] == "legacy-bad-aggregate", "preflight must preserve project id")
            require(project["status"] == "blocked", "bad project must be blocked")
            messages = " ".join(issue["message"] for issue in project["issues"])
            require("Only one aggregate field" in messages, "preflight must surface the aggregate validation error")
            require("read_only_no_write" in payload["safety"], "preflight must declare read-only safety")
            require("no_database_connection" in payload["safety"], "preflight must not touch database")
        finally:
            reset_project_drafts(remove_store=True)
            configure_project_draft_store_path(None)

    print("[OK] platform project config preflight reports legacy field-schema blockers")


if __name__ == "__main__":
    main()
