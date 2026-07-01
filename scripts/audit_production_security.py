from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEAK_VALUES = {
    "",
    "change-me",
    "changeme",
    "admin",
    "admin123",
    "password",
    "module_manager_password",
    "review123",
    "construct123",
}
REQUIRED_KEYS = {
    "JWT_SECRET",
    "ADMIN_PASSWORD",
    "DATABASE_URL",
}
AUDITED_KEYS = REQUIRED_KEYS | {
    "APP_ENV",
    "APP_SECRET",
    "DEMO_AUTH_ENABLED",
    "SECURITY_ALLOWED_ORIGINS",
    "SECURITY_TRUSTED_HOSTS",
    "PHOTO_PROXY_ALLOWED_HOSTS",
}
PRODUCTION_DOMAINS = {
    "https://www.sgcc.online",
    "https://sgcc.online",
}
PRODUCTION_HOSTS = {
    "www.sgcc.online",
    "sgcc.online",
}


def parse_env(path: Path) -> dict[str, str]:
    if not path.exists():
        raise AssertionError(f"Env file not found: {path}")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def is_weak_value(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in WEAK_VALUES


def audit(env: dict[str, str], env_path: Path) -> list[str]:
    failures: list[str] = []

    missing = sorted(key for key in AUDITED_KEYS if key not in env or env[key].strip() == "")
    if missing:
        failures.append("Missing or empty required production settings: " + ", ".join(missing))

    app_env = env.get("APP_ENV", "").strip().lower()
    if app_env not in {"prod", "production"}:
        failures.append("APP_ENV must be prod or production")

    for key in sorted(REQUIRED_KEYS | {"APP_SECRET"}):
        value = env.get(key, "")
        if is_weak_value(value):
            failures.append(f"{key} must not use an empty or weak default value")

    for key in ["JWT_SECRET", "APP_SECRET"]:
        value = env.get(key, "")
        if value and len(value) < 32:
            failures.append(f"{key} must be at least 32 characters")

    admin_password = env.get("ADMIN_PASSWORD", "")
    if is_weak_value(admin_password):
        failures.append("ADMIN_PASSWORD must be changed from the default weak password")

    database_url = env.get("DATABASE_URL", "")
    if any(weak in database_url.lower() for weak in WEAK_VALUES if weak):
        failures.append("DATABASE_URL must not contain a weak default credential")

    if env.get("DEMO_AUTH_ENABLED", "").strip().lower() == "true":
        failures.append("DEMO_AUTH_ENABLED must not be true in production")

    origins = split_csv(env.get("SECURITY_ALLOWED_ORIGINS", ""))
    if "*" in origins:
        failures.append("SECURITY_ALLOWED_ORIGINS must not contain * in production")
    if not (PRODUCTION_DOMAINS & set(origins)):
        failures.append(
            "SECURITY_ALLOWED_ORIGINS must include https://www.sgcc.online or https://sgcc.online"
        )

    trusted_hosts = split_csv(env.get("SECURITY_TRUSTED_HOSTS", ""))
    normalized_hosts = {host.removeprefix("https://").removeprefix("http://") for host in trusted_hosts}
    if "*" in trusted_hosts or "*" in normalized_hosts:
        failures.append("SECURITY_TRUSTED_HOSTS must not contain * in production")
    if not (PRODUCTION_HOSTS & normalized_hosts):
        failures.append("SECURITY_TRUSTED_HOSTS must include www.sgcc.online or sgcc.online")

    photo_hosts = split_csv(env.get("PHOTO_PROXY_ALLOWED_HOSTS", ""))
    if not photo_hosts:
        failures.append(
            "PHOTO_PROXY_ALLOWED_HOSTS must list real external photo source domains; "
            "production photo proxy rejects external fallback photos when the allowlist is empty"
        )

    if failures:
        failures.insert(0, f"Production security audit failed for {env_path}")
    return failures


def main() -> int:
    env_path = Path(os.environ.get("SECURITY_ENV_PATH") or ".env")
    if not env_path.is_absolute():
        env_path = ROOT / env_path
    try:
        parsed = parse_env(env_path)
        for key, value in parsed.items():
            os.environ.setdefault(key, value)
        failures = audit(dict(os.environ), env_path)
    except AssertionError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    if failures:
        print("[FAIL] " + failures[0], file=sys.stderr)
        for failure in failures[1:]:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(f"[OK] production security audit passed: {env_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
