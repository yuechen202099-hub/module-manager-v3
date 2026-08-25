import asyncio
import hashlib
import html
import importlib.util
import inspect
import json
import time
from copy import deepcopy
from datetime import datetime
from io import BytesIO
from threading import Event, Thread
from uuid import uuid4
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from zipfile import ZipFile

from fastapi import UploadFile
from fastapi.testclient import TestClient
import pytest
from starlette.requests import Request

import app.main as main_module
from app.main import create_app
from app.api.routes import auth, exports as export_routes, groups as group_routes, local_test, miniprogram
from app.core.config import settings
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core import security
from app.services.ezcodes_scheduler import sync_manager
from app.services import account_store, local_simulation, photo_barcode_check, photo_storage, state_repository, unmatched_review
from app.services.export_retirement import RETIREMENT_MESSAGE
from app.services.photo_storage import resolve_photo_for_response


client = TestClient(create_app())


def assert_export_retired(response) -> None:
    assert response.status_code == 410
    assert response.json() == {"detail": RETIREMENT_MESSAGE}


def build_api_workbook(rows: list[list[str]]) -> bytes:
    from io import BytesIO

    import pytest

    pytest.importorskip("openpyxl")
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def load_static_page_verifier():
    verifier_path = Path(__file__).resolve().parents[2] / "scripts" / "verify-static-pages.py"
    spec = importlib.util.spec_from_file_location("verify_static_pages", verifier_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_success_shape(payload: dict) -> None:
    assert "data" in payload
    assert payload["error"] is None
    assert isinstance(payload["request_id"], str)


def assert_active_nav(html: str, href: str) -> None:
    assert f'href="{href}"' in html
    assert (
        f'class="button active" href="{href}"' in html
        or f'class="button secondary active" href="{href}"' in html
        or f'class="nav-link active" href="{href}"' in html
    )


def assert_vue_shell_response(response) -> None:
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert '<div id="app"></div>' in response.text
    assert 'type="module"' in response.text
    assert "/vue/assets/" in response.text
    assert 'id="workFrame"' not in response.text
    assert 'embedded: "1"' not in response.text
    assert "LegacyStaticPageView" not in response.text


def production_test_settings(**overrides) -> SimpleNamespace:
    values = {
        "app_env": "production",
        "allowed_origins": ["https://www.sgcc.online", "https://sgcc.online"],
        "trusted_hosts": ["testserver", "www.sgcc.online", "sgcc.online", "127.0.0.1", "localhost"],
        "trusted_proxy_hosts": {"127.0.0.1", "::1", "localhost"},
        "security_frame_ancestors": "'self'",
        "state_backend": "postgres",
        "max_upload_mb": 20,
        "max_upload_files_per_request": 8,
        "photo_proxy_hosts": set(),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def production_rbac_client(monkeypatch, tmp_path) -> tuple[TestClient, dict[str, dict[str, str]]]:
    production_settings = production_test_settings(
        demo_auth_enabled=False,
        admin_username="root-admin",
        admin_password="RootPass12345",
        admin_team_id="north-team-01",
        auth_users_path=str(tmp_path / "rbac-users.json"),
        jwt_secret="jwt-secret-for-production-rbac-test",
        jwt_expire_minutes=60,
        trusted_proxy_hosts={"testclient"},
    )
    monkeypatch.setattr(auth, "settings", production_settings)
    monkeypatch.setattr(account_store, "settings", production_settings)
    monkeypatch.setattr(security, "settings", production_settings)
    monkeypatch.setattr(main_module, "settings", production_settings)
    monkeypatch.setattr(local_test, "settings", production_settings)
    production_client = TestClient(main_module.create_app())

    admin_login = production_client.post(
        "/auth/login",
        json={"username": "root-admin", "password": "RootPass12345"},
    )
    assert admin_login.status_code == 200
    headers = {
        "admin": {"Authorization": f"bearer {admin_login.json()['data']['access_token']}"},
    }
    reviewer_token = security.create_access_token(
        {"sub": "reviewer-a", "username": "reviewer-a", "roles": ["reviewer"], "team_id": "north-team-01"}
    )
    headers["reviewer"] = {"Authorization": f"bearer {reviewer_token}"}
    for username, password, role in (("constructor-a", "ConstructPass12345", "constructor"),):
        created = production_client.post(
            "/auth/users",
            headers=headers["admin"],
            json={
                "username": username,
                "password": password,
                "name": username,
                "roles": [role],
                "team_id": "north-team-01",
                "status": "active",
            },
        )
        assert created.status_code == 200
        login = production_client.post(
            "/auth/login",
            json={"username": username, "password": password},
        )
        assert login.status_code == 200
        headers[role] = {"Authorization": f"bearer {login.json()['data']['access_token']}"}
    return production_client, headers


def test_reviewer_only_account_is_disabled_and_cannot_authenticate(monkeypatch, tmp_path) -> None:
    users_path = tmp_path / "reviewer-only-users.json"
    users_path.write_text(
        json.dumps(
            {
                "version": 1,
                "updated_at": "2026-07-23T00:00:00+00:00",
                "users": [
                    {
                        "username": "old-reviewer",
                        "name": "Old Reviewer",
                        "roles": ["reviewer"],
                        "team_id": "north-team-01",
                        "status": "active",
                        "disabled": False,
                        "password_hash": security.hash_password("secret"),
                        "created_at": "2026-07-23T00:00:00+00:00",
                        "updated_at": "2026-07-23T00:00:00+00:00",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    production_settings = production_test_settings(
        demo_auth_enabled=False,
        admin_username="root-admin",
        admin_password="RootPass12345",
        admin_team_id="north-team-01",
        auth_users_path=str(users_path),
        jwt_secret="jwt-secret-for-reviewer-disable-test",
        jwt_expire_minutes=60,
    )
    monkeypatch.setattr(account_store, "settings", production_settings)
    monkeypatch.setattr(security, "settings", production_settings)

    users = account_store.ensure_user_store()
    migrated = users["old-reviewer"]

    assert migrated["disabled"] is True
    assert migrated["disabled_reason"] == "V3.2.0 已停用审阅员角色"
    assert account_store.authenticate_user("old-reviewer", "secret") is None


def test_review_mutation_requires_admin_after_v3_2_0(monkeypatch, tmp_path) -> None:
    production_settings = production_test_settings(
        demo_auth_enabled=False,
        admin_username="root-admin",
        admin_password="RootPass12345",
        admin_team_id="north-team-01",
        auth_users_path=str(tmp_path / "users.json"),
        jwt_secret="jwt-secret-for-review-route-test",
        jwt_expire_minutes=60,
        trusted_proxy_hosts={"testclient"},
    )
    monkeypatch.setattr(auth, "settings", production_settings)
    monkeypatch.setattr(account_store, "settings", production_settings)
    monkeypatch.setattr(security, "settings", production_settings)
    monkeypatch.setattr(main_module, "settings", production_settings)
    monkeypatch.setattr(local_test, "settings", production_settings)
    production_client = TestClient(main_module.create_app())

    class FailingRepository:
        def confirm_group_barcode_manually(self, *args, **kwargs):
            raise AssertionError("reviewer should be rejected before repository access")

    monkeypatch.setattr(local_test, "state_repository", lambda: FailingRepository())
    reviewer_token = security.create_access_token(
        {"sub": "reviewer-a", "username": "reviewer-a", "roles": ["reviewer"], "team_id": "north-team-01"}
    )
    reviewer_headers = {"Authorization": f"bearer {reviewer_token}"}

    response = production_client.post(
        "/local-test/groups/g-1/barcode-manual-confirm",
        headers=reviewer_headers,
        json={
            "actor": "reviewer-a",
            "meter_no": "METER-001",
            "module_asset_no": "MODULE-001",
            "collector": "COLLECTOR-001",
            "reason": "复核",
            "photo_ids": ["photo-1"],
        },
    )

    assert response.status_code == 403


def test_constructor_cannot_use_export_or_review_routes(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    export_response = production_client.get("/local-test/photo-barcode/review-groups/export", headers=headers["constructor"])
    review_response = production_client.post(
        "/local-test/groups/g-1/barcode-manual-confirm",
        headers=headers["constructor"],
        json={
            "actor": "constructor-a",
            "meter_no": "METER-001",
            "module_asset_no": "MODULE-001",
            "collector": "COLLECTOR-001",
            "reason": "复核",
            "photo_ids": ["photo-1"],
        },
    )

    assert_export_retired(export_response)
    assert review_response.status_code == 403


def test_production_exact_group_create_requires_admin(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    repository = FakeLegacyUnmatchedRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)

    response = production_client.post(
        "/local-test/groups",
        headers=headers["constructor"],
        json={"actor": "forged-admin", "terminal": "T-001", "meter_no": "120000000001"},
    )

    assert response.status_code == 403
    assert repository.calls == []


def test_production_group_create_rejects_placeholder_formal_identity(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    repository = FakeLegacyUnmatchedRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)
    invalid_cases = (
        ("", "120000000001"),
        ("00000000", "120000000001"),
        ("未关联终端", "120000000001"),
        ("manual-terminal", "120000000001"),
        ("unmatched-terminal", "120000000001"),
        ("T-001", ""),
        ("T-001", "00000000"),
        ("T-001", "未关联终端"),
        ("T-001", "manual-meter"),
        ("T-001", "unmatched-meter"),
    )

    for terminal, meter_no in invalid_cases:
        response = production_client.post(
            "/local-test/groups",
            headers=headers["admin"],
            json={"actor": "forged-admin", "terminal": terminal, "meter_no": meter_no},
        )
        assert response.status_code == 400, (terminal, meter_no, response.text)

    invalid_match_key = production_client.post(
        "/local-test/groups",
        headers=headers["admin"],
        json={
            "actor": "forged-admin",
            "terminal": "T-001",
            "meter_no": "120000000001",
            "meter_match_key": "manual-match-key",
        },
    )
    assert invalid_match_key.status_code == 400

    assert repository.calls == []


def test_barcode_maintenance_routes_are_admin_only_and_never_run_recognition(
    monkeypatch,
    tmp_path,
) -> None:
    from app.api.routes import barcode_maintenance
    from app.services import barcode_maintenance_worker

    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        barcode_maintenance_worker,
        "scan_group_evidence",
        lambda *_args, **_kwargs: pytest.fail("admin API must not execute recognition"),
    )
    monkeypatch.setattr(
        barcode_maintenance,
        "maintenance_status",
        lambda: {"paused": True, "verification_pending": 2, "delivery_cache_pending": 1},
    )
    monkeypatch.setattr(
        barcode_maintenance,
        "set_maintenance_paused",
        lambda paused, actor: calls.append(("paused", paused, actor)) or {"paused": paused},
    )
    monkeypatch.setattr(
        barcode_maintenance,
        "enqueue_verification_jobs",
        lambda group_ids, actor: calls.append(("enqueue", tuple(group_ids), actor))
        or {"enqueued": len(group_ids)},
    )

    assert production_client.get("/barcode-maintenance/status", headers=headers["reviewer"]).status_code == 403
    status = production_client.get("/barcode-maintenance/status", headers=headers["admin"])
    paused = production_client.post("/barcode-maintenance/pause", headers=headers["admin"])
    resumed = production_client.post("/barcode-maintenance/resume", headers=headers["admin"])
    enqueued = production_client.post(
        "/barcode-maintenance/enqueue",
        headers=headers["admin"],
        json={"group_ids": ["group-1", "group-2"]},
    )

    assert status.status_code == 200
    assert status.json()["data"]["paused"] is True
    assert paused.status_code == 200
    assert resumed.status_code == 200
    assert enqueued.status_code == 200
    assert enqueued.json()["data"]["enqueued"] == 2
    assert calls == [
        ("paused", True, "root-admin"),
        ("paused", False, "root-admin"),
        ("enqueue", ("group-1", "group-2"), "root-admin"),
    ]


def test_barcode_maintenance_route_fails_closed_when_backend_is_unavailable(
    monkeypatch,
    tmp_path,
) -> None:
    from app.api.routes import barcode_maintenance

    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    monkeypatch.setattr(
        barcode_maintenance,
        "maintenance_status",
        lambda: (_ for _ in ()).throw(state_repository.StateBackendNotReady("backend unavailable")),
    )

    response = production_client.get("/barcode-maintenance/status", headers=headers["admin"])

    assert response.status_code == 503
    assert "backend unavailable" in response.text


def test_production_legacy_unmatched_mutations_require_admin(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    repository = FakeLegacyUnmatchedRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)

    for method, suffix, body in legacy_unmatched_mutation_cases():
        response = production_client.request(
            method,
            f"/local-test/unmatched/u-1/{suffix}",
            headers=headers["reviewer"],
            json=body,
        )
        assert response.status_code == 403

    assert repository.calls == []


def test_production_legacy_unmatched_match_writes_return_gone(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    repository = FakeLegacyUnmatchedRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)
    retired_cases = [case for case in legacy_unmatched_mutation_cases() if case[1] in {"rematch", "associate", "create-group"}]

    for method, suffix, body in retired_cases:
        response = production_client.request(
            method,
            f"/local-test/unmatched/u-1/{suffix}",
            headers=headers["admin"],
            json=body,
        )
        assert response.status_code == 410
        assert "/review" in response.text
        assert "/candidates" in response.text
        assert "/finalize-match" in response.text

    assert repository.calls == []


def test_unmatched_mutation_rejects_stale_version_without_write_or_audit(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    repository = FakeLegacyUnmatchedRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)
    before = repository.snapshot()

    response = production_client.patch(
        "/local-test/unmatched/u-1",
        headers=headers["admin"],
        json={"actor": "forged", "expected_version": 1, "updates": {"note": "stale"}},
    )

    assert response.status_code == 409
    assert repository.snapshot() == before


def test_production_legacy_unmatched_mutation_uses_authenticated_actor(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    repository = FakeLegacyUnmatchedRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)

    response = production_client.patch(
        "/local-test/unmatched/u-1",
        headers=headers["admin"],
        json={"actor": "forged", "expected_version": 2, "updates": {"note": "trusted"}},
    )

    assert response.status_code == 200
    assert repository.calls[-1]["actor"] == "root-admin"


def test_unmatched_review_response_hides_raw_photo_urls(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class UnsafeReviewRepository(FakeUnmatchedReviewRepository):
        def _review(self, unmatched_id: str) -> dict:
            payload = super()._review(unmatched_id)
            payload["record"]["photo_urls"] = ["https://cdn.allowed.test/raw.jpg?token=secret"]
            payload["record"]["raw"] = {"source_url": "https://cdn.allowed.test/raw.jpg?token=secret"}
            payload["review"]["raw"] = {"photo_urls": ["https://cdn.allowed.test/nested.jpg?token=secret"]}
            payload["review"]["photos"][0].update(
                {
                    "image_url": "https://cdn.allowed.test/image.jpg?token=secret",
                    "signed_url": "https://cdn.allowed.test/signed.jpg?token=secret",
                    "raw": {"photo_urls": ["https://cdn.allowed.test/deep.jpg?token=secret"]},
                }
            )
            return payload

    repository = UnsafeReviewRepository("https://cdn.allowed.test/raw.jpg?token=secret")
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)

    payload = production_client.get(
        "/local-test/unmatched/unmatched-1/review",
        headers=headers["admin"],
    ).json()["data"]
    serialized = json.dumps(payload)

    assert "source_url" not in serialized
    assert "image_url" not in serialized
    assert "signed_url" not in serialized
    assert "photo_urls" not in serialized
    assert "raw" not in serialized
    assert "token=secret" not in serialized
    photo = payload["review"]["photos"][0]
    assert photo["content_url"] == "/local-test/unmatched/unmatched-1/photos/photo-1/content"
    assert set(photo) == {"id", "category", "content_url"}


def test_unmatched_list_response_projects_safe_record_fields(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class UnsafeListRepository(FakeLegacyUnmatchedRepository):
        def list_unmatched_records(self, *, query: str, limit: int, offset: int) -> dict:
            return {
                "total": 1,
                "items": [
                    {
                        "unmatched_id": "u-unsafe",
                        "meter_no": "120000000001",
                        "review_version": 3,
                        "photo_urls": ["https://cdn.allowed.test/raw.jpg?token=secret"],
                        "signed_url": "https://cdn.allowed.test/signed.jpg?token=secret",
                        "raw": {
                            "source_url": "https://cdn.allowed.test/nested.jpg?token=secret",
                            "photo_urls": ["https://cdn.allowed.test/deep.jpg?token=secret"],
                        },
                    }
                ],
            }

    monkeypatch.setattr(local_test, "state_repository", lambda: UnsafeListRepository())

    response = production_client.get("/local-test/unmatched", headers=headers["admin"])
    serialized = json.dumps(response.json()["data"])

    assert response.status_code == 200
    assert response.json()["data"]["items"][0]["unmatched_id"] == "u-unsafe"
    assert response.json()["data"]["items"][0]["review_version"] == 3
    assert "source_url" not in serialized
    assert "signed_url" not in serialized
    assert "photo_urls" not in serialized
    assert "raw" not in serialized
    assert "token=secret" not in serialized


@pytest.mark.parametrize(
    ("method", "path", "body", "wrapped"),
    (
        ("POST", "/local-test/unmatched/blank", {"actor": "forged"}, True),
        ("PATCH", "/local-test/unmatched/u-1", {"expected_version": 2, "updates": {"note": "updated"}}, True),
        (
            "PATCH",
            "/local-test/unmatched/u-1/assign",
            {"expected_version": 2, "constructor": "worker-a"},
            True,
        ),
        ("PATCH", "/local-test/unmatched/u-1/unassign", {"expected_version": 2, "reason": "retry"}, True),
        ("POST", "/local-test/unmatched/u-1/outside-project", {"expected_version": 2, "note": "outside"}, True),
        ("POST", "/local-test/unmatched/u-1/delete", {"expected_version": 2, "reason": "duplicate"}, False),
    ),
)
def test_active_unmatched_mutation_responses_project_safe_record_fields(
    monkeypatch,
    tmp_path,
    method: str,
    path: str,
    body: dict,
    wrapped: bool,
) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class UnsafeMutationRepository(FakeLegacyUnmatchedRepository):
        @staticmethod
        def _unsafe(record: dict) -> dict:
            return {
                **record,
                "meter_no": "120000000001",
                "photo_urls": ["https://cdn.allowed.test/raw.jpg?token=secret"],
                "signed_url": "https://cdn.allowed.test/signed.jpg?token=secret",
                "database_id": "internal-database-id",
                "catalog_row_db_id": "internal-catalog-id",
                "target_group_id": "internal-target-id",
                "raw": {"storage_key": "private/photo.jpg", "secret": "must-not-leak"},
            }

        def _mutate(self, method: str, *, actor: str, expected_version: int | None = None, **payload) -> dict:
            result = super()._mutate(method, actor=actor, expected_version=expected_version, **payload)
            result["record"] = self._unsafe(result["record"])
            return result

        def create_blank_unmatched_record(self, *, actor: str) -> dict:
            return {"record": self._unsafe(deepcopy(self.record))}

        def delete_unmatched_record(self, unmatched_id: str, *, actor: str, expected_version: int | None = None, **payload) -> dict:
            return self._mutate("delete", actor=actor, expected_version=expected_version, **payload)["record"]

    monkeypatch.setattr(local_test, "state_repository", lambda: UnsafeMutationRepository())

    response = production_client.request(method, path, headers=headers["admin"], json=body)
    payload = response.json()["data"]
    record = payload["record"] if wrapped else payload
    serialized = json.dumps(payload)

    assert response.status_code == 200
    assert record["unmatched_id"] == "u-1"
    assert record["meter_no"] == "120000000001"
    for private_value in (
        "photo_urls",
        "signed_url",
        "database_id",
        "catalog_row_db_id",
        "target_group_id",
        "raw",
        "token=secret",
        "private/photo.jpg",
        "must-not-leak",
    ):
        assert private_value not in serialized


def test_unmatched_list_response_preserves_full_filtered_stats(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class StatsListRepository(FakeLegacyUnmatchedRepository):
        def list_unmatched_records(self, *, query: str, limit: int, offset: int) -> dict:
            assert query == "status-stats"
            assert limit == 1
            assert offset == 0
            return {
                "total": 3,
                "limit": limit,
                "offset": offset,
                "items": [{"unmatched_id": "u-page-1", "review_version": 1}],
                "stats": {
                    "pending": "1",
                    "assigned": 1,
                    "outside": 1,
                    "private_note": "must-not-leak",
                },
            }

    monkeypatch.setattr(local_test, "state_repository", lambda: StatsListRepository())

    response = production_client.get(
        "/local-test/unmatched?query=status-stats&limit=1&offset=0",
        headers=headers["admin"],
    )
    payload = response.json()["data"]

    assert response.status_code == 200
    assert payload["total"] == 3
    assert len(payload["items"]) == 1
    assert payload["stats"] == {"pending": 1, "assigned": 1, "outside": 1}


def test_production_constructor_unmatched_list_is_scoped_to_authenticated_actor(
    monkeypatch,
    tmp_path,
) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class ScopedListRepository(FakeLegacyUnmatchedRepository):
        def __init__(self) -> None:
            super().__init__()
            self.list_calls: list[dict] = []

        def list_unmatched_records(
            self,
            *,
            query: str,
            limit: int,
            offset: int,
            assigned_to: str = "",
        ) -> dict:
            self.list_calls.append(
                {
                    "query": query,
                    "limit": limit,
                    "offset": offset,
                    "assigned_to": assigned_to,
                }
            )
            return {
                "total": 0,
                "limit": limit,
                "offset": offset,
                "items": [],
                "stats": {"pending": 0, "assigned": 0, "outside": 0},
            }

    repository = ScopedListRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)

    constructor = production_client.get(
        "/local-test/unmatched?query=mine&limit=20&offset=0",
        headers=headers["constructor"],
    )
    admin = production_client.get(
        "/local-test/unmatched?query=all&limit=20&offset=0",
        headers=headers["admin"],
    )

    assert constructor.status_code == 200
    assert admin.status_code == 200
    assert repository.list_calls == [
        {"query": "mine", "limit": 20, "offset": 0, "assigned_to": "constructor-a"},
        {"query": "all", "limit": 20, "offset": 0, "assigned_to": ""},
    ]


def test_production_unmatched_export_is_retired_for_every_role(
    monkeypatch,
    tmp_path,
) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    constructor = production_client.get(
        "/local-test/unmatched/export?query=full-list",
        headers=headers["constructor"],
    )
    reviewer = production_client.get(
        "/local-test/unmatched/export?query=full-list",
        headers=headers["reviewer"],
    )
    admin = production_client.get(
        "/local-test/unmatched/export?query=full-list",
        headers=headers["admin"],
    )

    assert_export_retired(constructor)
    assert_export_retired(reviewer)
    assert_export_retired(admin)


def test_production_unmatched_export_is_retired_before_snapshot_validation(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    response = production_client.get(
        "/local-test/unmatched/export",
        headers=headers["admin"],
    )

    assert_export_retired(response)


def test_production_unmatched_dedupe_is_retired_without_write_or_audit(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    repository = FakeLegacyUnmatchedRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)
    before = repository.snapshot()

    response = production_client.post(
        "/local-test/unmatched/dedupe",
        headers=headers["admin"],
        json={"actor": "forged-admin"},
    )

    assert response.status_code == 410
    assert repository.snapshot() == before


class FakeUnmatchedReviewRepository:
    def __init__(self, source_url: str = "https://cdn.allowed.test/server-photo.jpg") -> None:
        self.calls: list[dict] = []
        self.review = {
            "unmatched_id": "unmatched-1",
            "version": 2,
            "state": "pending",
            "manual_confirmed": False,
            "photos": [{"id": "photo-1", "source_url": source_url}],
        }

    def _review(self, unmatched_id: str) -> dict:
        if unmatched_id != "unmatched-1":
            raise KeyError(unmatched_id)
        return {"record": {"unmatched_id": unmatched_id}, "review": self.review}

    def get_unmatched_review(self, unmatched_id: str) -> dict:
        self.calls.append({"method": "get", "unmatched_id": unmatched_id})
        return self._review(unmatched_id)

    def list_unmatched_match_candidates(self, unmatched_id: str, *, actor: str) -> dict:
        self.calls.append({"method": "candidates", "unmatched_id": unmatched_id, "actor": actor})
        self._review(unmatched_id)
        return {"total": 1, "items": [{"candidate_key": "catalog:row-1", "terminal": "TERM-1"}]}

    def save_unmatched_review(self, unmatched_id: str, *, actor: str, expected_version: int, **payload) -> dict:
        self.calls.append({"method": "save", "actor": actor, "expected_version": expected_version, **payload})
        self._review(unmatched_id)
        if expected_version != 2:
            raise unmatched_review.ReviewVersionConflict("stale")
        if payload.get("state") == "invalid":
            raise ValueError("Unsupported review state")
        return {"record": self._review(unmatched_id)["record"], "review": self.review, "actor": actor}

    def rescan_unmatched_review_photo(
        self,
        unmatched_id: str,
        photo_id: str,
        *,
        actor: str,
        expected_version: int,
        category: str = "",
    ) -> dict:
        self.calls.append(
            {
                "method": "rescan",
                "actor": actor,
                "photo_id": photo_id,
                "expected_version": expected_version,
                "category": category,
            }
        )
        review = self._review(unmatched_id)["review"]
        if photo_id != "photo-1":
            raise KeyError(photo_id)
        if expected_version != review["version"]:
            raise unmatched_review.ReviewVersionConflict("stale")
        return {"record": self._review(unmatched_id)["record"], "review": review, "actor": actor}

    def confirm_unmatched_review(self, unmatched_id: str, *, actor: str, expected_version: int, confirmed: bool = True) -> dict:
        self.calls.append({"method": "confirm", "actor": actor, "expected_version": expected_version, "confirmed": confirmed})
        self._review(unmatched_id)
        if expected_version != 2:
            raise unmatched_review.ReviewVersionConflict("stale")
        return {
            "record": self._review(unmatched_id)["record"],
            "review": {**self.review, "manual_confirmed": bool(confirmed)},
            "actor": actor,
        }

    def finalize_unmatched_match(self, unmatched_id: str, *, actor: str, candidate_key: str, expected_version: int) -> dict:
        self.calls.append({"method": "finalize", "actor": actor, "candidate_key": candidate_key, "expected_version": expected_version})
        self._review(unmatched_id)
        if expected_version != 2:
            raise unmatched_review.ReviewVersionConflict("stale")
        if candidate_key != "catalog:row-1":
            raise ValueError("Selected candidate is invalid or unavailable")
        return {"group": {"id": "group-1"}, "attached": False, "actor": actor}


class FakeLegacyUnmatchedRepository:
    def __init__(self) -> None:
        self.record = {"unmatched_id": "u-1", "review_version": 2, "note": "before"}
        self.calls: list[dict] = []
        self.audit: list[dict] = []

    def snapshot(self) -> dict:
        return deepcopy({"record": self.record, "calls": self.calls, "audit": self.audit})

    def _mutate(self, method: str, *, actor: str, expected_version: int | None = None, **payload) -> dict:
        if expected_version is not None and expected_version != self.record["review_version"]:
            raise unmatched_review.ReviewVersionConflict("stale")
        self.calls.append({"method": method, "actor": actor, "expected_version": expected_version, **payload})
        self.audit.append({"method": method, "actor": actor})
        self.record = {**self.record, **payload, "review_version": self.record["review_version"] + 1}
        return {"record": deepcopy(self.record)}

    def create_empty_group_for_terminal(self, *, actor: str, **payload) -> dict:
        self.calls.append({"method": "create_empty_group", "actor": actor, **payload})
        return {"group": {"id": "group-1", **payload}}

    def dedupe_unmatched_records(self, *, actor: str) -> dict:
        self.calls.append({"method": "dedupe", "actor": actor})
        self.audit.append({"method": "dedupe", "actor": actor})
        return {"removed": 1}

    def update_unmatched_record(self, unmatched_id: str, *, actor: str, expected_version: int | None = None, updates=None) -> dict:
        return self._mutate("update", actor=actor, expected_version=expected_version, **(updates or {}))

    def assign_unmatched_record(self, unmatched_id: str, *, actor: str, expected_version: int | None = None, **payload) -> dict:
        return self._mutate("assign", actor=actor, expected_version=expected_version, **payload)

    def unassign_unmatched_record(self, unmatched_id: str, *, actor: str, expected_version: int | None = None, **payload) -> dict:
        return self._mutate("unassign", actor=actor, expected_version=expected_version, **payload)

    def mark_unmatched_outside_project(self, unmatched_id: str, *, actor: str, expected_version: int | None = None, **payload) -> dict:
        return self._mutate("outside-project", actor=actor, expected_version=expected_version, **payload)

    def rematch_unmatched_record(self, unmatched_id: str, *, actor: str, expected_version: int | None = None, **payload) -> dict:
        return {"matched": False, **self._mutate("rematch", actor=actor, expected_version=expected_version, **payload)}

    def associate_unmatched_record(self, unmatched_id: str, *, actor: str, expected_version: int | None = None, **payload) -> dict:
        self._mutate("associate", actor=actor, expected_version=expected_version, **payload)
        return {"group": {"id": "group-1"}}

    def create_group_from_unmatched_record(self, unmatched_id: str, *, actor: str, expected_version: int | None = None, **payload) -> dict:
        self._mutate("create-group", actor=actor, expected_version=expected_version, **payload)
        return {"group": {"id": "group-1"}}

    def delete_unmatched_record(self, unmatched_id: str, *, actor: str, expected_version: int | None = None, **payload) -> dict:
        return self._mutate("delete", actor=actor, expected_version=expected_version, **payload)


def test_group_region_scan_resolves_trusted_photo_without_mutating_state(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class TrustedGroupRepository:
        def __init__(self) -> None:
            self.group = {
                "id": "group-1",
                "photos": [{"id": "photo-1", "source_url": "https://server.example/photo.jpg"}],
            }

        def get_group(self, group_id: str):
            return self.group if group_id == self.group["id"] else None

    repository = TrustedGroupRepository()
    before = deepcopy(repository.group)
    scanned_photos = []

    def scan(photo, barcode_type, region):
        scanned_photos.append(photo)
        return {
            "barcode_type": barcode_type,
            "values": ["3130001122100009124734"],
            "normalized_values": ["3130001122100009124734"],
            "method": "barcode",
            "region": region,
            "photo_id": photo["id"],
        }

    monkeypatch.setattr(local_test, "state_repository", lambda: repository)
    monkeypatch.setattr(photo_barcode_check, "scan_photo_region", scan)

    body = {
        "barcode_type": "module",
        "region": {"x": 0.25, "y": 0.3, "width": 0.4, "height": 0.18},
    }
    response = production_client.post(
        "/local-test/groups/group-1/photos/photo-1/region-scan",
        headers=headers["admin"],
        json=body,
    )
    untrusted_source = production_client.post(
        "/local-test/groups/group-1/photos/photo-1/region-scan",
        headers=headers["admin"],
        json={**body, "url": "http://127.0.0.1/private"},
    )
    missing = production_client.post(
        "/local-test/groups/other-team-group/photos/photo-1/region-scan",
        headers=headers["admin"],
        json=body,
    )

    assert response.status_code == 200
    assert response.json()["data"]["photo_id"] == "photo-1"
    assert scanned_photos == [repository.group["photos"][0]]
    assert repository.group == before
    assert untrusted_source.status_code == 422
    assert missing.status_code == 404


def test_unmatched_region_scan_rejects_worker_and_unknown_photo(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    repository = FakeUnmatchedReviewRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)
    monkeypatch.setattr(
        photo_barcode_check,
        "scan_photo_region",
        lambda photo, barcode_type, region: {"photo_id": photo["id"], "barcode_type": barcode_type, "region": region},
    )
    body = {
        "barcode_type": "meter",
        "region": {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5},
    }

    denied = production_client.post(
        "/local-test/unmatched/unmatched-1/photos/photo-1/region-scan",
        headers=headers["constructor"],
        json=body,
    )
    missing = production_client.post(
        "/local-test/unmatched/unmatched-1/photos/not-present/region-scan",
        headers=headers["admin"],
        json=body,
    )

    assert denied.status_code == 403
    assert missing.status_code == 404
    assert repository.calls == [{"method": "get", "unmatched_id": "unmatched-1"}]


def test_region_scan_rejects_invalid_payloads_and_hides_image_source(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class TrustedGroupRepository:
        group = {"id": "group-1", "photos": [{"id": "photo-1"}]}

        def get_group(self, group_id: str):
            return self.group if group_id == self.group["id"] else None

    monkeypatch.setattr(local_test, "state_repository", TrustedGroupRepository)
    monkeypatch.setattr(
        photo_barcode_check,
        "scan_photo_region",
        lambda _photo, _barcode_type, _region: (_ for _ in ()).throw(
            ValueError("Photo image is unavailable at C:\\private\\photo.jpg")
        ),
    )
    base = {"barcode_type": "meter", "region": {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5}}
    invalid_bodies = [
        {**base, "barcode_type": "invalid"},
        {**base, "region": {"x": "NaN", "y": 0.1, "width": 0.5, "height": 0.5}},
        {**base, "region": {"x": 0.8, "y": 0.1, "width": 0.3, "height": 0.5}},
        {**base, "region": {"x": 0.1, "y": 0.1, "width": 0.001, "height": 0.001}},
    ]

    for body in invalid_bodies:
        response = production_client.post(
            "/local-test/groups/group-1/photos/photo-1/region-scan",
            headers=headers["admin"],
            json=body,
        )
        assert response.status_code == 422

    unavailable = production_client.post(
        "/local-test/groups/group-1/photos/photo-1/region-scan",
        headers=headers["admin"],
        json=base,
    )

    assert unavailable.status_code == 422
    assert unavailable.json()["detail"] == "Image recognition unavailable"
    assert "private" not in unavailable.text


def legacy_unmatched_mutation_cases():
    return (
        ("PATCH", "assign", {"actor": "forged-admin", "expected_version": 2, "constructor": "worker-a"}),
        ("PATCH", "unassign", {"actor": "forged-admin", "expected_version": 2, "reason": "test"}),
        ("POST", "outside-project", {"actor": "forged-admin", "expected_version": 2, "note": "test"}),
        ("POST", "rematch", {"actor": "forged-admin", "expected_version": 2, "meter_no": "120000000001"}),
        ("POST", "associate", {"actor": "forged-admin", "expected_version": 2, "target_group_id": "g-1"}),
        ("POST", "create-group", {"actor": "forged-admin", "expected_version": 2, "terminal": "T-001"}),
        ("POST", "delete", {"actor": "forged-admin", "expected_version": 2, "reason": "test"}),
    )


class ApiReviewSession:
    def __init__(self, record: SimpleNamespace, tracker: dict) -> None:
        self.record = record
        self.record_snapshot = deepcopy(vars(record))
        self.tracker = tracker
        self.statements = []
        self.staged = []

    def __enter__(self):
        self.tracker["active_sessions"] += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        self.tracker["active_sessions"] -= 1
        return False

    def scalar(self, statement):
        self.statements.append(statement)
        return self.record

    def add(self, value):
        self.staged.append(value)
        self.tracker["staged"].append(value)

    def commit(self):
        self.tracker["commits"] += 1

    def rollback(self):
        self.tracker["rollbacks"] += 1
        vars(self.record).clear()
        vars(self.record).update(deepcopy(self.record_snapshot))


def test_postgres_photo_storage_repair_invalidates_verification_before_commit(monkeypatch) -> None:
    from app.services import delivery_cache

    group = SimpleNamespace(id=uuid4(), legacy_id="group-repair", team_id="team-repair")
    photo = SimpleNamespace(
        id=uuid4(),
        legacy_id="photo-repair",
        image_url="https://old.example/photo.jpg",
        storage_type="oss",
        storage_bucket="old-bucket",
        storage_key="old-key",
        sha256="a" * 64,
        object_key="old-key",
        byte_size=1,
        content_type="image/jpeg",
        raw_data={},
    )
    tracker = {"commits": 0, "row_locks": []}

    class RepairSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, statement):
            tracker["row_locks"].append(statement._for_update_arg is not None)
            return group if "material_groups" in str(statement) else photo

        def commit(self):
            tracker["commits"] += 1

    invalidations = []
    package_invalidations = []
    monkeypatch.setattr(local_test.settings, "state_backend", "postgres")
    monkeypatch.setattr(local_test, "SessionLocal", lambda: RepairSession())
    monkeypatch.setattr(local_test, "current_team_id", lambda: "team-repair")
    monkeypatch.setattr(
        local_test,
        "invalidate_verification_for_group",
        lambda session, changed_group, actor, reason: invalidations.append(
            (session, changed_group, actor, reason, tracker["commits"])
        ),
        raising=False,
    )
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda session, changed_group, *, actor, reason: package_invalidations.append(
            (session, changed_group, actor, reason, tracker["commits"])
        ),
    )

    local_test._persist_repaired_photo_storage(
        "group-repair",
        {
            "id": "photo-repair",
            "image_url": "https://new.example/photo.jpg",
            "storage_type": "oss",
            "storage_bucket": "new-bucket",
            "storage_key": "new-key",
            "sha256": "b" * 64,
            "byte_size": 2,
            "content_type": "image/jpeg",
        },
    )

    assert len(invalidations) == 1
    _session, changed_group, actor, reason, commits_before_invalidation = invalidations[0]
    assert changed_group is group
    assert actor == "photo-storage-repair"
    assert reason == "photo_replaced"
    assert commits_before_invalidation == 0
    assert len(package_invalidations) == 1
    _session, changed_group, actor, reason, commits_before_invalidation = package_invalidations[0]
    assert changed_group is group
    assert actor == "photo-storage-repair"
    assert reason == "photo_replaced"
    assert commits_before_invalidation == 0
    assert tracker["commits"] == 1
    assert tracker["row_locks"] == [True, True]


def test_json_photo_storage_repair_persists_for_restart_and_invalidates_verification(monkeypatch) -> None:
    group = {
        "id": "group-repair",
        "photos": [{"id": "photo-repair", "image_url": "https://old.example/photo.jpg"}],
    }
    invalidations = []
    persisted = []
    monkeypatch.setattr(local_test.settings, "state_backend", "json")
    monkeypatch.setattr(local_test, "get_group", lambda group_id: group if group_id == "group-repair" else None)
    monkeypatch.setattr(local_test, "save_all_team_states", lambda: persisted.append(deepcopy(group)))
    monkeypatch.setattr(
        state_repository,
        "invalidate_verification_for_group",
        lambda session, changed_group, actor, reason: invalidations.append(
            (session, changed_group, actor, reason)
        ),
        raising=False,
    )

    local_test._persist_repaired_photo_storage(
        "group-repair",
        {"id": "photo-repair", "image_url": "https://new.example/photo.jpg", "sha256": "b" * 64},
    )

    assert invalidations == [(None, group, "photo-storage-repair", "photo_replaced")]
    assert persisted[0]["photos"][0]["image_url"] == "https://new.example/photo.jpg"
    group["photos"][0]["image_url"] = "https://mutated-after-save.example/photo.jpg"
    assert persisted[0]["photos"][0]["image_url"] == "https://new.example/photo.jpg"


def test_json_photo_storage_repair_persistence_failure_does_not_mutate_live_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id = f"json-photo-repair-rollback-{uuid4()}"
    state = local_simulation.blank_state(team_id)
    state["groups"] = [
        {
            "id": "group-repair",
            "photos": [
                {
                    "id": "photo-repair",
                    "image_url": "https://old.example/photo.jpg",
                    "sha256": "a" * 64,
                }
            ],
        }
    ]
    before = deepcopy(state)
    monkeypatch.setitem(local_simulation._team_states, team_id, state)
    monkeypatch.setattr(local_test.settings, "state_backend", "json")
    monkeypatch.setattr(local_test, "current_team_id", lambda: team_id)
    monkeypatch.setattr(
        local_test,
        "save_all_team_states",
        lambda: (_ for _ in ()).throw(RuntimeError("injected repair persistence failure")),
    )

    token = local_simulation.set_current_team(team_id)
    try:
        with pytest.raises(RuntimeError, match="injected repair persistence failure"):
            local_test._persist_repaired_photo_storage(
                "group-repair",
                {
                    "id": "photo-repair",
                    "image_url": "https://new.example/photo.jpg",
                    "sha256": "b" * 64,
                },
            )
    finally:
        local_simulation.reset_current_team(token)

    assert local_simulation._team_states[team_id] == before


@pytest.mark.parametrize("missing", ["group", "photo"])
def test_postgres_photo_storage_repair_rejects_concurrently_deleted_target(
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    group = SimpleNamespace(id=uuid4(), legacy_id="group-repair", team_id="team-repair")

    class RepairSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, statement):
            if "material_groups" in str(statement):
                return None if missing == "group" else group
            return None

    monkeypatch.setattr(local_test.settings, "state_backend", "postgres")
    monkeypatch.setattr(local_test, "SessionLocal", lambda: RepairSession())
    monkeypatch.setattr(local_test, "current_team_id", lambda: "team-repair")

    with pytest.raises(KeyError, match="group-repair|photo-repair"):
        local_test._persist_repaired_photo_storage("group-repair", {"id": "photo-repair"})


def test_postgres_photo_storage_repair_commit_failure_is_not_reported_as_success(monkeypatch) -> None:
    from app.services import delivery_cache

    group = SimpleNamespace(id=uuid4(), legacy_id="group-repair", team_id="team-repair")
    photo = SimpleNamespace(
        id=uuid4(),
        legacy_id="photo-repair",
        image_url="https://old.example/photo.jpg",
        storage_type="oss",
        storage_bucket="old-bucket",
        storage_key="old-key",
        sha256="a" * 64,
        object_key="old-key",
        byte_size=1,
        content_type="image/jpeg",
        raw_data={},
    )

    class FailingRepairSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, statement):
            return group if "material_groups" in str(statement) else photo

        def commit(self):
            raise RuntimeError("injected repair commit failure")

    monkeypatch.setattr(local_test.settings, "state_backend", "postgres")
    monkeypatch.setattr(local_test, "SessionLocal", lambda: FailingRepairSession())
    monkeypatch.setattr(local_test, "current_team_id", lambda: "team-repair")
    monkeypatch.setattr(local_test, "invalidate_verification_for_group", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(RuntimeError, match="injected repair commit failure"):
        local_test._persist_repaired_photo_storage("group-repair", {"id": "photo-repair"})


def test_photo_storage_repair_cleans_unreferenced_new_object_when_persistence_fails(monkeypatch) -> None:
    stored = {
        "url": "oss://bucket/repaired/photo.jpg",
        "storage_type": "oss",
        "storage_bucket": "bucket",
        "storage_key": "repaired/photo.jpg",
        "sha256": "b" * 64,
        "storage_source": "repaired-photos-oss-upload",
        "content_type": "image/jpeg",
        "created_new": True,
    }
    deleted: list[dict] = []
    monkeypatch.setattr(local_test, "_read_remote_image", lambda *_args, **_kwargs: (b"repaired", "image/jpeg"))
    monkeypatch.setattr(local_test, "save_image_bytes", lambda **_kwargs: stored)
    monkeypatch.setattr(
        local_test,
        "_persist_repaired_photo_storage",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("persistence failed")),
    )
    monkeypatch.setattr(local_test, "_saved_photo_storage_is_referenced", lambda _stored: False, raising=False)
    monkeypatch.setattr(local_test, "delete_saved_image", lambda value: deleted.append(value) or True)

    with pytest.raises(local_test.HTTPException) as exc_info:
        local_test._replace_photo_storage_from_source(
            "group-repair",
            {"id": "photo-repair", "raw_data": {}},
            "https://source.example/photo.jpg",
        )

    assert exc_info.value.status_code == 503
    assert deleted == [stored]


def test_failed_saved_image_cleanup_is_durably_queued(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = {
        "url": "oss://bucket/orphan/photo.jpg",
        "storage_type": "oss",
        "storage_bucket": "bucket",
        "storage_key": "orphan/photo.jpg",
        "created_new": True,
    }
    queued: list[tuple[dict, str, str]] = []
    monkeypatch.setattr(
        local_test,
        "delete_saved_image",
        lambda _stored: (_ for _ in ()).throw(RuntimeError("temporary OSS failure")),
    )
    monkeypatch.setattr(
        local_test,
        "enqueue_storage_cleanup_retry",
        lambda item, *, reason, error: queued.append((item, reason, error)),
        raising=False,
    )

    local_test.cleanup_saved_images_quietly([stored])

    assert queued == [(stored, "request_rollback", "temporary OSS failure")]


def test_storage_cleanup_retry_queue_survives_failure_and_completes_on_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert hasattr(photo_storage, "enqueue_storage_cleanup_retry")
    assert hasattr(photo_storage, "process_storage_cleanup_jobs")
    monkeypatch.setattr(photo_storage.settings, "storage_cleanup_queue_path", str(tmp_path), raising=False)
    stored = {
        "url": "oss://bucket/orphan/photo.jpg",
        "storage_type": "oss",
        "storage_bucket": "bucket",
        "storage_key": "orphan/photo.jpg",
        "created_new": True,
    }
    photo_storage.enqueue_storage_cleanup_retry(
        stored,
        reason="repair_persistence_failed",
        error="temporary OSS failure",
    )
    queued_files = list(tmp_path.glob("*.json"))
    assert len(queued_files) == 1

    monkeypatch.setattr(
        photo_storage,
        "delete_saved_image",
        lambda _stored: (_ for _ in ()).throw(RuntimeError("still unavailable")),
    )
    first = photo_storage.process_storage_cleanup_jobs(limit=20)
    assert first["failed"] == 1
    persisted = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert persisted["attempt_count"] == 1
    assert persisted["status"] == "pending"

    monkeypatch.setattr(photo_storage, "delete_saved_image", lambda _stored: True)
    second = photo_storage.process_storage_cleanup_jobs(limit=20)
    assert second["completed"] == 1
    assert list(tmp_path.glob("*.json")) == []


def test_storage_cleanup_manual_jobs_do_not_starve_pending_jobs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(photo_storage.settings, "storage_cleanup_queue_path", str(tmp_path), raising=False)
    for index in range(20):
        job_id = f"manual-{index:02d}"
        (tmp_path / f"{job_id}.json").write_text(
            json.dumps({"id": job_id, "status": "manual_required", "stored": {}}),
            encoding="utf-8",
        )
    pending_id = "zz-pending"
    (tmp_path / f"{pending_id}.json").write_text(
        json.dumps(
            {
                "id": pending_id,
                "status": "pending",
                "attempt_count": 0,
                "stored": {
                    "url": "oss://bucket/orphan/photo.jpg",
                    "storage_type": "oss",
                    "storage_bucket": "bucket",
                    "storage_key": "orphan/photo.jpg",
                    "created_new": True,
                },
            }
        ),
        encoding="utf-8",
    )
    deleted: list[str] = []
    monkeypatch.setattr(
        photo_storage,
        "delete_saved_image",
        lambda stored: deleted.append(str(stored["storage_key"])) or True,
    )

    result = photo_storage.process_storage_cleanup_jobs(limit=20)

    assert result == {"processed": 1, "completed": 1, "failed": 0, "manual_required": 0}
    assert deleted == ["orphan/photo.jpg"]
    assert not (tmp_path / f"{pending_id}.json").exists()
    assert len(list(tmp_path.glob("manual-*.json"))) == 20


def test_postgres_scan_import_uses_one_set_based_delivery_invalidation() -> None:
    source = inspect.getsource(local_test._postgres_import_scan_records)

    assert "invalidate_postgres_delivery_cache_for_group_changes(" in source
    assert "invalidate_postgres_delivery_cache_for_group_change(" not in source


def test_photo_url_import_rejects_placeholder_before_repository_write(monkeypatch) -> None:
    class PlaceholderRepository:
        def get_group(self, group_id: str):
            return {
                "id": group_id,
                "terminal": "00000000",
                "meter_no": "00000000",
                "meter_match_key": "00000000",
                "address": "",
            }

        def add_photo_urls_to_group(self, *_args, **_kwargs):
            raise AssertionError("placeholder route must reject before repository write")

    monkeypatch.setattr(local_test, "state_repository", lambda: PlaceholderRepository())
    login = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    headers = {"Authorization": f"bearer {login.json()['data']['access_token']}"}

    response = client.post(
        "/local-test/groups/00000000/photos/import-urls",
        headers=headers,
        json={"actor": "admin", "photo_urls": ["https://example.test/photo.jpg"]},
    )

    assert response.status_code == 400
    assert "00000000" in response.json()["detail"]


def postgres_review_record() -> SimpleNamespace:
    return SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        legacy_id="unmatched-1",
        team_id="north-team-01",
        record_type="scan",
        status="open",
        terminal="",
        meter_no="120000912473",
        meter_match_key="0000912473",
        barcode="120000912473",
        collector="C001",
        module_asset_no="M001",
        address="review road",
        payload={"photo_urls": ["https://photos.example/review.jpg"]},
    )


def test_postgres_unmatched_mutation_rejects_stale_version_without_write_or_audit(monkeypatch) -> None:
    record = postgres_review_record()
    tracker = {"active_sessions": 0, "commits": 0, "rollbacks": 0, "staged": [], "sessions": []}

    class TestPostgresRepository(state_repository.PostgresStateRepository):
        def _session(self):
            session = ApiReviewSession(record, tracker)
            tracker["sessions"].append(session)
            return session

    monkeypatch.setattr(state_repository.local_simulation, "current_team_id", lambda: "north-team-01")
    before = deepcopy(vars(record))

    with pytest.raises(unmatched_review.ReviewVersionConflict):
        TestPostgresRepository().update_unmatched_record(
            "unmatched-1",
            actor="root-admin",
            expected_version=0,
            updates={"note": "stale"},
        )

    assert vars(record) == before
    assert tracker["commits"] == 0
    assert tracker["staged"] == []


def test_production_unmatched_review_role_matrix(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    repository = FakeUnmatchedReviewRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)
    local_test.settings.photo_proxy_hosts = {"cdn.allowed.test"}
    monkeypatch.setattr(photo_storage, "settings", local_test.settings)
    monkeypatch.setattr(local_test, "_resolve_photo_proxy_host_addresses", lambda _hostname: ["8.8.8.8"])
    monkeypatch.setattr(local_test, "_read_remote_image", lambda *args, **kwargs: (b"image", "image/jpeg"))

    review_path = "/local-test/unmatched/unmatched-1/review"
    candidates_path = "/local-test/unmatched/unmatched-1/candidates"
    content_path = "/local-test/unmatched/unmatched-1/photos/photo-1/content"
    rescan_path = "/local-test/unmatched/unmatched-1/photos/photo-1/rescan"
    confirm_path = "/local-test/unmatched/unmatched-1/confirm"
    finalize_path = "/local-test/unmatched/unmatched-1/finalize-match"
    save_body = {"expected_version": 2, "metadata": {}, "photo_updates": [], "state": "pending"}
    confirm_body = {"expected_version": 2, "confirmed": True}
    finalize_body = {"candidate_key": "catalog:row-1", "expected_version": 2}

    requests = [
        ("get", review_path, None),
        ("patch", review_path, save_body),
        ("get", candidates_path, None),
        ("get", content_path, None),
        ("post", rescan_path, {"expected_version": 2, "category": "collector_barcode"}),
        ("post", confirm_path, confirm_body),
    ]
    for method, path, body in requests:
        assert production_client.request(method.upper(), path, json=body).status_code == 401
        assert production_client.request(method.upper(), path, headers=headers["reviewer"], json=body).status_code == 403
        assert production_client.request(method.upper(), path, headers=headers["constructor"], json=body).status_code == 403

    assert production_client.post(finalize_path, json=finalize_body).status_code == 401
    assert production_client.post(finalize_path, headers=headers["reviewer"], json=finalize_body).status_code == 403
    assert production_client.post(finalize_path, headers=headers["constructor"], json=finalize_body).status_code == 403
    assert repository.calls == []

    for method, path, body in requests:
        assert production_client.request(method.upper(), path, headers=headers["admin"], json=body).status_code == 200
    assert production_client.post(finalize_path, headers=headers["admin"], json=finalize_body).status_code == 200
    candidate_calls = [call for call in repository.calls if call["method"] == "candidates"]
    assert {call["actor"] for call in candidate_calls} == {"root-admin"}


def test_unmatched_candidate_compatibility_route_uses_same_audited_handler(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    main_module.settings.state_backend = "json"
    repository = FakeUnmatchedReviewRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)
    begin_calls: list[str] = []
    original_begin = local_simulation.begin_authoritative_json_write

    def tracked_begin(team_id: str):
        begin_calls.append(local_simulation.normalize_team_id(team_id))
        return original_begin(team_id)

    monkeypatch.setattr(main_module, "begin_authoritative_json_write", tracked_begin)

    canonical = production_client.get(
        "/local-test/unmatched/unmatched-1/candidates",
        headers=headers["admin"],
    )
    compatibility = production_client.get(
        "/local-test/unmatched/unmatched-1/match-candidates",
        headers=headers["admin"],
    )

    assert canonical.status_code == 200
    assert compatibility.status_code == 200
    assert compatibility.json()["data"] == canonical.json()["data"]
    assert [call["actor"] for call in repository.calls if call["method"] == "candidates"] == [
        "root-admin",
        "root-admin",
    ]
    assert begin_calls == ["north-team-01", "north-team-01"]
    assert "north-team-01" not in local_simulation._authoritative_write_locks


def test_unmatched_candidate_response_projects_safe_fields(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class UnsafeCandidateRepository(FakeUnmatchedReviewRepository):
        def list_unmatched_match_candidates(self, unmatched_id: str, *, actor: str) -> dict:
            return {
                "total": 1,
                "items": [
                    {
                        "candidate_key": f"candidate:{'a' * 64}",
                        "catalog_row_id": "row-1",
                        "catalog_row_db_id": "internal-postgres-uuid",
                        "target_group_id": "group-1",
                        "has_existing_group": True,
                        "terminal": "TERM-1",
                        "meter_no": "120000000001",
                        "meter_match_key": "0000000001",
                        "address": "测试地址",
                        "match_reasons": ["表号精确匹配"],
                        "raw": {"secret": "must-not-leak"},
                    }
                ],
            }

    monkeypatch.setattr(local_test, "state_repository", lambda: UnsafeCandidateRepository())

    response = production_client.get(
        "/local-test/unmatched/unmatched-1/candidates",
        headers=headers["admin"],
    )
    payload = response.json()["data"]
    serialized = json.dumps(payload)

    assert response.status_code == 200
    assert payload == {
        "total": 1,
        "items": [
            {
                "candidate_key": f"candidate:{'a' * 64}",
                "has_existing_group": True,
                "terminal": "TERM-1",
                "meter_no": "120000000001",
                "address": "测试地址",
                "match_reasons": ["表号精确匹配"],
            }
        ],
    }
    for private_field in (
        "catalog_row_id",
        "catalog_row_db_id",
        "target_group_id",
        "meter_match_key",
        "raw",
        "must-not-leak",
    ):
        assert private_field not in serialized


def test_unmatched_candidate_response_drops_legacy_internal_candidate_keys(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class LegacyCandidateRepository(FakeUnmatchedReviewRepository):
        def list_unmatched_match_candidates(self, unmatched_id: str, *, actor: str) -> dict:
            return {
                "total": 1,
                "items": [
                    {
                        "candidate_key": "catalog:internal-row-uuid:T-1",
                        "terminal": "T-1",
                        "meter_no": "120000000001",
                    }
                ],
            }

    monkeypatch.setattr(local_test, "state_repository", lambda: LegacyCandidateRepository())

    response = production_client.get(
        "/local-test/unmatched/unmatched-1/candidates",
        headers=headers["admin"],
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"total": 0, "items": []}
    assert "internal-row-uuid" not in response.text


def test_dual_unmatched_candidate_unavailable_maps_to_503(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class DualUnavailableCandidateRepository(FakeUnmatchedReviewRepository):
        def list_unmatched_match_candidates(self, unmatched_id: str, *, actor: str) -> dict:
            raise state_repository.StateBackendNotReady("Dual unmatched-review writes require coordination")

    monkeypatch.setattr(local_test, "state_repository", lambda: DualUnavailableCandidateRepository())

    response = production_client.get(
        "/local-test/unmatched/unmatched-1/candidates",
        headers=headers["admin"],
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Dual unmatched-review writes require coordination"


def test_unmatched_candidate_requires_manual_confirmation_maps_to_400(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class UnconfirmedCandidateRepository(FakeUnmatchedReviewRepository):
        def list_unmatched_match_candidates(self, unmatched_id: str, *, actor: str) -> dict:
            raise ValueError("Manual confirmation required before final matching")

    monkeypatch.setattr(local_test, "state_repository", lambda: UnconfirmedCandidateRepository())

    response = production_client.get(
        "/local-test/unmatched/unmatched-1/candidates",
        headers=headers["admin"],
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Manual confirmation required before final matching"


def test_unmatched_finalization_response_uses_stable_ids_and_content_routes(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class UnsafeFinalizationRepository(FakeUnmatchedReviewRepository):
        def finalize_unmatched_match(self, unmatched_id: str, *, actor: str, candidate_key: str, expected_version: int):
            self.calls.append(
                {
                    "method": "finalize",
                    "actor": actor,
                    "candidate_key": candidate_key,
                    "expected_version": expected_version,
                }
            )
            return {
                "group": {
                    "id": "group-1",
                    "task_id": 7,
                    "terminal": "TERM-1",
                    "meter_no": "120000000001",
                    "meter_match_key": "0000000001",
                    "address": "safe road",
                    "status": "incomplete",
                    "photo_count": 1,
                    "photos": [
                        {
                            "id": "p-unmatched-unmatched-1-stable",
                            "category": "before_box",
                            "image_url": "https://photos.example/raw.jpg?token=secret",
                            "source_url": "https://photos.example/source.jpg?token=secret",
                            "signed_url": "https://photos.example/signed.jpg?token=secret",
                            "storage_bucket": "private-bucket",
                            "storage_key": "private/photo.jpg",
                            "object_key": "private/photo.jpg",
                        }
                    ],
                    "raw_data": {"source_url": "https://photos.example/deep.jpg?token=secret"},
                },
                "task": {"id": 7, "raw": {"signed_url": "https://photos.example/task.jpg"}},
                "attached": False,
                "added_photos": 1,
            }

    monkeypatch.setattr(local_test, "state_repository", lambda: UnsafeFinalizationRepository())

    response = production_client.post(
        "/local-test/unmatched/unmatched-1/finalize-match",
        headers=headers["admin"],
        json={"candidate_key": "catalog:row-1", "expected_version": 2},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert set(payload) == {"group", "attached"}
    assert payload["attached"] is False
    assert payload["group"] == {
        "id": "group-1",
        "task_id": 7,
        "terminal": "TERM-1",
        "meter_no": "120000000001",
        "meter_match_key": "0000000001",
        "address": "safe road",
        "status": "incomplete",
        "photo_count": 1,
        "photos": [
            {
                "id": "p-unmatched-unmatched-1-stable",
                "category": "before_box",
                "content_url": "/local-test/groups/group-1/photos/p-unmatched-unmatched-1-stable/content",
            }
        ],
    }
    assert "token=secret" not in json.dumps(payload)


def test_production_audit_log_is_admin_only_and_recursively_redacted(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class UnsafeAuditRepository:
        def __init__(self) -> None:
            self.calls = 0

        def list_audit_events(self, *, limit: int, offset: int) -> dict:
            self.calls += 1
            return {
                "total": 1,
                "items": [
                    {
                        "id": "audit-1",
                        "action": "nested-photo-audit",
                        "actor": "admin-a",
                        "entity_id": "internal-audit-entity-uuid",
                        "payload": {
                            "candidate_key": "catalog:internal-row-uuid",
                            "catalog_row_db_id": "internal-row-uuid",
                            "target_group_id": "internal-group-uuid",
                            "raw": {"secret": "raw-private-value"},
                            "innocent_label": "https://photos.example/hidden.jpg?token=secret",
                            "nested": {
                                "photos": [
                                    {
                                        "source_url": "https://photos.example/raw.jpg?token=secret",
                                        "signed_url": "https://photos.example/signed.jpg?token=secret",
                                        "storage": {
                                            "storage_bucket": "private-bucket",
                                            "storage_key": "private/photo.jpg",
                                            "object_key": "private/photo.jpg",
                                            "storageBucket": "private-camel-bucket",
                                            "storageKey": "private/camel-photo.jpg",
                                            "objectKey": "private/camel-object.jpg",
                                            "ossKey": "private/camel-oss.jpg",
                                        },
                                        "signedUrl": "https://photos.example/camel-signed.jpg?token=secret",
                                        "rawUrl": "https://photos.example/camel-raw.jpg?token=secret",
                                        "presignedUrl": "https://photos.example/presigned.jpg?token=secret",
                                        "rawSignedUrl": "https://photos.example/raw-signed.jpg?token=secret",
                                        "bucketName": "private-provider-bucket",
                                        "storageObjectKey": "private/storage-object.jpg",
                                        "ossObjectKey": "private/oss-object.jpg",
                                        "presignedUri": "oss://private/presigned",
                                        "rawSignedURI": "oss://private/raw-signed",
                                        "signed-link": "https://photos.example/signed-link",
                                        "s3Key": "private/s3-object.jpg",
                                        "cos_object_name": "private/cos-object.jpg",
                                        "ossPath": "private/oss-path.jpg",
                                        "objectPath": "private/object-path.jpg",
                                    }
                                ]
                            },
                        },
                    }
                ],
            }

    repository = UnsafeAuditRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)

    assert production_client.get("/local-test/audit-log").status_code == 401
    assert production_client.get("/local-test/audit-log", headers=headers["constructor"]).status_code == 403
    assert production_client.get("/local-test/audit-log", headers=headers["reviewer"]).status_code == 403
    assert repository.calls == 0

    response = production_client.get("/local-test/audit-log", headers=headers["admin"])

    assert response.status_code == 200
    assert repository.calls == 1
    payload = response.json()["data"]
    photo = payload["items"][0]["payload"]["nested"]["photos"][0]
    assert set(payload["items"][0]) == {"id", "action", "actor", "payload"}
    assert payload["items"][0]["payload"]["candidate_key"] == "[REDACTED]"
    assert payload["items"][0]["payload"]["catalog_row_db_id"] == "[REDACTED]"
    assert payload["items"][0]["payload"]["target_group_id"] == "[REDACTED]"
    assert payload["items"][0]["payload"]["raw"] == "[REDACTED]"
    assert payload["items"][0]["payload"]["innocent_label"] == "[REDACTED]"
    assert photo["source_url"] == "[REDACTED]"
    assert photo["signed_url"] == "[REDACTED]"
    assert photo["signedUrl"] == "[REDACTED]"
    assert photo["rawUrl"] == "[REDACTED]"
    for key in (
        "presignedUrl",
        "rawSignedUrl",
        "bucketName",
        "storageObjectKey",
        "ossObjectKey",
        "presignedUri",
        "rawSignedURI",
        "signed-link",
        "s3Key",
        "cos_object_name",
        "ossPath",
        "objectPath",
    ):
        assert photo[key] == "[REDACTED]"
    serialized = json.dumps(payload)
    for secret in (
        "internal-audit-entity-uuid",
        "internal-row-uuid",
        "internal-group-uuid",
        "raw-private-value",
        "token=secret",
    ):
        assert secret not in serialized
    assert photo["storage"] == {
        "storage_bucket": "[REDACTED]",
        "storage_key": "[REDACTED]",
        "object_key": "[REDACTED]",
        "storageBucket": "[REDACTED]",
        "storageKey": "[REDACTED]",
        "objectKey": "[REDACTED]",
        "ossKey": "[REDACTED]",
    }
    assert "token=secret" not in json.dumps(payload)


def test_production_unmatched_review_rejects_wrong_roles_before_malformed_body_validation(
    monkeypatch,
    tmp_path,
) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    repository = FakeUnmatchedReviewRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)
    malformed_headers = {"Content-Type": "application/json"}

    constructor_response = production_client.patch(
        "/local-test/unmatched/unmatched-1/review",
        headers={**headers["constructor"], **malformed_headers},
        content=b"{",
    )
    reviewer_finalize_response = production_client.post(
        "/local-test/unmatched/unmatched-1/finalize-match",
        headers={**headers["reviewer"], **malformed_headers},
        content=b"{",
    )

    assert constructor_response.status_code == 403
    assert reviewer_finalize_response.status_code == 403
    assert repository.calls == []


def test_unmatched_rescan_accepts_json_category_and_rejects_invalid(monkeypatch) -> None:
    repository = FakeUnmatchedReviewRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)

    accepted = client.post(
        "/local-test/unmatched/unmatched-1/photos/photo-1/rescan",
        json={"expected_version": 2, "category": "collector_barcode"},
    )

    assert accepted.status_code == 200
    rescan_calls = [call for call in repository.calls if call["method"] == "rescan"]
    assert rescan_calls == [
        {
            "method": "rescan",
            "actor": "local-reviewer",
            "photo_id": "photo-1",
            "expected_version": 2,
            "category": "collector_barcode",
        }
    ]

    invalid = client.post(
        "/local-test/unmatched/unmatched-1/photos/photo-1/rescan",
        json={"expected_version": 2, "category": "not-a-category"},
    )

    assert invalid.status_code == 400
    assert [call for call in repository.calls if call["method"] == "rescan"] == rescan_calls


def test_unmatched_rescan_version_conflict_returns_409_without_persisting(monkeypatch) -> None:
    class ConflictRepository(FakeUnmatchedReviewRepository):
        def rescan_unmatched_review_photo(
            self,
            unmatched_id: str,
            photo_id: str,
            *,
            actor: str,
            expected_version: int,
            category: str = "",
        ) -> dict:
            self.calls.append(
                {
                    "method": "rescan",
                    "actor": actor,
                    "photo_id": photo_id,
                    "expected_version": expected_version,
                    "category": category,
                }
            )
            raise unmatched_review.ReviewVersionConflict("stale rescan snapshot")

    repository = ConflictRepository()
    review_before = deepcopy(repository.review)
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)

    response = client.post(
        "/local-test/unmatched/unmatched-1/photos/photo-1/rescan",
        json={"expected_version": 1, "category": "collector_barcode"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "stale rescan snapshot"
    assert repository.review == review_before
    assert repository.calls == [
        {
            "method": "rescan",
            "actor": "local-reviewer",
            "photo_id": "photo-1",
            "expected_version": 1,
            "category": "collector_barcode",
        }
    ]


def test_production_unmatched_review_routes_use_postgres_repository_transactions(
    monkeypatch,
    tmp_path,
) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    record = postgres_review_record()
    tracker = {"active_sessions": 0, "commits": 0, "rollbacks": 0, "staged": [], "sessions": []}
    scan_categories = []

    class TestPostgresRepository(state_repository.PostgresStateRepository):
        def _session(self):
            session = ApiReviewSession(record, tracker)
            tracker["sessions"].append(session)
            return session

    def fake_scan(photo, context, *, use_ocr=False):
        assert tracker["active_sessions"] == 0
        scan_categories.append(photo["category"])
        return {
            "barcode_check_status": "matched",
            "barcode_check_method": "barcode_qr_ocr",
            "barcode_check_matched_value": context["meter_no"],
        }

    postgres_repository = TestPostgresRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: postgres_repository)
    monkeypatch.setattr(state_repository.local_simulation, "current_team_id", lambda: "north-team-01")
    monkeypatch.setattr(state_repository.photo_barcode_check, "check_photo_barcode", fake_scan)

    detail = production_client.get(
        "/local-test/unmatched/unmatched-1/review",
        headers=headers["admin"],
    )
    assert detail.status_code == 200
    photo_id = detail.json()["data"]["review"]["photos"][0]["id"]

    saved = production_client.patch(
        "/local-test/unmatched/unmatched-1/review",
        headers=headers["admin"],
        json={
            "expected_version": 1,
            "metadata": {"collector": "C002"},
            "photo_updates": [],
            "state": "reviewed",
        },
    )
    assert saved.status_code == 200
    assert saved.json()["data"]["review"]["version"] == 2

    before_invalid_state = deepcopy(record.payload)
    session_count = len(tracker["sessions"])
    invalid_state = production_client.patch(
        "/local-test/unmatched/unmatched-1/review",
        headers=headers["admin"],
        json={"expected_version": 2, "state": "invalid"},
    )
    assert invalid_state.status_code == 400
    assert record.payload == before_invalid_state
    assert len(tracker["sessions"]) == session_count

    invalid_category = production_client.post(
        f"/local-test/unmatched/unmatched-1/photos/{photo_id}/rescan",
        headers=headers["admin"],
        json={"expected_version": 2, "category": "not-a-category"},
    )
    assert invalid_category.status_code == 400
    assert len(tracker["sessions"]) == session_count

    rescanned = production_client.post(
        f"/local-test/unmatched/unmatched-1/photos/{photo_id}/rescan",
        headers=headers["admin"],
        json={"expected_version": 2, "category": "collector_barcode"},
    )
    assert rescanned.status_code == 200
    assert rescanned.json()["data"]["review"]["version"] == 3
    assert rescanned.json()["data"]["review"]["photos"][0]["category"] == "collector_barcode"
    assert scan_categories == ["collector_barcode"]

    confirmed = production_client.post(
        "/local-test/unmatched/unmatched-1/confirm",
        headers=headers["admin"],
        json={"expected_version": 3, "confirmed": True},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["review"]["version"] == 4
    assert confirmed.json()["data"]["review"]["manual_confirmed"] is True

    audits = [item for item in tracker["staged"] if isinstance(item, state_repository.AuditLog)]
    assert tracker["commits"] == 3
    assert tracker["rollbacks"] == 0
    assert [audit.action for audit in audits] == [
        "unmatched_review_saved",
        "unmatched_review_barcode_rescan",
        "unmatched_review_confirmed",
    ]


def test_production_unmatched_review_binds_actor_to_signed_in_reviewer(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    repository = FakeUnmatchedReviewRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)

    response = production_client.patch(
        "/local-test/unmatched/unmatched-1/review",
        headers=headers["reviewer"],
        json={
            "actor": "root-admin",
            "expected_version": 2,
            "metadata": {"meter_no": "METER-001"},
            "photo_updates": [],
            "state": "pending",
        },
    )

    assert response.status_code == 403
    assert repository.calls == []


def test_production_unmatched_review_maps_repository_errors(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    repository = FakeUnmatchedReviewRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)

    assert production_client.get("/local-test/unmatched/missing/review", headers=headers["admin"]).status_code == 404
    assert production_client.patch(
        "/local-test/unmatched/unmatched-1/review",
        headers=headers["admin"],
        json={"expected_version": 1},
    ).status_code == 409
    assert production_client.patch(
        "/local-test/unmatched/unmatched-1/review",
        headers=headers["admin"],
        json={"expected_version": 2, "state": "invalid"},
    ).status_code == 400
    assert production_client.post(
        "/local-test/unmatched/unmatched-1/photos/missing/rescan",
        headers=headers["admin"],
        json={"expected_version": 2, "category": "collector_barcode"},
    ).status_code == 404
    assert production_client.post(
        "/local-test/unmatched/unmatched-1/confirm",
        headers=headers["admin"],
        json={"expected_version": 1},
    ).status_code == 409
    assert production_client.post(
        "/local-test/unmatched/unmatched-1/finalize-match",
        headers=headers["admin"],
        json={"candidate_key": "invalid", "expected_version": 2},
    ).status_code == 400
    assert production_client.post(
        "/local-test/unmatched/unmatched-1/finalize-match",
        headers=headers["admin"],
        json={"candidate_key": "catalog:row-1", "expected_version": 1},
    ).status_code == 409


def test_production_finalization_identity_conflict_returns_409(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class ConflictRepository(FakeUnmatchedReviewRepository):
        def finalize_unmatched_match(self, *args, **kwargs):
            conflict_type = getattr(unmatched_review, "FinalizationIdentityConflict", ValueError)
            raise conflict_type("Candidate conflicts with existing formal group identity")

    monkeypatch.setattr(local_test, "state_repository", lambda: ConflictRepository())

    response = production_client.post(
        "/local-test/unmatched/unmatched-1/finalize-match",
        headers=headers["admin"],
        json={"candidate_key": "catalog:row-1", "expected_version": 2},
    )

    assert response.status_code == 409
    assert "conflicts with existing formal group identity" in response.json()["detail"]


def test_production_unmatched_photo_content_uses_server_source_and_rejects_ssrf(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    repository = FakeUnmatchedReviewRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)
    local_test.settings.photo_proxy_hosts = {"cdn.allowed.test"}
    monkeypatch.setattr(photo_storage, "settings", local_test.settings)
    monkeypatch.setattr(local_test, "_resolve_photo_proxy_host_addresses", lambda _hostname: ["8.8.8.8"])
    fetched_urls = []

    def fake_read_remote_image(url: str, **kwargs):
        kwargs["url_validator"](url)
        fetched_urls.append(url)
        return b"image", "image/jpeg"

    monkeypatch.setattr(local_test, "_read_remote_image", fake_read_remote_image)
    content = production_client.get(
        "/local-test/unmatched/unmatched-1/photos/photo-1/content?url=http://127.0.0.1/private.jpg",
        headers=headers["admin"],
    )
    assert content.status_code == 200
    assert fetched_urls == ["https://cdn.allowed.test/server-photo.jpg"]

    repository.review["photos"][0]["source_url"] = "http://127.0.0.1/private.jpg"
    denied = production_client.get(
        "/local-test/unmatched/unmatched-1/photos/photo-1/content",
        headers=headers["admin"],
    )
    assert denied.status_code == 400
    assert fetched_urls == ["https://cdn.allowed.test/server-photo.jpg"]


def test_production_unmatched_review_confirm_is_not_a_formal_scan_pass(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    repository = FakeUnmatchedReviewRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)

    response = production_client.post(
        "/local-test/unmatched/unmatched-1/confirm",
        headers=headers["admin"],
        json={"expected_version": 2, "confirmed": True},
    )

    assert response.status_code == 200
    review = response.json()["data"]["review"]
    assert review["manual_confirmed"] is True
    assert "formal_scan_pass" not in review


def test_production_scan_clear_requires_admin_role(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class FakeRepository:
        clear_calls = 0

        def clear_scan_data(self):
            self.clear_calls += 1
            return {"summary": {"scan_rows": 0}}

    repository = FakeRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)

    assert production_client.post("/local-test/scan/clear").status_code == 401
    assert production_client.post("/local-test/scan/clear", headers=headers["reviewer"]).status_code == 403
    assert production_client.post("/local-test/scan/clear", headers=headers["constructor"]).status_code == 403
    assert repository.clear_calls == 0

    allowed = production_client.post("/local-test/scan/clear", headers=headers["admin"])
    assert allowed.status_code == 200
    assert repository.clear_calls == 1


def test_production_review_mutation_requires_reviewer_or_admin(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class FakeRepository:
        claim_calls = 0

        def claim_task(self, task_id, reviewer):
            self.claim_calls += 1
            return {"id": task_id, "reviewer": reviewer}

    repository = FakeRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)

    anonymous = production_client.post(
        "/local-test/tasks/999999/claim",
        json={"reviewer": "anonymous-reviewer"},
    )
    assert anonymous.status_code == 401
    assert repository.claim_calls == 0

    denied = production_client.post(
        "/local-test/tasks/999999/claim",
        headers=headers["constructor"],
        json={"reviewer": "constructor-a"},
    )
    assert denied.status_code == 403
    assert repository.claim_calls == 0

    allowed = production_client.post(
        "/local-test/tasks/999999/claim",
        headers=headers["reviewer"],
        json={"reviewer": "reviewer-a"},
    )
    assert allowed.status_code == 403
    assert repository.claim_calls == 0

    admin_allowed = production_client.post(
        "/local-test/tasks/999999/claim",
        headers=headers["admin"],
        json={"reviewer": "admin-selected-reviewer"},
    )
    assert admin_allowed.status_code == 200
    assert repository.claim_calls == 1


def test_production_construction_mutation_requires_constructor_or_admin(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class FakeRepository:
        claim_calls = 0

        def claim_construction_task(self, task_id, actor):
            self.claim_calls += 1
            return {"id": task_id, "constructor": actor}

    repository = FakeRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)

    anonymous = production_client.post(
        "/local-test/construction/tasks/999999/claim",
        json={"actor": "anonymous-constructor"},
    )
    assert anonymous.status_code == 401
    assert repository.claim_calls == 0

    denied = production_client.post(
        "/local-test/construction/tasks/999999/claim",
        headers=headers["reviewer"],
        json={"actor": "reviewer-a"},
    )
    assert denied.status_code == 403
    assert repository.claim_calls == 0

    allowed = production_client.post(
        "/local-test/construction/tasks/999999/claim",
        headers=headers["constructor"],
        json={"actor": "constructor-a"},
    )
    assert allowed.status_code == 200
    assert repository.claim_calls == 1

    admin_allowed = production_client.post(
        "/local-test/construction/tasks/999999/claim",
        headers=headers["admin"],
        json={"actor": "admin-selected-constructor"},
    )
    assert admin_allowed.status_code == 200
    assert repository.claim_calls == 2


def test_production_group_metadata_requires_reviewer_or_admin(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class FakeRepository:
        update_calls = 0
        actors = []

        def update_group_metadata(self, group_id, actor, updates):
            self.update_calls += 1
            self.actors.append(actor)
            return {"id": group_id, "actor": actor, **updates}

    repository = FakeRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)

    denied = production_client.patch(
        "/local-test/groups/group-1/metadata",
        headers=headers["constructor"],
        json={"actor": "constructor-a", "updates": {"meter_no": "METER-001"}},
    )
    spoofed = production_client.patch(
        "/local-test/groups/group-1/metadata",
        headers=headers["reviewer"],
        json={"actor": "admin", "updates": {"meter_no": "METER-001"}},
    )
    match_key_denied = production_client.patch(
        "/local-test/groups/group-1/metadata",
        headers=headers["reviewer"],
        json={"updates": {"meter_match_key": "MATCH-001"}},
    )

    assert denied.status_code == 403
    assert spoofed.status_code == 403

    assert match_key_denied.status_code == 403
    assert repository.update_calls == 0

    allowed = production_client.patch(
        "/local-test/groups/group-1/metadata",
        headers=headers["admin"],
        json={"actor": "admin-selected-reviewer", "updates": {"meter_no": "METER-001"}},
    )
    assert allowed.status_code == 200
    assert repository.update_calls == 1
    assert repository.actors == ["root-admin"]


@pytest.mark.parametrize(
    ("path", "updates"),
    [
        ("/local-test/groups/group-1/terminal", {"terminal": "00000000"}),
        ("/local-test/groups/group-1/terminal", {"terminal": "manual-terminal"}),
        ("/local-test/groups/group-1/metadata", {"updates": {"meter_no": "未关联终端"}}),
        ("/local-test/groups/group-1/metadata", {"updates": {"meter_match_key": "unmatched-key"}}),
    ],
)
def test_production_formal_identity_updates_reject_placeholders_before_repository_write(
    monkeypatch,
    tmp_path,
    path: str,
    updates: dict,
) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class FakeRepository:
        calls = []

        def update_group_terminal(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return {"group": {"id": "group-1"}}

        def update_group_metadata(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return {"group": {"id": "group-1"}}

    repository = FakeRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)

    response = production_client.patch(path, headers=headers["admin"], json=updates)

    assert response.status_code == 400
    assert repository.calls == []


def test_production_group_photo_url_import_requires_reviewer_or_admin(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class FakeRepository:
        add_calls = 0

        def add_photo_urls_to_group(self, group_id, **kwargs):
            self.add_calls += 1
            return {"id": group_id, **kwargs}

    repository = FakeRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)
    payload = {"actor": "constructor-a", "photo_urls": ["https://example.test/photo.jpg"]}

    denied = production_client.post(
        "/local-test/groups/group-1/photos/import-urls",
        headers=headers["constructor"],
        json=payload,
    )
    spoofed = production_client.post(
        "/local-test/groups/group-1/photos/import-urls",
        headers=headers["reviewer"],
        json={**payload, "actor": "admin"},
    )

    assert denied.status_code == 403
    assert spoofed.status_code == 403
    assert repository.add_calls == 0


def test_production_barcode_endpoints_bind_effective_actor_to_token_subject(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class FakeRepository:
        calls = []

        def rescan_photo_barcode(self, group_id, photo_id, reviewer, category):
            self.calls.append(("rescan", reviewer))
            return {"id": photo_id, "group_id": group_id, "category": category}

        def confirm_group_barcode_manually(self, group_id, *, actor, **_kwargs):
            self.calls.append(("confirm", actor))
            return {"group": {"id": group_id}}

    repository = FakeRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)

    rescan = production_client.post(
        "/local-test/groups/group-1/photos/photo-1/barcode-rescan",
        headers=headers["admin"],
        json={"reviewer": "delegated-reviewer", "category": "module_meter"},
    )
    confirmed = production_client.post(
        "/local-test/groups/group-1/barcode-manual-confirm",
        headers=headers["admin"],
        json={
            "actor": "forged-admin",
            "meter_no": "110000288056",
            "collector": "COLLECTOR001",
            "module_asset_no": "MOD001",
            "reason": "现场核验",
            "photo_ids": ["photo-1"],
        },
    )

    assert rescan.status_code == 200
    assert confirmed.status_code == 200
    assert repository.calls == [("rescan", "root-admin"), ("confirm", "root-admin")]


def test_production_group_image_upload_checks_role_before_storage(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    storage_calls = []

    class FakeRepository:
        add_calls = []

        def get_group(self, group_id):
            return {
                "id": group_id,
                "terminal": "TERMINAL-001",
                "meter_no": "METER-001",
                "meter_match_key": "METER-001",
                "address": "valid address",
            }

        def add_photo_urls_to_group(self, group_id, **kwargs):
            self.add_calls.append({"group_id": group_id, **kwargs})
            return {"id": group_id, **kwargs}

    repository = FakeRepository()

    def fake_save_image_bytes(**kwargs):
        storage_calls.append(kwargs)
        return {
            "url": "https://example.test/stored.jpg",
            "sha256": "abc",
            "storage_type": "local",
            "storage_key": "stored.jpg",
            "storage_bucket": "",
            "storage_source": "test",
        }

    monkeypatch.setattr(local_test, "save_image_bytes", fake_save_image_bytes)
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)

    denied = production_client.post(
        "/local-test/groups/group-1/photos/upload-images",
        headers=headers["constructor"],
        data={"actor": "admin"},
        files={"files": ("photo.jpg", tiny_jpeg_bytes(), "image/jpeg")},
    )

    assert denied.status_code == 403
    assert storage_calls == []

    allowed = production_client.post(
        "/local-test/groups/group-1/photos/upload-images",
        headers=headers["admin"],
        files={"files": ("photo.jpg", tiny_jpeg_bytes(), "image/jpeg")},
    )

    assert allowed.status_code == 200
    assert len(storage_calls) == 1
    assert repository.add_calls[0]["actor"] == "root-admin"


def test_manual_group_photo_upload_rejects_placeholder_identity_before_storage(monkeypatch) -> None:
    storage_calls = []

    class FakeRepository:
        def get_group(self, group_id):
            return {
                "id": group_id,
                "terminal": "00000000",
                "meter_no": "00000000",
                "meter_match_key": "00000000",
                "address": "待导入总清单地址",
            }

        def add_photo_urls_to_group(self, *_args, **_kwargs):
            pytest.fail("placeholder group must fail before repository write")

    monkeypatch.setattr(local_test, "state_repository", lambda: FakeRepository())
    monkeypatch.setattr(local_test, "save_image_bytes", lambda **kwargs: storage_calls.append(kwargs))

    response = client.post(
        "/local-test/groups/00000000/photos/upload-images",
        files={"files": ("photo.jpg", tiny_jpeg_bytes(), "image/jpeg")},
    )

    assert response.status_code == 400
    assert "00000000" in response.json()["detail"]
    assert storage_calls == []


def test_manual_group_photo_upload_cleans_new_storage_object_when_repository_rejects(monkeypatch) -> None:
    stored = {
        "url": "/static/uploads/manual/new.jpg",
        "sha256": "a" * 64,
        "storage_type": "local_upload",
        "storage_key": "manual/new.jpg",
        "storage_bucket": "",
        "storage_source": "manual-local-upload",
        "created_new": True,
    }
    cleaned = []

    class FakeRepository:
        def get_group(self, group_id):
            return {
                "id": group_id,
                "terminal": "TERMINAL-001",
                "meter_no": "METER-001",
                "meter_match_key": "METER-001",
                "address": "valid address",
            }

        def add_photo_urls_to_group(self, *_args, **_kwargs):
            raise KeyError("group disappeared")

    monkeypatch.setattr(local_test, "state_repository", lambda: FakeRepository())
    monkeypatch.setattr(local_test, "save_image_bytes", lambda **_kwargs: dict(stored))
    monkeypatch.setattr(
        local_test,
        "delete_saved_image",
        lambda payload: cleaned.append(dict(payload)) or True,
        raising=False,
    )

    response = client.post(
        "/local-test/groups/group-1/photos/upload-images",
        files={"files": ("photo.jpg", tiny_jpeg_bytes(), "image/jpeg")},
    )

    assert response.status_code == 404
    assert cleaned == [stored]


def test_manual_group_photo_upload_cleans_only_unreferenced_duplicate_objects(monkeypatch) -> None:
    stored = [
        {
            "url": "/static/uploads/manual/retained.jpg",
            "sha256": "a" * 64,
            "storage_type": "local_upload",
            "storage_key": "manual/retained.jpg",
            "storage_bucket": "",
            "storage_source": "manual-local-upload",
            "created_new": True,
        },
        {
            "url": "/static/uploads/manual/duplicate.jpg",
            "sha256": "b" * 64,
            "storage_type": "local_upload",
            "storage_key": "manual/duplicate.jpg",
            "storage_bucket": "",
            "storage_source": "manual-local-upload",
            "created_new": True,
        },
    ]
    cleaned = []

    class FakeRepository:
        def get_group(self, group_id):
            return {
                "id": group_id,
                "terminal": "TERMINAL-001",
                "meter_no": "METER-001",
                "meter_match_key": "METER-001",
                "address": "valid address",
            }

        def add_photo_urls_to_group(self, *_args, **_kwargs):
            return {
                "group": {"id": "group-1"},
                "added": 1,
                "skipped_duplicates": 1,
                "retained_photo_urls": [stored[0]["url"]],
            }

    stored_iter = iter(stored)
    monkeypatch.setattr(local_test, "state_repository", lambda: FakeRepository())
    monkeypatch.setattr(local_test, "save_image_bytes", lambda **_kwargs: dict(next(stored_iter)))
    monkeypatch.setattr(
        local_test,
        "delete_saved_image",
        lambda payload: cleaned.append(dict(payload)) or True,
        raising=False,
    )

    response = client.post(
        "/local-test/groups/group-1/photos/upload-images",
        files=[
            ("files", ("retained.jpg", tiny_jpeg_bytes(), "image/jpeg")),
            ("files", ("duplicate.jpg", tiny_jpeg_bytes(), "image/jpeg")),
        ],
    )

    assert response.status_code == 200
    assert cleaned == [stored[1]]
    assert "retained_photo_urls" not in response.json()["data"]


def test_manual_group_photo_upload_does_not_delete_committed_objects_when_response_build_fails(monkeypatch) -> None:
    stored = {
        "url": "/static/uploads/manual/committed.jpg",
        "sha256": "c" * 64,
        "storage_type": "local_upload",
        "storage_key": "manual/committed.jpg",
        "storage_bucket": "",
        "storage_source": "manual-local-upload",
        "created_new": True,
    }
    cleaned = []

    class FakeRepository:
        def get_group(self, group_id):
            return {
                "id": group_id,
                "terminal": "TERMINAL-001",
                "meter_no": "METER-001",
                "meter_match_key": "METER-001",
                "address": "valid address",
            }

        def add_photo_urls_to_group(self, *_args, **_kwargs):
            return {
                "group": {"id": "group-1"},
                "added": 1,
                "skipped_duplicates": 0,
                "retained_photo_urls": [stored["url"]],
            }

    monkeypatch.setattr(local_test, "state_repository", lambda: FakeRepository())
    monkeypatch.setattr(local_test, "save_image_bytes", lambda **_kwargs: dict(stored))
    monkeypatch.setattr(local_test, "response_payload", lambda _result: (_ for _ in ()).throw(RuntimeError("response failed")))
    monkeypatch.setattr(
        local_test,
        "delete_saved_image",
        lambda payload: cleaned.append(dict(payload)) or True,
        raising=False,
    )

    with pytest.raises(RuntimeError, match="response failed"):
        client.post(
            "/local-test/groups/group-1/photos/upload-images",
            files={"files": ("committed.jpg", tiny_jpeg_bytes(), "image/jpeg")},
        )

    assert cleaned == []


def test_delete_saved_local_image_removes_only_new_file_inside_upload_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    upload_root = tmp_path / "uploads"
    target = upload_root / "manual" / "new.jpg"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"new photo")
    monkeypatch.setattr(photo_storage, "static_upload_root", lambda: upload_root)

    deleted = photo_storage.delete_saved_image(
        {
            "created_new": True,
            "storage_type": "local_upload",
            "storage_key": "manual/new.jpg",
        }
    )

    assert deleted is True
    assert not target.exists()


def test_production_placeholder_review_routes_reject_constructor(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    responses = [
        production_client.post("/tasks/999999/claim", headers=headers["constructor"]),
        production_client.post("/tasks/999999/release", headers=headers["constructor"]),
        production_client.patch(
            "/groups/999999/review",
            headers=headers["constructor"],
            json={"status": "approved", "comment": "forbidden"},
        ),
        production_client.post(
            "/groups/999999/exceptions",
            headers=headers["constructor"],
            json={"kind": "quality", "description": "forbidden"},
        ),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403]


def test_production_upload_role_guard_runs_before_multipart_parse(monkeypatch, tmp_path) -> None:
    from starlette.requests import Request as StarletteRequest

    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    original_form = StarletteRequest.form
    form_calls = []

    async def tracked_form(request, *args, **kwargs):
        form_calls.append(request.url.path)
        return await original_form(request, *args, **kwargs)

    monkeypatch.setattr(StarletteRequest, "form", tracked_form)

    manual_upload = production_client.post(
        "/local-test/groups/group-1/photos/upload-images",
        headers=headers["constructor"],
        data={"actor": "constructor-a"},
        files={"files": ("photo.jpg", tiny_jpeg_bytes(), "image/jpeg")},
    )
    construction_upload = production_client.post(
        "/local-test/construction/groups/group-1/upload-batch",
        headers=headers["reviewer"],
        data={"actor": "reviewer-a"},
        files={"files": ("photo.jpg", tiny_jpeg_bytes(), "image/jpeg")},
    )

    assert manual_upload.status_code == 403
    assert construction_upload.status_code == 403
    assert form_calls == []


def test_production_local_test_persists_only_successful_writes(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    persist_calls = []
    monkeypatch.setattr(main_module, "save_all_team_states", lambda: persist_calls.append("saved"))

    class FakeRepository:
        def clear_scan_data(self):
            return {"summary": {"scan_rows": 0}}

    monkeypatch.setattr(local_test, "state_repository", lambda: FakeRepository())

    for backend in ("json", "dual"):
        main_module.settings.state_backend = backend
        persist_calls.clear()

        anonymous = production_client.post("/local-test/scan/clear")
        wrong_role = production_client.post("/local-test/scan/clear", headers=headers["constructor"])
        allowed = production_client.post("/local-test/scan/clear", headers=headers["admin"])

        assert anonymous.status_code == 401
        assert wrong_role.status_code == 403
        assert allowed.status_code == 200
        assert persist_calls == ["saved"]


DUAL_UNMATCHED_WRITE_CASES = (
    (
        "save",
        "PATCH",
        "/local-test/unmatched/{unmatched_id}/review",
        lambda context: {
            "expected_version": context["version"],
            "metadata": {"collector": "C-DUAL"},
            "photo_updates": [],
            "state": "pending",
        },
        "admin",
    ),
    (
        "rescan",
        "POST",
        "/local-test/unmatched/{unmatched_id}/photos/{photo_id}/rescan",
        lambda context: {"expected_version": context["version"], "category": "collector_barcode"},
        "admin",
    ),
    (
        "confirm",
        "POST",
        "/local-test/unmatched/{unmatched_id}/confirm",
        lambda context: {"expected_version": context["version"], "confirmed": True},
        "admin",
    ),
    (
        "finalize",
        "POST",
        "/local-test/unmatched/{unmatched_id}/finalize-match",
        lambda context: {
            "expected_version": context["version"],
            "candidate_key": context["candidate_key"],
        },
        "admin",
    ),
)


@pytest.mark.parametrize(("operation", "method", "path_template", "body_factory", "role"), DUAL_UNMATCHED_WRITE_CASES)
def test_dual_http_unmatched_writes_fail_fast_without_deadlock_or_backend_divergence(
    monkeypatch,
    tmp_path,
    operation: str,
    method: str,
    path_template: str,
    body_factory,
    role: str,
) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    main_module.settings.state_backend = "dual"
    local_test.settings.state_backend = "dual"
    state_repository.settings.state_backend = "dual"
    team_id = "north-team-01"
    local_simulation._team_states[team_id] = local_simulation.blank_state(team_id)
    local_simulation._team_states[team_id]["summary"] = local_simulation.empty_summary()
    token = local_simulation.set_current_team(team_id)
    try:
        state = local_simulation.get_state()
        record = local_simulation.ensure_unmatched_record(
            {
                "barcode": "3130001122100009124734",
                "meter_no": "120000912473",
                "collector": "C001",
                "module_asset_no": "M001",
                "photo_urls": [f"https://photos.example/dual-http-{operation}-{index}.jpg" for index in range(4)],
            }
        )
        state["scan_unmatched"].append(record)
        state["total_catalog"].append(
            {
                "id": f"catalog-dual-http-{operation}",
                "terminal": f"T-DUAL-{operation.upper()}",
                "meter_no": "120000912473",
                "meter_match_key": local_simulation.build_total_catalog_match_key("120000912473"),
                "address": "dual http road",
            }
        )
        review = unmatched_review.build_review(record)
        confirmed = local_simulation.confirm_unmatched_review(
            record["unmatched_id"],
            actor="reviewer-a",
            expected_version=review["version"],
        )
        review = confirmed["review"]
        candidate = local_simulation.list_unmatched_match_candidates(record["unmatched_id"])["items"][0]
        context = {
            "version": review["version"],
            "candidate_key": candidate["candidate_key"],
        }
        photo_id = review["photos"][0]["id"]
        before = deepcopy(state)
    finally:
        local_simulation.reset_current_team(token)

    postgres_calls = []

    class MutatingPostgresMirror:
        def __getattr__(self, name: str):
            def mutate(*args, **kwargs):
                postgres_calls.append((name, args, kwargs))
                return {"mutated": True}

            return mutate

    persistence_calls = []

    def fail_json_persistence() -> None:
        persistence_calls.append("attempted")
        raise OSError(f"injected JSON persistence failure for {operation}")

    monkeypatch.setattr(state_repository.DualWriteStateRepository, "postgres_repository_factory", MutatingPostgresMirror)
    monkeypatch.setattr(main_module, "save_all_team_states", fail_json_persistence)
    path = path_template.format(unmatched_id=record["unmatched_id"], photo_id=photo_id)
    responses = []
    errors = []

    def issue_request() -> None:
        try:
            responses.append(
                production_client.request(
                    method,
                    path,
                    headers=headers[role],
                    json=body_factory(context),
                )
            )
        except BaseException as exc:  # pragma: no cover - assertion reports transport failures
            errors.append(exc)

    request_thread = Thread(target=issue_request, daemon=True)
    request_thread.start()
    request_thread.join(timeout=5)

    assert not request_thread.is_alive(), f"{operation} dual HTTP request exceeded 5-second deadlock guard"
    assert errors == []
    assert len(responses) == 1
    assert responses[0].status_code == 503
    assert "coordinated" in responses[0].text.lower()
    assert postgres_calls == []
    assert persistence_calls == []
    assert local_simulation._team_states[team_id] == before
    assert team_id not in local_simulation._authoritative_write_locks


@pytest.mark.parametrize("terminal", ["00000000", "未关联终端", "manual-terminal", "unmatched-terminal"])
def test_json_http_legacy_assign_rejects_placeholder_terminal_without_state_or_persistence_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    terminal: str,
) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    main_module.settings.state_backend = "json"
    local_test.settings.state_backend = "json"
    state_repository.settings.state_backend = "json"
    team_id = "north-team-01"
    state_path = tmp_path / "legacy-assign-state.json"
    monkeypatch.setenv("LOCAL_SIMULATION_STATE_PATH", str(state_path))
    local_simulation._team_states[team_id] = local_simulation.blank_state(team_id)
    token = local_simulation.set_current_team(team_id)
    try:
        state = local_simulation.get_state()
        record = local_simulation.ensure_unmatched_record(
            {
                "unmatched_id": "http-legacy-assign-placeholder-terminal",
                "barcode": "120000912473",
                "meter_no": "120000912473",
                "terminal": terminal,
                "collector": "C001",
                "module_asset_no": "M001",
                "photo_urls": [],
            }
        )
        state["scan_unmatched"].append(record)
        local_simulation.refresh_summary()
        local_simulation.save_all_team_states()
        before = deepcopy(state)
        before_bytes = state_path.read_bytes()
    finally:
        local_simulation.reset_current_team(token)

    response = production_client.patch(
        f"/local-test/unmatched/{record['unmatched_id']}/assign",
        headers=headers["admin"],
        json={
            "actor": "forged-actor",
            "expected_version": 1,
            "constructor": "constructor-a",
            "note": "must not persist",
        },
    )

    assert response.status_code == 400
    assert "real terminal" in response.text
    assert local_simulation._team_states[team_id]["tasks"] == before["tasks"]
    assert local_simulation._team_states[team_id]["scan_unmatched"] == before["scan_unmatched"]
    assert local_simulation._team_states[team_id]["summary"] == before["summary"]
    assert local_simulation._team_states[team_id]["audit_events"] == before["audit_events"]
    assert local_simulation._team_states[team_id] == before
    assert state_path.read_bytes() == before_bytes
    assert team_id not in local_simulation._authoritative_write_locks


def test_json_http_finalization_identity_conflict_is_409_without_state_or_persistence_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    main_module.settings.state_backend = "json"
    local_test.settings.state_backend = "json"
    state_repository.settings.state_backend = "json"
    team_id = "north-team-01"
    state_path = tmp_path / "round6-http-identity-state.json"
    monkeypatch.setenv("LOCAL_SIMULATION_STATE_PATH", str(state_path))
    local_simulation._team_states[team_id] = local_simulation.blank_state(team_id)
    token = local_simulation.set_current_team(team_id)
    try:
        state = local_simulation.get_state()
        meter_no = "120000912473"
        meter_key = local_simulation.build_total_catalog_match_key(meter_no)
        task = local_simulation.ensure_task_for_terminal("T-ROUND6-OLD")
        state["groups"].append(
            {
                "id": "g-round6-http-conflict",
                "task_id": task["id"],
                "terminal": "T-ROUND6-OLD",
                "stage_terminal": "T-ROUND6-OLD",
                "meter_no": meter_no,
                "meter_match_key": meter_key,
                "address": "old road",
                "status": "incomplete",
                "photos": [],
                "photo_count": 0,
            }
        )
        record = local_simulation.ensure_unmatched_record(
            {
                "unmatched_id": "round6-http-identity-conflict",
                "barcode": meter_no,
                "meter_no": meter_no,
                "collector": "C001",
                "module_asset_no": "M001",
                "photo_urls": ["https://photos.example/round6-http.jpg"],
            }
        )
        review = unmatched_review.build_review(record)
        review.update(
            {
                "manual_confirmed": True,
                "reviewer": "root-admin",
                "reviewed_at": "2026-07-13T12:00:00+00:00",
            }
        )
        record["temporary_review"] = review
        state["scan_unmatched"].append(record)
        state["total_catalog"].append(
            {
                "id": "catalog-round6-http-conflict",
                "terminal": "T-ROUND6-NEW",
                "meter_no": meter_no,
                "meter_match_key": meter_key,
                "address": "new road",
            }
        )
        candidate = local_simulation.list_unmatched_match_candidates(record["unmatched_id"])["items"][0]
        assert candidate["target_group_id"] == ""
        local_simulation.refresh_summary()
        local_simulation.save_all_team_states()
        before = deepcopy(state)
        before_bytes = state_path.read_bytes()
    finally:
        local_simulation.reset_current_team(token)

    response = production_client.post(
        f"/local-test/unmatched/{record['unmatched_id']}/finalize-match",
        headers=headers["admin"],
        json={"candidate_key": candidate["candidate_key"], "expected_version": 1},
    )

    assert response.status_code == 409
    assert "conflicts with existing formal group identity" in response.json()["detail"]
    after = local_simulation._team_states[team_id]
    for field in ("groups", "tasks", "summary", "audit_events", "unmatched_finalization_replays"):
        assert after[field] == before[field]
    assert after == before
    assert state_path.read_bytes() == before_bytes
    assert team_id not in local_simulation._authoritative_write_locks


def test_fourth_review_production_rejections_do_not_create_team_or_lock_state(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    main_module.settings.state_backend = "json"
    local_test.settings.state_backend = "json"
    authenticated_team = "north-team-01"
    untrusted_team = "task-4-untrusted-header"
    local_simulation._team_states.pop(authenticated_team, None)
    local_simulation._team_states.pop(untrusted_team, None)
    local_simulation._authoritative_write_locks.pop(authenticated_team, None)
    local_simulation._authoritative_write_locks.pop(untrusted_team, None)
    begin_calls: list[str] = []
    original_begin = local_simulation.begin_authoritative_json_write

    def tracked_begin(team_id: str):
        begin_calls.append(local_simulation.normalize_team_id(team_id))
        return original_begin(team_id)

    monkeypatch.setattr(main_module, "begin_authoritative_json_write", tracked_begin)

    anonymous = production_client.post(
        "/local-test/scan/clear",
        headers={"X-Team-Id": untrusted_team},
    )
    wrong_role = production_client.post(
        "/local-test/scan/clear",
        headers={**headers["reviewer"], "X-Team-Id": untrusted_team},
    )

    assert anonymous.status_code == 401
    assert wrong_role.status_code == 403
    assert begin_calls == []
    assert untrusted_team not in local_simulation._team_states
    assert authenticated_team not in local_simulation._team_states
    assert untrusted_team not in local_simulation._authoritative_write_locks
    assert authenticated_team not in local_simulation._authoritative_write_locks

    class FakeRepository:
        def clear_scan_data(self):
            return {"summary": {"scan_rows": 0}}

    monkeypatch.setattr(local_test, "state_repository", lambda: FakeRepository())
    allowed = production_client.post(
        "/local-test/scan/clear",
        headers={**headers["admin"], "X-Team-Id": untrusted_team},
    )

    assert allowed.status_code == 200
    assert begin_calls == [authenticated_team]
    assert untrusted_team not in local_simulation._team_states
    assert authenticated_team in local_simulation._team_states
    assert untrusted_team not in local_simulation._authoritative_write_locks
    assert authenticated_team not in local_simulation._authoritative_write_locks


def test_json_request_write_waits_for_finalizer_cas_and_preserves_both_writes(monkeypatch) -> None:
    team_id = "task-4-third-review"
    team_token = local_simulation.set_current_team(team_id)
    try:
        state = local_simulation.get_state()
        state.clear()
        state.update(local_simulation.blank_state(team_id))
        state["summary"] = local_simulation.empty_summary()
        record = local_simulation.ensure_unmatched_record(
            {
                "barcode": "120000912473",
                "meter_no": "120000912473",
                "collector": "C001",
                "module_asset_no": "M001",
                "photo_urls": [f"https://photos.example/third-review/{index}.jpg" for index in range(4)],
            }
        )
        review = unmatched_review.build_review(record)
        review.update(
            {
                "manual_confirmed": True,
                "reviewer": "admin-finalizer",
                "reviewed_at": "2026-07-13T12:00:00+00:00",
            }
        )
        record["temporary_review"] = review
        state["scan_unmatched"].append(record)
        state["total_catalog"].append(
            {
                "id": "catalog-third-review",
                "terminal": "T-THIRD-REVIEW",
                "meter_no": "120000912473",
                "meter_match_key": local_simulation.build_total_catalog_match_key("120000912473"),
                "address": "third review road",
            }
        )
        candidate = local_simulation.list_unmatched_match_candidates(record["unmatched_id"])["items"][0]
    finally:
        local_simulation.reset_current_team(team_token)

    monkeypatch.setattr(main_module.settings, "state_backend", "json")
    finalizer_after_cas = Event()
    release_finalizer = Event()
    request_entered_protocol = Event()
    request_started = Event()
    finalizer_errors: list[Exception] = []
    finalizer_results: list[dict] = []
    request_responses = []
    original_save = local_simulation.save_all_team_states
    original_clear = local_simulation.clear_scan_data

    def pause_after_finalizer_cas() -> None:
        finalizer_after_cas.set()
        if not release_finalizer.wait(timeout=5):
            raise TimeoutError("test did not release finalizer CAS")
        original_save()

    def tracked_request_begin(target_team_id: str):
        request_entered_protocol.set()
        request_started.set()
        return local_simulation.begin_authoritative_json_write(target_team_id)

    def tracked_clear_scan_data() -> dict:
        request_started.set()
        return original_clear()

    def run_finalizer() -> None:
        token = local_simulation.set_current_team(team_id)
        try:
            finalizer_results.append(
                local_simulation.finalize_unmatched_match(
                    record["unmatched_id"],
                    actor="admin-finalizer",
                    candidate_key=candidate["candidate_key"],
                    expected_version=1,
                )
            )
        except Exception as exc:
            finalizer_errors.append(exc)
        finally:
            local_simulation.reset_current_team(token)

    test_client = TestClient(create_app())

    def run_request_write() -> None:
        request_responses.append(
            test_client.post("/local-test/scan/clear", headers={"X-Team-Id": team_id})
        )

    monkeypatch.setattr(local_simulation, "save_all_team_states", pause_after_finalizer_cas)
    monkeypatch.setattr(local_simulation, "clear_scan_data", tracked_clear_scan_data)
    monkeypatch.setattr(main_module, "begin_authoritative_json_write", tracked_request_begin, raising=False)
    finalizer_thread = Thread(target=run_finalizer)
    request_thread = Thread(target=run_request_write)
    finalizer_thread.start()
    assert finalizer_after_cas.wait(timeout=5)
    request_thread.start()
    assert request_started.wait(timeout=5)

    try:
        assert finalizer_thread.is_alive()
    finally:
        release_finalizer.set()
        finalizer_thread.join(timeout=5)
        request_thread.join(timeout=5)

    assert request_entered_protocol.is_set()
    assert not finalizer_thread.is_alive()
    assert not request_thread.is_alive()
    assert finalizer_errors == []
    assert len(finalizer_results) == 1
    assert len(request_responses) == 1
    assert request_responses[0].status_code == 200

    team_token = local_simulation.set_current_team(team_id)
    try:
        final_state = local_simulation.get_state()
        assert any(
            group.get("source_unmatched_id") == record["unmatched_id"]
            for group in final_state["groups"]
        )
        assert final_state["scan_unmatched"] == []
        assert final_state["summary"]["scan_rows"] == 0
    finally:
        local_simulation.reset_current_team(team_token)


def demo_admin_headers() -> dict[str, str]:
    admin_login = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    assert admin_login.status_code == 200
    return {"Authorization": f"bearer {admin_login.json()['data']['access_token']}"}


def test_group_search_api_preserves_all_nested_durable_verification_statuses(monkeypatch) -> None:
    statuses = [
        "not_eligible",
        "pending",
        "processing",
        "passed",
        "partial",
        "unreadable",
        "mismatch",
        "manual_confirmed",
        "failed",
    ]
    items = [
        {
            "id": f"api-{status}",
            "task_id": 1,
            "terminal": "TERMINAL-API",
            "meter_no": f"METER-{status}",
            "status": "pending",
            "photo_count": 4,
            "barcode_verification": {
                "status": status,
                "eligible": status != "not_eligible",
                "terminal": status in {"passed", "partial", "unreadable", "mismatch", "manual_confirmed", "failed"},
                "recognition_source": "manual_confirmed" if status == "manual_confirmed" else "machine_barcode",
                "evidence_version": 3,
                "attempt_count": 1,
                "invalidation_reason": "",
                "result": {"passed_count": 3 if status in {"passed", "manual_confirmed"} else 1},
            },
        }
        for status in statuses
    ]

    class FakeRepository:
        def search_group_targets(self, **_kwargs):
            return {"total": len(items), "terminals": ["TERMINAL-API"], "items": items}

    monkeypatch.setattr(group_routes, "state_repository", lambda: FakeRepository())

    response = client.get(
        "/groups/search?query=METER&limit=20",
        headers=demo_admin_headers(),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert [item["barcode_verification"]["status"] for item in payload["items"]] == statuses


def tiny_jpeg_bytes(color: str | tuple[int, int, int] = "white") -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, format="JPEG")
    return buffer.getvalue()


def tiny_png_bytes(color: str | tuple[int, int, int] = "white") -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, format="PNG")
    return buffer.getvalue()


def seed_photo_barcode_review_groups(count: int = 3) -> list[dict]:
    client.post("/local-test/bootstrap")
    state = local_simulation.get_state()
    seeded: list[dict] = []
    for index, group in enumerate(state["groups"][:count]):
        group["status"] = "approved" if index == 0 else "pending"
        group["reviewer"] = "api-test" if index == 0 else ""
        group["module_asset_no"] = f"MODULE-{index + 1:03d}"
        group["asset_no"] = group["module_asset_no"]
        group["collector"] = f"COLLECTOR-{index + 1:03d}"
        group["construction_module_asset_no"] = group["module_asset_no"]
        group["construction_collector"] = group["collector"]
        group["photos"] = [
            {
                "id": f"{group['id']}-photo-{photo_index}",
                "group_id": group["id"],
                "sort_order": photo_index,
                "category": ["before_box", "after_box", "module_meter", "collector_barcode"][photo_index - 1],
                "category_label": ["before_box", "after_box", "module_meter", "collector_barcode"][photo_index - 1],
                "image_url": f"https://example.test/{group['id']}-{photo_index}.jpg",
                "thumbnail_url": f"https://example.test/{group['id']}-{photo_index}-thumb.jpg",
                "barcode": "",
                "collector": "",
                "asset_no": "",
                "creator": "安装人员A",
            }
            for photo_index in range(1, 5)
        ]
        group["photo_count"] = 4
        for photo_index, photo in enumerate(group["photos"][:4]):
            photo["barcode_check_status"] = "unreadable"
            photo["barcode_check_expected_type"] = "none"
            photo["barcode_check_values"] = []
            photo["barcode_check_normalized_values"] = []
            photo["barcode_group_evidence_checked"] = True
        seeded.append(group)
    local_simulation.save_all_team_states()
    assert len(seeded) == count
    return seeded


def test_health_check() -> None:
    response = client.get("/health", headers={"x-request-id": "test-request"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "test-request"
    payload = response.json()
    assert payload["data"] == {"status": "ok"}
    assert payload["request_id"] == "test-request"


def test_system_status_version_requires_admin_and_reports_runtime_state() -> None:
    admin = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    constructor = client.post("/auth/login", json={"username": "constructor", "password": "construct123"})
    admin_headers = {"Authorization": f"bearer {admin.json()['data']['access_token']}"}
    constructor_headers = {"Authorization": f"bearer {constructor.json()['data']['access_token']}"}

    denied = client.get("/local-test/system/status", headers=constructor_headers)
    response = client.get("/local-test/system/status", headers=admin_headers)

    assert denied.status_code == 403
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["version"] == "3.2.8"
    assert {"disk", "state_file", "uploads", "storage", "backups", "teams", "warnings"}.issubset(data)
    assert "used_percent" in data["disk"]
    assert "warn_bytes" in data["uploads"]
    assert data["storage"]["backend"] in {"local", "oss"}


def test_oss_photo_response_resolves_preview_url_without_rewriting_canonical(monkeypatch) -> None:
    monkeypatch.setattr(settings, "oss_public_base_url", "https://oss-preview.example.test/base")
    monkeypatch.setattr(settings, "oss_thumbnail_process", "image/resize,w_120")
    monkeypatch.setattr(settings, "oss_preview_process", "image/resize,w_800")
    photo = {
        "id": "p-oss",
        "image_url": "oss://bucket-a/path/to/photo 1.jpg",
        "storage_type": "oss",
        "storage_key": "path/to/photo 1.jpg",
        "storage_bucket": "bucket-a",
    }

    resolved = resolve_photo_for_response(photo)

    assert resolved["canonical_image_url"] == "oss://bucket-a/path/to/photo 1.jpg"
    assert resolved["image_url"] == "https://oss-preview.example.test/base/path/to/photo%201.jpg"
    assert resolved["thumbnail_url"] == "https://oss-preview.example.test/base/path/to/photo%201.jpg?x-oss-process=image/resize,w_120"
    assert resolved["preview_url"] == "https://oss-preview.example.test/base/path/to/photo%201.jpg?x-oss-process=image/resize,w_800"
    assert photo["image_url"] == "oss://bucket-a/path/to/photo 1.jpg"


def test_oss_photo_response_keeps_raw_reference_when_signing_config_missing(monkeypatch) -> None:
    monkeypatch.setattr(settings, "oss_public_base_url", "")
    monkeypatch.setattr(settings, "oss_endpoint", "")
    monkeypatch.setattr(settings, "oss_internal_endpoint", "")
    monkeypatch.setattr(settings, "oss_bucket", "")
    monkeypatch.setattr(settings, "oss_access_key_id", "")
    monkeypatch.setattr(settings, "oss_access_key_secret", "")
    photo = {
        "id": "p-oss",
        "image_url": "oss://bucket-a/path/to/photo.jpg",
        "storage_type": "oss",
        "storage_key": "path/to/photo.jpg",
        "storage_bucket": "bucket-a",
    }

    resolved = resolve_photo_for_response(photo)

    assert resolved["canonical_image_url"] == "oss://bucket-a/path/to/photo.jpg"
    assert resolved["image_url"] == "oss://bucket-a/path/to/photo.jpg"
    assert resolved["thumbnail_url"] == "oss://bucket-a/path/to/photo.jpg"
    assert resolved["preview_url"] == "oss://bucket-a/path/to/photo.jpg"


def test_broken_oss_processed_preview_falls_back_to_original(monkeypatch) -> None:
    pytest = importlib.import_module("pytest")
    pytest.importorskip("PIL")
    from PIL import Image, ImageDraw

    from app.api.routes import local_test

    broken = Image.new("RGB", (320, 180), (128, 128, 128))
    draw = ImageDraw.Draw(broken)
    palette = [(20, 20, 20), (236, 236, 236), (70, 120, 60), (160, 120, 170)]
    for x in range(84, 236):
        draw.line((x, 0, x, 180), fill=palette[x % len(palette)])
    broken_buffer = BytesIO()
    broken.save(broken_buffer, format="JPEG", quality=95)

    original = Image.new("RGB", (320, 180), (220, 230, 240))
    original_buffer = BytesIO()
    original.save(original_buffer, format="JPEG", quality=90)
    original_bytes = original_buffer.getvalue()

    def fake_sign_oss_server_url(_key: str, process: str = "") -> str:
        return f"signed://{process or 'original'}"

    def fake_read_remote_image(url: str, *, max_bytes: int = 30 * 1024 * 1024):
        if url.endswith("original"):
            return original_bytes, "image/jpeg"
        return broken_buffer.getvalue(), "image/jpeg"

    monkeypatch.setattr(local_test, "sign_oss_server_url", fake_sign_oss_server_url)
    monkeypatch.setattr(local_test, "_read_remote_image", fake_read_remote_image)

    content, media_type = local_test._read_oss_photo_or_repair(
        "g-1",
        {},
        "module-manager-v2/default-team/photos/aa/photo.jpg",
        "",
        "image/resize,w_1280",
    )

    assert media_type == "image/jpeg"
    assert content == original_bytes


def test_group_photo_content_original_oss_uses_unprocessed_source(monkeypatch) -> None:
    from app.api.routes import local_test

    group = {
        "id": "g-oss",
        "photos": [
            {
                "id": "p-oss",
                "image_url": "oss://bucket-a/path/to/photo.jpg",
                "storage_type": "oss",
                "storage_key": "path/to/photo.jpg",
            }
        ],
    }
    captured: dict[str, str] = {}

    class FakeRepository:
        def get_group(self, group_id: str) -> dict | None:
            return group if group_id == "g-oss" else None

        def get_delivery_cached_photo_path(self, _group_id: str, _photo_id: str):
            raise FileNotFoundError

    def fake_read_oss_photo_or_repair(
        _group_id: str,
        _photo: dict,
        _storage_key: str,
        _parsed_key: str,
        process: str,
        *,
        kind: str = "preview",
    ) -> tuple[bytes, str]:
        captured["process"] = process
        captured["kind"] = kind
        return b"jpeg", "image/jpeg"

    monkeypatch.setattr(local_test, "state_repository", lambda: FakeRepository())
    monkeypatch.setattr(local_test, "_read_oss_photo_or_repair", fake_read_oss_photo_or_repair)

    response = client.get("/local-test/groups/g-oss/photos/p-oss/content?kind=original")

    assert response.status_code == 200
    assert captured == {"process": "", "kind": "original"}


def test_login_page_and_demo_auth_are_available() -> None:
    page = client.get("/login")
    config = client.get("/auth/config")
    admin = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    reviewer = client.post("/auth/login", json={"username": "reviewer", "password": "review123"})
    constructor = client.post("/auth/login", json={"username": "constructor", "password": "construct123"})
    bad = client.post("/auth/login", json={"username": "admin", "password": "bad"})

    assert_vue_shell_response(page)
    assert "admin / admin123" not in page.text
    assert "reviewer / review123" not in page.text
    assert 'value="admin"' not in page.text
    assert 'value="admin123"' not in page.text
    assert config.status_code == 200
    assert config.json()["data"]["demo_auth_enabled"] is True
    assert {item["username"] for item in config.json()["data"]["demo_accounts"]} == {"admin", "constructor"}
    assert {item["team_id"] for item in config.json()["data"]["demo_accounts"]} == {"demo-team"}
    assert admin.status_code == 200
    assert admin.json()["data"]["team_id"] == "demo-team"
    assert admin.json()["data"]["user"]["home"] == "/app"
    assert admin.json()["data"]["user"]["team_id"] == "demo-team"
    assert admin.json()["data"]["user"]["roles"] == ["admin"]
    assert reviewer.status_code == 401
    assert constructor.status_code == 200
    assert constructor.json()["data"]["user"]["roles"] == ["constructor"]
    assert constructor.json()["data"]["user"]["home"] == "/app?page=construction"
    assert bad.status_code == 401


def test_sliding_window_rate_limiter_sweeps_expired_keys() -> None:
    limiter = SlidingWindowRateLimiter(limit=1, window_seconds=1)

    assert limiter.check("stale-key").allowed is True
    time.sleep(1.1)
    assert limiter.check("active-key").allowed is True

    assert "stale-key" not in limiter._events
    assert "active-key" in limiter._events


def test_request_client_ip_ignores_forwarded_for_from_untrusted_clients() -> None:
    request = SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.10"},
        client=SimpleNamespace(host="198.51.100.99"),
    )

    assert auth.request_client_ip(request) == "198.51.100.99"


def test_request_client_ip_accepts_forwarded_for_from_trusted_proxy() -> None:
    request = SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.10, 198.51.100.20"},
        client=SimpleNamespace(host="127.0.0.1"),
    )

    assert auth.request_client_ip(request) == "203.0.113.10"


def test_login_rate_limit_blocks_repeated_bad_passwords() -> None:
    auth.login_limiter.clear()
    for _ in range(8):
        response = client.post(
            "/auth/login",
            headers={"x-forwarded-for": "203.0.113.10"},
            json={"username": "admin", "password": "wrong"},
        )
        assert response.status_code == 401

    successful_login = client.post(
        "/auth/login",
        headers={"x-forwarded-for": "203.0.113.10"},
        json={"username": "admin", "password": "admin123"},
    )
    assert successful_login.status_code == 200

    response = client.post(
        "/auth/login",
        headers={"x-forwarded-for": "203.0.113.10"},
        json={"username": "admin", "password": "wrong"},
    )

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


def test_login_rate_limit_does_not_count_successful_logins() -> None:
    auth.login_limiter.clear()
    for _ in range(12):
        response = client.post(
            "/auth/login",
            headers={"x-forwarded-for": "203.0.113.11"},
            json={"username": "admin", "password": "admin123"},
        )

        assert response.status_code == 200


def test_demo_auth_is_disabled_by_default_in_production(monkeypatch) -> None:
    production_settings = SimpleNamespace(
        app_env="production",
        demo_auth_enabled=None,
        admin_username="real-admin",
        admin_password="real-secret",
    )
    monkeypatch.setattr(auth, "settings", production_settings)

    demo_admin = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    real_admin = client.post("/auth/login", json={"username": "real-admin", "password": "real-secret"})
    production_config = client.get("/auth/config")

    assert demo_admin.status_code == 401
    assert real_admin.status_code == 200
    assert real_admin.json()["data"]["user"]["roles"] == ["admin"]
    assert production_config.status_code == 200
    assert production_config.json()["data"]["demo_auth_enabled"] is False
    assert production_config.json()["data"]["demo_accounts"] == []


def test_production_account_config_and_api_token_gate(monkeypatch, tmp_path) -> None:
    production_settings = production_test_settings(
        demo_auth_enabled=False,
        admin_username="root-admin",
        admin_password="RootPass12345",
        admin_team_id="north-team-01",
        auth_users_path=str(tmp_path / "users.json"),
        jwt_secret="jwt-secret-for-production-test-12345",
        jwt_expire_minutes=60,
        trusted_proxy_hosts={"testclient"},
    )
    monkeypatch.setattr(auth, "settings", production_settings)
    monkeypatch.setattr(account_store, "settings", production_settings)
    monkeypatch.setattr(security, "settings", production_settings)
    monkeypatch.setattr(main_module, "settings", production_settings)
    production_client = TestClient(main_module.create_app())

    admin_login = production_client.post(
        "/auth/login",
        json={"username": "root-admin", "password": "RootPass12345"},
    )
    assert admin_login.status_code == 200
    admin_token = admin_login.json()["data"]["access_token"]
    admin_headers = {"Authorization": f"bearer {admin_token}"}

    assert production_client.get("/local-test/summary").status_code == 401
    assert production_client.get("/auth/users").status_code == 401

    users = production_client.get("/auth/users", headers=admin_headers)
    assert users.status_code == 200
    assert {item["username"] for item in users.json()["data"]["items"]} == {"root-admin"}

    created = production_client.post(
        "/auth/users",
        headers=admin_headers,
        json={
            "username": "constructor-a",
            "password": "ConstructPass12345",
            "name": "Constructor A",
            "roles": ["constructor"],
            "team_id": "north-team-01",
            "status": "active",
        },
    )
    assert created.status_code == 200
    constructor_login = production_client.post(
        "/auth/login",
        headers={"x-forwarded-for": "10.0.0.5", "user-agent": "constructor-agent"},
        json={"username": "constructor-a", "password": "ConstructPass12345", "team_id": "other-team"},
    )
    assert constructor_login.status_code == 200
    assert constructor_login.json()["data"]["team_id"] == "north-team-01"
    constructor_token = constructor_login.json()["data"]["access_token"]

    summary = production_client.get("/local-test/summary", headers=admin_headers)
    assert summary.status_code == 200
    summary_payload = summary.json()["data"]["summary"]
    assert summary_payload["team_id"] == "north-team-01"
    assert {
        "photo_accuracy_checked",
        "photo_accuracy_passed",
        "photo_accuracy_failed",
        "photo_accuracy_unreadable",
        "photo_accuracy_not_required",
        "photo_accuracy_rate",
        "group_barcode_accuracy_checked",
        "group_barcode_accuracy_passed",
        "group_barcode_accuracy_failed",
        "group_barcode_accuracy_unreadable",
        "group_barcode_accuracy_not_required",
        "group_barcode_accuracy_rate",
    }.issubset(summary_payload)
    reviewer_headers = {
        "Authorization": "bearer "
        + security.create_access_token(
            {"sub": "reviewer-a", "username": "reviewer-a", "roles": ["reviewer"], "team_id": "north-team-01"}
        )
    }
    reviewer_review_list = production_client.get(
        "/local-test/photo-barcode/review-groups",
        headers=reviewer_headers,
    )
    assert reviewer_review_list.status_code == 403
    admin_review_list = production_client.get(
        "/local-test/photo-barcode/review-groups?status=unreadable",
        headers=admin_headers,
    )
    assert admin_review_list.status_code == 200
    assert {"total", "items"}.issubset(admin_review_list.json()["data"])

    users_after_login = production_client.get("/auth/users", headers=admin_headers)
    constructor_user = next(item for item in users_after_login.json()["data"]["items"] if item["username"] == "constructor-a")
    assert constructor_user["last_login_ip"] == "10.0.0.5"
    assert len(constructor_user["login_history"]) == 1
    assert constructor_user["login_history"][0]["ip"] == "10.0.0.5"
    assert constructor_user["login_history"][0]["device"] == "constructor-agent"
    assert constructor_user["login_history"][0]["at"]

    deleted = production_client.delete("/auth/users/constructor-a", headers=admin_headers)
    assert deleted.status_code == 200
    assert deleted.json()["data"]["user"]["username"] == "constructor-a"
    users_after_delete = production_client.get("/auth/users", headers=admin_headers)
    assert {item["username"] for item in users_after_delete.json()["data"]["items"]} == {"root-admin"}
    deleted_login = production_client.post(
        "/auth/login",
        json={"username": "constructor-a", "password": "ConstructPass12345"},
    )
    assert deleted_login.status_code == 401
    delete_self = production_client.delete("/auth/users/root-admin", headers=admin_headers)
    assert delete_self.status_code == 400


def test_project_summary_route_reuses_server_snapshot_until_forced(monkeypatch, tmp_path) -> None:
    from app.api.routes import local_test
    from app.services.project_board_cache import ProjectBoardSummaryCache

    calls = 0
    cache = ProjectBoardSummaryCache(cache_root=tmp_path, interval_seconds=300, enabled=True)

    class FakeRepository:
        def summary(self) -> dict:
            nonlocal calls
            calls += 1
            return {"summary": {"team_id": "default-team", "groups": calls}, "paths": {}}

    monkeypatch.setattr(local_test, "project_board_summary_cache", cache)
    monkeypatch.setattr(local_test, "state_repository", lambda: FakeRepository())

    first = client.get("/local-test/summary")
    second = client.get("/local-test/summary")
    forced = client.get("/local-test/summary?refresh=true")

    assert first.status_code == 200
    assert second.status_code == 200
    assert forced.status_code == 200
    assert first.json()["data"]["summary"]["groups"] == 1
    assert second.json()["data"]["summary"]["groups"] == 1
    assert forced.json()["data"]["summary"]["groups"] == 2
    assert calls == 2


def test_task_snapshot_route_reuses_cache_and_forced_refreshes(monkeypatch, tmp_path) -> None:
    from app.services.task_snapshot_cache import TaskSnapshotCache

    calls = 0

    class FakeRepository:
        def list_tasks(self, **kwargs):
            nonlocal calls
            calls += 1
            assert kwargs == {"include_installer_distribution": False}
            return [{"id": str(calls), "terminal": "T-1"}]

    monkeypatch.setattr(
        local_test,
        "task_snapshot_cache",
        TaskSnapshotCache(cache_root=tmp_path, interval_seconds=60, enabled=True),
        raising=False,
    )
    monkeypatch.setattr(local_test, "state_repository", lambda: FakeRepository())

    first = client.get("/local-test/tasks/snapshot")
    second = client.get("/local-test/tasks/snapshot")
    forced = client.get("/local-test/tasks/snapshot?refresh=true")

    assert first.status_code == second.status_code == forced.status_code == 200
    assert first.json()["data"]["version"] == second.json()["data"]["version"]
    assert forced.json()["data"]["version"] != first.json()["data"]["version"]
    assert calls == 2


def test_task_mutation_routes_invalidate_the_current_team_snapshot(monkeypatch) -> None:
    invalidated: list[str] = []

    class FakeCache:
        def invalidate(self, team_id: str) -> None:
            invalidated.append(team_id)

    class FakeRepository:
        def claim_task(self, task_id, reviewer):
            return {"id": str(task_id), "claimed_by": reviewer}

        def release_task(self, task_id, reviewer, force=False):
            return {"id": str(task_id), "claimed_by": "", "force": force}

        def release_all_claimed_tasks(self, reviewer):
            return {"released": 1, "reviewer": reviewer}

        def open_construction_task(self, task_id, actor):
            return {"id": str(task_id), "actor": actor}

        def close_construction_task(self, task_id, actor):
            return {"id": str(task_id), "actor": actor}

        def set_construction_task_priority(self, task_id, actor, priority):
            return {"id": str(task_id), "actor": actor, "construction_priority": priority}

        def assign_construction_task(self, task_id, **kwargs):
            return {"id": str(task_id), **kwargs}

        def unassign_construction_task(self, task_id, actor):
            return {"id": str(task_id), "actor": actor}

        def claim_construction_task(self, task_id, actor):
            return {"id": str(task_id), "actor": actor}

        def release_construction_task(self, task_id, actor, force=False):
            return {"id": str(task_id), "actor": actor, "force": force}

    monkeypatch.setattr(local_test, "task_snapshot_cache", FakeCache())
    monkeypatch.setattr(local_test, "state_repository", lambda: FakeRepository())
    monkeypatch.setattr(local_test, "request_is_admin", lambda _request: True)
    monkeypatch.setattr(local_test, "require_production_admin_payload", lambda _request: None)

    responses = [
        client.post("/local-test/tasks/1/claim", json={"reviewer": "reviewer-a"}),
        client.post("/local-test/tasks/1/release", json={"reviewer": "reviewer-a"}),
        client.post("/local-test/tasks/release-all", json={"reviewer": "admin"}),
        client.patch("/local-test/construction/tasks/1/open", json={"actor": "admin"}),
        client.patch("/local-test/construction/tasks/1/close", json={"actor": "admin"}),
        client.patch("/local-test/construction/tasks/1/priority", json={"priority": True}),
        client.patch(
            "/local-test/construction/tasks/1/assign",
            json={"actor": "admin", "constructor": "constructor-a"},
        ),
        client.patch("/local-test/construction/tasks/1/unassign", json={"actor": "admin"}),
        client.post("/local-test/construction/tasks/1/claim", json={"actor": "constructor-a"}),
        client.post("/local-test/construction/tasks/1/release", json={"actor": "constructor-a"}),
    ]

    assert all(response.status_code == 200 for response in responses)
    assert invalidated == ["default-team"] * len(responses)


def test_group_mutation_routes_invalidate_the_current_team_snapshot() -> None:
    mutation_functions = [
        local_test.finalize_unmatched_match,
        local_test.associate_unmatched,
        local_test.create_group_from_unmatched,
        local_test.construction_group_upload_batch,
        local_test.create_empty_group,
        local_test.change_group_terminal,
        local_test.change_group_metadata,
        local_test.import_group_photo_urls,
        local_test.upload_group_photo_images,
        local_test.save_review,
        local_test.mark_exception,
        local_test.reset_group_unconstructed,
        local_test.return_group_exception_order,
        local_test.save_photo_category,
        local_test.rescan_photo_barcode,
        local_test.confirm_group_barcode_manually,
        local_test.delete_photo,
    ]

    invalid_counts = [
        (function.__name__, inspect.getsource(function).count("invalidate_task_snapshot()"))
        for function in mutation_functions
        if inspect.getsource(function).count("invalidate_task_snapshot()") != 1
    ]

    assert invalid_counts == []


def test_catalog_and_scan_mutations_invalidate_the_current_team_snapshot() -> None:
    mutation_functions = [
        local_test.clear_scan,
        local_test.import_url_rows,
        local_test.import_template_xlsx,
        local_test.run_scan_import_job,
        local_test.import_total_catalog,
    ]

    invalid_counts = [
        (function.__name__, inspect.getsource(function).count("invalidate_task_snapshot("))
        for function in mutation_functions
        if inspect.getsource(function).count("invalidate_task_snapshot(") != 1
    ]

    assert invalid_counts == []


def test_production_group_mutations_invalidate_the_admin_team_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRepository:
        def bulk_archive_groups(self, group_ids, *, actor, reason):
            return {"items": [], "group_ids": group_ids, "actor": actor, "reason": reason}

        def update_group_metadata(self, group_id, *, actor, updates, audit_action):
            return {"group": {"id": group_id}, "actor": actor, "updates": updates, "audit_action": audit_action}

        def reset_group_to_unconstructed(self, group_id, *, actor, reason, force, source_page):
            return {"group": {"id": group_id}, "actor": actor, "reason": reason, "force": force}

        def reset_group_to_unreviewed(self, group_id, *, actor, reason, force, source_page):
            return {"group": {"id": group_id}, "actor": actor, "reason": reason, "force": force}

    invalidated: list[str] = []
    monkeypatch.setattr(group_routes, "state_repository", lambda: FakeRepository())
    monkeypatch.setattr(
        group_routes,
        "invalidate_task_snapshot_for_team",
        invalidated.append,
        raising=False,
    )
    request = Request({"type": "http", "method": "POST", "path": "/groups", "headers": []})
    request.state.request_id = "group-mutation-test"
    admin_payload = {"team_id": "team-formal", "username": "admin-a"}

    group_routes.bulk_archive_groups(
        group_routes.GroupBulkArchiveRequest(group_ids=["group-1"], reason="archive"),
        request,
        admin_payload,
    )
    group_routes.update_group_metadata(
        "group-1",
        group_routes.GroupMetadataUpdateRequest(updates={"address": "new address"}),
        request,
        admin_payload,
    )
    group_routes.reset_group_unconstructed(
        "group-1",
        group_routes.GroupResetRequest(reason="reset construction"),
        request,
        admin_payload,
    )
    group_routes.reset_group_unreviewed(
        "group-1",
        group_routes.GroupResetRequest(reason="reset review"),
        request,
        admin_payload,
    )

    assert invalidated == ["team-formal"] * 4


def test_miniprogram_committed_uploads_invalidate_the_current_team_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRepository:
        def upload_construction_group_batch(self, group_id, **_kwargs):
            return {"group": {"id": group_id, "photos": []}}

    stored_photo = {
        "url": "/static/uploads/construction/photo.jpg",
        "sha256": "a" * 64,
        "storage_type": "local",
        "storage_key": "construction/photo.jpg",
        "storage_bucket": "",
        "storage_source": "local",
    }
    invalidated: list[str] = []
    monkeypatch.setattr(miniprogram, "require_constructor_payload", lambda _request: {"sub": "constructor-a"})
    monkeypatch.setattr(miniprogram, "validate_construction_upload_group_before_file_save", lambda _group_id: None)
    monkeypatch.setattr(miniprogram, "current_request_team", lambda _request: "team-mini")
    monkeypatch.setattr(miniprogram, "display_name_for_actor", lambda _request, _actor: "Installer A")
    monkeypatch.setattr(miniprogram, "save_image_bytes", lambda **_kwargs: stored_photo)
    monkeypatch.setattr(miniprogram, "state_repository", lambda: FakeRepository())
    monkeypatch.setattr(
        miniprogram,
        "invalidate_task_snapshot_for_team",
        invalidated.append,
        raising=False,
    )
    request = Request({"type": "http", "method": "POST", "path": "/miniprogram/groups/group-1", "headers": []})
    request.state.request_id = "miniprogram-upload-test"

    asyncio.run(
        miniprogram.upload_group_batch(
            "group-1",
            request,
            client_batch_id="batch-one",
            client_completed_at="2026-07-22T01:00:00+08:00",
            collector="collector-1",
            module_asset_no="module-1",
            exception_note="",
            photo_slots=["before_box"],
            client_photo_ids=["photo-one"],
            files=[UploadFile(filename="one.jpg", file=BytesIO(b"image-one"))],
        )
    )
    miniprogram._pending_upload_batches.clear()
    asyncio.run(
        miniprogram.upload_group_file(
            "group-1",
            request,
            client_batch_id="batch-two",
            client_completed_at="2026-07-22T01:05:00+08:00",
            collector="collector-1",
            module_asset_no="module-1",
            photo_slot="after_box",
            client_photo_id="photo-two",
            expected_count=1,
            commit=True,
            file=UploadFile(filename="two.jpg", file=BytesIO(b"image-two")),
        )
    )

    assert invalidated == ["team-mini", "team-mini"]


def test_review_groups_route_caps_page_at_twenty(monkeypatch) -> None:
    class FakeRepository:
        def list_review_task_groups(self, task_id: int, **kwargs):
            assert task_id == 1
            assert kwargs["limit"] == 20
            return {
                "total": 1,
                "items": [{"id": "group-1"}],
                "status_counts": {
                    "all": 1,
                    "reviewable": 1,
                    "exception": 0,
                    "archived": 0,
                    "unconstructed": 0,
                },
                "limit": 20,
                "offset": 0,
            }

    monkeypatch.setattr(local_test, "state_repository", lambda: FakeRepository())

    oversized = client.get("/local-test/tasks/1/review-groups?limit=100&offset=0&review_status=all")
    response = client.get("/local-test/tasks/1/review-groups?limit=20&offset=0&review_status=all")

    assert oversized.status_code == 422
    assert response.status_code == 200
    assert response.json()["data"]["limit"] == 20
    assert len(response.json()["data"]["items"]) <= 20


def test_photo_barcode_review_groups_are_paginated_and_include_archived_groups() -> None:
    headers = demo_admin_headers()
    seeded = seed_photo_barcode_review_groups(count=3)

    first_page = client.get(
        "/local-test/photo-barcode/review-groups?status=unreadable&limit=2&offset=0",
        headers=headers,
    )
    second_page = client.get(
        "/local-test/photo-barcode/review-groups?status=unreadable&limit=2&offset=2",
        headers=headers,
    )

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    first_payload = first_page.json()["data"]
    second_payload = second_page.json()["data"]
    assert first_payload["total"] >= 3
    assert len(first_payload["items"]) == 2
    assert len(second_payload["items"]) >= 1
    assert first_payload["limit"] == 2
    assert first_payload["offset"] == 0
    assert second_payload["limit"] == 2
    assert second_payload["offset"] == 2
    archived_item = next(item for item in first_payload["items"] + second_payload["items"] if item["group_id"] == seeded[0]["id"])
    assert archived_item["group_status"] == "approved"
    assert archived_item["archived"] is True


def test_photo_barcode_review_groups_support_passed_all_and_query_filters() -> None:
    headers = demo_admin_headers()
    seeded = seed_photo_barcode_review_groups(count=3)
    seeded[0]["group_barcode_manual_confirmed"] = True
    seeded[0]["group_barcode_manual_confirmed_fields"] = ["meter", "module", "collector"]
    seeded[0]["terminal"] = "TERMINAL-PASSED-001"
    seeded[1]["terminal"] = "TERMINAL-UNREADABLE-002"

    passed_response = client.get(
        "/local-test/photo-barcode/review-groups?status=matched&query=TERMINAL-PASSED-001",
        headers=headers,
    )
    all_response = client.get(
        "/local-test/photo-barcode/review-groups?status=all&query=TERMINAL-",
        headers=headers,
    )

    assert passed_response.status_code == 200
    passed_payload = passed_response.json()["data"]
    assert passed_payload["total"] == 1
    assert passed_payload["items"][0]["group_id"] == seeded[0]["id"]
    assert passed_payload["items"][0]["status"] == "matched"
    assert all_response.status_code == 200
    all_items = all_response.json()["data"]["items"]
    assert {item["group_id"] for item in all_items} >= {seeded[0]["id"], seeded[1]["id"]}


def test_photo_barcode_review_groups_export_is_retired() -> None:
    headers = demo_admin_headers()

    export_response = client.get(
        "/local-test/photo-barcode/review-groups/export?status=unreadable",
        headers=headers,
    )

    assert_export_retired(export_response)


def test_photo_barcode_review_groups_export_is_retired_before_query_filtering() -> None:
    headers = demo_admin_headers()

    export_response = client.get(
        "/local-test/photo-barcode/review-groups/export?status=matched&query=TERMINAL-EXPORT-PASSED-001",
        headers=headers,
    )

    assert_export_retired(export_response)


def test_account_login_history_keeps_30_rows_and_marks_ip_common_user(monkeypatch, tmp_path) -> None:
    production_settings = production_test_settings(
        demo_auth_enabled=False,
        admin_username="root-admin",
        admin_password="RootPass12345",
        admin_team_id="north-team-01",
        auth_users_path=str(tmp_path / "users.json"),
        jwt_secret="jwt-secret-for-production-test-12345",
        jwt_expire_minutes=60,
        trusted_proxy_hosts={"testclient"},
    )
    monkeypatch.setattr(auth, "settings", production_settings)
    monkeypatch.setattr(account_store, "settings", production_settings)
    monkeypatch.setattr(security, "settings", production_settings)
    monkeypatch.setattr(main_module, "settings", production_settings)
    production_client = TestClient(main_module.create_app())

    admin_login = production_client.post(
        "/auth/login",
        json={"username": "root-admin", "password": "RootPass12345"},
    )
    admin_headers = {"Authorization": f"bearer {admin_login.json()['data']['access_token']}"}
    for username in ["constructor-a", "constructor-b"]:
        created = production_client.post(
            "/auth/users",
            headers=admin_headers,
            json={
                "username": username,
                "password": "ConstructPass12345",
                "name": username,
                "roles": ["constructor"],
                "team_id": "north-team-01",
                "status": "active",
            },
        )
        assert created.status_code == 200

    for index in range(35):
        response = production_client.post(
            "/auth/login",
            headers={"x-forwarded-for": "10.0.0.8", "user-agent": f"constructor-a-agent-{index}"},
            json={"username": "constructor-a", "password": "ConstructPass12345"},
        )
        assert response.status_code == 200

    reviewer_b_login = production_client.post(
        "/auth/login",
        headers={"x-forwarded-for": "10.0.0.8", "user-agent": "constructor-b-agent"},
        json={"username": "constructor-b", "password": "ConstructPass12345"},
    )
    assert reviewer_b_login.status_code == 200

    users = production_client.get("/auth/users", headers=admin_headers).json()["data"]["items"]
    by_username = {item["username"]: item for item in users}
    reviewer_a_history = by_username["constructor-a"]["login_history"]
    reviewer_b_history = by_username["constructor-b"]["login_history"]

    assert len(reviewer_a_history) == 30
    assert reviewer_a_history[0]["ip"] == "10.0.0.8"
    assert reviewer_a_history[0]["device"] == "constructor-a-agent-34"
    assert reviewer_b_history[0]["ip_common_user"] == "constructor-a"
    assert reviewer_b_history[0]["ip_common_user_count"] == 30
    assert reviewer_b_history[0]["ip_login_count"] == 31


def test_api_docs_are_disabled_in_production(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "settings", production_test_settings())
    production_client = TestClient(main_module.create_app())

    assert production_client.get("/docs").status_code == 404
    assert production_client.get("/redoc").status_code == 404
    assert production_client.get("/openapi.json").status_code == 404


def test_local_api_docs_do_not_receive_production_csp() -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert "content-security-policy" not in response.headers


def test_production_security_headers_present(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "settings", production_test_settings())
    production_client = TestClient(main_module.create_app())

    response = production_client.get("/login")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_production_cors_allows_project_preflight_before_auth(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "settings", production_test_settings())
    production_client = TestClient(main_module.create_app())

    response = production_client.options(
        "/projects",
        headers={
            "Origin": "https://www.sgcc.online",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://www.sgcc.online"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_production_cors_rejects_untrusted_origins(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "settings", production_test_settings())
    production_client = TestClient(main_module.create_app())

    for path, method in (("/auth/login", "POST"), ("/projects", "GET")):
        response = production_client.options(
            path,
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": method,
            },
        )

        assert response.headers.get("access-control-allow-origin") != "https://evil.example"


def test_project_routes_return_contract_shape() -> None:
    response = client.get("/projects")

    assert response.status_code == 200
    assert_success_shape(response.json())


def test_task_claim_placeholder_uses_contract_shape() -> None:
    response = client.post("/tasks/12/claim")

    assert response.status_code == 200
    payload = response.json()
    assert_success_shape(payload)
    assert payload["data"]["task_id"] == 12
    assert payload["data"]["status"] == "claimed"


def test_validation_error_uses_contract_shape() -> None:
    response = client.get("/tasks/not-an-int")

    assert response.status_code == 422
    payload = response.json()
    assert payload["data"] is None
    assert payload["error"]["code"] == "validation_error"
    assert isinstance(payload["request_id"], str)


def test_review_api_preserves_retired_delivery_cache_queue_after_json_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client.post("/local-test/bootstrap")
    tasks = client.get("/local-test/tasks").json()["data"]["items"]
    task = next(item for item in tasks if item["can_claim"])
    claimed = client.post(
        f"/local-test/tasks/{task['id']}/claim",
        json={"reviewer": "api-cache-reviewer"},
    )
    assert claimed.status_code == 200
    group = client.get(f"/local-test/tasks/{task['id']}/groups?limit=1").json()["data"]["items"][0]
    events: list[str] = []

    monkeypatch.setattr(local_test, "state_repository", lambda: state_repository.JsonStateRepository())
    monkeypatch.setattr(local_simulation, "photo_can_build_delivery_cache", lambda _photo: True)
    monkeypatch.setattr(
        local_simulation,
        "download_delivery_photo_content",
        lambda _photo: pytest.fail("review request must not access OSS"),
    )

    def persist() -> None:
        assert local_simulation._team_states[local_simulation.DEFAULT_TEAM_ID]["delivery_cache_jobs"] == []
        events.append("persist")

    monkeypatch.setattr(main_module, "save_all_team_states", persist)

    response = client.patch(
        f"/local-test/groups/{group['id']}/review",
        json={"status": "approved", "reviewer": "api-cache-reviewer", "note": "ready"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "approved"
    assert events == ["persist"]
    assert local_simulation.get_state()["delivery_cache_jobs"] == []


def test_local_test_task_and_review_flow() -> None:
    client.post("/local-test/bootstrap")

    tasks_response = client.get("/local-test/tasks")
    assert tasks_response.status_code == 200
    tasks = tasks_response.json()["data"]["items"]
    status_response = client.get("/local-test/tasks/status")
    assert status_response.status_code == 200
    task_status = status_response.json()["data"]
    assert task_status["version"]
    assert task_status["total"] == len(tasks)
    assert "address_search_text" not in task_status
    task = next(item for item in tasks if item["can_claim"])
    assert "address" in task
    assert "address_search_text" in task
    assert isinstance(task["address_search_text"], str)
    assert "installer_distribution" in task
    assert isinstance(task["installer_distribution"], list)
    if task["installer_distribution"]:
        installer_item = task["installer_distribution"][0]
        assert {"installer", "group_count", "share"}.issubset(installer_item)
        assert installer_item["installer"]
        assert installer_item["group_count"] > 0
        assert 0 < installer_item["share"] <= 1

    claim_response = client.post(f"/local-test/tasks/{task['id']}/claim", json={"reviewer": "api-test"})
    assert claim_response.status_code == 200
    assert claim_response.json()["data"]["claimed_by"] == "api-test"

    groups_response = client.get(f"/local-test/tasks/{task['id']}/groups?limit=1")
    assert groups_response.status_code == 200
    group = groups_response.json()["data"]["items"][0]
    assert "photos" in group

    summary_response = client.get(f"/local-test/tasks/{task['id']}/groups?limit=1&summary=true")
    assert summary_response.status_code == 200
    summary_group = summary_response.json()["data"]["items"][0]
    assert "photos" not in summary_group
    assert "photo_count" in summary_group
    assert "reviewer" in summary_group

    review_response = client.patch(
        f"/local-test/groups/{group['id']}/review",
        json={"status": "approved", "reviewer": "api-test", "note": "api smoke"},
    )
    assert review_response.status_code == 200
    assert review_response.json()["data"]["status"] == "approved"

    photo_group = next(item for item in client.get(f"/local-test/tasks/{task['id']}/groups").json()["data"]["items"] if item["photos"])
    photo = photo_group["photos"][0]
    category_response = client.patch(
        f"/local-test/groups/{photo_group['id']}/photos/{photo['id']}/category",
        json={"category": "collector_barcode", "reviewer": "api-test"},
    )
    category_summary_response = client.patch(
        f"/local-test/groups/{photo_group['id']}/photos/{photo['id']}/category?include_group=true",
        json={"category": "module_meter", "reviewer": "api-test"},
    )
    delete_response = client.request(
        "DELETE",
        f"/local-test/groups/{photo_group['id']}/photos/{photo['id']}",
        json={"reviewer": "api-test"},
    )
    assert category_response.status_code == 200
    assert category_response.json()["data"]["category"] == "collector_barcode"
    assert category_summary_response.status_code == 200
    assert category_summary_response.json()["data"]["photo"]["category"] == "module_meter"
    assert category_summary_response.json()["data"]["group"]["id"] == photo_group["id"]
    assert "photos" not in category_summary_response.json()["data"]["group"]
    assert delete_response.status_code == 200
    assert delete_response.json()["data"]["deleted_photo"]["id"] == photo["id"]


def test_reviewer_claim_rejects_body_reviewer_spoofing() -> None:
    team_id = f"reviewer-spoof-{uuid4()}"
    team_headers = {"X-Team-Id": team_id}
    client.post("/local-test/bootstrap", headers=team_headers)
    token = security.create_access_token(
        {"sub": "reviewer-a", "username": "reviewer-a", "roles": ["reviewer"], "team_id": team_id}
    )
    headers = {**team_headers, "Authorization": f"bearer {token}"}
    task = next(item for item in client.get("/local-test/tasks", headers=headers).json()["data"]["items"] if item["can_claim"])

    response = client.post(
        f"/local-test/tasks/{task['id']}/claim",
        headers=headers,
        json={"reviewer": "reviewer-b"},
    )

    assert response.status_code == 403
    tasks_after = client.get("/local-test/tasks", headers=team_headers).json()["data"]["items"]
    assert next(item for item in tasks_after if item["id"] == task["id"]).get("claimed_by") in (None, "")


def test_construction_claim_rejects_body_actor_spoofing() -> None:
    team_id = f"constructor-spoof-{uuid4()}"
    admin_token = security.create_access_token(
        {"sub": "admin", "username": "admin", "roles": ["admin"], "team_id": team_id}
    )
    constructor_token = security.create_access_token(
        {"sub": "constructor-a", "username": "constructor-a", "roles": ["constructor"], "team_id": team_id}
    )
    admin_headers = {"X-Team-Id": team_id, "Authorization": f"bearer {admin_token}"}
    constructor_headers = {"X-Team-Id": team_id, "Authorization": f"bearer {constructor_token}"}
    client.post("/local-test/bootstrap", headers=admin_headers)
    task = client.get("/local-test/tasks", headers=admin_headers).json()["data"]["items"][0]
    opened = client.patch(
        f"/local-test/construction/tasks/{task['id']}/open",
        headers=admin_headers,
        json={"actor": "admin"},
    )
    assigned = client.patch(
        f"/local-test/construction/tasks/{task['id']}/assign",
        headers=admin_headers,
        json={"actor": "admin", "constructor": "constructor-b"},
    )
    assert opened.status_code == 200
    assert assigned.status_code == 200

    response = client.post(
        f"/local-test/construction/tasks/{task['id']}/claim",
        headers=constructor_headers,
        json={"actor": "constructor-b"},
    )

    assert response.status_code == 403


def test_construction_priority_route_enforces_admin_idempotence_and_forbidden_body_fields() -> None:
    team_id = f"priority-route-{uuid4()}"
    admin_token = security.create_access_token(
        {"sub": "admin-a", "username": "admin-a", "roles": ["admin"], "team_id": team_id}
    )
    reviewer_token = security.create_access_token(
        {"sub": "reviewer-a", "username": "reviewer-a", "roles": ["reviewer"], "team_id": team_id}
    )
    constructor_token = security.create_access_token(
        {"sub": "constructor-a", "username": "constructor-a", "roles": ["constructor"], "team_id": team_id}
    )
    admin_headers = {"X-Team-Id": team_id, "Authorization": f"bearer {admin_token}"}
    reviewer_headers = {"X-Team-Id": team_id, "Authorization": f"bearer {reviewer_token}"}
    constructor_headers = {"X-Team-Id": team_id, "Authorization": f"bearer {constructor_token}"}
    client.post("/local-test/bootstrap", headers=admin_headers)
    client.post("/local-test/scan/clear", headers=admin_headers)
    task = client.get("/local-test/tasks", headers=admin_headers).json()["data"]["items"][0]
    url = f"/local-test/construction/tasks/{task['id']}/priority"

    reviewer = client.patch(url, headers=reviewer_headers, json={"priority": True})
    constructor = client.patch(url, headers=constructor_headers, json={"priority": True})
    forbidden = client.patch(url, headers=admin_headers, json={"priority": True, "actor": "spoofed"})
    first = client.patch(url, headers=admin_headers, json={"priority": True})
    repeated = client.patch(url, headers=admin_headers, json={"priority": True})
    disabled = client.patch(url, headers=admin_headers, json={"priority": False})
    disabled_again = client.patch(url, headers=admin_headers, json={"priority": False})
    audits = client.get("/local-test/audit-log?limit=20", headers=admin_headers).json()["data"]["items"]

    assert reviewer.status_code == 403
    assert constructor.status_code == 403
    assert forbidden.status_code == 422
    assert first.status_code == 200
    assert repeated.status_code == 200
    assert disabled.status_code == 200
    assert disabled_again.status_code == 200
    assert first.json()["data"]["construction_priority"] is True
    assert disabled_again.json()["data"]["construction_priority"] is False
    assert [item["action"] for item in audits].count("construction_priority_updated") == 2


def test_construction_priority_import_template_preview_confirm_and_admin_guard() -> None:
    team_id = f"priority-import-{uuid4()}"
    admin_token = security.create_access_token({"sub": "admin-a", "username": "admin-a", "roles": ["admin"], "team_id": team_id})
    reviewer_token = security.create_access_token({"sub": "reviewer-a", "username": "reviewer-a", "roles": ["reviewer"], "team_id": team_id})
    admin_headers = {"X-Team-Id": team_id, "Authorization": f"bearer {admin_token}"}
    reviewer_headers = {"X-Team-Id": team_id, "Authorization": f"bearer {reviewer_token}"}
    client.post("/local-test/bootstrap", headers=admin_headers)
    client.post("/local-test/scan/clear", headers=admin_headers)
    task = client.get("/local-test/tasks", headers=admin_headers).json()["data"]["items"][0]
    workbook = build_api_workbook([["终端号", "优先施工"], [task["terminal"], "是"], ["unknown-terminal", "否"]])
    template = client.get("/local-test/construction/priority-template", headers=admin_headers)
    forbidden = client.post("/local-test/construction/priority-import", headers=reviewer_headers, files={"file": ("priority.xlsx", workbook)})
    preview = client.post("/local-test/construction/priority-import?confirm=false", headers=admin_headers, files={"file": ("priority.xlsx", workbook)})
    confirmed = client.post("/local-test/construction/priority-import?confirm=true", headers=admin_headers, files={"file": ("priority.xlsx", workbook)})

    assert template.status_code == 200
    assert "filename*=" in template.headers["content-disposition"]
    assert forbidden.status_code == 403
    assert preview.status_code == 200
    assert preview.json()["data"]["counts"]["unknown"] == 1
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["confirmed"] is True


def test_construction_priority_import_isolated_classified_and_rejects_invalid_files_without_writes() -> None:
    team_a = f"priority-import-review-a-{uuid4()}"
    team_b = f"priority-import-review-b-{uuid4()}"
    token_a = security.create_access_token({"sub": "admin-a", "username": "admin-a", "roles": ["admin"], "team_id": team_a})
    token_b = security.create_access_token({"sub": "admin-b", "username": "admin-b", "roles": ["admin"], "team_id": team_b})
    headers_a = {"X-Team-Id": team_a, "Authorization": f"bearer {token_a}"}
    headers_b = {"X-Team-Id": team_b, "Authorization": f"bearer {token_b}"}
    for headers in (headers_a, headers_b):
        client.post("/local-test/bootstrap", headers=headers)
        client.post("/local-test/scan/clear", headers=headers)
    task_a = client.get("/local-test/tasks", headers=headers_a).json()["data"]["items"][0]
    task_b = client.get("/local-test/tasks", headers=headers_b).json()["data"]["items"][0]
    assert task_a["terminal"] == task_b["terminal"]

    enabled = client.post(
        "/local-test/construction/priority-import?confirm=true",
        headers=headers_a,
        files={"file": ("priority.xlsx", build_api_workbook([["终端号", "优先施工"], [task_a["terminal"], "是"]]))},
    )
    task_b_after = client.get("/local-test/tasks", headers=headers_b).json()["data"]["items"][0]
    assert enabled.status_code == 200
    assert task_b_after["construction_priority"] is False

    unchanged = client.post(
        "/local-test/construction/priority-import?confirm=true",
        headers=headers_a,
        files={"file": ("priority.xlsx", build_api_workbook([["终端号", "优先施工"], [task_a["terminal"], "是"]]))},
    )
    assert unchanged.status_code == 200
    assert unchanged.json()["data"]["counts"]["unchanged"] == 1

    team_token = local_simulation.set_current_team(team_a)
    try:
        state = local_simulation.get_state()
        for group in state["groups"]:
            if int(group.get("task_id") or 0) == int(task_a["id"]):
                group["photo_count"] = 1
                group["status"] = "unreviewed"
    finally:
        local_simulation.reset_current_team(team_token)
    completed = client.post(
        "/local-test/construction/priority-import?confirm=true",
        headers=headers_a,
        files={"file": ("priority.xlsx", build_api_workbook([["终端号", "优先施工"], [task_a["terminal"], "否"]]))},
    )
    audits_before_invalid = client.get("/local-test/audit-log?limit=100", headers=headers_a).json()["data"]["items"]
    conflict = client.post(
        "/local-test/construction/priority-import?confirm=true",
        headers=headers_a,
        files={"file": ("priority.xlsx", build_api_workbook([["终端号", "优先施工"], [task_a["terminal"], "是"], [task_a["terminal"], "否"]]))},
    )
    malformed = client.post(
        "/local-test/construction/priority-import?confirm=true",
        headers=headers_a,
        files={"file": ("priority.xlsx", build_api_workbook([["终端号", "优先施工"], ["", "是"]]))},
    )
    non_xlsx = client.post(
        "/local-test/construction/priority-import",
        headers=headers_a,
        files={"file": ("priority.csv", b"terminal,priority")},
    )
    oversized = client.post(
        "/local-test/construction/priority-import",
        headers=headers_a,
        files={"file": ("priority.xlsx", b"x" * (2 * 1024 * 1024 + 1))},
    )
    audits_after_invalid = client.get("/local-test/audit-log?limit=100", headers=headers_a).json()["data"]["items"]

    assert completed.status_code == 200
    assert completed.json()["data"]["counts"]["completed"] == 1
    assert conflict.status_code == 422
    assert malformed.status_code == 422
    assert non_xlsx.status_code == 422
    assert oversized.status_code == 422
    assert audits_after_invalid == audits_before_invalid
    actions = [audit["action"] for audit in audits_after_invalid]
    assert actions.count("construction_priority_updated") == 1
    assert actions.count("construction_priority_imported") == 3


def test_construction_priority_route_is_team_isolated_and_rejects_completed_or_missing_tasks() -> None:
    team_a = f"priority-isolation-a-{uuid4()}"
    team_b = f"priority-isolation-b-{uuid4()}"
    admin_a = security.create_access_token(
        {"sub": "admin-a", "username": "admin-a", "roles": ["admin"], "team_id": team_a}
    )
    admin_b = security.create_access_token(
        {"sub": "admin-b", "username": "admin-b", "roles": ["admin"], "team_id": team_b}
    )
    headers_a = {"X-Team-Id": team_a, "Authorization": f"bearer {admin_a}"}
    headers_b = {"X-Team-Id": team_b, "Authorization": f"bearer {admin_b}"}
    client.post("/local-test/bootstrap", headers=headers_a)
    client.post("/local-test/bootstrap", headers=headers_b)
    client.post("/local-test/scan/clear", headers=headers_a)
    client.post("/local-test/scan/clear", headers=headers_b)
    task_a = client.get("/local-test/tasks", headers=headers_a).json()["data"]["items"][0]
    task_b = client.get("/local-test/tasks", headers=headers_b).json()["data"]["items"][0]
    assert task_a["terminal"] == task_b["terminal"]

    enabled_a = client.patch(
        f"/local-test/construction/tasks/{task_a['id']}/priority",
        headers=headers_a,
        json={"priority": True},
    )
    task_b_after = next(
        item
        for item in client.get("/local-test/tasks", headers=headers_b).json()["data"]["items"]
        if item["id"] == task_b["id"]
    )
    missing = client.patch(
        "/local-test/construction/tasks/999999/priority",
        headers=headers_b,
        json={"priority": False},
    )

    team_token = local_simulation.set_current_team(team_a)
    try:
        state = local_simulation.get_state()
        for group in state["groups"]:
            if group["task_id"] == task_a["id"]:
                group["photo_count"] = max(int(group.get("photo_count") or 0), 1)
                group["status"] = "pending"
        local_simulation.refresh_summary()
    finally:
        local_simulation.reset_current_team(team_token)
    completed = client.patch(
        f"/local-test/construction/tasks/{task_a['id']}/priority",
        headers=headers_a,
        json={"priority": True},
    )

    assert enabled_a.status_code == 200
    assert task_b_after["construction_priority"] is False
    assert missing.status_code == 404
    assert completed.status_code == 400


def test_json_final_construction_upload_auto_clears_priority_and_records_audit() -> None:
    team_id = f"priority-json-upload-{uuid4()}"
    admin_token = security.create_access_token(
        {"sub": "admin-a", "username": "admin-a", "roles": ["admin"], "team_id": team_id}
    )
    admin_headers = {"X-Team-Id": team_id, "Authorization": f"bearer {admin_token}"}
    client.post("/local-test/bootstrap", headers=admin_headers)
    client.post("/local-test/scan/clear", headers=admin_headers)
    task = client.get("/local-test/tasks", headers=admin_headers).json()["data"]["items"][0]

    team_token = local_simulation.set_current_team(team_id)
    try:
        state = local_simulation.get_state()
        final_group = next(group for group in state["groups"] if group["task_id"] == task["id"])
        state["groups"] = [
            group
            for group in state["groups"]
            if group["task_id"] != task["id"] or group["id"] == final_group["id"]
        ]
        live_task = next(item for item in state["tasks"] if item["id"] == task["id"])
        live_task["construction_enabled"] = True
        live_task["construction_claimed_by"] = "constructor-a"
        local_simulation.refresh_summary()
    finally:
        local_simulation.reset_current_team(team_token)

    enabled = client.patch(
        f"/local-test/construction/tasks/{task['id']}/priority",
        headers=admin_headers,
        json={"priority": True},
    )

    team_token = local_simulation.set_current_team(team_id)
    try:
        entered = local_simulation.claim_construction_task(task["id"], "constructor-a")
        released = local_simulation.release_construction_task(task["id"], "constructor-a")
        reassigned = local_simulation.assign_construction_task(task["id"], "admin-a", "constructor-a")
        assert entered["construction_priority"] is True
        assert released["construction_priority"] is True
        assert reassigned["construction_priority"] is True
        result = local_simulation.upload_construction_group_batch(
            final_group["id"],
            actor="constructor-a",
            client_batch_id="priority-json-final",
            collector="collector-a",
            module_asset_no="module-a",
            photos=[
                {"url": f"https://example.test/{slot}.jpg", "sha256": f"{index:064x}", "client_photo_id": slot, "slot": slot}
                for index, slot in enumerate(("before_box", "after_box", "module_meter", "collector_barcode"), start=1)
            ],
        )
        completed_task = dict(result["task"])
        reset = local_simulation.reset_group_to_unconstructed(
            final_group["id"],
            actor="admin-a",
            force=True,
        )
        actions = [item["action"] for item in local_simulation.list_audit_events(limit=50)["items"]]
    finally:
        local_simulation.reset_current_team(team_token)

    assert enabled.status_code == 200
    assert completed_task["construction_available"] is False
    assert completed_task["construction_priority"] is False
    assert reset["group"]["photo_count"] == 0
    assert result["task"]["construction_priority"] is False
    assert "construction_priority_auto_cleared" in actions


def test_miniprogram_upload_refresh_failure_rolls_back_json_state(monkeypatch) -> None:
    team_id = f"priority-miniprogram-rollback-{uuid4()}"
    admin_token = security.create_access_token(
        {"sub": "admin-a", "username": "admin-a", "roles": ["admin"], "team_id": team_id}
    )
    constructor_token = security.create_access_token(
        {"sub": "constructor-a", "username": "constructor-a", "roles": ["constructor"], "team_id": team_id}
    )
    admin_headers = {"X-Team-Id": team_id, "Authorization": f"bearer {admin_token}"}
    constructor_headers = {"X-Team-Id": team_id, "Authorization": f"bearer {constructor_token}"}
    client.post("/local-test/bootstrap", headers=admin_headers)
    client.post("/local-test/scan/clear", headers=admin_headers)
    task = client.get("/local-test/tasks", headers=admin_headers).json()["data"]["items"][0]

    team_token = local_simulation.set_current_team(team_id)
    try:
        state = local_simulation.get_state()
        group = next(item for item in state["groups"] if item["task_id"] == task["id"])
        live_task = next(item for item in state["tasks"] if item["id"] == task["id"])
        live_task["construction_enabled"] = True
        live_task["construction_claimed_by"] = "constructor-a"
        local_simulation.refresh_summary()
        before_group = deepcopy(group)
        before_task = deepcopy(live_task)
        before_audits = deepcopy(state["audit_events"])
    finally:
        local_simulation.reset_current_team(team_token)

    enabled = client.patch(
        f"/local-test/construction/tasks/{task['id']}/priority",
        headers=admin_headers,
        json={"priority": True},
    )
    assert enabled.status_code == 200
    team_token = local_simulation.set_current_team(team_id)
    try:
        priority_task = deepcopy(next(item for item in local_simulation.get_state()["tasks"] if item["id"] == task["id"]))
        before_audits = deepcopy(local_simulation.get_state()["audit_events"])
    finally:
        local_simulation.reset_current_team(team_token)
    monkeypatch.setattr(local_simulation, "refresh_summary", lambda: (_ for _ in ()).throw(RuntimeError("refresh failed")))
    monkeypatch.setattr(local_simulation, "validate_construction_upload_required_slots", lambda _group, _photos: None)

    data = {
        "client_batch_id": "miniprogram-rollback",
        "collector": "collector-a",
        "module_asset_no": "module-a",
    }
    with pytest.raises(RuntimeError, match="refresh failed"):
        client.post(
            f"/miniprogram/groups/{group['id']}/upload-batch",
            headers=constructor_headers,
            data=data,
            files=[("files", ("photo.jpg", tiny_jpeg_bytes(), "image/jpeg"))],
        )

    team_token = local_simulation.set_current_team(team_id)
    try:
        state = local_simulation.get_state()
        after_group = next(item for item in state["groups"] if item["id"] == group["id"])
        after_task = next(item for item in state["tasks"] if item["id"] == task["id"])
        after_audits = state["audit_events"]
    finally:
        local_simulation.reset_current_team(team_token)

    assert after_group == before_group
    assert after_task["construction_priority"] is True
    assert after_task["construction_priority_updated_by"] == priority_task["construction_priority_updated_by"]
    assert after_audits == before_audits


def test_photo_barcode_rescan_route_only_requeues_group_without_ocr(monkeypatch) -> None:
    headers = {"X-Team-Id": "rescan-route-test"}
    client.post("/local-test/bootstrap", headers=headers)
    task = next(item for item in client.get("/local-test/tasks", headers=headers).json()["data"]["items"] if item["can_claim"])
    claim_response = client.post(
        f"/local-test/tasks/{task['id']}/claim",
        headers=headers,
        json={"reviewer": "api-test"},
    )
    assert claim_response.status_code == 200
    photo_group = next(
        item
        for item in client.get(f"/local-test/tasks/{task['id']}/groups", headers=headers).json()["data"]["items"]
        if item["photos"]
    )
    photo = photo_group["photos"][0]

    monkeypatch.setattr(
        local_simulation.photo_barcode_check,
        "check_photo_barcode",
        lambda *_args, **_kwargs: pytest.fail("rescan request must not execute OCR or barcode recognition"),
    )

    response = client.post(
        f"/local-test/groups/{photo_group['id']}/photos/{photo['id']}/barcode-rescan?include_group=true",
        headers=headers,
        json={"reviewer": "api-test", "category": "module_meter"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["photo"]["category"] == photo["category"]
    assert data["group"]["id"] == photo_group["id"]
    audits = client.get("/local-test/audit-log?limit=5", headers=headers).json()["data"]["items"]
    assert any(item["action"] == "group_barcode_rescan_requested" for item in audits)

    spoof_token = security.create_access_token(
        {"username": "intruder", "name": "Intruder", "roles": ["reviewer"], "team_id": "rescan-route-test"}
    )
    spoofed = client.post(
        f"/local-test/groups/{photo_group['id']}/photos/{photo['id']}/barcode-rescan?include_group=true",
        headers={**headers, "Authorization": f"bearer {spoof_token}"},
        json={"reviewer": "api-test", "category": "module_meter"},
    )
    assert spoofed.status_code == 400
    assert "claimed by the current reviewer" in spoofed.json()["detail"]


def test_group_barcode_manual_confirm_route_marks_summary_and_audits() -> None:
    team_id = f"manual-confirm-route-test-{uuid4()}"
    headers = {"X-Team-Id": team_id}
    client.post("/local-test/bootstrap", headers=headers)
    token = local_simulation.set_current_team(team_id)
    try:
        state = local_simulation.get_state()
        task = next(item for item in state["tasks"] if item["can_claim"])
        group = next(item for item in state["groups"] if item["task_id"] == task["id"])
        group.update(
            {
                "meter_no": "110000288056",
                "collector": "COLLECTOR001",
                "module_asset_no": "MOD001",
                "photo_count": 4,
                "barcode_verification": {
                    "status": "unreadable",
                    "meter_matched": False,
                    "module_matched": False,
                    "collector_matched": False,
                    "recognition_source": "machine_barcode",
                },
                "photos": [
                    {"id": "manual-confirm-p1", "category": "before_box", "archive_status": "archived", "sha256": "a" * 64},
                    {"id": "manual-confirm-p2", "category": "collector_barcode", "archive_status": "archived", "sha256": "b" * 64},
                    {"id": "manual-confirm-p3", "category": "module_meter", "archive_status": "archived", "sha256": "c" * 64},
                    {"id": "manual-confirm-p4", "category": "after_box", "archive_status": "archived", "sha256": "d" * 64},
                ],
            }
        )
        local_simulation.refresh_summary()
    finally:
        local_simulation.reset_current_team(token)

    cached_summary_response = client.get("/local-test/summary", headers=headers)
    assert cached_summary_response.status_code == 200
    cached_summary = cached_summary_response.json()["data"]["summary"]
    assert cached_summary["group_barcode_accuracy_unreadable"] >= 1

    claim_response = client.post(f"/local-test/tasks/{task['id']}/claim", json={"reviewer": "api-test"}, headers=headers)
    assert claim_response.status_code == 200

    response = client.post(
        f"/local-test/groups/{group['id']}/barcode-manual-confirm",
        json={
            "actor": "api-test",
            "meter_no": "110000288056",
            "collector": "COLLECTOR001",
            "module_asset_no": "MOD001",
            "reason": "现场标签清晰，机器读取失败",
            "photo_ids": ["manual-confirm-p1", "manual-confirm-p2"],
        },
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()["data"]

    assert payload["group"]["group_barcode_manual_confirmed"] is True
    assert payload["group"]["group_barcode_passed_count"] == 3
    assert payload["group"]["group_barcode_check_status"] == "matched"

    summary_response = client.get("/local-test/summary", headers=headers)
    assert summary_response.status_code == 200
    summary = summary_response.json()["data"]["summary"]
    assert summary["group_barcode_accuracy_passed"] >= 1
    assert summary["group_barcode_accuracy_unreadable"] == cached_summary["group_barcode_accuracy_unreadable"] - 1

    audit_response = client.get("/local-test/audit-log?limit=1", headers=headers)
    assert audit_response.status_code == 200
    assert audit_response.json()["data"]["items"][0]["action"] == "group_barcode_manual_confirmed"


def test_local_test_team_header_isolates_review_state() -> None:
    team_a = {"X-Team-Id": "team-a"}
    team_b = {"X-Team-Id": "team-b"}

    client.post("/local-test/bootstrap", headers=team_a)
    client.post("/local-test/bootstrap", headers=team_b)
    task_a = next(item for item in client.get("/local-test/tasks", headers=team_a).json()["data"]["items"] if item["can_claim"])
    task_b = next(item for item in client.get("/local-test/tasks", headers=team_b).json()["data"]["items"] if item["id"] == task_a["id"])

    claim_a = client.post(f"/local-test/tasks/{task_a['id']}/claim", headers=team_a, json={"reviewer": "alice"})
    after_a = client.get("/local-test/tasks", headers=team_a).json()["data"]["items"]
    after_b = client.get("/local-test/tasks", headers=team_b).json()["data"]["items"]
    teams = client.get("/local-test/teams", headers=team_a).json()["data"]["items"]

    assert claim_a.status_code == 200
    assert next(item for item in after_a if item["id"] == task_a["id"])["claimed_by"] == "alice"
    assert task_b["claimed_by"] is None
    assert next(item for item in after_b if item["id"] == task_a["id"])["claimed_by"] is None
    assert {"team-a", "team-b"}.issubset({item["team_id"] for item in teams})


def test_async_scan_template_import_job_completes() -> None:
    team = {"X-Team-Id": f"async-import-team-{uuid4().hex}"}
    catalog = build_api_workbook(
        [
            ["terminal", "meter_no", "address"],
            ["T-ASYNC", "ZZ0000001001", "Async road"],
        ]
    )
    scan = build_api_workbook(
        [
            ["barcode", "meter_match_key", "terminal", "collector", "module_asset_no", "photo_urls"],
            ["scan-1", "0000001001", "T-ASYNC", "collector", "asset-1", "https://example.invalid/1.jpg"],
            ["scan-2", "0000001001", "T-ASYNC", "collector", "asset-2", "https://example.invalid/2.jpg"],
        ]
    )

    catalog_response = client.post(
        "/local-test/catalog/total/import-xlsx",
        headers=team,
        files={"file": ("catalog.xlsx", catalog, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    job_response = client.post(
        "/local-test/scan/import-template-xlsx/jobs",
        headers=team,
        files={"file": ("scan.xlsx", scan, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert catalog_response.status_code == 200
    assert job_response.status_code == 200
    job_id = job_response.json()["data"]["job_id"]
    payload = {}
    for _ in range(50):
        poll = client.get(f"/local-test/scan/import-template-xlsx/jobs/{job_id}", headers=team)
        assert poll.status_code == 200
        payload = poll.json()["data"]
        if payload["status"] == "complete":
            break
        time.sleep(0.05)

    assert payload["status"] == "complete"
    assert payload["result"]["template_rows"] == 2
    assert payload["result"]["applied_records"] == 2
    assert payload["progress"]["phase"] == "complete"


def test_task_hall_page_is_available() -> None:
    response = client.get("/task-hall", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/global-search"

    embedded = client.get("/task-hall?embedded=1", follow_redirects=False)
    assert embedded.status_code == 307
    assert embedded.headers["location"] == "/global-search"

def test_app_shell_page_is_available() -> None:
    assert_vue_shell_response(client.get("/app"))

def test_claim_tasks_page_exposes_admin_release_all_control() -> None:
    assert_vue_shell_response(client.get("/claim-tasks"))
    assert_vue_shell_response(client.get("/claim-tasks?embedded=1"))

def test_admin_can_release_all_claimed_tasks() -> None:
    admin_login = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    constructor_login = client.post("/auth/login", json={"username": "constructor", "password": "construct123"})
    admin_headers = {"Authorization": f"bearer {admin_login.json()['data']['access_token']}"}
    constructor_headers = {"Authorization": f"bearer {constructor_login.json()['data']['access_token']}"}

    client.post("/local-test/bootstrap", headers=admin_headers)
    tasks = client.get("/local-test/tasks", headers=admin_headers).json()["data"]["items"]
    claimable = [task for task in tasks if task["can_claim"]][:2]
    assert claimable
    for index, task in enumerate(claimable):
        claim = client.post(
            f"/local-test/tasks/{task['id']}/claim",
            headers=admin_headers,
            json={"reviewer": f"reviewer-{index}"},
        )
        assert claim.status_code == 200

    constructor_denied = client.post(
        "/local-test/tasks/release-all",
        headers=constructor_headers,
        json={"reviewer": "constructor"},
    )
    released = client.post(
        "/local-test/tasks/release-all",
        headers=admin_headers,
        json={"reviewer": "admin"},
    )

    assert constructor_denied.status_code == 403
    assert released.status_code == 200
    assert released.json()["data"]["released"] == len(claimable)
    after = client.get("/local-test/tasks", headers=admin_headers).json()["data"]["items"]
    claimed_ids = {task["id"] for task in claimable}
    assert not any(task.get("claimed_by") for task in after if task["id"] in claimed_ids)


def test_construction_task_open_claim_and_upload_batch() -> None:
    admin_login = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    constructor_login = client.post("/auth/login", json={"username": "constructor", "password": "construct123"})
    constructor_name = constructor_login.json()["data"]["user"]["name"]
    admin_headers = {"Authorization": f"bearer {admin_login.json()['data']['access_token']}"}
    constructor_headers = {"Authorization": f"bearer {constructor_login.json()['data']['access_token']}"}

    client.post("/local-test/bootstrap", headers=admin_headers)
    client.post("/local-test/scan/clear", headers=admin_headers)
    task = client.get("/local-test/tasks", headers=admin_headers).json()["data"]["items"][0]
    hidden = client.get(
        "/local-test/construction/tasks?actor=constructor",
        headers=constructor_headers,
    ).json()["data"]["items"]
    denied_claim = client.post(
        f"/local-test/construction/tasks/{task['id']}/claim",
        headers=constructor_headers,
        json={"actor": "constructor"},
    )
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
    claimed = client.post(
        f"/local-test/construction/tasks/{task['id']}/claim",
        headers=constructor_headers,
        json={"actor": "constructor"},
    )
    groups = client.get(
        f"/local-test/construction/tasks/{task['id']}/groups?limit=1&summary=true",
        headers=constructor_headers,
    ).json()["data"]["items"]
    group = groups[0]
    missing_module_upload = client.post(
        f"/local-test/construction/groups/{group['id']}/upload-batch",
        headers=constructor_headers,
        data={
            "actor": "constructor",
            "client_batch_id": "batch-api-missing-module",
            "client_completed_at": "bad-client-time",
            "collector": "collector-api",
            "module_asset_no": "module-api",
            "photo_slots": ["before_box", "after_box"],
            "client_photo_ids": ["photo-a", "photo-b"],
        },
        files=[
            ("files", ("before.jpg", tiny_jpeg_bytes("red"), "image/jpeg")),
            ("files", ("after.jpg", tiny_jpeg_bytes("blue"), "image/jpeg")),
        ],
    )
    uploaded = client.post(
        f"/local-test/construction/groups/{group['id']}/upload-batch",
        headers=constructor_headers,
        data={
            "actor": "constructor",
            "client_batch_id": "batch-api-1",
            "client_completed_at": "bad-client-time",
            "collector": "collector-api",
            "module_asset_no": "module-api",
            "photo_slots": ["before_box", "module_meter", "after_box"],
            "client_photo_ids": ["photo-a", "photo-b", "photo-c"],
        },
        files=[
            ("files", ("before.jpg", tiny_jpeg_bytes("red"), "image/jpeg")),
            ("files", ("meter.jpg", tiny_jpeg_bytes("green"), "image/jpeg")),
            ("files", ("after.jpg", tiny_jpeg_bytes("blue"), "image/jpeg")),
        ],
    )

    assert hidden == []
    assert denied_claim.status_code == 400
    assert opened.status_code == 200
    assert opened.json()["data"]["construction_enabled"] is True
    assert assigned.status_code == 200
    assert assigned.json()["data"]["construction_claimed_by"] == "constructor"
    assert claimed.status_code == 200
    assert claimed.json()["data"]["construction_claimed_by"] == "constructor"
    assert missing_module_upload.status_code == 400
    assert "模块与电能表" in missing_module_upload.json()["detail"]
    assert uploaded.status_code == 200
    payload = uploaded.json()["data"]
    assert payload["added"] == 3
    assert payload["skipped_duplicates"] == 0
    assert payload["group"]["status"] == "exception"
    assert payload["group"]["exception_note"] == "缺采集器照片"
    assert "missing_collector_photo" in payload["group"]["exception_reasons"]
    assert payload["group"]["photos"][0]["upload_source"] == "construction-mobile"
    assert payload["group"]["photos"][0]["construction_slot"] == "before_box"
    assert payload["group"]["photos"][0]["category"] == "before_box"
    assert payload["group"]["photos"][0]["creator"] == constructor_name
    assert payload["group"]["photos"][0]["creator"] != "constructor"
    assert payload["group"]["photos"][0]["sha256"]
    assert payload["group"]["photos"][0]["storage_type"] == "local_upload"
    assert payload["group"]["photos"][0]["storage_key"].startswith("construction/")
    assert payload["uploaded_urls"][0].startswith("/static/uploads/construction/")

    after_first_upload = client.get(
        f"/local-test/construction/tasks/{task['id']}/groups?limit=1000&summary=true",
        headers=constructor_headers,
    ).json()["data"]["items"]
    assert group["id"] not in {item["id"] for item in after_first_upload}

    collector_upload = client.post(
        f"/local-test/construction/groups/{group['id']}/upload-batch",
        headers=constructor_headers,
        data={
            "actor": "constructor",
            "client_batch_id": "batch-api-collector-fix",
            "client_completed_at": "2026-06-08T09:10:00",
            "collector": "collector-api",
            "module_asset_no": "module-api",
            "photo_slots": ["collector_barcode"],
            "client_photo_ids": ["photo-collector"],
        },
        files=[
            ("files", ("collector.jpg", tiny_jpeg_bytes("yellow"), "image/jpeg")),
        ],
    )
    assert collector_upload.status_code == 200
    collector_payload = collector_upload.json()["data"]
    assert collector_payload["group"]["status"] == "pending"
    assert collector_payload["group"]["exception_note"] == ""
    assert "missing_collector_photo" not in collector_payload["group"]["exception_reasons"]

    second_group = after_first_upload[0]
    complete_upload = client.post(
        f"/local-test/construction/groups/{second_group['id']}/upload-batch",
        headers=constructor_headers,
        data={
            "actor": "constructor",
            "client_batch_id": "batch-api-2",
            "client_completed_at": "2026-06-08T09:30:00",
            "collector": "collector-api-2",
            "module_asset_no": "module-api-2",
            "photo_slots": ["before_box", "after_box", "module_meter", "collector_barcode"],
            "client_photo_ids": ["photo-1", "photo-2", "photo-3", "photo-4"],
        },
        files=[
            ("files", ("before.jpg", tiny_jpeg_bytes("red"), "image/jpeg")),
            ("files", ("after.jpg", tiny_jpeg_bytes("blue"), "image/jpeg")),
            ("files", ("meter.jpg", tiny_jpeg_bytes("green"), "image/jpeg")),
            ("files", ("collector.jpg", tiny_jpeg_bytes("yellow"), "image/jpeg")),
        ],
    )
    assert complete_upload.status_code == 200
    complete_payload = complete_upload.json()["data"]
    assert complete_payload["added"] == 4
    assert complete_payload["group"]["status"] == "pending"
    workload = client.get(f"/local-test/installers/{constructor_name}/daily-workload", headers=admin_headers)
    assert workload.status_code == 200
    client_day = next(item for item in workload.json()["data"]["items"] if item["date"] == "2026-06-08")
    assert client_day["group_count"] == 1
    assert client_day["completion_count"] == 1
    assert client_day["start_time"] == "09:30"
    assert client_day["end_time"] == "09:30"

    client.post(
        f"/local-test/tasks/{task['id']}/claim",
        headers=admin_headers,
        json={"reviewer": "admin"},
    )
    review_groups = client.get(
        f"/local-test/tasks/{task['id']}/groups?limit=1000&scan_only=false&summary=true",
        headers=admin_headers,
    ).json()["data"]["items"]
    assert second_group["id"] in {item["id"] for item in review_groups}
    review_detail = client.get(f"/local-test/groups/{second_group['id']}", headers=admin_headers).json()["data"]
    assert len(review_detail["photos"]) == 4
    assert all(photo["image_url"].startswith("/static/uploads/construction/") for photo in review_detail["photos"])
    assert all(photo["download_status"] == "downloaded" for photo in review_detail["photos"])
    assert {photo["category"] for photo in review_detail["photos"]} == {
        "before_box",
        "collector_barcode",
        "module_meter",
        "after_box",
    }

    repaired_detail = client.get(f"/local-test/groups/{group['id']}", headers=admin_headers).json()["data"]
    collector_photo = next(photo for photo in repaired_detail["photos"] if photo["construction_slot"] == "collector_barcode")
    deleted_collector = client.request(
        "DELETE",
        f"/local-test/groups/{group['id']}/photos/{collector_photo['id']}",
        headers=admin_headers,
        json={"reviewer": "admin"},
    )
    assert deleted_collector.status_code == 200

    deleted_group = deleted_collector.json()["data"]["group"]
    assert deleted_group["status"] == "exception"
    assert deleted_group["exception_note"] == "缺采集器照片"
    assert "missing_collector_photo" in deleted_group["exception_reasons"]
    exception_groups = client.get("/local-test/exception-groups", headers=admin_headers).json()["data"]["items"]
    assert group["id"] in {item["id"] for item in exception_groups}

    released = client.post(
        f"/local-test/construction/tasks/{task['id']}/release",
        headers=constructor_headers,
        json={"actor": "constructor"},
    )
    assert released.status_code == 200
    assert released.json()["data"]["construction_claimed_by"] in (None, "")
    after_release = client.get(
        "/local-test/construction/tasks?actor=constructor",
        headers=constructor_headers,
    ).json()["data"]["items"]
    assert task["id"] not in {item["id"] for item in after_release}


def test_construction_online_events_feed_fused_installer_workload() -> None:
    admin_login = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    admin_headers = {"Authorization": f"bearer {admin_login.json()['data']['access_token']}"}
    client.post(
        "/auth/users",
        headers=admin_headers,
        json={
            "username": "constructor",
            "password": "construct123",
            "name": "施工员",
            "roles": ["constructor"],
            "team_id": "demo-team",
            "status": "active",
        },
    )
    constructor_login = client.post("/auth/login", json={"username": "constructor", "password": "construct123"})
    constructor_name = constructor_login.json()["data"]["user"]["name"]
    constructor_headers = {"Authorization": f"bearer {constructor_login.json()['data']['access_token']}"}

    client.post("/local-test/bootstrap", headers=admin_headers)
    client.post("/local-test/scan/clear", headers=admin_headers)
    task = client.get("/local-test/tasks", headers=admin_headers).json()["data"]["items"][0]
    client.patch(
        f"/local-test/construction/tasks/{task['id']}/assign",
        headers=admin_headers,
        json={"actor": "admin", "constructor": "constructor"},
    )
    groups = client.get(
        f"/local-test/construction/tasks/{task['id']}/groups?limit=1000&summary=true",
        headers=constructor_headers,
    ).json()["data"]["items"]

    current = datetime(2026, 6, 8, 9, 0)
    spoofed = client.post(
        "/local-test/construction/heartbeat",
        headers=constructor_headers,
        json={"actor": "other-installer", "task_id": task["id"], "occurred_at": current.isoformat()},
    )
    assert spoofed.status_code == 403
    while current <= datetime(2026, 6, 8, 11, 0):
        heartbeat = client.post(
            "/local-test/construction/heartbeat",
            headers=constructor_headers,
            json={"actor": "constructor", "task_id": task["id"], "occurred_at": current.isoformat()},
        )
        assert heartbeat.status_code == 200
        current = current + local_simulation.timedelta(minutes=5)

    draft_done = client.post(
        "/local-test/construction/non-idle-events",
        headers=constructor_headers,
        json={
            "event_type": "group_draft_completed",
            "actor": "constructor",
            "task_id": task["id"],
            "group_id": groups[0]["id"],
            "client_batch_id": "deleted-draft",
            "occurred_at": "2026-06-08T09:20:00",
        },
    )
    draft_deleted = client.post(
        "/local-test/construction/non-idle-events",
        headers=constructor_headers,
        json={
            "event_type": "group_draft_deleted",
            "actor": "constructor",
            "task_id": task["id"],
            "group_id": groups[0]["id"],
            "client_batch_id": "deleted-draft",
            "occurred_at": "2026-06-08T09:25:00",
        },
    )
    assert draft_done.status_code == 200
    assert draft_deleted.status_code == 200

    for index, completed_at in enumerate(("2026-06-08T09:30:00", "2026-06-08T10:10:00")):
        upload = client.post(
            f"/local-test/construction/groups/{groups[index]['id']}/upload-batch",
            headers=constructor_headers,
            data={
                "actor": "constructor",
                "client_batch_id": f"online-kpi-batch-{uuid4().hex}-{index}",
                "client_completed_at": completed_at,
                "collector": f"collector-{index}",
                "module_asset_no": f"module-{index}",
                "photo_slots": ["before_box", "after_box", "module_meter", "collector_barcode"],
                "client_photo_ids": [f"before-{index}", f"after-{index}", f"meter-{index}", f"collector-{index}"],
            },
            files=[
                ("files", ("before.jpg", tiny_jpeg_bytes((255, index, 0)), "image/jpeg")),
                ("files", ("after.jpg", tiny_jpeg_bytes((0, index, 255)), "image/jpeg")),
                ("files", ("meter.jpg", tiny_jpeg_bytes((0, 255, index)), "image/jpeg")),
                ("files", ("collector.jpg", tiny_jpeg_bytes((255, 255, index)), "image/jpeg")),
            ],
        )
        assert upload.status_code == 200

    workload = client.get(f"/local-test/installers/{constructor_name}/daily-workload", headers=admin_headers)

    assert workload.status_code == 200
    item = next(row for row in workload.json()["data"]["items"] if row["date"] == "2026-06-08")
    assert item["attendance_window_minutes"] == 480
    assert item["countable_online_minutes"] == 120
    assert item["base_online_coefficient"] == 1.06
    assert item["idle_penalty_coefficient"] == 0
    assert item["final_online_coefficient"] == 1.06
    assert item["pending_non_idle_count"] == 0
    assert item["confirmed_non_idle_count"] == 2
    assert item["fused_work_duration_minutes"] >= item["work_duration_minutes"]
    assert item["fused_work_duration_minutes"] <= item["attendance_window_minutes"]
    assert item["fused_efficiency_duration_minutes"] <= item["attendance_window_minutes"]
    assert item["fused_efficiency_duration_minutes"] <= item["fused_work_duration_minutes"]


def test_construction_upload_rejects_placeholder_group_id_before_file_save() -> None:
    admin_login = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    constructor_login = client.post("/auth/login", json={"username": "constructor", "password": "construct123"})
    admin_headers = {"Authorization": f"bearer {admin_login.json()['data']['access_token']}"}
    constructor_headers = {"Authorization": f"bearer {constructor_login.json()['data']['access_token']}"}

    client.post("/local-test/bootstrap", headers=admin_headers)
    task = client.get("/local-test/tasks", headers=admin_headers).json()["data"]["items"][0]
    client.patch(
        f"/local-test/construction/tasks/{task['id']}/open",
        headers=admin_headers,
        json={"actor": "admin"},
    )
    client.patch(
        f"/local-test/construction/tasks/{task['id']}/assign",
        headers=admin_headers,
        json={"actor": "admin", "constructor": "constructor"},
    )
    upload_dir = Path("v2-api/app/static/uploads/construction")

    def saved_upload_files() -> set[str]:
        if not upload_dir.exists():
            return set()
        return {str(path.relative_to(upload_dir)) for path in upload_dir.rglob("*") if path.is_file()}

    before_files = saved_upload_files()
    uploaded = client.post(
        "/local-test/construction/groups/00000000/upload-batch",
        headers=constructor_headers,
        data={
            "actor": "constructor",
            "client_batch_id": "batch-placeholder-api",
            "client_completed_at": "2026-06-08T09:30:00",
            "collector": "collector-api",
            "module_asset_no": "module-api",
            "photo_slots": ["before_box", "module_meter", "after_box"],
            "client_photo_ids": ["photo-a", "photo-b", "photo-c"],
        },
        files=[
            ("files", ("before.jpg", b"placeholder-before", "image/jpeg")),
            ("files", ("meter.jpg", b"placeholder-meter", "image/jpeg")),
            ("files", ("after.jpg", b"placeholder-after", "image/jpeg")),
        ],
    )

    assert uploaded.status_code == 400
    assert "00000000" in uploaded.json()["detail"]
    assert saved_upload_files() == before_files

    group = client.get(
        f"/local-test/construction/tasks/{task['id']}/groups?limit=1&summary=true",
        headers=constructor_headers,
    ).json()["data"]["items"][0]
    zero_terminal_group = local_simulation.get_group(group["id"])
    assert zero_terminal_group is not None
    original_terminal = zero_terminal_group["terminal"]
    zero_terminal_group["terminal"] = "00000000"

    before_files = saved_upload_files()
    placeholder_terminal_upload = client.post(
        f"/local-test/construction/groups/{group['id']}/upload-batch",
        headers=constructor_headers,
        data={
            "actor": "constructor",
            "client_batch_id": "batch-placeholder-terminal",
            "client_completed_at": "2026-06-08T09:35:00",
            "collector": "collector-api",
            "module_asset_no": "module-api",
            "photo_slots": ["before_box", "module_meter", "after_box"],
            "client_photo_ids": ["photo-a", "photo-b", "photo-c"],
        },
        files=[
            ("files", ("before.jpg", b"placeholder-terminal-before", "image/jpeg")),
            ("files", ("meter.jpg", b"placeholder-terminal-meter", "image/jpeg")),
            ("files", ("after.jpg", b"placeholder-terminal-after", "image/jpeg")),
        ],
    )

    assert placeholder_terminal_upload.status_code == 400
    assert "00000000" in placeholder_terminal_upload.json()["detail"]
    assert saved_upload_files() == before_files
    zero_terminal_group["terminal"] = original_terminal

    rejected_placeholder_update = client.patch(
        f"/local-test/groups/{group['id']}/metadata",
        headers=admin_headers,
        json={"actor": "admin", "updates": {"meter_no": "00000000"}},
    )
    assert rejected_placeholder_update.status_code == 400
    legacy_placeholder_group = local_simulation.get_group(group["id"])
    assert legacy_placeholder_group is not None
    legacy_placeholder_group["meter_no"] = "00000000"

    before_files = saved_upload_files()
    placeholder_meter_upload = client.post(
        f"/local-test/construction/groups/{group['id']}/upload-batch",
        headers=constructor_headers,
        data={
            "actor": "constructor",
            "client_batch_id": "batch-placeholder-meter",
            "client_completed_at": "2026-06-08T09:40:00",
            "collector": "collector-api",
            "module_asset_no": "module-api",
            "photo_slots": ["before_box", "module_meter", "after_box"],
            "client_photo_ids": ["photo-a", "photo-b", "photo-c"],
        },
        files=[
            ("files", ("before.jpg", b"placeholder-meter-before", "image/jpeg")),
            ("files", ("meter.jpg", b"placeholder-meter-meter", "image/jpeg")),
            ("files", ("after.jpg", b"placeholder-meter-after", "image/jpeg")),
        ],
    )

    assert placeholder_meter_upload.status_code == 400
    assert "00000000" in placeholder_meter_upload.json()["detail"]
    assert saved_upload_files() == before_files


def test_exception_group_assignment_is_visible_to_constructor() -> None:
    admin_login = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    constructor_login = client.post("/auth/login", json={"username": "constructor", "password": "construct123"})
    admin_headers = {"Authorization": f"bearer {admin_login.json()['data']['access_token']}"}
    constructor_headers = {"Authorization": f"bearer {constructor_login.json()['data']['access_token']}"}

    client.post("/local-test/bootstrap", headers=admin_headers)
    task = next(item for item in client.get("/local-test/tasks", headers=admin_headers).json()["data"]["items"] if item["can_claim"])
    claim = client.post(f"/local-test/tasks/{task['id']}/claim", headers=admin_headers, json={"reviewer": "admin"})
    assert claim.status_code == 200
    group = client.get(
        f"/local-test/tasks/{task['id']}/groups?limit=1&summary=true",
        headers=admin_headers,
    ).json()["data"]["items"][0]

    returned = client.patch(
        f"/local-test/groups/{group['id']}/return-exception",
        headers=admin_headers,
        json={"actor": "admin", "category": "照片缺失", "note": "现场补缺失照片"},
    )
    assert returned.status_code == 200
    order = returned.json()["data"]["order"]
    assigned = client.patch(
        f"/local-test/construction/exception-orders/{order['id']}/assign",
        headers=admin_headers,
        json={"actor": "admin", "constructor": "constructor", "note": "补采异常资料组"},
    )
    constructor_orders = client.get(
        "/local-test/construction/exception-orders?actor=constructor",
        headers=constructor_headers,
    ).json()["data"]["items"]
    constructor_tasks = client.get(
        "/local-test/construction/tasks?actor=constructor",
        headers=constructor_headers,
    ).json()["data"]["items"]

    assert assigned.status_code == 200
    assert assigned.json()["data"]["order"]["assigned_to"] == "constructor"
    assert order["id"] in {item["id"] for item in constructor_orders}
    assert str(group["id"]) in {str(item["group_id"]) for item in constructor_orders}
    assert task["id"] in {item["id"] for item in constructor_tasks}


def test_construction_exception_order_routes_reject_actor_spoofing() -> None:
    team_id = f"exception-order-spoof-{uuid4()}"
    admin_token = security.create_access_token(
        {"sub": "admin", "username": "admin", "roles": ["admin"], "team_id": team_id}
    )
    reviewer_token = security.create_access_token(
        {"sub": "reviewer-a", "username": "reviewer-a", "roles": ["reviewer"], "team_id": team_id}
    )
    constructor_token = security.create_access_token(
        {"sub": "constructor-a", "username": "constructor-a", "roles": ["constructor"], "team_id": team_id}
    )
    admin_headers = {"X-Team-Id": team_id, "Authorization": f"bearer {admin_token}"}
    reviewer_headers = {"X-Team-Id": team_id, "Authorization": f"bearer {reviewer_token}"}
    constructor_headers = {"X-Team-Id": team_id, "Authorization": f"bearer {constructor_token}"}

    client.post("/local-test/bootstrap", headers=admin_headers)
    task = next(item for item in client.get("/local-test/tasks", headers=admin_headers).json()["data"]["items"] if item["can_claim"])
    claim = client.post(
        f"/local-test/tasks/{task['id']}/claim",
        headers=admin_headers,
        json={"reviewer": "reviewer-a"},
    )
    assert claim.status_code == 200
    group = client.get(
        f"/local-test/tasks/{task['id']}/groups?limit=1&summary=true",
        headers=admin_headers,
    ).json()["data"]["items"][0]
    returned = client.patch(
        f"/local-test/groups/{group['id']}/return-exception",
        headers=admin_headers,
        json={"actor": "reviewer-a", "category": "照片缺失", "note": "现场补缺失照片"},
    )
    assert returned.status_code == 200
    order_id = returned.json()["data"]["order"]["id"]

    spoof_assign = client.patch(
        f"/local-test/construction/exception-orders/{order_id}/assign",
        headers=constructor_headers,
        json={"actor": "admin", "constructor": "constructor-b", "note": "spoof assign"},
    )
    assert spoof_assign.status_code == 403

    assigned = client.patch(
        f"/local-test/construction/exception-orders/{order_id}/assign",
        headers=admin_headers,
        json={"actor": "admin", "constructor": "constructor-b", "note": "admin assign"},
    )
    assert assigned.status_code == 200
    spoof_submit = client.patch(
        f"/local-test/construction/exception-orders/{order_id}/submit",
        headers=constructor_headers,
        json={"actor": "constructor-b", "updates": {"collector": "C-1"}, "note": "spoof submit"},
    )
    spoof_unassign = client.patch(
        f"/local-test/construction/exception-orders/{order_id}/unassign",
        headers=constructor_headers,
        json={"actor": "admin", "reason": "spoof unassign"},
    )

    assert spoof_submit.status_code == 403
    assert spoof_unassign.status_code == 403


def test_constructor_can_keep_up_to_five_assigned_terminals() -> None:
    admin_login = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    constructor_login = client.post("/auth/login", json={"username": "constructor", "password": "construct123"})
    admin_headers = {"Authorization": f"bearer {admin_login.json()['data']['access_token']}"}
    constructor_headers = {"Authorization": f"bearer {constructor_login.json()['data']['access_token']}"}

    client.post("/local-test/bootstrap", headers=admin_headers)
    tasks = client.get("/local-test/tasks", headers=admin_headers).json()["data"]["items"][:6]
    assert len(tasks) == 6
    for task in tasks:
        opened = client.patch(
            f"/local-test/construction/tasks/{task['id']}/open",
            headers=admin_headers,
            json={"actor": "admin"},
        )
        assert opened.status_code == 200

    allowed_tasks = tasks[:5]
    denied_task = tasks[5]
    assigned_responses = [
        client.patch(
            f"/local-test/construction/tasks/{task['id']}/assign",
            headers=admin_headers,
            json={"actor": "admin", "constructor": "constructor"},
        )
        for task in allowed_tasks
    ]
    claimed = client.post(
        f"/local-test/construction/tasks/{allowed_tasks[0]['id']}/claim",
        headers=constructor_headers,
        json={"actor": "constructor"},
    )
    visible = client.get(
        "/local-test/construction/tasks?actor=constructor",
        headers=constructor_headers,
    )
    denied = client.post(
        f"/local-test/construction/tasks/{denied_task['id']}/claim",
        headers=constructor_headers,
        json={"actor": "constructor"},
    )
    denied_assign = client.patch(
        f"/local-test/construction/tasks/{denied_task['id']}/assign",
        headers=admin_headers,
        json={"actor": "admin", "constructor": "constructor"},
    )

    assert all(response.status_code == 200 for response in assigned_responses)
    assert claimed.status_code == 200
    assert {task["id"] for task in visible.json()["data"]["items"]} == {task["id"] for task in allowed_tasks}
    assert denied.status_code == 400
    assert "assigned by an administrator" in denied.json()["detail"]
    assert denied_assign.status_code == 400
    assert "already has 5 active terminals" in denied_assign.json()["detail"]


def test_construction_tasks_include_meter_search_text_for_task_picker() -> None:
    admin_login = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    admin_headers = {"Authorization": f"bearer {admin_login.json()['data']['access_token']}"}

    client.post("/local-test/bootstrap", headers=admin_headers)
    task = client.get("/local-test/tasks", headers=admin_headers).json()["data"]["items"][0]
    groups = client.get(
        f"/local-test/tasks/{task['id']}/groups?limit=1000&scan_only=false&summary=true",
        headers=admin_headers,
    ).json()["data"]["items"]
    target_meter = next(item["meter_no"] for item in groups if item.get("meter_no"))

    assigned = client.patch(
        f"/local-test/construction/tasks/{task['id']}/assign",
        headers=admin_headers,
        json={"actor": "admin", "constructor": "constructor"},
    )
    assert assigned.status_code == 200

    construction_tasks = client.get(
        "/local-test/construction/tasks?actor=constructor",
        headers=admin_headers,
    )
    matching_task = next(item for item in construction_tasks.json()["data"]["items"] if item["id"] == task["id"])

    assert target_meter in matching_task["meter_search_text"]


def test_direct_workspace_routes_redirect_to_app_shell() -> None:
    for path in [
        "/project-board",
        "/claim-tasks",
        "/construction",
        "/account-management",
        "/sync-config",
        "/collector-inventory",
        "/collector-batches",
        "/collector-workbench",
    ]:
        assert_vue_shell_response(client.get(path, follow_redirects=False))
    assert_export_retired(client.get("/exports", follow_redirects=False))
    response = client.get("/construction-cache", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/construction"
    response = client.get("/unmatched", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/global-search?review=1"


def test_production_exports_page_is_retired_before_auth(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    assert_export_retired(production_client.get("/exports"))
    assert_export_retired(production_client.get("/exports", headers=headers["reviewer"]))
    assert_export_retired(production_client.get("/exports", headers=headers["constructor"]))
    assert_export_retired(production_client.get("/exports", headers=headers["admin"]))


def test_project_board_page_is_available() -> None:
    assert_vue_shell_response(client.get("/project-board"))
    assert_vue_shell_response(client.get("/project-board?embedded=1"))

def test_static_page_verifier_rejects_visible_mojibake(tmp_path, monkeypatch) -> None:
    verifier = load_static_page_verifier()
    page = tmp_path / "bad.html"
    page.write_text("<!doctype html><html><body>妞ゅ湱娲伴惇瀣緲 濡炪倕婀卞ú?/body></html>", encoding="utf-8")
    monkeypatch.setattr(verifier, "STATIC_ROOT", tmp_path)

    try:
        verifier.verify_page("bad.html", ["妞ゅ湱娲伴惇瀣緲"], node=None)
    except AssertionError as exc:
        assert "mojibake fragment" in str(exc)
    else:
        raise AssertionError("visible mojibake should be rejected")


def test_legacy_static_html_pages_are_not_served() -> None:
    for path in [
        "/static/app_shell.html",
        "/static/login.html",
        "/static/project_board.html",
        "/static/claim_tasks.html",
        "/static/construction.html",
        "/static/construction_cache.html",
        "/static/unmatched.html",
        "/static/sync_config.html",
    ]:
        response = client.get(path)
        assert response.status_code == 404


def test_demo_review_image_assets_are_available() -> None:
    for index in range(1, 5):
        response = client.get(f"/static/demo-assets/review-photo-{index}.svg")

        assert response.status_code == 200
        assert "image/svg+xml" in response.headers["content-type"]


def test_claim_tasks_page_is_available() -> None:
    assert_vue_shell_response(client.get("/claim-tasks"))
    assert_vue_shell_response(client.get("/claim-tasks?embedded=1"))

def test_construction_page_is_available() -> None:
    assert_vue_shell_response(client.get("/construction"))
    assert_vue_shell_response(client.get("/construction?embedded=1"))


def test_global_search_page_is_available() -> None:
    assert_vue_shell_response(client.get("/global-search"))
    assert_vue_shell_response(client.get("/global-search?embedded=1"))


def test_unmatched_page_redirects_to_global_search_review_mode() -> None:
    response = client.get("/unmatched?embedded=1", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/global-search?review=1"


def test_legacy_review_page_redirects_to_global_search_with_encoded_group_id() -> None:
    response = client.get("/review/group%201%26review%3Dyes", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/global-search?group_id=group%201%26review%3Dyes&review=1"

def test_group_target_route_is_searchable() -> None:
    client.post("/local-test/bootstrap")

    response = client.get("/local-test/group-targets?query=350&limit=5")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert "items" in payload
    assert len(payload["items"]) <= 5


def test_admin_global_group_search_is_admin_only(monkeypatch, tmp_path) -> None:
    from app.api.routes import local_test

    production_settings = production_test_settings(
        demo_auth_enabled=False,
        admin_username="root-admin",
        admin_password="RootPass12345",
        admin_team_id="global-search-team",
        auth_users_path=str(tmp_path / "users.json"),
        jwt_secret="jwt-secret-for-global-search-test-12345",
        jwt_expire_minutes=60,
        state_backend="json",
    )
    monkeypatch.setattr(auth, "settings", production_settings)
    monkeypatch.setattr(account_store, "settings", production_settings)
    monkeypatch.setattr(security, "settings", production_settings)
    monkeypatch.setattr(local_test, "settings", production_settings)
    monkeypatch.setattr(main_module, "settings", production_settings)
    production_client = TestClient(main_module.create_app())

    admin_login = production_client.post(
        "/auth/login",
        json={"username": "root-admin", "password": "RootPass12345"},
    )
    assert admin_login.status_code == 200
    admin_headers = {"Authorization": f"bearer {admin_login.json()['data']['access_token']}"}

    created = production_client.post(
        "/auth/users",
        headers=admin_headers,
        json={
            "username": "constructor-a",
            "password": "ConstructPass12345",
            "name": "Constructor A",
            "roles": ["constructor"],
            "team_id": "global-search-team",
            "status": "active",
        },
    )
    assert created.status_code == 200
    constructor_login = production_client.post(
        "/auth/login",
        json={"username": "constructor-a", "password": "ConstructPass12345"},
    )
    assert constructor_login.status_code == 200
    constructor_headers = {"Authorization": f"bearer {constructor_login.json()['data']['access_token']}"}

    bootstrap = production_client.post("/local-test/bootstrap", headers=admin_headers)
    assert bootstrap.status_code == 200

    forbidden = production_client.get("/groups/search?query=350&limit=5", headers=constructor_headers)
    assert forbidden.status_code == 403
    legacy_forbidden = production_client.get("/local-test/group-targets?query=350&limit=5", headers=constructor_headers)
    assert legacy_forbidden.status_code == 403

    blank = production_client.get("/groups/search", headers=admin_headers)
    assert blank.status_code == 200
    assert blank.json()["data"]["total"] == 0
    assert blank.json()["data"]["items"] == []

    response = production_client.get("/groups/search?query=350&limit=5", headers=admin_headers)
    assert response.status_code == 200
    legacy_response = production_client.get("/local-test/group-targets?query=350&limit=5", headers=admin_headers)
    assert legacy_response.status_code == 200
    payload = response.json()["data"]
    assert payload["total"] >= 1
    assert len(payload["items"]) <= 5
    assert {"id", "task_id", "terminal", "meter_no", "status", "photo_count"}.issubset(payload["items"][0])
    target_group = payload["items"][0]
    import_photos = production_client.post(
        "/local-test/scan/import-url-rows",
        headers=admin_headers,
        json={
            "rows": [
                {
                    "barcode": target_group["meter_no"],
                    "meter_match_key": target_group["meter_match_key"],
                    "terminal": target_group["terminal"],
                    "collector": "search-display-collector",
                    "module_asset_no": "search-display-module",
                    "creator": "search-display-creator",
                    "photo_urls": "https://example.test/search-display.jpg",
                }
            ]
        },
    )
    assert import_photos.status_code == 200

    enriched = production_client.get(
        f"/groups/search?query={target_group['meter_no']}&limit=1",
        headers=admin_headers,
    )
    assert enriched.status_code == 200
    first_group = enriched.json()["data"]["items"][0]
    assert first_group["installer"] == target_group.get("installer", "")
    assert first_group["collector"] == "search-display-collector"
    assert first_group["module_asset_no"] == "search-display-module"
    assert first_group["creator"] == "search-display-creator"
    task_id = int(first_group["task_id"])
    team_token = local_simulation.set_current_team("global-search-team")
    try:
        local_simulation.assign_construction_task(task_id, actor="root-admin", constructor="installer-search-a")
    finally:
        local_simulation.reset_current_team(team_token)
    assigned = production_client.get(
        f"/groups/search?query={target_group['meter_no']}&limit=1",
        headers=admin_headers,
    )
    assert assigned.status_code == 200
    assert assigned.json()["data"]["items"][0]["installer"] == "installer-search-a"
    first_photo = first_group["photos"][0]
    assert {"id", "thumbnail_url", "preview_url", "collector", "module_asset_no", "creator"}.issubset(first_photo)
    assert first_photo["thumbnail_url"] or first_photo["preview_url"] or first_photo["image_url"]


def test_admin_group_backoffice_edit_and_resets_are_audited(monkeypatch, tmp_path) -> None:
    from app.api.routes import local_test

    production_settings = production_test_settings(
        demo_auth_enabled=False,
        admin_username="root-admin",
        admin_password="RootPass12345",
        admin_team_id="group-admin-team",
        auth_users_path=str(tmp_path / "users.json"),
        jwt_secret="jwt-secret-for-group-admin-test-12345",
        jwt_expire_minutes=60,
        state_backend="json",
    )
    monkeypatch.setattr(auth, "settings", production_settings)
    monkeypatch.setattr(account_store, "settings", production_settings)
    monkeypatch.setattr(security, "settings", production_settings)
    monkeypatch.setattr(local_test, "settings", production_settings)
    monkeypatch.setattr(main_module, "settings", production_settings)
    production_client = TestClient(main_module.create_app())

    admin_login = production_client.post(
        "/auth/login",
        json={"username": "root-admin", "password": "RootPass12345"},
    )
    assert admin_login.status_code == 200
    admin_headers = {"Authorization": f"bearer {admin_login.json()['data']['access_token']}"}

    created = production_client.post(
        "/auth/users",
        headers=admin_headers,
        json={
            "username": "constructor-a",
            "password": "ConstructPass12345",
            "name": "Constructor A",
            "roles": ["constructor"],
            "team_id": "group-admin-team",
            "status": "active",
        },
    )
    assert created.status_code == 200
    constructor_login = production_client.post(
        "/auth/login",
        json={"username": "constructor-a", "password": "ConstructPass12345"},
    )
    assert constructor_login.status_code == 200
    constructor_headers = {"Authorization": f"bearer {constructor_login.json()['data']['access_token']}"}

    assert production_client.post("/local-test/bootstrap", headers=admin_headers).status_code == 200
    group = production_client.get("/groups/search?query=350&limit=1", headers=admin_headers).json()["data"]["items"][0]

    forbidden = production_client.patch(
        f"/groups/{group['id']}/metadata",
        headers=constructor_headers,
        json={"updates": {"address": "constructor should not edit"}},
    )
    assert forbidden.status_code == 403
    legacy_privileged_forbidden = production_client.patch(
        f"/local-test/groups/{group['id']}/metadata",
        headers=constructor_headers,
        json={"actor": "forged-admin", "updates": {"status": "approved", "reviewer": "forged-admin"}},
    )
    assert legacy_privileged_forbidden.status_code == 403
    legacy_terminal_forbidden = production_client.patch(
        f"/local-test/groups/{group['id']}/terminal",
        headers=constructor_headers,
        json={"actor": "forged-admin", "terminal": "FORGED-TERM"},
    )
    assert legacy_terminal_forbidden.status_code == 403

    edited = production_client.patch(
        f"/groups/{group['id']}/metadata",
        headers=admin_headers,
        json={
            "updates": {
                "meter_no": "ADMIN-METER-001",
                "terminal": "ADMIN-TERM-001",
                "address": "admin edited address",
                "status": "approved",
                "reviewer": "manual-reviewer",
                "review_note": "manual review note",
                "exception_note": "manual exception note",
                "collector": "admin collector",
                "module_asset_no": "admin module",
            }
        },
    )
    assert edited.status_code == 200
    edited_payload = edited.json()["data"]
    edited_group = edited_payload["group"]
    assert edited_group["meter_no"] == "ADMIN-METER-001"
    assert edited_group["terminal"] == "ADMIN-TERM-001"
    assert edited_group["address"] == "admin edited address"
    assert edited_group["status"] == "approved"
    assert edited_group["reviewer"] == "manual-reviewer"
    assert edited_group["collector"] == "admin collector"
    assert edited_group["module_asset_no"] == "admin module"
    assert set(edited_payload["changed_fields"]) >= {"meter_no", "terminal", "address", "status", "reviewer"}

    searched = production_client.get("/groups/search?query=ADMIN-METER-001&limit=1", headers=admin_headers)
    assert searched.status_code == 200
    searched_group = searched.json()["data"]["items"][0]
    assert searched_group["collector"] == "admin collector"
    assert searched_group["module_asset_no"] == "admin module"
    assert searched_group["exception_note"] == "manual exception note"

    reset_review = production_client.patch(
        f"/groups/{group['id']}/reset-unreviewed",
        headers=admin_headers,
        json={"reason": "admin smoke reset review"},
    )
    assert reset_review.status_code == 200
    reset_review_group = reset_review.json()["data"]["group"]
    assert reset_review_group["status"] == "pending"
    assert reset_review_group["reviewer"] == ""
    assert reset_review_group["review_note"] == ""
    assert reset_review_group["exception_note"] == ""

    reset_construction = production_client.patch(
        f"/groups/{group['id']}/reset-unconstructed",
        headers=admin_headers,
        json={"reason": "admin smoke reset construction"},
    )
    assert reset_construction.status_code == 200
    reset_construction_payload = reset_construction.json()["data"]
    assert reset_construction_payload["group"]["photo_count"] == 0
    assert reset_construction_payload["group"]["collector"] == ""
    assert reset_construction_payload["group"]["module_asset_no"] == ""
    assert reset_construction_payload["group"]["construction_collector"] == ""
    assert reset_construction_payload["group"]["construction_module_asset_no"] == ""
    assert reset_construction_payload["soft_deleted_photos"] >= 0

    target_for_archive = production_client.get("/groups/search?query=350&limit=1", headers=admin_headers).json()["data"][
        "items"
    ][0]
    archive_photos = production_client.post(
        "/local-test/scan/import-url-rows",
        headers=admin_headers,
        json={
            "rows": [
                {
                    "barcode": target_for_archive["meter_no"],
                    "meter_match_key": target_for_archive["meter_match_key"],
                    "terminal": target_for_archive["terminal"],
                    "collector": "archive-collector",
                    "module_asset_no": "archive-module",
                    "creator": "archive-creator",
                    "photo_urls": "https://example.test/archive-a.jpg,https://example.test/archive-b.jpg",
                }
            ]
        },
    )
    assert archive_photos.status_code == 200
    archive_response = production_client.post(
        "/groups/bulk-archive",
        headers=admin_headers,
        json={"group_ids": [target_for_archive["id"]], "reason": "admin bulk archive smoke"},
    )
    assert archive_response.status_code == 200
    archive_payload = archive_response.json()["data"]
    assert archive_payload["archived_count"] == 1
    archived_group = archive_payload["groups"][0]
    assert archived_group["id"] == target_for_archive["id"]
    assert archived_group["photos"]
    assert all(photo["archive_status"] == "archived" for photo in archived_group["photos"])

    audit = production_client.get("/local-test/audit-log?limit=20", headers=admin_headers)
    assert audit.status_code == 200
    actions = [item["action"] for item in audit.json()["data"]["items"]]
    assert "admin_group_metadata_update" in actions
    assert "admin_group_reset_unreviewed" in actions
    assert "group_reset_to_unconstructed" in actions
    assert "admin_groups_bulk_archive" in actions


def test_unmatched_create_group_route_creates_terminal_task() -> None:
    client.post("/local-test/bootstrap")
    client.post(
        "/local-test/scan/import-url-rows",
        json={
            "rows": [
                {
                    "meter_no": "NO-MATCH-API",
                    "terminal": "",
                    "collector": "collector-api",
                    "module_asset_no": "module-api",
                    "photo_urls": "https://example.test/api-a.jpg,https://example.test/api-b.jpg",
                }
            ]
        },
    )
    unmatched = client.get("/local-test/unmatched?query=NO-MATCH-API").json()["data"]["items"][0]

    response = client.post(
        f"/local-test/unmatched/{unmatched['unmatched_id']}/create-group",
        json={
            "actor": "api-test",
            "expected_version": unmatched["review_version"],
            "terminal": "T-API",
            "updates": {"address": "api manual address"},
        },
    )
    tasks = client.get("/local-test/tasks").json()["data"]["items"]

    assert response.status_code == 200
    assert response.json()["data"]["group"]["terminal"] == "T-API"
    assert response.json()["data"]["group"]["photo_count"] == 2
    assert any(task["terminal"] == "T-API" and task["can_claim"] for task in tasks)


def test_unmatched_blank_route_creates_unmatched_record() -> None:
    client.post("/local-test/bootstrap")

    response = client.post("/local-test/unmatched/blank", json={"actor": "api-test"})
    record = response.json()["data"]["record"]
    listed = client.get(f"/local-test/unmatched?query={record['unmatched_id']}").json()["data"]

    assert response.status_code == 200
    assert record["record_type"] == "blank_group"
    assert listed["total"] == 1
    assert listed["items"][0]["unmatched_id"] == record["unmatched_id"]


def test_unmatched_list_rows_include_review_version() -> None:
    client.post("/local-test/bootstrap")
    created = client.post("/local-test/unmatched/blank", json={"actor": "api-test"}).json()["data"]["record"]

    listed = client.get(f"/local-test/unmatched?query={created['unmatched_id']}").json()["data"]["items"]

    assert len(listed) == 1
    assert isinstance(listed[0]["review_version"], int)
    assert listed[0]["review_version"] == 1


def test_group_metadata_route_updates_form_fields() -> None:
    client.post("/local-test/bootstrap")
    created = client.post(
        "/local-test/groups",
        json={
            "actor": "api-test",
            "terminal": "T-FORM",
            "meter_no": "M-FORM",
            "address": "form address before",
        },
    ).json()["data"]["group"]
    client.post(
        f"/local-test/groups/{created['id']}/photos/import-urls",
        json={
            "actor": "api-test",
            "photo_urls": ["https://example.test/form-1.jpg"],
            "collector": "old collector",
            "module_asset_no": "old module",
            "creator": "old installer",
        },
    )

    response = client.patch(
        f"/local-test/groups/{created['id']}/metadata",
        json={
            "actor": "api-test",
            "updates": {
                "meter_no": "API-FORM",
                "address": "api form address",
                "collector": "api collector",
                "module_asset_no": "api module",
                "creator": "api installer",
            },
        },
    )
    updated = response.json()["data"]["group"]

    assert response.status_code == 200
    assert updated["meter_no"] == "API-FORM"
    assert updated["address"] == "api form address"
    assert updated["photos"][0]["collector"] == "api collector"
    assert updated["photos"][0]["asset_no"] == "api module"
    assert updated["photos"][0]["creator"] == "api installer"


def test_manual_group_and_photo_import_routes() -> None:
    client.post("/local-test/bootstrap")

    created = client.post(
        "/local-test/groups",
        json={
            "actor": "api-test",
            "terminal": "T-MANUAL",
            "meter_no": "M-MANUAL",
            "address": "manual address",
        },
    )
    group = created.json()["data"]["group"]

    imported = client.post(
        f"/local-test/groups/{group['id']}/photos/import-urls",
        json={
            "actor": "api-test",
            "photo_urls": ["https://example.test/manual-1.jpg", "https://example.test/manual-2.jpg"],
            "collector": "collector-manual",
            "module_asset_no": "module-manual",
            "creator": "installer-manual",
        },
    )

    assert created.status_code == 200
    assert group["terminal"] == "T-MANUAL"
    assert group["photo_count"] == 0
    assert imported.status_code == 200
    assert imported.json()["data"]["added"] == 2
    assert imported.json()["data"]["group"]["photo_count"] == 2
    imported_photo = imported.json()["data"]["group"]["photos"][0]
    assert imported_photo["storage_type"] == "external_url"
    assert imported_photo["storage_key"] == "https://example.test/manual-1.jpg"


def test_manual_group_photo_upload_route() -> None:
    client.post("/local-test/bootstrap")

    created = client.post(
        "/local-test/groups",
        json={
            "actor": "api-test",
            "terminal": "T-UPLOAD",
            "meter_no": "M-UPLOAD",
            "address": "manual upload address",
        },
    )
    group = created.json()["data"]["group"]

    uploaded = client.post(
        f"/local-test/groups/{group['id']}/photos/upload-images",
        data={"actor": "api-test", "collector": "collector-upload", "module_asset_no": "module-upload"},
        files=[
            ("files", ("upload-a.jpg", tiny_jpeg_bytes("red"), "image/jpeg")),
            ("files", ("upload-b.png", tiny_png_bytes("blue"), "image/png")),
        ],
    )

    assert uploaded.status_code == 200
    payload = uploaded.json()["data"]
    assert payload["added"] == 2
    assert payload["group"]["photo_count"] == 2
    assert payload["uploaded_urls"][0].startswith("/static/uploads/manual/")
    uploaded_photo = payload["group"]["photos"][0]
    assert uploaded_photo["storage_type"] == "local_upload"
    assert uploaded_photo["storage_key"].startswith("manual/")
    assert uploaded_photo["sha256"]


def test_upload_rejects_html_file_before_save() -> None:
    client.post("/local-test/bootstrap")
    created = client.post(
        "/local-test/groups",
        json={
            "actor": "api-test",
            "terminal": "T-HTML-UPLOAD",
            "meter_no": "M-HTML-UPLOAD",
            "address": "html upload rejection address",
        },
    )
    group = created.json()["data"]["group"]
    upload_dir = Path("v2-api/app/static/uploads/manual")

    def saved_upload_files() -> set[str]:
        if not upload_dir.exists():
            return set()
        return {str(path.relative_to(upload_dir)) for path in upload_dir.rglob("*") if path.is_file()}

    before_files = saved_upload_files()
    uploaded = client.post(
        f"/local-test/groups/{group['id']}/photos/upload-images",
        data={"actor": "api-test"},
        files=[("files", ("masked-html.jpg", b"<!doctype html><script>alert(1)</script>", "text/html"))],
    )

    assert uploaded.status_code == 400
    assert "Unsupported image MIME type" in uploaded.json()["detail"]
    assert saved_upload_files() == before_files


def test_upload_rejects_spoofed_html_before_save() -> None:
    client.post("/local-test/bootstrap")
    created = client.post(
        "/local-test/groups",
        json={
            "actor": "api-test",
            "terminal": "T-SPOOF-UPLOAD",
            "meter_no": "M-SPOOF-UPLOAD",
            "address": "spoofed html upload rejection address",
        },
    )
    group = created.json()["data"]["group"]
    upload_dir = Path("v2-api/app/static/uploads/manual")

    def saved_upload_files() -> set[str]:
        if not upload_dir.exists():
            return set()
        return {str(path.relative_to(upload_dir)) for path in upload_dir.rglob("*") if path.is_file()}

    before_files = saved_upload_files()
    uploaded = client.post(
        f"/local-test/groups/{group['id']}/photos/upload-images",
        data={"actor": "api-test"},
        files=[
            ("files", ("valid-first.jpg", tiny_jpeg_bytes(), "image/jpeg")),
            ("files", ("masked-html.jpg", b"   <html><script>alert(1)</script>", "image/jpeg")),
        ],
    )

    assert uploaded.status_code == 400
    assert "active content" in uploaded.json()["detail"]
    assert saved_upload_files() == before_files


def test_upload_rejects_fake_image_bytes_before_save() -> None:
    client.post("/local-test/bootstrap")
    created = client.post(
        "/local-test/groups",
        json={
            "actor": "api-test",
            "terminal": "T-FAKE-UPLOAD",
            "meter_no": "M-FAKE-UPLOAD",
            "address": "fake upload rejection address",
        },
    )
    group = created.json()["data"]["group"]

    uploaded = client.post(
        f"/local-test/groups/{group['id']}/photos/upload-images",
        data={"actor": "api-test"},
        files=[("files", ("fake.jpg", b"not-a-real-image", "image/jpeg"))],
    )

    assert uploaded.status_code == 400
    assert "unsupported image bytes" in uploaded.json()["detail"]


def test_upload_rejects_too_many_files(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_upload_files_per_request", 1)
    client.post("/local-test/bootstrap")
    created = client.post(
        "/local-test/groups",
        json={
            "actor": "api-test",
            "terminal": "T-COUNT-UPLOAD",
            "meter_no": "M-COUNT-UPLOAD",
            "address": "upload count rejection address",
        },
    )
    group = created.json()["data"]["group"]

    uploaded = client.post(
        f"/local-test/groups/{group['id']}/photos/upload-images",
        data={"actor": "api-test"},
        files=[
            ("files", ("first.jpg", b"fake-image-a", "image/jpeg")),
            ("files", ("second.jpg", b"fake-image-b", "image/jpeg")),
        ],
    )

    assert uploaded.status_code == 400
    assert "Too many files" in uploaded.json()["detail"]


def test_photo_proxy_rejects_localhost(monkeypatch) -> None:
    response = client.get("/local-test/photo-proxy", params={"url": "http://localhost/private.jpg"})

    assert response.status_code == 400
    assert "not allowed" in response.json()["detail"]


def test_photo_proxy_requires_allowlist_in_production(monkeypatch) -> None:
    from app.api.routes import local_test
    from app.services import photo_storage

    production_settings = production_test_settings(app_env="production", photo_proxy_hosts=set())
    monkeypatch.setattr(local_test, "settings", production_settings)
    monkeypatch.setattr(photo_storage, "settings", production_settings)

    response = client.get("/local-test/photo-proxy", params={"url": "https://example.test/photo.jpg"})

    assert response.status_code == 400
    assert "not allowed" in response.json()["detail"]


def test_photo_proxy_rejects_private_dns(monkeypatch) -> None:
    from app.services import photo_storage

    monkeypatch.setattr(
        photo_storage,
        "resolve_remote_image_host_addresses",
        lambda hostname: ["10.0.0.5"],
        raising=False,
    )

    response = client.get("/local-test/photo-proxy", params={"url": "https://cdn.example.test/photo.jpg"})

    assert response.status_code == 400
    assert "not allowed" in response.json()["detail"]


def test_read_remote_image_with_validator_blocks_redirect_before_fetch(monkeypatch) -> None:
    from app.api.routes import local_test
    from fastapi import HTTPException

    no_redirect_requests: list[str] = []
    automatic_redirect_requests: list[str] = []

    def validator(url: str) -> None:
        if "127.0.0.1" in url:
            raise HTTPException(status_code=400, detail="Photo proxy host is not allowed")

    def automatic_redirect_fetch(_request, timeout: int):
        automatic_redirect_requests.append(str(getattr(_request, "full_url", _request)))
        raise AssertionError("validated remote image reads must not auto-follow redirects")

    def no_redirect_fetch(url: str, **_kwargs):
        no_redirect_requests.append(url)
        raise HTTPError(
            url,
            302,
            "Found",
            {"Location": "http://127.0.0.1/private.jpg"},
            None,
        )

    monkeypatch.setattr(local_test, "urlopen", automatic_redirect_fetch)
    monkeypatch.setattr(local_test, "open_validated_remote_image_url", no_redirect_fetch)

    try:
        local_test._read_remote_image("https://cdn.example.test/photo.jpg", url_validator=validator)
        raise AssertionError("redirected remote image should be rejected")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "redirect" in str(exc.detail).lower() or "not allowed" in str(exc.detail).lower()
    assert automatic_redirect_requests == []
    assert no_redirect_requests == ["https://cdn.example.test/photo.jpg"]


def test_read_remote_image_with_validator_uses_dns_pinned_opener(monkeypatch) -> None:
    from app.api.routes import local_test

    class Response:
        headers = {"Content-Type": "image/jpeg", "Content-Length": "5"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self) -> str:
            return "https://cdn.example.test/photo.jpg"

        def read(self, _limit: int) -> bytes:
            return b"image"

    calls: list[str] = []
    monkeypatch.setattr(
        local_test,
        "open_validated_remote_image_url",
        lambda url, **_kwargs: calls.append(url) or Response(),
        raising=False,
    )
    monkeypatch.setattr(local_test, "validate_image_content", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        local_test._NO_REDIRECT_OPENER,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("legacy opener must not run")),
    )

    content, content_type = local_test._read_remote_image(
        "https://cdn.example.test/photo.jpg",
        url_validator=lambda _url: None,
    )

    assert content == b"image"
    assert content_type == "image/jpeg"
    assert calls == ["https://cdn.example.test/photo.jpg"]


@pytest.mark.parametrize("entrypoint", ["photo-proxy", "group-photo-source"])
def test_external_photo_routes_resolve_source_host_once(monkeypatch, entrypoint: str) -> None:
    from app.api.routes import local_test

    class Response:
        headers = {"Content-Type": "image/jpeg", "Content-Length": "5"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self) -> str:
            return "https://cdn.example.test/photo.jpg"

        def read(self, _limit: int) -> bytes:
            return b"image"

    dns_calls: list[str] = []

    def resolver(hostname: str) -> list[str]:
        dns_calls.append(hostname)
        return ["93.184.216.34"]

    def pinned_open(url: str, **_kwargs):
        local_test.validate_remote_image_url(url, resolver=resolver)
        return Response()

    monkeypatch.setattr(local_test, "_resolve_photo_proxy_host_addresses", resolver)
    monkeypatch.setattr(local_test, "open_validated_remote_image_url", pinned_open)
    monkeypatch.setattr(local_test, "validate_image_content", lambda *_args, **_kwargs: None)

    if entrypoint == "photo-proxy":
        local_test.photo_proxy("https://cdn.example.test/photo.jpg")
    else:
        local_test._photo_content_response_from_source(
            "https://cdn.example.test/photo.jpg",
            request=None,
            variant="preview",
        )

    assert dns_calls == ["cdn.example.test"]


def test_request_size_limit_returns_413(monkeypatch) -> None:
    limited_settings = production_test_settings(app_env="local", max_upload_mb=0)
    monkeypatch.setattr(main_module, "settings", limited_settings)
    limited_client = TestClient(main_module.create_app())

    response = limited_client.post("/local-test/bootstrap", content=b"x")

    assert response.status_code == 413


def test_catalog_routes_are_filterable() -> None:
    client.post("/local-test/bootstrap")

    response = client.get("/local-test/catalog/total?limit=5")
    filtered = client.get("/local-test/catalog/stage?query=350&limit=5")

    assert response.status_code == 200
    assert response.json()["data"]["total"] > 0
    assert len(response.json()["data"]["items"]) <= 5
    assert filtered.status_code == 200
    assert "items" in filtered.json()["data"]


def test_sync_config_page_is_available() -> None:
    assert_vue_shell_response(client.get("/sync-config"))

def test_clear_scan_data_route_resets_local_scan_state() -> None:
    client.post("/local-test/bootstrap")

    response = client.post("/local-test/scan/clear")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["summary"]["scan_rows"] == 0
    assert payload["summary"]["downloaded_photos"] == 0
    assert payload["summary"]["unclassified_photos"] == 0


def test_url_row_import_route_updates_local_tasks() -> None:
    client.post("/local-test/bootstrap")
    first_group = client.get("/local-test/groups?limit=1").json()["data"]["items"][0]
    client.post("/local-test/scan/clear")

    response = client.post(
        "/local-test/scan/import-url-rows",
        json={
            "rows": [
                {
                    "meter_no": first_group["meter_no"],
                    "terminal": first_group["terminal"],
                    "collector": "C-001",
                    "module_asset_no": "M-001",
                    "photo_urls": "https://example.test/1.jpg,https://example.test/2.jpg",
                }
            ]
        },
    )
    tasks = client.get("/local-test/tasks").json()["data"]["items"]

    assert response.status_code == 200
    assert response.json()["data"]["applied_records"] == 2
    assert any(task["can_claim"] for task in tasks)


def test_url_row_import_adds_incremental_photos_for_duplicate_meter_number() -> None:
    client.post("/local-test/bootstrap")
    first_group = client.get("/local-test/groups?limit=1").json()["data"]["items"][0]
    client.post("/local-test/scan/clear")

    rows = [
        {
            "meter_no": first_group["meter_no"],
            "terminal": first_group["terminal"],
            "collector": "C-001",
            "module_asset_no": "M-001",
            "photo_urls": "https://example.test/1.jpg",
        },
        {
            "meter_no": first_group["meter_no"],
            "terminal": first_group["terminal"],
            "collector": "C-002",
            "module_asset_no": "M-002",
            "photo_urls": "https://example.test/2.jpg",
        },
    ]
    response = client.post("/local-test/scan/import-url-rows", json={"rows": rows})
    group = client.get(f"/local-test/groups/{first_group['id']}").json()["data"]

    assert response.status_code == 200
    assert response.json()["data"]["applied_records"] == 2
    assert response.json()["data"]["skipped_duplicate_meters"] == 0
    assert response.json()["data"]["photos_new"] == 2
    assert group["photo_count"] == 2


def test_installer_daily_workload_includes_work_time_segments() -> None:
    client.post("/local-test/bootstrap")
    groups = client.get("/local-test/groups?limit=3").json()["data"]["items"]
    client.post("/local-test/scan/clear")

    rows = [
        {
            "meter_no": groups[0]["meter_no"],
            "terminal": groups[0]["terminal"],
            "creator": "kpi-installer",
            "created_at": "2026-06-22 08:10:00",
            "photo_urls": "https://example.test/kpi-1.jpg",
        },
        {
            "meter_no": groups[0]["meter_no"],
            "terminal": groups[0]["terminal"],
            "creator": "kpi-installer",
            "created_at": "2026-06-22 08:50:00",
            "photo_urls": "https://example.test/kpi-2.jpg",
        },
        {
            "meter_no": groups[1]["meter_no"],
            "terminal": groups[1]["terminal"],
            "creator": "kpi-installer",
            "created_at": "2026-06-22 09:20:00",
            "photo_urls": "https://example.test/kpi-3.jpg",
        },
        {
            "meter_no": groups[2]["meter_no"],
            "terminal": groups[2]["terminal"],
            "creator": "kpi-installer",
            "created_at": "2026-06-22 11:00:00",
            "photo_urls": "https://example.test/kpi-4.jpg",
        },
    ]

    response = client.post("/local-test/scan/import-url-rows", json={"rows": rows})
    workload = client.get("/local-test/installers/kpi-installer/daily-workload")

    assert response.status_code == 200
    assert workload.status_code == 200
    item = workload.json()["data"]["items"][0]
    assert item["date"] == "2026-06-22"
    assert item["start_time"] == "08:10"
    assert item["end_time"] == "11:00"
    assert item["work_duration_minutes"] == 50
    assert item["efficiency_duration_minutes"] == 50
    assert item["work_duration_label"]
    assert item["work_span_minutes"] == 170
    assert item["break_threshold_minutes"] == 45
    assert item["timepoint_count"] == 4
    assert item["completion_count"] == 3
    assert item["completion_per_effective_hour"] == 3.6
    assert item["weighted_completion"] >= 2.25
    segments = {segment["hour"]: segment["minutes"] for segment in item["hourly_segments"]}
    assert segments[8] == 35
    assert segments[9] == 15
    assert segments[10] == 0
    two_hour = {segment["start_hour"]: segment for segment in item["two_hour_segments"]}
    assert two_hour[8]["minutes"] == 50
    assert two_hour[8]["efficiency_minutes"] == 50
    assert two_hour[8]["completion_count"] == 2
    assert two_hour[8]["completion_per_effective_hour"] == 2.4
    assert len(two_hour[8]["addresses"]) == 2
    assert two_hour[10]["minutes"] == 0
    assert two_hour[10]["completion_count"] == 1
    assert two_hour[10]["addresses"][0]["difficulty_weight"] >= 0.75


def test_installer_kpi_clusters_same_building_number_public_equipment() -> None:
    completion_records = [
        {
            "group_id": "g-room",
            "meter_no": "110000000001",
            "terminal": "350000000001",
            "address": "上海市宝山区聚丰园路95弄18号201室",
            "completed_at": datetime(2026, 6, 22, 8, 10),
        },
        {
            "group_id": "g-public",
            "meter_no": "110000000002",
            "terminal": "350000000001",
            "address": "上海市宝山区聚丰园路95弄18号公用设备",
            "completed_at": datetime(2026, 6, 22, 8, 20),
        },
        {
            "group_id": "g-other-building",
            "meter_no": "110000000003",
            "terminal": "350000000001",
            "address": "上海市宝山区聚丰园路95弄19号公用设备",
            "completed_at": datetime(2026, 6, 22, 8, 30),
        },
    ]

    summary = local_simulation.build_work_time_summary(
        [record["completed_at"] for record in completion_records],
        completion_records,
    )

    segment = next(item for item in summary["two_hour_segments"] if item["start_hour"] == 8)
    addresses = {item["meter_no"]: item for item in segment["addresses"]}

    assert addresses["110000000001"]["address_cluster_key"].endswith("95弄18号")
    assert addresses["110000000002"]["address_cluster_key"] == addresses["110000000001"]["address_cluster_key"]
    assert addresses["110000000002"]["cluster_size"] == 2
    assert addresses["110000000003"]["address_cluster_key"].endswith("95弄19号")
    assert addresses["110000000003"]["address_cluster_key"] != addresses["110000000001"]["address_cluster_key"]


def test_excel_exports_are_retired() -> None:
    admin_headers = _final_delivery_headers()

    task_export = client.post("/exports/task-detail", headers=admin_headers, json={"task_id": 1})
    all_final_export = client.post("/exports/final-delivery", headers=admin_headers, json={"project_id": 1})
    terminal_final_export = client.post(
        "/exports/final-delivery",
        headers=admin_headers,
        json={"task_id": 1},
    )
    exception_export = client.post("/exports/exception-meters", headers=admin_headers, json={})
    project_outside_export = client.post("/exports/project-outside", headers=admin_headers, json={})

    for response in (
        task_export,
        all_final_export,
        terminal_final_export,
        exception_export,
        project_outside_export,
    ):
        assert_export_retired(response)


def test_production_legacy_export_endpoints_are_retired_for_every_role(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)
    cases = [
        ("/exports/task-detail", {"task_id": 101}),
        ("/exports/exception-meters", {"reviewer": ""}),
        ("/exports/project-outside", {}),
    ]

    for role in ("constructor", "reviewer"):
        for path, payload in cases:
            response = production_client.post(path, headers=headers[role], json=payload)
            assert_export_retired(response)

    for path, payload in cases:
        response = production_client.post(path, headers=headers["admin"], json=payload)
        assert_export_retired(response)


def _final_delivery_headers(*, role: str = "admin", subject: str = "admin-a") -> dict[str, str]:
    token = security.create_access_token(
        {
            "sub": subject,
            "username": subject,
            "roles": [role],
            "team_id": local_simulation.DEFAULT_TEAM_ID,
        }
    )
    return {"Authorization": f"bearer {token}"}


def test_final_delivery_is_retired_for_anonymous_and_non_admin() -> None:
    anonymous = client.post("/exports/final-delivery", json={"task_id": 17})
    reviewer = client.post(
        "/exports/final-delivery",
        headers=_final_delivery_headers(role="reviewer", subject="reviewer-a"),
        json={"task_id": 17},
    )

    assert_export_retired(anonymous)
    assert_export_retired(reviewer)


def test_final_delivery_export_is_retired_before_zip_creation() -> None:
    response = client.post(
        "/exports/final-delivery",
        headers=_final_delivery_headers(),
        json={"task_id": 17},
    )

    assert_export_retired(response)


def test_final_delivery_cache_miss_path_is_retired_before_repository_access() -> None:
    response = client.post(
        "/exports/final-delivery",
        headers=_final_delivery_headers(),
        json={"task_id": 17},
    )

    assert_export_retired(response)


@pytest.mark.parametrize("failure", [RuntimeError("response failed"), asyncio.CancelledError()])
def test_final_delivery_export_releases_exact_lease_when_response_construction_fails(
    failure: BaseException,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_path = tmp_path / "formal.zip"
    package_path.write_bytes(b"zip")
    releases = []

    class Package:
        path = package_path

        def release(self):
            releases.append(self.path)

    class Repository:
        def request_final_delivery_export(self, **_kwargs):
            return Package()

    def fail_response(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(export_routes, "get_state_repository", lambda: Repository())
    monkeypatch.setattr(export_routes, "FileResponse", fail_response)

    with pytest.raises(type(failure)):
        export_routes.export_final_delivery(
            export_routes.FinalDeliveryExportRequest(task_id=17),
            SimpleNamespace(state=SimpleNamespace(auth={"sub": "admin", "roles": ["admin"]})),
            {"sub": "admin", "roles": ["admin"]},
        )

    assert releases == [package_path]


def _direct_asgi_scope() -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/exports/final-delivery",
        "raw_path": b"/exports/final-delivery",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("test", 1234),
        "server": ("testserver", 80),
    }


def _leased_export_response(
    monkeypatch: pytest.MonkeyPatch,
    package_path: Path,
    releases: list[Path],
):
    class Package:
        path = package_path

        def release(self):
            releases.append(self.path)

    class Repository:
        def request_final_delivery_export(self, **_kwargs):
            return Package()

    monkeypatch.setattr(export_routes, "get_state_repository", lambda: Repository())
    return export_routes.export_final_delivery(
        export_routes.FinalDeliveryExportRequest(task_id=17),
        SimpleNamespace(state=SimpleNamespace(auth={"sub": "admin", "roles": ["admin"]})),
        {"sub": "admin", "roles": ["admin"]},
    )


@pytest.mark.parametrize("exit_kind", ["normal", "send_error", "cancelled", "missing_file"])
def test_final_delivery_asgi_response_releases_exact_lease_on_every_exit(
    exit_kind: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_path = tmp_path / "direct-asgi.zip"
    package_path.write_bytes(b"zip-content")
    releases: list[Path] = []
    response = _leased_export_response(monkeypatch, package_path, releases)
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)
        if exit_kind == "send_error" and message["type"] == "http.response.body":
            raise RuntimeError("injected send failure")
        if exit_kind == "cancelled" and message["type"] == "http.response.body":
            raise asyncio.CancelledError()

    if exit_kind == "missing_file":
        package_path.unlink()

    if exit_kind == "normal":
        asyncio.run(response(_direct_asgi_scope(), receive, send))
    else:
        expected = asyncio.CancelledError if exit_kind == "cancelled" else RuntimeError
        with pytest.raises(expected):
            asyncio.run(response(_direct_asgi_scope(), receive, send))

    assert releases == [package_path]
    if exit_kind == "normal":
        assert sent[-1]["type"] == "http.response.body"


def test_final_delivery_export_is_retired_before_group_validation() -> None:
    response = client.post(
        "/exports/final-delivery",
        headers=_final_delivery_headers(),
        json={"terminal": "00112233"},
    )

    assert_export_retired(response)


@pytest.mark.parametrize(
    "cache_code",
    ["delivery_cache_invalid", "delivery_cache_pending", "invalid_photo_count"],
)
def test_final_delivery_export_is_retired_before_every_cache_validation_shape(
    cache_code: str,
) -> None:
    response = client.post(
        "/exports/final-delivery",
        headers=_final_delivery_headers(),
        json={"task_id": 17, "cache_code": cache_code},
    )

    assert_export_retired(response)


def test_final_delivery_manifest_is_retired_for_every_scope() -> None:
    all_response = client.get("/local-test/export-manifest/final-delivery")
    response = client.get("/local-test/export-manifest/final-delivery?task_id=17")
    all_scope_response = client.get("/local-test/export-manifest/final-delivery?task_id=17&review_scope=all")

    assert_export_retired(all_response)
    assert_export_retired(response)
    assert_export_retired(all_scope_response)


def test_group_detail_uses_local_data_without_legacy_sync(monkeypatch) -> None:
    client.post("/local-test/bootstrap")
    first_group = client.get("/local-test/groups?limit=1").json()["data"]["items"][0]

    def fail_if_called(group_id: str):
        raise AssertionError(f"legacy sync should not run for group detail: {group_id}")

    monkeypatch.setattr(sync_manager, "load_group_photo_urls", fail_if_called)

    response = client.get(f"/local-test/groups/{first_group['id']}")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["id"] == first_group["id"]
    assert "photos" in payload


def test_postgres_scan_import_invalidates_group_delivery_artifacts_before_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    group = SimpleNamespace(
        id=uuid4(),
        legacy_id="postgres-scan-group",
        team_id="scan-team",
        meter_match_key="meter-key-001",
        photo_count=0,
        raw_data={"status": "approved", "delivery_cache_status": "ready"},
        status=state_repository.GroupStatus.APPROVED,
        reviewer="reviewer-a",
        review_note="ready",
        exception_note="",
        exception_reasons=[],
        exception_status=None,
        has_archive_blocker=False,
        reviewed_at=datetime.now(),
        last_photo_imported_at=None,
        updated_at=None,
    )
    project = SimpleNamespace(updated_at=None)
    events: list[object] = []
    statements: list[str] = []
    staged: list[object] = []

    class Scalars:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalars(self, statement):
            sql = str(statement)
            statements.append(sql)
            if "FROM material_groups" in sql:
                return Scalars([group])
            if "FROM photos" in sql or "FROM unmatched_records" in sql:
                return Scalars([])
            raise AssertionError(sql)

        def add(self, value):
            staged.append(value)

        def commit(self):
            events.append("commit")

    monkeypatch.setattr(local_test, "SessionLocal", lambda: Session())
    monkeypatch.setattr(local_test, "current_team_id", lambda: group.team_id)
    monkeypatch.setattr(local_test, "_postgres_project_for_team", lambda _session, _team: project)
    monkeypatch.setattr(local_test, "_unmatched_duplicate_keys", lambda _records: set())
    monkeypatch.setattr(
        local_test,
        "scan_record_to_photo_rows",
        lambda _record, _index: [{"has_image": True}],
    )
    monkeypatch.setattr(
        local_test,
        "build_photo_record",
        lambda _index, _row: {
            "id": "postgres-scan-photo",
            "source_fingerprint": "scan-photo-fingerprint",
            "sha256": "",
            "storage_key": "photos/postgres-scan-photo.jpg",
            "image_url": "/static/uploads/postgres-scan-photo.jpg",
            "source_url": "/static/uploads/postgres-scan-photo.jpg",
            "source_file": "scan-import.xlsx",
            "barcode": "M-001",
            "collector": "C-001",
            "asset_no": "MOD-001",
            "creator": "installer-a",
            "download_status": "ready",
            "category_label": "unclassified",
        },
    )
    monkeypatch.setattr(
        local_test,
        "invalidate_verification_for_group",
        lambda *_args, **_kwargs: events.append("verification"),
    )
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_changes",
        lambda *_args, **_kwargs: events.append("package"),
    )

    result = local_test._postgres_import_scan_records(
        [{"meter_match_key": group.meter_match_key, "barcode": "M-001"}]
    )

    assert result["photos_new"] == 1
    assert events == ["verification", "package", "commit"]
    imported_photo = next(item for item in staged if isinstance(item, local_test.Photo))
    assert imported_photo.raw_data["sha256_source"] == "image_url"
    assert imported_photo.sha256 == hashlib.sha256(imported_photo.image_url.encode("utf-8")).hexdigest()
    group_statements = [statement for statement in statements if "FROM material_groups" in statement]
    photo_statements = [statement for statement in statements if "FROM photos" in statement]
    assert group_statements and all("FOR UPDATE" in statement for statement in group_statements)
    assert photo_statements and all("FOR UPDATE" in statement for statement in photo_statements)
