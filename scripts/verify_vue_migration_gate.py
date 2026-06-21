from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "v2-api" / "app" / "static"
VUE_DIR = ROOT / "v2-web"
REGISTRY = VUE_DIR / "src" / "router" / "staticPages.ts"

LEGACY_PRODUCTION_STATIC_PAGES = {
    "project_board.html": "project-board",
    "claim_tasks.html": "claim-tasks",
    "task_hall.html": "task-hall",
    "construction.html": "construction",
    "sync_config.html": "sync-config",
}

CANCELLED_STATIC_PAGES = {
    "construction_cache.html",
    "unmatched.html",
}

CANCELLED_STATIC_PAGE_ROUTES = {
    "construction-cache",
    "unmatched",
}

COMPATIBILITY_STATIC_PAGES = {
    "app_shell.html",
    "login.html",
    "v201.html",
}

MOJIBAKE_PATTERNS = (
    "鐧",
    "椤",
    "璧",
    "妯",
    "鏂",
    "瀹",
    "绠",
    "鍏",
    "闈",
    "浠",
    "鎬",
    "鍔",
    "浜",
    "鏈",
    "缂",
    "寮",
    "鍥",
    "绛",
    "绂",
    "淇",
    "棰",
    "涔",
    "鍗",
    "鈥",
    "�",
)


def fail(message: str) -> None:
    raise AssertionError(message)


def read(path: Path) -> str:
    if not path.exists():
        fail(f"Missing required file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def registry_entries(text: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for match in re.finditer(
        r"key:\s*'(?P<key>[^']+)'.*?migrationStatus:\s*'(?P<status>[^']+)'",
        text,
        re.DOTALL,
    ):
        entries[match.group("key")] = match.group("status")
    return entries


def find_mojibake() -> list[str]:
    findings: list[str] = []
    for path in (VUE_DIR / "src").rglob("*.*"):
        if path.suffix not in {".vue", ".ts", ".css"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(pattern in text for pattern in MOJIBAKE_PATTERNS):
            findings.append(str(path.relative_to(ROOT)))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the static-to-Vue migration gate.")
    parser.add_argument("--strict-native", action="store_true", help="Fail unless every registered production page is native Vue.")
    args = parser.parse_args()

    registry_text = read(REGISTRY)
    entries = registry_entries(registry_text)
    missing = sorted(set(LEGACY_PRODUCTION_STATIC_PAGES.values()) - set(entries))
    if missing:
        fail("Vue static page registry is missing production pages: " + ", ".join(missing))

    unknown_static = sorted(
        path.name
        for path in STATIC_DIR.glob("*.html")
        if path.name not in LEGACY_PRODUCTION_STATIC_PAGES
        and path.name not in CANCELLED_STATIC_PAGES
        and path.name not in COMPATIBILITY_STATIC_PAGES
    )
    if unknown_static:
        fail("Unregistered static HTML production candidates found: " + ", ".join(unknown_static))

    cancelled_registered = sorted(page for page in CANCELLED_STATIC_PAGE_ROUTES if page in entries)
    if cancelled_registered:
        fail("Cancelled static HTML pages are still registered in Vue: " + ", ".join(cancelled_registered))

    vite_config = read(VUE_DIR / "vite.config.ts")
    if "outDir: '../v2-api/app/static/vue'" not in vite_config:
        fail("Vite build output must target v2-api/app/static/vue")
    if "base: '/vue/'" not in vite_config:
        fail("Vite base must be /vue/ for FastAPI hosting")

    main_py = read(ROOT / "v2-api" / "app" / "main.py")
    if '@app.get("/vue")' not in main_py or '@app.get("/vue/{full_path:path}")' not in main_py:
        fail("FastAPI must expose /vue and /vue/{full_path:path}")

    non_native = sorted(key for key, status in entries.items() if status != "native_vue")
    if args.strict_native and non_native:
        fail("Pages still running through legacy bridge: " + ", ".join(non_native))

    if args.strict_native:
        router_text = read(VUE_DIR / "src" / "router" / "index.ts")
        if "LegacyStaticPageView" in router_text:
            fail("Vue router must not reference LegacyStaticPageView in strict native mode")
        if "requiresEmbedded" in registry_text or "staticPath" in registry_text or "legacy_bridge" in registry_text:
            fail("Vue page registry must not keep static-page bridge fields in strict native mode")
        legacy_response_patterns = [
            'FileResponse(static_dir / "app_shell.html")',
            'FileResponse(static_dir / "project_board.html")',
            'FileResponse(static_dir / "claim_tasks.html")',
            'FileResponse(static_dir / "task_hall.html")',
            'FileResponse(static_dir / "construction.html")',
            'FileResponse(static_dir / "construction_cache.html")',
            'FileResponse(static_dir / "unmatched.html")',
            'FileResponse(static_dir / "sync_config.html")',
        ]
        for pattern in legacy_response_patterns:
            if pattern in main_py:
                fail(f"FastAPI still serves legacy static page: {pattern}")
        if 'request.query_params.get("embedded")' in main_py:
            fail("FastAPI workspace routes must ignore embedded static mode and serve Vue only")

    mojibake = find_mojibake()
    if args.strict_native and mojibake:
        fail("Possible mojibake remains in Vue source: " + ", ".join(mojibake))

    print("[OK] Vue shell and static page registry are wired.")
    print(f"[INFO] registered pages: {len(entries)}")
    print(f"[INFO] legacy bridge pages: {len(non_native)}")
    if mojibake:
        print("[WARN] possible mojibake remains in Vue source:")
        for item in mojibake:
            print(f"  - {item}")
    if non_native:
        print("[WARN] strict native migration is not complete:")
        for item in non_native:
            print(f"  - {item}: {entries[item]}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
