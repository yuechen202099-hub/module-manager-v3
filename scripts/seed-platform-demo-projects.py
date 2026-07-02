from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "v2-api"
sys.path.insert(0, str(API_ROOT))

from app.services.platform.catalog import create_project_draft  # noqa: E402


DEMO_PROJECTS = [
    {
        "name": "终端更换模板模拟",
        "description": "用于验证终端主字段、台区聚合字段和系统外已完成模板。",
        "module_ids": ["progress", "delivery", "field", "review"],
        "work_item_schema": {
            "primary_field": {"key": "terminal_no", "label": "终端", "source": "import", "required": True},
            "aggregate_field": {"key": "station_area", "label": "台区", "source": "import", "required": True},
            "custom_fields": [
                {"key": "address", "label": "安装地址", "source": "import", "required": False},
                {
                    "key": "communication_module",
                    "label": "通讯模块",
                    "source": "field_collection",
                    "capture_method": "scan",
                    "required": True,
                    "parent_key": "terminal_no",
                },
                {
                    "key": "carrier_module",
                    "label": "载波模块",
                    "source": "field_collection",
                    "capture_method": "scan",
                    "required": False,
                    "parent_key": "terminal_no",
                },
            ],
        },
    },
    {
        "name": "台区线损排查模板模拟",
        "description": "用于验证台区主字段、总表聚合字段和用户侧子字段。",
        "module_ids": ["progress", "delivery", "field", "review", "risks"],
        "work_item_schema": {
            "primary_field": {"key": "station_area", "label": "台区", "source": "import", "required": True},
            "aggregate_field": {"key": "master_meter", "label": "总表", "source": "import", "required": True},
            "custom_fields": [
                {"key": "user_meter", "label": "用户表", "source": "import", "required": False},
                {
                    "key": "site_issue",
                    "label": "现场问题",
                    "source": "field_collection",
                    "capture_method": "manual",
                    "required": False,
                    "parent_key": "station_area",
                },
                {
                    "key": "evidence_photo",
                    "label": "证据照片",
                    "source": "field_collection",
                    "capture_method": "photo",
                    "data_type": "image",
                    "required": False,
                    "parent_key": "station_area",
                },
            ],
        },
    },
]


def ensure_local_environment(force: bool) -> None:
    app_env = os.getenv("APP_ENV", "local").strip().lower()
    if force or app_env in {"local", "dev", "development", "test"}:
        return
    raise SystemExit(
        f"Refusing to seed demo projects when APP_ENV={app_env!r}. "
        "Set APP_ENV=local or pass --force-local on a disposable local environment."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed synthetic project-management demo projects.")
    parser.add_argument("--force-local", action="store_true", help="Allow seeding outside APP_ENV=local/test.")
    args = parser.parse_args()
    ensure_local_environment(args.force_local)

    created = []
    for project in DEMO_PROJECTS:
        created.append(create_project_draft(**project))
    for project in created:
        print(f"{project['id']}\t{project['name']}\t{project['status']}")


if __name__ == "__main__":
    main()
