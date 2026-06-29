from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.core.security import create_access_token
from app.services import local_simulation
from app.services.local_simulation import LocalTestPaths, bootstrap_local_simulation


client = TestClient(create_app())


def fake_catalog_rows(source: str) -> list[dict]:
    return [
        {
            "source": source,
            "row_number": 2,
            "terminal": "T-001",
            "meter_no": "ZZ1001",
            "address": "A road",
            "meter_match_key": "1001",
        },
        {
            "source": source,
            "row_number": 3,
            "terminal": "T-002",
            "meter_no": "ZZ1002",
            "address": "B road",
            "meter_match_key": "1002",
        },
    ]


def fake_scan_rows() -> list[dict]:
    return [
        {
            "row_number": index + 2,
            "barcode": f"scan-{index}",
            "meter_match_key": "1001",
            "source_file": "local",
            "collector": "collector",
            "asset_no": f"asset-{index}",
            "asset_type": "module",
            "creator": "tester",
            "created_at": "2026-06-29",
            "has_image": True,
        }
        for index in range(4)
    ]


def seed_synthetic_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local_simulation, "read_catalog_rows", lambda path, source: fake_catalog_rows(source))
    monkeypatch.setattr(local_simulation, "read_scan_rows", lambda path: fake_scan_rows())
    bootstrap_local_simulation(LocalTestPaths(Path("total.xlsx"), Path("stage.xlsx"), Path("scan.xlsx")))


def login_headers(username: str, password: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"bearer {response.json()['data']['access_token']}"}


