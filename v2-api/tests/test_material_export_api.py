from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.api.routes.material_exports as material_exports
from app.api.routes.material_exports import router
from app.api.schemas.material_export import (
    FileAcknowledgeRequest,
    ReserveJobRequest,
    TaskIdsRequest,
    TerminalSettingRequest,
)
from app.core.security import create_access_token


def _admin_headers(**extra: str) -> dict[str, str]:
    token = create_access_token(
        {
            "username": "admin",
            "roles": ["admin"],
            "team_id": "team-a",
        }
    )
    return {"Authorization": f"Bearer {token}", **extra}


def test_new_material_export_jobs_are_temporarily_rejected(monkeypatch) -> None:
    @dataclass(frozen=True)
    class ReservedJob:
        job_id: str

    class Context:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return False

    class SessionFactory:
        @staticmethod
        def begin():
            return Context()

    monkeypatch.setattr(material_exports, "SessionLocal", SessionFactory)
    monkeypatch.setattr(
        material_exports,
        "_service",
        lambda *_args: SimpleNamespace(
            reserve_job=lambda **_kwargs: ReservedJob(job_id="job-1")
        ),
    )
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).post(
        "/material-exports/jobs",
        json={"task_ids": ["1"], "preflight_fingerprint": "a" * 64},
        headers=_admin_headers(),
    )

    assert response.status_code == 503


def test_server_photo_stream_is_temporarily_rejected_before_bytes_are_read(
    monkeypatch,
) -> None:
    authorize_calls: list[str] = []

    def authorize(**_kwargs):
        authorize_calls.append("authorize")
        return SimpleNamespace(content_type="image/jpeg", byte_size=3)

    monkeypatch.setattr(material_exports, "authorize_material_export_stream", authorize)
    monkeypatch.setattr(material_exports, "build_export_stream", lambda *_args, **_kwargs: iter([b"abc"]))
    monkeypatch.setattr(material_exports, "record_material_export_stream_event", lambda **_kwargs: None)
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get(
        "/material-exports/jobs/job-1/files/file-1",
        headers=_admin_headers(**{"X-Material-Export-Lease": "lease-1"}),
    )

    assert response.status_code == 503
    assert authorize_calls == []


def test_strict_requests_reject_spoofed_identity_and_invalid_values() -> None:
    with pytest.raises(ValidationError):
        TerminalSettingRequest.model_validate(
            {"requested_collector_count": -1, "actor": "spoof"}
        )
    with pytest.raises(ValidationError):
        TaskIdsRequest(task_ids=[])
    with pytest.raises(ValidationError):
        TaskIdsRequest(task_ids=[str(index) for index in range(501)])
    with pytest.raises(ValidationError):
        ReserveJobRequest(task_ids=["1"], preflight_fingerprint="short")
    with pytest.raises(ValidationError):
        FileAcknowledgeRequest(byte_size=1, sha256="not-a-sha")


def test_constructor_cannot_read_or_mutate_material_exports() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    token = create_access_token(
        {
            "username": "worker",
            "roles": ["constructor"],
            "team_id": "team-a",
        }
    )
    headers = {"Authorization": f"Bearer {token}"}
    for path, body in (
        ("/material-exports/preflight", {"task_ids": ["1"]}),
        (
            "/material-exports/jobs",
            {"task_ids": ["1"], "preflight_fingerprint": "a" * 64},
        ),
        ("/material-exports/terminal-summaries", {"task_ids": ["1"]}),
    ):
        assert client.post(path, json=body, headers=headers).status_code == 403


def test_material_export_router_exposes_only_new_non_zip_contract() -> None:
    paths = {route.path for route in router.routes}
    assert "/material-exports/preflight" in paths
    assert "/material-exports/jobs" in paths
    assert "/material-exports/jobs/{job_id}/files/{file_id}" in paths
    assert all("zip" not in path.lower() for path in paths)
    assert all(not path.startswith("/exports") for path in paths)
