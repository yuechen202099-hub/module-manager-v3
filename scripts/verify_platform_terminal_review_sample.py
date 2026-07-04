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
        require(
            hasattr(seed, "seed_terminal_review_sample"),
            "terminal demo seed must expose seed_terminal_review_sample",
        )
        result = seed.seed_terminal_review_sample(team_id="demo-team", force_local=True)
        review_work_order = result.get("review_work_order") or {}
        review_work_orders = result.get("review_work_orders") or [review_work_order]
        require(review_work_order.get("review_status") == "pending_review", "terminal sample must enter pending review")
        require(review_work_order.get("primary_value") == "TT-TERM-REVIEW-001", "terminal review sample primary value mismatch")
        require(len(review_work_orders) >= 2, "terminal sample must include a no-communication-module replacement variant")

        fields = {
            field.get("key"): field
            for field in review_work_order.get("field_reviews", [])
            if isinstance(field, dict)
        }
        require(
            fields.get("new_terminal_no", {}).get("relation_role") == "replacement_device",
            "new terminal must be reviewed as the main replacement device",
        )
        require(
            fields.get("old_device_no", {}).get("relation_role") == "old_device",
            "old terminal/device must be reviewed as recovered old device",
        )
        require(
            fields.get("communication_module_replace_confirm", {}).get("relation_role") == "accessory_replace_confirm",
            "communication module confirmation must be reviewed as accessory confirmation",
        )
        for key in ("old_communication_module_no", "communication_module_no"):
            required_when = fields.get(key, {}).get("required_when") or {}
            require(
                required_when.get("field_key") == "communication_module_replace_confirm",
                f"{key} must keep communication-module required_when",
            )
        for key in ("old_sim_card_no", "new_sim_card_no"):
            required_when = fields.get(key, {}).get("required_when") or {}
            require(
                required_when.get("field_key") == "sim_card_replace_confirm",
                f"{key} must keep SIM-card required_when",
            )

        photo_slots = {
            slot.get("key"): slot
            for slot in review_work_order.get("photo_slot_reviews", [])
            if isinstance(slot, dict)
        }
        require(
            photo_slots.get("old_device_recovery_photo", {}).get("relation_role") == "evidence_photo",
            "old device recovery photo must remain evidence",
        )
        require(
            (photo_slots.get("old_new_module_photo", {}).get("required_when") or {}).get("field_key")
            == "communication_module_replace_confirm",
            "old/new module photo must keep communication-module required_when",
        )

        no_comm_work_order = next(
            (
                item
                for item in review_work_orders
                if str(item.get("primary_value") or "") == "TT-TERM-REVIEW-002"
            ),
            None,
        )
        require(no_comm_work_order is not None, "terminal no-communication-module sample missing")
        no_comm_fields = {
            field.get("key"): field
            for field in no_comm_work_order.get("field_reviews", [])
            if isinstance(field, dict)
        }
        require(
            no_comm_fields.get("communication_module_replace_confirm", {}).get("collected_value") == "不更换",
            "no-communication sample must record communication module as not replaced",
        )
        require(
            not no_comm_fields.get("old_communication_module_no", {}).get("collected_value"),
            "no-communication sample must not collect old communication module number",
        )
        require(
            not no_comm_fields.get("communication_module_no", {}).get("collected_value"),
            "no-communication sample must not collect new communication module number",
        )
        require(
            no_comm_fields.get("sim_card_replace_confirm", {}).get("collected_value") == "更换",
            "no-communication sample must still allow SIM replacement",
        )
        no_comm_photo_slots = {
            slot.get("key"): slot
            for slot in no_comm_work_order.get("photo_slot_reviews", [])
            if isinstance(slot, dict)
        }
        require(
            no_comm_photo_slots.get("old_new_module_photo", {}).get("covered") is False,
            "no-communication sample must not require or cover old/new module photo",
        )

        repeat = seed.seed_terminal_review_sample(team_id="demo-team", force_local=True)
        require(repeat.get("created") is False, "terminal review sample seed must be idempotent")

    print("[OK] terminal review sample preserves main-device review hierarchy")


if __name__ == "__main__":
    main()
