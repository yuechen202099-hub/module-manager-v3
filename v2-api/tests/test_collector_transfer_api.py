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
    CollectorDirectConflictError,
    CollectorInventoryAssignmentLockedError,
    CollectorInventoryNumberConflictError,
    CollectorInventorySnapshotChangedError,
    CollectorPhotoConflictError,
    CollectorRunBlockedError,
    CollectorSnapshotChangedError,
    CollectorTerminalSourceBlockedError,
    PoolInsufficientError,
    TerminalNoConstructedMeterError,
    TerminalNotFoundError,
    TerminalReviewRequiredError,
    TerminalSourceChangedError,
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

    def scan_inventory_photo_region(self, **payload) -> dict:
        self.calls.append(("scan_inventory_photo_region", payload))
        return {
            "barcode_type": "collector",
            "values": ["COLLECTOR-001"],
            "normalized_values": ["COLLECTOR-001"],
            "method": "barcode",
            "region": payload["region"],
        }

    def correct_inventory_number(self, **payload) -> dict:
        self.calls.append(("correct_inventory_number", payload))
        return {
            "collector_id": payload["collector_id"],
            "collector_no": payload["collector_no"],
            "decision": "direct_reuse",
            "requires_photo": False,
            "add_to_pool": False,
            "pool_status": "direct",
            "photo": {"id": "photo-1"},
        }

    def allocate(self, *, run_id: str) -> dict:
        self.calls.append(("allocate", run_id))
        raise PoolInsufficientError(required=3, available=2)

    def rollback_assignment(self, *, assignment_id: str) -> dict:
        self.calls.append(("rollback_assignment", assignment_id))
        return {"assignment_id": assignment_id, "status": "rolled_back"}

    def list_global_terminals(self, **payload) -> dict:
        self.calls.append(("list_global_terminals", payload))
        return {
            "items": [
                {
                    "terminal_key": "terminal-key-1",
                    "project_id": "project-1",
                    "terminal_code": "T-001",
                    "workflow_state": "ready",
                }
            ],
            "page": payload["page"],
            "page_size": payload["page_size"],
            "total": 1,
        }

    def open_global_terminal(self, **payload) -> dict:
        self.calls.append(("open_global_terminal", payload))
        return {
            "run_id": "run-1",
            "terminal_id": "terminal-1",
            "workbench_terminal_id": "terminal-1",
            "source_changed": False,
        }

    def open_review_workbench_terminal(self, **payload) -> dict:
        self.calls.append(("open_review_workbench_terminal", payload))
        return {
            "terminal": {
                "terminal_key": "opaque-key",
                "project_id": "project-1",
                "terminal_code": "T-001",
            },
            "workflow_state": "ready",
            "source_revision": "a" * 64,
            "meters": [{"group_id": "g-1", "meter_no": "M-001"}],
            "rephoto": {
                "meter_items": [{"meter_no": "M-001"}],
                "collector_items": [{"collector_no": "C-001"}],
            },
        }

    def global_terminal_detail(self, *, terminal_id: str) -> dict:
        self.calls.append(("global_terminal_detail", terminal_id))
        return {"run_id": "run-1", "terminal": {"id": terminal_id}}

    def replace_terminal_missing(self, *, terminal_id: str) -> dict:
        self.calls.append(("replace_terminal_missing", terminal_id))
        return {
            "run_id": "run-1",
            "terminal_id": terminal_id,
            "required": 1,
            "assigned": 1,
            "assignments": [],
        }

    def create_manual_demand(self, *, terminal_id: str, quantity: int) -> dict:
        self.calls.append(
            (
                "create_manual_demand",
                {"terminal_id": terminal_id, "quantity": quantity},
            )
        )
        return {
            "run_id": "run-1",
            "terminal_id": terminal_id,
            "required": quantity,
            "assigned": quantity,
            "assignments": [
                {
                    "assignment_id": "assignment-1",
                    "requirement_id": "requirement-1",
                    "original_collector_no": "人工需求",
                    "physical_collector_id": "collector-1",
                    "final_collector_no": "POOL-001",
                    "mode": "random",
                }
            ],
        }

    def refresh_global_terminal(self, *, terminal_id: str) -> dict:
        self.calls.append(("refresh_global_terminal", terminal_id))
        return {
            "run_id": "run-2",
            "terminal_id": "terminal-2",
            "workbench_terminal_id": "terminal-2",
            "source_changed": False,
        }

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
) -> tuple[TestClient, dict[str, dict[str, str]], list[routes.RequestIdentity]]:
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
    identities: list[routes.RequestIdentity] = []

    @contextmanager
    def fake_service_for_request(request):
        identities.append(routes.require_admin(request))
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

    assert identity.team_id == "token-team"
    assert identity.actor == "constructor-a"
    assert identity.roles == frozenset({"admin"})
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


