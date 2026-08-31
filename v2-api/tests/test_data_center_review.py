from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.api.routes import groups as groups_routes
from app.api.routes import local_test as local_test_routes
from app.core import security
from app.services import local_simulation
from app.services import data_center as data_center_service
from app.services import state_repository as repository
from app.services.group_barcode_verification import evaluate_group_eligibility
from app.schemas.data_center import DataCenterQuery


def _photo(photo_id: str, category: str, sha: str, *, archive_status: str = "pending") -> dict:
    return {
        "id": photo_id,
        "category": category,
        "archive_status": archive_status,
        "sha256": sha * 64,
        "upload_status": "uploaded",
        "image_url": f"https://example.test/{photo_id}.jpg",
        "is_active": True,
    }


def _review_state(team_id: str, *, archived: bool = False) -> dict:
    archive_status = "archived" if archived else "pending"
    state = local_simulation.blank_state(team_id)
    state["barcode_maintenance_control"]["paused"] = False
    state["tasks"] = [
        {
            "id": 1,
            "terminal": "120000000001",
            "claimed_by": "admin-a",
            "total_groups": 1,
            "uploaded_count": 1,
        }
    ]
    state["groups"] = [
        {
            "id": "g-1",
            "task_id": 1,
            "terminal": "120000000001",
            "meter_no": "110000288056",
            "meter_match_key": "0000288056",
            "address": "A road",
            "status": "approved" if archived else "pending",
            "photo_count": 4,
            "collector": "COLLECTOR001",
            "module_asset_no": "MOD001",
            "construction_collector": "COLLECTOR001",
            "construction_module_asset_no": "MOD001",
            "archive_status": archive_status,
            "delivery_cache_status": "ready" if archived else "pending",
            "delivery_package_invalidation_epoch": 7,
            "barcode_verification": {
                "status": "passed",
                "evidence_version": 7,
                "meter_matched": True,
                "module_matched": True,
                "collector_matched": True,
                "recognition_source": "machine_barcode",
                "result": {"passed_count": 3, "matched_fields": ["meter", "module", "collector"], "missing_fields": []},
            },
            "group_barcode_manual_confirmed": False,
            "photos": [
                _photo("p1", "before_box", "a", archive_status=archive_status),
                _photo("p2", "collector_barcode", "b", archive_status=archive_status),
                _photo("p3", "module_meter", "c", archive_status=archive_status),
                _photo("p4", "after_box", "d", archive_status=archive_status),
            ],
        }
    ]
    state["delivery_package_jobs"] = [
        {
            "id": "package-job-1",
            "group_ids": ["g-1"],
            "status": "processing",
            "lease_owner": "package-worker",
            "lease_token": "package-lease",
            "lease_expires_at": "2026-07-23T12:00:00+00:00",
            "completed_at": "2026-07-23T11:00:00+00:00",
        }
    ]
    return state


@pytest.fixture()
def json_review_repo(monkeypatch: pytest.MonkeyPatch) -> repository.JsonStateRepository:
    team_id = f"data-center-review-{uuid4()}"
    state = _review_state(team_id)
    monkeypatch.setitem(local_simulation._team_states, team_id, state)
    monkeypatch.setattr(local_simulation, "current_team_id", lambda: team_id)
    return repository.JsonStateRepository()


def _latest_group() -> dict:
    return local_simulation.get_state()["groups"][0]


def _current_confirmation_fingerprint() -> str:
    group = _latest_group()
    snapshot, anomalies = repository._manual_classification_snapshot(group, group["photos"])
    return repository.data_center_service.manual_classification_fingerprint(snapshot, anomalies)


def _review_headers(*, username: str, role: str, team_id: str) -> dict[str, str]:
    token = security.create_access_token(
        {
            "sub": username,
            "username": username,
            "roles": [role],
            "team_id": team_id,
        }
    )
    return {"Authorization": f"bearer {token}"}


def test_data_center_anomalies_are_chinese_specific_and_ignore_missing_collector_photo() -> None:
    group = deepcopy(_review_state("anomaly-team")["groups"][0])
    group.update(
        {
            "module_asset_no": "",
            "construction_module_asset_no": "",
            "exception_status": "open",
            "exception_note": "",
            "exception_reasons": [
                "missing_collector_photo",
                "missing_module_asset_no",
                "缺少模块资产编号",
                "资料组照片不足 4 张",
            ],
            "barcode_verification": {
                "status": "mismatch",
                "evidence_version": 8,
                "meter_matched": False,
                "module_matched": False,
                "collector_matched": True,
                "result": {
                    "passed_count": 1,
                    "matched_fields": ["collector"],
                    "missing_fields": ["meter", "module"],
                },
            },
        }
    )

    anomalies = data_center_service.group_anomalies(group)
    messages = {item["message"] for item in anomalies}

    assert "缺少模块号" in messages
    assert "表号与照片识别结果不一致" in messages
    assert "模块号与台账不一致" in messages
    assert "条码识别未通过" in messages
    assert "缺采集器照片" not in messages
    assert "缺少采集器照片" not in messages
    assert "缺少模块资产编号" not in messages
    assert "资料组照片不足 4 张" not in messages
    assert "缺少必要施工照片" in messages
    assert all(item["status"] == "open" for item in anomalies)
    assert len({item["code"] for item in anomalies}) == len(anomalies)
    assert all(len(item["evidence_fingerprint"]) == 64 for item in anomalies)


