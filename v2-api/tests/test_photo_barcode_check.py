from __future__ import annotations

import sys
from io import BytesIO
from types import SimpleNamespace

from PIL import Image

from app.services import photo_barcode_check
from app.services.photo_barcode_check import (
    build_group_barcode_check,
    check_photo_barcode,
    default_barcode_scanner,
    summarize_group_barcode_accuracy,
    summarize_photo_accuracy,
)


def scanner(values: list[str]):
    return lambda _photo: values


def test_meter_barcode_matches_meter_number_and_match_key() -> None:
    result = check_photo_barcode(
        photo={"category": "meter_barcode", "image_url": "https://example.test/meter.jpg"},
        group={"meter_no": "110000288056", "meter_match_key": "0000288056"},
        scanner=scanner(["110000288056"]),
    )

    assert result["barcode_check_status"] == "matched"
    assert result["barcode_check_expected_type"] == "meter"
    assert result["barcode_check_values"] == ["110000288056"]
    assert "110000288056" in result["barcode_check_expected_values"]
    assert result["barcode_check_matched_value"] == "110000288056"


def test_collector_barcode_mismatch_is_failed() -> None:
    result = check_photo_barcode(
        photo={"category": "collector_barcode", "image_url": "https://example.test/collector.jpg"},
        group={"collector": "COLLECTOR-001", "construction_collector": "COLLECTOR-002"},
        scanner=scanner(["COLLECTOR-999"]),
    )

    assert result["barcode_check_status"] == "mismatched"
    assert result["barcode_check_expected_type"] == "collector"
    assert result["barcode_check_values"] == ["COLLECTOR-999"]
    assert "COLLECTOR001" in result["barcode_check_expected_values"]
    assert "COLLECTOR002" in result["barcode_check_expected_values"]


def test_module_meter_without_scannable_value_is_unreadable() -> None:
    result = check_photo_barcode(
        photo={"category": "module_meter", "image_url": "https://example.test/module.jpg"},
        group={"module_asset_no": "MOD-001"},
        scanner=scanner([]),
    )

    assert result["barcode_check_status"] == "unreadable"
    assert result["barcode_check_expected_type"] == "module"
    assert result["barcode_check_error"] == "no_barcode_detected"


def test_non_barcode_category_does_not_affect_accuracy_denominator() -> None:
    result = check_photo_barcode(
        photo={"category": "before_box", "image_url": "https://example.test/box.jpg"},
        group={"meter_no": "110000288056"},
        scanner=scanner([]),
    )

    assert result["barcode_check_status"] == "not_required"
    assert result["barcode_check_expected_type"] == "none"


def test_non_barcode_category_does_not_call_scanner() -> None:
    calls = 0

    def count_calls(_photo):
        nonlocal calls
        calls += 1
        return ["SHOULD-NOT-SCAN"]

    result = check_photo_barcode(
        photo={"category": "before_box", "image_url": "https://example.test/box.jpg"},
        group={"meter_no": "110000288056"},
        scanner=count_calls,
    )

    assert result["barcode_check_status"] == "not_required"
    assert result["barcode_check_values"] == []
    assert calls == 0


def test_photo_accuracy_summary_counts_only_required_categories() -> None:
    summary = summarize_photo_accuracy(
        [
            {"barcode_check_status": "matched"},
            {"barcode_check_status": "mismatched"},
            {"barcode_check_status": "unreadable"},
            {"barcode_check_status": "not_required"},
            {},
        ]
    )

    assert summary == {
        "photo_accuracy_checked": 3,
        "photo_accuracy_passed": 1,
        "photo_accuracy_failed": 1,
        "photo_accuracy_unreadable": 1,
        "photo_accuracy_not_required": 1,
        "photo_accuracy_rate": 0.3333,
    }


