from __future__ import annotations

import sys
from io import BytesIO
from types import SimpleNamespace

import pytest
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


def ocr_reader(values: list[str]):
    return lambda _photo, _expected_values: values


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
    assert result["barcode_check_method"] == "barcode"


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
    assert result["barcode_check_ocr_values"] == []


def test_ocr_is_not_used_unless_requested() -> None:
    calls = 0

    def count_ocr(_photo, _expected_values):
        nonlocal calls
        calls += 1
        return ["MOD-001"]

    result = check_photo_barcode(
        photo={"category": "module_meter", "image_url": "https://example.test/module.jpg"},
        group={"module_asset_no": "MOD-001"},
        scanner=scanner([]),
        ocr_reader=count_ocr,
    )

    assert result["barcode_check_status"] == "unreadable"
    assert result["barcode_check_method"] == "none"
    assert calls == 0


def test_ocr_rescues_manual_rescan_when_barcode_is_unreadable() -> None:
    result = check_photo_barcode(
        photo={"category": "module_meter", "image_url": "https://example.test/module.jpg"},
        group={"module_asset_no": "MOD-001"},
        scanner=scanner([]),
        ocr_reader=ocr_reader(["MOD-001"]),
        use_ocr=True,
    )

    assert result["barcode_check_status"] == "matched"
    assert result["barcode_check_method"] == "ocr"
    assert result["barcode_check_matched_value"] == "MOD001"
    assert result["barcode_check_ocr_normalized_values"] == ["MOD001"]


def test_ocr_runs_after_mismatched_barcode_and_can_correct_result() -> None:
    result = check_photo_barcode(
        photo={"category": "collector_barcode", "image_url": "https://example.test/collector.jpg"},
        group={"collector": "COLLECTOR-001"},
        scanner=scanner(["COLLECTOR-999"]),
        ocr_reader=ocr_reader(["COLLECTOR-001"]),
        use_ocr=True,
    )

    assert result["barcode_check_status"] == "matched"
    assert result["barcode_check_method"] == "ocr"
    assert result["barcode_check_values"] == ["COLLECTOR-999", "COLLECTOR-001"]


def test_ocr_candidate_unique_suffix_completes_expected_long_value() -> None:
    values = photo_barcode_check._extract_ocr_candidates(
        "93820300014798766",
        ["31300093820300014798766"],
    )

    assert values == ["31300093820300014798766"]


def test_ocr_candidate_near_full_value_completes_missing_zero() -> None:
    values = photo_barcode_check._extract_ocr_candidates(
        "3130009382030014798766",
        ["31300093820300014798766"],
    )

    assert values == ["31300093820300014798766"]


def test_ocr_candidate_ambiguous_suffix_is_not_completed() -> None:
    values = photo_barcode_check._extract_ocr_candidates(
        "93820300014798766",
        ["31300093820300014798766", "99900093820300014798766"],
    )

    assert values == ["93820300014798766"]


def test_ocr_candidate_short_suffix_is_not_completed() -> None:
    values = photo_barcode_check._extract_ocr_candidates(
        "014798766",
        ["31300093820300014798766"],
    )

    assert values == ["014798766"]


def test_ocr_candidate_uses_digit_run_inside_noisy_text() -> None:
    values = photo_barcode_check._extract_ocr_candidates(
        "noise Sisevorsez820300014798766",
        ["31300093820300014798766"],
    )

    assert values == ["31300093820300014798766"]