def test_approved_group_exits_current_exception_while_resolved_history_is_preserved() -> None:
    group = deepcopy(_review_state("approved-exception-team")["groups"][0])
    group.update(
        {
            "status": "approved",
            "module_asset_no": "",
            "construction_module_asset_no": "",
            "exception_status": "open",
            "exception_note": "缺少模块资产编号",
            "exception_reasons": ["missing_module_asset_no"],
            "has_archive_blocker": True,
        }
    )
    fingerprint = data_center_service.group_anomaly_evidence_fingerprint(group)
    initial_anomalies = data_center_service.group_anomalies(group)
    group[data_center_service.ANOMALY_RESOLUTIONS_KEY] = {
        anomaly["code"]: {
            "evidence_fingerprint": fingerprint,
            "message": anomaly["message"],
            "resolved_by": "module_admin",
            "resolved_at": "2026-08-29T18:47:02+08:00",
            "source_page": "review_rephoto_workbench",
        }
        for anomaly in initial_anomalies
    }

    row = data_center_service.group_row(group)

    assert row["exception_status"] == ""
    assert row["anomalies"]
    assert all(anomaly["status"] == "resolved" for anomaly in row["anomalies"])
    assert all(anomaly["resolved_by"] == "module_admin" for anomaly in row["anomalies"])


def test_json_approved_review_rejects_unconfirmed_current_anomaly(
    json_review_repo: repository.JsonStateRepository,
) -> None:
    group = _latest_group()
    group.update(
        {
            "status": "incomplete",
            "exception_status": "",
            "exception_note": "人工异常",
            "exception_reasons": ["manual_quality"],
            "has_archive_blocker": False,
        }
    )
    before = deepcopy(group)

    with pytest.raises(ValueError, match="未确认"):
        json_review_repo.review_group("g-1", "approved", "module_admin")

    assert _latest_group() == before


def test_json_approved_review_bulk_resolves_current_anomalies_and_audits(
    json_review_repo: repository.JsonStateRepository,
) -> None:
    """Catches bulk approval changing status without durable per-anomaly and aggregate audit history."""
    group = _latest_group()
    group.update(
        {
            "status": "incomplete",
            "module_asset_no": "",
            "construction_module_asset_no": "",
            "exception_status": "open",
            "exception_reasons": ["manual_quality"],
            "has_archive_blocker": True,
        }
    )
    anomalies = data_center_service.group_anomalies(group)
    expected = {item["code"]: item["evidence_fingerprint"] for item in anomalies}

    reviewed = json_review_repo.review_group(
        "g-1",
        "approved",
        "module_admin",
        "全部异常已人工核实",
        resolve_all_anomalies=True,
        expected_open_anomalies=expected,
        source_page="review_rephoto_workbench",
    )

    assert reviewed["status"] == "approved"
    assert all(item["status"] == "resolved" for item in data_center_service.group_anomalies(reviewed))
    resolutions = reviewed[data_center_service.ANOMALY_RESOLUTIONS_KEY]
    assert set(resolutions) == set(expected)
    assert all(item["resolved_by"] == "module_admin" for item in resolutions.values())
    assert all(item["resolved_at"] for item in resolutions.values())
    assert all(item["source_page"] == "review_rephoto_workbench" for item in resolutions.values())
    assert {
        code: item["confirmed_evidence_fingerprint"]
        for code, item in resolutions.items()
    } == expected
    per_anomaly_audits = [
        event
        for event in local_simulation.get_state()["audit_events"]
        if event["action"] == "data_center_anomaly_resolved"
    ]
    assert len(per_anomaly_audits) == len(expected)
    assert {
        event["payload"]["anomaly_code"]: event["payload"]["confirmed_evidence_fingerprint"]
        for event in per_anomaly_audits
    } == expected
    assert all(
        event["payload"]["source_page"] == "review_rephoto_workbench"
        for event in per_anomaly_audits
    )
    payload = _audit_payload("data_center_anomalies_bulk_resolved_on_approval")
    assert payload["group_id"] == "g-1"
    assert payload["terminal"] == "120000000001"
    assert payload["anomaly_count"] == len(expected)
    assert payload["anomaly_codes"] == sorted(expected)
    assert payload["source_page"] == "review_rephoto_workbench"


def test_json_approved_review_bulk_rejects_changed_anomaly_snapshot_without_writes(
    json_review_repo: repository.JsonStateRepository,
) -> None:
    """Catches approving anomalies that differ from those shown in the confirmation dialog."""
    group = _latest_group()
    group["module_asset_no"] = ""
    group["construction_module_asset_no"] = ""
    anomalies = data_center_service.group_anomalies(group)
    expected = {item["code"]: item["evidence_fingerprint"] for item in anomalies}
    expected[next(iter(expected))] = "0" * 64
    before = deepcopy(local_simulation.get_state())

    with pytest.raises(repository.AnomalyResolutionConflict, match="变化"):
        json_review_repo.review_group(
            "g-1",
            "approved",
            "module_admin",
            resolve_all_anomalies=True,
            expected_open_anomalies=expected,
        )

    assert local_simulation.get_state() == before


def test_json_approved_review_closes_resolved_exception_state_and_keeps_history(
    json_review_repo: repository.JsonStateRepository,
) -> None:
    group = _latest_group()
    group.update(
        {
            "status": "exception",
            "exception_status": "open",
            "exception_note": "人工异常",
            "exception_reasons": ["manual_quality"],
            "has_archive_blocker": True,
        }
    )
    anomalies = data_center_service.group_anomalies(group)
    fingerprint = anomalies[0]["evidence_fingerprint"]
    group[data_center_service.ANOMALY_RESOLUTIONS_KEY] = {
        anomaly["code"]: {
            "evidence_fingerprint": fingerprint,
            "message": anomaly["message"],
            "resolved_by": "module_admin",
            "resolved_at": "2026-08-29T18:47:02+08:00",
            "source_page": "review_rephoto_workbench",
        }
        for anomaly in anomalies
    }

    reviewed = json_review_repo.review_group("g-1", "approved", "module_admin", "资料核对完成")

    assert reviewed["status"] == "approved"
    assert reviewed["exception_status"] == ""
    assert reviewed["has_archive_blocker"] is False
    assert reviewed["exception_note"] == "人工异常"
    assert reviewed["exception_reasons"] == ["manual_quality"]
    history = reviewed[data_center_service.ANOMALY_RESOLUTIONS_KEY]
    assert history
    assert all(item["resolved_by"] == "module_admin" for item in history.values())
    assert all(item["status"] == "resolved" for item in data_center_service.group_anomalies(reviewed))