def test_group_barcode_check_passes_when_required_values_are_spread_across_photos() -> None:
    group = {
        "meter_no": "110000288056",
        "module_asset_no": "MOD-001",
        "collector": "COLLECTOR-001",
        "photos": [
            {"barcode_check_normalized_values": ["COLLECTOR001"], "barcode_check_status": "matched"},
            {"barcode_check_normalized_values": ["110000288056"], "barcode_check_status": "matched"},
            {"barcode_check_normalized_values": ["MOD001"], "barcode_check_status": "matched"},
            {"barcode_check_status": "unreadable", "barcode_check_normalized_values": []},
        ],
    }

    result = build_group_barcode_check(group)

    assert result["group_barcode_check_status"] == "matched"
    assert result["group_barcode_missing_fields"] == []
    assert set(result["group_barcode_matched_fields"]) == {"meter", "module", "collector"}


def test_group_barcode_check_keeps_legacy_matched_photo_evidence() -> None:
    group = {
        "meter_no": "110000288056",
        "module_asset_no": "MOD-001",
        "collector": "COLLECTOR-001",
        "photos": [
            {
                "barcode_check_status": "matched",
                "barcode_check_expected_type": "meter",
                "barcode_check_matched_value": "110000288056",
                "barcode_check_normalized_values": [],
            },
            {
                "barcode_check_status": "matched",
                "barcode_check_expected_type": "module",
                "barcode_check_matched_value": "MOD001",
                "barcode_check_normalized_values": ["OLDMODULEVALUE"],
            },
            {
                "barcode_check_status": "matched",
                "barcode_check_expected_type": "collector",
                "barcode_check_matched_value": "COLLECTOR001",
            },
        ],
    }

    result = build_group_barcode_check(group)

    assert result["group_barcode_check_status"] == "matched"
    assert result["group_barcode_missing_fields"] == []
    assert result["group_barcode_unmatched_values"] == []
    assert result["group_barcode_detected_values"]["meter"] == ["110000288056"]
    assert result["group_barcode_detected_values"]["module"] == ["MOD001"]
    assert result["group_barcode_detected_values"]["collector"] == ["COLLECTOR001"]
    assert set(result["group_barcode_matched_fields"]) == {"meter", "module", "collector"}


def test_group_barcode_check_counts_long_meter_code_from_legacy_module_photo() -> None:
    group = {
        "meter_no": "110000281742",
        "meter_match_key": "0000281742",
        "module_asset_no": "3130054512250026172609",
        "collector": "3130009381930003253416",
        "photos": [
            {
                "barcode_check_status": "matched",
                "barcode_check_expected_type": "collector",
                "barcode_check_matched_value": "3130009381930003253416",
                "barcode_check_normalized_values": ["3130009381930003253416"],
            },
            {
                "barcode_check_status": "matched",
                "barcode_check_expected_type": "module",
                "barcode_check_matched_value": "3130054512250026172609",
                "barcode_check_normalized_values": ["3130001111800002817421", "3130054512250026172609"],
            },
        ],
    }

    result = build_group_barcode_check(group)

    assert result["group_barcode_check_status"] == "matched"
    assert result["group_barcode_missing_fields"] == []
    assert result["group_barcode_detected_values"]["meter"] == ["3130001111800002817421"]
    assert result["group_barcode_detected_values"]["module"] == ["3130054512250026172609"]
    assert result["group_barcode_detected_values"]["collector"] == ["3130009381930003253416"]


def test_group_barcode_check_accepts_legacy_meter_long_code_with_noise() -> None:
    group = {
        "meter_no": "110000281742",
        "meter_match_key": "0000281742",
        "module_asset_no": "3130054512250026172609",
        "collector": "3130009381930003253416",
        "photos": [
            {
                "barcode_check_status": "matched",
                "barcode_check_expected_type": "meter",
                "barcode_check_matched_value": "3130001111800002817421",
                "barcode_check_normalized_values": ["3130001111800002817421", "NOISE999"],
            },
            {
                "barcode_check_status": "matched",
                "barcode_check_expected_type": "module",
                "barcode_check_matched_value": "3130054512250026172609",
                "barcode_check_normalized_values": ["3130054512250026172609"],
            },
            {
                "barcode_check_status": "matched",
                "barcode_check_expected_type": "collector",
                "barcode_check_matched_value": "3130009381930003253416",
                "barcode_check_normalized_values": ["3130009381930003253416"],
            },
        ],
    }

    result = build_group_barcode_check(group)

    assert result["group_barcode_check_status"] == "matched"
    assert result["group_barcode_missing_fields"] == []
    assert result["group_barcode_unmatched_values"] == []
    assert result["group_barcode_detected_values"]["meter"] == ["3130001111800002817421"]