def test_run_tesseract_falls_back_to_legacy_psm(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if "--psm" in command:
            return SimpleNamespace(stdout="", stderr="read_params_file: Can't open 7")
        return SimpleNamespace(stdout="3130009382030014798766", stderr="")

    monkeypatch.setattr(photo_barcode_check.shutil, "which", lambda _name: "tesseract")
    monkeypatch.setattr(photo_barcode_check.subprocess, "run", fake_run)

    text = photo_barcode_check._run_tesseract(Image.new("RGB", (8, 8), "white"))

    assert text == "3130009382030014798766"
    assert "--psm" in calls[0]
    assert "-psm" in calls[1]


def test_ocr_rescue_is_capped_for_manual_rescan_cpu_safety() -> None:
    assert photo_barcode_check.OCR_RESCUE_MAX_CANDIDATES <= 3
    assert photo_barcode_check.OCR_RESCUE_TIMEOUT_SECONDS <= 3


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


def test_non_barcode_category_can_collect_group_barcode_evidence() -> None:
    result = check_photo_barcode(
        photo={"category": "before_box", "image_url": "https://example.test/box.jpg"},
        group={"meter_no": "110000288056"},
        scanner=scanner(["110000288056"]),
        collect_group_evidence=True,
    )

    assert result["barcode_check_status"] == "not_required"
    assert result["barcode_check_expected_type"] == "none"
    assert result["barcode_check_values"] == ["110000288056"]
    assert result["barcode_check_normalized_values"] == ["110000288056"]


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


def test_group_barcode_check_honors_manual_group_confirmation() -> None:
    result = build_group_barcode_check(
        {
            "meter_no": "110000288056",
            "collector": "COLLECTOR001",
            "module_asset_no": "MOD001",
            "group_barcode_manual_confirmed": True,
            "photos": [],
        }
    )

    assert result["group_barcode_check_status"] == "matched"
    assert result["group_barcode_missing_fields"] == []
    assert set(result["group_barcode_matched_fields"]) == {"meter", "module", "collector"}
    assert result["group_barcode_manual_confirmed"] is True


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


def test_group_barcode_check_passes_when_all_required_values_exist_with_extra_noise() -> None:
    group = {
        "meter_no": "110000288056",
        "module_asset_no": "MOD-001",
        "collector": "COLLECTOR-001",
        "photos": [
            {"barcode_check_normalized_values": ["110000288056", "NOISE999"]},
            {"barcode_check_normalized_values": ["MOD001"]},
            {"barcode_check_normalized_values": ["COLLECTOR001"]},
            {"barcode_check_status": "not_required", "barcode_check_normalized_values": []},
        ],
    }

    result = build_group_barcode_check(group)

    assert result["group_barcode_check_status"] == "matched"
    assert result["group_barcode_missing_fields"] == []
    assert result["group_barcode_unmatched_values"] == ["NOISE999"]


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
                    {"barcode_check_normalized_values": []},
                ],
            },
            {
                "meter_no": "110000288057",
                "module_asset_no": "MOD-002",
                "collector": "COLLECTOR-002",
                "photos": [{"barcode_check_normalized_values": ["110000288057"]}],
            },
            {
                "meter_no": "110000288059",
                "module_asset_no": "MOD-004",
                "collector": "COLLECTOR-004",
                "photos": [
                    {"barcode_check_normalized_values": ["110000288059"]},
                    {"barcode_check_normalized_values": ["MOD004"]},
                    {"barcode_check_status": "unreadable", "barcode_check_normalized_values": []},
                    {"barcode_check_status": "unreadable", "barcode_check_normalized_values": []},
                ],
            },
            {"meter_no": "110000288058", "module_asset_no": "", "collector": "COLLECTOR-003", "photos": []},
        ]
    )

    assert summary == {
        "group_barcode_accuracy_checked": 2,
        "group_barcode_accuracy_passed": 1,
        "group_barcode_accuracy_failed": 0,
        "group_barcode_accuracy_unreadable": 1,
        "group_barcode_accuracy_not_required": 2,
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
                    },
                    {"id": "photo-2", "category": "module_meter", "barcode_check_status": "unreadable"},
                    {"id": "photo-3", "category": "collector_barcode", "barcode_check_status": "unreadable"},
                    {"id": "photo-4", "category": "before_box", "barcode_check_status": "not_required"},
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