def bind_constructor(code: str = "wx-code-constructor") -> dict:
    response = client.post(
        "/miniprogram/auth/bind",
        json={"code": code, "username": "constructor", "password": "construct123"},
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["token_type"] == "bearer"
    assert payload["user"]["username"] == "constructor"
    assert payload["user"]["roles"] == ["constructor"]
    return payload


def constructor_headers(username: str) -> dict[str, str]:
    token = create_access_token({"username": username, "roles": ["constructor"], "team_id": "default-team"})
    return {"Authorization": f"bearer {token}"}


def setup_assigned_construction_task(monkeypatch: pytest.MonkeyPatch) -> tuple[dict, dict[str, str]]:
    admin_headers = login_headers("admin", "admin123")
    seed_synthetic_state(monkeypatch)
    tasks = client.get("/local-test/tasks", headers=admin_headers).json()["data"]["items"]
    task = tasks[-1]
    opened = client.patch(
        f"/local-test/construction/tasks/{task['id']}/open",
        headers=admin_headers,
        json={"actor": "admin"},
    )
    assigned = client.patch(
        f"/local-test/construction/tasks/{task['id']}/assign",
        headers=admin_headers,
        json={"actor": "admin", "constructor": "constructor"},
    )
    assert opened.status_code == 200
    assert assigned.status_code == 200
    miniprogram_session = bind_constructor("wx-code-assigned-task")
    return assigned.json()["data"], {"Authorization": f"bearer {miniprogram_session['access_token']}"}


def test_miniprogram_bind_and_wechat_login_returns_constructor_token() -> None:
    bound = bind_constructor("wx-code-bind-login")

    login = client.post("/miniprogram/auth/login", json={"code": "wx-code-bind-login"})

    assert login.status_code == 200
    payload = login.json()["data"]
    assert payload["access_token"]
    assert payload["token_type"] == "bearer"
    assert payload["openid"] == bound["openid"]
    assert payload["user"]["username"] == "constructor"
    assert payload["user"]["roles"] == ["constructor"]


def test_miniprogram_bind_rejects_non_constructor_account() -> None:
    response = client.post(
        "/miniprogram/auth/bind",
        json={"code": "wx-code-admin-denied", "username": "admin", "password": "admin123"},
    )

    assert response.status_code == 403
    assert "constructor" in response.json()["detail"].lower()


def test_miniprogram_tasks_return_assigned_tasks_only(monkeypatch: pytest.MonkeyPatch) -> None:
    task, headers = setup_assigned_construction_task(monkeypatch)

    response = client.get("/miniprogram/tasks", headers=headers)

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert [item["source"] for item in items] == ["assigned"]
    assert task["id"] in {item["id"] for item in items}
    first = next(item for item in items if item["id"] == task["id"])
    assert first["title"]
    assert first["total_groups"] >= 1
    assert first["uploaded_count"] >= 0
    assert first["unbuilt_count"] >= 0
    assert first["exception_count"] >= 0


def test_miniprogram_groups_reject_task_not_assigned_to_current_constructor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task, _headers = setup_assigned_construction_task(monkeypatch)
    other_headers = constructor_headers("other-constructor")

    todo_groups = client.get(f"/miniprogram/tasks/{task['id']}/groups?filter=todo", headers=other_headers)
    exception_groups = client.get(f"/miniprogram/tasks/{task['id']}/groups?filter=exception", headers=other_headers)

    assert todo_groups.status_code == 404
    assert exception_groups.status_code == 404


def test_miniprogram_group_filters_and_upload_keep_production_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    task, headers = setup_assigned_construction_task(monkeypatch)

    groups = client.get(f"/miniprogram/tasks/{task['id']}/groups?filter=todo", headers=headers)
    assert groups.status_code == 200
    group_items = groups.json()["data"]["items"]
    assert group_items
    group = group_items[0]
    assert group["id"]
    assert group["task_id"] == task["id"]
    assert "meter_no" in group
    assert "address" in group

    uploaded = client.post(
        f"/miniprogram/groups/{group['id']}/upload-batch",
        headers=headers,
        data={
            "client_batch_id": "wx-batch-1",
            "client_completed_at": "2026-06-29T10:00:00",
            "collector": "collector-wx",
            "module_asset_no": "module-wx",
            "photo_slots": ["before_box", "module_meter", "after_box"],
            "client_photo_ids": ["wx-photo-a", "wx-photo-b", "wx-photo-c"],
        },
        files=[
            ("files", ("before.jpg", b"wx-before", "image/jpeg")),
            ("files", ("meter.jpg", b"wx-meter", "image/jpeg")),
            ("files", ("after.jpg", b"wx-after", "image/jpeg")),
        ],
    )
    assert uploaded.status_code == 200
    upload_payload = uploaded.json()["data"]
    assert upload_payload["group"]["photos"][0]["upload_source"] == "construction-mobile"
    assert upload_payload["uploaded_urls"][0].startswith("/static/uploads/construction/")

    exception_groups = client.get(f"/miniprogram/tasks/{task['id']}/groups?filter=exception", headers=headers)
    assert exception_groups.status_code == 200
    assert group["id"] in {item["id"] for item in exception_groups.json()["data"]["items"]}


def test_miniprogram_single_file_uploads_commit_as_one_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    task, headers = setup_assigned_construction_task(monkeypatch)
    groups = client.get(f"/miniprogram/tasks/{task['id']}/groups?filter=todo", headers=headers)
    group = groups.json()["data"]["items"][0]

    slots = [
        ("before_box", "before.jpg", b"wx-before-one"),
        ("module_meter", "meter.jpg", b"wx-meter-one"),
        ("after_box", "after.jpg", b"wx-after-one"),
    ]
    responses = []
    for index, (slot, filename, content) in enumerate(slots):
        responses.append(
            client.post(
                f"/miniprogram/groups/{group['id']}/upload-file",
                headers=headers,
                data={
                    "client_batch_id": "wx-single-batch",
                    "client_completed_at": "2026-06-29T10:10:00",
                    "collector": "collector-one",
                    "module_asset_no": "module-one",
                    "photo_slot": slot,
                    "client_photo_id": f"single-{slot}",
                    "expected_count": str(len(slots)),
                    "commit": "true" if index == len(slots) - 1 else "false",
                },
                files={"file": (filename, content, "image/jpeg")},
            )
        )

    assert [item.status_code for item in responses] == [200, 200, 200]
    assert responses[0].json()["data"]["status"] == "staged"
    committed = responses[-1].json()["data"]
    assert committed["status"] == "committed"
    assert committed["group"]["photos"][0]["upload_source"] == "construction-mobile"
    assert len(committed["uploaded_urls"]) == 3


def test_miniprogram_activity_records_use_signed_in_constructor(monkeypatch: pytest.MonkeyPatch) -> None:
    task, headers = setup_assigned_construction_task(monkeypatch)

    heartbeat = client.post(
        "/miniprogram/activity/heartbeat",
        headers=headers,
        json={"task_id": task["id"], "occurred_at": "2026-06-29T10:00:00"},
    )
    non_idle = client.post(
        "/miniprogram/activity/non-idle-events",
        headers=headers,
        json={
            "event_type": "group_draft_completed",
            "task_id": task["id"],
            "group_id": "",
            "client_batch_id": "wx-draft-1",
            "occurred_at": "2026-06-29T10:05:00",
        },
    )

    assert heartbeat.status_code == 200
    assert heartbeat.json()["data"]["actor"] == "constructor"
    assert non_idle.status_code == 200
    assert non_idle.json()["data"]["actor"] == "constructor"
