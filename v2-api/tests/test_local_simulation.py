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
    apply_group_photo_urls,
    apply_synced_scan_records,
    bootstrap_local_simulation,
    classify_photo,
    claim_task,
    clear_scan_data,
    delete_unmatched_record,
    get_task_progress,
    get_group,
    import_scan_template_xlsx,
    list_audit_events,
    list_task_groups,
    list_groups,
    list_unmatched_records,
    list_tasks,
    normalize_cell,
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
    assert tasks[0]["renovation_count"] == 1
    assert tasks[0]["uploaded_count"] == 1
    assert tasks[0]["upload_rate"] == 1.0
    assert tasks[0]["review_rate"] == 0.0
    assert tasks[1]["partial_groups"] == 1
    assert tasks[1]["completeness_rate"] == 1.0
    assert tasks[1]["unreviewed_count"] == 1
    assert tasks[2]["scan_rows"] == 0
    assert tasks[2]["can_claim"] is False
    assert tasks[2]["completeness_rate"] == 0.0

    with pytest.raises(ValueError):
        claim_task(tasks[2]["id"], reviewer="alice")


def test_normalize_cell_repairs_latin1_mojibake() -> None:
    mojibake = "\u00e5\u00ae\u009d\u00e5\u00b1\u00b1\u00e5\u008c\u00ba\u00e9\u0094\u00a6\u00e7\u00a7\u008b\u00e8\u00b7\u00af1152\u00e5\u008f\u00b7"

    assert normalize_cell(mojibake) == "\u5b9d\u5c71\u533a\u9526\u79cb\u8def1152\u53f7"
    assert normalize_cell("\u4e0a\u6d77\u5e02\u5b9d\u5c71\u533a") == "\u4e0a\u6d77\u5e02\u5b9d\u5c71\u533a"


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
    assert duplicate["skipped_duplicates"] == 2
    assert group["photo_count"] == 2


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


def test_incomplete_group_is_marked_exception_after_last_photo_archived(synthetic_state: dict) -> None:
    group = synthetic_state["groups"][1]
    photo = group["photos"][0]

    claim_task(2, reviewer="alice")
    classify_photo(group["id"], photo["id"], "collector_barcode", reviewer="alice")

    assert group["status"] == "exception"
    assert group["has_archive_blocker"] is True
    assert "照片不足" in group["exception_note"]


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
