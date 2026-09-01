from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routes.material_exports import router
from app.api.schemas.material_export import (
    FileAcknowledgeRequest,
    ReserveJobRequest,
    TaskIdsRequest,
    TerminalSettingRequest,
)
from app.core.security import create_access_token


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
