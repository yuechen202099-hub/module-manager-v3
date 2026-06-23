from app.services.spreadsheet_import import (
    infer_meter_match_key,
    parse_csv_text,
    parse_spreadsheet_rows,
    split_photo_url_cell,
)


def test_parse_spreadsheet_rows_supports_required_chinese_fields() -> None:
    result = parse_spreadsheet_rows(
        [
            {
                "\u7ec8\u7aef": "T-001",
                "\u91c7\u96c6\u5668": "C-001",
                "\u8868\u53f7": "ZZ1234567890",
                "\u6a21\u5757": "M-001",
                "\u5730\u5740": "\u4e00\u53f7\u697c 101",
                "\u7167\u7247URL": "https://example.test/a.jpg\uff1bhttps://example.test/b.jpg",
                "\u5206\u7c7b\u547d\u540d": "\u6a21\u5757\u4e0e\u7535\u80fd\u8868",
            }
        ]
    )

    assert result.errors == ()
    assert result.accepted_rows == 1
    assert result.photo_count == 2
    record = result.records[0]
    assert record.terminal == "T-001"
    assert record.collector == "C-001"
    assert record.meter_no == "ZZ1234567890"
    assert record.module_asset_no == "M-001"
    assert record.address == "\u4e00\u53f7\u697c 101"
    assert record.meter_match_key == "1234567890"
    assert record.category_name == "\u6a21\u5757\u4e0e\u7535\u80fd\u8868"
    assert [photo.url for photo in record.photos] == [
        "https://example.test/a.jpg",
        "https://example.test/b.jpg",
    ]
    assert {photo.category_name for photo in record.photos} == {"\u6a21\u5757\u4e0e\u7535\u80fd\u8868"}


def test_parse_spreadsheet_rows_supports_numbered_photo_url_columns_and_dedupes() -> None:
    result = parse_spreadsheet_rows(
        [
            {
                "terminal": "T-001",
                "collector": "C-001",
                "meter_no": "ZZ1234567890",
                "module_asset_no": "M-001",
                "photo_url_1": "https://example.test/a.jpg",
                "photo_url_2": "https://example.test/a.jpg",
                "photo_url_3": "https://example.test/c.jpg",
                "category_name": "collector_barcode",
            }
        ]
    )

    assert result.errors == ()
    assert [photo.url for photo in result.records[0].photos] == [
        "https://example.test/a.jpg",
        "https://example.test/c.jpg",
    ]


def test_parse_spreadsheet_rows_keeps_urls_and_skips_non_url_photo_values() -> None:
    result = parse_spreadsheet_rows(
        [
            {
                "meter_no": "ZZ1234567890",
                "photo_urls": "C:/local/a.jpg, https://example.test/a.jpg",
            }
        ]
    )

    assert result.errors == ()
    record = result.records[0]
    assert [photo.url for photo in record.photos] == ["https://example.test/a.jpg"]
    assert record.warnings == ("Skipped non-URL photo values: C:/local/a.jpg",)


def test_parse_spreadsheet_rows_rejects_rows_without_matchable_meter_identity() -> None:
    result = parse_spreadsheet_rows([{"terminal": "T-001", "photo_urls": "https://example.test/a.jpg"}])

    assert result.accepted_rows == 0
    assert result.rejected_rows == 1
    assert result.errors[0].field == "meter_match_key"


def test_infer_meter_match_key_prefers_long_barcode_when_available() -> None:
    assert infer_meter_match_key(meter_no="ZZ999", barcode="ABCDEFGHIJK1234567890X") == "1234567890"


def test_infer_meter_match_key_keeps_10_digit_total_catalog_meter() -> None:
    assert infer_meter_match_key(meter_no="2004243564") == "2004243564"


def test_split_photo_url_cell_accepts_lists_and_common_separators() -> None:
    assert split_photo_url_cell(["https://a.test/1.jpg\nhttps://a.test/2.jpg", "https://a.test/3.jpg"]) == [
        "https://a.test/1.jpg",
        "https://a.test/2.jpg",
        "https://a.test/3.jpg",
    ]


def test_parse_csv_text_feeds_generic_parser() -> None:
    rows = parse_csv_text(
        "terminal,meter_no,photo_urls,category_name\n"
        "T-001,ZZ1234567890,https://example.test/a.jpg,before_box\n"
    )

    result = parse_spreadsheet_rows(rows)

    assert result.errors == ()
    assert result.records[0].terminal == "T-001"
    assert result.records[0].photos[0].url == "https://example.test/a.jpg"
