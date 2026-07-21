from asyncio import CancelledError
from copy import deepcopy
from datetime import datetime
import hashlib
from io import BytesIO
from pathlib import Path
from importlib.util import find_spec
from threading import Event, Thread
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import local_simulation
from app.services import photo_barcode_check
from app.services import unmatched_review
from app.services.state_repository import DualWriteStateRepository, JsonStateRepository, StateBackendNotReady
from app.services.local_simulation import (
    DEFAULT_SCAN_FILE,
    DEFAULT_TOTAL_CATALOG,
    LocalTestPaths,
    apply_group_photo_urls,
    apply_synced_scan_records,
    add_photo_urls_to_group,
    blank_state,
    build_delivery_cache_for_group,
    build_final_delivery_export,
    build_final_delivery_manifest,
    bootstrap_local_simulation,
    classify_photo,
    claim_task,
    clear_scan_data,
    assign_construction_task,
    confirm_group_barcode_manually,
    create_blank_unmatched_record,
    create_empty_group_for_terminal,
    create_group_from_unmatched_record,
    delete_group_photo,
    delete_unmatched_record,
    dedupe_unmatched_records,
    get_task_progress,
    get_delivery_cached_photo_path,
    get_group,
    get_state,
    import_scan_template_xlsx,
    import_total_catalog_xlsx,
    list_audit_events,
    list_exception_groups,
    list_task_groups,
    list_groups,
    list_replacement_records,
    list_unmatched_records,
    list_tasks,
    bulk_archive_groups,
    normalize_cell,
    release_task,
    rematch_unmatched_record,
    reset_group_to_unconstructed,
    return_group_to_exception_order,
    review_group,
    save_exception_note,
    search_group_targets,
    set_current_team,
    submit_construction_exception_order,
    sync_state_photos_to_oss,
    reset_current_team,
    update_group_metadata,
)


SAMPLE_FILES = [DEFAULT_TOTAL_CATALOG, DEFAULT_SCAN_FILE]


requires_sample_workbooks = pytest.mark.skipif(
    not all(path.exists() for path in SAMPLE_FILES) or find_spec("openpyxl") is None,
    reason="local sample workbooks or openpyxl are not available",
)


def dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 6, 22, hour, minute)


def heartbeat_range(start_hour: int, start_minute: int, end_hour: int, end_minute: int, step_minutes: int = 5):
    current = dt(start_hour, start_minute)
    end = dt(end_hour, end_minute)
    values = []
    while current <= end:
        values.append(current)
        current = current + local_simulation.timedelta(minutes=step_minutes)
    return values


def test_fused_online_work_summary_rewards_countable_online_time_without_exceeding_attendance_window() -> None:
    summary = local_simulation.build_fused_online_work_summary(
        date_key="2026-06-22",
        work_duration_minutes=360,
        weighted_completion=36,
        heartbeats=heartbeat_range(9, 0, 17, 0),
        confirmed_completion_times=[dt(9, 40), dt(10, 30), dt(11, 20), dt(12, 10), dt(13), dt(13, 50), dt(14, 40), dt(15, 30), dt(16, 20)],
    )

    assert summary["attendance_window_minutes"] == 480
    assert summary["online_minutes"] == 480
    assert summary["countable_online_minutes"] == 480
    assert summary["online_ratio"] == 1
    assert summary["base_online_coefficient"] == 1.25
    assert summary["idle_penalty_coefficient"] == 0
    assert summary["final_online_coefficient"] == 1.25
    assert summary["fused_work_duration_minutes"] == 450
    assert summary["fused_efficiency_duration_minutes"] == 360
    assert summary["fused_weighted_completion_per_effective_hour"] == 6


def test_fused_online_work_summary_caps_online_and_fused_minutes_to_attendance_window() -> None:
    summary = local_simulation.build_fused_online_work_summary(
        date_key="2026-06-22",
        work_duration_minutes=600,
        weighted_completion=24,
        heartbeats=heartbeat_range(8, 0, 18, 0),
        confirmed_completion_times=[dt(9, 40), dt(10, 30), dt(11, 20), dt(12, 10), dt(13), dt(13, 50), dt(14, 40), dt(15, 30), dt(16, 20)],
    )

    assert summary["attendance_window_minutes"] == 480
    assert summary["countable_online_minutes"] == 480
    assert summary["online_ratio"] == 1
    assert summary["fused_work_duration_minutes"] == 480
    assert summary["fused_efficiency_duration_minutes"] == 480


def test_fused_online_work_summary_ignores_online_time_before_9_and_after_17() -> None:
    summary = local_simulation.build_fused_online_work_summary(
        date_key="2026-06-22",
        work_duration_minutes=120,
        weighted_completion=10,
        heartbeats=heartbeat_range(8, 0, 10, 0) + heartbeat_range(17, 0, 17, 30),
        confirmed_completion_times=[dt(9, 30), dt(10, 25)],
    )

    assert summary["attendance_window_minutes"] == 480
    assert summary["online_minutes"] == 60
    assert summary["countable_online_minutes"] == 60
    assert summary["online_ratio"] == 0.125


def test_fused_online_work_summary_applies_idle_penalty_after_first_idle_hour() -> None:
    summary = local_simulation.build_fused_online_work_summary(
        date_key="2026-06-22",
        work_duration_minutes=300,
        weighted_completion=30,
        heartbeats=heartbeat_range(9, 0, 14, 0),
        confirmed_completion_times=[dt(10), dt(12), dt(14)],
    )

    assert summary["free_idle_segment_used"] is True
    assert len(summary["idle_segments"]) == 3
    assert summary["idle_penalty_coefficient"] == 0.4
    assert summary["final_online_coefficient"] == 0.76
    assert summary["fused_work_duration_minutes"] == 227


def test_fused_online_work_summary_never_returns_negative_final_online_coefficient() -> None:
    summary = local_simulation.build_fused_online_work_summary(
        date_key="2026-06-22",
        work_duration_minutes=300,
        weighted_completion=30,
        heartbeats=heartbeat_range(9, 0, 17, 0),
        confirmed_completion_times=[dt(10), dt(11), dt(12), dt(13), dt(14), dt(15)],
    )

    assert summary["idle_penalty_coefficient"] > 1
    assert summary["final_online_coefficient"] == 0
    assert summary["fused_work_duration_minutes"] == 0


def test_fused_online_work_summary_deleted_pending_draft_does_not_count_as_confirmed_non_idle() -> None:
    summary = local_simulation.build_fused_online_work_summary(
        date_key="2026-06-22",
        work_duration_minutes=120,
        weighted_completion=12,
        heartbeats=heartbeat_range(9, 0, 11, 0),
        confirmed_completion_times=[],
        pending_non_idle_events=[dt(9, 30)],
        deleted_pending_non_idle_events=[dt(9, 35)],
    )

    assert summary["pending_non_idle_count"] == 0
    assert summary["confirmed_non_idle_count"] == 0
    assert len(summary["idle_segments"]) == 1


def test_fused_online_work_summary_uploaded_group_counts_client_completed_at_as_confirmed_non_idle() -> None:
    summary = local_simulation.build_fused_online_work_summary(
        date_key="2026-06-22",
        work_duration_minutes=120,
        weighted_completion=12,
        heartbeats=heartbeat_range(9, 0, 11, 0),
        confirmed_completion_times=[dt(9, 30), dt(10, 25)],
        pending_non_idle_events=[{"occurred_at": dt(9, 20), "client_batch_id": "batch-1"}],
        upload_action_times=[{"occurred_at": dt(9, 35), "client_batch_id": "batch-1"}],
    )

    assert summary["pending_non_idle_count"] == 0
    assert summary["confirmed_non_idle_count"] == 2
    assert summary["idle_segments"] == []


def test_fused_online_work_summary_upload_action_time_does_not_refresh_idle_time() -> None:
    summary = local_simulation.build_fused_online_work_summary(
        date_key="2026-06-22",
        work_duration_minutes=120,
        weighted_completion=12,
        heartbeats=heartbeat_range(9, 0, 11, 0),
        confirmed_completion_times=[],
        upload_action_times=[dt(10, 30)],
    )

    assert len(summary["idle_segments"]) == 1
    assert summary["confirmed_non_idle_count"] == 0


def test_construction_photo_without_client_completion_is_not_confirmed_non_idle() -> None:
    photo = {
        "upload_source": "construction-mobile",
        "created_at": "2026-06-22T10:30:00",
        "client_completed_at": "",
    }

    assert local_simulation._photo_work_datetime(photo) == dt(10, 30)
    assert local_simulation._photo_confirmed_non_idle_datetime(photo) is None

    photo["client_completed_at"] = "2026-06-22T09:30:00"

    assert local_simulation._photo_confirmed_non_idle_datetime(photo) == dt(9, 30)


def test_fused_online_work_summary_without_attendance_window_keeps_original_kpi_low_confidence() -> None:
    summary = local_simulation.build_fused_online_work_summary(
        date_key="2026-06-22",
        work_duration_minutes=90,
        weighted_completion=9,
        heartbeats=[],
        confirmed_completion_times=[dt(10)],
    )

    assert summary["attendance_window_minutes"] == 0
    assert summary["online_confidence"] == "low"
    assert summary["final_online_coefficient"] == 1
    assert summary["fused_work_duration_minutes"] == 90
    assert summary["fused_efficiency_duration_minutes"] == 90
    assert summary["fused_weighted_completion_per_effective_hour"] == 6


def test_work_time_bonus_minutes_do_not_reduce_efficiency() -> None:
    timestamps = [dt(9, minute) for minute in range(0, 32, 2)]
    completion_records = [
        {"group_id": "g1", "address": "A road 1", "completed_at": dt(9, 4)},
        {"group_id": "g2", "address": "A road 2", "completed_at": dt(9, 16)},
        {"group_id": "g3", "address": "A road 3", "completed_at": dt(9, 28)},
    ]

    summary = local_simulation.build_work_time_summary(timestamps, completion_records)

    assert summary["work_duration_base_minutes_v2"] == 30
    assert summary["dense_bonus_minutes_v2"] == 25
    assert summary["work_duration_minutes"] == 55
    assert summary["efficiency_duration_minutes"] == 30
    assert summary["completion_per_effective_hour"] == 6


def tiny_jpeg_bytes(color: str = "white") -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, format="JPEG")
    return buffer.getvalue()


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
        {
            "source": source,
            "row_number": 4,
            "terminal": "T-003",
            "meter_no": "ZZ1003",
            "address": "C road",
            "meter_match_key": "1003",
        },
    ]


def fake_scan_rows() -> list[dict]:
    rows = []
    for index in range(4):
        rows.append(
            {
                "row_number": index + 2,
                "barcode": f"scan-{index}",
                "meter_match_key": "1001",
                "source_file": "local",
                "collector": "collector",
                "asset_no": f"asset-{index}",
                "asset_type": "module",
                "creator": "tester",
                "created_at": "2026-06-09",
                "has_image": True,
            }
        )
    rows.append(
        {
            "row_number": 6,
            "barcode": "scan-4",
            "meter_match_key": "1002",
            "source_file": "local",
            "collector": "collector",
            "asset_no": "asset-4",
            "asset_type": "module",
            "creator": "tester",
            "created_at": "2026-06-09",
            "has_image": True,
        }
    )
    return rows


def archive_all_group_photos(group: dict, reviewer: str = "alice") -> None:
    categories = ["before_box", "collector_barcode", "module_meter", "after_box"]
    for index, photo in enumerate(list(group["photos"])):
        classify_photo(group["id"], photo["id"], categories[index % len(categories)], reviewer=reviewer)


def build_catalog_workbook_bytes(rows: list[tuple[str, str, str]]) -> bytes:
    pytest.importorskip("openpyxl")
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["终端", "表号", "安装地址"])
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.fixture()
def synthetic_state(monkeypatch: pytest.MonkeyPatch) -> dict:
    def read_catalog(path: Path, source: str) -> list[dict]:
        return fake_catalog_rows(source)

    monkeypatch.setattr(local_simulation, "read_catalog_rows", read_catalog)
    monkeypatch.setattr(local_simulation, "read_scan_rows", lambda path: fake_scan_rows())
    return bootstrap_local_simulation(LocalTestPaths(Path("total.xlsx"), Path("stage.xlsx"), Path("scan.xlsx")))


def test_new_team_starts_empty_and_imports_total_catalog() -> None:
    token = set_current_team("empty-total-import-team")
    try:
        state = get_state()
        assert state["loaded"] is False
        assert state["summary"]["groups"] == 0
        assert state["tasks"] == []

        workbook = build_catalog_workbook_bytes(
            [
                ("T-001", "ZZ1001", "A road"),
                ("T-001", "ZZ1001", "A road duplicate"),
                ("T-002", "ZZ1002", "B road"),
            ]
        )
        result = import_total_catalog_xlsx(workbook)
        tasks = list_tasks()

        assert result["catalog_rows"] == 3
        assert result["imported_rows"] == 2
        assert result["skipped_duplicate_meters"] == 1
        assert result["summary"]["groups"] == 2
        assert result["summary"]["stage_catalog_rows"] == 0
        assert {task["terminal"] for task in tasks} == {"T-001", "T-002"}
        assert all(task["can_claim"] is False for task in tasks)
    finally:
        reset_current_team(token)