def test_group_barcode_check_keeps_legacy_mismatched_photo_as_review_item() -> None:
    group = {
        "meter_no": "110000288056",
        "module_asset_no": "MOD-001",
        "collector": "COLLECTOR-001",
        "photos": [
            {
                "barcode_check_status": "matched",
                "barcode_check_expected_type": "meter",
                "barcode_check_matched_value": "110000288056",
            },
            {
                "barcode_check_status": "matched",
                "barcode_check_expected_type": "module",
                "barcode_check_matched_value": "MOD001",
            },
            {
                "barcode_check_status": "mismatched",
                "barcode_check_expected_type": "collector",
                "barcode_check_normalized_values": ["COLLECTOR999"],
            },
        ],
    }

    result = build_group_barcode_check(group)

    assert result["group_barcode_check_status"] == "mismatched"
    assert result["group_barcode_missing_fields"] == ["collector"]
    assert result["group_barcode_unmatched_values"] == ["COLLECTOR999"]


def test_group_barcode_check_rejects_stale_legacy_matched_value() -> None:
    group = {
        "meter_no": "110000288056",
        "module_asset_no": "MOD-001",
        "collector": "COLLECTOR-001",
        "photos": [
            {
                "barcode_check_status": "matched",
                "barcode_check_expected_type": "meter",
                "barcode_check_matched_value": "110000288056",
            },
            {
                "barcode_check_status": "matched",
                "barcode_check_expected_type": "module",
                "barcode_check_matched_value": "MOD999",
            },
            {
                "barcode_check_status": "matched",
                "barcode_check_expected_type": "collector",
                "barcode_check_matched_value": "COLLECTOR001",
            },
        ],
    }

    result = build_group_barcode_check(group)

    assert result["group_barcode_check_status"] == "mismatched"
    assert result["group_barcode_missing_fields"] == ["module"]
    assert result["group_barcode_unmatched_values"] == ["MOD999"]
    assert result["group_barcode_detected_values"]["module"] == []


def test_group_barcode_check_marks_unreadable_when_one_required_value_is_missing() -> None:
    group = {
        "meter_no": "110000288056",
        "module_asset_no": "MOD-001",
        "collector": "COLLECTOR-001",
        "photos": [
            {"barcode_check_normalized_values": ["110000288056"], "barcode_check_status": "matched"},
            {"barcode_check_normalized_values": ["MOD001"], "barcode_check_status": "matched"},
            {"barcode_check_status": "unreadable", "barcode_check_normalized_values": []},
        ],
    }

    result = build_group_barcode_check(group)

    assert result["group_barcode_check_status"] == "unreadable"
    assert result["group_barcode_missing_fields"] == ["collector"]
    assert result["group_barcode_detected_values"]["meter"] == ["110000288056"]
    assert result["group_barcode_detected_values"]["module"] == ["MOD001"]


def test_group_barcode_check_marks_mismatched_when_detected_value_belongs_to_no_group_field() -> None:
    group = {
        "meter_no": "110000288056",
        "module_asset_no": "MOD-001",
        "collector": "COLLECTOR-001",
        "photos": [
            {"barcode_check_normalized_values": ["110000288056"], "barcode_check_status": "matched"},
            {"barcode_check_normalized_values": ["MOD001"], "barcode_check_status": "matched"},
            {"barcode_check_normalized_values": ["COLLECTOR999"], "barcode_check_status": "mismatched"},
        ],
    }

    result = build_group_barcode_check(group)

    assert result["group_barcode_check_status"] == "mismatched"
    assert result["group_barcode_unmatched_values"] == ["COLLECTOR999"]


