from __future__ import annotations

from app.services.photo_barcode_check import check_photo_barcode, summarize_photo_accuracy


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
