from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main as main_module
from app.api.routes import collector_transfer as routes
from app.core import security
from app.services.collector_transfer import (
    CollectorAllocationConflictError,
    CollectorPhotoConflictError,
    CollectorRunBlockedError,
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

    def scan_inventory(self, *, project_id: str, collector_no: str) -> dict:
        self.calls.append(
            ("scan_inventory", {"project_id": project_id, "collector_no": collector_no})
        )
        return {
            "collector_id": "collector-1",
            "collector_no": collector_no,
            "decision": "direct_reuse",
            "requires_photo": False,
            "add_to_pool": False,
            "pool_status": "direct",
            "photo": {"id": "photo-1"},
        }

    def register_inventory(self, **payload) -> dict:
        self.calls.append(("register_inventory", payload))
        return {
            "collector_id": "collector-1",
            "collector_no": payload["collector_no"],
            "pool_status": "available",
        }

    def list_inventory(self, *, project_id: str, status: str | None = None) -> dict:
        self.calls.append(("list_inventory", {"project_id": project_id, "status": status}))
        return {
            "items": [{"collector_id": "collector-1", "collector_no": "000123", "pool_status": "available"}],
            "total": 1,
            "stats": {"direct": 0, "available": 1, "reserved": 0, "used": 0, "awaiting_photo": 0},
        }

    def allocate(self, *, run_id: str) -> dict:
        self.calls.append(("allocate", run_id))
        raise PoolInsufficientError(required=3, available=2)

    def rollback_assignment(self, *, assignment_id: str) -> dict:
        self.calls.append(("rollback_assignment", assignment_id))
        return {"assignment_id": assignment_id, "status": "rolled_back"}

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


def test_cancelled_batch_inventory_import_route_is_not_registered(monkeypatch) -> None:
    """Catches the retired Excel/photo batch path being exposed again."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)

    response = client.post(
        "/collector-transfer/runs/run-1/inventory/import",
        headers=auth_headers(),
    )

    assert response.status_code == 404
    assert service.calls == []


def test_mobile_scan_contract_requires_project_but_no_run(monkeypatch) -> None:
    """Catches mixing customer-platform entry fields into the mobile inventory endpoint."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)

    response = client.post(
        "/collector-transfer/inventory/scan",
        headers=auth_headers(),
        json={"project_id": "11111111-1111-1111-1111-111111111111", "collector_no": "000123"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "collector_id": "collector-1",
        "collector_no": "000123",
        "decision": "direct_reuse",
        "requires_photo": False,
        "add_to_pool": False,
        "pool_status": "direct",
        "photo": {"id": "photo-1"},
    }
    assert "client_platform" not in response.text
    assert service.calls == [
        (
            "scan_inventory",
            {
                "project_id": "11111111-1111-1111-1111-111111111111",
                "collector_no": "000123",
            },
        )
    ]


def test_old_run_scoped_mobile_mutations_are_not_registered(monkeypatch) -> None:
    """Catches the retired batch prerequisite remaining callable beside the project inventory API."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)

    old_scan = client.post(
        "/collector-transfer/runs/run-1/scan",
        headers=auth_headers(),
        json={"collector_no": "000123"},
    )
    old_photo = client.post(
        "/collector-transfer/runs/run-1/collectors/collector-1/photo",
        headers=auth_headers(),
        files={"file": ("000123.jpg", b"old-route", "image/jpeg")},
    )

    assert old_scan.status_code == 404
    assert old_photo.status_code == 404
    assert service.calls == []


def test_project_inventory_list_accepts_only_known_status_filters(monkeypatch) -> None:
    """Catches list requests regaining a run selector or accepting an unbounded status value."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)

    response = client.get(
        "/collector-transfer/inventory",
        headers=auth_headers(),
        params={"project_id": "11111111-1111-1111-1111-111111111111", "status": "available"},
    )
    invalid = client.get(
        "/collector-transfer/inventory",
        headers=auth_headers(),
        params={"project_id": "11111111-1111-1111-1111-111111111111", "status": "mystery"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["total"] == 1
    assert invalid.status_code == 422
    assert service.calls == [
        (
            "list_inventory",
            {"project_id": "11111111-1111-1111-1111-111111111111", "status": "available"},
        )
    ]


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


def test_blocked_run_allocation_has_a_stable_conflict_contract(monkeypatch) -> None:
    """Catches a blocked run falling through to the generic 400 invalid-request contract."""
    service = FakeCollectorTransferService()

    def reject_blocked_run(*, run_id: str) -> dict:
        service.calls.append(("allocate", run_id))
        raise CollectorRunBlockedError("批次存在资料阻断，不能执行随机分配")

    monkeypatch.setattr(service, "allocate", reject_blocked_run)
    client = client_with_service(monkeypatch, service)

    response = client.post(
        "/collector-transfer/runs/run-blocked/allocate",
        headers=auth_headers(),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "run_blocked"
    assert response.json()["error"]["message"] == "批次存在资料阻断，不能执行随机分配。"
    assert service.calls == [("allocate", "run-blocked")]


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


def test_project_inventory_photo_passes_barcode_and_validated_storage_atomically(monkeypatch) -> None:
    """Catches exposing a pool collector before the uploaded image is durably registered."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)
    storage_calls: list[dict[str, object]] = []

    def save_inventory_image(**payload):
        storage_calls.append(payload)
        return {
            "url": "/static/uploads/collector-inventory/000123.jpg",
            "sha256": "a" * 64,
            "storage_type": "local_upload",
            "storage_key": "collector-inventory/000123.jpg",
            "content_type": "image/jpeg",
        }

    monkeypatch.setattr(
        routes,
        "save_image_bytes",
        save_inventory_image,
    )

    response = client.post(
        "/collector-transfer/inventory",
        headers=auth_headers(),
        data={
            "project_id": "11111111-1111-1111-1111-111111111111",
            "collector_no": "000123",
        },
        files={"file": ("000123.jpg", b"validated-by-storage-layer", "image/jpeg")},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "collector_id": "collector-1",
        "collector_no": "000123",
        "pool_status": "available",
    }
    call_name, payload = service.calls[0]
    assert call_name == "register_inventory"
    assert payload["project_id"] == "11111111-1111-1111-1111-111111111111"
    assert payload["collector_no"] == "000123"
    assert payload["byte_size"] == len(b"validated-by-storage-layer")
    assert payload["stored"]["sha256"] == "a" * 64
    assert storage_calls[0]["scope"] == "collector-inventory"
    assert storage_calls[0]["group_id"] == "11111111-1111-1111-1111-111111111111"
    assert "000123" in str(storage_calls[0]["key_hint"])


def test_mobile_photo_validation_error_uses_the_stable_api_error_shape(monkeypatch) -> None:
    """Catches upload validation falling back to FastAPI's unrelated detail-only error shape."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)

    def reject_image(**_kwargs):
        raise ValueError("仅支持图片文件")

    monkeypatch.setattr(routes, "save_image_bytes", reject_image)

    response = client.post(
        "/collector-transfer/inventory",
        headers=auth_headers(),
        data={
            "project_id": "11111111-1111-1111-1111-111111111111",
            "collector_no": "000123",
        },
        files={"file": ("000123.txt", b"not-an-image", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert service.calls == []


def test_project_inventory_photo_rejects_customer_platform_credentials(monkeypatch) -> None:
    """Catches the multipart inventory endpoint silently accepting customer-platform secrets."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)
    storage_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        routes,
        "save_image_bytes",
        lambda **payload: storage_calls.append(payload),
    )

    response = client.post(
        "/collector-transfer/inventory",
        headers=auth_headers(),
        data={
            "project_id": "11111111-1111-1111-1111-111111111111",
            "collector_no": "000123",
            "client_username": "customer",
            "client_password": "secret",
            "client_session": "session-cookie",
        },
        files={"file": ("000123.jpg", b"valid-looking-image", "image/jpeg")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert storage_calls == []
    assert service.calls == []


def test_project_inventory_photo_rejects_blank_barcode_before_storage(monkeypatch) -> None:
    """Catches whitespace-only barcode text creating an upload before service validation."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)
    storage_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        routes,
        "save_image_bytes",
        lambda **payload: storage_calls.append(payload),
    )

    response = client.post(
        "/collector-transfer/inventory",
        headers=auth_headers(),
        data={
            "project_id": "11111111-1111-1111-1111-111111111111",
            "collector_no": "   ",
        },
        files={"file": ("blank.jpg", b"valid-looking-image", "image/jpeg")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert storage_calls == []
    assert service.calls == []


def test_mobile_photo_sha_conflict_returns_409_and_removes_new_orphan(monkeypatch) -> None:
    """Catches a concurrent cross-collector SHA conflict leaking storage or returning 400/500."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)
    stored = {
        "url": "/static/uploads/collector-inventory/conflict.jpg",
        "sha256": "c" * 64,
        "storage_type": "local_upload",
        "storage_key": "collector-inventory/conflict.jpg",
        "content_type": "image/jpeg",
        "created_new": True,
    }
    deleted: list[str] = []
    monkeypatch.setattr(routes, "save_image_bytes", lambda **_kwargs: stored)
    monkeypatch.setattr(routes, "saved_image_is_registered", lambda **_kwargs: False)
    monkeypatch.setattr(routes, "delete_saved_image", lambda item: deleted.append(str(item["storage_key"])))

    def reject_reuse(**_kwargs):
        raise CollectorPhotoConflictError("photo content is already bound to another physical collector")

    monkeypatch.setattr(service, "register_inventory", reject_reuse)

    response = client.post(
        "/collector-transfer/inventory",
        headers=auth_headers(),
        data={
            "project_id": "11111111-1111-1111-1111-111111111111",
            "collector_no": "collector-2",
        },
        files={"file": ("collector-2.jpg", b"duplicate-image", "image/jpeg")},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "photo_conflict"
    assert deleted == ["collector-inventory/conflict.jpg"]


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
            "scan_inventory",
            (
                "POST",
                "/collector-transfer/inventory/scan",
                {"project_id": "project-1", "collector_no": "000123"},
            ),
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
    constructor_allocate = client.post(
        "/collector-transfer/runs/run-1/allocate",
        headers=headers["constructor"],
    )
    reviewer_read = client.get(
        "/collector-transfer/runs",
        headers=headers["reviewer"],
    )
    constructor_scan = client.post(
        "/collector-transfer/inventory/scan",
        headers={**headers["constructor"], "X-Team-Id": "spoofed-team"},
        json={"project_id": "project-1", "collector_no": "000123"},
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
    assert constructor_allocate.status_code == 403
    assert reviewer_read.status_code == 403
    assert constructor_scan.status_code == 200
    assert constructor_read.status_code == 200
    assert constructor_workbench_update.status_code == 200
    assert identities[0] == ("token-team", "constructor-a")
    assert admin_allocate.status_code == 409
    assert admin_allocate.json()["error"]["code"] == "pool_insufficient"


def test_only_an_administrator_can_rollback_a_collector_assignment(monkeypatch) -> None:
    """Catches exposing the compensating allocation operation to the mobile constructor role."""
    service = FakeCollectorTransferService()
    client, headers, _identities = production_client_with_service(monkeypatch, service)

    constructor = client.post(
        "/collector-transfer/assignments/assignment-1/rollback",
        headers=headers["constructor"],
    )
    administrator = client.post(
        "/collector-transfer/assignments/assignment-1/rollback",
        headers=headers["admin"],
    )

    assert constructor.status_code == 403
    assert administrator.status_code == 200
    assert administrator.json()["data"] == {"assignment_id": "assignment-1", "status": "rolled_back"}
    assert service.calls == [("rollback_assignment", "assignment-1")]


def test_transfer_project_list_is_team_isolated_and_readable_by_constructor_and_admin(monkeypatch) -> None:
    """Catches collector pages falling back to a cross-team mock project list in production."""

    class CapturingSession:
        def __init__(self) -> None:
            self.statements = []

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> bool:
            return False

        def scalars(self, statement):
            self.statements.append(statement)
            return SimpleNamespace(all=lambda: [
                SimpleNamespace(
                    id=UUID("11111111-1111-1111-1111-111111111111"),
                    name="token-team 项目",
                    status="active",
                    updated_at=datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc),
                )
            ])

    session = CapturingSession()
    service = FakeCollectorTransferService()
    client, headers, _identities = production_client_with_service(monkeypatch, service)
    monkeypatch.setattr(routes, "SessionLocal", lambda: session)

    constructor = client.get("/collector-transfer/projects", headers=headers["constructor"])
    administrator = client.get("/collector-transfer/projects", headers=headers["admin"])
    reviewer = client.get("/collector-transfer/projects", headers=headers["reviewer"])

    expected = {
        "items": [{
            "id": "11111111-1111-1111-1111-111111111111",
            "name": "token-team 项目",
            "status": "active",
            "updated_at": "2026-08-24T00:00:00+00:00",
        }]
    }
    assert constructor.status_code == 200
    assert constructor.json()["data"] == expected
    assert administrator.status_code == 200
    assert administrator.json()["data"] == expected
    assert reviewer.status_code == 403
    assert len(session.statements) == 2
    for statement in session.statements:
        compiled = statement.compile()
        assert "projects.team_id" in str(compiled)
        assert "projects.status" in str(compiled)
        assert "token-team" in {str(value) for value in compiled.params.values()}
        assert "active" in {str(value) for value in compiled.params.values()}


def test_request_models_reject_team_actor_and_customer_platform_credentials(monkeypatch) -> None:
    """Catches accepting identity or customer-platform secrets from an untrusted JSON body."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)

    response = client.post(
        "/collector-transfer/inventory/scan",
        headers={**auth_headers(team_id="trusted-token-team"), "X-Team-Id": "spoofed-header-team"},
        json={
            "project_id": "project-1",
            "collector_no": "000123",
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
