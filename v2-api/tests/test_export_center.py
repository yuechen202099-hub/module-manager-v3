from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

import app.main as main_module
from app.api.routes import auth, exports as export_routes, local_test
from app.core import security
from app.services import account_store, local_simulation
from app.services.export_center import (
    SUPPORTED_EXPORT_JOB_PAGE_SIZES,
    build_device_workbook,
)


def production_test_settings(**overrides) -> SimpleNamespace:
    values = {
        "app_env": "production",
        "allowed_origins": ["https://www.sgcc.online", "https://sgcc.online"],
        "trusted_hosts": ["testserver", "www.sgcc.online", "sgcc.online", "127.0.0.1", "localhost"],
        "trusted_proxy_hosts": {"testclient"},
        "security_frame_ancestors": "'self'",
        "state_backend": "json",
        "max_upload_mb": 20,
        "max_upload_files_per_request": 8,
        "photo_proxy_hosts": set(),
        "demo_auth_enabled": False,
        "admin_username": "root-admin",
        "admin_password": "RootPass12345",
        "admin_team_id": "north-team-01",
        "auth_users_path": "",
        "jwt_secret": "jwt-secret-for-export-center-test",
        "jwt_expire_minutes": 60,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def production_rbac_client(monkeypatch: pytest.MonkeyPatch, tmp_path) -> tuple[TestClient, dict[str, dict[str, str]]]:
    production_settings = production_test_settings(auth_users_path=str(tmp_path / "export-users.json"))
    monkeypatch.setattr(auth, "settings", production_settings)
    monkeypatch.setattr(account_store, "settings", production_settings)
    monkeypatch.setattr(security, "settings", production_settings)
    monkeypatch.setattr(main_module, "settings", production_settings)
    monkeypatch.setattr(local_test, "settings", production_settings)
    client = TestClient(main_module.create_app())

    admin_login = client.post(
        "/auth/login",
        json={"username": "root-admin", "password": "RootPass12345"},
    )
    assert admin_login.status_code == 200
    headers = {"admin": {"Authorization": f"bearer {admin_login.json()['data']['access_token']}"}}
    created = client.post(
        "/auth/users",
        headers=headers["admin"],
        json={
            "username": "constructor-a",
            "password": "ConstructPass12345",
            "name": "constructor-a",
            "roles": ["constructor"],
            "team_id": "north-team-01",
            "status": "active",
        },
    )
    assert created.status_code == 200
    constructor_login = client.post(
        "/auth/login",
        json={"username": "constructor-a", "password": "ConstructPass12345"},
    )
    assert constructor_login.status_code == 200
    headers["constructor"] = {
        "Authorization": f"bearer {constructor_login.json()['data']['access_token']}",
    }
    return client, headers


@pytest.mark.parametrize(
    ("kind", "values", "expected"),
    [
        ("terminal", ["00001234", "00001234", "", "00000000"], ["00001234"]),
        ("meter", ["00004567", " 00004567 ", None, "=cmd"], ["00004567"]),
        ("module", ["00007890", "00007890", "UNKNOWN"], ["00007890"]),
        ("collector", ["00009999", "00009998", "00000000"], ["00009998", "00009999"]),
    ],
)
def test_device_export_deduplicates_filters_sorts_and_keeps_text(kind: str, values: list[object], expected: list[str]) -> None:
    workbook_bytes = build_device_workbook(
        kind=kind,
        rows=values,
        project={"id": "project-1", "name": "North Project"},
        filters={"terminal": "T-1"},
    )

    workbook = load_workbook(BytesIO(workbook_bytes))
    sheet = workbook.active

    assert [cell.value for cell in sheet["A"][1:]] == expected
    assert all(cell.data_type == "s" for cell in sheet["A"][1:])
    assert all(cell.number_format == "@" for cell in sheet["A"][1:])
    assert workbook.properties.title == f"{kind} device export"
    assert "North Project" in (workbook.properties.subject or "")
    assert f"count={len(expected)}" in (workbook.properties.description or "")


def test_terminal_readiness_is_one_server_query_and_reports_blockers(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    client, headers = production_rbac_client(monkeypatch, tmp_path)
    calls: list[dict] = []

    class ReadinessRepository:
        def list_terminal_delivery_readiness(self, *, page: int, page_size: int, query: str = "") -> dict:
            calls.append({"page": page, "page_size": page_size, "query": query})
            return {
                "page": page,
                "page_size": page_size,
                "total": 1,
                "items": [
                    {
                        "terminal": "T-1",
                        "group_count": 4,
                        "constructed_count": 4,
                        "archived_count": 3,
                        "cache_ready_count": 3,
                        "status": "blocked",
                        "blockers": ["1 个资料组未归档"],
                    }
                ],
            }

    monkeypatch.setattr(export_routes, "state_repository", lambda: ReadinessRepository())

    response = client.get("/exports/terminal-readiness?page=1&page_size=20&query=T-1", headers=headers["admin"])

    assert response.status_code == 200
    assert response.json()["data"]["items"][0] == {
        "terminal": "T-1",
        "group_count": 4,
        "constructed_count": 4,
        "archived_count": 3,
        "cache_ready_count": 3,
        "status": "blocked",
        "blockers": ["1 个资料组未归档"],
    }
    assert calls == [{"page": 1, "page_size": 20, "query": "T-1"}]


@pytest.mark.parametrize("page_size", sorted(SUPPORTED_EXPORT_JOB_PAGE_SIZES))
def test_export_jobs_use_supported_page_sizes(monkeypatch: pytest.MonkeyPatch, tmp_path, page_size: int) -> None:
    client, headers = production_rbac_client(monkeypatch, tmp_path)
    calls: list[dict] = []

    class JobRepository:
        def list_export_jobs(self, *, page: int, page_size: int, job_type: str = "") -> dict:
            calls.append({"page": page, "page_size": page_size, "job_type": job_type})
            return {"page": page, "page_size": page_size, "total": 0, "items": []}

    monkeypatch.setattr(export_routes, "state_repository", lambda: JobRepository())

    response = client.get(f"/exports/jobs?page_size={page_size}", headers=headers["admin"])

    assert response.status_code == 200
    assert response.json()["data"]["page_size"] == page_size
    assert calls == [{"page": 1, "page_size": page_size, "job_type": ""}]


def test_export_jobs_reject_unsupported_page_size(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    client, headers = production_rbac_client(monkeypatch, tmp_path)

    response = client.get("/exports/jobs?page_size=10", headers=headers["admin"])

    assert response.status_code == 422


def test_constructor_cannot_create_or_download_export(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    client, headers = production_rbac_client(monkeypatch, tmp_path)

    create = client.post(
        "/exports/jobs",
        headers=headers["constructor"],
        json={"job_type": "device_terminal", "filters": {}},
    )
    download = client.get("/exports/jobs/job-1/download", headers=headers["constructor"])

    assert create.status_code == 403
    assert download.status_code == 403


def test_export_create_and_download_are_audited(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    client, headers = production_rbac_client(monkeypatch, tmp_path)
    events: list[tuple[str, str, dict]] = []

    class JobRepository:
        def create_export_job(self, *, job_type: str, filters: dict, actor: str) -> dict:
            return {
                "id": "job-1",
                "job_type": job_type,
                "status": "succeeded",
                "file_name": "terminal-devices.xlsx",
                "content": b"workbook-bytes",
            }

        def open_export_job_download(self, job_id: str, *, actor: str) -> dict:
            assert job_id == "job-1"
            return {
                "id": "job-1",
                "job_type": "device_terminal",
                "file_name": "terminal-devices.xlsx",
                "content": b"workbook-bytes",
                "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }

        def append_audit_event(self, action: str, actor: str, payload: dict) -> dict:
            events.append((action, actor, deepcopy(payload)))
            return {"id": f"audit-{len(events)}", "action": action, "actor": actor, "payload": payload}

    monkeypatch.setattr(export_routes, "state_repository", lambda: JobRepository())

    create = client.post(
        "/exports/jobs",
        headers=headers["admin"],
        json={"job_type": "device_terminal", "filters": {"terminal": "T-1"}},
    )
    download = client.get("/exports/jobs/job-1/download", headers=headers["admin"])

    assert create.status_code == 200
    assert create.json()["data"]["id"] == "job-1"
    assert download.status_code == 200
    assert download.content == b"workbook-bytes"
    assert events == [
        (
            "export_job_created",
            "root-admin",
            {"job_id": "job-1", "job_type": "device_terminal", "filters": {"terminal": "T-1"}},
        ),
        (
            "export_job_downloaded",
            "root-admin",
            {"job_id": "job-1", "job_type": "device_terminal", "file_name": "terminal-devices.xlsx"},
        ),
    ]
