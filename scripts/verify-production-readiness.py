from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_ENV_KEYS = {
    "APP_ENV",
    "APP_SECRET",
    "DEMO_AUTH_ENABLED",
    "DATABASE_URL",
    "JWT_SECRET",
    "ADMIN_USERNAME",
    "ADMIN_PASSWORD",
}

WEAK_VALUES = {
    "",
    "change-me",
    "changeme",
    "password",
    "admin",
    "admin123",
    "review123",
    "module_manager_password",
}


def fail(message: str) -> None:
    raise AssertionError(message)


def parse_env(path: Path) -> dict[str, str]:
    if not path.exists():
        fail(f"Env file not found: {path}")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().lstrip("\ufeff")] = value.strip().strip('"').strip("'")
    return values


def is_strong_secret(value: str) -> bool:
    if value.strip().lower() in WEAK_VALUES:
        return False
    if len(value) < 24:
        return False
    return bool(re.search(r"[A-Za-z]", value) and re.search(r"\d", value))


def is_strong_password(value: str) -> bool:
    if value.strip().lower() in WEAK_VALUES:
        return False
    return len(value) >= 12 and bool(re.search(r"[A-Za-z]", value) and re.search(r"\d", value))


def verify_infra_files() -> None:
    nginx = ROOT / "infra" / "nginx" / "module-manager-v2.conf"
    systemd = ROOT / "infra" / "module-manager-v2.service"
    server_doc = ROOT / "docs" / "SERVER_DEPLOYMENT_PREP.md"
    for path in [nginx, systemd, server_doc]:
        if not path.exists():
            fail(f"Missing deployment file: {path.relative_to(ROOT)}")
    nginx_text = nginx.read_text(encoding="utf-8")
    systemd_text = systemd.read_text(encoding="utf-8")
    server_doc_text = server_doc.read_text(encoding="utf-8")
    if "proxy_pass http://127.0.0.1:8000" not in nginx_text:
        fail("Nginx sample must proxy to local FastAPI on 127.0.0.1:8000")
    if "client_max_body_size" not in nginx_text:
        fail("Nginx sample must set client_max_body_size for manual image uploads")
    required_nginx_snippets = [
        "server_tokens off",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
        "Permissions-Policy",
        "proxy_set_header X-Forwarded-For",
        "proxy_set_header X-Forwarded-Proto",
    ]
    for snippet in required_nginx_snippets:
        if snippet not in nginx_text:
            fail(f"Nginx sample missing production hardening snippet: {snippet}")
    if "EnvironmentFile=/opt/module-manager-v2/.env" not in systemd_text:
        fail("systemd sample must load /opt/module-manager-v2/.env")
    if "uvicorn app.main:app" not in systemd_text:
        fail("systemd sample must start the FastAPI app with uvicorn")
    if "/docs" not in server_doc_text or "/openapi.json" not in server_doc_text:
        fail("server deployment prep must document that production API docs are disabled")


def verify_example_env(path: Path) -> None:
    values = parse_env(path)
    missing = sorted(REQUIRED_ENV_KEYS - set(values))
    if missing:
        fail("Missing required keys in .env.example: " + ", ".join(missing))
    if values.get("APP_ENV") != "local":
        fail(".env.example should remain local-oriented; production values belong in server .env")
    if values.get("DEMO_AUTH_ENABLED", "").lower() != "true":
        fail(".env.example should keep demo auth enabled for local walkthroughs")
    verify_infra_files()
    print(f"[OK] example env contains required keys: {path}")
    print("[OK] deployment samples are present and internally consistent")


def verify_production_env(path: Path) -> None:
    values = parse_env(path)
    missing = sorted(REQUIRED_ENV_KEYS - set(values))
    if missing:
        fail("Missing required production env keys: " + ", ".join(missing))
    app_env = values.get("APP_ENV", "").lower()
    if app_env not in {"prod", "production"}:
        fail("APP_ENV must be production before exposing real project data")
    if values.get("DEMO_AUTH_ENABLED", "").lower() != "false":
        fail("DEMO_AUTH_ENABLED must be false for production")
    app_secret = values.get("APP_SECRET", "")
    jwt_secret = values.get("JWT_SECRET", "")
    if not is_strong_secret(app_secret):
        fail("APP_SECRET must be a strong random value, at least 24 chars with letters and digits")
    if not is_strong_secret(jwt_secret):
        fail("JWT_SECRET must be a strong random value, at least 24 chars with letters and digits")
    if app_secret == jwt_secret:
        fail("APP_SECRET and JWT_SECRET must not be identical")
    if not is_strong_password(values.get("ADMIN_PASSWORD", "")):
        fail("ADMIN_PASSWORD must be changed to a strong password, at least 12 chars with letters and digits")
    if values.get("ADMIN_USERNAME", "").lower() in {"", "admin"}:
        fail("ADMIN_USERNAME should be changed from the demo/admin default")
    if "module_manager_password" in values.get("DATABASE_URL", ""):
        fail("DATABASE_URL still contains the default sample database password")
    if values.get("POSTGRES_PASSWORD", "").lower() in WEAK_VALUES:
        fail("POSTGRES_PASSWORD must be changed from the sample value")
    verify_infra_files()
    print(f"[OK] production env passes safety checks: {path}")
    print("[OK] deployment samples are present and internally consistent")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify deployment readiness for Module Manager V2.")
    parser.add_argument("--example", action="store_true", help="Check .env.example and deployment sample completeness.")
    parser.add_argument("--env", type=Path, default=None, help="Check a production .env file strictly.")
    args = parser.parse_args()
    if args.example:
        verify_example_env(ROOT / ".env.example")
    elif args.env:
        verify_production_env(args.env)
    else:
        default_env = ROOT / ".env"
        if default_env.exists():
            verify_production_env(default_env)
        else:
            verify_example_env(ROOT / ".env.example")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
