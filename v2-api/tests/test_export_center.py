from __future__ import annotations

import os
import stat
import threading
import inspect
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.responses import FileResponse
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy.exc import IntegrityError

import app.main as main_module
from app import models
from app.api.routes import auth, exports as export_routes, local_test
from app.core import security
from app.services import account_store, export_center as export_center_service, local_simulation
from app.services.delivery_package_queue import DeliveryPackageNotReady
from app.services.final_delivery_export import group_is_formally_archived
from app.services.export_center import (
    SUPPORTED_EXPORT_JOB_PAGE_SIZES,
    build_device_workbook,
)
from app.services.state_repository import JsonStateRepository, PostgresStateRepository


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
        def list_export_jobs(
            self,
            *,
            page: int,
            page_size: int,
            category: str = "",
            job_types: list[str] | None = None,
            status: list[str] | None = None,
        ) -> dict:
            calls.append(
                {
                    "page": page,
                    "page_size": page_size,
                    "category": category,
                    "job_types": list(job_types or []),
                    "status": list(status or []),
                }
            )
            return {"page": page, "page_size": page_size, "total": 0, "items": []}

    monkeypatch.setattr(export_routes, "state_repository", lambda: JobRepository())

    response = client.get(f"/exports/jobs?page_size={page_size}", headers=headers["admin"])

    assert response.status_code == 200
    assert response.json()["data"]["page_size"] == page_size
    assert calls == [{"page": 1, "page_size": page_size, "category": "", "job_types": [], "status": []}]


