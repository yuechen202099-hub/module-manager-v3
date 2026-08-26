from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from jose import jwt

from app import main as main_module
from app.api.routes import collector_transfer as collector_routes
from app.core import security
from app.core.config import settings
from app.services import collector_transfer as collector_service


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


def test_constructor_is_rejected_before_collector_session_file_or_service_access(monkeypatch) -> None:
    """Catches any collector endpoint authorizing after opening storage or entering domain service code."""
    touched: list[str] = []

    @contextmanager
    def tracked_session():
        touched.append("session")
        yield object()

    class ForbiddenService:
        def __init__(self, **_payload):
            touched.append("service")
            raise AssertionError("domain service reached before administrator authorization")

    def forbidden_save(**_payload):
        touched.append("file")
        raise AssertionError("save_image_bytes reached before administrator authorization")

    monkeypatch.setattr(collector_routes, "SessionLocal", tracked_session)
    monkeypatch.setattr(collector_routes, "save_image_bytes", forbidden_save)
    monkeypatch.setattr(collector_service, "PostgresCollectorTransferService", ForbiddenService)
    client = TestClient(main_module.create_app(), raise_server_exceptions=False)
    token = security.create_access_token(
        {
            "sub": "constructor",
            "username": "constructor",
            "roles": ["constructor"],
            "team_id": "team-1",
        }
    )
    headers = {"Authorization": f"bearer {token}"}
    requests = [
        ("GET", "/collector-transfer/projects", {}),
        ("POST", "/collector-transfer/runs", {"json": {"project_id": "project-1", "name": "盘点"}}),
        ("GET", "/collector-transfer/runs", {}),
        ("GET", "/collector-transfer/runs/run-1", {}),
        (
            "POST",
            "/collector-transfer/inventory/scan",
            {"json": {"project_id": "project-1", "collector_no": "C-001"}},
        ),
        ("GET", "/collector-transfer/inventory?project_id=project-1", {}),
        ("POST", "/collector-transfer/runs/run-1/allocate", {}),
        ("POST", "/collector-transfer/assignments/assignment-1/rollback", {}),
        ("GET", "/collector-transfer/workbench/terminals", {}),
        (
            "POST",
            "/collector-transfer/workbench/terminals/open",
            {
                "json": {
                    "terminal_key": "opaque-key",
                    "project_id": "project-1",
                    "terminal_code": "T-001",
                    "source_revision": "a" * 64,
                }
            },
        ),
        (
            "POST",
            "/collector-transfer/review-workbench/terminals/open",
            {"json": {"terminal_key": "opaque-key", "source_revision": "a" * 64}},
        ),
        ("GET", "/collector-transfer/workbench/terminals/terminal-1", {}),
        ("POST", "/collector-transfer/workbench/terminals/terminal-1/replace-missing", {}),
        ("POST", "/collector-transfer/workbench/terminals/terminal-1/refresh", {}),
        ("GET", "/collector-transfer/runs/run-1/workbench", {}),
        ("GET", "/collector-transfer/runs/run-1/workbench/terminal-1", {}),
        (
            "PATCH",
            "/collector-transfer/workbench/items/item-1",
            {"json": {"completed": True}},
        ),
        (
            "POST",
            "/collector-transfer/inventory",
            {
                "data": {"project_id": "project-1", "collector_no": "C-001"},
                "files": {"file": ("collector.jpg", b"image-bytes", "image/jpeg")},
            },
        ),
    ]

    responses = [
        client.request(method, path, headers=headers, **kwargs)
        for method, path, kwargs in requests
    ]

    assert [response.status_code for response in responses] == [403] * len(requests)
    assert all(response.json()["error"]["code"] == "forbidden" for response in responses)
    assert touched == []
