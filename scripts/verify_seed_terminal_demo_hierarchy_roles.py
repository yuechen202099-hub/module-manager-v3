from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = ROOT / "scripts" / "seed-platform-terminal-demo.py"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"[FAIL] {message}")


def load_seed_module():
    spec = importlib.util.spec_from_file_location("seed_platform_terminal_demo", SEED_PATH)
    require(spec is not None and spec.loader is not None, "seed module spec cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_platform_terminal_demo"] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        os.environ["APP_ENV"] = "local"
        os.environ["STATE_BACKEND"] = "json"
        os.environ["DEMO_AUTH_ENABLED"] = "true"
        os.environ["PLATFORM_PROJECT_DRAFTS_PATH"] = str(temp_path / "platform-project-drafts.json")
        os.environ["LOCAL_SIMULATION_STATE_PATH"] = str(temp_path / "local-simulation-state.json")

        seed = load_seed_module()
        result = seed.seed_terminal_demo(team_id="demo-team", force_local=True)
        schema = result["project"].get("work_item_schema", {})
        custom_by_key = {field.get("key"): field for field in schema.get("custom_fields", [])}

        require(schema.get("primary_field", {}).get("relation_role") == "task_object", "terminal primary role missing")
        require(schema.get("aggregate_field", {}).get("relation_role") == "aggregate", "terminal aggregate role missing")

        expected_roles = {
            "old_device_no": "old_device",
            "new_terminal_no": "replacement_device",
            "communication_module_replace_confirm": "accessory_replace_confirm",
            "old_communication_module_no": "old_device",
            "communication_module_no": "accessory_new_device",
            "sim_card_replace_confirm": "accessory_replace_confirm",
            "old_sim_card_no": "old_device",
            "new_sim_card_no": "accessory_new_device",
            "before_reform_photo": "evidence_photo",
            "old_device_recovery_photo": "evidence_photo",
            "old_new_module_photo": "evidence_photo",
            "after_reform_photo": "evidence_photo",
        }
        for key, role in expected_roles.items():
            require(custom_by_key.get(key, {}).get("relation_role") == role, f"{key} relation_role mismatch")
            require(
                custom_by_key.get(key, {}).get("show_in_construction_panel") is True,
                f"{key} should be visible on construction panel",
            )

        require(
            custom_by_key.get("new_terminal_no", {}).get("parent_key") == "terminal_no",
            "new_terminal_no must be attached under terminal_no",
        )
        require(
            custom_by_key.get("new_terminal_no", {}).get("capture_method") == "scan",
            "new_terminal_no must be scanned during construction",
        )
        require(
            custom_by_key.get("new_terminal_no", {}).get("required") is True,
            "new_terminal_no must be required for terminal replacement",
        )

        for key in ("old_communication_module_no", "communication_module_no", "old_new_module_photo"):
            required_when = custom_by_key.get(key, {}).get("required_when") or {}
            require(required_when.get("field_key") == "communication_module_replace_confirm", f"{key} required_when field mismatch")

        for key in ("old_sim_card_no", "new_sim_card_no"):
            required_when = custom_by_key.get(key, {}).get("required_when") or {}
            require(required_when.get("field_key") == "sim_card_replace_confirm", f"{key} required_when field mismatch")

    print("[OK] terminal demo seed preserves hierarchy relation roles")


if __name__ == "__main__":
    main()