def test_group_barcode_review_items_skip_incomplete_photo_sets() -> None:
    items = photo_barcode_check.list_group_barcode_review_items(
        [
            {
                "id": "group-1",
                "meter_no": "110000288056",
                "module_asset_no": "MOD-001",
                "collector": "COLLECTOR-001",
                "photos": [
                    {"id": "photo-1", "barcode_check_normalized_values": ["110000288056"]},
                    {"id": "photo-2", "barcode_check_normalized_values": ["MOD001"]},
                    {"id": "photo-3", "barcode_check_status": "unreadable"},
                ],
            }
        ],
        statuses={"unreadable"},
    )

    assert items == []


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


def test_default_barcode_scanner_reads_qr_payload_candidates(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "qr.jpg"
    image_path.write_bytes(tiny_jpeg_bytes())
    observed_formats: list[object] = []

    class BarcodeFormat:
        Any = "any-format"

    def read_barcodes(_image, formats=None):
        observed_formats.append(formats)
        return [SimpleNamespace(text="https://sgcc.online/q?module=3130054512250026172609")]

    monkeypatch.setitem(
        sys.modules,
        "zxingcpp",
        SimpleNamespace(BarcodeFormat=BarcodeFormat, read_barcodes=read_barcodes),
    )

    values = default_barcode_scanner({"local_path": str(image_path)})

    assert observed_formats == ["any-format"]
    assert "3130054512250026172609" in values


def test_default_barcode_scanner_rescues_enhanced_rotated_image(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "slanted-barcode.jpg"
    Image.new("RGB", (100, 100), "white").save(image_path, format="JPEG")
    calls: list[tuple[str, tuple[int, int]]] = []

    def read_barcodes(image):
        calls.append((image.mode, image.size))
        if image.mode == "L" and image.size == (116, 92):
            return [SimpleNamespace(text="3130009382030009453489")]
        return []

    monkeypatch.setitem(sys.modules, "zxingcpp", SimpleNamespace(read_barcodes=read_barcodes))

    values = default_barcode_scanner({"local_path": str(image_path)})

    assert values == ["3130009382030009453489"]
    assert calls[0] == ("RGB", (100, 100))
    assert ("L", (100, 100)) in calls
    assert ("L", (100, 60)) in calls
    assert ("L", (106, 70)) in calls
    assert ("L", (110, 78)) in calls
    assert len(calls) == 10


def test_default_barcode_scanner_stops_at_candidate_cap(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "hard-barcode.jpg"
    Image.new("RGB", (100, 100), "white").save(image_path, format="JPEG")
    calls = 0

    def read_barcodes(_image):
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setitem(sys.modules, "zxingcpp", SimpleNamespace(read_barcodes=read_barcodes))

    values = default_barcode_scanner({"local_path": str(image_path)})

    assert values == []
    assert calls == photo_barcode_check.BARCODE_RESCUE_MAX_CANDIDATES


def test_default_barcode_scanner_honors_photo_candidate_limit(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "limited-barcode.jpg"
    Image.new("RGB", (100, 100), "white").save(image_path, format="JPEG")
    calls = 0

    def read_barcodes(_image):
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setitem(sys.modules, "zxingcpp", SimpleNamespace(read_barcodes=read_barcodes))

    values = default_barcode_scanner({"local_path": str(image_path), "barcode_scan_max_candidates": 3})

    assert values == []
    assert calls == 3


def test_default_barcode_scanner_downsizes_rescue_work_image(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "large-barcode.jpg"
    Image.new("RGB", (2300, 100), "white").save(image_path, format="JPEG")
    calls: list[tuple[str, tuple[int, int]]] = []

    def read_barcodes(image):
        calls.append((image.mode, image.size))
        if len(calls) == 2:
            return [SimpleNamespace(text="LARGE123")]
        return []

    monkeypatch.setitem(sys.modules, "zxingcpp", SimpleNamespace(read_barcodes=read_barcodes))

    values = default_barcode_scanner({"local_path": str(image_path)})

    assert values == ["LARGE123"]
    assert calls[0] == ("RGB", (2300, 100))
    assert calls[1][0] == "L"
    assert max(calls[1][1]) == photo_barcode_check.BARCODE_RESCUE_MAX_WORK_LONG_SIDE


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