def test_admin_opens_ready_review_workbench_terminal_with_opaque_identity(monkeypatch) -> None:
    """Catches reintroducing project or terminal identity fields at the unified API boundary."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)

    response = client.post(
        "/collector-transfer/review-workbench/terminals/open",
        headers=auth_headers(),
        json={"terminal_key": "opaque-key", "source_revision": "a" * 64},
    )

    assert response.status_code == 200
    assert response.json()["data"]["rephoto"] == {
        "meter_items": [{"meter_no": "M-001"}],
        "collector_items": [{"collector_no": "C-001"}],
    }
    assert service.calls == [
        (
            "open_review_workbench_terminal",
            {"terminal_key_value": "opaque-key", "source_revision": "a" * 64},
        )
    ]


def test_locked_review_workbench_terminal_returns_no_rephoto(monkeypatch) -> None:
    """Catches exposing re-photo controls while the authorized terminal remains review-locked."""
    service = FakeCollectorTransferService()

    def locked(**payload) -> dict:
        service.calls.append(("open_review_workbench_terminal", payload))
        return {
            "terminal": {"terminal_key": "opaque-key", "terminal_code": "T-001"},
            "workflow_state": "needs_review",
            "source_revision": "a" * 64,
            "review_blockers": [
                {
                    "group_id": "g-1",
                    "codes": ["review_not_approved", "barcode_verification_required"],
                }
            ],
            "rephoto": None,
        }

    monkeypatch.setattr(service, "open_review_workbench_terminal", locked)
    client = client_with_service(monkeypatch, service)

    response = client.post(
        "/collector-transfer/review-workbench/terminals/open",
        headers=auth_headers(),
        json={"terminal_key": "opaque-key", "source_revision": "a" * 64},
    )

    assert response.status_code == 200
    assert response.json()["data"]["workflow_state"] == "needs_review"
    assert response.json()["data"]["rephoto"] is None


@pytest.mark.parametrize("extra_field", ["project_id", "terminal_code", "actor"])
def test_review_workbench_open_rejects_extra_identity_fields(monkeypatch, extra_field) -> None:
    """Catches callers bypassing the opaque key with client-supplied resource or actor identity."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)

    response = client.post(
        "/collector-transfer/review-workbench/terminals/open",
        headers=auth_headers(),
        json={
            "terminal_key": "opaque-key",
            "source_revision": "a" * 64,
            extra_field: "spoofed",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert service.calls == []


@pytest.mark.parametrize(
    ("error", "status_code", "code", "expected_details"),
    [
        (TerminalNotFoundError("foreign-terminal"), 404, "terminal_not_found", None),
        (
            TerminalNoConstructedMeterError("no constructed meter"),
            409,
            "terminal_has_no_constructed_meter",
            None,
        ),
        (
            TerminalReviewRequiredError(
                [
                    SimpleNamespace(
                        group_id="g-1",
                        blockers=("review_not_approved", "barcode_verification_required"),
                    )
                ]
            ),
            409,
            "terminal_review_required",
            {
                "group_ids": ["g-1"],
                "blockers": [
                    {
                        "group_id": "g-1",
                        "codes": ["review_not_approved", "barcode_verification_required"],
                    }
                ],
            },
        ),
        (TerminalSourceChangedError("changed"), 409, "terminal_source_changed", None),
    ],
)
def test_review_workbench_open_maps_terminal_errors_without_resource_disclosure(
    monkeypatch,
    error,
    status_code,
    code,
    expected_details,
) -> None:
    """Catches leaking cross-team identity or unstable review-gate errors through the unified route."""
    service = FakeCollectorTransferService()

    def fail(**_payload):
        raise error

    monkeypatch.setattr(service, "open_review_workbench_terminal", fail)
    client = client_with_service(monkeypatch, service, raise_server_exceptions=False)

    response = client.post(
        "/collector-transfer/review-workbench/terminals/open",
        headers=auth_headers(),
        json={"terminal_key": "opaque-key", "source_revision": "a" * 64},
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert "foreign-terminal" not in response.text
    if expected_details is not None:
        assert response.json()["error"]["details"] == expected_details


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


def test_inventory_photo_region_scan_forwards_the_locked_snapshot(monkeypatch) -> None:
    """Catches scanning a client-selected region without binding it to the visible record snapshot."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)
    region = {"x": 0.1, "y": 0.2, "width": 0.7, "height": 0.3}

    response = client.post(
        "/collector-transfer/inventory/collector-1/photo/region-scan",
        headers=auth_headers(),
        json={
            "project_id": "11111111-1111-1111-1111-111111111111",
            "expected_collector_no": "OCR-WRONG",
            "expected_photo_sha256": "c1" * 32,
            "region": region,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["normalized_values"] == ["COLLECTOR-001"]
    assert service.calls == [
        (
            "scan_inventory_photo_region",
            {
                "project_id": "11111111-1111-1111-1111-111111111111",
                "collector_id": "collector-1",
                "expected_collector_no": "OCR-WRONG",
                "expected_photo_sha256": "c1" * 32,
                "region": region,
            },
        )
    ]


def test_inventory_number_correction_forwards_manual_confirmation(monkeypatch) -> None:
    """Catches a recognition suggestion mutating inventory without the explicit PATCH confirmation."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)
    region = {"x": 0.12, "y": 0.22, "width": 0.66, "height": 0.24}

    response = client.patch(
        "/collector-transfer/inventory/collector-1",
        headers=auth_headers(),
        json={
            "project_id": "11111111-1111-1111-1111-111111111111",
            "expected_collector_no": "OCR-WRONG",
            "expected_photo_sha256": "c2" * 32,
            "collector_no": "DIRECT-CORRECTED",
            "recognition_method": "barcode",
            "region": region,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["collector_no"] == "DIRECT-CORRECTED"
    assert service.calls == [
        (
            "correct_inventory_number",
            {
                "project_id": "11111111-1111-1111-1111-111111111111",
                "collector_id": "collector-1",
                "expected_collector_no": "OCR-WRONG",
                "expected_photo_sha256": "c2" * 32,
                "collector_no": "DIRECT-CORRECTED",
                "recognition_method": "barcode",
                "region": region,
            },
        )
    ]


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (CollectorInventorySnapshotChangedError("changed"), "inventory_snapshot_changed"),
        (CollectorInventoryAssignmentLockedError("rollback"), "inventory_assignment_locked"),
        (CollectorInventoryNumberConflictError("exists"), "inventory_number_conflict"),
    ],
)
def test_inventory_number_correction_maps_stable_conflicts(monkeypatch, error, code) -> None:
    """Catches inventory concurrency conflicts falling through to an unstable generic 400 response."""
    service = FakeCollectorTransferService()

    def fail(**_payload):
        raise error

    monkeypatch.setattr(service, "correct_inventory_number", fail)
    client = client_with_service(monkeypatch, service, raise_server_exceptions=False)
    response = client.patch(
        "/collector-transfer/inventory/collector-1",
        headers=auth_headers(),
        json={
            "project_id": "11111111-1111-1111-1111-111111111111",
            "expected_collector_no": "OCR-WRONG",
            "expected_photo_sha256": "c2" * 32,
            "collector_no": "DIRECT-CORRECTED",
            "recognition_method": "manual",
            "region": None,
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == code


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        (
            "post",
            "/collector-transfer/inventory/collector-1/photo/region-scan",
            {
                "project_id": "11111111-1111-1111-1111-111111111111",
                "expected_collector_no": "OCR-WRONG",
                "expected_photo_sha256": "c1" * 32,
                "region": {"x": 0.1, "y": 0.2, "width": 0.7, "height": 0.3},
                "actor": "spoofed",
            },
        ),
        (
            "patch",
            "/collector-transfer/inventory/collector-1",
            {
                "project_id": "11111111-1111-1111-1111-111111111111",
                "expected_collector_no": "OCR-WRONG",
                "expected_photo_sha256": "c2" * 32,
                "collector_no": "DIRECT-CORRECTED",
                "recognition_method": "manual",
                "region": None,
                "pool_status": "available",
            },
        ),
    ],
)
def test_inventory_photo_tools_reject_extra_fields(monkeypatch, method, path, payload) -> None:
    """Catches clients spoofing actor or server-owned inventory state in correction requests."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)

    response = getattr(client, method)(path, headers=auth_headers(), json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert service.calls == []


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
        (
            "global_terminal_detail",
            ("GET", "/collector-transfer/workbench/terminals/terminal-1", None),
            CollectorDirectConflictError("direct conflict"),
            409,
            "direct_conflict",
        ),
        (
            "replace_terminal_missing",
            (
                "POST",
                "/collector-transfer/workbench/terminals/terminal-1/replace-missing",
                None,
            ),
            CollectorSnapshotChangedError("source changed"),
            409,
            "snapshot_changed",
        ),
        (
            "open_global_terminal",
            (
                "POST",
                "/collector-transfer/workbench/terminals/open",
                {
                    "terminal_key": "terminal-key-1",
                    "project_id": "project-1",
                    "terminal_code": "T-001",
                },
            ),
            CollectorTerminalSourceBlockedError("terminal source is blocked"),
            409,
            "terminal_source_blocked",
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
        state=SimpleNamespace(
            auth={
                "team_id": "team-1",
                "username": "admin-a",
                "roles": ["admin"],
            }
        ),
        headers={},
    )

    with pytest.raises(ValueError, match="boom"):
        with routes.service_for_request(request):
            raise ValueError("boom")

    assert session.rollback_count == 1


def test_global_terminal_routes_enforce_role_matrix_before_service_mutations(
    monkeypatch,
) -> None:
    """Catches constructors replacing, rolling back, refreshing, or using the legacy allocator."""
    service = FakeCollectorTransferService()
    client, headers, _identities = production_client_with_service(monkeypatch, service)
    open_body = {
        "terminal_key": "terminal-key-1",
        "project_id": "11111111-1111-1111-1111-111111111111",
        "terminal_code": "T-001",
        "source_revision": "a" * 64,
    }

    constructor_list = client.get(
        "/collector-transfer/workbench/terminals",
        headers=headers["constructor"],
        params={"query": "T-001", "state": "ready", "page": 2, "page_size": 25},
    )
    constructor_open = client.post(
        "/collector-transfer/workbench/terminals/open",
        headers=headers["constructor"],
        json=open_body,
    )
    constructor_detail = client.get(
        "/collector-transfer/workbench/terminals/terminal-1",
        headers=headers["constructor"],
    )
    constructor_complete = client.patch(
        "/collector-transfer/workbench/items/item-1",
        headers=headers["constructor"],
        json={"completed": True},
    )
    forbidden_responses = [
        client.get(
            "/collector-transfer/workbench/terminals",
            headers=headers["constructor"],
            params={"include_blocked": "true"},
        ),
        client.post(
            "/collector-transfer/workbench/terminals/terminal-1/replace-missing",
            headers=headers["constructor"],
        ),
        client.post(
            "/collector-transfer/workbench/terminals/terminal-1/refresh",
            headers=headers["constructor"],
        ),
        client.post(
            "/collector-transfer/assignments/assignment-1/rollback",
            headers=headers["constructor"],
        ),
        client.post(
            "/collector-transfer/runs/run-1/allocate",
            headers=headers["constructor"],
        ),
    ]

    assert constructor_list.status_code == 403
    assert constructor_open.status_code == 403
    assert constructor_detail.status_code == 403
    assert constructor_complete.status_code == 403
    assert [response.status_code for response in forbidden_responses] == [403] * 5
    assert all(
        response.json()["error"]["code"] == "forbidden"
        for response in forbidden_responses
    )
    assert service.calls == []

    administrator_responses = [
        client.post(
            "/collector-transfer/workbench/terminals/terminal-1/replace-missing",
            headers=headers["admin"],
        ),
        client.post(
            "/collector-transfer/workbench/terminals/terminal-1/refresh",
            headers=headers["admin"],
        ),
        client.post(
            "/collector-transfer/assignments/assignment-1/rollback",
            headers=headers["admin"],
        ),
    ]
    assert [response.status_code for response in administrator_responses] == [200] * 3
    assert [name for name, _payload in service.calls[-3:]] == [
        "replace_terminal_missing",
        "refresh_global_terminal",
        "rollback_assignment",
    ]


def test_global_terminal_request_models_reject_invalid_or_spoofed_input(
    monkeypatch,
) -> None:
    """Catches unbounded queries or client-supplied identity fields reaching the service."""
    service = FakeCollectorTransferService()
    client = client_with_service(monkeypatch, service)
    headers = auth_headers(role="admin")
    invalid_responses = [
        client.get(
            "/collector-transfer/workbench/terminals",
            headers=headers,
            params={"state": "unknown"},
        ),
        client.get(
            "/collector-transfer/workbench/terminals",
            headers=headers,
            params={"page_size": 101},
        ),
        client.post(
            "/collector-transfer/workbench/terminals/open",
            headers=headers,
            json={
                "terminal_key": "",
                "project_id": "project-1",
                "terminal_code": "T-001",
            },
        ),
        client.post(
            "/collector-transfer/workbench/terminals/open",
            headers=headers,
            json={
                "terminal_key": "terminal-key-1",
                "project_id": "project-1",
                "terminal_code": "T-001",
                "team_id": "spoofed-team",
                "actor": "spoofed-admin",
                "roles": ["admin"],
            },
        ),
    ]

    assert [response.status_code for response in invalid_responses] == [422] * 4
    assert all(
        response.json()["error"]["code"] == "validation_error"
        for response in invalid_responses
    )
    assert service.calls == []


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
    assert constructor_scan.status_code == 403
    assert constructor_read.status_code == 403
    assert constructor_workbench_update.status_code == 403
    assert identities[0] == routes.RequestIdentity(
        "token-team",
        "admin-a",
        frozenset({"admin"}),
    )
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


def test_transfer_project_list_is_team_isolated_and_admin_only(monkeypatch) -> None:
    """Catches collector project discovery opening storage for non-administrators."""

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
    assert constructor.status_code == 403
    assert administrator.status_code == 200
    assert administrator.json()["data"] == expected
    assert reviewer.status_code == 403
    assert len(session.statements) == 1
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


def test_manual_collector_demand_requires_positive_quantity_and_administrator(
    monkeypatch,
) -> None:
    """Catches invalid quantities or non-administrators consuming collector-pool inventory."""
    service = FakeCollectorTransferService()
    client, headers, _identities = production_client_with_service(monkeypatch, service)
    path = "/collector-transfer/review-workbench/terminals/terminal-1/manual-demand"

    constructor = client.post(
        path,
        headers=headers["constructor"],
        json={"quantity": 1},
    )
    zero = client.post(path, headers=headers["admin"], json={"quantity": 0})
    negative = client.post(path, headers=headers["admin"], json={"quantity": -1})
    boolean = client.post(path, headers=headers["admin"], json={"quantity": True})
    spoofed = client.post(
        path,
        headers=headers["admin"],
        json={"quantity": 1, "team_id": "spoofed-team", "actor": "spoofed-admin"},
    )
    administrator = client.post(
        path,
        headers=headers["admin"],
        json={"quantity": 1},
    )

    assert constructor.status_code == 403
    assert [
        zero.status_code,
        negative.status_code,
        boolean.status_code,
        spoofed.status_code,
    ] == [422, 422, 422, 422]
    assert all(
        response.json()["error"]["code"] == "validation_error"
        for response in (zero, negative, boolean, spoofed)
    )
    assert administrator.status_code == 200
    assert administrator.json()["data"]["assignments"][0]["original_collector_no"] == "人工需求"
    assert service.calls == [
        (
            "create_manual_demand",
            {"terminal_id": "terminal-1", "quantity": 1},
        )
    ]
