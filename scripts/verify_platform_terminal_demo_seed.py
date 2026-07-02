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
    "old_device_no": ("旧设备（拆回）", "scan", "text"),
    "communication_module_no": ("通讯模块（需更换）", "scan", "text"),
    "new_sim_card_no": ("新SIM卡", "manual", "text"),
    "before_reform_photo": ("改造前照片", "photo", "image"),
    "old_device_recovery_photo": ("旧设备回收照片", "photo", "image"),
    "old_new_module_photo": ("新旧模块照片", "photo", "image"),
    "after_reform_photo": ("改造后照片", "photo", "image"),
}
for key, (label, capture_method, data_type) in expected_fields.items():
    field = custom_by_key.get(key)
    if not field:
        fail(f"terminal demo seed missing field {key}")
    if field["label"] != label or field["capture_method"] != capture_method or field["data_type"] != data_type:
        fail(f"terminal demo seed field {key} has wrong label/capture/data type")
    if field.get("parent_key") != "terminal_no":
        fail(f"terminal demo seed field {key} must belong to terminal_no")

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
