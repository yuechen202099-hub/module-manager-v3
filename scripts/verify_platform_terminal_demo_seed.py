from __future__ import annotations

import importlib.util
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEED_SCRIPT = ROOT / "scripts" / "seed-platform-terminal-demo.py"


def fail(message: str) -> None:
    raise SystemExit(message)


if not SEED_SCRIPT.exists():
    fail("missing scripts/seed-platform-terminal-demo.py")

spec = importlib.util.spec_from_file_location("seed_platform_terminal_demo", SEED_SCRIPT)
if spec is None or spec.loader is None:
    fail("cannot import terminal demo seed script")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

required_names = [
    "TERMINAL_PROJECT_NAME",
    "TERMINAL_PROJECT_SCHEMA",
    "SAMPLE_WORK_ORDERS",
    "ensure_local_environment",
    "seed_terminal_demo",
]
for name in required_names:
    if not hasattr(module, name):
        fail(f"terminal demo seed script missing {name}")

if module.TERMINAL_PROJECT_NAME != "更换终端":
    fail("terminal demo seed must target 更换终端")

schema = module.TERMINAL_PROJECT_SCHEMA
if schema["primary_field"]["key"] != "terminal_no":
    fail("terminal demo seed primary field must be terminal_no")
if schema["aggregate_field"]["key"] != "area_no":
    fail("terminal demo seed aggregate field must be area_no")

custom_by_key = {field["key"]: field for field in schema["custom_fields"]}
expected_fields = {
    "old_device_no": ("scan", "text"),
    "communication_module_no": ("scan", "text"),
    "new_sim_card_no": ("manual", "text"),
    "before_reform_photo": ("photo", "image"),
    "old_device_recovery_photo": ("photo", "image"),
    "old_new_module_photo": ("photo", "image"),
    "after_reform_photo": ("photo", "image"),
}
for key, (capture_method, data_type) in expected_fields.items():
    field = custom_by_key.get(key)
    if not field:
        fail(f"terminal demo seed missing field {key}")
    if not str(field.get("label") or "").strip():
        fail(f"terminal demo seed field {key} must have a non-empty label")
    if field["capture_method"] != capture_method or field["data_type"] != data_type:
        fail(f"terminal demo seed field {key} has wrong capture/data type")
    if field.get("parent_key") != "terminal_no":
        fail(f"terminal demo seed field {key} must belong to terminal_no")

new_terminal = custom_by_key.get("new_terminal_no")
if not new_terminal:
    fail("terminal demo seed missing field new_terminal_no")
if new_terminal.get("capture_method") != "scan" or new_terminal.get("data_type") != "text":
    fail("terminal demo seed new terminal must be a scanned text field")
if new_terminal.get("parent_key") != "terminal_no":
    fail("terminal demo seed new terminal must belong to terminal_no")
if new_terminal.get("relation_role") != "replacement_device":
    fail("terminal demo seed new terminal must be marked as replacement_device")
if new_terminal.get("required") is not True:
    fail("terminal demo seed new terminal must be required")

orders = module.SAMPLE_WORK_ORDERS
if not (3 <= len(orders) <= 5):
    fail("terminal demo seed must define 3-5 sample work orders")

required_order_keys = {"terminal_no", "area_no", "meter_no", "address", "constructor"}
seen_terminals = set()
for order in orders:
    missing = required_order_keys - set(order)
    if missing:
        fail(f"sample work order missing {sorted(missing)[0]}")
    terminal = str(order["terminal_no"]).strip()
    if not terminal:
        fail("sample work order terminal_no cannot be empty")
    if terminal in seen_terminals:
        fail("sample work order terminal_no values must be unique")
    seen_terminals.add(terminal)

previous_app_env = os.environ.get("APP_ENV")
os.environ["APP_ENV"] = "production"
try:
    try:
        module.ensure_local_environment(False)
    except SystemExit:
        pass
    else:
        fail("terminal demo seed must refuse production-like environments")
finally:
    if previous_app_env is None:
        os.environ.pop("APP_ENV", None)
    else:
        os.environ["APP_ENV"] = previous_app_env

source = SEED_SCRIPT.read_text(encoding="utf-8")
if "PLATFORM_PROJECT_DRAFTS_PATH" not in source:
    fail("terminal demo seed must document/use the draft store path environment")
if "LOCAL_SIMULATION_STATE_PATH" not in source or "platform-terminal-demo-state-local.json" not in source:
    fail("terminal demo seed must persist local simulation state to a predictable local file")

print("[OK] terminal platform demo seed script is structurally safe.")
