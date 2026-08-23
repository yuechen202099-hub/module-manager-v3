from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app import main as main_module
from app.api.routes import collector_transfer as routes
from app.core import security
from app.services.collector_transfer import (
    CollectorAllocationConflictError,
    PoolInsufficientError,
)


class FakeCollectorTransferService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def create_run(self, *, project_id: str, name: str) -> dict:
        self.calls.append(("create_run", {"project_id": project_id, "name": name}))
        return {"id": "run-1", "status": "inventory", "terminal_count": 2}

    def list_runs(self, *, project_id: str | None = None) -> list[dict]:
        self.calls.append(("list_runs", project_id))
        return [{"id": "run-1", "status": "inventory"}]

    def scan_collector(self, *, run_id: str, collector_no: str) -> dict:
        self.calls.append(("scan_collector", {"run_id": run_id, "collector_no": collector_no}))
        return {
            "collector_id": "collector-1",
            "collector_no": collector_no,
            "decision": "direct_reuse",
            "requires_photo": False,
            "add_to_pool": False,
        }

    def allocate(self, *, run_id: str) -> dict:
        self.calls.append(("allocate", run_id))
        raise PoolInsufficientError(required=3, available=2)

    def list_workbench(self, *, run_id: str) -> dict:
        self.calls.append(("list_workbench", run_id))
        return {"run_id": run_id, "terminals": [{"id": "terminal-1", "progress": 50}]}

    def terminal_workbench(self, *, run_id: str, terminal_id: str) -> dict:
        self.calls.append(("terminal_workbench", {"run_id": run_id, "terminal_id": terminal_id}))
        return {
            "run_id": run_id,
            "terminal": {"id": terminal_id, "terminal_code": "T-001"},
            "items": [{"id": "item-1", "kind": "meter_install"}],
        }

    def set_workbench_item_status(self, *, item_id: str, completed: bool) -> dict:
        self.calls.append(("set_workbench_item_status", {"item_id": item_id, "completed": completed}))
        return {"id": item_id, "status": "completed" if completed else "pending"}

    def register_photo(self, **payload) -> dict:
        self.calls.append(("register_photo", payload))
        return {"collector_id": payload["collector_id"], "pool_status": "available"}

    def import_inventory(self, **payload) -> dict:
        self.calls.append(("import_inventory", payload))
        return {"batch_id": "batch-1", "total": len(payload["rows"]), "invalid": 0}


def client_with_service(
    monkeypatch,
    service: FakeCollectorTransferService,
    *,
    raise_server_exceptions: bool = True,
) -> TestClient:
    @contextmanager
    def fake_service_for_request(_request):
        yield service

    monkeypatch.setattr(routes, "service_for_request", fake_service_for_request)
    return TestClient(
        main_module.create_app(),
        raise_server_exceptions=raise_server_exceptions,
    )


def auth_headers(
    *,
    team_id: str = "team-1",
    username: str = "admin-a",
    role: str = "admin",
) -> dict[str, str]:
    token = security.create_access_token(
        {
            "sub": username,
            "username": username,
            "roles": [role],
            "team_id": team_id,
        }
    )
    return {"Authorization": f"bearer {token}"}


def production_client_with_service(
    monkeypatch,
    service: FakeCollectorTransferService,
) -> tuple[TestClient, dict[str, dict[str, str]], list[tuple[str, str]]]:
    settings = SimpleNamespace(
        app_env="production",
        allowed_origins=["https://example.test"],
        trusted_hosts=["testserver"],
        security_frame_ancestors="'self'",
        max_upload_mb=20,
        state_backend="postgres",
        jwt_secret="collector-transfer-production-test-secret",
        jwt_expire_minutes=60,
    )
    monkeypatch.setattr(main_module, "settings", settings)
    monkeypatch.setattr(security, "settings", settings)
    identities: list[tuple[str, str]] = []

    @contextmanager
    def fake_service_for_request(request):
        identities.append(routes.request_identity(request))
        yield service

    monkeypatch.setattr(routes, "service_for_request", fake_service_for_request)
    headers = {}
    for role in ("admin", "constructor", "reviewer"):
        token = security.create_access_token(
            {
                "sub": f"{role}-a",
                "username": f"{role}-a",
                "roles": [role],
                "team_id": "token-team",
            }
        )
        headers[role] = {"Authorization": f"bearer {token}"}
    return TestClient(main_module.create_app()), headers, identities