def test_json_data_center_anomaly_resolution_keeps_history_and_reopens_after_evidence_change(
    json_review_repo: repository.JsonStateRepository,
) -> None:
    group = _latest_group()
    group["module_asset_no"] = ""
    group["construction_module_asset_no"] = ""
    detail = json_review_repo.get_data_center_detail(kind="group", item_id="g-1")
    assert detail is not None
    anomaly = next(item for item in detail["anomalies"] if item["code"] == "module_missing")

    resolved = json_review_repo.resolve_data_center_group_anomaly(
        "g-1",
        "module_missing",
        actor="admin-a",
        expected_evidence_fingerprint=anomaly["evidence_fingerprint"],
        source_page="review_rephoto_workbench",
    )
    resolved_anomaly = next(item for item in resolved["anomalies"] if item["code"] == "module_missing")

    assert resolved_anomaly["status"] == "resolved"
    assert resolved_anomaly["resolved_by"] == "admin-a"
    assert resolved_anomaly["resolved_at"]
    payload = _audit_payload("data_center_anomaly_resolved")
    assert payload["group_id"] == "g-1"
    assert payload["anomaly_code"] == "module_missing"
    assert payload["anomaly_message"] == "缺少模块号"
    assert payload["source_page"] == "review_rephoto_workbench"

    group = _latest_group()
    group["address"] = "资料变化后的地址"
    reopened = json_review_repo.get_data_center_detail(kind="group", item_id="g-1")
    assert reopened is not None
    reopened_anomaly = next(item for item in reopened["anomalies"] if item["code"] == "module_missing")
    assert reopened_anomaly["status"] == "open"
    assert reopened_anomaly["resolved_by"] == ""
    assert reopened_anomaly["resolved_at"] == ""


def test_data_center_anomaly_resolution_route_uses_server_actor_and_rejects_stale_evidence(
    monkeypatch: pytest.MonkeyPatch,
    json_review_repo: repository.JsonStateRepository,
) -> None:
    group = _latest_group()
    group["module_asset_no"] = ""
    group["construction_module_asset_no"] = ""
    detail = json_review_repo.get_data_center_detail(kind="group", item_id="g-1")
    assert detail is not None
    anomaly = next(item for item in detail["anomalies"] if item["code"] == "module_missing")
    team_id = local_simulation.get_state()["team_id"]
    monkeypatch.setattr(groups_routes, "state_repository", lambda: json_review_repo)
    client = TestClient(main_module.create_app())
    headers = _review_headers(username="admin-route", role="admin", team_id=team_id)

    stale = client.post(
        "/groups/data-center/groups/g-1/anomalies/module_missing/resolve",
        headers=headers,
        json={"expected_evidence_fingerprint": "0" * 64, "source_page": "review_rephoto_workbench"},
    )
    assert stale.status_code == 409

    response = client.post(
        "/groups/data-center/groups/g-1/anomalies/module_missing/resolve",
        headers=headers,
        json={
            "expected_evidence_fingerprint": anomaly["evidence_fingerprint"],
            "source_page": "review_rephoto_workbench",
        },
    )

    assert response.status_code == 200
    resolved = next(item for item in response.json()["data"]["anomalies"] if item["code"] == "module_missing")
    assert resolved["status"] == "resolved"
    assert resolved["resolved_by"] == "admin-route"


