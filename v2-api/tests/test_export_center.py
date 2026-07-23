from __future__ import annotations

import os
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
            self.append_audit_event(
                "export_job_downloaded",
                actor,
                {"job_id": "job-1", "job_type": "device_terminal", "file_name": "terminal-devices.xlsx"},
            )
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

    assert repository_page == pure_page


def test_pg_terminal_readiness_matches_shared_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    groups = [
        formal_group("group-a", terminal="T-1", archive_status="archived"),
        formal_group("group-b", terminal="T-1", archive_status=""),
    ]
    repository = PostgresStateRepository()
    monkeypatch.setattr(repository, "_export_center_lightweight_groups", lambda query="": groups)

    repository_page = repository.list_terminal_delivery_readiness(page=1, page_size=20)
    pure_page = export_center_service.build_terminal_readiness_page(groups, page=1, page_size=20)

    assert repository_page == pure_page


def test_pg_lightweight_readiness_query_includes_barcode_verification() -> None:
    source = inspect.getsource(PostgresStateRepository._export_center_lightweight_groups)
    assert "GroupBarcodeVerification" in source
    assert "auto_archive_status" in source


def test_download_route_streams_validated_path_and_repository_owns_download_audit(
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
            events.append(("export_job_downloaded", actor, {"job_id": job_id}))
            return {
                "id": job_id,
                "job_type": "device_terminal",
                "file_name": "terminal-devices.xlsx",
                "path": export_file,
                "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }

        def append_audit_event(self, action: str, actor: str, payload: dict) -> dict:
            pytest.fail("download audit must be written by open_export_job_download")

    monkeypatch.setattr(export_routes, "state_repository", lambda: JobRepository())
    monkeypatch.setattr(Path, "read_bytes", lambda self: pytest.fail("download route must not read whole file"))
    monkeypatch.setattr(export_routes, "FileResponse", lambda *_args, **_kwargs: pytest.fail("download route must stream opened fd"))

    response = client.get("/exports/jobs/job-1/download", headers=headers["admin"])

    assert response.status_code == 200
    assert response.content == b"streamed-workbook"
    assert events == [("export_job_downloaded", "root-admin", {"job_id": "job-1"})]


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


def test_json_export_job_create_reuses_same_request_key_and_changes_on_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    team_id = "team-export-dedupe"
    state = local_simulation.blank_state(team_id)
    state["groups"] = [formal_group("group-1", archive_status="archived")]
    monkeypatch.setitem(local_simulation._team_states, team_id, state)
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
    assert third["id"] != first["id"]
    assert len(state["export_jobs"]) == 2
    assert all(job.get("request_key") for job in state["export_jobs"])


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