def test_request_identity_decodes_bearer_claims_and_ignores_team_header() -> None:
    """Catches any environment allowing X-Team-Id to override authenticated claims."""
    request = SimpleNamespace(
        state=SimpleNamespace(),
        headers={**auth_headers(team_id="token-team", username="constructor-a"), "X-Team-Id": "spoofed-team"},
    )

    identity = routes.request_identity(request)

    assert identity == ("token-team", "constructor-a")
    assert request.state.auth["team_id"] == "token-team"


def test_request_identity_rejects_x_team_header_without_bearer_token() -> None:
    """Catches the non-production compatibility path treating X-Team-Id as authentication."""
    request = SimpleNamespace(
        state=SimpleNamespace(),
        headers={"X-Team-Id": "spoofed-team"},
    )

    with pytest.raises(HTTPException) as raised:
        routes.request_identity(request)

    assert raised.value.status_code == 401


def test_create_run_uses_project_snapshot_contract(monkeypatch) -> None:
    """Catches a route that accepts uploaded replacement data instead of a project snapshot."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)

    response = client.post(
        "/collector-transfer/runs",
        headers=auth_headers(),
        json={"project_id": "11111111-1111-1111-1111-111111111111", "name": "8月盘点"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"id": "run-1", "status": "inventory", "terminal_count": 2}
    assert service.calls == [
        (
            "create_run",
            {"project_id": "11111111-1111-1111-1111-111111111111", "name": "8月盘点"},
        )
    ]


def test_mobile_scan_contract_only_returns_inventory_decision(monkeypatch) -> None:
    """Catches mixing customer-platform entry fields into the mobile inventory endpoint."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)

    response = client.post(
        "/collector-transfer/runs/run-1/scan",
        headers=auth_headers(),
        json={"collector_no": "000123"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "collector_id": "collector-1",
        "collector_no": "000123",
        "decision": "direct_reuse",
        "requires_photo": False,
        "add_to_pool": False,
    }
    assert "client_platform" not in response.text


def test_pool_shortage_is_a_conflict_with_no_partial_success_payload(monkeypatch) -> None:
    """Catches turning an all-or-nothing pool shortage into a partial 200 response."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)

    response = client.post(
        "/collector-transfer/runs/run-1/allocate",
        headers=auth_headers(),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "pool_insufficient"
    assert response.json()["error"]["details"] == {"required": 3, "available": 2}
    assert "assignments" not in response.text


def test_workbench_endpoint_is_read_only_customer_relay_data(monkeypatch) -> None:
    """Catches coupling the workbench list to an automatic customer upload action."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)

    response = client.get(
        "/collector-transfer/runs/run-1/workbench",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["data"]["terminals"] == [{"id": "terminal-1", "progress": 50}]
    assert "upload" not in response.text.lower()


def test_list_runs_and_terminal_workbench_have_separate_summary_and_detail_contracts(monkeypatch) -> None:
    """Catches forcing the mobile run selector to download all workbench photos."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)

    runs = client.get("/collector-transfer/runs", headers=auth_headers())
    detail = client.get(
        "/collector-transfer/runs/run-1/workbench/terminal-1",
        headers=auth_headers(),
    )

    assert runs.status_code == 200
    assert runs.json()["data"] == [{"id": "run-1", "status": "inventory"}]
    assert detail.status_code == 200
    assert detail.json()["data"]["items"] == [{"id": "item-1", "kind": "meter_install"}]


def test_run_detail_returns_diagnostics_and_terminal_summary(monkeypatch) -> None:
    """Catches omitting the run-detail query required between creation and inventory work."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)

    response = client.get(
        "/collector-transfer/runs/run-1",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "run_id": "run-1",
        "terminals": [{"id": "terminal-1", "progress": 50}],
    }
    assert service.calls == [("list_workbench", "run-1")]


def test_workbench_completion_is_an_explicit_manual_confirmation(monkeypatch) -> None:
    """Catches marking an item completed merely because it was displayed."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)

    response = client.patch(
        "/collector-transfer/workbench/items/item-1",
        headers=auth_headers(),
        json={"completed": True},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"id": "item-1", "status": "completed"}
    assert service.calls == [
        ("set_workbench_item_status", {"item_id": "item-1", "completed": True})
    ]


def test_mobile_photo_upload_passes_validated_storage_metadata_to_the_transaction(monkeypatch) -> None:
    """Catches exposing a pool collector before the uploaded image is durably registered."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)
    monkeypatch.setattr(
        routes,
        "save_image_bytes",
        lambda **_kwargs: {
            "url": "/static/uploads/collector-transfer/000123.jpg",
            "sha256": "a" * 64,
            "storage_type": "local_upload",
            "storage_key": "collector-transfer/000123.jpg",
            "content_type": "image/jpeg",
        },
    )

    response = client.post(
        "/collector-transfer/runs/run-1/collectors/collector-1/photo",
        headers=auth_headers(),
        files={"file": ("000123.jpg", b"validated-by-storage-layer", "image/jpeg")},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"collector_id": "collector-1", "pool_status": "available"}
    call_name, payload = service.calls[0]
    assert call_name == "register_photo"
    assert payload["byte_size"] == len(b"validated-by-storage-layer")
    assert payload["stored"]["sha256"] == "a" * 64


def test_mobile_photo_validation_error_uses_the_stable_api_error_shape(monkeypatch) -> None:
    """Catches upload validation falling back to FastAPI's unrelated detail-only error shape."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)

    def reject_image(**_kwargs):
        raise ValueError("仅支持图片文件")

    monkeypatch.setattr(routes, "save_image_bytes", reject_image)

    response = client.post(
        "/collector-transfer/runs/run-1/collectors/collector-1/photo",
        headers=auth_headers(),
        files={"file": ("000123.txt", b"not-an-image", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert service.calls == []


def test_corrupt_workbook_returns_stable_invalid_request(monkeypatch) -> None:
    """Catches BadZipFile/openpyxl parser failures escaping the API as HTTP 500."""
    service = FakeCollectorTransferService()
    client = client_with_service(
        monkeypatch,
        service,
        raise_server_exceptions=False,
    )

    response = client.post(
        "/collector-transfer/runs/run-1/inventory/import",
        headers=auth_headers(),
        files={
            "workbook": (
                "collectors.xlsx",
                b"this-is-not-an-xlsx-zip",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert service.calls == []


def test_excel_and_barcode_named_photos_share_the_same_inventory_decision_path(monkeypatch) -> None:
    """Catches creating a second import-only collector pool that bypasses mobile scan rules."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["采集器"])
    sheet.append(["000123"])
    buffer = BytesIO()
    workbook.save(buffer)
    monkeypatch.setattr(
        routes,
        "save_image_bytes",
        lambda **kwargs: {
            "url": f"/static/uploads/collector-transfer/{kwargs['filename']}",
            "sha256": "b" * 64,
            "storage_type": "local_upload",
            "storage_key": f"collector-transfer/{kwargs['filename']}",
            "content_type": kwargs["content_type"],
        },
    )

    response = client.post(
        "/collector-transfer/runs/run-1/inventory/import",
        headers=auth_headers(),
        files=[
            ("workbook", ("collectors.xlsx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
            ("photos", ("000123.jpg", b"validated-photo", "image/jpeg")),
        ],
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"batch_id": "batch-1", "total": 1, "invalid": 0}
    call_name, payload = service.calls[0]
    assert call_name == "import_inventory"
    assert payload["rows"] == ((2, "000123"),)
    assert payload["photos_by_collector"]["000123"]["original_filename"] == "000123.jpg"


def test_batch_import_failure_deletes_only_the_uncommitted_photo_unit(monkeypatch) -> None:
    """Catches cleanup deleting a prior row's photo after that row committed successfully."""
    registered_keys: set[str] = set()
    deleted_keys: list[str] = []

    class FailingAfterFirstCommitService(FakeCollectorTransferService):
        def import_inventory(self, **payload) -> dict:
            first = payload["photos_by_collector"]["000123"]["stored"]
            registered_keys.add(str(first["storage_key"]))
            raise RuntimeError("second row failed before its photo was committed")

    service = FailingAfterFirstCommitService()
    client = client_with_service(monkeypatch, service)
    monkeypatch.setattr(
        routes,
        "save_image_bytes",
        lambda **kwargs: {
            "url": f"/static/uploads/collector-transfer/{kwargs['filename']}",
            "sha256": ("a" if kwargs["filename"].startswith("000123") else "b") * 64,
            "storage_type": "local_upload",
            "storage_key": f"collector-transfer/{kwargs['filename']}",
            "content_type": kwargs["content_type"],
            "created_new": True,
        },
    )
    monkeypatch.setattr(
        routes,
        "saved_image_is_registered",
        lambda *, team_id, stored: str(stored["storage_key"]) in registered_keys,
        raising=False,
    )
    monkeypatch.setattr(
        routes,
        "delete_saved_image",
        lambda stored: deleted_keys.append(str(stored["storage_key"])),
    )

    with pytest.raises(RuntimeError, match="second row failed"):
        client.post(
            "/collector-transfer/runs/run-1/inventory/import",
            headers=auth_headers(),
            files=[
                ("photos", ("000123.jpg", b"first", "image/jpeg")),
                ("photos", ("000456.jpg", b"second", "image/jpeg")),
            ],
        )

    assert deleted_keys == ["collector-transfer/000456.jpg"]


def test_batch_import_success_cleans_only_invalid_or_unused_photo_units(monkeypatch) -> None:
    """Catches a row-level invalid result leaking its pre-saved photo object."""
    registered_keys: set[str] = set()
    deleted_keys: list[str] = []

    class MixedOutcomeService(FakeCollectorTransferService):
        def import_inventory(self, **payload) -> dict:
            first = payload["photos_by_collector"]["000123"]["stored"]
            registered_keys.add(str(first["storage_key"]))
            return {
                "batch_id": "batch-mixed",
                "total": 2,
                "inserted": 1,
                "invalid": 1,
                "rows": [
                    {"row_number": 2, "collector_no": "000123", "outcome": "inserted"},
                    {"row_number": 3, "collector_no": "000456", "outcome": "invalid"},
                ],
            }

    service = MixedOutcomeService()
    client = client_with_service(monkeypatch, service)
    monkeypatch.setattr(
        routes,
        "save_image_bytes",
        lambda **kwargs: {
            "url": f"/static/uploads/collector-transfer/{kwargs['filename']}",
            "sha256": ("a" if kwargs["filename"].startswith("000123") else "b") * 64,
            "storage_type": "local_upload",
            "storage_key": f"collector-transfer/{kwargs['filename']}",
            "content_type": kwargs["content_type"],
            "created_new": True,
        },
    )
    monkeypatch.setattr(
        routes,
        "saved_image_is_registered",
        lambda *, team_id, stored: str(stored["storage_key"]) in registered_keys,
    )
    monkeypatch.setattr(
        routes,
        "delete_saved_image",
        lambda stored: deleted_keys.append(str(stored["storage_key"])),
    )

    response = client.post(
        "/collector-transfer/runs/run-1/inventory/import",
        headers=auth_headers(),
        files=[
            ("photos", ("000123.jpg", b"first", "image/jpeg")),
            ("photos", ("000456.jpg", b"second", "image/jpeg")),
        ],
    )

    assert response.status_code == 200
    assert deleted_keys == ["collector-transfer/000456.jpg"]


@pytest.mark.parametrize(
    ("method_name", "request_spec", "error", "status_code", "code"),
    [
        (
            "list_workbench",
            ("GET", "/collector-transfer/runs/missing/workbench", None),
            KeyError("missing"),
            404,
            "not_found",
        ),
        (
            "scan_collector",
            ("POST", "/collector-transfer/runs/run-1/scan", {"collector_no": "000123"}),
            ValueError("collector is already used"),
            400,
            "invalid_request",
        ),
        (
            "allocate",
            ("POST", "/collector-transfer/runs/run-1/allocate", None),
            CollectorAllocationConflictError("conflict"),
            409,
            "allocation_conflict",
        ),
    ],
)
def test_service_errors_have_stable_http_contracts(
    monkeypatch,
    method_name,
    request_spec,
    error,
    status_code,
    code,
) -> None:
    """Catches domain lookup/validation/conflict errors escaping as HTTP 500 responses."""
    service = FakeCollectorTransferService()

    def fail(**_payload):
        raise error

    monkeypatch.setattr(service, method_name, fail)
    client = client_with_service(
        monkeypatch,
        service,
        raise_server_exceptions=False,
    )
    method, path, json = request_spec

    response = client.request(
        method,
        path,
        headers=auth_headers(),
        json=json,
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code


def test_failed_service_call_rolls_back_the_request_session(monkeypatch) -> None:
    """Catches failed requests returning while a database transaction and row locks remain open."""

    class TrackedSession:
        def __init__(self) -> None:
            self.rollback_count = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def rollback(self) -> None:
            self.rollback_count += 1

    session = TrackedSession()
    monkeypatch.setattr(routes, "SessionLocal", lambda: session)
    request = SimpleNamespace(
        state=SimpleNamespace(auth={"team_id": "team-1", "username": "admin-a"}),
        headers={},
    )

    with pytest.raises(ValueError, match="boom"):
        with routes.service_for_request(request):
            raise ValueError("boom")

    assert session.rollback_count == 1


def test_production_roles_and_token_identity_protect_collector_transfer(monkeypatch) -> None:
    """Catches trusting spoofed team headers or allowing constructors to run admin-only actions."""
    service = FakeCollectorTransferService()
    client, headers, identities = production_client_with_service(monkeypatch, service)

    anonymous = client.get("/collector-transfer/runs")
    constructor_create = client.post(
        "/collector-transfer/runs",
        headers=headers["constructor"],
        json={"project_id": "project-1", "name": "盘点"},
    )
    constructor_import = client.post(
        "/collector-transfer/runs/run-1/inventory/import",
        headers=headers["constructor"],
    )
    constructor_allocate = client.post(
        "/collector-transfer/runs/run-1/allocate",
        headers=headers["constructor"],
    )
    reviewer_read = client.get(
        "/collector-transfer/runs",
        headers=headers["reviewer"],
    )
    constructor_scan = client.post(
        "/collector-transfer/runs/run-1/scan",
        headers={**headers["constructor"], "X-Team-Id": "spoofed-team"},
        json={"collector_no": "000123"},
    )
    constructor_read = client.get(
        "/collector-transfer/runs",
        headers=headers["constructor"],
    )
    constructor_workbench_update = client.patch(
        "/collector-transfer/workbench/items/item-1",
        headers=headers["constructor"],
        json={"completed": False},
    )
    admin_allocate = client.post(
        "/collector-transfer/runs/run-1/allocate",
        headers=headers["admin"],
    )

    assert anonymous.status_code == 401
    assert constructor_create.status_code == 403
    assert constructor_import.status_code == 403
    assert constructor_allocate.status_code == 403
    assert reviewer_read.status_code == 403
    assert constructor_scan.status_code == 200
    assert constructor_read.status_code == 200
    assert constructor_workbench_update.status_code == 200
    assert identities[0] == ("token-team", "constructor-a")
    assert admin_allocate.status_code == 409
    assert admin_allocate.json()["error"]["code"] == "pool_insufficient"


def test_request_models_reject_team_actor_and_customer_platform_credentials(monkeypatch) -> None:
    """Catches accepting identity or customer-platform secrets from an untrusted JSON body."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)

    response = client.post(
        "/collector-transfer/runs",
        headers={**auth_headers(team_id="trusted-token-team"), "X-Team-Id": "spoofed-header-team"},
        json={
            "project_id": "project-1",
            "name": "盘点",
            "team_id": "spoofed-team",
            "actor": "spoofed-admin",
            "client_username": "customer",
            "client_password": "secret",
            "client_session": "session-cookie",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert service.calls == []