def test_admin_can_approve_data_center_group_and_audit_actor(
    monkeypatch: pytest.MonkeyPatch,
    json_review_repo: repository.JsonStateRepository,
) -> None:
    """Catches bypassing review_group and therefore losing its durable actor/audit path."""
    state = local_simulation.get_state()
    team_id = state["team_id"]
    state["tasks"][0]["claimed_by"] = "admin"
    state["groups"][0]["status"] = "pending"
    before_events = len(state["review_events"])
    monkeypatch.setattr(groups_routes, "state_repository", lambda: json_review_repo)
    client = TestClient(main_module.create_app())

    response = client.patch(
        "/groups/data-center/groups/g-1/review",
        headers=_review_headers(username="admin", role="admin", team_id=team_id),
        json={"status": "approved", "note": "资料核对完成"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "approved"
    committed = local_simulation.get_state()
    assert len(committed["review_events"]) == before_events + 1
    assert committed["review_events"][-1]["group_id"] == "g-1"
    assert committed["review_events"][-1]["reviewer"] == "admin"
    assert committed["review_events"][-1]["note"] == "资料核对完成"


def test_admin_can_bulk_resolve_current_anomalies_and_approve_with_server_actor(
    monkeypatch: pytest.MonkeyPatch,
    json_review_repo: repository.JsonStateRepository,
) -> None:
    """Catches trusting a client actor or dropping the anomaly evidence snapshot at the review route."""
    state = local_simulation.get_state()
    team_id = state["team_id"]
    group = state["groups"][0]
    group["module_asset_no"] = ""
    group["construction_module_asset_no"] = ""
    detail = json_review_repo.get_data_center_detail(kind="group", item_id="g-1")
    expected = {
        item["code"]: item["evidence_fingerprint"]
        for item in detail["anomalies"]
        if item["status"] == "open"
    }
    monkeypatch.setattr(groups_routes, "state_repository", lambda: json_review_repo)
    client = TestClient(main_module.create_app())
    headers = _review_headers(username="admin-route", role="admin", team_id=team_id)

    stale = client.patch(
        "/groups/data-center/groups/g-1/review",
        headers=headers,
        json={
            "status": "approved",
            "resolve_all_anomalies": True,
            "expected_open_anomalies": {**expected, next(iter(expected)): "0" * 64},
            "source_page": "review_rephoto_workbench",
        },
    )
    assert stale.status_code == 409

    response = client.patch(
        "/groups/data-center/groups/g-1/review",
        headers=headers,
        json={
            "status": "approved",
            "resolve_all_anomalies": True,
            "expected_open_anomalies": expected,
            "source_page": "review_rephoto_workbench",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "approved"
    reloaded = json_review_repo.get_data_center_detail(kind="group", item_id="g-1")
    assert reloaded is not None
    assert all(item["status"] == "resolved" for item in reloaded["anomalies"])
    assert all(item["resolved_by"] == "admin-route" for item in reloaded["anomalies"])


def test_admin_data_center_review_ignores_removed_reviewer_claim(
    monkeypatch: pytest.MonkeyPatch,
    json_review_repo: repository.JsonStateRepository,
) -> None:
    """Catches the removed reviewer-claim workflow blocking an admin review decision."""
    state = local_simulation.get_state()
    team_id = state["team_id"]
    state["tasks"][0]["claimed_by"] = "former-reviewer"
    state["groups"][0]["status"] = "exception"
    monkeypatch.setattr(groups_routes, "state_repository", lambda: json_review_repo)
    client = TestClient(main_module.create_app())

    response = client.patch(
        "/groups/data-center/groups/g-1/review",
        headers=_review_headers(username="admin", role="admin", team_id=team_id),
        json={"status": "incomplete", "note": "管理员复核", "exception_note": "资料异常"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "incomplete"
    assert _latest_group()["reviewer"] == "admin"


def test_manual_classification_confirmation_requires_anomaly_acknowledgement_and_audits_snapshot(
    json_review_repo: repository.JsonStateRepository,
) -> None:
    """Catches silently accepting abnormal evidence or omitting the durable classification snapshot."""
    group = _latest_group()
    group["status"] = "pending"
    group["photos"][0]["category"] = "unclassified"
    group["barcode_verification"]["status"] = "unreadable"

    with pytest.raises(ValueError, match="确认异常"):
        json_review_repo.manual_confirm_group_classification(
            "g-1",
            actor="admin-a",
            acknowledge_anomalies=False,
            expected_evidence_fingerprint=_current_confirmation_fingerprint(),
            source_page="review_rephoto_workbench",
        )

    result = json_review_repo.manual_confirm_group_classification(
        "g-1",
        actor="admin-a",
        acknowledge_anomalies=True,
        expected_evidence_fingerprint=_current_confirmation_fingerprint(),
        source_page="review_rephoto_workbench",
    )
    confirmation = _latest_group()["classification_manual_confirmation"]
    payload = _audit_payload("classification_manual_confirmed")

    assert result["status"] == "approved"
    assert confirmation["actor"] == "admin-a"
    assert confirmation["acknowledged_anomalies"] is True
    assert confirmation["anomalies"] == ["unclassified_photos", "barcode_verification_required"]
    assert confirmation["photo_snapshot"][0] == {
        "photo_id": "p1",
        "category": "unclassified",
        "sha256": "a" * 64,
    }
    assert payload["source_page"] == "review_rephoto_workbench"
    assert payload["actor"] == "admin-a"
    assert payload["anomalies"] == confirmation["anomalies"]
    assert payload["photo_snapshot"] == confirmation["photo_snapshot"]


def test_admin_can_manually_confirm_group_classification_through_api(
    monkeypatch: pytest.MonkeyPatch,
    json_review_repo: repository.JsonStateRepository,
) -> None:
    """Catches a missing admin-only HTTP path or loss of the token-bound actor."""
    state = local_simulation.get_state()
    team_id = state["team_id"]
    monkeypatch.setattr(groups_routes, "state_repository", lambda: json_review_repo)
    client = TestClient(main_module.create_app())

    response = client.post(
        "/groups/data-center/groups/g-1/classification-manual-confirm",
        headers=_review_headers(username="admin", role="admin", team_id=team_id),
        json={
            "acknowledge_anomalies": False,
            "expected_evidence_fingerprint": _current_confirmation_fingerprint(),
            "source_page": "review_rephoto_workbench",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "approved"
    assert _latest_group()["classification_manual_confirmation"]["actor"] == "admin"


def test_admin_can_delete_data_center_photo_without_a_review_claim(
    monkeypatch: pytest.MonkeyPatch,
    json_review_repo: repository.JsonStateRepository,
) -> None:
    """Catches routing the workbench through the legacy reviewer-claim deletion contract."""
    state = local_simulation.get_state()
    team_id = state["team_id"]
    state["tasks"][0]["claimed_by"] = "another-user"
    monkeypatch.setattr(groups_routes, "state_repository", lambda: json_review_repo)
    client = TestClient(main_module.create_app())

    response = client.delete(
        "/groups/data-center/groups/g-1/photos/p2",
        headers=_review_headers(username="admin-delete", role="admin", team_id=team_id),
    )

    assert response.status_code == 200
    assert [photo["id"] for photo in response.json()["data"]["group"]["photos"]] == ["p1", "p3", "p4"]
    assert [photo["id"] for photo in _latest_group()["photos"]] == ["p1", "p3", "p4"]
    event = local_simulation.get_state()["photo_events"][-1]
    assert event["photo_id"] == "p2"
    assert event["reviewer"] == "admin-delete"


def test_data_center_detail_exposes_explicit_manual_classification_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    json_review_repo: repository.JsonStateRepository,
) -> None:
    """Catches forcing clients to infer a manual confirmation from the generic approved status."""
    state = local_simulation.get_state()
    team_id = state["team_id"]
    monkeypatch.setattr(groups_routes, "state_repository", lambda: json_review_repo)
    client = TestClient(main_module.create_app())
    headers = _review_headers(username="admin", role="admin", team_id=team_id)

    confirmed = client.post(
        "/groups/data-center/groups/g-1/classification-manual-confirm",
        headers=headers,
        json={
            "acknowledge_anomalies": False,
            "expected_evidence_fingerprint": _current_confirmation_fingerprint(),
            "source_page": "review_rephoto_workbench",
        },
    )
    detail = client.get("/groups/data-center/group/g-1", headers=headers)

    assert confirmed.status_code == 200
    assert detail.status_code == 200
    marker = detail.json()["data"]["classification_manual_confirmation"]
    assert marker["actor"] == "admin"
    assert marker["acknowledged_anomalies"] is False
    assert marker["photo_snapshot"][0] == {
        "photo_id": "p1",
        "category": "before_box",
        "sha256": "a" * 64,
    }


def test_reclassifying_photo_revokes_manual_classification_confirmation(
    json_review_repo: repository.JsonStateRepository,
) -> None:
    """Catches stale manual confirmation surviving a later category change."""
    json_review_repo.manual_confirm_group_classification(
        "g-1",
        actor="admin-a",
        acknowledge_anomalies=False,
        expected_evidence_fingerprint=_current_confirmation_fingerprint(),
        source_page="review_rephoto_workbench",
    )
    group = _latest_group()
    group["barcode_verification"]["status"] = "pending"

    json_review_repo.classify_data_center_group_photo(
        "g-1",
        "p1",
        "collector_barcode",
        actor="admin-a",
        reason="重新分类",
        source_page="review_rephoto_workbench",
    )

    group = _latest_group()
    assert group["status"] == "unreviewed"
    assert group.get("classification_manual_confirmation") is None
    revoked = _audit_payload("classification_manual_confirmation_revoked")
    assert revoked["actor"] == "admin-a"
    assert revoked["reason"] == "重新分类"


def test_json_confirmation_rejects_concurrent_photo_evidence_change_without_audit(
    monkeypatch: pytest.MonkeyPatch,
    json_review_repo: repository.JsonStateRepository,
) -> None:
    state = local_simulation.get_state()
    team_id = state["team_id"]
    monkeypatch.setattr(groups_routes, "state_repository", lambda: json_review_repo)
    client = TestClient(main_module.create_app())
    headers = _review_headers(username="admin", role="admin", team_id=team_id)
    detail = client.get("/groups/data-center/group/g-1", headers=headers)
    fingerprint = detail.json()["data"]["classification_confirmation_fingerprint"]
    before_confirm_audits = [
        event for event in state["audit_events"]
        if event.get("action") == "classification_manual_confirmed"
    ]

    state["groups"][0]["photos"][0]["category"] = "collector_barcode"
    response = client.post(
        "/groups/data-center/groups/g-1/classification-manual-confirm",
        headers=headers,
        json={
            "acknowledge_anomalies": True,
            "expected_evidence_fingerprint": fingerprint,
            "source_page": "review_rephoto_workbench",
        },
    )

    assert response.status_code == 409
    assert "重新加载" in response.json()["detail"]
    assert _latest_group().get("classification_manual_confirmation") is None
    assert [
        event for event in state["audit_events"]
        if event.get("action") == "classification_manual_confirmed"
    ] == before_confirm_audits


def test_legacy_classify_route_repository_path_revokes_only_when_category_changes(
    json_review_repo: repository.JsonStateRepository,
) -> None:
    json_review_repo.manual_confirm_group_classification(
        "g-1", actor="admin-a", acknowledge_anomalies=False,
        expected_evidence_fingerprint=_current_confirmation_fingerprint(),
    )
    before_events = len(local_simulation.get_state()["audit_events"])

    json_review_repo.classify_photo("g-1", "p1", "before_box", "admin-a")
    assert _latest_group().get("classification_manual_confirmation") is not None
    assert len(local_simulation.get_state()["audit_events"]) == before_events

    json_review_repo.classify_photo("g-1", "p1", "collector_barcode", "admin-a")

    assert _latest_group().get("classification_manual_confirmation") is None
    assert _latest_group()["status"] == "unreviewed"
    revoked = _audit_payload("classification_manual_confirmation_revoked")
    assert revoked["photo_id"] == "p1"


def test_legacy_photo_category_http_route_revokes_manual_confirmation_on_change(
    monkeypatch: pytest.MonkeyPatch,
    json_review_repo: repository.JsonStateRepository,
) -> None:
    json_review_repo.manual_confirm_group_classification(
        "g-1",
        actor="admin-a",
        acknowledge_anomalies=False,
        expected_evidence_fingerprint=_current_confirmation_fingerprint(),
    )
    team_id = local_simulation.get_state()["team_id"]
    monkeypatch.setattr(local_test_routes, "state_repository", lambda: json_review_repo)
    client = TestClient(main_module.create_app())
    headers = _review_headers(username="admin-a", role="admin", team_id=team_id)

    unchanged = client.patch(
        "/local-test/groups/g-1/photos/p1/category",
        headers=headers,
        json={"category": "before_box", "reviewer": "admin-a"},
    )
    assert unchanged.status_code == 200
    assert _latest_group().get("classification_manual_confirmation") is not None

    changed = client.patch(
        "/local-test/groups/g-1/photos/p1/category",
        headers=headers,
        json={"category": "collector_barcode", "reviewer": "admin-a"},
    )

    assert changed.status_code == 200
    assert changed.json()["data"]["category"] == "collector_barcode"
    assert _latest_group().get("classification_manual_confirmation") is None
    assert _latest_group()["status"] == "unreviewed"
    assert _audit_payload("classification_manual_confirmation_revoked")["photo_id"] == "p1"


def test_legacy_barcode_rescan_category_context_preserves_classification_and_confirmation(
    json_review_repo: repository.JsonStateRepository,
) -> None:
    json_review_repo.manual_confirm_group_classification(
        "g-1", actor="admin-a", acknowledge_anomalies=False,
        expected_evidence_fingerprint=_current_confirmation_fingerprint(),
    )
    before_marker = deepcopy(_latest_group()["classification_manual_confirmation"])

    result = json_review_repo.rescan_photo_barcode(
        "g-1", "p1", "admin-a", "collector_barcode"
    )

    assert result["category"] == "before_box"
    assert _latest_group()["photos"][0]["category"] == "before_box"
    assert _latest_group()["classification_manual_confirmation"] == before_marker
    assert _latest_group()["status"] == "approved"
    revoked_events = [
        event
        for event in local_simulation.get_state()["audit_events"]
        if event.get("action") == "classification_manual_confirmation_revoked"
    ]
    assert revoked_events == []


def test_data_center_category_carrying_rescan_revokes_marker_only_for_real_evidence_change(
    json_review_repo: repository.JsonStateRepository,
) -> None:
    json_review_repo.manual_confirm_group_classification(
        "g-1", actor="admin-a", acknowledge_anomalies=False,
        expected_evidence_fingerprint=_current_confirmation_fingerprint(),
    )
    json_review_repo.rescan_data_center_group_photo_barcode(
        "g-1", "p1", actor="admin-a", category="before_box"
    )
    assert _latest_group().get("classification_manual_confirmation") is not None

    json_review_repo.rescan_data_center_group_photo_barcode(
        "g-1", "p1", actor="admin-a", category="collector_barcode"
    )

    assert _latest_group().get("classification_manual_confirmation") is None
    assert _latest_group()["status"] == "unreviewed"
    revoked_events = [
        event
        for event in local_simulation.get_state()["audit_events"]
        if event.get("action") == "classification_manual_confirmation_revoked"
    ]
    assert len(revoked_events) == 1


@pytest.mark.parametrize(
    "operation",
    [
        "manual_confirm_group_classification",
        "classify_photo",
        "classify_data_center_group_photo",
        "rescan_data_center_group_photo_barcode",
    ],
)
def test_dual_classification_evidence_writes_fail_before_json_or_postgres_mutates(
    monkeypatch: pytest.MonkeyPatch,
    json_review_repo: repository.JsonStateRepository,
    operation: str,
) -> None:
    if operation != "manual_confirm_group_classification":
        json_review_repo.manual_confirm_group_classification(
            "g-1", actor="admin-a", acknowledge_anomalies=False,
            expected_evidence_fingerprint=_current_confirmation_fingerprint(),
        )
    before = deepcopy(local_simulation.get_state())
    monkeypatch.setattr(
        repository.DualWriteStateRepository,
        "postgres_repository_factory",
        staticmethod(lambda: pytest.fail("PostgreSQL writer must not be constructed")),
    )
    dual = repository.DualWriteStateRepository()

    with pytest.raises(repository.StateBackendNotReady, match="before either backend mutated"):
        if operation == "manual_confirm_group_classification":
            dual.manual_confirm_group_classification(
                "g-1", actor="admin-a", acknowledge_anomalies=False,
                expected_evidence_fingerprint=_current_confirmation_fingerprint(),
            )
        elif operation == "classify_photo":
            dual.classify_photo("g-1", "p1", "collector_barcode", "admin-a")
        elif operation == "classify_data_center_group_photo":
            dual.classify_data_center_group_photo(
                "g-1", "p1", "collector_barcode", actor="admin-a"
            )
        else:
            dual.rescan_data_center_group_photo_barcode(
                "g-1", "p1", actor="admin-a", category="collector_barcode"
            )

    assert local_simulation.get_state() == before


@pytest.mark.parametrize("status", ["approved", "incomplete"])
def test_data_center_review_status_survives_list_and_detail_reload(
    monkeypatch: pytest.MonkeyPatch,
    json_review_repo: repository.JsonStateRepository,
    status: str,
) -> None:
    """Catches dropping the persisted review state at the data-center serialization boundary."""
    state = local_simulation.get_state()
    team_id = state["team_id"]
    state["tasks"][0]["claimed_by"] = "admin"
    state["groups"][0]["status"] = "pending"
    monkeypatch.setattr(groups_routes, "state_repository", lambda: json_review_repo)
    client = TestClient(main_module.create_app())
    headers = _review_headers(username="admin", role="admin", team_id=team_id)

    decision = client.patch(
        "/groups/data-center/groups/g-1/review",
        headers=headers,
        json={"status": status, "note": "reviewed", "exception_note": "missing" if status == "incomplete" else ""},
    )
    detail = client.get("/groups/data-center/group/g-1", headers=headers)
    listing = client.get("/groups/data-center", headers=headers)

    assert decision.status_code == 200
    assert detail.status_code == 200
    assert listing.status_code == 200
    persisted = _latest_group()["status"]
    list_row = next(item for item in listing.json()["data"]["items"] if item["id"] == "g-1")
    observed = {
        "persisted": persisted,
        "detail": detail.json()["data"].get("status"),
        "list": list_row.get("status"),
    }
    assert observed == {"persisted": status, "detail": status, "list": status}


@pytest.mark.parametrize("status", ["approved", "incomplete", "exception"])
def test_constructor_cannot_decide_data_center_review_before_repository(
    monkeypatch: pytest.MonkeyPatch,
    json_review_repo: repository.JsonStateRepository,
    status: str,
) -> None:
    """Catches repository access or state mutation before the administrator dependency rejects."""
    state = local_simulation.get_state()
    team_id = state["team_id"]
    before = deepcopy(state)
    repository_accesses = 0

    def counted_repository():
        nonlocal repository_accesses
        repository_accesses += 1
        return json_review_repo

    monkeypatch.setattr(groups_routes, "state_repository", counted_repository)
    client = TestClient(main_module.create_app())

    response = client.patch(
        "/groups/data-center/groups/g-1/review",
        headers=_review_headers(username="constructor", role="constructor", team_id=team_id),
        json={"status": status, "note": "x", "exception_note": "x"},
    )

    assert response.status_code == 403
    assert repository_accesses == 0
    assert local_simulation.get_state() == before


def _audit_has_before_after(action: str, field: str) -> bool:
    for event in local_simulation.get_state()["audit_events"]:
        if event.get("action") != action:
            continue
        payload = event.get("payload") or {}
        previous = payload.get("previous") or payload.get("before") or {}
        updates = payload.get("updates") or payload.get("after") or {}
        if field in previous and field in updates:
            return True
    return False


def _audit_payload(action: str) -> dict:
    for event in reversed(local_simulation.get_state()["audit_events"]):
        if event.get("action") == action:
            return event.get("payload") or {}
    raise AssertionError(f"missing audit action {action}")


def _mark_future_authoritative_barcode_pass(group: dict, *, photo_id: str, category: str) -> None:
    future = deepcopy(group)
    photo = next(item for item in future["photos"] if item["id"] == photo_id)
    photo["category"] = category
    eligibility = evaluate_group_eligibility(future)
    assert eligibility.status == "pending"
    assert eligibility.evidence_fingerprint
    verification = group["barcode_verification"]
    verification.update(
        {
            "status": "passed",
            "evidence_fingerprint": eligibility.evidence_fingerprint,
            "meter_matched": True,
            "module_matched": True,
            "collector_matched": True,
            "recognition_source": "machine_barcode",
            "auto_archive_status": "pending",
            "result": {
                "passed_count": 3,
                "matched_fields": ["meter", "module", "collector"],
                "missing_fields": [],
                "machine_barcode_values": ["110000288056", "MOD001", "COLLECTOR001"],
            },
        }
    )


def test_data_center_edit_invalidates_barcode_archive_and_preserves_retired_delivery_history(
    json_review_repo: repository.JsonStateRepository,
) -> None:
    group = _latest_group()
    group["status"] = "approved"
    group["archive_status"] = "archived"
    group["delivery_cache_status"] = "ready"
    for photo in group["photos"]:
        photo["archive_status"] = "archived"
    delivery_history = deepcopy(local_simulation.get_state()["delivery_package_jobs"])
    invalidation_epoch = group["delivery_package_invalidation_epoch"]
    result = json_review_repo.update_data_center_group(
        group_id="g-1",
        patch={"module_asset_no": "MOD002"},
        actor="admin-a",
        reason="更正模块号",
        source_page="data_center",
    )
    group = _latest_group()

    assert result["archive_status"] != "archived"
    assert group["barcode_verification"]["status"] == "pending"
    assert group["delivery_package_invalidation_epoch"] == invalidation_epoch
    assert local_simulation.get_state()["delivery_package_jobs"] == delivery_history
    assert _audit_has_before_after("data_center_group_updated", "module_asset_no")
    update_payload = _audit_payload("data_center_group_updated")
    invalidation_payload = _audit_payload("data_center_archive_invalidated")
    for payload in (update_payload, invalidation_payload):
        assert payload["source_page"] == "data_center"
        assert payload["source"] == "data_center"
        assert payload["actor"] == "admin-a"
        assert payload["reason"]
        assert "before" in payload
        assert "after" in payload


def test_json_data_center_edit_persists_all_identity_fields_on_active_photos(
    json_review_repo: repository.JsonStateRepository,
) -> None:
    group = _latest_group()
    group["construction_module_asset_no"] = "MOD001"
    group["construction_collector"] = "COLLECTOR001"

    json_review_repo.update_data_center_group(
        group_id="g-1",
        patch={
            "meter_no": "110000288099",
            "module_asset_no": "MOD099",
            "collector": "COLLECTOR099",
        },
        actor="admin-a",
        reason="核对三项号码",
        source_page="data_center",
    )

    group = _latest_group()
    assert group["meter_no"] == "110000288099"
    assert group["meter_match_key"] == "0000288099"
    assert group["module_asset_no"] == "MOD099"
    assert group["collector"] == "COLLECTOR099"
    assert group["construction_module_asset_no"] == "MOD099"
    assert group["construction_collector"] == "COLLECTOR099"
    for photo in group["photos"]:
        assert photo["barcode"] == "110000288099"
        assert photo["asset_no"] == "MOD099"
        assert photo["collector"] == "COLLECTOR099"


def test_json_data_center_edit_replaces_stale_construction_module_when_source_already_matches(
    json_review_repo: repository.JsonStateRepository,
) -> None:
    group = _latest_group()
    group["module_asset_no"] = "MOD099"
    group["construction_module_asset_no"] = "MOD001"
    for photo in group["photos"]:
        photo["asset_no"] = "MOD099"

    json_review_repo.update_data_center_group(
        group_id="g-1",
        patch={"module_asset_no": "MOD099"},
        actor="admin-a",
        reason="覆盖旧施工模块号",
        source_page="data_center",
    )

    detail = json_review_repo.get_data_center_detail(kind="group", item_id="g-1")
    assert detail is not None
    assert detail["module_asset_no"] == "MOD099"
    assert _latest_group()["construction_module_asset_no"] == "MOD099"


def test_json_data_center_classifies_final_photo_then_auto_archives_without_delivery_enqueue(
    json_review_repo: repository.JsonStateRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = local_simulation.get_state()
    group = state["groups"][0]
    state["tasks"][0]["claimed_by"] = "other-reviewer"
    group["status"] = "pending"
    group["archive_status"] = "pending"
    for photo in group["photos"]:
        photo["storage_type"] = "oss"
        photo["storage_bucket"] = "module-manager-test"
        photo["storage_key"] = f"groups/g-1/{photo['id']}.jpg"
    for photo in group["photos"][:3]:
        label = local_simulation.PHOTO_CATEGORIES[str(photo["category"])]
        photo["archive_filename"] = local_simulation.build_archive_filename(label, photo["image_url"])
        photo["archived_at"] = "2026-07-23T10:00:00+00:00"
    group["photos"][3]["category"] = "unclassified"
    group["photos"][3]["archive_status"] = "pending"
    group["delivery_cache_status"] = "pending"
    state["delivery_package_jobs"] = []
    _mark_future_authoritative_barcode_pass(group, photo_id="p4", category="after_box")
    original_begin = local_simulation.begin_authoritative_json_write
    nested_begin_attempts = 0

    def fail_on_nested_write(team_id: str | None = None):
        nonlocal nested_begin_attempts
        if local_simulation.active_authoritative_json_write(team_id) is not None:
            nested_begin_attempts += 1
            raise AssertionError("delivery package request must reuse the active JSON write")
        return original_begin(team_id)

    monkeypatch.setattr(local_simulation, "begin_authoritative_json_write", fail_on_nested_write)

    result = json_review_repo.classify_data_center_group_photo(
        "g-1",
        "p4",
        "after_box",
        actor="admin-a",
        reason="补齐最后一张分类",
        source_page="data_center",
    )

    committed_state = local_simulation.get_state()
    group = committed_state["groups"][0]
    delivery_jobs = committed_state["delivery_cache_jobs"]
    package_jobs = committed_state["delivery_package_jobs"]

    assert result["archive_status"] == "archived"
    assert group["status"] == "approved"
    assert group["barcode_verification"]["auto_archive_status"] == "archived"
    assert all(photo["archive_status"] == "archived" for photo in group["photos"])
    assert delivery_jobs == []
    assert package_jobs == []
    assert nested_begin_attempts == 0
    payload = _audit_payload("data_center_photo_classified")
    assert payload["source_page"] == "data_center"
    assert payload["source"] == "data_center"
    assert payload["actor"] == "admin-a"
    assert payload["reason"] == "补齐最后一张分类"
    assert payload["before"]["category"] == "unclassified"
    assert payload["after"]["category"] == "after_box"


def test_manual_confirmation_requires_reason_and_auto_archives_when_ready(
    json_review_repo: repository.JsonStateRepository,
) -> None:
    state = local_simulation.get_state()
    delivery_history = deepcopy(
        {
            "delivery_cache_jobs": state["delivery_cache_jobs"],
            "delivery_package_jobs": state["delivery_package_jobs"],
        }
    )
    with pytest.raises(ValueError, match="原因"):
        json_review_repo.manual_confirm_group_barcode(
            "g-1",
            actor="admin-a",
            reason="",
            source_page="data_center",
            meter_no="110000288056",
            module_asset_no="MOD001",
            collector="COLLECTOR001",
            photo_ids=["p1", "p2", "p3", "p4"],
        )

    result = json_review_repo.manual_confirm_group_barcode(
        "g-1",
        actor="admin-a",
        reason="现场照片与台账一致",
        source_page="data_center",
        meter_no="110000288056",
        module_asset_no="MOD001",
        collector="COLLECTOR001",
        photo_ids=["p1", "p2", "p3", "p4"],
    )
    group = _latest_group()

    assert result["barcode_status"] == "manual_confirmed"
    assert result["archive_status"] == "archived"
    assert group["status"] == "approved"
    assert local_simulation.get_state()["delivery_cache_jobs"] == delivery_history["delivery_cache_jobs"]
    assert local_simulation.get_state()["delivery_package_jobs"] == delivery_history["delivery_package_jobs"]
    payload = _audit_payload("group_barcode_manual_confirmed")
    assert payload["source_page"] == "data_center"
    assert payload["source"] == "data_center"
    assert payload["actor"] == "admin-a"
    assert payload["reason"] == "现场照片与台账一致"
    assert "before" in payload
    assert "after" in payload


def test_unmatched_finalize_rejects_placeholder_or_ambiguous_target(
    json_review_repo: repository.JsonStateRepository,
) -> None:
    before = deepcopy(local_simulation.get_state())

    with pytest.raises(ValueError, match="唯一"):
        json_review_repo.finalize_unmatched_to_group(
            unmatched_id="unmatched-1",
            actor="admin-a",
            terminal="00000000",
            meter_no="00000000",
            candidate_key="manual:00000000",
            expected_version=1,
            source_page="data_center",
        )

    assert local_simulation.get_state() == before


def test_data_center_return_exception_uses_admin_path_and_complete_audit(
    json_review_repo: repository.JsonStateRepository,
) -> None:
    result = json_review_repo.return_data_center_group_to_exception_order(
        "g-1",
        actor="admin-a",
        category="barcode_error",
        note="数据中台退回异常",
        reason="照片证据需复核",
        source_page="data_center",
    )

    group = _latest_group()
    assert result["group"]["id"] == "g-1"
    assert group["exception_status"] == "open"
    payload = _audit_payload("group_returned_to_exception_order")
    assert payload["source_page"] == "data_center"
    assert payload["source"] == "data_center"
    assert payload["actor"] == "admin-a"
    assert payload["reason"] == "照片证据需复核"
    assert payload["before"]["exception_status"] == ""
    assert payload["after"]["exception_status"] == "open"


def test_data_center_exception_none_filter_returns_no_exception_rows(
    json_review_repo: repository.JsonStateRepository,
) -> None:
    state = local_simulation.get_state()
    state["groups"].append(
        {
            **deepcopy(state["groups"][0]),
            "id": "g-open",
            "exception_status": "open",
            "status": "rejected",
        }
    )

    page = json_review_repo.list_data_center_rows(
        DataCenterQuery(data_type="group", exception_status="none", page=1, page_size=20)
    )

    assert page["total"] == 1
    assert [item["id"] for item in page["items"]] == ["g-1"]
    assert page["items"][0]["exception_status"] == ""


def test_data_center_exception_drilldown_ignores_only_missing_collector_photo() -> None:
    collector_only = {
        "status": "exception",
        "exception_status": "open",
        "has_archive_blocker": True,
        "exception_reasons": ["missing_collector_photo"],
    }
    mixed = {
        **collector_only,
        "exception_reasons": ["missing_collector_photo", "missing_module_asset_no"],
    }

    assert data_center_service.exception_status_from_group(collector_only) == ""
    assert data_center_service.exception_status_from_group(mixed) == "open"
