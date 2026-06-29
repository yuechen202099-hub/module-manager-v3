from __future__ import annotations

import hashlib
import json
import threading
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from app.core.config import settings
from app.services.account_store import normalize_team_id, normalize_username

_lock = threading.RLock()
_memory_bindings: dict[str, dict[str, Any]] = {}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def binding_store_path() -> Path | None:
    configured = settings.wechat_binding_store_path.strip()
    if configured:
        return Path(configured)
    auth_path = settings.auth_users_path.strip()
    if auth_path:
        path = Path(auth_path)
        return path.with_name(f"{path.stem}.wechat-bindings.json")
    return None


def deterministic_openid(code: str) -> str:
    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()[:24]
    return f"mp_{digest}"


def resolve_openid(code: str) -> str:
    clean_code = str(code or "").strip()
    if not clean_code:
        raise ValueError("Wechat code is required")
    appid = settings.wechat_miniprogram_appid.strip()
    secret = settings.wechat_miniprogram_secret.strip()
    if not appid or not secret:
        if settings.app_env.lower() in {"prod", "production"}:
            raise ValueError("Wechat miniprogram credentials are not configured")
        return deterministic_openid(clean_code)
    query = urlencode(
        {
            "appid": appid,
            "secret": secret,
            "js_code": clean_code,
            "grant_type": "authorization_code",
        }
    )
    with urlopen(f"https://api.weixin.qq.com/sns/jscode2session?{query}", timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))
    openid = str(payload.get("openid") or "").strip()
    if not openid:
        message = payload.get("errmsg") or "Wechat login failed"
        raise ValueError(str(message))
    return openid


def _read_bindings_unlocked() -> dict[str, dict[str, Any]]:
    path = binding_store_path()
    if path is None:
        return deepcopy(_memory_bindings)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_bindings = payload.get("bindings") if isinstance(payload, dict) else None
    if not isinstance(raw_bindings, list):
        return {}
    bindings: dict[str, dict[str, Any]] = {}
    for item in raw_bindings:
        if not isinstance(item, dict):
            continue
        openid = str(item.get("openid") or "").strip()
        username = str(item.get("username") or "").strip()
        if not openid or not username:
            continue
        bindings[openid] = {
            **item,
            "openid": openid,
            "username": normalize_username(username),
            "team_id": normalize_team_id(item.get("team_id")),
        }
    return bindings


def _write_bindings_unlocked(bindings: dict[str, dict[str, Any]]) -> None:
    path = binding_store_path()
    if path is None:
        _memory_bindings.clear()
        _memory_bindings.update(deepcopy(bindings))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "updated_at": now_iso(),
        "bindings": [bindings[key] for key in sorted(bindings)],
    }
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def bind_code_to_user(code: str, user: dict[str, Any]) -> dict[str, Any]:
    openid = resolve_openid(code)
    username = normalize_username(user.get("username"))
    now = now_iso()
    with _lock:
        bindings = _read_bindings_unlocked()
        existing = bindings.get(openid) or {}
        binding = {
            **existing,
            "openid": openid,
            "username": username,
            "team_id": normalize_team_id(user.get("team_id")),
            "bound_at": existing.get("bound_at") or now,
            "updated_at": now,
        }
        bindings[openid] = binding
        _write_bindings_unlocked(bindings)
        return deepcopy(binding)


def get_binding_for_code(code: str) -> dict[str, Any] | None:
    openid = resolve_openid(code)
    with _lock:
        binding = _read_bindings_unlocked().get(openid)
        return deepcopy(binding) if binding else None
