from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter, sleep
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

THRESHOLDS = {
    "task_snapshot_ms": 300,
    "review_groups_ms": 1500,
    "review_group_count": 20,
    "task_builds_in_60_seconds": 1,
}
BUILD_SAMPLE_SECONDS = 60


def verify_measurements(
    *,
    task_snapshot_ms: float,
    review_groups_ms: float,
    review_group_count: int,
    task_builds_in_60_seconds: int,
) -> dict[str, Any]:
    measurements = {
        "task_snapshot_ms": round(float(task_snapshot_ms), 3),
        "review_groups_ms": round(float(review_groups_ms), 3),
        "review_group_count": int(review_group_count),
        "task_builds_in_60_seconds": int(task_builds_in_60_seconds),
    }
    failures = [name for name, limit in THRESHOLDS.items() if measurements[name] > limit]
    return {
        "ok": not failures,
        "failures": failures,
        "measurements": measurements,
        "thresholds": dict(THRESHOLDS),
    }


def request_json(
    base_url: str,
    path: str,
    *,
    token: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    body = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    request = Request(f"{base_url.rstrip('/')}{path}", data=body, headers=headers, method="POST" if body else "GET")
    try:
        with urlopen(request, timeout=30) as response:
            document = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code} for {path}: {detail}") from error
    if not isinstance(document, dict):
        raise RuntimeError(f"Unexpected JSON response for {path}")
    data = document.get("data", document)
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected data response for {path}")
    return data


def timed_get(base_url: str, path: str, token: str) -> tuple[dict[str, Any], float]:
    started = perf_counter()
    data = request_json(base_url, path, token=token)
    return data, round((perf_counter() - started) * 1000, 3)


def authenticate(base_url: str, username: str, password: str) -> str:
    data = request_json(base_url, "/auth/login", payload={"username": username, "password": password})
    token = str(data.get("access_token") or "")
    if not token:
        raise RuntimeError("Login response did not include an access token")
    return token


def cache_generation(snapshot: dict[str, Any]) -> str:
    generated_at = str(snapshot.get("generated_at") or "")
    cache = snapshot.get("cache") if isinstance(snapshot.get("cache"), dict) else {}
    return generated_at or str(cache.get("generated_at") or "")


def cache_build_count(snapshot: dict[str, Any]) -> int:
    cache = snapshot.get("cache") if isinstance(snapshot.get("cache"), dict) else {}
    return max(0, int(cache.get("build_count") or 0))


def cache_instance_id(snapshot: dict[str, Any]) -> str:
    cache = snapshot.get("cache") if isinstance(snapshot.get("cache"), dict) else {}
    return str(cache.get("instance_id") or "").strip()


def observed_build_count(
    start_count: int,
    end_count: int,
    start_instance_id: str,
    end_instance_id: str,
) -> int:
    if not start_instance_id or start_instance_id != end_instance_id:
        raise ValueError("task snapshot cache restarted during the build sample")
    if int(end_count) < int(start_count):
        raise ValueError("task snapshot build counter moved backwards")
    return int(end_count) - int(start_count)


def run_verification(base_url: str, token: str) -> dict[str, Any]:
    first_snapshot, first_snapshot_ms = timed_get(base_url, "/local-test/tasks/snapshot", token)
    second_snapshot, warm_snapshot_ms = timed_get(base_url, "/local-test/tasks/snapshot", token)
    tasks = second_snapshot.get("items") if isinstance(second_snapshot.get("items"), list) else []
    if not tasks:
        raise RuntimeError("Task snapshot contains no task to verify")
    task_id = str(tasks[0].get("id") or "") if isinstance(tasks[0], dict) else ""
    if not task_id:
        raise RuntimeError("First task snapshot item has no id")
    review_path = f"/local-test/tasks/{quote(task_id, safe='')}/review-groups?limit=20&offset=0&review_status=all&query="
    review_page, review_groups_ms = timed_get(base_url, review_path, token)
    review_items = review_page.get("items") if isinstance(review_page.get("items"), list) else []
    start_build_count = cache_build_count(second_snapshot)
    start_instance_id = cache_instance_id(second_snapshot)
    sleep(BUILD_SAMPLE_SECONDS)
    sampled_snapshot, _sampled_snapshot_ms = timed_get(base_url, "/local-test/tasks/snapshot", token)
    end_build_count = cache_build_count(sampled_snapshot)
    end_instance_id = cache_instance_id(sampled_snapshot)
    task_builds_in_sample = observed_build_count(
        start_build_count,
        end_build_count,
        start_instance_id,
        end_instance_id,
    )
    report = verify_measurements(
        task_snapshot_ms=warm_snapshot_ms,
        review_groups_ms=review_groups_ms,
        review_group_count=len(review_items),
        task_builds_in_60_seconds=task_builds_in_sample,
    )
    report.update(
        {
            "checked_at": datetime.now(UTC).isoformat(),
            "base_url": base_url.rstrip("/"),
            "task_id": task_id,
            "first_task_snapshot_ms": first_snapshot_ms,
            "snapshot_version_reused": first_snapshot.get("version") == second_snapshot.get("version"),
            "snapshot_generation_reused": cache_generation(first_snapshot) == cache_generation(second_snapshot),
            "build_sample_seconds": BUILD_SAMPLE_SECONDS,
            "start_build_count": start_build_count,
            "end_build_count": end_build_count,
            "cache_instance_id": start_instance_id,
        }
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify V3.1.0 task and review performance thresholds.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--token", default=os.getenv("MODULE_MANAGER_ACCESS_TOKEN", ""))
    parser.add_argument("--username", default=os.getenv("ADMIN_USERNAME", "admin"))
    parser.add_argument("--password", default=os.getenv("ADMIN_PASSWORD", "admin123"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        token = args.token or authenticate(args.base_url, args.username, args.password)
        report = run_verification(args.base_url, token)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["ok"] else 1
    except Exception as error:
        print(f"performance verification failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
