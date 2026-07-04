from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "v2-api"
sys.path.insert(0, str(API_ROOT))

from app.services.platform.readiness import _device_hierarchy_check  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"[FAIL] {message}")


def main() -> None:
    module_check = _device_hierarchy_check(
        {
            "primary_field": {"key": "meter_no", "label": "电能表"},
            "custom_fields": [
                {
                    "key": "module_asset_no",
                    "label": "模块（需更换）",
                    "parent_key": "meter_no",
                    "source": "field_collection",
                    "capture_method": "scan",
                    "required": True,
                    "relation_role": "accessory_new_device",
                },
                {
                    "key": "collector_replace_confirm",
                    "label": "采集器是否更换",
                    "parent_key": "meter_no",
                    "source": "field_collection",
                    "capture_method": "select",
                    "required": True,
                    "relation_role": "accessory_replace_confirm",
                },
                {
                    "key": "collector_no",
                    "label": "新采集器号",
                    "parent_key": "meter_no",
                    "source": "field_collection",
                    "capture_method": "scan",
                    "required": False,
                    "relation_role": "accessory_new_device",
                    "required_when": {"field_key": "collector_replace_confirm", "equals": "更换"},
                },
            ],
        }
    )
    module_evidence = module_check["evidence"]
    require(
        module_evidence.get("replacement_hierarchy_mode") == "accessory_under_task_object",
        "module replacement must be classified as accessory replacement under the task object",
    )
    require(
        module_evidence.get("requires_accessory_confirmation") is False,
        "module replacement main path must not require accessory confirmation",
    )

    terminal_check = _device_hierarchy_check(
        {
            "primary_field": {"key": "terminal_no", "label": "终端"},
            "custom_fields": [
                {
                    "key": "old_device_no",
                    "label": "旧终端/旧设备",
                    "parent_key": "terminal_no",
                    "source": "field_collection",
                    "capture_method": "scan",
                    "required": True,
                    "relation_role": "old_device",
                },
                {
                    "key": "new_terminal_no",
                    "label": "新终端号",
                    "parent_key": "terminal_no",
                    "source": "field_collection",
                    "capture_method": "scan",
                    "required": True,
                    "relation_role": "replacement_device",
                },
                {
                    "key": "communication_module_replace_confirm",
                    "label": "通讯模块是否更换",
                    "parent_key": "terminal_no",
                    "source": "field_collection",
                    "capture_method": "select",
                    "required": True,
                    "relation_role": "accessory_replace_confirm",
                },
                {
                    "key": "communication_module_no",
                    "label": "新通讯模块号",
                    "parent_key": "terminal_no",
                    "source": "field_collection",
                    "capture_method": "scan",
                    "required": False,
                    "relation_role": "accessory_new_device",
                    "required_when": {
                        "field_key": "communication_module_replace_confirm",
                        "equals": "更换",
                    },
                },
            ],
        }
    )
    terminal_evidence = terminal_check["evidence"]
    require(
        terminal_evidence.get("replacement_hierarchy_mode") == "main_device_with_accessory_confirmation",
        "terminal replacement must be classified as main-device replacement with accessory confirmation",
    )
    require(
        terminal_evidence.get("requires_accessory_confirmation") is True,
        "terminal replacement must require accessory confirmation evidence",
    )
    require(
        "new_terminal_no" in terminal_evidence.get("main_replacement_keys", []),
        "terminal readiness evidence must keep the new terminal main replacement key",
    )

    print("[OK] platform device replacement hierarchy mode is explicit")


if __name__ == "__main__":
    main()
