from __future__ import annotations

import html
import os
import sys
import subprocess
import warnings
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "v2-api"
os.environ["STATE_BACKEND"] = "json"
sys.path.insert(0, str(API_ROOT))
warnings.filterwarnings("ignore", category=DeprecationWarning, module="fastapi.testclient")
warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient` is deprecated.*")

from fastapi.testclient import TestClient  # noqa: E402

from app.api.routes import auth  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.main import create_app  # noqa: E402


settings.state_backend = "json"
client = TestClient(create_app())


def check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        message = f"[FAIL] {name}"
        if detail:
            message += f": {detail}"
        raise AssertionError(message)
    print(f"[OK] {name}")


def get_text(path: str) -> str:
    response = client.get(path)
    check(f"{path} returns 200", response.status_code == 200, str(response.status_code))
    check(f"{path} returns html", "text/html" in response.headers.get("content-type", ""))
    return html.unescape(response.text)


def assert_vue_shell(path: str) -> str:
    text = get_text(path)
    check(f"{path} serves Vue shell", '<div id="app"></div>' in text)
    check(f"{path} loads Vue assets", "/vue/assets/" in text and 'type="module"' in text)
    check(f"{path} does not serve legacy iframe shell", 'id="workFrame"' not in text and "embedded=1" not in text)
    check(f"{path} does not expose legacy static view", "LegacyStaticPageView" not in text)
    return text


def login(username: str, password: str):
    return client.post("/auth/login", json={"username": username, "password": password})


def main() -> int:
    health = client.get("/health")
    check("health check", health.status_code == 200)
    root = client.get("/", follow_redirects=False)
    check("root redirects to login", root.status_code in {302, 307} and root.headers.get("location") == "/login")
    legacy = client.get("/v201", follow_redirects=False)
    check("legacy v201 redirects to review desk", legacy.status_code in {302, 307} and legacy.headers.get("location") == "/app?page=task-hall")
    legacy_static = client.get("/static/v201.html")
    check("legacy static v201 is removed", legacy_static.status_code == 404)
    check("legacy static v201 removal is explicit", "legacy_static_page_removed" in legacy_static.text)
    favicon = client.get("/favicon.ico")
    check("favicon is served", favicon.status_code == 200)
    check("favicon is svg", "image/svg+xml" in favicon.headers.get("content-type", ""))

    admin = login("admin", "admin123")
    reviewer = login("reviewer", "review123")
    constructor = login("constructor", "construct123")
    bad = login("admin", "bad-password")
    auth_config = client.get("/auth/config")
    check("demo admin login", admin.status_code == 200)
    check("demo reviewer login", reviewer.status_code == 200)
    check("demo constructor login", constructor.status_code == 200)
    check("bad password rejected", bad.status_code == 401)
    check("auth config route", auth_config.status_code == 200)
    check("auth config exposes local demo accounts", {item["username"] for item in auth_config.json()["data"]["demo_accounts"]} == {"admin", "reviewer", "constructor"})
    check("admin opens app shell", admin.json()["data"]["user"]["home"] == "/app")
    check("reviewer opens app shell", reviewer.json()["data"]["user"]["home"] == "/app")
    check("constructor opens construction page", constructor.json()["data"]["user"]["home"] == "/app?page=construction")

    vue_routes = [
        "/login",
        "/app",
        "/app?page=project-board",
        "/app?page=claim-tasks",
        "/app?page=task-hall",
        "/app?page=construction",
        "/project-board",
        "/claim-tasks",
        "/task-hall",
        "/construction",
        "/sync-config",
    ]
    for path in vue_routes:
        text = assert_vue_shell(path)
        check(f"{path} does not hardcode demo passwords", "admin / admin123" not in text and "reviewer / review123" not in text)

    cancelled_app_shell_routes = [
        "/app?page=unmatched",
        "/app?page=construction-cache",
    ]
    for path in cancelled_app_shell_routes:
        text = assert_vue_shell(path)
        check(f"{path} only serves Vue shell for client-side redirect", '<div id="app"></div>' in text)

    cancelled_routes = {
        "/unmatched": "/task-hall",
        "/unmatched?embedded=1": "/task-hall",
        "/construction-cache": "/construction",
        "/construction-cache?embedded=1": "/construction",
    }
    for path, expected_location in cancelled_routes.items():
        response = client.get(path, follow_redirects=False)
        check(
            f"{path} redirects away from cancelled standalone page",
            response.status_code in {302, 307} and response.headers.get("location") == expected_location,
            f"{response.status_code} {response.headers.get('location')}",
        )

    for legacy_file in [
        "/static/project_board.html",
        "/static/claim_tasks.html",
        "/static/task_hall.html",
        "/static/unmatched.html",
        "/static/construction_cache.html",
        "/static/sync_config.html",
    ]:
        response = client.get(legacy_file)
        check(f"{legacy_file} is not served in production path", response.status_code == 404)

    for index in range(1, 5):
        asset = client.get(f"/static/demo-assets/review-photo-{index}.svg")
        check(f"demo review image {index} is served", asset.status_code == 200)
        check(f"demo review image {index} is svg", "image/svg+xml" in asset.headers.get("content-type", ""))

    summary = client.get("/local-test/summary")
    check("summary route", summary.status_code == 200)
    data = summary.json()["data"]["summary"]
    check("summary has installer distribution", "installer_distribution" in data)

    client.post("/local-test/bootstrap")
    smoke_suffix = uuid4().hex[:8]
    created = client.post(
        "/local-test/groups",
        json={
            "actor": "smoke",
            "terminal": f"T-SMOKE-{smoke_suffix}",
            "meter_no": f"M-SMOKE-{smoke_suffix}",
            "address": "smoke",
        },
    )
    check("manual empty group can be created", created.status_code == 200)
    group_id = created.json()["data"]["group"]["id"]
    uploaded = client.post(
        f"/local-test/groups/{group_id}/photos/upload-images",
        data={"actor": "smoke", "collector": "smoke-collector", "module_asset_no": "smoke-module"},
        files=[
            ("files", ("smoke-a.jpg", b"smoke-image-a", "image/jpeg")),
            ("files", ("smoke-b.png", b"smoke-image-b", "image/png")),
        ],
    )
    check("manual补图 upload route works", uploaded.status_code == 200)
    upload_data = uploaded.json()["data"]
    check("manual补图 added two images", upload_data["added"] == 2)
    for url in upload_data.get("uploaded_urls", []):
        if url.startswith("/static/uploads/manual/"):
            uploaded_path = ROOT / "v2-api" / "app" / "static" / url.removeprefix("/static/")
            uploaded_path.unlink(missing_ok=True)

    original_settings = auth.settings
    try:
        auth.settings = SimpleNamespace(
            app_env="production",
            demo_auth_enabled=None,
            admin_username="real-admin",
            admin_password="real-secret",
        )
        disabled_demo = login("admin", "admin123")
        real_admin = login("real-admin", "real-secret")
        production_auth_config = client.get("/auth/config")
        check("production disables demo admin by default", disabled_demo.status_code == 401)
        check("production env admin still works", real_admin.status_code == 200)
        check("production auth config hides demo accounts", production_auth_config.json()["data"]["demo_accounts"] == [])
    finally:
        auth.settings = original_settings

    required_files = [
        "docs/CLIENT_ACCEPTANCE_REPORT.md",
        "docs/CLIENT_FINAL_AUDIT.md",
        "docs/CLIENT_DEMO_READINESS.md",
        "docs/CLIENT_DEMO_SCRIPT.md",
        "docs/CLIENT_SIGNOFF_CHECKLIST.md",
        "docs/CLIENT_VISUAL_QA.md",
        "docs/SERVER_DEPLOYMENT_PREP.md",
        "infra/nginx/module-manager-v2.conf",
        "infra/module-manager-v2.service",
        "scripts/seed-client-demo-data.py",
    ]
    for item in required_files:
        check(f"{item} exists", (ROOT / item).exists())

    signoff = (ROOT / "docs" / "CLIENT_SIGNOFF_CHECKLIST.md").read_text(encoding="utf-8")
    check("client signoff checklist contains payment acceptance item", "付款流程" in signoff)
    check("client signoff checklist references final release zip", "module-manager-v2-client-demo-final-delivery-ready.zip" in signoff)

    visual_qa = (ROOT / "docs" / "CLIENT_VISUAL_QA.md").read_text(encoding="utf-8")
    check("visual QA records shared topbar height", "topbar: 64px" in visual_qa)
    check("visual QA records shared panel header height", "panel header: 48px" in visual_qa)

    demo_script = (ROOT / "scripts" / "run-client-demo.ps1").read_text(encoding="utf-8")
    check("demo startup prints sync status entry", "/sync-config" in demo_script and "Sync status" in demo_script)

    static_check = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify-static-pages.py")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    check("static page syntax check", static_check.returncode == 0, static_check.stderr or static_check.stdout)

    print("\nClient demo smoke check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
