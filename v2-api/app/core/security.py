from __future__ import annotations

import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from jose import JWTError, jwt

from app.core.config import settings

HASH_ITERATIONS = 260_000
HASH_ALGORITHM = "sha256"
JWT_ALGORITHM = "HS256"
AUTH_VALIDITY_TIMEZONE = ZoneInfo("Asia/Shanghai")


def hash_password(password: str, *, salt: str | None = None) -> str:
    if not password:
        raise ValueError("Password cannot be empty")
    salt_value = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        HASH_ALGORITHM,
        password.encode("utf-8"),
        bytes.fromhex(salt_value),
        HASH_ITERATIONS,
    ).hex()
    return f"pbkdf2_{HASH_ALGORITHM}${HASH_ITERATIONS}${salt_value}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    if not password or not stored_hash:
        return False
    if not stored_hash.startswith(f"pbkdf2_{HASH_ALGORITHM}$"):
        return hmac.compare_digest(password, stored_hash)
    try:
        _, iterations, salt, digest = stored_hash.split("$", 3)
        candidate = hashlib.pbkdf2_hmac(
            HASH_ALGORITHM,
            password.encode("utf-8"),
            bytes.fromhex(salt),
            int(iterations),
        ).hex()
        return hmac.compare_digest(candidate, digest)
    except (TypeError, ValueError):
        return False


def access_token_expires_at() -> datetime:
    now_local = datetime.now(UTC).astimezone(AUTH_VALIDITY_TIMEZONE)
    next_midnight_local = (now_local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return next_midnight_local.astimezone(UTC)


def create_access_token(user: dict[str, Any]) -> str:
    expires_at = access_token_expires_at()
    payload = {
        "sub": user["username"],
        "name": user.get("name") or user.get("display_name") or user["username"],
        "roles": list(user.get("roles") or []),
        "team_id": user.get("team_id") or settings.admin_team_id,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid access token") from exc
    if not payload.get("sub"):
        raise ValueError("Invalid access token")
    return payload
