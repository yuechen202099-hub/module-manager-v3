from __future__ import annotations

import argparse
import json
import sys
from io import BytesIO
from pathlib import Path
from typing import Any


EXPECTED_VERSION = "3.1.0"
EXPECTED_MIGRATION = "v2-api/alembic/versions/0006_group_barcode_verification.py"
EXPECTED_PERFORMANCE_THRESHOLDS = {
    "task_snapshot_ms": 300,
    "review_groups_ms": 1500,
    "review_group_count": 20,
    "task_builds_in_60_seconds": 1,
}


def fail(message: str) -> None:
    raise AssertionError(message)


def read(root: Path, relative_path: str) -> str:
    return (root / relative_path).read_text(encoding="utf-8")


def sample_group() -> dict[str, Any]:
    categories = ("before_box", "collector_barcode", "module_meter", "after_box")
    return {
        "id": "release-sample",
        "status": "archived",
        "terminal": "T-3-1-RELEASE",
        "meter_no": "M-3-1-RELEASE",
        "module_asset_no": "MOD-3-1-RELEASE",
        "collector": "COL-3-1-RELEASE",
        "address": "Release verification address",
        "client_completed_at": "2026-07-23T09:00:00+08:00",
        "photos": [
            {
                "id": f"release-photo-{index}",
                "sha256": f"{index:x}" * 64,
                "category": category,
                "is_active": True,
                "upload_status": "uploaded",
            }
            for index, category in enumerate(categories, start=1)
        ],
    }


def verify(root: Path) -> list[str]:
    api_root = root / "v2-api"
    if str(api_root) not in sys.path:
        sys.path.insert(0, str(api_root))

    from openpyxl import load_workbook

    from app.services.barcode_maintenance_worker import DEFAULT_BATCH_PAUSE_SECONDS, DEFAULT_BATCH_SIZE
    from app.services.final_delivery_export import build_delivery_workbook
    from app.services.group_barcode_verification import evaluate_group_eligibility
    from scripts.verify_task_review_performance import THRESHOLDS

    version_markers = {
        "v2-api/app/main.py": f'version="{EXPECTED_VERSION}"',
        "v2-api/app/services/ops_status.py": f'return "{EXPECTED_VERSION}"',
        "v2-api/pyproject.toml": f'version = "{EXPECTED_VERSION}"',
        "v2-web/package.json": f'"version": "{EXPECTED_VERSION}"',
        "v2-web/index.html": f"Module Manager V{EXPECTED_VERSION}",
        "v2-web/src/version.json": f'"version":"{EXPECTED_VERSION}"',
        "v2-web/src/components/AppLayout.vue": f"V{EXPECTED_VERSION}",
        "scripts/build-client-release.ps1": f'[string]$Version = "{EXPECTED_VERSION}"',
    }
    for path, marker in version_markers.items():
        if marker not in read(root, path):
            fail(f"runtime version source is not {EXPECTED_VERSION}: {path}")

    migration = read(root, EXPECTED_MIGRATION)
    for marker in ("group_barcode_verifications", "barcode_maintenance_controls", "server_default=sa.true()"):
        if marker not in migration:
            fail(f"migration contract missing: {marker}")

    eligible = evaluate_group_eligibility(sample_group())
    if eligible.status != "pending":
        fail("4-photo eligibility sample must be pending")
    placeholder = sample_group()
    placeholder["terminal"] = "00000000"
    if evaluate_group_eligibility(placeholder).status != "not_eligible":
        fail("placeholder zero terminal must be rejected")

    if DEFAULT_BATCH_SIZE != 20 or DEFAULT_BATCH_PAUSE_SECONDS != 5:
        fail("worker must use 20 groups and 5 seconds")
    worker_source = read(root, "v2-api/app/services/barcode_maintenance_worker.py")
    if ".with_for_update(skip_locked=True)" not in worker_source or "sleeper(float(batch_pause_seconds))" not in worker_source:
        fail("worker must claim one group at a time and pause between batches")

    workbook = load_workbook(BytesIO(build_delivery_workbook([sample_group()])), read_only=True)
    if workbook.sheetnames != ["老设备", "新设备"]:
        fail("export sample must generate the two required sheets")

    if THRESHOLDS != EXPECTED_PERFORMANCE_THRESHOLDS:
        fail("task claim and review performance thresholds changed")

    return [
        "migration",
        "4-photo eligibility",
        "worker paused",
        "20 groups serial",
        "5 seconds",
        "placeholder zero",
        "export sample",
        "task claim",
        "review performance",
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the offline V3.1 release candidate contract.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--json", action="store_true", help="Print the verified gate names as JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    gates = verify(args.repo_root.resolve())
    if args.json:
        print(json.dumps({"version": EXPECTED_VERSION, "gates": gates}, ensure_ascii=False))
    else:
        for gate in gates:
            print(f"[OK] {gate}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