def test_group_barcode_accuracy_summary_uses_group_denominator() -> None:
    summary = summarize_group_barcode_accuracy(
        [
            {
                "meter_no": "110000288056",
                "module_asset_no": "MOD-001",
                "collector": "COLLECTOR-001",
                "photos": [
                    {"barcode_check_normalized_values": ["110000288056"]},
                    {"barcode_check_normalized_values": ["MOD001"]},
                    {"barcode_check_normalized_values": ["COLLECTOR001"]},
                ],
            },
            {
                "meter_no": "110000288057",
                "module_asset_no": "MOD-002",
                "collector": "COLLECTOR-002",
                "photos": [{"barcode_check_normalized_values": ["110000288057"]}],
            },
            {"meter_no": "110000288058", "module_asset_no": "", "collector": "COLLECTOR-003", "photos": []},
        ]
    )

    assert summary == {
        "group_barcode_accuracy_checked": 2,
        "group_barcode_accuracy_passed": 1,
        "group_barcode_accuracy_failed": 0,
        "group_barcode_accuracy_unreadable": 1,
        "group_barcode_accuracy_not_required": 1,
        "group_barcode_accuracy_rate": 0.5,
    }


def test_group_barcode_unreadable_items_include_human_review_fields() -> None:
    items = photo_barcode_check.list_group_barcode_review_items(
        [
            {
                "id": "group-1",
                "meter_no": "110000288056",
                "module_asset_no": "MOD-001",
                "collector": "COLLECTOR-001",
                "terminal": "T-01",
                "address": "A区1号",
                "installer": "张三",
                "photos": [
                    {
                        "id": "photo-1",
                        "category": "meter_barcode",
                        "image_url": "/local-test/groups/group-1/photos/photo-1/content",
                        "barcode_check_normalized_values": ["110000288056"],
                        "barcode_check_status": "matched",
                    }
                ],
            },
            {
                "id": "group-2",
                "meter_no": "110000288057",
                "module_asset_no": "MOD-002",
                "collector": "COLLECTOR-002",
                "photos": [
                    {"id": "photo-2", "barcode_check_normalized_values": ["110000288057"]},
                    {"id": "photo-3", "barcode_check_normalized_values": ["MOD002"]},
                    {"id": "photo-4", "barcode_check_normalized_values": ["COLLECTOR002"]},
                ],
            },
        ],
        statuses={"unreadable"},
    )

    assert len(items) == 1
    assert items[0]["group_id"] == "group-1"
    assert items[0]["missing_fields"] == ["module", "collector"]
    assert items[0]["expected"]["module"] == ["MOD001"]
    assert items[0]["detected_values"]["meter"] == ["110000288056"]
    assert items[0]["photos"][0]["thumbnail_url"] == "/local-test/groups/group-1/photos/photo-1/content?kind=thumbnail"
    assert items[0]["installer"] == "张三"


def tiny_jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), "white").save(buffer, format="JPEG")
    return buffer.getvalue()


def fake_zxing(expected_size: tuple[int, int] = (8, 8)):
    def read_barcodes(image):
        assert not isinstance(image, (str, bytes))
        assert image.size == expected_size
        return [SimpleNamespace(text="ABC-123")]

    return SimpleNamespace(read_barcodes=read_barcodes)


def test_default_barcode_scanner_decodes_local_image_before_zxing(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "barcode.jpg"
    image_path.write_bytes(tiny_jpeg_bytes())
    monkeypatch.setitem(sys.modules, "zxingcpp", fake_zxing())

    values = default_barcode_scanner({"local_path": str(image_path)})

    assert values == ["ABC123"]


def test_default_barcode_scanner_downloads_oss_image_with_server_signed_url(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return tiny_jpeg_bytes()

    requested_urls: list[str] = []

    def fake_urlopen(url: str, timeout: int):
        requested_urls.append(url)
        assert timeout == 8
        return FakeResponse()

    monkeypatch.setitem(sys.modules, "zxingcpp", fake_zxing())
    monkeypatch.setattr(photo_barcode_check, "sign_oss_server_url", lambda key: f"https://signed.test/{key}", raising=False)
    monkeypatch.setattr(photo_barcode_check.urllib.request, "urlopen", fake_urlopen)

    values = default_barcode_scanner(
        {
            "storage_type": "oss",
            "storage_key": "module-manager-v2/default-team/photos/aa/photo.jpg",
            "image_url": "oss://bucket/module-manager-v2/default-team/photos/aa/photo.jpg",
        }
    )

    assert values == ["ABC123"]
    assert requested_urls == ["https://signed.test/module-manager-v2/default-team/photos/aa/photo.jpg"]