def test_export_jobs_forward_server_side_filters(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    client, headers = production_rbac_client(monkeypatch, tmp_path)
    calls: list[dict] = []

    class JobRepository:
        def list_export_jobs(
            self,
            *,
            page: int,
            page_size: int,
            category: str = "",
            job_types: list[str] | None = None,
            status: list[str] | None = None,
        ) -> dict:
            calls.append(
                {
                    "page": page,
                    "page_size": page_size,
                    "category": category,
                    "job_types": list(job_types or []),
                    "status": list(status or []),
                }
            )
            return {"page": page, "page_size": page_size, "total": 3, "items": []}

    monkeypatch.setattr(export_routes, "state_repository", lambda: JobRepository())

    response = client.get(
        "/exports/jobs?page=2&page_size=50&category=business&job_types=task_detail,exception_meter&status=pending,failed",
        headers=headers["admin"],
    )

    assert response.status_code == 200
    assert response.json()["data"]["total"] == 3
    assert calls == [
        {
            "page": 2,
            "page_size": 50,
            "category": "business",
            "job_types": ["task_detail", "exception_meter"],
            "status": ["pending", "failed"],
        }
    ]


def test_export_jobs_reject_unsupported_page_size(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    client, headers = production_rbac_client(monkeypatch, tmp_path)

    response = client.get("/exports/jobs?page_size=10", headers=headers["admin"])

    assert response.status_code == 422


def test_postgres_export_jobs_include_created_by() -> None:
    repository = PostgresStateRepository()
    row = models.ExportJob(
        id=uuid4(),
        team_id="north-team-01",
        project_id=uuid4(),
        job_type="device_terminal",
        status=models.JobStatus.SUCCEEDED,
        file_name="terminal-devices.xlsx",
        filter_snapshot={"terminal": "T-1"},
        request_key="request-1",
        row_count=12,
        progress=100,
        error_message="",
        params={"created_by": "root-admin"},
    )

    class FakeScalars:
        def all(self):
            return [row]

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, *_args, **_kwargs):
            return 1

        def scalars(self, *_args, **_kwargs):
            return FakeScalars()

    repository._session = lambda: FakeSession()

    page = repository.list_export_jobs(page=1, page_size=20)

    assert page["items"][0]["created_by"] == "root-admin"


def test_postgres_create_export_job_integrity_fallback_keeps_existing_created_by(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = PostgresStateRepository()
    existing = models.ExportJob(
        id=uuid4(),
        team_id="north-team-01",
        project_id=uuid4(),
        job_type="device_terminal",
        status=models.JobStatus.SUCCEEDED,
        file_name="terminal-devices.xlsx",
        filter_snapshot={"terminal": "T-1"},
        request_key="request-1",
        row_count=12,
        progress=100,
        error_message="",
        params={"created_by": "other-admin", "terminal": "T-1", "size_bytes": 3},
    )

    class FakeSession:
        def __init__(self):
            self.scalar_calls = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, *_args, **_kwargs):
            self.scalar_calls += 1
            return None if self.scalar_calls == 1 else existing

        def add(self, _row):
            return None

        def flush(self):
            raise IntegrityError("insert into export_jobs", {}, Exception("duplicate"))

        def rollback(self):
            return None

    monkeypatch.setattr(repository, "_session", lambda: FakeSession())
    monkeypatch.setattr(repository, "_export_project_id", lambda _session: uuid4())
    monkeypatch.setattr(
        export_center_service,
        "build_inline_export_content",
        lambda *_args, **_kwargs: (b"xlsx", "terminal-devices.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    )
    monkeypatch.setattr(export_center_service, "write_export_content", lambda *_args, **_kwargs: ("temp/export.xlsx", "sha256", 3))
    orphaned_paths: list[str] = []
    monkeypatch.setattr(
        "app.services.state_repository._remove_orphan_export_content",
        lambda path: orphaned_paths.append(str(path)),
    )

    job = repository.create_export_job(
        job_type="device_terminal",
        filters={"terminal": "T-1"},
        actor="current-admin",
    )

    assert job["created"] is False
    assert job["created_by"] == "other-admin"
    assert orphaned_paths == ["temp/export.xlsx"]


def test_pg_inline_export_commit_error_removes_only_new_orphan_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = PostgresStateRepository()
    generated_path = tmp_path / "new-inline-export.xlsx"
    reused_path = tmp_path / "reused-inline-export.xlsx"
    reused_path.write_bytes(b"existing export")
    transaction_error = RuntimeError("commit failed")

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, *_args, **_kwargs):
            return None

        def add(self, _row):
            return None

        def flush(self):
            return None

        def commit(self):
            raise transaction_error

    monkeypatch.setattr(repository, "_session", lambda: FakeSession())
    monkeypatch.setattr(repository, "_export_project_id", lambda _session: uuid4())
    monkeypatch.setattr(
        export_center_service,
        "build_inline_export_content",
        lambda *_args, **_kwargs: (
            b"new export",
            generated_path.name,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    )

    def write_inline_content(content: bytes, **_kwargs):
        generated_path.write_bytes(content)
        return str(generated_path), "sha256", len(content)

    monkeypatch.setattr(export_center_service, "write_export_content", write_inline_content)
    removed_paths: list[Path] = []

    def remove_orphan_content(path_value: str) -> None:
        path = Path(path_value)
        removed_paths.append(path)
        path.unlink(missing_ok=True)

    monkeypatch.setattr(
        "app.services.state_repository._remove_orphan_export_content",
        remove_orphan_content,
    )

    with pytest.raises(RuntimeError, match="commit failed") as exc_info:
        repository.create_export_job(
            job_type="device_terminal",
            filters={"terminal": "T-1"},
            actor="root-admin",
        )

    assert exc_info.value is transaction_error
    assert exc_info.traceback[-1].name == "commit"
    assert removed_paths == [generated_path]
    assert not generated_path.exists()
    assert reused_path.read_bytes() == b"existing export"


def test_terminal_readiness_route_includes_latest_generated_at(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    client, headers = production_rbac_client(monkeypatch, tmp_path)

    class ReadinessRepository:
        def list_terminal_delivery_readiness(self, *, page: int, page_size: int, query: str = "") -> dict:
            return {
                "page": page,
                "page_size": page_size,
                "total": 1,
                "items": [
                    {
                        "terminal": "T-1",
                        "group_count": 2,
                        "constructed_count": 2,
                        "archived_count": 2,
                        "cache_ready_count": 2,
                        "status": "ready",
                        "blockers": [],
                        "latest_generated_at": "2026-07-23T08:09:10+00:00",
                    }
                ],
            }

    monkeypatch.setattr(export_routes, "state_repository", lambda: ReadinessRepository())

    response = client.get("/exports/terminal-readiness", headers=headers["admin"])

    assert response.status_code == 200
    assert response.json()["data"]["items"][0]["latest_generated_at"] == "2026-07-23T08:09:10+00:00"


def test_json_export_jobs_filter_by_category_job_types_and_status(monkeypatch: pytest.MonkeyPatch) -> None:
    team_id = "team-export-jobs-filtering"
    state = local_simulation.blank_state(team_id)
    state["export_jobs"] = [
        {
            "id": "job-terminal",
            "job_type": "final_delivery",
            "status": "succeeded",
            "file_name": "final-delivery.zip",
            "row_count": 0,
            "progress": 100,
            "error_message": "",
            "filter_snapshot": {"terminal": "T-1"},
            "request_key": "req-terminal",
            "created_by": "root-admin",
            "created_at": "2026-07-23T10:00:00+00:00",
            "updated_at": "2026-07-23T10:00:00+00:00",
            "finished_at": "2026-07-23T10:00:01+00:00",
        },
        {
            "id": "job-business-match",
            "job_type": "task_detail",
            "status": "failed",
            "file_name": "task-detail.xlsx",
            "row_count": 12,
            "progress": 100,
            "error_message": "missing row",
            "filter_snapshot": {"task_id": 22},
            "request_key": "req-business-match",
            "created_by": "root-admin",
            "created_at": "2026-07-23T11:00:00+00:00",
            "updated_at": "2026-07-23T11:00:00+00:00",
            "finished_at": "2026-07-23T11:00:01+00:00",
        },
        {
            "id": "job-business-other-status",
            "job_type": "exception_meter",
            "status": "succeeded",
            "file_name": "exception-meter.xlsx",
            "row_count": 2,
            "progress": 100,
            "error_message": "",
            "filter_snapshot": {},
            "request_key": "req-business-other-status",
            "created_by": "root-admin",
            "created_at": "2026-07-23T12:00:00+00:00",
            "updated_at": "2026-07-23T12:00:00+00:00",
            "finished_at": "2026-07-23T12:00:01+00:00",
        },
        {
            "id": "job-device",
            "job_type": "device_terminal",
            "status": "failed",
            "file_name": "device-terminal.xlsx",
            "row_count": 5,
            "progress": 100,
            "error_message": "device failed",
            "filter_snapshot": {},
            "request_key": "req-device",
            "created_by": "root-admin",
            "created_at": "2026-07-23T13:00:00+00:00",
            "updated_at": "2026-07-23T13:00:00+00:00",
            "finished_at": "2026-07-23T13:00:01+00:00",
        },
    ]
    monkeypatch.setitem(local_simulation._team_states, team_id, state)
    token = local_simulation.set_current_team(team_id)
    try:
        page = JsonStateRepository().list_export_jobs(
            page=1,
            page_size=20,
            category="business",
            job_types=["task_detail", "exception_meter"],
            status=["failed"],
        )
    finally:
        local_simulation.reset_current_team(token)

    assert page["total"] == 1
    assert [item["id"] for item in page["items"]] == ["job-business-match"]


def test_json_terminal_readiness_includes_latest_generated_at_from_export_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    team_id = "team-export-readiness-latest-generated"
    state = local_simulation.blank_state(team_id)
    state["groups"] = [formal_group("group-a", terminal="T-1", archive_status="archived")]
    state["export_jobs"] = [
        {
            "id": "job-1",
            "job_type": "final_delivery",
            "status": "succeeded",
            "file_name": "final-delivery.zip",
            "filter_snapshot": {"terminal": "T-1"},
            "created_at": "2026-07-23T12:00:00+00:00",
        }
    ]
    monkeypatch.setitem(local_simulation._team_states, team_id, state)
    token = local_simulation.set_current_team(team_id)
    try:
        page = JsonStateRepository().list_terminal_delivery_readiness(page=1, page_size=20)
    finally:
        local_simulation.reset_current_team(token)

    assert page["items"][0]["latest_generated_at"] == "2026-07-23T12:00:00+00:00"


def test_export_catalog_marks_task_detail_required_filters(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    client, headers = production_rbac_client(monkeypatch, tmp_path)

    response = client.get("/exports/catalog", headers=headers["admin"])

    assert response.status_code == 200
    task_detail = next(item for item in response.json()["data"]["items"] if item["key"] == "task_detail")
    assert task_detail["required_filters"] == [{"key": "task_id", "label": "任务", "kind": "task"}]


def test_export_task_options_are_admin_only(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    client, headers = production_rbac_client(monkeypatch, tmp_path)

    response = client.get("/exports/task-options?query=T-1&limit=20", headers=headers["constructor"])

    assert response.status_code == 403


def test_json_export_task_options_filter_and_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    team_id = "team-export-task-options"
    state = local_simulation.blank_state(team_id)
    state["tasks"] = [
        {"id": 12, "terminal": "T-200", "name": "终端 T-200", "status": "approved"},
        {"id": 11, "terminal": "T-100", "name": "终端 T-100", "status": "pending"},
        {"id": 13, "terminal": "Z-300", "name": "其他", "status": "released"},
    ]
    monkeypatch.setitem(local_simulation._team_states, team_id, state)
    token = local_simulation.set_current_team(team_id)
    try:
        items = JsonStateRepository().list_export_task_options(query="T-", limit=1)
    finally:
        local_simulation.reset_current_team(token)

    assert items == [
        {
            "task_id": 11,
            "terminal": "T-100",
            "status": "pending",
            "label": "T-100 / #11 / 终端 T-100",
        }
    ]


def test_task_detail_export_job_requires_positive_task_id(monkeypatch: pytest.MonkeyPatch) -> None:
    team_id = "team-task-detail-filter"
    monkeypatch.setitem(local_simulation._team_states, team_id, local_simulation.blank_state(team_id))
    token = local_simulation.set_current_team(team_id)
    try:
        with pytest.raises(ValueError, match="task_id"):
            JsonStateRepository().create_export_job(
                job_type="task_detail",
                filters={},
                actor="root-admin",
            )
    finally:
        local_simulation.reset_current_team(token)


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


def formal_group(
    group_id: str,
    *,
    terminal: str = "T-1",
    status: str = "pending",
    archive_status: str = "",
    active_count: int = 4,
    invalid_count: int = 0,
    cache_status: str = "ready",
    cache_path_prefix: str = "team/group",
) -> dict:
    categories = ["before_box", "collector_barcode", "module_meter", "after_box"]
    photos = []
    for index, category in enumerate(categories, start=1):
        upload_status = "invalid" if index <= invalid_count else "uploaded"
        photos.append(
            {
                "id": f"{group_id}-photo-{index}",
                "category": category,
                "is_active": index <= active_count + invalid_count,
                "upload_status": upload_status,
                "archive_status": archive_status,
                "delivery_cache_status": cache_status,
                "delivery_cache_path": f"{cache_path_prefix}/{group_id}-{index}.jpg",
            }
        )
    return {
        "id": group_id,
        "task_id": 1,
        "terminal": terminal,
        "meter_no": f"000000000{group_id[-1]}",
        "module_asset_no": f"000000010{group_id[-1]}",
        "collector": f"000000020{group_id[-1]}",
        "address": f"Address {group_id}",
        "client_completed_at": "2026-07-24T08:00:00Z",
        "status": status,
        "archive_status": archive_status,
        "photo_count": 99,
        "photos": photos,
    }


def test_terminal_readiness_uses_formal_delivery_preflight_and_active_uploaded_photos() -> None:
    approved_without_archive = formal_group("group-1", status="approved", archive_status="")
    for photo in approved_without_archive["photos"]:
        photo["archive_status"] = ""
    invalid_photo_group = formal_group("group-2", archive_status="archived", invalid_count=1)
    missing_cache_path = formal_group("group-3", archive_status="archived")
    missing_cache_path["photos"][0]["delivery_cache_path"] = ""
    traversal_cache_path = formal_group("group-4", archive_status="archived")
    traversal_cache_path["photos"][0]["delivery_cache_path"] = "../escape.jpg"
    ready = formal_group("group-5", archive_status="archived")

    page = export_center_service.build_terminal_readiness_page(
        [approved_without_archive, invalid_photo_group, missing_cache_path, traversal_cache_path, ready],
        page=1,
        page_size=20,
    )

    item = page["items"][0]
    assert item["terminal"] == "T-1"
    assert item["group_count"] == 5
    assert item["constructed_count"] == 4
    assert item["archived_count"] == 4
    assert item["cache_ready_count"] == 1
    assert item["status"] == "blocked"
    assert item["blockers"] == [
        "1 个资料组未施工",
        "1 个资料组未归档",
        "2 个资料组交付缓存未就绪",
        "1 个资料组交付缓存路径不受控",
    ]

def test_terminal_readiness_matches_final_delivery_archive_and_upload_status_semantics() -> None:
    group_level_archived = formal_group("group-6", archive_status="archived")
    for photo in group_level_archived["photos"]:
        photo["archive_status"] = ""
    pending_upload_group = formal_group("group-7", terminal="T-2", archive_status="archived")
    pending_upload_group["photos"][0]["upload_status"] = "pending"

    page = export_center_service.build_terminal_readiness_page(
        [group_level_archived, pending_upload_group],
        page=1,
        page_size=20,
    )

    first, second = page["items"]
    assert first["terminal"] == "T-1"
    assert first["archived_count"] == 1
    assert first["cache_ready_count"] == 1
    assert export_center_service.terminal_delivery_preflight(group_level_archived)["archived"] == group_is_formally_archived(
        group_level_archived
    )
    assert second["terminal"] == "T-2"
    assert second["constructed_count"] == 0
    assert second["archived_count"] == 1
    assert second["cache_ready_count"] == 0
    assert second["blockers"] == [
        "1 \u4e2a\u8d44\u6599\u7ec4\u672a\u65bd\u5de5",
        "1 \u4e2a\u8d44\u6599\u7ec4\u4ea4\u4ed8\u7f13\u5b58\u672a\u5c31\u7eea",
    ]


def test_request_key_changes_when_barcode_verification_or_delivery_output_fields_change() -> None:
    group = formal_group("group-1", archive_status="")
    group["barcode_verification"] = {"auto_archive_status": "pending"}
    first = export_center_service.export_request_key(
        job_type="final_delivery",
        filters={"terminal": "T-1"},
        snapshot=export_center_service.stable_export_snapshot([group]),
    )
    group["barcode_verification"]["auto_archive_status"] = "archived"
    second = export_center_service.export_request_key(
        job_type="final_delivery",
        filters={"terminal": "T-1"},
        snapshot=export_center_service.stable_export_snapshot([group]),
    )
    group["replacement_old_meter_no"] = "000000001111"
    third = export_center_service.export_request_key(
        job_type="final_delivery",
        filters={"terminal": "T-1"},
        snapshot=export_center_service.stable_export_snapshot([group]),
    )

    assert first != second
    assert second != third


def test_json_terminal_readiness_matches_shared_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    team_id = "team-export-readiness"
    state = local_simulation.blank_state(team_id)
    state["groups"] = [
        formal_group("group-a", terminal="T-1", archive_status="archived"),
        formal_group("group-b", terminal="T-1", archive_status=""),
    ]
    monkeypatch.setitem(local_simulation._team_states, team_id, state)
    token = local_simulation.set_current_team(team_id)
    try:
        repository_page = JsonStateRepository().list_terminal_delivery_readiness(page=1, page_size=20)
        pure_page = export_center_service.build_terminal_readiness_page(state["groups"], page=1, page_size=20)
    finally:
        local_simulation.reset_current_team(token)

    assert repository_page["page"] == pure_page["page"]
    assert repository_page["page_size"] == pure_page["page_size"]
    assert repository_page["total"] == pure_page["total"]
    assert [{k: v for k, v in item.items() if k != "latest_generated_at"} for item in repository_page["items"]] == pure_page["items"]
    assert repository_page["items"][0]["latest_generated_at"] == ""


def test_pg_terminal_readiness_matches_shared_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    groups = [
        formal_group("group-a", terminal="T-1", archive_status="archived"),
        formal_group("group-b", terminal="T-1", archive_status=""),
    ]
    repository = PostgresStateRepository()
    monkeypatch.setattr(repository, "_export_center_lightweight_groups", lambda query="": groups)

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *_args, **_kwargs):
            return SimpleNamespace(all=lambda: [])

    repository._session = lambda: FakeSession()

    repository_page = repository.list_terminal_delivery_readiness(page=1, page_size=20)
    pure_page = export_center_service.build_terminal_readiness_page(groups, page=1, page_size=20)

    assert repository_page["page"] == pure_page["page"]
    assert repository_page["page_size"] == pure_page["page_size"]
    assert repository_page["total"] == pure_page["total"]
    assert [{k: v for k, v in item.items() if k != "latest_generated_at"} for item in repository_page["items"]] == pure_page["items"]
    assert repository_page["items"][0]["latest_generated_at"] == ""


def test_pg_lightweight_readiness_query_includes_barcode_verification() -> None:
    source = inspect.getsource(PostgresStateRepository._export_center_lightweight_groups)
    assert "GroupBarcodeVerification" in source
    assert "auto_archive_status" in source


def test_download_route_streams_validated_path_after_success_audit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    client, headers = production_rbac_client(monkeypatch, tmp_path)
    cache_root = tmp_path / "delivery-cache"
    cache_root.mkdir()
    monkeypatch.setattr(local_simulation, "delivery_cache_root", lambda: cache_root)
    export_file = cache_root / "terminal-devices.xlsx"
    export_file.write_bytes(b"streamed-workbook")
    events: list[tuple[str, str, dict]] = []

    class JobRepository:
        def open_export_job_download(self, job_id: str, *, actor: str) -> dict:
            return {
                "id": job_id,
                "job_type": "device_terminal",
                "file_name": "terminal-devices.xlsx",
                "relative_path": "terminal-devices.xlsx",
                "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }

        def append_audit_event(self, action: str, actor: str, payload: dict) -> dict:
            events.append((action, actor, deepcopy(payload)))
            return {"id": "audit-1", "action": action, "actor": actor, "payload": payload}

    monkeypatch.setattr(export_routes, "state_repository", lambda: JobRepository())
    monkeypatch.setattr(Path, "read_bytes", lambda self: pytest.fail("download route must not read whole file"))
    monkeypatch.setattr(export_routes, "FileResponse", lambda *_args, **_kwargs: pytest.fail("download route must stream opened fd"))

    response = client.get("/exports/jobs/job-1/download", headers=headers["admin"])

    assert response.status_code == 200
    assert response.content == b"streamed-workbook"
    assert events == [
        (
            "export_job_downloaded",
            "root-admin",
            {"job_id": "job-1", "job_type": "device_terminal", "file_name": "terminal-devices.xlsx"},
        )
    ]


def test_download_route_opens_safe_stream_before_success_audit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    client, headers = production_rbac_client(monkeypatch, tmp_path)
    events: list[tuple[str, str, dict]] = []

    class JobRepository:
        def open_export_job_download(self, job_id: str, *, actor: str) -> dict:
            return {
                "id": job_id,
                "job_type": "device_terminal",
                "file_name": "terminal-devices.xlsx",
                "relative_path": "exports/missing.xlsx",
                "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }

        def append_audit_event(self, action: str, actor: str, payload: dict) -> dict:
            events.append((action, actor, deepcopy(payload)))
            return {"id": "audit-1", "action": action, "actor": actor, "payload": payload}

    monkeypatch.setattr(export_routes, "state_repository", lambda: JobRepository())
    monkeypatch.setattr(
        export_center_service,
        "open_validated_export_stream",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("missing")),
    )

    response = client.get("/exports/jobs/job-1/download", headers=headers["admin"])

    assert response.status_code == 409
    assert events == []


def test_download_route_closes_opened_stream_when_audit_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    client, headers = production_rbac_client(monkeypatch, tmp_path)
    closed: list[str] = []

    class FakeOpened:
        media_type = "application/octet-stream"
        file_name = "terminal-devices.xlsx"
        size_bytes = 7

        def iter_bytes(self):
            yield b"content"

        def close(self):
            closed.append("closed")

    class JobRepository:
        def open_export_job_download(self, job_id: str, *, actor: str) -> dict:
            return {
                "id": job_id,
                "job_type": "device_terminal",
                "file_name": "terminal-devices.xlsx",
                "relative_path": "exports/job.xlsx",
                "media_type": "application/octet-stream",
            }

        def append_audit_event(self, action: str, actor: str, payload: dict) -> dict:
            raise RuntimeError("audit unavailable")

    monkeypatch.setattr(export_routes, "state_repository", lambda: JobRepository())
    monkeypatch.setattr(export_center_service, "open_validated_export_stream", lambda *_args, **_kwargs: FakeOpened())

    with pytest.raises(RuntimeError, match="audit unavailable"):
        client.get("/exports/jobs/job-1/download", headers=headers["admin"])

    assert closed == ["closed"]


def test_posix_export_stream_uses_openat_without_following_parent_symlinks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "cache"
    root.mkdir()
    monkeypatch.setattr(local_simulation, "delivery_cache_root", lambda: root)
    monkeypatch.setattr(export_center_service.os, "O_DIRECTORY", 0x10000, raising=False)
    monkeypatch.setattr(export_center_service.os, "O_NOFOLLOW", 0x20000, raising=False)
    calls: list[tuple[str, int, int | None]] = []
    closed: list[int] = []
    next_fd = iter([10, 11, 12])

    def fake_open(path, flags, *, dir_fd=None):
        calls.append((os.fspath(path), flags, dir_fd))
        return next(next_fd)

    def fake_fstat(fd):
        assert fd == 12
        return SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_size=17)

    monkeypatch.setattr(export_center_service.os, "open", fake_open)
    monkeypatch.setattr(export_center_service.os, "fstat", fake_fstat)
    monkeypatch.setattr(export_center_service.os, "close", lambda fd: closed.append(fd))

    opened = export_center_service._open_export_stream_posix(
        root=root,
        relative_path="exports/job.xlsx",
        filename="job.xlsx",
        media_type="application/octet-stream",
    )
    opened.close()

    assert calls == [
        (os.fspath(root), os.O_RDONLY | 0x10000 | 0x20000, None),
        ("exports", os.O_RDONLY | 0x10000 | 0x20000, 10),
        ("job.xlsx", os.O_RDONLY | 0x20000, 11),
    ]
    assert closed == [11, 10, 12]


def test_posix_export_stream_closes_parent_fds_when_final_open_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "cache"
    root.mkdir()
    monkeypatch.setattr(local_simulation, "delivery_cache_root", lambda: root)
    monkeypatch.setattr(export_center_service.os, "O_DIRECTORY", 0x10000, raising=False)
    monkeypatch.setattr(export_center_service.os, "O_NOFOLLOW", 0x20000, raising=False)
    closed: list[int] = []

    def fake_open(path, flags, *, dir_fd=None):
        if os.fspath(path) == os.fspath(root):
            return 20
        if os.fspath(path) == "exports":
            return 21
        raise OSError("symlink or missing")

    monkeypatch.setattr(export_center_service.os, "open", fake_open)
    monkeypatch.setattr(export_center_service.os, "close", lambda fd: closed.append(fd))

    with pytest.raises(FileNotFoundError):
        export_center_service._open_export_stream_posix(
            root=root,
            relative_path="exports/job.xlsx",
            filename="job.xlsx",
            media_type="application/octet-stream",
        )

    assert closed == [21, 20]


def test_open_validated_export_stream_holds_original_file_after_path_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "cache"
    root.mkdir()
    export_file = root / "job.xlsx"
    export_file.write_bytes(b"original-content")
    monkeypatch.setattr(local_simulation, "delivery_cache_root", lambda: root)

    opened = export_center_service.open_validated_export_stream(export_file)
    export_file.write_bytes(b"replacement-content")
    try:
        assert b"".join(opened.iter_bytes()) == b"original-content"
    finally:
        opened.close()


def test_open_validated_export_stream_rejects_symlink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "cache"
    root.mkdir()
    target = root / "target.xlsx"
    target.write_bytes(b"target-content")
    link = root / "link.xlsx"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink unavailable on this Windows host: {exc}")
    monkeypatch.setattr(local_simulation, "delivery_cache_root", lambda: root)

    with pytest.raises(FileNotFoundError):
        export_center_service.open_validated_export_stream(link)


def test_json_inline_export_job_request_key_reuses_same_content_despite_state_change(monkeypatch: pytest.MonkeyPatch) -> None:
    team_id = "team-export-dedupe"
    state = local_simulation.blank_state(team_id)
    state["groups"] = [formal_group("group-1", archive_status="archived")]
    monkeypatch.setitem(local_simulation._team_states, team_id, state)
    monkeypatch.setattr(
        export_center_service,
        "build_inline_export_content",
        lambda *_args, **_kwargs: (
            b"stable-workbook",
            "device-terminal.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    )
    token = local_simulation.set_current_team(team_id)
    try:
        repository = JsonStateRepository()
        first = repository.create_export_job(job_type="device_terminal", filters={"terminal": "T-1"}, actor="root-admin")
        second = repository.create_export_job(job_type="device_terminal", filters={"terminal": "T-1"}, actor="root-admin")
        state["groups"].append(formal_group("group-2", archive_status="archived"))
        third = repository.create_export_job(job_type="device_terminal", filters={"terminal": "T-1"}, actor="root-admin")
    finally:
        local_simulation.reset_current_team(token)

    assert first["id"] == second["id"]
    assert first["created"] is True
    assert second["created"] is False
    assert third["id"] == first["id"]
    assert third["created"] is False
    assert len(state["export_jobs"]) == 1
    assert state["export_jobs"][0]["request_key"] == export_center_service.inline_export_request_key(
        job_type="device_terminal",
        filters={"terminal": "T-1"},
        content_sha256=state["export_jobs"][0]["content_sha256"],
    )


def test_json_inline_export_job_request_key_changes_when_content_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    team_id = "team-export-content-key"
    state = local_simulation.blank_state(team_id)
    state["groups"] = [formal_group("group-1", archive_status="archived")]
    monkeypatch.setitem(local_simulation._team_states, team_id, state)
    contents = iter([b"first-workbook", b"second-workbook"])

    def build_content(*_args, **_kwargs):
        return next(contents), "device-terminal.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    monkeypatch.setattr(export_center_service, "build_inline_export_content", build_content)
    token = local_simulation.set_current_team(team_id)
    try:
        repository = JsonStateRepository()
        first = repository.create_export_job(job_type="device_terminal", filters={"terminal": "T-1"}, actor="root-admin")
        second = repository.create_export_job(job_type="device_terminal", filters={"terminal": "T-1"}, actor="root-admin")
    finally:
        local_simulation.reset_current_team(token)

    assert first["id"] != second["id"]
    assert len(state["export_jobs"]) == 2
    assert state["export_jobs"][0]["request_key"] != state["export_jobs"][1]["request_key"]


def test_json_export_job_concurrent_create_rechecks_request_key_under_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    team_id = "team-export-concurrent-dedupe"
    state = local_simulation.blank_state(team_id)
    state["groups"] = [formal_group("group-1", archive_status="archived")]
    monkeypatch.setitem(local_simulation._team_states, team_id, state)
    barrier = threading.Barrier(2)

    def slow_build(*_args, **_kwargs):
        barrier.wait(timeout=5)
        return b"workbook", "device-terminal.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    monkeypatch.setattr(export_center_service, "build_inline_export_content", slow_build)
    results: list[dict] = []
    errors: list[BaseException] = []

    def create_job() -> None:
        token = local_simulation.set_current_team(team_id)
        try:
            results.append(
                JsonStateRepository().create_export_job(
                    job_type="device_terminal",
                    filters={"terminal": "T-1"},
                    actor="root-admin",
                )
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            local_simulation.reset_current_team(token)

    threads = [threading.Thread(target=create_job) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert len(results) == 2
    assert {item["id"] for item in results} == {state["export_jobs"][0]["id"]}
    assert [item["created"] for item in sorted(results, key=lambda item: item["created"], reverse=True)] == [True, False]
    assert len(state["export_jobs"]) == 1


def test_export_create_audits_only_new_jobs(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    client, headers = production_rbac_client(monkeypatch, tmp_path)
    events: list[tuple[str, str, dict]] = []
    created = True

    class JobRepository:
        def create_export_job(self, *, job_type: str, filters: dict, actor: str) -> dict:
            nonlocal created
            result = {
                "id": "job-1",
                "job_type": job_type,
                "status": "pending",
                "file_name": "final-delivery.zip",
                "created": created,
            }
            created = False
            return result

        def append_audit_event(self, action: str, actor: str, payload: dict) -> dict:
            events.append((action, actor, deepcopy(payload)))
            return {"id": f"audit-{len(events)}", "action": action, "actor": actor, "payload": payload}

    monkeypatch.setattr(export_routes, "state_repository", lambda: JobRepository())

    first = client.post(
        "/exports/jobs",
        headers=headers["admin"],
        json={"job_type": "final_delivery", "filters": {"terminal": "T-1", "review_scope": "reviewed"}},
    )
    second = client.post(
        "/exports/jobs",
        headers=headers["admin"],
        json={"job_type": "final_delivery", "filters": {"terminal": "T-1", "review_scope": "reviewed"}},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert events == [
        (
            "export_job_created",
            "root-admin",
            {
                "job_id": "job-1",
                "job_type": "final_delivery",
                "filters": {"terminal": "T-1", "review_scope": "reviewed"},
            },
        )
    ]


def test_final_delivery_request_key_reuses_existing_delivery_package_job(monkeypatch: pytest.MonkeyPatch) -> None:
    team_id = "team-final-delivery-dedupe"
    state = local_simulation.blank_state(team_id)
    state["groups"] = [formal_group("group-1", status="approved", archive_status="archived")]
    monkeypatch.setitem(local_simulation._team_states, team_id, state)
    token = local_simulation.set_current_team(team_id)
    calls = 0

    def not_ready(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise DeliveryPackageNotReady(job_id="delivery-job-1", status="pending")

    monkeypatch.setattr(JsonStateRepository, "request_final_delivery_export", not_ready)
    try:
        repository = JsonStateRepository()
        first = repository.create_export_job(
            job_type="final_delivery",
            filters={"terminal": "T-1", "review_scope": "reviewed"},
            actor="root-admin",
        )
        second = repository.create_export_job(
            job_type="final_delivery",
            filters={"terminal": "T-1", "review_scope": "reviewed"},
            actor="root-admin",
        )
    finally:
        local_simulation.reset_current_team(token)

    assert first["id"] == second["id"]
    assert calls == 0
    assert len(state["export_jobs"]) == 1


def test_json_final_delivery_export_job_links_delivery_job_in_same_create_unit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id = "team-final-delivery-atomic-link"
    state = local_simulation.blank_state(team_id)
    state["groups"] = [formal_group("group-1", status="approved", archive_status="archived")]
    monkeypatch.setitem(local_simulation._team_states, team_id, state)
    monkeypatch.setattr(
        JsonStateRepository,
        "request_final_delivery_export",
        lambda *_args, **_kwargs: pytest.fail("create_export_job must stage final delivery directly in the same JSON lock"),
    )
    token = local_simulation.set_current_team(team_id)
    try:
        result = JsonStateRepository().create_export_job(
            job_type="final_delivery",
            filters={"terminal": "T-1", "review_scope": "reviewed"},
            actor="root-admin",
        )
    finally:
        local_simulation.reset_current_team(token)

    assert result["status"] == "pending"
    assert len(state["export_jobs"]) == 1
    assert len(state["delivery_package_jobs"]) == 1
    assert state["export_jobs"][0]["params"]["delivery_package_job_id"] == state["delivery_package_jobs"][0]["id"]


def test_pg_final_delivery_export_job_links_delivery_job_in_same_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.delivery_package_queue as delivery_package_queue

    repository = PostgresStateRepository()
    project_id = uuid4()
    export_row_holder: dict[str, object] = {}
    commits = 0

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, statement):
            return None

        def add(self, row):
            export_row_holder["row"] = row

        def commit(self):
            nonlocal commits
            commits += 1

        def rollback(self):
            pass

        def get(self, model, row_id):
            return export_row_holder["row"]

    captured: dict[str, object] = {}

    def fake_request_postgres_delivery_package(session, **kwargs):
        captured.update(kwargs)
        assert isinstance(session, FakeSession)
        raise DeliveryPackageNotReady(job_id="delivery-job-pg", status="pending")

    monkeypatch.setattr(repository, "_session", lambda: FakeSession())
    monkeypatch.setattr(repository, "_export_project_id", lambda session: project_id)
    monkeypatch.setattr(repository, "_export_center_lightweight_groups", lambda: [formal_group("group-1", status="approved", archive_status="archived")])
    monkeypatch.setattr(
        PostgresStateRepository,
        "request_final_delivery_export",
        lambda *_args, **_kwargs: pytest.fail("create_export_job must stage final delivery with the create session"),
    )
    monkeypatch.setattr(delivery_package_queue, "request_postgres_delivery_package", fake_request_postgres_delivery_package)

    result = repository.create_export_job(
        job_type="final_delivery",
        filters={"terminal": "T-1", "review_scope": "reviewed"},
        actor="root-admin",
    )

    assert result["status"] == "pending"
    assert captured["auto_commit"] is False
    assert export_row_holder["row"].params["delivery_package_job_id"] == "delivery-job-pg"
    assert commits == 1


def test_pg_inline_export_request_key_uses_content_hash_not_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = PostgresStateRepository()
    project_id = uuid4()
    rows: list[object] = []
    snapshots = [
        [formal_group("group-1", archive_status="archived")],
        [formal_group("group-1", archive_status="archived"), formal_group("group-2", archive_status="archived")],
    ]

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, statement):
            expected_key = export_center_service.inline_export_request_key(
                job_type="device_terminal",
                filters={"terminal": "T-1"},
                content_sha256=export_center_service.file_sha256(b"same-workbook"),
            )
            return next((row for row in rows if row.request_key == expected_key), None)

        def add(self, row):
            rows.append(row)

        def flush(self):
            pass

        def commit(self):
            pass

        def rollback(self):
            pass

        def get(self, model, row_id):
            return next((row for row in rows if row.id == row_id), None)

    monkeypatch.setattr(repository, "_session", lambda: FakeSession())
    monkeypatch.setattr(repository, "_export_project_id", lambda session: project_id)
    monkeypatch.setattr(repository, "_export_center_lightweight_groups", lambda: snapshots.pop(0))
    monkeypatch.setattr(
        export_center_service,
        "build_inline_export_content",
        lambda *_args, **_kwargs: (
            b"same-workbook",
            "device-terminal.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    )

    first = repository.create_export_job(job_type="device_terminal", filters={"terminal": "T-1"}, actor="root-admin")
    second = repository.create_export_job(job_type="device_terminal", filters={"terminal": "T-1"}, actor="root-admin")

    assert first["id"] == second["id"]
    assert second["created"] is False
    assert len(rows) == 1
    assert rows[0].request_key == export_center_service.inline_export_request_key(
        job_type="device_terminal",
        filters={"terminal": "T-1"},
        content_sha256=rows[0].content_sha256,
    )


def test_pg_export_job_integrity_error_reuses_existing_job_without_background_enqueue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = PostgresStateRepository()
    request_key_holder: dict[str, str] = {}
    existing_id = uuid4()

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, statement):
            if not request_key_holder:
                return None
            return SimpleNamespace(
                id=existing_id,
                job_type="final_delivery",
                status="pending",
                file_name="final-delivery.zip",
                row_count=0,
                progress=0,
                error_message="",
                filter_snapshot={"terminal": "T-1"},
                params={"created_by": "root-admin", "terminal": "T-1"},
                request_key=request_key_holder["value"],
                created_at=None,
                updated_at=None,
                finished_at=None,
            )

        def add(self, row):
            request_key_holder["value"] = row.request_key

        def flush(self):
            raise IntegrityError("duplicate request_key", {}, Exception("duplicate"))

        def commit(self):
            pass

        def rollback(self):
            pass

    monkeypatch.setattr(repository, "_session", lambda: FakeSession())
    monkeypatch.setattr(repository, "_export_project_id", lambda session: uuid4())
    monkeypatch.setattr(repository, "_export_center_lightweight_groups", lambda: [formal_group("group-1", status="approved", archive_status="archived")])
    monkeypatch.setattr(
        export_center_service,
        "request_background_export",
        lambda *_args, **_kwargs: pytest.fail("dedupe conflict must not enqueue final delivery again"),
    )

    result = repository.create_export_job(
        job_type="final_delivery",
        filters={"terminal": "T-1"},
        actor="root-admin",
    )

    assert result["id"] == str(existing_id)
    assert result["created"] is False


def test_export_job_types_are_catalog_strings_without_runtime_enum() -> None:
    assert not hasattr(models, "ExportJobType")
    assert "final_delivery" in export_center_service.CATALOG_BY_KEY
    assert "_terminal_readiness_item" not in export_center_service.__dict__
