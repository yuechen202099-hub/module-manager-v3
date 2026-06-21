from __future__ import annotations

import json
import re
import threading
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.security import hash_password, verify_password

VALID_ROLES = {"admin", "reviewer", "constructor"}
VALID_STATUSES = {"active", "disabled"}
_lock = threading.RLock()
_memory_users: dict[str, dict[str, Any]] = {}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def normalize_team_id(team_id: str | None) -> str:
    value = re.sub(r"[^0-9A-Za-z_-]+", "-", str(team_id or "").strip()).strip("-").lower()
    return value or "default-team"


def normalize_username(username: str) -> str:
    value = re.sub(r"[^0-9A-Za-z_.@-]+", "-", str(username or "").strip()).strip("-").lower()
    if not value:
        raise ValueError("Username is required")
    if len(value) > 64:
        raise ValueError("Username is too long")
    return value


def users_path() -> Path | None:
    configured = settings.auth_users_path.strip()
    if not configured:
        return None
    return Path(configured)


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "username": user["username"],
        "name": user.get("name") or user["username"],
        "roles": list(user.get("roles") or []),
        "team_id": normalize_team_id(user.get("team_id")),
        "status": user.get("status") or "active",
        "home": user.get("home") or "/app",
        "created_at": user.get("created_at"),
        "updated_at": user.get("updated_at"),
        "last_login_at": user.get("last_login_at"),
        "last_login_ip": user.get("last_login_ip"),
        "last_login_device": user.get("last_login_device"),
    }


def _default_admin_user() -> dict[str, Any]:
    now = now_iso()
    return {
        "username": normalize_username(settings.admin_username),
        "name": "项目管理员",
        "roles": ["admin"],
        "team_id": normalize_team_id(settings.admin_team_id),
        "status": "active",
        "home": "/app",
        "password_hash": hash_password(settings.admin_password),
        "created_at": now,
        "updated_at": now,
        "last_login_at": None,
        "last_login_ip": None,
        "last_login_device": None,
    }


def _read_users_unlocked() -> dict[str, dict[str, Any]]:
    path = users_path()
    if path is None:
        return deepcopy(_memory_users)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_users = payload.get("users") if isinstance(payload, dict) else None
    if not isinstance(raw_users, list):
        return {}
    users: dict[str, dict[str, Any]] = {}
    for raw_user in raw_users:
        if not isinstance(raw_user, dict):
            continue
        try:
            username = normalize_username(raw_user.get("username"))
        except ValueError:
            continue
        roles = [role for role in raw_user.get("roles", []) if role in VALID_ROLES]
        if not roles:
            roles = ["reviewer"]
        user = {
            **raw_user,
            "username": username,
            "name": str(raw_user.get("name") or username),
            "roles": sorted(set(roles)),
            "team_id": normalize_team_id(raw_user.get("team_id")),
            "status": raw_user.get("status") if raw_user.get("status") in VALID_STATUSES else "active",
            "home": raw_user.get("home") or "/app",
        }
        if user.get("password_hash"):
            users[username] = user
    return users


def _write_users_unlocked(users: dict[str, dict[str, Any]]) -> None:
    path = users_path()
    if path is None:
        _memory_users.clear()
        _memory_users.update(deepcopy(users))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "updated_at": now_iso(),
        "users": [users[key] for key in sorted(users)],
    }
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def ensure_user_store() -> dict[str, dict[str, Any]]:
    with _lock:
        users = _read_users_unlocked()
        admin = _default_admin_user()
        existing = users.get(admin["username"])
        if existing is None:
            users[admin["username"]] = admin
            _write_users_unlocked(users)
        return users


def list_users() -> list[dict[str, Any]]:
    users = ensure_user_store()
    return [public_user(users[key]) for key in sorted(users)]


def get_user(username: str) -> dict[str, Any] | None:
    users = ensure_user_store()
    user = users.get(normalize_username(username))
    return deepcopy(user) if user else None


def authenticate_user(username: str, password: str, *, ip: str = "", device: str = "") -> dict[str, Any] | None:
    user = get_user(username)
    if not user or user.get("status") != "active":
        return None
    if not verify_password(password, user.get("password_hash", "")):
        return None
    update_last_login(user["username"], ip=ip, device=device)
    return get_user(user["username"])


def upsert_user(
    *,
    username: str,
    password: str | None = None,
    name: str = "",
    roles: list[str] | None = None,
    team_id: str = "",
    status: str = "active",
) -> dict[str, Any]:
    normalized_username = normalize_username(username)
    clean_roles = sorted({role for role in (roles or ["reviewer"]) if role in VALID_ROLES})
    if not clean_roles:
        raise ValueError("At least one valid role is required")
    if status not in VALID_STATUSES:
        raise ValueError("Invalid user status")
    with _lock:
        users = ensure_user_store()
        existing = users.get(normalized_username)
        if existing is None and not password:
            raise ValueError("Password is required for new users")
        now = now_iso()
        user = {
            **(existing or {}),
            "username": normalized_username,
            "name": name.strip() or normalized_username,
            "roles": clean_roles,
            "team_id": normalize_team_id(team_id),
            "status": status,
            "home": "/app",
            "updated_at": now,
            "created_at": (existing or {}).get("created_at") or now,
            "last_login_at": (existing or {}).get("last_login_at"),
            "last_login_ip": (existing or {}).get("last_login_ip"),
            "last_login_device": (existing or {}).get("last_login_device"),
        }
        if password:
            user["password_hash"] = hash_password(password)
        users[normalized_username] = user
        _write_users_unlocked(users)
        return public_user(user)


def update_user_password(username: str, password: str) -> dict[str, Any]:
    normalized_username = normalize_username(username)
    with _lock:
        users = ensure_user_store()
        if normalized_username not in users:
            raise KeyError(username)
        users[normalized_username]["password_hash"] = hash_password(password)
        users[normalized_username]["updated_at"] = now_iso()
        _write_users_unlocked(users)
        return public_user(users[normalized_username])


def delete_user(username: str) -> dict[str, Any]:
    normalized_username = normalize_username(username)
    with _lock:
        users = ensure_user_store()
        user = users.get(normalized_username)
        if user is None:
            raise KeyError(username)
        remaining_admins = [
            item
            for key, item in users.items()
            if key != normalized_username
            and item.get("status") == "active"
            and "admin" in set(item.get("roles") or [])
        ]
        if "admin" in set(user.get("roles") or []) and not remaining_admins:
            raise ValueError("Cannot delete the last active administrator")
        deleted = public_user(user)
        del users[normalized_username]
        _write_users_unlocked(users)
        return deleted


def update_last_login(username: str, *, ip: str = "", device: str = "") -> None:
    normalized_username = normalize_username(username)
    with _lock:
        users = ensure_user_store()
        if normalized_username not in users:
            return
        users[normalized_username]["last_login_at"] = now_iso()
        users[normalized_username]["last_login_ip"] = str(ip or "").strip()[:128]
        users[normalized_username]["last_login_device"] = str(device or "").strip()[:256]
        _write_users_unlocked(users)