def test_local_upload_photos_are_synced_to_oss(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    token = set_current_team("oss-local-sync-team")
    try:
        state = get_state()
        state.clear()
        state.update(blank_state("oss-local-sync-team"))
        upload_dir = tmp_path / "manual"
        upload_dir.mkdir()
        photo_bytes = tiny_jpeg_bytes()
        (upload_dir / "photo.jpg").write_bytes(photo_bytes)
        state["groups"] = [
            {
                "id": "g-oss-001",
                "task_id": 1,
                "meter_match_key": "1001",
                "meter_no": "ZZ1001",
                "terminal": "T-001",
                "address": "A road",
                "status": "pending",
                "photo_count": 1,
                "photos": [
                    {
                        "id": "p-local-001",
                        "image_url": "/static/uploads/manual/photo.jpg",
                        "storage_type": "local_upload",
                        "storage_key": "manual/photo.jpg",
                        "source_file": "manual",
                    }
                ],
            }
        ]

        def fake_save_image_bytes(**kwargs):
            assert kwargs["content"] == photo_bytes
            assert kwargs["scope"] == "imported"
            return {
                "url": "oss://bucket/imported/photo.jpg",
                "sha256": "sha256-local",
                "storage_type": "oss",
                "storage_key": "imported/photo.jpg",
                "storage_bucket": "bucket",
                "storage_source": "imported-oss-upload",
                "content_type": "image/jpeg",
            }

        monkeypatch.setattr(local_simulation, "active_storage_backend", lambda: "oss")
        monkeypatch.setattr(local_simulation, "static_upload_root", lambda: tmp_path)
        monkeypatch.setattr(local_simulation, "save_image_bytes", fake_save_image_bytes)
        monkeypatch.setattr(local_simulation, "save_all_team_states", lambda: None)

        report = sync_state_photos_to_oss(team_id="oss-local-sync-team", max_workers=1)
        photo = state["groups"][0]["photos"][0]

        assert report["uploaded"] == 1
        assert report["failed"] == 0
        assert photo["image_url"] == "oss://bucket/imported/photo.jpg"
        assert photo["storage_type"] == "oss"
        assert photo["storage_key"] == "imported/photo.jpg"
        assert photo["pre_oss_image_url"] == "/static/uploads/manual/photo.jpg"
    finally:
        reset_current_team(token)


def test_team_states_are_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    def read_catalog(path: Path, source: str) -> list[dict]:
        return fake_catalog_rows(source)

    monkeypatch.setattr(local_simulation, "read_catalog_rows", read_catalog)
    monkeypatch.setattr(local_simulation, "read_scan_rows", lambda path: fake_scan_rows())

    token_a = set_current_team("team-a")
    try:
        team_a = bootstrap_local_simulation(LocalTestPaths(Path("total.xlsx"), Path("stage.xlsx"), Path("scan.xlsx")))
        claim_task(1, reviewer="alice")
        assert team_a["tasks"][0]["claimed_by"] == "alice"
    finally:
        reset_current_team(token_a)

    token_b = set_current_team("team-b")
    try:
        team_b = bootstrap_local_simulation(LocalTestPaths(Path("total.xlsx"), Path("stage.xlsx"), Path("scan.xlsx")))
        assert team_b["summary"]["team_id"] == "team-b"
        assert team_b["tasks"][0]["claimed_by"] is None
        claim_task(1, reviewer="bob")
        assert team_b["tasks"][0]["claimed_by"] == "bob"
    finally:
        reset_current_team(token_b)

    token_a = set_current_team("team-a")
    try:
        assert list_tasks()[0]["claimed_by"] == "alice"
    finally:
        reset_current_team(token_a)


@requires_sample_workbooks
def test_bootstrap_local_simulation_uses_sample_workbooks() -> None:
    state = bootstrap_local_simulation(LocalTestPaths())
    summary = state["summary"]

    assert summary["total_catalog_rows"] > 20_000
    assert summary["stage_catalog_rows"] == 0
    assert summary["scan_rows"] > 0
    assert summary["groups"] == summary["total_catalog_rows"]
    assert summary["matched_groups"] > 0


@requires_sample_workbooks
def test_local_groups_are_displayed_with_total_catalog_meter_number() -> None:
    bootstrap_local_simulation(LocalTestPaths())
    result = list_groups(limit=10)

    assert result["total"] > 0
    first = result["items"][0]
    assert first["meter_no"]
    assert first["address"]
    assert first["meter_no"] != first["meter_match_key"]


@requires_sample_workbooks
def test_group_detail_can_be_loaded_from_generated_id() -> None:
    bootstrap_local_simulation(LocalTestPaths())
    result = list_groups(limit=1)
    group = get_group(result["items"][0]["id"])

    assert group is not None
    assert group["id"].startswith("g-")


def test_task_can_be_claimed_and_released(synthetic_state: dict) -> None:
    claimed = claim_task(1, reviewer="alice")
    assert claimed["status"] == "in_review"
    assert claimed["claimed_by"] == "alice"
    assert claimed["claimed_at"]

    released = release_task(1, reviewer="alice")
    assert released["status"] == "released"
    assert released["claimed_by"] is None
    assert released["released_at"]


def test_tasks_are_split_by_terminal_and_require_scan_info(synthetic_state: dict) -> None:
    tasks = list_tasks()

    assert [task["terminal"] for task in tasks] == ["T-001", "T-002", "T-003"]
    assert tasks[0]["scan_rows"] == 4
    assert tasks[0]["can_claim"] is True
    assert tasks[0]["complete_groups"] == 1
    assert tasks[0]["completeness_rate"] == 1.0
    assert tasks[0]["renovation_count"] == 1
    assert tasks[0]["uploaded_count"] == 1
    assert tasks[0]["upload_rate"] == 1.0
    assert tasks[0]["review_rate"] == 0.0
    assert tasks[1]["partial_groups"] == 1
    assert tasks[1]["completeness_rate"] == 1.0
    assert tasks[1]["exception_groups"] == 1
    assert tasks[1]["unreviewed_count"] == 0
    assert tasks[1]["review_rate"] == 0.0
    assert tasks[2]["scan_rows"] == 0
    assert tasks[2]["can_claim"] is False
    assert tasks[2]["completeness_rate"] == 0.0
    assert tasks[2]["incomplete_groups"] == 0
    assert tasks[2]["unconstructed_groups"] == 1

    with pytest.raises(ValueError):
        claim_task(tasks[2]["id"], reviewer="alice")


def test_json_construction_priority_defaults_and_list_payloads_share_availability(
    synthetic_state: dict,
) -> None:
    defaults = local_simulation.ensure_construction_task_fields({})
    assert defaults["construction_priority"] is False
    assert defaults["construction_priority_updated_by"] == ""
    assert defaults["construction_priority_updated_at"] == ""

    task = synthetic_state["tasks"][0]
    uploaded_group = next(group for group in synthetic_state["groups"] if group["task_id"] == task["id"])
    uploaded_group["status"] = "pending"
    pending_group = deepcopy(uploaded_group)
    pending_group.update(
        {
            "id": "priority-pending-group",
            "photo_count": 0,
            "photos": [],
            "status": "unconstructed",
        }
    )
    synthetic_state["groups"].append(pending_group)
    task["construction_priority"] = True
    task["construction_priority_updated_by"] = "dispatcher-a"
    task["construction_priority_updated_at"] = "2026-07-21T09:30:00"

    local_simulation.refresh_task_summary(task["id"])
    task_payload = next(item for item in list_tasks() if item["id"] == task["id"])
    construction_payload = next(
        item
        for item in local_simulation.list_construction_tasks(include_closed=True)
        if item["id"] == task["id"]
    )

    assert task_payload["construction_priority"] is True
    assert task_payload["construction_available"] is True
    assert task_payload["review_available"] is True
    assert {
        key: task_payload[key]
        for key in ("construction_priority", "construction_available", "review_available")
    } == {
        key: construction_payload[key]
        for key in ("construction_priority", "construction_available", "review_available")
    }


def test_refresh_summary_rederives_availability_without_clearing_persisted_priority(
    synthetic_state: dict,
) -> None:
    task = synthetic_state["tasks"][0]
    uploaded_group = next(group for group in synthetic_state["groups"] if group["task_id"] == task["id"])
    uploaded_group["status"] = "pending"
    pending_group = deepcopy(uploaded_group)
    pending_group.update(
        {
            "id": "priority-refresh-pending-group",
            "photo_count": 0,
            "photos": [],
            "status": "unconstructed",
        }
    )
    synthetic_state["groups"].append(pending_group)
    partial_stats = {"total_groups": 2, "uploaded_count": 1, "unreviewed_count": 1}
    task.update({"construction_priority": True, **partial_stats})
    local_simulation.ensure_construction_task_fields(task, partial_stats)

    priority_version = local_simulation.task_status_summary()["version"]
    task["construction_priority"] = False
    no_priority_version = local_simulation.task_status_summary()["version"]
    assert priority_version != no_priority_version

    task["construction_priority"] = True
    local_simulation.ensure_construction_task_fields(task, partial_stats)
    pending_group["photo_count"] = uploaded_group["photo_count"]
    pending_group["photos"] = deepcopy(uploaded_group["photos"])
    pending_group["status"] = "pending"

    local_simulation.refresh_summary()

    assert task["uploaded_count"] == 2
    assert task["construction_priority"] is True
    assert task["construction_available"] is False
    payload = next(item for item in local_simulation.list_tasks() if item["id"] == task["id"])
    assert payload["construction_priority"] is False


def test_summary_reports_installer_group_share(synthetic_state: dict) -> None:
    summary = synthetic_state["summary"]
    distribution = {item["installer"]: item for item in summary["installer_distribution"]}

    assert distribution["tester"]["group_count"] == 2
    assert distribution["tester"]["share"] == 1.0
    assert "未填写" not in distribution


def test_task_installer_distribution_uses_group_installer_only(synthetic_state: dict) -> None:
    synthetic_state["tasks"][0]["construction_claimed_by"] = "task-owner"
    groups = [
        {"task_id": 1, "photo_count": 1, "installer": "alice "},
        {"task_id": 1, "photo_count": 1, "constructor": " alice"},
        {"task_id": 1, "photo_count": 1, "creator": "bob"},
        {"task_id": 1, "photo_count": 1},
        {"task_id": 1, "photo_count": 0, "installer": "ignored"},
    ]

    distribution = {item["installer"]: item for item in local_simulation.task_installer_distribution(groups)}

    assert distribution["alice"]["group_count"] == 2
    assert distribution["alice"]["share"] == 0.5
    assert distribution["bob"]["group_count"] == 1
    assert distribution["bob"]["share"] == 0.25
    assert "task-owner" not in distribution
    assert "ignored" not in distribution


def test_task_installer_distribution_displays_account_name(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_user(username: str):
        if username == "xa":
            return {"username": "xa", "name": "樊哲浩"}
        return None

    monkeypatch.setattr(local_simulation.account_store, "get_user", fake_get_user)

    distribution = local_simulation.task_installer_distribution(
        [
            {"task_id": 1, "photo_count": 1, "creator": "xa"},
            {"task_id": 1, "photo_count": 1, "creator": "樊哲浩"},
        ]
    )

    assert distribution == [{"installer": "樊哲浩", "group_count": 2, "share": 1.0}]


def test_task_installer_distribution_prefers_photo_creator(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_user(username: str):
        if username == "xa":
            return {"username": "xa", "name": "樊哲浩"}
        return None

    monkeypatch.setattr(local_simulation.account_store, "get_user", fake_get_user)

    distribution = local_simulation.task_installer_distribution(
        [
            {
                "task_id": 1,
                "photo_count": 2,
                "creator": "raw-installer",
                "photos": [{"creator": "xa"}, {"creator": "xa"}],
            },
            {
                "task_id": 1,
                "photo_count": 2,
                "photos": [{"creator": "白红运"}, {"creator": "龙翔"}],
            },
        ]
    )

    assert distribution == [
        {"installer": "樊哲浩", "group_count": 1, "share": 0.3333},
        {"installer": "白红运", "group_count": 1, "share": 0.3333},
        {"installer": "龙翔", "group_count": 1, "share": 0.3333},
    ]


def test_task_installer_distribution_counts_active_photo_creator_when_photo_count_is_stale() -> None:
    distribution = local_simulation.task_installer_distribution(
        [
            {
                "task_id": 1,
                "photo_count": 0,
                "installer": "raw-installer",
                "photos": [{"creator": "photo-installer", "is_active": True}],
            }
        ]
    )

    assert distribution == [{"installer": "photo-installer", "group_count": 1, "share": 1.0}]


def test_task_installer_distribution_ignores_inactive_photo_creator_before_fallback() -> None:
    distribution = local_simulation.task_installer_distribution(
        [
            {
                "task_id": 1,
                "photo_count": 1,
                "installer": "raw-installer",
                "photos": [{"creator": "deleted-installer", "is_active": False}],
            }
        ]
    )

    assert distribution == [{"installer": "raw-installer", "group_count": 1, "share": 1.0}]


def test_list_tasks_can_skip_installer_distribution(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {
        "tasks": [
            {
                "id": 7,
                "terminal": "T-007",
                "title": "终端 T-007",
                "status": "published",
                "construction_enabled": True,
            }
        ],
        "groups": [],
    }
    monkeypatch.setattr(local_simulation, "get_state", lambda: state)
    monkeypatch.setattr(
        local_simulation,
        "task_installer_distribution",
        lambda _groups: pytest.fail("installer distribution should be skipped"),
    )

    rows = local_simulation.list_tasks(include_installer_distribution=False)

    assert rows[0]["terminal"] == "T-007"


def test_task_installer_distribution_does_not_use_replacement_by_as_installer() -> None:
    distribution = local_simulation.task_installer_distribution(
        [
            {
                "task_id": 1,
                "photo_count": 1,
                "replacement_by": "replacement-only",
                "photos": [{"creator": "", "is_active": True}],
            }
        ]
    )

    assert distribution == []


def test_normalize_cell_repairs_latin1_mojibake() -> None:
    mojibake = "\u00e5\u00ae\u009d\u00e5\u00b1\u00b1\u00e5\u008c\u00ba\u00e9\u0094\u00a6\u00e7\u00a7\u008b\u00e8\u00b7\u00af1152\u00e5\u008f\u00b7"

    assert normalize_cell(mojibake) == "\u5b9d\u5c71\u533a\u9526\u79cb\u8def1152\u53f7"
    assert normalize_cell("\u4e0a\u6d77\u5e02\u5b9d\u5c71\u533a") == "\u4e0a\u6d77\u5e02\u5b9d\u5c71\u533a"


def test_normalized_photo_source_url_sanitizes_terminal_url_after_exactly_four_wrappers() -> None:
    def wrap_four_times(terminal_url: str) -> str:
        wrapped = terminal_url
        for level in range(4):
            wrapped = f"https://wrapper-{level}.example/open?downloadImg={quote(wrapped, safe='')}"
        return wrapped

    first = local_simulation.normalized_photo_source_url(
        wrap_four_times("https://cdn.example/photos/a.jpg?signature=one&token=first&variant=full")
    )
    equivalent = local_simulation.normalized_photo_source_url(
        wrap_four_times("https://cdn.example/photos/a.jpg?signature=two&token=second&variant=full")
    )
    different_path = local_simulation.normalized_photo_source_url(
        wrap_four_times("https://cdn.example/photos/b.jpg?variant=full")
    )
    different_stable_identity = local_simulation.normalized_photo_source_url(
        wrap_four_times("https://cdn.example/photos/a.jpg?variant=thumbnail")
    )

    assert first == equivalent == "https://cdn.example/photos/a.jpg?variant=full"
    assert first != different_path
    assert first != different_stable_identity


def test_review_group_updates_status_and_summary(synthetic_state: dict) -> None:
    state = synthetic_state
    first_id = state["groups"][0]["id"]

    claim_task(1, reviewer="alice")
    reviewed = review_group(first_id, status="approved", reviewer="alice", note="sample passed")
    tasks = list_tasks()

    assert reviewed["status"] == "approved"
    assert reviewed["review_note"] == "sample passed"
    assert state["summary"]["approved_groups"] == 1
    assert state["summary"]["reviewed_groups"] == 1
    assert state["summary"]["exception_groups"] == 1
    assert state["summary"]["review_progress"] == 0.3333
    assert tasks[0]["completed_groups"] == 1
    assert tasks[0]["progress"] == 1.0


def test_review_group_rejects_unknown_status(synthetic_state: dict) -> None:
    state = synthetic_state
    first_id = state["groups"][0]["id"]

    with pytest.raises(ValueError):
        review_group(first_id, status="done", reviewer="alice")


def test_review_group_blocks_non_claiming_reviewer(synthetic_state: dict) -> None:
    first_id = synthetic_state["groups"][0]["id"]
    claim_task(1, reviewer="alice")

    with pytest.raises(ValueError):
        review_group(first_id, status="approved", reviewer="bob")


def test_exception_note_marks_group_and_progress(synthetic_state: dict) -> None:
    second_id = synthetic_state["groups"][1]["id"]

    claim_task(2, reviewer="alice")
    reviewed = save_exception_note(second_id, reviewer="alice", note="missing required photos")
    progress = get_task_progress(2)

    assert reviewed["status"] == "exception"
    assert reviewed["exception_note"] == "missing required photos"
    assert progress["exception_groups"] == 1
    assert progress["reviewed_groups"] == 0
    assert progress["pending_groups"] == 0


def test_pending_archive_blocker_counts_as_problem_but_not_archived(synthetic_state: dict) -> None:
    group = synthetic_state["groups"][1]
    group["status"] = "pending"
    local_simulation.refresh_summary()
    progress = get_task_progress(group["task_id"])

    assert group["has_archive_blocker"] is True
    assert synthetic_state["summary"]["exception_groups"] == 1
    assert synthetic_state["summary"]["reviewed_groups"] == 0
    assert progress["exception_groups"] == 1
    assert progress["reviewed_groups"] == 0
    assert progress["pending_groups"] == 0


def test_problem_group_is_not_counted_again_as_missing_photo(synthetic_state: dict) -> None:
    group = synthetic_state["groups"][1]

    assert group["photo_count"] == 1
    local_simulation.refresh_summary()

    assert group["has_archive_blocker"] is True
    assert synthetic_state["summary"]["exception_groups"] == 1
    assert synthetic_state["summary"]["incomplete_groups"] == 0
    assert synthetic_state["summary"]["scanned_groups"] == 2


def test_task_groups_can_be_filtered_by_status(synthetic_state: dict) -> None:
    result = list_task_groups(2, status="incomplete")

    assert result["total"] == 1
    assert result["items"][0]["photo_count"] == 1


def test_task_groups_can_be_limited_to_scanned_groups(synthetic_state: dict) -> None:
    scanned = list_task_groups(3, scan_only=True)
    all_groups = list_task_groups(3, scan_only=False)

    assert scanned["total"] == 0
    assert all_groups["total"] == 1


def test_review_task_groups_filter_before_paging_and_count_full_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    groups = [
        {
            "id": f"group-{index:02d}",
            "task_id": 1,
            "terminal": "T-001",
            "meter_no": f"M-{index:03d}",
            "meter_match_key": f"KEY-{index:03d}",
            "address": f"ROOM {index:03d}",
            "status": "pending",
            "photo_count": 4,
            "photos": [],
        }
        for index in range(45)
    ]
    monkeypatch.setattr(local_simulation, "find_task", lambda _task_id: {"id": 1})
    monkeypatch.setattr(local_simulation, "get_state", lambda: {"groups": groups})

    result = local_simulation.list_review_task_groups(
        1,
        limit=20,
        offset=20,
        review_status="reviewable",
        query="ROOM",
    )

    assert result["limit"] == 20
    assert result["offset"] == 20
    assert len(result["items"]) == 20
    assert result["total"] == result["status_counts"]["reviewable"] == 45
    assert all("ROOM" in item["address"] for item in result["items"])


@pytest.mark.parametrize(
    "query",
    [
        "TERM-SEARCH",
        "METER-SEARCH",
        "ADDRESS-SEARCH",
        "MODULE-SEARCH",
        "COLLECTOR-SEARCH",
        "reviewer-alice",
    ],
)
def test_review_task_groups_searches_all_review_identity_fields(
    monkeypatch: pytest.MonkeyPatch,
    query: str,
) -> None:
    groups = [
        {
            "id": "reviewable",
            "task_id": 1,
            "terminal": "TERM-SEARCH",
            "meter_no": "METER-SEARCH",
            "meter_match_key": "MATCH-SEARCH",
            "address": "ADDRESS-SEARCH",
            "module_asset_no": "MODULE-SEARCH",
            "collector": "COLLECTOR-SEARCH",
            "reviewer": "reviewer-alice",
            "status": "pending",
            "photo_count": 4,
            "photos": [],
        },
        {"id": "exception", "task_id": 1, "status": "exception", "photo_count": 4, "photos": []},
        {"id": "archived", "task_id": 1, "status": "approved", "photo_count": 4, "photos": []},
        {"id": "unconstructed", "task_id": 1, "status": "pending", "photo_count": 0, "photos": []},
    ]
    monkeypatch.setattr(local_simulation, "find_task", lambda _task_id: {"id": 1})
    monkeypatch.setattr(local_simulation, "get_state", lambda: {"groups": groups})

    result = local_simulation.list_review_task_groups(1, query=query)

    assert result["total"] == 1
    assert result["items"][0]["id"] == "reviewable"
    assert result["status_counts"] == {
        "all": 1,
        "reviewable": 1,
        "exception": 0,
        "archived": 0,
        "unconstructed": 0,
    }


def test_review_task_groups_reports_all_status_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    groups = [
        {"id": "reviewable", "task_id": 1, "meter_no": "10000001", "status": "pending", "photo_count": 4, "photos": []},
        {"id": "exception", "task_id": 1, "meter_no": "10000002", "status": "exception", "photo_count": 4, "photos": []},
        {"id": "archived", "task_id": 1, "meter_no": "10000003", "status": "approved", "photo_count": 4, "photos": []},
        {"id": "unconstructed", "task_id": 1, "meter_no": "10000004", "status": "pending", "photo_count": 0, "photos": []},
    ]
    monkeypatch.setattr(local_simulation, "find_task", lambda _task_id: {"id": 1})
    monkeypatch.setattr(local_simulation, "get_state", lambda: {"groups": groups})

    result = local_simulation.list_review_task_groups(1, review_status="exception")

    assert result["total"] == 1
    assert result["items"][0]["id"] == "exception"
    assert result["status_counts"] == {
        "all": 4,
        "reviewable": 1,
        "exception": 1,
        "archived": 1,
        "unconstructed": 1,
    }


def test_task_groups_can_return_lightweight_summaries(synthetic_state: dict) -> None:
    result = list_task_groups(1, limit=1, summary_only=True)

    assert result["total"] >= 1
    assert "photos" not in result["items"][0]
    assert "photo_count" in result["items"][0]
    assert "reviewer" in result["items"][0]


def test_task_group_summary_includes_barcode_coverage_and_category_state(synthetic_state: dict) -> None:
    group = synthetic_state["groups"][0]
    group.update(
        {
            "meter_no": "110000288056",
            "meter_match_key": "0000288056",
            "collector": "COLLECTOR001",
            "module_asset_no": "MOD001",
            "photo_count": 4,
            "photos": [
                {
                    "id": "p-meter",
                    "category": "before_box",
                    "archive_status": "archived",
                    "barcode_check_status": "matched",
                    "barcode_check_expected_type": "meter",
                    "barcode_check_matched_value": "110000288056",
                    "barcode_check_normalized_values": ["110000288056"],
                },
                {
                    "id": "p-collector",
                    "category": "collector_barcode",
                    "archive_status": "archived",
                    "barcode_check_status": "matched",
                    "barcode_check_expected_type": "collector",
                    "barcode_check_matched_value": "COLLECTOR001",
                    "barcode_check_normalized_values": ["COLLECTOR001"],
                },
                {
                    "id": "p-module",
                    "category": "module_meter",
                    "archive_status": "archived",
                    "barcode_check_status": "matched",
                    "barcode_check_expected_type": "module",
                    "barcode_check_matched_value": "MOD001",
                    "barcode_check_normalized_values": ["MOD001"],
                },
                {
                    "id": "p-after",
                    "category": "after_box",
                    "archive_status": "archived",
                },
            ],
        }
    )

    result = list_task_groups(group["task_id"], summary_only=True)
    item = next(item for item in result["items"] if item["id"] == group["id"])

    assert "photos" not in item
    assert item["group_barcode_check_status"] == "matched"
    assert item["group_barcode_passed_count"] == 3
    assert set(item["group_barcode_matched_fields"]) == {"meter", "module", "collector"}
    assert item["photo_category_complete"] is True


def test_manual_group_barcode_confirmation_audits_and_marks_group_passed(synthetic_state: dict) -> None:
    group = synthetic_state["groups"][0]
    group.update(
        {
            "meter_no": "110000288056",
            "collector": "COLLECTOR001",
            "module_asset_no": "MOD001",
            "photo_count": 4,
            "photos": [
                {"id": "p1", "category": "before_box", "archive_status": "archived"},
                {"id": "p2", "category": "collector_barcode", "archive_status": "archived"},
                {"id": "p3", "category": "module_meter", "archive_status": "archived"},
                {"id": "p4", "category": "after_box", "archive_status": "archived"},
            ],
        }
    )
    claim_task(group["task_id"], "alice")

    result = confirm_group_barcode_manually(group["id"], actor="alice")
    updated = result["group"]
    events = list_audit_events(limit=5)["items"]

    assert updated["group_barcode_manual_confirmed"] is True
    assert updated["group_barcode_check_status"] == "matched"
    assert updated["group_barcode_passed_count"] == 3
    assert events[0]["action"] == "group_barcode_manual_confirmed"
    assert events[0]["payload"]["group_id"] == group["id"]


def test_task_groups_are_ordered_for_review_queue(synthetic_state: dict) -> None:
    template = deepcopy(synthetic_state["groups"][0])

    def make_group(group_id: str, meter_no: str, status: str, photo_count: int, archived: bool = False) -> dict:
        group = deepcopy(template)
        group.update(
            {
                "id": group_id,
                "task_id": 1,
                "terminal": template["terminal"],
                "meter_no": meter_no,
                "status": status,
                "photo_count": photo_count,
                "has_archive_blocker": status == "exception",
                "exception_reasons": ["测试异常"] if status == "exception" else [],
            }
        )
        group["photos"] = deepcopy(template["photos"][:photo_count])
        for index, photo in enumerate(group["photos"], start=1):
            photo["id"] = f"{group_id}-photo-{index}"
            photo["archive_status"] = "archived" if archived else "pending"
        return group

    synthetic_state["groups"] = [
        group for group in synthetic_state["groups"] if group["task_id"] != 1
    ] + [
        make_group("queue-unconstructed", "0004", "pending", 0),
        make_group("queue-exception", "0003", "exception", 4),
        make_group("queue-done", "0002", "approved", 4, archived=True),
        make_group("queue-reviewable", "0001", "pending", 4),
    ]

    result = list_task_groups(1, scan_only=False)

    assert [item["id"] for item in result["items"]] == [
        "queue-reviewable",
        "queue-exception",
        "queue-unconstructed",
        "queue-done",
    ]


def test_unconstructed_groups_stay_out_of_exception_queue_but_remain_in_task_list(synthetic_state: dict) -> None:
    no_scan_group = synthetic_state["groups"][2]

    assert no_scan_group["photo_count"] == 0
    assert no_scan_group.get("has_archive_blocker") is False
    assert no_scan_group.get("exception_reasons") == []

    exceptions = list_exception_groups()
    task_groups = list_task_groups(3, scan_only=False)

    assert no_scan_group["id"] not in {group["id"] for group in exceptions["items"]}
    assert no_scan_group["id"] in {group["id"] for group in task_groups["items"]}
    assert task_groups["items"][0]["construction_status"] == "unconstructed"
    assert synthetic_state["summary"]["unconstructed_groups"] == 1
    assert synthetic_state["summary"]["incomplete_groups"] == 0
    assert synthetic_state["summary"]["exception_groups"] == 1


def test_downloaded_photo_can_be_classified(synthetic_state: dict) -> None:
    first_group = synthetic_state["groups"][0]
    photo = first_group["photos"][0]

    with pytest.raises(ValueError, match="must be claimed"):
        classify_photo(first_group["id"], photo["id"], "collector_barcode", reviewer="alice")

    claim_task(1, reviewer="alice")
    classified = classify_photo(first_group["id"], photo["id"], "collector_barcode", reviewer="alice")

    assert classified["category"] == "collector_barcode"
    assert classified["category_label"] == "\u91c7\u96c6\u5668\u6761\u5f62\u7801"
    assert classified["classified_by"] == "alice"
    assert classified["archive_status"] == "archived"
    assert classified["archive_filename"] == "\u91c7\u96c6\u5668\u6761\u5f62\u7801.jpg"
    assert classified["archived_at"]
    assert synthetic_state["summary"]["unclassified_photos"] == 4


def test_classifying_photo_runs_barcode_check_and_updates_accuracy_summary(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(photo_barcode_check, "default_barcode_scanner", lambda photo: ["collector"])
    first_group = synthetic_state["groups"][0]
    photo = first_group["photos"][0]

    claim_task(1, reviewer="alice")
    classified = classify_photo(first_group["id"], photo["id"], "collector_barcode", reviewer="alice")
    summary = get_state()["summary"]

    assert classified["barcode_check_status"] == "matched"
    assert classified["barcode_check_expected_type"] == "collector"
    assert classified["barcode_check_values"] == ["collector"]
    assert summary["photo_accuracy_checked"] == 1
    assert summary["photo_accuracy_passed"] == 1
    assert summary["photo_accuracy_failed"] == 0
    assert summary["photo_accuracy_unreadable"] == 0
    assert summary["photo_accuracy_not_required"] == 0
    assert summary["photo_accuracy_rate"] == 1


def test_bulk_archive_runs_barcode_check_for_preclassified_photos(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(photo_barcode_check, "default_barcode_scanner", lambda photo: ["collector"])
    group = synthetic_state["groups"][0]
    photo = group["photos"][0]
    photo["category"] = "collector_barcode"
    photo["category_label"] = local_simulation.PHOTO_CATEGORIES["collector_barcode"]

    result = bulk_archive_groups([group["id"]], actor="admin", reason="accuracy smoke")
    archived_photo = result["groups"][0]["photos"][0]
    summary = get_state()["summary"]

    assert archived_photo["barcode_check_status"] == "matched"
    assert summary["photo_accuracy_checked"] == 1
    assert summary["photo_accuracy_passed"] == 1


def test_bulk_archive_preserves_existing_barcode_check_for_preclassified_photos(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(photo: dict) -> list[str]:
        raise AssertionError(f"already checked photo was scanned again: {photo.get('id')}")

    monkeypatch.setattr(photo_barcode_check, "default_barcode_scanner", fail_if_called)
    group = synthetic_state["groups"][0]
    photo = group["photos"][0]
    photo.update(
        {
            "category": "collector_barcode",
            "category_label": local_simulation.PHOTO_CATEGORIES["collector_barcode"],
            "barcode_check_status": "matched",
            "barcode_check_expected_type": "collector",
            "barcode_check_values": ["collector"],
            "barcode_check_normalized_values": ["COLLECTOR"],
            "barcode_check_expected_values": ["COLLECTOR"],
            "barcode_check_matched_value": "COLLECTOR",
            "barcode_checked_at": "2026-06-27T00:00:00+00:00",
            "barcode_check_error": "",
        }
    )

    result = bulk_archive_groups([group["id"]], actor="admin", reason="preserve accuracy")
    archived_photo = result["groups"][0]["photos"][0]

    assert archived_photo["barcode_check_status"] == "matched"
    assert archived_photo["barcode_checked_at"] == "2026-06-27T00:00:00+00:00"


def test_previewable_url_photo_can_be_classified_without_download_status(synthetic_state: dict) -> None:
    first_group = synthetic_state["groups"][0]
    photo = first_group["photos"][0]
    photo["image_url"] = "https://example.test/photo.jpg"
    photo["download_status"] = "oss_reused"

    claim_task(1, reviewer="alice")
    classified = classify_photo(first_group["id"], photo["id"], "collector_barcode", reviewer="alice")

    assert classified["category"] == "collector_barcode"
    assert classified["download_status"] == "downloaded"


def test_delivery_cache_builds_for_approved_group(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    group = synthetic_state["groups"][0]
    for photo in group["photos"]:
        photo["image_url"] = f"https://example.test/{photo['id']}.jpg"

    monkeypatch.setattr(local_simulation.settings, "delivery_cache_path", str(tmp_path))
    monkeypatch.setattr(local_simulation, "schedule_delivery_cache_build", lambda *args, **kwargs: None)
    monkeypatch.setattr(local_simulation, "save_all_team_states", lambda: None)
    monkeypatch.setattr(
        local_simulation,
        "download_delivery_photo_content",
        lambda photo: (f"cached-{photo['id']}".encode("utf-8"), ".jpg", "image/jpeg"),
    )

    claim_task(group["task_id"], reviewer="alice")
    archive_all_group_photos(group, reviewer="alice")
    result = build_delivery_cache_for_group(group["id"], force=True)
    manifest = build_final_delivery_manifest(task_id=group["task_id"])
    first_photo = manifest["groups"][0]["photos"][0]
    cached_path = get_delivery_cached_photo_path(group["id"], first_photo["id"])

    assert group["status"] == "approved"
    assert result["status"] == "ready"
    assert first_photo["delivery_cache_url"].startswith(f"/local-test/delivery-cache/{group['id']}/")
    assert cached_path.read_bytes().startswith(b"cached-")


def test_photo_can_be_classified_as_unmatched_data_group(synthetic_state: dict) -> None:
    first_group = synthetic_state["groups"][0]
    photo = first_group["photos"][0]

    claim_task(1, reviewer="alice")
    classified = classify_photo(first_group["id"], photo["id"], "unmatched_group", reviewer="alice")

    assert classified["category"] == "unmatched_group"
    assert classified["category_label"] == "未匹配数据组"
    assert classified["archive_filename"] == "未匹配数据组.jpg"


def test_delete_group_photo_requires_claim_and_resets_review_state(synthetic_state: dict) -> None:
    group = synthetic_state["groups"][0]
    original_photo_count = group["photo_count"]
    photo = group["photos"][0]

    with pytest.raises(ValueError, match="must be claimed"):
        delete_group_photo(group["id"], photo["id"], reviewer="alice")

    claim_task(group["task_id"], reviewer="alice")
    deleted = delete_group_photo(group["id"], photo["id"], reviewer="alice")
    audits = list_audit_events()

    assert deleted["deleted_photo"]["id"] == photo["id"]
    assert deleted["group"]["photo_count"] == original_photo_count - 1
    assert all(item["id"] != photo["id"] for item in deleted["group"]["photos"])
    assert deleted["group"]["status"] == "incomplete"
    assert deleted["group"]["reviewer"] is None
    assert audits["items"][0]["action"] == "delete_group_photo"


def test_clear_scan_data_resets_downloaded_photos_and_claimable_tasks(synthetic_state: dict) -> None:
    state = clear_scan_data()
    tasks = list_tasks()

    assert state["summary"]["scan_rows"] == 0
    assert state["summary"]["downloaded_photos"] == 0
    assert state["summary"]["unclassified_photos"] == 0
    assert state["scan_unmatched"] == []
    assert all(group["photos"] == [] for group in state["groups"])
    assert all(group["photo_count"] == 0 for group in state["groups"])
    assert all(task["can_claim"] is False for task in tasks)


def test_apply_synced_scan_records_matches_catalog_and_refreshes_tasks(synthetic_state: dict) -> None:
    clear_scan_data()
    before = list_tasks()
    assert before[0]["can_claim"] is False

    result = apply_synced_scan_records(
        [
            {
                "file_id": "remote-file-1",
                "source_file": "remote-source",
                "installer": "installer",
                "barcode": "ABCDEFGHIJK000001001X",
                "meter_match_key": "1001",
                "terminal": "T-001",
                "collector": "collector",
                "meter_no": "ZZ1001",
                "module_asset_no": "asset-1",
                "address": "A road",
                "asset_type": "module",
                "creator": "tester",
                "created_at": "2026-06-09",
                "image_count": 2,
                "image_urls": ["https://download.example/photo-1.jpg", "https://download.example/photo-2.jpg"],
            }
        ]
    )
    after = list_tasks()
    group = synthetic_state["groups"][0]

    assert result["applied_records"] == 2
    assert result["unmatched_records"] == 0
    assert group["photo_count"] == 2
    assert group["photos"][0]["image_url"] == "https://download.example/photo-1.jpg"
    assert group["photos"][1]["image_url"] == "https://download.example/photo-2.jpg"
    assert after[0]["can_claim"] is True
    assert after[0]["scan_rows"] == 2

    duplicate = apply_synced_scan_records(
        [
            {
                "file_id": "remote-file-1",
                "source_file": "remote-source",
                "barcode": "ABCDEFGHIJK000001001X",
                "meter_match_key": "1001",
                "image_urls": ["https://download.example/photo-1.jpg", "https://download.example/photo-2.jpg"],
            }
        ]
    )

    assert duplicate["applied_records"] == 0
    assert duplicate["skipped_duplicate_meters"] == 0
    assert duplicate["photos_duplicate"] == 2
    assert group["photo_count"] == 2


def test_apply_synced_scan_records_supplements_duplicate_meter_in_same_batch(synthetic_state: dict) -> None:
    clear_scan_data()

    result = apply_synced_scan_records(
        [
            {
                "file_id": "remote-file-a",
                "source_file": "remote-source",
                "barcode": "ABCDEFGHIJK000001001X",
                "meter_match_key": "1001",
                "meter_no": "ZZ1001",
                "image_urls": ["https://download.example/a.jpg"],
            },
            {
                "file_id": "remote-file-b",
                "source_file": "remote-source",
                "barcode": "ABCDEFGHIJK000001001X",
                "meter_match_key": "1001",
                "meter_no": "ZZ1001",
                "image_urls": ["https://download.example/b.jpg"],
            },
        ]
    )

    group = synthetic_state["groups"][0]
    assert result["applied_records"] == 2
    assert result["skipped_duplicate_meters"] == 0
    assert result["photos_new"] == 2
    assert group["photo_count"] == 2
    assert group["photos"][0]["image_url"] == "https://download.example/a.jpg"
    assert group["photos"][1]["image_url"] == "https://download.example/b.jpg"


def test_reset_group_to_unconstructed_soft_clears_photos(synthetic_state: dict) -> None:
    clear_scan_data()
    apply_synced_scan_records(
        [
            {
                "file_id": "remote-reset",
                "source_file": "remote-source",
                "barcode": "ABCDEFGHIJK000001001X",
                "meter_match_key": "1001",
                "meter_no": "ZZ1001",
                "collector": "collector-a",
                "module_asset_no": "asset-a",
                "image_urls": ["https://download.example/reset-a.jpg", "https://download.example/reset-b.jpg"],
            }
        ]
    )
    group = synthetic_state["groups"][0]
    claim_task(group["task_id"], "alice")
    group["group_barcode_manual_confirmed"] = True
    group["group_barcode_manual_confirmed_fields"] = ["meter", "module", "collector"]
    group["group_barcode_manual_confirmed_by"] = "alice"
    group["group_barcode_manual_confirmed_at"] = "2026-06-29T10:00:00+08:00"

    result = reset_group_to_unconstructed(group["id"], actor="alice", reason="现场返工")

    assert result["soft_deleted_photos"] == 2
    assert group["photos"] == []
    assert len(group["deleted_photos"]) == 2
    assert group["photo_count"] == 0
    assert group["status"] == "pending"
    assert group.get("collector") == ""
    assert group.get("module_asset_no") == ""
    assert group.get("construction_collector") == ""
    assert group.get("construction_module_asset_no") == ""
    assert group.get("group_barcode_manual_confirmed") is False
    assert group.get("group_barcode_manual_confirmed_fields") == []
    assert group.get("group_barcode_manual_confirmed_by") == ""
    assert group.get("group_barcode_manual_confirmed_at") == ""
    barcode_check = photo_barcode_check.build_group_barcode_check(group)
    assert barcode_check["group_barcode_check_status"] != "matched"
    assert barcode_check["group_barcode_matched_fields"] == []
    assert group["deleted_photos"][0]["is_active"] is False


def test_return_group_to_exception_order_creates_assigned_work_order(synthetic_state: dict) -> None:
    clear_scan_data()
    apply_synced_scan_records(
        [
            {
                "file_id": "remote-exception",
                "source_file": "remote-source",
                "barcode": "ABCDEFGHIJK000001001X",
                "meter_match_key": "1001",
                "meter_no": "ZZ1001",
                "collector": "collector-a",
                "module_asset_no": "asset-a",
                "image_urls": ["https://download.example/exception-a.jpg"],
            }
        ]
    )
    group = synthetic_state["groups"][0]
    claim_task(group["task_id"], "alice")
    assign_construction_task(group["task_id"], actor="admin", constructor="constructor")

    result = return_group_to_exception_order(
        group["id"],
        actor="alice",
        category="module_error",
        note="模块号错误",
    )
    assert result["order"]["assigned_to"] == "constructor"
    assert result["order"]["status"] == "assigned"

    submitted = submit_construction_exception_order(
        result["order"]["id"],
        actor="constructor",
        updates={"collector": "collector-b", "module_asset_no": "asset-b"},
        note="现场已修正",
    )

    assert group["status"] == "pending"
    assert submitted["order"]["status"] == "submitted"
    assert submitted["group"]["construction_collector"] == "collector-b"
    assert submitted["group"]["construction_module_asset_no"] == "asset-b"


def test_unmatched_records_are_searchable_and_audited(synthetic_state: dict) -> None:
    result = apply_synced_scan_records(
        [
            {
                "file_id": "remote-unmatched-1",
                "source_file": "remote-source",
                "barcode": "NO-MATCH-001",
                "meter_match_key": "no-match",
                "terminal": "T-404",
                "collector": "collector-x",
                "module_asset_no": "module-x",
                "image_urls": ["https://download.example/unmatched.jpg"],
            }
        ]
    )

    records = list_unmatched_records(query="NO-MATCH")
    deleted = delete_unmatched_record(records["items"][0]["unmatched_id"], actor="alice", reason="bad source")
    audits = list_audit_events()

    assert result["unmatched_records"] == 1
    assert records["total"] == 1
    assert deleted["barcode"] == "NO-MATCH-001"
    assert audits["items"][0]["action"] == "delete_unmatched"
    assert audits["items"][0]["actor"] == "alice"


def test_json_unmatched_pagination_stats_cover_the_full_filtered_result(
    synthetic_state: dict,
) -> None:
    state = local_simulation.get_state()
    state["scan_unmatched"] = []
    for suffix, updates in (
        ("PENDING", {}),
        ("ASSIGNED", {"assigned_to": "installer-a"}),
        ("OUTSIDE", {"project_outside": True}),
    ):
        record = local_simulation.ensure_unmatched_record(
            {
                "barcode": f"FILTERED-{suffix}",
                "meter_no": f"FILTERED-{suffix}",
                "terminal": f"T-{suffix}",
                **updates,
            }
        )
        state["scan_unmatched"].append(record)

    result = local_simulation.list_unmatched_records(query="FILTERED", limit=1, offset=0)

    assert result["total"] == 3
    assert len(result["items"]) == 1
    assert result["stats"] == {"pending": 1, "assigned": 1, "outside": 1}

    scoped = local_simulation.list_unmatched_records(
        query="FILTERED",
        limit=20,
        offset=0,
        assigned_to="installer-a",
    )
    assert scoped["total"] == 1
    assert [item["assigned_to"] for item in scoped["items"]] == ["installer-a"]
    assert scoped["stats"] == {"pending": 0, "assigned": 1, "outside": 0}


def seed_unmatched_review_record(
    *,
    meter_no: str = "120000912473",
    photo_prefix: str = "https://photos.example",
    manual_confirmed: bool = False,
) -> str:
    state = local_simulation.get_state()
    barcode = "3130001122100009124734" if meter_no == "120000912473" else meter_no
    record = local_simulation.ensure_unmatched_record(
        {
            "barcode": barcode,
            "meter_no": meter_no,
            "collector": "C001",
            "module_asset_no": "M001",
            "photo_urls": [f"{photo_prefix}/{index}.jpg" for index in range(4)],
        }
    )
    if manual_confirmed:
        review = unmatched_review.build_review(record)
        review["state"] = "reviewed"
        review["manual_confirmed"] = True
        review["reviewer"] = "reviewer-a"
        review["reviewed_at"] = "2026-07-13T09:00:00+00:00"
        review["updated_at"] = "2026-07-13T09:00:00+00:00"
        record["temporary_review"] = review
        record["review_version"] = review["version"]
    state["scan_unmatched"].append(record)
    return record["unmatched_id"]


@pytest.mark.parametrize("terminal", ["00000000", "未关联终端", "manual-terminal", "unmatched-terminal"])
def test_json_repository_legacy_assign_rejects_placeholder_terminal_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    terminal: str,
) -> None:
    team_id = "round3-json-legacy-assign"
    state_path = tmp_path / "state.json"
    monkeypatch.setenv("LOCAL_SIMULATION_STATE_PATH", str(state_path))
    local_simulation._team_states[team_id] = local_simulation.blank_state(team_id)
    token = local_simulation.set_current_team(team_id)
    try:
        state = local_simulation.get_state()
        record = local_simulation.ensure_unmatched_record(
            {
                "unmatched_id": "legacy-assign-placeholder-terminal",
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

        with pytest.raises(ValueError, match="real terminal"):
            JsonStateRepository().assign_unmatched_record(
                record["unmatched_id"],
                actor="admin-a",
                constructor="constructor-a",
                expected_version=1,
                note="must not persist",
            )

        assert state["tasks"] == before["tasks"]
        assert state["scan_unmatched"] == before["scan_unmatched"]
        assert state["summary"] == before["summary"]
        assert state["audit_events"] == before["audit_events"]
        assert state == before
        assert state_path.read_bytes() == before_bytes
    finally:
        local_simulation.reset_current_team(token)
        local_simulation._team_states.pop(team_id, None)


def add_unmatched_match_catalog_row(
    *,
    catalog_id: str = "catalog-match-1",
    terminal: str = "T-MATCH-1",
    meter_no: str = "120000912473",
    address: str = "match road",
) -> dict:
    row = {
        "id": catalog_id,
        "terminal": terminal,
        "meter_no": meter_no,
        "meter_match_key": local_simulation.build_total_catalog_match_key(meter_no),
        "address": address,
        "collector": "C001",
        "module_asset_no": "M001",
    }
    local_simulation.get_state()["total_catalog"].append(row)
    return row


@pytest.mark.parametrize("meter_no", ["", "12"])
def test_unmatched_match_candidates_return_zero_for_empty_or_short_meter(
    synthetic_state: dict,
    meter_no: str,
) -> None:
    unmatched_id = seed_unmatched_review_record(manual_confirmed=True)
    state = local_simulation.get_state()
    record = next(item for item in state["scan_unmatched"] if item["unmatched_id"] == unmatched_id)
    record["meter_no"] = meter_no
    record["barcode"] = meter_no

    assert local_simulation.list_unmatched_match_candidates(unmatched_id) == {"total": 0, "items": []}


def test_unmatched_match_candidates_are_server_derived_deterministic_and_reject_invalid_terminals(
    synthetic_state: dict,
) -> None:
    unmatched_id = seed_unmatched_review_record(manual_confirmed=True)
    state = local_simulation.get_state()
    state["total_catalog"] = []

    assert local_simulation.list_unmatched_match_candidates(unmatched_id) == {"total": 0, "items": []}

    add_unmatched_match_catalog_row(catalog_id="catalog-invalid-empty", terminal="")
    add_unmatched_match_catalog_row(catalog_id="catalog-invalid-zero", terminal="00000000")
    add_unmatched_match_catalog_row(catalog_id="catalog-b", terminal="T-MATCH-B")
    add_unmatched_match_catalog_row(catalog_id="catalog-a", terminal="T-MATCH-A")

    multiple = local_simulation.list_unmatched_match_candidates(unmatched_id)
    assert multiple["total"] == 2
    assert [item["terminal"] for item in multiple["items"]] == ["T-MATCH-A", "T-MATCH-B"]
    assert all(item["candidate_key"].startswith("candidate:") for item in multiple["items"])

    state["total_catalog"] = [state["total_catalog"][-1]]
    unique = local_simulation.list_unmatched_match_candidates(unmatched_id)
    assert unique["total"] == 1
    assert unique["items"][0]["terminal"] == "T-MATCH-A"


def test_json_unmatched_search_includes_corrected_temporary_review_identity(
    synthetic_state: dict,
) -> None:
    unmatched_id = seed_unmatched_review_record()
    record = next(
        item
        for item in local_simulation.get_state()["scan_unmatched"]
        if item["unmatched_id"] == unmatched_id
    )
    review = unmatched_review.build_review(record)
    review["meter_no"] = "CORRECTED-METER-001"
    review["collector"] = "CORRECTED-COLLECTOR-001"
    review["module_asset_no"] = "CORRECTED-MODULE-001"
    record["temporary_review"] = review

    for query in ("CORRECTED-METER-001", "CORRECTED-COLLECTOR-001", "CORRECTED-MODULE-001"):
        result = local_simulation.list_unmatched_records(query=query, limit=20, offset=0)
        assert result["total"] == 1
        assert result["items"][0]["unmatched_id"] == unmatched_id


def test_json_candidate_view_is_audited_with_authenticated_actor(
    synthetic_state: dict,
) -> None:
    synthetic_state["total_catalog"] = []
    add_unmatched_match_catalog_row(terminal="T-CANDIDATE-AUDIT")
    unmatched_id = seed_unmatched_review_record(manual_confirmed=True)

    result = JsonStateRepository().list_unmatched_match_candidates(
        unmatched_id,
        actor="reviewer-a",
    )

    event = local_simulation.get_state()["audit_events"][-1]
    assert result["total"] == 1
    assert event["action"] == "unmatched_review_candidates_viewed"
    assert event["actor"] == "reviewer-a"
    assert event["payload"] == {
        "unmatched_id": unmatched_id,
        "review_version": 1,
        "candidate_count": 1,
        "candidate_digest": unmatched_review.candidate_snapshot_digest(result["items"]),
    }


def test_json_candidate_view_requires_manual_confirmation_without_audit(
    synthetic_state: dict,
) -> None:
    synthetic_state["total_catalog"] = []
    add_unmatched_match_catalog_row(terminal="T-CANDIDATE-CONFIRM")
    unmatched_id = seed_unmatched_review_record()
    before_audits = deepcopy(local_simulation.get_state()["audit_events"])

    with pytest.raises(ValueError, match="Manual confirmation required"):
        JsonStateRepository().list_unmatched_match_candidates(
            unmatched_id,
            actor="reviewer-a",
        )

    assert local_simulation.get_state()["audit_events"] == before_audits


def test_unmatched_match_requires_server_candidate_and_creates_no_placeholder(synthetic_state: dict) -> None:
    unmatched_id = seed_unmatched_review_record(manual_confirmed=True)
    local_simulation.get_state()["total_catalog"] = []
    review = local_simulation.get_unmatched_review(unmatched_id)["review"]

    with pytest.raises(ValueError, match="candidate"):
        local_simulation.finalize_unmatched_match(
            unmatched_id,
            actor="admin-a",
            candidate_key="catalog:missing",
            expected_version=review["version"],
        )

    state = local_simulation.get_state()
    assert all(task.get("terminal") != "00000000" for task in state["tasks"])
    assert all(group.get("terminal") != "00000000" for group in state["groups"])


@pytest.mark.parametrize(
    ("terminal", "meter_no"),
    [
        ("manual-1", "120000912473"),
        ("unmatched-1", "120000912473"),
        ("未关联终端", "120000912473"),
        ("00000000", "120000912473"),
        ("T-STRICT", "manual-1"),
        ("T-STRICT", "unmatched-1"),
        ("T-STRICT", "未关联终端"),
        ("T-STRICT", "00000000"),
    ],
)
def test_json_candidate_finalization_rejects_synthetic_identity_without_writes(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
    terminal: str,
    meter_no: str,
) -> None:
    unmatched_id = seed_unmatched_review_record(manual_confirmed=True)
    candidate_key = f"catalog:strict:{terminal}:{meter_no}"
    candidate = {
        "candidate_key": candidate_key,
        "target_group_id": "",
        "terminal": terminal,
        "meter_no": meter_no,
        "meter_match_key": "0000912473",
        "address": "strict road",
    }
    monkeypatch.setattr(
        local_simulation,
        "list_unmatched_match_candidates",
        lambda checked_id: {"total": 1, "items": [candidate]} if checked_id == unmatched_id else {"total": 0, "items": []},
    )
    before = deepcopy(local_simulation.get_state())

    with pytest.raises(ValueError, match="real (terminal|meter number)"):
        local_simulation.finalize_unmatched_match(
            unmatched_id,
            actor="admin-a",
            candidate_key=candidate_key,
            expected_version=1,
        )

    assert local_simulation.get_state() == before


def test_unmatched_finalize_migrates_review_recomputes_formal_status_and_removes_open_record(
    synthetic_state: dict,
) -> None:
    unmatched_id = seed_unmatched_review_record()
    local_simulation.get_state()["total_catalog"] = []
    add_unmatched_match_catalog_row()
    opened = local_simulation.get_unmatched_review(unmatched_id)
    saved = local_simulation.save_unmatched_review(
        unmatched_id,
        actor="reviewer-a",
        expected_version=opened["review"]["version"],
        photo_updates=[{"id": opened["review"]["photos"][0]["id"], "category": "before_box"}],
    )
    confirmed = local_simulation.confirm_unmatched_review(
        unmatched_id,
        actor="reviewer-a",
        expected_version=saved["review"]["version"],
    )
    stored_review = local_simulation.get_unmatched_record(unmatched_id)["temporary_review"]
    stored_review["photos"][0].update(
        {
            "barcode_check_status": "matched",
            "barcode_check_values": ["120000912473"],
            "barcode_check_ocr_values": ["OCR-120000912473"],
            "barcode_check_method": "barcode_ocr",
            "barcode_check_error": "",
        }
    )
    candidate = local_simulation.list_unmatched_match_candidates(unmatched_id)["items"][0]

    result = local_simulation.finalize_unmatched_match(
        unmatched_id,
        actor="admin-a",
        candidate_key=candidate["candidate_key"],
        expected_version=confirmed["review"]["version"],
    )

    group = result["group"]
    photo = group["photos"][0]
    assert group["terminal"] == candidate["terminal"]
    assert group["source_unmatched_id"] == unmatched_id
    assert group["group_barcode_manual_confirmed"] is False
    assert group["group_barcode_check_status"] != "matched"
    assert photo["category"] == "before_box"
    assert photo["source_url"] == opened["review"]["photos"][0]["source_url"]
    assert photo["barcode_check_values"] == ["120000912473"]
    assert photo["barcode_check_ocr_values"] == ["OCR-120000912473"]
    assert photo["barcode_check_method"] == "barcode_ocr"
    assert photo["temporary_review_manual_confirmed"] is True
    assert photo["temporary_review_reviewer"] == "reviewer-a"
    assert local_simulation.get_unmatched_record(unmatched_id) is None
    assert "00000000" not in str(result)


def test_unmatched_finalize_rejects_after_metadata_edit_revokes_confirmation(
    synthetic_state: dict,
) -> None:
    unmatched_id = seed_unmatched_review_record()
    local_simulation.get_state()["total_catalog"] = []
    add_unmatched_match_catalog_row()
    opened = local_simulation.get_unmatched_review(unmatched_id)
    photo_id = opened["review"]["photos"][0]["id"]
    classified = local_simulation.save_unmatched_review(
        unmatched_id,
        actor="reviewer-a",
        expected_version=opened["review"]["version"],
        photo_updates=[{"id": photo_id, "category": "before_box"}],
    )
    confirmed = local_simulation.confirm_unmatched_review(
        unmatched_id,
        actor="reviewer-a",
        expected_version=classified["review"]["version"],
    )
    candidate = local_simulation.list_unmatched_match_candidates(unmatched_id)["items"][0]
    edited = local_simulation.save_unmatched_review(
        unmatched_id,
        actor="reviewer-b",
        expected_version=confirmed["review"]["version"],
        metadata={"collector": "C002"},
        state="reviewed",
    )

    before_groups = deepcopy(local_simulation.get_state()["groups"])

    with pytest.raises(ValueError, match="Manual confirmation required"):
        local_simulation.finalize_unmatched_match(
            unmatched_id,
            actor="admin-a",
            candidate_key=candidate["candidate_key"],
            expected_version=edited["review"]["version"],
        )

    assert local_simulation.get_state()["groups"] == before_groups
    assert local_simulation.get_unmatched_record(unmatched_id)["temporary_review"]["manual_confirmed"] is False


def test_unmatched_finalize_rejects_after_rescan_revokes_confirmation(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unmatched_id = seed_unmatched_review_record()
    local_simulation.get_state()["total_catalog"] = []
    add_unmatched_match_catalog_row()
    opened = local_simulation.get_unmatched_review(unmatched_id)
    photo_id = opened["review"]["photos"][0]["id"]
    confirmed = local_simulation.confirm_unmatched_review(
        unmatched_id,
        actor="reviewer-a",
        expected_version=opened["review"]["version"],
    )
    candidate = local_simulation.list_unmatched_match_candidates(unmatched_id)["items"][0]
    monkeypatch.setattr(
        local_simulation.photo_barcode_check,
        "check_photo_barcode",
        lambda photo, group, *, use_ocr=False: {
            "barcode_check_status": "matched",
            "barcode_check_values": ["120000912473"],
            "barcode_check_method": "barcode_ocr",
        },
    )
    rescanned = local_simulation.rescan_unmatched_review_photo(
        unmatched_id,
        photo_id,
        actor="reviewer-b",
        expected_version=confirmed["review"]["version"],
        category="before_box",
    )

    before_groups = deepcopy(local_simulation.get_state()["groups"])

    with pytest.raises(ValueError, match="Manual confirmation required"):
        local_simulation.finalize_unmatched_match(
            unmatched_id,
            actor="admin-a",
            candidate_key=candidate["candidate_key"],
            expected_version=rescanned["review"]["version"],
        )

    assert local_simulation.get_state()["groups"] == before_groups
    assert local_simulation.get_unmatched_record(unmatched_id)["temporary_review"]["manual_confirmed"] is False


def test_unmatched_finalize_rejects_stale_version_before_any_formal_mutation(synthetic_state: dict) -> None:
    unmatched_id = seed_unmatched_review_record(manual_confirmed=True)
    local_simulation.get_state()["total_catalog"] = []
    add_unmatched_match_catalog_row()
    candidate = local_simulation.list_unmatched_match_candidates(unmatched_id)["items"][0]
    before = deepcopy(local_simulation.get_state())

    with pytest.raises(unmatched_review.ReviewVersionConflict):
        local_simulation.finalize_unmatched_match(
            unmatched_id,
            actor="admin-a",
            candidate_key=candidate["candidate_key"],
            expected_version=0,
        )

    assert local_simulation.get_state() == before


def test_unmatched_finalize_attaches_only_exact_meter_group_on_shared_terminal(synthetic_state: dict) -> None:
    unmatched_id = seed_unmatched_review_record(manual_confirmed=True)
    state = local_simulation.get_state()
    state["total_catalog"] = []
    catalog = add_unmatched_match_catalog_row(terminal="T-SHARED")
    template = deepcopy(state["groups"][0])
    unrelated = {
        **deepcopy(template),
        "id": "g-shared-a-unrelated",
        "terminal": "T-SHARED",
        "stage_terminal": "T-SHARED",
        "meter_no": "999999999999",
        "meter_match_key": "9999999999",
        "total_catalog_row_id": "catalog-unrelated",
        "photos": [],
        "photo_count": 0,
        "status": "incomplete",
    }
    exact = {
        **deepcopy(template),
        "id": "g-shared-z-exact",
        "terminal": "T-SHARED",
        "stage_terminal": "T-SHARED",
        "meter_no": catalog["meter_no"],
        "meter_match_key": catalog["meter_match_key"],
        "total_catalog_row_id": catalog["id"],
        "photos": [],
        "photo_count": 0,
        "status": "incomplete",
    }
    state["groups"].extend([unrelated, exact])

    candidate = local_simulation.list_unmatched_match_candidates(unmatched_id)["items"][0]
    assert candidate["target_group_id"] == exact["id"]

    result = local_simulation.finalize_unmatched_match(
        unmatched_id,
        actor="admin-a",
        candidate_key=candidate["candidate_key"],
        expected_version=1,
    )

    assert result["attached"] is True
    assert result["group"]["id"] == exact["id"]
    assert unrelated["meter_no"] == "999999999999"
    assert "source_unmatched_id" not in unrelated


def test_unmatched_finalize_merges_review_evidence_into_duplicate_photo(synthetic_state: dict) -> None:
    unmatched_id = seed_unmatched_review_record()
    state = local_simulation.get_state()
    state["total_catalog"] = []
    catalog = add_unmatched_match_catalog_row(terminal="T-DUPLICATE")
    record = next(item for item in state["scan_unmatched"] if item["unmatched_id"] == unmatched_id)
    review = unmatched_review.build_review(record)
    review["manual_confirmed"] = True
    review["reviewer"] = "reviewer-a"
    review["reviewed_at"] = "2026-07-13T09:00:00+00:00"
    review["photos"][0].update(
        {
            "category": "before_box",
            "qr_values": ["QR-001"],
            "ocr_normalized_values": ["ocr-001"],
            "barcode_rescanned_by": "reviewer-a",
            "barcode_rescanned_at": "2026-07-13T08:59:00+00:00",
        }
    )
    record["temporary_review"] = review
    template = deepcopy(state["groups"][0])
    existing_photo = deepcopy(template["photos"][0])
    existing_photo.update(
        {
            "id": "p-existing-duplicate",
            "image_url": review["photos"][0]["source_url"],
            "source_url": review["photos"][0]["source_url"],
            "source_fingerprint": "older-explicit-fingerprint",
            "category": "unclassified",
        }
    )
    existing_photo.pop("source_url_hash", None)
    group = {
        **template,
        "id": "g-duplicate-target",
        "terminal": "T-DUPLICATE",
        "stage_terminal": "T-DUPLICATE",
        "meter_no": catalog["meter_no"],
        "meter_match_key": catalog["meter_match_key"],
        "total_catalog_row_id": catalog["id"],
        "photos": [existing_photo],
        "photo_count": 1,
        "status": "incomplete",
    }
    state["groups"].append(group)
    candidate = local_simulation.list_unmatched_match_candidates(unmatched_id)["items"][0]

    result = local_simulation.finalize_unmatched_match(
        unmatched_id,
        actor="admin-a",
        candidate_key=candidate["candidate_key"],
        expected_version=1,
    )

    merged = next(photo for photo in result["group"]["photos"] if photo["id"] == "p-existing-duplicate")
    assert result["added_photos"] == 3
    assert merged["category"] == "before_box"
    assert merged["qr_values"] == ["QR-001"]
    assert merged["ocr_normalized_values"] == ["ocr-001"]
    assert merged["barcode_rescanned_by"] == "reviewer-a"
    assert merged["barcode_rescanned_at"] == "2026-07-13T08:59:00+00:00"
    assert merged["temporary_review_manual_confirmed"] is True
    assert merged["temporary_review_reviewer"] == "reviewer-a"
    assert merged["source_url"] == review["photos"][0]["source_url"]


def test_json_migrated_evidence_resets_whole_group_review_archive_and_exception_state(
    synthetic_state: dict,
) -> None:
    unmatched_id = seed_unmatched_review_record(
        photo_prefix="https://photos.example/whole-reset",
        manual_confirmed=True,
    )
    state = local_simulation.get_state()
    state["total_catalog"] = []
    catalog = add_unmatched_match_catalog_row(terminal="T-WHOLE-RESET")
    record = next(item for item in state["scan_unmatched"] if item["unmatched_id"] == unmatched_id)
    review = unmatched_review.build_review(record)
    categories = ["before_box", "collector_barcode", "module_meter", "after_box"]
    for photo, category in zip(review["photos"], categories, strict=True):
        photo["category"] = category
    review["photos"][0]["qr_values"] = ["QR-WHOLE-RESET"]
    record["temporary_review"] = review

    template = deepcopy(state["groups"][0])
    photo_template = deepcopy(template["photos"][0])
    existing_photos = []
    for index, review_photo in enumerate(review["photos"], start=1):
        existing = deepcopy(photo_template)
        existing.update(
            {
                "id": f"p-whole-reset-{index}",
                "source_url": review_photo["source_url"],
                "image_url": review_photo["source_url"],
                "source_fingerprint": f"existing-whole-reset-{index}",
                "sha256": "",
                "source_url_hash": "",
                "asset_no": f"asset-whole-reset-{index}",
                "category": "unclassified",
                "archive_status": "archived",
                "archive_filename": f"old-{index}.jpg",
                "archived_at": "2026-07-12T09:00:00+00:00",
                "classified_by": "reviewer-old",
                "classified_at": "2026-07-12T08:00:00+00:00",
            }
        )
        existing_photos.append(existing)
    group = {
        **template,
        "id": "g-whole-reset-target",
        "terminal": "T-WHOLE-RESET",
        "stage_terminal": "T-WHOLE-RESET",
        "meter_no": catalog["meter_no"],
        "meter_match_key": catalog["meter_match_key"],
        "total_catalog_row_id": catalog["id"],
        "photos": existing_photos,
        "photo_count": 4,
        "status": "approved",
        "reviewer": "reviewer-old",
        "review_note": "approved",
        "reviewed_at": "2026-07-12T09:00:00+00:00",
        "exception_status": "open",
        "exception_note": "stale exception",
        "exception_reasons": ["stale exception"],
        "exception_flags": ["stale exception"],
        "has_archive_blocker": True,
        "archive_status": "archived",
        "photo_category_complete": True,
        "photo_category_classified_count": 4,
        "classified_by": "reviewer-old",
        "classified_at": "2026-07-12T08:00:00+00:00",
        "bulk_archive_reason": "old archive",
    }
    state["groups"].append(group)
    candidate = local_simulation.list_unmatched_match_candidates(unmatched_id)["items"][0]

    result = local_simulation.finalize_unmatched_match(
        unmatched_id,
        actor="admin-a",
        candidate_key=candidate["candidate_key"],
        expected_version=1,
    )

    reset = result["group"]
    assert result["added_photos"] == 0
    assert reset["status"] == "pending"
    assert reset["reviewer"] is None
    assert reset["review_note"] == ""
    assert reset["reviewed_at"] is None
    assert reset["exception_status"] == ""
    assert reset["exception_note"] == ""
    assert reset["exception_reasons"] == []
    assert reset["exception_flags"] == []
    assert reset["has_archive_blocker"] is False
    for stale_key in (
        "archive_status",
        "photo_category_complete",
        "photo_category_classified_count",
        "classified_by",
        "classified_at",
        "bulk_archive_reason",
    ):
        assert stale_key not in reset
    assert [photo["category"] for photo in reset["photos"]] == categories
    assert reset["photos"][0]["qr_values"] == ["QR-WHOLE-RESET"]
    assert all(photo["archive_status"] == "pending" for photo in reset["photos"])
    assert all(photo["archive_filename"] == "" for photo in reset["photos"])
    assert all(photo["classified_by"] == "" for photo in reset["photos"])
    assert all(photo["classified_at"] == "" for photo in reset["photos"])


def test_unmatched_finalize_restores_complete_json_state_after_late_failure(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unmatched_id = seed_unmatched_review_record(manual_confirmed=True)
    state = local_simulation.get_state()
    state["total_catalog"] = []
    add_unmatched_match_catalog_row(terminal="T-ROLLBACK")
    candidate = local_simulation.list_unmatched_match_candidates(unmatched_id)["items"][0]
    before = deepcopy(state)

    def fail_after_all_state_writes() -> None:
        raise RuntimeError("late JSON persistence failure")

    monkeypatch.setattr(local_simulation, "save_all_team_states", fail_after_all_state_writes)

    with pytest.raises(RuntimeError, match="late JSON persistence failure"):
        local_simulation.finalize_unmatched_match(
            unmatched_id,
            actor="admin-a",
            candidate_key=candidate["candidate_key"],
            expected_version=1,
        )

    assert local_simulation.get_state() == before


def test_unmatched_finalize_interleaving_hides_partial_state_and_preserves_successful_write(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = local_simulation.get_state()
    state["total_catalog"] = []
    failing_id = seed_unmatched_review_record(
        meter_no="120000912473",
        photo_prefix="https://photos.example/failing",
        manual_confirmed=True,
    )
    successful_id = seed_unmatched_review_record(
        meter_no="120000912474",
        photo_prefix="https://photos.example/successful",
        manual_confirmed=True,
    )
    add_unmatched_match_catalog_row(
        catalog_id="catalog-failing",
        terminal="T-FAILING",
        meter_no="120000912473",
    )
    add_unmatched_match_catalog_row(
        catalog_id="catalog-successful",
        terminal="T-SUCCESSFUL",
        meter_no="120000912474",
    )
    failing_candidate = local_simulation.list_unmatched_match_candidates(failing_id)["items"][0]
    successful_candidate = local_simulation.list_unmatched_match_candidates(successful_id)["items"][0]
    failing_recompute_started = Event()
    release_failing_recompute = Event()
    original_recompute = local_simulation._apply_formal_group_barcode_check
    failure: list[Exception] = []
    successful_started = Event()
    successful_results: list[dict] = []
    successful_errors: list[Exception] = []

    def interleaved_recompute(group: dict) -> None:
        if group.get("source_unmatched_id") == failing_id:
            failing_recompute_started.set()
            if not release_failing_recompute.wait(timeout=5):
                raise TimeoutError("test did not release failing finalizer")
            raise RuntimeError("interleaved failing finalizer")
        original_recompute(group)

    def run_failing_finalizer() -> None:
        try:
            local_simulation.finalize_unmatched_match(
                failing_id,
                actor="admin-failing",
                candidate_key=failing_candidate["candidate_key"],
                expected_version=1,
            )
        except Exception as exc:
            failure.append(exc)

    def run_successful_finalizer() -> None:
        successful_started.set()
        try:
            successful_results.append(
                local_simulation.finalize_unmatched_match(
                    successful_id,
                    actor="admin-successful",
                    candidate_key=successful_candidate["candidate_key"],
                    expected_version=1,
                )
            )
        except Exception as exc:
            successful_errors.append(exc)

    monkeypatch.setattr(local_simulation, "_apply_formal_group_barcode_check", interleaved_recompute)
    thread = Thread(target=run_failing_finalizer)
    successful_thread = Thread(target=run_successful_finalizer)
    thread.start()
    assert failing_recompute_started.wait(timeout=5)

    try:
        live_during_failure = deepcopy(local_simulation.get_state())
        successful_thread.start()
        assert successful_started.wait(timeout=5)
        assert successful_thread.is_alive()
    finally:
        release_failing_recompute.set()
        thread.join(timeout=5)
        successful_thread.join(timeout=5)

    assert not thread.is_alive()
    assert not successful_thread.is_alive()
    assert len(failure) == 1
    assert isinstance(failure[0], RuntimeError)
    assert str(failure[0]) == "interleaved failing finalizer"
    assert successful_errors == []
    assert len(successful_results) == 1
    assert failing_id in {item["unmatched_id"] for item in live_during_failure["scan_unmatched"]}
    assert all(
        group.get("source_unmatched_id") != failing_id
        for group in live_during_failure["groups"]
    )

    final_state = local_simulation.get_state()
    assert local_simulation.get_unmatched_record(failing_id) is not None
    assert local_simulation.get_unmatched_record(successful_id) is None
    assert successful_results[0]["group"]["source_unmatched_id"] == successful_id
    assert any(group.get("source_unmatched_id") == successful_id for group in final_state["groups"])
    assert all(group.get("source_unmatched_id") != failing_id for group in final_state["groups"])
    finalized_ids = {
        event["payload"]["unmatched_id"]
        for event in final_state["audit_events"]
        if event["action"] == "unmatched_review_finalized"
    }
    assert finalized_ids == {successful_id}


def test_unmatched_authoritative_json_write_defers_internal_persistence_until_commit(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "authoritative-state.json"
    monkeypatch.setenv("LOCAL_SIMULATION_STATE_PATH", str(state_path))
    transaction = local_simulation.begin_authoritative_json_write()
    token = local_simulation.activate_authoritative_json_write(transaction)
    committed = False
    try:
        local_simulation.get_state()["audit_events"].append(
            {"id": "deferred-write", "action": "deferred", "actor": "test", "payload": {}}
        )
        local_simulation.save_all_team_states()
        assert state_path.exists() is False

        local_simulation.finish_authoritative_json_write(transaction, token)
        committed = True
    finally:
        if not committed and local_simulation._private_team_state.get() is transaction:
            local_simulation.abort_authoritative_json_write(transaction, token)

    assert state_path.exists() is True
    assert "deferred-write" in state_path.read_text(encoding="utf-8")


def test_fourth_review_partial_snapshot_failure_releases_team_ownership(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id = "task-4-partial-snapshot"
    local_simulation._team_states[team_id] = deepcopy(synthetic_state)
    local_simulation._team_states[team_id]["team_id"] = team_id
    original_deepcopy = local_simulation.copy.deepcopy
    failed = False

    class SnapshotAborted(BaseException):
        pass

    def fail_first_snapshot(value):
        nonlocal failed
        if not failed:
            failed = True
            raise SnapshotAborted("snapshot aborted")
        return original_deepcopy(value)

    monkeypatch.setattr(local_simulation.copy, "deepcopy", fail_first_snapshot)

    with pytest.raises(SnapshotAborted, match="snapshot aborted"):
        local_simulation.begin_authoritative_json_write(team_id)

    assert team_id not in local_simulation._authoritative_write_locks
    transaction = local_simulation.begin_authoritative_json_write(team_id)
    token = local_simulation.activate_authoritative_json_write(transaction)
    local_simulation.abort_authoritative_json_write(transaction, token)


def test_fourth_review_cancelled_finalizer_releases_team_for_reacquisition(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id = "task-4-cancelled-finalizer"
    local_simulation._team_states[team_id] = deepcopy(synthetic_state)
    local_simulation._team_states[team_id]["team_id"] = team_id
    team_token = local_simulation.set_current_team(team_id)
    try:
        state = local_simulation.get_state()
        state["total_catalog"] = []
        unmatched_id = seed_unmatched_review_record(manual_confirmed=True)
        add_unmatched_match_catalog_row(terminal="T-CANCELLED")
        candidate = local_simulation.list_unmatched_match_candidates(unmatched_id)["items"][0]

        def cancel_after_staged_writes(_group: dict) -> None:
            raise CancelledError("cancel finalizer")

        monkeypatch.setattr(local_simulation, "_apply_formal_group_barcode_check", cancel_after_staged_writes)

        with pytest.raises(CancelledError, match="cancel finalizer"):
            local_simulation.finalize_unmatched_match(
                unmatched_id,
                actor="admin-cancelled",
                candidate_key=candidate["candidate_key"],
                expected_version=1,
            )

        assert team_id not in local_simulation._authoritative_write_locks
        transaction = local_simulation.begin_authoritative_json_write(team_id)
        token = local_simulation.activate_authoritative_json_write(transaction)
        local_simulation.get_state()["audit_events"].append(
            {"id": "after-cancel", "action": "after-cancel", "actor": "test", "payload": {}}
        )
        local_simulation.finish_authoritative_json_write(transaction, token)
        assert any(event["id"] == "after-cancel" for event in local_simulation.get_state()["audit_events"])
    finally:
        local_simulation.reset_current_team(team_token)


def test_fourth_review_missing_team_stays_private_until_commit() -> None:
    team_id = "task-4-private-missing-team"
    local_simulation._team_states.pop(team_id, None)
    local_simulation._authoritative_write_locks.pop(team_id, None)
    team_token = local_simulation.set_current_team(team_id)
    try:
        transaction = local_simulation.begin_authoritative_json_write(team_id)
        token = local_simulation.activate_authoritative_json_write(transaction)
        local_simulation.get_state()["audit_events"].append(
            {"id": "private-write", "action": "private", "actor": "test", "payload": {}}
        )

        assert team_id not in local_simulation._team_states
        local_simulation.abort_authoritative_json_write(transaction, token)
        assert team_id not in local_simulation._team_states
        assert team_id not in local_simulation._authoritative_write_locks

        transaction = local_simulation.begin_authoritative_json_write(team_id)
        token = local_simulation.activate_authoritative_json_write(transaction)
        local_simulation.get_state()["audit_events"].append(
            {"id": "committed-write", "action": "committed", "actor": "test", "payload": {}}
        )
        local_simulation.finish_authoritative_json_write(transaction, token)

        assert team_id in local_simulation._team_states
        assert team_id not in local_simulation._authoritative_write_locks
        assert [event["id"] for event in local_simulation._team_states[team_id]["audit_events"]] == ["committed-write"]
    finally:
        local_simulation.reset_current_team(team_token)


def test_fourth_review_delivery_cache_submission_is_discarded_on_late_failure(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = synthetic_state["groups"][0]
    group["status"] = "approved"
    submitted: list[tuple] = []

    class CapturingExecutor:
        def submit(self, callback, *args):
            submitted.append((callback, args))

    monkeypatch.setattr(local_simulation, "_delivery_cache_executor", CapturingExecutor())
    monkeypatch.setattr(local_simulation, "photo_can_build_delivery_cache", lambda _photo: True)
    transaction = local_simulation.begin_authoritative_json_write()
    token = local_simulation.activate_authoritative_json_write(transaction)
    try:
        local_simulation.schedule_delivery_cache_build(group["id"])

        assert submitted == []

        def fail_late_persistence() -> None:
            raise RuntimeError("late request persistence failure")

        with pytest.raises(RuntimeError, match="late request persistence failure"):
            local_simulation.finish_authoritative_json_write(transaction, token, persist=fail_late_persistence)

        assert submitted == []
        assert (local_simulation.DEFAULT_TEAM_ID, group["id"]) not in local_simulation._delivery_cache_inflight
    finally:
        if local_simulation._private_team_state.get() is transaction:
            local_simulation.abort_authoritative_json_write(transaction, token)
        local_simulation._delivery_cache_inflight.discard((local_simulation.DEFAULT_TEAM_ID, group["id"]))


def test_fourth_review_delivery_cache_worker_serializes_with_finalizer(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    group = synthetic_state["groups"][0]
    group["status"] = "approved"
    group["photos"][0]["image_url"] = "https://example.test/cache-worker.jpg"
    state = local_simulation.get_state()
    state["total_catalog"] = []
    unmatched_id = seed_unmatched_review_record(
        meter_no="120000912474",
        photo_prefix="https://photos.example/cache-finalizer",
        manual_confirmed=True,
    )
    add_unmatched_match_catalog_row(
        catalog_id="catalog-cache-finalizer",
        terminal="T-CACHE-FINALIZER",
        meter_no="120000912474",
    )
    candidate = local_simulation.list_unmatched_match_candidates(unmatched_id)["items"][0]
    submitted: list[tuple] = []

    class CapturingExecutor:
        def submit(self, callback, *args):
            submitted.append((callback, args))

    monkeypatch.setattr(local_simulation, "_delivery_cache_executor", CapturingExecutor())
    monkeypatch.setattr(local_simulation.settings, "delivery_cache_path", str(tmp_path))
    monkeypatch.setattr(local_simulation, "photo_can_build_delivery_cache", lambda _photo: True)
    transaction = local_simulation.begin_authoritative_json_write()
    token = local_simulation.activate_authoritative_json_write(transaction)
    try:
        local_simulation.schedule_delivery_cache_build(group["id"])
        assert submitted == []
        local_simulation.finish_authoritative_json_write(transaction, token)
    finally:
        if local_simulation._private_team_state.get() is transaction:
            local_simulation.abort_authoritative_json_write(transaction, token)
        local_simulation._delivery_cache_inflight.discard((local_simulation.DEFAULT_TEAM_ID, group["id"]))
    assert len(submitted) == 1

    finalizer_staged = Event()
    release_finalizer = Event()
    worker_mutating = Event()
    original_recompute = local_simulation._apply_formal_group_barcode_check

    def pause_finalizer(group_state: dict) -> None:
        if group_state.get("source_unmatched_id") == unmatched_id:
            finalizer_staged.set()
            if not release_finalizer.wait(timeout=5):
                raise TimeoutError("test did not release cache finalizer")
        original_recompute(group_state)

    def tracked_download(_photo: dict):
        worker_mutating.set()
        return b"cached-photo", ".jpg", "image/jpeg"

    monkeypatch.setattr(local_simulation, "_apply_formal_group_barcode_check", pause_finalizer)
    monkeypatch.setattr(local_simulation, "download_delivery_photo_content", tracked_download)
    finalizer_errors: list[BaseException] = []

    def run_finalizer() -> None:
        try:
            local_simulation.finalize_unmatched_match(
                unmatched_id,
                actor="admin-finalizer",
                candidate_key=candidate["candidate_key"],
                expected_version=1,
            )
        except BaseException as exc:
            finalizer_errors.append(exc)

    callback, args = submitted[0]
    finalizer_thread = Thread(target=run_finalizer)
    worker_thread = Thread(target=callback, args=args)
    finalizer_thread.start()
    assert finalizer_staged.wait(timeout=5)
    worker_thread.start()
    try:
        assert worker_mutating.wait(timeout=0.2) is False
    finally:
        release_finalizer.set()
        finalizer_thread.join(timeout=5)
        worker_thread.join(timeout=5)

    assert finalizer_errors == []
    assert not finalizer_thread.is_alive()
    assert not worker_thread.is_alive()
    assert worker_mutating.is_set()
    assert local_simulation.get_group(group["id"])["delivery_cache_status"] == "ready"


def test_json_state_repository_finalizes_unmatched_match_from_server_candidate(synthetic_state: dict) -> None:
    repository = JsonStateRepository()
    unmatched_id = seed_unmatched_review_record(manual_confirmed=True)
    local_simulation.get_state()["total_catalog"] = []
    add_unmatched_match_catalog_row(terminal="T-JSON-FINAL")
    review = repository.get_unmatched_review(unmatched_id)["review"]
    candidate = repository.list_unmatched_match_candidates(unmatched_id)["items"][0]

    result = repository.finalize_unmatched_match(
        unmatched_id,
        actor="admin-a",
        candidate_key=candidate["candidate_key"],
        expected_version=review["version"],
    )

    assert result["group"]["terminal"] == "T-JSON-FINAL"
    assert local_simulation.get_unmatched_record(unmatched_id) is None


def test_json_repository_reselects_compatible_formal_meter_identity_before_mutation(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = JsonStateRepository()
    state = local_simulation.get_state()
    state["total_catalog"] = []
    catalog = add_unmatched_match_catalog_row(terminal="T-ROUND6-COMPAT")
    existing = {
        **deepcopy(state["groups"][0]),
        "id": "g-round6-compatible",
        "terminal": catalog["terminal"],
        "stage_terminal": catalog["terminal"],
        "meter_no": catalog["meter_no"],
        "meter_match_key": catalog["meter_match_key"],
        "photos": [],
        "photo_count": 0,
    }
    state["groups"].append(existing)
    unmatched_id = seed_unmatched_review_record(manual_confirmed=True)
    candidate = repository.list_unmatched_match_candidates(unmatched_id)["items"][0]
    candidate = {**candidate, "target_group_id": ""}
    monkeypatch.setattr(
        local_simulation,
        "list_unmatched_match_candidates",
        lambda checked_id: {"total": 1, "items": [candidate]} if checked_id == unmatched_id else {"total": 0, "items": []},
    )
    before_group_count = len(state["groups"])

    result = repository.finalize_unmatched_match(
        unmatched_id,
        actor="admin-round6",
        candidate_key=candidate["candidate_key"],
        expected_version=1,
    )

    assert result["attached"] is True
    assert result["group"]["id"] == existing["id"]
    assert len(local_simulation.get_state()["groups"]) == before_group_count


def test_json_repository_rejects_incompatible_formal_meter_identity_without_any_write(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = JsonStateRepository()
    state = local_simulation.get_state()
    state["total_catalog"] = []
    catalog = add_unmatched_match_catalog_row(terminal="T-ROUND6-NEW")
    existing = {
        **deepcopy(state["groups"][0]),
        "id": "g-round6-incompatible",
        "terminal": "T-ROUND6-OLD",
        "stage_terminal": "T-ROUND6-OLD",
        "meter_no": catalog["meter_no"],
        "meter_match_key": catalog["meter_match_key"],
        "photos": [],
        "photo_count": 0,
    }
    state["groups"].append(existing)
    unmatched_id = seed_unmatched_review_record(manual_confirmed=True)
    candidate = repository.list_unmatched_match_candidates(unmatched_id)["items"][0]
    assert candidate["target_group_id"] == ""
    state_path = tmp_path / "round6-json-identity-state.json"
    monkeypatch.setenv("LOCAL_SIMULATION_STATE_PATH", str(state_path))
    local_simulation.refresh_summary()
    local_simulation.save_all_team_states()
    before = deepcopy(state)
    before_bytes = state_path.read_bytes()

    with pytest.raises(unmatched_review.FinalizationIdentityConflict):
        repository.finalize_unmatched_match(
            unmatched_id,
            actor="admin-round6",
            candidate_key=candidate["candidate_key"],
            expected_version=1,
        )

    after = state
    for field in ("groups", "tasks", "summary", "audit_events", "unmatched_finalization_replays"):
        assert after[field] == before[field]
    assert after == before
    assert state_path.read_bytes() == before_bytes


def test_round7_audit_redaction_covers_provider_uri_link_path_and_name_variants() -> None:
    payload = {
        "presignedUri": "secret-a",
        "rawSignedURI": "secret-b",
        "signed-link": "secret-c",
        "s3Key": "secret-d",
        "cos_object_name": "secret-e",
        "ossPath": "secret-f",
        "objectPath": "secret-g",
        "candidate_key": "catalog:1:T-001",
        "opaque_candidate_key": f"candidate:{'a' * 64}",
        "project_id": "1",
    }

    redacted = unmatched_review.redact_audit_photo_secrets(payload)

    for key in ("presignedUri", "rawSignedURI", "signed-link", "s3Key", "cos_object_name", "ossPath", "objectPath"):
        assert redacted[key] == unmatched_review.AUDIT_REDACTED_VALUE
    assert redacted["candidate_key"] == unmatched_review.AUDIT_REDACTED_VALUE
    assert redacted["opaque_candidate_key"] == payload["opaque_candidate_key"]
    assert redacted["project_id"] == payload["project_id"]


def test_json_migrated_photo_ids_do_not_collide_across_unmatched_records(synthetic_state: dict) -> None:
    repository = JsonStateRepository()
    state = local_simulation.get_state()
    state["total_catalog"] = []
    add_unmatched_match_catalog_row(terminal="T-JSON-SHARED")

    first_id = seed_unmatched_review_record(
        photo_prefix="https://photos.example/first",
        manual_confirmed=True,
    )
    first_candidate = repository.list_unmatched_match_candidates(first_id)["items"][0]
    first = repository.finalize_unmatched_match(
        first_id,
        actor="admin-a",
        candidate_key=first_candidate["candidate_key"],
        expected_version=1,
    )

    second_id = seed_unmatched_review_record(
        photo_prefix="https://photos.example/second",
        manual_confirmed=True,
    )
    second_review = repository.get_unmatched_review(second_id)["review"]
    second_candidate = repository.list_unmatched_match_candidates(second_id)["items"][0]
    second = repository.finalize_unmatched_match(
        second_id,
        actor="admin-a",
        candidate_key=second_candidate["candidate_key"],
        expected_version=1,
    )

    group_id = second["group"]["id"]
    photo_ids = [photo["id"] for photo in second["group"]["photos"]]
    expected_second_ids = {
        f"p-unmatched-{second_id}-{hashlib.sha256(photo['id'].encode('utf-8')).hexdigest()[:16]}"
        for photo in second_review["photos"]
    }
    assert second["group"]["id"] == first["group"]["id"]
    assert len(photo_ids) == 8
    assert len(photo_ids) == len(set(photo_ids))
    assert expected_second_ids.issubset(photo_ids)


def test_json_finalize_exact_replay_uses_authoritative_ledger_without_duplicate_writes(
    synthetic_state: dict,
) -> None:
    repository = JsonStateRepository()
    state = local_simulation.get_state()
    state["total_catalog"] = []
    add_unmatched_match_catalog_row(terminal="T-JSON-REPLAY")
    unmatched_id = seed_unmatched_review_record(
        photo_prefix="https://photos.example/json-replay",
        manual_confirmed=True,
    )
    candidate = repository.list_unmatched_match_candidates(unmatched_id)["items"][0]

    first = repository.finalize_unmatched_match(
        unmatched_id,
        actor="admin-a",
        candidate_key=candidate["candidate_key"],
        expected_version=1,
    )
    after_first = deepcopy(local_simulation.get_state())
    second = repository.finalize_unmatched_match(
        unmatched_id,
        actor="admin-retry",
        candidate_key=candidate["candidate_key"],
        expected_version=1,
    )

    replay_key = f"{local_simulation.current_team_id()}:{unmatched_id}"
    ledger = local_simulation.get_state()["unmatched_finalization_replays"]
    assert second == first
    assert local_simulation.get_state() == after_first
    assert ledger[replay_key] == {
        "status": "associated",
        "candidate_key": candidate["candidate_key"],
        "expected_version": 1,
        "result": first,
    }

    second["group"]["terminal"] = "tampered-return"
    third = repository.finalize_unmatched_match(
        unmatched_id,
        actor="admin-retry",
        candidate_key=candidate["candidate_key"],
        expected_version=1,
    )
    assert third == first
    assert ledger[replay_key]["result"] == first

    with pytest.raises(KeyError):
        repository.finalize_unmatched_match(
            unmatched_id,
            actor="admin-retry",
            candidate_key="catalog:different:T-JSON-REPLAY",
            expected_version=1,
        )
    with pytest.raises(KeyError):
        repository.finalize_unmatched_match(
            unmatched_id,
            actor="admin-retry",
            candidate_key=candidate["candidate_key"],
            expected_version=2,
        )
    assert local_simulation.get_state() == after_first


def test_json_finalize_requires_manual_confirmation_without_mutating_state(
    synthetic_state: dict,
) -> None:
    synthetic_state["total_catalog"] = []
    add_unmatched_match_catalog_row(terminal="T-CONFIRM-REQUIRED")
    unmatched_id = seed_unmatched_review_record(
        photo_prefix="https://photos.example/confirm-required",
        manual_confirmed=True,
    )
    candidate = local_simulation.list_unmatched_match_candidates(unmatched_id)["items"][0]
    record = local_simulation.get_unmatched_record(unmatched_id)
    record["temporary_review"]["manual_confirmed"] = False
    record["temporary_review"]["reviewer"] = ""
    record["temporary_review"]["reviewed_at"] = ""
    before = deepcopy(local_simulation.get_state())

    with pytest.raises(ValueError, match="Manual confirmation required"):
        local_simulation.finalize_unmatched_match(
            unmatched_id,
            actor="admin-a",
            candidate_key=candidate["candidate_key"],
            expected_version=1,
        )

    assert local_simulation.get_state() == before


def test_json_legacy_identity_patch_syncs_review_and_revokes_confirmation(
    synthetic_state: dict,
) -> None:
    unmatched_id = seed_unmatched_review_record()
    confirmed = local_simulation.confirm_unmatched_review(
        unmatched_id,
        actor="reviewer-a",
        expected_version=1,
    )

    updated = local_simulation.update_unmatched_record(
        unmatched_id,
        actor="admin-a",
        expected_version=confirmed["review"]["version"],
        updates={
            "meter_no": "120000912474",
            "collector": "C002",
            "module_asset_no": "M002",
        },
    )

    review = updated["temporary_review"]
    assert review["meter_no"] == "120000912474"
    assert review["collector"] == "C002"
    assert review["module_asset_no"] == "M002"
    assert review["manual_confirmed"] is False
    assert review["reviewer"] == ""
    assert review["reviewed_at"] == ""


def test_json_asset_no_alias_syncs_canonical_module_and_revokes_confirmation(
    synthetic_state: dict,
) -> None:
    unmatched_id = seed_unmatched_review_record()
    confirmed = local_simulation.confirm_unmatched_review(
        unmatched_id,
        actor="reviewer-a",
        expected_version=1,
    )

    updated = local_simulation.update_unmatched_record(
        unmatched_id,
        actor="admin-a",
        expected_version=confirmed["review"]["version"],
        updates={"asset_no": "M002"},
    )

    review = updated["temporary_review"]
    assert updated["module_asset_no"] == "M002"
    assert updated["asset_no"] == "M002"
    assert review["module_asset_no"] == "M002"
    assert review["manual_confirmed"] is False
    assert review["reviewer"] == ""
    assert review["reviewed_at"] == ""


def test_unmatched_review_save_persists_without_creating_group_or_changing_summary(synthetic_state: dict) -> None:
    unmatched_id = seed_unmatched_review_record()
    before = deepcopy(local_simulation.get_state())

    opened = local_simulation.get_unmatched_review(unmatched_id)
    saved = local_simulation.save_unmatched_review(
        unmatched_id,
        actor="reviewer-a",
        expected_version=opened["review"]["version"],
        metadata={"meter_no": "120000912474"},
        photo_updates=[{"id": opened["review"]["photos"][0]["id"], "category": "before_box"}],
        state="reviewed",
    )
    after = local_simulation.get_state()
    events = [event for event in after["audit_events"] if event["action"] == "unmatched_review_saved"]

    assert saved["review"]["meter_no"] == "120000912474"
    assert saved["review"]["photos"][0]["category"] == "before_box"
    assert saved["record"]["temporary_review"] == saved["review"]
    assert "audit_event" not in saved["review"]
    assert len(events) == 1
    assert events[0]["actor"] == "reviewer-a"
    assert events[0]["payload"]["before_version"] == 1
    assert events[0]["payload"]["after_version"] == 2
    assert "audit_event" not in events[0]["payload"]["after"]
    assert after["groups"] == before["groups"]
    assert after["tasks"] == before["tasks"]
    assert after["summary"] == before["summary"]
    assert [
        (task["id"], task["terminal"], task["status"])
        for task in after["tasks"]
    ] == [
        (task["id"], task["terminal"], task["status"])
        for task in before["tasks"]
    ]
    assert {
        key: after["summary"][key]
        for key in (
            "groups",
            "matched_groups",
            "incomplete_groups",
            "approved_groups",
            "exception_groups",
            "review_progress",
            "photo_accuracy_checked",
            "photo_accuracy_passed",
            "photo_accuracy_failed",
            "photo_accuracy_unreadable",
            "photo_accuracy_rate",
            "group_barcode_accuracy_checked",
            "group_barcode_accuracy_passed",
            "group_barcode_accuracy_failed",
            "group_barcode_accuracy_unreadable",
            "group_barcode_accuracy_rate",
        )
    } == {
        key: before["summary"][key]
        for key in (
            "groups",
            "matched_groups",
            "incomplete_groups",
            "approved_groups",
            "exception_groups",
            "review_progress",
            "photo_accuracy_checked",
            "photo_accuracy_passed",
            "photo_accuracy_failed",
            "photo_accuracy_unreadable",
            "photo_accuracy_rate",
            "group_barcode_accuracy_checked",
            "group_barcode_accuracy_passed",
            "group_barcode_accuracy_failed",
            "group_barcode_accuracy_unreadable",
            "group_barcode_accuracy_rate",
        )
    }
    assert [
        (group["id"], [(photo["id"], photo.get("archive_status")) for photo in group["photos"]])
        for group in after["groups"]
    ] == [
        (group["id"], [(photo["id"], photo.get("archive_status")) for photo in group["photos"]])
        for group in before["groups"]
    ]
    assert "00000000" not in str(after["groups"])
    assert "00000000" not in str(after["tasks"])
    assert "00000000" not in str(after["summary"])


def test_unmatched_review_save_rejects_stale_version_without_persisting_or_auditing(synthetic_state: dict) -> None:
    unmatched_id = seed_unmatched_review_record()
    opened = local_simulation.get_unmatched_review(unmatched_id)
    saved = local_simulation.save_unmatched_review(
        unmatched_id,
        actor="reviewer-a",
        expected_version=opened["review"]["version"],
        metadata={"meter_no": "120000912474"},
    )

    with pytest.raises(unmatched_review.ReviewVersionConflict):
        local_simulation.save_unmatched_review(
            unmatched_id,
            actor="reviewer-b",
            expected_version=opened["review"]["version"],
            metadata={"meter_no": "120000912475"},
        )

    reloaded = local_simulation.get_unmatched_review(unmatched_id)
    events = [event for event in local_simulation.get_state()["audit_events"] if event["action"] == "unmatched_review_saved"]
    assert reloaded["review"] == saved["review"]
    assert len(events) == 1


def test_unmatched_review_save_persists_across_json_reload(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCAL_SIMULATION_STATE_PATH", str(tmp_path / "state.json"))
    unmatched_id = seed_unmatched_review_record()
    opened = local_simulation.get_unmatched_review(unmatched_id)
    saved = local_simulation.save_unmatched_review(
        unmatched_id,
        actor="reviewer-a",
        expected_version=opened["review"]["version"],
        metadata={"collector": "C002"},
    )

    local_simulation.get_state()["scan_unmatched"] = []
    assert local_simulation.load_all_team_states() is True
    reloaded = local_simulation.get_unmatched_review(unmatched_id)
    events = [event for event in local_simulation.get_state()["audit_events"] if event["action"] == "unmatched_review_saved"]

    assert reloaded["review"] == saved["review"]
    assert len(events) == 1


def test_unmatched_review_open_return_values_are_mutation_isolated(synthetic_state: dict) -> None:
    unmatched_id = seed_unmatched_review_record()
    initial = local_simulation.get_unmatched_review(unmatched_id)
    local_simulation.save_unmatched_review(
        unmatched_id,
        actor="reviewer-a",
        expected_version=initial["review"]["version"],
        photo_updates=[{"id": initial["review"]["photos"][0]["id"], "category": "before_box"}],
    )
    before = deepcopy(local_simulation.get_state())

    opened = local_simulation.get_unmatched_review(unmatched_id)
    opened["record"]["temporary_review"]["photos"][0]["category"] = "after_box"
    opened["review"]["meter_no"] = "mutated-meter"

    after = local_simulation.get_state()
    persisted = local_simulation.get_unmatched_review(unmatched_id)
    assert after == before
    assert persisted["review"]["version"] == before["scan_unmatched"][-1]["temporary_review"]["version"]
    assert persisted["review"]["photos"][0]["category"] == "before_box"
    assert after["audit_events"] == before["audit_events"]


def test_unmatched_review_save_return_values_are_mutation_isolated(synthetic_state: dict) -> None:
    unmatched_id = seed_unmatched_review_record()
    opened = local_simulation.get_unmatched_review(unmatched_id)
    saved = local_simulation.save_unmatched_review(
        unmatched_id,
        actor="reviewer-a",
        expected_version=opened["review"]["version"],
        photo_updates=[{"id": opened["review"]["photos"][0]["id"], "category": "before_box"}],
    )
    before = deepcopy(local_simulation.get_state())

    saved["record"]["temporary_review"]["meter_no"] = "mutated-meter"
    saved["review"]["photos"][0]["category"] = "after_box"

    after = local_simulation.get_state()
    persisted = local_simulation.get_unmatched_review(unmatched_id)
    assert after == before
    assert persisted["review"]["version"] == before["scan_unmatched"][-1]["temporary_review"]["version"]
    assert persisted["review"]["meter_no"] != "mutated-meter"
    assert persisted["review"]["photos"][0]["category"] == "before_box"
    assert after["audit_events"] == before["audit_events"]


def test_json_state_repository_saves_unmatched_review_through_local_state(synthetic_state: dict) -> None:
    repository = JsonStateRepository()
    unmatched_id = seed_unmatched_review_record()
    opened = repository.get_unmatched_review(unmatched_id)

    saved = repository.save_unmatched_review(
        unmatched_id,
        actor="reviewer-a",
        expected_version=opened["review"]["version"],
        metadata={"module_asset_no": "M002"},
    )

    assert saved["review"]["module_asset_no"] == "M002"
    assert local_simulation.get_unmatched_review(unmatched_id)["review"] == saved["review"]


def test_unmatched_rescan_uses_ocr_persists_audits_and_keeps_formal_accuracy_unchanged(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unmatched_id = seed_unmatched_review_record()
    opened = local_simulation.get_unmatched_review(unmatched_id)
    photo_id = opened["review"]["photos"][0]["id"]
    before = deepcopy(local_simulation.get_state())
    calls: list[dict] = []

    def check_photo_barcode(photo: dict, group: dict, *, use_ocr: bool = False) -> dict:
        calls.append({"photo": photo, "group": group, "use_ocr": use_ocr})
        return {
            "barcode_check_status": "matched",
            "barcode_check_values": ["120000912473"],
            "barcode_check_ocr_values": ["120000912473"],
            "barcode_check_method": "barcode_ocr",
        }

    monkeypatch.setattr(local_simulation.photo_barcode_check, "check_photo_barcode", check_photo_barcode)

    result = local_simulation.rescan_unmatched_review_photo(
        unmatched_id,
        photo_id,
        actor="reviewer-a",
        expected_version=opened["review"]["version"],
        category="module_meter",
    )
    persisted = local_simulation.get_unmatched_review(unmatched_id)
    events = [
        event
        for event in local_simulation.get_state()["audit_events"]
        if event["action"] == "unmatched_review_barcode_rescan"
    ]

    assert len(calls) == 1
    assert calls[0]["use_ocr"] is True
    assert calls[0]["photo"]["image_url"] == opened["review"]["photos"][0]["source_url"]
    assert calls[0]["photo"]["category"] == "module_meter"
    assert {
        key: calls[0]["group"][key]
        for key in ("meter_no", "meter_match_key", "collector", "module_asset_no")
    } == {
        key: unmatched_review.barcode_context(opened["review"])[key]
        for key in ("meter_no", "meter_match_key", "collector", "module_asset_no")
    }
    assert result["photo"]["barcode_check_method"] == "barcode_ocr"
    assert result["review"]["version"] == opened["review"]["version"] + 1
    assert persisted["review"] == result["review"]
    assert len(events) == 1
    assert events[0]["actor"] == "reviewer-a"
    assert events[0]["payload"]["unmatched_id"] == unmatched_id
    assert events[0]["payload"]["photo_id"] == photo_id
    assert events[0]["payload"]["result"]["barcode_check_method"] == "barcode_ocr"
    assert local_simulation.get_state()["groups"] == before["groups"]
    assert local_simulation.get_state()["tasks"] == before["tasks"]
    assert local_simulation.get_state()["summary"] == before["summary"]


def test_unmatched_rescan_invalidates_prior_manual_confirmation(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unmatched_id = seed_unmatched_review_record()
    opened = local_simulation.get_unmatched_review(unmatched_id)
    photo_id = opened["review"]["photos"][0]["id"]
    confirmed = local_simulation.confirm_unmatched_review(
        unmatched_id,
        actor="reviewer-a",
        expected_version=opened["review"]["version"],
    )
    monkeypatch.setattr(
        local_simulation.photo_barcode_check,
        "check_photo_barcode",
        lambda photo, group, *, use_ocr=False: {
            "barcode_check_status": "matched",
            "barcode_check_values": ["120000912473"],
        },
    )

    rescanned = local_simulation.rescan_unmatched_review_photo(
        unmatched_id,
        photo_id,
        actor="reviewer-b",
        expected_version=confirmed["review"]["version"],
    )

    assert rescanned["review"]["manual_confirmed"] is False
    assert rescanned["review"]["reviewed_at"] == ""
    events = [
        event
        for event in local_simulation.get_state()["audit_events"]
        if event["action"] == "unmatched_review_barcode_rescan"
    ]
    assert events[-1]["payload"]["before_confirmation"] == {
        "manual_confirmed": True,
        "reviewed_at": confirmed["review"]["reviewed_at"],
    }
    assert events[-1]["payload"]["after_confirmation"] == {
        "manual_confirmed": False,
        "reviewed_at": "",
    }


def test_unmatched_rescan_rechecks_version_after_scan_before_persisting(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unmatched_id = seed_unmatched_review_record()
    opened = local_simulation.get_unmatched_review(unmatched_id)
    photo_id = opened["review"]["photos"][0]["id"]

    def drifting_scan(photo: dict, group: dict, *, use_ocr: bool = False) -> dict:
        local_simulation.save_unmatched_review(
            unmatched_id,
            actor="reviewer-concurrent",
            expected_version=opened["review"]["version"],
            metadata={"collector": "C-CONCURRENT"},
        )
        return {"barcode_check_status": "matched", "barcode_check_values": ["120000912473"]}

    monkeypatch.setattr(local_simulation.photo_barcode_check, "check_photo_barcode", drifting_scan)

    with pytest.raises(unmatched_review.ReviewVersionConflict):
        local_simulation.rescan_unmatched_review_photo(
            unmatched_id,
            photo_id,
            actor="reviewer-a",
            expected_version=opened["review"]["version"],
        )

    persisted = local_simulation.get_unmatched_review(unmatched_id)["review"]
    assert persisted["collector"] == "C-CONCURRENT"
    assert persisted["version"] == opened["review"]["version"] + 1
    assert persisted["photos"][0]["barcode_check_status"] == "not_checked"
    assert not any(
        event["action"] == "unmatched_review_barcode_rescan"
        for event in local_simulation.get_state()["audit_events"]
    )


def test_unmatched_rescan_return_value_is_mutation_isolated(synthetic_state: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    unmatched_id = seed_unmatched_review_record()
    opened = local_simulation.get_unmatched_review(unmatched_id)
    photo_id = opened["review"]["photos"][0]["id"]
    monkeypatch.setattr(
        local_simulation.photo_barcode_check,
        "check_photo_barcode",
        lambda photo, group, *, use_ocr=False: {"barcode_check_status": "unreadable"},
    )

    result = local_simulation.rescan_unmatched_review_photo(
        unmatched_id,
        photo_id,
        actor="reviewer-a",
        expected_version=opened["review"]["version"],
    )
    before = deepcopy(local_simulation.get_state())
    result["record"]["temporary_review"]["meter_no"] = "mutated-meter"
    result["photo"]["barcode_check_status"] = "mutated-status"

    assert local_simulation.get_state() == before
    persisted = local_simulation.get_unmatched_review(unmatched_id)
    assert persisted["review"]["meter_no"] != "mutated-meter"
    assert persisted["review"]["photos"][0]["barcode_check_status"] == "unreadable"


def test_unmatched_rescan_rejects_stale_expected_version_without_scanning_or_persisting(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unmatched_id = seed_unmatched_review_record()
    opened = local_simulation.get_unmatched_review(unmatched_id)
    photo_id = opened["review"]["photos"][0]["id"]
    before = deepcopy(local_simulation.get_state())
    monkeypatch.setattr(
        local_simulation.photo_barcode_check,
        "check_photo_barcode",
        lambda *args, **kwargs: pytest.fail("stale rescan must not start a CPU scan"),
    )

    with pytest.raises(unmatched_review.ReviewVersionConflict):
        local_simulation.rescan_unmatched_review_photo(
            unmatched_id,
            photo_id,
            actor="reviewer-a",
            expected_version=opened["review"]["version"] - 1,
        )

    assert local_simulation.get_state() == before


def test_unmatched_rescan_with_sparse_meter_uses_empty_match_key_and_persists(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unmatched_id = seed_unmatched_review_record()
    record = local_simulation.get_state()["scan_unmatched"][-1]
    record["meter_no"] = ""
    record["barcode"] = ""
    opened = local_simulation.get_unmatched_review(unmatched_id)
    photo_id = opened["review"]["photos"][0]["id"]
    calls: list[dict] = []

    def check_photo_barcode(photo: dict, group: dict, *, use_ocr: bool = False) -> dict:
        calls.append({"group": group, "use_ocr": use_ocr})
        return {"barcode_check_status": "matched", "barcode_check_method": "barcode_ocr"}

    monkeypatch.setattr(local_simulation.photo_barcode_check, "check_photo_barcode", check_photo_barcode)

    result = local_simulation.rescan_unmatched_review_photo(
        unmatched_id,
        photo_id,
        actor="reviewer-a",
        expected_version=opened["review"]["version"],
    )
    events = [
        event
        for event in local_simulation.get_state()["audit_events"]
        if event["action"] == "unmatched_review_barcode_rescan"
    ]

    assert len(calls) == 1
    assert calls[0]["use_ocr"] is True
    assert calls[0]["group"]["meter_no"] == ""
    assert calls[0]["group"]["meter_match_key"] == ""
    assert result["review"]["meter_no"] == ""
    assert result["photo"]["barcode_check_method"] == "barcode_ocr"
    assert result["review"]["version"] == opened["review"]["version"] + 1
    assert local_simulation.get_unmatched_review(unmatched_id)["review"] == result["review"]
    assert len(events) == 1
    assert "00000000" not in str(result)


def test_unmatched_confirmation_persists_reloads_and_keeps_formal_statistics_unchanged(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCAL_SIMULATION_STATE_PATH", str(tmp_path / "state.json"))
    unmatched_id = seed_unmatched_review_record()
    opened = local_simulation.get_unmatched_review(unmatched_id)
    before = deepcopy(local_simulation.get_state())

    confirmed = local_simulation.confirm_unmatched_review(
        unmatched_id,
        actor="reviewer-a",
        expected_version=opened["review"]["version"],
    )
    events = [
        event
        for event in local_simulation.get_state()["audit_events"]
        if event["action"] == "unmatched_review_confirmed"
    ]
    local_simulation.get_state()["scan_unmatched"] = []
    assert local_simulation.load_all_team_states() is True
    reloaded = local_simulation.get_unmatched_review(unmatched_id)

    assert confirmed["review"]["manual_confirmed"] is True
    assert confirmed["review"]["reviewer"] == "reviewer-a"
    assert confirmed["review"]["reviewed_at"]
    assert confirmed["review"]["version"] == opened["review"]["version"] + 1
    assert {
        key: confirmed["review"][key]
        for key in confirmed["review"]
        if key not in {"manual_confirmed", "reviewer", "reviewed_at", "version"}
    } == {
        key: opened["review"][key]
        for key in opened["review"]
        if key not in {"manual_confirmed", "reviewer", "reviewed_at", "version"}
    }
    persisted_review = deepcopy(confirmed["review"])
    confirmed["record"]["temporary_review"]["manual_confirmed"] = False
    confirmed["review"]["manual_confirmed"] = False
    assert reloaded["review"] == persisted_review
    assert len(events) == 1
    assert events[0]["payload"]["confirmed"] is True
    assert local_simulation.get_state()["groups"] == before["groups"]
    assert local_simulation.get_state()["tasks"] == before["tasks"]
    assert local_simulation.get_state()["summary"] == before["summary"]


def test_json_state_repository_delegates_unmatched_rescan_and_confirmation(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = JsonStateRepository()
    unmatched_id = seed_unmatched_review_record()
    opened = repository.get_unmatched_review(unmatched_id)
    photo_id = opened["review"]["photos"][0]["id"]
    monkeypatch.setattr(
        local_simulation.photo_barcode_check,
        "check_photo_barcode",
        lambda photo, group, *, use_ocr=False: {"barcode_check_status": "matched"},
    )

    rescanned = repository.rescan_unmatched_review_photo(
        unmatched_id,
        photo_id,
        actor="reviewer-a",
        expected_version=opened["review"]["version"],
    )
    confirmed = repository.confirm_unmatched_review(
        unmatched_id,
        actor="reviewer-a",
        expected_version=rescanned["review"]["version"],
    )

    assert confirmed["review"]["manual_confirmed"] is True
    assert local_simulation.get_unmatched_review(unmatched_id)["review"] == confirmed["review"]


def test_dual_unmatched_review_writes_fail_before_either_backend_mutates(
    synthetic_state: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synthetic_state["total_catalog"] = []
    add_unmatched_match_catalog_row(terminal="T-DUAL-FINAL")
    unmatched_id = seed_unmatched_review_record(
        photo_prefix="https://photos.example/dual",
        manual_confirmed=True,
    )
    mirror_calls = []

    class MutatingPostgresMirror:
        def __getattr__(self, operation: str):
            def mutate(*args, **kwargs):
                mirror_calls.append((operation, args, kwargs))
                return {"mutated": True}

            return mutate

    monkeypatch.setattr(DualWriteStateRepository, "postgres_repository_factory", MutatingPostgresMirror)
    repo = DualWriteStateRepository()
    opened = repo.get_unmatched_review(unmatched_id)
    photo_id = opened["review"]["photos"][0]["id"]
    candidate = repo.list_unmatched_match_candidates(unmatched_id)["items"][0]
    version = opened["review"]["version"]
    before = deepcopy(synthetic_state)
    operations = [
        lambda: repo.save_unmatched_review(
            unmatched_id,
            actor="reviewer-a",
            expected_version=version,
            metadata={"collector": "C-DUAL"},
            photo_updates=[],
            state="pending",
        ),
        lambda: repo.rescan_unmatched_review_photo(
            unmatched_id,
            photo_id,
            actor="reviewer-a",
            expected_version=version,
            category="collector_barcode",
        ),
        lambda: repo.confirm_unmatched_review(
            unmatched_id,
            actor="reviewer-a",
            expected_version=version,
        ),
        lambda: repo.finalize_unmatched_match(
            unmatched_id,
            actor="admin-a",
            candidate_key=candidate["candidate_key"],
            expected_version=version,
        ),
    ]

    for operation in operations:
        with pytest.raises(StateBackendNotReady, match="before either backend mutated"):
            operation()

    assert synthetic_state == before
    assert mirror_calls == []


def test_dual_fail_fast_reuses_but_does_not_close_active_authoritative_transaction(
    synthetic_state: dict,
) -> None:
    synthetic_state["total_catalog"] = []
    add_unmatched_match_catalog_row(terminal="T-DUAL-FAIL")
    unmatched_id = seed_unmatched_review_record(
        photo_prefix="https://photos.example/dual-fail",
        manual_confirmed=True,
    )

    repo = DualWriteStateRepository()
    opened = repo.get_unmatched_review(unmatched_id)
    candidate = repo.list_unmatched_match_candidates(unmatched_id)["items"][0]
    transaction = local_simulation.begin_authoritative_json_write()
    token = local_simulation.activate_authoritative_json_write(transaction)
    try:
        with pytest.raises(StateBackendNotReady, match="before either backend mutated"):
            repo.finalize_unmatched_match(
                unmatched_id,
                actor="admin-a",
                candidate_key=candidate["candidate_key"],
                expected_version=opened["review"]["version"],
            )

        assert transaction.closed is False
        assert local_simulation.active_authoritative_json_write() is transaction
    finally:
        local_simulation.abort_authoritative_json_write(transaction, token)


def test_json_audit_events_recursively_redact_photo_storage_secrets(synthetic_state: dict) -> None:
    event = local_simulation.append_audit_event(
        "nested-photo-audit",
        "reviewer-a",
        {
            "candidate_key": "catalog:row-1",
            "nested": {
                "photos": [
                    {
                        "source_url": "https://photos.example/raw.jpg?token=secret",
                        "signed_url": "https://oss.example/signed.jpg?signature=secret",
                        "storage": {
                            "storage_bucket": "private-bucket",
                            "storage_key": "private/key.jpg",
                            "storageBucket": "private-camel-bucket",
                            "storageKey": "private/camel-key.jpg",
                            "objectKey": "private/camel-object.jpg",
                            "ossKey": "private/camel-oss.jpg",
                        },
                        "signedUrl": "https://oss.example/camel-signed.jpg?signature=secret",
                        "rawUrl": "https://oss.example/camel-raw.jpg?signature=secret",
                        "presignedUrl": "https://oss.example/presigned.jpg?signature=secret",
                        "rawSignedUrl": "https://oss.example/raw-signed.jpg?signature=secret",
                        "photo-source-url": "https://oss.example/photo-source.jpg?signature=secret",
                        "sourceImageUrl": "https://oss.example/source-image.jpg?signature=secret",
                        "bucketName": "private-provider-bucket",
                        "storageObjectKey": "private/storage-object.jpg",
                        "ossObjectKey": "private/oss-object.jpg",
                        "presignedUri": "oss://private/presigned",
                        "rawSignedURI": "oss://private/raw-signed",
                        "signed-link": "https://oss.example/signed-link",
                        "s3Key": "private/s3-object.jpg",
                        "cos_object_name": "private/cos-object.jpg",
                        "ossPath": "private/oss-path.jpg",
                        "objectPath": "private/object-path.jpg",
                    }
                ]
            },
        },
    )

    photo = event["payload"]["nested"]["photos"][0]
    assert event["payload"]["candidate_key"] == "[REDACTED]"
    assert photo["source_url"] == "[REDACTED]"
    assert photo["signed_url"] == "[REDACTED]"
    assert photo["signedUrl"] == "[REDACTED]"
    assert photo["rawUrl"] == "[REDACTED]"
    for key in (
        "presignedUrl",
        "rawSignedUrl",
        "photo-source-url",
        "sourceImageUrl",
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
    assert photo["storage"] == {
        "storage_bucket": "[REDACTED]",
        "storage_key": "[REDACTED]",
        "storageBucket": "[REDACTED]",
        "storageKey": "[REDACTED]",
        "objectKey": "[REDACTED]",
        "ossKey": "[REDACTED]",
    }
    assert local_simulation.list_audit_events()["items"][0] == event


def test_unmatched_dedupe_removes_duplicate_meter_records(synthetic_state: dict) -> None:
    synthetic_state["scan_unmatched"] = []
    synthetic_state["scan_unmatched"].extend(
        [
            {
                "unmatched_id": "dup-plain",
                "barcode": "3130001201100201234503",
                "meter_no": "110020123450",
                "meter_match_key": "002012345",
                "terminal": "T-404",
                "address": "A road 101",
                "photo_urls": ["https://download.example/a.jpg"],
            },
            {
                "unmatched_id": "dup-assigned",
                "barcode": "3130001201100201234503",
                "meter_no": "110020123450",
                "meter_match_key": "002012345",
                "terminal": "T-404",
                "address": "A road 101",
                "assigned_to": "constructor-a",
                "photo_urls": ["https://download.example/a.jpg", "https://download.example/b.jpg"],
            },
        ]
    )

    result = dedupe_unmatched_records(actor="admin")
    records = list_unmatched_records(query="110020123450")
    audits = list_audit_events()

    assert result["removed"] == 1
    assert result["duplicate_ids"] == ["dup-plain"]
    assert records["total"] == 1
    assert records["items"][0]["unmatched_id"] == "dup-assigned"
    assert audits["items"][0]["action"] == "dedupe_unmatched"


def test_blank_group_creation_enters_unmatched_queue(synthetic_state: dict) -> None:
    record = create_blank_unmatched_record(actor="alice")
    records = list_unmatched_records(query=record["unmatched_id"])
    audits = list_audit_events()

    assert record["record_type"] == "blank_group"
    assert records["total"] == 1
    assert records["items"][0]["unmatched_id"] == record["unmatched_id"]
    assert audits["items"][0]["action"] == "create_blank_unmatched"


def test_group_targets_can_be_fuzzy_searched_for_manual_association(synthetic_state: dict) -> None:
    by_address = search_group_targets(query="T-001 A road")
    by_photo_field = search_group_targets(query="collector asset-1")
    by_terminal = search_group_targets(terminal="T-002")

    assert by_address["total"] == 1
    assert by_address["items"][0]["meter_no"] == "ZZ1001"
    assert by_photo_field["total"] == 1
    assert by_photo_field["items"][0]["terminal"] == "T-001"
    assert by_terminal["total"] == 1
    assert by_terminal["items"][0]["meter_no"] == "ZZ1002"


def test_unmatched_record_can_create_group_for_terminal(synthetic_state: dict) -> None:
    apply_synced_scan_records(
        [
            {
                "file_id": "manual-create-1",
                "source_file": "manual-source",
                "barcode": "MANUAL-001",
                "meter_match_key": "manual-key",
                "terminal": "",
                "collector": "collector-manual",
                "module_asset_no": "module-manual",
                "photo_urls": "https://example.test/manual-a.jpg,https://example.test/manual-b.jpg",
            }
        ]
    )
    record = list_unmatched_records(query="MANUAL-001")["items"][0]

    result = create_group_from_unmatched_record(
        record["unmatched_id"],
        actor="alice",
        terminal="T-NEW",
        updates={"address": "manual address", "meter_no": "ZZ-MANUAL"},
    )
    created = result["group"]
    tasks = list_tasks()
    audits = list_audit_events()

    assert created["terminal"] == "T-NEW"
    assert created["meter_no"] == "ZZ-MANUAL"
    assert created["address"] == "manual address"
    assert created["photo_count"] == 2
    assert any(task["terminal"] == "T-NEW" and task["can_claim"] for task in tasks)
    assert list_unmatched_records(query="MANUAL-001")["total"] == 0
    assert audits["items"][0]["action"] == "create_group_from_unmatched"


def test_unmatched_record_attaches_to_existing_terminal_group(synthetic_state: dict) -> None:
    target = synthetic_state["groups"][0]
    original_group_count = len(synthetic_state["groups"])
    synthetic_state["scan_unmatched"].append(
        {
            "unmatched_id": "manual-attach-1",
            "barcode": target["meter_no"],
            "meter_no": target["meter_no"],
            "meter_match_key": target["meter_match_key"],
            "terminal": "",
            "collector": "collector-attach",
            "module_asset_no": "module-attach",
            "image_urls": ["https://example.test/attach-a.jpg"],
        }
    )

    result = create_group_from_unmatched_record(
        "manual-attach-1",
        actor="alice",
        terminal=target["terminal"],
        updates={"address": "corrected address"},
    )
    audits = list_audit_events()

    assert result["attached"] is True
    assert result["group"]["id"] == target["id"]
    assert result["added_photos"] == 1
    assert len(synthetic_state["groups"]) == original_group_count
    assert result["group"]["address"] == "corrected address"
    assert list_unmatched_records(query="manual-attach-1")["total"] == 0
    assert audits["items"][0]["action"] == "attach_unmatched_to_existing_group"


def test_replacement_rematch_adds_delivery_export_remark(synthetic_state: dict) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    target = synthetic_state["groups"][0]
    claim_task(target["task_id"], "alice")
    archive_all_group_photos(target)
    review_group(target["id"], status="approved", reviewer="alice", note="ready")
    apply_synced_scan_records(
        [
            {
                "file_id": "replacement-export-1",
                "source_file": "replacement-source",
                "barcode": "NEW-METER-001",
                "meter_no": "NEW-METER-001",
                "meter_match_key": "NEW-METER-001",
                "terminal": target["terminal"],
                "collector": "collector-replacement",
                "module_asset_no": "module-replacement",
                "photo_urls": "https://example.test/replacement-a.jpg",
            }
        ]
    )
    record = list_unmatched_records(query="NEW-METER-001")["items"][0]

    result = rematch_unmatched_record(
        record["unmatched_id"],
        actor="alice",
        meter_no="NEW-METER-001",
        old_meter_no=target["meter_no"],
        terminal=target["terminal"],
    )

    workbook = openpyxl.load_workbook(
        BytesIO(build_final_delivery_export(terminal=target["terminal"], review_scope="all")),
        read_only=True,
    )
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    remark_index = rows[0].index("备注")
    target_rows = [row for row in rows[1:] if row[1] == target["meter_no"]]

    assert result["matched"] is True
    assert target_rows
    assert any(row[remark_index] == f"换表：旧表号 {target['meter_no']}" for row in target_rows)


def test_list_replacement_records_includes_matched_manual_replacements(synthetic_state: dict) -> None:
    target = synthetic_state["groups"][0]
    original_meter_no = target["meter_no"]
    apply_synced_scan_records(
        [
            {
                "file_id": "replacement-list-1",
                "source_file": "replacement-list-source",
                "barcode": "NEW-METER-LIST-001",
                "meter_no": "NEW-METER-LIST-001",
                "meter_match_key": "NEW-METER-LIST-001",
                "terminal": target["terminal"],
                "collector": "collector-list",
                "module_asset_no": "module-list",
                "photo_urls": "https://example.test/replacement-list-a.jpg",
            }
        ]
    )
    record = list_unmatched_records(query="NEW-METER-LIST-001")["items"][0]

    rematch_unmatched_record(
        record["unmatched_id"],
        actor="alice",
        meter_no="NEW-METER-LIST-001",
        old_meter_no=original_meter_no,
        terminal=target["terminal"],
    )

    result = list_replacement_records(query="NEW-METER-LIST-001")

    assert result["total"] == 1
    item = result["items"][0]
    assert item["group_id"] == target["id"]
    assert item["terminal"] == target["terminal"]
    assert item["address"] == target["address"]
    assert item["old_meter_no"] == original_meter_no
    assert item["new_meter_no"] == "NEW-METER-LIST-001"
    assert item["replacement_by"] == "alice"


def test_admin_can_create_empty_group_and_import_missing_photos(synthetic_state: dict) -> None:
    result = create_empty_group_for_terminal(
        "T-MANUAL",
        actor="admin",
        meter_no="ZZ-MANUAL",
        address="manual address",
    )
    created = result["group"]

    imported = add_photo_urls_to_group(
        created["id"],
        actor="admin",
        photo_urls=["https://example.test/manual-a.jpg", "https://example.test/manual-b.jpg"],
        collector="collector-manual",
        module_asset_no="module-manual",
        creator="installer-manual",
    )
    tasks = list_tasks()
    audits = list_audit_events()

    assert created["terminal"] == "T-MANUAL"
    assert created["photo_count"] == 2
    assert created["status"] == "incomplete"
    assert imported["added"] == 2
    assert imported["group"]["photos"][0]["creator"] == "installer-manual"
    assert any(task["terminal"] == "T-MANUAL" and task["can_claim"] for task in tasks)
    assert audits["items"][0]["action"] == "add_group_photos"


@pytest.mark.parametrize(
    ("terminal", "meter_no"),
    [
        ("", "120000000001"),
        ("00000000", "120000000001"),
        ("未关联终端", "120000000001"),
        ("manual-terminal", "120000000001"),
        ("unmatched-terminal", "120000000001"),
        ("T-REAL", ""),
        ("T-REAL", "00000000"),
        ("T-REAL", "未关联终端"),
        ("T-REAL", "manual-meter"),
        ("T-REAL", "unmatched-meter"),
    ],
)
def test_json_repository_rejects_placeholder_formal_identity_without_write(
    synthetic_state: dict,
    terminal: str,
    meter_no: str,
) -> None:
    before = deepcopy(
        {
            "tasks": synthetic_state["tasks"],
            "groups": synthetic_state["groups"],
            "audit_events": synthetic_state.get("audit_events", []),
        }
    )

    with pytest.raises(ValueError, match="real (terminal|meter number)"):
        JsonStateRepository().create_empty_group_for_terminal(
            terminal=terminal,
            actor="admin",
            meter_no=meter_no,
        )

    assert synthetic_state["tasks"] == before["tasks"]
    assert synthetic_state["groups"] == before["groups"]
    assert synthetic_state.get("audit_events", []) == before["audit_events"]


def test_json_unmatched_group_creation_rejects_placeholder_meter_without_write(synthetic_state: dict) -> None:
    synthetic_state["scan_unmatched"].append(
        {
            "unmatched_id": "invalid-formal-meter",
            "barcode": "manual-meter",
            "meter_no": "manual-meter",
            "meter_match_key": "manual-meter",
            "photo_urls": ["https://example.test/unsafe.jpg"],
        }
    )
    before = deepcopy(
        {
            "tasks": synthetic_state["tasks"],
            "groups": synthetic_state["groups"],
            "scan_unmatched": synthetic_state["scan_unmatched"],
            "audit_events": synthetic_state.get("audit_events", []),
        }
    )

    with pytest.raises(ValueError, match="real meter number"):
        create_group_from_unmatched_record(
            "invalid-formal-meter",
            actor="admin",
            terminal="T-REAL",
            expected_version=1,
        )

    assert synthetic_state["tasks"] == before["tasks"]
    assert synthetic_state["groups"] == before["groups"]
    assert synthetic_state["scan_unmatched"] == before["scan_unmatched"]
    assert synthetic_state.get("audit_events", []) == before["audit_events"]


def test_group_metadata_form_updates_group_and_photo_fields(synthetic_state: dict) -> None:
    group = synthetic_state["groups"][0]

    result = update_group_metadata(
        group["id"],
        actor="alice",
        updates={
            "meter_no": "ZZ-FORM",
            "address": "form address",
            "collector": "collector-form",
            "module_asset_no": "module-form",
            "creator": "installer-form",
        },
    )
    audits = list_audit_events()

    assert result["group"]["meter_no"] == "ZZ-FORM"
    assert result["group"]["address"] == "form address"
    assert all(photo["collector"] == "collector-form" for photo in result["group"]["photos"])
    assert all(photo["asset_no"] == "module-form" for photo in result["group"]["photos"])
    assert all(photo["creator"] == "installer-form" for photo in result["group"]["photos"])
    assert audits["items"][0]["action"] == "update_group_metadata"


@pytest.mark.parametrize(
    ("operation", "value"),
    [
        (operation, value)
        for operation in ("terminal", "meter_no", "meter_match_key")
        for value in ("00000000", "未关联终端", "manual-placeholder", "unmatched-placeholder")
    ],
)
def test_json_formal_identity_updates_reject_placeholders_without_state_or_audit_changes(
    synthetic_state: dict,
    operation: str,
    value: str,
) -> None:
    group_id = synthetic_state["groups"][0]["id"]
    before = deepcopy(synthetic_state)

    with pytest.raises(ValueError, match="real (terminal|meter number|meter match key)"):
        if operation == "terminal":
            local_simulation.update_group_terminal(group_id, terminal=value, actor="admin")
        else:
            update_group_metadata(group_id, actor="admin", updates={operation: value})

    assert synthetic_state == before


def test_json_group_creation_rejects_placeholder_match_key_without_state_or_audit_changes(
    synthetic_state: dict,
) -> None:
    before = deepcopy(synthetic_state)

    with pytest.raises(ValueError, match="real meter match key"):
        create_empty_group_for_terminal(
            terminal="T-REAL",
            actor="admin",
            meter_no="120000000001",
            meter_match_key="manual-match-key",
        )

    assert synthetic_state == before


def test_incomplete_group_is_marked_exception_after_last_photo_archived(synthetic_state: dict) -> None:
    group = synthetic_state["groups"][1]
    photo = group["photos"][0]

    claim_task(2, reviewer="alice")
    classify_photo(group["id"], photo["id"], "collector_barcode", reviewer="alice")

    assert group["status"] == "exception"
    assert group["has_archive_blocker"] is True
    assert "照片不足" in group["exception_note"]


def test_archive_blocks_duplicate_module_and_missing_required_scan_fields(synthetic_state: dict) -> None:
    clear_scan_data()
    apply_synced_scan_records(
        [
            {
                "meter_match_key": "1001",
                "barcode": f"dup-left-{index}",
                "collector": "collector-a",
                "module_asset_no": "DUP-MODULE",
                "image_urls": [f"https://example.test/left-{index}.jpg"],
            }
            for index in range(4)
        ]
        + [
            {
                "meter_match_key": "1002",
                "barcode": f"dup-right-{index}",
                "collector": "",
                "module_asset_no": "DUP-MODULE",
                "image_urls": [f"https://example.test/right-{index}.jpg"],
            }
            for index in range(4)
        ]
    )
    duplicate_group = synthetic_state["groups"][0]
    missing_group = synthetic_state["groups"][1]

    claim_task(1, reviewer="alice")
    claim_task(2, reviewer="bob")
    archive_all_group_photos(duplicate_group, reviewer="alice")
    archive_all_group_photos(missing_group, reviewer="bob")

    assert duplicate_group["status"] == "exception"
    assert "模块号重复" in duplicate_group["exception_note"]
    assert missing_group["status"] == "exception"
    assert "缺少采集器信息" in missing_group["exception_note"]

    clear_scan_data()
    apply_synced_scan_records(
        [
            {
                "meter_match_key": "1001",
                "barcode": f"missing-module-{index}",
                "collector": "collector-a",
                "module_asset_no": "",
                "image_urls": [f"https://example.test/missing-module-{index}.jpg"],
            }
            for index in range(4)
        ]
    )
    module_group = synthetic_state["groups"][0]
    claim_task(1, reviewer="alice")
    archive_all_group_photos(module_group, reviewer="alice")

    assert module_group["status"] == "exception"
    assert "缺少模块资产编号" in module_group["exception_note"]


def test_archive_validation_accepts_group_level_module_asset_number(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local_simulation, "collect_module_group_map", lambda: {})
    group = {
        "id": "group-with-module",
        "module_asset_no": "MOD-001",
        "photos": [
            {"id": f"photo-{index}", "collector": "COLLECTOR-001"}
            for index in range(4)
        ],
    }

    reasons = local_simulation.validate_group_archive(group)

    assert "缺少模块资产编号" not in reasons


def test_archive_validation_detects_duplicate_module_number_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local_simulation, "collect_module_group_map", lambda: {"MOD-001": {"other-group"}})
    group = {
        "id": "group-with-duplicate-module",
        "construction_module_asset_no": "MOD-001",
        "photos": [
            {"id": f"photo-{index}", "collector": "COLLECTOR-001"}
            for index in range(4)
        ],
    }

    reasons = local_simulation.validate_group_archive(group)

    assert any(reason.startswith("模块号重复") for reason in reasons)


@pytest.mark.skipif(find_spec("openpyxl") is None, reason="openpyxl is not available")
def test_import_scan_template_xlsx_reads_business_fields_and_hyperlink(synthetic_state: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    from io import BytesIO

    from openpyxl import Workbook

    clear_scan_data()
    monkeypatch.setattr(
        local_simulation,
        "resolve_detail_image_urls",
        lambda url: [
            "https://example.test/barcodeImgDetail?downloadImg=cloud://photo-a.jpg",
            "https://example.test/barcodeImgDetail?downloadImg=cloud://photo-b.jpg",
        ],
    )
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "合并"
    sheet.append(["编号", "扫码内容", "数量", "采集器", "地址", "模块资产编号", "资产类型", "创建者", "创建时间", "图片 (电脑查看)", "来自文件"])
    sheet.append(
        [
            1,
            "ABCDEFGHIJK1001X",
            1,
            "COLLECTOR-01",
            "scan address",
            "MODULE-01",
            "单相双模",
            "安装员A",
            "2026-06-09 23:08:30",
            "查看图片",
            "installer-folder",
        ]
    )
    sheet["J2"].hyperlink = "https://example.test/barcodeImgDetail?itemIdentifer=abc"
    stream = BytesIO()
    workbook.save(stream)

    result = import_scan_template_xlsx(stream.getvalue())
    group = synthetic_state["groups"][0]
    photo = group["photos"][0]

    assert result["template_rows"] == 1
    assert result["applied_records"] == 2
    assert photo["barcode"] == "ABCDEFGHIJK1001X"
    assert photo["collector"] == "COLLECTOR-01"
    assert photo["asset_no"] == "MODULE-01"
    assert photo["creator"] == "安装员A"
    assert photo["image_url"] == "https://example.test/barcodeImgDetail?downloadImg=cloud://photo-a.jpg"
    assert group["photos"][1]["image_url"] == "https://example.test/barcodeImgDetail?downloadImg=cloud://photo-b.jpg"


def test_synced_photo_urls_can_be_loaded_per_group(synthetic_state: dict) -> None:
    clear_scan_data()
    result = apply_synced_scan_records(
        [
            {
                "file_id": "remote-file-1",
                "source_file": "remote-source",
                "barcode": "ABCDEFGHIJK000001001X",
                "meter_match_key": "1001",
                "image_file_ids": ["cloud://photo-1.jpg", "cloud://photo-2.jpg"],
                "image_urls": [],
            }
        ]
    )
    group = synthetic_state["groups"][0]

    assert result["applied_records"] == 2
    assert group["photos"][0]["image_file_id"] == "cloud://photo-1.jpg"
    assert group["photos"][0]["image_url"] == ""

    loaded = apply_group_photo_urls(
        group["id"],
        {
            "cloud://photo-1.jpg": "https://download.example/photo-1.jpg",
            "cloud://photo-2.jpg": "https://download.example/photo-2.jpg",
        },
    )

    assert loaded["loaded_photo_urls"] == 2
    assert group["photos"][0]["image_url"] == "https://download.example/photo-1.jpg"
    assert group["photos"][1]["image_url"] == "https://download.example/photo-2.jpg"


def test_local_test_routes_cover_review_flow(synthetic_state: dict) -> None:
    client = TestClient(create_app())

    claim_response = client.post("/local-test/tasks/1/claim", json={"reviewer": "alice"})
    groups_response = client.get("/local-test/tasks/1/groups?limit=1")
    group_id = groups_response.json()["data"]["items"][0]["id"]
    review_response = client.patch(
        f"/local-test/groups/{group_id}/review",
        json={"status": "approved", "reviewer": "alice", "note": "ok"},
    )
    progress_response = client.get("/local-test/tasks/1/progress")

    assert claim_response.status_code == 200
    assert groups_response.status_code == 200
    assert groups_response.json()["data"]["total"] == 1
    assert review_response.status_code == 200
    assert review_response.json()["data"]["status"] == "approved"
    assert progress_response.json()["data"]["reviewed_groups"] == 1
    assert progress_response.json()["data"]["completeness_rate"] == 1.0


@requires_sample_workbooks
def test_sample_paths_are_absolute_windows_files() -> None:
    for path in SAMPLE_FILES:
        assert isinstance(path, Path)
        assert path.suffix == ".xlsx"
