from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def request_json(url: str, *, method: str = "GET", data: dict | None = None, token: str = "") -> dict:
    body = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def assert_http_ok(url: str) -> None:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=20) as response:
        if response.status != 200:
            raise AssertionError(f"{url} returned HTTP {response.status}")


def assert_http_status(url: str, expected_status: int) -> None:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            actual_status = response.status
    except urllib.error.HTTPError as exc:
        actual_status = exc.code
    if actual_status != expected_status:
        raise AssertionError(f"{url} returned HTTP {actual_status}, expected {expected_status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run production health checks for Module Manager.")
    parser.add_argument("--base-url", default="http://127.0.0.1", help="Base URL, for example http://127.0.0.1")
    parser.add_argument("--expected-version", required=True, help="Expected app version, for example 3.0.37")
    parser.add_argument("--env", type=Path, default=Path("/opt/module-manager-v2/.env"))
    parser.add_argument("--skip-admin", action="store_true", help="Skip authenticated admin API checks")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    for path in ["/health", "/login", "/project-board", "/task-hall", "/construction"]:
        assert_http_ok(f"{base_url}{path}")
    print("[OK] core public pages return 200")

    for path in ["/docs", "/redoc", "/openapi.json"]:
        assert_http_status(f"{base_url}{path}", 404)
    print("[OK] production API docs are hidden")

    if args.skip_admin:
        return 0

    env = read_env(args.env)
    username = env.get("ADMIN_USERNAME", "")
    password = env.get("ADMIN_PASSWORD", "")
    team_id = env.get("ADMIN_TEAM_ID", "default-team")
    if not username or not password:
        raise AssertionError("ADMIN_USERNAME and ADMIN_PASSWORD are required for admin checks")

    login = request_json(
        f"{base_url}/auth/login",
        method="POST",
        data={"username": username, "password": password, "team_id": team_id},
    )
    token = login["data"]["access_token"]

    status = request_json(f"{base_url}/local-test/system/status", token=token)
    actual_version = str(status["data"]["version"])
    if actual_version != args.expected_version:
        raise AssertionError(f"Expected version {args.expected_version}, got {actual_version}")
    print(f"[OK] system status version {actual_version}")

    summary = request_json(f"{base_url}/local-test/summary", token=token)["data"]["summary"]
    required_summary_keys = {
        "photo_accuracy_checked",
        "photo_accuracy_passed",
        "photo_accuracy_failed",
        "photo_accuracy_unreadable",
        "photo_accuracy_not_required",
        "photo_accuracy_rate",
        "group_barcode_accuracy_checked",
        "group_barcode_accuracy_passed",
        "group_barcode_accuracy_failed",
        "group_barcode_accuracy_unreadable",
        "group_barcode_accuracy_not_required",
        "group_barcode_accuracy_rate",
    }
    missing = sorted(required_summary_keys - set(summary))
    if missing:
        raise AssertionError("Summary missing barcode accuracy fields: " + ", ".join(missing))
    print("[OK] summary contains photo and group barcode accuracy fields")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, urllib.error.URLError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
