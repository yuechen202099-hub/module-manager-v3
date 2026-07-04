from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "v2-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.platform.catalog import configure_project_draft_store_path, reset_project_drafts  # noqa: E402
from app.services.platform.handoff_readiness import build_platform_handoff_readiness  # noqa: E402


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
        "id": "legacy-config-blocker",
        "name": "历史字段草稿",
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
        try:
            write_store(store_path, [bad_legacy_project()])
            readiness = build_platform_handoff_readiness()
            preflight = readiness.get("config_preflight", {})

            require(preflight.get("ready_for_config_load") is False, "handoff must expose blocked config preflight")
            require(preflight.get("summary", {}).get("blocked_projects") == 1, "handoff must count blocked drafts")
            require(readiness.get("ready_for_review_package") is False, "blocked config preflight must block review package")
            require(
                "fix_config_preflight_blockers" in readiness.get("next_actions", []),
                "handoff must surface the config-preflight fix action",
            )
            require(
                "read_only_no_write" in preflight.get("safety", []),
                "handoff config preflight must keep read-only safety evidence",
            )

            summary = readiness.get("project_readiness_summary", {})
            require(summary.get("readiness_version") == 1, "handoff must keep a project readiness summary")
            require(
                "fix_config_preflight_blockers"
                in {item.get("action") for item in summary.get("action_counts", []) if isinstance(item, dict)},
                "blocked handoff summary must expose config preflight as an action count",
            )
        finally:
            reset_project_drafts(remove_store=True)
            configure_project_draft_store_path(None)

    print("[OK] platform handoff readiness includes config preflight blockers")


if __name__ == "__main__":
    main()
