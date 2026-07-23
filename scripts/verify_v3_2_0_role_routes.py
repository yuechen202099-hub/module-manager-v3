from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def main() -> int:
    user_role_type = read_text("v2-web/src/api/types.ts")
    static_pages = read_text("v2-web/src/router/staticPages.ts")
    router_source = read_text("v2-web/src/router/index.ts")
    account_page = read_text("v2-web/src/views/AccountManagementView.vue")

    assert "'reviewer'" not in user_role_type
    assert "审阅工作台" not in static_pages
    assert "path: '/global-search'" in router_source
    assert "/global-search?group_id=" in router_source
    assert "value: 'reviewer'" not in account_page

    print("[OK] V3.2.0 role and legacy route checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
