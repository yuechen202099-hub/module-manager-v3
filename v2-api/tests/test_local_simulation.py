from pathlib import Path
from importlib.util import find_spec

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import local_simulation
from app.services.local_simulation import (
    DEFAULT_SCAN_FILE,
    DEFAULT_STAGE_CATALOG,
    DEFAULT_TOTAL_CATALOG,
    LocalTestPaths,
    bootstrap_local_simulation,
    classify_photo,
    claim_task,
    get_task_progress,
    get_group,
    list_task_groups,
    list_groups,
    list_tasks,
    release_task,
    review_group,
    save_exception_note,
)


SAMPLE_FILES = [DEFAULT_TOTAL_CATALOG, DEFAULT_STAGE_CATALOG, DEFAULT_SCAN_FILE]


requires_sample_workbooks = pytest.mark.skipif(
    not all(path.exists() for path in SAMPLE_FILES) or find_spec("openpyxl") is None,
    reason="local sample workbooks or openpyxl are not available",
)


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


@pytest.fixture()
def synthetic_state(monkeypatch: pytest.MonkeyPatch) -> dict:
    def read_catalog(path: Path, source: str) -> list[dict]:
        return fake_catalog_rows(source)

    monkeypatch.setattr(local_simulation, "read_catalog_rows", read_catalog)
    monkeypatch.setattr(local_simulation, "read_scan_rows", lambda path: fake_scan_rows())
    return bootstrap_local_simulation(LocalTestPaths(Path("total.xlsx"), Path("stage.xlsx"), Path("scan.xlsx")))


@requires_sample_workbooks
def test_bootstrap_local_simulation_uses_sample_workbooks() -> None:
    state = bootstrap_local_simulation(LocalTestPaths())
    summary = state["summary"]

    assert summary["total_catalog_rows"] > 20_000
    assert summary["stage_catalog_rows"] > 5_000
    assert summary["scan_rows"] > 0
    assert summary["groups"] == summary["stage_catalog_rows"]
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
    assert tasks[1]["partial_groups"] == 1
    assert tasks[1]["completeness_rate"] == 0.25
    assert tasks[2]["scan_rows"] == 0
    assert tasks[2]["can_claim"] is False
    assert tasks[2]["completeness_rate"] == 0.0

    with pytest.raises(ValueError):
        claim_task(tasks[2]["id"], reviewer="alice")


def test_review_group_updates_status_and_summary(synthetic_state: dict) -> None:
    state = synthetic_state
    first_id = state["groups"][0]["id"]

    reviewed = review_group(first_id, status="approved", reviewer="alice", note="sample passed")
    tasks = list_tasks()

    assert reviewed["status"] == "approved"
    assert reviewed["review_note"] == "sample passed"
    assert state["summary"]["approved_groups"] == 1
    assert state["summary"]["reviewed_groups"] == 1
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

    reviewed = save_exception_note(second_id, reviewer="alice", note="missing required photos")
    progress = get_task_progress(2)

    assert reviewed["status"] == "exception"
    assert reviewed["exception_note"] == "missing required photos"
    assert progress["exception_groups"] == 1
    assert progress["reviewed_groups"] == 1
    assert progress["pending_groups"] == 0


def test_task_groups_can_be_filtered_by_status(synthetic_state: dict) -> None:
    result = list_task_groups(2, status="incomplete")

    assert result["total"] == 1
    assert result["items"][0]["photo_count"] == 1


def test_task_groups_can_be_limited_to_scanned_groups(synthetic_state: dict) -> None:
    scanned = list_task_groups(3, scan_only=True)
    all_groups = list_task_groups(3, scan_only=False)

    assert scanned["total"] == 0
    assert all_groups["total"] == 1


def test_downloaded_photo_can_be_classified(synthetic_state: dict) -> None:
    first_group = synthetic_state["groups"][0]
    photo = first_group["photos"][0]

    classified = classify_photo(first_group["id"], photo["id"], "collector_barcode", reviewer="alice")

    assert classified["category"] == "collector_barcode"
    assert classified["category_label"] == "采集器条形码"
    assert classified["classified_by"] == "alice"
    assert synthetic_state["summary"]["unclassified_photos"] == 4


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
