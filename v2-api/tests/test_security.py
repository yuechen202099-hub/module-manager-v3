from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from jose import jwt

from app.core import security
from app.core.config import settings


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        current = datetime(2026, 6, 26, 1, 30, tzinfo=UTC)
        if tz is None:
            return current.replace(tzinfo=None)
        return current.astimezone(tz)


def test_access_token_expires_at_next_shanghai_midnight(monkeypatch) -> None:
    monkeypatch.setattr(security, "datetime", FixedDateTime)
    monkeypatch.setattr(settings, "jwt_expire_minutes", 60 * 24 * 30)

    token = security.create_access_token({"username": "constructor", "roles": ["constructor"]})
    payload = jwt.get_unverified_claims(token)
    expires_at = datetime.fromtimestamp(payload["exp"], UTC)

    expected = datetime(2026, 6, 27, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(UTC)
    assert expires_at == expected
