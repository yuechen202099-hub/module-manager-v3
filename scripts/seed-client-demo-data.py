from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from typing import Any


DEMO_REVIEWER = "reviewer"
LEGACY_DEMO_REVIEWERS = {"local-reviewer"}
DEMO_PHOTO_URLS = [
    "/static/demo-assets/review-photo-1.svg",
    "/static/demo-assets/review-photo-2.svg",
    "/static/demo-assets/review-photo-3.svg",
    "/static/demo-assets/review-photo-4.svg",
]


def request_json(base_url: str, path: str, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {detail}") from exc
    return json.loads(body).get("data", {})


def has_visible_review_photo(base_url: str, reviewer: str) -> bool:
    tasks = request_json(base_url, "/local-test/tasks").get("items", [])
    for task in tasks:
        if task.get("claimed_by") != reviewer:
            continue
        groups = request_json(base_url, f"/local-test/tasks/{task['id']}/groups?limit=1000&scan_only=true").get("items", [])
        for group in groups:
            detail = request_json(base_url, f"/local-test/groups/{group['id']}")
            if any(photo.get("image_url") for photo in detail.get("photos", [])):
                return True
    return False


def ensure_demo_review_group(base_url: str, reviewer: str) -> dict[str, Any] | None:
    tasks = request_json(base_url, "/local-test/tasks").get("items", [])
    task = next((item for item in tasks if item.get("has_scan_info") and item.get("claimed_by") in {None, reviewer}), None)
    task = task or next((item for item in tasks if item.get("can_claim")), None)
    if task is not None and task.get("claimed_by") in LEGACY_DEMO_REVIEWERS:
        request_json(
            base_url,
            f"/local-test/tasks/{task['id']}/release",
            "POST",
            {"reviewer": task["claimed_by"]},
        )
        refreshed = request_json(base_url, "/local-test/tasks").get("items", [])
        task = next((item for item in refreshed if item.get("id") == task["id"]), None)
    if task is None:
        legacy_task = next(
            (
                item
                for item in tasks
                if item.get("has_scan_info") and item.get("claimed_by") in LEGACY_DEMO_REVIEWERS
            ),
            None,
        )
        if legacy_task is not None:
            request_json(
                base_url,
                f"/local-test/tasks/{legacy_task['id']}/release",
                "POST",
                {"reviewer": legacy_task["claimed_by"]},
            )
            refreshed = request_json(base_url, "/local-test/tasks").get("items", [])
            task = next((item for item in refreshed if item.get("id") == legacy_task["id"]), None)
    if not task:
        return None

    if task.get("claimed_by") != reviewer:
        request_json(base_url, f"/local-test/tasks/{task['id']}/claim", "POST", {"reviewer": reviewer})

    groups = request_json(base_url, f"/local-test/tasks/{task['id']}/groups?limit=1000&scan_only=true").get("items", [])
    group = groups[0] if groups else None
    if group is None:
        created = request_json(
            base_url,
            "/local-test/groups",
            "POST",
            {
                "actor": "demo-seed",
                "terminal": str(task.get("terminal") or "DEMO-TERMINAL"),
                "meter_no": "DEMO-METER-001",
                "address": "演示资料组",
            },
        )
        group = created["group"]

    request_json(
        base_url,
        f"/local-test/groups/{group['id']}/photos/import-urls",
        "POST",
        {
            "actor": "demo-seed",
            "photo_urls": DEMO_PHOTO_URLS,
            "collector": "demo-collector",
            "module_asset_no": "demo-module",
            "creator": "演示安装人员",
        },
    )
    return {"task_id": task["id"], "terminal": task.get("terminal"), "group_id": group["id"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Ensure the local client demo has one review group with visible image URLs.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--reviewer", default=DEMO_REVIEWER)
    args = parser.parse_args()

    if has_visible_review_photo(args.base_url, args.reviewer):
        print("[OK] client demo already has visible review photos")
        return 0

    result = ensure_demo_review_group(args.base_url, args.reviewer)
    if result is None:
        print("[OK] no claimable demo task found; visible review photo seed skipped")
        return 0
    print(f"[OK] seeded visible review photos for task {result['task_id']} group {result['group_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
