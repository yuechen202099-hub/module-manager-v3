from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest

from app.services import local_simulation
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


def test_data_center_edit_invalidates_barcode_archive_and_delivery_cache(
    json_review_repo: repository.JsonStateRepository,
) -> None:
    group = _latest_group()
    group["status"] = "approved"
    group["archive_status"] = "archived"
    group["delivery_cache_status"] = "ready"
    for photo in group["photos"]:
        photo["archive_status"] = "archived"
    result = json_review_repo.update_data_center_group(
        group_id="g-1",
        patch={"module_asset_no": "MOD002"},
        actor="admin-a",
        reason="更正模块号",
        source_page="data_center",
    )
    group = _latest_group()
    package_job = local_simulation.get_state()["delivery_package_jobs"][0]

    assert result["archive_status"] != "archived"
    assert group["barcode_verification"]["status"] == "pending"
    assert group["delivery_package_invalidation_epoch"] == 8
    assert package_job["status"] == "stale"
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


def test_json_data_center_classifies_final_photo_then_auto_archives_and_queues_delivery(
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
    assert delivery_jobs, "auto archive must enqueue delivery cache"
    assert package_jobs, "auto archive must enqueue delivery package"
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
    package_statuses = {str(job.get("status") or "") for job in local_simulation.get_state()["delivery_package_jobs"]}

    assert result["barcode_status"] == "manual_confirmed"
    assert result["archive_status"] == "archived"
    assert group["status"] == "approved"
    assert package_statuses & {"pending", "ready"}
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
