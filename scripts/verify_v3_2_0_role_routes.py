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
    services_source = read_text("v2-web/src/api/services.ts")
    auth_store_source = read_text("v2-web/src/stores/auth.ts")

    assert "'reviewer'" not in user_role_type
    assert "task-hall" in router_source
    assert "path: '/global-search'" in router_source
    assert "/global-search?group_id=" in router_source
    assert "value: 'reviewer'" not in account_page
    assert "function invalidateLegacySession" in services_source
    assert "function normalizeLegacySessionRoles" in services_source
    assert "export function readLegacySessionAccessToken" in services_source
    assert "localStorage.getItem('module_manager_reviewer') || 'admin'" not in services_source
    assert "if (!session?.user) return mockUser" not in services_source
    assert "services.readLegacySessionAccessToken()" in auth_store_source
    assert "JSON.parse(localStorage.getItem('module_manager_session')" not in auth_store_source

    print("[OK] V3.2.0 role and legacy route checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
